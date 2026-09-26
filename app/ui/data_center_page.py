from __future__ import annotations

from PySide6.QtCore import Qt
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..integration import IntegrationGateway
from .widgets import StatCard, secondary_button


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


class DataCenterDetailDialog(QDialog):
    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"数据详情 · {record.get('issue', '—')}")
        self.resize(650, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        fields = (
            ("期号", record.get("issue", "—")),
            ("开奖状态", record.get("draw_status", "—")),
            ("VIP100数量", record.get("vip100_count", 0)),
            ("算法HASH", record.get("hash_status", "—")),
            ("Outcome状态", record.get("outcome_status", "—")),
            ("Strategy ingest状态", record.get("strategy_ingest_status", "—")),
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


class DataCenterPage(QWidget):
    """Read-only data health and runtime overview."""

    def __init__(self, gateway: IntegrationGateway | None = None, parent=None):
        super().__init__(parent)
        self.gateway = gateway or IntegrationGateway()
        self.snapshot_data: dict = {}
        self.recent_records: tuple[dict, ...] = ()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("数据中心")
        title.setObjectName("PageTitle")
        hint = QLabel("正式数据健康、完整性与服务运行总览")
        hint.setObjectName("PageHint")
        title_box.addWidget(title)
        title_box.addWidget(hint)
        heading.addLayout(title_box)
        heading.addStretch()
        self.overall_status = QLabel("—")
        self.overall_status.setObjectName("Muted")
        heading.addWidget(self.overall_status)
        refresh_button = QPushButton("刷新")
        secondary_button(refresh_button)
        refresh_button.clicked.connect(self.refresh)
        heading.addWidget(refresh_button)
        root.addLayout(heading)

        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        root.addWidget(self.alert)

        status_grid = QGridLayout()
        status_grid.setSpacing(8)
        status_specs = (
            ("draw_status", "YU28"),
            ("draw_latest_issue", "最新开奖期号"),
            ("vip100_status", "VIP100"),
            ("vip100_latest_issue", "最新预测期号"),
            ("vip100_prediction_count", "VIP100算法"),
            ("hash_status", "HASH"),
            ("strategy_status", "Strategy Engine"),
            ("strategy_db_status", "Strategy DB"),
            ("data_freshness", "数据新鲜度"),
            ("le28_dependency", "Le28依赖"),
        )
        self.status_cards: dict[str, StatCard] = {}
        for index, (key, caption) in enumerate(status_specs):
            card = StatCard(caption, compact=True)
            self.status_cards[key] = card
            status_grid.addWidget(card, index // 5, index % 5)
        root.addLayout(status_grid)

        volumes = QFrame()
        volumes.setObjectName("Panel")
        volume_layout = QGridLayout(volumes)
        volume_layout.setContentsMargins(15, 10, 15, 10)
        count_specs = (
            ("draw_periods", "YU28开奖"),
            ("vip100_periods", "VIP100生产期"),
            ("vip100_prediction_rows", "正式预测"),
            ("drawn_prediction_periods", "已开奖预测期"),
            ("pending_prediction_periods", "待开奖预测期"),
            ("strategy_total", "策略总数"),
            ("RESEARCH_ONLY", "RESEARCH_ONLY"),
            ("CANDIDATE", "CANDIDATE"),
            ("FORWARD_TEST", "FORWARD_TEST"),
            ("VERIFIED", "VERIFIED"),
            ("REJECTED", "REJECTED"),
            ("insufficient_samples", "样本不足"),
        )
        self.count_labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(count_specs):
            column = index % 6
            row = (index // 6) * 2
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("0")
            value_label.setObjectName("SectionTitle")
            self.count_labels[key] = value_label
            volume_layout.addWidget(caption_label, row, column)
            volume_layout.addWidget(value_label, row + 1, column)
        root.addWidget(volumes)

        diagnostics = QHBoxLayout()
        self.integrity_table = QTableWidget(0, 3)
        self.integrity_table.setHorizontalHeaderLabels(("完整性检查", "状态", "详情"))
        self.integrity_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.integrity_table.verticalHeader().setVisible(False)
        self.integrity_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.integrity_table.setMinimumHeight(205)
        diagnostics.addWidget(self.integrity_table, 5)

        self.service_table = QTableWidget(0, 4)
        self.service_table.setHorizontalHeaderLabels(("服务", "状态", "PID", "状态时间/来源"))
        self.service_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.service_table.verticalHeader().setVisible(False)
        self.service_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.service_table.setMinimumHeight(205)
        diagnostics.addWidget(self.service_table, 5)
        root.addLayout(diagnostics)

        recent_title = QLabel("最近运行记录")
        recent_title.setObjectName("SectionTitle")
        root.addWidget(recent_title)
        self.recent_table = QTableWidget(0, 7)
        self.recent_table.setHorizontalHeaderLabels(
            (
                "期号",
                "开奖状态",
                "VIP100数量",
                "HASH",
                "Outcome状态",
                "Strategy ingest状态",
                "数据时间",
            )
        )
        self.recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SingleSelection)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.Stretch
        )
        self.recent_table.cellDoubleClicked.connect(self._show_detail)
        root.addWidget(self.recent_table, 1)

    def refresh(self) -> None:
        try:
            snapshot = self.gateway.data_center.snapshot()
        except Exception as exc:
            self._show_error(f"数据中心读取失败：{type(exc).__name__}: {exc}")
            return
        self.snapshot_data = snapshot
        self.recent_records = tuple(snapshot.get("recent", ()))
        top = snapshot.get("top", {})
        for key, card in self.status_cards.items():
            value = top.get(key, "—")
            if key == "vip100_prediction_count":
                value = f"{value}/100"
            card.set_value(value)
            _style_status(card.value_label, str(value))
        for key, label in self.count_labels.items():
            label.setText(str(snapshot.get("counts", {}).get(key, 0)))

        overall = str(snapshot.get("overall_status", "ERROR"))
        self.overall_status.setText(overall)
        _style_status(self.overall_status, overall)
        errors = list(snapshot.get("errors", ()))
        if errors:
            self._show_error("；".join(errors))
        else:
            self.alert.clear()
            self.alert.setVisible(False)
        self._render_integrity(snapshot.get("integrity", ()))
        self._render_services(snapshot.get("services", ()))
        self._render_recent(self.recent_records)

    def _show_error(self, message: str) -> None:
        self.alert.setObjectName("DangerText")
        self.alert.setText(message)
        self.alert.setVisible(True)
        self.alert.style().unpolish(self.alert)
        self.alert.style().polish(self.alert)

    def _render_integrity(self, checks) -> None:
        self.integrity_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            values = (check.get("name", ""), check.get("status", ""), check.get("detail", ""))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setForeground(QColor(_status_color(str(value))))
                self.integrity_table.setItem(row, column, item)
        self.integrity_table.resizeColumnToContents(0)
        self.integrity_table.resizeColumnToContents(1)

    def _render_services(self, services) -> None:
        self.service_table.setRowCount(len(services))
        for row, service in enumerate(services):
            detail = service.get("updated_at") or service.get("source") or "—"
            if service.get("error"):
                detail = f"{detail} · {service['error']}"
            values = (
                service.get("name", ""),
                service.get("status", ""),
                service.get("pid") or "—",
                detail,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setForeground(QColor(_status_color(str(value))))
                if column == 3:
                    item.setToolTip(str(service.get("source") or ""))
                self.service_table.setItem(row, column, item)
        self.service_table.resizeColumnToContents(0)
        self.service_table.resizeColumnToContents(1)

    def _render_recent(self, records) -> None:
        self.recent_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.get("issue", ""),
                record.get("draw_status", ""),
                record.get("vip100_count", 0),
                record.get("hash_status", ""),
                record.get("outcome_status", ""),
                record.get("strategy_ingest_status", ""),
                record.get("data_time", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, str(record.get("issue", "")))
                if column in (1, 3, 4, 5):
                    item.setForeground(QColor(_status_color(str(value))))
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


def _status_color(status: str) -> str:
    if status in GOOD_STATES or status.startswith("100/"):
        return "#16834B"
    if status in WAIT_STATES:
        return "#C26A00"
    if status in BAD_STATES:
        return "#B43B3B"
    return "#667085"


def _style_status(label: QLabel, status: str) -> None:
    label.setStyleSheet(f"color: {_status_color(status)}; font-weight: 600;")
