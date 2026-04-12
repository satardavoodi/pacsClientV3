from pathlib import Path

from aipacs_runtime import is_module_enabled
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QWidget, QLabel, QVBoxLayout
from .server_settings import ServerSettingsWidget
from .tools_settings_ui import ToolsSettingsWidget
from .viewerconfigsetting import ModalityGridConfigWidget
from .filter_config import FilterConfigWidget
from .installation_module_settings import InstallationModuleSettingsWidget
class SettingsTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super(SettingsTabWidget, self).__init__(parent)
        self.setup_ui()
        self.tabBar().setUsesScrollButtons(True)
        self.tabBar().setElideMode(Qt.ElideRight)
        self.tabBar().setExpanding(False)
        self.apply_dark_theme()  # ✅ NEW: dark theme only for Settings area

    def setup_ui(self):
        self.server_settings = ServerSettingsWidget()
        self.tools_settings = ToolsSettingsWidget()
        self.viewer_config=ModalityGridConfigWidget()
        self.image_filter=FilterConfigWidget()
        self.lightviewer_settings = None
        self.echomind_settings = None
        self.installation_module_settings = InstallationModuleSettingsWidget()
        self.tab2 = QWidget()

        self.addTab(self.server_settings, 'Server Settings')
        self.addTab(self.tools_settings, 'Tools Settings')
        #self.addTab(self.tab2, 'Tab 2')
        self.addTab(self.viewer_config,"Viewer Configuration")
        self.addTab(self.image_filter,"Image Filter")
        self.addTab(self.installation_module_settings, "Installation & Updates")

        if is_module_enabled("run_cd"):
            from .lightviewer_settings import LightViewerSettingsWidget

            self.lightviewer_settings = LightViewerSettingsWidget()
            self.addTab(self.lightviewer_settings, "Light Viewer")
        if is_module_enabled("echomind"):
            from .echomind_settings import EchoMindSettingsWidget

            self.echomind_settings = EchoMindSettingsWidget()
            self.addTab(self.echomind_settings, "EchoMind")
        # start ui
        self.tab2_ui()

    def apply_dark_theme(self):
        """
        Dark theme scoped to SettingsTabWidget only (does not affect the rest of app).
        """
        self.setObjectName("SettingsTabWidget")
        arrow_icon = Path("Qss/icons/fefefe/material_design/keyboard_arrow_down.png").resolve().as_posix()
        style = """
            QTabWidget#SettingsTabWidget {
                background: #0b0d10;
                color: #e5e7eb;
            }
            QTabWidget#SettingsTabWidget QWidget {
                background: #0b0d10;
                color: #e5e7eb;
            }

            QTabWidget#SettingsTabWidget::pane {
                border: 1px solid #232a33;
                border-radius: 12px;
                background: #0b0d10;
                top: -1px;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab {
                background: #243041;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-bottom: none;
                border-radius: 8px 8px 0 0;
                padding: 11px 20px;
                margin-right: 3px;
                font-size: 14px;
                min-width: 120px;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab:selected {
                background: #3b82f6;
                color: #ffffff;
                border-color: #3b82f6;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab:hover:!selected {
                background: #2b3a4e;
                color: #f3f4f6;
            }

            QTabWidget#SettingsTabWidget QTableWidget,
            QTabWidget#SettingsTabWidget QTableView {
                background: #0f1319;
                alternate-background-color: #111827;
                gridline-color: #232a33;
                border: 1px solid #232a33;
                border-radius: 10px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTabWidget#SettingsTabWidget QHeaderView::section {
                background: #10141a;
                color: #e5e7eb;
                padding: 6px 8px;
                border: 1px solid #232a33;
                font-weight: 700;
            }
            QTabWidget#SettingsTabWidget QTableCornerButton::section {
                background: #10141a;
                border: 1px solid #232a33;
            }

            QTabWidget#SettingsTabWidget QLabel {
                font-size: 14px;
            }
            QTabWidget#SettingsTabWidget QGroupBox::title {
                font-size: 28px;
                font-weight: 900;
            }
            QTabWidget#SettingsTabWidget QCheckBox {
                spacing: 8px;
                font-size: 14px;
            }
            QTabWidget#SettingsTabWidget QLineEdit,
            QTabWidget#SettingsTabWidget QTextEdit,
            QTabWidget#SettingsTabWidget QPlainTextEdit {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 34px;
                font-size: 14px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTabWidget#SettingsTabWidget QLineEdit:focus,
            QTabWidget#SettingsTabWidget QTextEdit:focus,
            QTabWidget#SettingsTabWidget QPlainTextEdit:focus {
                border: 1px solid #3b82f6;
            }

            QTabWidget#SettingsTabWidget QComboBox,
            QTabWidget#SettingsTabWidget QSpinBox,
            QTabWidget#SettingsTabWidget QDoubleSpinBox {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 5px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QTabWidget#SettingsTabWidget QComboBox {
                padding-right: 34px;
            }
            QTabWidget#SettingsTabWidget QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                border-left: 1px solid #2b313b;
                width: 28px;
            }
            QTabWidget#SettingsTabWidget QComboBox::down-arrow {
                image: url(__ARROW__);
                width: 14px;
                height: 14px;
            }
            QTabWidget#SettingsTabWidget QComboBox QAbstractItemView {
                background: #0f1319;
                color: #e5e7eb;
                border: 1px solid #232a33;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }

            QTabWidget#SettingsTabWidget QGroupBox {
                border: 1px solid #232a33;
                border-radius: 12px;
                margin-top: 28px;
                padding: 18px 20px 18px 20px;
                padding-top: 44px;
                background: #10141a;
            }
            QTabWidget#SettingsTabWidget QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                top: 2px;
                padding: 6px 16px;
                color: #f3f4f6;
                background: #0f1319;
                border: 1px solid #232a33;
                border-radius: 11px;
            }

            QTabWidget#SettingsTabWidget QPushButton {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QTabWidget#SettingsTabWidget QPushButton:hover {
                background: #252d3d;
                border-color: #3b82f6;
            }
            QTabWidget#SettingsTabWidget QPushButton:pressed {
                background: #162033;
            }
            QTabWidget#SettingsTabWidget QPushButton:disabled {
                background: rgba(27, 34, 48, 0.45);
                color: rgba(229, 231, 235, 0.4);
                border-color: rgba(43, 49, 59, 0.5);
            }

            QTabWidget#SettingsTabWidget QSlider::groove:horizontal {
                background: #2b313b;
                height: 6px;
                border-radius: 3px;
            }
            QTabWidget#SettingsTabWidget QSlider::handle:horizontal {
                background: #3b82f6;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }

            QTabWidget#SettingsTabWidget QFrame[frameShape="4"],
            QTabWidget#SettingsTabWidget QFrame[frameShape="5"] {
                color: #232a33;
                border: none;
            }

            QTabWidget#SettingsTabWidget QScrollBar:vertical {
                background: #0f1319;
                width: 12px;
                margin: 0px;
                border: 1px solid #232a33;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:vertical {
                background: #2b313b;
                min-height: 24px;
                border-radius: 6px;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:vertical:hover {
                background: #334155;
            }
            QTabWidget#SettingsTabWidget QScrollBar::add-line:vertical,
            QTabWidget#SettingsTabWidget QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QTabWidget#SettingsTabWidget QScrollBar:horizontal {
                background: #0f1319;
                height: 12px;
                margin: 0px;
                border: 1px solid #232a33;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:horizontal {
                background: #2b313b;
                min-width: 24px;
                border-radius: 6px;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:horizontal:hover {
                background: #334155;
            }
            QTabWidget#SettingsTabWidget QScrollBar::add-line:horizontal,
            QTabWidget#SettingsTabWidget QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """
        self.setStyleSheet(style.replace("__ARROW__", arrow_icon))

    def on_ai_servers_saved(self, services: dict):
        print("AI servers updated:", services)

    def tab2_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel('page 2. w1'))
        layout.addWidget(QLabel('page 2. w2'))
        self.tab2.setLayout(layout)


