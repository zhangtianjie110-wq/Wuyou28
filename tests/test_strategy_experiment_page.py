from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.strategy_experiment_page import StrategyExperimentPage


def prediction(issue: int, actual: str = "大单") -> dict:
    return {
        "id": issue,
        "issue_no": str(issue),
        "source_type": "VIP",
        "big_single": 30,
        "big_double": 25,
        "small_single": 20,
        "small_double": 25,
        "actual_combo": actual,
    }


class FakeDatabase:
    def __init__(self):
        self.path = Path(tempfile.gettempdir()) / "strategy-experiment-test.db"
        self.rows = [prediction(index) for index in range(1, 5)]
        self.saved = None
        self.backtest = None

    def valid_backtest_records(self, source_type):
        return list(self.rows)

    def save_strategy(self, name, source_type, method, parameters):
        self.saved = {"id": 7, "name": name, "source_type": source_type, "method": method, "parameters": parameters}
        return 7

    def get_strategy(self, strategy_id):
        return self.saved

    def save_backtest_result(self, strategy, result):
        self.backtest = result
        return 1


class StrategyExperimentPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_empty_conditions_and_single_condition_backtest(self):
        database = FakeDatabase()
        page = StrategyExperimentPage(database)
        try:
            self.assertEqual("0", page.condition_count.text())
            page.add_condition_button.click()
            self.assertEqual("1", page.condition_count.text())
            page._run_backtest()
            self.assertEqual(1, page.results.rowCount())
            self.assertEqual("4", page.results.item(0, 1).text())
            self.assertEqual("4", page.results.item(0, 2).text())
        finally:
            page.close()

    def test_save_keeps_complete_conditions_and_backtest_result(self):
        database = FakeDatabase()
        page = StrategyExperimentPage(database)
        try:
            page.add_condition_button.click()
            page._run_backtest()
            page._save_strategy()
            self.assertIsNotNone(database.saved)
            self.assertEqual({"min_groups": 1}, database.saved["parameters"]["conditions"])
            self.assertIsNotNone(database.saved["parameters"]["backtest_result"])
            self.assertIsNotNone(database.backtest)
        finally:
            page.close()

    def test_generate_and_scan_actions_render_candidate_results(self):
        database = FakeDatabase()
        page = StrategyExperimentPage(database)
        try:
            page.generate_button.click()
            self.assertEqual("500", page.condition_count.text())
            page._scan_conditions()
            self.assertEqual(500, page.scan_results.rowCount())
            self.assertFalse(page.scan_results.isHidden())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
