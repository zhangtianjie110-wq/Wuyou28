from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.auto_backtest import prepare_backtest_records, split_train_validation

from .evaluator import StrategyEvaluator
from .models import CandidateResult, ExperimentResult, StrategyCondition


ProgressCallback = Callable[[int, int], None]


class StrategyLabEngine:
    """Scan candidates without using validation data for discovery or ranking."""

    def __init__(self, evaluator: StrategyEvaluator | None = None):
        self.evaluator = evaluator or StrategyEvaluator()

    def scan(
        self,
        records: Iterable[Mapping[str, Any]],
        conditions: Sequence[StrategyCondition],
        *,
        data_source: str = "VIP",
        train_ratio: float = 0.7,
        min_sample_size: int = 30,
        train_window: int = 200,
        validation_window: int = 50,
        step: int = 50,
        progress: ProgressCallback | None = None,
    ) -> ExperimentResult:
        if not conditions:
            raise ValueError("至少需要一个候选条件")
        if len(conditions) > 100:
            raise ValueError("MVP 单次扫描最多允许 100 个候选条件")
        prepared = prepare_backtest_records(records, data_source)
        train_rows, validation_rows = split_train_validation(
            prepared, train_ratio, source_type=data_source
        )
        results: list[CandidateResult] = []
        total = len(conditions)
        for index, condition in enumerate(conditions, start=1):
            if condition.data_source != data_source:
                condition = StrategyCondition(
                    condition.condition_id, condition.name, condition.params, data_source
                )
            train, validation, overall = self.evaluator.evaluate_train_validation(
                prepared,
                condition,
                train_ratio=train_ratio,
                min_sample_size=min_sample_size,
            )
            windows = self.evaluator.walk_forward(
                prepared,
                condition,
                train_window=train_window,
                validation_window=validation_window,
                step=step,
                min_sample_size=min_sample_size,
            )
            score = self.training_score(train)
            results.append(
                CandidateResult(
                    condition=condition,
                    train=train,
                    validation=validation,
                    overall=overall,
                    walk_forward=windows,
                    score=score,
                    status=self._status(train, validation, min_sample_size),
                )
            )
            if progress:
                progress(index, total)
        # Validation metrics are deliberately absent from this ordering key.
        results.sort(key=lambda item: (-item.score, item.condition.condition_id))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        return ExperimentResult(
            experiment_id=f"EXP-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
            data_source=data_source,
            candidates=tuple(results),
            created_at=now,
            train_ratio=min(max(float(train_ratio), 0.1), 0.9),
            train_issue_range=self._issue_range(train_rows),
            validation_issue_range=self._issue_range(validation_rows),
        )

    @staticmethod
    def training_score(metrics) -> float:
        """Conservative score calculated exclusively from training metrics."""

        rate = float(metrics.hit_rate or 0.0)
        sample_factor = min(metrics.valid_samples / 100.0, 1.0)
        miss_factor = max(0.0, 1.0 - metrics.max_consecutive_misses / 20.0)
        recent = [
            value
            for value in (metrics.recent_30, metrics.recent_50, metrics.recent_100)
            if value is not None
        ]
        stability = 1.0
        if len(recent) > 1:
            stability = max(0.0, 1.0 - (max(recent) - min(recent)) / 100.0)
        return round(rate * 0.55 + sample_factor * 20 + miss_factor * 15 + stability * 10, 4)

    @staticmethod
    def _status(train, validation, minimum: int) -> str:
        if train.valid_samples < minimum:
            return "训练样本不足"
        if validation.valid_samples == 0:
            return "无验证样本"
        if train.hit_rate is None or validation.hit_rate is None:
            return "待验证"
        if abs(train.hit_rate - validation.hit_rate) > 20:
            return "波动较大"
        return "候选"

    @staticmethod
    def _issue_range(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str] | None:
        if not rows:
            return None
        return str(rows[0].get("issue_no") or ""), str(rows[-1].get("issue_no") or "")


__all__ = ["StrategyLabEngine"]
