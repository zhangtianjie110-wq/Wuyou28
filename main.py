from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from app.constants import APP_NAME
from app.database import Database
from app.ui.main_window import MainWindow
from app.ui.theme import APP_STYLE


def self_test() -> int:
    from app.capture import parse_prediction_text

    path = Path(tempfile.gettempdir()) / "le28_predictor_packaged_self_test.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    try:
        database = Database(path)
        parse_prediction_text(
            "3485504 期\n8+2+5=15\n已保存算法\n大单 25\n大双 25\n小单 25\n小双 25\n共 100",
            "VIP",
        )
        database.add_collection_log(
            issue_no="3485504",
            source_type="VIP",
            mode="自检",
            read_method="UI Automation",
            status="成功",
            message="打包自检",
        )
        return 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setStyle("Fusion")
    application.setStyleSheet(APP_STYLE)
    ui_only = "--ui-only" in sys.argv or "--frontend" in sys.argv
    if ui_only:
        # Frontend mode reads live data through IntegrationGateway. Legacy
        # operational pages receive an isolated DB and own no running services.
        isolated_dir = Path(tempfile.mkdtemp(prefix="wuyou28-ui-only-"))
        database = Database(isolated_dir / "ui_only.db")
    else:
        database = Database()
    window = MainWindow(database, ui_only=ui_only)
    screen = application.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        window.move(area.center() - window.rect().center())
    window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    window.show()
    QTimer.singleShot(150, lambda: (window.raise_(), window.activateWindow()))

    def release_topmost() -> None:
        window.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        window.show()
        window.raise_()
        window.activateWindow()

    QTimer.singleShot(5000, release_topmost)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
