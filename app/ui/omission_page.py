from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from ..history_analytics import UI_WINDOWS
from ..integration import IntegrationGateway
from .history_analytics_widgets import (
    HistoryObjectDetailDialog,
    HistoryQualityWidget,
    SortableItem,
    format_decimal,
    format_percentile,
    format_ratio,
)
from .widgets import PageHeader, StatCard, polish_detail_button, polish_table, secondary_button


DIMENSIONS = (
    ("号码", "NUMBER"),
    ("大小", "BIG_SMALL"),
    ("单双", "ODD_EVEN"),
    ("四组合", "FOUR_COMBINATIONS"),
)


class OmissionPage(QWidget):
    """Read-only omission analysis backed by HistoryAnalyticsEngine."""

    HEADERS = ("对象", "当前遗漏", "平均遗漏", "最大遗漏", "状态", "历史分位", "详情")

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self._snapshot: dict[str, Any] = {}
        self._detail_dialog: HistoryObjectDetailDialog | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(7)
        root.addWidget(PageHeader("遗漏统计", "历史遗漏数据"))

        summary_row = QHBoxLayout()
        self.summary_cards = {
            key: StatCard(title, "—", compact=True)
            for key, title in (
                ("current", "最大遗漏"),
                ("average", "平均遗漏"),
                ("hot", "最长未出现对象"),
                ("cold", "数据期数"),
            )
        }
        for card in self.summary_cards.values():
            summary_row.addWidget(card, 1)
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
        controls.addWidget(QLabel("排序"))
        self.sort_box = QComboBox()
        self.sort_box.addItem("当前遗漏最高", "current")
        self.sort_box.addItem("最大遗漏最高", "maximum")
        self.sort_box.addItem("对象排序", "object")
        controls.addWidget(self.sort_box)
        controls.addStretch()
        self.sample_label = QLabel("实际样本 —")
        self.sample_label.setObjectName("Muted")
        controls.addWidget(self.sample_label)
        self.hint_label = QLabel("历史统计仅供分析参考")
        self.hint_label.setObjectName("Muted")
        controls.addWidget(self.hint_label)
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
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.horizontalHeader().resizeSection(6, 90)
        polish_table(self.table, 420)
        self.table.setColumnHidden(5, True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setMinimumHeight(260)
        self.table.setMaximumHeight(16777215)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.table, 1)
        self.dimension_box.currentIndexChanged.connect(self.refresh)
        self.range_box.currentIndexChanged.connect(self.refresh)
        self.sort_box.currentIndexChanged.connect(self.refresh)

    def refresh(self, *_args) -> None:
        try:
            snapshot = self.gateway.history_omission(
                str(self.dimension_box.currentData()), self.range_box.currentData()
            )
        except Exception as exc:
            self._snapshot = {}
            self.table.setRowCount(0)
            self.alert.setText(f"遗漏分析读取失败：{exc}")
            self.alert.setVisible(True)
            return
        self._snapshot = snapshot
        self.alert.clear()
        self.alert.setVisible(False)
        self.sample_label.setText(f"实际样本 {snapshot.get('actual_samples', 0)}")
        self.quality.set_quality(snapshot.get("quality", {}))
        records = tuple(snapshot.get("records", ()))
        sort_key = self.sort_box.currentData()
        if sort_key == "maximum":
            records = tuple(sorted(records, key=lambda item: item.get("maximum_omission", 0), reverse=True))
        elif sort_key == "object":
            records = tuple(sorted(records, key=lambda item: str(item.get("object", ""))))
        else:
            records = tuple(sorted(records, key=lambda item: item.get("current_omission", 0), reverse=True))
        self._update_summary(records)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            ratio = record.get("over_average_ratio")
            values = (
                (record["object"], record["object"]),
                (str(record["current_omission"]), record["current_omission"]),
                (format_decimal(record["average_omission"]), record["average_omission"]),
                (str(record["maximum_omission"]), record["maximum_omission"]),
                ("偏高" if ratio is not None and ratio >= 1.0 else "正常", -1.0 if ratio is None else ratio),
                (
                    format_percentile(record["historical_percentile"]),
                    -1.0 if record["historical_percentile"] is None else record["historical_percentile"],
                ),
                ("详情", record["object"]),
            )
            for column, (text, sort_value) in enumerate(values):
                item = SortableItem(str(text), sort_value)
                item.setData(Qt.UserRole, record["object"])
                item.setTextAlignment(Qt.AlignCenter)
                if column == 4 and ratio is not None and ratio >= 1.0:
                    item.setForeground(QColor("#C26A00" if ratio < 2.0 else "#B43B3B"))
                self.table.setItem(row_index, column, item)
            button = QPushButton("详情")
            polish_detail_button(button)
            button.setProperty("object_name", record["object"])
            secondary_button(button)
            button.clicked.connect(partial(self._open_detail, record["object"]))
            self.table.setCellWidget(row_index, 6, button)
        self.table.setSortingEnabled(True)

    def _update_summary(self, records) -> None:
        records = tuple(records)
        if not records:
            for card in self.summary_cards.values():
                card.set_value("—")
            return
        current = max(records, key=lambda item: item.get("current_omission", 0))
        average = sum(float(item.get("average_omission", 0) or 0) for item in records) / len(records)
        coldest = max(records, key=lambda item: item.get("current_omission", 0))
        self.summary_cards["current"].set_value(str(current.get("current_omission", "—")))
        self.summary_cards["average"].set_value(f"{average:.1f}")
        self.summary_cards["hot"].set_value(str(coldest.get("object", "—")))
        self.summary_cards["cold"].set_value(str(self._snapshot.get("actual_samples", "—")))

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
