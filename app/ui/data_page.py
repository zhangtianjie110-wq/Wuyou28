from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
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
from ..data_integrity import DataIntegrityAuditor
from .widgets import secondary_button


class DataPage(QWidget):
    """Read-only data health page for the strategy-first runtime.

    The legacy constructor arguments are accepted so older navigation wiring
    remains source-compatible, but they are intentionally ignored.
    """

    data_changed = Signal()

    def __init__(self, database: Database, *legacy_args, parent=None):
        super().__init__(parent)
        del legacy_args
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("数据中心")
        title.setObjectName("PageTitle")
        hint = QLabel("查看 YU28 历史数据与 VIP100_HISTORY 预测健康状态。")
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 6, 12, 6)
        content_layout.setSpacing(14)

        health_group = QGroupBox("数据健康状态")
        health_layout = QVBoxLayout(health_group)
        self.health_status = QLabel("正在检查数据完整性……")
        self.health_status.setObjectName("Muted")
        self.health_status.setWordWrap(True)
        health_layout.addWidget(self.health_status)
        content_layout.addWidget(health_group)

        period_group = QGroupBox("最近历史期号")
        period_layout = QVBoxLayout(period_group)
        self.periods = QTableWidget(0, 5)
        self.periods.setHorizontalHeaderLabels(
            ["期号", "YU28开奖", "VIP预测", "结果", "更新时间"]
        )
        self.periods.setEditTriggers(QTableWidget.NoEditTriggers)
        self.periods.setSelectionBehavior(QTableWidget.SelectRows)
        self.periods.verticalHeader().setVisible(False)
        self.periods.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.periods.setMinimumHeight(220)
        period_layout.addWidget(self.periods)
        content_layout.addWidget(period_group)

        tools_group = QGroupBox("数据工具")
        tools_layout = QVBoxLayout(tools_group)
        import_button = QPushButton("导入 Excel / CSV")
        template_button = QPushButton("下载导入模板")
        secondary_button(template_button)
        import_button.clicked.connect(self._import)
        template_button.clicked.connect(self._template)
        tools_layout.addWidget(import_button)
        tools_layout.addWidget(template_button)
        content_layout.addWidget(tools_group)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.refresh()

    def refresh(self) -> None:
        self.refresh_health()
        self.refresh_periods()

    def refresh_health(self) -> None:
        try:
            result = DataIntegrityAuditor(self.database).audit(auto_queue=False)
            summary = result["summary"]
            self.health_status.setText(
                "YU28期数 {total_periods} · 完整 {complete} · 部分 {partial} · "
                "缺失 {missing} · 未处理任务 {pending_count}".format(**summary)
            )
        except Exception as exc:
            self.health_status.setText(f"数据健康检查失败：{exc}")

    def refresh_periods(self) -> None:
        draws = self.database.list_yu28_draws(20)
        predictions = {
            str(row["issue_no"]): row
            for row in self.database.list_predictions_for_integrity()
            if str(row["source_type"]) == "VIP"
        }
        rows = list(reversed(draws))
        self.periods.setRowCount(len(rows))
        for row_index, draw in enumerate(rows):
            issue = str(draw["nbr"])
            prediction = predictions.get(issue)
            values = [
                issue,
                str(draw.get("number") or "—"),
                "有" if prediction else "缺失",
                str(prediction.get("actual_result") or "未回填") if prediction else "—",
                str(draw.get("created_at") or draw.get("time") or "—").replace("T", " "),
            ]
            for column, value in enumerate(values):
                self.periods.setItem(row_index, column, QTableWidgetItem(value))

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
        self.refresh()

    def _template(self) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        default = str(EXPORT_DIR / "YU28导入模板.xlsx")
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


__all__ = ["DataPage"]
