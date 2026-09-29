from __future__ import annotations

from datetime import datetime
from functools import partial
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from ..integration.models import StrategyDetail, StrategySummary
from .display_text import display_status
from .widgets import StatCard, polish_table, secondary_button


STATUS_COLORS = {
    "RESEARCH_ONLY": "#667085",
    "CANDIDATE": "#C26A00",
    "FORWARD_TEST": "#1478E5",
    "VERIFIED": "#16834B",
    "REJECTED": "#B43B3B",
}

CONDITION_FIELDS = {
    "minimum_count": "最低出现次数",
    "maximum_count": "最高出现次数",
    "max_min_spread": "最高与最低次数差",
    "lowest_gap": "最低两项差值",
    "highest_gap": "最高两项差值",
    "big_count": "大数预测数量",
    "odd_count": "单数预测数量",
    "four_combo_concentration": "四组合集中度",
    "prediction_concentration": "预测集中度",
    "prediction_dispersion": "预测离散度",
    "recent_5_big_rate": "近5期大数比例",
    "recent_5_odd_rate": "近5期单数比例",
    "recent_10_big_rate": "近10期大数比例",
    "recent_10_odd_rate": "近10期单数比例",
    "lowest_combination": "最低组合",
    "highest_combination": "最高组合",
    "lowest_is_unique": "最低组合要求",
    "highest_is_unique": "最高组合要求",
}

LARGE_SAMPLE_CONDITION_FIELDS = {
    "pair_rank": "双组合排名关系",
    "lowest_boundary_tie": "第二低与第三低并列",
}

DYNAMIC_CONDITION_FIELDS = {
    "r1_count": "最低数量",
    "r4_count": "最高数量",
    "r1_r2_gap": "第一与第二差值",
    "r2_r3_gap": "第二与第三差值",
    "r3_r4_gap": "第三与第四差值",
    "spread": "最高最低极差",
    "has_tie": "存在并列",
    "lowest_tie_count": "最低并列数量",
    "highest_tie_count": "最高并列数量",
    "concentration": "四组集中程度",
}

PAIR_NAMES = (
    "大单+大双",
    "大单+小单",
    "大单+小双",
    "大双+小单",
    "大双+小双",
    "小单+小双",
)

PREDICTOR_TEXT = {
    "lowest_1": "最低一项组合",
    "lowest_2": "最低两项组合",
    "highest_1": "最高一项组合",
    "highest_2": "最高两项组合",
    "fixed_pair": "固定双组合",
}

HISTORY_SCOPES = (
    ("全部历史", "ALL"),
    ("训练集", "TRAIN"),
    ("验证集", "VALIDATION"),
    ("测试集", "TEST"),
    ("正式前向", "FORWARD"),
)


class SortableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.setData(Qt.UserRole + 1, text if sort_value is None else sort_value)

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            left = self.data(Qt.UserRole + 1)
            right = other.data(Qt.UserRole + 1)
            try:
                return left < right
            except TypeError:
                return str(left) < str(right)
        return super().__lt__(other)


