from __future__ import annotations

import re

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QHeaderView, QLabel, QVBoxLayout, QWidget, QSizePolicy


_NUMBER_PATTERN = re.compile(r"(?:\d|%|¥|\$)")


def _is_number_text(value: object) -> bool:
    return bool(_NUMBER_PATTERN.search(str(value or "")))


def big_number_label(label: QLabel) -> QLabel:
    """Apply the shared large numeric style to a primary numeric label."""
    label.setObjectName("BigNumber")
    return label


def stat_number_label(label: QLabel) -> QLabel:
    """Apply the shared numeric style used by cards and summaries."""
    label.setObjectName("StatNumber")
    return label


def table_number_style(table) -> None:
    """Mark a table for the shared readable numeric/table typography."""
    table.setProperty("number_style", True)
    table.style().unpolish(table)
    table.style().polish(table)


def card_value_style(label: QLabel, value: object, compact: bool = False) -> None:
    """Choose a numeric or status style without changing the card's data."""
    if _is_number_text(value):
        stat_number_label(label)
    else:
        label.setObjectName("StatusValue" if compact else "CardValue")
    label.style().unpolish(label)
    label.style().polish(label)


class PageHeader(QFrame):
    """Shared page heading used by the main read-only views."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 7)
        layout.setSpacing(12)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageHeaderTitle")
        text_layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageHeaderSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout)
        layout.addStretch()
        self.status_label = QLabel("")
        self.status_label.setObjectName("PageHeaderStatus")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        self.updated_label = QLabel("")
        self.updated_label.setObjectName("PageHeaderMeta")
        self.updated_label.setVisible(False)
        layout.addWidget(self.updated_label)

    def set_status(self, value: object) -> None:
        text = str(value or "")
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_updated(self, value: object) -> None:
        text = str(value or "")
        self.updated_label.setText(text)
        self.updated_label.setVisible(bool(text))


class Card(QFrame):
    """Lightweight white rounded container for page-level content."""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_body = QVBoxLayout(self)
        self.layout_body.setContentsMargins(14, 12, 14, 12)
        self.layout_body.setSpacing(8)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("CardTitle")
            self.layout_body.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("CardSubtitle")
            self.layout_body.addWidget(subtitle_label)


class StatCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "—",
        subtitle: str = "",
        compact: bool = False,
        accent: str = "",
        icon: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._compact = compact
        self._title_text = str(title)
        self._value_text = str(value)
        self._subtitle_text = str(subtitle)
        self.setObjectName(f"Metric{accent.title()}" if accent else "Card")
        self.setFixedHeight(110)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("MetricIcon")
            icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            layout.addWidget(icon_label)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.value_label = QLabel(value)
        card_value_style(self.value_label, value, compact)
        self.value_label.setWordWrap(False)
        self.value_label.setMinimumWidth(0)
        self.value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.value_label.setStyleSheet(
            f"font-size: {'18px' if compact and not _is_number_text(value) else '20px'};"
        )
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("CardSubtitle")
        self.subtitle_label.setWordWrap(False)
        self.subtitle_label.setMinimumWidth(0)
        self.subtitle_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.subtitle_label.setStyleSheet("font-size: 12px;")
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.value_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)
        self._update_elided_text()

    @staticmethod
    def _elide(label: QLabel, text: str) -> None:
        width = max(0, label.contentsRect().width())
        if width <= 0:
            label.setText(text)
            return
        label.setText(QFontMetrics(label.font()).elidedText(text, Qt.ElideRight, width))

    def _update_elided_text(self) -> None:
        self._elide(self.title_label, self._title_text)
        self._elide(self.value_label, self._value_text)
        self._elide(self.subtitle_label, self._subtitle_text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def set_value(self, value: object) -> None:
        self._value_text = str(value)
        self.value_label.setText(str(value))
        card_value_style(self.value_label, value, self._compact)
        self.value_label.setStyleSheet(
            f"font-size: {'18px' if self._compact and not _is_number_text(value) else '20px'};"
        )
        self._update_elided_text()

    def set_subtitle(self, value: object) -> None:
        text = str(value)
        self._subtitle_text = text
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))
        self._update_elided_text()

    def set_status_style(self, state: str) -> None:
        name = "StatusValue"
        if state in ("失败", "读取失败", "未连接"):
            name = "DangerText"
        elif state in ("待检查", "跳过"):
            name = "WarningText"
        self.value_label.setObjectName(name)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


class TrendChart(QWidget):
    """Dependency-free chart used for real backtest hit-rate trends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: list[float] = []
        self.setMinimumHeight(120)

    def set_values(self, values: list[float]) -> None:
        self.values = [max(0.0, min(100.0, float(value))) for value in values]
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = self.rect().adjusted(12, 10, -12, -16)
        painter.setPen(QPen(QColor("#E8EDF4"), 1))
        for ratio in (0.0, 0.5, 1.0):
            y = bounds.bottom() - bounds.height() * ratio
            painter.drawLine(bounds.left(), int(y), bounds.right(), int(y))
        if not self.values:
            painter.setPen(QColor("#9AA4B4"))
            painter.drawText(bounds, Qt.AlignCenter, "暂无回测数据")
            return
        count = max(1, len(self.values) - 1)
        points = [
            QPointF(
                bounds.left() + bounds.width() * index / count,
                bounds.bottom() - bounds.height() * value / 100.0,
            )
            for index, value in enumerate(self.values)
        ]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        fill = QPainterPath(line)
        fill.lineTo(points[-1].x(), bounds.bottom())
        fill.lineTo(points[0].x(), bounds.bottom())
        fill.closeSubpath()
        painter.fillPath(fill, QColor(38, 136, 245, 26))
        painter.setPen(QPen(QColor("#2688F5"), 2))
        painter.drawPath(line)


def secondary_button(button) -> None:
    button.setProperty("secondary", True)
    button.style().unpolish(button)
    button.style().polish(button)


def danger_button(button) -> None:
    button.setProperty("danger", True)
    button.style().unpolish(button)
    button.style().polish(button)


def polish_table(table, height: int = 420) -> None:
    """Apply the shared compact table treatment without changing its data model."""
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setWordWrap(False)
    table_number_style(table)
    table.setFixedHeight(height)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
    table.horizontalHeader().setMinimumSectionSize(36)
    for column in range(table.columnCount()):
        header_item = table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setTextAlignment(Qt.AlignCenter)
    action_columns = {
        column
        for column in range(table.columnCount())
        if table.horizontalHeaderItem(column) is not None
        and str(table.horizontalHeaderItem(column).text()).strip() in {"详情", "查看", "操作"}
    }
    for column in action_columns:
        table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
        table.horizontalHeader().resizeSection(column, 100)
    table.verticalHeader().setDefaultSectionSize(40)


def polish_detail_button(button) -> None:
    """Keep a table action readable and clickable at narrow window sizes."""
    button.setMinimumSize(90, 32)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    button.setCursor(Qt.PointingHandCursor)
