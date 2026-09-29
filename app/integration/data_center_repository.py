from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any, Callable

from .draw_repository import DrawRepository
from .health import freshness, read_json_object, readonly_sqlite
from .strategy_repository import LIFECYCLE_STATES, StrategyResearchRepository
from .vip100_repository import Vip100Repository


class DataCenterRepository:
    """Aggregate production health without controlling or mutating any service."""

    def __init__(
        self,
        draws: DrawRepository,
        vip100: Vip100Repository,
        strategies: StrategyResearchRepository,
        ui_probe: Callable[[], bool] | None = None,
    ):
        self.draws = draws
        self.vip100 = vip100
        self.strategies = strategies
        self.project_root = self.vip100.production_dir.parent.parent
        self._ui_probe = ui_probe or self._probe_8787
        self._snapshot_cache: tuple[float, int, dict] | None = None
        self._snapshot_cache_ttl = 1.0

    @staticmethod
    def _probe_8787() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 8787), timeout=0.25):
                return True
        except OSError:
            return False

    @staticmethod
    def _error_status(exc: Exception) -> dict:
        return {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "freshness": {"status": "ERROR"},
        }

    def _prediction_documents(self) -> list[dict[str, Any]]:
        values = []
        if not self.vip100.predictions_dir.is_dir():
            return values
        paths = sorted(
            (
                path
                for path in self.vip100.predictions_dir.glob("*.json")
                if path.is_file() and path.stem.isdigit()
            ),
            key=lambda path: int(path.stem),
        )
        for path in paths:
            try:
                document = read_json_object(path)
                records = document.get("records")
                records = records if isinstance(records, list) else []
                identifiers = [
                    str(record.get("algorithm_id", ""))
                    for record in records
                    if isinstance(record, dict)
                ]
                duplicate_count = len(identifiers) - len(set(identifiers))
                values.append(
                    {
                        "issue": str(document.get("issue") or path.stem),
                        "generated_at": str(document.get("generated_at") or ""),
                        "declared_count": int(document.get("prediction_count") or 0),
                        "actual_count": len(records),
                        "algorithm_hash": str(document.get("algorithm_hash") or ""),
                        "duplicate_count": duplicate_count,
                        "error": None,
                    }
                )
            except Exception as exc:
                values.append(
                    {
                        "issue": path.stem,
                        "generated_at": "",
                        "declared_count": 0,
                        "actual_count": 0,
                        "algorithm_hash": "",
                        "duplicate_count": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return values

    def _strategy_database(self) -> dict:
        with readonly_sqlite(self.strategies.database_path) as connection:
            periods = {
                str(row["issue"]): dict(row)
                for row in connection.execute(
                    """SELECT issue, timestamp, actual_result, prediction_count,
                              generated_at, algorithm_set_sha256
                       FROM production_periods"""
                )
            }
            prediction_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM production_predictions"
                ).fetchone()[0]
            )
            duplicate_rows = int(
                connection.execute(
                    """SELECT COALESCE(SUM(total - 1), 0) FROM (
                           SELECT COUNT(*) AS total
                           FROM production_predictions
                           GROUP BY issue, algorithm_id HAVING COUNT(*) > 1
                       )"""
                ).fetchone()[0]
            )
        return {
            "status": "ONLINE",
            "periods": periods,
            "prediction_rows": prediction_rows,
            "duplicate_rows": duplicate_rows,
        }

    @staticmethod
    def _gaps(issues: set[int]) -> list[int]:
        if len(issues) < 2:
            return []
        ordered = sorted(issues)
        missing = []
        for left, right in zip(ordered, ordered[1:]):
            missing.extend(range(left + 1, right))
        return missing

    def _service_from_file(
        self, name: str, path: Path, *, stale_after: int | None = None
    ) -> dict:
        try:
            document = read_json_object(path)
            timestamp = document.get("updated_at")
            state = str(document.get("status", "UNKNOWN"))
            state_freshness = (
                freshness(timestamp, stale_after)
                if timestamp and stale_after
                else {"status": "UNKNOWN", "timestamp": timestamp}
            )
            if state == "RUNNING" and state_freshness.get("status") == "STALE":
                state = "STALE"
            pid = document.get("pid")
            if state in {"RUNNING", "STALE"} and not DataCenterRepository._pid_running(pid):
                state = "OFFLINE"
            return {
                "name": name,
                "status": state,
                "pid": pid,
                "updated_at": timestamp
                or datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).astimezone().isoformat(),
                "source": str(path),
                "error": None,
            }
        except FileNotFoundError:
            return {
                "name": name,
                "status": "OFFLINE",
                "pid": None,
                "updated_at": None,
                "source": str(path),
                "error": "status file not found",
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "ERROR",
                "pid": None,
                "updated_at": None,
                "source": str(path),
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _pid_running(pid: object) -> bool:
        try:
            value = int(pid)
            if value <= 0:
                return False
            if sys.platform == "win32":
                import ctypes

                process_query_limited_information = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    process_query_limited_information, False, value
                )
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            os.kill(value, 0)
            return True
        except PermissionError:
            return True
        except (OSError, TypeError, ValueError):
            return False

    def _services(self) -> list[dict]:
        data_root = self.project_root / "data"
        values = [
            self._service_from_file(
                "VIP100 validation",
                data_root / "vip100_v2_continuous" / "state.json",
                stale_after=120,
            ),
            self._service_from_file(
                "VIP100 production",
                self.vip100.production_dir / "state.json",
                stale_after=120,
            ),
            self._service_from_file(
                "YU28 producer",
                self.draws.database_path.with_name("yu28_producer_status.json"),
                stale_after=120,
            ),
            self._service_from_file(
                "StrategyResearchEngine",
                self.strategies.runtime_status_path,
                stale_after=120,
            ),
        ]
        try:
            ui_running = bool(self._ui_probe())
            ui_error = None
        except Exception as exc:
            ui_running = False
            ui_error = f"{type(exc).__name__}: {exc}"
        values.append(
            {
                "name": "8787 UI",
                "status": "RUNNING" if ui_running else "OFFLINE",
                "pid": None,
                "updated_at": None,
                "source": "TCP 127.0.0.1:8787",
                "error": ui_error,
            }
        )
        return values

    def snapshot(self, recent_limit: int = 12) -> dict:
        safe_recent_limit = max(1, min(int(recent_limit), 100))
        now = time.monotonic()
        cached = self._snapshot_cache
        if (
            cached is not None
            and cached[1] == safe_recent_limit
            and now - cached[0] < self._snapshot_cache_ttl
        ):
            return cached[2]
        errors = []
        try:
            draw_status = self.draws.status()
        except Exception as exc:
            draw_status = self._error_status(exc)
        try:
            draw_records = self.draws.recent(10000)
        except Exception as exc:
            draw_records = []
            errors.append(f"draw records: {type(exc).__name__}: {exc}")
        try:
            vip_status = self.vip100.status()
        except Exception as exc:
            vip_status = self._error_status(exc)
        try:
            strategy_status = self.strategies.status()
        except Exception as exc:
            strategy_status = self._error_status(exc)
        try:
            strategy_rows = self.strategies.list_strategies(5000)
        except Exception as exc:
            strategy_rows = []
            errors.append(f"strategy results: {type(exc).__name__}: {exc}")
        try:
            prediction_documents = self._prediction_documents()
        except Exception as exc:
            prediction_documents = []
            errors.append(f"VIP100 batches: {type(exc).__name__}: {exc}")
        try:
            strategy_database = self._strategy_database()
        except Exception as exc:
            strategy_database = {
                "status": "ERROR",
                "periods": {},
                "prediction_rows": 0,
                "duplicate_rows": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

        draw_issues = {
            int(record.issue) for record in draw_records if str(record.issue).isdigit()
        }
        prediction_issues = {
            int(row["issue"])
            for row in prediction_documents
            if str(row["issue"]).isdigit()
        }
        strategy_periods = strategy_database["periods"]
        strategy_issues = {
            int(issue) for issue in strategy_periods if str(issue).isdigit()
        }
        expected_hash = str(
            self.vip100.hash_status().get("standard_sha256") or ""
        )

        draw_gaps = self._gaps(draw_issues)
        if prediction_issues and draw_issues:
            first_prediction = min(prediction_issues)
            last_draw = min(max(draw_issues), max(prediction_issues))
            missing_prediction_issues = sorted(
                issue
                for issue in draw_issues
                if first_prediction <= issue <= last_draw
                and issue not in prediction_issues
            )
        else:
            missing_prediction_issues = []
        incomplete = [
            row
            for row in prediction_documents
            if row["declared_count"] != 100
            or row["actual_count"] != 100
            or row["error"]
        ]
        duplicate_records = sum(
            int(row["duplicate_count"]) for row in prediction_documents
        ) + int(strategy_database.get("duplicate_rows", 0))
        drawn_predictions = prediction_issues & draw_issues
        pending_predictions = prediction_issues - draw_issues
        missing_outcomes = sorted(drawn_predictions - strategy_issues)
        hash_anomalies = [
            row["issue"]
            for row in prediction_documents
            if not expected_hash or row["algorithm_hash"] != expected_hash
        ]
        if vip_status.get("hash_status") != "HASH_OK" and not hash_anomalies:
            hash_anomalies.append("GLOBAL")

        lifecycle_counts = {state: 0 for state in LIFECYCLE_STATES}
        insufficient = 0
        for strategy in strategy_rows:
            lifecycle_counts[strategy.status] = (
                lifecycle_counts.get(strategy.status, 0) + 1
            )
            if strategy.sample_warning:
                insufficient += 1

        checks = [
            self._check(
                "开奖期号连续性",
                not draw_gaps,
                f"缺失 {len(draw_gaps)} 个期号"
                + self._issue_suffix(draw_gaps),
                warning=True,
            ),
            self._check(
                "VIP100每期100条",
                not incomplete,
                f"异常 {len(incomplete)} 期"
                + self._issue_suffix(
                    [int(row["issue"]) for row in incomplete if str(row["issue"]).isdigit()]
                ),
            ),
            self._check(
                "缺失预测期",
                not missing_prediction_issues,
                f"缺失 {len(missing_prediction_issues)} 期"
                + self._issue_suffix(missing_prediction_issues),
                warning=True,
            ),
            self._check(
                "重复记录",
                duplicate_records == 0,
                f"重复 {duplicate_records} 条",
            ),
            self._check(
                "已开奖但未回填结果",
                not missing_outcomes,
                f"未回填 {len(missing_outcomes)} 期"
                + self._issue_suffix(missing_outcomes),
                warning=True,
            ),
            self._check(
                "HASH异常",
                not hash_anomalies,
                f"异常 {len(hash_anomalies)} 项"
                + self._issue_suffix(hash_anomalies),
            ),
            self._check(
                "Strategy DB读取状态",
                strategy_database.get("status") == "ONLINE",
                strategy_database.get("error") or strategy_database.get("status"),
            ),
        ]

        recent = []
        for document in sorted(
            prediction_documents,
            key=lambda row: int(row["issue"]) if str(row["issue"]).isdigit() else -1,
            reverse=True,
        )[:safe_recent_limit]:
            issue = int(document["issue"]) if str(document["issue"]).isdigit() else -1
            is_drawn = issue in draw_issues
            is_ingested = issue in strategy_issues
            hash_ok = bool(expected_hash) and document["algorithm_hash"] == expected_hash
            recent.append(
                {
                    "issue": document["issue"],
                    "draw_status": "DRAWN" if is_drawn else "PENDING",
                    "vip100_count": document["actual_count"],
                    "hash_status": "HASH_OK" if hash_ok else "HASH_MISMATCH",
                    "outcome_status": (
                        "SETTLED"
                        if is_ingested
                        else "MISSING_OUTCOME"
                        if is_drawn
                        else "WAITING_DRAW"
                    ),
                    "strategy_ingest_status": (
                        "INGESTED"
                        if is_ingested
                        else "PENDING"
                        if is_drawn
                        else "WAITING_DRAW"
                    ),
                    "data_time": document["generated_at"],
                    "error": document["error"],
                }
            )

        freshness_states = [
            draw_status.get("freshness", {}).get("status"),
            vip_status.get("freshness", {}).get("status"),
            strategy_status.get("freshness", {}).get("status"),
        ]
        if "ERROR" in freshness_states:
            data_freshness = "ERROR"
        elif "OFFLINE" in freshness_states:
            data_freshness = "ERROR"
        elif "STALE" in freshness_states:
            data_freshness = "STALE"
        else:
            data_freshness = "HEALTHY"
        services = self._services()
        health_level = self._health_level(
            draw_status, vip_status, strategy_status, checks, services
        )
        result = {
            "overall_status": health_level,
            "top": {
                "draw_status": draw_status.get("status", "OFFLINE"),
                "draw_latest_issue": draw_status.get("latest_issue"),
                "vip100_status": vip_status.get("status", "OFFLINE"),
                "vip100_latest_issue": vip_status.get("latest_issue"),
                "vip100_prediction_count": vip_status.get("prediction_count", 0),
                "hash_status": vip_status.get("hash_status", "OFFLINE"),
                "strategy_status": strategy_status.get("status", "OFFLINE"),
                "strategy_db_status": strategy_status.get(
                    "database_status", "OFFLINE"
                ),
                "data_freshness": data_freshness,
            },
            "counts": {
                "draw_periods": len(draw_issues),
                "vip100_periods": len(prediction_documents),
                "vip100_prediction_rows": sum(
                    int(row["actual_count"]) for row in prediction_documents
                ),
                "drawn_prediction_periods": len(drawn_predictions),
                "pending_prediction_periods": len(pending_predictions),
                "strategy_total": len(strategy_rows),
                **{
                    state: lifecycle_counts.get(state, 0)
                    for state in LIFECYCLE_STATES
                },
                "insufficient_samples": insufficient,
            },
            "integrity": checks,
            "recent": recent,
            "services": services,
            "errors": errors,
        }
        self._snapshot_cache = (now, safe_recent_limit, result)
        return result

    @staticmethod
    def _issue_suffix(issues) -> str:
        values = [str(issue) for issue in list(issues)[:8]]
        return f"（{', '.join(values)}{'…' if len(issues) > 8 else ''}）" if values else ""

    @staticmethod
    def _check(
        name: str,
        passed: bool,
        detail: str,
        *,
        warning: bool = False,
    ) -> dict:
        return {
            "name": name,
            "status": "HEALTHY" if passed else "WARNING" if warning else "ERROR",
            "detail": "正常" if passed else detail,
        }

    @staticmethod
    def _health_level(
        draw_status: dict,
        vip_status: dict,
        strategy_status: dict,
        checks: list[dict],
        services: list[dict],
    ) -> str:
        source_states = {
            str(draw_status.get("status", "OFFLINE")),
            str(vip_status.get("status", "OFFLINE")),
            str(strategy_status.get("status", "OFFLINE")),
            str(strategy_status.get("database_status", "OFFLINE")),
        }
        if source_states & {"ERROR", "OFFLINE", "HASH_MISMATCH"}:
            return "ERROR"
        if any(check["status"] == "ERROR" for check in checks):
            return "ERROR"
        if "STALE" in source_states or any(
            service["status"] == "STALE" for service in services
        ):
            return "STALE"
        if any(check["status"] == "WARNING" for check in checks):
            return "WARNING"
        if any(service["status"] in {"OFFLINE", "ERROR"} for service in services):
            return "WARNING"
        return "HEALTHY"
