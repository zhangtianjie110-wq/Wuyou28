from __future__ import annotations

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    QThreadPool,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
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
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..backup import daily_backup
from ..constants import APP_NAME, APP_VERSION, BACKUP_DIR, CONFIG_DIR
from ..database import Database
from ..yu28_controller import YU28Controller
from .data_page import DataPage
from .data_center_page import DataCenterPage
from .history_page import HistoryPage
from .history_analysis_page import HistoryAnalysisPage
from .home_page import HomePage
from .hot_cold_page import HotColdPage
from .omission_page_v1 import OmissionPage
from .simulation_page import SimulationPage
from .statistics_page import StatisticsPage
from .settings_page import SettingsPage
from .strategy_page import StrategyPage
from .strategy_lab_page import StrategyLabPage
from .strategy_research_page import StrategyResearchPage
from strategy_lab.page import StrategyExperimentPage
from strategy_lab.auto_page import StrategyAutoPage
from .trend_page import TrendPage
from .vip100_page import Vip100Page
from .yu28_tools_page import HistoryTrendPage, LongDragonStatsPage, LotteryStatsPage
from .formal_ui_diy import InterfaceSettingsPage, apply_formal_theme
from .ui_diy import UIConfigManager

_ACTIVE_STARTUP_TASKS = set()


class _LazyPage(QWidget):
    """A stack placeholder that creates its real page on first use."""

    data_changed = Signal()
    settings_changed = Signal()
    interface_settings_requested = Signal()

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._page = None
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)

    def ensure_loaded(self):
        if self._page is None:
            self._page = self._factory()
            self._body.addWidget(self._page)
            for signal_name in (
                "data_changed",
                "settings_changed",
                "interface_settings_requested",
            ):
                source = getattr(self._page, signal_name, None)
                target = getattr(self, signal_name, None)
                if source is not None and target is not None:
                    source.connect(target)
        return self._page

    def refresh(self, *args, **kwargs):
        page = self.ensure_loaded()
        if getattr(page, "_defer_initial_refresh", False) and not kwargs.get("force"):
            return None
        callback = getattr(page, "refresh", None)
        return callback(*args, **kwargs) if callable(callback) else None

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.ensure_loaded(), name)


class _StartupTaskSignals(QObject):
    finished = Signal(object)


