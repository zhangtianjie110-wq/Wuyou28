from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.yu28_tools_page import (
    HistoryTrendPage,
    LongDragonStatsPage,
    LotteryStatsPage,
    Yu28ToolsPage,
)
from app.yu28 import YU28Draw


class _Gateway:
    def daily_stats(self):
        return {"date": "2026-09-27", "data": {"大": 10, "小": 9}}

    def omission(self):
        return {"data": {"大": 2, "小单": 0}}

    def long_dragon(self):
        return {"data": [{
            "type": "周期",
            "content": "单双",
            "count": 8,
            "start": "3463693",
            "current": "3463700",
            "status": "进行中",
        }]}

    def text_trend(self, limit=20):
        return {
            "countdown": "02:40",
            "data": [
                YU28Draw(
                    "3463701",
                    "2026-09-27 12:00:00",
                    "4+8+2=14",
                    "大双",
                    "02:40",
                )
            ][:limit],
        }


class Yu28ToolsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_four_tabs_render_gateway_data(self):
        page = Yu28ToolsPage(_Gateway())
        self.assertEqual(page.tabs.count(), 4)
        self.assertEqual(
            [page.tabs.tabText(index) for index in range(page.tabs.count())],
            ["今日统计", "遗漏", "长龙", "文本走势"],
        )
        page.load_daily_stats()
        page.load_omission()
        page.load_long_dragon()
        page.load_text_trend()
        self.assertGreater(page.stats_table.rowCount(), 0)
        self.assertGreater(page.omission_table.rowCount(), 0)
        self.assertGreater(page.dragon_table.rowCount(), 0)
        self.assertEqual(page.trend_table.item(0, 0).text(), "3463701")

    def test_standalone_pages_reuse_the_existing_gateway_payloads(self):
        gateway = _Gateway()
        stats = LotteryStatsPage(gateway)
        dragon = LongDragonStatsPage(gateway)
        trend = HistoryTrendPage(gateway)

        stats.refresh()
        dragon.refresh()
        trend.refresh()

        self.assertGreater(stats.table.rowCount(), 0)
        self.assertEqual(dragon.table.item(0, 3).text(), "3463693")
        self.assertEqual(trend.table.item(0, 0).text(), "3463701")
        self.assertEqual(trend.table.item(0, 2).text(), "4+8+2=14")


if __name__ == "__main__":
    unittest.main()
