from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.auto_backtest import prepare_backtest_records
from app.stats import issue_sort_key

from .evaluator import StrategyEvaluator
from .freeze import FrozenStrategy
from .models import EvaluationMetrics, StrategyCondition
from .storage import StrategyLabStorage


@dataclass(frozen=True)
class TrackingConfig:
    min_recent_hit_rate: float = 50.0
    max_hit_rate_drop: float = 10.0
    max_consecutive_misses: int = 15

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class TrackingResult:
    tracking_id: str
    freeze_id: str
    tracked_at: str
    new_samples: int
    recent_performance: EvaluationMetrics
    current_status: str
    anomaly: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tracking_id": self.tracking_id,
            "freeze_id": self.freeze_id,
            "tracked_at": self.tracked_at,
            "new_samples": self.new_samples,
            "recent_performance": self.recent_performance.to_dict(),
            "current_status": self.current_status,
            "anomaly": self.anomaly,
            "reasons": list(self.reasons),
        }


class StrategyTracker:
    """Evaluate only post-freeze rows and mark anomalies without deletion."""

    def __init__(
        self,
        storage: StrategyLabStorage,
        evaluator: StrategyEvaluator | None = None,
        config: TrackingConfig | None = None,
    ):
        self.storage = storage
        self.evaluator = evaluator or StrategyEvaluator()
        self.config = config or TrackingConfig()

    def track(
        self,
        frozen: FrozenStrategy,
        records: Iterable[Mapping[str, Any]],
        *,
        data_source: str = "VIP",
    ) -> TrackingResult:
        prepared = prepare_backtest_records(records, data_source)
        if frozen.frozen_at_issue:
            boundary = issue_sort_key(frozen.frozen_at_issue)
            prepared = [
                row
                for row in prepared
                if issue_sort_key(str(row.get("issue_no") or "")) > boundary
            ]
        condition = StrategyCondition(
            frozen.condition_id,
            frozen.strategy_name,
            frozen.condition_params,
            data_source,
        )
        metrics = self.evaluator.evaluate(prepared, condition, min_sample_size=1)
        reasons = self._anomaly_reasons(frozen, metrics)
        anomaly = bool(reasons)
        status = frozen.status
        if anomaly and status != "DISABLED":
            status = "WATCH"
            self.storage.update_frozen_status(frozen.freeze_id, status)
        result = TrackingResult(
            tracking_id=f"TRACK-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
            freeze_id=frozen.freeze_id,
            tracked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            new_samples=metrics.valid_samples,
            recent_performance=metrics,
            current_status=status,
            anomaly=anomaly,
            reasons=tuple(reasons),
        )
        self.storage.save_tracking_result(result, self.config.to_dict())
        return result

    def _anomaly_reasons(
        self,
        frozen: FrozenStrategy,
        metrics: EvaluationMetrics,
    ) -> list[str]:
        if metrics.valid_samples == 0:
            return []
        reasons: list[str] = []
        recent = metrics.recent_30
        if recent is not None and recent < self.config.min_recent_hit_rate:
            reasons.append(
                f"最近表现低于阈值：{recent:.2f}% < {self.config.min_recent_hit_rate:.2f}%"
            )
        baseline = frozen.validation_result.get("hit_rate")
        if baseline is not None and metrics.hit_rate is not None:
            drop = float(baseline) - metrics.hit_rate
            if drop > self.config.max_hit_rate_drop:
                reasons.append(
                    f"相对冻结验证结果下降：{drop:.2f}% > {self.config.max_hit_rate_drop:.2f}%"
                )
        if metrics.max_consecutive_misses > self.config.max_consecutive_misses:
            reasons.append(
                "连续未命中超限："
                f"{metrics.max_consecutive_misses} > {self.config.max_consecutive_misses}"
            )
        return reasons


__all__ = ["StrategyTracker", "TrackingConfig", "TrackingResult"]