class _StartupChecksTask(QRunnable):
    """Run startup maintenance without touching Qt widgets."""

    def __init__(self, database_path, backup_dir):
        super().__init__()
        self.setAutoDelete(False)
        self.database_path = database_path
        self.backup_dir = backup_dir
        self.signals = _StartupTaskSignals(QCoreApplication.instance())

    def run(self) -> None:
        result = {
            "backup": None,
            "backup_error": None,
        }
        try:
            result["backup"] = daily_backup(self.database_path, self.backup_dir)
        except Exception as exc:
            result["backup_error"] = f"{type(exc).__name__}: {exc}"
        self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(
        self,
        database: Database,
        parent=None,
        ui_only: bool = False,
        ui_config=None,
    ):
        super().__init__(parent)
        self.database = database
        self.ui_only = bool(ui_only)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 880)
        self.setMinimumSize(1180, 720)
        self.yu28_controller = YU28Controller(database, self)
        # One read-only gateway is shared by all lazily-created pages.
        from ..integration import IntegrationGateway

        self.gateway = IntegrationGateway()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(184)
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
        subtitle = QLabel("导航菜单")
        subtitle.setObjectName("Muted")
        brand_text.addWidget(logo)
        brand_text.addWidget(subtitle)
        brand.addWidget(brand_icon)
        brand.addLayout(brand_text)
        brand.addStretch()
        nav.addLayout(brand)
        nav.addSpacing(14)

        self.stack = QStackedWidget()
        self.home_page = HomePage(
            database,
            gateway=self.gateway,
            startup_lightweight=True,
        )
        self.data_page = _LazyPage(
            lambda: DataPage(database)
        )
        self.data_center_page = _LazyPage(
            lambda: DataCenterPage(self.gateway, startup_async=True)
        )
        self.history_page = _LazyPage(lambda: HistoryPage(database))
        self.omission_page = _LazyPage(lambda: OmissionPage(self.gateway))
        self.trend_page = _LazyPage(lambda: TrendPage(self.gateway))
        self.vip100_page = _LazyPage(lambda: Vip100Page(self.gateway))
        self.hot_cold_page = _LazyPage(lambda: HotColdPage(self.gateway))
        self.lottery_stats_page = _LazyPage(lambda: LotteryStatsPage(self.gateway))
        self.long_dragon_stats_page = _LazyPage(lambda: LongDragonStatsPage(self.gateway))
        self.history_trend_page = _LazyPage(lambda: HistoryTrendPage(self.gateway))
        self.strategy_research_page = _LazyPage(lambda: StrategyResearchPage(self.gateway))
        self.strategy_page = _LazyPage(lambda: StrategyPage(database))
        self.strategy_lab_page = _LazyPage(lambda: StrategyLabPage(database))
        self.strategy_experiment_page = _LazyPage(lambda: StrategyExperimentPage(database))
        self.strategy_auto_page = _LazyPage(lambda: StrategyAutoPage(database.path))
        self.simulation_page = _LazyPage(lambda: SimulationPage(database))
        self.history_analysis_page = _LazyPage(
            lambda: HistoryAnalysisPage(
                self.trend_page,
                self.omission_page,
                self.hot_cold_page,
                self.long_dragon_stats_page,
            )
        )
        self.statistics_page = _LazyPage(lambda: StatisticsPage(database))
        self.settings_page = _LazyPage(
            lambda: SettingsPage(database, self.yu28_controller)
        )
        # Configuration is mutable user state.  CONFIG_DIR points to the
        # per-user runtime directory for packaged builds and preserves the
        # checked-in UI defaults during development.
        self.ui_config = ui_config or UIConfigManager(CONFIG_DIR)
        self.interface_settings_page = InterfaceSettingsPage(self.ui_config)
        # Keep the normal home page on its native responsive layout. The
        # optional layout editor is attached only when edit mode is entered.
        self.interface_settings_page.set_home(self.home_page)
        self.interface_settings_page.edit_requested.connect(lambda: self.show_page_by_name('首页'))
        self.interface_settings_page.theme_changed.connect(lambda: apply_formal_theme(self, self.ui_config))
        visible_sections = [
            ("", [
                ("首页", "首页", self.home_page, QStyle.SP_DirHomeIcon),
                ("数据中心", "数据中心", self.data_center_page, QStyle.SP_DirOpenIcon),
            ]),
            ("策略中心", [
                ("VIP100", "VIP100", self.vip100_page, QStyle.SP_FileIcon),
                ("智能选法", "智能选法", self.strategy_lab_page, QStyle.SP_ComputerIcon),
                ("策略实验室", "策略实验室", self.strategy_experiment_page, QStyle.SP_FileDialogDetailedView),
                ("策略自动运行", "策略自动运行", self.strategy_auto_page, QStyle.SP_BrowserReload),
            ]),
            ("", [
                ("模拟测试", "模拟测试", self.simulation_page, QStyle.SP_DriveHDIcon),
            ]),
            ("历史数据", [
                ("开奖走势", "开奖走势", self.trend_page, QStyle.SP_FileDialogDetailedView),
                ("遗漏统计", "遗漏统计", self.omission_page, QStyle.SP_FileDialogDetailedView),
                ("冷热分析", "冷热分析", self.hot_cold_page, QStyle.SP_FileDialogDetailedView),
                ("长龙统计", "长龙统计", self.long_dragon_stats_page, QStyle.SP_FileDialogDetailedView),
            ]),
            ("", [
                ("设置", "设置", self.settings_page, QStyle.SP_FileDialogDetailedView),
            ]),
        ]
        self.page_indices: dict[str, int] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for section_index, (section_name, section_pages) in enumerate(visible_sections):
            if section_name:
                section_label = QLabel(section_name)
                section_label.setObjectName("NavSection")
                nav.addWidget(section_label)
            elif section_index:
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setObjectName("NavSeparator")
                nav.addWidget(separator)
            for page_name, label, page, icon_kind in section_pages:
                index = self.stack.addWidget(page)
                self.page_indices[page_name] = index
                button = QPushButton(label)
                button.setObjectName("NavButton")
                button.setIcon(self.style().standardIcon(icon_kind))
                button.setIconSize(QSize(16, 16))
                button.setCheckable(True)
                button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
                group.addButton(button, index)
                self.nav_buttons.append(button)
                nav.addWidget(button)
                if page_name == "首页":
                    button.setChecked(True)

        # Legacy pages stay available to existing callers, but are hidden from
        # the final primary navigation. No page implementation is deleted.
        hidden_pages = {
            "策略研究": self.strategy_research_page,
            "策略配置": self.strategy_page,
            "开奖统计": self.lottery_stats_page,
            "历史走势": self.history_trend_page,
            "历史数据旧版": self.history_page,
            "数据管理": self.data_page,
        }
        for name, page in hidden_pages.items():
            self.page_indices[name] = self.stack.addWidget(page)
        self.stack.addWidget(self.interface_settings_page)
        self.page_indices["界面设置"] = self.stack.indexOf(self.interface_settings_page)
        nav.addStretch()
        connection = QLabel("●  数据层已连接")
        self.connection_label = connection
        connection.setObjectName("SuccessText")
        connection.setVisible(False)
        nav.addWidget(connection)
        version = QLabel(f"v{APP_VERSION}")
        self.version_label = version
        version.setObjectName("Muted")
        version.setAlignment(Qt.AlignLeft)
        version.setVisible(False)
        nav.addWidget(version)
        layout.addWidget(sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("TopBar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(20, 10, 20, 10)
        topbar_layout.setSpacing(10)
        self.topbar_title = QLabel("无忧28")
        self.topbar_title.setObjectName("TopBarTitle")
        self.topbar_page = QLabel("首页")
        self.topbar_page.setObjectName("TopBarPage")
        topbar_layout.addWidget(self.topbar_title)
        topbar_layout.addWidget(self.topbar_page)
        topbar_layout.addStretch()
        self.topbar_status = QLabel("正式数据 · 只读")
        self.topbar_status.setObjectName("TopBarStatus")
        topbar_layout.addWidget(self.topbar_status)
        self.topbar_refresh = QPushButton("更新")
        self.topbar_refresh.setObjectName("TopBarAction")
        self.topbar_refresh.setToolTip("刷新当前页面")
        self.topbar_refresh.clicked.connect(self._refresh_current_page)
        topbar_layout.addWidget(self.topbar_refresh)
        self.topbar_more = QPushButton("更多")
        self.topbar_more.setObjectName("TopBarAction")
        self.topbar_more.setToolTip("更多页面操作")
        self.topbar_more.clicked.connect(lambda: self.statusBar().showMessage("当前页面使用正式只读数据", 3000))
        topbar_layout.addWidget(self.topbar_more)
        content_layout.addWidget(topbar)
        content_layout.addWidget(self.stack, 1)
        layout.addWidget(content, 1)
        apply_formal_theme(self, self.ui_config)

        self.data_page.data_changed.connect(self.refresh_all)
        self.history_page.data_changed.connect(self.refresh_all)
        self.strategy_page.data_changed.connect(self.refresh_all)
        self.strategy_lab_page.data_changed.connect(self.refresh_all)
        self.strategy_experiment_page.data_changed.connect(self.refresh_all)
        self.strategy_auto_page.data_changed.connect(self.refresh_all)
        self.settings_page.settings_changed.connect(self.refresh_all)
        self.settings_page.interface_settings_requested.connect(self._show_interface_settings)
        settings_shortcut = QShortcut(QKeySequence('Alt+S'), self)
        settings_shortcut.activated.connect(lambda: self.show_page_by_name('设置'))
        self.home_page.navigate_requested.connect(self.show_page_by_name)
        if not self.ui_only:
            # These scans can touch the database. Schedule them after the
            # first frame is shown so they cannot delay window creation.
            QTimer.singleShot(0, self._run_post_show_checks)
            QTimer.singleShot(350, self.yu28_controller.start)
        else:
            self.statusBar().showMessage("已连接正式数据读取层", 8000)

    def _show_page(self, index: int) -> None:
        if index != self.page_indices['首页'] and self.interface_settings_page.model.edit_mode:
            self.interface_settings_page.exit_edit_mode()
        self.stack.setCurrentIndex(index)
        self._update_topbar(index)
        page = self.stack.currentWidget()
        # 首页数据 is loaded once in the background. Re-entering it only
        # changes the visible page; the toolbar refresh performs a forced read.
        if page is not self.home_page:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
        if page is self.settings_page and self.ui_only:
            self._disable_ui_only_settings()

    def _update_topbar(self, index: int) -> None:
        for name, page_index in self.page_indices.items():
            if page_index == index:
                self.topbar_page.setText(name)
                return

    def _refresh_current_page(self) -> None:
        page = self.stack.currentWidget()
        if page is self.home_page:
            self.home_page.refresh(force=True)
            return
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _show_interface_settings(self) -> None:
        self.stack.setCurrentWidget(self.interface_settings_page)
        self._update_topbar(self.stack.currentIndex())

    def refresh_all(self) -> None:
        # Hidden pages refresh on navigation.
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _disable_ui_only_settings(self) -> None:
        # Only the interface group is actionable in the independent frontend.
        for section in self.settings_page.findChildren(QGroupBox):
            if section.title() != "界面设置":
                section.setEnabled(False)
        for button in self.settings_page.findChildren(QPushButton):
            if button.text() == "保存设置":
                button.setEnabled(False)

    def _run_post_show_checks(self) -> None:
        task = _StartupChecksTask(
            self.database.path,
            BACKUP_DIR,
        )
        self._startup_checks_task = task
        _ACTIVE_STARTUP_TASKS.add(task)
        task.signals.finished.connect(self._on_post_show_checks_finished)
        task.signals.finished.connect(
            lambda _value, item=task: _ACTIVE_STARTUP_TASKS.discard(item)
        )
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _on_post_show_checks_finished(self, result: dict) -> None:
        backup = result.get("backup")
        backup_error = result.get("backup_error")
        if backup:
            self.statusBar().showMessage(f"今日数据库已自动备份：{backup.name}", 7000)
        elif backup_error:
            self.statusBar().showMessage(f"自动备份失败：{backup_error}", 9000)

    def show_page_by_name(self, name: str) -> None:
        aliases = {
            "策略研究": "智能选法",
            "历史分析": "开奖走势",
            "走势图": "开奖走势",
            "遗漏分析": "遗漏统计",
        }
        name = aliases.get(name, name)
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

    def closeEvent(self, event) -> None:
        self.yu28_controller.stop()
        super().closeEvent(event)
