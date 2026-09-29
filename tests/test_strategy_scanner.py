from __future__ import annotations

import unittest

from app.strategy_scanner import StrategyConditionGenerator, StrategyScanner


def row(index: int) -> dict:
    return {
        "id": index,
        "issue_no": str(200000 + index),
        "source_type": "VIP",
        "actual_result": "大单" if index % 2 else "小双",
        "big_single": 10,
        "big_double": 20,
        "small_single": 30,
        "small_double": 40,
    }


class StrategyScannerTests(unittest.TestCase):
    def test_generator_is_bounded_and_contains_required_condition_shapes(self):
        generator = StrategyConditionGenerator()
        candidates = generator.generate()
        self.assertEqual(500, len(candidates))
        self.assertLessEqual(len(generator.generate(5000)), 5000)
        self.assertTrue(any(item.get("min_groups") == 2 for item in candidates))
        self.assertTrue(any("selected_groups" in item for item in candidates))
        self.assertTrue(all("conditions" not in item for item in candidates))

    def test_scanner_returns_single_condition_metrics(self):
        results = StrategyScanner().scan(
            [row(index) for index in range(1, 41)],
            [{"min_groups": 1, "condition_family": "测试"}],
            min_sample_size=1,
            walk_forward=False,
        )
        self.assertEqual(1, len(results))
        self.assertEqual("EXP-0001", results[0]["strategy_id"])
        self.assertIn("train", results[0])
        self.assertIn("validation", results[0])
        self.assertIn("score", results[0])

    def test_scanner_keeps_multiple_candidates_sorted_by_composite_score(self):
        results = StrategyScanner().scan(
            [row(index) for index in range(1, 61)],
            [
                {"min_groups": 1, "condition_family": "A"},
                {"min_groups": 2, "condition_family": "B"},
                {"selected_groups": ["大单", "大双"], "condition_family": "C"},
            ],
            min_sample_size=1,
            walk_forward=False,
        )
        self.assertEqual(3, len(results))
        self.assertEqual(
            sorted((item["score"] for item in results), reverse=True),
            [item["score"] for item in results],
        )
        self.assertTrue(all(item["selection_basis"] == "training_only" for item in results))


if __name__ == "__main__":
    unittest.main()
