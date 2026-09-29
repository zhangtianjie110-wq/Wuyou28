import json
import sqlite3

from strategy_lab.engine import StrategyLabEngine
from strategy_lab.filter import StrategyFilterEngine
from strategy_lab.models import StrategyCondition
from strategy_lab.ranking import StrategyRanking
from strategy_lab.storage import StrategyLabStorage

from .helpers import make_records


def test_storage_keeps_complete_conditions_and_results(tmp_path):
    database_path = tmp_path / "strategy_lab.sqlite3"
    storage = StrategyLabStorage(database_path)
    condition = StrategyCondition(
        "LAB-1",
        "完整条件",
        {"min_groups": 2, "interval_min": 0, "rank_relations": ["大单<大双"]},
    )
    experiment = StrategyLabEngine().scan(make_records(80), [condition], min_sample_size=1)
    storage.save_experiment(experiment)
    decisions = StrategyFilterEngine().filter(experiment.candidates)
    rankings = StrategyRanking().rank(experiment.candidates, decisions)
    storage.save_filter_results(experiment.experiment_id, decisions, StrategyFilterEngine().config)
    storage.save_rankings(experiment.experiment_id, rankings, StrategyRanking().weights)
    saved_id = storage.save_strategy(experiment.experiment_id, experiment.candidates[0])
    assert database_path.exists()
    assert storage.experiment_count() == 1
    assert saved_id == 1
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT condition_params, training_result, validation_result FROM saved_strategies"
        ).fetchone()
    assert json.loads(row[0]) == dict(condition.params)
    assert "hit_rate" in json.loads(row[1])
    assert "hit_rate" in json.loads(row[2])
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strategy_filters").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM strategy_rankings").fetchone()[0] == 1


def test_storage_does_not_create_or_modify_product_database(tmp_path):
    product_database = tmp_path / "wuyou28.db"
    product_database.write_bytes(b"product-database-sentinel")
    before = product_database.read_bytes()
    StrategyLabStorage(tmp_path / "strategy_lab.sqlite3")
    assert product_database.read_bytes() == before
