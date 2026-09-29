from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from itertools import combinations, product
from time import perf_counter
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.auto_backtest import prepare_backtest_records, split_train_validation

from .conditions import COMBINATION_CODES, MINIMUM_RANGES, RANK_RELATIONS
from .engine import StrategyLabEngine
from .models import CandidateResult, ExperimentResult, StrategyCondition
from .storage import StrategyLabStorage


SUPPORTED_SEARCH_LIMITS = (50, 100, 200)


@dataclass(frozen=True)
class SearchSpace:
    minimum_ranges: tuple[tuple[int, int], ...] = MINIMUM_RANGES
    lowest_difference_ranges: tuple[tuple[int, int], ...] = (
        (0, 0),
        (0, 1),
        (0, 2),
        (0, 3),
    )
    spread_ranges: tuple[tuple[int, int], ...] = (
        (0, 12),
        (0, 16),
        (0, 20),
        (0, 24),
    )
    rank_relations: tuple[tuple[str, ...] | None, ...] = RANK_RELATIONS
    allow_ties: tuple[bool, ...] = (False, True)
    trigger_intervals: tuple[tuple[int, int | None], ...] = (
        (0, None),
        (2, 5),
        (5, 10),
    )
    combination_pairs: tuple[tuple[str, str], ...] = tuple(
        combinations(COMBINATION_CODES, 2)
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchConfig:
    max_candidates: int = 100
    data_source: str = "VIP"
    cache_namespace: str | None = None
    train_ratio: float = 0.7
    min_sample_size: int = 30
    train_window: int = 200
    validation_window: int = 50
    step: int = 50

    def __post_init__(self) -> None:
        if self.max_candidates not in SUPPORTED_SEARCH_LIMITS:
            raise ValueError("搜索数量仅支持 50、100 或 200")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    search_id: str
    experiment: ExperimentResult
    parameter_count: int
    cache_hits: int
    evaluated_count: int
    runtime_seconds: float
    result_summary: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_id": self.search_id,
            "parameter_count": self.parameter_count,
            "cache_hits": self.cache_hits,
            "evaluated_count": self.evaluated_count,
            "runtime_seconds": self.runtime_seconds,
            "result_summary": dict(self.result_summary),
            "experiment": self.experiment.to_dict(),
        }


