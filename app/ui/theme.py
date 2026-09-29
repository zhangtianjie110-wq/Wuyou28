# Shared typography contract.  Widgets use object names below so the same
# hierarchy applies to every page, including lazily-created views.
FONT_TEXT = '"Microsoft YaHei", "微软雅黑", "Segoe UI"'
# Kept as a compatibility alias for callers that import the old constant.
FONT_NUMBER = FONT_TEXT
Font_Title = 22
Font_Section = 16
Font_Card_Title = 14
Font_Number_Large = 32
Font_Number = 18
Font_Table_Header = 14
Font_Table_Content = 14
Font_Tip = 14


APP_STYLE = """
QMainWindow, QWidget { background: #F5F7FA; color: #1F2937; font-family: "Microsoft YaHei", "微软雅黑", "Segoe UI"; font-size: 14px; }
QStackedWidget { background: #FFFFFF; }
QFrame#Sidebar { background: #EAF1F8; border: 0; border-right: 1px solid #D4DFEB; }
QFrame#TopBar { background: #FFFFFF; border-bottom: 1px solid #E2E8F0; }
QLabel#TopBarTitle { color: #172033; font-size: 16px; font-weight: 700; }
QLabel#TopBarPage { color: #7D8799; font-size: 14px; }
QLabel#TopBarStatus { color: #16834B; background: #EAF8F1; border-radius: 10px; padding: 4px 9px; font-size: 14px; }
QPushButton#TopBarAction { background: #F5F8FC; color: #1266B5; border: 1px solid #D8E4F2; border-radius: 8px; padding: 6px 12px; min-height: 34px; font-size: 15px; }
QPushButton#TopBarAction:hover { background: #EAF3FF; }
QFrame#BrandIcon { background: #2688F5; border-radius: 13px; }
QLabel#BrandNumber { color: white; font-size: 22px; font-weight: 700; }
QLabel#AppTitle { font-size: 19px; font-weight: 700; color: #172033; }
QLabel#HomeBrand { color: #172033; font-size: 21px; font-weight: 700; }
QLabel#HomePageLabel { color: #7D8799; font-size: 14px; padding-left: 8px; }
QLabel#PageTitle { font-size: 22px; font-weight: 650; color: #172033; }
QFrame#PageHeader { background: transparent; }
QLabel#PageHeaderTitle { font-size: 22px; font-weight: 700; color: #172033; }
QLabel#PageHeaderSubtitle { color: #7D8799; font-size: 14px; }
QLabel#PageHeaderMeta { color: #7D8799; font-size: 14px; }
QLabel#PageHeaderStatus { color: #16834B; background: #EAF8F1; border-radius: 10px; padding: 4px 9px; font-size: 14px; }
QLabel#PageHint, QLabel#Muted { color: #7D8799; }
QLabel#UpdateTime { color: #7D8799; font-size: 14px; }
QLabel#SectionTitle { color: #20293A; font-size: 16px; font-weight: 700; }
QLabel#StatusOnline { color: #16A56A; background: #EAF8F1; border-radius: 12px; padding: 6px 11px; font-weight: 600; }
QPushButton#NavButton { border: 0; border-radius: 8px; padding: 7px 10px; min-height: 36px; text-align: left; color: #526176; background: transparent; font-size: 15px; font-weight: 550; }
QPushButton#NavButton:hover { background: #F2F7FD; color: #1478E5; }
QPushButton#NavButton:checked { background: #D6E5F8; color: #0B70DB; font-weight: 650; border-left: 2px solid #2688F5; }
QFrame#Card, QFrame#Panel { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
QFrame#SettingsSidebar { background: #F7F9FC; border: 1px solid #E2E8F0; border-radius: 10px; }
QPushButton#SettingsNavButton { background: transparent; color: #526176; border: 0; border-radius: 7px; padding: 8px 10px; text-align: left; font-weight: 550; }
QPushButton#SettingsNavButton:hover { background: #EAF3FF; color: #1478E5; }
QPushButton#SettingsNavButton:checked { background: #DCEEFF; color: #1266B5; font-weight: 650; }
QFrame#DrawBar { background: #FFFFFF; border: 1px solid #D9E4F0; border-radius: 10px; }
QFrame#NextDrawPanel { background: #FFFFFF; border: 1px solid #D9E4F0; border-radius: 10px; }
QLabel#NextRealtime { color: #1266B5; background: #EAF3FF; border-radius: 9px; padding: 3px 8px; font-size: 14px; font-weight: 650; }
QLabel#NextCountdown { color: #172033; font-size: 32px; font-weight: 700; letter-spacing: 0px; }
QLabel#NextDrawTime { color: #7D8799; font-size: 14px; }
QFrame#VipStatusPanel { background: #FFFFFF; border: 1px solid #D9E4F0; border-radius: 10px; }
QLabel#VipPanelTitle { color: #172033; font-size: 14px; font-weight: 650; }
QLabel#VipPanelMeta { color: #7D8799; font-size: 14px; }
QLabel#VipPanelNumber { color: #344054; font-size: 18px; font-weight: 650; }
QLabel#VipCountValue { color: #1D5FA7; font-size: 32px; font-weight: 700; }
QLabel#VipCountTotal { color: #9AA4B4; font-size: 16px; }
QFrame#VipGroupCellBig, QFrame#VipGroupCellSmall { background: #FBFCFE; border: 1px solid #E2E8F0; border-radius: 2px; }
QLabel#VipGroupTitleBig { color: #D45757; font-size: 14px; }
QLabel#VipGroupValueBig { color: #C84747; font-size: 18px; font-weight: 650; }
QLabel#VipGroupTitleSmall { color: #3C77C6; font-size: 14px; }
QLabel#VipGroupValueSmall { color: #2868B6; font-size: 18px; font-weight: 650; }
QFrame#HomeMetric { background: #F8FAFD; border: 1px solid #E2E8F0; border-radius: 8px; }
QLabel#HomeMetricTitle { color: #7D8799; font-size: 14px; }
QLabel#HomeMetricValue { color: #172033; font-size: 18px; font-weight: 700; }
QPushButton#HomeQuickButton { background: #EAF3FF; color: #1266B5; border: 1px solid #CFE3FA; border-radius: 8px; padding: 11px 12px; font-weight: 650; }
QPushButton#HomeQuickButton:hover { background: #DCEEFF; border-color: #AFCFF0; }
QLabel#BarCaption { color: #7D8799; font-size: 14px; }
QLabel#DrawIssue { color: #172033; font-size: 18px; font-weight: 700; }
QLabel#DrawBall { background: #EAF3FF; color: #1266B5; border: 1px solid #CFE3FA; border-radius: 23px; font-size: 32px; font-weight: 700; }
QLabel#DrawEquals { color: #7D8799; font-size: 18px; }
QLabel#DrawTotal { color: #172033; font-size: 24px; font-weight: 700; }
QLabel#DrawTags { color: #344054; font-size: 14px; font-weight: 650; }
QLabel#NextIssue { color: #FFFFFF; font-size: 18px; font-weight: 650; }
QFrame#EngineStatusLine { background: #FFFFFF; border: 1px solid #E1E8F0; border-radius: 7px; }
QLabel#StatusToken { color: #526176; background: #F7F9FC; border-radius: 4px; padding: 3px 5px; font-size: 14px; }
QFrame#WorkPanel, QFrame#SummaryPanel { background: #FFFFFF; border: 1px solid #E1E7EF; border-radius: 8px; }
QLabel#SummaryCaption { color: #7D8799; font-size: 14px; }
QLabel#SummaryValue { color: #243247; font-size: 16px; font-weight: 650; }
QFrame#TrendMetricCard { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
QFrame#StrategyAnalysisCard, QFrame#StrategyFeaturedCard, QFrame#StrategyObserveCard, QFrame#StrategyDetailCard { background: #FFFFFF; border: 1px solid #DCE4EE; border-radius: 8px; }
QFrame#StrategyResultCard, QFrame#StrategyObserveItem { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 7px; }
QLabel#StrategyCardTitle, QLabel#StrategySectionTitle { color: #20293A; font-size: 18px; font-weight: 700; }
QLabel#StrategyFeaturedTitle { color: #172033; font-size: 18px; font-weight: 700; }
QLabel#StrategyCardName { color: #243247; font-size: 15px; font-weight: 650; }
QLabel#StrategyRank { color: #1478E5; font-size: 16px; font-weight: 700; min-width: 48px; }
QFrame#StrategyMetric { background: #F8FAFD; border: 1px solid #E8EDF4; border-radius: 6px; }
QLabel#StrategyMetricTitle { color: #7D8799; font-size: 14px; }
QLabel#StrategyMetricValue { color: #172033; font-size: 18px; font-weight: 700; }
QLabel#StrategyStatusBadge { color: #1266B5; background: #EAF3FF; border-radius: 9px; padding: 4px 8px; font-size: 14px; font-weight: 650; }
QLabel#StrategyScore { color: #1478E5; font-size: 16px; font-weight: 700; }
QPushButton#PrimaryAction { background: #1E74D6; color: white; border-radius: 8px; padding: 8px 15px; min-height: 34px; font-size: 15px; font-weight: 650; }
QPushButton#PrimaryAction:hover { background: #155FB7; }
QLabel#TrendMetricTitle { color: #7D8799; font-size: 14px; }
QLabel#TrendMetricValue { color: #172033; font-size: 18px; font-weight: 700; }
QFrame#MetricBlue, QFrame#MetricGreen, QFrame#MetricOrange, QFrame#MetricPurple { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
QLabel#MetricIcon { font-size: 25px; font-weight: 650; }
QLabel#CardTitle { color: #667085; font-size: 14px; }
QLabel#CardValue { color: #172033; font-size: 18px; font-weight: 650; }
QLabel#BigNumber, QLabel#StatNumber { color: #172033; font-size: 18px; font-weight: 700; }
QLabel#StatusValue { color: #18A66A; font-size: 18px; font-weight: 600; }
QLabel#CardSubtitle { color: #8B95A7; font-size: 14px; }
QLabel#SuccessText { color: #16A56A; font-weight: 600; }
QLabel#WarningText { color: #E58019; font-weight: 600; }
QLabel#DangerText { color: #D84C4C; font-weight: 600; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #FFFFFF; border: 1px solid #D9E1EC; border-radius: 8px; padding: 6px 9px; min-height: 22px; font-size: 15px; selection-background-color: #2F80ED; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #2F80ED; }
QPushButton { background: #1686F8; color: white; border: 0; border-radius: 8px; padding: 8px 14px; min-height: 34px; font-size: 15px; font-weight: 550; }
QPushButton:hover { background: #0878E8; }
QPushButton:pressed { background: #0869C9; }
QPushButton:disabled { background: #D7DEE9; color: #97A1B2; }
QPushButton[secondary="true"] { background: #EEF1F6; color: #465269; }
QPushButton[secondary="true"]:hover { background: #E3E8F0; }
QPushButton[danger="true"] { background: #FFF0F0; color: #C74343; }
QPushButton[accent="purple"] { background: #7C52EE; }
QPushButton[accent="green"] { background: #24B879; }
QPushButton[accent="orange"] { background: #FF8A34; }
QTableWidget { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 7px; gridline-color: transparent; alternate-background-color: #FBFCFE; font-size: 14px; }
QTableWidget#DrawHistoryTable { border: 1px solid #D7E0EA; gridline-color: #D7E0EA; }
QTableWidget#DrawHistoryTable::item { border-right: 1px solid #E5EBF2; border-bottom: 1px solid #E5EBF2; padding: 4px 6px; }
QTableWidget::item { padding: 5px 8px; border-bottom: 1px solid #F0F2F6; font-size: 14px; }
QTableWidget[number_style="true"]::item { font-size: 14px; font-weight: 600; }
QTableWidget::item:selected { background: #E7F2FF; color: #24517A; }
QHeaderView::section { background: #F7F9FC; color: #667085; border: 0; border-bottom: 1px solid #E7EDF4; padding: 7px; font-size: 14px; font-weight: 600; }
QGroupBox { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; margin-top: 12px; padding: 14px 12px 12px 12px; font-size: 15px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 7px; }
QListWidget { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; outline: 0; padding: 5px; }
QListWidget::item { border-radius: 9px; padding: 10px; margin: 2px; }
QListWidget::item:selected { background: #E7F2FF; color: #166EC8; }
QScrollArea { border: 0; background: transparent; }
QTabWidget#HistoryAnalysisTabs::pane { border: 0; background: transparent; }
QTabBar::tab { background: #F5F8FC; color: #667085; border: 0; border-radius: 7px; padding: 8px 18px; margin-right: 5px; font-size: 15px; }
QTabBar::tab:selected { background: #DCEEFF; color: #1266B5; font-weight: 650; }
QStatusBar { background: #FFFFFF; color: #7D8799; }
QSplitter::handle { background: transparent; width: 8px; }
"""
