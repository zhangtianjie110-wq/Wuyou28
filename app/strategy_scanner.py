from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable, Mapping

from .auto_backtest import (
    prepare_backtest_records,
    run_train_validation_backtest,
    run_walk_forward,
)
from .constants import COMBINATIONS


MIN_VALUE_RANGES = ((8, 10), (10, 12), (11, 15), (12, 16), (13, 17))
DIFF_RANGES = ((0, 0), (0, 1), (0, 2), (0, 3))
RANK_RELATIONS = (None, ("大单<大双",), ("大双<小单",))
MAX_CANDIDATES = 5000


class StrategyConditionGenerator:
    """Generate deterministic, bounded condition parameter dictionaries."""

    def generate(self, max_candidates: int = 500) -> list[dict[str, Any]]:
        limit = max(1, min(int(max_candidates), MAX_CANDIDATES))
        selection_families: list[tuple[str, dict[str, Any]]] = [
            ("最低两个组合", {"min_groups": 2}),
            ("最低+第二低", {"min_groups": 2}),
        ]
        pair_values = tuple(combinations(COMBINATIONS, 2))
        for family in ("最高+最低", "中间两个组合", "指定双组合"):
            selection_families.extend(
                (family, {"selected_groups": list(pair)}) for pair in pair_values
            )

        candidates: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        # Seed every selection family so the default 500-item page always
        # contains representatives of each supported condition shape.
        for family, selection in selection_families:
            seed = {
                **selection,
                "condition_family": family,
                "min_value_min": MIN_VALUE_RANGES[0][0],
                "min_value_max": MIN_VALUE_RANGES[0][1],
                "lowest_two_diff_min": DIFF_RANGES[0][0],
                "lowest_two_diff_max": DIFF_RANGES[0][1],
                "max_min_diff_min": DIFF_RANGES[0][0],
                "max_min_diff_max": DIFF_RANGES[0][1],
                "allow_tie": False,
                "exclude_tied_lowest": True,
                "exclude_insufficient": True,
                "exclude_abnormal": True,
            }
            key = tuple(sorted((str(k), repr(v)) for k, v in seed.items()))
            seen.add(key)
            candidates.append(seed)
        if len(candidates) >= limit:
            return candidates[:limit]
        for family, selection in selection_families:
            for minimum in MIN_VALUE_RANGES:
                for lowest_diff in DIFF_RANGES:
                    for spread in DIFF_RANGES:
                        for allow_tie in (False, True):
                            for rank_relation in RANK_RELATIONS:
                                conditions = {
                                    **selection,
                                    "condition_family": family,
                                    "min_value_min": minimum[0],
                                    "min_value_max": minimum[1],
                                    "lowest_two_diff_min": lowest_diff[0],
                                    "lowest_two_diff_max": lowest_diff[1],
                                    "max_min_diff_min": spread[0],
                                    "max_min_diff_max": spread[1],
                                    "allow_tie": allow_tie,
                                    "exclude_tied_lowest": not allow_tie,
                                    "exclude_insufficient": True,
                                    "exclude_abnormal": True,
                                }
                                if rank_relation is not None:
                                    conditions["rank_relations"] = list(rank_relation)
                                key = tuple(sorted((str(k), repr(v)) for k, v in conditions.items()))
                                if key in seen:
                                    continue
                                seen.add(key)
                                candidates.append(conditions)
                                if len(candidates) >= limit:
                                    return candidates
        return candidates


class StrategyScanner:
    """Run generated conditions through the existing train/validation engine."""

    def scan(
        self,
        records: Iterable[Mapping[str, Any]],
        conditions: Iterable[Mapping[str, Any]],
        *,
        source_type: str = "VIP",
        train_ratio: float = 0.7,
        min_sample_size: int = 30,
        walk_forward: bool = True,
        train_window: int = 200,
        validation_window: int = 50,
        step: int = 50,
    ) -> list[dict[str, Any]]:
        prepared = prepare_backtest_records(records, source_type)
        results: list[dict[str, Any]] = []
        for index, raw_conditions in enumerate(conditions, start=1):
            condition = dict(raw_conditions)
            train_validation = run_train_validation_backtest(
                prepared,
                condition,
                train_ratio=train_ratio,
                source_type=source_type,
                min_sample_size=min_sample_size,
            )
            train = train_validation["train"]
            validation = train_validation["validation"]
            overall = train_validation["overall"]
            forward = None
            if walk_forward:
                forward = run_walk_forward(
                    prepared,
                    condition,
                    train_window=train_window,
                    validation_window=validation_window,
                    step=step,
                    source_type=source_type,
                    min_sample_size=min_sample_size,
                )
            score, stability = self._training_score(train)
            validation_rate = validation.get("hit_rate")
            valid_samples = int(overall.get("valid_samples") or 0)
            if condition.get("exclude_insufficient") and valid_samples < int(min_sample_size):
                status = "样本不足"
            elif validation_rate is None:
                status = "无验证样本"
            elif stability < 0.7:
                status = "训练不稳定"
            else:
                status = "候选"
            results.append(
                {
                    "strategy_id": f"EXP-{index:04d}",
                    "condition_index": index,
                    "conditions": condition,
                    "source_type": source_type,
                    "trigger_count": overall.get("matched_periods", 0),
                    "valid_samples": valid_samples,
                    "hits": overall.get("hits", 0),
                    "hit_rate": overall.get("hit_rate"),
                    "max_consecutive_hits": overall.get("max_consecutive_hits", 0),
                    "max_consecutive_misses": overall.get("max_consecutive_misses", 0),
                    "average_condition_interval": overall.get("average_condition_interval"),
                    "historical_hit_rate": overall.get("hit_rate"),
                    "train_hit_rate": train.get("hit_rate"),
                    "validation_hit_rate": validation_rate,
                    "train": train,
                    "validation": validation,
                    "walk_forward": forward,
                    "score": score,
                    "stability": stability,
                    "status": status,
                    "selection_basis": "training_only",
                }
            )
        results.sort(key=lambda item: (-float(item["score"]), int(item["condition_index"])))
        return results

    @staticmethod
    def _training_score(train: Mapping[str, Any]) -> tuple[float, float]:
        rate = float(train.get("hit_rate") or 0.0)
        samples = int(train.get("valid_samples") or 0)
        misses = int(train.get("max_consecutive_misses") or 0)
        recent = train.get("recent") or {}
        recent_rates = [
            float((recent.get(window) or {}).get("hit_rate"))
            for window in ("30", "50", "100")
            if (recent.get(window) or {}).get("hit_rate") is not None
        ]
        spread = max(recent_rates) - min(recent_rates) if len(recent_rates) > 1 else 0.0
        stability = max(0.0, 1.0 - spread / 100.0)
        sample_factor = min(samples / 100.0, 1.0)
        miss_factor = max(0.0, 1.0 - misses / 20.0)
        score = rate * 0.55 + sample_factor * 20.0 + miss_factor * 15.0 + stability * 10.0
        return round(score, 4), round(stability, 4)


__all__ = ["StrategyConditionGenerator", "StrategyScanner", "MAX_CANDIDATES"]
