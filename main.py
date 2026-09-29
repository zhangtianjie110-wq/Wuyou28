from __future__ import annotations

import sys
import tempfile
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QCoreApplication, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.constants import APP_NAME, APP_VERSION
from app.database import Database
from app.deployment import configure_logging, log_startup_failure, prepare_runtime, resource_path
from app.update_manager import UpdateInfo, UpdateManager
from app.ui.main_window import MainWindow
from app.ui.theme import APP_STYLE


_ACTIVE_UPDATE_TASKS = set()


class _UpdateCheckSignals(QObject):
    finished = Signal(object)


class _UpdateCheckTask(QRunnable):
    def __init__(self, manager: UpdateManager):
        super().__init__()
        self.setAutoDelete(False)
        self.manager = manager
        self.signals = _UpdateCheckSignals(QCoreApplication.instance())

    def run(self) -> None:
        self.signals.finished.emit(self.manager.check())


def _start_update_check(application: QApplication, window: MainWindow) -> None:
    if not getattr(sys, "frozen", False):
        return
    manager = UpdateManager(
        current_version=APP_VERSION,
        executable=sys.executable,
        local_version_path=resource_path("version.json"),
    )
    if not manager.manifest_url:
        return
    task = _UpdateCheckTask(manager)
    _ACTIVE_UPDATE_TASKS.add(task)

    def finish(info: UpdateInfo | None) -> None:
        _ACTIVE_UPDATE_TASKS.discard(task)
        if info is None:
            return
        answer = QMessageBox.question(
            window,
            "发现新版本",
            f"发现新版本：{info.latest_version}\n"
            f"当前版本：{info.current_version}\n"
            "是否更新？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            manager._log(f"PROMPT_DECLINED current={info.current_version} latest={info.latest_version}")
            return
        try:
            manager.schedule_update(info)
        except Exception as exc:
            manager._log(
                f"UPDATE_FAILED current={info.current_version} latest={info.latest_version} "
                f"error={type(exc).__name__}: {exc}"
            )
            QMessageBox.critical(window, "更新失败", f"更新未完成，当前版本保持不变。\n{exc}")
            return
        application.quit()

    task.signals.finished.connect(finish)
    QThreadPool.globalInstance().start(task)


def self_test() -> int:
    path = Path(tempfile.gettempdir()) / "wuyou28_packaged_self_test.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    try:
        database = Database(path)
        record_id = database.add_prediction(
            {
                "issue_no": "3485504",
                "source_type": "VIP",
                "plan_count": 100,
                "big_single": 25,
                "big_double": 25,
                "small_single": 25,
                "small_double": 25,
            }
        )
        database.save_yu28_draw(
            {
                "nbr": "3485503",
                "time": "2026-09-29 00:00:00",
                "number": "8+2+5=15",
                "combination": "大单",
                "countdown": "",
            }
        )
        if database.get_prediction(record_id) is None:
            raise RuntimeError("核心数据库自检未能读取预测记录")
        if database.find_yu28_draw("3485503") is None:
            raise RuntimeError("核心数据库自检未能读取 YU28 开奖记录")
        return 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()


def run_strategy_auto_once() -> int:
    from strategy_lab.auto_runner import StrategyAutoRunner

    try:
        result = StrategyAutoRunner().run_now()
    except Exception:
        logging.getLogger(__name__).exception("策略自动实验失败")
        return 1
    logging.getLogger(__name__).info(
        "策略自动实验完成 run_id=%s candidates=%s pass=%s fail=%s",
        result.run_id,
        result.search_count,
        result.pass_count,
        result.fail_count,
    )
    return 0


def main() -> int:
    prepare_runtime()
    configure_logging()
    logging.getLogger(__name__).info("启动 %s %s", APP_NAME, APP_VERSION)
    if "--self-test" in sys.argv:
        return self_test()
    if "--strategy-auto-run" in sys.argv:
        return run_strategy_auto_once()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    icon = resource_path("wuyou28.svg")
    if icon.exists():
        application.setWindowIcon(QIcon(str(icon)))
    application.setStyle("Fusion")
    application.setStyleSheet(APP_STYLE)
    ui_only = "--ui-only" in sys.argv or "--frontend" in sys.argv
    if ui_only:
        # Frontend mode reads live data through IntegrationGateway.
        isolated_dir = Path(tempfile.mkdtemp(prefix="wuyou28-ui-only-"))
        database = Database(isolated_dir / "ui_only.db")
    else:
        database = Database()

    window = MainWindow(
        database,
        ui_only=ui_only,
    )
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))
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
    QTimer.singleShot(2500, lambda: _start_update_check(application, window))
    return application.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log_startup_failure(exc)
        raise