class StrategySearchEngine:
    """Generate, deduplicate and cache bounded strategy experiments."""

    def __init__(
        self,
        storage: StrategyLabStorage,
        engine: StrategyLabEngine | None = None,
    ):
        self.storage = storage
        self.engine = engine or StrategyLabEngine()

    def generate_conditions(
        self,
        space: SearchSpace | None = None,
        *,
        limit: int = 100,
    ) -> tuple[StrategyCondition, ...]:
        if limit not in SUPPORTED_SEARCH_LIMITS:
            raise ValueError("搜索数量仅支持 50、100 或 200")
        current = space or SearchSpace()
        seen: set[str] = set()
        conditions: list[StrategyCondition] = []
        variants = product(
            current.combination_pairs,
            current.minimum_ranges,
            current.lowest_difference_ranges,
            current.spread_ranges,
            current.rank_relations,
            current.allow_ties,
            current.trigger_intervals,
        )
        for pair_codes, minimum, difference, spread, relation, allow_tie, interval in variants:
            pair = [COMBINATION_CODES.get(code, code) for code in pair_codes]
            params: dict[str, Any] = {
                "condition_family": "自动搜索双组合",
                "selected_groups": pair,
                "min_value_min": minimum[0],
                "min_value_max": minimum[1],
                "lowest_two_diff_min": difference[0],
                "lowest_two_diff_max": difference[1],
                "max_min_diff_min": spread[0],
                "max_min_diff_max": spread[1],
                "allow_tie": allow_tie,
                "interval_min": interval[0],
                "interval_max": interval[1],
                "continuous_state": "any",
                "continuous_min": 0,
            }
            if relation:
                params["rank_relations"] = list(relation)
            key = self.parameter_hash(params)
            if key in seen:
                continue
            seen.add(key)
            index = len(conditions) + 1
            name = (
                f"{'/'.join(pair)} · 最小{minimum[0]}-{minimum[1]} · "
                f"双差{difference[0]}-{difference[1]} · 极差{spread[0]}-{spread[1]}"
            )
            conditions.append(
                StrategyCondition(f"SEARCH-{index:04d}", name, params)
            )
            if len(conditions) >= limit:
                break
        return tuple(conditions)

    def search(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        config: SearchConfig | None = None,
        space: SearchSpace | None = None,
    ) -> SearchResult:
        active = config or SearchConfig()
        cache_source = active.cache_namespace or active.data_source
        started = perf_counter()
        conditions = self.generate_conditions(space, limit=active.max_candidates)
        cached: list[CandidateResult] = []
        pending: list[StrategyCondition] = []
        for condition in conditions:
            result = self.storage.find_cached_candidate(
                condition.params, cache_source
            )
            if result is None:
                pending.append(
                    StrategyCondition(
                        condition.condition_id,
                        condition.name,
                        condition.params,
                        active.data_source,
                    )
                )
            else:
                cached.append(
                    replace(
                        result,
                        condition=StrategyCondition(
                            condition.condition_id,
                            condition.name,
                            condition.params,
                            active.data_source,
                        ),
                    )
                )

        evaluated: list[CandidateResult] = []
        issue_ranges: tuple[tuple[str, str] | None, tuple[str, str] | None] = (None, None)
        rows = list(records)
        for start in range(0, len(pending), 100):
            batch = pending[start : start + 100]
            result = self.engine.scan(
                rows,
                batch,
                data_source=active.data_source,
                train_ratio=active.train_ratio,
                min_sample_size=active.min_sample_size,
                train_window=active.train_window,
                validation_window=active.validation_window,
                step=active.step,
            )
            evaluated.extend(result.candidates)
            issue_ranges = (result.train_issue_range, result.validation_issue_range)
        if issue_ranges == (None, None):
            prepared = prepare_backtest_records(rows, active.data_source)
            train, validation = split_train_validation(
                prepared, active.train_ratio, source_type=active.data_source
            )
            issue_ranges = (self._range(train), self._range(validation))

        combined = cached + evaluated
        combined.sort(key=lambda item: (-item.score, self.parameter_hash(item.condition.params)))
        search_id = f"SEARCH-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        experiment = ExperimentResult(
            experiment_id=search_id,
            data_source=cache_source,
            candidates=tuple(combined),
            created_at=created_at,
            train_ratio=active.train_ratio,
            train_issue_range=issue_ranges[0],
            validation_issue_range=issue_ranges[1],
        )
        runtime = round(perf_counter() - started, 6)
        summary = {
            "candidate_count": len(combined),
            "cache_hits": len(cached),
            "evaluated_count": len(evaluated),
            "statuses": self._status_counts(combined),
        }
        self.storage.save_experiment(experiment)
        self.storage.save_search(
            search_id,
            active.to_dict(),
            [dict(condition.params) for condition in conditions],
            runtime,
            summary,
            created_at,
        )
        return SearchResult(
            search_id=search_id,
            experiment=experiment,
            parameter_count=len(conditions),
            cache_hits=len(cached),
            evaluated_count=len(evaluated),
            runtime_seconds=runtime,
            result_summary=summary,
        )

    @staticmethod
    def parameter_hash(params: Mapping[str, Any]) -> str:
        payload = json.dumps(
            dict(params), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _range(rows: list[Mapping[str, Any]]) -> tuple[str, str] | None:
        if not rows:
            return None
        return str(rows[0].get("issue_no") or ""), str(rows[-1].get("issue_no") or "")

    @staticmethod
    def _status_counts(candidates: list[CandidateResult]) -> dict[str, int]:
        result: dict[str, int] = {}
        for candidate in candidates:
            result[candidate.status] = result.get(candidate.status, 0) + 1
        return result


__all__ = [
    "SUPPORTED_SEARCH_LIMITS",
    "SearchConfig",
    "SearchResult",
    "SearchSpace",
    "StrategySearchEngine",
]
