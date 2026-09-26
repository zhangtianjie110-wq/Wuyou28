from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..backup import backup_database
from ..constants import BACKUP_DIR
from ..database import Database
from .widgets import secondary_button


class SettingsPage(QWidget):
    settings_changed = Signal()
    interface_settings_requested = Signal()

    def __init__(self, database: Database, capture_controller, yu28_controller, parent=None):
        super().__init__(parent)
        self.database = database
        self.capture_controller = capture_controller
        self.yu28_controller = yu28_controller
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        hint = QLabel("调整训练/验证比例，测试只读采集组件，并管理数据库备份。")
        hint.setObjectName("PageHint")
        root.addWidget(title)
        root.addWidget(hint)

        interface_group = QGroupBox("界面设置")
        interface_layout = QVBoxLayout(interface_group)
        interface_hint = QLabel("自定义主题、字体、导航宽度、表格行高、开奖号码样式，并进入首页可视化编辑模式。")
        interface_hint.setObjectName("Muted")
        interface_hint.setWordWrap(True)
        interface_layout.addWidget(interface_hint)
        interface_button = QPushButton("打开界面设置 / 编辑界面")
        interface_button.setShortcut('Alt+U')
        interface_button.setToolTip('打开界面设置 (Alt+U)')
        interface_button.clicked.connect(self.interface_settings_requested.emit)
        interface_layout.addWidget(interface_button)
        root.addWidget(interface_group)

        source_group = QGroupBox("数据源")
        source_layout = QVBoxLayout(source_group)
        source_form = QFormLayout()
        self.yu28_key = QLineEdit()
        self.yu28_key.setEchoMode(QLineEdit.Password)
        self.yu28_key.setClearButtonEnabled(True)
        self.yu28_key.setPlaceholderText(
            "已安全保存（输入新 Key 可替换）"
            if self.yu28_controller.has_api_key()
            else "yu28_ 开头的 API Key"
        )
        source_form.addRow("YU28 API Key", self.yu28_key)
        self.yu28_status = QLabel(self.yu28_controller.last_status)
        self.yu28_status.setObjectName("Muted")
        source_form.addRow("连接状态", self.yu28_status)
        self.yu28_issue = QLabel("—")
        self.yu28_draw = QLabel("—")
        self.yu28_time = QLabel("—")
        self.yu28_countdown = QLabel("—")
        source_form.addRow("最新期号", self.yu28_issue)
        source_form.addRow("开奖结果", self.yu28_draw)
        source_form.addRow("开奖时间", self.yu28_time)
        source_form.addRow("下期倒计时", self.yu28_countdown)
        source_layout.addLayout(source_form)
        source_buttons = QHBoxLayout()
        save_key = QPushButton("安全保存 Key")
        test_yu28 = QPushButton("测试 YU28 连接")
        secondary_button(test_yu28)
        save_key.clicked.connect(self._save_yu28_key)
        test_yu28.clicked.connect(self._test_yu28)
        source_buttons.addWidget(save_key)
        source_buttons.addWidget(test_yu28)
        source_buttons.addStretch()
        source_layout.addLayout(source_buttons)
        source_note = QLabel("Key 仅保存在 Windows 凭据管理器，请求时仅通过 X-Api-Key 请求头发送。")
        source_note.setObjectName("Muted")
        source_note.setWordWrap(True)
        source_layout.addWidget(source_note)
        root.addWidget(source_group)

        split_group = QGroupBox("回测数据集")
        split_form = QFormLayout(split_group)
        self.train_ratio = QDoubleSpinBox()
        self.train_ratio.setRange(10, 90)
        self.train_ratio.setDecimals(0)
        self.train_ratio.setSuffix(" %")
        self.train_ratio.setValue(float(self.database.get_setting("train_ratio", "0.7")) * 100)
        self.validation_label = QLabel()
        self.train_ratio.valueChanged.connect(self._update_ratio_label)
        split_form.addRow("训练集比例", self.train_ratio)
        split_form.addRow("验证集比例", self.validation_label)
        self._update_ratio_label()
        root.addWidget(split_group)

        capture_group = QGroupBox("采集组件测试")
        capture_layout = QVBoxLayout(capture_group)
        capture_form = QFormLayout()
        self._configured_window_title = self.database.get_setting("capture_window_title", "乐28")
        self.window_title = QLineEdit()
        self.window_title.setPlaceholderText("已配置外部开奖窗口（留空保持当前）")
        capture_form.addRow("采集窗口标识", self.window_title)
        capture_layout.addLayout(capture_form)
        safety = QLabel(
            "测试仅读取窗口；正式采集只允许切换到“VIP预测”，"
            "不会操作投注和资金相关按钮。"
        )
        safety.setObjectName("Muted")
        safety.setWordWrap(True)
        capture_layout.addWidget(safety)
        test_buttons = QHBoxLayout()
        for name in ("窗口识别", "UI Automation", "OCR"):
            button = QPushButton(f"测试{name}")
            button.clicked.connect(lambda _checked=False, value=name: self._test_capture(value))
            test_buttons.addWidget(button)
        test_buttons.addStretch()
        capture_layout.addLayout(test_buttons)
        self.test_result = QLabel("尚未测试")
        self.test_result.setObjectName("Muted")
        self.test_result.setWordWrap(True)
        capture_layout.addWidget(self.test_result)
        root.addWidget(capture_group)

        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self._save)
        save_row = QHBoxLayout()
        save_row.addWidget(save_button)
        save_row.addStretch()
        root.addLayout(save_row)

        backup_group = QGroupBox("数据库备份")
        backup_layout = QVBoxLayout(backup_group)
        db_path = QLabel(f"数据库：{self.database.path}")
        db_path.setWordWrap(True)
        db_path.setTextInteractionFlags(db_path.textInteractionFlags() | Qt.TextSelectableByMouse)
        backup_path = QLabel(f"备份目录：{BACKUP_DIR}")
        backup_path.setWordWrap(True)
        backup_layout.addWidget(db_path)
        backup_layout.addWidget(backup_path)
        note = QLabel("软件启动时每天最多自动备份一次，也可以随时立即备份。")
        note.setObjectName("Muted")
        backup_layout.addWidget(note)
        backup_buttons = QHBoxLayout()
        backup_now = QPushButton("立即备份")
        open_folder = QPushButton("打开备份文件夹")
        secondary_button(open_folder)
        backup_now.clicked.connect(self._backup)
        open_folder.clicked.connect(self._open_backup_folder)
        backup_buttons.addWidget(backup_now)
        backup_buttons.addWidget(open_folder)
        backup_buttons.addStretch()
        backup_layout.addLayout(backup_buttons)
        root.addWidget(backup_group)
        root.addStretch()
        self.capture_controller.diagnostic_finished.connect(self._show_test_result)
        self.yu28_controller.status_changed.connect(self._show_yu28_status)
        self.yu28_controller.latest_changed.connect(self._show_yu28_latest)
        if self.yu28_controller.latest:
            self._show_yu28_latest(self.yu28_controller.latest)

    def _update_ratio_label(self) -> None:
        self.validation_label.setText(f"{100 - int(self.train_ratio.value())} %")

    def _save(self) -> None:
        self.database.set_setting("train_ratio", self.train_ratio.value() / 100)
        value = self.window_title.text().strip() or self._configured_window_title or "乐28"
        self.database.set_setting("capture_window_title", value)
        self._configured_window_title = value
        self.settings_changed.emit()
        QMessageBox.information(self, "保存成功", "训练集和验证集比例已保存。")

    def _save_yu28_key(self, show_message: bool = True) -> bool:
        value = self.yu28_key.text().strip()
        if not value:
            if show_message:
                QMessageBox.information(self, "没有新 Key", "请输入新的 YU28 API Key。")
            return self.yu28_controller.has_api_key()
        try:
            self.yu28_controller.save_api_key(value)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self.yu28_key.clear()
        self.yu28_key.setPlaceholderText("已安全保存（输入新 Key 可替换）")
        self._show_yu28_status("YU28 Key 已安全保存，等待连接测试", "muted")
        if show_message:
            QMessageBox.information(self, "保存成功", "YU28 API Key 已保存到 Windows 凭据管理器。")
        return True

    def _test_yu28(self) -> None:
        if self.yu28_key.text().strip() and not self._save_yu28_key(show_message=False):
            return
        self.yu28_controller.test_connection()

    def _show_yu28_status(self, message: str, state: str) -> None:
        names = {"success": "SuccessText", "error": "DangerText", "working": "WarningText"}
        self.yu28_status.setText(message)
        self.yu28_status.setObjectName(names.get(state, "Muted"))
        self.yu28_status.style().unpolish(self.yu28_status)
        self.yu28_status.style().polish(self.yu28_status)

    def _show_yu28_latest(self, draw: dict) -> None:
        self.yu28_issue.setText(str(draw.get("nbr") or "—"))
        number = str(draw.get("number") or "—")
        combination = str(draw.get("combination") or "")
        self.yu28_draw.setText(f"{number}  {combination}".strip())
        self.yu28_time.setText(str(draw.get("time") or "—"))
        self.yu28_countdown.setText(str(draw.get("countdown") or "—"))

    def refresh(self) -> None:
        self._show_yu28_status(
            self.yu28_controller.last_status, self.yu28_controller.last_state
        )
        if self.yu28_controller.latest:
            self._show_yu28_latest(self.yu28_controller.latest)

    def _test_capture(self, kind: str) -> None:
        title = self.window_title.text().strip() or self._configured_window_title or "乐28"
        self.database.set_setting("capture_window_title", title)
        self.test_result.setText(f"正在测试{kind}……")
        self.capture_controller.run_diagnostic(kind, title)

    def _show_test_result(self, kind: str, success: bool, message: str) -> None:
        prefix = "成功" if success else "失败"
        self.test_result.setText(f"{kind}测试{prefix}：{message}")

    def _backup(self) -> None:
        try:
            path = backup_database(self.database.path, BACKUP_DIR)
            QMessageBox.information(self, "备份成功", f"数据库已备份到：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", str(exc))

    def _open_backup_folder(self) -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(BACKUP_DIR))):
            QMessageBox.warning(self, "无法打开", f"请手动打开：\n{BACKUP_DIR}")


# Public import retained for callers of the original settings module.
from .formal_ui_diy import InterfaceSettingsPage
