"""Descriptive stability analysis for strategy experiments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..evaluator import StrategyEvaluator
from ..models import EvaluationMetrics, StrategyCondition
from app.auto_backtest import prepare_backtest_records


@dataclass(frozen=True)
class WindowResult:
    index: int
    start_issue: str
    end_issue: str
    metrics: EvaluationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "start_issue": self.start_issue, "end_issue": self.end_issue, "metrics": self.metrics.to_dict()}


@dataclass(frozen=True)
class SensitivityResult:
    parameter: str
    value: Any
    metrics: EvaluationMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"parameter": self.parameter, "value": self.value, "metrics": self.metrics.to_dict()}


@dataclass(frozen=True)
class RobustnessResult:
    windows: tuple[WindowResult, ...]
    sensitivities: tuple[SensitivityResult, ...]
    worst_window_index: int | None
    worst_hit_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [item.to_dict() for item in self.windows],
            "sensitivities": [item.to_dict() for item in self.sensitivities],
            "worst_window_index": self.worst_window_index,
            "worst_hit_rate": self.worst_hit_rate,
        }


def analyze_time_windows(
    records: Sequence[Mapping[str, Any]],
    condition: StrategyCondition,
    *,
    window_size: int = 100,
    step: int = 50,
    evaluator: StrategyEvaluator | None = None,
    min_sample_size: int = 1,
) -> tuple[WindowResult, ...]:
    if window_size <= 0 or step <= 0:
        raise ValueError("窗口大小和步长必须大于 0")
    engine = evaluator or StrategyEvaluator()
    rows = prepare_backtest_records(records, condition.data_source)
    result: list[WindowResult] = []
    index = 1
    for start in range(0, max(0, len(rows) - window_size + 1), step):
        window = rows[start:start + window_size]
        if not window:
            continue
        metrics = engine.evaluate(window, condition, min_sample_size=min_sample_size)
        result.append(WindowResult(index, str(window[0].get("issue_no") or ""), str(window[-1].get("issue_no") or ""), metrics))
        index += 1
    if not result and rows:
        metrics = engine.evaluate(rows, condition, min_sample_size=min_sample_size)
        result.append(WindowResult(1, str(rows[0].get("issue_no") or ""), str(rows[-1].get("issue_no") or ""), metrics))
    return tuple(result)


def analyze_parameter_sensitivity(
    records: Sequence[Mapping[str, Any]],
    condition: StrategyCondition,
    variants: Mapping[str, Iterable[Any]],
    *,
    evaluator: StrategyEvaluator | None = None,
    min_sample_size: int = 1,
) -> tuple[SensitivityResult, ...]:
    engine = evaluator or StrategyEvaluator()
    result: list[SensitivityResult] = []
    for parameter, values in variants.items():
        for value in values:
            params = dict(condition.params)
            params[parameter] = value
            variant = StrategyCondition(condition.condition_id, condition.name, params, condition.data_source)
            result.append(SensitivityResult(parameter, value, engine.evaluate(records, variant, min_sample_size=min_sample_size)))
    return tuple(result)


def analyze_robustness(
    records: Sequence[Mapping[str, Any]],
    condition: StrategyCondition,
    *,
    window_size: int = 100,
    step: int = 50,
    parameter_variants: Mapping[str, Iterable[Any]] | None = None,
    evaluator: StrategyEvaluator | None = None,
    min_sample_size: int = 1,
) -> RobustnessResult:
    windows = analyze_time_windows(records, condition, window_size=window_size, step=step, evaluator=evaluator, min_sample_size=min_sample_size)
    sensitivities = analyze_parameter_sensitivity(records, condition, parameter_variants or {}, evaluator=evaluator, min_sample_size=min_sample_size)
    available = [(item.metrics.hit_rate, item.index) for item in windows if item.metrics.hit_rate is not None]
    worst = min(available, key=lambda item: item[0]) if available else (None, None)
    return RobustnessResult(windows, sensitivities, worst[1], worst[0])


# Friendly aliases used by integrations that name analyses by their output.
time_window_analysis = analyze_time_windows
parameter_sensitivity_analysis = analyze_parameter_sensitivity


def worst_window(result: RobustnessResult) -> int | None:
    return result.worst_window_index

__all__ = ["WindowResult", "SensitivityResult", "RobustnessResult", "analyze_time_windows", "analyze_parameter_sensitivity", "analyze_robustness", "time_window_analysis", "parameter_sensitivity_analysis", "worst_window"]
