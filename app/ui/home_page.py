from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from .widgets import StatCard


GOOD_STATES = {"ONLINE", "RUNNING", "FRESH", "HEALTHY", "HASH_OK", "DRAWN", "SETTLED", "INGESTED"}
WAIT_STATES = {"STALE", "PENDING", "WAITING_DRAW", "WARNING"}


class HomePage(QWidget):
    """A dense desktop overview; all values come from the read-only gateway."""

    navigate_requested = Signal(str)

    def __init__(self, database=None, capture_controller=None, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.database = database
        self.capture_controller = capture_controller
        self.gateway = gateway or IntegrationGateway()
        self._draw_records: dict[str, Any] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        heading = QHBoxLayout()
        brand = QLabel("无忧28")
        brand.setObjectName("HomeBrand")
        heading.addWidget(brand)
        page = QLabel("首页")
        page.setObjectName("HomePageLabel")
        heading.addWidget(page)
        heading.addStretch()
        self.updated_label = QLabel("最近更新 —")
        self.updated_label.setObjectName("UpdateTime")
        heading.addWidget(self.updated_label)
        root.addLayout(heading)

        self.alert = QLabel()
        self.alert.setObjectName("WarningText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        draw_panel = QFrame()
        draw_panel.setObjectName("DrawBar")
        self.draw_panel = draw_panel
        draw_layout = QVBoxLayout(draw_panel)
        draw_layout.setContentsMargins(16, 11, 16, 11)
        draw_layout.setSpacing(12)

        issue_box = QVBoxLayout()
        issue_box.setSpacing(1)
        issue_caption = QLabel("当前开奖")
        issue_caption.setObjectName("BarCaption")
        self.draw_issue = QLabel("—")
        self.draw_issue.setObjectName("DrawIssue")
        issue_box.addWidget(issue_caption)
        issue_box.addWidget(self.draw_issue)
        draw_layout.addLayout(issue_box)

        self.number_blocks: list[QLabel] = []
        numbers_box = QHBoxLayout()
        numbers_box.setSpacing(6)
        for _ in range(3):
            block = QLabel("—")
            block.setObjectName("DrawBall")
            block.setAlignment(Qt.AlignCenter)
            block.setFixedSize(46, 46)
            self.number_blocks.append(block)
            numbers_box.addWidget(block)

        self.draw_numbers = QLabel("—")
        self.draw_numbers.setVisible(False)
        equals = QLabel("=")
        equals.setObjectName("DrawEquals")
        numbers_box.addWidget(equals)
        sum_box = QVBoxLayout()
        sum_box.setSpacing(0)
        sum_caption = QLabel("和值")
        sum_caption.setObjectName("BarCaption")
        self.draw_sum = QLabel("—")
        self.draw_sum.setObjectName("DrawTotal")
        sum_box.addWidget(sum_caption)
        sum_box.addWidget(self.draw_sum)
        numbers_box.addLayout(sum_box)
        numbers_box.addStretch()
        draw_layout.addLayout(numbers_box)

        self.draw_summary = QLabel("等待数据")
        self.draw_summary.setObjectName("DrawTags")
        draw_layout.addWidget(self.draw_summary)
        draw_layout.addStretch(1)

        self.next_panel = QFrame()
        self.next_panel.setObjectName("SummaryPanel")
        next_box = QVBoxLayout(self.next_panel)
        next_box.setSpacing(1)
        next_caption = QLabel("下一期")
        next_caption.setObjectName("BarCaption")
        self.next_issue = QLabel("—")
        self.next_issue.setObjectName("NextIssue")
        self.next_status = QLabel("等待数据")
        self.next_status.setObjectName("Muted")
        next_box.addWidget(next_caption)
        next_box.addWidget(self.next_issue)
        next_box.addWidget(self.next_status)
        next_box.addStretch()
        root.addWidget(draw_panel)
        root.addWidget(self.next_panel)

        status_panel = QFrame()
        self.status_panel = status_panel
        status_panel.setObjectName("EngineStatusLine")
        status_layout = QHBoxLayout(status_panel)
        status_layout.setContentsMargins(10, 5, 10, 5)
        status_layout.setSpacing(14)
        self.status_tokens: dict[str, QLabel] = {}
        for key in ("yu28", "vip", "hash", "strategy", "health"):
            token = QLabel("—")
            token.setObjectName("StatusToken")
            self.status_tokens[key] = token
            status_layout.addWidget(token)
        status_layout.addStretch()
        self.status_update = QLabel("更新时间 —")
        self.status_update.setObjectName("UpdateTime")
        status_layout.addWidget(self.status_update)

        # Hidden compatibility objects preserve the existing test surface;
        # the four large status cards are no longer part of the visible UI.
        self.status_cards: dict[str, StatCard] = {}
        for key in ("yu28", "vip", "strategy", "health"):
            card = StatCard(key, compact=True)
            card.setVisible(False)
            self.status_cards[key] = card
            self.layout().addWidget(card)

        work = QGridLayout()
        work.setHorizontalSpacing(12)
        work.setVerticalSpacing(8)
        work.setColumnStretch(0, 65)
        work.setColumnStretch(1, 35)

        recent_panel = QFrame()
        self.recent_panel = recent_panel
        recent_panel.setObjectName("WorkPanel")
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(12, 10, 12, 10)
        recent_layout.setSpacing(7)
        recent_header = QHBoxLayout()
        recent_title = QLabel("最近开奖")
        recent_title.setObjectName("SectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        recent_header.addWidget(QLabel("最近 10 期"), 0, Qt.AlignRight)
        recent_layout.addLayout(recent_header)
        self.recent_table = QTableWidget(0, 9)
        self.recent_table.setObjectName("RecentDrawTable")
        self.recent_table.setHorizontalHeaderLabels(("期号", "号码", "和值", "大小", "单双", "四组合", "VIP100", "状态", "时间"))
        self.recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SingleSelection)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.verticalHeader().setDefaultSectionSize(32)
        self.recent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.recent_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        recent_layout.addWidget(self.recent_table, 1)
        work.addWidget(recent_panel, 0, 0)

        self.summary_panel = QFrame()
        summary_column = QVBoxLayout(self.summary_panel)
        summary_column.setSpacing(8)
        self.vip_summary = self._summary_panel("VIP100 当前期", "等待数据")
        self.omission_summary = self._summary_panel("当前遗漏", "由正式遗漏页面提供")
        self.road_summary = self._summary_panel("路子状态", "由正式路子页面提供")
        summary_column.addWidget(self.vip_summary)
        summary_column.addWidget(self.omission_summary)
        summary_column.addWidget(self.road_summary)
        summary_column.addStretch()
        work.addWidget(self.summary_panel, 0, 1)
        root.addLayout(work, 1)
        root.addWidget(status_panel)

        for label, target in (("VIP100", "VIP100"), ("策略研究", "策略研究"), ("遗漏分析", "遗漏分析"), ("走势图", "走势图"), ("火车路子", "火车路子")):
            button = QPushButton(label, self)
            button.setVisible(False)
            button.clicked.connect(lambda _checked=False, name=target: self.navigate_requested.emit(name))

    def attach_layout_editor(self, model):
        """Reparent existing live controls; the gateway and renderers stay intact."""
        from .formal_ui_diy import HomeLayoutCanvas
        root = self.layout()

        def detach_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                elif item.layout():
                    detach_layout(item.layout())
                    item.layout().deleteLater()

        while root.count() > 2:
            item = root.takeAt(2)
            if item.widget():
                item.widget().hide()
            elif item.layout():
                detach_layout(item.layout())
                item.layout().deleteLater()
        self.edit_toolbar = QFrame()
        row = QHBoxLayout(self.edit_toolbar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel('首页 · Layout Edit Mode · 8px 网格'))
        row.addStretch()
        root.addWidget(self.edit_toolbar)
        self.edit_toolbar.hide()
        self.layout_body = QHBoxLayout()
        self.layout_scroll = QScrollArea()
        self.layout_scroll.setWidgetResizable(True)
        self.layout_canvas = HomeLayoutCanvas(model, {
            'current': self.draw_panel, 'next': self.next_panel,
            'vip': self.summary_panel, 'history': self.recent_panel, 'status': self.status_panel,
        })
        self.layout_scroll.setWidget(self.layout_canvas)
        self.layout_body.addWidget(self.layout_scroll, 1)
        root.addLayout(self.layout_body, 1)
        self.setFocusPolicy(Qt.StrongFocus)
        return self.layout_canvas

    @staticmethod
    def _summary_panel(title: str, value: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SummaryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        caption = QLabel(title)
        caption.setObjectName("SummaryCaption")
        value_label = QLabel(value)
        value_label.setObjectName("SummaryValue")
        value_label.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(value_label)
        panel.value_label = value_label  # type: ignore[attr-defined]
        return panel

    def refresh(self) -> None:
        try:
            health = dict(self.gateway.health() or {})
            latest = self.gateway.draws.latest()
            snapshot = self.gateway.data_center.snapshot(recent_limit=10)
            try:
                recent_draws = self.gateway.draws.recent(10)
            except Exception:
                recent_draws = ()
            self._draw_records = {str(item.issue): item for item in recent_draws}
        except Exception as exc:
            self._show_error(f"首页读取失败：{type(exc).__name__}: {exc}")
            self._render_empty()
            return
        self._clear_error()
        self._render_draw(latest)
        self._render_status(health)
        self._render_recent(snapshot.get("recent", ()))
        self._render_summaries(health)
        self._render_updated(latest)

    def _render_draw(self, record) -> None:
        if record is None:
            self.draw_issue.setText("—")
            self.draw_numbers.setText("—")
            self.draw_sum.setText("—")
            self.draw_summary.setText("等待数据")
            self.next_issue.setText("—")
            self.next_status.setText("等待数据")
            for block in self.number_blocks:
                block.setText("—")
            return
        numbers, total = _parse_draw(str(getattr(record, "number", "")))
        issue = str(getattr(record, "issue", "—"))
        combination = str(getattr(record, "combination", ""))
        big_small, odd_even = _split_combination(combination)
        self.draw_issue.setText(issue)
        self.draw_numbers.setText(" + ".join(numbers))
        self.draw_sum.setText(str(total if total is not None else "—"))
        self.draw_summary.setText(" · ".join(value for value in (big_small, odd_even, combination) if value) or "—")
        for block, value in zip(self.number_blocks, numbers):
            block.setText(value)
        for block in self.number_blocks[len(numbers):]:
            block.setText("—")
        try:
            self.next_issue.setText(f"{int(issue) + 1}期")
        except (TypeError, ValueError):
            self.next_issue.setText("下一期")
        countdown = str(getattr(record, "countdown", "") or "").strip()
        self.next_status.setText(countdown if countdown else "等待开奖")

    def _render_status(self, health: dict[str, Any]) -> None:
        draw = str(health.get("DRAW_SOURCE_STATUS", "OFFLINE"))
        count = int(health.get("VIP100_PREDICTION_COUNT") or 0)
        vip = str(health.get("VIP100_STATUS", "OFFLINE"))
        hash_status = str(health.get("VIP100_HASH_STATUS", "—"))
        strategy = str(health.get("STRATEGY_ENGINE_STATUS", "OFFLINE"))
        freshness = str(health.get("DATA_FRESHNESS", "OFFLINE"))
        values = {"yu28": f"● 数据源 {draw}", "vip": f"VIP100 {count}/100", "hash": hash_status, "strategy": f"● 策略引擎 {strategy}", "health": f"数据健康 {freshness}"}
        for key, value in values.items():
            self.status_tokens[key].setText(value)
            _style_status(self.status_tokens[key], value.split()[-1])
        self.status_cards["yu28"].set_value(draw)
        self.status_cards["vip"].set_value(f"{count}/100")
        self.status_cards["vip"].set_subtitle(hash_status)
        self.status_cards["strategy"].set_value(strategy)
        self.status_cards["health"].set_value(freshness)

    def _render_summaries(self, health: dict[str, Any]) -> None:
        try:
            vip_batch = self.gateway.vip100.latest()
        except Exception:
            vip_batch = None
        if vip_batch is not None:
            self.vip_summary.value_label.setText(f"{vip_batch.issue}期   {vip_batch.prediction_count}/100\n{vip_batch.algorithm_hash or 'HASH_UNAVAILABLE'}")
        else:
            self.vip_summary.value_label.setText(f"{health.get('VIP100_LATEST_ISSUE') or '—'}期   {health.get('VIP100_PREDICTION_COUNT', 0)}/100")
        try:
            from ..integration.omission_analysis_v1 import analyze_draws
            omission = analyze_draws(self.gateway.draws.recent(30), 30)
            gaps = omission.get("data_gap_count", 0)
            records = omission.get("records", [])
            hottest = max(records, key=lambda item: int(item.get("current_omission", 0)), default=None)
            text = f"最近30期 · DATA_GAP {gaps}"
            if hottest:
                text += f"\n号码 {hottest.get('number')} 当前遗漏 {hottest.get('current_omission')}"
            self.omission_summary.value_label.setText(text)
        except Exception:
            self.omission_summary.value_label.setText("正式数据待刷新 · 详见遗漏分析")
        try:
            from .road_page import road_stats
            from .trend_page import build_trend_rows
            rows = build_trend_rows(self.gateway.draws.recent(30), 30)
            stats = road_stats(rows, "combination")
            direction = stats.get("current_direction") or ("DATA_GAP" if rows and rows[-1].data_gap else "—")
            self.road_summary.value_label.setText(f"四组合 · {direction}\n当前连续 {stats.get('current_streak', 0)} · 最长 {stats.get('max_streak', 0)}")
        except Exception:
            self.road_summary.value_label.setText("正式数据待刷新 · 详见火车路子")

    def _render_recent(self, records) -> None:
        rows = list(records or ())[:10]
        self.recent_table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            issue = str(record.get("issue", "—"))
            draw = self._draw_records.get(issue)
            numbers, total = _parse_draw(str(getattr(draw, "number", ""))) if draw else ([], None)
            combination = str(getattr(draw, "combination", "") if draw else "")
            big_small, odd_even = _split_combination(combination)
            values = (issue, " + ".join(numbers) or "—", total if total is not None else "—", big_small or "—", odd_even or "—", combination or "—", _vip_count(record), record.get("draw_status", "—"), _format_time(record.get("data_time", "")) or record.get("data_time", "—"))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (3, 4, 5, 7):
                    item.setForeground(QColor(_status_color(str(value))))
                self.recent_table.setItem(row, column, item)

    def _render_updated(self, latest) -> None:
        text = _format_time(getattr(latest, "draw_time", "") if latest is not None else "") or "—"
        self.updated_label.setText(f"最近更新 {text}")
        self.status_update.setText(f"更新时间 {text}")

    def _render_empty(self) -> None:
        self._render_draw(None)
        self._render_status({})
        self._render_summaries({})
        self.recent_table.setRowCount(0)
        self.updated_label.setText("最近更新 —")
        self.status_update.setText("更新时间 —")

    def _show_error(self, message: str) -> None:
        self.alert.setText(message)
        self.alert.setVisible(True)

    def _clear_error(self) -> None:
        self.alert.clear()
        self.alert.setVisible(False)


def _parse_draw(value: str) -> tuple[list[str], int | None]:
    left, _, right = value.partition("=")
    numbers = [part.strip() for part in left.split("+") if part.strip()]
    try:
        total = int(right.strip()) if right.strip() else sum(int(part) for part in numbers)
    except ValueError:
        total = None
    return numbers, total


def _split_combination(combination: str) -> tuple[str, str]:
    if not combination:
        return "", ""
    return ("大" if "大" in combination else "小" if "小" in combination else "", "单" if "单" in combination else "双" if "双" in combination else "")


def _vip_count(record: dict) -> str:
    value = record.get("vip100_count", record.get("vip_count", 0))
    try:
        return f"{int(value)}/100"
    except (TypeError, ValueError):
        return str(value)


def _format_time(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        return str(value)


def _status_color(status: str) -> str:
    if status in GOOD_STATES or status.startswith("100/"):
        return "#16834B"
    if status in WAIT_STATES:
        return "#C26A00"
    if status in {"ERROR", "OFFLINE", "HASH_MISMATCH", "MISSING_OUTCOME"}:
        return "#B43B3B"
    return "#667085"


def _style_status(label: QLabel, status: str) -> None:
    label.setStyleSheet(f"color: {_status_color(status)}; font-weight: 600;")
