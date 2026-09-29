import sqlite3

from strategy_lab.models import StrategyCondition
from strategy_lab.tests.helpers import make_records
from strategy_lab.v2.baselines import compare_to_baselines
from strategy_lab.v2.robustness import analyze_parameter_sensitivity, analyze_robustness
from strategy_lab.v2.validation import ValidationConfig, evaluate_three_way, split_time_series


def test_three_way_split_is_chronological_and_exact_for_100_rows():
    split = split_time_series(make_records(100))
    assert [len(split.train), len(split.validation), len(split.test)] == [70, 20, 10]
    assert split.train[-1]["issue_no"] < split.validation[0]["issue_no"] < split.test[0]["issue_no"]


def test_final_test_is_report_only_and_not_a_selection_slice():
    records = make_records(30)
    condition = StrategyCondition("v21", "v21", {"min_groups": 2})
    split, result = evaluate_three_way(records, condition, min_sample_size=1)
    assert len(split.test) == 3
    assert result.test.total_samples == 3
    assert result.to_dict()["selection_basis"] == "training_validation_only"


def test_robustness_reports_worst_window_and_sensitivity():
    records = make_records(40)
    condition = StrategyCondition("v21", "v21", {"min_groups": 2})
    result = analyze_robustness(records, condition, window_size=10, step=10, parameter_variants={"min_groups": [1, 2]}, min_sample_size=1)
    assert result.windows
    assert result.worst_window_index is not None
    assert len(result.sensitivities) == 2


def test_baseline_comparison_returns_difference():
    records = make_records(20)
    condition = StrategyCondition("v21", "v21", {"min_groups": 2})
    results = compare_to_baselines(records, condition, min_sample_size=1)
    assert {item.name for item in results} == {"majority_actual", "uniform_4_way"}
    assert all(item.difference is not None for item in results)
