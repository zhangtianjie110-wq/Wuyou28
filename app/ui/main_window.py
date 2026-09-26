from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..backup import daily_backup
from ..constants import APP_NAME, APP_VERSION, BACKUP_DIR
from ..database import Database
from ..capture_controller import CaptureController
from ..data_integrity import DataIntegrityAuditor
from ..draw_capture_coordinator import DrawCaptureCoordinator
from ..yu28_controller import YU28Controller
from .data_page import DataPage
from .data_center_page import DataCenterPage
from .history_page import HistoryPage
from .home_page import HomePage
from .omission_page_v1 import OmissionPage
from .simulation_page import SimulationPage
from .statistics_page import StatisticsPage
from .settings_page import SettingsPage
from .strategy_page import StrategyPage
from .strategy_lab_page import StrategyLabPage
from .strategy_research_page import StrategyResearchPage
from .trend_page import TrendPage
from .road_page import RoadPage
from .vip100_page import Vip100Page
from .formal_ui_diy import InterfaceSettingsPage, apply_formal_theme
from .ui_diy import UIConfigManager


class MainWindow(QMainWindow):
    def __init__(self, database: Database, parent=None, ui_only: bool = False, ui_config=None):
        super().__init__(parent)
        self.database = database
        self.ui_only = bool(ui_only)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 880)
        self.setMinimumSize(1180, 720)
        self.capture_controller = CaptureController(database, self)
        self.yu28_controller = YU28Controller(database, self)
        self.integrity_auditor = DataIntegrityAuditor(database)
        self.capture_coordinator = DrawCaptureCoordinator(
            database, self.capture_controller, self
        )
        self.yu28_controller.new_draw.connect(self.capture_coordinator.on_new_draw)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(204)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 16, 12, 14)
        nav.setSpacing(3)
        brand = QHBoxLayout()
        brand_icon = QFrame()
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setFixedSize(46, 46)
        brand_icon_layout = QVBoxLayout(brand_icon)
        brand_icon_layout.setContentsMargins(0, 0, 0, 0)
        number = QLabel("28")
        number.setObjectName("BrandNumber")
        number.setAlignment(Qt.AlignCenter)
        brand_icon_layout.addWidget(number)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        logo = QLabel("无忧28")
        logo.setObjectName("AppTitle")
        subtitle = QLabel("开奖 · 预测 · 分析")
        subtitle.setObjectName("Muted")
        brand_text.addWidget(logo)
        brand_text.addWidget(subtitle)
        brand.addWidget(brand_icon)
        brand.addLayout(brand_text)
        brand.addStretch()
        nav.addLayout(brand)
        nav.addSpacing(14)

        self.stack = QStackedWidget()
        self.home_page = HomePage(database, self.capture_controller)
        self.data_page = DataPage(
            database, self.capture_controller, self.capture_coordinator
        )
        self.data_center_page = DataCenterPage()
        self.history_page = HistoryPage(database)
        self.omission_page = OmissionPage()
        self.trend_page = TrendPage()
        self.road_page = RoadPage()
        self.vip100_page = Vip100Page()
        self.strategy_research_page = StrategyResearchPage()
        self.strategy_page = StrategyPage(database)
        self.strategy_lab_page = StrategyLabPage(database)
        self.simulation_page = SimulationPage(database)
        self.statistics_page = StatisticsPage(database)
        self.settings_page = SettingsPage(database, self.capture_controller, self.yu28_controller)
        config_dir = Path(sys.executable).parent / 'ui' / 'config' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'config'
        self.ui_config = ui_config or UIConfigManager(config_dir)
        self.interface_settings_page = InterfaceSettingsPage(self.ui_config)
        self.interface_settings_page.bind_home(self.home_page)
        self.interface_settings_page.edit_requested.connect(lambda: self.show_page_by_name('首页'))
        self.interface_settings_page.theme_changed.connect(lambda: apply_formal_theme(self, self.ui_config))
        pages = [
            ("⌂   首页", self.home_page),
            ("D   数据中心", self.data_center_page),
            ("V   VIP100", self.vip100_page),
            ("R   策略研究", self.strategy_research_page),
            ("◌   遗漏分析", self.omission_page),
            ("⌁   走势图", self.trend_page),
            ("▥   火车路子", self.road_page),
            ("⚙   设置", self.settings_page),
        ]
        self.page_indices = {label.strip().split()[-1]: index for index, (label, _page) in enumerate(pages)}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (label, page) in enumerate(pages):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
            group.addButton(button, index)
            nav.addWidget(button)
            self.stack.addWidget(page)
            if index == 0:
                button.setChecked(True)
        self.stack.addWidget(self.interface_settings_page)
        nav.addStretch()
        connection = QLabel("●  数据层已连接")
        connection.setObjectName("SuccessText")
        nav.addWidget(connection)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("Muted")
        version.setAlignment(Qt.AlignLeft)
        nav.addWidget(version)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        apply_formal_theme(self, self.ui_config)

        self.data_page.data_changed.connect(self.refresh_all)
        self.history_page.data_changed.connect(self.refresh_all)
        self.strategy_page.data_changed.connect(self.refresh_all)
        self.strategy_lab_page.data_changed.connect(self.refresh_all)
        self.settings_page.settings_changed.connect(self.refresh_all)
        self.settings_page.interface_settings_requested.connect(self._show_interface_settings)
        settings_shortcut = QShortcut(QKeySequence('Alt+S'), self)
        settings_shortcut.activated.connect(lambda: self.show_page_by_name('设置'))
        self.capture_controller.capture_finished.connect(self._capture_finished)
        self.home_page.navigate_requested.connect(self.show_page_by_name)
        if not self.ui_only:
            self._run_daily_backup()
            self._run_integrity_audit()
            QTimer.singleShot(250, self.capture_coordinator.start)
            QTimer.singleShot(350, self.yu28_controller.start)
        else:
            self.statusBar().showMessage("已连接正式数据读取层", 8000)
            # Only the interface group is actionable in the independent frontend.
            # Source and capture controls belong to the separately running services.
            for section in self.settings_page.findChildren(QGroupBox):
                if section.title() != '界面设置':
                    section.setEnabled(False)
            for button in self.settings_page.findChildren(QPushButton):
                if button.text() == '保存设置':
                    button.setEnabled(False)

    def _show_page(self, index: int) -> None:
        if index != self.page_indices['首页'] and self.interface_settings_page.model.edit_mode:
            self.interface_settings_page.exit_edit_mode()
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _show_interface_settings(self) -> None:
        self.stack.setCurrentWidget(self.interface_settings_page)

    def refresh_all(self) -> None:
        # Hidden pages refresh on navigation. Rebuilding their tables during
        # every automatic capture used to block the UI thread needlessly.
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _capture_finished(self, _summary: dict) -> None:
        try:
            self.strategy_lab_page.refresh_forward_all()
        except Exception as exc:
            self.statusBar().showMessage(f"策略实验室前向验证更新失败：{exc}", 9000)
        # DataPage refreshes its log from logs_changed (emitted immediately
        # after capture_finished); avoid doing the same work twice.
        if self.stack.currentWidget() is not self.data_page:
            self.refresh_all()

    def show_page_by_name(self, name: str) -> None:
        index = self.page_indices.get(name)
        if index is None:
            return
        self._show_page(index)
        for candidate in self.findChildren(QPushButton, "NavButton"):
            if candidate.text().strip().endswith(name):
                candidate.setChecked(True)
                break

    def _run_daily_backup(self) -> None:
        try:
            path = daily_backup(self.database.path, BACKUP_DIR)
            if path:
                self.statusBar().showMessage(f"今日数据库已自动备份：{path.name}", 7000)
            else:
                self.statusBar().showMessage("数据库已就绪", 4000)
        except Exception as exc:
            self.statusBar().showMessage(f"自动备份失败：{exc}", 9000)

    def _run_integrity_audit(self) -> None:
        try:
            result = self.integrity_auditor.audit(auto_queue=True)
            summary = result["summary"]
            self.data_page.refresh_health()
            self.statusBar().showMessage(
                "完整性检查完成："
                f"总期数 {summary['total_periods']}，待补 {summary['pending_count']}，"
                f"缺失 {summary['missing']}",
                7000,
            )
        except Exception as exc:
            self.statusBar().showMessage(f"完整性检查失败：{exc}", 9000)

    def closeEvent(self, event) -> None:
        self.capture_controller.stop_auto()
        self.capture_coordinator.stop()
        self.yu28_controller.stop()
        super().closeEvent(event)
