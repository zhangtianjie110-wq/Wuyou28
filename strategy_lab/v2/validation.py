"""Time-ordered three-way validation for reproducible experiments.

The final test slice is deliberately represented separately from the search
input.  Callers can therefore pass only ``train + validation`` to discovery
and retain ``test`` for a final, non-selection report.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app.auto_backtest import prepare_backtest_records

from ..evaluator import StrategyEvaluator
from ..models import EvaluationMetrics, StrategyCondition


@dataclass(frozen=True)
class ValidationConfig:
    train_ratio: float = 0.70
    validation_ratio: float = 0.20
    test_ratio: float = 0.10

    def __post_init__(self) -> None:
        values = (self.train_ratio, self.validation_ratio, self.test_ratio)
        if any(value <= 0 for value in values):
            raise ValueError("三段比例必须大于 0")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("训练、验证、测试比例之和必须为 1")

    def to_dict(self) -> dict[str, float]:
        return {
            "train_ratio": self.train_ratio,
            "validation_ratio": self.validation_ratio,
            "test_ratio": self.test_ratio,
        }


@dataclass(frozen=True)
class ValidationSplit:
    train: tuple[Mapping[str, Any], ...]
    validation: tuple[Mapping[str, Any], ...]
    test: tuple[Mapping[str, Any], ...]
    train_range: tuple[str, str] | None
    validation_range: tuple[str, str] | None
    test_range: tuple[str, str] | None

    @property
    def discovery(self) -> tuple[Mapping[str, Any], ...]:
        return self.train + self.validation


@dataclass(frozen=True)
class ValidationResult:
    condition_id: str
    train: EvaluationMetrics
    validation: EvaluationMetrics
    test: EvaluationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "test": self.test.to_dict(),
            "selection_basis": "training_validation_only",
        }


def _range(rows: tuple[Mapping[str, Any], ...]) -> tuple[str, str] | None:
    return None if not rows else (str(rows[0].get("issue_no") or ""), str(rows[-1].get("issue_no") or ""))


def split_time_series(
    records: Iterable[Mapping[str, Any]],
    config: ValidationConfig | None = None,
    *,
    source_type: str | None = None,
) -> ValidationSplit:
    """Return chronological train/validation/test slices; never shuffles."""
    active = config or ValidationConfig()
    ordered = tuple(prepare_backtest_records(records, source_type))
    count = len(ordered)
    if count < 3:
        raise ValueError("三段验证至少需要 3 条完整历史记录")
    # Boundaries are deterministic and ensure each slice has at least one row.
    train_end = max(1, min(count - 2, round(count * active.train_ratio)))
    validation_end = max(train_end + 1, min(count - 1, round(count * (active.train_ratio + active.validation_ratio))))
    return ValidationSplit(
        train=ordered[:train_end],
        validation=ordered[train_end:validation_end],
        test=ordered[validation_end:],
        train_range=_range(ordered[:train_end]),
        validation_range=_range(ordered[train_end:validation_end]),
        test_range=_range(ordered[validation_end:]),
    )


def evaluate_three_way(
    records: Iterable[Mapping[str, Any]],
    condition: StrategyCondition,
    *,
    config: ValidationConfig | None = None,
    evaluator: StrategyEvaluator | None = None,
    min_sample_size: int = 30,
) -> tuple[ValidationSplit, ValidationResult]:
    """Evaluate one condition on all slices without using test for selection."""
    split = split_time_series(records, config, source_type=condition.data_source)
    engine = evaluator or StrategyEvaluator()
    return split, ValidationResult(
        condition_id=condition.condition_id,
        train=engine.evaluate(split.train, condition, min_sample_size=min_sample_size),
        validation=engine.evaluate(split.validation, condition, min_sample_size=min_sample_size),
        test=engine.evaluate(split.test, condition, min_sample_size=min_sample_size),
    )


# Explicit aliases keep the public API convenient for callers and tests.
three_way_split = split_time_series
validate_three_way = evaluate_three_way

__all__ = [
    "ValidationConfig", "ValidationSplit", "ValidationResult",
    "split_time_series", "three_way_split", "evaluate_three_way", "validate_three_way",
]
