import sqlite3
from dataclasses import replace

import pytest

from strategy_lab.filter import StrategyFilterEngine
from strategy_lab.freeze import StrategyFreezeService
from strategy_lab.models import StrategyCondition
from strategy_lab.storage import StrategyLabStorage

from .helpers import make_candidate


def test_freeze_saves_immutable_strategy_snapshot(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    candidate = make_candidate("FREEZE")
    candidate = replace(
        candidate,
        condition=StrategyCondition(
            "FREEZE",
            "冻结策略",
            {"min_groups": 2, "selected_groups": ["大单", "大双"]},
        ),
    )
    decision = StrategyFilterEngine().evaluate(candidate)
    frozen = StrategyFreezeService(storage).freeze(
        candidate, decision, strategy_version="1.2.0"
    )
    assert frozen.status == "ACTIVE"
    assert frozen.strategy_version == "1.2.0"
    with pytest.raises(TypeError):
        frozen.condition_params["min_groups"] = 1
    assert isinstance(frozen.condition_params["selected_groups"], tuple)
    with sqlite3.connect(storage.path) as connection:
        row = connection.execute(
            "SELECT strategy_version, status FROM strategy_freeze"
        ).fetchone()
    assert row == ("1.2.0", "ACTIVE")


def test_failed_candidate_cannot_be_frozen(tmp_path):
    storage = StrategyLabStorage(tmp_path / "lab.sqlite3")
    candidate = make_candidate("FAIL", triggers=10)
    decision = StrategyFilterEngine().evaluate(candidate)
    with pytest.raises(ValueError, match="通过自动筛选"):
        StrategyFreezeService(storage).freeze(candidate, decision)
