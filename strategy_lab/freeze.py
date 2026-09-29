from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from .filter import FilterDecision
from .models import CandidateResult
from .storage import StrategyLabStorage


FREEZE_STATUSES = ("ACTIVE", "WATCH", "DISABLED")


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _immutable_copy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    copied = json.loads(json.dumps(dict(value), ensure_ascii=False))
    return _freeze_value(copied)


def plain_snapshot(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): plain_snapshot(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain_snapshot(item) for item in value]
    return value


@dataclass(frozen=True)
class FrozenStrategy:
    freeze_id: str
    strategy_name: str
    strategy_version: str
    condition_id: str
    condition_params: Mapping[str, Any]
    training_result: Mapping[str, Any]
    validation_result: Mapping[str, Any]
    created_at: str
    status: str = "ACTIVE"
    frozen_at_issue: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "freeze_id": self.freeze_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "condition_id": self.condition_id,
            "condition_params": plain_snapshot(self.condition_params),
            "training_result": plain_snapshot(self.training_result),
            "validation_result": plain_snapshot(self.validation_result),
            "created_at": self.created_at,
            "status": self.status,
            "frozen_at_issue": self.frozen_at_issue,
        }


class StrategyFreezeService:
    def __init__(self, storage: StrategyLabStorage):
        self.storage = storage

    def freeze(
        self,
        candidate: CandidateResult,
        decision: FilterDecision,
        *,
        strategy_name: str | None = None,
        strategy_version: str = "1.0.0",
        status: str = "ACTIVE",
    ) -> FrozenStrategy:
        if not decision.passed:
            raise ValueError("只有通过自动筛选的策略可以冻结")
        if decision.candidate.condition.condition_id != candidate.condition.condition_id:
            raise ValueError("筛选结果与策略不匹配")
        if status not in FREEZE_STATUSES:
            raise ValueError(f"无效冻结状态：{status}")
        name = (strategy_name or candidate.condition.name).strip()
        version = strategy_version.strip()
        if not name or not version:
            raise ValueError("策略名称和版本不能为空")
        frozen = FrozenStrategy(
            freeze_id=f"FREEZE-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
            strategy_name=name,
            strategy_version=version,
            condition_id=candidate.condition.condition_id,
            condition_params=_immutable_copy(candidate.condition.params),
            training_result=_immutable_copy(candidate.train.to_dict()),
            validation_result=_immutable_copy(candidate.validation.to_dict()),
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            status=status,
            frozen_at_issue=self._last_issue(candidate),
        )
        self.storage.save_frozen_strategy(frozen)
        return frozen

    def list(self) -> tuple[FrozenStrategy, ...]:
        return tuple(self._from_record(item) for item in self.storage.list_frozen_strategies())

    @staticmethod
    def _last_issue(candidate: CandidateResult) -> str:
        issues = [
            str(item.get("issue_no") or "")
            for item in candidate.overall.details
            if item.get("issue_no")
        ]
        return max(issues) if issues else ""

    @staticmethod
    def _from_record(item: Mapping[str, Any]) -> FrozenStrategy:
        return FrozenStrategy(
            freeze_id=str(item["freeze_id"]),
            strategy_name=str(item["strategy_name"]),
            strategy_version=str(item["strategy_version"]),
            condition_id=str(item["condition_id"]),
            condition_params=_immutable_copy(item["condition_params"]),
            training_result=_immutable_copy(item["training_result"]),
            validation_result=_immutable_copy(item["validation_result"]),
            created_at=str(item["created_at"]),
            status=str(item["status"]),
            frozen_at_issue=str(item.get("frozen_at_issue") or ""),
        )


__all__ = [
    "FREEZE_STATUSES",
    "FrozenStrategy",
    "StrategyFreezeService",
    "plain_snapshot",
]
