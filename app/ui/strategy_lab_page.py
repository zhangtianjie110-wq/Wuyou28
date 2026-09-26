from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..database import Database
from ..strategy_lab import (
    StrategyLabStore,
    choose_lab_plan,
    evaluate_forward_profile,
    run_strategy_lab_scan,
)
from ..auto_backtest import convert_prediction
from ..constants import COMBINATIONS
from .widgets import secondary_button


class StrategyLabPage(QWidget):
    data_changed = Signal()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.store = StrategyLabStore(database.path.with_name("strategy_lab.db"))
        self.current_scan = None
        self.current_records = []
        self.current_candidate = None
        self.forward_cache = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(10)
        title = QLabel("策略实验室")
        title.setObjectName("PageTitle")
        hint = QLabel("只做历史研究与前向验证，不生成投注指令，不提供推荐结论。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        overview = QGroupBox("实验概览")
        overview_layout = QGridLayout(overview)
        self.sample_label = QLabel("—")
        self.plan_label = QLabel("—")
        self.scan_label = QLabel("—")
        self.profile_label = QLabel("—")
        overview_layout.addWidget(QLabel("当前有效样本"), 0, 0)
        overview_layout.addWidget(self.sample_label, 0, 1)
        overview_layout.addWidget(QLabel("当前验证方案"), 0, 2)
        overview_layout.addWidget(self.plan_label, 0, 3)
        overview_layout.addWidget(QLabel("本轮扫描"), 1, 0)
        overview_layout.addWidget(self.scan_label, 1, 1)
        overview_layout.addWidget(QLabel("冻结策略档案"), 1, 2)
        overview_layout.addWidget(self.profile_label, 1, 3)
        root.addWidget(overview)

        controls = QGroupBox("条件扫描")
        controls_layout = QHBoxLayout(controls)
        self.source = QComboBox()
        self.source.addItems(["VIP"])
        self.max_candidates = QSpinBox()
        self.max_candidates.setRange(1, 1000)
        self.max_candidates.setValue(128)
        self.minimum_trigger = QSpinBox()
        self.minimum_trigger.setRange(1, 1000)
        self.minimum_trigger.setValue(5)
        scan_button = QPushButton("开始扫描")
        secondary_button(scan_button)
        scan_button.clicked.connect(self.scan)
        forward_button = QPushButton("更新前向验证")
        secondary_button(forward_button)
        forward_button.clicked.connect(self.refresh_forward)
        controls_layout.addWidget(QLabel("数据源"))
        controls_layout.addWidget(self.source)
        controls_layout.addWidget(QLabel("最大候选数"))
        controls_layout.addWidget(self.max_candidates)
        controls_layout.addWidget(QLabel("最低训练触发"))
        controls_layout.addWidget(self.minimum_trigger)
        controls_layout.addWidget(scan_button)
        controls_layout.addWidget(forward_button)
        controls_layout.addStretch()
        root.addWidget(controls)

        self.notice = QLabel("")
        self.notice.setStyleSheet("color: #C26A00; font-weight: 700;")
        root.addWidget(self.notice)

        results_group = QGroupBox("研究结果")
        results_layout = QVBoxLayout(results_group)
        self.results = QTableWidget(0, 10)
        self.results.setHorizontalHeaderLabels([
            "状态", "条件", "有效数据", "触发次数", "触发比例", "训练命中率",
            "验证命中率", "差值", "Walk-Forward", "样本提示",
        ])
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.currentCellChanged.connect(self._select_result)
        results_layout.addWidget(self.results)
        root.addWidget(results_group, 3)

        profile_group = QGroupBox("策略档案")
        profile_layout = QVBoxLayout(profile_group)
        profile_actions = QHBoxLayout()
        self.profile_name = QLabel("冻结当前选中条件")
        freeze_button = QPushButton("冻结策略档案")
        secondary_button(freeze_button)
        freeze_button.clicked.connect(self.freeze_current)
        profile_actions.addWidget(self.profile_name)
        profile_actions.addWidget(freeze_button)
        profile_actions.addStretch()
        profile_layout.addLayout(profile_actions)
        self.profiles = QTableWidget(0, 8)
        self.profiles.setHorizontalHeaderLabels(["strategy_id", "来源", "版本", "冻结期号", "条件", "状态", "前向样本", "前向命中率"])
        self.profiles.setEditTriggers(QTableWidget.NoEditTriggers)
        self.profiles.setSelectionBehavior(QTableWidget.SelectRows)
        self.profiles.verticalHeader().setVisible(False)
        self.profiles.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.profiles.currentCellChanged.connect(self._select_profile)
        profile_layout.addWidget(self.profiles)
        root.addWidget(profile_group, 2)

        detail_group = QGroupBox("逐期详情")
        detail_layout = QVBoxLayout(detail_group)
        self.details = QTableWidget(0, 7)
        self.details.setHorizontalHeaderLabels(["期号", "四组数量", "实际结果", "实际组合", "命中状态", "阶段", "条件参数"])
        self.details.setEditTriggers(QTableWidget.NoEditTriggers)
        self.details.verticalHeader().setVisible(False)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        detail_layout.addWidget(self.details)
        root.addWidget(detail_group, 2)
        self.source.currentTextChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        records = self.database.valid_backtest_records(self.source.currentText())
        plan = choose_lab_plan(len(records))
        self.sample_label.setText(f"{self.source.currentText()}：{len(records)}")
        self.plan_label.setText(plan["label"])
        if plan["warning"]:
            self.notice.setText(plan["warning"])
        profiles = self.store.list_profiles(self.source.currentText())
        self.profile_label.setText(str(len(profiles)))
        self._show_profiles(profiles)

    def scan(self):
        source = self.source.currentText()
        self.current_records = self.database.valid_backtest_records(source)
        self.current_scan = run_strategy_lab_scan(
            self.current_records,
            source_type=source,
            max_candidates=self.max_candidates.value(),
            minimum_trigger=self.minimum_trigger.value(),
        )
        self.store.save_run(self.current_scan)
        self.notice.setText(
            f"本轮生成 {self.current_scan['generated_candidates']} 组，去重后测试 {self.current_scan['tested_candidates']} 组，"
            f"训练通过 {self.current_scan['training_passed']} 组，进入验证 {self.current_scan['validation_tested']} 组。"
        )
        self._show_results(self.current_scan["results"])
        self._show_profiles(self.store.list_profiles(source))

    def refresh_forward(self):
        source = self.source.currentText()
        self._refresh_forward_source(source)
        self._show_profiles(self.store.list_profiles(source))
        self.notice.setText(f"已按冻结期号更新 {len(self.store.list_profiles(source))} 个策略档案的 forward_test。")

    def refresh_forward_all(self):
        """Refresh VIP after a completed collection cycle."""

        for source in ("VIP",):
            self._refresh_forward_source(source)
        self._show_profiles(self.store.list_profiles(self.source.currentText()))

    def _refresh_forward_source(self, source: str):
        records = self.database.valid_backtest_records(source)
        profiles = self.store.list_profiles(source)
        for profile in profiles:
            result = evaluate_forward_profile(profile, records)
            self.store.save_forward_result(profile, result)
            self.forward_cache[profile["strategy_id"]] = result

    def freeze_current(self):
        if not self.current_candidate or not self.current_candidate.get("validated"):
            self.notice.setText("只有训练阶段通过最低样本要求的条件才能冻结。")
            return
        records = self.current_records or self.database.valid_backtest_records(self.source.currentText())
        if not records:
            return
        frozen = records[-1]["issue_no"]
        profile = self.store.create_profile(
            f"实验条件-{self.source.currentText()}", self.source.currentText(),
            self.current_candidate["conditions"], frozen,
            self.current_candidate["train"], self.current_candidate["validation"],
        )
        self.profile_name.setText(f"已冻结 {profile['strategy_id']} @ {profile['frozen_at_issue']}")
        self._show_profiles(self.store.list_profiles(self.source.currentText()))

    def _show_results(self, results):
        self.results.setRowCount(len(results))
        for row, candidate in enumerate(results):
            train = candidate["train"]
            validation = candidate.get("validation") or {}
            walk = candidate.get("walk_forward")
            values = [
                candidate["status"], json.dumps(candidate["conditions"], ensure_ascii=False, sort_keys=True),
                candidate["total_valid_data"], candidate["trigger_count"], f"{candidate['trigger_ratio']:.2f}%",
                self._rate(train.get("hit_rate")), self._rate(validation.get("hit_rate")),
                self._rate_diff((validation.get("hit_rate") - train.get("hit_rate")) if validation.get("hit_rate") is not None and train.get("hit_rate") is not None else None),
                "未启用" if not walk else f"{len(walk['windows'])}窗",
                candidate["status_reason"],
            ]
            for column, value in enumerate(values):
                self.results.setItem(row, column, QTableWidgetItem(str(value)))
        if results:
            self.results.setCurrentCell(0, 0)

    def _show_profiles(self, profiles):
        self.profiles.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            forward = self.forward_cache.get(profile["strategy_id"], {})
            values = [
                profile["strategy_id"], profile["source_type"], profile["version"], profile["frozen_at_issue"],
                json.dumps(profile["conditions"], ensure_ascii=False, sort_keys=True),
                forward.get("status", "等待前向数据"), forward.get("valid_samples", "—"), self._rate(forward.get("hit_rate")),
            ]
            for column, value in enumerate(values):
                self.profiles.setItem(row, column, QTableWidgetItem(str(value)))

    def _select_result(self, row, _column, _previous_row, _previous_column):
        if self.current_scan and 0 <= row < len(self.current_scan["results"]):
            self.current_candidate = self.current_scan["results"][row]
            self._show_details(self.current_candidate, self.current_records)

    def _select_profile(self, row, _column, _previous_row, _previous_column):
        if row < 0:
            return
        profiles = self.store.list_profiles(self.source.currentText())
        if row >= len(profiles):
            return
        profile = profiles[row]
        result = self.forward_cache.get(profile["strategy_id"])
        if result:
            self._show_details(result, self.database.valid_backtest_records(profile["source_type"]))

    def _show_details(self, result, records):
        details = result.get("details", [])
        by_issue = {str(item["issue_no"]): item for item in records}
        condition = result.get("conditions", {})
        if "train" in result:
            details = [dict(item, dataset="训练集") for item in result["train"].get("details", [])]
            details += [dict(item, dataset="验证集") for item in (result.get("validation") or {}).get("details", [])]
        self.details.setRowCount(len(details))
        for row, detail in enumerate(details):
            source = by_issue.get(str(detail.get("issue_no")), {})
            converted = convert_prediction(source) if source else {}
            counts = converted.get("counts", {})
            values = [
                detail.get("issue_no", ""), " / ".join(str(counts.get(combo, "")) for combo in COMBINATIONS),
                source.get("actual_result", ""), detail.get("actual_combo", converted.get("actual_combo", "")),
                "待开奖" if detail.get("hit") is None else ("命中" if detail.get("hit") else "未命中"),
                detail.get("dataset", result.get("stage", "")), json.dumps(condition, ensure_ascii=False, sort_keys=True),
            ]
            for column, value in enumerate(values):
                self.details.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _rate(value):
        return "—" if value is None else f"{value:.2f}%"

    @staticmethod
    def _rate_diff(value):
        return "—" if value is None else f"{value:+.2f}%"
