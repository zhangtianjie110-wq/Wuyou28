from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import EXPORT_DIR
from ..database import Database
from ..import_export import create_import_template, import_file
from .widgets import secondary_button


class DataPage(QWidget):
    data_changed = Signal()

    def __init__(
        self, database: Database, capture_controller, capture_coordinator, parent=None
    ):
        super().__init__(parent)
        self.database = database
        self.capture_controller = capture_controller
        self.capture_coordinator = capture_coordinator
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("数据采集")
        title.setObjectName("PageTitle")
        hint = QLabel(
            "从已打开的“乐28”窗口只读采集。页面切换仅限 VIP 预测，"
            "不会查找或点击投注、充值、提现、支付等资金控件。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        self.capture_status = QLabel("采集器就绪")
        self.capture_status.setObjectName("Muted")
        self.capture_status.setWordWrap(True)
        root.addWidget(self.capture_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 6, 12, 6)
        content_layout.setSpacing(14)

        manual_group = QGroupBox("手动窗口采集")
        manual_layout = QHBoxLayout(manual_group)
        for source in ("VIP",):
            button = QPushButton(f"采集{source}")
            button.clicked.connect(lambda _checked=False, value=source: self._manual_capture(value))
            manual_layout.addWidget(button)
        manual_layout.addStretch()
        content_layout.addWidget(manual_group)

        queue_group = QGroupBox("YU28 开奖驱动自动采集")
        queue_layout = QVBoxLayout(queue_group)
        self.queue_status = QLabel("等待 YU28 新期开奖；不再按固定时间重复采集")
        self.queue_status.setObjectName("Muted")
        queue_layout.addWidget(self.queue_status)
        self.jobs = QTableWidget(0, 6)
        self.jobs.setHorizontalHeaderLabels(
            ["预测期号", "数据源", "状态", "尝试次数", "下次重试", "失败原因"]
        )
        self.jobs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.jobs.setSelectionBehavior(QTableWidget.SelectRows)
        self.jobs.verticalHeader().setVisible(False)
        jobs_header = self.jobs.horizontalHeader()
        jobs_header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((105, 72, 90, 82, 158)):
            jobs_header.resizeSection(column, width)
        jobs_header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.jobs.setMinimumHeight(150)
        queue_layout.addWidget(self.jobs)
        content_layout.addWidget(queue_group)

        health_group = QGroupBox("数据健康状态")
        health_layout = QVBoxLayout(health_group)
        self.health_status = QLabel("正在检查数据库完整性……")
        self.health_status.setObjectName("Muted")
        self.health_status.setWordWrap(True)
        health_layout.addWidget(self.health_status)
        content_layout.addWidget(health_group)

        completeness_group = QGroupBox("最近期号完整性（YU28 + VIP）")
        completeness_layout = QVBoxLayout(completeness_group)
        self.cycles = QTableWidget(0, 5)
        self.cycles.setHorizontalHeaderLabels(
            ["预测期号", "YU28基准期", "YU28", "VIP", "最终写入"]
        )
        self.cycles.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cycles.setSelectionBehavior(QTableWidget.SelectRows)
        self.cycles.verticalHeader().setVisible(False)
        cycle_header = self.cycles.horizontalHeader()
        cycle_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cycles.setMinimumHeight(165)
        completeness_layout.addWidget(self.cycles)
        content_layout.addWidget(completeness_group)

        logs_group = QGroupBox("最近采集日志")
        logs_layout = QVBoxLayout(logs_group)
        self.logs = QTableWidget(0, 7)
        self.logs.setHorizontalHeaderLabels(
            ["时间", "模式", "类型", "预测期号", "读取方式", "状态", "说明"]
        )
        self.logs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.logs.setSelectionBehavior(QTableWidget.SelectRows)
        self.logs.verticalHeader().setVisible(False)
        header = self.logs.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((154, 82, 62, 92, 112, 68)):
            header.resizeSection(column, width)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.logs.setMinimumHeight(210)
        logs_layout.addWidget(self.logs)
        content_layout.addWidget(logs_group)

        tools_group = QGroupBox("文件导入")
        tools_layout = QVBoxLayout(tools_group)
        tools = QHBoxLayout()
        import_button = QPushButton("导入 Excel / CSV")
        template_button = QPushButton("下载导入模板")
        secondary_button(template_button)
        import_button.clicked.connect(self._import)
        template_button.clicked.connect(self._template)
        tools.addWidget(import_button)
        tools.addWidget(template_button)
        tools.addStretch()
        tools_layout.addLayout(tools)
        content_layout.addWidget(tools_group)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.capture_controller.status_changed.connect(self.capture_status.setText)
        self.capture_controller.logs_changed.connect(self.refresh_logs)
        self.capture_coordinator.status_changed.connect(self.queue_status.setText)
        self.capture_coordinator.runtime_state_changed.connect(self._runtime_state_changed)
        self.capture_coordinator.jobs_changed.connect(self.refresh_jobs)
        self.refresh_logs()
        self.refresh_jobs()
        self.refresh_health()

    def _manual_capture(self, source: str) -> None:
        self.capture_controller.collect(source, "手动")

    def refresh(self) -> None:
        self.refresh_logs()
        self.refresh_jobs()
        self.refresh_cycles()
        self.refresh_health()

    def refresh_health(self) -> None:
        summary = self.database.integrity_summary()
        self.health_status.setText(
            "总期数 {total_periods} · complete {complete} · partial {partial} · "
            "missing {missing} · 重复 {duplicate_count} · 错期 {wrong_issue_count} · "
            "待补 {pending_count}".format(**summary)
        )

    def _runtime_state_changed(self, state: str) -> None:
        if not self.capture_coordinator.runtime_state:
            return
        current = self.queue_status.text()
        if not current.startswith(f"{state}："):
            self.queue_status.setText(state if current == "" else f"{state}：{current}")

    def refresh_jobs(self) -> None:
        if not self.isVisible():
            return
        labels = {
            "pending": "待处理",
            "collecting": "采集中",
            "success": "成功",
            "failed": "失败",
            "retrying": "等待重试",
        }
        records = self.database.list_capture_jobs(50)
        self.jobs.setUpdatesEnabled(False)
        try:
            self.jobs.setRowCount(len(records))
            for row, record in enumerate(records):
                values = [
                    record["issue_no"],
                    record["source_type"],
                    labels.get(record["status"], record["status"]),
                    record["attempts"],
                    record["next_retry_at"].replace("T", " ") or "—",
                    record["last_error"] or "—",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 5:
                        item.setToolTip(str(value))
                    self.jobs.setItem(row, column, item)
        finally:
            self.jobs.setUpdatesEnabled(True)
        self.refresh_cycles()
        self.refresh_health()

    def refresh_cycles(self) -> None:
        if not self.isVisible():
            return
        labels = {
            "pending": "等待",
            "collecting": "采集中",
            "retrying": "重试中",
            "failed": "失败",
            "success": "成功",
            "complete": "完整写入",
            "incomplete": "未完整",
        }
        records = self.database.list_capture_cycles(10)
        self.cycles.setUpdatesEnabled(False)
        try:
            self.cycles.setRowCount(len(records))
            for row, record in enumerate(records):
                values = [
                    record["prediction_issue"],
                    record["trigger_issue"],
                    labels.get(record["yu28_status"], record["yu28_status"]),
                    labels.get(record["vip_status"], record["vip_status"]),
                    labels.get(record["final_status"], record["final_status"]),
                ]
                for column, value in enumerate(values):
                    self.cycles.setItem(row, column, QTableWidgetItem(str(value)))
        finally:
            self.cycles.setUpdatesEnabled(True)

    def refresh_logs(self) -> None:
        if not self.isVisible():
            return
        records = self.database.list_collection_logs(50)
        self.logs.setUpdatesEnabled(False)
        try:
            self.logs.setRowCount(len(records))
            for row, record in enumerate(records):
                values = [
                    record["created_at"].replace("T", " "),
                    record["mode"],
                    record["source_type"],
                    record["issue_no"] or "—",
                    record["read_method"] or "—",
                    record["status"],
                    record["message"],
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 6:
                        item.setToolTip(str(value))
                    self.logs.setItem(row, column, item)
        finally:
            self.logs.setUpdatesEnabled(True)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入历史数据或开奖结果", "", "数据文件 (*.xlsx *.xlsm *.csv)"
        )
        if not path:
            return
        try:
            summary = import_file(self.database, path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self.data_changed.emit()
        errors = "\n".join(summary["errors"][:8])
        extra = f"\n\n前几项问题：\n{errors}" if errors else ""
        QMessageBox.information(
            self,
            "导入完成",
            f"新增 {summary['added']} 条，更新 {summary['updated']} 条，跳过 {summary['skipped']} 条。{extra}",
        )

    def _template(self) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        default = str(EXPORT_DIR / "乐28导入模板.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存导入模板", default, "Excel 文件 (*.xlsx);;CSV 文件 (*.csv)"
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".xlsx"
        try:
            create_import_template(path)
            QMessageBox.information(self, "模板已保存", f"模板已保存到：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
