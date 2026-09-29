from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.road_page import RoadPage, build_road_segments, road_stats
from app.ui.trend_page import TrendRow


def row(issue: int, *, total: int | None = None, gap: bool = False) -> TrendRow:
    if gap:
        return TrendRow(issue=str(issue), data_gap=True)
    total = int(total if total is not None else issue % 28)
    size = "大" if total >= 14 else "小"
    parity = "双" if total % 2 == 0 else "单"
    return TrendRow(
        issue=str(issue),
        total=total,
        big_small=size,
        odd_even=parity,
        combination=size + parity,
    )


class RoadPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_segments_break_on_direction_change_and_data_gap(self):
        rows = (row(1, total=1), row(2, total=2), row(3, total=20), row(4, gap=True), row(5, total=21))
        segments = build_road_segments(rows, "big_small")
        self.assertEqual(["小", "大", "DATA_GAP", "大"], [segment.direction or "DATA_GAP" for segment in segments])
        self.assertEqual([2, 1, 0, 1], [segment.length for segment in segments])
        stats = road_stats(rows, "big_small")
        self.assertEqual("大", stats["current_direction"])
        self.assertEqual(1, stats["current_streak"])
        self.assertEqual(2, stats["max_streak"])

        after_gap = road_stats((*rows, row(6, gap=True)), "big_small")
        self.assertEqual("", after_gap["current_direction"])
        self.assertEqual(0, after_gap["current_streak"])
        self.assertEqual(2, after_gap["max_streak"])

    def test_page_renders_three_roads_and_switches_ranges(self):
        class Draws:
            def recent(self, limit=30):
                return [{"issue": str(issue), "number": f"1+2+{issue % 28 - 3}={issue % 28}"} for issue in range(100, 100 + limit)]

        class Gateway:
            draws = Draws()

        page = RoadPage(Gateway())
        try:
            self.assertEqual(30, len(page.rows))
            self.assertEqual(3, page.summary_table.rowCount())
            self.assertIsNotNone(page.road_table("big_small"))
            self.assertIsNotNone(page.road_table("odd_even"))
            self.assertIsNotNone(page.road_table("combination"))
            page.range_box.setCurrentText("200")
            self.assertEqual(200, len(page.rows))
        finally:
            page.close()

    def test_data_gap_is_visible_and_page_is_read_only(self):
        class Draws:
            def recent(self, limit=30):
                return [
                    {"issue": "10", "number": "1+2+2=5"},
                    {"issue": "12", "number": "8+8+4=20"},
                ]

        class Gateway:
            draws = Draws()

        page = RoadPage(Gateway())
        try:
            self.assertEqual(1, page.data_gap_count())
            self.assertEqual(page.summary_table.EditTrigger.NoEditTriggers, page.summary_table.editTriggers())
            gap_cells = [
                page.road_table(attribute).findItems("DATA_GAP", Qt.MatchFlag.MatchExactly)
                for attribute in ("big_small", "odd_even", "combination")
            ]
            self.assertTrue(all(cells for cells in gap_cells))
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
