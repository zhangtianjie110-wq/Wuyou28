from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.integration.gateway import IntegrationGateway
from app.integration.models import IntegrationPaths
from app.integration.strategy_large_sample_repository import StrategyLargeSampleRepository
from app.ui.strategy_research_page import StrategyDetailDialog, StrategyResearchPage


ENGINE_ROOT = (
    Path.home()
    / "Documents"
    / "Codex"
    / "2026-09-25"
    / "vip"
    / "research"
    / "vip_formula_engine"
    / "StrategyResearchEngine"
)
sys.path.insert(0, str(ENGINE_ROOT))

from strategy_research_engine.large_sample_v1 import persist_pipeline, run_pipeline


COMBINATIONS = ("大单", "大双", "小单", "小双")


def research_row(issue: int) -> dict:
    counts = {
        "大单": 20 + issue % 3,
        "大双": 24,
        "小单": 26,
        "小双": 30 - issue % 3,
    }
    low = sorted(COMBINATIONS, key=lambda name: (counts[name], COMBINATIONS.index(name)))
    high = sorted(COMBINATIONS, key=lambda name: (-counts[name], COMBINATIONS.index(name)))
    actual_cycle = ("大双", "小单", "大双", "小单", "大单", "小双")
    return {
        "issue": issue,
        "actual_combination": actual_cycle[issue % len(actual_cycle)],
        "counts": counts,
        "low_order": low,
        "high_order": high,
        "minimum_count": counts[low[0]],
        "second_minimum_count": counts[low[1]],
        "maximum_count": counts[high[0]],
        "lowest_gap": counts[low[1]] - counts[low[0]],
        "max_min_spread": counts[high[0]] - counts[low[0]],
        "lowest_is_unique": counts[low[0]] < counts[low[1]],
        "lowest_boundary_tie": counts[low[1]] == counts[low[2]],
        "four_combo_concentration": sum((value / 100) ** 2 for value in counts.values()),
    }


class FakeLargeSampleGateway:
    def __init__(self, repository: StrategyLargeSampleRepository):
        self.repository = repository

    def strategy_status(self):
        return {
            "status": "RUNNING",
            "database_status": "ONLINE",
            "latest_research_at": None,
            "production_periods": 0,
            "candidate_strategies": 0,
            "forward_test_strategies": 0,
            "verified_strategies": 0,
            "freshness": {"status": "FRESH"},
        }

    def strategy_large_sample_status(self):
        return self.repository.status()

    def strategy_large_sample_list(self, limit=100):
        return self.repository.list_strategies(limit)

    def strategy_detail(self, strategy_id, history_scope="ALL", history_limit=100):
        return self.repository.get(strategy_id, history_scope, history_limit)


class StrategyLargeSampleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.temporary = tempfile.TemporaryDirectory(prefix="strategy-large-ui-")
        cls.database = Path(cls.temporary.name) / "strategy.sqlite3"
        result = run_pipeline([research_row(issue) for issue in range(1, 5001)])
        persist_pipeline(result, cls.database)
        cls.repository = StrategyLargeSampleRepository(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_gateway_reads_large_sample_without_writing(self):
        paths = IntegrationPaths(
            draw_db=Path(self.temporary.name) / "draw.sqlite3",
            draw_raw_inputs=Path(self.temporary.name) / "raw",
            vip100_production=Path(self.temporary.name) / "production",
            vip100_hash_status=Path(self.temporary.name) / "hash.json",
            strategy_db=self.database,
            strategy_runtime_status=Path(self.temporary.name) / "status.json",
        )
        gateway = IntegrationGateway(paths)
        before = self.database.read_bytes()
        status = gateway.strategy_large_sample_status()
        values = gateway.strategy_large_sample_list()
        detail = gateway.strategy_detail(values[0].strategy_id)
        after = self.database.read_bytes()
        self.assertTrue(status["available"])
        self.assertTrue(values)
        self.assertIsNotNone(detail)
        self.assertEqual(before, after)

    def test_reconstructed_and_forward_are_strictly_separated(self):
        strategy = self.repository.list_strategies()[0]
        reconstructed = self.repository.get(strategy.strategy_id, "RECONSTRUCTED", 100)
        forward = self.repository.get(strategy.strategy_id, "FORWARD", 100)
        self.assertTrue(reconstructed.history_records)
        self.assertEqual(
            {"RECONSTRUCTED"},
            {record["source_type"] for record in reconstructed.history_records},
        )
        self.assertFalse(forward.history_records)
        self.assertFalse(forward.forward_records)

    def test_candidate_identity_and_lifecycle_are_frozen(self):
        for strategy in self.repository.list_strategies():
            self.assertEqual("CANDIDATE", strategy.status)
            self.assertEqual(f"v1-{strategy.rule_hash[:12]}", strategy.strategy_version)
            self.assertEqual(strategy.strategy_hash, strategy.rule_hash)
            self.assertEqual("WAITING_DATA", strategy.prediction_status)
            self.assertEqual("RECONSTRUCTED", strategy.prediction_source)

    def test_large_sample_ui_is_chinese_and_shows_baseline(self):
        page = StrategyResearchPage(FakeLargeSampleGateway(self.repository))
        try:
            self.assertTrue(page.large_sample_mode)
            self.assertTrue(page.baseline_group.isVisibleTo(page))
            headers = tuple(
                page.table.horizontalHeaderItem(index).text()
                for index in range(page.table.columnCount())
            )
            self.assertEqual(StrategyResearchPage.LARGE_SAMPLE_HEADERS, headers)
            self.assertIn("训练命中率", headers)
            self.assertIn("测试命中率", headers)
            self.assertEqual("候选策略", page.table.item(0, 13).text())
            self.assertNotIn("TRAIN", " ".join(headers))
        finally:
            page.close()

    def test_detail_shows_chinese_splits_walk_forward_and_source(self):
        strategy = self.repository.list_strategies()[0]
        detail = self.repository.get(strategy.strategy_id, "ALL", 100)
        dialog = StrategyDetailDialog(
            detail, "001", FakeLargeSampleGateway(self.repository)
        )
        try:
            self.assertNotEqual("—", dialog.stat_labels["train_accuracy"].text())
            self.assertNotEqual("—", dialog.stat_labels["validation_accuracy"].text())
            self.assertNotEqual("—", dialog.stat_labels["test_accuracy"].text())
            self.assertNotEqual("—", dialog.stat_labels["walk_forward_accuracy"].text())
            self.assertIn(
                dialog.history_table.item(0, 4).text(),
                {"训练", "验证", "测试"},
            )
            self.assertEqual("历史重建", dialog.history_table.item(0, 5).text())
        finally:
            dialog.close()

    def test_ui_has_no_direct_database_or_engine_write_path(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "strategy_research_page.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("strategy_research_engine", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertIn("strategy_large_sample_list", source)
        self.assertNotIn("下注", source)

    def test_internal_enum_values_are_not_rendered_as_visible_statuses(self):
        page = StrategyResearchPage(FakeLargeSampleGateway(self.repository))
        try:
            visible = " ".join(
                page.table.item(row, 13).text()
                for row in range(page.table.rowCount())
            )
            for value in ("TRAIN", "VALIDATION", "TEST", "RECONSTRUCTED", "CANDIDATE"):
                self.assertNotIn(value, visible)
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
