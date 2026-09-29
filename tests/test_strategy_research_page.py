from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from app.integration.models import StrategyDetail, StrategySummary
from app.ui.strategy_research_page import (
    CONDITION_FIELDS,
    StrategyDetailDialog,
    StrategyResearchPage,
    format_strategy_conditions,
)


def make_summary(
    strategy_id: str,
    status: str,
    *,
    trigger_count: int,
    prediction_status: str = "WAITING_DATA",
    current_prediction: tuple[str, ...] | None = None,
) -> StrategySummary:
    return StrategySummary(
        strategy_id=strategy_id,
        strategy_hash=f"hash-{strategy_id}",
        status=status,
        source_status=status,
        predictor="lowest_2",
        conditions={
            "all": [
                {"field": "minimum_count", "op": "between", "value": [8, 12]},
                {"field": "lowest_is_unique", "op": "eq", "value": 1},
                {"field": "future_field", "op": "ge", "value": 3},
            ]
        },
        train_samples=60,
        validation_samples=20,
        test_samples=20,
        trigger_count=trigger_count,
        hit_count=6,
        miss_count=4,
        accuracy=0.6,
        validation_accuracy=0.6,
        test_accuracy=0.55,
        walk_forward_accuracy=0.57,
        max_consecutive_misses=3,
        recent_20_accuracy=0.55,
        recent_50_accuracy=0.54,
        recent_100_accuracy=0.53,
        forward_samples=8,
        forward_accuracy=0.625,
        created_at="2026-09-26T01:00:00+00:00",
        train_triggers=20,
        validation_triggers=8,
        test_triggers=7,
        train_accuracy=0.5,
        max_consecutive_hits=4,
        current_streak_type="HIT",
        current_streak_count=2,
        average_trigger_interval=3.5,
        strategy_name=f"策略-{strategy_id}",
        strategy_version=f"v1-hash-{strategy_id}",
        rule_hash=f"hash-{strategy_id}",
        target_issue="3486200",
        triggered=prediction_status == "READY",
        current_prediction=current_prediction,
        prediction_status=prediction_status,
        prediction_generated_at="2026-09-26T02:20:00+00:00",
        prediction_source="FORWARD",
    )


class FakeGateway:
    def __init__(self):
        self.rows = (
            make_summary("Strategy_z", "RESEARCH_ONLY", trigger_count=8),
            make_summary(
                "Strategy_a",
                "FORWARD_TEST",
                trigger_count=40,
                prediction_status="READY",
                current_prediction=("大单", "小双"),
            ),
            make_summary(
                "Strategy_m",
                "VERIFIED",
                trigger_count=80,
                prediction_status="NOT_TRIGGERED",
            ),
        )
        self.detail_calls: list[tuple[str, str, int]] = []

    def strategy_status(self):
        return {
            "status": "RUNNING",
            "database_status": "ONLINE",
            "latest_research_at": "2026-09-26T02:00:00+00:00",
            "production_periods": 121,
            "candidate_strategies": 2,
            "forward_test_strategies": 1,
            "verified_strategies": 1,
            "freshness": {"status": "FRESH"},
        }

    def strategy_list(self, limit=2000):
        return list(self.rows[:limit])

    def strategy_current_status(self):
        return {
            "target_issue": "3486200",
            "strategy_total": 3,
            "status_counts": {
                "READY": 1,
                "NOT_TRIGGERED": 1,
                "WAITING_DATA": 1,
                "INVALID_INPUT": 0,
                "MISSED_FORWARD": 0,
            },
            "distribution": {"大单": 1, "小双": 1},
        }

    def strategy_detail(self, strategy_id, history_scope="ALL", history_limit=100):
        self.detail_calls.append((strategy_id, history_scope, history_limit))
        summary = next(row for row in self.rows if row.strategy_id == strategy_id)
        records = (
            {
                "issue": 3486199,
                "prediction": '["大单","小双"]',
                "actual_result": "大单",
                "result_status": "PASS",
                "sample_type": "FORWARD",
                "generated_at": "2026-09-26T02:10:00+00:00",
                "strategy_version": summary.strategy_version,
                "rule_hash": summary.rule_hash,
            },
            {
                "issue": 3486198,
                "prediction": '["大双"]',
                "actual_result": "小单",
                "result_status": "INVALID_INPUT",
                "sample_type": "RECONSTRUCTED",
                "generated_at": "2026-09-26T02:00:00+00:00",
                "strategy_version": summary.strategy_version,
                "rule_hash": summary.rule_hash,
            },
            {
                "issue": 3486100,
                "prediction": '["小单"]',
                "actual_result": "小单",
                "result_status": "PASS",
                "sample_type": "VALIDATION",
                "generated_at": None,
                "strategy_version": None,
                "rule_hash": None,
            },
        )
        if history_scope == "FORWARD":
            records = tuple(row for row in records if row["sample_type"] == "FORWARD")
        elif history_scope == "VALIDATION":
            records = tuple(row for row in records if row["sample_type"] == "VALIDATION")
        return StrategyDetail(
            summary=summary,
            statistics={
                "matched_issues": 11,
                "valid_samples": 10,
                "invalid_samples": 1,
                "hit_count": 6,
                "miss_count": 4,
                "accuracy": 0.6,
                "recent_30_accuracy": 0.6,
                "recent_50_accuracy": 0.58,
                "recent_100_accuracy": 0.57,
                "recent_200_accuracy": 0.56,
                "max_consecutive_hits": 4,
                "max_consecutive_misses": 3,
                "current_streak_type": "HIT",
                "current_streak_count": 2,
                "average_trigger_interval": 3.5,
            },
            latest_trigger={
                "issue": 3486199,
                "distance": 1,
                "prediction": '["大单","小双"]',
                "actual_result": "大单",
                "result_status": "PASS",
                "sample_type": "FORWARD",
            },
            history_records=records[:history_limit],
            history_scope=history_scope,
            history_limit=history_limit,
        )


class StrategyResearchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.gateway = FakeGateway()
        self.page = StrategyResearchPage(self.gateway)

    def tearDown(self):
        self.page.close()

    def test_main_table_is_compact_and_has_real_detail_buttons(self):
        headers = tuple(
            self.page.table.horizontalHeaderItem(index).text()
            for index in range(self.page.table.columnCount())
        )
        self.assertEqual(StrategyResearchPage.HEADERS, headers)
        self.assertNotIn("完整条件", headers)
        self.assertNotIn("策略标识", headers)
        self.assertTrue(
            all(isinstance(self.page.table.cellWidget(row, 6), QPushButton)
                for row in range(self.page.table.rowCount()))
        )

    def test_display_number_is_stable_across_sort_filter_and_reopen(self):
        expected = {
            "Strategy_a": "001",
            "Strategy_m": "002",
            "Strategy_z": "003",
        }
        self.assertEqual(expected, self.page.display_numbers)
        original_ids = {row.strategy_id for row in self.page.loaded_strategies}
        self.page.table.sortItems(1, Qt.DescendingOrder)
        observed = {
            str(self.page.table.item(row, 0).data(Qt.UserRole)):
            self.page.table.item(row, 0).text()
            for row in range(self.page.table.rowCount())
        }
        self.assertEqual(expected, observed)
        for row in range(self.page.table.rowCount()):
            self.assertEqual(
                self.page.table.item(row, 0).data(Qt.UserRole),
                self.page.table.cellWidget(row, 6).property("strategy_id"),
            )
        self.page.status_filter.setCurrentText("已验证")
        self.assertEqual("002", self.page.table.item(0, 0).text())
        reopened = StrategyResearchPage(self.gateway)
        try:
            self.assertEqual(expected, reopened.display_numbers)
            self.assertEqual(original_ids, {row.strategy_id for row in reopened.loaded_strategies})
        finally:
            reopened.close()

    def test_current_prediction_status_and_summary_remain_chinese(self):
        self.assertEqual("运行中", self.page.status_cards["engine"].value_label.text())
        self.assertEqual("在线", self.page.status_cards["database"].value_label.text())
        predictions = {
            self.page.table.item(row, 5).text()
            for row in range(self.page.table.rowCount())
        }
        self.assertEqual({"大单 + 小双", "未触发", "等待当期数据"}, predictions)
        self.assertEqual("3486200", self.page.current_labels["target_issue"].text())

    def test_condition_formatter_is_complete_natural_chinese(self):
        summary = self.gateway.rows[0]
        text = format_strategy_conditions(summary)
        self.assertIn("预测目标：最低两项组合", text)
        self.assertIn("最低出现次数范围：8 至 12", text)
        self.assertIn("最低组合要求：必须唯一", text)
        self.assertIn("其他条件：future_field：不低于 3", text)
        self.assertEqual(4, len(text.splitlines()))
        self.assertNotIn("{", text)
        self.assertNotIn('"field"', text)
        self.assertEqual(18, len(CONDITION_FIELDS))

    def test_every_supported_condition_field_and_operation_is_rendered(self):
        children = []
        for index, field in enumerate(CONDITION_FIELDS):
            operation, value = (
                ("in", ["大单", "小双"])
                if field == "lowest_combination"
                else ("le", 10)
                if index % 3 == 0
                else ("ge", 2)
                if index % 3 == 1
                else ("eq", 1)
            )
            children.append({"field": field, "op": operation, "value": value})
        summary = replace(self.gateway.rows[0], conditions={"all": children})
        text = format_strategy_conditions(summary)
        self.assertEqual(len(CONDITION_FIELDS) + 1, len(text.splitlines()))
        for label in CONDITION_FIELDS.values():
            self.assertIn(label, text)
        for internal_name in CONDITION_FIELDS:
            self.assertNotIn(internal_name, text)

    def test_detail_dialog_displays_official_statistics_and_latest_trigger(self):
        detail = self.gateway.strategy_detail("Strategy_a")
        dialog = StrategyDetailDialog(detail, "001", self.gateway)
        try:
            self.assertEqual("001", dialog.info_labels["display_number"].text())
            self.assertEqual("v1-hash-Strategy_a", dialog.info_labels["version"].text())
            self.assertEqual("11", dialog.stat_labels["matched_issues"].text())
            self.assertEqual("10", dialog.stat_labels["valid_samples"].text())
            self.assertEqual("1", dialog.stat_labels["invalid_samples"].text())
            self.assertEqual("6", dialog.stat_labels["hit_count"].text())
            self.assertEqual("4", dialog.stat_labels["miss_count"].text())
            self.assertEqual("60.0%", dialog.stat_labels["accuracy"].text())
            self.assertEqual("58.0%", dialog.stat_labels["recent_50_accuracy"].text())
            self.assertEqual("连中2", dialog.stat_labels["current_streak"].text())
            self.assertEqual("3.5期", dialog.stat_labels["average_trigger_interval"].text())
            self.assertEqual("3486199", dialog.latest_labels["issue"].text())
            self.assertEqual("1期", dialog.latest_labels["distance"].text())
            self.assertEqual("对", dialog.latest_labels["result"].text())
            self.assertEqual("正式前向", dialog.latest_labels["sample_type"].text())
        finally:
            dialog.close()

    def test_history_filters_keep_reconstructed_out_of_formal_forward(self):
        detail = self.gateway.strategy_detail("Strategy_a")
        dialog = StrategyDetailDialog(detail, "001", self.gateway)
        try:
            all_types = {
                dialog.history_table.item(row, 4).text()
                for row in range(dialog.history_table.rowCount())
            }
            self.assertIn("历史重建", all_types)
            dialog.history_scope.setCurrentText("验证集")
            self.assertEqual(1, dialog.history_table.rowCount())
            self.assertEqual("验证", dialog.history_table.item(0, 4).text())
            dialog.history_scope.setCurrentText("正式前向")
            self.assertEqual(1, dialog.history_table.rowCount())
            self.assertEqual("正式前向", dialog.history_table.item(0, 4).text())
            self.assertNotIn(
                "历史重建",
                {
                    dialog.history_table.item(row, 4).text()
                    for row in range(dialog.history_table.rowCount())
                },
            )
            self.assertEqual(("Strategy_a", "FORWARD", 100), self.gateway.detail_calls[-1])
        finally:
            dialog.close()

    def test_invalid_sample_is_visible_but_does_not_change_valid_rate(self):
        detail = self.gateway.strategy_detail("Strategy_a")
        self.assertEqual(1, detail.statistics["invalid_samples"])
        self.assertEqual(
            detail.statistics["hit_count"] / detail.statistics["valid_samples"],
            detail.statistics["accuracy"],
        )
        invalid = next(
            row for row in detail.history_records
            if row["result_status"] == "INVALID_INPUT"
        )
        self.assertEqual("RECONSTRUCTED", invalid["sample_type"])

    def test_detail_button_opens_native_dialog_and_reads_gateway(self):
        with patch.object(StrategyDetailDialog, "exec", return_value=0) as execute:
            self.page._show_detail_for_id("Strategy_a")
        execute.assert_called_once_with()
        self.assertIsInstance(self.page._detail_dialog, StrategyDetailDialog)
        self.assertEqual(("Strategy_a", "ALL", 100), self.gateway.detail_calls[-1])
        self.assertEqual("策略 001 详情", self.page._detail_dialog.windowTitle())

    def test_refresh_only_rereads_gateway_and_preserves_identity(self):
        detail = self.gateway.strategy_detail("Strategy_a")
        original = (
            detail.summary.strategy_id,
            detail.summary.strategy_version,
            detail.summary.rule_hash,
        )
        dialog = StrategyDetailDialog(detail, "001", self.gateway)
        try:
            before = len(self.gateway.detail_calls)
            dialog.refresh_button.click()
            self.assertEqual(before + 1, len(self.gateway.detail_calls))
            refreshed = dialog.detail.summary
            self.assertEqual(
                original,
                (refreshed.strategy_id, refreshed.strategy_version, refreshed.rule_hash),
            )
        finally:
            dialog.close()

    def test_ui_uses_gateway_without_database_or_engine_imports(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "strategy_research_page.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("strategy_research_engine", source)
        self.assertNotIn(".strategies.", source)
        self.assertIn("gateway.strategy_detail", source)
        self.assertNotIn("下注", source)
        self.assertNotIn("推荐购买", source)
        self.assertNotIn("Feifei", source)


if __name__ == "__main__":
    unittest.main()
