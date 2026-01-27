from PySide6.QtCore import (QCoreApplication, QMetaObject, QRect,
                            QSize, Qt)
from PySide6.QtGui import (QFont, QIcon, QPixmap, QCursor)
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
                               QVBoxLayout, QGridLayout, QWidget, QTabWidget, QLayout,
                               QMainWindow, QStackedWidget)

from PacsClient.utils.config import JSON_PATH, ICON_PATH
from PacsClient.utils.db_manager import init_database
from . import settings_ui
from . import home_ui
from .web_browser_ui import WebBrowserWidget


def relayout_all(widget: QWidget):
    widget.adjustSize()
    widget.updateGeometry()
    for child in widget.findChildren(QWidget):
        child.adjustSize()
        child.updateGeometry()
        try:
            layout = child.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        except Exception as e:
            print(f"[layout skip]: {child=} {e=}")


class ControlPanelInterface(QMainWindow):
    orginazationName = "AIPacs"
    applicationName = ""

    def __init__(self, parent=None, tab_widget: QTabWidget = None):
        QMainWindow.__init__(self)
        self.tab_widget = tab_widget
        self.__add_AIPacs_tab()
        self.ui = ControlPanelWindow(MainWindow=self)
        self.ui.setupUi()

        self.setWindowTitle("AIPacs")
        self.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.setContentsMargins(0, 0, 0, 0)
        if self.centralWidget() is not None:
            self.centralWidget().setContentsMargins(0, 0, 0, 0)

        self.setStyleSheet("""
            QMainWindow { background: #1a202c; border: none; }
        """)

        init_database()
        self.showMaximized()

    def __add_AIPacs_tab(self):
        self.tab_widget.addTab(self, 'AIPacs')


