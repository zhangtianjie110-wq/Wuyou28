import csv
import unittest
from pathlib import Path

from app.backup import backup_database, daily_backup, restore_database
from app.database import Database
from app.import_export import export_history, import_file


class ImportBackupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ".test_data" / "import_backup"
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.rglob("*"):
            if path.is_file():
                path.unlink()
        self.db = Database(self.root / "test.db")

    def tearDown(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                path.unlink()

    def test_csv_import_and_export(self):
        source = self.root / "input.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["期号", "预测类型", "大单", "大双", "小单", "小双", "实际结果"]
            )
            writer.writeheader()
            writer.writerow(
                {"期号": "2001", "预测类型": "VIP", "大单": 11, "大双": 13, "小单": 15, "小双": 17, "实际结果": "27"}
            )
        summary = import_file(self.db, source)
        self.assertEqual(summary["added"], 1)
        saved = self.db.list_predictions()[0]
        self.assertEqual(saved["actual_combo"], "大单")
        destination = self.root / "output.xlsx"
        export_history(destination, [saved])
        self.assertTrue(destination.exists())
        self.assertGreater(destination.stat().st_size, 0)

    def test_daily_backup_runs_once(self):
        backup_dir = self.root / "backups"
        first = daily_backup(self.db.path, backup_dir)
        second = daily_backup(self.db.path, backup_dir)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        manual = backup_database(self.db.path, backup_dir)
        self.assertTrue(manual.exists())

    def test_restore_database_requires_explicit_overwrite_and_recovers_rows(self):
        backup_dir = self.root / "backups"
        backup = backup_database(self.db.path, backup_dir)
        restored = self.root / "restored.db"
        restore_database(backup, restored)
        self.assertEqual(Database(restored).list_predictions(), [])
        with self.assertRaises(FileExistsError):
            restore_database(backup, restored)
        self.db.add_prediction({
            "issue_no": "9901",
            "source_type": "VIP",
            "big_single": 11,
            "big_double": 13,
            "small_single": 15,
            "small_double": 17,
        })
        restore_database(backup, restored, overwrite=True)
        self.assertEqual(Database(restored).list_predictions(), [])

    def test_result_only_import_matches_vip(self):
        base = {
            "issue_no": "3001",
            "big_single": 11,
            "big_double": 13,
            "small_single": 15,
            "small_double": 17,
        }
        self.db.add_prediction({**base, "source_type": "VIP"})
        source = self.root / "results.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["期号", "实际结果"])
            writer.writeheader()
            writer.writerow({"期号": "3001", "实际结果": "小双"})
        summary = import_file(self.db, source)
        self.assertEqual(summary["updated"], 1)
        records = self.db.find_by_issue("3001")
        self.assertEqual({row["actual_combo"] for row in records}, {"小双"})


if __name__ == "__main__":
    unittest.main()
