from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .health import freshness, read_json_object, readonly_sqlite
from .models import StrategyDetail, StrategySummary


LIFECYCLE_STATES = {
    "RESEARCH_ONLY",
    "CANDIDATE",
    "FORWARD_TEST",
    "VERIFIED",
    "REJECTED",
}


class StrategyResearchRepository:
    """Read StrategyResearchEngine state and results without running research."""

    def __init__(self, database_path: Path, runtime_status_path: Path):
        self.database_path = Path(database_path)
        self.runtime_status_path = Path(runtime_status_path)

    @staticmethod
    def _lifecycle(
        result_status: object,
        candidate_status: object = None,
        forward_status: object = None,
    ) -> str:
        # Stored lifecycle values are authoritative. The gateway never promotes a strategy.
        for value in (forward_status, candidate_status, result_status):
            status = str(value or "").upper()
            if status in LIFECYCLE_STATES:
                return status
        if str(result_status or "").upper() == "INSUFFICIENT_SAMPLE":
            return "RESEARCH_ONLY"
        return "RESEARCH_ONLY"

    @staticmethod
    def _current_streak(rows: Iterable[dict[str, Any]]) -> tuple[str, int]:
        decided = [bool(row["hit"]) for row in rows if row.get("hit") is not None]
        if not decided:
            return "NONE", 0
        latest = decided[-1]
        count = 0
        for value in reversed(decided):
            if value != latest:
                break
            count += 1
        return ("HIT" if latest else "MISS"), count

    @staticmethod
    def _average_interval(rows: Iterable[dict[str, Any]]) -> float | None:
        issues = sorted({int(row["issue"]) for row in rows})
        if len(issues) < 2:
            return None
        gaps = [right - left for left, right in zip(issues, issues[1:])]
        return sum(gaps) / len(gaps)

    @staticmethod
    def _latest_run(connection) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM research_runs ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _has_prediction_history(connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_prediction_history'"
        ).fetchone() is not None

    @classmethod
    def _current_predictions(
        cls, connection
    ) -> tuple[str | None, dict[str, dict[str, Any]]]:
        if not cls._has_prediction_history(connection):
            return None, {}
        issue = connection.execute(
            "SELECT MAX(target_issue) FROM strategy_prediction_history WHERE source='FORWARD'"
        ).fetchone()[0]
        if issue is None:
            return None, {}
        rows = connection.execute(
            """SELECT h.*, s.actual_result, s.validation_status
               FROM strategy_prediction_history h
               LEFT JOIN strategy_prediction_settlements s
                 ON s.target_issue=h.target_issue
                AND s.strategy_id=h.strategy_id
                AND s.strategy_version=h.strategy_version
                AND s.source=h.source
               WHERE h.target_issue=? AND h.source='FORWARD'
               ORDER BY h.strategy_id""",
            (issue,),
        ).fetchall()
        return str(issue), {str(row["strategy_id"]): dict(row) for row in rows}

    @classmethod
    def _prediction_history(cls, connection, strategy_id: str) -> tuple[dict[str, Any], ...]:
        if not cls._has_prediction_history(connection):
            return ()
        rows = connection.execute(
            """SELECT h.*, s.actual_result, s.validation_status, s.settled_at
               FROM strategy_prediction_history h
               LEFT JOIN strategy_prediction_settlements s
                 ON s.target_issue=h.target_issue
                AND s.strategy_id=h.strategy_id
                AND s.strategy_version=h.strategy_version
                AND s.source=h.source
               WHERE h.strategy_id=?
               ORDER BY h.target_issue, h.strategy_version, h.source""",
            (strategy_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def _forward_metrics(connection) -> dict[str, tuple[int, float | None]]:
        rows = connection.execute(
            """SELECT strategy_id, COUNT(*) AS samples,
                      AVG(CASE WHEN hit=1 THEN 1.0 ELSE 0.0 END) AS accuracy
               FROM forward_evaluations WHERE triggered=1 GROUP BY strategy_id"""
        ).fetchall()
        return {
            str(row["strategy_id"]): (int(row["samples"]), row["accuracy"])
            for row in rows
        }

    @staticmethod
    def _split_metrics(
        connection, run_id: str
    ) -> dict[str, dict[str, tuple[int, float | None]]]:
        rows = connection.execute(
            """SELECT strategy_id, dataset_split, COUNT(*) AS triggers,
                      AVG(CASE WHEN hit=1 THEN 1.0 ELSE 0.0 END) AS accuracy
               FROM strategy_triggers WHERE run_id=?
               GROUP BY strategy_id, dataset_split""",
            (run_id,),
        ).fetchall()
        values: dict[str, dict[str, tuple[int, float | None]]] = {}
        for row in rows:
            values.setdefault(str(row["strategy_id"]), {})[
                str(row["dataset_split"])
            ] = (int(row["triggers"]), row["accuracy"])
        return values

    @staticmethod
    def _average_intervals(connection, run_id: str) -> dict[str, float]:
        rows = connection.execute(
            """WITH ordered AS (
                   SELECT strategy_id, issue,
                          LAG(issue) OVER(PARTITION BY strategy_id ORDER BY issue) AS previous_issue
                   FROM strategy_triggers WHERE run_id=?
               )
               SELECT strategy_id, AVG(issue - previous_issue) AS average_interval
               FROM ordered WHERE previous_issue IS NOT NULL GROUP BY strategy_id""",
            (run_id,),
        ).fetchall()
        return {
            str(row["strategy_id"]): float(row["average_interval"])
            for row in rows
            if row["average_interval"] is not None
        }

    @staticmethod
    def _summary(
        row: dict[str, Any],
        *,
        lifecycle: str,
        forward_samples: int,
        forward_accuracy: float | None,
        split_metrics: dict[str, tuple[int, float | None]] | None = None,
        average_interval: float | None = None,
        created_at: str | None = None,
        current_streak: tuple[str, int] = ("NONE", 0),
        current_issue: str | None = None,
        current_prediction: dict[str, Any] | None = None,
    ) -> StrategySummary:
        split_metrics = split_metrics or {}
        train_triggers, train_accuracy = split_metrics.get("train", (0, None))
        validation_triggers, _ = split_metrics.get("validation", (0, None))
        test_triggers, _ = split_metrics.get("test", (0, None))
        source_status = str(row.get("status") or "")
        strategy_id = str(row["strategy_id"])
        strategy_hash = str(row["strategy_hash"])
        prediction_values = None
        if current_prediction and current_prediction.get("current_prediction"):
            parsed = json.loads(str(current_prediction["current_prediction"]))
            prediction_values = tuple(str(value) for value in parsed)
        return StrategySummary(
            strategy_id=strategy_id,
            strategy_hash=strategy_hash,
            status=lifecycle,
            source_status=source_status,
            predictor=str(row["predictor"]),
            conditions=json.loads(str(row["condition_json"])),
            train_samples=int(row.get("train_samples") or 0),
            validation_samples=int(row.get("validation_samples") or 0),
            test_samples=int(row.get("test_samples") or 0),
            trigger_count=int(row.get("trigger_count") or 0),
            hit_count=int(row.get("hit_count") or 0),
            miss_count=int(row.get("miss_count") or 0),
            accuracy=row.get("accuracy"),
            validation_accuracy=row.get("validation_accuracy"),
            test_accuracy=row.get("test_accuracy"),
            walk_forward_accuracy=row.get("walk_forward_accuracy"),
            max_consecutive_misses=int(row.get("max_consecutive_misses") or 0),
            recent_20_accuracy=row.get("recent_20_accuracy"),
            recent_50_accuracy=row.get("recent_50_accuracy"),
            recent_100_accuracy=row.get("recent_100_accuracy"),
            forward_samples=forward_samples,
            forward_accuracy=forward_accuracy,
            created_at=created_at,
            train_triggers=train_triggers,
            validation_triggers=validation_triggers,
            test_triggers=test_triggers,
            train_accuracy=train_accuracy,
            max_consecutive_hits=int(row.get("max_consecutive_hits") or 0),
            current_streak_type=current_streak[0],
            current_streak_count=current_streak[1],
            average_trigger_interval=average_interval,
            sample_warning=(
                "INSUFFICIENT_SAMPLE"
                if source_status.upper() == "INSUFFICIENT_SAMPLE"
                else None
            ),
            strategy_name=str(
                (current_prediction or {}).get("strategy_name") or strategy_id
            ),
            strategy_version=str(
                (current_prediction or {}).get("strategy_version")
                or f"v1-{strategy_hash[:12]}"
            ),
            rule_hash=str(
                (current_prediction or {}).get("rule_hash") or strategy_hash
            ),
            target_issue=(
                str(current_prediction["target_issue"])
                if current_prediction
                else current_issue
            ),
            triggered=bool(
                int((current_prediction or {}).get("triggered") or 0)
            ),
            current_prediction=prediction_values,
            prediction_status=str(
                (current_prediction or {}).get("prediction_status") or "WAITING_DATA"
            ),
            prediction_generated_at=(
                str(current_prediction["generated_at"])
                if current_prediction and current_prediction.get("generated_at")
                else None
            ),
            prediction_source=(
                str(current_prediction["source"])
                if current_prediction and current_prediction.get("source")
                else None
            ),
        )

    def list_strategies(self, limit: int = 2000) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 5000))
        with readonly_sqlite(self.database_path) as connection:
            latest = self._latest_run(connection)
            if latest is None:
                return []
            run_id = str(latest["run_id"])
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM strategy_results WHERE run_id=? ORDER BY strategy_id LIMIT ?",
                    (run_id, safe_limit),
                )
            ]
            candidates = {
                str(row["strategy_id"]): dict(row)
                for row in connection.execute("SELECT * FROM candidate_strategies")
            }
            forward_states = {
                str(row["strategy_id"]): dict(row)
                for row in connection.execute("SELECT * FROM forward_strategies")
            }
            forward = self._forward_metrics(connection)
            splits = self._split_metrics(connection, run_id)
            intervals = self._average_intervals(connection, run_id)
            current_issue, current_predictions = self._current_predictions(connection)

        values = []
        for row in rows:
            strategy_id = str(row["strategy_id"])
            candidate = candidates.get(strategy_id, {})
            forward_state = forward_states.get(strategy_id, {})
            forward_samples, forward_accuracy = forward.get(strategy_id, (0, None))
            lifecycle = self._lifecycle(
                row.get("status"),
                candidate.get("status"),
                forward_state.get("status"),
            )
            values.append(
                self._summary(
                    row,
                    lifecycle=lifecycle,
                    forward_samples=forward_samples,
                    forward_accuracy=forward_accuracy,
                    split_metrics=splits.get(strategy_id),
                    average_interval=intervals.get(strategy_id),
                    created_at=str(
                        candidate.get("created_at") or latest.get("completed_at") or ""
                    )
                    or None,
                    current_issue=current_issue,
                    current_prediction=current_predictions.get(strategy_id),
                )
            )
        return values

    def list_candidates(self, limit: int = 100) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 1000))
        values = self.list_strategies(5000)
        return [
            value
            for value in values
            if value.status
            in {"RESEARCH_ONLY", "CANDIDATE", "FORWARD_TEST", "VERIFIED"}
            and value.sample_warning is None
        ][:safe_limit]

    def list_rejected(self, limit: int = 100) -> list[StrategySummary]:
        safe_limit = max(1, min(int(limit), 1000))
        return [
            value
            for value in self.list_strategies(5000)
            if value.status == "REJECTED" or value.sample_warning
        ][:safe_limit]

    @staticmethod
    def _limited_rows(connection, sql: str, parameters: tuple) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(sql, parameters)]

    @classmethod
    def _detail_history(
        cls,
        connection,
        strategy_id: str,
        run_id: str | None,
        scope: str,
        limit: int,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        research_rows: list[dict[str, Any]] = []
        if run_id is not None and scope in {"ALL", "VALIDATION"}:
            split_clause = " AND dataset_split='validation'" if scope == "VALIDATION" else ""
            research_rows = cls._limited_rows(
                connection,
                f"""SELECT * FROM strategy_triggers
                    WHERE run_id=? AND strategy_id=?{split_clause}
                    ORDER BY issue DESC LIMIT ?""",
                (run_id, strategy_id, limit),
            )

        forward_rows: list[dict[str, Any]] = []
        if scope in {"ALL", "FORWARD"}:
            forward_rows = cls._limited_rows(
                connection,
                """SELECT * FROM forward_evaluations
                   WHERE strategy_id=? ORDER BY issue DESC LIMIT ?""",
                (strategy_id, limit),
            )

        prediction_rows: list[dict[str, Any]] = []
        if cls._has_prediction_history(connection) and scope in {"ALL", "FORWARD"}:
            source_clause = " AND h.source='FORWARD'" if scope == "FORWARD" else ""
            prediction_rows = cls._limited_rows(
                connection,
                f"""SELECT h.*, s.actual_result, s.validation_status, s.settled_at
                    FROM strategy_prediction_history h
                    LEFT JOIN strategy_prediction_settlements s
                      ON s.target_issue=h.target_issue
                     AND s.strategy_id=h.strategy_id
                     AND s.strategy_version=h.strategy_version
                     AND s.source=h.source
                    WHERE h.strategy_id=?{source_clause}
                    ORDER BY h.target_issue DESC, h.source LIMIT ?""",
                (strategy_id, limit),
            )

        normalized: dict[tuple[int, str], dict[str, Any]] = {}
        for row in research_rows:
            sample_type = str(row.get("dataset_split") or "").upper()
            normalized[(int(row["issue"]), sample_type)] = {
                "issue": int(row["issue"]),
                "prediction": row.get("predicted_combinations"),
                "actual_result": row.get("actual_combination"),
                "result_status": "PASS" if bool(row.get("hit")) else "FAIL",
                "sample_type": sample_type,
                "generated_at": None,
                "strategy_version": None,
                "rule_hash": None,
            }
        for row in forward_rows:
            triggered = int(row.get("triggered") or 0) == 1
            hit = row.get("hit")
            status = (
                "NOT_TRIGGERED"
                if not triggered
                else "PENDING" if hit is None else "PASS" if bool(hit) else "FAIL"
            )
            normalized[(int(row["issue"]), "FORWARD")] = {
                "issue": int(row["issue"]),
                "prediction": row.get("predicted_combinations"),
                "actual_result": row.get("actual_combination"),
                "result_status": status,
                "sample_type": "FORWARD",
                "generated_at": row.get("evaluated_at"),
                "strategy_version": None,
                "rule_hash": None,
            }
        for row in prediction_rows:
            sample_type = str(row.get("source") or "").upper()
            normalized[(int(row["target_issue"]), sample_type)] = {
                "issue": int(row["target_issue"]),
                "prediction": row.get("current_prediction"),
                "actual_result": row.get("actual_result"),
                "result_status": row.get("validation_status")
                or row.get("prediction_status")
                or "PENDING",
                "sample_type": sample_type,
                "generated_at": row.get("generated_at"),
                "strategy_version": row.get("strategy_version"),
                "rule_hash": row.get("rule_hash"),
            }
        history = tuple(
            sorted(
                normalized.values(),
                key=lambda row: (int(row["issue"]), str(row["sample_type"])),
                reverse=True,
            )[:limit]
        )
        return tuple(research_rows), tuple(forward_rows), history

    @staticmethod
    def _recent_accuracy(rows: list[dict[str, Any]], count: int) -> float | None:
        selected = rows[-count:]
        if not selected:
            return None
        return sum(int(row["hit"]) for row in selected) / len(selected)

    def get(
        self,
        strategy_id: str,
        history_scope: str = "ALL",
        history_limit: int = 100,
    ) -> StrategyDetail | None:
        scope = str(history_scope or "ALL").upper()
        if scope not in {"ALL", "VALIDATION", "FORWARD"}:
            raise ValueError(f"unsupported strategy history scope: {history_scope}")
        safe_limit = max(1, min(int(history_limit), 500))
        with readonly_sqlite(self.database_path) as connection:
            candidate_row = connection.execute(
                "SELECT * FROM candidate_strategies WHERE strategy_id=?", (strategy_id,)
            ).fetchone()
            forward_row = connection.execute(
                "SELECT * FROM forward_strategies WHERE strategy_id=?", (strategy_id,)
            ).fetchone()
            result_row = connection.execute(
                """SELECT r.*, rr.completed_at FROM strategy_results r
                   JOIN research_runs rr ON rr.run_id=r.run_id
                   WHERE r.strategy_id=? ORDER BY rr.completed_at DESC LIMIT 1""",
                (strategy_id,),
            ).fetchone()
            if candidate_row is None and result_row is None:
                return None
            combined = {**dict(candidate_row or {}), **dict(result_row or {})}
            metric_run = str(result_row["run_id"]) if result_row is not None else None
            metric_triggers = (
                []
                if metric_run is None
                else [
                    dict(row)
                    for row in connection.execute(
                        """SELECT issue, dataset_split, hit FROM strategy_triggers
                           WHERE run_id=? AND strategy_id=? ORDER BY issue""",
                        (metric_run, strategy_id),
                    )
                ]
            )
            metric_forward = [
                dict(row)
                for row in connection.execute(
                    """SELECT issue, triggered, hit FROM forward_evaluations
                       WHERE strategy_id=? ORDER BY issue""",
                    (strategy_id,),
                )
            ]
            current_issue, current_predictions = self._current_predictions(connection)
            latest_production_issue = connection.execute(
                "SELECT MAX(issue) FROM production_periods"
            ).fetchone()[0]
            historical_triggers, forward_records, history_records = self._detail_history(
                connection,
                strategy_id,
                metric_run,
                scope,
                safe_limit,
            )
            prediction_history = tuple(
                row
                for row in self._prediction_history(connection, strategy_id)
                if scope == "ALL" or row.get("source") == scope
            )[-safe_limit:]
            invalid_samples = 0
            if self._has_prediction_history(connection):
                invalid_samples = int(
                    connection.execute(
                        """SELECT COUNT(*)
                           FROM strategy_prediction_history h
                           LEFT JOIN strategy_prediction_settlements s
                             ON s.target_issue=h.target_issue
                            AND s.strategy_id=h.strategy_id
                            AND s.strategy_version=h.strategy_version
                            AND s.source=h.source
                           WHERE h.strategy_id=?
                             AND COALESCE(s.validation_status, h.prediction_status)
                                 IN ('INVALID_INPUT','MISSED_FORWARD')""",
                        (strategy_id,),
                    ).fetchone()[0]
                )
            latest_prediction_trigger = None
            if self._has_prediction_history(connection):
                latest_prediction_trigger = connection.execute(
                    """SELECT h.target_issue AS issue, h.current_prediction AS prediction,
                              h.source AS sample_type, h.generated_at,
                              h.strategy_version, h.rule_hash,
                              s.actual_result, s.validation_status AS result_status
                       FROM strategy_prediction_history h
                       LEFT JOIN strategy_prediction_settlements s
                         ON s.target_issue=h.target_issue
                        AND s.strategy_id=h.strategy_id
                        AND s.strategy_version=h.strategy_version
                        AND s.source=h.source
                       WHERE h.strategy_id=? AND h.triggered=1
                       ORDER BY h.target_issue DESC LIMIT 1""",
                    (strategy_id,),
                ).fetchone()
            latest_forward_trigger = connection.execute(
                """SELECT issue, predicted_combinations AS prediction,
                          actual_combination AS actual_result, evaluated_at AS generated_at,
                          CASE WHEN hit=1 THEN 'PASS' WHEN hit=0 THEN 'FAIL'
                               ELSE 'PENDING' END AS result_status
                   FROM forward_evaluations
                   WHERE strategy_id=? AND triggered=1
                   ORDER BY issue DESC LIMIT 1""",
                (strategy_id,),
            ).fetchone()
            latest_research_trigger = (
                None
                if metric_run is None
                else connection.execute(
                    """SELECT issue, predicted_combinations AS prediction,
                              actual_combination AS actual_result,
                              CASE WHEN hit=1 THEN 'PASS' ELSE 'FAIL' END AS result_status,
                              dataset_split AS sample_type
                       FROM strategy_triggers
                       WHERE run_id=? AND strategy_id=?
                       ORDER BY issue DESC LIMIT 1""",
                    (metric_run, strategy_id),
                ).fetchone()
            )

        split_metrics: dict[str, tuple[int, float | None]] = {}
        for split in ("train", "validation", "test"):
            selected = [row for row in metric_triggers if row.get("dataset_split") == split]
            split_metrics[split] = (
                len(selected),
                sum(int(row["hit"]) for row in selected) / len(selected)
                if selected
                else None,
            )
        triggered_forward = [
            row for row in metric_forward if int(row.get("triggered") or 0) == 1
        ]
        decided_forward = [
            row for row in triggered_forward if row.get("hit") is not None
        ]
        forward_accuracy = (
            sum(int(row["hit"]) for row in decided_forward) / len(decided_forward)
            if decided_forward
            else None
        )
        lifecycle = self._lifecycle(
            combined.get("status"),
            candidate_row["status"] if candidate_row is not None else None,
            forward_row["status"] if forward_row is not None else None,
        )
        streak_rows = triggered_forward if triggered_forward else metric_triggers
        summary = self._summary(
            combined,
            lifecycle=lifecycle,
            forward_samples=len(triggered_forward),
            forward_accuracy=forward_accuracy,
            split_metrics=split_metrics,
            average_interval=self._average_interval(streak_rows),
            created_at=str(
                candidate_row["created_at"]
                if candidate_row is not None
                else combined.get("completed_at") or ""
            )
            or None,
            current_streak=self._current_streak(streak_rows),
            current_issue=current_issue,
            current_prediction=current_predictions.get(strategy_id),
        )
        valid_samples = int(combined.get("hit_count") or 0) + int(
            combined.get("miss_count") or 0
        )
        statistics = {
            "matched_issues": valid_samples + invalid_samples,
            "valid_samples": valid_samples,
            "invalid_samples": invalid_samples,
            "hit_count": int(combined.get("hit_count") or 0),
            "miss_count": int(combined.get("miss_count") or 0),
            "accuracy": combined.get("accuracy"),
            "recent_30_accuracy": self._recent_accuracy(metric_triggers, 30),
            "recent_50_accuracy": self._recent_accuracy(metric_triggers, 50),
            "recent_100_accuracy": self._recent_accuracy(metric_triggers, 100),
            "recent_200_accuracy": self._recent_accuracy(metric_triggers, 200),
            "max_consecutive_hits": int(combined.get("max_consecutive_hits") or 0),
            "max_consecutive_misses": int(combined.get("max_consecutive_misses") or 0),
            "current_streak_type": summary.current_streak_type,
            "current_streak_count": summary.current_streak_count,
            "average_trigger_interval": summary.average_trigger_interval,
        }
        latest_trigger = dict(latest_prediction_trigger) if latest_prediction_trigger else None
        if latest_trigger is None and latest_forward_trigger is not None:
            latest_trigger = dict(latest_forward_trigger)
            latest_trigger["sample_type"] = "FORWARD"
            latest_trigger["strategy_version"] = None
            latest_trigger["rule_hash"] = None
        if latest_trigger is None and latest_research_trigger is not None:
            latest_trigger = dict(latest_research_trigger)
            latest_trigger["sample_type"] = str(
                latest_trigger.get("sample_type") or ""
            ).upper()
            latest_trigger["generated_at"] = None
            latest_trigger["strategy_version"] = None
            latest_trigger["rule_hash"] = None
        if latest_trigger is not None:
            comparison_issue = current_issue or latest_production_issue
            latest_trigger["distance"] = (
                max(0, int(comparison_issue) - int(latest_trigger["issue"]))
                if comparison_issue is not None
                else None
            )

        # The official schema stores only aggregate Walk-Forward accuracy.
        return StrategyDetail(
            summary,
            historical_triggers,
            forward_records,
            (),
            prediction_history,
            statistics,
            latest_trigger,
            history_records,
            scope,
            safe_limit,
        )

    def current_status(self) -> dict[str, Any]:
        strategies = self.list_strategies(5000)
        statuses = {status: 0 for status in (
            "READY",
            "NOT_TRIGGERED",
            "WAITING_DATA",
            "INVALID_INPUT",
            "MISSED_FORWARD",
        )}
        distribution: dict[str, int] = {}
        target_issue = None
        for strategy in strategies:
            statuses[strategy.prediction_status] = statuses.get(
                strategy.prediction_status, 0
            ) + 1
            if strategy.target_issue and (
                target_issue is None or int(strategy.target_issue) > int(target_issue)
            ):
                target_issue = strategy.target_issue
            if strategy.prediction_status == "READY":
                for value in strategy.current_prediction or ():
                    distribution[value] = distribution.get(value, 0) + 1
        return {
            "target_issue": target_issue,
            "strategy_total": len(strategies),
            "status_counts": statuses,
            "distribution": distribution,
        }

    def prediction_history(self, strategy_id: str) -> tuple[dict[str, Any], ...]:
        with readonly_sqlite(self.database_path) as connection:
            return self._prediction_history(connection, str(strategy_id))

    def status(self) -> dict:
        runtime = {}
        runtime_error = None
        try:
            runtime = read_json_object(self.runtime_status_path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            runtime_error = f"{type(exc).__name__}: {exc}"
        current = freshness(runtime.get("updated_at"), 120)
        database_error = None
        try:
            with readonly_sqlite(self.database_path) as connection:
                connection.execute("SELECT 1 FROM metadata LIMIT 1").fetchone()
                latest = self._latest_run(connection)
                pool_size = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM candidate_strategies"
                    ).fetchone()[0]
                )
                forward = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM forward_strategies"
                    ).fetchone()[0]
                )
                production_periods = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM production_periods"
                    ).fetchone()[0]
                )
                lifecycle_counts = {state: 0 for state in LIFECYCLE_STATES}
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS total FROM forward_strategies GROUP BY status"
                ):
                    state = str(row["status"]).upper()
                    if state in lifecycle_counts:
                        lifecycle_counts[state] += int(row["total"])
                for row in connection.execute(
                    """SELECT c.status, COUNT(*) AS total
                       FROM candidate_strategies c
                       WHERE NOT EXISTS(
                           SELECT 1 FROM forward_strategies f
                           WHERE f.strategy_id=c.strategy_id
                       ) GROUP BY c.status"""
                ):
                    state = str(row["status"]).upper()
                    if state in lifecycle_counts:
                        lifecycle_counts[state] += int(row["total"])
        except FileNotFoundError:
            latest = None
            pool_size = 0
            forward = 0
            production_periods = 0
            lifecycle_counts = {state: 0 for state in LIFECYCLE_STATES}
            database_status = "OFFLINE"
        except Exception as exc:
            latest = None
            pool_size = 0
            forward = 0
            production_periods = 0
            lifecycle_counts = {state: 0 for state in LIFECYCLE_STATES}
            database_status = "ERROR"
            database_error = f"{type(exc).__name__}: {exc}"
        else:
            database_status = "ONLINE"
        status = "ERROR" if runtime_error else str(runtime.get("status", "OFFLINE"))
        if current["status"] == "STALE" and status == "RUNNING":
            status = "STALE"
        return {
            "status": status,
            "database_status": database_status,
            "latest_research_at": latest.get("completed_at") if latest else None,
            "production_periods": production_periods,
            "candidate_strategies": int(
                latest.get("candidate_count") if latest else 0
            ),
            "candidate_pool_size": pool_size,
            "forward_strategies": forward,
            "forward_test_strategies": lifecycle_counts["FORWARD_TEST"],
            "verified_strategies": lifecycle_counts["VERIFIED"],
            "lifecycle_counts": lifecycle_counts,
            "freshness": current,
            "runtime_error": runtime_error,
            "database_error": database_error,
        }
