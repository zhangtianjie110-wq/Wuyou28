import unittest
from pathlib import Path

from app.database import Database, DuplicateRecordError


def record(issue="1001", result=""):
    return {
        "issue_no": issue,
        "source_type": "VIP",
        "big_single": 25,
        "big_double": 25,
        "small_single": 25,
        "small_double": 25,
        "actual_result": result,
    }


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / ".test_data"
        root.mkdir(exist_ok=True)
        self.path = root / "database_tests.db"
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()
        self.db = Database(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()

    def test_persistence_and_unique_source_issue(self):
        record_id = self.db.add_prediction(record())
        self.assertGreater(record_id, 0)
        reopened = Database(self.path)
        self.assertEqual(len(reopened.list_predictions()), 1)
        with self.assertRaises(DuplicateRecordError):
            reopened.add_prediction(record())

    def test_prediction_persists_without_legacy_metadata(self):
        payload = record(issue="3485738")
        payload["plan_count"] = 100
        record_id = self.db.add_prediction(payload)
        self.assertIsNotNone(self.db.get_prediction(record_id))

    def test_result_update_recalculates_counts_and_status(self):
        record_id = self.db.add_prediction(record())
        self.assertEqual(self.db.get_prediction(record_id)["status"], "待开奖")
        self.db.update_prediction(record_id, {"actual_result": "14"})
        saved = self.db.get_prediction(record_id)
        self.assertEqual(saved["actual_combo"], "大双")
        self.assertEqual(saved["correct_count"], 75)
        self.assertEqual(saved["wrong_count"], 25)
        self.assertEqual(saved["status"], "正常")

    def test_delete_and_backtest_cleanup(self):
        record_id = self.db.add_prediction(record(result="大单"))
        strategy_id = self.db.save_strategy("删除测试", "VIP", "lowest_one", {})
        self.db.save_backtest_result(self.db.get_strategy(strategy_id), {"hits": 1})
        deleted = self.db.delete_prediction(record_id)
        self.assertEqual(deleted["issue_no"], "1001")
        self.assertIsNone(self.db.get_prediction(record_id))
        self.assertIsNone(self.db.latest_backtest(strategy_id))

    def test_invalid_records_are_excluded(self):
        record_id = self.db.add_prediction(record(result="大单"))
        self.assertEqual(len(self.db.valid_backtest_records("VIP")), 1)
        self.db.set_invalid(record_id, True)
        self.assertEqual(len(self.db.valid_backtest_records("VIP")), 0)

    def test_strategy_state_and_statistics_are_vip_only(self):
        self.db.add_prediction(record(issue="3001", result="大单"))
        strategy_id = self.db.save_strategy(
            "真实策略", "VIP", "lowest_one", {"enabled": True}
        )
        self.assertTrue(self.db.get_strategy(strategy_id)["enabled"])
        self.db.set_strategy_enabled(strategy_id, False)
        self.assertFalse(self.db.get_strategy(strategy_id)["enabled"])
        stats = self.db.statistics()
        self.assertEqual(set(stats), {"VIP"})
        self.assertEqual(stats["VIP"]["records"], 1)
        dashboard = self.db.dashboard()
        self.assertEqual(dashboard["total_rows"], 1)
        self.assertEqual(set(dashboard["source_counts"]), {"VIP"})


if __name__ == "__main__":
    unittest.main()
