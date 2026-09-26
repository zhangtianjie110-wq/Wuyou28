from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from ..integration.models import Vip100Batch, Vip100Prediction
from .widgets import StatCard


COMBINATIONS = ("大单", "大双", "小单", "小双")


class AlgorithmDetailDialog(QDialog):
    def __init__(self, batch: Vip100Batch, prediction: Vip100Prediction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"VIP100 算法详情 · {prediction.algorithm_id}")
        self.resize(680, 440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        values = (
            ("算法ID", prediction.algorithm_id),
            ("完整公式", prediction.formula),
            ("当前预测", f"{prediction.prediction} · {prediction.combination}"),
            ("当前期结果", batch.actual_result or "待开奖"),
            ("当前期命中状态", _hit_text(prediction.hit)),
            ("引擎版本", batch.engine_version),
            ("Algorithm HASH", batch.algorithm_hash),
            ("Input HASH", batch.input_hash),
            ("生成时间", batch.generated_at),
        )
        for name, value in values:
            label = QLabel(str(value))
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
            form.addRow(f"{name}：", label)
        root.addLayout(form)
        root.addStretch()


class Vip100Page(QWidget):
    """Read-only native view over IntegrationGateway VIP100 production data."""

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.batch: Vip100Batch | None = None
        self.loaded_predictions: tuple[Vip100Prediction, ...] = ()
        self.filtered_predictions: tuple[Vip100Prediction, ...] = ()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("VIP100")
        title.setObjectName("PageTitle")
        hint = QLabel("VIP100_LOCAL_V2 正式预测，只读展示")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        status_grid = QGridLayout()
        status_grid.setSpacing(9)
        self.status_cards: dict[str, StatCard] = {}
        card_specs = (
            ("prediction_issue", "当前预测期号"),
            ("draw_issue", "开奖最新期号"),
            ("local_status", "LOCAL_V2"),
            ("algorithm_count", "算法状态"),
            ("hash_status", "算法哈希"),
            ("freshness", "数据新鲜度"),
            ("strategy_status", "策略研究引擎"),
        )
        for index, (key, caption) in enumerate(card_specs):
            card = StatCard(caption, compact=True)
            self.status_cards[key] = card
            status_grid.addWidget(card, index // 4, index % 4)
        root.addLayout(status_grid)

        filters = QHBoxLayout()
        self.issue_selector = QComboBox()
        self.issue_selector.setMinimumWidth(150)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索算法ID、名称或公式")
        self.combination_filter = QComboBox()
        self.combination_filter.addItems(("全部组合",) + COMBINATIONS)
        self.hit_filter = QComboBox()
        self.hit_filter.addItems(("全部状态", "命中", "未中", "待开奖"))
        filters.addWidget(QLabel("预测期号"))
        filters.addWidget(self.issue_selector)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.combination_filter)
        filters.addWidget(self.hit_filter)
        root.addLayout(filters)

        distribution = QFrame()
        distribution.setObjectName("Panel")
        distribution_layout = QHBoxLayout(distribution)
        distribution_layout.setContentsMargins(16, 12, 16, 12)
        self.distribution_labels: dict[str, QLabel] = {}
        for key in COMBINATIONS:
            label = QLabel(f"{key} 0 · 0.0%")
            self.distribution_labels[key] = label
            distribution_layout.addWidget(label)
        self.minimum_label = QLabel("最少组合 —")
        self.maximum_label = QLabel("最多组合 —")
        self.spread_label = QLabel("最大差值 0")
        distribution_layout.addSpacing(10)
        distribution_layout.addWidget(self.minimum_label)
        distribution_layout.addWidget(self.maximum_label)
        distribution_layout.addWidget(self.spread_label)
        distribution_layout.addStretch()
        root.addWidget(distribution)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("序号", "算法ID", "预测组合", "公式", "结果", "命中状态")
        )
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
        for column, width in enumerate((58, 190, 92, 430, 70)):
            header.resizeSection(column, width)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.issue_selector.currentTextChanged.connect(self._load_issue)
        self.search.textChanged.connect(self._apply_filters)
        self.combination_filter.currentTextChanged.connect(self._apply_filters)
        self.hit_filter.currentTextChanged.connect(self._apply_filters)
        self.table.cellDoubleClicked.connect(self._show_detail)

    def refresh(self) -> None:
        try:
            health = self.gateway.health()
            issues = self.gateway.vip100.list_issues()
        except Exception as exc:
            self._show_error(f"IntegrationGateway 读取失败：{type(exc).__name__}: {exc}")
            return

        selected = self.issue_selector.currentText()
        self.issue_selector.blockSignals(True)
        self.issue_selector.clear()
        self.issue_selector.addItems(issues)
        if selected in issues:
            self.issue_selector.setCurrentText(selected)
        self.issue_selector.blockSignals(False)

        self.status_cards["draw_issue"].set_value(health.get("DRAW_LATEST_ISSUE") or "—")
        self.status_cards["local_status"].set_value(health.get("VIP100_STATUS", "OFFLINE"))
        self.status_cards["algorithm_count"].set_value(
            f"{health.get('VIP100_PREDICTION_COUNT', 0)}/100"
        )
        self.status_cards["hash_status"].set_value(health.get("VIP100_HASH_STATUS", "OFFLINE"))
        self.status_cards["freshness"].set_value(health.get("DATA_FRESHNESS", "OFFLINE"))
        self.status_cards["strategy_status"].set_value(
            health.get("STRATEGY_ENGINE_STATUS", "OFFLINE")
        )
        self._set_health_alert(health)

        issue = self.issue_selector.currentText()
        if issue:
            self._load_issue(issue)
        else:
            self._clear_batch("没有可读取的 VIP100 正式预测")

    def _load_issue(self, issue: str) -> None:
        if not issue:
            return
        try:
            batch = self.gateway.vip100.get(issue)
        except Exception as exc:
            self._clear_batch(f"期号 {issue} 读取失败：{type(exc).__name__}: {exc}")
            return
        if batch is None:
            self._clear_batch(f"期号 {issue} 不存在")
            return
        self.batch = batch
        self.loaded_predictions = tuple(batch.predictions)
        self.status_cards["prediction_issue"].set_value(batch.issue)
        self._update_distribution(self.loaded_predictions)
        self._apply_filters()
        if batch.prediction_count != 100:
            self._show_error(f"预测数据不完整：{batch.prediction_count}/100")

    def _clear_batch(self, message: str) -> None:
        self.batch = None
        self.loaded_predictions = ()
        self.filtered_predictions = ()
        self.status_cards["prediction_issue"].set_value("—")
        self.table.setRowCount(0)
        self._update_distribution(())
        self._show_error(message)

    def _set_health_alert(self, health: dict) -> None:
        issues = []
        if health.get("VIP100_STATUS") in {"OFFLINE", "STALE", "ERROR"}:
            issues.append(f"LOCAL_V2 {health.get('VIP100_STATUS')}")
        count = health.get("VIP100_PREDICTION_COUNT", 0)
        if count != 100:
            issues.append(f"预测数量 {count}/100")
        if health.get("VIP100_HASH_STATUS") != "HASH_OK":
            issues.append(f"算法哈希 {health.get('VIP100_HASH_STATUS', 'OFFLINE')}")
        if health.get("DATA_FRESHNESS") != "FRESH":
            issues.append(f"数据新鲜度 {health.get('DATA_FRESHNESS', 'OFFLINE')}")
        if issues:
            self._show_error("；".join(issues))
        else:
            self.alert.clear()
            self.alert.setVisible(False)

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _apply_filters(self, *_args) -> None:
        query = self.search.text().strip().lower()
        combination = self.combination_filter.currentText()
        hit = self.hit_filter.currentText()
        rows = []
        for prediction in self.loaded_predictions:
            searchable = " ".join(
                (prediction.algorithm_id, prediction.algorithm_name, prediction.formula)
            ).lower()
            if query and query not in searchable:
                continue
            if combination != "全部组合" and prediction.combination != combination:
                continue
            if hit != "全部状态" and _hit_text(prediction.hit) != hit:
                continue
            rows.append(prediction)
        self.filtered_predictions = tuple(rows)
        self._render_table()

    def _render_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_predictions))
        for row_index, prediction in enumerate(self.filtered_predictions):
            values = (
                prediction.position,
                prediction.algorithm_id,
                prediction.combination,
                prediction.formula,
                prediction.prediction,
                _hit_text(prediction.hit),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                item.setData(Qt.UserRole, prediction.algorithm_id)
                if column == 5:
                    color = {"命中": "#16834B", "未中": "#B43B3B"}.get(str(value), "#8A6500")
                    item.setForeground(QColor(color))
                self.table.setItem(row_index, column, item)
        self.table.setSortingEnabled(True)

    def _update_distribution(self, predictions: tuple[Vip100Prediction, ...]) -> None:
        counts = Counter(row.combination for row in predictions)
        total = len(predictions)
        for combination in COMBINATIONS:
            count = counts.get(combination, 0)
            percentage = count * 100.0 / total if total else 0.0
            self.distribution_labels[combination].setText(
                f"{combination} {count} · {percentage:.1f}%"
            )
        if total:
            minimum = min(counts.get(key, 0) for key in COMBINATIONS)
            maximum = max(counts.get(key, 0) for key in COMBINATIONS)
            minimum_names = "/".join(key for key in COMBINATIONS if counts.get(key, 0) == minimum)
            maximum_names = "/".join(key for key in COMBINATIONS if counts.get(key, 0) == maximum)
            self.minimum_label.setText(f"最少组合 {minimum_names} {minimum}")
            self.maximum_label.setText(f"最多组合 {maximum_names} {maximum}")
            self.spread_label.setText(f"最大差值 {maximum - minimum}")
        else:
            self.minimum_label.setText("最少组合 —")
            self.maximum_label.setText("最多组合 —")
            self.spread_label.setText("最大差值 0")

    def _show_detail(self, row: int, _column: int) -> None:
        if self.batch is None:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        algorithm_id = str(item.data(Qt.UserRole))
        prediction = next(
            (candidate for candidate in self.loaded_predictions if candidate.algorithm_id == algorithm_id),
            None,
        )
        if prediction is not None:
            AlgorithmDetailDialog(self.batch, prediction, self).exec()

    def visible_prediction_count(self) -> int:
        return self.table.rowCount()

    def distribution_total(self) -> int:
        return len(self.loaded_predictions)


def _hit_text(hit: bool | None) -> str:
    if hit is True:
        return "命中"
    if hit is False:
        return "未中"
    return "待开奖"
