from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.auto_backtest import (
    prepare_backtest_records,
    run_condition_backtest,
    run_train_validation_backtest,
    run_walk_forward,
)

from .models import EvaluationMetrics, StrategyCondition, WalkForwardWindow


class StrategyEvaluator:
    """Adapter that delegates all hit calculations to ``app.auto_backtest``."""

    @staticmethod
    def _optional_history_filter(params: Mapping[str, Any]):
        requested_state = str(params.get("continuous_state") or "any").lower()
        minimum_streak = max(0, int(params.get("continuous_min") or 0))
        minimum_interval = max(0, int(params.get("interval_min") or 0))
        maximum_interval_raw = params.get("interval_max")
        maximum_interval = (
            None if maximum_interval_raw in (None, "") else max(0, int(maximum_interval_raw))
        )

        def check(row: dict[str, Any]) -> tuple[bool, str]:
            if requested_state == "any" and not minimum_streak and not minimum_interval and maximum_interval is None:
                return True, ""
            raw = row.get("raw") or {}
            state = str(raw.get("previous_state") or raw.get("continuous_state") or "").lower()
            streak = raw.get("previous_streak", raw.get("continuous_count"))
            interval = raw.get("trigger_interval", raw.get("interval"))
            if requested_state != "any" and state != requested_state:
                return False, "前序连续状态不满足"
            if minimum_streak:
                if streak is None or int(streak) < minimum_streak:
                    return False, "前序连续次数不满足"
            if minimum_interval or maximum_interval is not None:
                if interval is None:
                    return False, "缺少历史触发间隔"
                numeric_interval = int(interval)
                if numeric_interval < minimum_interval:
                    return False, "触发间隔小于下限"
                if maximum_interval is not None and numeric_interval > maximum_interval:
                    return False, "触发间隔大于上限"
            return True, ""

        return check

    @staticmethod
    def _history_constraints_active(params: Mapping[str, Any]) -> bool:
        return (
            str(params.get("continuous_state") or "any").lower() != "any"
            or int(params.get("continuous_min") or 0) > 0
            or int(params.get("interval_min") or 0) > 0
            or params.get("interval_max") not in (None, "")
        )

    def _enrich_history_features(
        self,
        records: Iterable[Mapping[str, Any]],
        condition: StrategyCondition,
    ) -> list[dict[str, Any]]:
        """Derive state from completed earlier triggers, never the current row."""

        rows = prepare_backtest_records(records, condition.data_source)
        if not self._history_constraints_active(condition.params):
            return rows
        base_params = dict(condition.params)
        for key in ("continuous_state", "continuous_min", "interval_min", "interval_max"):
            base_params.pop(key, None)
        baseline = run_condition_backtest(
            rows,
            base_params,
            source_type=condition.data_source,
            min_sample_size=1,
        )
        trigger_by_issue = {
            str(detail.get("issue_no") or ""): detail
            for detail in baseline.get("details") or ()
        }
        previous_state = ""
        previous_streak = 0
        last_trigger_index: int | None = None
        enriched: list[dict[str, Any]] = []
        for index, source in enumerate(rows):
            row = dict(source)
            row["previous_state"] = previous_state
            row["previous_streak"] = previous_streak
            row["trigger_interval"] = (
                None if last_trigger_index is None else index - last_trigger_index
            )
            enriched.append(row)
            # Update only after the feature row has been observed.  The
            # current draw can therefore affect future rows, never itself.
            detail = trigger_by_issue.get(str(row.get("issue_no") or ""))
            if detail is None or detail.get("hit") is None:
                continue
            state = "hit" if bool(detail["hit"]) else "miss"
            previous_streak = previous_streak + 1 if state == previous_state else 1
            previous_state = state
            last_trigger_index = index
        return enriched

    def evaluate(
        self,
        records: Iterable[Mapping[str, Any]],
        condition: StrategyCondition,
        *,
        min_sample_size: int = 30,
    ) -> EvaluationMetrics:
        prepared = self._enrich_history_features(records, condition)
        raw = run_condition_backtest(
            prepared,
            condition.params,
            source_type=condition.data_source,
            min_sample_size=min_sample_size,
            extra_conditions=(self._optional_history_filter(condition.params),),
        )
        return self.normalize(raw)

    def evaluate_train_validation(
        self,
        records: Iterable[Mapping[str, Any]],
        condition: StrategyCondition,
        *,
        train_ratio: float = 0.7,
        min_sample_size: int = 30,
    ) -> tuple[EvaluationMetrics, EvaluationMetrics, EvaluationMetrics]:
        prepared = self._enrich_history_features(records, condition)
        raw = run_train_validation_backtest(
            prepared,
            condition.params,
            train_ratio=train_ratio,
            source_type=condition.data_source,
            min_sample_size=min_sample_size,
            extra_conditions=(self._optional_history_filter(condition.params),),
        )
        return self.normalize(raw["train"]), self.normalize(raw["validation"]), self.normalize(raw["overall"])

    def walk_forward(
        self,
        records: Iterable[Mapping[str, Any]],
        condition: StrategyCondition,
        *,
        train_window: int = 200,
        validation_window: int = 50,
        step: int = 50,
        min_sample_size: int = 30,
    ) -> tuple[WalkForwardWindow, ...]:
        prepared = self._enrich_history_features(records, condition)
        raw = run_walk_forward(
            prepared,
            condition.params,
            train_window=train_window,
            validation_window=validation_window,
            step=step,
            source_type=condition.data_source,
            min_sample_size=min_sample_size,
            extra_conditions=(self._optional_history_filter(condition.params),),
        )
        return tuple(
            WalkForwardWindow(
                index=int(window["window_index"]),
                train_issue_range=tuple(window["train_issue_range"]),
                validation_issue_range=tuple(window["validation_issue_range"]),
                train=self.normalize(window["train"]),
                validation=self.normalize(window["validation"]),
            )
            for window in raw["windows"]
        )

    @staticmethod
    def normalize(raw: Mapping[str, Any]) -> EvaluationMetrics:
        recent = raw.get("recent") or {}

        def recent_rate(window: str) -> float | None:
            value = (recent.get(window) or {}).get("hit_rate")
            return None if value is None else float(value)

        return EvaluationMetrics(
            total_samples=int(raw.get("total_periods") or 0),
            trigger_count=int(raw.get("matched_periods") or 0),
            valid_samples=int(raw.get("valid_samples") or 0),
            hit_count=int(raw.get("hits") or 0),
            hit_rate=None if raw.get("hit_rate") is None else float(raw["hit_rate"]),
            recent_30=recent_rate("30"),
            recent_50=recent_rate("50"),
            recent_100=recent_rate("100"),
            max_consecutive_hits=int(raw.get("max_consecutive_hits") or 0),
            max_consecutive_misses=int(raw.get("max_consecutive_misses") or 0),
            average_trigger_interval=(
                None
                if raw.get("average_condition_interval") is None
                else float(raw["average_condition_interval"])
            ),
            details=tuple(dict(item) for item in raw.get("details") or ()),
        )


__all__ = ["StrategyEvaluator"]
