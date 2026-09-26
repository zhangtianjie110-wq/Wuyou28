from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..auto_backtest import convert_prediction, run_train_validation_backtest, run_walk_forward, scan_conditions
from ..constants import COMBINATIONS
from ..database import Database
from .widgets import danger_button, secondary_button


class StrategyPage(QWidget):
    """Research-only strategy page backed by the v1.1 read-only engine."""

    data_changed = Signal()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.current_strategy_id = None
        self.last_strategy = None
        self.last_result = None
        self._result_rows = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(10)
        title = QLabel("策略回测")
        title.setObjectName("PageTitle")
        hint = QLabel("v1.1 只读分析：条件在训练集确定，验证集只做一次性评估。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setMinimumWidth(265)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(QLabel("已保存策略"))
        self.strategy_list = QListWidget()
        self.strategy_list.currentItemChanged.connect(self._load_selected)
        left_layout.addWidget(self.strategy_list, 1)
        list_buttons = QHBoxLayout()
        new_button = QPushButton("新建")
        delete_button = QPushButton("删除")
        secondary_button(new_button)
        danger_button(delete_button)
        new_button.clicked.connect(self._new)
        delete_button.clicked.connect(self._delete)
        list_buttons.addWidget(new_button)
        list_buttons.addWidget(delete_button)
        left_layout.addLayout(list_buttons)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        form_group = QGroupBox("条件与数据范围")
        form = QGridLayout(form_group)
        self.name = QLineEdit("策略A")
        self.source = QComboBox()
        self.source.addItems(["VIP"])
        self.data_range = QComboBox()
        self.data_range.addItems(["全部", "最近100", "最近200", "最近500", "自定义"])
        self.custom_count = self._spin(1, 100000, 500)
        self.custom_count.setEnabled(False)
        self.data_range.currentTextChanged.connect(lambda value: self.custom_count.setEnabled(value == "自定义"))
        self.selection = QComboBox()
        self.selection.addItem("最小1组", {"min_groups": 1})
        self.selection.addItem("最小2组", {"min_groups": 2})
        self.selection.addItem("指定双组合", {"specified": True})
        self.pair = QComboBox()
        for left_combo in COMBINATIONS:
            for right_combo in COMBINATIONS:
                if COMBINATIONS.index(left_combo) < COMBINATIONS.index(right_combo):
                    self.pair.addItem(f"{left_combo} + {right_combo}", [left_combo, right_combo])
        self.pair.setEnabled(False)
        self.selection.currentIndexChanged.connect(lambda index: self.pair.setEnabled(index == 2))
        self.min_from = self._spin(0, 100, 0)
        self.min_to = self._spin(0, 100, 100)
        self.diff_from = self._spin(0, 100, 0)
        self.diff_to = self._spin(0, 100, 100)
        self.spread_from = self._spin(0, 100, 0)
        self.spread_to = self._spin(0, 100, 100)
        self.allow_tie = QCheckBox("允许最小值并列")
        self.allow_tie.setChecked(True)
        self.rank = QComboBox()
        self.rank.addItem("不限制排名", None)
        self.rank.addItem("大单 < 大双", ["大单<大双"])
        self.rank.addItem("大双 < 小单", ["大双<小单"])
        self.mode = QComboBox()
        self.mode.addItems(["70/30 训练验证", "Walk-Forward"])
        self.train_ratio = QDoubleSpinBox()
        self.train_ratio.setRange(0.1, 0.9)
        self.train_ratio.setSingleStep(0.05)
        self.train_ratio.setValue(0.7)
        self.train_window = self._spin(1, 100000, 200)
        self.validation_window = self._spin(1, 100000, 50)
        self.step = self._spin(1, 100000, 50)
        self._add(form, "策略名称", self.name, 0, 0)
        self._add(form, "数据源", self.source, 0, 2)
        self._add(form, "数据范围", self.data_range, 1, 0)
        self._add(form, "自定义期数", self.custom_count, 1, 2)
        self._add(form, "触发方式", self.selection, 2, 0)
        self._add(form, "指定双组合", self.pair, 2, 2)
        self._add(form, "最小值区间", self._range_widget(self.min_from, self.min_to), 3, 0)
        self._add(form, "最小差值区间", self._range_widget(self.diff_from, self.diff_to), 3, 2)
        self._add(form, "最大最小差区间", self._range_widget(self.spread_from, self.spread_to), 4, 0)
        self._add(form, "排名关系", self.rank, 4, 2)
        self._add(form, "验证模式", self.mode, 5, 0)
        self._add(form, "训练比例", self.train_ratio, 5, 2)
        self._add(form, "滚动训练期数", self.train_window, 6, 0)
        self._add(form, "滚动验证期数", self.validation_window, 6, 2)
        self._add(form, "滚动步长", self.step, 7, 0)
        form.addWidget(self.allow_tie, 7, 2)
        right_layout.addWidget(form_group)

        actions = QHBoxLayout()
        for label, slot in (("保存策略", self._save), ("开始回测", self._run), ("自动扫描", self._scan), ("Walk-Forward", self._walk_forward)):
            button = QPushButton(label)
            secondary_button(button)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        right_layout.addLayout(actions)
        self.warning = QLabel("")
        self.warning.setStyleSheet("color: #C26A00; font-weight: 700;")
        right_layout.addWidget(self.warning)
        self.summary = QLabel("尚未运行回测")
        self.summary.setObjectName("Muted")
        right_layout.addWidget(self.summary)

        result_group = QGroupBox("结果列表（点击查看逐期记录）")
        result_layout = QVBoxLayout(result_group)
        self.results = QTableWidget(0, 11)
        self.results.setHorizontalHeaderLabels(["条件", "触发次数", "有效样本", "训练命中率", "验证命中率", "差值", "最近30", "最近50", "最大连中", "最大连错", "平均触发间隔"])
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.currentCellChanged.connect(self._result_selected)
        result_layout.addWidget(self.results)
        right_layout.addWidget(result_group, 2)
        detail_group = QGroupBox("单策略详细记录")
        detail_layout = QVBoxLayout(detail_group)
        self.details = QTableWidget(0, 7)
        self.details.setHorizontalHeaderLabels(["期号", "四组数量", "条件参数", "实际开奖结果", "实际组合", "结果", "数据集"])
        self.details.setEditTriggers(QTableWidget.NoEditTriggers)
        self.details.verticalHeader().setVisible(False)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        detail_layout.addWidget(self.details)
        right_layout.addWidget(detail_group, 2)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        self.refresh()

    @staticmethod
    def _spin(minimum, maximum, value):
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    @staticmethod
    def _range_widget(start, end):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(start)
        layout.addWidget(QLabel("至"))
        layout.addWidget(end)
        return widget

    @staticmethod
    def _add(form, label, widget, row, column):
        form.addWidget(QLabel(label), row, column)
        form.addWidget(widget, row, column + 1)

    def _conditions(self):
        selection = self.selection.currentData() or {"min_groups": 1}
        params = {
            "min_value_min": self.min_from.value(), "min_value_max": self.min_to.value(),
            "lowest_two_diff_min": self.diff_from.value(), "lowest_two_diff_max": self.diff_to.value(),
            "max_min_diff_min": self.spread_from.value(), "max_min_diff_max": self.spread_to.value(),
            "allow_tie": self.allow_tie.isChecked(),
        }
        if selection.get("specified"):
            params["selected_groups"] = list(self.pair.currentData())
        else:
            params["min_groups"] = int(selection.get("min_groups", 1))
        if self.rank.currentData():
            params["rank_relations"] = self.rank.currentData()
        return params

    def _records(self):
        records = self.database.valid_backtest_records(self.source.currentText())
        label = self.data_range.currentText()
        if label == "全部":
            return records
        count = self.custom_count.value() if label == "自定义" else int(label.replace("最近", ""))
        return records[-count:]

    def _strategy_parameters(self):
        return {
            "engine": "auto_backtest_v1.1", "conditions": self._conditions(),
            "data_range": self.data_range.currentText(), "custom_count": self.custom_count.value(),
            "mode": self.mode.currentText(), "train_ratio": self.train_ratio.value(),
            "train_window": self.train_window.value(), "validation_window": self.validation_window.value(),
            "step": self.step.value(), "enabled": True,
        }

    def _save(self, show_message=True):
        if not self.name.text().strip():
            QMessageBox.warning(self, "无法保存", "策略名称不能为空。")
            return None
        conditions = self._conditions()
        if (
            conditions["min_value_min"] > conditions["min_value_max"]
            or conditions["lowest_two_diff_min"] > conditions["lowest_two_diff_max"]
            or conditions["max_min_diff_min"] > conditions["max_min_diff_max"]
        ):
            QMessageBox.warning(self, "参数错误", "条件区间起始值不能大于结束值。")
            return None
        method = "lowest_two" if conditions.get("min_groups") == 2 or conditions.get("selected_groups") else "lowest_one"
        try:
            strategy_id = self.database.save_strategy(self.name.text().strip(), self.source.currentText(), method, self._strategy_parameters())
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return None
        self.current_strategy_id = strategy_id
        self.refresh()
        self.data_changed.emit()
        if show_message:
            QMessageBox.information(self, "保存成功", "策略条件已保存。")
        return strategy_id

    def _run(self):
        strategy_id = self._save(False)
        if strategy_id is None:
            return
        records = self._records()
        conditions = self._conditions()
        is_walk_forward = self.mode.currentIndex() == 1
        if is_walk_forward:
            result = run_walk_forward(records, conditions, train_window=self.train_window.value(), validation_window=self.validation_window.value(), step=self.step.value(), source_type=self.source.currentText())
        else:
            result = run_train_validation_backtest(records, conditions, train_ratio=self.train_ratio.value(), source_type=self.source.currentText())
        if is_walk_forward:
            rows = result.get("windows", [])
            result["matched"] = sum(item["validation"].get("matched_periods", 0) for item in rows)
            result["hits"] = sum(item["validation"].get("hits", 0) for item in rows)
            result["misses"] = sum(item["validation"].get("misses", 0) for item in rows)
            result["hit_rate"] = round(result["hits"] / (result["hits"] + result["misses"]) * 100, 2) if result["hits"] + result["misses"] else 0.0
            train = {}
            validation = {}
        else:
            rows = [result]
            train = result.get("train", {})
            validation = result.get("validation", {})
        strategy = self.database.get_strategy(strategy_id)
        if strategy:
            self.database.save_backtest_result(strategy, result)
            self.last_strategy = strategy
        self.last_result = result
        self._show_results(rows, records)
        self.data_changed.emit()

    def _scan(self):
        strategy_id = self._save(False)
        if strategy_id is None:
            return
        records = self._records()
        result = scan_conditions(records, source_type=self.source.currentText(), train_ratio=self.train_ratio.value(), max_candidates=64)
        wrapper = {"scan": result, "matched": 0, "hits": 0, "misses": 0, "hit_rate": 0.0, "conditions": {"scan_max_candidates": 64}, "selection_basis": "training_only"}
        strategy = self.database.get_strategy(strategy_id)
        if strategy:
            self.database.save_backtest_result(strategy, wrapper)
            self.last_strategy = strategy
        self.last_result = result
        self._show_results(result["results"], records)
        self.warning.setText(f"自动扫描测试了 {result['tested_conditions']} 组条件；仅展示统计，不推荐策略。")
        self.data_changed.emit()

    def _walk_forward(self):
        self.mode.setCurrentIndex(1)
        self._run()

    def _show_results(self, rows, records):
        self._result_rows = rows
        self.results.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            train, validation = item.get("train", {}), item.get("validation", {})
            overall = item.get("overall", train)
            values = [
                json.dumps(item.get("conditions", {}), ensure_ascii=False, sort_keys=True),
                train.get("matched_periods", 0) + validation.get("matched_periods", 0),
                train.get("valid_samples", 0) + validation.get("valid_samples", 0),
                self._rate(train.get("hit_rate")), self._rate(validation.get("hit_rate")),
                self._rate_diff(item.get("hit_rate_difference")), self._recent(overall, "30"), self._recent(overall, "50"),
                overall.get("max_consecutive_hits", "—"), overall.get("max_consecutive_misses", "—"), overall.get("average_condition_interval", "—"),
            ]
            for column, value in enumerate(values):
                self.results.setItem(row_index, column, QTableWidgetItem(str(value)))
        if rows:
            self.results.setCurrentCell(0, 0)
        self.summary.setText(self._summary_text(rows))

    @staticmethod
    def _rate(value):
        return "—" if value is None else f"{value:.2f}%"

    @staticmethod
    def _rate_diff(value):
        return "—" if value is None else f"{value:+.2f}%"

    @staticmethod
    def _recent(data, window):
        item = data.get("recent", {}).get(window, {})
        return "—" if not item.get("samples") else f"{item['hits']}/{item['samples']}"

    @staticmethod
    def _summary_text(rows):
        if not rows:
            return "没有可展示的结果"
        first = rows[0]
        return f"训练样本 {first.get('train', {}).get('total_periods', 0)}，训练触发 {first.get('train', {}).get('matched_periods', 0)}，验证样本 {first.get('validation', {}).get('total_periods', 0)}，验证触发 {first.get('validation', {}).get('matched_periods', 0)}"

    def _result_selected(self, row, _column, _previous_row, _previous_column):
        if 0 <= row < len(self._result_rows):
            self._show_details(self._result_rows[row], self._records())

    def _show_details(self, result, records):
        condition = result.get("conditions", {})
        details = result.get("details", [])
        if not details and result.get("train"):
            details = result["train"].get("details", []) + result["validation"].get("details", [])
        by_issue = {str(item.get("issue_no")): item for item in records}
        self.details.setRowCount(len(details))
        for row_index, item in enumerate(details):
            source = by_issue.get(str(item.get("issue_no")), {})
            converted = convert_prediction(source) if source else {}
            counts = converted.get("counts", {})
            values = [item.get("issue_no", ""), " / ".join(str(counts.get(combo, "")) for combo in COMBINATIONS), json.dumps(condition, ensure_ascii=False, sort_keys=True), source.get("actual_result", ""), item.get("actual_combo", converted.get("actual_combo", "")), "待开奖" if item.get("hit") is None else ("命中" if item.get("hit") else "未命中"), item.get("dataset", "训练/验证")]
            for column, value in enumerate(values):
                self.details.setItem(row_index, column, QTableWidgetItem(str(value)))

    def refresh(self):
        selected_id = self.current_strategy_id
        self.strategy_list.blockSignals(True)
        self.strategy_list.clear()
        select_row = -1
        for index, strategy in enumerate(self.database.list_strategies()):
            label = "v1.1" if strategy["parameters"].get("engine") == "auto_backtest_v1.1" else strategy["method"]
            item = QListWidgetItem(f"{strategy['name']} · {strategy['source_type']} · {label}")
            item.setData(Qt.UserRole, strategy["id"])
            self.strategy_list.addItem(item)
            if strategy["id"] == selected_id:
                select_row = index
        self.strategy_list.blockSignals(False)
        if select_row >= 0:
            self.strategy_list.setCurrentRow(select_row)

    def _new(self):
        self.current_strategy_id = None
        self.strategy_list.clearSelection()
        self.name.setText("策略A")
        self.source.setCurrentIndex(0)
        self.data_range.setCurrentIndex(0)
        self.selection.setCurrentIndex(0)
        self.min_from.setValue(0)
        self.min_to.setValue(100)
        self.diff_from.setValue(0)
        self.diff_to.setValue(100)
        self.spread_from.setValue(0)
        self.spread_to.setValue(100)
        self.allow_tie.setChecked(True)
        self.rank.setCurrentIndex(0)

    def _load_selected(self, current, _previous):
        if current is None:
            return
        strategy = self.database.get_strategy(int(current.data(Qt.UserRole)))
        if not strategy:
            return
        self.current_strategy_id = strategy["id"]
        self.name.setText(strategy["name"])
        self.source.setCurrentText(strategy["source_type"])
        params = strategy["parameters"]
        if params.get("engine") != "auto_backtest_v1.1":
            return
        self.data_range.setCurrentText(params.get("data_range", "全部"))
        self.custom_count.setValue(int(params.get("custom_count", 500)))
        self.train_ratio.setValue(float(params.get("train_ratio", 0.7)))
        self.train_window.setValue(int(params.get("train_window", 200)))
        self.validation_window.setValue(int(params.get("validation_window", 50)))
        self.step.setValue(int(params.get("step", 50)))
        conditions = params.get("conditions", {})
        self.min_from.setValue(int(conditions.get("min_value_min", 0)))
        self.min_to.setValue(int(conditions.get("min_value_max", 100)))
        self.diff_from.setValue(int(conditions.get("lowest_two_diff_min", 0)))
        self.diff_to.setValue(int(conditions.get("lowest_two_diff_max", 100)))
        self.spread_from.setValue(int(conditions.get("max_min_diff_min", 0)))
        self.spread_to.setValue(int(conditions.get("max_min_diff_max", 100)))
        self.allow_tie.setChecked(bool(conditions.get("allow_tie", True)))

    def _delete(self):
        if self.current_strategy_id is None:
            return
        self.database.delete_strategy(self.current_strategy_id)
        self.current_strategy_id = None
        self.last_result = None
        self._new()
        self.refresh()
        self.data_changed.emit()
