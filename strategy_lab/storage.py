from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.constants import DATA_DIR

from .filter import FilterConfig, FilterDecision
from .models import (
    CandidateResult,
    EvaluationMetrics,
    ExperimentResult,
    StrategyCondition,
    WalkForwardWindow,
)
from .ranking import RankingEntry, RankingWeights


DEFAULT_PATH = DATA_DIR / "strategy_lab.db"


class StrategyLabStorage:
    """Persistence owned by the lab; never writes to the product database."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    data_source TEXT NOT NULL,
                    train_ratio REAL NOT NULL,
                    train_issue_range TEXT,
                    validation_issue_range TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_candidates (
                    experiment_id TEXT NOT NULL,
                    rank_no INTEGER NOT NULL,
                    condition_id TEXT NOT NULL,
                    condition_name TEXT NOT NULL,
                    condition_params TEXT NOT NULL,
                    training_result TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    overall_result TEXT NOT NULL,
                    walk_forward_result TEXT NOT NULL,
                    score REAL NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, condition_id),
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS saved_strategies (
                    strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    condition_params TEXT NOT NULL,
                    training_result TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS strategy_filters (
                    experiment_id TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    reasons TEXT NOT NULL,
                    filter_config TEXT NOT NULL,
                    walk_forward_pass_ratio REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (experiment_id, condition_id),
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS strategy_rankings (
                    experiment_id TEXT NOT NULL,
                    rank_no INTEGER NOT NULL,
                    condition_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ranking_score REAL NOT NULL,
                    ranking_metrics TEXT NOT NULL,
                    ranking_weights TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (experiment_id, condition_id),
                    UNIQUE (experiment_id, rank_no),
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS strategy_searches (
                    search_id TEXT PRIMARY KEY,
                    search_config TEXT NOT NULL,
                    parameter_combinations TEXT NOT NULL,
                    runtime_seconds REAL NOT NULL,
                    result_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_freeze (
                    freeze_id TEXT PRIMARY KEY,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    condition_params TEXT NOT NULL,
                    training_result TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'WATCH', 'DISABLED')),
                    frozen_at_issue TEXT NOT NULL DEFAULT '',
                    UNIQUE(strategy_name, strategy_version)
                );
                CREATE TABLE IF NOT EXISTS strategy_tracking (
                    tracking_id TEXT PRIMARY KEY,
                    freeze_id TEXT NOT NULL,
                    tracked_at TEXT NOT NULL,
                    new_samples INTEGER NOT NULL,
                    recent_performance TEXT NOT NULL,
                    current_status TEXT NOT NULL,
                    anomaly INTEGER NOT NULL,
                    reasons TEXT NOT NULL,
                    tracking_config TEXT NOT NULL,
                    FOREIGN KEY (freeze_id) REFERENCES strategy_freeze(freeze_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS strategy_compare (
                    comparison_id TEXT NOT NULL,
                    freeze_id TEXT NOT NULL,
                    comparison_snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (comparison_id, freeze_id),
                    FOREIGN KEY (freeze_id) REFERENCES strategy_freeze(freeze_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS strategy_auto_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    data_status TEXT NOT NULL DEFAULT '{}',
                    search_count INTEGER NOT NULL DEFAULT 0,
                    pass_count INTEGER NOT NULL DEFAULT 0,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    top_strategies TEXT NOT NULL DEFAULT '[]',
                    frozen_strategy_status TEXT NOT NULL DEFAULT '[]',
                    warnings TEXT NOT NULL DEFAULT '[]',
                    report_json TEXT NOT NULL DEFAULT '',
                    report_html TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_auto_runs_started
                    ON strategy_auto_runs(started_at DESC);
                CREATE TABLE IF NOT EXISTS strategy_auto_schedule (
                    schedule_id INTEGER PRIMARY KEY CHECK(schedule_id = 1),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    run_time TEXT NOT NULL DEFAULT '02:30',
                    next_run TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_gui_runs (
                    gui_run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT NOT NULL DEFAULT ''
                );
                """
            )

    def save_gui_run(self, record: dict[str, Any]) -> str:
        """Persist GUI operation metadata in the isolated lab database."""
        run_id = str(record["gui_run_id"])
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO experiment_gui_runs
                (gui_run_id, started_at, experiment_type, parameters, snapshot_id,
                 status, result_summary, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(record.get("started_at") or ""),
                    str(record.get("experiment_type") or ""),
                    self._json(record.get("parameters") or {}),
                    str(record.get("snapshot_id") or ""),
                    str(record.get("status") or ""),
                    self._json(record.get("result_summary") or {}),
                    str(record.get("error_message") or ""),
                ),
            )
        return run_id

    def save_auto_run(self, record: dict[str, Any]) -> str:
        run_id = str(record["run_id"])
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO strategy_auto_runs
                (run_id, started_at, finished_at, status, data_status,
                 search_count, pass_count, fail_count, top_strategies,
                 frozen_strategy_status, warnings, report_json, report_html,
                 error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(record.get("started_at") or ""),
                    str(record.get("finished_at") or ""),
                    str(record.get("status") or ""),
                    self._json(record.get("data_status") or {}),
                    int(record.get("search_count") or 0),
                    int(record.get("pass_count") or 0),
                    int(record.get("fail_count") or 0),
                    self._json(record.get("top_strategies") or []),
                    self._json(record.get("frozen_strategy_status") or []),
                    self._json(record.get("warnings") or []),
                    str(record.get("report_json") or ""),
                    str(record.get("report_html") or ""),
                    str(record.get("error_message") or ""),
                ),
            )
        return run_id

    def get_last_auto_run(self, *, successful_only: bool = False) -> dict[str, Any] | None:
        where = "WHERE status = 'PASS'" if successful_only else ""
        with self._connect() as connection:
            row = connection.execute(
                f"""SELECT * FROM strategy_auto_runs {where}
                ORDER BY started_at DESC, run_id DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field, fallback in (
            ("data_status", {}),
            ("top_strategies", []),
            ("frozen_strategy_status", []),
            ("warnings", []),
        ):
            try:
                result[field] = json.loads(result[field])
            except (TypeError, ValueError):
                result[field] = fallback
        return result

    def save_auto_schedule(
        self,
        *,
        enabled: bool,
        run_time: str,
        next_run: str,
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO strategy_auto_schedule
                (schedule_id, enabled, run_time, next_run, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    run_time=excluded.run_time,
                    next_run=excluded.next_run,
                    updated_at=excluded.updated_at""",
                (int(enabled), run_time, next_run, updated_at),
            )

    def get_auto_schedule(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_auto_schedule WHERE schedule_id = 1"
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        return result

    def save_experiment(self, experiment: ExperimentResult) -> str:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO experiments
                (experiment_id, data_source, train_ratio, train_issue_range,
                 validation_issue_range, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    experiment.experiment_id,
                    experiment.data_source,
                    experiment.train_ratio,
                    self._json(experiment.train_issue_range),
                    self._json(experiment.validation_issue_range),
                    experiment.created_at,
                ),
            )
            connection.execute(
                "DELETE FROM experiment_candidates WHERE experiment_id = ?",
                (experiment.experiment_id,),
            )
            for rank, candidate in enumerate(experiment.candidates, start=1):
                connection.execute(
                    """INSERT INTO experiment_candidates
                    (experiment_id, rank_no, condition_id, condition_name,
                     condition_params, training_result, validation_result,
                     overall_result, walk_forward_result, score, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        experiment.experiment_id,
                        rank,
                        candidate.condition.condition_id,
                        candidate.condition.name,
                        self._json(dict(candidate.condition.params)),
                        self._json(candidate.train.to_dict()),
                        self._json(candidate.validation.to_dict()),
                        self._json(candidate.overall.to_dict()),
                        self._json([window.to_dict() for window in candidate.walk_forward]),
                        candidate.score,
                        candidate.status,
                    ),
                )
        return experiment.experiment_id

    def save_strategy(
        self,
        experiment_id: str,
        candidate: CandidateResult,
        strategy_name: str | None = None,
    ) -> int:
        name = (strategy_name or candidate.condition.name).strip()
        if not name:
            raise ValueError("策略名称不能为空")
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO saved_strategies
                (experiment_id, condition_id, strategy_name, data_source,
                 condition_params, training_result, validation_result)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    experiment_id,
                    candidate.condition.condition_id,
                    name,
                    candidate.condition.data_source,
                    self._json(dict(candidate.condition.params)),
                    self._json(candidate.train.to_dict()),
                    self._json(candidate.validation.to_dict()),
                ),
            )
            return int(cursor.lastrowid)

    def save_filter_results(
        self,
        experiment_id: str,
        decisions: tuple[FilterDecision, ...] | list[FilterDecision],
        config: FilterConfig,
    ) -> int:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM strategy_filters WHERE experiment_id = ?",
                (experiment_id,),
            )
            for decision in decisions:
                connection.execute(
                    """INSERT INTO strategy_filters
                    (experiment_id, condition_id, passed, reasons, filter_config,
                     walk_forward_pass_ratio) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        experiment_id,
                        decision.candidate.condition.condition_id,
                        int(decision.passed),
                        self._json(list(decision.reasons)),
                        self._json(config.to_dict()),
                        decision.walk_forward_pass_ratio,
                    ),
                )
        return len(decisions)

    def save_rankings(
        self,
        experiment_id: str,
        rankings: tuple[RankingEntry, ...] | list[RankingEntry],
        weights: RankingWeights,
    ) -> int:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM strategy_rankings WHERE experiment_id = ?",
                (experiment_id,),
            )
            for entry in rankings:
                connection.execute(
                    """INSERT INTO strategy_rankings
                    (experiment_id, rank_no, condition_id, status, ranking_score,
                     ranking_metrics, ranking_weights) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        experiment_id,
                        entry.rank,
                        entry.candidate.condition.condition_id,
                        entry.status,
                        entry.ranking_score,
                        self._json(entry.to_dict()),
                        self._json(weights.to_dict()),
                    ),
                )
        return len(rankings)

    def find_cached_candidate(
        self,
        condition_params: Any,
        data_source: str,
    ) -> CandidateResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT c.*, e.data_source
                FROM experiment_candidates AS c
                JOIN experiments AS e ON e.experiment_id = c.experiment_id
                WHERE c.condition_params = ? AND e.data_source = ?
                ORDER BY e.created_at DESC, c.rank_no ASC
                LIMIT 1""",
                (self._json(dict(condition_params)), data_source),
            ).fetchone()
        return None if row is None else self._candidate_from_row(row)

    def save_search(
        self,
        search_id: str,
        search_config: Any,
        parameter_combinations: Any,
        runtime_seconds: float,
        result_summary: Any,
        created_at: str,
    ) -> str:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO strategy_searches
                (search_id, search_config, parameter_combinations, runtime_seconds,
                 result_summary, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    search_id,
                    self._json(search_config),
                    self._json(parameter_combinations),
                    float(runtime_seconds),
                    self._json(result_summary),
                    created_at,
                ),
            )
        return search_id

    def save_frozen_strategy(self, frozen: Any) -> str:
        snapshot = frozen.to_dict()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO strategy_freeze
                (freeze_id, strategy_name, strategy_version, condition_id,
                 condition_params, training_result, validation_result, created_at,
                 status, frozen_at_issue) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    frozen.freeze_id,
                    frozen.strategy_name,
                    frozen.strategy_version,
                    frozen.condition_id,
                    self._json(snapshot["condition_params"]),
                    self._json(snapshot["training_result"]),
                    self._json(snapshot["validation_result"]),
                    frozen.created_at,
                    frozen.status,
                    frozen.frozen_at_issue,
                ),
            )
        return str(frozen.freeze_id)

    def list_frozen_strategies(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_freeze ORDER BY created_at DESC, freeze_id"
            ).fetchall()
        return [
            {
                **dict(row),
                "condition_params": json.loads(row["condition_params"]),
                "training_result": json.loads(row["training_result"]),
                "validation_result": json.loads(row["validation_result"]),
            }
            for row in rows
        ]

    def update_frozen_status(self, freeze_id: str, status: str) -> None:
        if status not in ("ACTIVE", "WATCH", "DISABLED"):
            raise ValueError(f"无效冻结状态：{status}")
        with self._connect() as connection:
            connection.execute(
                "UPDATE strategy_freeze SET status = ? WHERE freeze_id = ?",
                (status, freeze_id),
            )

    def save_tracking_result(self, result: Any, config: Any) -> str:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO strategy_tracking
                (tracking_id, freeze_id, tracked_at, new_samples, recent_performance,
                 current_status, anomaly, reasons, tracking_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.tracking_id,
                    result.freeze_id,
                    result.tracked_at,
                    result.new_samples,
                    self._json(result.recent_performance.to_dict()),
                    result.current_status,
                    int(result.anomaly),
                    self._json(list(result.reasons)),
                    self._json(config),
                ),
            )
        return str(result.tracking_id)

    def save_comparison(self, comparison: Any) -> str:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM strategy_compare WHERE comparison_id = ?",
                (comparison.comparison_id,),
            )
            for row in comparison.rows:
                connection.execute(
                    """INSERT INTO strategy_compare
                    (comparison_id, freeze_id, comparison_snapshot, created_at)
                    VALUES (?, ?, ?, ?)""",
                    (
                        comparison.comparison_id,
                        row.freeze_id,
                        self._json(row.to_dict()),
                        comparison.created_at,
                    ),
                )
        return str(comparison.comparison_id)

    def experiment_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS value FROM experiments").fetchone()
            return int(row["value"])

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _metrics_from_dict(value: dict[str, Any]) -> EvaluationMetrics:
        payload = dict(value)
        payload["details"] = tuple(dict(item) for item in payload.get("details") or ())
        return EvaluationMetrics(**payload)

    @classmethod
    def _candidate_from_row(cls, row: sqlite3.Row) -> CandidateResult:
        train = json.loads(row["training_result"])
        validation = json.loads(row["validation_result"])
        overall = json.loads(row["overall_result"])
        windows = json.loads(row["walk_forward_result"])
        condition = StrategyCondition(
            condition_id=str(row["condition_id"]),
            name=str(row["condition_name"]),
            params=json.loads(row["condition_params"]),
            data_source=str(row["data_source"]),
        )
        return CandidateResult(
            condition=condition,
            train=cls._metrics_from_dict(train),
            validation=cls._metrics_from_dict(validation),
            overall=cls._metrics_from_dict(overall),
            walk_forward=tuple(
                WalkForwardWindow(
                    index=int(window["index"]),
                    train_issue_range=tuple(window["train_issue_range"]),
                    validation_issue_range=tuple(window["validation_issue_range"]),
                    train=cls._metrics_from_dict(window["train"]),
                    validation=cls._metrics_from_dict(window["validation"]),
                )
                for window in windows
            ),
            score=float(row["score"]),
            status=str(row["status"]),
        )


__all__ = ["DEFAULT_PATH", "StrategyLabStorage"]
