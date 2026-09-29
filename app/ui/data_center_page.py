from __future__ import annotations

import logging
import re
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    QThreadPool,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from .display_text import display_message, display_status
from .widgets import PageHeader, StatCard, polish_table, secondary_button


GOOD_STATES = {
    "HEALTHY",
    "ONLINE",
    "RUNNING",
    "HASH_OK",
    "DRAWN",
    "SETTLED",
    "INGESTED",
    "NO",
}
WAIT_STATES = {
    "STALE",
    "WARNING",
    "PENDING",
    "WAITING_DRAW",
}
BAD_STATES = {
    "ERROR",
    "OFFLINE",
    "HASH_MISMATCH",
    "MISSING_OUTCOME",
    "YES",
}
_ACTIVE_DATA_CENTER_TASKS = set()
logger = logging.getLogger(__name__)


class _DataCenterTaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _DataCenterSnapshotTask(QRunnable):
    def __init__(self, gateway: IntegrationGateway):
        super().__init__()
        self.setAutoDelete(False)
        self.gateway = gateway
        self.signals = _DataCenterTaskSignals(QCoreApplication.instance())

    def run(self) -> None:
        try:
            self.signals.finished.emit(self.gateway.data_center.snapshot())
        except Exception as exc:
            logger.exception("data center background snapshot failed")
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class DataCenterDetailDialog(QDialog):
    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"数据详情 · {record.get('issue', '—')}")
        self.resize(650, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        fields = (
            ("期号", record.get("issue", "—")),
            ("开奖状态", display_status(record.get("draw_status"))),
            ("VIP100数量", record.get("vip100_count", 0)),
            ("算法校验", display_status(record.get("hash_status"))),
            ("开奖结果状态", display_status(record.get("outcome_status"))),
            ("策略导入状态", display_status(record.get("strategy_ingest_status"))),
            ("数据时间", record.get("data_time", "—")),
            ("读取异常", record.get("error") or "无"),
        )
        for name, value in fields:
            label = QLabel(str(value))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(f"{name}：", label)
        layout.addLayout(form)
        layout.addStretch()


class DataHealthDetailDialog(QDialog):
    """Compact read-only health details shown independently of the main page."""

    def __init__(self, snapshot: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据健康详情")
        self.resize(560, 390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("数据健康详情")
        title.setObjectName("PageHeaderTitle")
        layout.addWidget(title)

        checks = list(snapshot.get("integrity", ()) or ())
        check_map = {str(item.get("name", "")): item for item in checks}
        rows = (
            ("开奖连续性", _find_check(check_map, "开奖期号连续性")),
            ("VIP100完整性", _find_check(check_map, "VIP100每期100条")),
            ("数据缺口", str(_data_gap_count(snapshot))),
            ("已开奖预测", str((snapshot.get("counts", {}) or {}).get("drawn_prediction_periods", 0))),
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(10)
        for row, (caption, value) in enumerate(rows):
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel(_detail_value(value))
            value_label.setWordWrap(True)
            value_label.setObjectName("StatNumber")
            grid.addWidget(caption_label, row, 0)
            grid.addWidget(value_label, row, 1)
        layout.addLayout(grid)

        service_title = QLabel("服务状态")
        service_title.setObjectName("SectionTitle")
        layout.addWidget(service_title)
        services = list(snapshot.get("services", ()) or ())
        service_grid = QGridLayout()
        service_grid.setHorizontalSpacing(16)
        service_grid.setVerticalSpacing(6)
        service_rows = (
            ("数据采集", _service_detail_status(services, "yu28", "producer", "采集")),
            ("分析引擎", _service_detail_status(services, "strategy", "engine", "分析")),
            ("VIP100", _service_detail_status(services, "vip100")),
        )
        for row, (caption, value) in enumerate(service_rows):
            service_grid.addWidget(QLabel(caption), row, 0)
            service_grid.addWidget(QLabel(value), row, 1)
        layout.addLayout(service_grid)
        layout.addStretch()

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)


class DataCenterPage(QWidget):
    """Read-only data health and runtime overview."""

    def __init__(
        self,
        gateway: IntegrationGateway | None = None,
        parent=None,
        startup_async: bool = False,
    ):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.snapshot_data: dict = {}
        self.recent_records: tuple[dict, ...] = ()
        self._defer_initial_refresh = bool(startup_async)
        self._background_task = None
        self._build_ui()
        if startup_async:
            self._set_loading_state()
            QTimer.singleShot(0, self._start_background_refresh)
        else:
            self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 24)
        root.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        heading = QHBoxLayout()
        self.page_header = PageHeader("数据中心", "正式数据健康、完整性与服务运行总览")
        heading.addWidget(self.page_header, 1)
        self.overall_status = self.page_header.status_label
        self.page_header.set_status("—")
        refresh_button = QPushButton("刷新")
        secondary_button(refresh_button)
        refresh_button.clicked.connect(self.refresh)
        heading.addWidget(refresh_button)
        check_button = QPushButton("检查数据")
        secondary_button(check_button)
        check_button.clicked.connect(self.refresh)
        heading.addWidget(check_button)
        root.addLayout(heading)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        status_grid = QHBoxLayout()
        status_grid.setSpacing(10)
        self.health_cards: dict[str, StatCard] = {}
        for key, caption in (("connection", "数据连接"), ("vip100", "VIP100"), ("engine", "分析引擎")):
            card = StatCard(caption, "加载中…", compact=True)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.health_cards[key] = card
            status_grid.addWidget(card, 1)
        root.addLayout(status_grid)

        key_panel = QFrame()
        key_panel.setObjectName("Panel")
        key_layout = QVBoxLayout(key_panel)
        key_layout.setContentsMargins(16, 13, 16, 13)
        key_title = QLabel("关键数据")
        key_title.setObjectName("SectionTitle")
        key_layout.addWidget(key_title)
        key_grid = QGridLayout()
        key_grid.setHorizontalSpacing(24)
        key_grid.setVerticalSpacing(5)
        self.key_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate((
            ("latest_issue", "最新开奖期号"),
            ("algorithms", "VIP100算法数量"),
            ("prediction_rows", "预测记录数量"),
            ("data_gap", "数据缺口"),
            ("completeness", "数据完整率"),
        )):
            metric = QFrame()
            metric.setObjectName("HomeMetric")
            metric_layout = QVBoxLayout(metric)
            metric_layout.setContentsMargins(10, 7, 10, 7)
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("加载中…")
            value_label.setObjectName("StatNumber")
            self.key_labels[key] = value_label
            metric_layout.addWidget(caption_label)
            metric_layout.addWidget(value_label)
            key_grid.addWidget(metric, index // 3, index % 3)
        key_layout.addLayout(key_grid)
        root.addWidget(key_panel)

        # Keep the full legacy status surface available to older callers and
        # the detailed view, but do not place it in the default user layout.
        self.status_cards: dict[str, StatCard] = {}
        status_specs = (
            ("draw_status", "YU28"),
            ("draw_latest_issue", "最新开奖期号"),
            ("vip100_status", "VIP100"),
            ("vip100_latest_issue", "最新预测期号"),
            ("vip100_prediction_count", "VIP100算法"),
            ("hash_status", "算法校验"),
            ("strategy_status", "策略研究引擎"),
            ("strategy_db_status", "策略数据库"),
            ("data_freshness", "数据新鲜度"),
        )
        for index, (key, caption) in enumerate(status_specs):
            card = StatCard(caption, compact=True)
            self.status_cards[key] = card
            card.setVisible(False)

        # Compatibility counters remain available to callers and are shown
        # only in the expandable detail section.
        count_specs = (
            ("draw_periods", "YU28开奖"),
            ("vip100_periods", "VIP100生产期"),
            ("vip100_prediction_rows", "正式预测"),
            ("drawn_prediction_periods", "已开奖预测期"),
            ("pending_prediction_periods", "待开奖预测期"),
            ("strategy_total", "策略总数"),
            ("RESEARCH_ONLY", "研究中"),
            ("CANDIDATE", "候选策略"),
            ("FORWARD_TEST", "前向验证"),
            ("VERIFIED", "已验证"),
            ("REJECTED", "已淘汰"),
            ("insufficient_samples", "样本不足"),
        )
        self.count_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(count_specs):
            value_label = QLabel("0")
            self.count_labels[key] = value_label
            value_label.setProperty("caption", caption)

        health_panel = QFrame()
        health_panel.setObjectName("Panel")
        health_layout = QVBoxLayout(health_panel)
        health_layout.setContentsMargins(16, 13, 16, 13)
        health_header = QHBoxLayout()
        health_title = QLabel("数据健康检查")
        health_title.setObjectName("SectionTitle")
        health_header.addWidget(health_title)
        health_header.addStretch()
        self.health_summary_labels = {
            "healthy": QLabel("正常项目 0"),
            "warning": QLabel("警告项目 0"),
        }
        for label in self.health_summary_labels.values():
            label.setObjectName("Muted")
            health_header.addWidget(label)
        self.details_toggle = QPushButton("查看详细检查")
        secondary_button(self.details_toggle)
        self.details_toggle.clicked.connect(self._toggle_details)
        health_header.addWidget(self.details_toggle)
        health_layout.addLayout(health_header)
        self.details_panel = QFrame()
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(0, 10, 0, 0)
        details_layout.setSpacing(12)

        diagnostics = QHBoxLayout()
        self.integrity_table = QTableWidget(0, 3)
        self.integrity_table.setHorizontalHeaderLabels(("完整性检查", "状态", "详情"))
        self.integrity_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.integrity_table.verticalHeader().setVisible(False)
        self.integrity_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.integrity_table.setMinimumHeight(205)
        self.integrity_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_table(self.integrity_table, 220)
        diagnostics.addWidget(self.integrity_table, 5)

        self.service_table = QTableWidget(0, 4)
        self.service_table.setHorizontalHeaderLabels(("服务", "状态", "进程号", "状态时间/来源"))
        self.service_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.service_table.verticalHeader().setVisible(False)
        self.service_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.service_table.setMinimumHeight(205)
        self.service_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_table(self.service_table, 230)
        diagnostics.addWidget(self.service_table, 5)
        details_layout.addLayout(diagnostics)

        volumes = QFrame()
        volumes.setObjectName("Panel")
        volume_layout = QGridLayout(volumes)
        volume_layout.setContentsMargins(15, 10, 15, 10)
        for index, (key, caption) in enumerate(count_specs):
            column = index % 6
            row = (index // 6) * 2
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            volume_layout.addWidget(caption_label, row, column)
            volume_layout.addWidget(self.count_labels[key], row + 1, column)
        details_layout.addWidget(volumes)

        recent_title = QLabel("最近运行记录")
        recent_title.setObjectName("SectionTitle")
        self.recent_table = QTableWidget(0, 7)
        self.recent_table.setHorizontalHeaderLabels(
            (
                "期号",
                "开奖状态",
                "VIP100数量",
                "算法校验",
                "开奖结果状态",
                "策略导入状态",
                "数据时间",
            )
        )
        self.recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SingleSelection)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_table.setWordWrap(False)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.Stretch
        )
        self.recent_table.cellDoubleClicked.connect(self._show_detail)
        polish_table(self.recent_table, 240)
        details_layout.addWidget(recent_title)
        details_layout.addWidget(self.recent_table, 1)
        # The compatibility tables stay detached from the main layout. The
        # user-facing detail view is opened in DataHealthDetailDialog.
        self.details_panel.setVisible(False)
        root.addWidget(health_panel)

        services_panel = QFrame()
        services_panel.setObjectName("Panel")
        services_layout = QVBoxLayout(services_panel)
        services_layout.setContentsMargins(16, 13, 16, 13)
        services_title = QLabel("后台服务")
        services_title.setObjectName("SectionTitle")
        services_layout.addWidget(services_title)
        services_grid = QHBoxLayout()
        services_grid.setSpacing(10)
        self.service_summary_labels: dict[str, QLabel] = {}
        for key, caption in (("engine", "分析引擎"), ("vip100", "VIP100")):
            card = StatCard(caption, "加载中…", compact=True)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.service_summary_labels[key] = card.value_label
            services_grid.addWidget(card, 1)
        services_layout.addLayout(services_grid)
        root.addWidget(services_panel)

    def _toggle_details(self) -> None:
        dialog = DataHealthDetailDialog(self.snapshot_data or {}, self)
        dialog.exec()

    def _set_loading_state(self) -> None:
        self.page_header.set_status("加载中")
        for card in self.health_cards.values():
            card.set_value("加载中…")
        for card in self.status_cards.values():
            card.set_value("加载中…")
        for label in self.key_labels.values():
            label.setText("加载中…")
        self.health_summary_labels["healthy"].setText("正常项目 —")
        self.health_summary_labels["warning"].setText("警告项目 —")
        for label in self.service_summary_labels.values():
            label.setText("加载中…")
        self.alert.setText("正在后台读取数据中心快照…")
        self.alert.setVisible(True)

    def _start_background_refresh(self) -> None:
        if self._background_task is not None:
            return
        task = _DataCenterSnapshotTask(self.gateway)
        self._background_task = task
        _ACTIVE_DATA_CENTER_TASKS.add(task)
        task.signals.finished.connect(self._on_background_refresh_finished)
        task.signals.failed.connect(self._on_background_refresh_failed)
        task.signals.finished.connect(
            lambda _value, item=task: _ACTIVE_DATA_CENTER_TASKS.discard(item)
        )
        task.signals.failed.connect(
            lambda _value, item=task: _ACTIVE_DATA_CENTER_TASKS.discard(item)
        )
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _on_background_refresh_finished(self, snapshot: dict) -> None:
        self._defer_initial_refresh = False
        self._render_snapshot(snapshot)

    @Slot(str)
    def _on_background_refresh_failed(self, message: str) -> None:
        self._defer_initial_refresh = False
        self._show_error(f"数据中心读取失败：{message}")

    def refresh(self) -> None:
        try:
            snapshot = self.gateway.data_center.snapshot()
        except Exception as exc:
            self._show_error(f"数据中心读取失败：{type(exc).__name__}: {exc}")
            return
        self._defer_initial_refresh = False
        self._render_snapshot(snapshot)

    def _render_snapshot(self, snapshot: dict) -> None:
        self.snapshot_data = snapshot
        self.recent_records = tuple(snapshot.get("recent", ()))
        top = snapshot.get("top", {})
        status_keys = {
            "draw_status",
            "vip100_status",
            "hash_status",
            "strategy_status",
            "strategy_db_status",
            "data_freshness",
        }
        for key, card in self.status_cards.items():
            value = top.get(key, "—")
            if key == "vip100_prediction_count":
                value = f"{value}/100"
            card.set_value(display_status(value) if key in status_keys else value)
            _style_status(card.value_label, str(value))
        connection = top.get("draw_status", "—")
        vip_count = top.get("vip100_prediction_count", 0)
        engine = top.get("strategy_status", "—")
        self.health_cards["connection"].set_value(display_status(connection))
        self.health_cards["vip100"].set_value(f"{vip_count}/100")
        self.health_cards["engine"].set_value(display_status(engine))
        _style_status(self.health_cards["connection"].value_label, str(connection))
        _style_status(self.health_cards["vip100"].value_label, f"{vip_count}/100")
        _style_status(self.health_cards["engine"].value_label, str(engine))
        counts = snapshot.get("counts", {})
        self.key_labels["latest_issue"].setText(str(top.get("draw_latest_issue") or "—"))
        self.key_labels["algorithms"].setText(f"{vip_count}/100")
        self.key_labels["prediction_rows"].setText(str(counts.get("vip100_prediction_rows", 0)))
        self.key_labels["data_gap"].setText(str(_data_gap_count(snapshot)))
        self.key_labels["completeness"].setText(_data_completeness(snapshot))
        for key, label in self.count_labels.items():
            label.setText(str(counts.get(key, 0)))

        overall = str(snapshot.get("overall_status", "ERROR"))
        self.overall_status.setText(display_status(overall))
        _style_status(self.overall_status, overall)
        errors = list(snapshot.get("errors", ()))
        if errors:
            self._show_error("；".join(display_message(error) for error in errors))
        else:
            self.alert.clear()
            self.alert.setVisible(False)
        self._render_integrity(snapshot.get("integrity", ()))
        self._render_services(snapshot.get("services", ()))
        self._render_recent(self.recent_records)
        checks = list(snapshot.get("integrity", ()) or ())
        healthy_count = sum(1 for check in checks if str(check.get("status", "")) == "HEALTHY")
        self.health_summary_labels["healthy"].setText(f"正常项目 {healthy_count}")
        self.health_summary_labels["warning"].setText(f"警告项目 {max(0, len(checks) - healthy_count)}")

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _render_integrity(self, checks) -> None:
        self.integrity_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            raw_status = check.get("status", "")
            values = (
                display_message(check.get("name", ""), ""),
                display_status(raw_status, ""),
                display_message(check.get("detail", ""), ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setForeground(QColor(_status_color(str(raw_status))))
                self.integrity_table.setItem(row, column, item)
        self.integrity_table.resizeColumnToContents(0)
        self.integrity_table.resizeColumnToContents(1)

    def _render_services(self, services) -> None:
        services = list(services or ())
        def service_status(*needles: str) -> str:
            for service in services:
                name = str(service.get("name", "")).lower()
                if any(needle.lower() in name for needle in needles):
                    return display_status(service.get("status", "—"), "")
            return "—"

        self.service_summary_labels["engine"].setText(service_status("strategy", "engine", "分析"))
        self.service_summary_labels["vip100"].setText(service_status("vip100"))
        self.service_table.setRowCount(len(services))
        for row, service in enumerate(services):
            raw_status = service.get("status", "")
            detail = service.get("updated_at") or service.get("source") or "—"
            if service.get("error"):
                detail = f"{detail} · {service['error']}"
            values = (
                display_message(service.get("name", ""), ""),
                display_status(raw_status, ""),
                service.get("pid") or "—",
                display_message(detail),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setForeground(QColor(_status_color(str(raw_status))))
                if column == 3:
                    item.setToolTip(str(service.get("source") or ""))
                self.service_table.setItem(row, column, item)
        self.service_table.resizeColumnToContents(0)
        self.service_table.resizeColumnToContents(1)

    def _render_recent(self, records) -> None:
        self.recent_table.setRowCount(len(records))
        for row, record in enumerate(records):
            raw_statuses = (
                record.get("draw_status", ""),
                record.get("hash_status", ""),
                record.get("outcome_status", ""),
                record.get("strategy_ingest_status", ""),
            )
            values = (
                record.get("issue", ""),
                display_status(raw_statuses[0], ""),
                record.get("vip100_count", 0),
                display_status(raw_statuses[1], ""),
                display_status(raw_statuses[2], ""),
                display_status(raw_statuses[3], ""),
                record.get("data_time", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, str(record.get("issue", "")))
                if column in (1, 3, 4, 5):
                    raw_index = {1: 0, 3: 1, 4: 2, 5: 3}[column]
                    item.setForeground(QColor(_status_color(str(raw_statuses[raw_index]))))
                self.recent_table.setItem(row, column, item)
        for column in range(6):
            self.recent_table.resizeColumnToContents(column)

    def _show_detail(self, row: int, _column: int) -> None:
        item = self.recent_table.item(row, 0)
        if item is None:
            return
        issue = str(item.data(Qt.UserRole))
        record = next(
            (value for value in self.recent_records if str(value.get("issue")) == issue),
            None,
        )
        if record is not None:
            DataCenterDetailDialog(record, self).exec()

    def visible_recent_count(self) -> int:
        return self.recent_table.rowCount()


def _find_check(checks: dict[str, dict], name: str) -> str:
    check = checks.get(name)
    if not check:
        return "未提供"
    status = display_status(check.get("status", "—"), "")
    detail = display_message(check.get("detail", ""), "")
    return f"{status} · {detail}" if detail else status


def _detail_value(value: object) -> str:
    return str(value or "—")


def _service_detail_status(services: list[dict], *needles: str) -> str:
    for service in services:
        name = str(service.get("name", "")).lower()
        if any(needle.lower() in name for needle in needles):
            return display_status(service.get("status", "—"), "")
    return "—"


def _status_color(status: str) -> str:
    if status in GOOD_STATES or status.startswith("100/"):
        return "#16834B"
    if status in WAIT_STATES:
        return "#C26A00"
    if status in BAD_STATES:
        return "#B43B3B"
    return "#667085"


def _data_gap_count(snapshot: dict) -> int:
    """Extract user-facing data gaps from the existing integrity results."""
    total = 0
    for check in snapshot.get("integrity", ()) or ():
        if str(check.get("status", "")) == "HEALTHY":
            continue
        name = str(check.get("name", ""))
        if not any(token in name for token in ("缺失", "未回填", "连续性", "每期100条")):
            continue
        detail = str(check.get("detail", ""))
        match = re.search(r"(?:缺失|未回填|异常|重复)\s*(\d+)", detail)
        total += int(match.group(1)) if match else 1
    return total


def _data_completeness(snapshot: dict) -> str:
    """Format a lightweight completeness indicator from the loaded snapshot."""
    counts = snapshot.get("counts", {}) or {}
    total = int(counts.get("draw_periods", 0) or 0)
    if total <= 0:
        return "—"
    gaps = _data_gap_count(snapshot)
    ratio = max(0.0, min(100.0, (1.0 - gaps / total) * 100.0))
    return f"{ratio:.1f}%"


def _style_status(label: QLabel, status: str) -> None:
    label.setStyleSheet(f"color: {_status_color(status)}; font-weight: 600;")
