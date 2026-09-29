from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.widgets import PageHeader

from .auto_runner import AutoRunResult, StrategyAutoRunner


class _AutoRunWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, runner: StrategyAutoRunner):
        super().__init__()
        self.runner = runner

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.runner.run_now())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class StrategyAutoPage(QWidget):
    data_changed = Signal()

    def __init__(
        self,
        database_path: str | Path,
        parent=None,
        *,
        runner: StrategyAutoRunner | None = None,
    ):
        super().__init__(parent)
        source_path = Path(database_path)
        self.runner = runner or StrategyAutoRunner(
            lab_db_path=source_path.parent / "strategy_lab.db",
        )
        self._thread: QThread | None = None
        self._worker: _AutoRunWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(10)
        root.addWidget(PageHeader("策略自动运行", "每日自动检查数据、执行实验并生成报告"))

        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        for column, title in enumerate(("当前状态", "上次运行时间", "下次运行时间")):
            label = QLabel(title)
            label.setObjectName("CardTitle")
            grid.addWidget(label, 0, column)
        self.status_value = QLabel("待机")
        self.last_run_value = QLabel("尚未运行")
        self.next_run_value = QLabel("-")
        for column, value in enumerate(
            (self.status_value, self.last_run_value, self.next_run_value)
        ):
            value.setObjectName("CardValue")
            value.setWordWrap(True)
            grid.addWidget(value, 1, column)
        root.addWidget(card)

        report = QFrame()
        report.setObjectName("Card")
        report_layout = QVBoxLayout(report)
        report_layout.setContentsMargins(18, 14, 18, 14)
        report_layout.addWidget(QLabel("最新报告"))
        self.report_value = QLabel("尚未生成")
        self.report_value.setObjectName("Muted")
        self.report_value.setWordWrap(True)
        report_layout.addWidget(self.report_value)
        root.addWidget(report)

        self.run_button = QPushButton("立即运行")
        self.run_button.setObjectName("PrimaryAction")
        self.run_button.setFixedWidth(120)
        self.run_button.clicked.connect(self.run_now)
        root.addWidget(self.run_button)
        self.message = QLabel("自动任务默认每天 02:30 执行")
        self.message.setObjectName("Muted")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        root.addStretch()

    def refresh(self) -> None:
        last = self.runner.get_last_run()
        if last:
            self.status_value.setText("运行成功" if last["status"] == "PASS" else "运行失败")
            self.last_run_value.setText(str(last.get("finished_at") or last.get("started_at") or "-"))
            report = str(last.get("report_html") or last.get("report_json") or "")
            self.report_value.setText(report or "尚未生成")
            if last.get("error_message"):
                self.message.setText(str(last["error_message"]))
        self.next_run_value.setText(
            self.runner.get_next_run().isoformat(sep=" ", timespec="minutes")
        )

    @Slot()
    def run_now(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.status_value.setText("运行中")
        self.message.setText("正在执行数据检查与策略实验…")
        self.run_button.setEnabled(False)
        self._thread = QThread(self)
        self._worker = _AutoRunWorker(self.runner)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._finished)
        self._thread.start()

    @Slot(object)
    def _completed(self, result: AutoRunResult) -> None:
        self.status_value.setText("运行成功")
        self.last_run_value.setText(result.finished_at)
        self.report_value.setText(result.report_html)
        self.message.setText(
            f"候选 {result.search_count}，PASS {result.pass_count}，FAIL {result.fail_count}"
        )
        self.data_changed.emit()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.status_value.setText("运行失败")
        self.message.setText(message)

    @Slot()
    def _finished(self) -> None:
        self.run_button.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.refresh()


__all__ = ["StrategyAutoPage"]
