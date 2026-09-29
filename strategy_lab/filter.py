from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .models import CandidateResult


@dataclass(frozen=True)
class FilterConfig:
    min_trigger_count: int = 50
    min_train_hit_rate: float = 60.0
    min_validation_hit_rate: float = 58.0
    max_consecutive_misses: int = 15
    min_walk_forward_pass_ratio: float = 0.5
    walk_forward_min_hit_rate: float | None = None

    def to_dict(self) -> dict[str, int | float | None]:
        return asdict(self)


@dataclass(frozen=True)
class FilterDecision:
    candidate: CandidateResult
    passed: bool
    reasons: tuple[str, ...]
    walk_forward_passed: int
    walk_forward_total: int
    walk_forward_pass_ratio: float

    @property
    def result(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict:
        return {
            "condition_id": self.candidate.condition.condition_id,
            "strategy_name": self.candidate.condition.name,
            "result": self.result,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "walk_forward_passed": self.walk_forward_passed,
            "walk_forward_total": self.walk_forward_total,
            "walk_forward_pass_ratio": self.walk_forward_pass_ratio,
        }


class StrategyFilterEngine:
    """Apply configurable historical thresholds without changing scan order."""

    def __init__(self, config: FilterConfig | None = None):
        self.config = config or FilterConfig()

    def evaluate(self, candidate: CandidateResult) -> FilterDecision:
        config = self.config
        reasons: list[str] = []
        if candidate.overall.trigger_count < config.min_trigger_count:
            reasons.append(
                f"触发次数不足：{candidate.overall.trigger_count} < {config.min_trigger_count}"
            )
        self._rate_reason(
            reasons,
            "训练命中率不足",
            candidate.train.hit_rate,
            config.min_train_hit_rate,
        )
        self._rate_reason(
            reasons,
            "验证命中率不足",
            candidate.validation.hit_rate,
            config.min_validation_hit_rate,
        )
        maximum_misses = max(
            candidate.train.max_consecutive_misses,
            candidate.validation.max_consecutive_misses,
        )
        if maximum_misses > config.max_consecutive_misses:
            reasons.append(
                f"最大连续未命中超限：{maximum_misses} > {config.max_consecutive_misses}"
            )

        window_rate = (
            config.min_validation_hit_rate
            if config.walk_forward_min_hit_rate is None
            else config.walk_forward_min_hit_rate
        )
        total_windows = len(candidate.walk_forward)
        passed_windows = sum(
            1
            for window in candidate.walk_forward
            if window.validation.valid_samples > 0
            and window.validation.hit_rate is not None
            and window.validation.hit_rate >= window_rate
        )
        pass_ratio = passed_windows / total_windows if total_windows else 0.0
        if pass_ratio < config.min_walk_forward_pass_ratio:
            reasons.append(
                "Walk Forward通过率不足："
                f"{pass_ratio * 100:.2f}% < {config.min_walk_forward_pass_ratio * 100:.2f}%"
            )
        return FilterDecision(
            candidate=candidate,
            passed=not reasons,
            reasons=tuple(reasons),
            walk_forward_passed=passed_windows,
            walk_forward_total=total_windows,
            walk_forward_pass_ratio=round(pass_ratio, 4),
        )

    def filter(self, candidates: Iterable[CandidateResult]) -> tuple[FilterDecision, ...]:
        return tuple(self.evaluate(candidate) for candidate in candidates)

    @staticmethod
    def _rate_reason(
        reasons: list[str],
        label: str,
        value: float | None,
        minimum: float,
    ) -> None:
        if value is None:
            reasons.append(f"{label}：无有效样本")
        elif value < minimum:
            reasons.append(f"{label}：{value:.2f}% < {minimum:.2f}%")


__all__ = ["FilterConfig", "FilterDecision", "StrategyFilterEngine"]
