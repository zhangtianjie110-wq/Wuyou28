import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V3PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preflight = json.loads((ROOT / "data" / "v3_preflight.json").read_text(encoding="utf-8"))
        cls.report = json.loads((ROOT / "data" / "v3_report.json").read_text(encoding="utf-8"))

    def test_baseline_is_100_and_unchanged(self):
        self.assertEqual(self.preflight["baseline"]["count"], 100)
        self.assertEqual(self.preflight["baseline"]["unique_ids"], 100)
        self.assertEqual(self.preflight["baseline"]["unique_formulaText"], 100)
        self.assertEqual(self.preflight["baseline"]["sha256_id_order"], "8ab6c0e4b07809b636bf4f7b5d3561d65ac0c3ce7469b6cad6167328558fa460")

    def test_no_mutation_or_temp_algorithm(self):
        self.assertFalse(self.preflight["mutation_performed"])
        self.assertEqual(self.preflight["temporary_algorithms_created"], 0)
        self.assertFalse(self.preflight["leveldb_write"])

    def test_v3_did_not_start_without_safe_bridge(self):
        self.assertEqual(self.report["control_experiments"], 0)
        self.assertFalse(self.report["production_integration"])


if __name__ == "__main__":
    unittest.main()
