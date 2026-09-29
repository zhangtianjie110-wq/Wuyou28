from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .health import readonly_sqlite
from .models import StrategySummary


class StrategyAlgorithmQualityRepository:
    """Read-only access to isolated algorithm-quality v4 research results."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @staticmethod
    def _latest_run(connection) -> dict[str, Any] | None:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='algorithm_v4_runs'"
        ).fetchone()
        if exists is None:
            return None
        row = connection.execute(
            "SELECT * FROM algorithm_v4_runs WHERE status='COMPLETE' ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def status(self) -> dict[str, Any]:
        try:
            with readonly_sqlite(self.database_path) as connection:
                run = self._latest_run(connection)
        except FileNotFoundError:
            run = None
        if run is None:
            return {"available": False, "source_type": "RECONSTRUCTED"}
        value = dict(run)
        value["available"] = True
        for source, target in (
            ("summary_json", "summary"),
            ("ranking_json", "ranking"),
            ("baselines_json", "baselines"),
            ("timing_json", "timing"),
        ):
            value[target] = json.loads(str(value.pop(source)))
        return value

    @staticmethod
    def _summary(row: dict[str, Any]) -> StrategySummary:
        train = json.loads(str(row["train_metrics_json"]))
        validation = json.loads(str(row["validation_metrics_json"]))
        test = json.loads(str(row["test_metrics_json"]))
        strict = json.loads(str(row["strict_metrics_json"]))
        recent = json.loads(str(row["recent_metrics_json"]))
        conditions = {
            "quality_method": str(row["quality_method"]),
            "group_method": str(row["group_method"]),
            "selection_method": str(row["selection_method"]),
            "max_weight_ratio": float(row["max_weight_ratio"]),
            "ci_low": strict.get("ci_low"),
            "ci_high": strict.get("ci_high"),
            "recent": recent,
            "stage_status": str(row["stage_status"]),
        }
        return StrategySummary(
            strategy_id=str(row["method_id"]),
            strategy_hash=str(row["rule_hash"]),
            status=str(row["lifecycle"]),
            source_status=str(row["stage_status"]),
            predictor="algorithm_quality",
            conditions=conditions,
            train_samples=int(train.get("triggers", 0)),
            validation_samples=int(validation.get("triggers", 0)),
            test_samples=int(test.get("triggers", 0)),
            trigger_count=int(strict.get("triggers", 0)),
            hit_count=int(strict.get("hits", 0)),
            miss_count=int(strict.get("misses", 0)),
            accuracy=strict.get("accuracy"),
            validation_accuracy=validation.get("accuracy"),
            test_accuracy=test.get("accuracy"),
            walk_forward_accuracy=None,
            max_consecutive_misses=int(strict.get("max_consecutive_misses", 0)),
            recent_20_accuracy=(recent.get("30") or {}).get("accuracy"),
            recent_50_accuracy=(recent.get("50") or {}).get("accuracy"),
            recent_100_accuracy=(recent.get("100") or {}).get("accuracy"),
            forward_samples=0,
            forward_accuracy=None,
            created_at=str(row["created_at"]),
            train_triggers=int(train.get("triggers", 0)),
            validation_triggers=int(validation.get("triggers", 0)),
            test_triggers=int(test.get("triggers", 0)),
            train_accuracy=train.get("accuracy"),
            max_consecutive_hits=int(strict.get("max_consecutive_hits", 0)),
            average_trigger_interval=strict.get("average_trigger_interval"),
            strategy_name="算法质量与群体共识",
            strategy_version=str(row["method_version"]),
            rule_hash=str(row["rule_hash"]),
            prediction_status="WAITING_DATA",
            prediction_source="RECONSTRUCTED",
        )

    def list_methods(self, limit: int = 20) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 42))
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return []
            rows = connection.execute(
                """SELECT * FROM algorithm_v4_methods
                   WHERE run_id=? AND stage_status IN ('FINAL_CANDIDATE','TESTED')
                   ORDER BY CASE stage_status WHEN 'FINAL_CANDIDATE' THEN 0 ELSE 1 END,
                            method_id LIMIT ?""",
                (run["run_id"], safe_limit),
            ).fetchall()
        return [self._summary(dict(row)) for row in rows]

    def algorithm_stats(self) -> tuple[dict[str, Any], ...]:
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return ()
            rows = connection.execute(
                """SELECT * FROM algorithm_v4_algorithm_stats
                   WHERE run_id=? ORDER BY algorithm_order""",
                (run["run_id"],),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def groups(self) -> tuple[dict[str, Any], ...]:
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return ()
            rows = connection.execute(
                """SELECT * FROM algorithm_v4_groups
                   WHERE run_id=? ORDER BY group_number""",
                (run["run_id"],),
            ).fetchall()
        return tuple(
            {**dict(row), "members": json.loads(str(row["members_json"]))}
            for row in rows
        )

    def current(self) -> dict[str, Any]:
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return {}
            row = connection.execute(
                "SELECT * FROM algorithm_v4_current_consensus WHERE run_id=?",
                (run["run_id"],),
            ).fetchone()
        if row is None:
            return {}
        value = dict(row)
        for source, target in (
            ("equal_totals_json", "equal_totals"),
            ("weighted_totals_json", "weighted_totals"),
            ("equal_pair_json", "equal_pair"),
            ("weighted_pair_json", "weighted_pair"),
        ):
            value[target] = json.loads(str(value.pop(source)))
        return value
