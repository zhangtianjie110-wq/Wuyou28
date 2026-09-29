import sqlite3

from strategy_lab.compare import StrategyComparator
from strategy_lab.filter import StrategyFilterEngine
from strategy_lab.freeze import StrategyFreezeService
from strategy_lab.storage import StrategyLabStorage

from .helpers import make_candidate


def test_compare_outputs_all_requested_historical_metrics(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    service = StrategyFreezeService(storage)
    first_candidate = make_candidate("A", train_rate=65, validation_rate=60)
    second_candidate = make_candidate("B", train_rate=68, validation_rate=62)
    first = service.freeze(
        first_candidate,
        StrategyFilterEngine().evaluate(first_candidate),
        strategy_name="策略A",
    )
    second = service.freeze(
        second_candidate,
        StrategyFilterEngine().evaluate(second_candidate),
        strategy_name="策略B",
    )
    result = StrategyComparator(storage).compare((first, second))
    assert len(result.rows) == 2
    row = result.rows[0].to_dict()
    assert row["sample_count"] == 200
    assert row["train_hit_rate"] == 65
    assert row["validation_hit_rate"] == 60
    assert row["recent_30"] == 60
    assert row["max_consecutive_misses"] == 5
    assert row["average_trigger_interval"] == 2.0
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strategy_compare").fetchone()[0] == 2
