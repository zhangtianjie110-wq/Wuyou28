from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ..history_analytics import HOT_COLD_STATUS, UI_WINDOWS
from ..integration import IntegrationGateway
from .history_analytics_widgets import (
    HistoryObjectDetailDialog,
    HistoryQualityWidget,
    SortableItem,
    format_percentile,
    format_rate,
    format_signed_rate,
)
from .omission_page import DIMENSIONS
from .widgets import PageHeader, StatCard, polish_detail_button, polish_table, secondary_button


STATUS_ORDER = {value: index for index, value in enumerate(HOT_COLD_STATUS)}


class HotColdPage(QWidget):
    """Read-only hot/cold analysis backed by HistoryAnalyticsEngine."""

    HEADERS = (
        "对象",
        "出现次数",
        "实际样本",
        "出现率",
        "长期基准",
        "偏离",
        "历史分位",
        "冷热状态",
        "详情",
    )

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self._snapshot: dict[str, Any] = {}
        self._all_records: tuple[dict[str, Any], ...] = ()
        self._detail_dialog: HistoryObjectDetailDialog | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(7)
        root.addWidget(PageHeader("冷热分析", "历史冷热状态"))

        summary_row = QHBoxLayout()
        self.summary_cards = {
            key: StatCard(title, "—", compact=True)
            for key, title in (("hot", "热门"), ("warm", "温和"), ("cold", "冷门"))
        }
        for card in self.summary_cards.values():
            summary_row.addWidget(card, 1)
        summary_row.addStretch(1)
        root.addLayout(summary_row)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("分析对象"))
        self.dimension_box = QComboBox()
        for text, value in DIMENSIONS:
            self.dimension_box.addItem(text, value)
        controls.addWidget(self.dimension_box)
        controls.addWidget(QLabel("数据范围"))
        self.range_box = QComboBox()
        for value in UI_WINDOWS:
            self.range_box.addItem(str(value), value)
        self.range_box.addItem("全部", None)
        controls.addWidget(self.range_box)
        controls.addWidget(QLabel("冷热状态"))
        self.status_box = QComboBox()
        self.status_box.addItem("全部", None)
        for value in HOT_COLD_STATUS:
            self.status_box.addItem(value, value)
        controls.addWidget(self.status_box)
        controls.addStretch()
        self.sample_label = QLabel("实际样本 —")
        self.sample_label.setObjectName("Muted")
        controls.addWidget(self.sample_label)
        root.addLayout(controls)

        self.alert = QLabel()
        self.alert.setObjectName("DangerText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)
        self.quality = HistoryQualityWidget()
        self.quality.setMinimumHeight(116)
        self.quality.setMaximumHeight(132)
        self.quality.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        quality_layout = self.quality.layout()
        if quality_layout is not None:
            quality_layout.setContentsMargins(12, 8, 12, 8)
            quality_layout.setHorizontalSpacing(16)
            quality_layout.setVerticalSpacing(6)
        for caption in self.quality.findChildren(QLabel):
            caption.setMinimumHeight(17)
            caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            if caption.objectName() == "Muted":
                caption.setStyleSheet("font-size: 13px;")
        for value_label in self.quality.labels.values():
            value_label.setMinimumHeight(20)
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            value_label.setStyleSheet("font-size: 16px;")
        root.addWidget(self.quality)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.table, 420)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setMinimumHeight(260)
        self.table.setMaximumHeight(16777215)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.table, 1)
        self.dimension_box.currentIndexChanged.connect(self.refresh)
        self.range_box.currentIndexChanged.connect(self.refresh)
        self.status_box.currentIndexChanged.connect(self._render)

    def refresh(self, *_args) -> None:
        try:
            snapshot = self.gateway.history_hot_cold(
                str(self.dimension_box.currentData()), self.range_box.currentData()
            )
        except Exception as exc:
            self._snapshot = {}
            self._all_records = ()
            self.table.setRowCount(0)
            self.alert.setText(f"冷热分析读取失败：{exc}")
            self.alert.setVisible(True)
            return
        self._snapshot = snapshot
        self._all_records = tuple(snapshot.get("records", ()))
        self.alert.clear()
        self.alert.setVisible(False)
        self.sample_label.setText(f"实际样本 {snapshot.get('actual_samples', 0)}")
        self.quality.set_quality(snapshot.get("quality", {}))
        self._update_summary(self._all_records)
        self._render()

    def _update_summary(self, records) -> None:
        counts = {status: 0 for status in HOT_COLD_STATUS}
        for record in records:
            status = record.get("status")
            if status in counts:
                counts[status] += 1
        self.summary_cards["hot"].set_value(str(counts.get("极热", 0) + counts.get("偏热", 0)))
        self.summary_cards["warm"].set_value(str(counts.get("正常", 0)))
        self.summary_cards["cold"].set_value(str(counts.get("极冷", 0) + counts.get("偏冷", 0)))

    def _render(self, *_args) -> None:
        selected_status = self.status_box.currentData()
        records = tuple(
            record
            for record in self._all_records
            if selected_status is None or record.get("status") == selected_status
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            percentile = record.get("historical_percentile")
            values = (
                (record["object"], record["object"]),
                (str(record["occurrences"]), record["occurrences"]),
                (str(record["actual_samples"]), record["actual_samples"]),
                (format_rate(record["rate"]), record["rate"]),
                (format_rate(record["baseline_rate"]), record["baseline_rate"]),
                (format_signed_rate(record["deviation"]), record["deviation"]),
                (format_percentile(percentile), -1.0 if percentile is None else percentile),
                (record["status"], STATUS_ORDER.get(record["status"], 2)),
                ("详情", record["object"]),
            )
            for column, (text, sort_value) in enumerate(values):
                item = SortableItem(str(text), sort_value)
                item.setData(Qt.UserRole, record["object"])
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column, item)
            button = QPushButton("详情")
            polish_detail_button(button)
            button.setProperty("object_name", record["object"])
            secondary_button(button)
            button.clicked.connect(partial(self._open_detail, record["object"]))
            self.table.setCellWidget(row_index, 8, button)
        self.table.setSortingEnabled(True)

    def _open_detail(self, object_name: str) -> None:
        self._detail_dialog = HistoryObjectDetailDialog(
            self.gateway,
            str(self.dimension_box.currentData()),
            object_name,
            self,
        )
        self._detail_dialog.exec()

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)
