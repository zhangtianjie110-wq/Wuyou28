from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from .trend_page import TrendRow, build_trend_rows


@dataclass(frozen=True)
class RoadSegment:
    """One compact road column, containing one uninterrupted direction run."""

    direction: str = ""
    issues: tuple[str, ...] = ()
    data_gap: bool = False

    @property
    def length(self) -> int:
        return len(self.issues) if not self.data_gap else 0


def build_road_segments(rows: Iterable[TrendRow], attribute: str) -> tuple[RoadSegment, ...]:
    """Group chronological rows into direction runs; DATA_GAP always breaks a run."""
    segments: list[RoadSegment] = []
    current_direction = ""
    current_issues: list[str] = []

    def flush() -> None:
        nonlocal current_direction, current_issues
        if current_issues:
            segments.append(RoadSegment(current_direction, tuple(current_issues)))
        current_direction = ""
        current_issues = []

    for row in rows:
        if row.data_gap:
            flush()
            segments.append(RoadSegment(data_gap=True, issues=(row.issue,)))
            continue
        direction = str(getattr(row, attribute, "") or "")
        if not direction:
            continue
        if current_direction != direction:
            flush()
            current_direction = direction
        current_issues.append(row.issue)
    flush()
    return tuple(segments)


def road_stats(rows: Iterable[TrendRow], attribute: str) -> dict[str, Any]:
    rows = tuple(rows)
    segments = build_road_segments(rows, attribute)
    real_segments = [segment for segment in segments if not segment.data_gap]
    last_real = next((row for row in reversed(rows) if not row.data_gap), None)
    trailing = 0
    current_direction = ""
    if last_real is not None and (not rows or not rows[-1].data_gap):
        current_direction = str(getattr(last_real, attribute, "") or "")
        for segment in reversed(real_segments):
            if segment.direction != current_direction:
                break
            trailing = segment.length
            break
    return {
        "segments": segments,
        "current_direction": current_direction,
        "current_streak": trailing,
        "max_streak": max((segment.length for segment in real_segments), default=0),
    }


class RoadPage(QWidget):
    RANGES = (30, 50, 100, 200)
    ROAD_DEFINITIONS = (
        ("大小路子", "big_small", ("大", "小")),
        ("单双路子", "odd_even", ("单", "双")),
        ("四组合路子", "combination", ("大单", "大双", "小单", "小双")),
    )

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.rows: tuple[TrendRow, ...] = ()
        self.stats: dict[str, dict[str, Any]] = {}
        self._tables: dict[str, QTableWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("火车 / 路子")
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

        self.summary_table = QTableWidget(0, 4)
        self.summary_table.setHorizontalHeaderLabels(("路子", "当前方向", "当前连续", "最近最长连续"))
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSortingEnabled(False)
        self.summary_table.setAlternatingRowColors(True)
        root.addWidget(self.summary_table)

        self.road_layout = QGridLayout()
        self.road_layout.setHorizontalSpacing(12)
        self.road_layout.setVerticalSpacing(8)
        root.addLayout(self.road_layout)
        self.refresh()

    def refresh(self) -> None:
        limit = int(self.range_box.currentText())
        try:
            self.rows = build_trend_rows(self.gateway.draws.recent(limit), limit)
            gap_count = sum(1 for row in self.rows if row.data_gap)
            self.status_label.setText(f"{'DATA_GAP' if gap_count else 'COMPLETE'} · {gap_count} 个缺口")
        except Exception as exc:
            self.rows = ()
            self.status_label.setText(f"ERROR · {exc}")
        self._render()

    def _render(self) -> None:
        for index in reversed(range(self.road_layout.count())):
            item = self.road_layout.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.stats = {}
        self.summary_table.setRowCount(len(self.ROAD_DEFINITIONS))
        for row_index, (title, attribute, directions) in enumerate(self.ROAD_DEFINITIONS):
            stats = road_stats(self.rows, attribute)
            self.stats[attribute] = stats
            values = (
                title,
                stats["current_direction"] or ("DATA_GAP" if self.rows and self.rows[-1].data_gap else "—"),
                str(stats["current_streak"]),
                str(stats["max_streak"]),
            )
            for column, value in enumerate(values):
                self.summary_table.setItem(row_index, column, QTableWidgetItem(value))
            table = self._make_road_table(stats["segments"], directions)
            self._tables[attribute] = table
            self.road_layout.addWidget(QLabel(title), row_index, 0)
            self.road_layout.addWidget(table, row_index, 1)

    @staticmethod
    def _make_road_table(segments: tuple[RoadSegment, ...], directions: tuple[str, ...]) -> QTableWidget:
        max_length = max((segment.length for segment in segments), default=1)
        table = QTableWidget(max_length, max(1, len(segments)))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(72)
        table.setHorizontalHeaderLabels([str(index + 1) for index in range(max(1, len(segments)))])
        for column, segment in enumerate(segments):
            if segment.data_gap:
                item = QTableWidgetItem("DATA_GAP")
                item.setForeground(QColor("#B43B3B"))
                item.setToolTip(f"缺口期号：{', '.join(segment.issues)}")
                table.setItem(0, column, item)
                continue
            for row, issue in enumerate(segment.issues):
                item = QTableWidgetItem(segment.direction)
                item.setToolTip(f"期号：{issue}")
                table.setItem(row, column, item)
        return table

    def road_table(self, attribute: str) -> QTableWidget | None:
        return self._tables.get(attribute)

    def data_gap_count(self) -> int:
        return sum(1 for row in self.rows if row.data_gap)
