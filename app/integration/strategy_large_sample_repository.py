from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .health import readonly_sqlite
from .models import StrategyDetail, StrategySummary


class StrategyLargeSampleRepository:
    """Read-only view of isolated StrategyResearchEngine large-sample tables."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @staticmethod
    def _has_schema(connection) -> bool:
        return connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='large_sample_runs'"""
        ).fetchone() is not None

    @classmethod
    def _latest_run(cls, connection) -> dict[str, Any] | None:
        if not cls._has_schema(connection):
            return None
        row = connection.execute(
            """SELECT * FROM large_sample_runs
               WHERE status='COMPLETE' ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    def status(self) -> dict[str, Any]:
        try:
            with readonly_sqlite(self.database_path) as connection:
                run = self._latest_run(connection)
                if run is None:
                    return {"available": False, "source_type": "RECONSTRUCTED"}
                baseline_row = connection.execute(
                    "SELECT * FROM large_sample_baseline WHERE run_id=?",
                    (run["run_id"],),
                ).fetchone()
        except FileNotFoundError:
            return {"available": False, "source_type": "RECONSTRUCTED"}
        baseline = json.loads(str(baseline_row["metrics_json"])) if baseline_row else {}
        return {
            "available": True,
            **run,
            "baseline": baseline,
            "baseline_tie_control": (
                str(baseline_row["tie_control"]) if baseline_row else None
            ),
        }

    @staticmethod
    def _summary(row: dict[str, Any]) -> StrategySummary:
        train = json.loads(str(row["train_metrics_json"]))
        validation = json.loads(str(row["validation_metrics_json"]))
        test = json.loads(str(row["test_metrics_json"]))
        walk = json.loads(str(row["walk_forward_json"]))
        full = json.loads(str(row["full_metrics_json"]))
        definition = json.loads(str(row["rule_definition_json"]))
        pair = tuple(json.loads(str(row["selected_pair_json"])))
        return StrategySummary(
            strategy_id=str(row["strategy_id"]),
            strategy_hash=str(row["rule_hash"]),
            status="CANDIDATE",
            source_status="CANDIDATE",
            predictor="fixed_pair",
            conditions=definition,
            train_samples=int(row["train_issues"]),
            validation_samples=int(row["validation_issues"]),
            test_samples=int(row["test_issues"]),
            trigger_count=int(full["triggers"]),
            hit_count=int(full["hits"]),
            miss_count=int(full["misses"]),
            accuracy=full.get("accuracy"),
            validation_accuracy=validation.get("accuracy"),
            test_accuracy=test.get("accuracy"),
            walk_forward_accuracy=walk.get("accuracy"),
            max_consecutive_misses=int(full["max_consecutive_misses"]),
            recent_20_accuracy=full.get("recent_30_accuracy"),
            recent_50_accuracy=full.get("recent_50_accuracy"),
            recent_100_accuracy=full.get("recent_100_accuracy"),
            forward_samples=0,
            forward_accuracy=None,
            created_at=str(row["created_at"]),
            train_triggers=int(train["triggers"]),
            validation_triggers=int(validation["triggers"]),
            test_triggers=int(test["triggers"]),
            train_accuracy=train.get("accuracy"),
            max_consecutive_hits=int(full["max_consecutive_hits"]),
            current_streak_type=str(full["current_streak_type"]),
            current_streak_count=int(full["current_streak_count"]),
            average_trigger_interval=full.get("average_trigger_interval"),
            sample_warning=str(row["sample_warning"] or "") or None,
            strategy_name=str(row["strategy_name"]),
            strategy_version=str(row["strategy_version"]),
            rule_hash=str(row["rule_hash"]),
            target_issue=None,
            triggered=False,
            current_prediction=pair,
            prediction_status="WAITING_DATA",
            prediction_generated_at=None,
            prediction_source="RECONSTRUCTED",
        )

    def list_strategies(self, limit: int = 100) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 100))
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return []
            rows = connection.execute(
                """SELECT c.*, r.train_issues, r.validation_issues, r.test_issues
                   FROM large_sample_candidates c
                   JOIN large_sample_runs r USING(run_id)
                   WHERE c.run_id=? ORDER BY c.strategy_name LIMIT ?""",
                (run["run_id"], safe_limit),
            ).fetchall()
        return [self._summary(dict(row)) for row in rows]

    def contains(self, strategy_id: str) -> bool:
        try:
            with readonly_sqlite(self.database_path) as connection:
                if not self._has_schema(connection):
                    return False
                return connection.execute(
                    "SELECT 1 FROM large_sample_candidates WHERE strategy_id=? LIMIT 1",
                    (str(strategy_id),),
                ).fetchone() is not None
        except FileNotFoundError:
            return False

    def get(
        self,
        strategy_id: str,
        history_scope: str = "ALL",
        history_limit: int = 100,
    ) -> StrategyDetail | None:
        scope = str(history_scope or "ALL").upper()
        if scope not in {"ALL", "TRAIN", "VALIDATION", "TEST", "RECONSTRUCTED", "FORWARD"}:
            raise ValueError(f"unsupported large-sample history scope: {history_scope}")
        safe_limit = max(1, min(int(history_limit), 500))
        with readonly_sqlite(self.database_path) as connection:
            run = self._latest_run(connection)
            if run is None:
                return None
            row = connection.execute(
                """SELECT c.*, r.train_issues, r.validation_issues, r.test_issues
                   FROM large_sample_candidates c
                   JOIN large_sample_runs r USING(run_id)
                   WHERE c.run_id=? AND c.strategy_id=?""",
                (run["run_id"], str(strategy_id)),
            ).fetchone()
            if row is None:
                return None
            clause = ""
            parameters: tuple[Any, ...] = (run["run_id"], str(strategy_id))
            if scope in {"TRAIN", "VALIDATION", "TEST"}:
                clause = " AND dataset_split=?"
                parameters += (scope,)
            triggers = (
                []
                if scope == "FORWARD"
                else [
                    dict(item)
                    for item in connection.execute(
                        f"""SELECT * FROM large_sample_triggers
                             WHERE run_id=? AND strategy_id=?{clause}
                             ORDER BY issue DESC LIMIT ?""",
                        parameters + (safe_limit,),
                    )
                ]
            )
            all_triggers = [
                dict(item)
                for item in connection.execute(
                    """SELECT * FROM large_sample_triggers
                       WHERE run_id=? AND strategy_id=? ORDER BY issue""",
                    (run["run_id"], str(strategy_id)),
                )
            ]
            windows = tuple(
                dict(item)
                for item in connection.execute(
                    """SELECT * FROM large_sample_walk_forward
                       WHERE run_id=? AND strategy_id=? ORDER BY window_index""",
                    (run["run_id"], str(strategy_id)),
                )
            )
        source = dict(row)
        summary = self._summary(source)
        train = json.loads(str(source["train_metrics_json"]))
        validation = json.loads(str(source["validation_metrics_json"]))
        test = json.loads(str(source["test_metrics_json"]))
        walk = json.loads(str(source["walk_forward_json"]))
        full = json.loads(str(source["full_metrics_json"]))
        history = tuple(
            {
                "issue": int(item["issue"]),
                "prediction": item["predicted_pair_json"],
                "actual_result": item["actual_combination"],
                "result_status": "PASS" if bool(item["hit"]) else "FAIL",
                "sample_type": str(item["dataset_split"]),
                "source_type": str(item["source_type"]),
                "generated_at": None,
                "strategy_version": summary.strategy_version,
                "rule_hash": summary.rule_hash,
            }
            for item in triggers
        )
        latest = history[0] if history else None
        if latest is not None:
            latest = {**latest, "distance": int(run["test_end"]) - int(latest["issue"])}
        statistics = {
            "matched_issues": int(full["triggers"]),
            "valid_samples": int(full["triggers"]),
            "invalid_samples": 0,
            "hit_count": int(full["hits"]),
            "miss_count": int(full["misses"]),
            "accuracy": full.get("accuracy"),
            "recent_30_accuracy": full.get("recent_30_accuracy"),
            "recent_50_accuracy": full.get("recent_50_accuracy"),
            "recent_100_accuracy": full.get("recent_100_accuracy"),
            "recent_200_accuracy": full.get("recent_200_accuracy"),
            "max_consecutive_hits": int(full["max_consecutive_hits"]),
            "max_consecutive_misses": int(full["max_consecutive_misses"]),
            "current_streak_type": str(full["current_streak_type"]),
            "current_streak_count": int(full["current_streak_count"]),
            "average_trigger_interval": full.get("average_trigger_interval"),
            "train_triggers": int(train["triggers"]),
            "train_accuracy": train.get("accuracy"),
            "validation_triggers": int(validation["triggers"]),
            "validation_accuracy": validation.get("accuracy"),
            "test_triggers": int(test["triggers"]),
            "test_accuracy": test.get("accuracy"),
            "walk_forward_windows": int(walk["window_count"]),
            "walk_forward_triggers": int(walk["triggers"]),
            "walk_forward_accuracy": walk.get("accuracy"),
            "walk_forward_worst": walk.get("worst_window_accuracy"),
            "walk_forward_best": walk.get("best_window_accuracy"),
            "walk_forward_median": walk.get("median_window_accuracy"),
            "walk_forward_volatility": walk.get("window_volatility"),
            "walk_forward_max_misses": int(walk["max_consecutive_misses"]),
            "sample_warning": source.get("sample_warning"),
            "overfit_warning": source.get("overfit_warning"),
        }
        normalized_all = tuple(
            {
                "issue": int(item["issue"]),
                "prediction": item["predicted_pair_json"],
                "actual_result": item["actual_combination"],
                "result_status": "PASS" if bool(item["hit"]) else "FAIL",
                "sample_type": str(item["dataset_split"]),
                "source_type": str(item["source_type"]),
            }
            for item in all_triggers
        )
        return StrategyDetail(
            summary=summary,
            historical_triggers=normalized_all,
            forward_records=(),
            walk_forward_windows=windows,
            prediction_history=(),
            statistics=statistics,
            latest_trigger=latest,
            history_records=history,
            history_scope=scope,
            history_limit=safe_limit,
        )
