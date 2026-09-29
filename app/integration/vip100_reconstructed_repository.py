from __future__ import annotations

from pathlib import Path

from .health import readonly_sqlite
from .models import Vip100Batch, Vip100Prediction


class Vip100ReconstructedRepository:
    """Read-only access to the isolated historical replay database."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def list_issues(self, limit: int = 200) -> list[str]:
        if limit <= 0 or not self.database_path.is_file():
            return []
        with readonly_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """SELECT target_issue FROM vip100_reconstructed_runs
                   WHERE source_type='RECONSTRUCTED'
                   ORDER BY target_issue DESC LIMIT ?""",
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def count(self) -> int:
        if not self.database_path.is_file():
            return 0
        with readonly_sqlite(self.database_path) as connection:
            return int(
                connection.execute(
                    """SELECT COUNT(*) FROM vip100_reconstructed_runs
                       WHERE source_type='RECONSTRUCTED'"""
                ).fetchone()[0]
            )

    def get(self, issue: str | int) -> Vip100Batch | None:
        if not self.database_path.is_file():
            return None
        with readonly_sqlite(self.database_path) as connection:
            run = connection.execute(
                """SELECT * FROM vip100_reconstructed_runs
                   WHERE target_issue=? AND source_type='RECONSTRUCTED'""",
                (int(issue),),
            ).fetchone()
            if run is None:
                return None
            rows = connection.execute(
                """SELECT * FROM vip100_reconstructed_predictions
                   WHERE target_issue=? AND source_type='RECONSTRUCTED'
                   ORDER BY algorithm_order""",
                (int(issue),),
            ).fetchall()
        if int(run["prediction_count"]) != 100 or len(rows) != 100:
            raise ValueError("historical replay batch is not exactly 100 rows")
        predictions = tuple(
            Vip100Prediction(
                position=int(row["algorithm_order"]),
                algorithm_id=str(row["algorithm_id"]),
                algorithm_name=f"算法 {int(row['algorithm_order']):03d}",
                formula=str(row["formula"]),
                prediction=int(row["prediction"]),
                combination=str(row["combination"]),
                hit=None if row["hit"] is None else bool(row["hit"]),
            )
            for row in rows
        )
        return Vip100Batch(
            issue=str(run["target_issue"]),
            generated_at=str(run["generated_at"]),
            engine_version=str(run["engine_version"]),
            algorithm_hash=str(run["algorithm_hash"]),
            history_hash=str(run["input_snapshot_hash"]),
            input_hash=str(run["input_snapshot_hash"]),
            source=str(run["source_type"]),
            actual_result=str(run["actual_result"]) if run["actual_result"] else None,
            predictions=predictions,
            input_start_issue=str(run["input_start_issue"]),
            input_end_issue=str(run["input_end_issue"]),
            replay_version=str(run["replay_version"]),
        )

    def latest(self) -> Vip100Batch | None:
        issues = self.list_issues(1)
        return self.get(issues[0]) if issues else None

    def summary(self) -> dict:
        if not self.database_path.is_file():
            return {
                "source_type": "RECONSTRUCTED",
                "issue_count": 0,
                "prediction_count": 0,
            }
        with readonly_sqlite(self.database_path) as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS issue_count,
                          COALESCE(SUM(prediction_count),0) AS prediction_count,
                          MIN(target_issue) AS start_issue,
                          MAX(target_issue) AS end_issue
                   FROM vip100_reconstructed_runs
                   WHERE source_type='RECONSTRUCTED'"""
            ).fetchone()
        return {"source_type": "RECONSTRUCTED", **dict(row)}
