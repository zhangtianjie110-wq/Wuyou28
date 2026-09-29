from strategy_lab.filter import StrategyFilterEngine
from strategy_lab.ranking import StrategyRanking

from .helpers import make_candidate


def test_ranking_orders_candidates_by_historical_quality_metrics():
    stronger = make_candidate(
        "A", validation_rate=68, samples=200, misses=3, walk_forward_rates=(65, 70)
    )
    weaker = make_candidate(
        "B", validation_rate=60, samples=80, misses=10, walk_forward_rates=(60, 50)
    )
    candidates = (weaker, stronger)
    decisions = StrategyFilterEngine().filter(candidates)
    ranking = StrategyRanking().rank(candidates, decisions)
    assert ranking[0].candidate.condition.condition_id == "A"
    assert ranking[0].ranking_score > ranking[1].ranking_score
    assert ranking[0].to_dict()["status"] == "候选"
    assert "condition_params" in ranking[0].to_dict()


def test_ranking_uses_candidate_observation_elimination_statuses():
    candidate = make_candidate("PASS")
    observation = make_candidate("WATCH", validation_rate=50, walk_forward_rates=(50, 50))
    eliminated = make_candidate("OUT", train_rate=40, triggers=20, walk_forward_rates=(40, 40))
    candidates = (eliminated, observation, candidate)
    decisions = StrategyFilterEngine().filter(candidates)
    ranking = StrategyRanking().rank(candidates, decisions)
    assert [item.status for item in ranking] == ["候选", "观察", "淘汰"]
    assert all("最佳" not in item.status for item in ranking)
