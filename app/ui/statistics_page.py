from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..database import Database
from .widgets import StatCard


class StatisticsPage(QWidget):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        title = QLabel("数据统计")
        title.setObjectName("PageTitle")
        hint = QLabel("VIP 统计结果直接来自当前 SQLite 数据库。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.vip_records = StatCard("VIP 记录", accent="purple", icon="V")
        self.vip_rate = StatCard("VIP 计划命中率", accent="orange", icon="✓")
        for index, card in enumerate((self.vip_records, self.vip_rate)):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        root.addLayout(cards)

        section = QLabel("独立数据汇总")
        section.setObjectName("SectionTitle")
        root.addWidget(section)
        self.summary = QTableWidget(1, 10)
        self.summary.setHorizontalHeaderLabels(
            ["类型", "记录", "期数", "已开奖", "待开奖", "待检查", "无效", "正确计划", "错误计划", "计划命中率"]
        )
        self.summary.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary.setAlternatingRowColors(True)
        self.summary.verticalHeader().setVisible(False)
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary.setMaximumHeight(150)
        root.addWidget(self.summary)

        backtest_title = QLabel("最近策略回测")
        backtest_title.setObjectName("SectionTitle")
        root.addWidget(backtest_title)
        self.backtests = QTableWidget(1, 7)
        self.backtests.setHorizontalHeaderLabels(
            ["类型", "策略", "符合次数", "命中", "未命中", "命中率", "运行时间"]
        )
        self.backtests.setEditTriggers(QTableWidget.NoEditTriggers)
        self.backtests.setSelectionBehavior(QTableWidget.SelectRows)
        self.backtests.verticalHeader().setVisible(False)
        self.backtests.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.backtests, 1)
        self.refresh()

    def refresh(self) -> None:
        data = self.database.statistics()
        vip = data["VIP"]
        self.vip_records.set_value(vip["records"])
        self.vip_records.set_subtitle(f"{vip['issues']} 个独立期号")
        self.vip_rate.set_value(f"{vip['plan_hit_rate']:.2f}%")
        self.vip_rate.set_subtitle(f"正确 {vip['correct_plans']} / 错误 {vip['wrong_plans']}")
        for row, source in enumerate(("VIP",)):
            item = data[source]
            values = [source, item["records"], item["issues"], item["completed"], item["pending"],
                      item["review"], item["invalid"], item["correct_plans"], item["wrong_plans"],
                      f"{item['plan_hit_rate']:.2f}%"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignCenter)
                self.summary.setItem(row, column, cell)
            backtest = item["backtest"]
            backtest_values = [source, "—", 0, 0, 0, "0.00%", "—"]
            if backtest:
                backtest_values = [source, backtest["strategy_name"], backtest["matched"], backtest["hits"],
                                   backtest["misses"], f"{backtest['hit_rate']:.2f}%",
                                   backtest["created_at"].replace("T", " ")]
            for column, value in enumerate(backtest_values):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignCenter)
                self.backtests.setItem(row, column, cell)
