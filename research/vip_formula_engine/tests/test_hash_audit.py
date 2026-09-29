import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HashAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((ROOT / "data" / "v3_hash_audit.json").read_text(encoding="utf-8"))

    def test_both_hashes_reproduce(self):
        self.assertTrue(self.report["historical_matches"])
        self.assertTrue(self.report["v3_matches"])

    def test_dataset_identity_is_unchanged(self):
        self.assertEqual(self.report["count"], 100)
        self.assertEqual(self.report["unique_ids"], 100)
        self.assertEqual(self.report["unique_formulaText"], 100)

    def test_root_cause_is_serialization_order(self):
        self.assertIn("key ordering", self.report["root_cause"])
        self.assertFalse(self.report["leveldb_write"])


if __name__ == "__main__":
    unittest.main()
