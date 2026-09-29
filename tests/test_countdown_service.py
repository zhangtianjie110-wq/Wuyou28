from __future__ import annotations

import os
from datetime import datetime, timedelta
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.countdown_service import CountdownService
from app.integration.models import DrawRecord


class CountdownServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_yu28_countdown_is_published(self):
        service = CountdownService()
        values = []
        service.changed.connect(lambda text, expected: values.append((text, expected)))
        service.set_draw(
            DrawRecord("1", "", "1+1+1=3", "小单", countdown="02:05")
        )
        self.assertIn(values[-1][0], {"02:04", "02:05"})
        self.assertRegex(values[-1][1], r"^\d{2}:\d{2}$")
        service.stop()

    def test_empty_record_reports_waiting_data(self):
        service = CountdownService()
        values = []
        service.changed.connect(lambda text, _expected: values.append(text))
        service.clear()
        self.assertEqual(values[-1], "等待数据")
        service.stop()

    def test_draw_time_is_used_when_countdown_is_missing(self):
        service = CountdownService()
        service.set_draw(
            DrawRecord(
                "1",
                (datetime.now().astimezone() - timedelta(seconds=30)).isoformat(),
                "1+1+1=3",
                "小单",
            )
        )
        self.assertIsNotNone(service.seconds_remaining)
        self.assertGreater(service.seconds_remaining, 200)
        service.stop()


if __name__ == "__main__":
    unittest.main()