class ControlPanelWindow(object):

    def __init__(self, MainWindow):
        self.MainWindow: ControlPanelInterface = MainWindow
        self.size_button = QSize(22, 22)
        self._menu_expanded = False

    def connect_buttons(self):
        self.menuBtn.clicked.connect(self._toggle_menu)
        self.settingsBtn.clicked.connect(lambda: self.centerMenuContainer.setVisible(not self.centerMenuContainer.isVisible()))
        self.infoBtn.clicked.connect(lambda: self.centerMenuContainer.setVisible(not self.centerMenuContainer.isVisible()))
        self.helpBtn.clicked.connect(lambda: self.centerMenuContainer.setVisible(not self.centerMenuContainer.isVisible()))
        self.closeCenterMenuBtn.clicked.connect(lambda: self.centerMenuContainer.hide())
        self.closeRightMenuBtn.clicked.connect(lambda: self.rightMenuContainer.hide())

    def _toggle_menu(self):
        """Toggle left menu between collapsed and expanded."""
        self._menu_expanded = not self._menu_expanded
        if self._menu_expanded:
            self.leftMenuContainer.setFixedWidth(180)
        else:
            self.leftMenuContainer.setFixedWidth(50)

    def _create_menu_button(self, parent, name, icon_file, text="", tooltip=""):
        """Create a styled menu button with icon."""
        btn = QPushButton(parent)
        btn.setObjectName(name)
        
        # Load icon from file
        icon_path = str(ICON_PATH / icon_file)
        icon = QIcon(icon_path)
        btn.setIcon(icon)
        btn.setIconSize(QSize(22, 22))
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedSize(42, 42)
        btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                border-radius: 8px;
            }
        """)
        return btn

    def setup_left_menu_subcontainer(self):
        self.leftMenuContainer = QFrame(self.centralwidget)
        self.leftMenuContainer.setObjectName(u"leftMenuContainer")
        self.leftMenuContainer.setFixedWidth(50)
        self.leftMenuContainer.setStyleSheet("background-color: #2d3748; border-radius: 10px; margin: 3px;")

        self.verticalLayout = QVBoxLayout(self.leftMenuContainer)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setContentsMargins(3, 8, 3, 8)

        self.leftMenuSubContainer = QWidget(self.leftMenuContainer)
        self.verticalLayout_2 = QVBoxLayout(self.leftMenuSubContainer)
        self.verticalLayout_2.setSpacing(5)
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)

        # Menu toggle button
        self.menuBtn = self._create_menu_button(self.leftMenuSubContainer, "menuBtn", "align-justify.png", "", "Menu")
        self.verticalLayout_2.addWidget(self.menuBtn)

        self.verticalLayout.addWidget(self.leftMenuSubContainer)
        self.horizontalLayout.addWidget(self.leftMenuContainer, 0, Qt.AlignmentFlag.AlignLeft)

    def setup_left_menu(self):
        self.frame_2 = QFrame(self.leftMenuSubContainer)
        self.verticalLayout_3 = QVBoxLayout(self.frame_2)
        self.verticalLayout_3.setSpacing(5)
        self.verticalLayout_3.setContentsMargins(0, 5, 0, 5)

        # Main navigation buttons (no text, icon only)
        self.home_btn = self._create_menu_button(self.frame_2, "home_btn", "home.png", "", "Home")
        self.verticalLayout_3.addWidget(self.home_btn)

        self.dataBtn = self._create_menu_button(self.frame_2, "dataBtn", "list.png", "", "Data Analysis")
        self.verticalLayout_3.addWidget(self.dataBtn)

        self.reportBtn = self._create_menu_button(self.frame_2, "reportBtn", "printer.png", "", "View Reports")
        self.verticalLayout_3.addWidget(self.reportBtn)

        self.settings_server_btn = self._create_menu_button(self.frame_2, "settings_server_btn", "settings.png", "", "Settings")
        self.verticalLayout_3.addWidget(self.settings_server_btn)

        self.download_manager_btn = self._create_menu_button(self.frame_2, "download_manager_btn", "download.png", "", "Download Manager")
        self.verticalLayout_3.addWidget(self.download_manager_btn)

        self.web_browser_btn = self._create_menu_button(self.frame_2, "web_browser_btn", "globe.png", "", "Web Browser")
        self.verticalLayout_3.addWidget(self.web_browser_btn)

        self.verticalLayout_2.addWidget(self.frame_2)

        # Spacer
        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.verticalLayout_2.addItem(self.verticalSpacer)

        # Bottom buttons
        self.frame_3 = QFrame(self.leftMenuSubContainer)
        self.verticalLayout_4 = QVBoxLayout(self.frame_3)
        self.verticalLayout_4.setSpacing(5)
        self.verticalLayout_4.setContentsMargins(0, 5, 0, 5)

        self.settingsBtn = self._create_menu_button(self.frame_3, "settingsBtn", "grid.png", "", "Themes")
        self.verticalLayout_4.addWidget(self.settingsBtn)

        self.infoBtn = self._create_menu_button(self.frame_3, "infoBtn", "info.png", "", "Information")
        self.verticalLayout_4.addWidget(self.infoBtn)

        self.helpBtn = self._create_menu_button(self.frame_3, "helpBtn", "help-circle.png", "", "Get help")
        self.verticalLayout_4.addWidget(self.helpBtn)

        self.verticalLayout_2.addWidget(self.frame_3)

    def setupUi(self):
        font = QFont()
        font.setPointSize(10)
        self.MainWindow.setFont(font)

        self.centralwidget = QWidget(self.MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")

        self.horizontalLayout = QHBoxLayout(self.centralwidget)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)

        # Left menu
        self.setup_left_menu_subcontainer()
        self.setup_left_menu()

        # Center slide menu (hidden by default)
        self.centerMenuContainer = QFrame(self.centralwidget)
        self.centerMenuContainer.setObjectName(u"centerMenuContainer")
        self.centerMenuContainer.setFixedWidth(200)
        self.centerMenuContainer.setStyleSheet("background-color: #2d3748; border-radius: 10px; margin: 5px;")
        self.centerMenuContainer.hide()

        self.verticalLayout_5 = QVBoxLayout(self.centerMenuContainer)
        self.verticalLayout_5.setSpacing(5)
        self.verticalLayout_5.setContentsMargins(10, 10, 10, 10)

        # Close button for center menu
        self.frame_4 = QFrame(self.centerMenuContainer)
        self.horizontalLayout_3 = QHBoxLayout(self.frame_4)
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel("Center Menu", self.frame_4)
        self.label.setStyleSheet("color: white; font-weight: bold;")
        self.horizontalLayout_3.addWidget(self.label)

        self.closeCenterMenuBtn = self._create_menu_button(self.frame_4, "closeCenterMenuBtn", "x-circle.png", "", "Close")
        self.horizontalLayout_3.addWidget(self.closeCenterMenuBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.verticalLayout_5.addWidget(self.frame_4)

        # Center menu pages (stacked widget)
        self.centerMenuPages = QStackedWidget(self.centerMenuContainer)
        self.centerMenuPages.setObjectName(u"centerMenuPages")

        # Page 3 - Settings
        self.page_3 = QWidget()
        self.verticalLayout_7 = QVBoxLayout(self.page_3)
        self.label_2 = QLabel("Settings", self.page_3)
        self.label_2.setStyleSheet("color: white;")
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_7.addWidget(self.label_2)
        
        self.frame_13 = QFrame(self.page_3)
        self.horizontalLayout_14 = QHBoxLayout(self.frame_13)
        self.label_6 = QLabel("Theme", self.frame_13)
        self.label_6.setStyleSheet("color: white;")
        self.horizontalLayout_14.addWidget(self.label_6)
        self.themeList = QComboBox(self.frame_13)
        self.horizontalLayout_14.addWidget(self.themeList)
        self.verticalLayout_7.addWidget(self.frame_13)
        self.centerMenuPages.addWidget(self.page_3)

        # Page 5 - Help
        self.page_5 = QWidget()
        self.verticalLayout_9 = QVBoxLayout(self.page_5)
        self.label_4 = QLabel("Help", self.page_5)
        self.label_4.setStyleSheet("color: white;")
        self.label_4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_9.addWidget(self.label_4)
        self.centerMenuPages.addWidget(self.page_5)

        # Page 4 - Information
        self.page_4 = QWidget()
        self.verticalLayout_8 = QVBoxLayout(self.page_4)
        self.label_3 = QLabel("Information", self.page_4)
        self.label_3.setStyleSheet("color: white;")
        self.label_3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_8.addWidget(self.label_3)
        self.centerMenuPages.addWidget(self.page_4)

        self.verticalLayout_5.addWidget(self.centerMenuPages)
        self.horizontalLayout.addWidget(self.centerMenuContainer)

        # Main body container
        self.mainBodyContainer = QWidget(self.centralwidget)
        self.mainBodyContainer.setObjectName(u"mainBodyContainer")
        self.mainBodyContainer.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))

        self.verticalLayout_10 = QVBoxLayout(self.mainBodyContainer)
        self.verticalLayout_10.setSpacing(0)
        self.verticalLayout_10.setContentsMargins(0, 0, 0, 0)

        # Main content
        self.mainBodyContent = QWidget(self.mainBodyContainer)
        self.mainBodyContent.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))

        self.horizontalLayout_8 = QHBoxLayout(self.mainBodyContent)
        self.horizontalLayout_8.setSpacing(0)
        self.horizontalLayout_8.setContentsMargins(0, 0, 0, 0)

        self.mainContentsContainer = QWidget(self.mainBodyContent)
        self.mainContentsContainer.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))

        self.verticalLayout_24 = QVBoxLayout(self.mainContentsContainer)
        self.verticalLayout_24.setSpacing(0)
        self.verticalLayout_24.setContentsMargins(0, 0, 0, 0)

        # Main pages (stacked widget)
        self.mainPages = QStackedWidget(self.mainContentsContainer)
        self.mainPages.setObjectName(u"mainPages")
        self.mainPages.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))

        # Get title bar tab area
        title_bar_tab_area = None
        if hasattr(self.MainWindow.tab_widget, 'parent'):
            tab_widget_parent = self.MainWindow.tab_widget.parent()
            if hasattr(tab_widget_parent, 'get_tab_area'):
                title_bar_tab_area = tab_widget_parent.get_tab_area()

        # Home widget
        self.home_widget = home_ui.HomePanelWidget(
            tab_widget=self.MainWindow.tab_widget,
            title_bar_tab_area=title_bar_tab_area
        )
        self.home_widget.set_mainwindow(self.MainWindow)
        self.mainPages.addWidget(self.home_widget)

        # Settings widget
        self.settings_widget = settings_ui.SettingsTabWidget()
        self.mainPages.addWidget(self.settings_widget)

        # Data page
        self.dataPage = QWidget()
        self.verticalLayout_29 = QVBoxLayout(self.dataPage)
        self.label_13 = QLabel("Data Analysis", self.dataPage)
        self.label_13.setStyleSheet("color: white;")
        self.label_13.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_29.addWidget(self.label_13)
        self.mainPages.addWidget(self.dataPage)

        # Reports page
        self.reportsPage = QWidget()
        self.verticalLayout_30 = QVBoxLayout(self.reportsPage)
        self.label_16 = QLabel("Reports", self.reportsPage)
        self.label_16.setStyleSheet("color: white;")
        self.label_16.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_30.addWidget(self.label_16)
        self.mainPages.addWidget(self.reportsPage)

        # Web Browser page
        self.webBrowserPage = QWidget()
        self.verticalLayout_31 = QVBoxLayout(self.webBrowserPage)
        self.verticalLayout_31.setContentsMargins(0, 0, 0, 0)
        self.web_browser_widget = WebBrowserWidget()
        self.verticalLayout_31.addWidget(self.web_browser_widget)
        self.mainPages.addWidget(self.webBrowserPage)

        self.verticalLayout_24.addWidget(self.mainPages)
        self.horizontalLayout_8.addWidget(self.mainContentsContainer, 1)

        # Right menu (hidden by default)
        self.rightMenuContainer = QFrame(self.mainBodyContent)
        self.rightMenuContainer.setObjectName(u"rightMenuContainer")
        self.rightMenuContainer.setFixedWidth(200)
        self.rightMenuContainer.setStyleSheet("background-color: #2d3748; border-radius: 10px; margin: 5px;")
        self.rightMenuContainer.hide()

        self.verticalLayout_6 = QVBoxLayout(self.rightMenuContainer)
        self.verticalLayout_6.setSpacing(5)
        self.verticalLayout_6.setContentsMargins(10, 10, 10, 10)

        self.frame_17 = QFrame(self.rightMenuContainer)
        self.horizontalLayout_19 = QHBoxLayout(self.frame_17)
        self.horizontalLayout_19.setContentsMargins(0, 0, 0, 0)
        
        self.label_10 = QLabel("Right Menu", self.frame_17)
        self.label_10.setStyleSheet("color: white; font-weight: bold;")
        self.horizontalLayout_19.addWidget(self.label_10)

        self.closeRightMenuBtn = self._create_menu_button(self.frame_17, "closeRightMenuBtn", "x-circle.png", "", "Close")
        self.horizontalLayout_19.addWidget(self.closeRightMenuBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.verticalLayout_6.addWidget(self.frame_17)

        # Right menu pages
        self.rightMenuPages = QStackedWidget(self.rightMenuContainer)
        self.page_12 = QWidget()
        self.verticalLayout_33 = QVBoxLayout(self.page_12)
        self.label_17 = QLabel("Profile", self.page_12)
        self.label_17.setStyleSheet("color: white;")
        self.label_17.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_33.addWidget(self.label_17)
        self.rightMenuPages.addWidget(self.page_12)

        self.page = QWidget()
        self.verticalLayout_11 = QVBoxLayout(self.page)
        self.label_5 = QLabel("Notifications", self.page)
        self.label_5.setStyleSheet("color: white;")
        self.verticalLayout_11.addWidget(self.label_5, 0, Qt.AlignmentFlag.AlignHCenter)
        self.rightMenuPages.addWidget(self.page)

        self.verticalLayout_6.addWidget(self.rightMenuPages)
        self.horizontalLayout_8.addWidget(self.rightMenuContainer, 0)

        self.verticalLayout_10.addWidget(self.mainBodyContent)

        # Footer
        self.footerContainter = QWidget(self.mainBodyContainer)
        self.footerContainter.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))

        self.horizontalLayout_11 = QHBoxLayout(self.footerContainter)
        self.horizontalLayout_11.setSpacing(0)
        self.horizontalLayout_11.setContentsMargins(10, 5, 10, 5)

        self.frame_10 = QFrame(self.footerContainter)
        self.horizontalLayout_12 = QHBoxLayout(self.frame_10)
        self.horizontalLayout_12.setContentsMargins(0, 0, 0, 0)
        self.label_15 = QLabel("", self.frame_10)
        self.horizontalLayout_12.addWidget(self.label_15)
        self.horizontalLayout_11.addWidget(self.frame_10)

        self.frame_14 = QFrame(self.footerContainter)
        self.horizontalLayout_15 = QHBoxLayout(self.frame_14)
        self.horizontalLayout_15.setContentsMargins(0, 0, 0, 0)
        self.activityLabel = QLabel("", self.frame_14)
        self.activityLabel.setStyleSheet("color: #888;")
        font2 = QFont()
        font2.setPointSize(9)
        self.activityLabel.setFont(font2)
        self.horizontalLayout_15.addWidget(self.activityLabel, 0, Qt.AlignmentFlag.AlignRight)
        self.horizontalLayout_11.addWidget(self.frame_14, 0, Qt.AlignmentFlag.AlignRight)

        self.sizeGrip = QFrame(self.footerContainter)
        self.sizeGrip.setObjectName(u"sizeGrip")
        self.sizeGrip.setMinimumSize(QSize(20, 20))
        self.sizeGrip.setMaximumSize(QSize(20, 20))
        self.horizontalLayout_11.addWidget(self.sizeGrip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        self.verticalLayout_10.addWidget(self.footerContainter)
        self.verticalLayout_10.setStretch(0, 1)
        self.verticalLayout_10.setStretch(1, 0)

        self.horizontalLayout.addWidget(self.mainBodyContainer, 1)

        # Finalize
        self.MainWindow.setCentralWidget(self.centralwidget)
        self.centerMenuPages.setCurrentIndex(0)
        self.mainPages.setCurrentIndex(0)
        self.rightMenuPages.setCurrentIndex(1)
        QMetaObject.connectSlotsByName(self.MainWindow)

        # Connect buttons
        self.connect_buttons()
        self.connect_left_navigation()

    def connect_left_navigation(self):
        """Connect left-side navigation buttons to stacked pages."""
        self.home_btn.clicked.connect(lambda: self.mainPages.setCurrentIndex(0))
        self.settings_server_btn.clicked.connect(lambda: self.mainPages.setCurrentIndex(1))
        self.dataBtn.clicked.connect(lambda: self.mainPages.setCurrentIndex(2))
        self.reportBtn.clicked.connect(lambda: self.mainPages.setCurrentIndex(3))
        
        self.download_manager_btn.clicked.connect(self.open_download_manager)
        self.web_browser_btn.clicked.connect(self.open_web_browser)
        
    def open_download_manager(self):
        """Open download manager tab"""
        try:
            if hasattr(self, 'home_widget') and hasattr(self.home_widget, 'open_download_manager'):
                self.home_widget.open_download_manager()
        except Exception as e:
            print(f"Error opening download manager: {str(e)}")
            
    def open_web_browser(self):
        """Open web browser tab"""
        try:
            if hasattr(self, 'home_widget') and hasattr(self.home_widget, 'open_web_browser'):
                self.home_widget.open_web_browser()
        except Exception as e:
            print(f"Error opening web browser: {str(e)}")
