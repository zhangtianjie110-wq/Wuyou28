from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


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
        self.setObjectName(f"Metric{accent.title()}" if accent else "Card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(10)
        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("MetricIcon")
            icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            layout.addWidget(icon_label)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatusValue" if compact else "CardValue")
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("CardSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addWidget(title_label)
        text_layout.addWidget(self.value_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)

    def set_value(self, value: object) -> None:
        self.value_label.setText(str(value))

    def set_subtitle(self, value: object) -> None:
        text = str(value)
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

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
