from dataclasses import replace

from strategy_lab.models import ExperimentResult, StrategyCondition
from strategy_lab.search import SearchConfig, SearchSpace, StrategySearchEngine
from strategy_lab.storage import StrategyLabStorage

from .helpers import make_candidate, make_records


class _CountingEngine:
    def __init__(self):
        self.calls = 0

    def scan(self, records, conditions, **kwargs):
        self.calls += 1
        candidates = tuple(
            replace(make_candidate(condition.condition_id), condition=condition)
            for condition in conditions
        )
        return ExperimentResult(
            experiment_id=f"BATCH-{self.calls}",
            data_source=kwargs["data_source"],
            candidates=candidates,
            created_at="2026-09-28T00:00:00+08:00",
            train_issue_range=("1", "70"),
            validation_issue_range=("71", "100"),
        )


def test_search_generation_deduplicates_equal_parameters(tmp_path):
    engine = StrategySearchEngine(StrategyLabStorage(tmp_path / "lab.sqlite3"))
    repeated_space = SearchSpace(
        minimum_ranges=((8, 10), (8, 10)),
        lowest_difference_ranges=((0, 1), (0, 1)),
        spread_ranges=((0, 12),),
        rank_relations=(None,),
        allow_ties=(False, False),
        trigger_intervals=((0, None),),
        combination_pairs=(("BD", "BS"), ("BD", "BS")),
    )
    conditions = engine.generate_conditions(repeated_space, limit=50)
    hashes = [engine.parameter_hash(item.params) for item in conditions]
    assert len(conditions) == 1
    assert len(hashes) == len(set(hashes))
    assert len(engine.generate_conditions(limit=200)) == 200


def test_search_uses_cached_results_for_identical_parameters(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    counter = _CountingEngine()
    engine = StrategySearchEngine(storage, counter)
    config = SearchConfig(max_candidates=50, min_sample_size=1)
    first = engine.search(make_records(100), config=config)
    second = engine.search(make_records(100), config=config)
    assert first.evaluated_count == 50
    assert first.cache_hits == 0
    assert second.evaluated_count == 0
    assert second.cache_hits == 50
    assert counter.calls == 1
    assert first.search_id != second.search_id
    assert second.result_summary["candidate_count"] == 50


def test_search_cache_isolated_by_data_namespace(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    counter = _CountingEngine()
    engine = StrategySearchEngine(storage, counter)
    history = SearchConfig(
        max_candidates=50,
        min_sample_size=1,
        cache_namespace="VIP100_HISTORY",
    )
    legacy = SearchConfig(
        max_candidates=50,
        min_sample_size=1,
        cache_namespace="VIP_LEGACY",
    )

    first_history = engine.search(make_records(100), config=history)
    first_legacy = engine.search(make_records(100), config=legacy)
    second_history = engine.search(make_records(100), config=history)

    assert first_history.experiment.data_source == "VIP100_HISTORY"
    assert first_legacy.experiment.data_source == "VIP_LEGACY"
    assert first_history.evaluated_count == 50
    assert first_legacy.evaluated_count == 50
    assert second_history.cache_hits == 50
    assert counter.calls == 2


def test_two_hundred_candidate_search_runs_in_bounded_batches(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    counter = _CountingEngine()
    result = StrategySearchEngine(storage, counter).search(
        make_records(100),
        config=SearchConfig(max_candidates=200, min_sample_size=1),
    )
    assert result.parameter_count == 200
    assert result.evaluated_count == 200
    assert counter.calls == 2
