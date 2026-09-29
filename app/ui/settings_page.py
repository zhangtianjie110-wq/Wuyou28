from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..backup import backup_database
from ..constants import BACKUP_DIR
from ..database import Database
from .widgets import PageHeader, StatCard, secondary_button


class SettingsPage(QWidget):
    settings_changed = Signal()
    interface_settings_requested = Signal()

    def __init__(self, database: Database, yu28_controller, parent=None):
        super().__init__(parent)
        self.database = database
        self.yu28_controller = yu28_controller
        self._settings_sections: dict[str, QWidget] = {}
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(20, 20, 20, 20)
        page_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(4, 4, 12, 4)
        root.setSpacing(10)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        self._settings_scroll = scroll

        root.addWidget(PageHeader("设置", "软件、数据与策略运行设置"))

        categories = QLabel("正式数据 · 本地配置 · 只读状态")
        categories.setObjectName("Muted")
        root.addWidget(categories)

        overview_title = QLabel("系统状态总览")
        overview_title.setObjectName("SectionTitle")
        root.addWidget(overview_title)
        overview = QHBoxLayout()
        self.database_status_card = StatCard("数据状态", "检查中", compact=True)
        self.vip_status_card = StatCard("VIP100", "100/100", compact=True)
        for card in (self.database_status_card, self.vip_status_card):
            overview.addWidget(card, 1)
        root.addLayout(overview)
        base_group = QGroupBox("软件设置")
        base_layout = QFormLayout(base_group)
        self.auto_refresh = QCheckBox("启用自动刷新")
        self.auto_refresh.setChecked(True)
        self.auto_start = QCheckBox("开机自动启动")
        self.start_minimized = QCheckBox("启动后最小化")
        self.start_home = QCheckBox("启动进入首页")
        self.startup_data_check = QCheckBox("启动自动检查数据")
        self.auto_start.setChecked(self.database.get_setting("auto_start", "0") == "1")
        self.start_minimized.setChecked(self.database.get_setting("start_minimized", "0") == "1")
        self.start_home.setChecked(self.database.get_setting("start_home", "1") == "1")
        self.startup_data_check.setChecked(self.database.get_setting("startup_data_check", "0") == "1")
        base_layout.addRow("自动刷新", self.auto_refresh)
        base_layout.addRow("开机自动启动", self.auto_start)
        base_layout.addRow("启动后最小化", self.start_minimized)
        base_layout.addRow("启动进入首页", self.start_home)
        base_layout.addRow("启动检查数据", self.startup_data_check)
        root.addWidget(base_group)
        self._register_section("软件设置", base_group)

        source_group = QGroupBox("数据源")
        source_layout = QVBoxLayout(source_group)
        source_form = QFormLayout()
        self.yu28_key = QLineEdit()
        self.yu28_key.setEchoMode(QLineEdit.Password)
        self.yu28_key.setClearButtonEnabled(True)
        self.yu28_key.setPlaceholderText(
            "已安全保存（输入新密钥可替换）"
            if self.yu28_controller.has_api_key()
            else "以 yu28_ 开头的 API 密钥"
        )
        source_form.addRow("YU28 API 密钥", self.yu28_key)
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
        save_key = QPushButton("安全保存密钥")
        test_yu28 = QPushButton("测试 YU28 连接")
        secondary_button(test_yu28)
        save_key.clicked.connect(self._save_yu28_key)
        test_yu28.clicked.connect(self._test_yu28)
        source_buttons.addWidget(save_key)
        source_buttons.addWidget(test_yu28)
        source_buttons.addStretch()
        source_layout.addLayout(source_buttons)
        source_note = QLabel("密钥仅保存在 Windows 凭据管理器，请求时仅通过 X-Api-Key 请求头发送。")
        source_note.setObjectName("Muted")
        source_note.setWordWrap(True)
        source_layout.addWidget(source_note)
        self._register_section("数据来源", source_group)

        data_management_group = QGroupBox("数据管理")
        data_management_layout = QVBoxLayout(data_management_group)
        data_summary = QFormLayout()
        self.database_status = QLabel("正常")
        self.database_latest_issue = QLabel("—")
        self.database_count = QLabel("—")
        self.database_last_sync = QLabel("—")
        data_summary.addRow("数据库", self.database_status)
        data_summary.addRow("最新开奖", self.database_latest_issue)
        data_summary.addRow("数据数量", self.database_count)
        data_summary.addRow("最后同步", self.database_last_sync)
        data_management_layout.addLayout(data_summary)
        maintenance_buttons = QHBoxLayout()
        integrity_button = QPushButton("检查数据完整性")
        integrity_button.clicked.connect(self._refresh_data_summary)
        repair_button = QPushButton("自动补缺")
        repair_button.clicked.connect(lambda: self._show_feature_notice("自动补缺"))
        clean_button = QPushButton("清理重复数据")
        clean_button.clicked.connect(lambda: self._show_feature_notice("清理重复数据"))
        backup_button = QPushButton("备份数据库")
        backup_button.clicked.connect(self._backup)
        restore_button = QPushButton("恢复数据库")
        restore_button.clicked.connect(lambda: self._show_feature_notice("恢复数据库"))
        for button in (integrity_button, repair_button, clean_button, backup_button, restore_button):
            secondary_button(button)
            maintenance_buttons.addWidget(button)
        data_management_layout.addLayout(maintenance_buttons)
        # Keep the YU28 connection credential in the data-management area.
        data_management_layout.addWidget(source_group)
        root.addWidget(data_management_group)
        self._register_section("数据管理", data_management_group)
        self._refresh_data_summary()

        self.data_check = QCheckBox("打开页面时检查数据健康")
        self.data_check.setChecked(self.database.get_setting("data_check", "1") == "1")
        data_management_layout.addWidget(self.data_check)

        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self._save)
        save_row = QHBoxLayout()
        save_row.addWidget(save_button)
        save_row.addStretch()
        root.addLayout(save_row)

        advanced_group = QGroupBox("高级设置")
        self.backup_group = advanced_group
        advanced_layout = QFormLayout(advanced_group)
        db_path = QLabel(f"数据库：{self.database.path}")
        db_path.setWordWrap(True)
        db_path.setTextInteractionFlags(db_path.textInteractionFlags() | Qt.TextSelectableByMouse)
        backup_path = QLabel(f"备份目录：{BACKUP_DIR}")
        backup_path.setWordWrap(True)
        advanced_layout.addRow("数据库", db_path)
        advanced_layout.addRow("备份目录", backup_path)
        note = QLabel("软件启动时每天最多自动备份一次，也可以随时立即备份。")
        note.setObjectName("Muted")
        advanced_layout.addRow(note)
        backup_buttons = QHBoxLayout()
        backup_now = QPushButton("立即备份")
        open_folder = QPushButton("打开备份文件夹")
        secondary_button(open_folder)
        backup_now.clicked.connect(self._backup)
        open_folder.clicked.connect(self._open_backup_folder)
        backup_buttons.addWidget(backup_now)
        backup_buttons.addWidget(open_folder)
        backup_buttons.addStretch()
        advanced_layout.addRow(backup_buttons)
        advanced_layout.addRow("日志", QLabel("按需查看运行日志"))
        advanced_layout.addRow("调试", QLabel("仅诊断模式使用"))
        advanced_layout.addRow("技术信息", QLabel("核心页面详情中查看"))
        config_buttons = QHBoxLayout()
        import_config = QPushButton("导入配置")
        export_config = QPushButton("导出配置")
        secondary_button(import_config)
        secondary_button(export_config)
        import_config.clicked.connect(lambda: self._show_feature_notice("导入配置"))
        export_config.clicked.connect(lambda: self._show_feature_notice("导出配置"))
        config_buttons.addWidget(import_config)
        config_buttons.addWidget(export_config)
        config_buttons.addStretch()
        advanced_layout.addRow("配置文件", config_buttons)
        root.addWidget(advanced_group)

        strategy_group = QGroupBox("策略管理")
        strategy_layout = QVBoxLayout(strategy_group)
        strategy_summary = QFormLayout()
        self.strategy_status = QLabel("未加载")
        self.strategy_status.setObjectName("Muted")
        self.strategy_version = QLabel("当前版本：—")
        strategy_summary.addRow("当前策略", self.strategy_status)
        strategy_summary.addRow("策略版本", self.strategy_version)
        strategy_layout.addLayout(strategy_summary)
        strategy_buttons = QHBoxLayout()
        for label in ("保存策略", "复制策略", "导入策略", "导出策略", "删除策略"):
            button = QPushButton(label)
            secondary_button(button)
            button.clicked.connect(lambda _checked=False, value=label: self._show_feature_notice(value))
            strategy_buttons.addWidget(button)
        strategy_layout.addLayout(strategy_buttons)
        root.addWidget(strategy_group)
        self._register_section("策略管理", strategy_group)
        self._refresh_strategy_summary()
        root.removeWidget(advanced_group)
        root.addWidget(advanced_group)

        for group, expanded in (
            (base_group, True),
            (data_management_group, True),
            (source_group, True),
            (strategy_group, True),
            (advanced_group, False),
        ):
            self._configure_collapsible(group, expanded)
        self._register_section("高级设置", advanced_group)

        root.addStretch()
        self.yu28_controller.status_changed.connect(self._show_yu28_status)
        self.yu28_controller.latest_changed.connect(self._show_yu28_latest)
        if self.yu28_controller.latest:
            self._show_yu28_latest(self.yu28_controller.latest)

    def _register_section(self, name: str, widget: QWidget) -> None:
        self._settings_sections[name] = widget

    @staticmethod
    def _configure_collapsible(group: QGroupBox, expanded: bool) -> None:
        group.setCheckable(True)
        group.setChecked(expanded)

        def update_content(visible: bool) -> None:
            for child in group.findChildren(QWidget):
                child.setVisible(visible)

        group.toggled.connect(update_content)
        update_content(expanded)

    @staticmethod
    def _style_status_label(label: QLabel, state: str) -> None:
        names = {"正常": "SuccessText", "异常": "DangerText", "待检查": "WarningText"}
        label.setObjectName(names.get(state, "Muted"))
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_data_summary(self) -> None:
        """Refresh the lightweight settings summary without running an audit."""
        try:
            dashboard = self.database.dashboard()
        except Exception as exc:
            self.database_status.setText("异常")
            self.database_status.setToolTip(str(exc))
            self._style_status_label(self.database_status, "异常")
            self.database_status_card.set_value("异常")
            self.database_status_card.set_status_style("异常")
            return
        self.database_status.setText("正常")
        self._style_status_label(self.database_status, "正常")
        self.database_status_card.set_value("正常")
        self.database_status_card.set_status_style("正常")
        self.database_latest_issue.setText(str(dashboard.get("current_issue") or "—"))
        self.database_count.setText(f"{int(dashboard.get('total_rows') or 0):,}")
        self.database_last_sync.setText(str(dashboard.get("last_time") or "—"))

    def _refresh_strategy_summary(self) -> None:
        try:
            strategies = self.database.list_strategies()
        except Exception:
            strategies = []
        enabled = [item for item in strategies if item.get("enabled")]
        if enabled:
            self.strategy_status.setText(f"{enabled[0].get('name', '未命名')} · 已启用（共 {len(strategies)} 个）")
            self.strategy_version.setText(f"当前版本：{enabled[0].get('updated_at') or '默认'}")
        else:
            self.strategy_status.setText("未选择启用策略")
            self.strategy_version.setText("当前版本：—")

    def _show_feature_notice(self, feature: str) -> None:
        QMessageBox.information(
            self,
            feature,
            f"{feature}入口已保留，具体维护流程将在对应模块接入后启用。",
        )

    def _save(self) -> None:
        for key, widget in (
            ("auto_start", self.auto_start),
            ("start_minimized", self.start_minimized),
            ("start_home", self.start_home),
            ("startup_data_check", self.startup_data_check),
            ("data_check", self.data_check),
            ("auto_refresh", self.auto_refresh),
        ):
            self.database.set_setting(key, "1" if widget.isChecked() else "0")
        self._refresh_data_summary()
        self.settings_changed.emit()
        QMessageBox.information(self, "保存成功", "软件、数据与策略设置已保存。")

    def _save_yu28_key(self, show_message: bool = True) -> bool:
        value = self.yu28_key.text().strip()
        if not value:
            if show_message:
                QMessageBox.information(self, "没有新密钥", "请输入新的 YU28 API 密钥。")
            return self.yu28_controller.has_api_key()
        try:
            self.yu28_controller.save_api_key(value)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self.yu28_key.clear()
        self.yu28_key.setPlaceholderText("已安全保存（输入新密钥可替换）")
        self._show_yu28_status("YU28 密钥已安全保存，等待连接测试", "muted")
        if show_message:
            QMessageBox.information(self, "保存成功", "YU28 API 密钥已保存到 Windows 凭据管理器。")
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
