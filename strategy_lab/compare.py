from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .freeze import FrozenStrategy, plain_snapshot
from .storage import StrategyLabStorage


@dataclass(frozen=True)
class StrategyComparisonRow:
    freeze_id: str
    strategy_name: str
    strategy_version: str
    condition_params: Mapping[str, Any]
    sample_count: int
    train_hit_rate: float | None
    validation_hit_rate: float | None
    recent_30: float | None
    recent_50: float | None
    recent_100: float | None
    max_consecutive_hits: int
    max_consecutive_misses: int
    average_trigger_interval: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "freeze_id": self.freeze_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "condition_params": plain_snapshot(self.condition_params),
            "sample_count": self.sample_count,
            "train_hit_rate": self.train_hit_rate,
            "validation_hit_rate": self.validation_hit_rate,
            "recent_30": self.recent_30,
            "recent_50": self.recent_50,
            "recent_100": self.recent_100,
            "max_consecutive_hits": self.max_consecutive_hits,
            "max_consecutive_misses": self.max_consecutive_misses,
            "average_trigger_interval": self.average_trigger_interval,
        }


@dataclass(frozen=True)
class ComparisonResult:
    comparison_id: str
    created_at: str
    rows: tuple[StrategyComparisonRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "created_at": self.created_at,
            "rows": [row.to_dict() for row in self.rows],
        }


class StrategyComparator:
    def __init__(self, storage: StrategyLabStorage):
        self.storage = storage

    def compare(self, strategies: Iterable[FrozenStrategy]) -> ComparisonResult:
        items = tuple(strategies)
        if len(items) < 2:
            raise ValueError("至少选择两个冻结策略进行比较")
        rows = tuple(self._row(item) for item in items)
        result = ComparisonResult(
            comparison_id=f"COMPARE-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            rows=rows,
        )
        self.storage.save_comparison(result)
        return result

    @staticmethod
    def _row(strategy: FrozenStrategy) -> StrategyComparisonRow:
        train = strategy.training_result
        validation = strategy.validation_result
        return StrategyComparisonRow(
            freeze_id=strategy.freeze_id,
            strategy_name=strategy.strategy_name,
            strategy_version=strategy.strategy_version,
            condition_params=strategy.condition_params,
            sample_count=int(train.get("valid_samples") or 0)
            + int(validation.get("valid_samples") or 0),
            train_hit_rate=_optional_float(train.get("hit_rate")),
            validation_hit_rate=_optional_float(validation.get("hit_rate")),
            recent_30=_optional_float(validation.get("recent_30")),
            recent_50=_optional_float(validation.get("recent_50")),
            recent_100=_optional_float(validation.get("recent_100")),
            max_consecutive_hits=max(
                int(train.get("max_consecutive_hits") or 0),
                int(validation.get("max_consecutive_hits") or 0),
            ),
            max_consecutive_misses=max(
                int(train.get("max_consecutive_misses") or 0),
                int(validation.get("max_consecutive_misses") or 0),
            ),
            average_trigger_interval=_optional_float(
                validation.get("average_trigger_interval")
                if validation.get("average_trigger_interval") is not None
                else train.get("average_trigger_interval")
            ),
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


__all__ = ["ComparisonResult", "StrategyComparator", "StrategyComparisonRow"]
