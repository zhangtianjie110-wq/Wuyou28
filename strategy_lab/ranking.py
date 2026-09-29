from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from .filter import FilterConfig, FilterDecision, StrategyFilterEngine
from .models import CandidateResult


@dataclass(frozen=True)
class RankingWeights:
    validation_hit_rate: float = 0.45
    valid_samples: float = 0.20
    walk_forward_stability: float = 0.20
    consecutive_miss_control: float = 0.15

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class RankingEntry:
    rank: int
    candidate: CandidateResult
    filter_decision: FilterDecision
    ranking_score: float
    status: str

    def to_dict(self) -> dict:
        overall = self.candidate.overall
        return {
            "rank": self.rank,
            "condition_id": self.candidate.condition.condition_id,
            "strategy_name": self.candidate.condition.name,
            "condition_params": dict(self.candidate.condition.params),
            "trigger_count": overall.trigger_count,
            "valid_samples": overall.valid_samples,
            "train_hit_rate": self.candidate.train.hit_rate,
            "validation_hit_rate": self.candidate.validation.hit_rate,
            "recent_30": overall.recent_30,
            "recent_50": overall.recent_50,
            "recent_100": overall.recent_100,
            "max_consecutive_hits": overall.max_consecutive_hits,
            "max_consecutive_misses": overall.max_consecutive_misses,
            "average_trigger_interval": overall.average_trigger_interval,
            "walk_forward_pass_ratio": self.filter_decision.walk_forward_pass_ratio,
            "ranking_score": self.ranking_score,
            "status": self.status,
            "filter_result": self.filter_decision.result,
            "elimination_reasons": list(self.filter_decision.reasons),
        }


class StrategyRanking:
    """Rank historical candidates without producing predictive conclusions."""

    def __init__(
        self,
        weights: RankingWeights | None = None,
        filter_config: FilterConfig | None = None,
    ):
        self.weights = weights or RankingWeights()
        self.filter_config = filter_config or FilterConfig()

    def rank(
        self,
        candidates: Iterable[CandidateResult],
        decisions: Iterable[FilterDecision] | None = None,
    ) -> tuple[RankingEntry, ...]:
        candidate_list = tuple(candidates)
        decision_list = (
            tuple(decisions)
            if decisions is not None
            else StrategyFilterEngine(self.filter_config).filter(candidate_list)
        )
        decision_by_id: Mapping[str, FilterDecision] = {
            item.candidate.condition.condition_id: item for item in decision_list
        }
        provisional: list[tuple[CandidateResult, FilterDecision, float, str]] = []
        for candidate in candidate_list:
            decision = decision_by_id.get(candidate.condition.condition_id)
            if decision is None:
                raise ValueError(f"缺少筛选结果：{candidate.condition.condition_id}")
            status = self._status(candidate, decision)
            provisional.append((candidate, decision, self._score(candidate, decision), status))
        priority = {"候选": 0, "观察": 1, "淘汰": 2}
        provisional.sort(
            key=lambda item: (
                priority[item[3]],
                -item[2],
                item[0].condition.condition_id,
            )
        )
        return tuple(
            RankingEntry(index, candidate, decision, score, status)
            for index, (candidate, decision, score, status) in enumerate(provisional, start=1)
        )

    def _score(self, candidate: CandidateResult, decision: FilterDecision) -> float:
        weights = self.weights
        validation = float(candidate.validation.hit_rate or 0.0)
        sample_score = min(candidate.overall.valid_samples / 200.0, 1.0) * 100.0
        walk_forward_score = decision.walk_forward_pass_ratio * 100.0
        miss_score = max(
            0.0,
            1.0 - candidate.overall.max_consecutive_misses / 30.0,
        ) * 100.0
        return round(
            validation * weights.validation_hit_rate
            + sample_score * weights.valid_samples
            + walk_forward_score * weights.walk_forward_stability
            + miss_score * weights.consecutive_miss_control,
            4,
        )

    def _status(self, candidate: CandidateResult, decision: FilterDecision) -> str:
        if decision.passed:
            return "候选"
        train_rate = candidate.train.hit_rate
        if (
            candidate.overall.trigger_count >= self.filter_config.min_trigger_count
            and train_rate is not None
            and train_rate >= self.filter_config.min_train_hit_rate
        ):
            return "观察"
        return "淘汰"


__all__ = ["RankingEntry", "RankingWeights", "StrategyRanking"]
