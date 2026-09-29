from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .health import readonly_sqlite
from .models import StrategySummary


class StrategyStateSimilarityRepository:
    """Read-only access to isolated state-similarity v3 research results."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @staticmethod
    def _has_schema(connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_v3_runs'"
        ).fetchone() is not None

    @classmethod
    def _latest_run(cls, connection) -> dict[str, Any] | None:
        if not cls._has_schema(connection):
            return None
        row = connection.execute(
            "SELECT * FROM state_v3_runs WHERE status='COMPLETE' ORDER BY completed_at DESC LIMIT 1"
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
            ("best_summary_json", "best_summary"),
            ("baseline_json", "baselines"),
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
            "representation": str(row["representation"]),
            "distance_method": str(row["distance_method"]),
            "k_value": int(row["k_value"]),
            "time_decay": str(row["time_decay"]),
            "min_similar_samples": int(row["min_similar_samples"]),
            "distance_threshold": row["distance_threshold"],
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
            predictor="state_similarity",
            conditions=conditions,
            train_samples=int(train.get("targets", 0)),
            validation_samples=int(validation.get("targets", 0)),
            test_samples=int(test.get("targets", 0)),
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
            strategy_name=f"状态相似方法 K={int(row['k_value'])}",
            strategy_version=str(row["method_version"]),
            rule_hash=str(row["rule_hash"]),
            prediction_status="WAITING_DATA",
            prediction_source="RECONSTRUCTED",
        )

    def list_methods(self, limit: int = 20) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 40))
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return []
            rows = connection.execute(
                """SELECT * FROM state_v3_methods
                   WHERE run_id=? AND stage_status IN ('FINAL_CANDIDATE','TESTED')
                   ORDER BY CASE stage_status WHEN 'FINAL_CANDIDATE' THEN 0 ELSE 1 END,
                            method_id LIMIT ?""",
                (run["run_id"], safe_limit),
            ).fetchall()
        return [self._summary(dict(row)) for row in rows]

    def current(self) -> dict[str, Any]:
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return {}
            row = connection.execute(
                "SELECT * FROM state_v3_current_state WHERE run_id=?", (run["run_id"],)
            ).fetchone()
            if row is None:
                return {}
            neighbors = connection.execute(
                "SELECT * FROM state_v3_current_neighbors WHERE run_id=? ORDER BY neighbor_rank",
                (run["run_id"],),
            ).fetchall()
        value = dict(row)
        value["features"] = json.loads(str(value.pop("features_json")))
        value["selected_pair"] = json.loads(str(value.pop("selected_pair_json")))
        value["pair_statistics"] = json.loads(str(value.pop("pair_statistics_json")))
        value["neighbors"] = tuple(
            {
                **dict(item),
                "counts": json.loads(str(item["counts_json"])),
                "hit_pairs": json.loads(str(item["hit_pairs_json"])),
            }
            for item in neighbors
        )
        return value

    def replay(self, method_id: str | None = None, limit: int = 100) -> tuple[dict, ...]:
        safe_limit = max(1, min(int(limit), 500))
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return ()
            selected = str(method_id or run.get("best_method_id") or "")
            rows = connection.execute(
                """SELECT * FROM state_v3_replay
                   WHERE run_id=? AND method_id=? ORDER BY target_issue DESC LIMIT ?""",
                (run["run_id"], selected, safe_limit),
            ).fetchall()
        return tuple(
            {
                **dict(row),
                "selected_pair": json.loads(str(row["selected_pair_json"])),
            }
            for row in rows
        )

    def segments(self, method_id: str | None = None) -> tuple[dict, ...]:
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return ()
            selected = str(method_id or run.get("best_method_id") or "")
            rows = connection.execute(
                """SELECT * FROM state_v3_segments
                   WHERE run_id=? AND method_id=? ORDER BY segment_index""",
                (run["run_id"], selected),
            ).fetchall()
        return tuple(dict(row) for row in rows)
