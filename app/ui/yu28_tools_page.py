from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from ..integration import IntegrationGateway
from .widgets import PageHeader, StatCard, polish_table


class Yu28ToolsPage(QWidget):
    """Temporary read-only UI for the YU28 tools exposed by IntegrationGateway."""

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("常用工具")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._stats_tab(), "今日统计")
        self.tabs.addTab(self._omission_tab(), "遗漏")
        self.tabs.addTab(self._dragon_tab(), "长龙")
        self.tabs.addTab(self._trend_tab(), "文本走势")
        self.tabs.currentChanged.connect(self._load_tab)
        root.addWidget(self.tabs, 1)

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(table, 360)
        return table

    @staticmethod
    def _tab_layout() -> tuple[QWidget, QVBoxLayout]:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        return tab, layout

    def _stats_tab(self) -> QWidget:
        tab, layout = self._tab_layout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.load_daily_stats)
        layout.addWidget(refresh, 0)
        self.stats_table = self._table(("项目", "次数"))
        layout.addWidget(self.stats_table)
        return tab

    def _omission_tab(self) -> QWidget:
        tab, layout = self._tab_layout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.load_omission)
        layout.addWidget(refresh, 0)
        self.omission_table = self._table(("项目", "遗漏期数"))
        layout.addWidget(self.omission_table)
        return tab

    def _dragon_tab(self) -> QWidget:
        tab, layout = self._tab_layout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.load_long_dragon)
        layout.addWidget(refresh, 0)
        self.dragon_table = self._table(
            ("类型", "内容", "连续期数", "起始期号", "当前期号", "状态")
        )
        layout.addWidget(self.dragon_table)
        return tab

    def _trend_tab(self) -> QWidget:
        tab, layout = self._tab_layout()
        controls = QHBoxLayout()
        self.trend_count = QSpinBox()
        self.trend_count.setRange(1, 100)
        self.trend_count.setValue(20)
        self.trend_count.setSuffix(" 期")
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.load_text_trend)
        controls.addWidget(QLabel("显示期数"))
        controls.addWidget(self.trend_count)
        controls.addWidget(refresh)
        controls.addStretch()
        layout.addLayout(controls)
        self.trend_countdown = QLabel("下期倒计时 —")
        self.trend_countdown.setObjectName("Muted")
        layout.addWidget(self.trend_countdown)
        self.trend_table = self._table(("期号", "开奖时间", "开奖号码", "组合"))
        layout.addWidget(self.trend_table)
        return tab

    def refresh(self) -> None:
        self._load_tab(self.tabs.currentIndex())

    def _load_tab(self, index: int) -> None:
        loaders = {
            0: self.load_daily_stats,
            1: self.load_omission,
            2: self.load_long_dragon,
            3: self.load_text_trend,
        }
        loader = loaders.get(index)
        if loader is not None:
            loader()

    def load_daily_stats(self) -> None:
        try:
            self._set_rows(self.stats_table, _daily_stats_rows(self.gateway))
            self._clear_error()
        except Exception as exc:
            self.stats_table.setRowCount(0)
            self._show_error(f"今日统计读取失败：{exc}")

    def load_omission(self) -> None:
        try:
            payload = self.gateway.omission()
            self._set_rows(self.omission_table, tuple(payload.get("data", {}).items()))
            self._clear_error()
        except Exception as exc:
            self.omission_table.setRowCount(0)
            self._show_error(f"遗漏读取失败：{exc}")

    def load_long_dragon(self) -> None:
        try:
            self._set_rows(self.dragon_table, _long_dragon_rows(self.gateway))
            self._clear_error()
        except Exception as exc:
            self.dragon_table.setRowCount(0)
            self._show_error(f"长龙读取失败：{exc}")

    def load_text_trend(self) -> None:
        try:
            payload, rows = _text_trend_rows(self.gateway, self.trend_count.value())
            self._set_rows(self.trend_table, rows)
            self.trend_countdown.setText(
                f"下期倒计时 {payload.get('countdown') or '—'}"
            )
            self._clear_error()
        except Exception as exc:
            self.trend_table.setRowCount(0)
            self.trend_countdown.setText("下期倒计时 —")
            self._show_error(f"文本走势读取失败：{exc}")

    @staticmethod
    def _set_rows(table: QTableWidget, rows) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _clear_error(self) -> None:
        self.alert.clear()
        self.alert.setVisible(False)


