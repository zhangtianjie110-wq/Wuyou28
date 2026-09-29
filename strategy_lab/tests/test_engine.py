from strategy_lab.engine import StrategyLabEngine
from strategy_lab.models import EvaluationMetrics, StrategyCondition

from .helpers import make_records


def _metrics(rate: float, samples: int = 100) -> EvaluationMetrics:
    return EvaluationMetrics(
        total_samples=samples,
        trigger_count=samples,
        valid_samples=samples,
        hit_count=round(samples * rate / 100),
        hit_rate=rate,
        recent_30=rate,
        recent_50=rate,
        recent_100=rate,
        max_consecutive_hits=2,
        max_consecutive_misses=2,
        average_trigger_interval=1.0,
    )


class _RankingEvaluator:
    def evaluate_train_validation(self, records, condition, **kwargs):
        if condition.condition_id == "A":
            return _metrics(80), _metrics(5), _metrics(50)
        return _metrics(40), _metrics(99), _metrics(70)

    def walk_forward(self, records, condition, **kwargs):
        return ()


def test_validation_metrics_do_not_influence_candidate_ranking():
    engine = StrategyLabEngine(_RankingEvaluator())
    conditions = [
        StrategyCondition("A", "训练优先", {"min_groups": 2}),
        StrategyCondition("B", "验证较高", {"min_groups": 2}),
    ]
    result = engine.scan(make_records(20), conditions, min_sample_size=1)
    assert [item.condition.condition_id for item in result.candidates] == ["A", "B"]
    assert result.candidates[0].validation.hit_rate == 5
    assert result.to_dict()["selection_basis"] == "training_only"


def test_engine_uses_chronological_seventy_thirty_split():
    condition = StrategyCondition("LAB-1", "基础", {"min_groups": 2})
    result = StrategyLabEngine().scan(make_records(100), [condition], min_sample_size=1)
    assert result.train_issue_range == ("202609280001", "202609280070")
    assert result.validation_issue_range == ("202609280071", "202609280100")
    assert result.candidates[0].train.total_samples == 70
    assert result.candidates[0].validation.total_samples == 30


def test_engine_rejects_unbounded_candidate_list():
    candidates = [
        StrategyCondition(f"LAB-{index}", str(index), {"min_groups": 2})
        for index in range(101)
    ]
    try:
        StrategyLabEngine().scan(make_records(20), candidates)
    except ValueError as exc:
        assert "100" in str(exc)
    else:
        raise AssertionError("more than 100 candidates must be rejected")
