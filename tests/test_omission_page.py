from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.history_analytics.engine import HistoryAnalyticsEngine
from app.ui.history_analytics_widgets import HistoryObjectDetailDialog
from app.ui.hot_cold_page import HotColdPage
from app.ui.omission_page_v1 import OmissionPage


def draw(issue: int, number: int) -> dict:
    return {
        "issue": str(issue),
        "number": f"0+0+{number}={number}",
        "draw_time": f"2026-09-27 00:{issue % 60:02d}:00",
    }


class Source:
    def __init__(self, rows):
        self.rows = list(rows)

    def history(self, limit=500000):
        return self.rows[-limit:]

    def since(self, issue, limit=500000):
        return [row for row in self.rows if int(row["issue"]) > int(issue)][:limit]

    def latest(self):
        return self.rows[-1] if self.rows else None


class FakeGateway:
    def __init__(self, rows=None):
        rows = rows or [draw(100 + index, index % 28) for index in range(40)]
        self.engine = HistoryAnalyticsEngine(Source(rows))
        self.detail_calls = 0

    def history_omission(self, dimension, window=None):
        return self.engine.omission(dimension, window)

    def history_hot_cold(self, dimension, window=30):
        return self.engine.hot_cold(dimension, window)

    def history_object_detail(self, dimension, object_name):
        self.detail_calls += 1
        return self.engine.detail(dimension, object_name)


class HistoryAnalyticsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_omission_page_switches_dimensions_windows_and_sorts(self):
        gateway = FakeGateway()
        page = OmissionPage(gateway)
        try:
            self.assertEqual(28, page.table.rowCount())
            self.assertEqual(7, page.table.columnCount())
            self.assertEqual("实际样本 30", page.sample_label.text())
            self.assertTrue(page.table.isSortingEnabled())
            page.dimension_box.setCurrentText("大小")
            self.assertEqual(2, page.table.rowCount())
            page.dimension_box.setCurrentText("单双")
            self.assertEqual(2, page.table.rowCount())
            page.dimension_box.setCurrentText("四组合")
            self.assertEqual(4, page.table.rowCount())
            page.range_box.setCurrentText("1000")
            self.assertEqual(40, page.snapshot["actual_samples"])
        finally:
            page.close()

    def test_gap_warning_is_visible_and_missing_issue_is_not_an_observation(self):
        page = OmissionPage(FakeGateway([draw(1, 0), draw(3, 1), draw(4, 2)]))
        try:
            self.assertTrue(page.quality.warning.isVisibleTo(page))
            self.assertEqual("1", page.quality.labels["missing_issues"].text())
            self.assertEqual(3, page.snapshot["actual_samples"])
            zero = next(row for row in page.snapshot["records"] if row["object"] == "0")
            self.assertEqual(2, zero["current_omission"])
        finally:
            page.close()

    def test_hot_cold_page_filters_status_and_uses_actual_sample(self):
        values = [0, 15] * 35 + [15] * 30
        page = HotColdPage(FakeGateway([draw(1000 + index, value) for index, value in enumerate(values)]))
        try:
            page.dimension_box.setCurrentText("大小")
            self.assertEqual(2, page.table.rowCount())
            self.assertEqual("实际样本 30", page.sample_label.text())
            statuses = {
                page.table.item(row, 7).text() for row in range(page.table.rowCount())
            }
            self.assertEqual({"极冷", "极热"}, statuses)
            page.status_box.setCurrentText("极热")
            self.assertEqual(1, page.table.rowCount())
            self.assertEqual("大", page.table.item(0, 0).text())
            page.range_box.setCurrentText("1000")
            self.assertEqual(100, page.snapshot["actual_samples"])
        finally:
            page.close()

    def test_detail_dialog_loads_on_demand_and_refreshes_gateway(self):
        gateway = FakeGateway()
        before = gateway.detail_calls
        dialog = HistoryObjectDetailDialog(gateway, "NUMBER", "0")
        try:
            self.assertEqual(before + 1, gateway.detail_calls)
            self.assertEqual(10, dialog.hot_table.rowCount())
            self.assertEqual("0", dialog.object_label.text())
            dialog.refresh_button.click()
            self.assertEqual(before + 2, gateway.detail_calls)
            self.assertEqual("全部", dialog.hot_table.item(9, 0).text())
        finally:
            dialog.close()

    def test_ui_has_no_database_write_or_core_statistic_loop(self):
        root = Path(__file__).resolve().parents[1] / "app" / "ui"
        for name in ("omission_page.py", "hot_cold_page.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("sqlite3", source)
            self.assertNotIn("INSERT ", source)
            self.assertNotIn("UPDATE ", source)
            self.assertNotIn("for draw in", source)
            self.assertIn("IntegrationGateway", source)
            self.assertNotIn("投注", source)
            self.assertNotIn("必出", source)
            self.assertNotIn("推荐", source)


if __name__ == "__main__":
    unittest.main()
