from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.integration.models import DrawRecord
from app.ui.home_page import HomePage, _HomeDataTask


class FakeDraws:
    def latest(self):
        return DrawRecord("3486500", "2026-09-26T12:00:00+08:00", "8+2+5=15", "大单")

    def recent(self, _limit):
        return [self.latest()]


class FakeVip100:
    def latest(self):
        return None


class FakeStrategies:
    def status(self):
        return {
            "database_status": "ONLINE",
            "lifecycle_counts": {"RESEARCH_ONLY": 2, "CANDIDATE": 1, "VERIFIED": 1},
        }

    def list_strategies(self, _limit):
        return []


class FakeDataCenter:
    def snapshot(self, recent_limit=10):
        return {
            "recent": [
                {
                    "issue": "3486500",
                    "draw_status": "DRAWN",
                    "vip100_count": 100,
                    "hash_status": "HASH_OK",
                    "outcome_status": "SETTLED",
                    "strategy_ingest_status": "INGESTED",
                    "data_time": "2026-09-26T12:00:00+08:00",
                }
            ]
        }


class FakeGateway:
    draws = FakeDraws()
    vip100 = FakeVip100()
    strategies = FakeStrategies()
    data_center = FakeDataCenter()

    def health(self):
        return {
            "DRAW_SOURCE_STATUS": "ONLINE",
            "DRAW_LATEST_ISSUE": "3486500",
            "VIP100_STATUS": "RUNNING",
            "VIP100_LATEST_ISSUE": "3486501",
            "VIP100_PREDICTION_COUNT": 100,
            "VIP100_HASH_STATUS": "HASH_OK",
            "STRATEGY_ENGINE_STATUS": "RUNNING",
            "DATA_FRESHNESS": "FRESH",
        }


class HomePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_home_uses_official_snapshot_and_shows_core_status(self):
        page = HomePage(object(), gateway=FakeGateway())
        try:
            self.assertEqual("3486500", page.draw_issue.text())
            self.assertEqual("8 + 2 + 5", page.draw_numbers.text())
            self.assertIn("大 · 单 · 大单", page.draw_summary.text())
            self.assertEqual("100/100", page.status_cards["vip"].value_label.text())
            self.assertEqual(1, page.recent_table.rowCount())
        finally:
            page.close()

    def test_home_shortcuts_only_target_formal_pages(self):
        page = HomePage(object(), gateway=FakeGateway())
        try:
            labels = {button.text() for button in page.findChildren(QPushButton)}
            self.assertEqual({"VIP100", "智能选法", "模拟测试", "遗漏统计", "开奖走势"}, labels)
            self.assertEqual("100/100", page.health_values["algorithms"].text())
            self.assertEqual("3486500", page.health_values["issue"].text())
            self.assertEqual("暂无TOP策略", page.strategy_values["top"].text())
            self.assertFalse(hasattr(page, "_collect"))
        finally:
            page.close()

    def test_background_load_keeps_core_data_when_strategy_storage_is_missing(self):
        class MissingStrategies:
            def status(self):
                raise FileNotFoundError("strategy_research.sqlite3")

            def list_strategies(self, _limit):
                raise FileNotFoundError("strategy_research.sqlite3")

        class Gateway(FakeGateway):
            strategies = MissingStrategies()

        finished = []
        failed = []
        task = _HomeDataTask(Gateway())
        task.signals.finished.connect(finished.append)
        task.signals.failed.connect(failed.append)
        task.run()

        self.assertFalse(failed)
        self.assertEqual(1, len(finished))
        self.assertEqual("3486500", finished[0]["latest"].issue)
        self.assertEqual({}, finished[0]["strategy_status"])
        self.assertEqual((), finished[0]["strategies"])


if __name__ == "__main__":
    unittest.main()
