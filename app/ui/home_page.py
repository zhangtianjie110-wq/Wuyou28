from __future__ import annotations

from collections import Counter
from datetime import datetime
import logging
import re
from typing import Any

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    QThreadPool,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from ..countdown_service import CountdownService
from .display_text import display_status
from .widgets import Card, PageHeader, StatCard, polish_table


GOOD_STATES = {"ONLINE", "RUNNING", "FRESH", "HEALTHY", "HASH_OK", "DRAWN", "SETTLED", "INGESTED"}
WAIT_STATES = {"STALE", "PENDING", "WAITING_DRAW", "WARNING"}
_ACTIVE_HOME_TASKS = set()
logger = logging.getLogger(__name__)


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _HomeDataTask(QRunnable):
    """Read the complete home snapshot away from the Qt GUI thread."""

    def __init__(self, gateway: IntegrationGateway):
        super().__init__()
        self.setAutoDelete(False)
        self.gateway = gateway
        self.signals = _TaskSignals(QCoreApplication.instance())

    def run(self) -> None:
        try:
            health = dict(self.gateway.health() or {})
            latest = self.gateway.draws.latest()
            snapshot = self.gateway.data_center.snapshot(recent_limit=100)
            recent_draws = tuple(self.gateway.draws.recent(100))
            vip_batch = self.gateway.vip100.latest()
            strategy_status = {}
            strategies = ()
            try:
                strategy_status = dict(self.gateway.strategies.status() or {})
                loader = getattr(self.gateway.strategies, "list_strategies", None)
                strategies = tuple(loader(200) or ()) if callable(loader) else ()
            except Exception as exc:
                # Strategy research storage is optional on a fresh install.
                # Keep the primary draw/VIP100 dashboard usable while retaining
                # a diagnostic record for the unavailable summary.
                logger.warning(
                    "home strategy summary unavailable: %s: %s",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
            self.signals.finished.emit(
                {
                    "health": health,
                    "latest": latest,
                    "snapshot": snapshot,
                    "recent_draws": recent_draws,
                    "vip_batch": vip_batch,
                    "strategy_status": strategy_status,
                    "strategies": strategies,
                }
            )
        except Exception as exc:
            logger.exception("home background data load failed")
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class HomePage(QWidget):
    """A dense desktop overview; all values come from the read-only gateway."""

    navigate_requested = Signal(str)

    def __init__(
        self,
        database=None,
        gateway: IntegrationGateway | None = None,
        parent=None,
        startup_lightweight: bool = False,
    ):
        super().__init__(parent)
        self.database = database
        self.gateway = gateway or IntegrationGateway()
        self._draw_records: dict[str, Any] = {}
        self._deferred_loaded = not startup_lightweight
        self._startup_lightweight = bool(startup_lightweight)
        self._background_load_started = False
        self._background_loading = False
        self._home_payload: dict[str, Any] | None = None
        self.countdown_service = CountdownService(self)
        self.countdown_service.changed.connect(self._on_countdown_changed)
        self._build_ui()
        if startup_lightweight:
            self._set_loading_state()
            QTimer.singleShot(0, self._start_background_load)
        else:
            self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 24)
        root.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.page_header = PageHeader("首页", "开奖、倒计时与 VIP100 状态")
        self.updated_label = self.page_header.updated_label
        self.page_header.set_updated("最近更新 —")
        # The desktop home uses the compact top bar as its page identity. Keep
        # this header object for refresh/compatibility callers, but do not let
        # it consume the large blank block above the core cards.
        self.page_header.setVisible(False)

        self.alert = QLabel()
        self.alert.setObjectName("WarningText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        # Keep the alert object for error-state compatibility, but keep the
        # normal dashboard free of a reserved banner area.

        health_panel = Card("数据健康", "正式数据读取状态")
        self.health_panel = health_panel
        health_grid = QGridLayout()
        health_grid.setHorizontalSpacing(10)
        health_grid.setVerticalSpacing(8)
        self.health_values: dict[str, QLabel] = {}
        health_specs = (
            ("state", "数据状态"),
            ("issue", "最新期号"),
            ("updated", "最新更新时间"),
            ("vip", "VIP100状态"),
            ("algorithms", "算法数量"),
        )
        for index, (key, caption) in enumerate(health_specs):
            metric = self._dashboard_metric(caption)
            self.health_values[key] = metric.value_label
            health_grid.addWidget(metric, index // 3, index % 3)
        health_panel.layout_body.addLayout(health_grid)
        # The visible top-right dashboard card already carries this health
        # summary; keep the legacy panel populated for compatibility without
        # consuming vertical space on the main page.
        health_panel.setVisible(False)

        draw_panel = QFrame()
        draw_panel.setObjectName("DrawBar")
        self.draw_panel = draw_panel
        draw_layout = QVBoxLayout(draw_panel)
        draw_layout.setContentsMargins(8, 4, 8, 4)
        draw_layout.setSpacing(2)

        issue_box = QVBoxLayout()
        issue_box.setSpacing(1)
        issue_caption = QLabel("当前期号")
        issue_caption.setObjectName("BarCaption")
        self.draw_issue = QLabel("—")
        self.draw_issue.setObjectName("DrawIssue")
        issue_box.addWidget(issue_caption)
        issue_box.addWidget(self.draw_issue)
        draw_layout.addLayout(issue_box)

        self.number_blocks: list[QLabel] = []
        numbers_box = QHBoxLayout()
        numbers_box.setSpacing(8)
        number_group = QHBoxLayout()
        number_group.setSpacing(8)
        for _ in range(3):
            block = QLabel("—")
            block.setObjectName("DrawBall")
            block.setAlignment(Qt.AlignCenter)
            block.setFixedSize(48, 48)
            self.number_blocks.append(block)
            number_group.addWidget(block)
        numbers_box.addLayout(number_group)
        numbers_box.addStretch(1)

        self.draw_numbers = QLabel("—")
        self.draw_numbers.setVisible(False)
        equals = QLabel("=")
        equals.setObjectName("DrawEquals")
        equals.setAlignment(Qt.AlignCenter)
        numbers_box.addWidget(equals)
        numbers_box.addSpacing(8)
        sum_box = QVBoxLayout()
        sum_box.setSpacing(1)
        sum_box.setAlignment(Qt.AlignCenter)
        sum_caption = QLabel("和值")
        sum_caption.setObjectName("BarCaption")
        self.draw_sum = QLabel("—")
        self.draw_sum.setObjectName("DrawTotal")
        self.draw_sum.setStyleSheet("font-size: 22px;")
        sum_box.addWidget(sum_caption)
        sum_box.addWidget(self.draw_sum)
        numbers_box.addLayout(sum_box)
        draw_layout.addLayout(numbers_box)

        self.draw_summary = QLabel("等待数据")
        self.draw_summary.setObjectName("DrawTags")
        # Kept as a compatibility attribute for older callers; combination
        # details are intentionally not part of the home card.
        self.draw_summary.setVisible(False)
        draw_layout.addStretch(1)
        draw_title = QLabel("最新开奖")
        draw_title.setObjectName("SectionTitle")
        draw_title.setStyleSheet("font-size: 14px;")
        draw_layout.insertWidget(0, draw_title)
        self.next_panel = QFrame()
        self.next_panel.setObjectName("NextDrawPanel")
        next_box = QVBoxLayout(self.next_panel)
        next_box.setContentsMargins(12, 6, 12, 6)
        next_box.setSpacing(2)
        next_header = QHBoxLayout()
        next_caption = QLabel("下一期开奖")
        next_caption.setObjectName("BarCaption")
        next_header.addWidget(next_caption)
        next_header.addStretch()
        next_realtime = QLabel("实时")
        next_realtime.setObjectName("NextRealtime")
        next_realtime.setStyleSheet("font-size: 12px; padding: 2px 6px;")
        next_header.addWidget(next_realtime)
        next_box.addLayout(next_header)
        self.next_issue = QLabel("—")
        self.next_issue.setObjectName("NextIssue")
        self.next_issue.setStyleSheet("font-size: 14px;")
        self.next_status = QLabel("等待数据")
        self.next_status.setObjectName("NextCountdown")
        self.next_status.setStyleSheet("font-size: 22px;")
        next_box.addWidget(self.next_issue)
        next_box.addWidget(self.next_status)
        self.next_time = QLabel("预计开奖时间 —")
        self.next_time.setObjectName("NextDrawTime")
        self.next_time.setStyleSheet("font-size: 12px;")
        next_box.addWidget(self.next_time)
        next_box.addStretch(1)

        vip_panel = QFrame()
        vip_panel.setObjectName("VipStatusPanel")
        self.vip_panel = vip_panel
        vip_layout = QVBoxLayout(vip_panel)
        vip_layout.setContentsMargins(12, 6, 12, 6)
        vip_layout.setSpacing(2)
        vip_header = QHBoxLayout()
        vip_title = QLabel("数据状态")
        self.vip_title_label = vip_title
        vip_title.setObjectName("VipPanelTitle")
        vip_title.setStyleSheet("font-size: 14px;")
        vip_header.addWidget(vip_title)
        vip_header.addStretch()
        self.vip_status_label = QLabel("正常")
        self.vip_status_label.setObjectName("StatusOnline")
        self.vip_status_label.setStyleSheet("font-size: 12px; padding: 2px 7px;")
        vip_header.addWidget(self.vip_status_label)
        vip_layout.addLayout(vip_header)
        vip_state_caption = QLabel("数据状态")
        vip_state_caption.setObjectName("VipPanelMeta")
        vip_state_caption.setStyleSheet("font-size: 12px;")
        vip_layout.addWidget(vip_state_caption)
        vip_state_row = QHBoxLayout()
        self.vip_count_label = QLabel("正常运行")
        self.vip_count_label.setObjectName("VipCountValue")
        self.vip_count_label.setStyleSheet("font-size: 22px;")
        vip_state_row.addWidget(self.vip_count_label)
        vip_total = QLabel("")
        vip_total.setObjectName("VipCountTotal")
        vip_total.setVisible(False)
        vip_state_row.addWidget(vip_total)
        vip_state_row.addStretch()
        vip_layout.addLayout(vip_state_row)
        self.vip_issue_label = QLabel("最新开奖：—")
        self.vip_issue_label.setObjectName("VipPanelNumber")
        self.data_vip_label = QLabel("VIP100：—")
        self.data_vip_label.setObjectName("VipPanelNumber")
        self.data_updated_label = QLabel("数据缺口：—")
        self.data_updated_label.setObjectName("VipPanelNumber")
        details_row = QHBoxLayout()
        details_row.setSpacing(8)
        for label in (self.vip_issue_label, self.data_vip_label, self.data_updated_label):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setStyleSheet("font-size: 12px;")
            details_row.addWidget(label, 1)
        # Keep legacy labels populated for compatibility callers, but do not
        # surface repeated issue/VIP/gap details on the final home card.
        details_host = QWidget()
        details_host.setLayout(details_row)
        details_host.setVisible(False)
        vip_layout.addWidget(details_host)
        self.vip_hash_state_label = QLabel("状态：HASH_OK")
        self.vip_hash_state_label.setObjectName("VipPanelMeta")
        # HASH remains available to the detailed VIP100 page, not the home
        # dashboard card.
        self.vip_hash_state_label.setVisible(False)
        self.vip_hash_label = self.vip_hash_state_label
        vip_grid = QGridLayout()
        vip_grid.setSpacing(6)
        self.vip_group_labels: dict[str, QLabel] = {}
        for index, key in enumerate(("大单", "大双", "小单", "小双")):
            cell = QFrame()
            cell.setObjectName("VipGroupCellBig" if key.startswith("大") else "VipGroupCellSmall")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 6, 8, 6)
            caption = QLabel(key)
            caption.setObjectName("VipGroupTitleBig" if key.startswith("大") else "VipGroupTitleSmall")
            value = QLabel("—")
            value.setObjectName("VipGroupValueBig" if key.startswith("大") else "VipGroupValueSmall")
            cell_layout.addWidget(caption)
            cell_layout.addWidget(value)
            self.vip_group_labels[key] = value
            vip_grid.addWidget(cell, index // 2, index % 2)
        vip_grid_host = QWidget()
        vip_grid_host.setLayout(vip_grid)
        vip_grid_host.setVisible(False)
        vip_layout.addWidget(vip_grid_host)

        for panel in (draw_panel, self.next_panel, vip_panel):
            panel.setFixedHeight(110)
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        hero_row = QHBoxLayout()
        hero_row.setSpacing(8)
        hero_row.addWidget(draw_panel, 4)
        hero_row.addWidget(self.next_panel, 3)
        hero_row.addWidget(vip_panel, 3)
        root.addLayout(hero_row)
        # Product dashboard sections stay compact and visible below the
        # three primary cards; legacy technical strips remain hidden.
        # The top-right data-health card is the only visible health summary.
        # Keep this legacy panel detached so it cannot introduce blank space.

        status_panel = QFrame()
        self.status_panel = status_panel
        status_panel.setObjectName("EngineStatusLine")
        status_layout = QHBoxLayout(status_panel)
        status_layout.setContentsMargins(10, 5, 10, 5)
        status_layout.setSpacing(12)
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
        status_panel.setVisible(False)
        self.status_panel = status_panel

        # Keep the legacy status cards and status strip populated for callers,
        # but use the compact dashboard metrics above for the visible home UI.
        self.status_cards: dict[str, StatCard] = {}
        for key in ("yu28", "vip", "strategy", "health"):
            card = StatCard(key, compact=True)
            card.setVisible(False)
            self.status_cards[key] = card

        strategy_panel = Card("智能选法摘要", "当前研究结果与观察状态")
        self.strategy_panel = strategy_panel
        strategy_grid = QGridLayout()
        strategy_grid.setHorizontalSpacing(16)
        strategy_grid.setVerticalSpacing(8)
        self.strategy_values: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate((
            ("top", "当前TOP策略"),
            ("validation", "验证表现"),
            ("recent", "最近表现"),
            ("latest", "最近回测"),
            ("observed", "观察策略数量"),
        )):
            metric = self._dashboard_metric(caption)
            self.strategy_values[key] = metric.value_label
            strategy_grid.addWidget(metric, index // 3, index % 3)
        strategy_panel.layout_body.addLayout(strategy_grid)
        strategy_panel.setVisible(False)

        quick_panel = Card("快速入口", "常用功能")
        self.quick_panel = quick_panel
        quick_panel.setParent(self)
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(10)
        for label, target in (
            ("VIP100", "VIP100"),
            ("智能选法", "智能选法"),
            ("模拟测试", "模拟测试"),
        ):
            button = QPushButton(label, self)
            button.setObjectName("HomeQuickButton")
            button.clicked.connect(lambda _checked=False, name=target: self.navigate_requested.emit(name))
            quick_layout.addWidget(button, 1)
        quick_panel.layout_body.addLayout(quick_layout)
        quick_panel.setVisible(False)

        # Legacy panels stay instantiated and refreshed for the layout editor
        # and older callers, but complex tables are no longer shown on home.
        recent_panel = QFrame()
        self.recent_panel = recent_panel
        recent_panel.setObjectName("WorkPanel")
        recent_panel.setMinimumHeight(300)
        recent_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(12, 10, 12, 10)
        recent_layout.setSpacing(7)
        recent_header = QHBoxLayout()
        recent_title = QLabel("最近开奖")
        recent_title.setObjectName("SectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        recent_header.addWidget(QLabel("最近 100 期"), 0, Qt.AlignRight)
        recent_layout.addLayout(recent_header)
        self.recent_table = QTableWidget(0, 6)
        self.recent_table.setObjectName("RecentDrawTable")
        self.recent_table.setHorizontalHeaderLabels(("期号", "开奖", "和值", "组合", "时间", "状态"))
        self.recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SingleSelection)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_table.setWordWrap(False)
        self.recent_table.setTextElideMode(Qt.ElideRight)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.verticalHeader().setDefaultSectionSize(36)
        header = self.recent_table.horizontalHeader()
        for column in range(self.recent_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
        for column, width in ((0, 92), (2, 56), (3, 64), (5, 68)):
            header.resizeSection(column, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        polish_table(self.recent_table, 300)
        self.recent_table.setMinimumHeight(240)
        self.recent_table.setMaximumHeight(16777215)
        self.recent_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        recent_layout.addWidget(self.recent_table, 1)
        root.addWidget(recent_panel, 1)

        self.summary_panel = QFrame()
        summary_column = QVBoxLayout(self.summary_panel)
        summary_column.setSpacing(8)
        self.vip_summary = self._summary_panel("VIP100 当前期", "等待数据")
        self.omission_summary = self._summary_panel("当前遗漏", "由正式遗漏页面提供")
        summary_column.addWidget(self.vip_summary)
        summary_column.addWidget(self.omission_summary)
        summary_column.addStretch()
        self.summary_panel.setVisible(False)

        # Compatibility shortcuts retained for older callers. The visible
        # quick-entry cards above are the primary home actions.
        for label, target in (("遗漏统计", "遗漏统计"), ("开奖走势", "开奖走势")):
            button = QPushButton(label, self)
            button.setVisible(False)
            button.clicked.connect(lambda _checked=False, name=target: self.navigate_requested.emit(name))

    @staticmethod
    def _dashboard_metric(title: str) -> QFrame:
        metric = QFrame()
        metric.setObjectName("HomeMetric")
        layout = QVBoxLayout(metric)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        caption = QLabel(title)
        caption.setObjectName("HomeMetricTitle")
        value = QLabel("—")
        value.setObjectName("HomeMetricValue")
        value.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(value)
        metric.value_label = value  # type: ignore[attr-defined]
        return metric

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

        while root.count():
            item = root.takeAt(0)
            if item.widget():
                item.widget().hide()
            elif item.layout():
                detach_layout(item.layout())
                item.layout().deleteLater()
        self.edit_toolbar = QFrame()
        row = QHBoxLayout(self.edit_toolbar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel('首页 · 布局编辑模式 · 8 像素网格'))
        row.addStretch()
        root.addWidget(self.edit_toolbar)
        self.edit_toolbar.hide()
        self.layout_body = QHBoxLayout()
        self.layout_scroll = QScrollArea()
        self.layout_scroll.setWidgetResizable(True)
        self.layout_canvas = HomeLayoutCanvas(model, {
            'current': self.draw_panel, 'next': self.next_panel,
            'vip': self.vip_panel, 'history': self.recent_panel, 'status': self.status_panel,
        })
        self.layout_scroll.setWidget(self.layout_canvas)
        self.layout_body.addWidget(self.layout_scroll, 1)
        root.addLayout(self.layout_body, 1)
        self.setFocusPolicy(Qt.StrongFocus)
        return self.layout_canvas

    @staticmethod
    def _summary_panel(title: str, value: str) -> QFrame:
        panel = Card()
        panel.setObjectName("SummaryPanel")
        layout = panel.layout_body
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

    def refresh(self, *, force: bool = False) -> None:
        self._deferred_loaded = True
        if self._home_payload is not None and not force:
            self._apply_background_payload(self._home_payload)
            return
        if self._startup_lightweight and self._background_loading and not force:
            return
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
        self._render_status(health, snapshot)
        self._render_recent(snapshot.get("recent", ()))
        self._render_summaries(health)
        self._render_updated(latest)

    def refresh_lightweight(self) -> None:
        """Compatibility entry point for callers requesting a light refresh."""
        if self._startup_lightweight:
            self._start_background_load()
            return
        try:
            health = dict(self.gateway.health() or {})
            latest = self.gateway.draws.latest()
        except Exception as exc:
            self._show_error(f"首页读取失败：{type(exc).__name__}: {exc}")
            self._render_empty()
            return
        self._clear_error()
        self._render_draw(latest)
        self._render_status(health)
        self._render_updated(latest)

    def _set_loading_state(self) -> None:
        self.alert.setText("正在加载首页数据…")
        # Loading is already represented inside the three core cards. Keep
        # the alert available for failures without reserving a large banner
        # above the dashboard during normal startup.
        self.alert.setVisible(False)
        self.draw_issue.setText("加载中…")
        self.draw_numbers.setText("—")
        self.draw_sum.setText("—")
        self.draw_summary.setText("加载中…")
        self.next_issue.setText("加载中…")
        self.next_status.setText("等待数据")
        self.countdown_service.clear()
        self.next_time.setText("预计开奖时间 —")
        self.vip_status_label.setText("加载中…")
        self.vip_count_label.setText("加载中…")
        self.vip_issue_label.setText("最新开奖：加载中…")
        self.data_vip_label.setText("VIP100：加载中…")
        self.data_updated_label.setText("数据缺口：加载中…")
        self.vip_hash_state_label.setText("状态：加载中…")

    def _start_background_load(self) -> None:
        if self._background_load_started:
            return
        self._background_load_started = True
        self._background_loading = True
        task = _HomeDataTask(self.gateway)
        self._background_task = task
        _ACTIVE_HOME_TASKS.add(task)
        task.signals.finished.connect(self._on_background_load_finished)
        task.signals.failed.connect(self._on_background_load_failed)
        task.signals.finished.connect(lambda _value, item=task: _ACTIVE_HOME_TASKS.discard(item))
        task.signals.failed.connect(lambda _value, item=task: _ACTIVE_HOME_TASKS.discard(item))
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _on_background_load_finished(self, payload: dict[str, Any]) -> None:
        self._background_loading = False
        self._deferred_loaded = True
        self._home_payload = payload
        self._apply_background_payload(payload)

    def _apply_background_payload(self, payload: dict[str, Any]) -> None:
        try:
            health = payload["health"]
            latest = payload["latest"]
            snapshot = payload["snapshot"]
            recent_draws = payload["recent_draws"]
            self._draw_records = {str(item.issue): item for item in recent_draws}
            self._clear_error()
            self._render_draw(latest)
            self._render_status(health, snapshot)
            self._render_recent(snapshot.get("recent", ()))
            self._render_summaries(
                health,
                vip_batch=payload.get("vip_batch"),
                strategy_status=payload.get("strategy_status"),
                strategies=payload.get("strategies"),
                omission_draws=recent_draws,
            )
            self._render_updated(latest)
        except Exception as exc:
            self._show_error(f"首页详细数据读取失败：{type(exc).__name__}: {exc}")

    @Slot(str)
    def _on_background_load_failed(self, message: str) -> None:
        self._background_loading = False
        self._show_error(f"首页读取失败：{message}")
        self.draw_issue.setText("读取失败")
        self.draw_summary.setText("数据暂不可用")
        self.countdown_service.clear()
        self.next_status.setText("等待数据")

    def _render_draw(self, record) -> None:
        if record is None:
            self.draw_issue.setText("—")
            self.draw_numbers.setText("—")
            self.draw_sum.setText("—")
            self.draw_summary.setText("等待数据")
            self.next_issue.setText("加载中…")
            self.next_status.setText("等待数据")
            self.countdown_service.clear()
            self.next_time.setText("预计开奖时间 —")
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
        # Preserve the legacy value for non-visual callers; it is hidden from
        # the homepage to keep the card focused on numbers and sum.
        self.draw_summary.setText(" · ".join(value for value in (big_small, odd_even, combination) if value) or "—")
        for block, value in zip(self.number_blocks, numbers):
            block.setText(value)
        for block in self.number_blocks[len(numbers):]:
            block.setText("—")
        try:
            self.next_issue.setText(f"{int(issue) + 1}期")
        except (TypeError, ValueError):
            self.next_issue.setText("加载中…")
        self.countdown_service.set_draw(record)

    def _render_status(self, health: dict[str, Any], snapshot: dict[str, Any] | None = None) -> None:
        draw = str(health.get("DRAW_SOURCE_STATUS", "OFFLINE"))
        count = int(health.get("VIP100_PREDICTION_COUNT") or 0)
        vip = str(health.get("VIP100_STATUS", "OFFLINE"))
        hash_status = str(health.get("VIP100_HASH_STATUS", "—"))
        strategy = str(health.get("STRATEGY_ENGINE_STATUS", "OFFLINE"))
        freshness = str(health.get("DATA_FRESHNESS", "OFFLINE"))
        values = {
            "yu28": f"● 数据源 {display_status(draw)}",
            "vip": f"VIP100 {count}/100",
            "hash": display_status(hash_status),
            "strategy": f"● 策略引擎 {display_status(strategy)}",
            "health": f"数据健康 {display_status(freshness)}",
        }
        raw_statuses = {
            "yu28": draw,
            "vip": f"{count}/100",
            "hash": hash_status,
            "strategy": strategy,
            "health": freshness,
        }
        for key, value in values.items():
            self.status_tokens[key].setText(value)
            _style_status(self.status_tokens[key], raw_statuses[key])
        self.health_values["state"].setText(display_status(freshness))
        self.health_values["issue"].setText(str(health.get("DRAW_LATEST_ISSUE") or "—"))
        self.health_values["vip"].setText(display_status(vip))
        self.health_values["algorithms"].setText(f"{count}/100")
        data_status = "正常" if freshness in GOOD_STATES else display_status(freshness)
        self.vip_count_label.setText("正常运行" if data_status == "正常" else data_status)
        self.vip_hash_state_label.setText(f"状态：{hash_status}")
        self.vip_status_label.setText("正常运行" if data_status == "正常" else data_status)
        latest_issue = health.get("DRAW_LATEST_ISSUE") or "—"
        self.vip_issue_label.setText(f"最新开奖：{latest_issue}期" if latest_issue != "—" else "最新开奖：—")
        self.data_vip_label.setText(f"VIP100：{count}/100")
        self.data_updated_label.setText(f"数据缺口：{_snapshot_gap_count(snapshot)}")
        for key, value in zip(
            ("大单", "大双", "小单", "小双"),
            (health.get("VIP100_BIG_SINGLE"), health.get("VIP100_BIG_DOUBLE"), health.get("VIP100_SMALL_SINGLE"), health.get("VIP100_SMALL_DOUBLE")),
        ):
            self.vip_group_labels[key].setText("—" if value is None else str(value))
        self.status_cards["yu28"].set_value(display_status(draw))
        self.status_cards["vip"].set_value(f"{count}/100")
        self.status_cards["vip"].set_subtitle(display_status(hash_status))
        self.status_cards["strategy"].set_value(display_status(strategy))
        self.status_cards["health"].set_value(display_status(freshness))

    def _on_countdown_changed(self, text: str, expected_time: str) -> None:
        self.next_status.setText(text)
        self.next_time.setText(f"预计开奖时间 {expected_time}")

    def _tick_countdown(self) -> None:
        """Compatibility hook for callers; the service owns the clock."""
        self.countdown_service.tick()

    def _render_summaries(
        self,
        health: dict[str, Any],
        *,
        vip_batch=None,
        strategy_status: dict[str, Any] | None = None,
        strategies=None,
        omission_draws=None,
    ) -> None:
        if vip_batch is None and strategy_status is None and strategies is None:
            try:
                vip_batch = self.gateway.vip100.latest()
            except Exception:
                vip_batch = None
        if vip_batch is not None:
            self.vip_summary.value_label.setText(
                f"{vip_batch.issue}期   {vip_batch.prediction_count}/100\n"
                f"{vip_batch.algorithm_hash or '哈希值暂不可用'}"
            )
            counts = Counter(prediction.combination for prediction in vip_batch.predictions)
            for key, label in self.vip_group_labels.items():
                label.setText(str(counts.get(key, 0)))
        else:
            self.vip_summary.value_label.setText(f"{health.get('VIP100_LATEST_ISSUE') or '—'}期   {health.get('VIP100_PREDICTION_COUNT', 0)}/100")
        self._render_strategy_summary(strategy_status, strategies)
        try:
            from ..integration.omission_analysis_v1 import analyze_draws
            omission = analyze_draws(
                omission_draws
                if omission_draws is not None
                else self.gateway.draws.recent(30),
                30,
            )
            gaps = omission.get("data_gap_count", 0)
            records = omission.get("records", [])
            hottest = max(records, key=lambda item: int(item.get("current_omission", 0)), default=None)
            text = f"最近30期 · 数据缺口 {gaps}"
            if hottest:
                text += f"\n号码 {hottest.get('number')} 当前遗漏 {hottest.get('current_omission')}"
            self.omission_summary.value_label.setText(text)
        except Exception:
            self.omission_summary.value_label.setText("正式数据待刷新 · 详见遗漏分析")

    def _render_strategy_summary(
        self,
        status: dict[str, Any] | None = None,
        strategies=None,
    ) -> None:
        """Render a compact strategy snapshot without changing the read API."""
        if status is None:
            try:
                status = dict(self.gateway.strategies.status() or {})
            except Exception:
                status = {}
        else:
            status = dict(status)
        lifecycle = status.get("lifecycle_counts") or {}
        observed = sum(
            int(lifecycle.get(key, 0) or 0)
            for key in ("RESEARCH_ONLY", "CANDIDATE", "FORWARD_TEST")
        )
        if not observed:
            observed = int(status.get("candidate_strategies", 0) or 0)
        top = None
        try:
            if strategies is None:
                loader = getattr(self.gateway.strategies, "list_strategies", None)
                strategies = list(loader(200) or ()) if callable(loader) else []
            else:
                strategies = list(strategies)
            eligible = [
                candidate for candidate in strategies
                if getattr(candidate, "sample_warning", None) is None
            ]
            top = max(
                eligible,
                key=lambda candidate: (
                    _rate_number(getattr(candidate, "validation_accuracy", None)),
                    _rate_number(getattr(candidate, "recent_50_accuracy", None)),
                    int(getattr(candidate, "validation_samples", 0) or 0),
                ),
                default=None,
            )
        except Exception:
            top = None
        if top is None:
            self.strategy_values["top"].setText("暂无TOP策略")
            self.strategy_values["validation"].setText("暂无验证结果")
            self.strategy_values["recent"].setText("暂无近期表现")
        else:
            name = str(getattr(top, "strategy_name", "") or getattr(top, "strategy_id", "—"))
            self.strategy_values["top"].setText(name)
            self.strategy_values["validation"].setText(_format_rate(getattr(top, "validation_accuracy", None)))
            self.strategy_values["recent"].setText(_format_rate(getattr(top, "recent_50_accuracy", None)))
        latest_run = status.get("latest_research_at") or status.get("updated_at")
        self.strategy_values["latest"].setText(_format_time(str(latest_run or "")) or "暂无记录")
        self.strategy_values["observed"].setText(str(observed))
    def _render_recent(self, records) -> None:
        rows = list(records or ())[:100]
        self.recent_table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            issue = str(record.get("issue", "—"))
            draw = self._draw_records.get(issue)
            numbers, total = _parse_draw(str(getattr(draw, "number", ""))) if draw else ([], None)
            combination = str(getattr(draw, "combination", "") if draw else "")
            big_small, odd_even = _split_combination(combination)
            draw_status = record.get("draw_status", "—")
            values = (
                issue,
                "   ".join(numbers) or "—",
                total if total is not None else "—",
                combination or "—",
                _format_time(record.get("data_time", "")) or record.get("data_time", "—"),
                display_status(draw_status),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (3, 5):
                    status_value = draw_status if column == 5 else value
                    item.setForeground(QColor(_status_color(str(status_value))))
                self.recent_table.setItem(row, column, item)

    def _render_updated(self, latest) -> None:
        text = _format_time(getattr(latest, "draw_time", "") if latest is not None else "") or "—"
        self.updated_label.setText(f"最近更新 {text}")
        self.status_update.setText(f"更新时间 {text}")
        self.health_values["updated"].setText(text)

    def _render_empty(self) -> None:
        self._render_draw(None)
        self._render_status({})
        self._render_summaries({})
        self.recent_table.setRowCount(0)
        self.updated_label.setText("最近更新 —")
        self.status_update.setText("更新时间 —")
        self.data_updated_label.setText("数据缺口：—")

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


def _snapshot_gap_count(snapshot: dict[str, Any] | None) -> int | str:
    """Summarize known integrity gaps from the already-loaded snapshot."""
    if snapshot is None:
        return "—"
    total = 0
    for check in snapshot.get("integrity", ()) or ():
        name = str(check.get("name", ""))
        if not any(token in name for token in ("缺失", "未回填")):
            continue
        match = re.search(r"(?:缺失|未回填)\s*(\d+)", str(check.get("detail", "")))
        if match:
            total += int(match.group(1))
    return total


def _vip_count(record: dict) -> str:
    value = record.get("vip100_count", record.get("vip_count", 0))
    try:
        return f"{int(value)}/100"
    except (TypeError, ValueError):
        return str(value)


def _rate_number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return -1.0
    return number if number > 1.0 else number * 100.0


def _format_rate(value: object) -> str:
    if value is None:
        return "—"
    number = _rate_number(value)
    return "—" if number < 0 else f"{number:.1f}%"


def _vip_runtime_status(value: object) -> str:
    status = str(value or "OFFLINE").upper()
    if status in {"RUNNING", "ONLINE", "HEALTHY", "HASH_OK"}:
        return "正常运行"
    return display_status(status)


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
