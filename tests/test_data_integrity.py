import unittest
from pathlib import Path

from app.data_integrity import DataIntegrityAuditor
from app.database import Database


def _draw(issue: str, number: str = "1+2+3=6") -> dict[str, str]:
    return {
        "nbr": issue,
        "time": "2026-09-24 12:00:00",
        "number": number,
        "combination": "小双",
        "countdown": "00:00",
    }


def _bundle(issue: str, source: str, actual_result: str = "") -> dict:
    values = (25, 25, 25, 25)
    return {
            "issue_no": issue,
            "source_type": source,
            "plan_count": sum(values),
            "big_single": values[0],
            "big_double": values[1],
            "small_single": values[2],
            "small_double": values[3],
            "actual_result": actual_result,
        }


class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / ".test_data"
        root.mkdir(exist_ok=True)
        self.path = root / "data_integrity.db"
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

    def test_audit_detects_gap_without_creating_legacy_tasks(self):
        self.db.save_yu28_draw(_draw("1000"))
        self.db.save_yu28_draw(_draw("1002", "2+2+4=8"))
        for source in ("VIP",):
            payload = _bundle("1001", source)
            self.db.add_prediction(payload)
        payload = _bundle("1002", "VIP")
        self.db.add_prediction(payload)

        result = DataIntegrityAuditor(self.db).audit()
        issues = {(row["issue_no"], row["issue_type"], row["source_type"]): row for row in result["issues"]}
        self.assertIn(("1001", "YU28开奖缺失", ""), issues)
        self.assertIn(("1003", "VIP缺失", "VIP"), issues)
        self.assertEqual(result["auto_queued"], 0)
        self.assertEqual(self.db.get_prediction(self.db.find_by_issue("1002")[0]["id"])["actual_result"], "8")
        self.assertGreaterEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["summary"]["pending_count"], 0)

    def test_complete_prediction_is_not_replaced_by_neighboring_data(self):
        self.db.save_yu28_draw(_draw("2000"))
        for source in ("VIP",):
            payload = _bundle("2001", source, "")
            self.db.add_prediction(payload)
        before = self.db.find_by_issue("2001")
        DataIntegrityAuditor(self.db).audit()
        after = self.db.find_by_issue("2001")
        self.assertEqual(
            [(row["source_type"], row["actual_result"]) for row in before],
            [(row["source_type"], row["actual_result"]) for row in after],
        )


if __name__ == "__main__":
    unittest.main()
