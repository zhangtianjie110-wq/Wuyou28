from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.integration.models import Vip100Batch, Vip100Prediction
from app.ui.vip100_page import COMBINATIONS, Vip100Page


HASH = "ceac161e70735b8319be5f1b5748db520a3c86a86842f54b1550bf82f921b067"


def make_batch(issue: str, offset: int = 0) -> Vip100Batch:
    predictions = tuple(
        Vip100Prediction(
            position=index + 1,
            algorithm_id=f"algorithm-{index + 1:03d}",
            algorithm_name=f"算法 {index + 1}",
            formula=f"[{index % 21 + 1}]+[{(index + 3) % 21 + 1}]",
            prediction=(index + offset) % 28,
            combination=COMBINATIONS[index % 4],
            hit=True if index % 3 == 0 else False if index % 3 == 1 else None,
        )
        for index in range(100)
    )
    return Vip100Batch(
        issue=issue,
        generated_at="2026-09-26T10:00:00+08:00",
        engine_version="VIP100LocalEngine-v2",
        algorithm_hash=HASH,
        history_hash="history-hash",
        input_hash=f"input-{issue}",
        source="VIP100_LOCAL_V2",
        actual_result="1+2+3=6",
        predictions=predictions,
    )


class FakeVipRepository:
    def __init__(self):
        self.batches = {"3486482": make_batch("3486482"), "3486481": make_batch("3486481", 1)}

    def list_issues(self, limit=200):
        return list(self.batches)[:limit]

    def get(self, issue):
        return self.batches.get(str(issue))


class FakeGateway:
    def __init__(self):
        self.vip100 = FakeVipRepository()
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        return {
            "DRAW_LATEST_ISSUE": "3486481",
            "VIP100_STATUS": "RUNNING",
            "VIP100_LATEST_ISSUE": "3486482",
            "VIP100_PREDICTION_COUNT": 100,
            "VIP100_HASH_STATUS": "HASH_OK",
            "STRATEGY_ENGINE_STATUS": "RUNNING",
            "STRATEGY_DB_STATUS": "ONLINE",
            "DATA_FRESHNESS": "FRESH",
        }


class Vip100PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.gateway = FakeGateway()
        self.page = Vip100Page(self.gateway)

    def tearDown(self):
        self.page.close()

    def test_page_displays_complete_current_batch_and_status(self):
        self.assertEqual("3486482", self.page.batch.issue)
        self.assertEqual(100, self.page.visible_prediction_count())
        self.assertEqual(100, self.page.distribution_total())
        self.assertEqual("100/100", self.page.status_cards["algorithm_count"].value_label.text())
        self.assertEqual("校验正常", self.page.status_cards["hash_status"].value_label.text())

    def test_distribution_is_derived_from_all_predictions(self):
        for combination in COMBINATIONS:
            self.assertIn("25 · 25.0%", self.page.distribution_labels[combination].text())
        self.assertEqual("最大差值 0", self.page.spread_label.text())

    def test_history_switch_reads_selected_immutable_batch(self):
        before = self.gateway.vip100.batches["3486482"].predictions
        self.page.issue_selector.setCurrentText("3486481")
        self.assertEqual("3486481", self.page.batch.issue)
        self.assertEqual(100, self.page.visible_prediction_count())
        self.assertIs(before, self.gateway.vip100.batches["3486482"].predictions)

    def test_search_and_filters_do_not_mutate_gateway_rows(self):
        original = self.page.loaded_predictions
        self.page.search.setText("algorithm-001")
        self.assertEqual(1, self.page.visible_prediction_count())
        self.page.search.clear()
        self.page.combination_filter.setCurrentText("大单")
        self.assertEqual(25, self.page.visible_prediction_count())
        self.page.combination_filter.setCurrentText("全部组合")
        self.page.hit_filter.setCurrentText("命中")
        self.assertEqual(34, self.page.visible_prediction_count())
        self.assertIs(original, self.page.loaded_predictions)

    def test_page_has_no_service_or_database_control_surface(self):
        forbidden = {"start", "stop", "restart", "run", "write", "save", "delete"}
        self.assertTrue(forbidden.isdisjoint(dir(self.page)))
        calls_before = self.gateway.health_calls
        self.page.close()
        self.assertEqual(calls_before, self.gateway.health_calls)

    def test_vip100_page_has_no_legacy_dependency_contract(self):
        self.assertTrue(self.gateway.health())
        self.page.refresh()
        self.assertEqual(100, self.page.visible_prediction_count())


if __name__ == "__main__":
    unittest.main()
