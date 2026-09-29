from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from ..integration.models import Vip100Batch, Vip100Prediction
from .display_text import display_status
from .widgets import PageHeader, StatCard, table_number_style


COMBINATIONS = ("大单", "大双", "小单", "小双")


class DownwardComboBox(QComboBox):
    """Keep the issue list anchored below its field for a stable layout."""

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        QTimer.singleShot(0, lambda: self._place_popup(popup))

    def _place_popup(self, popup) -> None:
        if popup is not None and popup.isVisible():
            # Keep the issue popup below the field and bounded to a compact
            # viewport.  QComboBox's view supplies the internal scrollbar.
            self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.view().setMaximumHeight(520)
            popup.setMaximumHeight(520)
            popup.move(self.mapToGlobal(QPoint(0, self.height())))


class AlgorithmDetailDialog(QDialog):
    def __init__(self, batch: Vip100Batch, prediction: Vip100Prediction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"VIP100 算法详情 · {prediction.algorithm_id}")
        self.resize(680, 440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        values = (
            ("算法编号", prediction.position),
            ("算法标识", prediction.algorithm_id),
            ("完整公式", prediction.formula),
            ("原始预测组合", f"{prediction.prediction} · {prediction.combination}"),
            ("生成时间", batch.generated_at),
            (
                "最近30期",
                _prediction_metric(
                    prediction,
                    "recent_30",
                    "recent30",
                    "recent_30_rate",
                    "recent_30_accuracy",
                ),
            ),
            (
                "最近100期",
                _prediction_metric(
                    prediction,
                    "recent_100",
                    "recent100",
                    "recent_100_rate",
                    "recent_100_accuracy",
                ),
            ),
            ("最大连中", _prediction_metric(prediction, "max_hit_streak", "max_win_streak")),
            ("最大连错", _prediction_metric(prediction, "max_miss_streak", "max_loss_streak")),
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
        root.setContentsMargins(24, 18, 24, 24)
        root.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.page_header = PageHeader("VIP100", "100条算法预测与组合统计")
        self.hint = self.page_header.subtitle_label
        root.addWidget(self.page_header)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        status_grid = QHBoxLayout()
        status_grid.setSpacing(12)
        self.top_status_cards: dict[str, StatCard] = {}
        for key, caption in (("status", "VIP100状态"), ("issue", "当前期号"), ("count", "算法数量"), ("data", "数据状态")):
            card = StatCard(caption, "加载中…", compact=True)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.top_status_cards[key] = card
            status_grid.addWidget(card, 1)
        root.addLayout(status_grid)

        overview_grid = QHBoxLayout()
        overview_grid.setSpacing(12)
        self.overview_cards: dict[str, StatCard] = {}
        for key, caption in (
            ("total", "算法总数"),
            ("recent", "历史表现"),
            ("streak", "连续状态"),
            ("stable", "稳定算法数量"),
        ):
            card = StatCard(caption, "—", compact=True)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.overview_cards[key] = card
            overview_grid.addWidget(card, 1)
        root.addLayout(overview_grid)

        # Keep the previous status surface for compatibility callers, but do
        # not expose technical fields such as HASH in the primary layout.
        self.status_cards: dict[str, StatCard] = {}
        card_specs = (
            ("prediction_issue", "当前预测期号"),
            ("draw_issue", "开奖最新期号"),
            ("local_status", "本地V2"),
            ("algorithm_count", "算法状态"),
            ("hash_status", "算法校验"),
            ("freshness", "数据新鲜度"),
            ("strategy_status", "策略研究引擎"),
        )
        for index, (key, caption) in enumerate(card_specs):
            card = StatCard(caption, compact=True)
            self.status_cards[key] = card
            card.setVisible(False)

        filters = QHBoxLayout()
        self.source_selector = QComboBox()
        self.source_selector.addItem("正式前向", "FORWARD")
        self.source_selector.addItem("历史重建", "RECONSTRUCTED")
        self.issue_selector = DownwardComboBox()
        self.issue_selector.setMinimumWidth(150)
        self.issue_selector.setMaxVisibleItems(20)
        self.issue_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.issue_selector.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.issue_selector.view().setMaximumHeight(520)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索算法标识、名称或公式")
        self.combination_filter = QComboBox()
        self.combination_filter.addItems(("全部组合",) + COMBINATIONS)
        self.hit_filter = QComboBox()
        self.hit_filter.addItems(("全部状态", "命中", "未中", "待开奖"))
        self.sort_selector = QComboBox()
        self.sort_selector.addItems(
            ("综合表现", "最高表现", "最近30期表现", "最近100期表现", "当前连中", "当前连错", "编号顺序")
        )
        self.current_hit_streak_filter = QComboBox()
        self.current_hit_streak_filter.addItems(("全部", "连中1+", "连中2+", "连中3+"))
        self.current_miss_streak_filter = QComboBox()
        self.current_miss_streak_filter.addItems(("全部", "连错1+", "连错2+", "连错3+"))
        filters.addWidget(QLabel("预测期号"))
        filters.addWidget(self.issue_selector)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.combination_filter)
        filters.addWidget(self.hit_filter)
        filters.addWidget(QLabel("排序"))
        filters.addWidget(self.sort_selector)
        filters.addWidget(QLabel("当前连中"))
        filters.addWidget(self.current_hit_streak_filter)
        filters.addWidget(QLabel("当前连错"))
        filters.addWidget(self.current_miss_streak_filter)
        filter_panel = QFrame()
        filter_panel.setObjectName("Panel")
        filter_layout = QVBoxLayout(filter_panel)
        filter_layout.setContentsMargins(14, 10, 14, 10)
        filter_title = QLabel("筛选预测")
        filter_title.setObjectName("CardTitle")
        filter_layout.addWidget(filter_title)
        filter_layout.addLayout(filters)
        root.addWidget(filter_panel)
        self.source_selector.setVisible(False)

        self.source_info = QLabel("数据类型：正式前向")
        self.source_info.setObjectName("Muted")
        self.advanced_panel = QFrame()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(12, 8, 12, 8)
        advanced_layout.addWidget(self.source_info)
        self.advanced_panel.setVisible(False)
        self.advanced_toggle = QCheckBox("显示高级技术信息")
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        self.advanced_toggle.setVisible(False)
        root.addWidget(self.advanced_toggle)
        root.addWidget(self.advanced_panel)

        distribution = QFrame()
        self.distribution_panel = distribution
        distribution.setObjectName("Panel")
        distribution_layout = QVBoxLayout(distribution)
        distribution_layout.setContentsMargins(14, 12, 14, 12)
        distribution_title = QLabel("四组合统计")
        distribution_title.setObjectName("SectionTitle")
        distribution_layout.addWidget(distribution_title)
        distribution_grid = QGridLayout()
        distribution_grid.setHorizontalSpacing(8)
        distribution_grid.setVerticalSpacing(8)
        self.distribution_labels: dict[str, QLabel] = {}
        self.distribution_cards: dict[str, QFrame] = {}
        for index, key in enumerate(COMBINATIONS):
            card = QFrame()
            card.setObjectName("HomeMetric")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 7, 10, 7)
            caption = QLabel(key)
            caption.setObjectName("Muted")
            label = QLabel("0 · 0.0%")
            label.setObjectName("StatNumber")
            card_layout.addWidget(caption)
            card_layout.addWidget(label)
            self.distribution_cards[key] = card
            self.distribution_labels[key] = label
            distribution_grid.addWidget(card, index // 4, index % 4)
        distribution_layout.addLayout(distribution_grid)
        distribution_meta = QHBoxLayout()
        self.minimum_label = QLabel("最少组合 —")
        self.maximum_label = QLabel("最多组合 —")
        self.spread_label = QLabel("最大差值 0")
        distribution_meta.addWidget(self.minimum_label)
        distribution_meta.addWidget(self.maximum_label)
        distribution_meta.addWidget(self.spread_label)
        distribution_meta.addStretch()
        distribution_layout.addLayout(distribution_meta)
        root.addWidget(distribution)
        distribution.setVisible(False)

        table_header = QHBoxLayout()
        table_title = QLabel("算法列表")
        table_title.setObjectName("SectionTitle")
        table_header.addWidget(table_title)
        table_header.addStretch()
        self.detail_button = QPushButton("查看算法详情")
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self._show_selected_detail)
        table_header.addWidget(self.detail_button)
        root.addLayout(table_header)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ("编号", "预测组合", "预测结果", "最近30期", "最近100期", "当前连中", "当前连错", "状态")
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        # Sorting is controlled by the explicit selector above.  Keeping the
        # table's built-in sorter disabled preserves the prediction-position
        # to row correspondence and avoids an implicit initial reverse sort.
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table_number_style(self.table)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setFixedHeight(480)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
        for column, width in enumerate((70, 130, 100, 92, 92, 82, 82, 86)):
            header.resizeSection(column, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table)

        self.source_selector.currentIndexChanged.connect(self.refresh)
        self.issue_selector.currentTextChanged.connect(self._load_issue)
        self.search.textChanged.connect(self._apply_filters)
        self.combination_filter.currentTextChanged.connect(self._apply_filters)
        self.hit_filter.currentTextChanged.connect(self._apply_filters)
        self.sort_selector.currentTextChanged.connect(self._apply_filters)
        self.current_hit_streak_filter.currentTextChanged.connect(self._apply_filters)
        self.current_miss_streak_filter.currentTextChanged.connect(self._apply_filters)
        self.table.cellDoubleClicked.connect(self._show_detail)
        self.table.itemSelectionChanged.connect(
            lambda: self.detail_button.setEnabled(self.table.currentRow() >= 0)
        )

    def refresh(self) -> None:
        try:
            health = self.gateway.health()
            source = str(self.source_selector.currentData() or "FORWARD")
            if hasattr(self.gateway, "vip100_issues"):
                # Keep the selector to a practical recent history window; the
                # selected batch remains loaded through the existing gateway.
                issues = self.gateway.vip100_issues(source, 100)
            else:
                repository = self.gateway.vip100
                issues = repository.list_issues(100)
        except Exception as exc:
            self._show_error(f"数据读取层读取失败：{type(exc).__name__}: {exc}")
            return

        selected = self.issue_selector.currentText()
        self.issue_selector.blockSignals(True)
        self.issue_selector.clear()
        self.issue_selector.addItems(issues)
        if selected in issues:
            self.issue_selector.setCurrentText(selected)
        self.issue_selector.blockSignals(False)

        self.status_cards["draw_issue"].set_value(health.get("DRAW_LATEST_ISSUE") or "—")
        self.status_cards["local_status"].set_value(
            display_status(health.get("VIP100_STATUS", "OFFLINE"))
        )
        self.status_cards["algorithm_count"].set_value(
            f"{health.get('VIP100_PREDICTION_COUNT', 0)}/100"
        )
        self.status_cards["hash_status"].set_value(
            display_status(health.get("VIP100_HASH_STATUS", "OFFLINE"))
        )
        self.status_cards["freshness"].set_value(
            display_status(health.get("DATA_FRESHNESS", "OFFLINE"))
        )
        self.status_cards["strategy_status"].set_value(
            display_status(health.get("STRATEGY_ENGINE_STATUS", "OFFLINE"))
        )
        self.top_status_cards["status"].set_value(
            display_status(health.get("VIP100_STATUS", "OFFLINE"))
        )
        self.top_status_cards["issue"].set_value(
            health.get("VIP100_LATEST_ISSUE") or "—"
        )
        self.top_status_cards["count"].set_value(
            f"{health.get('VIP100_PREDICTION_COUNT', 0)}/100"
        )
        self.top_status_cards["data"].set_value(
            display_status(health.get("DATA_FRESHNESS", "OFFLINE"))
        )
        _style_status(
            self.top_status_cards["status"].value_label,
            str(health.get("VIP100_STATUS", "OFFLINE")),
        )
        _style_status(
            self.top_status_cards["count"].value_label,
            f"{health.get('VIP100_PREDICTION_COUNT', 0)}/100",
        )
        _style_status(
            self.top_status_cards["data"].value_label,
            str(health.get("DATA_FRESHNESS", "OFFLINE")),
        )
        self._set_health_alert(health)

        issue = self.issue_selector.currentText()
        if issue:
            self._load_issue(issue)
        else:
            source_name = display_status(self.source_selector.currentData())
            self._clear_batch(f"没有可读取的 VIP100 {source_name}数据")

    def _load_issue(self, issue: str) -> None:
        if not issue:
            return
        try:
            source = str(self.source_selector.currentData() or "FORWARD")
            if hasattr(self.gateway, "vip100_batch"):
                batch = self.gateway.vip100_batch(source, issue)
            else:
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
        self.top_status_cards["issue"].set_value(batch.issue)
        source_name = display_status(batch.source)
        self.hint.setText(f"VIP100 {source_name}数据，只读展示")
        input_range = (
            ""
            if not batch.input_start_issue
            else f" · 输入期号 {batch.input_start_issue} 至 {batch.input_end_issue}"
        )
        self.source_info.setText(
            f"数据类型：{source_name} · 算法数量 {batch.prediction_count}"
            f" · 生成时间 {batch.generated_at}{input_range}"
        )
        self._update_overview(batch, self.loaded_predictions)
        self._update_distribution(self.loaded_predictions)
        self._apply_filters()
        if batch.prediction_count != 100:
            self._show_error(f"预测数据不完整：{batch.prediction_count}/100")

    def _clear_batch(self, message: str) -> None:
        self.batch = None
        self.loaded_predictions = ()
        self.filtered_predictions = ()
        self.status_cards["prediction_issue"].set_value("—")
        self.top_status_cards["issue"].set_value("—")
        self._update_overview(None, ())
        self.table.setRowCount(0)
        self.detail_button.setEnabled(False)
        self._update_distribution(())
        self._show_error(message)

    def _set_health_alert(self, health: dict) -> None:
        issues = []
        if health.get("VIP100_STATUS") in {"OFFLINE", "STALE", "ERROR"}:
            issues.append(f"本地V2 {display_status(health.get('VIP100_STATUS'))}")
        count = health.get("VIP100_PREDICTION_COUNT", 0)
        if count != 100:
            issues.append(f"预测数量 {count}/100")
        if health.get("DATA_FRESHNESS") != "FRESH":
            issues.append(
                f"数据新鲜度 {display_status(health.get('DATA_FRESHNESS', 'OFFLINE'))}"
            )
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
        hit_streak_filter = self.current_hit_streak_filter.currentText()
        miss_streak_filter = self.current_miss_streak_filter.currentText()
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
            if not _matches_streak_filter(
                prediction,
                hit_streak_filter,
                ("current_hit_streak", "current_win_streak", "hit_streak"),
            ):
                continue
            if not _matches_streak_filter(
                prediction,
                miss_streak_filter,
                ("current_miss_streak", "current_loss_streak", "miss_streak"),
            ):
                continue
            rows.append(prediction)
        self.filtered_predictions = tuple(self._sort_predictions(rows))
        self._render_table()

    def _sort_predictions(self, rows: list[Vip100Prediction]) -> list[Vip100Prediction]:
        option = self.sort_selector.currentText()
        if option == "编号顺序" or option == "综合表现":
            return sorted(rows, key=lambda prediction: prediction.position)
        if option == "最高表现":
            return sorted(
                rows,
                key=lambda prediction: (
                    _metric_number(prediction, "recent_100", "recent100", "recent_100_rate", "recent_100_accuracy") is not None,
                    _metric_number(prediction, "recent_100", "recent100", "recent_100_rate", "recent_100_accuracy") or 0.0,
                    _metric_number(prediction, "recent_30", "recent30", "recent_30_rate", "recent_30_accuracy") or 0.0,
                    -prediction.position,
                ),
                reverse=True,
            )
        metric_names = {
            "最近30期表现": (
                "recent_30",
                "recent30",
                "recent_30_rate",
                "recent_30_accuracy",
            ),
            "最近100期表现": (
                "recent_100",
                "recent100",
                "recent_100_rate",
                "recent_100_accuracy",
            ),
            "当前连中": ("current_hit_streak", "current_win_streak", "hit_streak"),
            "当前连错": ("current_miss_streak", "current_loss_streak", "miss_streak"),
        }.get(option)
        if metric_names is None:
            return list(rows)
        return sorted(
            rows,
            key=lambda prediction: (
                _metric_number(prediction, *metric_names) is not None,
                _metric_number(prediction, *metric_names) or 0.0,
                -prediction.position,
            ),
            reverse=True,
        )

    def _render_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_predictions))
        for row_index, prediction in enumerate(self.filtered_predictions):
            values = (
                prediction.position,
                prediction.combination,
                prediction.prediction,
                _prediction_metric(prediction, "recent_30", "recent30", "recent_30_rate", "recent_30_accuracy"),
                _prediction_metric(prediction, "recent_100", "recent100", "recent_100_rate", "recent_100_accuracy"),
                _prediction_metric(prediction, "current_hit_streak", "current_win_streak", "hit_streak"),
                _prediction_metric(prediction, "current_miss_streak", "current_loss_streak", "miss_streak"),
                _hit_text(prediction.hit),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                item.setData(Qt.UserRole, prediction.algorithm_id)
                item.setTextAlignment(Qt.AlignCenter)
                if column == 7:
                    color = {"命中": "#16834B", "未中": "#B43B3B"}.get(str(value), "#8A6500")
                    item.setForeground(QColor(color))
                self.table.setItem(row_index, column, item)
        # Sorting is controlled by the explicit selector above.  Keeping the
        # table's built-in sorter disabled preserves prediction-position order.
        self.table.setSortingEnabled(False)

    def _update_overview(
        self,
        batch: Vip100Batch | None,
        predictions: tuple[Vip100Prediction, ...],
    ) -> None:
        self.overview_cards["total"].set_value(
            str(getattr(batch, "prediction_count", len(predictions)))
            if batch is not None
            else "—"
        )
        recent = _first_metric(
            batch,
            "recent_performance",
            "recent_30",
            "recent30",
            "recent_30_rate",
            "recent_30_accuracy",
        )
        self.overview_cards["recent"].set_value(recent or "—")
        max_hit = _first_metric(batch, "max_hit_streak", "max_win_streak")
        max_miss = _first_metric(batch, "max_miss_streak", "max_loss_streak")
        if max_hit or max_miss:
            self.overview_cards["streak"].set_value(
                f"连中 {max_hit or '—'} · 连错 {max_miss or '—'}"
            )
        else:
            self.overview_cards["streak"].set_value("—")
        stable = _first_metric(batch, "stable_algorithm_count", "stable_count")
        self.overview_cards["stable"].set_value(stable or "—")

    def _show_selected_detail(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._show_detail(row, 0)

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


def _first_metric(source: object | None, *names: str) -> str | None:
    """Read an already-persisted metric without deriving history in the UI."""
    if source is None:
        return None
    for name in names:
        value = getattr(source, name, None)
        if value is not None and value != "":
            return _format_metric(value)
    return None


def _prediction_metric(prediction: object, *names: str) -> str:
    value = _first_metric(prediction, *names)
    return value if value is not None else "—"


def _metric_number(prediction: object, *names: str) -> float | None:
    for name in names:
        value = getattr(prediction, name, None)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _format_metric(value: object) -> str:
    if isinstance(value, float):
        return f"{value * 100:.1f}%" if 0 <= value <= 1 else f"{value:.1f}"
    return str(value)


def _matches_streak_filter(
    prediction: object,
    selection: str,
    names: tuple[str, ...],
) -> bool:
    if selection == "全部":
        return True
    try:
        threshold = int(selection[-2])
    except (TypeError, ValueError):
        return True
    value = _metric_number(prediction, *names)
    return value is not None and value >= threshold


def _hit_text(hit: bool | None) -> str:
    if hit is True:
        return "命中"
    if hit is False:
        return "未中"
    return "待开奖"


def _status_color(status: str) -> str:
    if status in {"ONLINE", "RUNNING", "FRESH", "HEALTHY", "HASH_OK"} or status.startswith("100/"):
        return "#16834B"
    if status in {"STALE", "PENDING", "WARNING", "WAITING_DRAW"}:
        return "#C26A00"
    if status in {"ERROR", "OFFLINE", "HASH_MISMATCH"}:
        return "#B43B3B"
    return "#667085"


def _style_status(label: QLabel, status: str) -> None:
    label.setStyleSheet(f"color: {_status_color(status)}; font-weight: 600;")
