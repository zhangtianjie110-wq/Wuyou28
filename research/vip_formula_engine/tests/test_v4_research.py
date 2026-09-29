import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V4ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observation = json.loads((ROOT / "data" / "v4_ui_observation.json").read_text(encoding="utf-8"))
        cls.structure = json.loads((ROOT / "data" / "v4_structure_analysis.json").read_text(encoding="utf-8"))
        cls.report = json.loads((ROOT / "data" / "v4_report.json").read_text(encoding="utf-8"))

    def test_canonical_hash_is_required_value(self):
        self.assertEqual(self.report["canonical_sha256"], "18c1390bdbf3d5db6e48939fc5c124f217ab04e2195db2cc60b3bff4e0e838bd")
        self.assertTrue(self.report["canonical_sha256_matches_required"])

    def test_only_current_algorithm_has_reliable_mapping(self):
        self.assertEqual(self.report["page_classification"], "C")
        self.assertEqual(self.report["reliable_algorithm_mapping_count"], 1)
        self.assertEqual(self.report["same_issue_independent_output_count"], 1)

    def test_structure_analysis_covers_all_pairs(self):
        self.assertEqual(self.structure["algorithm_count"], 100)
        self.assertEqual(self.structure["pair_count"], 4950)
        self.assertEqual(len(self.report["closest_10"]), 10)

    def test_no_production_side_effect(self):
        self.assertFalse(self.report["leveldb_write"])
        self.assertFalse(self.report["production_integration"])


if __name__ == "__main__":
    unittest.main()
