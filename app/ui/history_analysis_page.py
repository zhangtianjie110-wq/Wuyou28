from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .widgets import PageHeader


class HistoryAnalysisPage(QWidget):
    """Single user-facing entry point for the existing history analysis pages."""

    def __init__(self, trend_page, omission_page, hot_cold_page, long_dragon_page, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(5)
        layout.addWidget(PageHeader("历史分析", "走势、遗漏、冷热与长龙的历史数据观察"))
        self.tabs = QTabWidget()
        self.tabs.setObjectName("HistoryAnalysisTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setContentsMargins(0, 0, 0, 0)
        self.tabs.tabBar().setFixedHeight(36)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet(
            "QTabWidget#HistoryAnalysisTabs::pane { border: 0; }"
            "QTabBar::tab { min-height: 32px; padding: 5px 16px; "
            "border: 0; border-radius: 7px; margin-right: 4px; }"
            "QTabBar::tab:selected { background: #DCEEFF; color: #1266B5; }"
        )
        self._pages = {}
        for tab_label, page_name, page in (
            ("走势", "开奖走势", trend_page),
            ("遗漏", "遗漏统计", omission_page),
            ("冷热", "冷热分析", hot_cold_page),
            ("长龙", "长龙统计", long_dragon_page),
        ):
            self._pages[page_name] = page
            self.tabs.addTab(page, tab_label)
        layout.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._refresh_current)

    def _refresh_current(self, index: int) -> None:
        page = self.tabs.widget(index)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def select_tab(self, page_name: str) -> None:
        page = self._pages.get(page_name)
        if page is not None:
            self.tabs.setCurrentWidget(page)

    def refresh(self) -> None:
        self._refresh_current(self.tabs.currentIndex())
