APP_STYLE = """
QMainWindow, QWidget { background: #F3F6FA; color: #1F2937; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QFrame#Sidebar { background: #FFFFFF; border: 0; border-right: 1px solid #E3EAF2; }
QFrame#BrandIcon { background: #2688F5; border-radius: 13px; }
QLabel#BrandNumber { color: white; font-size: 22px; font-weight: 700; }
QLabel#AppTitle { font-size: 19px; font-weight: 700; color: #172033; }
QLabel#HomeBrand { color: #172033; font-size: 21px; font-weight: 700; }
QLabel#HomePageLabel { color: #7D8799; font-size: 13px; padding-left: 8px; }
QLabel#PageTitle { font-size: 24px; font-weight: 650; color: #172033; }
QLabel#PageHint, QLabel#Muted { color: #7D8799; }
QLabel#UpdateTime { color: #7D8799; font-size: 12px; }
QLabel#SectionTitle { color: #20293A; font-size: 15px; font-weight: 600; }
QLabel#StatusOnline { color: #16A56A; background: #EAF8F1; border-radius: 12px; padding: 6px 11px; font-weight: 600; }
QPushButton#NavButton { border: 0; border-radius: 7px; padding: 7px 9px; min-height: 38px; text-align: left; color: #48566D; background: transparent; font-size: 13px; font-weight: 550; }
QPushButton#NavButton:hover { background: #F2F7FD; color: #1478E5; }
QPushButton#NavButton:checked { background: #EAF3FF; color: #0B70DB; font-weight: 650; }
QFrame#Card, QFrame#Panel { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
QFrame#DrawBar { background: #FFFFFF; border: 1px solid #D9E4F0; border-radius: 10px; }
QLabel#BarCaption { color: #7D8799; font-size: 11px; }
QLabel#DrawIssue { color: #172033; font-size: 20px; font-weight: 700; }
QLabel#DrawBall { background: #EAF3FF; color: #1266B5; border: 1px solid #CFE3FA; border-radius: 23px; font-size: 25px; font-weight: 700; }
QLabel#DrawEquals { color: #7D8799; font-size: 20px; }
QLabel#DrawTotal { color: #172033; font-size: 27px; font-weight: 700; }
QLabel#DrawTags { color: #344054; font-size: 13px; font-weight: 650; }
QLabel#NextIssue { color: #344054; font-size: 17px; font-weight: 650; }
QFrame#EngineStatusLine { background: #FFFFFF; border: 1px solid #E1E8F0; border-radius: 7px; }
QLabel#StatusToken { color: #526176; background: #F7F9FC; border-radius: 4px; padding: 3px 5px; font-size: 12px; }
QFrame#WorkPanel, QFrame#SummaryPanel { background: #FFFFFF; border: 1px solid #E1E7EF; border-radius: 8px; }
QLabel#SummaryCaption { color: #7D8799; font-size: 12px; }
QLabel#SummaryValue { color: #243247; font-size: 14px; font-weight: 650; }
QFrame#MetricBlue, QFrame#MetricGreen, QFrame#MetricOrange, QFrame#MetricPurple { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }
QLabel#MetricIcon { font-size: 25px; font-weight: 650; }
QLabel#CardTitle { color: #667085; font-size: 13px; }
QLabel#CardValue { color: #172033; font-size: 24px; font-weight: 650; }
QLabel#StatusValue { color: #18A66A; font-size: 14px; font-weight: 600; }
QLabel#CardSubtitle { color: #8B95A7; font-size: 11px; }
QLabel#SuccessText { color: #16A56A; font-weight: 600; }
QLabel#WarningText { color: #E58019; font-weight: 600; }
QLabel#DangerText { color: #D84C4C; font-weight: 600; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #FFFFFF; border: 1px solid #D9E1EC; border-radius: 8px; padding: 6px 9px; min-height: 22px; selection-background-color: #2F80ED; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #2F80ED; }
QPushButton { background: #1686F8; color: white; border: 0; border-radius: 8px; padding: 8px 14px; font-weight: 550; }
QPushButton:hover { background: #0878E8; }
QPushButton:pressed { background: #0869C9; }
QPushButton:disabled { background: #D7DEE9; color: #97A1B2; }
QPushButton[secondary="true"] { background: #EEF1F6; color: #465269; }
QPushButton[secondary="true"]:hover { background: #E3E8F0; }
QPushButton[danger="true"] { background: #FFF0F0; color: #C74343; }
QPushButton[accent="purple"] { background: #7C52EE; }
QPushButton[accent="green"] { background: #24B879; }
QPushButton[accent="orange"] { background: #FF8A34; }
QTableWidget { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 7px; gridline-color: transparent; alternate-background-color: #FBFCFE; }
QTableWidget::item { padding: 5px 7px; border-bottom: 1px solid #F0F2F6; }
QTableWidget::item:selected { background: #E7F2FF; color: #24517A; }
QHeaderView::section { background: #F7F9FC; color: #667085; border: 0; border-bottom: 1px solid #E7EDF4; padding: 8px; font-weight: 600; }
QGroupBox { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; margin-top: 12px; padding: 14px 12px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 7px; }
QListWidget { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; outline: 0; padding: 5px; }
QListWidget::item { border-radius: 9px; padding: 10px; margin: 2px; }
QListWidget::item:selected { background: #E7F2FF; color: #166EC8; }
QScrollArea { border: 0; background: transparent; }
QStatusBar { background: #FFFFFF; color: #7D8799; }
QSplitter::handle { background: transparent; width: 8px; }
"""
