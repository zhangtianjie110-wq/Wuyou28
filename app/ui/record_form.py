from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..stats import validate_and_enrich
from ..constants import SOURCE_TOTALS


class RecordForm(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QFormLayout()
        top.setHorizontalSpacing(18)
        top.setVerticalSpacing(10)
        self.issue = QLineEdit()
        self.issue.setPlaceholderText("例如：20260923001")
        self.source = QComboBox()
        self.source.addItems(["VIP"])
        self.source.currentTextChanged.connect(self._source_changed)
        self.result = QLineEdit()
        self.result.setPlaceholderText("可留空；支持 0-27 或 大单/大双/小单/小双")
        top.addRow("期号 *", self.issue)
        top.addRow("预测类型 *", self.source)
        top.addRow("开奖结果", self.result)
        root.addLayout(top)

        grid = QGridLayout()
        self.counts: dict[str, QSpinBox] = {}
        labels = [
            ("big_single", "大单"),
            ("big_double", "大双"),
            ("small_single", "小单"),
            ("small_double", "小双"),
        ]
        for index, (field, label) in enumerate(labels):
            box = QSpinBox()
            box.setRange(0, 100)
            box.setValue(25)
            box.valueChanged.connect(self._update_preview)
            self.counts[field] = box
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(box, 1, index)
        root.addLayout(grid)
        self._plan_text = ""

        preview_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        preview_row.addWidget(self.preview)
        preview_row.addStretch()
        root.addLayout(preview_row)
        self._source_changed(self.source.currentText())
        self._update_preview()

    def payload(self) -> dict[str, Any]:
        return {
            "issue_no": self.issue.text().strip(),
            "source_type": self.source.currentText(),
            "actual_result": self.result.text().strip(),
            # Existing plan details remain compatible with old records, but
            # the UI now works exclusively with the four summary counts.
            "plan_text": self._plan_text,
            **{field: box.value() for field, box in self.counts.items()},
        }

    def set_payload(self, record: dict[str, Any]) -> None:
        self.issue.setText(str(record.get("issue_no", "")))
        self.source.setCurrentText(str(record.get("source_type", "VIP")))
        self.result.setText(str(record.get("actual_result", "") or ""))
        self._plan_text = str(record.get("plan_text", "") or "")
        for field, box in self.counts.items():
            box.setValue(int(record.get(field, 0)))
        self._update_preview()

    def clear(self) -> None:
        self.issue.clear()
        self.source.setCurrentIndex(0)
        self.result.clear()
        self._plan_text = ""
        for box in self.counts.values():
            box.setValue(25)
        self.issue.setFocus()

    def _source_changed(self, source: str) -> None:
        expected = SOURCE_TOTALS.get(source, 100)
        current_total = sum(box.value() for box in self.counts.values()) if self.counts else 0
        old_expected = getattr(self, "_expected_total", 100)
        self._expected_total = expected
        if current_total == old_expected and len({box.value() for box in self.counts.values()}) == 1:
            default = expected // 4
            for box in self.counts.values():
                box.setValue(default)
        self._update_preview()

    def _update_preview(self) -> None:
        result = validate_and_enrich(self.payload())
        values = result.values
        total = sum(box.value() for box in self.counts.values())
        expected = SOURCE_TOTALS.get(self.source.currentText(), 100)
        reason = f" · {result.reason}" if result.reason else ""
        self.preview.setText(
            f"合计 {total}/{expected} · 最低 {values['stat_min']} · 最高 {values['stat_max']} · "
            f"最低两项 {values['lowest_two']} · 差值 {values['lowest_two_diff']} · "
            f"平均 {values['average']}{reason}"
        )
        self.changed.emit()