class _StandaloneYu28Page(QWidget):
    def __init__(self, title: str, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 20, 20, 20)
        self.root.setSpacing(10)
        self.page_header = PageHeader(title, "YU28工具数据只读查看")
        self.root.addWidget(self.page_header)
        self.alert = QLabel()
        self.alert.setObjectName("DangerText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        self.root.addWidget(self.alert)

    def _show_error(self, message: str) -> None:
        self.alert.setText(message)
        self.alert.setVisible(True)

    def _clear_error(self) -> None:
        self.alert.clear()
        self.alert.setVisible(False)


class LotteryStatsPage(_StandaloneYu28Page):
    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__("开奖统计", gateway, parent)
        self.table = Yu28ToolsPage._table(("项目", "次数"))
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        try:
            Yu28ToolsPage._set_rows(self.table, _daily_stats_rows(self.gateway))
            self._clear_error()
        except Exception as exc:
            self.table.setRowCount(0)
            self._show_error(f"开奖统计读取失败：{exc}")


class LongDragonStatsPage(_StandaloneYu28Page):
    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__("长龙统计", gateway, parent)
        # This is the formal navigation page. Keep its content compact and
        # leave the full viewport to the read-only results table.
        self.root.setContentsMargins(16, 6, 16, 8)
        self.root.setSpacing(5)
        self.page_header.subtitle_label.clear()
        self.page_header.subtitle_label.setVisible(False)
        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.current_card = StatCard("当前长龙", "—", compact=True)
        self.max_card = StatCard("历史最大长龙", "—", compact=True)
        self.status_card = StatCard("当前状态", "—", compact=True)
        for card in (self.current_card, self.max_card, self.status_card):
            card.setFixedHeight(96)
            summary.addWidget(card, 1)
        self.root.addLayout(summary)
        self.table = Yu28ToolsPage._table(
            ("类型", "内容", "连续期数", "起始期号", "当前期号", "状态")
        )
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setMinimumHeight(260)
        self.table.setMaximumHeight(16777215)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        try:
            rows = _long_dragon_rows(self.gateway)
            Yu28ToolsPage._set_rows(self.table, rows)
            if rows:
                lengths = [int(row[2]) for row in rows if str(row[2]).isdigit()]
                self.current_card.set_value(str(rows[0][2]))
                self.max_card.set_value(str(max(lengths, default=0)))
                self.status_card.set_value(str(rows[0][5]))
            else:
                for card in (self.current_card, self.max_card, self.status_card):
                    card.set_value("—")
            self._clear_error()
        except Exception as exc:
            self.table.setRowCount(0)
            self._show_error(f"长龙统计读取失败：{exc}")


class HistoryTrendPage(_StandaloneYu28Page):
    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__("历史走势", gateway, parent)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("文本模式 · 显示期数"))
        self.trend_count = QSpinBox()
        self.trend_count.setRange(1, 100)
        self.trend_count.setValue(20)
        self.trend_count.setSuffix(" 期")
        controls.addWidget(self.trend_count)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        controls.addStretch()
        self.root.addLayout(controls)
        self.countdown = QLabel("下期倒计时 —")
        self.countdown.setObjectName("Muted")
        self.root.addWidget(self.countdown)
        self.table = Yu28ToolsPage._table(("期号", "开奖时间", "开奖号码", "组合"))
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        try:
            payload, rows = _text_trend_rows(self.gateway, self.trend_count.value())
            Yu28ToolsPage._set_rows(self.table, rows)
            self.countdown.setText(f"下期倒计时 {payload.get('countdown') or '—'}")
            self._clear_error()
        except Exception as exc:
            self.table.setRowCount(0)
            self.countdown.setText("下期倒计时 —")
            self._show_error(f"历史走势读取失败：{exc}")


def _daily_stats_rows(gateway: IntegrationGateway) -> tuple:
    payload = gateway.daily_stats()
    return tuple(payload.get("data", {}).items())


def _long_dragon_rows(gateway: IntegrationGateway) -> tuple:
    payload = gateway.long_dragon()
    return tuple(
        (
            row["type"],
            row["content"],
            row["count"],
            row["start"],
            row["current"],
            row["status"],
        )
        for row in payload.get("data", ())
    )


def _text_trend_rows(gateway: IntegrationGateway, limit: int) -> tuple[dict, tuple]:
    payload = gateway.text_trend(limit)
    rows = tuple(
        (draw.nbr, draw.time, draw.number, draw.combination)
        for draw in payload.get("data", ())
    )
    return payload, rows
