from __future__ import annotations

from datetime import datetime
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from ..integration.models import StrategyDetail, StrategySummary
from .widgets import StatCard


LIFECYCLE_STATES = (
    "RESEARCH_ONLY",
    "CANDIDATE",
    "FORWARD_TEST",
    "VERIFIED",
    "REJECTED",
)

STATUS_COLORS = {
    "RESEARCH_ONLY": "#667085",
    "CANDIDATE": "#C26A00",
    "FORWARD_TEST": "#1478E5",
    "VERIFIED": "#16834B",
    "REJECTED": "#B43B3B",
}


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
    def __init__(self, detail: StrategyDetail, parent=None):
        super().__init__(parent)
        self.detail = detail
        summary = detail.summary
        self.setWindowTitle(f"策略详情 · {summary.strategy_id}")
        self.resize(1120, 760)
        root = QVBoxLayout(self)

        if summary.sample_warning:
            warning = QLabel("样本不足：该策略不能因短期准确率被视为推荐或高概率策略。")
            warning.setObjectName("WarningText")
            warning.setWordWrap(True)
            root.addWidget(warning)

        overview = QGridLayout()
        fields = (
            ("策略ID", summary.strategy_id),
            ("生命周期", summary.status),
            ("创建时间", _format_time(summary.created_at)),
            ("预测器", summary.predictor),
            ("策略HASH", summary.strategy_hash),
            ("最大连续命中", summary.max_consecutive_hits),
            ("最大连续未命中", summary.max_consecutive_misses),
            ("当前连续状态", _streak_text(summary)),
            ("平均触发间隔", _interval(summary.average_trigger_interval)),
            ("后台原始状态", summary.source_status or "—"),
        )
        for index, (name, value) in enumerate(fields):
            name_label = QLabel(name)
            name_label.setObjectName("Muted")
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            overview.addWidget(name_label, index // 5 * 2, index % 5)
            overview.addWidget(value_label, index // 5 * 2 + 1, index % 5)
        root.addLayout(overview)

        conditions = QTextEdit()
        conditions.setReadOnly(True)
        conditions.setMaximumHeight(88)
        conditions.setPlainText(_conditions(summary))
        condition_form = QFormLayout()
        condition_form.addRow("完整条件及参数：", conditions)
        root.addLayout(condition_form)

        metrics = QTableWidget(5, 4)
        metrics.setHorizontalHeaderLabels(("阶段", "数据期数", "触发次数", "准确率"))
        metrics.setEditTriggers(QTableWidget.NoEditTriggers)
        metrics.verticalHeader().setVisible(False)
        metrics.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        metric_rows = (
            ("TRAIN", summary.train_samples, summary.train_triggers, summary.train_accuracy),
            (
                "VALIDATION",
                summary.validation_samples,
                summary.validation_triggers,
                summary.validation_accuracy,
            ),
            ("TEST", summary.test_samples, summary.test_triggers, summary.test_accuracy),
            ("Walk-Forward", "—", "—", summary.walk_forward_accuracy),
            ("Forward", "—", summary.forward_samples, summary.forward_accuracy),
        )
        for row, values in enumerate(metric_rows):
            for column, value in enumerate(values):
                text = _rate(value) if column == 3 else str(value)
                metrics.setItem(row, column, QTableWidgetItem(text))
        root.addWidget(metrics)

        tabs = QTabWidget()
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        self.historical_table = _records_table(
            detail.historical_triggers, forward=False
        )
        history_layout.addWidget(self.historical_table)
        tabs.addTab(history_tab, f"历史触发 ({len(detail.historical_triggers)})")

        forward_tab = QWidget()
        forward_layout = QVBoxLayout(forward_tab)
        self.forward_table = _records_table(detail.forward_records, forward=True)
        forward_layout.addWidget(self.forward_table)
        tabs.addTab(forward_tab, f"Forward验证 ({len(detail.forward_records)})")

        walk_tab = QWidget()
        walk_layout = QVBoxLayout(walk_tab)
        walk_summary = QLabel(
            f"正式 Walk-Forward 汇总：{_rate(summary.walk_forward_accuracy)}"
        )
        walk_summary.setObjectName("SectionTitle")
        walk_layout.addWidget(walk_summary)
        if detail.walk_forward_windows:
            walk_table = QTableWidget(len(detail.walk_forward_windows), 6)
            walk_table.setHorizontalHeaderLabels(
                ("训练截止期", "测试开始期", "测试结束期", "触发", "命中", "未命中")
            )
            for row, window in enumerate(detail.walk_forward_windows):
                values = (
                    window.get("train_end_issue", ""),
                    window.get("test_start_issue", ""),
                    window.get("test_end_issue", ""),
                    window.get("triggers", 0),
                    window.get("hits", 0),
                    window.get("misses", 0),
                )
                for column, value in enumerate(values):
                    walk_table.setItem(row, column, QTableWidgetItem(str(value)))
            walk_layout.addWidget(walk_table)
        else:
            note = QLabel(
                "正式 StrategyResearchEngine 数据库只持久化 Walk-Forward 汇总，"
                "未持久化逐窗口明细；UI未重新计算或补造窗口结果。"
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            walk_layout.addWidget(note)
            walk_layout.addStretch()
        tabs.addTab(walk_tab, "Walk-Forward")
        root.addWidget(tabs, 1)


class StrategyResearchPage(QWidget):
    """Read-only view of official StrategyResearchEngine results."""

    HEADERS = (
        "策略ID",
        "状态",
        "完整条件",
        "触发次数",
        "TRAIN",
        "VALIDATION",
        "TEST",
        "Forward",
        "最近20",
        "最近50",
        "最近100",
        "最大连中",
        "最大连错",
        "平均触发间隔",
        "样本提示",
    )

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.loaded_strategies: tuple[StrategySummary, ...] = ()
        self.filtered_strategies: tuple[StrategySummary, ...] = ()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(11)
        title = QLabel("策略研究")
        title.setObjectName("PageTitle")
        hint = QLabel("StrategyResearchEngine 正式研究结果，只读展示")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        cards = QGridLayout()
        cards.setSpacing(9)
        specs = (
            ("engine", "Engine状态"),
            ("database", "DB状态"),
            ("updated", "最新研究时间"),
            ("periods", "正式生产期数"),
            ("candidates", "当前候选策略"),
            ("forward", "FORWARD_TEST"),
            ("verified", "VERIFIED"),
            ("freshness", "数据新鲜度"),
        )
        self.status_cards: dict[str, StatCard] = {}
        for index, (key, title_text) in enumerate(specs):
            card = StatCard(title_text, compact=True)
            self.status_cards[key] = card
            cards.addWidget(card, index // 4, index % 4)
        root.addLayout(cards)

        controls = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(("全部状态",) + LIFECYCLE_STATES)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索策略ID、预测器或完整条件")
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
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
        self.table.verticalHeader().setDefaultSectionSize(32)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        widths = (160, 115, 370, 82, 120, 120, 120, 110, 80, 80, 80, 80, 80, 110, 110)
        for column, width in enumerate(widths):
            header.resizeSection(column, width)
        root.addWidget(self.table, 1)

        self.status_filter.currentTextChanged.connect(self._apply_filters)
        self.search.textChanged.connect(self._apply_filters)
        self.table.cellDoubleClicked.connect(self._show_detail)

    def refresh(self) -> None:
        try:
            status = self.gateway.strategies.status()
            strategies = self.gateway.strategies.list_strategies(5000)
        except Exception as exc:
            self._show_error(
                f"StrategyResearchEngine 读取失败：{type(exc).__name__}: {exc}"
            )
            return
        self.loaded_strategies = tuple(strategies)
        freshness = status.get("freshness", {}).get("status", "OFFLINE")
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
            self.status_cards[key].set_value(value)
        problems = []
        if status.get("status") in {"OFFLINE", "STALE", "ERROR"}:
            problems.append(f"Engine {status.get('status')}")
        if status.get("database_status") != "ONLINE":
            problems.append(f"DB {status.get('database_status')}")
        if freshness != "FRESH":
            problems.append(f"数据新鲜度 {freshness}")
        if problems:
            self._show_error("；".join(problems))
        else:
            self.alert.clear()
            self.alert.setVisible(False)
        self._apply_filters()

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _apply_filters(self, *_args) -> None:
        lifecycle = self.status_filter.currentText()
        query = self.search.text().strip().lower()
        values = []
        for strategy in self.loaded_strategies:
            if lifecycle != "全部状态" and strategy.status != lifecycle:
                continue
            searchable = " ".join(
                (strategy.strategy_id, strategy.predictor, _conditions(strategy))
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
            conditions = _conditions(strategy)
            warning = "样本不足" if strategy.sample_warning else ""
            values = (
                (strategy.strategy_id, strategy.strategy_id),
                (strategy.status, strategy.status),
                (conditions, conditions),
                (str(strategy.trigger_count), strategy.trigger_count),
                (
                    _phase(
                        strategy.train_samples,
                        strategy.train_triggers,
                        strategy.train_accuracy,
                    ),
                    _sort_rate(strategy.train_accuracy),
                ),
                (
                    _phase(
                        strategy.validation_samples,
                        strategy.validation_triggers,
                        strategy.validation_accuracy,
                    ),
                    _sort_rate(strategy.validation_accuracy),
                ),
                (
                    _phase(
                        strategy.test_samples,
                        strategy.test_triggers,
                        strategy.test_accuracy,
                    ),
                    _sort_rate(strategy.test_accuracy),
                ),
                (
                    f"{strategy.forward_samples} · {_rate(strategy.forward_accuracy)}",
                    _sort_rate(strategy.forward_accuracy),
                ),
                (_rate(strategy.recent_20_accuracy), _sort_rate(strategy.recent_20_accuracy)),
                (_rate(strategy.recent_50_accuracy), _sort_rate(strategy.recent_50_accuracy)),
                (_rate(strategy.recent_100_accuracy), _sort_rate(strategy.recent_100_accuracy)),
                (str(strategy.max_consecutive_hits), strategy.max_consecutive_hits),
                (str(strategy.max_consecutive_misses), strategy.max_consecutive_misses),
                (_interval(strategy.average_trigger_interval), strategy.average_trigger_interval or -1),
                (warning, warning),
            )
            for column, (text, sort_value) in enumerate(values):
                item = SortableItem(text, sort_value)
                item.setData(Qt.UserRole, strategy.strategy_id)
                if column == 1:
                    item.setForeground(
                        QColor(STATUS_COLORS.get(strategy.status, "#667085"))
                    )
                if column == 2:
                    item.setToolTip(conditions)
                if column == 14 and warning:
                    item.setForeground(QColor("#C26A00"))
                    item.setToolTip(
                        "后台状态为 INSUFFICIENT_SAMPLE；不能视为推荐或高概率策略。"
                    )
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.count_label.setText(
            f"显示 {len(self.filtered_strategies)} / {len(self.loaded_strategies)} 条"
        )

    def _show_detail(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        strategy_id = str(item.data(Qt.UserRole))
        try:
            detail = self.gateway.strategies.get(strategy_id)
        except Exception as exc:
            self._show_error(
                f"策略详情读取失败：{type(exc).__name__}: {exc}"
            )
            return
        if detail is not None:
            StrategyDetailDialog(detail, self).exec()

    def visible_strategy_count(self) -> int:
        return self.table.rowCount()


def _records_table(records, *, forward: bool) -> QTableWidget:
    headers = (
        ("期号", "时间", "是否触发", "预测组合", "实际结果", "命中状态")
        if forward
        else ("期号", "数据集", "预测组合", "实际结果", "命中状态")
    )
    table = QTableWidget(len(records), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    for row, record in enumerate(records):
        triggered = int(record.get("triggered", 1) or 0) == 1
        hit = record.get("hit")
        if not triggered:
            outcome = "未触发"
        elif hit is None:
            outcome = "待结果"
        else:
            outcome = "命中" if bool(hit) else "未命中"
        predicted = _json_list(record.get("predicted_combinations"))
        values = (
            (
                record.get("issue", ""),
                _format_time(record.get("evaluated_at")),
                "是" if triggered else "否",
                predicted,
                record.get("actual_combination", ""),
                outcome,
            )
            if forward
            else (
                record.get("issue", ""),
                str(record.get("dataset_split", "")).upper(),
                predicted,
                record.get("actual_combination", ""),
                outcome,
            )
        )
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))
    return table


def _conditions(strategy: StrategySummary) -> str:
    return json.dumps(strategy.conditions, ensure_ascii=False, sort_keys=True)


def _json_list(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, list):
        return " / ".join(str(item) for item in value)
    return str(value or "")


def _rate(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _sort_rate(value) -> float:
    return -1.0 if value is None else float(value)


def _phase(samples: int, triggers: int, accuracy) -> str:
    return f"{triggers}/{samples} · {_rate(accuracy)}"


def _interval(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}期"


def _streak_text(summary: StrategySummary) -> str:
    labels = {"HIT": "连续命中", "MISS": "连续未命中", "NONE": "无"}
    label = labels.get(summary.current_streak_type, summary.current_streak_type)
    return label if summary.current_streak_count == 0 else f"{label} {summary.current_streak_count}"


def _format_time(value) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
