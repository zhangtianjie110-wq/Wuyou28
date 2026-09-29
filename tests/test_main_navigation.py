from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.database import Database
from app.ui.main_window import MainWindow
from app.ui.ui_diy import UIConfigManager


EXPECTED_NAVIGATION = [
    "首页",
    "数据中心",
    "VIP100",
    "智能选法",
    "策略实验室",
    "策略自动运行",
    "模拟测试",
    "开奖走势",
    "遗漏统计",
    "冷热分析",
    "长龙统计",
    "设置",
]

EXPECTED_HISTORY_RANGES = [
    "30",
    "50",
    "100",
    "200",
    "500",
    "1000",
    "5000",
    "10000",
    "50000",
    "全部",
]


class MainNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        gateway_patches = (
            patch("app.integration.gateway.IntegrationGateway.history_omission", return_value={"rows": (), "quality": {}, "actual_sample": 0}),
            patch("app.integration.gateway.IntegrationGateway.history_hot_cold", return_value={"rows": (), "quality": {}, "actual_sample": 0}),
        )
        self.patchers = gateway_patches
        for patcher in self.patchers:
            patcher.start()
        self.window = MainWindow(
            Database(root / "isolated.db"),
            ui_only=True,
            ui_config=UIConfigManager(root / "ui"),
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_final_navigation_order_and_removed_tools_entry(self):
        actual = [button.text().strip().split()[-1] for button in self.window.nav_buttons]
        self.assertEqual(actual, EXPECTED_NAVIGATION)
        self.assertNotIn("走势图分析", actual)
        self.assertNotIn("组合走势", actual)

    def test_every_navigation_page_opens(self):
        for name in EXPECTED_NAVIGATION:
            page = self.window.stack.widget(self.window.page_indices[name])
            page.refresh = lambda: None
            self.window.show_page_by_name(name)
            self.assertIs(self.window.stack.currentWidget(), page, name)

    def test_actual_history_range_controls_are_complete(self):
        omission = [
            self.window.omission_page.range_box.itemText(index)
            for index in range(self.window.omission_page.range_box.count())
        ]
        hot_cold = [
            self.window.hot_cold_page.range_box.itemText(index)
            for index in range(self.window.hot_cold_page.range_box.count())
        ]
        self.assertEqual(EXPECTED_HISTORY_RANGES, omission)
        self.assertEqual(EXPECTED_HISTORY_RANGES, hot_cold)

    def test_legacy_pages_remain_instantiated_but_are_hidden_from_primary_nav(self):
        actual = [button.text().strip().split()[-1] for button in self.window.nav_buttons]
        self.assertIsNotNone(self.window.strategy_research_page)
        self.assertIsNotNone(self.window.hot_cold_page)
        self.assertNotIn("策略研究", actual)
        self.assertNotIn("遗漏间隔", actual)

    def test_common_tools_are_primary_navigation_pages(self):
        actual = [button.text().strip().split()[-1] for button in self.window.nav_buttons]
        section_labels = [
            label.text()
            for label in self.window.findChildren(QLabel, "NavSection")
        ]
        self.assertEqual(section_labels, ["策略中心", "历史数据"])
        self.assertNotIn("历史分析", actual)
        for name, page in (
            ("开奖走势", self.window.trend_page),
            ("遗漏统计", self.window.omission_page),
            ("冷热分析", self.window.hot_cold_page),
            ("长龙统计", self.window.long_dragon_stats_page),
        ):
            self.assertIn(name, actual)
            self.assertIs(self.window.stack.widget(self.window.page_indices[name]), page)

    def test_history_analysis_legacy_alias_opens_trend_page(self):
        self.window.show_page_by_name("历史分析")
        self.assertIs(
            self.window.stack.currentWidget(),
            self.window.trend_page,
        )


if __name__ == "__main__":
    unittest.main()
