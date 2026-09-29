import unittest

from app.stats import (
    combination_matches,
    normalize_result,
    selected_combinations,
    validate_and_enrich,
)


class StatsTests(unittest.TestCase):
    def test_normalize_numeric_result(self):
        self.assertEqual(normalize_result("0"), "小双")
        self.assertEqual(normalize_result("13"), "小单")
        self.assertEqual(normalize_result("14"), "大双")
        self.assertEqual(normalize_result("27"), "大单")
        self.assertIsNone(normalize_result("28"))

    def test_enrich_four_combinations_and_result(self):
        result = validate_and_enrich(
            {
                "issue_no": "1001",
                "source_type": "VIP",
                "big_single": 20,
                "big_double": 24,
                "small_single": 26,
                "small_double": 30,
                "actual_result": "大单",
            }
        )
        self.assertEqual(result.status, "正常")
        self.assertEqual(result.values["correct_count"], 70)
        self.assertEqual(result.values["wrong_count"], 30)
        self.assertEqual(result.values["lowest_two"], "大单、大双")
        self.assertEqual(result.values["lowest_two_diff"], 4)
        self.assertEqual(result.values["average"], 25)

    def test_bad_vip_total_is_pending_review(self):
        result = validate_and_enrich(
            {
                "issue_no": "1002",
                "source_type": "VIP",
                "big_single": 10,
                "big_double": 10,
                "small_single": 10,
                "small_double": 10,
            }
        )
        self.assertEqual(result.status, "待检查")
        self.assertIn("VIP四组合合计应为 100", result.reason)

    def test_vip_uses_100_as_total(self):
        result = validate_and_enrich(
            {
                "issue_no": "1004",
                "source_type": "VIP",
                "big_single": 19,
                "big_double": 25,
                "small_single": 28,
                "small_double": 28,
                "actual_result": "大单",
            }
        )
        self.assertEqual(result.status, "正常")
        self.assertEqual(result.values["correct_count"], 72)
        self.assertEqual(result.values["wrong_count"], 28)

    def test_selection_methods(self):
        values = {
            "big_single": 11,
            "big_double": 13,
            "small_single": 15,
            "small_double": 17,
        }
        self.assertEqual(selected_combinations(values, "lowest_one"), ["大单"])
        self.assertEqual(selected_combinations(values, "highest_two"), ["小双", "小单"])
        self.assertEqual(selected_combinations(values, "middle_two"), ["大双", "小单"])

    def test_combination_matches_either_dimension(self):
        self.assertTrue(combination_matches("大单", "大单"))
        self.assertTrue(combination_matches("大单", "大双"))
        self.assertTrue(combination_matches("大单", "小单"))
        self.assertFalse(combination_matches("大单", "小双"))

    def test_100_plans_can_derive_four_counts(self):
        plans = ["大单"] * 20 + ["大双"] * 24 + ["小单"] * 26 + ["小双"] * 30
        result = validate_and_enrich(
            {
                "issue_no": "1003",
                "source_type": "VIP",
                "plan_text": "\n".join(plans),
                "actual_result": "小双",
            }
        )
        self.assertEqual(result.status, "正常")
        self.assertEqual(result.values["small_double"], 30)
        self.assertEqual(result.values["correct_count"], 80)
        self.assertEqual(result.values["wrong_count"], 20)


if __name__ == "__main__":
    unittest.main()
