from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..database import Database
from ..strategy_lab import (
    StrategyLabStore,
    choose_lab_plan,
    evaluate_forward_profile,
    run_vip100_strategy_search,
)
from ..auto_backtest import convert_prediction
from ..constants import COMBINATIONS
from .widgets import PageHeader, StatCard, polish_table, secondary_button


class StrategyLabPage(QWidget):
    data_changed = Signal()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.store = StrategyLabStore(database.path.with_name("strategy_lab.db"))
        self.current_scan = None
        self.current_records = []
        self.current_candidate = None
        self.current_display_results = []
        self.forward_cache = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(12)
        self.page_header = PageHeader("智能选法", "自动分析历史数据，筛选阶段性表现策略")
        root.addWidget(self.page_header)

        status_row = QHBoxLayout()
        self.strategy_count_card = StatCard("当前策略数量", "—", compact=True)
        self.running_strategy_card = StatCard("正在运行策略", "—", compact=True)
        self.best_strategy_card = StatCard("最优策略", "—", compact=True)
        self.validation_card = StatCard("最近验证结果", "—", compact=True)
        for card in (
            self.strategy_count_card,
            self.running_strategy_card,
            self.best_strategy_card,
            self.validation_card,
        ):
            status_row.addWidget(card, 1)
        root.addLayout(status_row)

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
        overview.setVisible(False)

        analysis_card = QFrame()
        analysis_card.setObjectName("StrategyAnalysisCard")
        analysis_layout = QHBoxLayout(analysis_card)
        analysis_layout.setContentsMargins(14, 10, 14, 10)
        analysis_layout.setSpacing(10)
        analysis_copy = QVBoxLayout()
        analysis_title = QLabel("开始分析")
        analysis_title.setObjectName("StrategyCardTitle")
        analysis_copy.addWidget(analysis_title)
        analysis_hint = QLabel("使用 VIP100 历史数据筛选阶段性表现策略")
        analysis_hint.setObjectName("Muted")
        analysis_copy.addWidget(analysis_hint)
        analysis_layout.addLayout(analysis_copy)
        analysis_layout.addStretch()
        analysis_layout.addWidget(QLabel("数据源"))
        self.source = QComboBox()
        self.source.addItems(["VIP"])
        self.max_candidates = QSpinBox()
        self.max_candidates.setRange(1, 1000)
        self.max_candidates.setValue(128)
        self.minimum_trigger = QSpinBox()
        self.minimum_trigger.setRange(1, 1000)
        self.minimum_trigger.setValue(5)
        analysis_layout.addWidget(self.source)
        self.scan_button = QPushButton("开始分析")
        self.scan_button.setObjectName("PrimaryAction")
        self.scan_button.clicked.connect(self.scan)
        analysis_layout.addWidget(self.scan_button)
        self.detail_button = QPushButton("查看详情")
        secondary_button(self.detail_button)
        self.detail_button.clicked.connect(self.show_selected_details)
        analysis_layout.addWidget(self.detail_button)
        self.forward_button = QPushButton("更新前向")
        secondary_button(self.forward_button)
        self.forward_button.clicked.connect(self.refresh_forward)
        analysis_layout.addWidget(self.forward_button)
        self.max_candidates.setVisible(False)
        self.minimum_trigger.setVisible(False)
        root.addWidget(analysis_card)

        self.notice = QLabel("")
        self.notice.setStyleSheet("color: #C26A00; font-weight: 700;")
        root.addWidget(self.notice)

        self.featured_card = QFrame()
        self.featured_card.setObjectName("StrategyFeaturedCard")
        featured_layout = QVBoxLayout(self.featured_card)
        featured_layout.setContentsMargins(18, 14, 18, 14)
        featured_header = QHBoxLayout()
        featured_title = QLabel("当前TOP策略")
        featured_title.setObjectName("StrategyFeaturedTitle")
        featured_header.addWidget(featured_title)
        featured_header.addStretch()
        self.featured_status = QLabel("暂无结果")
        self.featured_status.setObjectName("StrategyStatusBadge")
        featured_header.addWidget(self.featured_status)
        featured_layout.addLayout(featured_header)
        self.featured_values: dict[str, QLabel] = {}
        featured_grid = QGridLayout()
        featured_grid.setHorizontalSpacing(18)
        featured_grid.setVerticalSpacing(8)
        for index, (key, caption) in enumerate((
            ("name", "策略名称"),
            ("buy", "买入组合"),
            ("validation", "验证命中率"),
            ("score", "综合评分"),
            ("recent30", "最近30期"),
            ("recent50", "最近50期"),
            ("recent100", "最近100期"),
            ("misses", "最大连续错误"),
        )):
            metric = self._strategy_metric(caption)
            self.featured_values[key] = metric.value_label
            featured_grid.addWidget(metric, index // 4, index % 4)
        featured_layout.addLayout(featured_grid)
        root.addWidget(self.featured_card)

        results_group = QFrame()
        results_group.setObjectName("StrategySection")
        self.results = QTableWidget(0, 12)
        self.results.setHorizontalHeaderLabels([
            "状态", "条件", "有效数据", "触发次数", "触发比例", "训练命中率",
            "验证命中率", "差值", "综合评分", "覆盖风险", "Walk-Forward", "样本提示",
        ])
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.currentCellChanged.connect(self._select_result)
        self.results.setVisible(False)
        results_scroll = QScrollArea()
        results_scroll.setObjectName("StrategyCardScroll")
        results_scroll.setWidgetResizable(True)
        results_scroll.setFrameShape(QFrame.NoFrame)
        self.result_cards_host = QWidget()
        self.result_cards_layout = QVBoxLayout(self.result_cards_host)
        self.result_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.result_cards_layout.setSpacing(8)
        self.result_cards_layout.addStretch()
        results_scroll.setWidget(self.result_cards_host)
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(results_scroll)
        root.addWidget(results_group, 3)

        recent_group = QGroupBox("最近表现")
        recent_layout = QVBoxLayout(recent_group)
        self.recent_results = QTableWidget(0, 5)
        self.recent_results.setHorizontalHeaderLabels(["窗口", "触发次数", "命中次数", "命中率", "最大连续错误"])
        self.recent_results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_results.verticalHeader().setVisible(False)
        self.recent_results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.recent_results, 170)
        recent_layout.addWidget(self.recent_results)
        recent_group.setVisible(False)

        observe_card = QFrame()
        observe_card.setObjectName("StrategyObserveCard")
        profile_layout = QVBoxLayout(observe_card)
        profile_layout.setContentsMargins(16, 12, 16, 12)
        profile_actions = QHBoxLayout()
        observe_title = QLabel("观察策略")
        observe_title.setObjectName("StrategySectionTitle")
        profile_actions.addWidget(observe_title)
        self.observe_count = QLabel("已关注 0 个")
        self.observe_count.setObjectName("Muted")
        profile_actions.addWidget(self.observe_count)
        profile_actions.addStretch()
        self.profile_name = QLabel("冻结当前选中条件")
        self.profile_name.setObjectName("Muted")
        profile_actions.addWidget(self.profile_name)
        freeze_button = QPushButton("冻结策略档案")
        secondary_button(freeze_button)
        freeze_button.clicked.connect(self.freeze_current)
        profile_actions.addWidget(freeze_button)
        profile_layout.addLayout(profile_actions)
        self.profiles = QTableWidget(0, 8)
        self.profiles.setHorizontalHeaderLabels(["strategy_id", "来源", "版本", "冻结期号", "条件", "状态", "前向样本", "前向命中率"])
        self.profiles.setEditTriggers(QTableWidget.NoEditTriggers)
        self.profiles.setSelectionBehavior(QTableWidget.SelectRows)
        self.profiles.verticalHeader().setVisible(False)
        self.profiles.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.profiles.currentCellChanged.connect(self._select_profile)
        self.profiles.setVisible(False)
        polish_table(self.profiles, 220)
        self.profile_cards_layout = QVBoxLayout()
        self.profile_cards_layout.setSpacing(6)
        profile_layout.addLayout(self.profile_cards_layout)
        root.addWidget(observe_card)

        detail_group = QFrame()
        detail_group.setObjectName("StrategyDetailCard")
        detail_layout = QVBoxLayout(detail_group)
        detail_title = QLabel("策略详情")
        detail_title.setObjectName("StrategySectionTitle")
        detail_layout.addWidget(detail_title)
        self.detail_summary = QLabel("选择 TOP 策略后查看条件、买入组合和逐期命中状态")
        self.detail_summary.setObjectName("Muted")
        self.detail_summary.setWordWrap(True)
        detail_layout.addWidget(self.detail_summary)
        self.details = QTableWidget(0, 8)
        self.details.setHorizontalHeaderLabels(["期号", "买入组合", "开奖结果", "实际组合", "是否命中", "连续状态", "阶段", "条件参数"])
        self.details.setEditTriggers(QTableWidget.NoEditTriggers)
        self.details.verticalHeader().setVisible(False)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.details.setVisible(False)
        polish_table(self.details, 300)
        root.addWidget(detail_group)
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
        self.strategy_count_card.set_value(str(len(profiles)))
        self.running_strategy_card.set_value("待分析")
        self.best_strategy_card.set_value("—")
        self.validation_card.set_value("—")
        self._show_profiles(profiles)

    def scan(self):
        source = self.source.currentText()
        self.current_records = self.database.valid_backtest_records(source)
        self.current_scan = run_vip100_strategy_search(
            self.current_records,
            max_candidates=self.max_candidates.value(),
            minimum_trigger=self.minimum_trigger.value(),
        )
        self.store.save_run(self.current_scan)
        self.notice.setText(
            f"本轮生成 {self.current_scan['generated_candidates']} 组，去重后测试 {self.current_scan['tested_candidates']} 组，"
            f"训练通过 {self.current_scan['training_passed']} 组，进入验证 {self.current_scan['validation_tested']} 组；"
            f"当前展示 TOP {self.current_scan['top_n']}。"
        )
        self._show_results(self.current_scan["top_strategies"])
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
        self.current_display_results = list(results)
        self.strategy_count_card.set_value(str(len(results)))
        self.running_strategy_card.set_value("已完成")
        best = self.current_display_results[0] if self.current_display_results else None
        self.best_strategy_card.set_value(self._candidate_name(best) if best else "—")
        validation = (best or {}).get("validation") or {}
        self.validation_card.set_value(self._rate(validation.get("hit_rate")))
        self.results.setRowCount(len(results))
        for row, candidate in enumerate(results):
            train = candidate["train"]
            validation = candidate.get("validation") or {}
            walk = candidate.get("walk_forward")
            values = [
                f"#{candidate.get('rank', row + 1)} {candidate.get('quality_status', candidate['status'])}", json.dumps(candidate["conditions"], ensure_ascii=False, sort_keys=True),
                candidate["total_valid_data"], candidate["trigger_count"], f"{candidate['trigger_ratio']:.2f}%",
                self._rate(train.get("hit_rate")), self._rate(validation.get("hit_rate")),
                self._rate_diff((validation.get("hit_rate") - train.get("hit_rate")) if validation.get("hit_rate") is not None and train.get("hit_rate") is not None else None),
                f"{candidate.get('composite_score', 0.0):.2f}",
                candidate.get("coverage_risk", "LOW"),
                "未启用" if not walk else f"{len(walk['windows'])}窗",
                candidate["status_reason"],
            ]
            for column, value in enumerate(values):
                self.results.setItem(row, column, QTableWidgetItem(str(value)))
        self._render_result_cards(self.current_display_results)
        self._render_featured(self.current_display_results[0] if self.current_display_results else None)
        if results:
            self.results.setCurrentCell(0, 0)
            self._select_candidate(0)

    @staticmethod
    def _strategy_metric(title: str) -> QFrame:
        metric = QFrame()
        metric.setObjectName("StrategyMetric")
        layout = QVBoxLayout(metric)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("StrategyMetricTitle")
        value_label = QLabel("—")
        value_label.setObjectName("StrategyMetricValue")
        value_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        metric.value_label = value_label  # type: ignore[attr-defined]
        return metric

    def _render_featured(self, candidate):
        if not candidate:
            self.featured_status.setText("暂无结果")
            for value in self.featured_values.values():
                value.setText("—")
            return
        status = str(candidate.get("quality_status", candidate.get("status", "OBSERVE")))
        self.featured_status.setText(status)
        self.featured_values["name"].setText(self._candidate_name(candidate))
        self.featured_values["buy"].setText(self._candidate_buy(candidate))
        validation = candidate.get("validation") or {}
        self.featured_values["validation"].setText(self._rate(validation.get("hit_rate")))
        self.featured_values["score"].setText(f"{candidate.get('composite_score', 0.0):.2f}")
        rolling = candidate.get("rolling") or {}
        for window in (30, 50, 100):
            metrics = rolling.get(str(window), {})
            self.featured_values[f"recent{window}"].setText(self._rate(metrics.get("hit_rate")))
        recent = rolling.get("50", {})
        self.featured_values["misses"].setText(str(recent.get("max_consecutive_errors", 0)))

    def _render_result_cards(self, results):
        while self.result_cards_layout.count():
            item = self.result_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row, candidate in enumerate(results):
            card = QFrame()
            card.setObjectName("StrategyResultCard")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(12, 9, 12, 9)
            layout.setSpacing(12)
            rank = QLabel(f"TOP {candidate.get('rank', row + 1)}")
            rank.setObjectName("StrategyRank")
            layout.addWidget(rank)
            identity = QVBoxLayout()
            name = QLabel(self._candidate_name(candidate))
            name.setObjectName("StrategyCardName")
            identity.addWidget(name)
            buy = QLabel(self._candidate_buy(candidate))
            buy.setObjectName("Muted")
            identity.addWidget(buy)
            layout.addLayout(identity, 1)
            metrics = QVBoxLayout()
            validation = (candidate.get("validation") or {}).get("hit_rate")
            recent = (candidate.get("rolling") or {}).get("50", {}).get("hit_rate")
            metrics.addWidget(QLabel(f"验证 {self._rate(validation)}"))
            metrics.addWidget(QLabel(f"最近50期 {self._rate(recent)}"))
            layout.addLayout(metrics)
            state = QLabel(str(candidate.get("quality_status", candidate.get("status", "OBSERVE"))))
            state.setObjectName("StrategyStatusBadge")
            layout.addWidget(state)
            score = QLabel(f"评分 {candidate.get('composite_score', 0.0):.1f}")
            score.setObjectName("StrategyScore")
            layout.addWidget(score)
            button = QPushButton("查看详情")
            secondary_button(button)
            button.clicked.connect(lambda _checked=False, index=row: self._select_candidate(index))
            layout.addWidget(button)
            self.result_cards_layout.addWidget(card)
        self.result_cards_layout.addStretch()

    @staticmethod
    def _candidate_name(candidate) -> str:
        conditions = candidate.get("conditions") or {}
        return str(candidate.get("strategy_name") or conditions.get("name") or f"条件策略 {candidate.get('rank', '')}").strip()

    @staticmethod
    def _candidate_buy(candidate) -> str:
        conditions = candidate.get("conditions") or {}
        selected = conditions.get("selected_groups") or candidate.get("selected_groups") or ()
        return " + ".join(str(value) for value in selected) or "按条件选择"

    def _select_candidate(self, row: int) -> None:
        if not self.current_scan or not (0 <= row < len(self.current_display_results)):
            return
        self.current_candidate = self.current_display_results[row]
        self._render_featured(self.current_candidate)
        self._show_recent(self.current_candidate)
        self._show_details(self.current_candidate, self.current_records)

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
        while self.profile_cards_layout.count():
            item = self.profile_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.observe_count.setText(f"已关注 {len(profiles)} 个")
        if not profiles:
            empty = QLabel("暂无观察策略")
            empty.setObjectName("Muted")
            self.profile_cards_layout.addWidget(empty)
        for profile in profiles:
            card = QFrame()
            card.setObjectName("StrategyObserveItem")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(10, 7, 10, 7)
            name = QLabel(str(profile.get("strategy_id", "观察策略")))
            name.setObjectName("StrategyCardName")
            layout.addWidget(name, 1)
            forward = self.forward_cache.get(profile["strategy_id"], {})
            layout.addWidget(QLabel(f"最近表现 {self._rate(forward.get('hit_rate'))}"))
            state = QLabel(str(forward.get("status", "等待前向数据")))
            state.setObjectName("Muted")
            layout.addWidget(state)
            self.profile_cards_layout.addWidget(card)
        self.profile_cards_layout.addStretch()

    def _select_result(self, row, _column, _previous_row, _previous_column):
        if self.current_scan and 0 <= row < len(self.current_display_results):
            self._select_candidate(row)

    def show_selected_details(self):
        row = self.results.currentRow()
        if self.current_scan and 0 <= row < len(self.current_display_results):
            self._select_candidate(row)

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
        self.details.setColumnCount(8)
        self.details.setHorizontalHeaderLabels(["期号", "买入组合", "开奖结果", "实际组合", "是否命中", "连续状态", "阶段", "条件参数"])
        self.details.setRowCount(len(details))
        previous_hit = None
        streak = 0
        for row, detail in enumerate(details):
            source = by_issue.get(str(detail.get("issue_no")), {})
            converted = convert_prediction(source) if source else {}
            counts = converted.get("counts", {})
            hit = detail.get("hit")
            if hit is None:
                streak_text = "等待开奖"
                previous_hit = None
                streak = 0
            else:
                streak = streak + 1 if hit == previous_hit else 1
                previous_hit = hit
                streak_text = f"{'命中' if hit else '错误'}连续{streak}期"
            values = [
                detail.get("issue_no", ""), "、".join(detail.get("selected") or ()),
                source.get("actual_result", ""), detail.get("actual_combo", converted.get("actual_combo", "")),
                "待开奖" if hit is None else ("命中" if hit else "未命中"), streak_text,
                detail.get("dataset", result.get("stage", "")), json.dumps(condition, ensure_ascii=False, sort_keys=True),
            ]
            for column, value in enumerate(values):
                self.details.setItem(row, column, QTableWidgetItem(str(value)))
        selected = sorted({str(value) for detail in details for value in (detail.get("selected") or ())})
        decided = [detail for detail in details if detail.get("hit") is not None]
        hits = sum(bool(detail.get("hit")) for detail in decided)
        preview = "、".join(
            f"{detail.get('issue_no', '—')}:{'命中' if detail.get('hit') else '未中'}"
            for detail in details[:5]
        ) or "暂无记录"
        self.detail_summary.setText(
            f"策略条件：{json.dumps(condition, ensure_ascii=False, sort_keys=True)}\n"
            f"买入组合：{' + '.join(selected) or '按条件选择'} · 触发记录 {len(details)} 条 · 命中 {hits}/{len(decided)}\n"
            f"连续状态：{preview}"
        )

    def _show_recent(self, candidate):
        rolling = candidate.get("rolling") or {}
        windows = (30, 50, 100)
        self.recent_results.setRowCount(len(windows))
        for row, window in enumerate(windows):
            metrics = rolling.get(str(window), {})
            values = [
                f"最近{window}期",
                metrics.get("trigger_count", 0),
                metrics.get("hit_count", 0),
                self._rate(metrics.get("hit_rate")),
                metrics.get("max_consecutive_errors", 0),
            ]
            for column, value in enumerate(values):
                self.recent_results.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _rate(value):
        return "—" if value is None else f"{value:.2f}%"

    @staticmethod
    def _rate_diff(value):
        return "—" if value is None else f"{value:+.2f}%"
