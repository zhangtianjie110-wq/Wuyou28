import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class V2ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observation = json.loads((ROOT / "data" / "v2_single_algorithm_observations.json").read_text(encoding="utf-8"))
        cls.report = json.loads((ROOT / "data" / "v2_report.json").read_text(encoding="utf-8"))

    def test_ten_samples_are_chronological_and_have_prior_snapshots(self):
        samples = self.observation["samples"]
        self.assertEqual(len(samples), 10)
        issues = [int(item["issue"]) for item in samples]
        self.assertEqual(issues, sorted(issues, reverse=True))
        for sample in samples:
            self.assertTrue(all(int(row["issue"]) < int(sample["issue"]) for row in sample["history_snapshot"]))

    def test_active_algorithm_is_saved_algorithm(self):
        self.assertEqual(self.observation["active_formula"], self.observation["algorithm"]["formulaText"])

    def test_no_evaluator_promotion(self):
        self.assertFalse(self.report["evaluator_ready"])
        self.assertFalse(self.report["production_integration"])

    def test_export_wrapper_is_not_claimed(self):
        self.assertFalse(self.report["export_wrapper"]["formula_contains_11_equal"])
        self.assertFalse(self.report["export_wrapper"]["formula_contains_hash"])


if __name__ == "__main__":
    unittest.main()
