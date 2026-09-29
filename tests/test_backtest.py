import unittest

from app.backtest import run_backtest, run_rolling_backtest
from app.stats import validate_and_enrich


def make_row(index, result):
    values = validate_and_enrich(
        {
            "id": index,
            "issue_no": str(1000 + index),
            "source_type": "VIP",
            "big_single": 20,
            "big_double": 24,
            "small_single": 26,
            "small_double": 30,
            "actual_result": result,
        }
    ).values
    values["id"] = index
    return values


class BacktestTests(unittest.TestCase):
    def test_metrics_and_train_validation_split(self):
        rows = [make_row(i, "大单" if i <= 7 else "小双") for i in range(1, 11)]
        params = {
            "min_value_min": 0,
            "min_value_max": 100,
            "lowest_two_diff_max": 100,
            "allow_tie": True,
            "prev_wrong_min": 0,
            "prev_wrong_max": 100,
            "after_consecutive_losses": 0,
        }
        result = run_backtest(rows, "lowest_one", params, 0.7)
        self.assertEqual(result["matched"], 10)
        self.assertEqual(result["hits"], 7)
        self.assertEqual(result["misses"], 3)
        self.assertEqual(result["train"]["matched"], 7)
        self.assertEqual(result["validation"]["matched"], 3)
        self.assertEqual(result["warning"], "验证表现下降")

    def test_parameter_filter(self):
        rows = [make_row(i, "大单") for i in range(1, 6)]
        params = {
            "min_value_min": 12,
            "min_value_max": 15,
            "lowest_two_diff_max": 100,
            "allow_tie": True,
            "prev_wrong_min": 0,
            "prev_wrong_max": 100,
            "after_consecutive_losses": 0,
        }
        result = run_backtest(rows, "lowest_one", params, 0.7)
        self.assertEqual(result["matched"], 0)

    def test_partial_combination_match_counts_as_hit(self):
        rows = [make_row(1, "大双"), make_row(2, "小单"), make_row(3, "小双")]
        params = {
            "min_value_min": 0,
            "min_value_max": 100,
            "lowest_two_diff_max": 100,
            "allow_tie": True,
            "prev_wrong_min": 0,
            "prev_wrong_max": 100,
            "after_consecutive_losses": 0,
        }
        result = run_backtest(rows, "lowest_one", params, 0.7)
        self.assertEqual(result["hits"], 2)
        self.assertEqual(result["misses"], 1)

    def test_rolling_backtest_uses_real_windows(self):
        rows = [make_row(i, "大单" if i % 2 else "小双") for i in range(1, 7)]
        params = {
            "min_value_min": 0,
            "min_value_max": 100,
            "lowest_two_diff_max": 100,
            "allow_tie": True,
            "prev_wrong_min": 0,
            "prev_wrong_max": 100,
            "after_consecutive_losses": 0,
        }
        windows = run_rolling_backtest(rows, "lowest_one", params, 3, 0.7)
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[0]["start_issue"], "1001")
        self.assertEqual(windows[-1]["end_issue"], "1006")
        self.assertEqual(windows[0]["periods"], 3)


if __name__ == "__main__":
    unittest.main()
