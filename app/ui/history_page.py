from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..backup import backup_database
from ..constants import BACKUP_DIR, EXPORT_DIR
from ..database import Database, DuplicateRecordError
from ..import_export import export_history
from .record_dialog import RecordDialog
from .widgets import danger_button, secondary_button


class HistoryPage(QWidget):
    data_changed = Signal()

    HEADERS = [
        ("预测期号", "issue_no"),
        ("类型", "source_type"),
        ("大单", "big_single"),
        ("大双", "big_double"),
        ("小单", "small_single"),
        ("小双", "small_double"),
        ("实际结果", "actual_result"),
        ("正确", "correct_count"),
        ("错误", "wrong_count"),
        ("最低两项", "lowest_two"),
        ("差值", "lowest_two_diff"),
        ("状态", "status"),
    ]

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.records: list[dict] = []
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        title = QLabel("历史数据")
        title.setObjectName("PageTitle")
        hint = QLabel("搜索、筛选和修正历史记录；待检查与无效数据默认不参与回测。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索期号、计划或开奖结果")
        self.source_filter = QComboBox()
        self.source_filter.addItems(["全部", "VIP"])
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "正常", "待开奖", "待检查", "无效"])
        refresh_button = QPushButton("刷新")
        secondary_button(refresh_button)
        filters.addWidget(self.search, 2)
        filters.addWidget(self.source_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(refresh_button)
        root.addLayout(filters)

        actions = QHBoxLayout()
        add_button = QPushButton("补录数据")
        edit_button = QPushButton("修改选中记录")
        invalid_button = QPushButton("标记无效 / 恢复")
        delete_button = QPushButton("删除选中")
        cleanup_button = QPushButton("清理非正常")
        export_button = QPushButton("导出当前列表")
        secondary_button(export_button)
        danger_button(invalid_button)
        danger_button(delete_button)
        danger_button(cleanup_button)
        actions.addWidget(add_button)
        actions.addWidget(edit_button)
        actions.addWidget(invalid_button)
        actions.addWidget(delete_button)
        actions.addWidget(cleanup_button)
        actions.addWidget(export_button)
        actions.addStretch()
        root.addLayout(actions)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([item[0] for item in self.HEADERS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((105, 62, 62, 62, 62, 62, 78, 62, 62, 115, 62)):
            header.resizeSection(column, width)
        header.setSectionResizeMode(len(self.HEADERS) - 1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        self.source_filter.currentTextChanged.connect(self.refresh)
        self.status_filter.currentTextChanged.connect(self.refresh)
        refresh_button.clicked.connect(self.refresh)
        add_button.clicked.connect(self._add)
        edit_button.clicked.connect(self._edit)
        invalid_button.clicked.connect(self._toggle_invalid)
        delete_button.clicked.connect(self._delete_selected)
        cleanup_button.clicked.connect(self._delete_non_normal)
        export_button.clicked.connect(self._export)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.refresh()

    def _add(self) -> None:
        dialog = RecordDialog(parent=self)
        if dialog.exec() != RecordDialog.Accepted:
            return
        try:
            record_id = self.database.add_prediction(dialog.payload())
            record = self.database.get_prediction(record_id)
        except DuplicateRecordError as exc:
            QMessageBox.warning(self, "重复数据", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "补录失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()
        status = record["status"] if record else "未知"
        detail = f"\n{record['invalid_reason']}" if record and record["invalid_reason"] else ""
        QMessageBox.information(self, "补录成功", f"记录已保存，状态：{status}{detail}")

    def refresh(self) -> None:
        self.search_timer.stop()
        self.records = self.database.list_predictions(
            search=self.search.text(),
            source_type=self.source_filter.currentText(),
            status=self.status_filter.currentText(),
        )
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self.records))
            for row_index, record in enumerate(self.records):
                for column, (_, field) in enumerate(self.HEADERS):
                    value = record.get(field)
                    text = "" if value is None else str(value)
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, record["id"])
                    if field == "status":
                        colors = {
                            "正常": "#16834B",
                            "待开奖": "#8A6500",
                            "待检查": "#C26A00",
                            "无效": "#B43B3B",
                        }
                        item.setForeground(QColor(colors.get(text, "#334155")))
                    self.table.setItem(row_index, column, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择记录", "请先选择一条历史记录。")
            return None
        return int(self.table.item(row, 0).data(Qt.UserRole))

    def _edit(self) -> None:
        record_id = self._selected_id()
        if record_id is None:
            return
        record = self.database.get_prediction(record_id)
        if not record:
            return
        dialog = RecordDialog(record, self)
        if dialog.exec() != RecordDialog.Accepted:
            return
        try:
            self.database.update_prediction(record_id, dialog.payload())
        except DuplicateRecordError as exc:
            QMessageBox.warning(self, "重复数据", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "修改失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def _toggle_invalid(self) -> None:
        record_id = self._selected_id()
        if record_id is None:
            return
        record = self.database.get_prediction(record_id)
        if not record:
            return
        invalid = not bool(record["is_invalid"])
        self.database.set_invalid(record_id, invalid)
        self.refresh()
        self.data_changed.emit()

    def _backup_before_delete(self):
        try:
            return backup_database(self.database.path, BACKUP_DIR)
        except Exception as exc:
            QMessageBox.critical(
                self, "无法删除", f"删除前数据库备份失败，未删除任何数据。\n\n{exc}"
            )
            return None

    def _delete_selected(self) -> None:
        record_id = self._selected_id()
        if record_id is None:
            return
        record = self.database.get_prediction(record_id)
        if not record:
            QMessageBox.warning(self, "记录不存在", "这条记录可能已经被删除，请刷新后重试。")
            return
        answer = QMessageBox.warning(
            self,
            "确认删除记录",
            f"确定删除 {record['source_type']} {record['issue_no']} 期记录吗？\n\n"
            "删除后相关旧回测结果会清除，需要重新运行回测。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        backup_path = self._backup_before_delete()
        if backup_path is None:
            return
        try:
            self.database.delete_prediction(record_id)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(
            self, "删除完成", f"已删除 1 条记录。\n删除前备份：\n{backup_path}"
        )

    def _delete_non_normal(self) -> None:
        count = self.database.count_non_normal_predictions()
        if count == 0:
            QMessageBox.information(self, "无需清理", "当前没有非“正常”状态的记录。")
            return
        answer = QMessageBox.warning(
            self,
            "确认清理非正常记录",
            f"将永久删除 {count} 条非“正常”记录。\n\n"
            "包含：待开奖、待检查和无效记录。采集日志不会删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        backup_path = self._backup_before_delete()
        if backup_path is None:
            return
        try:
            deleted = self.database.delete_non_normal_predictions()
        except Exception as exc:
            QMessageBox.critical(self, "清理失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(
            self, "清理完成", f"已删除 {deleted} 条非正常记录。\n删除前备份：\n{backup_path}"
        )

    def _export(self) -> None:
        if not self.records:
            QMessageBox.information(self, "没有数据", "当前筛选结果为空。")
            return
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出历史数据",
            str(EXPORT_DIR / "历史数据.xlsx"),
            "Excel 文件 (*.xlsx);;CSV 文件 (*.csv)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".xlsx"
        try:
            export_history(path, self.records)
            QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
