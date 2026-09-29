from strategy_lab.filter import FilterConfig, StrategyFilterEngine

from .helpers import make_candidate


def test_default_filter_rules_pass_stable_candidate():
    decision = StrategyFilterEngine().evaluate(make_candidate())
    assert decision.passed is True
    assert decision.result == "PASS"
    assert decision.reasons == ()
    assert decision.walk_forward_pass_ratio == 1.0


def test_filter_records_every_failed_rule_reason():
    candidate = make_candidate(
        train_rate=59,
        validation_rate=57,
        triggers=40,
        misses=16,
        walk_forward_rates=(57, 50),
    )
    decision = StrategyFilterEngine().evaluate(candidate)
    assert decision.result == "FAIL"
    assert len(decision.reasons) == 5
    assert any("触发次数不足" in reason for reason in decision.reasons)
    assert any("训练命中率不足" in reason for reason in decision.reasons)
    assert any("验证命中率不足" in reason for reason in decision.reasons)
    assert any("最大连续未命中超限" in reason for reason in decision.reasons)
    assert any("Walk Forward通过率不足" in reason for reason in decision.reasons)


def test_filter_parameters_are_configurable():
    config = FilterConfig(
        min_trigger_count=10,
        min_train_hit_rate=50,
        min_validation_hit_rate=50,
        max_consecutive_misses=20,
        min_walk_forward_pass_ratio=0.25,
    )
    candidate = make_candidate(
        train_rate=55,
        validation_rate=52,
        triggers=20,
        misses=18,
        walk_forward_rates=(52, 40),
    )
    assert StrategyFilterEngine(config).evaluate(candidate).passed is True


def test_small_sample_candidate_is_eliminated():
    decision = StrategyFilterEngine().evaluate(make_candidate(triggers=49))
    assert decision.passed is False
    assert decision.reasons[0].startswith("触发次数不足")


def test_validation_filtering_does_not_change_training_metrics():
    accepted = make_candidate("A", validation_rate=58)
    rejected = make_candidate("B", validation_rate=57.99)
    before = (accepted.train.to_dict(), rejected.train.to_dict())
    decisions = StrategyFilterEngine().filter((accepted, rejected))
    assert decisions[0].passed is True
    assert decisions[1].passed is False
    assert before == (accepted.train.to_dict(), rejected.train.to_dict())
