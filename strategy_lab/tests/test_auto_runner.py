from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from strategy_lab.auto_page import StrategyAutoPage
from strategy_lab.auto_runner import AutoRunConfig, StrategyAutoRunner
from strategy_lab.models import ExperimentResult
from strategy_lab.storage import StrategyLabStorage
from app.vip100_replay import ReplayStore

from .helpers import make_candidate


FIXED_NOW = datetime(2026, 9, 29, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def _history_database(path):
    store = ReplayStore(path)
    store.initialize()
    combinations = ("大单", "大双", "小单", "小双")
    for issue, actual in ((1001, "大单"), (1002, "小双")):
        records = [
            {
                "algorithm_id": f"ALG-{index:03d}",
                "algorithm_order": index,
                "prediction": index % 28,
                "combination": combinations[(index - 1) % 4],
                "formula": f"formula-{index}",
                "formula_hash": f"hash-{index}",
            }
            for index in range(1, 101)
        ]
        store.write_batch(
            {
                "target_issue": str(issue),
                "source_type": "RECONSTRUCTED",
                "engine_version": "VIP100-test",
                "algorithm_hash": "algorithm-hash",
                "generated_at": FIXED_NOW.isoformat(),
                "as_of_issue": str(issue - 1),
                "input_start_issue": str(issue - 7),
                "input_end_issue": str(issue - 1),
                "input_count": 7,
                "prediction_count": 100,
                "replay_version": "VIP100_REPLAY_V1",
                "input_snapshot_hash": f"input-{issue}",
                "records": records,
            },
            actual_result="result",
            actual_combination=actual,
        )


class _SearchEngine:
    def __init__(self, storage: StrategyLabStorage):
        self.storage = storage

    def search(self, records, *, config):
        assert len(records) == 2
        candidate = make_candidate("AUTO-1")
        experiment = ExperimentResult(
            experiment_id="AUTO-EXPERIMENT",
            data_source=config.data_source,
            candidates=(candidate,),
            created_at=FIXED_NOW.isoformat(),
            train_ratio=0.7,
        )
        self.storage.save_experiment(experiment)
        return SimpleNamespace(experiment=experiment)


class _FailingSearchEngine:
    def search(self, records, *, config):
        raise RuntimeError("模拟搜索失败")


class _HistorySearchEngine(_SearchEngine):
    def search(self, records, *, config):
        assert config.cache_namespace == "VIP100_HISTORY"
        return super().search(records, config=config)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runner(tmp_path, search_engine=None):
    source = tmp_path / "vip100_history.sqlite3"
    _history_database(source)
    storage = StrategyLabStorage(tmp_path / "strategy_lab.db")
    return StrategyAutoRunner(
        history_db_path=source,
        storage=storage,
        report_dir=tmp_path / "reports" / "strategy_daily",
        log_path=tmp_path / "logs" / "strategy_runner.log",
        config=AutoRunConfig(max_candidates=100),
        search_engine=search_engine or _HistorySearchEngine(storage),
        now=lambda: FIXED_NOW,
    )


def test_manual_run_generates_reports_and_preserves_source_database(tmp_path):
    runner = _runner(tmp_path)
    before = _hash(tmp_path / "vip100_history.sqlite3")
    result = runner.run_now()
    after = _hash(tmp_path / "vip100_history.sqlite3")

    assert result.status == "PASS"
    assert result.search_count == 1
    assert result.pass_count == 1
    assert result.fail_count == 0
    assert before == after
    assert result.data_status["data_source"] == "VIP100_HISTORY"
    assert result.data_status["current_periods"] == 2
    assert result.data_status["new_periods"] == 0
    assert result.data_status["latest_issue"] == "1002"
    assert result.data_status["complete"] == 2
    assert result.data_status["partial"] == 0
    assert result.data_status["missing"] == 0
    assert result.data_status["prediction_rows"] == 200
    assert result.data_status["valid_backtest_records"] == 2
    payload = json.loads((tmp_path / "reports/strategy_daily/2026-09-29_report.json").read_text(encoding="utf-8"))
    assert payload["top_strategies"][0]["strategy_name"] == "策略AUTO-1"
    html = (tmp_path / "reports/strategy_daily/2026-09-29_report.html").read_text(encoding="utf-8")
    assert "策略实验日报" in html
    assert runner.get_last_run()["status"] == "PASS"


def test_schedule_run_records_next_daily_execution(tmp_path):
    runner = _runner(tmp_path)
    registered = []
    next_run = runner.schedule_run("02:30", registrar=registered.append)
    assert next_run == datetime(2026, 9, 30, 2, 30, tzinfo=FIXED_NOW.tzinfo)
    assert registered == [next_run]
    assert runner.get_next_run() == next_run


def test_failure_is_persisted_and_logged_without_changing_source(tmp_path):
    runner = _runner(tmp_path, _FailingSearchEngine())
    before = _hash(tmp_path / "vip100_history.sqlite3")
    with pytest.raises(RuntimeError, match="模拟搜索失败"):
        runner.run_now()
    assert _hash(tmp_path / "vip100_history.sqlite3") == before
    assert runner.get_last_run()["status"] == "FAIL"
    log = (tmp_path / "logs/strategy_runner.log").read_text(encoding="utf-8")
    assert "RUN_FAILED" in log
    assert "模拟搜索失败" in log
    failure_report = tmp_path / "reports/strategy_daily/2026-09-29_report.json"
    assert failure_report.is_file()
    payload = json.loads(failure_report.read_text(encoding="utf-8"))
    assert payload["search_count"] == 0
    assert "模拟搜索失败" in payload["warnings"][0]


def test_gui_shows_status_schedule_report_and_manual_action(tmp_path):
    application = QApplication.instance() or QApplication([])
    runner = _runner(tmp_path)
    runner.run_now()
    page = StrategyAutoPage(tmp_path / "strategy_lab.db", runner=runner)
    assert page.status_value.text() == "运行成功"
    assert "2026-09-30 02:30" in page.next_run_value.text()
    assert page.report_value.text().endswith("2026-09-29_report.html")
    assert page.run_button.text() == "立即运行"
    page.close()
    application.processEvents()


def test_default_storage_uses_required_database_name():
    from strategy_lab.storage import DEFAULT_PATH

    assert DEFAULT_PATH.name == "strategy_lab.db"


