from __future__ import annotations

from itertools import combinations, product
from typing import Any, Iterable

from app.constants import COMBINATIONS

from .models import StrategyCondition


COMBINATION_CODES = {
    "BD": "大双",
    "BS": "大单",
    "SD": "小双",
    "SS": "小单",
}
MINIMUM_RANGES = ((8, 10), (10, 12), (11, 15), (12, 16), (13, 17))
LOWEST_DIFFERENCES = (0, 1, 2, 3)
SPREAD_LIMITS = (12, 16, 20, 24)
RANK_RELATIONS: tuple[tuple[str, ...] | None, ...] = (
    None,
    ("大单<大双",),
    ("小单<小双",),
    ("大双<小单",),
)
MAX_CANDIDATES = 100


class StrategyConditionGenerator:
    """Generate a deterministic, bounded set accepted by ``auto_backtest``."""

    def __init__(self, default_limit: int = MAX_CANDIDATES):
        self.default_limit = self._limit(default_limit)

    @staticmethod
    def _limit(value: int) -> int:
        return max(1, min(int(value), MAX_CANDIDATES))

    def generate(
        self,
        limit: int | None = None,
        *,
        specified_pairs: Iterable[tuple[str, str]] | None = None,
    ) -> list[StrategyCondition]:
        cap = self._limit(self.default_limit if limit is None else limit)
        pairs = self._normalize_pairs(specified_pairs)
        families: list[tuple[str, dict[str, Any]]] = [
            ("最低两个组合", {"min_groups": 2}),
            ("最低+第二低", {"min_groups": 2}),
        ]
        families.extend(("指定双组合", {"selected_groups": list(pair)}) for pair in pairs)

        generated: list[StrategyCondition] = []
        seen: set[tuple[tuple[str, str], ...]] = set()

        def add_candidate(
            family: str,
            selection: dict[str, Any],
            minimum: tuple[int, int],
            difference: int,
            spread: int,
            allow_tie: bool,
            relation: tuple[str, ...] | None,
            history: dict[str, Any] | None = None,
        ) -> bool:
            params: dict[str, Any] = {
                **selection,
                "condition_family": family,
                "min_value_min": minimum[0],
                "min_value_max": minimum[1],
                "lowest_two_diff_min": 0,
                "lowest_two_diff_max": difference,
                "max_min_diff_min": 0,
                "max_min_diff_max": spread,
                "allow_tie": allow_tie,
                "continuous_state": "any",
                "continuous_min": 0,
                "interval_min": 0,
                "interval_max": None,
            }
            params.update(history or {})
            if relation:
                params["rank_relations"] = list(relation)
            key = tuple(sorted((name, repr(value)) for name, value in params.items()))
            if key in seen:
                return False
            seen.add(key)
            index = len(generated) + 1
            label = self._label(family, selection, minimum, difference, spread, allow_tie)
            generated.append(StrategyCondition(f"LAB-{index:04d}", label, params))
            return len(generated) >= cap

        # Reserve one slot for every requested selection family before filling
        # the parameter grid, so a bounded scan still covers explicit pairs.
        for family, selection in families:
            if add_candidate(
                family,
                selection,
                MINIMUM_RANGES[0],
                LOWEST_DIFFERENCES[0],
                SPREAD_LIMITS[0],
                False,
                None,
            ):
                return generated
        for history in (
            {"continuous_state": "hit", "continuous_min": 1},
            {"continuous_state": "miss", "continuous_min": 1},
            {"interval_min": 2, "interval_max": 5},
            {"continuous_state": "miss", "continuous_min": 2, "interval_min": 2},
        ):
            if add_candidate(
                families[0][0],
                families[0][1],
                MINIMUM_RANGES[0],
                LOWEST_DIFFERENCES[1],
                SPREAD_LIMITS[1],
                False,
                None,
                history,
            ):
                return generated
        variants = product(
            families,
            MINIMUM_RANGES,
            LOWEST_DIFFERENCES,
            SPREAD_LIMITS,
            (False, True),
            RANK_RELATIONS,
        )
        for (family, selection), minimum, difference, spread, allow_tie, relation in variants:
            if add_candidate(family, selection, minimum, difference, spread, allow_tie, relation):
                break
        return generated

    @staticmethod
    def _normalize_pairs(
        specified_pairs: Iterable[tuple[str, str]] | None,
    ) -> tuple[tuple[str, str], ...]:
        raw_pairs = specified_pairs or combinations(COMBINATION_CODES, 2)
        normalized: list[tuple[str, str]] = []
        for raw_left, raw_right in raw_pairs:
            left = COMBINATION_CODES.get(str(raw_left), str(raw_left))
            right = COMBINATION_CODES.get(str(raw_right), str(raw_right))
            if left not in COMBINATIONS or right not in COMBINATIONS or left == right:
                raise ValueError(f"无效双组合：{raw_left}/{raw_right}")
            pair = (left, right)
            if pair not in normalized and tuple(reversed(pair)) not in normalized:
                normalized.append(pair)
        if not normalized:
            raise ValueError("至少需要一个有效双组合")
        return tuple(normalized)

    @staticmethod
    def _label(
        family: str,
        selection: dict[str, Any],
        minimum: tuple[int, int],
        difference: int,
        spread: int,
        allow_tie: bool,
    ) -> str:
        pair = selection.get("selected_groups")
        target = "/".join(pair) if pair else family
        tie = "允许并列" if allow_tie else "排除并列"
        return f"{target} · 最小{minimum[0]}-{minimum[1]} · 差≤{difference} · 极差≤{spread} · {tie}"


__all__ = ["COMBINATION_CODES", "MAX_CANDIDATES", "StrategyConditionGenerator"]
