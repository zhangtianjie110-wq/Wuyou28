from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from app.constants import COMBINATIONS, DATA_DIR


HISTORY_DB_ENV = "WUYOU28_VIP100_HISTORY_DB"
HISTORY_DATA_SOURCE = "VIP100_HISTORY"
DEFAULT_HISTORY_DB_PATH = DATA_DIR / "vip100_history.sqlite3"
LEGACY_HISTORY_DB_PATH = DATA_DIR / "vip100_reconstructed_v1.sqlite3"


def resolve_history_database(path: str | Path | None = None) -> Path:
    """Resolve the VIP100 history database without a product-database fallback."""

    if path is not None:
        return Path(path).expanduser().resolve()
    override = os.environ.get(HISTORY_DB_ENV) or os.environ.get("VIP100_REPLAY_DB")
    if override:
        return Path(override).expanduser().resolve()
    for candidate in (DEFAULT_HISTORY_DB_PATH, LEGACY_HISTORY_DB_PATH):
        if candidate.is_file():
            return candidate.resolve()

    # Development installations may still keep the replay database beside the
    # VIP100 engine. Packaged builds use the canonical user-data path above.
    try:
        from app.integration.models import IntegrationPaths

        legacy = IntegrationPaths.from_environment().vip100_replay_db
        if legacy is not None and legacy.is_file():
            return legacy.resolve()
    except (OSError, RuntimeError, ValueError):
        pass
    return DEFAULT_HISTORY_DB_PATH.resolve()


class Vip100HistoryDataSource:
    """Read settled VIP100 replay rows and aggregate them per issue.

    The source database is opened in SQLite read-only/query-only mode. Its two
    normalized tables retain every algorithm id, prediction, draw result and
    hit flag; aggregation only adapts those rows to the existing backtest API.
    """

    REQUIRED_TABLES = {
        "vip100_reconstructed_runs",
        "vip100_reconstructed_predictions",
    }

    def __init__(self, path: str | Path | None = None):
        self.path = resolve_history_database(path)

    def connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(f"VIP100历史回测数据库不存在：{self.path}")
        connection = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        self._validate_schema(connection)
        return connection

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(cls.REQUIRED_TABLES - tables)
        if missing:
            raise ValueError(f"VIP100历史回测数据库缺少表：{', '.join(missing)}")

    @staticmethod
    def _period_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT r.target_issue,
                   r.generated_at,
                   r.actual_result,
                   r.actual_combination,
                   r.prediction_count AS declared_predictions,
                   COUNT(p.algorithm_id) AS prediction_rows,
                   COUNT(DISTINCT p.algorithm_id) AS unique_algorithms,
                   SUM(CASE WHEN p.hit IS NOT NULL THEN 1 ELSE 0 END) AS settled_rows,
                   SUM(CASE WHEN p.combination IN ('大单','大双','小单','小双')
                            THEN 1 ELSE 0 END) AS valid_combinations,
                   SUM(CASE WHEN p.combination='大单' THEN 1 ELSE 0 END) AS big_single,
                   SUM(CASE WHEN p.combination='大双' THEN 1 ELSE 0 END) AS big_double,
                   SUM(CASE WHEN p.combination='小单' THEN 1 ELSE 0 END) AS small_single,
                   SUM(CASE WHEN p.combination='小双' THEN 1 ELSE 0 END) AS small_double,
                   COALESCE(SUM(p.hit), 0) AS hit_count
            FROM vip100_reconstructed_runs r
            LEFT JOIN vip100_reconstructed_predictions p
              ON p.target_issue=r.target_issue
             AND p.source_type='RECONSTRUCTED'
            WHERE r.source_type='RECONSTRUCTED'
            GROUP BY r.target_issue
            ORDER BY r.target_issue
            """
        ).fetchall()

    @staticmethod
    def _complete(row: sqlite3.Row) -> bool:
        return (
            int(row["declared_predictions"] or 0) == 100
            and int(row["prediction_rows"] or 0) == 100
            and int(row["unique_algorithms"] or 0) == 100
            and int(row["settled_rows"] or 0) == 100
            and int(row["valid_combinations"] or 0) == 100
            and str(row["actual_combination"] or "") in COMBINATIONS
        )

    def data_status(self) -> dict[str, Any]:
        with self.connect() as connection:
            periods = self._period_rows(connection)
        complete = sum(1 for row in periods if self._complete(row))
        missing_outcomes = sum(
            1 for row in periods if str(row["actual_combination"] or "") not in COMBINATIONS
        )
        incomplete_predictions = sum(
            1
            for row in periods
            if int(row["prediction_rows"] or 0) != 100
            or int(row["unique_algorithms"] or 0) != 100
        )
        prediction_rows = sum(int(row["prediction_rows"] or 0) for row in periods)
        settled_rows = sum(int(row["settled_rows"] or 0) for row in periods)
        partial = len(periods) - complete
        return {
            "data_source": HISTORY_DATA_SOURCE,
            "database_path": str(self.path),
            "current_periods": len(periods),
            "new_periods": 0,
            "latest_issue": str(periods[-1]["target_issue"]) if periods else "",
            "complete": complete,
            "partial": partial,
            "missing": partial,
            "missing_periods": partial,
            "prediction_rows": prediction_rows,
            "settled_prediction_rows": settled_rows,
            "missing_prediction_rows": max(0, len(periods) * 100 - prediction_rows),
            "missing_outcome_periods": missing_outcomes,
            "incomplete_prediction_periods": incomplete_predictions,
        }

    def backtest_records(self, data_source: str = "VIP") -> list[dict[str, Any]]:
        with self.connect() as connection:
            periods = self._period_rows(connection)
        records: list[dict[str, Any]] = []
        for row in periods:
            if not self._complete(row):
                continue
            hit_count = int(row["hit_count"] or 0)
            records.append(
                {
                    "id": len(records) + 1,
                    "issue_no": str(row["target_issue"]),
                    "source_type": str(data_source),
                    "plan_count": 100,
                    "big_single": int(row["big_single"] or 0),
                    "big_double": int(row["big_double"] or 0),
                    "small_single": int(row["small_single"] or 0),
                    "small_double": int(row["small_double"] or 0),
                    "actual_result": str(row["actual_result"] or ""),
                    "actual_combo": str(row["actual_combination"]),
                    "correct_count": hit_count,
                    "wrong_count": 100 - hit_count,
                    "status": "正常",
                    "is_invalid": 0,
                    "created_at": str(row["generated_at"] or ""),
                    "history_source": "VIP100_RECONSTRUCTED",
                }
            )
        return records


__all__ = [
    "DEFAULT_HISTORY_DB_PATH",
    "HISTORY_DATA_SOURCE",
    "HISTORY_DB_ENV",
    "LEGACY_HISTORY_DB_PATH",
    "Vip100HistoryDataSource",
    "resolve_history_database",
]
