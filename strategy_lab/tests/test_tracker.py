import sqlite3
from dataclasses import replace

from strategy_lab.filter import StrategyFilterEngine
from strategy_lab.freeze import StrategyFreezeService
from strategy_lab.models import StrategyCondition
from strategy_lab.storage import StrategyLabStorage
from strategy_lab.tracker import StrategyTracker

from .helpers import make_candidate, make_records


def test_tracker_marks_watch_without_deleting_frozen_strategy(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    candidate = replace(
        make_candidate("TRACK"),
        condition=StrategyCondition("TRACK", "跟踪策略", {"min_groups": 1}),
    )
    frozen = StrategyFreezeService(storage).freeze(
        candidate, StrategyFilterEngine().evaluate(candidate)
    )
    losing_records = [dict(row, actual_combo="小双") for row in make_records(30)]
    result = StrategyTracker(storage).track(frozen, losing_records)
    assert result.new_samples == 30
    assert result.anomaly is True
    assert result.current_status == "WATCH"
    strategies = StrategyFreezeService(storage).list()
    assert len(strategies) == 1
    assert strategies[0].status == "WATCH"
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strategy_tracking").fetchone()[0] == 1
