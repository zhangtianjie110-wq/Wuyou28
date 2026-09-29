from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class StrategyCondition:
    """A reproducible strategy candidate and its complete parameters."""

    condition_id: str
    name: str
    params: Mapping[str, Any]
    data_source: str = "VIP"

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "name": self.name,
            "params": dict(self.params),
            "data_source": self.data_source,
        }


@dataclass(frozen=True)
class EvaluationMetrics:
    total_samples: int
    trigger_count: int
    valid_samples: int
    hit_count: int
    hit_rate: float | None
    recent_30: float | None
    recent_50: float | None
    recent_100: float | None
    max_consecutive_hits: int
    max_consecutive_misses: int
    average_trigger_interval: float | None
    details: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["details"] = [dict(item) for item in self.details]
        return value


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    train_issue_range: tuple[str, str]
    validation_issue_range: tuple[str, str]
    train: EvaluationMetrics
    validation: EvaluationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_issue_range": list(self.train_issue_range),
            "validation_issue_range": list(self.validation_issue_range),
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class CandidateResult:
    condition: StrategyCondition
    train: EvaluationMetrics
    validation: EvaluationMetrics
    overall: EvaluationMetrics
    walk_forward: tuple[WalkForwardWindow, ...]
    score: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition.to_dict(),
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "overall": self.overall.to_dict(),
            "walk_forward": [item.to_dict() for item in self.walk_forward],
            "score": self.score,
            "status": self.status,
            "selection_basis": "training_only",
        }


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    data_source: str
    candidates: tuple[CandidateResult, ...]
    created_at: str
    train_ratio: float = 0.7
    train_issue_range: tuple[str, str] | None = None
    validation_issue_range: tuple[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "data_source": self.data_source,
            "created_at": self.created_at,
            "train_ratio": self.train_ratio,
            "train_issue_range": list(self.train_issue_range) if self.train_issue_range else None,
            "validation_issue_range": list(self.validation_issue_range) if self.validation_issue_range else None,
            "selection_basis": "training_only",
            "candidates": [item.to_dict() for item in self.candidates],
        }
