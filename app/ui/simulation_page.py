from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..backtest import run_backtest
from ..database import Database
from .widgets import StatCard


class SimulationPage(QWidget):
    """Historical paper simulation. It never interacts with a betting app."""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        title = QLabel("模拟投注")
        title.setObjectName("PageTitle")
        hint = QLabel("使用真实历史结果进行虚拟盈亏演算；仅用于策略观察，不执行任何真实投注。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        controls = QHBoxLayout()
        form = QFormLayout()
        self.strategy = QComboBox()
        self.start_balance = QDoubleSpinBox()
        self.start_balance.setRange(1, 10_000_000)
        self.start_balance.setValue(1000)
        self.start_balance.setPrefix("¥ ")
        self.stake = QDoubleSpinBox()
        self.stake.setRange(0.01, 100_000)
        self.stake.setValue(10)
        self.stake.setPrefix("¥ ")
        form.addRow("启用策略", self.strategy)
        form.addRow("初始虚拟余额", self.start_balance)
        form.addRow("每次虚拟金额", self.stake)
        controls.addLayout(form)
        controls.addSpacing(18)
        run_button = QPushButton("运行历史模拟")
        run_button.setMinimumHeight(44)
        run_button.clicked.connect(self.run_simulation)
        controls.addWidget(run_button)
        controls.addStretch()
        root.addLayout(controls)

        cards = QHBoxLayout()
        self.end_balance = StatCard("结束余额", accent="blue")
        self.net = StatCard("模拟净值", accent="green")
        self.trades = StatCard("符合次数", accent="orange")
        self.drawdown = StatCard("最大回撤", accent="purple")
        for card in (self.end_balance, self.net, self.trades, self.drawdown):
            cards.addWidget(card)
        root.addLayout(cards)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["期号", "类型", "策略选择", "开奖结果", "结果", "本期盈亏", "模拟余额"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        selected = self.strategy.currentData()
        self.strategy.clear()
        for strategy in self.database.list_strategies():
            if strategy["enabled"]:
                self.strategy.addItem(f"{strategy['name']} · {strategy['source_type']}", strategy["id"])
        if selected is not None:
            index = self.strategy.findData(selected)
            if index >= 0:
                self.strategy.setCurrentIndex(index)

    def run_simulation(self) -> None:
        strategy_id = self.strategy.currentData()
        if strategy_id is None:
            QMessageBox.information(self, "没有启用策略", "请先在策略回测页面新增并启用一个策略。")
            return
        strategy = self.database.get_strategy(int(strategy_id))
        if not strategy:
            self.refresh()
            return
        records = self.database.valid_backtest_records(strategy["source_type"])
        ratio = float(self.database.get_setting("train_ratio", "0.7"))
        result = run_backtest(records, strategy["method"], strategy["parameters"], ratio)
        balance = float(self.start_balance.value())
        initial = balance
        stake = float(self.stake.value())
        peak = balance
        max_drawdown = 0.0
        rows = []
        for detail in result["details"]:
            change = stake if detail["hit"] else -stake
            balance += change
            peak = max(peak, balance)
            max_drawdown = max(max_drawdown, peak - balance)
            rows.append((detail, change, balance))
        self.end_balance.set_value(f"¥ {balance:,.2f}")
        net = balance - initial
        self.net.set_value(f"{'+' if net > 0 else ''}¥ {net:,.2f}")
        self.trades.set_value(len(rows))
        self.trades.set_subtitle(f"命中 {result['hits']} / 未命中 {result['misses']}")
        self.drawdown.set_value(f"¥ {max_drawdown:,.2f}")
        self.table.setRowCount(len(rows))
        for row, (detail, change, current_balance) in enumerate(rows):
            values = [detail["issue_no"], detail["source_type"], detail["selected"], detail["actual_combo"],
                      "命中" if detail["hit"] else "未命中", f"{change:+.2f}", f"{current_balance:,.2f}"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, cell)
