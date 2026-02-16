from PySide6.QtWidgets import QTabWidget, QWidget, QLabel, QVBoxLayout
from .server_settings import ServerSettingsWidget
from .tools_settings_ui import ToolsSettingsWidget
from .servers_config import ServersConfigWidget
from .viewerconfigsetting import ModalityGridConfigWidget
from .filter_config import FilterConfigWidget
from .lightviewer_settings import LightViewerSettingsWidget
class SettingsTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super(SettingsTabWidget, self).__init__(parent)
        # Apply dark theme to tab widget
        self.setStyleSheet("""
            QTabWidget::pane {
                background-color: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2d3748;
                color: #e2e8f0;
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1a202c;
                color: #ffffff;
                border-bottom: 2px solid #3182ce;
            }
            QTabBar::tab:hover {
                background-color: #374151;
            }
            QWidget {
                background-color: #1a202c;
                color: #e2e8f0;
            }
        """)
        self.setup_ui()
        self.apply_dark_theme()  # ✅ NEW: dark theme only for Settings area

    def setup_ui(self):
        self.server_settings = ServerSettingsWidget()
        self.tools_settings = ToolsSettingsWidget()
        self.servers_config = ServersConfigWidget()
        self.viewer_config=ModalityGridConfigWidget()
        self.image_filter=FilterConfigWidget()
        self.lightviewer_settings = LightViewerSettingsWidget()
        self.tab2 = QWidget()

        self.servers_config.saved.connect(self.on_ai_servers_saved)

        self.addTab(self.server_settings, 'Server Settings')
        self.addTab(self.tools_settings, 'Tools Settings')
        self.addTab(self.servers_config, "Server Config")
        #self.addTab(self.tab2, 'Tab 2')
        self.addTab(self.viewer_config,"Viewer Configuration")
        self.addTab(self.image_filter,"Image Filter")
        self.addTab(self.lightviewer_settings, "Light Viewer")
        # start ui
        self.tab2_ui()

    def apply_dark_theme(self):
        """
        Dark theme scoped to SettingsTabWidget only (does not affect the rest of app).
        """
        self.setObjectName("SettingsTabWidget")

        self.setStyleSheet("""
            /* ---------- Base ---------- */
            QTabWidget#SettingsTabWidget {
                background: #1a202c;
                color: #e2e8f0;
            }
            QTabWidget#SettingsTabWidget QWidget {
                background: #1a202c;
                color: #e2e8f0;
            }

            /* ---------- Tabs (Settings internal tabs) ---------- */
            QTabWidget#SettingsTabWidget::pane {
                border: 1px solid #4a5568;
                background: #1a202c;
                top: -1px;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab {
                background: #2d3748;
                color: #a0aec0;
                border: 1px solid #4a5568;
                border-bottom: none;
                border-radius: 6px 6px 0 0;
                padding: 12px 22px;
                margin-right: 2px;
                font-size: 20px;
                min-width: 170px;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab:selected {
                background: #3182ce;
                color: #ffffff;
                border-color: #3182ce;
            }
            QTabWidget#SettingsTabWidget QTabBar::tab:hover:!selected {
                background: #4a5568;
                color: #e2e8f0;
            }

            /* ---------- Tables ---------- */
            QTabWidget#SettingsTabWidget QTableWidget,
            QTabWidget#SettingsTabWidget QTableView {
                background: #0f172a;
                alternate-background-color: #111827;
                gridline-color: #334155;
                border: 1px solid #334155;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTabWidget#SettingsTabWidget QHeaderView::section {
                background: #2d3748;
                color: #e2e8f0;
                padding: 6px 8px;
                border: 1px solid #334155;
            }
            QTabWidget#SettingsTabWidget QTableCornerButton::section {
                background: #2d3748;
                border: 1px solid #334155;
            }

            /* ---------- Inputs ---------- */
            QTabWidget#SettingsTabWidget QLineEdit,
            QTabWidget#SettingsTabWidget QTextEdit,
            QTabWidget#SettingsTabWidget QPlainTextEdit {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTabWidget#SettingsTabWidget QLineEdit:focus,
            QTabWidget#SettingsTabWidget QTextEdit:focus,
            QTabWidget#SettingsTabWidget QPlainTextEdit:focus {
                border: 1px solid #60a5fa;
            }

            QTabWidget#SettingsTabWidget QComboBox,
            QTabWidget#SettingsTabWidget QSpinBox,
            QTabWidget#SettingsTabWidget QDoubleSpinBox {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 26px;
            }
            QTabWidget#SettingsTabWidget QComboBox::drop-down {
                border-left: 1px solid #334155;
                width: 22px;
            }
            QTabWidget#SettingsTabWidget QComboBox QAbstractItemView {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }

            /* ---------- GroupBox ---------- */
            QTabWidget#SettingsTabWidget QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
                background: #111827;
            }
            QTabWidget#SettingsTabWidget QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: #e2e8f0;
            }

            /* ---------- Buttons ---------- */
            QTabWidget#SettingsTabWidget QPushButton {
                background: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 6px;
                padding: 7px 12px;
            }
            QTabWidget#SettingsTabWidget QPushButton:hover {
                background: #4a5568;
                border-color: #60a5fa;
            }
            QTabWidget#SettingsTabWidget QPushButton:pressed {
                background: #1f2937;
            }
            QTabWidget#SettingsTabWidget QPushButton:disabled {
                background: rgba(45, 55, 72, 0.5);
                color: rgba(226, 232, 240, 0.4);
                border-color: rgba(74, 85, 104, 0.5);
            }

            /* ---------- Sliders ---------- */
            QTabWidget#SettingsTabWidget QSlider::groove:horizontal {
                background: #334155;
                height: 6px;
                border-radius: 3px;
            }
            QTabWidget#SettingsTabWidget QSlider::handle:horizontal {
                background: #60a5fa;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }

            /* ---------- Separators / Frames ---------- */
            QTabWidget#SettingsTabWidget QFrame[frameShape="4"],
            QTabWidget#SettingsTabWidget QFrame[frameShape="5"] {
                color: #334155;
                border: none;
            }

            /* ---------- Scrollbars ---------- */
            QTabWidget#SettingsTabWidget QScrollBar:vertical {
                background: #0b1220;
                width: 12px;
                margin: 0px;
                border: 1px solid #334155;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:vertical {
                background: #334155;
                min-height: 24px;
                border-radius: 6px;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QTabWidget#SettingsTabWidget QScrollBar::add-line:vertical,
            QTabWidget#SettingsTabWidget QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QTabWidget#SettingsTabWidget QScrollBar:horizontal {
                background: #0b1220;
                height: 12px;
                margin: 0px;
                border: 1px solid #334155;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:horizontal {
                background: #334155;
                min-width: 24px;
                border-radius: 6px;
            }
            QTabWidget#SettingsTabWidget QScrollBar::handle:horizontal:hover {
                background: #475569;
            }
            QTabWidget#SettingsTabWidget QScrollBar::add-line:horizontal,
            QTabWidget#SettingsTabWidget QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    def on_ai_servers_saved(self, services: dict):
        print("AI servers updated:", services)

    def tab2_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel('page 2. w1'))
        layout.addWidget(QLabel('page 2. w2'))
        self.tab2.setLayout(layout)


