from __future__ import annotations

import sqlite3

from app.vip100_replay import ReplayStore
from strategy_lab.vip100_history import Vip100HistoryDataSource


def _payload(issue: int) -> dict:
    combinations = ("大单", "大双", "小单", "小双")
    return {
        "target_issue": str(issue),
        "source_type": "RECONSTRUCTED",
        "engine_version": "VIP100-test",
        "algorithm_hash": "algorithm-hash",
        "generated_at": "2026-09-29T02:30:00+08:00",
        "as_of_issue": str(issue - 1),
        "input_start_issue": str(issue - 7),
        "input_end_issue": str(issue - 1),
        "input_count": 7,
        "prediction_count": 100,
        "replay_version": "VIP100_REPLAY_V1",
        "input_snapshot_hash": f"input-{issue}",
        "records": [
            {
                "algorithm_id": f"ALG-{index:03d}",
                "algorithm_order": index,
                "prediction": index % 28,
                "combination": combinations[(index - 1) % 4],
                "formula": f"formula-{index}",
                "formula_hash": f"hash-{index}",
            }
            for index in range(1, 101)
        ],
    }


def test_history_database_retains_algorithm_prediction_draw_and_hit(tmp_path):
    path = tmp_path / "vip100_history.sqlite3"
    store = ReplayStore(path)
    store.initialize()
    store.write_batch(
        _payload(2001),
        actual_result="1+2+3=6",
        actual_combination="小双",
    )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """SELECT p.target_issue, p.algorithm_id, p.prediction,
                      p.combination, r.actual_result, r.actual_combination, p.hit
               FROM vip100_reconstructed_predictions p
               JOIN vip100_reconstructed_runs r
                 ON r.target_issue=p.target_issue
               WHERE p.target_issue=2001 AND p.algorithm_id='ALG-001'"""
        ).fetchone()
    assert row == (2001, "ALG-001", 1, "大单", "1+2+3=6", "小双", 0)


def test_history_source_aggregates_complete_periods_and_excludes_unsettled(tmp_path):
    path = tmp_path / "vip100_history.sqlite3"
    store = ReplayStore(path)
    store.initialize()
    store.write_batch(
        _payload(2001),
        actual_result="1+2+3=6",
        actual_combination="小双",
    )
    store.write_batch(
        _payload(2002),
        actual_result=None,
        actual_combination=None,
    )

    source = Vip100HistoryDataSource(path)
    status = source.data_status()
    records = source.backtest_records()

    assert status["data_source"] == "VIP100_HISTORY"
    assert status["current_periods"] == 2
    assert status["complete"] == 1
    assert status["partial"] == 1
    assert status["missing_outcome_periods"] == 1
    assert status["prediction_rows"] == 200
    assert status["settled_prediction_rows"] == 100
    assert len(records) == 1
    assert records[0]["issue_no"] == "2001"
    assert records[0]["source_type"] == "VIP"
    assert sum(
        records[0][field]
        for field in ("big_single", "big_double", "small_single", "small_double")
    ) == 100


def test_history_source_requires_replay_schema(tmp_path):
    path = tmp_path / "invalid.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    source = Vip100HistoryDataSource(path)
    try:
        source.data_status()
    except ValueError as exc:
        assert "缺少表" in str(exc)
    else:
        raise AssertionError("invalid history schema was accepted")
