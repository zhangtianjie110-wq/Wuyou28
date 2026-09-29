import unittest
from pathlib import Path

from app.auto_backtest import (
    convert_prediction,
    generate_condition_candidates,
    register_condition,
    run_auto_backtest,
    run_condition_backtest,
    run_database_backtest,
    run_train_validation_backtest,
    run_walk_forward,
    scan_conditions,
    split_train_validation,
)
from app.database import Database


def row(index, source="VIP", actual="大单", counts=None):
    values = {
        "id": index,
        "issue_no": str(200000 + index),
        "source_type": source,
        "actual_result": actual,
        "big_single": 10,
        "big_double": 20,
        "small_single": 30,
        "small_double": 40,
    }
    if counts:
        values.update(counts)
    return values


class AutoBacktestTests(unittest.TestCase):
    def test_conversion_contains_all_requested_features(self):
        converted = convert_prediction(
            row(1, counts={"big_single": 2, "big_double": 8, "small_single": 2, "small_double": 20})
        )
        self.assertEqual(converted["minimum"], 2)
        self.assertEqual(converted["second_minimum"], 2)
        self.assertEqual(converted["maximum"], 20)
        self.assertEqual(converted["max_min_diff"], 18)
        self.assertEqual(converted["lowest_two"], ("大单", "小单"))
        self.assertTrue(converted["tied_min"])
        self.assertEqual(converted["ascending_rank"][0], "大单")
        self.assertEqual(converted["actual_combo"], "大单")

    def test_vip_metrics_are_reported(self):
        records = [row(i, "VIP", "大单" if i < 4 else "小双") for i in range(1, 6)]
        results = run_auto_backtest(records, {"min_groups": 1}, min_sample_size=4)
        self.assertEqual(results["VIP"]["total_periods"], 5)
        self.assertEqual(results["VIP"]["valid_samples"], 5)
        self.assertEqual(results["VIP"]["hits"], 3)
        self.assertFalse(results["VIP"]["insufficient_sample"])
        self.assertIn("30", results["VIP"]["recent"])
        self.assertEqual(results["VIP"]["current_state"], "miss")

    def test_and_conditions_and_specified_pair(self):
        records = [
            row(1, counts={"big_single": 1, "big_double": 2, "small_single": 20, "small_double": 30}),
            row(2, counts={"big_single": 5, "big_double": 6, "small_single": 20, "small_double": 30}),
        ]
        params = {
            "selected_groups": ["大单", "大双"],
            "min_value_min": 1,
            "min_value_max": 5,
            "lowest_two_diff_min": 1,
            "lowest_two_diff_max": 1,
            "max_min_diff_min": 29,
            "max_min_diff_max": 29,
            "allow_tie": False,
            "rank_relations": ["大单<大双"],
        }
        result = run_condition_backtest(records, params, source_type="VIP", min_sample_size=1)
        self.assertEqual(result["matched_periods"], 1)
        self.assertEqual(result["valid_samples"], 1)
        self.assertFalse(result["insufficient_sample"])

    def test_missing_outcome_is_excluded_without_fabrication(self):
        records = [row(1, actual=""), row(2, actual="大单")]
        result = run_condition_backtest(records, {"min_groups": 2}, source_type="VIP", min_sample_size=1)
        self.assertEqual(result["matched_periods"], 2)
        self.assertEqual(result["valid_samples"], 1)
        self.assertEqual(result["excluded_missing_outcome"], 1)
        self.assertEqual(result["details"][0]["hit"], None)

    def test_custom_condition_registry_and_database_entry_are_read_only(self):
        register_condition("minimum_even_test", lambda item: item["minimum"] % 2 == 0)
        records = [row(1, counts={"big_single": 2}), row(2, counts={"big_single": 3})]
        result = run_condition_backtest(records, {"minimum_even_test": True}, source_type="VIP", min_sample_size=1)
        self.assertEqual(result["matched_periods"], 1)
        db_path = Path(__file__).parent / ".test_data" / "auto_backtest.db"
        db_path.parent.mkdir(exist_ok=True)
        db_path.unlink(missing_ok=True)
        database = Database(db_path)
        try:
            for item in records:
                payload = dict(item)
                payload.update(
                    {
                        "plan_text": "",
                        "actual_result": "大单",
                        "big_single": 20,
                        "big_double": 20,
                        "small_single": 30,
                        "small_double": 30,
                    }
                )
                database.add_prediction(payload)
            before = len(database.list_predictions())
            result = run_database_backtest(database, {"min_groups": 1}, min_sample_size=1)
            after = len(database.list_predictions())
            self.assertEqual(before, after)
            self.assertEqual(result["VIP"]["valid_samples"], 2)
        finally:
            db_path.unlink(missing_ok=True)

    def test_time_split_excludes_partial_rows_and_never_shuffles(self):
        records = [row(index, actual="大单") for index in range(10, 0, -1)]
        records[3]["status"] = "部分失败"
        train, validation = split_train_validation(records, 0.7, source_type="VIP")
        self.assertEqual([item["issue_no"] for item in train], ["200001", "200002", "200003", "200004", "200005", "200006"])
        self.assertEqual([item["issue_no"] for item in validation], ["200008", "200009", "200010"])
        result = run_train_validation_backtest(records, {"min_groups": 1}, source_type="VIP", min_sample_size=1)
        self.assertEqual(result["selection_basis"], "training_only")
        self.assertEqual(result["train_samples"], 6)
        self.assertEqual(result["validation_samples"], 3)
        self.assertTrue(all(item["dataset"] == "训练集" for item in result["details"][:6]))
        self.assertTrue(all(item["dataset"] == "验证集" for item in result["details"][6:]))

    def test_scan_is_bounded_and_validation_is_not_used_for_selection(self):
        records = [row(index, actual="大单") for index in range(1, 21)]
        scan = scan_conditions(records, source_type="VIP", max_candidates=11, min_sample_size=1)
        self.assertEqual(scan["tested_conditions"], 11)
        self.assertEqual(scan["selection_basis"], "training_only")
        self.assertTrue(all(item["selection_basis"] == "training_only" for item in scan["results"]))
        self.assertTrue(all("conditions" in item for item in scan["results"]))
        self.assertLessEqual(len(generate_condition_candidates("VIP", max_candidates=17)), 17)

    def test_walk_forward_windows_have_strict_non_overlapping_future_boundaries(self):
        records = [row(index, actual="大单") for index in range(1, 11)]
        result = run_walk_forward(records, {"min_groups": 1}, train_window=4, validation_window=2, step=2, source_type="VIP", min_sample_size=1)
        self.assertEqual(len(result["windows"]), 3)
        for window in result["windows"]:
            train_end = int(window["train_issue_range"][1])
            validation_start = int(window["validation_issue_range"][0])
            self.assertLess(train_end, validation_start)
        self.assertEqual(result["windows"][0]["train_issue_range"], ("200001", "200004"))
        self.assertEqual(result["windows"][1]["validation_issue_range"], ("200007", "200008"))

    def test_repeatability_and_gui_default_engine_reference(self):
        records = [row(index, actual="大单") for index in range(1, 8)]
        first = run_train_validation_backtest(records, {"min_groups": 2}, source_type="VIP", min_sample_size=1)
        second = run_train_validation_backtest(records, {"min_groups": 2}, source_type="VIP", min_sample_size=1)
        self.assertEqual(first, second)
        strategy_source = Path(__file__).parents[1] / "app" / "ui" / "strategy_page.py"
        source = strategy_source.read_text(encoding="utf-8")
        self.assertIn("run_train_validation_backtest", source)
        self.assertIn("scan_conditions", source)
        self.assertIn("run_walk_forward", source)
        self.assertNotIn("from ..backtest import", source)


if __name__ == "__main__":
    unittest.main()
