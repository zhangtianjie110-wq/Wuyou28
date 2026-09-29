from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from app.integration import IntegrationGateway
from app.integration.strategy_algorithm_quality_repository import (
    StrategyAlgorithmQualityRepository,
)
from app.ui.display_text import display_status
from app.ui.strategy_research_page import StrategyResearchPage


class AlgorithmQualityV4IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.gateway = IntegrationGateway()
        cls.repository = StrategyAlgorithmQualityRepository(cls.gateway.paths.strategy_db)

    def test_formal_v4_result_is_complete_and_read_only(self):
        status = self.repository.status()
        self.assertTrue(status["available"])
        self.assertEqual("RECONSTRUCTED", status["source_type"])
        self.assertEqual(5000, status["total_issues"])
        self.assertEqual(100, status["total_algorithms"])
        self.assertEqual(500000, status["total_predictions"])
        self.assertEqual(0, status["final_candidates"])
        self.assertEqual("WEAK", status["evidence"])

    def test_gateway_exposes_only_read_models(self):
        self.assertTrue(self.gateway.strategy_algorithm_quality_status()["available"])
        self.assertEqual(6, len(self.gateway.strategy_algorithm_quality_list()))
        self.assertEqual(100, len(self.gateway.strategy_algorithm_quality_algorithms()))
        self.assertEqual(100, len(self.gateway.strategy_algorithm_quality_groups()))
        current = self.gateway.strategy_algorithm_quality_current()
        self.assertEqual(3486907, current["target_issue"])
        self.assertEqual({"大单", "大双", "小单", "小双"}, set(current["weighted_totals"]))

    def test_algorithm_identity_is_internal_and_order_is_stable(self):
        algorithms = self.repository.algorithm_stats()
        self.assertEqual(list(range(1, 101)), [row["algorithm_order"] for row in algorithms])
        self.assertEqual(100, len({row["algorithm_id"] for row in algorithms}))

    def test_v4_ui_is_chinese_and_shows_all_required_sections(self):
        page = StrategyResearchPage(self.gateway)
        try:
            self.assertTrue(page.algorithm_quality_mode)
            self.assertEqual("算法质量与群体共识 v4", page.research_type.currentText())
            self.assertEqual(
                ["算法质量", "算法群组", "当前加权共识"],
                [page.algorithm_v4_tabs.tabText(i) for i in range(page.algorithm_v4_tabs.count())],
            )
            self.assertEqual(100, page.algorithm_quality_table.rowCount())
            self.assertEqual(100, page.algorithm_groups_table.rowCount())
            self.assertEqual(4, page.weighted_consensus_table.rowCount())
            self.assertEqual("算法001", page.algorithm_quality_table.item(0, 0).text())
            self.assertTrue(page.algorithm_quality_table.item(0, 0).data(Qt.UserRole))
            visible = " ".join(
                widget.text() for widget in page.findChildren(QLabel) if not widget.isHidden()
            )
            visible += " " + " ".join(
                page.algorithm_v4_tabs.tabText(i)
                for i in range(page.algorithm_v4_tabs.count())
            )
            table_text = " ".join(
                page.table.item(row, column).text()
                for row in range(page.table.rowCount())
                for column in range(page.table.columnCount())
                if page.table.item(row, column) is not None
            )
            for token in (
                "ACCURACY_STABILITY", "TRAIN_AGREEMENT_NORMALIZED", "HIGHEST_TWO",
                "OBSERVATION", "WEAK", "RECONSTRUCTED",
            ):
                self.assertNotIn(token, visible + " " + table_text)
        finally:
            page.close()

    def test_chinese_mapping_covers_v4_enums(self):
        self.assertEqual("命中率与稳定性分层", display_status("ACCURACY_STABILITY"))
        self.assertEqual("训练期群组归一化", display_status("TRAIN_AGREEMENT_NORMALIZED"))
        self.assertEqual("最高两组", display_status("HIGHEST_TWO"))
        self.assertEqual("较低", display_status("LOW"))

    def test_ui_has_no_direct_database_or_research_engine_path(self):
        source = (
            Path(__file__).resolve().parents[1] / "app" / "ui" / "strategy_research_page.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("strategy_research_engine", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertIn("strategy_algorithm_quality_algorithms", source)
        self.assertNotIn("下注", source)


if __name__ == "__main__":
    unittest.main()
