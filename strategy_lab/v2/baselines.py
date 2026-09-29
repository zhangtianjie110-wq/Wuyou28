"""Simple descriptive baselines; no strategy ranking or guarantees."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app.stats import normalize_result

from ..models import EvaluationMetrics, StrategyCondition
from ..evaluator import StrategyEvaluator


@dataclass(frozen=True)
class BaselineResult:
    name: str
    sample_count: int
    hit_count: int
    hit_rate: float | None
    candidate_hit_rate: float | None = None
    difference: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "sample_count": self.sample_count, "hit_count": self.hit_count, "hit_rate": self.hit_rate, "candidate_hit_rate": self.candidate_hit_rate, "difference": self.difference}


def _outcomes(records: Iterable[Mapping[str, Any]]) -> list[str]:
    return [value for row in records if (value := normalize_result(row.get("actual_combo") or row.get("actual_result")))]


def evaluate_baselines(records: Iterable[Mapping[str, Any]]) -> tuple[BaselineResult, ...]:
    outcomes = _outcomes(records)
    count = len(outcomes)
    majority = Counter(outcomes).most_common(1)[0][0] if outcomes else None
    majority_hits = sum(item == majority for item in outcomes) if majority else 0
    uniform_rate = 100.0 / 4 if outcomes else None
    return (
        BaselineResult("majority_actual", count, majority_hits, round(majority_hits / count * 100, 2) if count else None),
        BaselineResult("uniform_4_way", count, round(count / 4), uniform_rate),
    )


def compare_to_baselines(records: Iterable[Mapping[str, Any]], condition: StrategyCondition, *, evaluator: StrategyEvaluator | None = None, min_sample_size: int = 1) -> tuple[BaselineResult, ...]:
    rows = list(records)
    metrics = (evaluator or StrategyEvaluator()).evaluate(rows, condition, min_sample_size=min_sample_size)
    return tuple(BaselineResult(item.name, item.sample_count, item.hit_count, item.hit_rate, metrics.hit_rate, None if item.hit_rate is None or metrics.hit_rate is None else round(metrics.hit_rate - item.hit_rate, 2)) for item in evaluate_baselines(rows))


compare_baseline = compare_to_baselines
baseline_compare = compare_to_baselines

__all__ = ["BaselineResult", "evaluate_baselines", "compare_to_baselines", "compare_baseline", "baseline_compare"]
