from __future__ import annotations

from dataclasses import dataclass
import unittest

from app.history_analytics import DIMENSION_OBJECTS, MAX_HISTORY_WINDOW
from app.history_analytics.engine import HistoryAnalyticsEngine


def row(issue: int | str, value) -> dict:
    return {
        "issue": str(issue),
        "number": value if isinstance(value, str) else f"0+0+{value}={value}",
        "draw_time": f"2026-09-27 00:{int(issue) % 60:02d}:00" if str(issue).isdigit() else "",
    }


class MutableHistorySource:
    def __init__(self, rows):
        self.rows = list(rows)
        self.history_calls = 0
        self.since_calls = 0

    def history(self, limit=500000):
        self.history_calls += 1
        return list(self.rows[-limit:])

    def since(self, issue, limit=500000):
        self.since_calls += 1
        marker = int(issue)
        return [item for item in self.rows if str(item.get("issue", "")).isdigit() and int(item["issue"]) > marker][:limit]

    def latest(self):
        valid = [item for item in self.rows if str(item.get("issue", "")).isdigit()]
        return max(valid, key=lambda item: int(item["issue"])) if valid else None


def record(snapshot: dict, object_name: str) -> dict:
    return next(item for item in snapshot["records"] if item["object"] == object_name)


class HistoryAnalyticsEngineTests(unittest.TestCase):
    def test_fixed_dataset_omission_definition_and_off_by_one(self):
        values = [0, 1, 1, 0, 1, 1, 1, 0, 1, 1]
        source = MutableHistorySource(row(100 + index, value) for index, value in enumerate(values))
        engine = HistoryAnalyticsEngine(source)
        zero = record(engine.omission("NUMBER", "ALL"), "0")
        self.assertEqual(2, zero["current_omission"])
        self.assertEqual(2.5, zero["average_omission"])
        self.assertEqual(3, zero["maximum_omission"])
        self.assertEqual(0.8, zero["over_average_ratio"])
        self.assertEqual(50.0, zero["historical_percentile"])
        self.assertEqual(2, zero["completed_cycles"])

        incremental = MutableHistorySource([row(1, 0)])
        incremental_engine = HistoryAnalyticsEngine(incremental)
        observed = [record(incremental_engine.omission("NUMBER", "ALL"), "0")["current_omission"]]
        for issue in (2, 3, 4):
            incremental.rows.append(row(issue, 1))
            observed.append(record(incremental_engine.omission("NUMBER", "ALL"), "0")["current_omission"])
        self.assertEqual([0, 1, 2, 3], observed)

    def test_all_dimensions_share_the_same_framework(self):
        source = MutableHistorySource(row(index + 1, index) for index in range(28))
        engine = HistoryAnalyticsEngine(source)
        self.assertEqual(tuple(str(value) for value in range(28)), DIMENSION_OBJECTS["NUMBER"])
        self.assertEqual(28, len(engine.omission("NUMBER", "ALL")["records"]))
        self.assertEqual({"大", "小"}, {item["object"] for item in engine.omission("BIG_SMALL", "ALL")["records"]})
        self.assertEqual({"单", "双"}, {item["object"] for item in engine.omission("ODD_EVEN", "ALL")["records"]})
        self.assertEqual(
            {"大单", "大双", "小单", "小双"},
            {item["object"] for item in engine.omission("FOUR_COMBINATIONS", "ALL")["records"]},
        )
        self.assertEqual(0, record(engine.omission("NUMBER", "ALL"), "27")["current_omission"])

    def test_hot_cold_windows_baseline_deviation_and_exact_boundaries(self):
        values = list(range(28)) + [0] * 12
        engine = HistoryAnalyticsEngine(
            MutableHistorySource(row(1000 + index, value) for index, value in enumerate(values))
        )
        recent_30 = record(engine.hot_cold("NUMBER", 30), "0")
        self.assertEqual(30, recent_30["actual_samples"])
        self.assertEqual(12, recent_30["occurrences"])
        self.assertAlmostEqual(0.4, recent_30["rate"])
        self.assertAlmostEqual(13 / 40, recent_30["baseline_rate"])
        self.assertAlmostEqual(0.4 - 13 / 40, recent_30["deviation"])
        self.assertIsNotNone(recent_30["historical_percentile"])

        for requested in (100, 1000):
            insufficient = record(engine.hot_cold("NUMBER", requested), "0")
            self.assertEqual(40, insufficient["actual_samples"])
            self.assertEqual(13, insufficient["occurrences"])
            self.assertAlmostEqual(13 / 40, insufficient["rate"])
        self.assertEqual(12, sum(item["object"] == "0" for item in [
            {"object": str(value)} for value in values[-30:]
        ]))
        self.assertEqual(MAX_HISTORY_WINDOW, engine.max_history)

    def test_hot_cold_status_uses_percentile_and_relative_baseline(self):
        values = [0, 15] * 35 + [15] * 30
        engine = HistoryAnalyticsEngine(
            MutableHistorySource(row(2000 + index, value) for index, value in enumerate(values))
        )
        snapshot = engine.hot_cold("BIG_SMALL", 30)
        self.assertEqual("极热", record(snapshot, "大")["status"])
        self.assertEqual("极冷", record(snapshot, "小")["status"])
        self.assertGreaterEqual(record(snapshot, "大")["historical_percentile"], 95.0)
        self.assertLessEqual(record(snapshot, "小")["historical_percentile"], 5.0)

    def test_quality_detects_gaps_duplicates_and_abnormal_records(self):
        source = MutableHistorySource(
            [row(1, 0), row(2, 1), row(2, 1), row(4, 2), row("bad", 3), row(5, 30)]
        )
        engine = HistoryAnalyticsEngine(source)
        quality = engine.quality("ALL")
        self.assertEqual(3, quality["valid_records"])
        self.assertEqual(3, quality["analysis_samples"])
        self.assertEqual(1, quality["missing_issues"])
        self.assertEqual(1, quality["duplicate_records"])
        self.assertEqual(2, quality["abnormal_records"])
        self.assertEqual("DATA_GAP", quality["status"])
        self.assertEqual("1", quality["start_issue"])
        self.assertEqual("4", quality["latest_issue"])

    def test_incremental_update_and_cache_rebuild(self):
        source = MutableHistorySource([row(1, 0), row(2, 1)])
        engine = HistoryAnalyticsEngine(source)
        first = engine.hot_cold("NUMBER", 30)
        second = engine.hot_cold("NUMBER", 30)
        self.assertIs(first, second)
        self.assertEqual(1, source.history_calls)
        source.rows.append(row(3, 2))
        updated = engine.hot_cold("NUMBER", 30)
        self.assertEqual(3, updated["actual_samples"])
        self.assertEqual(1, source.history_calls)
        self.assertEqual(1, source.since_calls)
        self.assertEqual(1, engine.cache_state["incremental_updates"])
        engine.rebuild_cache()
        rebuilt = engine.hot_cold("NUMBER", 30)
        self.assertEqual(3, rebuilt["actual_samples"])
        self.assertEqual(2, source.history_calls)
        self.assertEqual(2, engine.cache_state["full_loads"])


if __name__ == "__main__":
    unittest.main()