class StrategyDetailDialog(QDialog):
    """Read-only strategy detail. Refreshes only through IntegrationGateway."""

    def __init__(
        self,
        detail: StrategyDetail,
        display_number: str = "001",
        gateway: IntegrationGateway | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.detail = detail
        self.strategy_id = detail.summary.strategy_id
        self.display_number = display_number
        self.gateway = gateway
        self.setWindowTitle(f"策略 {display_number} 详情")
        self.resize(850, 650)
        self.setMinimumSize(720, 520)
        self._build_ui()
        self._show_detail(detail)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(9)

        self.alert = QLabel()
        self.alert.setObjectName("DangerText")
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        info_group = QGroupBox("策略基本信息")
        info_layout = QGridLayout(info_group)
        info_specs = (
            ("display_number", "策略编号"),
            ("lifecycle", "生命周期状态"),
            ("version", "策略版本"),
            ("rule_hash", "规则哈希"),
            ("target_issue", "目标期号"),
            ("prediction", "当期预测"),
            ("prediction_status", "预测状态"),
            ("generated_at", "预测生成时间"),
            ("selected_pair", "研究双组合"),
        )
        self.info_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(info_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_labels[key] = value_label
            row = (index // 4) * 2
            column = index % 4
            info_layout.addWidget(caption_label, row, column)
            info_layout.addWidget(value_label, row + 1, column)
        root.addWidget(info_group)

        conditions_group = QGroupBox("完整条件")
        conditions_layout = QVBoxLayout(conditions_group)
        self.conditions_text = QTextEdit()
        self.conditions_text.setReadOnly(True)
        self.conditions_text.setMaximumHeight(108)
        conditions_layout.addWidget(self.conditions_text)
        root.addWidget(conditions_group)

        summary_row = QHBoxLayout()
        stats_group = QGroupBox("历史统计")
        stats_layout = QGridLayout(stats_group)
        stats_specs = (
            ("matched_issues", "符合条件总期数"),
            ("valid_samples", "有效样本数"),
            ("invalid_samples", "无效样本数"),
            ("hit_count", "命中数"),
            ("miss_count", "未命中数"),
            ("accuracy", "命中率"),
            ("recent_30_accuracy", "最近30期"),
            ("recent_50_accuracy", "最近50期"),
            ("recent_100_accuracy", "最近100期"),
            ("recent_200_accuracy", "最近200期"),
            ("max_consecutive_hits", "最大连续命中"),
            ("max_consecutive_misses", "最大连续未命中"),
            ("current_streak", "当前连续状态"),
            ("average_trigger_interval", "平均触发间隔"),
            ("train_triggers", "训练触发"),
            ("train_accuracy", "训练命中率"),
            ("validation_triggers", "验证触发"),
            ("validation_accuracy", "验证命中率"),
            ("test_triggers", "测试触发"),
            ("test_accuracy", "测试命中率"),
            ("walk_forward_windows", "滚动验证窗口"),
            ("walk_forward_triggers", "滚动验证触发"),
            ("walk_forward_accuracy", "滚动验证命中率"),
            ("walk_forward_worst", "最差窗口命中率"),
            ("walk_forward_max_misses", "滚动验证最大连续未中"),
            ("research_warnings", "研究警告"),
        )
        self.stat_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(stats_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.stat_labels[key] = value_label
            stats_layout.addWidget(caption_label, index // 2, (index % 2) * 2)
            stats_layout.addWidget(value_label, index // 2, (index % 2) * 2 + 1)
        summary_row.addWidget(stats_group, 3)

        latest_group = QGroupBox("最近触发")
        latest_layout = QGridLayout(latest_group)
        latest_specs = (
            ("issue", "最近触发期号"),
            ("distance", "距离当前"),
            ("prediction", "当时预测"),
            ("actual", "实际结果"),
            ("result", "结果"),
            ("sample_type", "记录类型"),
        )
        self.latest_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(latest_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            value_label.setWordWrap(True)
            self.latest_labels[key] = value_label
            latest_layout.addWidget(caption_label, index, 0)
            latest_layout.addWidget(value_label, index, 1)
        summary_row.addWidget(latest_group, 2)
        root.addLayout(summary_row)

        self.pair_distribution_group = QGroupBox("六种双组合选择比例")
        pair_distribution_layout = QGridLayout(self.pair_distribution_group)
        self.pair_distribution_labels: dict[str, QLabel] = {}
        for index, pair_name in enumerate(PAIR_NAMES):
            caption_label = QLabel(pair_name.replace("+", " + "))
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.pair_distribution_labels[pair_name] = value_label
            pair_distribution_layout.addWidget(caption_label, 0, index)
            pair_distribution_layout.addWidget(value_label, 1, index)
        self.pair_distribution_group.setVisible(False)
        root.addWidget(self.pair_distribution_group)

        history_group = QGroupBox("逐期记录")
        history_layout = QVBoxLayout(history_group)
        history_controls = QHBoxLayout()
        self.history_scope = QComboBox()
        for text, value in HISTORY_SCOPES:
            self.history_scope.addItem(text, value)
        self.history_count = QLabel()
        self.history_count.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新")
        secondary_button(self.refresh_button)
        history_controls.addWidget(self.history_scope)
        history_controls.addWidget(self.history_count)
        history_controls.addStretch()
        history_controls.addWidget(self.refresh_button)
        history_layout.addLayout(history_controls)

        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ("期号", "当期预测", "实际开奖", "结果", "样本类型", "数据来源", "生成时间")
        )
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.prediction_history_table = self.history_table
        history_layout.addWidget(self.history_table)
        root.addWidget(history_group, 1)

        self.history_scope.currentIndexChanged.connect(self._reload)
        self.refresh_button.clicked.connect(self._reload)

    def _show_detail(self, detail: StrategyDetail) -> None:
        self.detail = detail
        summary = detail.summary
        self.info_labels["display_number"].setText(self.display_number)
        self.info_labels["lifecycle"].setText(display_status(summary.status))
        self.info_labels["version"].setText(summary.strategy_version or "—")
        self.info_labels["rule_hash"].setText(summary.rule_hash or summary.strategy_hash)
        self.info_labels["target_issue"].setText(summary.target_issue or "—")
        self.info_labels["prediction"].setText(_current_prediction_text(summary))
        self.info_labels["prediction_status"].setText(display_status(summary.prediction_status))
        self.info_labels["generated_at"].setText(_format_time(summary.prediction_generated_at))
        dynamic_mode = summary.conditions.get("dynamic_mode") if isinstance(summary.conditions, dict) else None
        self.info_labels["selected_pair"].setText(
            display_status(dynamic_mode)
            if dynamic_mode
            else " + ".join(summary.current_prediction or ()) or "—"
        )
        self.conditions_text.setPlainText(format_strategy_conditions(summary))

        stats = detail.statistics
        for key in (
            "matched_issues",
            "valid_samples",
            "invalid_samples",
            "hit_count",
            "miss_count",
            "max_consecutive_hits",
            "max_consecutive_misses",
            "train_triggers",
            "validation_triggers",
            "test_triggers",
            "walk_forward_windows",
            "walk_forward_triggers",
            "walk_forward_max_misses",
        ):
            self.stat_labels[key].setText(str(stats.get(key, 0)))
        for key in (
            "accuracy",
            "recent_30_accuracy",
            "recent_50_accuracy",
            "recent_100_accuracy",
            "recent_200_accuracy",
            "train_accuracy",
            "validation_accuracy",
            "test_accuracy",
            "walk_forward_accuracy",
            "walk_forward_worst",
        ):
            self.stat_labels[key].setText(_rate(stats.get(key)))
        warnings = []
        if stats.get("sample_warning"):
            warnings.append(display_status(stats["sample_warning"]))
        if stats.get("overfit_warning"):
            warnings.append(_warning_text(str(stats["overfit_warning"])))
        self.stat_labels["research_warnings"].setText("；".join(warnings) or "无")
        self.stat_labels["current_streak"].setText(
            _streak_values(
                str(stats.get("current_streak_type") or "NONE"),
                int(stats.get("current_streak_count") or 0),
            )
        )
        self.stat_labels["average_trigger_interval"].setText(
            _interval(stats.get("average_trigger_interval"))
        )
        pair_distribution = stats.get("selected_pair_distribution") or {}
        self.pair_distribution_group.setVisible(bool(pair_distribution))
        for pair_name, label in self.pair_distribution_labels.items():
            value = pair_distribution.get(pair_name, 0.0)
            label.setText(_rate(value) if pair_distribution else "—")

        latest = detail.latest_trigger
        if latest is None:
            self.latest_labels["issue"].setText("暂无触发记录")
            for key in ("distance", "prediction", "actual", "result", "sample_type"):
                self.latest_labels[key].setText("—")
        else:
            self.latest_labels["issue"].setText(str(latest.get("issue") or "—"))
            distance = latest.get("distance")
            self.latest_labels["distance"].setText("—" if distance is None else f"{distance}期")
            self.latest_labels["prediction"].setText(
                _prediction_value(latest.get("prediction")) or "—"
            )
            self.latest_labels["actual"].setText(str(latest.get("actual_result") or "等待开奖"))
            self.latest_labels["result"].setText(_result_text(latest.get("result_status")))
            self.latest_labels["sample_type"].setText(display_status(latest.get("sample_type")))
        self._render_history(detail.history_records)

    def _render_history(self, records) -> None:
        self.history_table.setRowCount(len(records))
        for row, record in enumerate(records):
            status = str(record.get("result_status") or "PENDING")
            values = (
                record.get("issue", ""),
                _prediction_value(record.get("prediction")) or display_status(status),
                record.get("actual_result") or "等待开奖",
                _result_text(status),
                display_status(record.get("sample_type")),
                display_status(record.get("source_type")),
                _format_time(record.get("generated_at")),
            )
            version = record.get("strategy_version") or "未记录"
            rule_hash = record.get("rule_hash") or "未记录"
            dynamic_details = _dynamic_record_tooltip(record)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                tooltip = f"策略版本：{version}\n规则哈希：{rule_hash}"
                if dynamic_details:
                    tooltip += f"\n{dynamic_details}"
                item.setToolTip(tooltip)
                if column == 3 and status == "PASS":
                    item.setForeground(QColor("#16834B"))
                elif column == 3 and status == "FAIL":
                    item.setForeground(QColor("#B43B3B"))
                self.history_table.setItem(row, column, item)
        self.history_count.setText(f"最近 {len(records)} 条")

    def _reload(self, *_args) -> None:
        scope = str(self.history_scope.currentData() or "ALL")
        if self.gateway is None:
            records = tuple(
                row
                for row in self.detail.history_records
                if scope == "ALL"
                or (scope == "VALIDATION" and row.get("sample_type") == "VALIDATION")
                or (scope == "FORWARD" and row.get("sample_type") == "FORWARD")
            )
            self._render_history(records[:100])
            return
        try:
            detail = self.gateway.strategy_detail(self.strategy_id, scope, 100)
        except Exception as exc:
            self.alert.setText(f"策略详情读取失败：{type(exc).__name__}: {exc}")
            self.alert.setVisible(True)
            return
        if detail is not None:
            self.alert.clear()
            self.alert.setVisible(False)
            self._show_detail(detail)


class StrategyResearchPage(QWidget):
    """Read-only view of official StrategyResearchEngine results."""

    HEADERS = (
        "策略编号",
        "样本数",
        "验证命中率",
        "前向命中率",
        "状态",
        "当期预测",
        "详情",
    )
    LARGE_SAMPLE_HEADERS = (
        "策略编号",
        "双组合",
        "条件摘要",
        "训练样本",
        "训练命中率",
        "验证样本",
        "验证命中率",
        "测试样本",
        "测试命中率",
        "最大连续未中",
        "平均触发间隔",
        "前向样本",
        "前向命中率",
        "状态",
        "详情",
    )
    DYNAMIC_PAIR_HEADERS = (
        "策略编号",
        "动态模式",
        "条件摘要",
        "训练样本",
        "训练命中率",
        "验证样本",
        "验证命中率",
        "测试样本",
        "测试命中率",
        "滚动验证命中率",
        "最大连续未中",
        "平均触发间隔",
        "状态",
        "详情",
    )
    STATE_V3_HEADERS = (
        "方法编号",
        "状态表示",
        "距离算法",
        "相似样本数",
        "时间权重",
        "训练命中率",
        "验证命中率",
        "测试命中率",
        "严格回放命中率",
        "95%置信区间",
        "生命周期",
    )
    ALGORITHM_V4_HEADERS = (
        "方法编号",
        "质量方法",
        "群组方法",
        "共识选择",
        "训练命中率",
        "验证命中率",
        "测试命中率",
        "严格回放命中率",
        "95%置信区间",
        "生命周期",
    )

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.loaded_strategies: tuple[StrategySummary, ...] = ()
        self.filtered_strategies: tuple[StrategySummary, ...] = ()
        self.display_numbers: dict[str, str] = {}
        self.large_sample_mode = False
        self.dynamic_pair_mode = False
        self.state_similarity_mode = False
        self.algorithm_quality_mode = False
        self.large_sample_status: dict = {}
        self.dynamic_pair_status: dict = {}
        self.state_similarity_status: dict = {}
        self.algorithm_quality_status: dict = {}
        self._research_type_initialized = False
        self._detail_dialog: StrategyDetailDialog | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)
        title = QLabel("策略研究")
        title.setObjectName("PageTitle")
        hint = QLabel("策略研究引擎正式研究结果，只读展示")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        cards = QGridLayout()
        cards.setSpacing(12)
        specs = (
            ("engine", "引擎状态"),
            ("database", "数据库状态"),
            ("updated", "最新研究时间"),
            ("periods", "正式生产期数"),
            ("candidates", "当前候选策略"),
            ("forward", "前向验证"),
            ("verified", "已验证"),
            ("freshness", "数据新鲜度"),
        )
        self.status_cards: dict[str, StatCard] = {}
        for index, (key, title_text) in enumerate(specs):
            card = StatCard(title_text, compact=True)
            self.status_cards[key] = card
            cards.addWidget(card, index // 4, index % 4)
        root.addLayout(cards)

        self.baseline_group = QGroupBox("A+基准")
        baseline_layout = QGridLayout(self.baseline_group)
        baseline_specs = (
            ("triggers", "触发次数"),
            ("hits", "命中"),
            ("misses", "未命中"),
            ("accuracy", "历史命中率"),
            ("recent_30_accuracy", "最近30"),
            ("recent_50_accuracy", "最近50"),
            ("recent_100_accuracy", "最近100"),
            ("recent_200_accuracy", "最近200"),
            ("max_consecutive_hits", "最大连续命中"),
            ("max_consecutive_misses", "最大连续未中"),
            ("current_streak", "当前连续状态"),
            ("average_trigger_interval", "平均触发间隔"),
        )
        self.baseline_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(baseline_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.baseline_labels[key] = value_label
            baseline_layout.addWidget(caption_label, (index // 6) * 2, index % 6)
            baseline_layout.addWidget(value_label, (index // 6) * 2 + 1, index % 6)
        self.baseline_group.setVisible(False)
        root.addWidget(self.baseline_group)

        current_row = QHBoxLayout()
        self.current_group = QGroupBox("当期策略状态")
        current_layout = QGridLayout(self.current_group)
        current_specs = (
            ("target_issue", "目标期号"),
            ("strategy_total", "策略总数"),
            ("ready", "已生成预测"),
            ("not_triggered", "未触发"),
            ("waiting", "等待数据"),
            ("invalid", "无效输入"),
            ("missed", "错过前向"),
        )
        self.current_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(current_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.current_labels[key] = value_label
            current_layout.addWidget(caption_label, 0, index)
            current_layout.addWidget(value_label, 1, index)
        current_row.addWidget(self.current_group, 2)

        self.distribution_group = QGroupBox("当期预测分布")
        distribution_layout = QGridLayout(self.distribution_group)
        self.distribution_labels: dict[str, QLabel] = {}
        for index, name in enumerate(("大单", "大双", "小单", "小双")):
            caption_label = QLabel(name)
            caption_label.setObjectName("Muted")
            value_label = QLabel("0")
            self.distribution_labels[name] = value_label
            distribution_layout.addWidget(caption_label, 0, index)
            distribution_layout.addWidget(value_label, 1, index)
        current_row.addWidget(self.distribution_group, 1)
        root.addLayout(current_row)

        self.state_v3_group = QGroupBox("当前状态")
        state_layout = QGridLayout(self.state_v3_group)
        state_specs = (
            ("target_issue", "当前目标期"),
            ("大单", "大单"),
            ("大双", "大双"),
            ("小单", "小单"),
            ("小双", "小双"),
            ("r1", "最低"),
            ("r2", "第二低"),
            ("r3", "第三低"),
            ("r4", "最高"),
            ("spread", "极差"),
            ("concentration", "集中程度"),
            ("state_label", "当前状态标签"),
            ("similar_count", "历史相似样本数量"),
            ("average_distance", "最近邻平均距离"),
        )
        self.state_v3_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(state_specs):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            self.state_v3_labels[key] = value_label
            row = (index // 7) * 2
            column = index % 7
            state_layout.addWidget(caption_label, row, column)
            state_layout.addWidget(value_label, row + 1, column)
        self.state_v3_group.setVisible(False)
        root.addWidget(self.state_v3_group)

        self.state_v3_tabs = QTabWidget()
        self.similar_state_tab = QWidget()
        similar_layout = QVBoxLayout(self.similar_state_tab)
        self.current_pair_table = QTableWidget(0, 4)
        self.current_pair_table.setHorizontalHeaderLabels(
            ("双组合", "样本数", "历史命中率", "95%置信区间")
        )
        self.current_pair_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.current_pair_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.current_pair_table, 150)
        self.neighbor_table = QTableWidget(0, 5)
        self.neighbor_table.setHorizontalHeaderLabels(
            ("历史期号", "相似度", "当时四组数量", "当时结果", "命中的双组合")
        )
        self.neighbor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.neighbor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.neighbor_table, 170)
        similar_layout.addWidget(self.current_pair_table)
        similar_layout.addWidget(self.neighbor_table)
        self.state_v3_tabs.addTab(self.similar_state_tab, "相似状态")

        self.recent_state_tab = QWidget()
        recent_layout = QVBoxLayout(self.recent_state_tab)
        self.recent_state_label = QLabel("—")
        self.recent_state_label.setObjectName("Muted")
        self.recent_state_table = QTableWidget(0, 7)
        self.recent_state_table.setHorizontalHeaderLabels(
            ("研究对象", "最近30", "最近50", "最近100", "最近200", "最近500", "长期基准")
        )
        self.recent_state_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_state_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.recent_state_table, 170)
        recent_layout.addWidget(self.recent_state_label)
        recent_layout.addWidget(self.recent_state_table)
        self.state_v3_tabs.addTab(self.recent_state_tab, "近期状态")

        self.replay_tab = QWidget()
        replay_layout = QVBoxLayout(self.replay_tab)
        self.replay_summary_label = QLabel("—")
        self.replay_summary_label.setObjectName("Muted")
        self.replay_table = QTableWidget(0, 7)
        self.replay_table.setHorizontalHeaderLabels(
            ("目标期", "当时历史池大小", "相似样本数", "选择双组合", "实际结果", "结果", "数据阶段")
        )
        self.replay_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.replay_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.replay_table, 170)
        replay_layout.addWidget(self.replay_summary_label)
        replay_layout.addWidget(self.replay_table)
        self.state_v3_tabs.addTab(self.replay_tab, "历史回放")
        self.state_v3_tabs.setVisible(False)
        root.addWidget(self.state_v3_tabs, 1)

        self.algorithm_v4_tabs = QTabWidget()
        self.algorithm_quality_tab = QWidget()
        quality_layout = QVBoxLayout(self.algorithm_quality_tab)
        self.algorithm_quality_table = QTableWidget(0, 9)
        self.algorithm_quality_table.setHorizontalHeaderLabels(
            ("算法编号", "最近30", "最近50", "最近100", "最近200", "最近500",
             "95%置信区间", "稳定性", "当前分层")
        )
        self.algorithm_quality_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.algorithm_quality_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.algorithm_quality_table, 180)
        quality_layout.addWidget(self.algorithm_quality_table)
        self.algorithm_v4_tabs.addTab(self.algorithm_quality_tab, "算法质量")

        self.algorithm_groups_tab = QWidget()
        groups_layout = QVBoxLayout(self.algorithm_groups_tab)
        self.algorithm_groups_table = QTableWidget(0, 5)
        self.algorithm_groups_table.setHorizontalHeaderLabels(
            ("群组编号", "算法数量", "主要成员", "群组内部一致率", "当前共识")
        )
        self.algorithm_groups_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.algorithm_groups_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.algorithm_groups_table, 160)
        groups_layout.addWidget(self.algorithm_groups_table)
        self.algorithm_v4_tabs.addTab(self.algorithm_groups_tab, "算法群组")

        self.weighted_consensus_tab = QWidget()
        consensus_layout = QVBoxLayout(self.weighted_consensus_tab)
        self.weighted_consensus_label = QLabel("—")
        self.weighted_consensus_label.setObjectName("Muted")
        self.weighted_consensus_table = QTableWidget(4, 3)
        self.weighted_consensus_table.setHorizontalHeaderLabels(
            ("组合", "普通等权", "加权共识")
        )
        self.weighted_consensus_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.weighted_consensus_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        polish_table(self.weighted_consensus_table, 150)
        consensus_layout.addWidget(self.weighted_consensus_label)
        consensus_layout.addWidget(self.weighted_consensus_table)
        self.algorithm_v4_tabs.addTab(self.weighted_consensus_tab, "当前加权共识")
        self.algorithm_v4_tabs.setVisible(False)
        root.addWidget(self.algorithm_v4_tabs, 1)

        controls = QHBoxLayout()
        research_type_label = QLabel("研究类型")
        research_type_label.setObjectName("Muted")
        self.research_type = QComboBox()
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部", ("all", None))
        self.status_filter.addItem("已触发", ("prediction", "READY"))
        self.status_filter.addItem("未触发", ("prediction", "NOT_TRIGGERED"))
        self.status_filter.addItem("等待数据", ("prediction", "WAITING_DATA"))
        self.status_filter.addItem("前向验证中", ("lifecycle", "FORWARD_TEST"))
        self.status_filter.addItem("已验证", ("lifecycle", "VERIFIED"))
        self.status_filter.addItem("候选策略", ("lifecycle", "CANDIDATE"))
        self.status_filter.addItem("观察中", ("lifecycle", "OBSERVATION"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索策略编号或名称")
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
        controls.addWidget(research_type_label)
        controls.addWidget(self.research_type)
        controls.addWidget(self.status_filter)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.count_label)
        root.addLayout(controls)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((88, 90, 120, 120, 120, 180, 76)):
            header.resizeSection(column, width)
        polish_table(self.table, 460)
        root.addWidget(self.table, 1)

        self.status_filter.currentTextChanged.connect(self._apply_filters)
        self.research_type.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self._apply_filters)
        self.table.cellDoubleClicked.connect(self._show_detail)

    def refresh(self) -> None:
        try:
            status = self.gateway.strategy_status()
            algorithm_status = (
                self.gateway.strategy_algorithm_quality_status()
                if hasattr(self.gateway, "strategy_algorithm_quality_status")
                else {"available": False}
            )
            state_status = (
                self.gateway.strategy_state_similarity_status()
                if hasattr(self.gateway, "strategy_state_similarity_status")
                else {"available": False}
            )
            dynamic_status = (
                self.gateway.strategy_dynamic_pair_status()
                if hasattr(self.gateway, "strategy_dynamic_pair_status")
                else {"available": False}
            )
            large_status = (
                self.gateway.strategy_large_sample_status()
                if hasattr(self.gateway, "strategy_large_sample_status")
                else {"available": False}
            )
            self._sync_research_types(
                algorithm_status, state_status, dynamic_status, large_status
            )
            research_type = str(self.research_type.currentData() or "CURRENT")
            self.algorithm_quality_mode = (
                research_type == "ALGORITHM_V4" and bool(algorithm_status.get("available"))
            )
            self.state_similarity_mode = (
                research_type == "STATE_V3" and bool(state_status.get("available"))
            )
            self.dynamic_pair_mode = (
                research_type == "DYNAMIC_V2" and bool(dynamic_status.get("available"))
            )
            self.large_sample_mode = (
                research_type == "FIXED_V1" and bool(large_status.get("available"))
            )
            self.large_sample_status = large_status
            self.dynamic_pair_status = dynamic_status
            self.state_similarity_status = state_status
            self.algorithm_quality_status = algorithm_status
            strategies = (
                self.gateway.strategy_algorithm_quality_list(20)
                if self.algorithm_quality_mode
                else self.gateway.strategy_state_similarity_list(20)
                if self.state_similarity_mode
                else self.gateway.strategy_dynamic_pair_list(100)
                if self.dynamic_pair_mode
                else self.gateway.strategy_large_sample_list(100)
                if self.large_sample_mode
                else self.gateway.strategy_list(5000)
            )
            current = (
                {
                    "target_issue": None,
                    "strategy_total": len(strategies),
                    "status_counts": {"WAITING_DATA": len(strategies)},
                    "distribution": {},
                }
                if self.large_sample_mode or self.dynamic_pair_mode or self.state_similarity_mode or self.algorithm_quality_mode
                else self.gateway.strategy_current_status()
            )
        except Exception as exc:
            self._show_error(f"策略研究引擎读取失败：{type(exc).__name__}: {exc}")
            return
        self.loaded_strategies = tuple(strategies)
        self.display_numbers = {
            strategy_id: f"{index:03d}"
            for index, strategy_id in enumerate(
                sorted({row.strategy_id for row in self.loaded_strategies}), start=1
            )
        }
        freshness = status.get("freshness", {}).get("status", "OFFLINE")
        if self.large_sample_mode:
            status = {
                **status,
                "latest_research_at": large_status.get("completed_at"),
                "production_periods": large_status.get("valid_issues", 0),
                "candidate_strategies": large_status.get("final_candidates", 0),
            }
        elif self.dynamic_pair_mode:
            status = {
                **status,
                "latest_research_at": dynamic_status.get("completed_at"),
                "production_periods": dynamic_status.get("total_issues", 0),
                "candidate_strategies": dynamic_status.get("final_candidates", 0),
            }
        elif self.state_similarity_mode:
            status = {
                **status,
                "latest_research_at": state_status.get("completed_at"),
                "production_periods": state_status.get("total_issues", 0),
                "candidate_strategies": state_status.get("final_candidates", 0),
            }
        elif self.algorithm_quality_mode:
            status = {
                **status,
                "latest_research_at": algorithm_status.get("completed_at"),
                "production_periods": algorithm_status.get("total_issues", 0),
                "candidate_strategies": algorithm_status.get("final_candidates", 0),
            }
        values = {
            "engine": status.get("status", "OFFLINE"),
            "database": status.get("database_status", "OFFLINE"),
            "updated": _format_time(status.get("latest_research_at")),
            "periods": status.get("production_periods", 0),
            "candidates": status.get("candidate_strategies", 0),
            "forward": status.get("forward_test_strategies", 0),
            "verified": status.get("verified_strategies", 0),
            "freshness": freshness,
        }
        for key, value in values.items():
            self.status_cards[key].set_value(
                display_status(value) if key in {"engine", "database", "freshness"} else value
            )
        counts = current.get("status_counts", {})
        current_values = {
            "target_issue": current.get("target_issue") or "—",
            "strategy_total": current.get("strategy_total", 0),
            "ready": counts.get("READY", 0),
            "not_triggered": counts.get("NOT_TRIGGERED", 0),
            "waiting": counts.get("WAITING_DATA", 0),
            "invalid": counts.get("INVALID_INPUT", 0),
            "missed": counts.get("MISSED_FORWARD", 0),
        }
        for key, value in current_values.items():
            self.current_labels[key].setText(str(value))
        distribution = current.get("distribution", {})
        for name, label in self.distribution_labels.items():
            label.setText(str(distribution.get(name, 0)))
        self._show_baseline(large_status.get("baseline", {}))
        self.current_group.setVisible(not self.state_similarity_mode and not self.algorithm_quality_mode)
        self.distribution_group.setVisible(not self.state_similarity_mode and not self.algorithm_quality_mode)
        self.state_v3_group.setVisible(self.state_similarity_mode)
        self.state_v3_tabs.setVisible(self.state_similarity_mode)
        self.algorithm_v4_tabs.setVisible(self.algorithm_quality_mode)
        if self.state_similarity_mode:
            self._show_state_similarity(state_status)
        elif self.algorithm_quality_mode:
            self._show_algorithm_quality(algorithm_status)
        self._configure_table()
        problems = []
        if status.get("status") in {"OFFLINE", "STALE", "ERROR"}:
            problems.append(f"引擎 {display_status(status.get('status'))}")
        if status.get("database_status") != "ONLINE":
            problems.append(f"数据库 {display_status(status.get('database_status'))}")
        if freshness != "FRESH":
            problems.append(f"数据新鲜度 {display_status(freshness)}")
        if problems:
            self._show_error("；".join(problems))
        else:
            self.alert.clear()
            self.alert.setVisible(False)
        self._apply_filters()

    def _sync_research_types(
        self,
        algorithm_status: dict,
        state_status: dict,
        dynamic_status: dict,
        large_status: dict,
    ) -> None:
        current = self.research_type.currentData()
        options = []
        if algorithm_status.get("available"):
            options.append(("算法质量与群体共识 v4", "ALGORITHM_V4"))
        if state_status.get("available"):
            options.append(("当前状态与相似状态 v3", "STATE_V3"))
        if dynamic_status.get("available"):
            options.append(("动态双组合 v2", "DYNAMIC_V2"))
        if large_status.get("available"):
            options.append(("固定双组合 v1", "FIXED_V1"))
        if not options:
            options.append(("正式策略", "CURRENT"))
        values = [value for _label, value in options]
        selected = current if current in values else values[0]
        self.research_type.blockSignals(True)
        self.research_type.clear()
        for label, value in options:
            self.research_type.addItem(label, value)
        self.research_type.setCurrentIndex(values.index(selected))
        self.research_type.blockSignals(False)
        self._research_type_initialized = True

    def _show_algorithm_quality(self, status: dict) -> None:
        algorithms = self.gateway.strategy_algorithm_quality_algorithms()
        self.algorithm_quality_table.setRowCount(len(algorithms))
        algorithm_numbers = {
            str(item.get("algorithm_id")): f"算法{int(item.get('algorithm_order', 0)):03d}"
            for item in algorithms
        }
        for row, item in enumerate(algorithms):
            interval = "{low}–{high}".format(
                low=_rate(item.get("ci_low")), high=_rate(item.get("ci_high"))
            )
            values = (
                algorithm_numbers.get(str(item.get("algorithm_id")), "—"),
                _rate(item.get("recent_30")),
                _rate(item.get("recent_50")),
                _rate(item.get("recent_100")),
                _rate(item.get("recent_200")),
                _rate(item.get("recent_500")),
                interval,
                f"波动 {_decimal(item.get('rolling_std'), 4)}",
                display_status(item.get("quality_tier")),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, str(item.get("algorithm_id") or ""))
                self.algorithm_quality_table.setItem(row, column, cell)

        groups = self.gateway.strategy_algorithm_quality_groups()
        self.algorithm_groups_table.setRowCount(len(groups))
        for row, item in enumerate(groups):
            members = [
                algorithm_numbers.get(str(value), "未知算法")
                for value in item.get("members", ())[:6]
            ]
            if int(item.get("algorithm_count", 0)) > len(members):
                members.append("等")
            values = (
                f"群组{int(item.get('group_number', 0)):03d}",
                item.get("algorithm_count", 0),
                "、".join(members),
                _rate(item.get("internal_agreement")),
                item.get("current_consensus", "—"),
            )
            for column, value in enumerate(values):
                self.algorithm_groups_table.setItem(row, column, QTableWidgetItem(str(value)))

        current = self.gateway.strategy_algorithm_quality_current()
        equal = current.get("equal_totals", {})
        weighted = current.get("weighted_totals", {})
        for row, name in enumerate(("大单", "大双", "小单", "小双")):
            values = (name, _decimal(equal.get(name), 2), _decimal(weighted.get(name), 2))
            for column, value in enumerate(values):
                self.weighted_consensus_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.weighted_consensus_label.setText(
            "目标期号 {issue}；质量方法：{quality}；群组方法：{group}；"
            "排序变化：{ranking}；选择变化：{pair}".format(
                issue=current.get("target_issue", "—"),
                quality=display_status(current.get("quality_method")),
                group=display_status(current.get("group_method")),
                ranking="是" if current.get("ranking_changed") else "否",
                pair="是" if current.get("selected_pair_changed") else "否",
            )
        )

    def _show_state_similarity(self, status: dict) -> None:
        current = self.gateway.strategy_state_similarity_current()
        features = current.get("features", {})
        counts = features.get("counts", {})
        values = {
            "target_issue": current.get("target_issue", "—"),
            "大单": counts.get("大单", 0),
            "大双": counts.get("大双", 0),
            "小单": counts.get("小单", 0),
            "小双": counts.get("小双", 0),
            "r1": _rank_value(features, "r1"),
            "r2": _rank_value(features, "r2"),
            "r3": _rank_value(features, "r3"),
            "r4": _rank_value(features, "r4"),
            "spread": features.get("spread", "—"),
            "concentration": _decimal(features.get("concentration"), 4),
            "state_label": display_status(current.get("state_label")),
            "similar_count": current.get("similar_sample_count", 0),
            "average_distance": _decimal(current.get("average_distance"), 4),
        }
        for key, value in values.items():
            self.state_v3_labels[key].setText(str(value))

        pair_statistics = current.get("pair_statistics", {})
        self.current_pair_table.setRowCount(len(PAIR_NAMES))
        for row, pair_name in enumerate(PAIR_NAMES):
            metrics = pair_statistics.get(pair_name, {})
            pair_values = (
                pair_name.replace("+", " + "),
                metrics.get("samples", 0),
                _rate(metrics.get("accuracy")),
                _confidence_interval(metrics),
            )
            for column, value in enumerate(pair_values):
                self.current_pair_table.setItem(row, column, QTableWidgetItem(str(value)))

        neighbors = current.get("neighbors", ())
        self.neighbor_table.setRowCount(len(neighbors))
        for row, item in enumerate(neighbors):
            counts_text = "、".join(
                f"{name} {item.get('counts', {}).get(name, 0)}"
                for name in ("大单", "大双", "小单", "小双")
            )
            neighbor_values = (
                item.get("historical_issue", "—"),
                _decimal(item.get("similarity"), 4),
                counts_text,
                item.get("actual_combination", "—"),
                "、".join(str(value).replace("+", " + ") for value in item.get("hit_pairs", ())),
            )
            for column, value in enumerate(neighbor_values):
                self.neighbor_table.setItem(row, column, QTableWidgetItem(str(value)))

        best = status.get("best_summary", {})
        recent = best.get("recent", {})
        strict = best.get("strict", {})
        self.recent_state_label.setText(
            f"近期状态：{display_status(best.get('recent_state'))}"
        )
        self.recent_state_table.setRowCount(1 if best else 0)
        if best:
            recent_values = (
                best.get("method_id", "—"),
                _rate((recent.get("30") or {}).get("accuracy")),
                _rate((recent.get("50") or {}).get("accuracy")),
                _rate((recent.get("100") or {}).get("accuracy")),
                _rate((recent.get("200") or {}).get("accuracy")),
                _rate((recent.get("500") or {}).get("accuracy")),
                _rate(strict.get("accuracy")),
            )
            for column, value in enumerate(recent_values):
                self.recent_state_table.setItem(0, column, QTableWidgetItem(str(value)))

        replay = self.gateway.strategy_state_similarity_replay(
            status.get("best_method_id"), 100
        )
        self.replay_table.setRowCount(len(replay))
        for row, item in enumerate(replay):
            result = "未触发" if not item.get("triggered") else "命中" if item.get("hit") else "未命中"
            replay_values = (
                item.get("target_issue", "—"),
                item.get("historical_pool_size", 0),
                item.get("similar_sample_count", 0),
                " + ".join(item.get("selected_pair") or ()),
                item.get("actual_combination", "—"),
                result,
                display_status(item.get("dataset_split")),
            )
            for column, value in enumerate(replay_values):
                self.replay_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.replay_summary_label.setText(
            "触发 {triggers}；命中率 {rate}；最大连续未中 {misses}；95%置信区间 {interval}".format(
                triggers=strict.get("triggers", 0),
                rate=_rate(strict.get("accuracy")),
                misses=strict.get("max_consecutive_misses", 0),
                interval=_confidence_interval(strict),
            )
        )

    def _show_baseline(self, baseline: dict) -> None:
        self.baseline_group.setVisible(self.large_sample_mode)
        if not self.large_sample_mode:
            return
        for key in (
            "triggers",
            "hits",
            "misses",
            "max_consecutive_hits",
            "max_consecutive_misses",
        ):
            self.baseline_labels[key].setText(str(baseline.get(key, 0)))
        for key in (
            "accuracy",
            "recent_30_accuracy",
            "recent_50_accuracy",
            "recent_100_accuracy",
            "recent_200_accuracy",
        ):
            self.baseline_labels[key].setText(_rate(baseline.get(key)))
        self.baseline_labels["current_streak"].setText(
            _streak_values(
                str(baseline.get("current_streak_type") or "NONE"),
                int(baseline.get("current_streak_count") or 0),
            )
        )
        self.baseline_labels["average_trigger_interval"].setText(
            _interval(baseline.get("average_trigger_interval"))
        )

    def _configure_table(self) -> None:
        headers = (
            self.ALGORITHM_V4_HEADERS
            if self.algorithm_quality_mode
            else self.STATE_V3_HEADERS
            if self.state_similarity_mode
            else self.DYNAMIC_PAIR_HEADERS
            if self.dynamic_pair_mode
            else self.LARGE_SAMPLE_HEADERS
            if self.large_sample_mode
            else self.HEADERS
        )
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        widths = (
            (90, 175, 175, 130, 105, 105, 105, 125, 150, 90)
            if self.algorithm_quality_mode
            else
            (90, 130, 110, 100, 145, 105, 105, 105, 125, 150, 90)
            if self.state_similarity_mode
            else
            (82, 145, 220, 90, 105, 90, 105, 90, 105, 125, 110, 110, 100, 70)
            if self.dynamic_pair_mode
            else
            (82, 120, 220, 90, 105, 90, 105, 90, 105, 110, 110, 90, 105, 100, 70)
            if self.large_sample_mode
            else (88, 90, 120, 120, 120, 180, 76)
        )
        for column, width in enumerate(widths):
            self.table.horizontalHeader().resizeSection(column, width)
        self.table.setSortingEnabled(True)

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _apply_filters(self, *_args) -> None:
        filter_kind, filter_value = self.status_filter.currentData()
        query = self.search.text().strip().lower()
        values = []
        for strategy in self.loaded_strategies:
            if filter_kind == "prediction" and strategy.prediction_status != filter_value:
                continue
            if filter_kind == "lifecycle" and strategy.status != filter_value:
                continue
            searchable = " ".join(
                (
                    self.display_numbers.get(strategy.strategy_id, ""),
                    strategy.strategy_id,
                    strategy.strategy_name,
                    strategy.strategy_version,
                    strategy.predictor,
                )
            ).lower()
            if query and query not in searchable:
                continue
            values.append(strategy)
        self.filtered_strategies = tuple(values)
        self._render()

    def _render(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_strategies))
        for row, strategy in enumerate(self.filtered_strategies):
            display_number = self.display_numbers[strategy.strategy_id]
            if self.algorithm_quality_mode:
                conditions = strategy.conditions
                values = (
                    (display_number, int(display_number)),
                    (display_status(conditions.get("quality_method")), str(conditions.get("quality_method"))),
                    (display_status(conditions.get("group_method")), str(conditions.get("group_method"))),
                    (display_status(conditions.get("selection_method")), str(conditions.get("selection_method"))),
                    (_rate(strategy.train_accuracy), _sort_rate(strategy.train_accuracy)),
                    (_rate(strategy.validation_accuracy), _sort_rate(strategy.validation_accuracy)),
                    (_rate(strategy.test_accuracy), _sort_rate(strategy.test_accuracy)),
                    (_rate(strategy.accuracy), _sort_rate(strategy.accuracy)),
                    (_confidence_interval(conditions), conditions.get("ci_low") or -1),
                    (display_status(strategy.status), strategy.status),
                )
            elif self.state_similarity_mode:
                conditions = strategy.conditions
                values = (
                    (display_number, int(display_number)),
                    (display_status(conditions.get("representation")), str(conditions.get("representation"))),
                    (display_status(conditions.get("distance_method")), str(conditions.get("distance_method"))),
                    (str(conditions.get("k_value", 0)), int(conditions.get("k_value", 0))),
                    (display_status(conditions.get("time_decay")), str(conditions.get("time_decay"))),
                    (_rate(strategy.train_accuracy), _sort_rate(strategy.train_accuracy)),
                    (_rate(strategy.validation_accuracy), _sort_rate(strategy.validation_accuracy)),
                    (_rate(strategy.test_accuracy), _sort_rate(strategy.test_accuracy)),
                    (_rate(strategy.accuracy), _sort_rate(strategy.accuracy)),
                    (_confidence_interval(conditions), conditions.get("ci_low") or -1),
                    (display_status(strategy.status), strategy.status),
                )
            elif self.dynamic_pair_mode:
                dynamic_mode = display_status(strategy.conditions.get("dynamic_mode"))
                summary = _dynamic_condition_summary(strategy.conditions)
                values = (
                    (display_number, int(display_number)),
                    (dynamic_mode, str(strategy.conditions.get("dynamic_mode") or "")),
                    (summary, summary),
                    (str(strategy.train_triggers), strategy.train_triggers),
                    (_rate(strategy.train_accuracy), _sort_rate(strategy.train_accuracy)),
                    (str(strategy.validation_triggers), strategy.validation_triggers),
                    (_rate(strategy.validation_accuracy), _sort_rate(strategy.validation_accuracy)),
                    (str(strategy.test_triggers), strategy.test_triggers),
                    (_rate(strategy.test_accuracy), _sort_rate(strategy.test_accuracy)),
                    (_rate(strategy.walk_forward_accuracy), _sort_rate(strategy.walk_forward_accuracy)),
                    (str(strategy.max_consecutive_misses), strategy.max_consecutive_misses),
                    (_interval(strategy.average_trigger_interval), strategy.average_trigger_interval or -1),
                    (display_status(strategy.status), strategy.status),
                    ("详情", strategy.strategy_id),
                )
            elif self.large_sample_mode:
                pair = " + ".join(strategy.current_prediction or ())
                summary = _condition_summary(strategy.conditions)
                values = (
                    (display_number, int(display_number)),
                    (pair, pair),
                    (summary, summary),
                    (str(strategy.train_triggers), strategy.train_triggers),
                    (_rate(strategy.train_accuracy), _sort_rate(strategy.train_accuracy)),
                    (str(strategy.validation_triggers), strategy.validation_triggers),
                    (_rate(strategy.validation_accuracy), _sort_rate(strategy.validation_accuracy)),
                    (str(strategy.test_triggers), strategy.test_triggers),
                    (_rate(strategy.test_accuracy), _sort_rate(strategy.test_accuracy)),
                    (str(strategy.max_consecutive_misses), strategy.max_consecutive_misses),
                    (
                        _interval(strategy.average_trigger_interval),
                        strategy.average_trigger_interval or -1,
                    ),
                    (str(strategy.forward_samples), strategy.forward_samples),
                    (_rate(strategy.forward_accuracy), _sort_rate(strategy.forward_accuracy)),
                    (display_status(strategy.status), strategy.status),
                    ("详情", strategy.strategy_id),
                )
            else:
                values = (
                    (display_number, int(display_number)),
                    (str(strategy.trigger_count), strategy.trigger_count),
                    (_rate(strategy.validation_accuracy), _sort_rate(strategy.validation_accuracy)),
                    (_rate(strategy.forward_accuracy), _sort_rate(strategy.forward_accuracy)),
                    (display_status(strategy.status), strategy.status),
                    (_current_prediction_text(strategy), strategy.prediction_status),
                    ("详情", strategy.strategy_id),
                )
            for column, (text, sort_value) in enumerate(values):
                item = SortableItem(text, sort_value)
                item.setData(Qt.UserRole, strategy.strategy_id)
                status_column = 9 if self.algorithm_quality_mode else 10 if self.state_similarity_mode else 12 if self.dynamic_pair_mode else 13 if self.large_sample_mode else 4
                if column == status_column:
                    item.setForeground(QColor(STATUS_COLORS.get(strategy.status, "#667085")))
                    if strategy.sample_warning:
                        item.setToolTip("样本不足")
                if not self.large_sample_mode and not self.dynamic_pair_mode and not self.state_similarity_mode and not self.algorithm_quality_mode and column == 5:
                    item.setToolTip(
                        "\n".join(
                            (
                                f"策略版本：{strategy.strategy_version}",
                                f"规则哈希：{strategy.rule_hash or strategy.strategy_hash}",
                                f"目标期号：{strategy.target_issue or '—'}",
                                f"生成时间：{_format_time(strategy.prediction_generated_at)}",
                                f"来源：{display_status(strategy.prediction_source)}",
                            )
                        )
                    )
                self.table.setItem(row, column, item)
            if not self.state_similarity_mode and not self.algorithm_quality_mode:
                detail_button = QPushButton("详情")
                detail_button.setProperty("strategy_id", strategy.strategy_id)
                secondary_button(detail_button)
                detail_button.clicked.connect(partial(self._show_detail_for_id, strategy.strategy_id))
                detail_column = 13 if self.dynamic_pair_mode else 14 if self.large_sample_mode else 6
                self.table.setCellWidget(row, detail_column, detail_button)
        self.table.setSortingEnabled(True)
        self.count_label.setText(
            f"显示 {len(self.filtered_strategies)} / {len(self.loaded_strategies)} 条"
        )

    def _show_detail(self, row: int, _column: int) -> None:
        if self.state_similarity_mode or self.algorithm_quality_mode:
            return
        item = self.table.item(row, 0)
        if item is not None:
            self._show_detail_for_id(str(item.data(Qt.UserRole)))

    def _show_detail_for_id(self, strategy_id: str) -> None:
        try:
            detail = self.gateway.strategy_detail(strategy_id, "ALL", 100)
        except Exception as exc:
            self._show_error(f"策略详情读取失败：{type(exc).__name__}: {exc}")
            return
        if detail is None:
            return
        self._detail_dialog = StrategyDetailDialog(
            detail,
            self.display_numbers[strategy_id],
            self.gateway,
            self,
        )
        self._detail_dialog.exec()

    def visible_strategy_count(self) -> int:
        return self.table.rowCount()


def format_strategy_conditions(strategy: StrategySummary) -> str:
    if isinstance(strategy.conditions, dict) and strategy.conditions.get("dynamic_mode"):
        lines = [
            f"动态模式：{display_status(strategy.conditions.get('dynamic_mode'))}",
            f"并列规则：{display_status(strategy.conditions.get('tie_rule'))}",
        ]
        filters = strategy.conditions.get("filters") or []
        if not filters:
            lines.append("过滤条件：无")
        else:
            for condition in filters:
                lines.extend(_condition_lines(condition))
        return "\n".join(lines)
    predictor = PREDICTOR_TEXT.get(strategy.predictor)
    lines = [f"预测目标：{predictor or '其他目标：' + strategy.predictor}"]
    selected_pair = strategy.conditions.get("selected_pair") if isinstance(strategy.conditions, dict) else None
    if isinstance(selected_pair, list) and len(selected_pair) == 2:
        lines.append(f"双组合：{' + '.join(str(value) for value in selected_pair)}")
    lines.extend(_condition_lines(strategy.conditions))
    return "\n".join(lines)


def _condition_lines(condition) -> list[str]:
    if not isinstance(condition, dict):
        return [f"其他条件：{condition}"]
    if "all" in condition:
        children = condition.get("all")
        if not isinstance(children, list) or not children:
            return ["过滤条件：无"]
        lines: list[str] = []
        for child in children:
            lines.extend(_condition_lines(child))
        return lines
    field = str(condition.get("field") or "未知字段")
    operation = str(condition.get("op") or "未知关系")
    value = condition.get("value")
    label = (
        CONDITION_FIELDS.get(field)
        or LARGE_SAMPLE_CONDITION_FIELDS.get(field)
        or DYNAMIC_CONDITION_FIELDS.get(field)
    )
    prefix = label if label else f"其他条件：{field}"
    if field in {"lowest_is_unique", "highest_is_unique"} and operation == "eq":
        return [f"{prefix}：{'必须唯一' if bool(value) else '允许并列'}"]
    if field == "lowest_boundary_tie" and operation == "eq":
        return [f"{prefix}：{'是' if bool(value) else '否'}"]
    if field == "pair_rank" and operation == "eq":
        rank_text = {
            "LOWEST_TWO": "最低两项",
            "CONTAINS_LOWEST": "包含最低项",
            "HIGHEST_TWO": "最高两项",
        }.get(str(value), "未知排名")
        return [f"{prefix}：{rank_text}"]
    if operation == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
        return [f"{prefix}范围：{_number(value[0])} 至 {_number(value[1])}"]
    if operation == "in" and isinstance(value, (list, tuple)):
        return [f"{prefix}：{'、'.join(_number(item) for item in value)}"]
    operation_text = {"eq": "", "le": "不高于 ", "ge": "不低于 "}.get(operation)
    if operation_text is None:
        return [f"{prefix}：{operation} {_number(value)}"]
    return [f"{prefix}：{operation_text}{_number(value)}"]


def _number(value) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _condition_summary(condition) -> str:
    lines = _condition_lines(condition)
    return "；".join(lines[:2]) if lines else "无过滤条件"


def _dynamic_condition_summary(condition) -> str:
    if not isinstance(condition, dict):
        return "无过滤条件"
    filters = condition.get("filters") or []
    filter_text = "；".join(
        line for item in filters for line in _condition_lines(item)
    ) or "无过滤条件"
    tie_rule = display_status(condition.get("tie_rule"))
    return f"{tie_rule}；{filter_text}"


def _dynamic_record_tooltip(record) -> str:
    if not isinstance(record, dict) or not record.get("dynamic_mode"):
        return ""
    counts = record.get("counts") or {}
    ranks = record.get("ranks") or []
    count_text = "、".join(f"{name} {counts.get(name, 0)}" for name in ("大单", "大双", "小单", "小双"))
    rank_text = "、".join(
        f"第{index}名 {name}" for index, name in enumerate(ranks, start=1)
    )
    filters = record.get("filters") or []
    filter_text = "；".join(
        line for item in filters for line in _condition_lines(item)
    ) or "无"
    return "\n".join(
        (
            f"四组数量：{count_text}",
            f"升序排名：{rank_text}",
            f"动态模式：{display_status(record.get('dynamic_mode'))}",
            f"并列规则：{display_status(record.get('tie_rule'))}",
            f"过滤条件：{filter_text}",
        )
    )


def _warning_text(value: str) -> str:
    labels = {
        "TRAIN_VALIDATION_GAP": "训练与验证差异偏大",
        "VALIDATION_TEST_GAP": "验证与测试差异偏大",
        "MISS_STREAK_DETERIORATION": "连续未中有所恶化",
        "DYNAMIC_COLLAPSE_WARNING": "动态选择退化警告",
    }
    return "、".join(labels.get(item, "研究警告") for item in value.split(",") if item)


def _current_prediction_text(strategy: StrategySummary) -> str:
    if strategy.prediction_status == "READY" and strategy.current_prediction:
        return " + ".join(strategy.current_prediction)
    return display_status(strategy.prediction_status)


def _prediction_value(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, (list, tuple)):
        return " + ".join(str(item) for item in value)
    return str(value or "")


def _result_text(value) -> str:
    status = str(value or "PENDING")
    return {
        "PASS": "对",
        "FAIL": "错",
        "PENDING": "等待开奖",
        "READY": "等待开奖",
    }.get(status, display_status(status))


def _rate(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _sort_rate(value) -> float:
    return -1.0 if value is None else float(value)


def _decimal(value, places: int = 4) -> str:
    return "—" if value is None else f"{float(value):.{places}f}"


def _confidence_interval(metrics) -> str:
    if not isinstance(metrics, dict):
        return "—"
    low = metrics.get("ci_low")
    high = metrics.get("ci_high")
    if low is None or high is None:
        return "—"
    return f"{float(low) * 100:.1f}% 至 {float(high) * 100:.1f}%"


def _rank_value(features: dict, key: str) -> str:
    name = features.get(key)
    count = features.get(f"{key}_count")
    return "—" if name is None or count is None else f"{name} {count}"


def _interval(value: float | None) -> str:
    return "—" if value is None else f"{float(value):.1f}期"


def _streak_values(streak_type: str, count: int) -> str:
    labels = {"HIT": "连中", "MISS": "连错", "NONE": "无"}
    label = labels.get(streak_type, display_status(streak_type))
    return label if count == 0 else f"{label}{count}"


def _format_time(value) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
