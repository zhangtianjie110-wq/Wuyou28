import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from strategy_lab.page import StrategyExperimentPage
from strategy_lab.storage import StrategyLabStorage
from strategy_lab.tests.test_page import _Database


def test_v21_mode_and_fixed_validation_are_visible(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = StrategyExperimentPage(_Database(), storage=StrategyLabStorage(tmp_path / "strategy_lab.db"))
    assert page.experiment_mode.currentData() == "v21"
    assert [page.experiment_mode.itemText(i) for i in range(3)] == [
        "基础回测 v1", "可复现实验 v2", "稳定性实验 v2.1"
    ]
    assert "70%" in page.validation_plan.text()
    assert "20%" in page.validation_plan.text()
    assert "10%" in page.validation_plan.text()
    assert page.v21_button.text() == "开始实验"
    assert page.result_tabs.tabText(7) == "稳定性 v2.1"
    page.close()
    app.processEvents()


def test_gui_run_table_is_initialized(tmp_path):
    storage = StrategyLabStorage(tmp_path / "strategy_lab.db")
    storage.save_gui_run({
        "gui_run_id": "GUI-TEST",
        "started_at": "2026-09-29T00:00:00+08:00",
        "experiment_type": "v2.1",
        "parameters": {"validation": {"train_ratio": 0.7}},
        "snapshot_id": "SNAP-TEST",
        "status": "PASS",
    })
    with sqlite3.connect(tmp_path / "strategy_lab.db") as connection:
        row = connection.execute(
            "SELECT experiment_type, snapshot_id, status FROM experiment_gui_runs WHERE gui_run_id = 'GUI-TEST'"
        ).fetchone()
    assert row == ("v2.1", "SNAP-TEST", "PASS")
