from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.database import Database
from app.ui.data_page import DataPage


class StrategyModePageTests(unittest.TestCase):
    def test_data_page_is_read_only_health_view(self):
        path = Path(tempfile.gettempdir()) / "wuyou28_strategy_mode_page.db"
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        application = QApplication.instance() or QApplication([])
        page = DataPage(Database(path))
        self.assertFalse(hasattr(page, "jobs"))
        self.assertFalse(hasattr(page, "cycles"))
        self.assertFalse(hasattr(page, "logs"))
        self.assertIn("YU28期数", page.health_status.text())
        page.close()
        application.processEvents()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
