from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.trend_page import TrendPage, build_trend_rows


def draw(issue: int, number: int) -> dict:
    return {"issue": str(issue), "number": f"1+2+{number - 3}={number}"}


class FakeDraws:
    def recent(self, limit=30):
        return [draw(issue, issue % 28) for issue in range(100, 100 + limit)]


class FakeGateway:
    draws = FakeDraws()


class TrendPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_renders_draws_and_range_switch(self):
        page = TrendPage(FakeGateway())
        try:
            self.assertEqual(30, page.visible_draw_count())
            self.assertEqual(10, page.draw_table.columnCount())
            self.assertEqual(
                ["期号", "开奖", "大", "小", "单", "双", "大单", "大双", "小单", "小双"],
                [page.draw_table.horizontalHeaderItem(column).text() for column in range(10)],
            )
            self.assertEqual(30, int(page.big_count_label.text()) + int(page.small_count_label.text()))
            self.assertEqual(30, int(page.odd_count_label.text()) + int(page.even_count_label.text()))
            self.assertFalse(hasattr(page, "size_sequence_label"))
            self.assertFalse(hasattr(page, "parity_sequence_label"))
            self.assertTrue(page.trend_table.isHidden())
            self.assertTrue(page.draw_table.showGrid())
            self.assertEqual(29, page.trend_table.columnCount())
            page.range_box.setCurrentText("200")
            self.assertEqual(200, page.visible_draw_count())
            self.assertEqual(200, len({page.trend_table.item(row, 0).text() for row in range(page.trend_table.rowCount())}))
            self.assertEqual([str(value) for value in range(28)], [page.trend_table.horizontalHeaderItem(column).text() for column in range(1, 29)])
        finally:
            page.close()

    def test_gap_is_explicit_and_has_no_marker(self):
        rows = build_trend_rows([draw(3486465, 5), draw(3486467, 6)], 30)
        self.assertEqual(1, sum(row.data_gap for row in rows))
        class GapDraws:
            def recent(self, limit=30):
                return [draw(3486465, 5), draw(3486467, 6)]
        class GapGateway:
            draws = GapDraws()
        page = TrendPage(GapGateway())
        try:
            self.assertEqual(1, page.data_gap_count())
            gap_row = next(index for index, row in enumerate(page.rows) if row.data_gap)
            self.assertEqual("DATA_GAP", page.trend_table.item(gap_row, 0).text())
            self.assertTrue(all(not page.trend_table.item(gap_row, column).text() for column in range(1, 29)))
        finally:
            page.close()

    def test_page_is_read_only(self):
        page = TrendPage(FakeGateway())
        try:
            self.assertEqual(page.draw_table.EditTrigger.NoEditTriggers, page.draw_table.editTriggers())
            self.assertEqual(page.trend_table.EditTrigger.NoEditTriggers, page.trend_table.editTriggers())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
