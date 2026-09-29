from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..auto_backtest import run_condition_backtest
from ..constants import COMBINATIONS
from ..database import Database
from ..strategy_scanner import StrategyConditionGenerator, StrategyScanner
from .widgets import PageHeader, StatCard, polish_table, secondary_button


CONDITION_PRESETS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("最少选择1组", {"min_groups": 1}),
    ("最少选择2组", {"min_groups": 2}),
    ("最小值不并列", {"allow_tie": False}),
    ("指定最低双组合", {"selected_groups": [COMBINATIONS[0], COMBINATIONS[1]]}),
    ("最大最小差不超过20", {"max_min_diff_max": 20}),
)


class StrategyExperimentPage(QWidget):
    """Small UI entry point for one-condition strategy experiments.

    The page only assembles condition parameters and delegates evaluation to
    ``auto_backtest``.  It does not implement a second research engine.
    """

    data_changed = Signal()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self._last_result: dict[str, Any] | None = None
        self._last_conditions: dict[str, Any] = {}
        self._last_records: list[dict[str, Any]] = []
        self._generated_conditions: list[dict[str, Any]] = []
        self._scan_results: list[dict[str, Any]] = []
        self._stopped = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 12)
        root.setSpacing(8)
        root.addWidget(PageHeader("策略实验室", "条件生成、回测分析与策略保存"))

        source_card = QFrame()
        source_card.setObjectName("Card")
        source_layout = QHBoxLayout(source_card)
        source_layout.setContentsMargins(12, 8, 12, 8)
        source_layout.addWidget(QLabel("数据源"))
        self.source = QComboBox()
        self.source.addItem("VIP100", "VIP")
        self.source.addItem("智能选法数据", "SMART")
        self.source.currentIndexChanged.connect(self.refresh)
        source_layout.addWidget(self.source)
        self.source_status = QLabel("—")
        self.source_status.setObjectName("Muted")
        source_layout.addWidget(self.source_status)
        source_layout.addStretch()
        root.addWidget(source_card)

        conditions_group = QGroupBox("条件管理")
        conditions_layout = QVBoxLayout(conditions_group)
        conditions_layout.setContentsMargins(10, 8, 10, 8)
        conditions_toolbar = QHBoxLayout()
        conditions_toolbar.addWidget(QLabel("当前条件数量"))
        self.condition_count = QLabel("0")
        self.condition_count.setObjectName("StatNumber")
        conditions_toolbar.addWidget(self.condition_count)
        conditions_toolbar.addStretch()
        conditions_toolbar.addWidget(QLabel("条件模板"))
        self.condition_preset = QComboBox()
        for label, _condition in CONDITION_PRESETS:
            self.condition_preset.addItem(label)
        conditions_toolbar.addWidget(self.condition_preset)
        self.add_condition_button = QPushButton("新增条件")
        self.add_condition_button.setObjectName("PrimaryAction")
        self.add_condition_button.clicked.connect(self._add_condition)
        conditions_toolbar.addWidget(self.add_condition_button)
        self.delete_condition_button = QPushButton("删除条件")
        secondary_button(self.delete_condition_button)
        self.delete_condition_button.clicked.connect(self._delete_condition)
        conditions_toolbar.addWidget(self.delete_condition_button)
        self.import_condition_button = QPushButton("导入条件")
        secondary_button(self.import_condition_button)
        self.import_condition_button.clicked.connect(self._import_conditions)
        conditions_toolbar.addWidget(self.import_condition_button)
        self.export_condition_button = QPushButton("导出条件")
        secondary_button(self.export_condition_button)
        self.export_condition_button.clicked.connect(self._export_conditions)
        conditions_toolbar.addWidget(self.export_condition_button)
        self.generate_button = QPushButton("生成条件")
        self.generate_button.setObjectName("PrimaryAction")
        self.generate_button.clicked.connect(self._generate_conditions)
        conditions_toolbar.addWidget(self.generate_button)
        self.scan_button = QPushButton("开始扫描")
        secondary_button(self.scan_button)
        self.scan_button.clicked.connect(self._scan_conditions)
        conditions_toolbar.addWidget(self.scan_button)
        conditions_layout.addLayout(conditions_toolbar)

        self.condition_list = QListWidget()
        self.condition_list.setSelectionMode(QListWidget.SingleSelection)
        self.condition_list.setMinimumHeight(62)
        self.condition_list.setMaximumHeight(116)
        self.condition_list.currentRowChanged.connect(self._update_condition_actions)
        conditions_layout.addWidget(self.condition_list)
        root.addWidget(conditions_group)

        controls = QFrame()
        controls.setObjectName("Card")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        controls_layout.addWidget(QLabel("策略名称"))
        self.strategy_name = QLineEdit("实验策略")
        self.strategy_name.setMinimumWidth(180)
        controls_layout.addWidget(self.strategy_name)
        controls_layout.addStretch()
        self.start_button = QPushButton("开始回测")
        self.start_button.setObjectName("PrimaryAction")
        self.start_button.clicked.connect(self._run_backtest)
        controls_layout.addWidget(self.start_button)
        self.stop_button = QPushButton("停止")
        secondary_button(self.stop_button)
        self.stop_button.clicked.connect(self._stop_backtest)
        controls_layout.addWidget(self.stop_button)
        self.save_button = QPushButton("保存策略")
        secondary_button(self.save_button)
        self.save_button.clicked.connect(self._save_strategy)
        controls_layout.addWidget(self.save_button)
        root.addWidget(controls)

        self.notice = QLabel("尚未运行回测")
        self.notice.setObjectName("Muted")
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)

        result_group = QGroupBox("回测结果")
        result_layout = QVBoxLayout(result_group)
        self.results = QTableWidget(0, 8)
        self.results.setHorizontalHeaderLabels(
            ("条件名称", "触发次数", "有效样本", "命中次数", "命中率", "最大连中", "最大连错", "平均间隔")
        )
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.results, 260)
        self.results.setMinimumHeight(210)
        self.results.setMaximumHeight(16777215)
        result_layout.addWidget(self.results)
        self.scan_results = QTableWidget(0, 6)
        self.scan_results.setHorizontalHeaderLabels(
            ("策略编号", "条件", "触发次数", "历史命中率", "验证命中率", "状态")
        )
        self.scan_results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.scan_results.setSelectionBehavior(QTableWidget.SelectRows)
        self.scan_results.verticalHeader().setVisible(False)
        self.scan_results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.scan_results, 240)
        self.scan_results.setVisible(False)
        result_layout.addWidget(self.scan_results)
        root.addWidget(result_group, 1)

    def refresh(self) -> None:
        records = self._records()
        label = self.source.currentText()
        self.source_status.setText(f"{label} · 可用样本 {len(records)}")
        self._update_condition_actions()

    def _records(self) -> list[dict[str, Any]]:
        # The current database exposes complete prediction rows under VIP.
        # Smart-selection output is derived from those same rows, so it uses
        # the existing read-only record query rather than a new data source.
        return list(self.database.valid_backtest_records("VIP"))

    def _add_condition(self) -> None:
        self._generated_conditions = []
        label, condition = CONDITION_PRESETS[self.condition_preset.currentIndex()]
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, dict(condition))
        self.condition_list.addItem(item)
        self.condition_list.setCurrentItem(item)
        self._update_condition_actions()

    def _delete_condition(self) -> None:
        self._generated_conditions = []
        row = self.condition_list.currentRow()
        if row >= 0:
            self.condition_list.takeItem(row)
        self._update_condition_actions()

    def _update_condition_actions(self, *_args) -> None:
        count = self.condition_list.count()
        self.condition_count.setText(str(count))
        self.delete_condition_button.setEnabled(self.condition_list.currentRow() >= 0)

    def _condition_parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for index in range(self.condition_list.count()):
            item = self.condition_list.item(index)
            value = item.data(Qt.UserRole)
            if isinstance(value, dict):
                params.update(value)
        return params

    def _condition_name(self) -> str:
        names = [self.condition_list.item(index).text() for index in range(self.condition_list.count())]
        return "、".join(names) if names else "无条件"

    def _import_conditions(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "导入条件", "", "JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(open(path, "r", encoding="utf-8").read())
            conditions = payload.get("conditions", payload) if isinstance(payload, dict) else payload
            if not isinstance(conditions, list):
                raise ValueError("条件文件必须是列表")
            self.condition_list.clear()
            self._generated_conditions = []
            for item in conditions:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("name") or "导入条件")
                condition = dict(item.get("params") or item)
                condition.pop("name", None)
                list_item = QListWidgetItem(label)
                list_item.setData(Qt.UserRole, condition)
                self.condition_list.addItem(list_item)
            self._update_condition_actions()
            self.notice.setText(f"已导入 {self.condition_list.count()} 条条件")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.notice.setText(f"条件导入失败：{exc}")

    def _generate_conditions(self) -> None:
        self._generated_conditions = StrategyConditionGenerator().generate(500)
        self.condition_list.clear()
        for index, condition in enumerate(self._generated_conditions, start=1):
            item = QListWidgetItem(f"条件 {index:03d} · {condition.get('condition_family', '组合条件')}")
            item.setData(Qt.UserRole, condition)
            self.condition_list.addItem(item)
        self._update_condition_actions()
        self.notice.setText(f"已生成 {len(self._generated_conditions)} 个候选条件")

    def _scan_conditions(self) -> None:
        conditions = list(self._generated_conditions)
        if not conditions:
            conditions = [
                self.condition_list.item(index).data(Qt.UserRole)
                for index in range(self.condition_list.count())
                if isinstance(self.condition_list.item(index).data(Qt.UserRole), dict)
            ]
        if not conditions:
            self.notice.setText("请先生成条件或新增至少一条条件")
            self.scan_results.setVisible(False)
            return
        self.scan_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.notice.setText(f"正在扫描 {len(conditions)} 个候选条件…")
        try:
            self._scan_results = StrategyScanner().scan(
                self._records(),
                conditions,
                source_type="VIP",
                train_ratio=0.7,
                min_sample_size=30,
                walk_forward=True,
            )
            self._show_scan_results(self._scan_results)
            self.notice.setText(f"扫描完成：{len(self._scan_results)} 个候选，按训练侧综合评分排序")
        except Exception as exc:
            self._scan_results = []
            self.scan_results.setRowCount(0)
            self.scan_results.setVisible(False)
            self.notice.setText(f"条件扫描失败：{exc}")
        finally:
            self.scan_button.setEnabled(True)
            self.generate_button.setEnabled(True)

    def _show_scan_results(self, results: list[dict[str, Any]]) -> None:
        self.scan_results.setRowCount(len(results))
        self.scan_results.setVisible(True)
        for row_index, result in enumerate(results):
            condition = result.get("conditions", {})
            family = condition.get("condition_family", "组合条件")
            values = (
                result.get("strategy_id", f"EXP-{row_index + 1:04d}"),
                family,
                result.get("trigger_count", 0),
                self._rate(result.get("historical_hit_rate")),
                self._rate(result.get("validation_hit_rate")),
                result.get("status", "—"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(json.dumps(condition, ensure_ascii=False, sort_keys=True))
                self.scan_results.setItem(row_index, column, item)

    def _export_conditions(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "导出条件", "strategy_conditions.json", "JSON (*.json)")
        if not path:
            return
        payload = {
            "conditions": [
                {"name": self.condition_list.item(index).text(), "params": self.condition_list.item(index).data(Qt.UserRole)}
                for index in range(self.condition_list.count())
            ]
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            self.notice.setText(f"已导出 {self.condition_list.count()} 条条件")
        except OSError as exc:
            self.notice.setText(f"条件导出失败：{exc}")

    def _run_backtest(self) -> None:
        self._stopped = False
        self.start_button.setEnabled(False)
        self.notice.setText("回测中…")
        try:
            conditions = self._condition_parameters()
            records = self._records()
            result = run_condition_backtest(
                records,
                conditions,
                source_type="VIP",
                min_sample_size=1,
            )
            if self._stopped:
                self.notice.setText("回测已停止")
                return
            self._last_conditions = dict(conditions)
            self._last_records = records
            self._last_result = result
            self._show_result(result)
            self.notice.setText(
                f"回测完成：{result['valid_samples']} 个有效样本，命中率 {self._rate(result.get('hit_rate'))}"
            )
        except Exception as exc:
            self._last_result = None
            self.results.setRowCount(0)
            self.notice.setText(f"回测失败：{exc}")
        finally:
            self.start_button.setEnabled(True)

    def _stop_backtest(self) -> None:
        self._stopped = True
        self.notice.setText("已请求停止回测")

    def _save_strategy(self) -> None:
        name = self.strategy_name.text().strip()
        if not name:
            self.notice.setText("策略名称不能为空")
            return
        conditions = self._last_conditions or self._condition_parameters()
        source_label = self.source.currentText()
        parameters = {
            "engine": "auto_backtest",
            "experiment": "strategy_lab_v1",
            "conditions": conditions,
            "condition_items": [
                {"name": self.condition_list.item(index).text(), "params": self.condition_list.item(index).data(Qt.UserRole)}
                for index in range(self.condition_list.count())
            ],
            "data_source": source_label,
            "source_type": "VIP",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "backtest_result": self._last_result,
            "enabled": True,
        }
        try:
            method = "lowest_two" if conditions.get("min_groups") == 2 else "lowest_one"
            strategy_id = self.database.save_strategy(name, "VIP", method, parameters)
            strategy = self.database.get_strategy(strategy_id)
            if strategy and self._last_result is not None:
                self.database.save_backtest_result(strategy, self._last_result)
            self.notice.setText(f"策略已保存：{name}")
            self.data_changed.emit()
        except Exception as exc:
            self.notice.setText(f"策略保存失败：{exc}")

    def _show_result(self, result: dict[str, Any]) -> None:
        values = (
            self._condition_name(),
            result.get("matched_periods", 0),
            result.get("valid_samples", 0),
            result.get("hits", 0),
            self._rate(result.get("hit_rate")),
            result.get("max_consecutive_hits", 0),
            result.get("max_consecutive_misses", 0),
            result.get("average_condition_interval", "—"),
        )
        self.results.setRowCount(1)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            self.results.setItem(0, column, item)

    @staticmethod
    def _rate(value: Any) -> str:
        return "—" if value is None else f"{float(value):.2f}%"


__all__ = ["StrategyExperimentPage"]
