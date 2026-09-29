from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from .widgets import PageHeader, polish_table


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
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(6)

        self.page_header = PageHeader("开奖走势", "历史开奖走势")
        self.status_label = self.page_header.status_label
        root.addWidget(self.page_header)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.latest_issue_label = self._metric_card(status_row, "最新期号")
        self.latest_draw_label = self._metric_card(status_row, "最新号码")
        self.trend_state_label = self._metric_card(status_row, "当前走势状态")
        root.addLayout(status_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("最近"))
        self.range_box = QComboBox()
        self.range_box.addItems([str(value) for value in self.RANGES])
        self.range_box.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.range_box)
        controls.addStretch()
        root.addLayout(controls)

        self.draw_table = QTableWidget(0, 10)
        self.draw_table.setObjectName("DrawHistoryTable")
        self.draw_table.setHorizontalHeaderLabels(("期号", "开奖", "大", "小", "单", "双", "大单", "大双", "小单", "小双"))
        self.draw_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.draw_table.setAlternatingRowColors(True)
        self.draw_table.setSortingEnabled(False)
        self.draw_table.setShowGrid(True)
        self.draw_table.setGridStyle(Qt.PenStyle.SolidLine)
        self.draw_table.setWordWrap(False)
        self.draw_table.verticalHeader().setVisible(False)
        self.draw_table.verticalHeader().setDefaultSectionSize(36)
        self.draw_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.draw_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.draw_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        polish_table(self.draw_table, 300)
        self.draw_table.setMinimumHeight(220)
        self.draw_table.setMaximumHeight(16777215)
        self.draw_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.draw_table, 1)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self.big_count_label = self._metric_card(stats_row, "大小 · 大", height=72)
        self.small_count_label = self._metric_card(stats_row, "大小 · 小", height=72)
        self.odd_count_label = self._metric_card(stats_row, "单双 · 单", height=72)
        self.even_count_label = self._metric_card(stats_row, "单双 · 双", height=72)
        root.addLayout(stats_row)

        self.trend_table = QTableWidget(0, 29)
        self.trend_table.setHorizontalHeaderLabels(("期号",) + tuple(str(value) for value in range(28)))
        self.trend_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trend_table.setAlternatingRowColors(True)
        self.trend_table.verticalHeader().setVisible(False)
        self.trend_table.verticalHeader().setDefaultSectionSize(40)
        self.trend_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.trend_table.setMinimumHeight(170)
        # Keep the legacy table populated for compatibility, but remove the
        # former secondary distribution card from the visible page.
        self.trend_table.setVisible(False)

        # Retain the legacy category table for callers that still inspect it;
        # the dense history table above is the only visible category view.
        self.category_table = QTableWidget(0, 6)
        self.category_table.setHorizontalHeaderLabels(("期号", "大", "小", "单", "双", "四组合"))
        self.category_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.category_table.setAlternatingRowColors(True)
        self.category_table.setVisible(False)
        self.refresh()

    @staticmethod
    def _metric_card(layout: QHBoxLayout, title: str, height: int = 110) -> QLabel:
        card = QFrame()
        card.setObjectName("TrendMetricCard")
        card.setFixedHeight(height)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("TrendMetricTitle")
        title_label.setStyleSheet("font-size: 14px;")
        value_label = QLabel("0")
        value_label.setObjectName("TrendMetricValue")
        value_label.setStyleSheet("font-size: 20px;")
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        layout.addWidget(card, 1)
        return value_label

    def refresh(self) -> None:
        limit = int(self.range_box.currentText())
        try:
            draws = self.gateway.draws.recent(limit)
            self.rows = build_trend_rows(draws, limit)
        except Exception as exc:
            self.rows = ()
            self.page_header.set_status(f"ERROR · {exc}")
            self._render()
            return
        gaps = sum(1 for row in self.rows if row.data_gap)
        self.page_header.set_status(f"{'DATA_GAP' if gaps else 'COMPLETE'} · {gaps} 个缺口")
        latest = next((row for row in reversed(self.rows) if not row.data_gap), None)
        self.latest_issue_label.setText(latest.issue if latest else "—")
        self.latest_draw_label.setText(latest.raw if latest else "—")
        self.trend_state_label.setText("有数据缺口" if gaps else ("数据完整" if latest else "暂无数据"))
        self._render()

    def _render(self) -> None:
        self.draw_table.setRowCount(len(self.rows))
        self.trend_table.setRowCount(len(self.rows))
        self.category_table.setRowCount(len(self.rows))
        display_rows = tuple(reversed(self.rows))
        self._render_sequences_and_counts()
        self.draw_table.setRowCount(len(display_rows))
        for index, row in enumerate(display_rows):
            self._render_draw_history_row(index, row)
        for index, row in enumerate(self.rows):
            if row.data_gap:
                category_values = (f"DATA_GAP · {row.issue}", "", "", "", "", "")
            else:
                category_values = (row.issue, row.big_small if row.big_small == "大" else "", row.big_small if row.big_small == "小" else "", row.odd_even if row.odd_even == "单" else "", row.odd_even if row.odd_even == "双" else "", row.combination)
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

    def _render_draw_history_row(self, index: int, row: TrendRow) -> None:
        if row.data_gap:
            values = (f"数据缺口 · {row.issue}", "", "", "", "", "", "", "", "", "")
        else:
            values = (
                row.issue,
                row.total,
                "大" if row.big_small == "大" else "",
                "小" if row.big_small == "小" else "",
                "单" if row.odd_even == "单" else "",
                "双" if row.odd_even == "双" else "",
                "大单" if row.combination == "大单" else "",
                "大双" if row.combination == "大双" else "",
                "小单" if row.combination == "小单" else "",
                "小双" if row.combination == "小双" else "",
            )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            if row.data_gap:
                item.setForeground(QColor("#B43B3B"))
            elif column in (2, 6, 7):
                item.setForeground(QColor("#E54646"))
            elif column in (3, 8, 9):
                item.setForeground(QColor("#2868E8"))
            elif column == 4:
                item.setForeground(QColor("#8A52D8"))
            elif column == 5:
                item.setForeground(QColor("#1A9B73"))
            self.draw_table.setItem(index, column, item)

    def _render_sequences_and_counts(self) -> None:
        valid_rows = tuple(row for row in self.rows if not row.data_gap)
        self.big_count_label.setText(str(sum(row.big_small == "大" for row in valid_rows)))
        self.small_count_label.setText(str(sum(row.big_small == "小" for row in valid_rows)))
        self.odd_count_label.setText(str(sum(row.odd_even == "单" for row in valid_rows)))
        self.even_count_label.setText(str(sum(row.odd_even == "双" for row in valid_rows)))

    def visible_draw_count(self) -> int:
        return sum(1 for row in self.rows if not row.data_gap)

    def data_gap_count(self) -> int:
        return sum(1 for row in self.rows if row.data_gap)
