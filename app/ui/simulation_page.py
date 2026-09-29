from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..backtest import run_backtest
from ..database import Database
from .widgets import PageHeader, StatCard, polish_table, secondary_button


class BetExecutor:
    """Reserved execution boundary; no real betting implementation exists."""

    mode = "SIMULATION"

    def execute(self, selection, amount):
        raise RuntimeError("真实下注执行未接入；当前仅支持模拟模式")


class SimulationBetExecutor(BetExecutor):
    mode = "SIMULATION"

    def execute(self, selection, amount):
        return {"mode": self.mode, "selection": tuple(selection), "amount": float(amount)}


def _selection_text(value) -> str:
    if isinstance(value, str):
        return value
    return "、".join(str(item) for item in (value or ()))


class SimulationPage(QWidget):
    """Historical paper simulation. It never interacts with a betting app."""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.bet_executor = SimulationBetExecutor()
        self.simulation_state = "READY"
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(8)
        root.addWidget(PageHeader("模拟测试", "使用历史结果进行虚拟盈亏演算，不执行真实投注"))

        overview = QHBoxLayout()
        self.plan_card = StatCard("当前模拟方案", "—", compact=True)
        self.funds_card = StatCard("模拟资金", "¥ 1,000.00", compact=True)
        self.state_card = StatCard("模拟状态", "待开始", compact=True)
        self.execution_card = StatCard("当前执行", "等待期号", compact=True)
        for card in (self.plan_card, self.funds_card, self.state_card, self.execution_card):
            overview.addWidget(card, 1)
        root.addLayout(overview)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        status_group = QGroupBox("模拟配置")
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(16, 13, 16, 13)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(5)
        self.strategy = QComboBox()
        self.start_balance = QDoubleSpinBox()
        self.start_balance.setRange(1, 10_000_000)
        self.start_balance.setValue(1000)
        self.start_balance.setPrefix("¥ ")
        self.stake = QDoubleSpinBox()
        self.stake.setRange(0.01, 100_000)
        self.stake.setValue(10)
        self.stake.setPrefix("¥ ")
        self.selection_mode = QComboBox()
        self.selection_mode.addItems(("单组合", "双组合", "自定义组合"))
        self.strategy.setMinimumWidth(180)
        self.strategy.setToolTip("选择用于历史模拟的策略")
        self.start_balance.setToolTip("仅用于本次模拟的虚拟初始余额")
        self.stake.setToolTip("每期使用的虚拟金额")
        self.recommended_strategy = QLabel("未选择")
        self.recommended_selection = QLabel("未设置")
        self.recommended_amount = QLabel("¥ 0")
        status_layout.addWidget(QLabel("策略"), 0, 0)
        status_layout.addWidget(self.strategy, 0, 1, 1, 3)
        status_layout.addWidget(QLabel("购买组合"), 1, 0)
        status_layout.addWidget(self.recommended_selection, 1, 1, 1, 3)
        status_layout.addWidget(QLabel("模拟金额"), 2, 0)
        status_layout.addWidget(self.stake, 2, 1)
        status_layout.addWidget(QLabel("初始余额"), 2, 2)
        status_layout.addWidget(self.start_balance, 2, 3)
        self.manual_mode = QRadioButton("手动模拟")
        self.auto_mode = QRadioButton("自动模拟")
        self.manual_mode.setChecked(True)
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.manual_mode)
        mode_layout.addWidget(self.auto_mode)
        self._legacy_mode_widget = mode_widget
        mode_widget.setVisible(False)
        mode_widget.setParent(self)
        self.selection_mode.setVisible(False)
        self.selection_mode.setParent(self)
        self.period_selector = QComboBox()
        self.period_selector.addItems(("最近100期", "最近500期", "全部"))
        self.period_selector.setToolTip("选择模拟结果查看范围；模拟入口仍使用现有回测数据")
        status_layout.addWidget(QLabel("选择周期"), 4, 0)
        status_layout.addWidget(self.period_selector, 4, 1, 1, 3)
        middle.addWidget(status_group, 3)

        execution_group = QGroupBox("模拟控制")
        execution_layout = QVBoxLayout(execution_group)
        execution_layout.setContentsMargins(16, 13, 16, 13)
        execution_layout.setSpacing(10)
        execution_hint = QLabel("历史数据模拟，不会执行真实下注")
        execution_hint.setObjectName("CardSubtitle")
        execution_layout.addWidget(execution_hint)
        execution_buttons = QHBoxLayout()
        execution_buttons.setSpacing(8)
        self.start_button = QPushButton("开始模拟")
        self.start_button.clicked.connect(self._start_simulation)
        self.pause_button = QPushButton("暂停模拟")
        self.pause_button.clicked.connect(lambda: self._set_simulation_state("PAUSED", "已暂停"))
        self.stop_button = QPushButton("停止模拟")
        self.stop_button.clicked.connect(lambda: self._set_simulation_state("STOPPED", "已停止"))
        self.reset_button = QPushButton("重置模拟")
        self.reset_button.clicked.connect(self._reset_simulation)
        for button in (self.start_button, self.pause_button, self.stop_button, self.reset_button):
            button.setFixedHeight(36)
            button.setMinimumWidth(76)
            execution_buttons.addWidget(button)
        execution_layout.addLayout(execution_buttons)
        execution_layout.addStretch(1)
        middle.addWidget(execution_group, 2)
        root.addLayout(middle)

        cards = QHBoxLayout()
        self.end_balance = StatCard("当前余额", accent="blue", compact=True)
        self.net = StatCard("累计收益", accent="green", compact=True)
        self.trades = StatCard("命中次数", accent="orange", compact=True)
        self.drawdown = StatCard("最大回撤", accent="purple", compact=True)
        for card in (self.end_balance, self.net, self.trades, self.drawdown):
            card.setFixedHeight(76)
            cards.addWidget(card)
        root.addLayout(cards)

        self.advanced_settings_button = QPushButton("高级设置  ▼")
        self.advanced_settings_button.setObjectName("SecondaryAction")
        secondary_button(self.advanced_settings_button)
        self.advanced_settings_button.setFixedHeight(34)
        self.advanced_settings_button.clicked.connect(self._show_advanced_settings)
        self.report_button = QPushButton("生成测试报告")
        self.report_button.setObjectName("SecondaryAction")
        self.report_button.setFixedHeight(34)
        self.report_button.clicked.connect(self._show_test_report)
        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(8)
        advanced_row.addWidget(self.advanced_settings_button, 1)
        # Keep the report action available to existing callers, but keep the
        # primary simulation surface focused on configuration, statistics and
        # records.
        self.report_button.setVisible(False)
        root.addLayout(advanced_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["期号", "策略", "组合", "金额", "开奖结果", "结果", "盈亏"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.table, 320)
        self.table.setMinimumHeight(220)
        self.table.setMaximumHeight(16777215)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.table, 1)
        self.refresh()

    def _build_advanced_settings(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("高级设置")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        automation_group = QGroupBox("自动执行")
        self.automation_group = automation_group
        automation_group.setCheckable(True)
        automation_group.setChecked(False)
        automation_layout = QVBoxLayout(automation_group)
        automation_content = QWidget()
        automation_content_layout = QVBoxLayout(automation_content)
        automation_content_layout.setContentsMargins(4, 4, 4, 4)
        self.auto_select_strategy = QCheckBox("自动选择策略")
        self.auto_generate_plan = QCheckBox("自动生成方案")
        self.auto_record_result = QCheckBox("自动记录结果")
        self.auto_statistics = QCheckBox("自动统计收益")
        for checkbox in (self.auto_select_strategy, self.auto_generate_plan, self.auto_record_result, self.auto_statistics):
            checkbox.setChecked(True)
            automation_content_layout.addWidget(checkbox)
        automation_layout.addWidget(automation_content)
        automation_content.setVisible(False)
        automation_group.toggled.connect(automation_content.setVisible)
        layout.addWidget(automation_group)

        risk_group = QGroupBox("风险控制")
        self.risk_group = risk_group
        risk_group.setCheckable(True)
        risk_group.setChecked(False)
        risk_layout = QFormLayout(risk_group)
        risk_layout.setContentsMargins(14, 12, 14, 12)
        self.take_profit = QDoubleSpinBox(); self.take_profit.setRange(0, 10_000_000); self.take_profit.setPrefix("¥ ")
        self.stop_loss = QDoubleSpinBox(); self.stop_loss.setRange(0, 10_000_000); self.stop_loss.setPrefix("¥ ")
        self.max_error_streak = QSpinBox(); self.max_error_streak.setRange(0, 999)
        self.max_single_amount = QDoubleSpinBox(); self.max_single_amount.setRange(0, 100_000); self.max_single_amount.setPrefix("¥ ")
        self._risk_content = QWidget()
        risk_content_layout = QFormLayout(self._risk_content)
        risk_content_layout.setContentsMargins(0, 0, 0, 0)
        for label, field in (
            ("止盈", self.take_profit),
            ("止损", self.stop_loss),
            ("最大连续错误", self.max_error_streak),
            ("单期最大金额", self.max_single_amount),
        ):
            risk_content_layout.addRow(label, field)
        risk_layout.addRow(self._risk_content)
        self._risk_content.setVisible(False)
        risk_group.toggled.connect(self._risk_content.setVisible)
        layout.addWidget(risk_group)

        close_button = QPushButton("完成")
        close_button.setMinimumHeight(36)
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)
        return dialog

    def _show_advanced_settings(self):
        if not hasattr(self, "advanced_dialog"):
            self.advanced_dialog = self._build_advanced_settings()
        self.advanced_dialog.show()
        self.advanced_dialog.raise_()
        self.advanced_dialog.activateWindow()

    def _show_test_report(self) -> None:
        """Present a report from the already-rendered simulation summary."""
        dialog = QDialog(self)
        dialog.setWindowTitle("模拟测试报告")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        title = QLabel("模拟测试报告")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        period = QLabel(f"统计周期：{self.period_selector.currentText()}")
        layout.addWidget(period)
        for label, card in (
            ("结束余额", self.end_balance),
            ("累计收益", self.net),
            ("命中次数", self.trades),
            ("最大回撤", self.drawdown),
        ):
            value = QLabel(f"{label}：{card.value_label.text()}")
            value.setObjectName("CardValue")
            layout.addWidget(value)
        rows = QLabel(f"模拟记录：{self.table.rowCount()} 条")
        rows.setObjectName("Muted")
        layout.addWidget(rows)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def _start_simulation(self):
        self._set_simulation_state("RUNNING", "运行中")
        self.run_simulation()

    def _set_simulation_state(self, state: str, label: str):
        self.simulation_state = state
        self.state_card.set_value(label)

    def _reset_simulation(self):
        self.simulation_state = "READY"
        self.state_card.set_value("待开始")
        self.execution_card.set_value("等待期号")
        self.funds_card.set_value(f"¥ {self.start_balance.value():,.2f}")
        self.plan_card.set_value("—")
        self.recommended_strategy.setText("未选择")
        self.recommended_selection.setText("未设置")
        self.recommended_amount.setText("¥ 0")
        self.end_balance.set_value("—")
        self.net.set_value("—")
        self.trades.set_value("0")
        self.drawdown.set_value("—")
        self.table.setRowCount(0)

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
        self.plan_card.set_value(str(strategy.get("name", "—")))
        self.funds_card.set_value(f"¥ {balance:,.2f}")
        self.state_card.set_value("已完成")
        self.execution_card.set_value(str(rows[-1][0].get("issue_no", "—")) if rows else "无执行记录")
        self.recommended_strategy.setText(str(strategy.get("name", "—")))
        self.recommended_selection.setText(
            _selection_text(rows[-1][0].get("selected")) if rows else "暂无"
        )
        self.recommended_amount.setText(f"¥ {stake:,.2f}")
        self.table.setRowCount(len(rows))
        for row, (detail, change, current_balance) in enumerate(rows):
            values = [
                detail["issue_no"],
                str(self.strategy.currentText() or "—").split(" · ", 1)[0],
                _selection_text(detail.get("selected")),
                f"¥ {stake:,.2f}",
                detail["actual_combo"],
                "命中" if detail["hit"] else "未命中",
                f"{change:+.2f}",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, cell)
