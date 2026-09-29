from __future__ import annotations

import html
import json
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from app.constants import APP_HOME, LOG_DIR

from .filter import StrategyFilterEngine
from .ranking import RankingEntry, StrategyRanking
from .search import SearchConfig, StrategySearchEngine
from .storage import DEFAULT_PATH, StrategyLabStorage
from .vip100_history import HISTORY_DATA_SOURCE, Vip100HistoryDataSource
from .v2 import V2ExperimentRunner, ValidationConfig, SnapshotBuilder
from .v2.experiment_audit import ExperimentAuditStore


@dataclass(frozen=True)
class AutoRunConfig:
    run_time: str = "02:30"
    max_candidates: int = 100
    data_source: str = "VIP"
    top_count: int = 20
    include_v21: bool = True


@dataclass(frozen=True)
class AutoRunResult:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    data_status: Mapping[str, Any]
    search_count: int
    pass_count: int
    fail_count: int
    top_strategies: tuple[Mapping[str, Any], ...]
    frozen_strategy_status: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    report_json: str
    report_html: str
    experiments: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyAutoRunner:
    """Orchestrate one bounded strategy-lab run and produce daily reports."""

    def __init__(
        self,
        history_db_path: str | Path | None = None,
        *,
        lab_db_path: str | Path = DEFAULT_PATH,
        report_dir: str | Path | None = None,
        log_path: str | Path | None = None,
        config: AutoRunConfig | None = None,
        storage: StrategyLabStorage | None = None,
        search_engine: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.source = Vip100HistoryDataSource(history_db_path)
        self.cache_namespace = HISTORY_DATA_SOURCE
        self.storage = storage or StrategyLabStorage(lab_db_path)
        self.report_dir = Path(report_dir or (APP_HOME / "reports" / "strategy_daily"))
        self.log_path = Path(log_path or (LOG_DIR / "strategy_runner.log"))
        self.config = config or AutoRunConfig()
        self.search_engine = search_engine or StrategySearchEngine(self.storage)
        self.filter_engine = StrategyFilterEngine()
        self.ranking_engine = StrategyRanking(filter_config=self.filter_engine.config)
        self._now = now or (lambda: datetime.now().astimezone())

    def run_now(self) -> AutoRunResult:
        started = self._now()
        run_id = f"AUTO-{started:%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
        previous = self.storage.get_last_auto_run(successful_only=True)
        record = {
            "run_id": run_id,
            "started_at": started.isoformat(timespec="seconds"),
            "status": "RUNNING",
        }
        data_status: dict[str, Any] = {}
        self.storage.save_auto_run(record)
        self._log(f"RUN_START run_id={run_id}")
        try:
            self._log("STEP vip100_history_check START")
            data_status = self.source.data_status()
            previous_periods = int((previous or {}).get("data_status", {}).get("current_periods") or 0)
            data_status["new_periods"] = max(
                0, int(data_status["current_periods"]) - previous_periods
            ) if previous else 0
            records = self.source.backtest_records(self.config.data_source)
            data_status["valid_backtest_records"] = len(records)
            self._log(
                "STEP vip100_history_check PASS "
                f"periods={data_status['current_periods']} records={len(records)}"
            )
            if not records:
                raise RuntimeError("没有可用于策略实验的有效历史样本")

            self._log("STEP batch_backtest START")
            search = self.search_engine.search(
                records,
                config=SearchConfig(
                    max_candidates=self.config.max_candidates,
                    data_source=self.config.data_source,
                    cache_namespace=self.cache_namespace,
                ),
            )
            candidates = search.experiment.candidates
            self._log(f"STEP batch_backtest PASS candidates={len(candidates)}")
            self._log("STEP strategy_search START")
            decisions = self.filter_engine.filter(candidates)
            rankings = self.ranking_engine.rank(candidates, decisions)
            self.storage.save_filter_results(
                search.experiment.experiment_id, decisions, self.filter_engine.config
            )
            self.storage.save_rankings(
                search.experiment.experiment_id, rankings, self.ranking_engine.weights
            )
            pass_count = sum(1 for item in decisions if item.passed)
            fail_count = len(decisions) - pass_count
            top = tuple(item.to_dict() for item in rankings[: self.config.top_count])
            self._log(
                f"STEP strategy_search PASS candidates={len(candidates)} "
                f"passed={pass_count} failed={fail_count}"
            )

            experiments: dict[str, Any] = {
                "v1": {
                    "status": "PASS",
                    "search_count": len(candidates),
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                }
            }
            if self.config.include_v21:
                experiments.update(self._run_v21(records))
            v21_status = experiments.get("v2.1", {}).get("status")
            if v21_status and v21_status != "PASS":
                warnings = tuple(warnings) + (f"v2.1 状态：{v21_status}",)

            self._log("STEP strategy_compare START")
            frozen_status = tuple(self._compare_frozen(rankings))
            self._log(f"STEP strategy_compare PASS frozen={len(frozen_status)}")
            warnings = self._warnings(data_status, pass_count, frozen_status)
            payload = {
                "date": started.date().isoformat(),
                "data_status": data_status,
                "search_count": len(candidates),
                "pass_count": pass_count,
                "fail_count": fail_count,
                "top_strategies": list(top),
                "frozen_strategy_status": list(frozen_status),
                "warnings": list(warnings),
                "experiments": experiments,
            }
            report_json, report_html = self._write_reports(payload)
            self._log("REPORT GENERATED")
            finished = self._now().isoformat(timespec="seconds")
            complete = {
                **record,
                **payload,
                "finished_at": finished,
                "status": "PASS",
                "report_json": str(report_json),
                "report_html": str(report_html),
            }
            self.storage.save_auto_run(complete)
            self._log(
                f"RUN_SUCCESS run_id={run_id} json={report_json} html={report_html}"
            )
            return AutoRunResult(
                run_id=run_id,
                status="PASS",
                started_at=record["started_at"],
                finished_at=finished,
                data_status=data_status,
                search_count=len(candidates),
                pass_count=pass_count,
                fail_count=fail_count,
                top_strategies=top,
                frozen_strategy_status=frozen_status,
                warnings=warnings,
                report_json=str(report_json),
                report_html=str(report_html),
                experiments=experiments,
            )
        except Exception as exc:
            finished = self._now().isoformat(timespec="seconds")
            message = f"{type(exc).__name__}: {exc}"
            failure_payload = {
                "date": started.date().isoformat(),
                "data_status": data_status,
                "search_count": 0,
                "pass_count": 0,
                "fail_count": 0,
                "top_strategies": [],
                "frozen_strategy_status": [],
                "warnings": [message],
                "experiments": {"v1": {"status": "FAIL"}},
            }
            report_json = ""
            report_html = ""
            try:
                json_path, html_path = self._write_reports(failure_payload)
                report_json, report_html = str(json_path), str(html_path)
            except Exception as report_exc:
                self._log(
                    "REPORT_FAILED "
                    f"error={type(report_exc).__name__}: {report_exc}"
                )
            self.storage.save_auto_run(
                {
                    **record,
                    **failure_payload,
                    "finished_at": finished,
                    "status": "FAIL",
                    "error_message": message,
                    "report_json": report_json,
                    "report_html": report_html,
                }
            )
            self._log(f"RUN_FAILED run_id={run_id} error={message}\n{traceback.format_exc()}")
            raise

    def schedule_run(
        self,
        run_time: str | None = None,
        *,
        registrar: Callable[[datetime], Any] | None = None,
    ) -> datetime:
        active_time = run_time or self.config.run_time
        next_run = self._calculate_next_run(active_time, self._now())
        if registrar is not None:
            registrar(next_run)
        self.storage.save_auto_schedule(
            enabled=True,
            run_time=active_time,
            next_run=next_run.isoformat(timespec="seconds"),
            updated_at=self._now().isoformat(timespec="seconds"),
        )
        self._log(f"SCHEDULE_SET run_time={active_time} next_run={next_run.isoformat()}")
        return next_run

    def get_last_run(self) -> dict[str, Any] | None:
        return self.storage.get_last_auto_run()

    def get_next_run(self) -> datetime:
        schedule = self.storage.get_auto_schedule()
        run_time = str((schedule or {}).get("run_time") or self.config.run_time)
        return self._calculate_next_run(run_time, self._now())

    @staticmethod
    def _calculate_next_run(run_time: str, now: datetime) -> datetime:
        try:
            hour_text, minute_text = run_time.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("运行时间必须为 HH:MM") from exc
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    def _compare_frozen(self, rankings: tuple[RankingEntry, ...]) -> list[dict[str, Any]]:
        top = rankings[0].to_dict() if rankings else None
        rows: list[dict[str, Any]] = []
        for frozen in self.storage.list_frozen_strategies():
            validation = dict(frozen.get("validation_result") or {})
            frozen_rate = validation.get("hit_rate")
            top_rate = None if top is None else top.get("validation_hit_rate")
            delta = None
            if frozen_rate is not None and top_rate is not None:
                delta = round(float(top_rate) - float(frozen_rate), 4)
            rows.append(
                {
                    "freeze_id": frozen["freeze_id"],
                    "strategy_name": frozen["strategy_name"],
                    "strategy_version": frozen["strategy_version"],
                    "status": frozen["status"],
                    "valid_samples": validation.get("valid_samples"),
                    "hit_rate": frozen_rate,
                    "max_consecutive_misses": validation.get("max_consecutive_misses"),
                    "average_trigger_interval": validation.get("average_trigger_interval"),
                    "recent_30": validation.get("recent_30"),
                    "latest_candidate": None if top is None else top.get("strategy_name"),
                    "validation_hit_rate_delta": delta,
                    "analysis_only": True,
                }
            )
        return rows

    @staticmethod
    def _warnings(
        data_status: Mapping[str, Any],
        pass_count: int,
        frozen_status: tuple[Mapping[str, Any], ...],
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if int(data_status.get("missing") or 0):
            warnings.append(f"存在 {data_status['missing']} 条缺失数据记录")
        if int(data_status.get("partial") or 0):
            warnings.append(f"存在 {data_status['partial']} 个未完整历史周期")
        if pass_count == 0:
            warnings.append("本次没有候选策略通过筛选")
        if not frozen_status:
            warnings.append("当前没有冻结策略可供比较")
        return tuple(warnings)

    def _write_reports(self, payload: Mapping[str, Any]) -> tuple[Path, Path]:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{payload['date']}_report"
        json_path = self.report_dir / f"{stem}.json"
        html_path = self.report_dir / f"{stem}.html"
        self._atomic_write(
            json_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        self._atomic_write(html_path, self._render_html(payload))
        return json_path, html_path

    def _run_v21(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Run additive v2/v2.1 analysis without changing v1 outcomes."""
        self._log("V21_VALIDATION START")
        try:
            max_candidates = self.config.max_candidates
            if max_candidates not in (50, 100, 200):
                max_candidates = 100 if max_candidates < 150 else 200
            runner = V2ExperimentRunner(
                storage=self.storage,
                audit_store=ExperimentAuditStore(self.storage.path),
                snapshot_builder=SnapshotBuilder(self.source.path),
            )
            result = runner.run_v21(
                records,
                config=SearchConfig(max_candidates=max_candidates, data_source="VIP", min_sample_size=1),
                validation_config=ValidationConfig(),
            )
            first_validation = result.validation[0] if result.validation else None
            first_robustness = result.robustness[0] if result.robustness else None
            for name, metrics in (
                ("TRAIN", None if first_validation is None else first_validation.train),
                ("VALIDATION", None if first_validation is None else first_validation.validation),
                ("FINAL_TEST", None if first_validation is None else first_validation.test),
            ):
                self._log(f"{name} {'PASS' if metrics is not None else 'FAIL'}")
            self._log(f"ROBUSTNESS {'PASS' if first_robustness is not None else 'FAIL'}")
            return {
                "v2": {
                    "status": "PASS",
                    "run_id": result.run_id,
                    "snapshot_id": result.snapshot.snapshot_id,
                    "search_count": len(result.search.experiment.candidates),
                },
                "v2.1": {
                    "status": "PASS",
                    "run_id": result.run_id,
                    "snapshot_id": result.snapshot.snapshot_id,
                    "train": None if first_validation is None else first_validation.train.to_dict(),
                    "validation": None if first_validation is None else first_validation.validation.to_dict(),
                    "final_test": None if first_validation is None else first_validation.test.to_dict(),
                    "robustness": None if first_robustness is None else first_robustness.to_dict(),
                },
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._log(f"V21_VALIDATION FAIL error={message}")
            return {
                "v2": {"status": "FAIL", "error": message},
                "v2.1": {"status": "INSUFFICIENT_DATA", "error": message},
            }

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _render_html(payload: Mapping[str, Any]) -> str:
        def cell(value: Any) -> str:
            return html.escape("" if value is None else str(value))

        top_rows = "".join(
            "<tr>"
            f"<td>{cell(item.get('rank'))}</td>"
            f"<td>{cell(item.get('strategy_name'))}</td>"
            f"<td>{cell(item.get('trigger_count'))}</td>"
            f"<td>{cell(item.get('validation_hit_rate'))}</td>"
            f"<td>{cell(item.get('max_consecutive_misses'))}</td>"
            f"<td>{cell(item.get('status'))}</td>"
            "</tr>"
            for item in payload.get("top_strategies", [])
        ) or '<tr><td colspan="6">暂无候选</td></tr>'
        warning_rows = "".join(
            f"<li>{cell(item)}</li>" for item in payload.get("warnings", [])
        ) or "<li>无</li>"
        experiments = payload.get("experiments", {})
        v21 = experiments.get("v2.1", {}) if isinstance(experiments, Mapping) else {}
        v21_status = cell(v21.get("status", "未执行"))
        v21_snapshot = cell(v21.get("snapshot_id", ""))
        status = payload.get("data_status", {})
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>无忧28 策略实验日报</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;margin:28px;color:#1f2937}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d1d5db;padding:8px;text-align:left}}
th{{background:#eff6ff}}.summary{{display:flex;gap:24px;margin:16px 0}}</style></head>
<body><h1>策略实验日报 {cell(payload.get('date'))}</h1>
<div class="summary"><span>数据期数：{cell(status.get('current_periods'))}</span>
<span>搜索：{cell(payload.get('search_count'))}</span><span>PASS：{cell(payload.get('pass_count'))}</span>
<span>FAIL：{cell(payload.get('fail_count'))}</span></div>
<h2>候选策略</h2><table><thead><tr><th>排名</th><th>策略</th><th>触发次数</th>
<th>验证命中率</th><th>最大连错</th><th>状态</th></tr></thead><tbody>{top_rows}</tbody></table>
<h2>稳定性实验 v2.1</h2><p>状态：{v21_status}　Snapshot：{v21_snapshot}</p>
<h2>警告</h2><ul>{warning_rows}</ul></body></html>"""

    def _log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().isoformat(timespec="seconds")
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {message}\n")


__all__ = [
    "AutoRunConfig",
    "AutoRunResult",
    "StrategyAutoRunner",
]
