"""Shared desktop palette: violet navigation and quiet dark work surfaces."""
from PySide6.QtGui import QColor, QPalette, QFont, QFontDatabase
from app.core.runtime_paths import resource_path


STYLESHEET = """QWidget { color: #f1f0fa; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QStackedWidget { background: #1d1f2b; }
QWidget#workspace { background: #1d1f2b; }
QFrame#rail { background: #7659d5; border: 0; }
QFrame#sidebar { background: #252735; border: 0; }
QLabel#sidebarBrand { font-size: 22px; font-weight: 800; }
QLabel#eyebrow { color: #a5a7ba; font-size: 10px; font-weight: 700; }
QPushButton { background: #323447; border: 1px solid #3b3d52; border-radius: 9px; padding: 10px 16px; font-weight: 600; min-height: 18px; }
QPushButton:hover { background: #3e4057; border-color: #8d76e4; }
QPushButton:pressed, QPushButton:checked { background: #7659d5; border-color: #947ce8; color: white; }
QPushButton:disabled { color: #85879d; background: #292b3a; border-color: #303244; }
QPushButton[primary="true"] { background: #7659d5; border-color: #7659d5; color: white; }
QPushButton[primary="true"]:hover { background: #876be0; }
QPushButton#navButton { text-align: left; padding: 13px 12px; border: 0; background: transparent; }
QPushButton#navButton:checked { background: #38324f; color: #c5b6ff; }
QPushButton#navButton:hover { background: #303244; }
QPushButton#railButton { background: transparent; border: 0; font-size: 20px; padding: 10px 5px; }
QPushButton#railButton:hover { background: #896de0; }
QFrame#moduleCard, QGroupBox { background: #252735; border: 1px solid #303244; border-radius: 14px; }
QFrame#moduleCard QLabel { background: transparent; border: 0; }
QGroupBox { margin-top: 14px; padding: 18px 12px 10px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 5px; color: #b8b5ce; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit { background: #20222f; color: #f1f0fa; border: 1px solid #3b3d52; border-radius: 8px; padding: 8px; selection-background-color: #7659d5; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus { border-color: #9a83ed; }
QComboBox QAbstractItemView { background: #292b3a; color: #f1f0fa; selection-background-color: #7659d5; }
QTableWidget, QTableView { background: #252735; alternate-background-color: #2b2d3d; gridline-color: #383a4e; color: #f1f0fa; border: 1px solid #383a4e; border-radius: 8px; selection-background-color: #514174; selection-color: white; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background: #303244; color: #c8c5dc; padding: 9px; border: 0; border-right: 1px solid #3b3d52; font-weight: 600; }
QProgressBar { background: #323447; border: 0; border-radius: 6px; min-height: 12px; text-align: center; color: #f1f0fa; }
QProgressBar::chunk { background: #8a6de1; border-radius: 6px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #20222f; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #49445f; min-height: 24px; border-radius: 5px; }
QScrollBar:horizontal { background: #20222f; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #49445f; min-width: 24px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QStatusBar { background: #1d1f2b; color: #a5a7ba; }
QToolTip { background: #38324f; color: #f1f0fa; border: 1px solid #8d76e4; padding: 6px; }
QTabWidget::pane { border: 1px solid #383a4e; background: #252735; }
QTabBar::tab { background: #303244; padding: 10px 16px; }
QTabBar::tab:selected { background: #7659d5; }
QMenu { background: #292b3a; border: 1px solid #49445f; }
QMenu::item:selected { background: #514174; }
"""


def apply_theme(app):
    family = 'Segoe UI'
    if not app.property('smartpostFontFamily'):
        font_id = QFontDatabase.addApplicationFont(str(resource_path('assets/fonts/InterVariable.ttf')))
        families = QFontDatabase.applicationFontFamilies(font_id)
        app.setProperty('smartpostFontFamily', families[0] if families else family)
    family = app.property('smartpostFontFamily')
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in (
        (QPalette.Window, '#1d1f2b'), (QPalette.WindowText, '#f1f0fa'),
        (QPalette.Base, '#20222f'), (QPalette.AlternateBase, '#2b2d3d'),
        (QPalette.Text, '#f1f0fa'), (QPalette.Button, '#323447'),
        (QPalette.ButtonText, '#f1f0fa'), (QPalette.Highlight, '#7659d5'),
        (QPalette.HighlightedText, '#ffffff'), (QPalette.Link, '#c5b6ff'),
        (QPalette.ToolTipBase, '#38324f'), (QPalette.ToolTipText, '#f1f0fa'),
        (QPalette.PlaceholderText, '#a5a7ba'),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setFont(QFont(family, 10))
    app.setStyleSheet(STYLESHEET.replace('Segoe UI', family))
