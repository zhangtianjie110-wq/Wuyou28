from strategy_lab.evaluator import StrategyEvaluator
from strategy_lab.models import StrategyCondition

from .helpers import make_records


def test_evaluator_exposes_required_metrics():
    condition = StrategyCondition(
        "LAB-0001",
        "最低两个",
        {"min_groups": 2, "min_value_min": 8, "min_value_max": 12},
    )
    metrics = StrategyEvaluator().evaluate(make_records(120), condition, min_sample_size=1)
    assert metrics.total_samples == 120
    assert metrics.trigger_count == 120
    assert metrics.valid_samples == 120
    assert metrics.hit_count >= 0
    assert metrics.hit_rate is not None
    assert metrics.recent_30 is not None
    assert metrics.recent_50 is not None
    assert metrics.recent_100 is not None
    assert metrics.average_trigger_interval == 1.0


def test_optional_history_condition_is_derived_without_using_current_outcome():
    records = make_records(20)
    condition = StrategyCondition(
        "LAB-STATE",
        "前序连续",
        {"min_groups": 1, "continuous_state": "hit", "continuous_min": 1},
    )
    metrics = StrategyEvaluator().evaluate(records, condition, min_sample_size=1)
    # The first rows cannot match because no earlier completed trigger exists.
    assert 0 < metrics.trigger_count < len(records)
    changed_current_outcomes = [dict(row, actual_combo="小双") for row in records]
    changed = StrategyEvaluator().evaluate(changed_current_outcomes, condition, min_sample_size=1)
    assert changed.trigger_count != metrics.trigger_count


def test_walk_forward_uses_200_50_50_windows():
    condition = StrategyCondition("LAB-WF", "窗口", {"min_groups": 2})
    windows = StrategyEvaluator().walk_forward(make_records(350), condition, min_sample_size=1)
    assert len(windows) == 3
    assert all(window.train.total_samples == 200 for window in windows)
    assert all(window.validation.total_samples == 50 for window in windows)
    assert windows[0].validation_issue_range[1] < windows[1].validation_issue_range[1]
