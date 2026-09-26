from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..integration import IntegrationGateway
from ..integration.omission_analysis_v1 import analyze_draws


class OmissionPage(QWidget):
    """Read-only native omission view over IntegrationGateway.draws."""

    RANGES = (30, 50, 100, 200)
    HEADERS = ("号码", "当前遗漏", "最大遗漏", "平均遗漏", "最近出现期号", "出现次数", "大小", "单双", "组合")

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self._snapshot: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)
        heading = QHBoxLayout()
        title = QLabel("遗漏分析")
        title.setObjectName("PageTitle")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(QLabel("窗口"))
        self.range_box = QComboBox()
        self.range_box.addItems([str(value) for value in self.RANGES])
        self.range_box.currentTextChanged.connect(self.refresh)
        heading.addWidget(self.range_box)
        self.status_label = QLabel("—")
        heading.addWidget(self.status_label)
        root.addLayout(heading)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        try:
            limit = int(self.range_box.currentText())
            snapshot = analyze_draws(self.gateway.draws.recent(limit), limit)
        except Exception as exc:
            self._snapshot = {"records": [], "data_gap_status": "ERROR", "error": str(exc)}
            self.status_label.setText("ERROR")
            self.table.setRowCount(0)
            return
        self._snapshot = snapshot
        self.status_label.setText(
            f"{snapshot.get('data_gap_status', 'COMPLETE')} · {snapshot.get('data_gap_count', 0)} 个DATA_GAP"
        )
        self.table.setSortingEnabled(False)
        records = snapshot.get("records", [])
        self.table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            values = (record["number"], record["current_omission"], record["maximum_omission"], record["average_omission"], record["last_issue"] or "—", record["occurrences"], record["big_small"], record["odd_even"], record["combination"])
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.table.setSortingEnabled(True)

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)
