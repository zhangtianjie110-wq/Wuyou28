from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from app.integration import IntegrationGateway, IntegrationPaths
from app.integration.strategy_dynamic_pair_repository import StrategyDynamicPairRepository
from app.ui.display_text import display_status
from app.ui.strategy_research_page import StrategyDetailDialog, StrategyResearchPage
from strategy_research_engine.dynamic_pair_v2 import SCHEMA


PAIR_DISTRIBUTION = {
    "大单+大双": 0.18,
    "大单+小单": 0.16,
    "大单+小双": 0.17,
    "大双+小单": 0.15,
    "大双+小双": 0.18,
    "小单+小双": 0.16,
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metrics(triggers: int, accuracy: float) -> dict:
    hits = round(triggers * accuracy)
    return {
        "triggers": triggers,
        "hits": hits,
        "misses": triggers - hits,
        "accuracy": accuracy,
        "max_consecutive_hits": 4,
        "max_consecutive_misses": 7,
        "current_streak_type": "MISS",
        "current_streak_count": 1,
        "average_trigger_interval": 2.5,
        "recent_30_accuracy": accuracy,
        "recent_50_accuracy": accuracy,
        "recent_100_accuracy": accuracy,
        "recent_200_accuracy": accuracy,
        "selected_pair_distribution": PAIR_DISTRIBUTION,
    }


def _create_fixture(database: Path) -> None:
    train = _metrics(120, 0.55)
    validation = _metrics(40, 0.525)
    test = _metrics(38, 0.5526)
    full = _metrics(198, 0.5455)
    walk = {
        "window_count": 3,
        "triggers": 90,
        "hits": 49,
        "misses": 41,
        "accuracy": 0.5444,
        "worst_window_accuracy": 0.5,
        "best_window_accuracy": 0.6,
        "median_window_accuracy": 0.5333,
        "window_volatility": 0.04,
        "max_consecutive_misses": 6,
    }
    filters = [{"field": "r1_r2_gap", "op": "le", "value": 1}]
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        connection.execute("CREATE TABLE large_sample_runs(run_id TEXT PRIMARY KEY, marker TEXT)")
        connection.execute("INSERT INTO large_sample_runs VALUES('V1_FROZEN','UNCHANGED')")
        connection.execute(
            "INSERT INTO dynamic_v2_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "DPV2_TEST", "strategy-dynamic-pair-v2", "RECONSTRUCTED", "dataset-hash",
                5000, 3500, 3481908, 3485407, 750, 3485408, 3486157,
                750, 3486158, 3486907, 6, 960, 702, 30, 30, 20, 1,
                _json({"train": 0.55, "validation": 0.525, "test": 0.5526, "walk_forward": 0.5444}),
                _json({"conclusion": "未发现一致改善。"}), _json({}),
                "2026-09-27T00:00:00+00:00", "2026-09-27T00:01:00+00:00", "COMPLETE",
            ),
        )
        connection.execute(
            "INSERT INTO dynamic_v2_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "DPV2_TEST", "DPV2_fixture", "动态双组合候选 001", "v2-rulehash",
                "rulehash", "R1_R4", "SKIP_AFFECTED_TIE", _json(filters), 1,
                "CANDIDATE", _json(train), _json(validation), _json(test), _json(walk),
                _json(full), None, None, None, "2026-09-27T00:01:00+00:00",
            ),
        )
        for split, issue in (("TRAIN", 3485407), ("VALIDATION", 3486157), ("TEST", 3486907)):
            connection.execute(
                "INSERT INTO dynamic_v2_triggers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "DPV2_TEST", "DPV2_fixture", issue, split, "RECONSTRUCTED",
                    20, 24, 26, 30, "大单", "大双", "小单", "小双", "R1_R4",
                    "SKIP_AFFECTED_TIE", _json(["大单", "小双"]), _json(filters), "大单", 1,
                ),
            )
        for index in range(1, 4):
            connection.execute(
                "INSERT INTO dynamic_v2_walk_forward VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("DPV2_TEST", "DPV2_fixture", index, 3481908, 3482107, 3482108, 3482157, 30, 16, 14, 0.5333),
            )
        connection.execute(
            "INSERT INTO dynamic_v2_baselines VALUES(?,?,?,?,?,?)",
            ("DPV2_TEST", 0.5, _json({}), _json({}), _json({}), "RECONSTRUCTED"),
        )
        connection.commit()
    finally:
        connection.close()


class FakeDynamicGateway:
    def __init__(self, repository: StrategyDynamicPairRepository):
        self.repository = repository
        self.dynamic_reads = 0

    def strategy_status(self):
        return {
            "status": "RUNNING", "database_status": "ONLINE", "latest_research_at": None,
            "production_periods": 0, "candidate_strategies": 0,
            "forward_test_strategies": 0, "verified_strategies": 0,
            "freshness": {"status": "FRESH"},
        }

    def strategy_dynamic_pair_status(self):
        return self.repository.status()

    def strategy_dynamic_pair_list(self, limit=100):
        self.dynamic_reads += 1
        return self.repository.list_strategies(limit)

    def strategy_large_sample_status(self):
        return {"available": False}

    def strategy_detail(self, strategy_id, history_scope="ALL", history_limit=100):
        return self.repository.get(strategy_id, history_scope, history_limit)


class DynamicPairFormalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.temporary = tempfile.TemporaryDirectory(prefix="dynamic-v2-ui-")
        cls.database = Path(cls.temporary.name) / "strategy.sqlite3"
        _create_fixture(cls.database)
        cls.repository = StrategyDynamicPairRepository(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_gateway_dynamic_reads_are_read_only(self):
        missing = Path(self.temporary.name) / "missing"
        gateway = IntegrationGateway(
            IntegrationPaths(missing, missing, missing, missing, self.database, missing, missing)
        )
        before = self.database.read_bytes()
        status = gateway.strategy_dynamic_pair_status()
        strategies = gateway.strategy_dynamic_pair_list()
        detail = gateway.strategy_detail(strategies[0].strategy_id)
        self.assertTrue(status["available"])
        self.assertEqual("DPV2_fixture", detail.summary.strategy_id)
        self.assertEqual(before, self.database.read_bytes())

    def test_v1_fixture_is_unchanged_by_dynamic_reads(self):
        connection = sqlite3.connect(self.database)
        try:
            before = connection.execute(
                "SELECT run_id,marker FROM large_sample_runs"
            ).fetchall()
        finally:
            connection.close()
        self.repository.status()
        self.repository.list_strategies()
        self.repository.get("DPV2_fixture")
        connection = sqlite3.connect(self.database)
        try:
            after = connection.execute(
                "SELECT run_id,marker FROM large_sample_runs"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual([("V1_FROZEN", "UNCHANGED")], before)
        self.assertEqual(before, after)

    def test_reconstructed_and_forward_are_strictly_separated(self):
        reconstructed = self.repository.get("DPV2_fixture", "RECONSTRUCTED", 100)
        forward = self.repository.get("DPV2_fixture", "FORWARD", 100)
        self.assertEqual({"RECONSTRUCTED"}, {row["source_type"] for row in reconstructed.history_records})
        self.assertFalse(forward.history_records)
        self.assertFalse(forward.forward_records)

    def test_dynamic_research_type_and_table_are_chinese(self):
        gateway = FakeDynamicGateway(self.repository)
        page = StrategyResearchPage(gateway)
        try:
            self.assertTrue(page.dynamic_pair_mode)
            self.assertEqual("动态双组合 v2", page.research_type.currentText())
            self.assertEqual(1, page.visible_strategy_count())
            headers = tuple(page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount()))
            self.assertEqual(StrategyResearchPage.DYNAMIC_PAIR_HEADERS, headers)
            self.assertEqual("最低项 + 最高项", page.table.item(0, 1).text())
            self.assertEqual("候选策略", page.table.item(0, 12).text())
            self.assertGreater(gateway.dynamic_reads, 0)
        finally:
            page.close()

    def test_detail_shows_all_six_pair_distributions(self):
        detail = self.repository.get("DPV2_fixture")
        dialog = StrategyDetailDialog(detail, "001", FakeDynamicGateway(self.repository))
        try:
            self.assertFalse(dialog.pair_distribution_group.isHidden())
            self.assertEqual(set(PAIR_DISTRIBUTION), set(dialog.pair_distribution_labels))
            self.assertTrue(all(label.text().endswith("%") for label in dialog.pair_distribution_labels.values()))
            self.assertEqual("最低项 + 最高项", dialog.info_labels["selected_pair"].text())
        finally:
            dialog.close()

    def test_dynamic_history_tooltips_are_chinese(self):
        detail = self.repository.get("DPV2_fixture")
        dialog = StrategyDetailDialog(detail, "001", FakeDynamicGateway(self.repository))
        try:
            tooltip = dialog.history_table.item(0, 0).toolTip()
            self.assertIn("四组数量", tooltip)
            self.assertIn("受影响并列时跳过", tooltip)
            self.assertNotIn("SKIP_AFFECTED_TIE", tooltip)
            self.assertNotIn("R1_R4", tooltip)
        finally:
            dialog.close()

    def test_display_mapping_and_ui_have_no_direct_write_path(self):
        self.assertEqual("动态选择退化警告", display_status("DYNAMIC_COLLAPSE_WARNING"))
        self.assertEqual("固定组合顺序", display_status("FIXED_COMBINATION_ORDER"))
        source = (Path(__file__).resolve().parents[1] / "app" / "ui" / "strategy_research_page.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("strategy_research_engine", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertIn("strategy_dynamic_pair_list", source)
        self.assertNotIn("下注", source)


if __name__ == "__main__":
    unittest.main()
