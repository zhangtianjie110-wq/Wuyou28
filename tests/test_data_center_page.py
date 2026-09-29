from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.data_center_page import DataCenterDetailDialog, DataCenterPage


def healthy_snapshot() -> dict:
    return {
        "overall_status": "HEALTHY",
        "top": {
            "draw_status": "ONLINE",
            "draw_latest_issue": "3486491",
            "vip100_status": "RUNNING",
            "vip100_latest_issue": "3486492",
            "vip100_prediction_count": 100,
            "hash_status": "HASH_OK",
            "strategy_status": "RUNNING",
            "strategy_db_status": "ONLINE",
            "data_freshness": "HEALTHY",
        },
        "counts": {
            "draw_periods": 275,
            "vip100_periods": 85,
            "vip100_prediction_rows": 8500,
            "drawn_prediction_periods": 84,
            "pending_prediction_periods": 1,
            "strategy_total": 1000,
            "RESEARCH_ONLY": 600,
            "CANDIDATE": 100,
            "FORWARD_TEST": 100,
            "VERIFIED": 50,
            "REJECTED": 150,
            "insufficient_samples": 300,
        },
        "integrity": [
            {"name": "开奖期号连续性", "status": "HEALTHY", "detail": "正常"},
            {"name": "VIP100每期100条", "status": "HEALTHY", "detail": "正常"},
            {"name": "缺失预测期", "status": "HEALTHY", "detail": "正常"},
            {"name": "重复记录", "status": "HEALTHY", "detail": "正常"},
            {"name": "已开奖但未回填结果", "status": "HEALTHY", "detail": "正常"},
            {"name": "HASH异常", "status": "HEALTHY", "detail": "正常"},
            {"name": "Strategy DB读取状态", "status": "HEALTHY", "detail": "正常"},
        ],
        "services": [
            {"name": "VIP100 validation", "status": "RUNNING", "pid": 1, "updated_at": "now", "source": "state-1", "error": None},
            {"name": "VIP100 production", "status": "RUNNING", "pid": 2, "updated_at": "now", "source": "state-2", "error": None},
            {"name": "YU28 producer", "status": "RUNNING", "pid": 3, "updated_at": "now", "source": "state-3", "error": None},
            {"name": "StrategyResearchEngine", "status": "RUNNING", "pid": 4, "updated_at": "now", "source": "state-4", "error": None},
            {"name": "8787 UI", "status": "RUNNING", "pid": None, "updated_at": None, "source": "TCP 127.0.0.1:8787", "error": None},
        ],
        "recent": [
            {
                "issue": "3486492",
                "draw_status": "PENDING",
                "vip100_count": 100,
                "hash_status": "HASH_OK",
                "outcome_status": "WAITING_DRAW",
                "strategy_ingest_status": "WAITING_DRAW",
                "data_time": "2026-09-26T04:11:00+08:00",
                "error": None,
            },
            {
                "issue": "3486491",
                "draw_status": "DRAWN",
                "vip100_count": 100,
                "hash_status": "HASH_OK",
                "outcome_status": "SETTLED",
                "strategy_ingest_status": "INGESTED",
                "data_time": "2026-09-26T04:07:00+08:00",
                "error": None,
            },
        ],
        "errors": [],
    }


class FakeDataCenterRepository:
    def __init__(self, snapshot=None):
        self.value = snapshot or healthy_snapshot()
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return self.value


class FakeGateway:
    def __init__(self, snapshot=None):
        self.data_center = FakeDataCenterRepository(snapshot)


class DataCenterPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.gateway = FakeGateway()
        self.page = DataCenterPage(self.gateway)

    def tearDown(self):
        self.page.close()

    def test_top_health_and_counts_are_displayed(self):
        self.assertEqual("在线", self.page.status_cards["draw_status"].value_label.text())
        self.assertEqual("运行中", self.page.status_cards["vip100_status"].value_label.text())
        self.assertEqual("100/100", self.page.status_cards["vip100_prediction_count"].value_label.text())
        self.assertEqual("校验正常", self.page.status_cards["hash_status"].value_label.text())
        self.assertEqual("8500", self.page.count_labels["vip100_prediction_rows"].text())

    def test_integrity_services_and_recent_records_render(self):
        self.assertEqual(7, self.page.integrity_table.rowCount())
        self.assertEqual(5, self.page.service_table.rowCount())
        self.assertEqual(2, self.page.visible_recent_count())
        self.assertEqual("策略数据库读取状态", self.page.integrity_table.item(6, 0).text())
        self.assertEqual("8787 界面服务", self.page.service_table.item(4, 0).text())

    def test_detail_uses_selected_read_only_record(self):
        dialog = DataCenterDetailDialog(self.page.recent_records[0])
        try:
            self.assertIn("3486492", dialog.windowTitle())
        finally:
            dialog.close()

    def test_single_source_offline_does_not_crash(self):
        value = healthy_snapshot()
        value["overall_status"] = "ERROR"
        value["top"]["strategy_status"] = "OFFLINE"
        value["top"]["strategy_db_status"] = "OFFLINE"
        value["integrity"][-1] = {
            "name": "Strategy DB读取状态",
            "status": "ERROR",
            "detail": "database unavailable",
        }
        page = DataCenterPage(FakeGateway(value))
        try:
            self.assertEqual("离线", page.status_cards["strategy_status"].value_label.text())
            self.assertEqual(2, page.visible_recent_count())
        finally:
            page.close()

    def test_refresh_and_close_do_not_control_services(self):
        before = self.gateway.data_center.calls
        self.page.refresh()
        self.assertEqual(before + 1, self.gateway.data_center.calls)
        self.page.close()
        forbidden = {"start", "stop", "restart", "run", "save", "write", "delete"}
        self.assertTrue(forbidden.isdisjoint(dir(self.page)))
        self.assertTrue(forbidden.isdisjoint(dir(self.gateway.data_center)))

    def test_page_has_no_direct_database_or_core_dependency(self):
        source = (
            Path(__file__).resolve().parents[1] / "app" / "ui" / "data_center_page.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("VIP100LocalEngine", source)
        self.assertNotIn("StrategyResearchEngine", source)


if __name__ == "__main__":
    unittest.main()
