from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..integration import IntegrationGateway
from .widgets import secondary_button


class SortableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.setData(Qt.UserRole + 1, text if sort_value is None else sort_value)

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            left = self.data(Qt.UserRole + 1)
            right = other.data(Qt.UserRole + 1)
            try:
                return left < right
            except TypeError:
                return str(left) < str(right)
        return super().__lt__(other)


class HistoryQualityWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("数据质量", parent)
        layout = QGridLayout(self)
        specs = (
            ("valid_records", "历史有效期数"),
            ("analysis_samples", "分析实际样本"),
            ("start_issue", "起始期号"),
            ("latest_issue", "最新期号"),
            ("missing_issues", "缺失期数"),
            ("duplicate_records", "重复记录"),
            ("abnormal_records", "异常记录"),
            ("last_updated_at", "最后更新时间"),
        )
        self.labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.labels[key] = value_label
            layout.addWidget(caption_label, (index // 4) * 2, index % 4)
            layout.addWidget(value_label, (index // 4) * 2 + 1, index % 4)
        self.warning = QLabel("历史数据存在缺口，遗漏统计可能受影响")
        self.warning.setObjectName("WarningText")
        self.warning.setVisible(False)
        layout.addWidget(self.warning, 4, 0, 1, 4)

    def set_quality(self, quality: dict) -> None:
        for key, label in self.labels.items():
            value = quality.get(key)
            if key == "last_updated_at":
                value = format_time(value)
            label.setText("—" if value in (None, "") else str(value))
        self.warning.setVisible(int(quality.get("missing_issues") or 0) > 0)


class HistoryObjectDetailDialog(QDialog):
    def __init__(
        self,
        gateway: IntegrationGateway,
        dimension: str,
        object_name: str,
        parent=None,
    ):
        super().__init__(parent)
        self.gateway = gateway
        self.dimension = dimension
        self.object_name = object_name
        self.detail: dict = {}
        self.setWindowTitle(f"{object_name} · 历史冷热统计详情")
        self.resize(860, 640)
        self.setMinimumSize(720, 500)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(9)
        heading = QHBoxLayout()
        self.object_label = QLabel(self.object_name)
        self.object_label.setObjectName("PageTitle")
        self.refresh_button = QPushButton("刷新")
        secondary_button(self.refresh_button)
        self.refresh_button.clicked.connect(self.refresh)
        heading.addWidget(self.object_label)
        heading.addStretch()
        heading.addWidget(self.refresh_button)
        root.addLayout(heading)

        self.alert = QLabel()
        self.alert.setObjectName("DangerText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        omission_group = QGroupBox("遗漏统计")
        omission_layout = QGridLayout(omission_group)
        specs = (
            ("current_omission", "当前遗漏"),
            ("average_omission", "平均遗漏"),
            ("maximum_omission", "最大遗漏"),
            ("over_average_ratio", "超均倍数"),
            ("historical_percentile", "遗漏历史分位"),
        )
        self.omission_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.omission_labels[key] = value_label
            omission_layout.addWidget(caption_label, 0, index)
            omission_layout.addWidget(value_label, 1, index)
        root.addWidget(omission_group)

        hot_group = QGroupBox("历史冷热统计")
        hot_layout = QVBoxLayout(hot_group)
        self.hot_table = QTableWidget(0, 8)
        self.hot_table.setHorizontalHeaderLabels(
            ("周期", "实际样本", "出现次数", "出现率", "长期基准", "偏离", "历史分位", "冷热状态")
        )
        self.hot_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hot_table.setAlternatingRowColors(True)
        self.hot_table.verticalHeader().setVisible(False)
        self.hot_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        hot_layout.addWidget(self.hot_table)
        root.addWidget(hot_group, 1)

        note = QLabel("历史分位与冷热状态仅描述历史统计，不代表未来出现概率。")
        note.setObjectName("Muted")
        root.addWidget(note)

    def refresh(self) -> None:
        try:
            detail = self.gateway.history_object_detail(self.dimension, self.object_name)
        except Exception as exc:
            self.alert.setText(f"历史分析详情读取失败：{exc}")
            self.alert.setVisible(True)
            return
        self.detail = detail
        self.alert.clear()
        self.alert.setVisible(False)
        omission = detail.get("omission", {})
        self.omission_labels["current_omission"].setText(str(omission.get("current_omission", 0)))
        self.omission_labels["average_omission"].setText(format_decimal(omission.get("average_omission")))
        self.omission_labels["maximum_omission"].setText(str(omission.get("maximum_omission", 0)))
        self.omission_labels["over_average_ratio"].setText(format_ratio(omission.get("over_average_ratio")))
        self.omission_labels["historical_percentile"].setText(format_percentile(omission.get("historical_percentile")))
        rows = detail.get("hot_cold", ())
        self.hot_table.setRowCount(len(rows))
        for row_index, record in enumerate(rows):
            values = (
                "全部" if record.get("window") is None else str(record.get("window")),
                record.get("actual_samples", 0),
                record.get("occurrences", 0),
                format_rate(record.get("rate")),
                format_rate(record.get("baseline_rate")),
                format_signed_rate(record.get("deviation")),
                format_percentile(record.get("historical_percentile")),
                record.get("status", "正常"),
            )
            for column, value in enumerate(values):
                self.hot_table.setItem(row_index, column, QTableWidgetItem(str(value)))


def format_decimal(value) -> str:
    return "—" if value is None else f"{float(value):.2f}"


def format_ratio(value) -> str:
    return "—" if value is None else f"{float(value):.2f}×"


def format_rate(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def format_signed_rate(value) -> str:
    return "—" if value is None else f"{float(value) * 100:+.2f}%"


def format_percentile(value) -> str:
    return "—" if value is None else f"{float(value):.1f}%"


def format_time(value) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
