from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway


COMBINATIONS = ("大单", "大双", "小单", "小双")


@dataclass(frozen=True)
class TrendRow:
    issue: str
    raw: str = ""
    first: str = ""
    second: str = ""
    third: str = ""
    total: int | None = None
    big_small: str = ""
    odd_even: str = ""
    combination: str = ""
    data_gap: bool = False


def _trend_row(draw: Any) -> TrendRow:
    if isinstance(draw, dict):
        raw = str(draw.get("number", "") or "")
        issue = str(draw.get("issue", draw.get("nbr", "")) or "")
    else:
        raw = str(getattr(draw, "number", "") or "")
        issue = str(getattr(draw, "issue", "") or "")
    parts = raw.split("=", 1)
    operands = parts[0].split("+") if parts else []
    total = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None
    first, second, third = (operands + ["", "", ""])[:3]
    if total is None or not 0 <= total <= 27:
        raise ValueError(f"invalid YU28 draw: {raw!r}")
    size = "大" if total >= 14 else "小"
    parity = "双" if total % 2 == 0 else "单"
    return TrendRow(
        issue=issue,
        raw=raw,
        first=first,
        second=second,
        third=third,
        total=total,
        big_small=size,
        odd_even=parity,
        combination=size + parity,
    )


def build_trend_rows(draws: Iterable[Any], limit: int) -> tuple[TrendRow, ...]:
    """Normalize recent draws and insert explicit rows for issue gaps."""
    normalized = sorted((_trend_row(draw) for draw in draws), key=lambda row: int(row.issue))
    if not normalized:
        return ()
    rows: list[TrendRow] = []
    for index, row in enumerate(normalized):
        if index:
            previous = int(normalized[index - 1].issue)
            current = int(row.issue)
            for missing in range(previous + 1, current):
                rows.append(TrendRow(issue=str(missing), data_gap=True))
        rows.append(row)
    # Limit applies to real draws; gap rows are retained between them.
    real_rows = [row for row in rows if not row.data_gap]
    if len(real_rows) > limit:
        keep = {row.issue for row in real_rows[-limit:]}
        first_issue = int(real_rows[-limit].issue)
        rows = [row for row in rows if int(row.issue) >= first_issue and (row.data_gap or row.issue in keep)]
    return tuple(rows)


class TrendPage(QWidget):
    RANGES = (30, 50, 100, 200)

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.rows: tuple[TrendRow, ...] = ()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("走势图")
        title.setObjectName("PageTitle")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(QLabel("最近"))
        self.range_box = QComboBox()
        self.range_box.addItems([str(value) for value in self.RANGES])
        self.range_box.currentTextChanged.connect(self.refresh)
        heading.addWidget(self.range_box)
        self.status_label = QLabel("—")
        heading.addWidget(self.status_label)
        root.addLayout(heading)

        self.draw_table = QTableWidget(0, 8)
        self.draw_table.setHorizontalHeaderLabels(("期号", "原始号码1", "原始号码2", "原始号码3", "和值", "大小", "单双", "组合"))
        self.draw_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.draw_table.setAlternatingRowColors(True)
        self.draw_table.setSortingEnabled(False)
        self.draw_table.setMinimumHeight(230)
        root.addWidget(self.draw_table)

        self.trend_table = QTableWidget(0, 29)
        self.trend_table.setHorizontalHeaderLabels(("期号",) + tuple(str(value) for value in range(28)))
        self.trend_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trend_table.setAlternatingRowColors(True)
        self.trend_table.setMinimumHeight(260)
        root.addWidget(QLabel("和值 0–27 走势（● 为当期和值，DATA_GAP 行不连线）"))
        root.addWidget(self.trend_table)

        self.category_table = QTableWidget(0, 6)
        self.category_table.setHorizontalHeaderLabels(("期号", "大", "小", "单", "双", "四组合"))
        self.category_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.category_table.setAlternatingRowColors(True)
        root.addWidget(QLabel("大小、单双和四组合走势"))
        root.addWidget(self.category_table)
        self.refresh()

    def refresh(self) -> None:
        limit = int(self.range_box.currentText())
        try:
            draws = self.gateway.draws.recent(limit)
            self.rows = build_trend_rows(draws, limit)
        except Exception as exc:
            self.rows = ()
            self.status_label.setText(f"ERROR · {exc}")
            self._render()
            return
        gaps = sum(1 for row in self.rows if row.data_gap)
        self.status_label.setText(f"{'DATA_GAP' if gaps else 'COMPLETE'} · {gaps} 个缺口")
        self._render()

    def _render(self) -> None:
        self.draw_table.setRowCount(len(self.rows))
        self.trend_table.setRowCount(len(self.rows))
        self.category_table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            if row.data_gap:
                draw_values = (f"DATA_GAP · {row.issue}", "", "", "", "", "", "", "")
                category_values = (f"DATA_GAP · {row.issue}", "", "", "", "", "")
            else:
                draw_values = (row.issue, row.first, row.second, row.third, row.total, row.big_small, row.odd_even, row.combination)
                category_values = (row.issue, row.big_small if row.big_small == "大" else "", row.big_small if row.big_small == "小" else "", row.odd_even if row.odd_even == "单" else "", row.odd_even if row.odd_even == "双" else "", row.combination)
            for column, value in enumerate(draw_values):
                item = QTableWidgetItem(str(value))
                if row.data_gap:
                    item.setForeground(QColor("#B43B3B"))
                self.draw_table.setItem(index, column, item)
            for column, value in enumerate(category_values):
                item = QTableWidgetItem(str(value))
                if row.data_gap:
                    item.setForeground(QColor("#B43B3B"))
                self.category_table.setItem(index, column, item)
            for column in range(29):
                value = f"DATA_GAP" if row.data_gap and column == 0 else (row.issue if column == 0 else "")
                if not row.data_gap and column == row.total + 1:
                    value = "●"
                item = QTableWidgetItem(value)
                if row.data_gap:
                    item.setForeground(QColor("#B43B3B"))
                self.trend_table.setItem(index, column, item)

    def visible_draw_count(self) -> int:
        return sum(1 for row in self.rows if not row.data_gap)

    def data_gap_count(self) -> int:
        return sum(1 for row in self.rows if row.data_gap)
