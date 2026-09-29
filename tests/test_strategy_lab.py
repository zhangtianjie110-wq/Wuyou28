import unittest
from pathlib import Path

from app.database import Database
from app.strategy_lab import (
    StrategyLabStore,
    choose_lab_plan,
    dataset_hash,
    evaluate_forward_profile,
    generate_lab_candidates,
    generate_vip100_candidates,
    rule_hash,
    run_strategy_lab_scan,
    run_vip100_strategy_search,
    strategy_version_id,
)


def record(index, source="VIP", actual="大单"):
    return {
        "id": index,
        "issue_no": str(300000 + index),
        "source_type": source,
        "big_single": 10,
        "big_double": 20,
        "small_single": 30,
        "small_double": 40,
        "actual_result": actual,
    }


class StrategyLabTests(unittest.TestCase):
    def test_dataset_hash_is_stable_and_excludes_storage_metadata(self):
        rows = [record(2), record(1)]
        first = dataset_hash(rows)
        rows[0]["id"] = 99999
        rows[0]["created_at"] = "2026-09-27T00:00:00"
        self.assertEqual(first, dataset_hash(rows))
        self.assertNotEqual(first, dataset_hash([record(1), {**record(2), "actual_result": "小双"}]))

    def test_rule_and_strategy_version_ids_are_separate_and_deterministic(self):
        conditions = {"min_groups": 1, "selected_groups": ["小双", "大单"]}
        same_rule = rule_hash({"selected_groups": ["大单", "小双"], "min_groups": 1})
        self.assertEqual(rule_hash(conditions), same_rule)
        first = strategy_version_id(same_rule, dataset_hash="dataset-a", freeze_config={"issue": "1"})
        second = strategy_version_id(same_rule, dataset_hash="dataset-a", freeze_config={"issue": "1"})
        changed_context = strategy_version_id(same_rule, dataset_hash="dataset-b", freeze_config={"issue": "1"})
        self.assertEqual(first, second)
        self.assertNotEqual(same_rule, first)
        self.assertNotEqual(first, changed_context)

    def test_run_manifest_and_candidate_fields_are_persisted(self):
        rows = [record(index) for index in range(1, 13)]
        result = run_strategy_lab_scan(rows, source_type="VIP", max_candidates=2, minimum_trigger=1)
        path = Path(__file__).parent / ".test_data" / "strategy_lab_manifest.db"
        path.parent.mkdir(exist_ok=True)
        path.unlink(missing_ok=True)
        try:
            store = StrategyLabStore(path)
            legacy_run_id = store.save_run(result)
            self.assertGreater(legacy_run_id, 0)
            with store.connect() as db:
                manifest = db.execute("SELECT * FROM strategy_lab_runs WHERE run_id=?", (result["run_id"],)).fetchone()
                candidate = db.execute("SELECT * FROM lab_candidates WHERE run_id=?", (legacy_run_id,)).fetchone()
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest["dataset_hash"], result["dataset_hash"])
            self.assertEqual(manifest["dataset_rows"], 12)
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["rule_hash"], result["results"][0]["rule_hash"])
            self.assertEqual(candidate["rule_json"], candidate["conditions_json"])
            self.assertIn("status", candidate.keys())
        finally:
            path.unlink(missing_ok=True)

    def test_adaptive_plans_for_current_sample_sizes(self):
        self.assertEqual(choose_lab_plan(99)["mode"], "basic")
        plan = choose_lab_plan(117)
        self.assertEqual((plan["train_window"], plan["validation_window"], plan["step"]), (60, 20, 20))
        self.assertEqual((choose_lab_plan(116)["train_window"], choose_lab_plan(116)["validation_window"]), (60, 20))
        self.assertEqual(choose_lab_plan(500)["mode"], "multi_window")

    def test_candidate_generation_is_bounded_and_covers_requested_families(self):
        candidates = generate_lab_candidates("VIP", max_candidates=128)
        self.assertLessEqual(len(candidates), 128)
        self.assertTrue(any("selected_groups" in item for item in candidates))
        self.assertTrue(any("second_min_value_min" in item for item in candidates))
        self.assertTrue(any("rank_relations" in item for item in candidates))
        self.assertTrue(any(len(item.get("and_conditions", [])) == 2 for item in candidates))
        self.assertTrue(any(len(item.get("and_conditions", [])) == 3 for item in candidates))

    def test_vip100_search_is_vip_only_fixed_70_30_and_ranked(self):
        self.assertEqual(generate_vip100_candidates(max_candidates=7), generate_lab_candidates("VIP", max_candidates=7))
        rows = [record(index, "VIP", "大单" if index % 2 else "小双") for index in range(1, 31)]
        rows.extend(record(index, "OTHER") for index in range(31, 35))
        result = run_vip100_strategy_search(rows, max_candidates=12, minimum_trigger=1, top_n=4)
        self.assertTrue(result["vip_only"])
        self.assertEqual((result["train_ratio"], result["validation_ratio"]), (0.7, 0.3))
        self.assertLessEqual(len(result["top_strategies"]), 4)
        self.assertEqual(result["top_strategies"], result["results"][:4])
        self.assertTrue(all(item["source_type"] == "VIP" for item in [result]))
        self.assertTrue(all("trigger_count" in item and "overall" in item for item in result["top_strategies"]))

    def test_vip100_search_adds_rolling_metrics_and_composite_score(self):
        rows = [
            {
                **record(index, "VIP", "大单" if index % 3 else "小双"),
                "big_single": 24,
                "big_double": 25,
                "small_single": 25,
                "small_double": 26,
            }
            for index in range(1, 151)
        ]
        result = run_vip100_strategy_search(rows, max_candidates=8, minimum_trigger=1, top_n=3)
        self.assertEqual(set(result["top_strategies"][0]["rolling"]), {"30", "50", "100"})
        for metrics in result["top_strategies"][0]["rolling"].values():
            self.assertIn("trigger_count", metrics)
            self.assertIn("hit_count", metrics)
            self.assertIn("hit_rate", metrics)
            self.assertIn("max_consecutive_errors", metrics)
        scores = [item["composite_score"] for item in result["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_vip100_search_marks_or_coverage_risk_without_changing_hits(self):
        rows = [
            {
                **record(index, "VIP", "大单" if index % 3 else "小双"),
                "big_single": 24,
                "big_double": 25,
                "small_single": 25,
                "small_double": 26,
            }
            for index in range(1, 151)
        ]
        result = run_vip100_strategy_search(rows, max_candidates=128, minimum_trigger=1, top_n=8)
        warnings = [item for item in result["results"] if item["coverage_warning"]]
        self.assertTrue(warnings)
        self.assertTrue(all(item["coverage_rate"] >= 99 for item in warnings))
        self.assertTrue(all(item["quality_status"] == "WARNING_COVERAGE" for item in warnings))
        self.assertTrue(all(item["status"] == "WARNING_COVERAGE" for item in warnings))
        self.assertTrue(all(item["coverage_risk"] == "HIGH" for item in warnings))
        self.assertTrue(all("hit_count" in item["rolling"]["30"] for item in warnings))

    def test_partial_rows_are_excluded(self):
        rows = [record(index, "VIP") for index in range(1, 13)]
        rows[2]["status"] = "部分失败"
        result = run_strategy_lab_scan(rows, source_type="VIP", max_candidates=20, minimum_trigger=2)
        self.assertEqual(result["total_valid_data"], 11)
        self.assertEqual(result["excluded_records"], 1)
        self.assertEqual(result["source_type"], "VIP")

    def test_training_filter_precedes_validation_and_small_sample_is_not_stable(self):
        rows = [record(index) for index in range(1, 30)]
        result = run_strategy_lab_scan(rows, source_type="VIP", max_candidates=8, minimum_trigger=5)
        self.assertEqual(result["validation_tested"], 0)
        self.assertTrue(all(item["status"] == "样本不足" for item in result["results"]))
        self.assertEqual(result["selection_basis"], "training_only")

    def test_frozen_profile_versions_and_forward_use_only_new_rows(self):
        rows = [record(index) for index in range(1, 11)]
        conditions = {"min_groups": 1}
        training = {"valid_samples": 5, "hit_rate": 60.0}
        validation = {"valid_samples": 2, "hit_rate": 50.0}
        path = Path(__file__).parent / ".test_data" / "strategy_lab_profile.db"
        path.parent.mkdir(exist_ok=True)
        path.unlink(missing_ok=True)
        try:
            store = StrategyLabStore(path)
            first = store.create_profile("实验", "VIP", conditions, "300005", training, validation)
            forward = evaluate_forward_profile(first, rows)
            self.assertEqual(forward["valid_samples"], 5)
            self.assertTrue(forward["conditions_frozen"])
            self.assertEqual(forward["status"], "持续观察")
            self.assertEqual(forward["conditions"], conditions)
            store.save_forward_result(first, forward)
            same = store.create_profile("实验", "VIP", conditions, "300005", training, validation)
            self.assertEqual(same["strategy_id"], first["strategy_id"])
            second = store.create_profile("实验", "VIP", {"min_groups": 2}, "300005", training, validation)
            self.assertNotEqual(second["strategy_id"], first["strategy_id"])
            self.assertEqual(second["version"], 2)
        finally:
            path.unlink(missing_ok=True)

    def test_original_database_rows_are_read_only(self):
        path = Path(__file__).parent / ".test_data" / "strategy_lab_source.db"
        path.parent.mkdir(exist_ok=True)
        path.unlink(missing_ok=True)
        try:
            db = Database(path)
            for index in range(1, 8):
                db.add_prediction({**record(index), "plan_text": ""})
            before = db.list_predictions()
            run_strategy_lab_scan(before, source_type="VIP", max_candidates=5, minimum_trigger=1)
            after = db.list_predictions()
            self.assertEqual(before, after)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
