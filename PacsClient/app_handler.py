from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QLabel,
    QCheckBox,
    QSpacerItem,
    QSizePolicy,
    QFrame,
    QWidget,
    QProgressBar,
    QGraphicsDropShadowEffect,
    QLayout,
)
from PySide6.QtGui import QFont, QPalette, QColor, QPixmap, QPainter, QLinearGradient, QIcon
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QSize
import json
import os
import logging
import qtawesome as qta
from .pacs.workstation_ui.mainwindow_ui import MainWindowWidget
from PacsClient.utils import IMAGES_LOGIN_PATH
from modules.network.socket_service import SocketService
from modules.network.socket_config import get_socket_config
from modules.network.socket_token_manager import get_socket_token_manager
from modules.LicenseGenerator.license_manager import LicenseManager
from PacsClient.utils.theme_manager import get_theme_manager

logger = logging.getLogger(__name__)


class AppHandler(QDialog):
    def __init__(self, startup_import_folder: str | None = None):
        super(AppHandler, self).__init__()
        self.startup_import_folder = startup_import_folder

        # self.setWindowTitle("AIPacs - Professional Medical Imaging Suite")
        self.setWindowTitle("")

        # Get the absolute path to the icon
        # icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "login", "images", "favicon.ico")
        icon_path = fr"{IMAGES_LOGIN_PATH}/'favicon.ico'"

        self.setWindowIcon(QIcon(icon_path))
        self._default_dialog_size = QSize(1000, 700)
        self._minimum_dialog_size = QSize(900, 660)
        self._error_banner_min_height = 60
        self._error_label_target_height = self._error_banner_min_height
        self._hide_error_pending = False
        self.resize(self._default_dialog_size)
        self.setMinimumSize(self._minimum_dialog_size)
        
        # Set window properties for better taskbar integration
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        
        # Initialize socket service for authentication
        self.socket_service = SocketService()
        self.auth_token = None
        self.auth_user = None
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()

        # Enhanced professional styling
        self.setStyleSheet("""
            QDialog { 
                background: transparent;
            }
            
            QFrame#MainContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e13, stop:0.3 #0f1419, stop:0.7 #141a21, stop:1 #0a0e13);
                border: 2px solid #1e2833;
                border-radius: 16px;
            }
            
            QLabel#BrandTitle { 
                color: #ffffff; 
                font-size: 28px; 
                font-weight: 800; 
                letter-spacing: 1px;
                margin-bottom: 4px;
            }
            QLabel#BrandSubtitle { 
                color: #94a3b8; 
                font-size: 14px; 
                font-weight: 400;
                letter-spacing: 0.5px;
            }
            QLabel#BrandDescription {
                color: #64748b;
                font-size: 12px;
                line-height: 1.5;
                margin-top: 8px;
            }
            
            QLabel#FormTitle { 
                color: #f8fafc; 
                font-size: 24px; 
                font-weight: 700;
                margin-bottom: 8px;
            }
            QLabel#FormSubtitle {
                color: #94a3b8;
                font-size: 14px;
                margin-bottom: 24px;
            }
            
            QLabel#ErrorLabel { 
                color: #fca5a5; 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(239, 68, 68, 0.12), stop:1 rgba(248, 113, 113, 0.08));
                border: 1px solid rgba(239, 68, 68, 0.2);
                border-radius: 8px; 
                padding: 12px 16px;
                font-weight: 500;
            }

            QFrame#BrandPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e293b, stop:0.4 #334155, stop:0.6 #475569, stop:1 #1e293b);
                border: 1px solid #334155;
                border-radius: 12px;
            }

            QLineEdit {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e293b, stop:1 #0f172a);
                color: #f1f5f9;
                border: 2px solid #334155;
                border-radius: 10px; 
                padding: 14px 16px;
                font-size: 14px;
                font-weight: 500;
            }
            QLineEdit:focus { 
                border: 2px solid #3b82f6;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e3a8a, stop:1 #1e293b);
            }
            QLineEdit:hover {
                border: 2px solid #475569;
            }

            QPushButton[variant="primary"] {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff; 
                border: none;
                border-radius: 10px; 
                padding: 14px 20px; 
                font-weight: 700;
                font-size: 15px;
                letter-spacing: 0.5px;
            }
            QPushButton[variant="primary"]:hover { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2563eb, stop:1 #1d4ed8);
            }
            QPushButton[variant="primary"]:pressed { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e40af);
            }
            QPushButton[variant="primary"]:disabled {
                background: #374151;
                color: #6b7280;
            }

            QPushButton[variant="secondary"] {
                background: transparent; 
                color: #cbd5e1; 
                border: 2px solid #475569;
                border-radius: 10px; 
                padding: 14px 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton[variant="secondary"]:hover { 
                border-color: #64748b; 
                color: #f1f5f9;
                background: rgba(71, 85, 105, 0.1);
            }
            
            QProgressBar {
                border: none;
                background: #1e293b;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #06b6d4);
                border-radius: 3px;
            }
        """)
        self.apply_theme(self._active_theme)

        # Main container with rounded corners and shadow
        main_container = QFrame(self)
        main_container.setObjectName("MainContainer")
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 8)
        main_container.setGraphicsEffect(shadow)
        
        # Root layout
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSizeConstraint(QLayout.SetMinimumSize)
        root_layout.addWidget(main_container)
        
        # Container layout: two panels
        container_layout = QHBoxLayout(main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Brand panel (left) - Enhanced
        brand_panel = QFrame(main_container)
        brand_panel.setObjectName("BrandPanel")
        brand_layout = QVBoxLayout(brand_panel)
        brand_layout.setContentsMargins(40, 40, 40, 40)
        brand_layout.setSpacing(16)

        # AI Logo
        logo_label = QLabel(brand_panel)
        try:
            # logo_pixmap = QPixmap("PacsClient/login/images/aiLogo.png")
            logo_pixmap = QPixmap(fr"{IMAGES_LOGIN_PATH}/aiLogo.png")
            if not logo_pixmap.isNull():
                # Scale logo to appropriate size
                scaled_logo = logo_pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_label.setPixmap(scaled_logo)
                logo_label.setAlignment(Qt.AlignCenter)
                logo_label.setStyleSheet("""
                    QLabel {
                        margin: 10px;
                        padding: 10px;
                        background: rgba(255, 255, 255, 0.05);
                        border: 2px solid rgba(255, 255, 255, 0.1);
                        border-radius: 15px;
                    }
                """)
            else:
                logo_label.setText("🤖")
                logo_label.setAlignment(Qt.AlignCenter)
                logo_label.setStyleSheet("font-size: 48px; margin: 20px;")
        except Exception as e:
            logger.warning("Could not load logo: %s", e)
            logo_label.setText("🤖")
            logo_label.setAlignment(Qt.AlignCenter)
            logo_label.setStyleSheet("font-size: 48px; margin: 20px;")

        # Brand content with better hierarchy
        brand_title = QLabel("AiPACS", brand_panel)
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("Professional Medical Imaging Suite", brand_panel)
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_description = QLabel("Secure DICOM viewing, analysis, and patient data management.\nBuilt for healthcare professionals.", brand_panel)
        brand_description.setObjectName("BrandDescription")
        brand_description.setWordWrap(True)

        # Features list
        features_label = QLabel("✓ DICOM Image Viewing\n✓ Patient Data Management\n✓ Secure Authentication\n✓ Multi-format Support", brand_panel)
        features_label.setObjectName("BrandDescription")
        features_label.setStyleSheet("margin-top: 20px; line-height: 1.6;")

        brand_layout.addStretch()
        brand_layout.addWidget(logo_label)
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_subtitle)
        brand_layout.addWidget(brand_description)
        brand_layout.addWidget(features_label)
        brand_layout.addStretch()

        # Form panel (right) - Enhanced
        form_panel = QFrame(main_container)
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(40, 40, 40, 40)
        form_layout.setSpacing(20)

        # Form header
        form_title = QLabel("Welcome Back", form_panel)
        form_title.setObjectName("FormTitle")
        form_subtitle = QLabel("Sign in to access your medical imaging workstation", form_panel)
        form_subtitle.setObjectName("FormSubtitle")
        form_layout.addWidget(form_title)
        form_layout.addWidget(form_subtitle)

        # Error display with animation support
        self.error_label = QLabel("", form_panel)
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setMaximumHeight(0)
        form_layout.addWidget(self.error_label)

        # Username field with icon
        username_container = QFrame(form_panel)
        username_layout = QVBoxLayout(username_container)
        username_layout.setContentsMargins(0, 0, 0, 0)
        username_layout.setSpacing(6)
        username_label = QLabel("Username", username_container)
        username_label.setStyleSheet("color: #94a3b8; font-weight: 600; font-size: 13px;")
        self.line_edit_username = QLineEdit(username_container)
        self.line_edit_username.setPlaceholderText("Enter your username")
        self.line_edit_username.returnPressed.connect(lambda: self.line_edit_password.setFocus())
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.line_edit_username)
        form_layout.addWidget(username_container)

        # Password field with show/hide
        password_container = QFrame(form_panel)
        password_layout = QVBoxLayout(password_container)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(6)
        password_label = QLabel("Password", password_container)
        password_label.setStyleSheet("color: #94a3b8; font-weight: 600; font-size: 13px;")
        password_row = QHBoxLayout()
        password_row.setSpacing(8)
        self.line_edit_password = QLineEdit(password_container)
        self.line_edit_password.setEchoMode(QLineEdit.Password)
        self.line_edit_password.setPlaceholderText("Enter your password")
        self.line_edit_password.returnPressed.connect(self.login)
        
        # Eye icon button
        self.btn_toggle_password = QPushButton(password_container)
        self.btn_toggle_password.setIcon(qta.icon('fa5s.eye', color='#cbd5e1'))
        self.btn_toggle_password.setCheckable(True)
        self.btn_toggle_password.setProperty("variant", "secondary")
        self.btn_toggle_password.clicked.connect(self._toggle_password)
        self.btn_toggle_password.setFixedSize(50, 48)
        self.btn_toggle_password.setToolTip("Show/Hide Password")
        
        # Server settings button
        self.btn_server_settings = QPushButton(password_container)
        self.btn_server_settings.setIcon(qta.icon('fa5s.cog', color='#cbd5e1'))
        self.btn_server_settings.setProperty("variant", "secondary")
        self.btn_server_settings.clicked.connect(self._show_server_settings)
        self.btn_server_settings.setFixedSize(50, 48)
        self.btn_server_settings.setToolTip("Server Settings")
        
        password_row.addWidget(self.line_edit_password)
        password_row.addWidget(self.btn_toggle_password)
        password_row.addWidget(self.btn_server_settings)
        password_layout.addWidget(password_label)
        password_layout.addLayout(password_row)
        form_layout.addWidget(password_container)

        # Local login option — allows using the app without a server connection
        local_login_container = QFrame(form_panel)
        local_login_layout = QHBoxLayout(local_login_container)
        local_login_layout.setContentsMargins(0, 0, 0, 0)
        local_login_layout.setSpacing(8)

        self.btn_local_login = QPushButton()
        self.btn_local_login.setCheckable(True)
        self.btn_local_login.setFixedSize(24, 24)
        self.btn_local_login.setCursor(Qt.PointingHandCursor)
        self.btn_local_login.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.btn_local_login.clicked.connect(self._toggle_local_login)
        self._update_local_login_icon()

        local_login_label = QLabel("Local Login (offline mode)")
        local_login_label.setStyleSheet(
            "color: #94a3b8; font-weight: 500; font-size: 13px;"
        )
        local_login_label.setCursor(Qt.PointingHandCursor)
        local_login_label.mousePressEvent = lambda e: self.btn_local_login.click()

        local_login_layout.addWidget(self.btn_local_login)
        local_login_layout.addWidget(local_login_label)
        local_login_layout.addStretch()
        form_layout.addWidget(local_login_container)

        # Remember me + Forgot password
        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        
        # Create custom checkbox using icons
        self.checkbox_container = QHBoxLayout()
        self.checkbox_container.setSpacing(8)
        
        # Checkbox button with icon
        self.checkbox_button = QPushButton()
        self.checkbox_button.setCheckable(True)
        self.checkbox_button.setFixedSize(24, 24)
        self.checkbox_button.setCursor(Qt.PointingHandCursor)
        self.checkbox_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.checkbox_button.clicked.connect(self._toggle_checkbox)
        
        # Label
        checkbox_label = QLabel("Remember me")
        checkbox_label.setStyleSheet("color: #cbd5e1; font-weight: 500; font-size: 13px;")
        checkbox_label.setCursor(Qt.PointingHandCursor)
        checkbox_label.mousePressEvent = lambda e: self.checkbox_button.click()
        
        self.checkbox_container.addWidget(self.checkbox_button)
        self.checkbox_container.addWidget(checkbox_label)
        self.checkbox_container.addStretch()
        
        # License info label
        self.license_info_label = QLabel()
        self.license_info_label.setStyleSheet("""
            color: #10b981; 
            font-weight: 600; 
            font-size: 12px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 4px;
            padding: 4px 8px;
        """)
        self.license_info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Update license info
        self._update_license_info()
        
        # Set initial icon
        self.checkbox_remember = self.checkbox_button  # For compatibility
        self._update_checkbox_icon()
        
        options_row.addLayout(self.checkbox_container)
        options_row.addWidget(self.license_info_label)
        
        forgot_password = QLabel('<a href="#" style="color: #3b82f6; text-decoration: none;">Forgot password?</a>', form_panel)
        forgot_password.setStyleSheet("font-size: 13px;")
        options_row.addWidget(forgot_password)
        form_layout.addLayout(options_row)

        # Loading progress bar (hidden by default)
        self.progress_bar = QProgressBar(form_panel)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        form_layout.addWidget(self.progress_bar)

        # Buttons with better spacing
        buttons_container = QFrame(form_panel)
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 10, 0, 0)
        buttons_layout.setSpacing(12)
        
        self.button_login = QPushButton("Sign In", buttons_container)
        self.button_login.setProperty("variant", "primary")
        self.button_login.clicked.connect(self.login)
        self.button_login.setMinimumHeight(50)
        
        self.button_cancel = QPushButton("Cancel", buttons_container)
        self.button_cancel.setProperty("variant", "secondary")
        self.button_cancel.clicked.connect(self.reject)
        self.button_cancel.setMinimumHeight(50)
        
        buttons_layout.addWidget(self.button_login)
        buttons_layout.addWidget(self.button_cancel)
        form_layout.addWidget(buttons_container)

        # Fill remaining space
        form_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        container_layout.addWidget(brand_panel, 5)
        container_layout.addWidget(form_panel, 4)

        # Initialize animations
        self._setup_animations()

        # Load saved credentials after UI is ready
        self._load_saved_credentials()

        # Fade in animation on startup
        self.setWindowOpacity(0)
        self.fade_in_animation.start()
        QTimer.singleShot(0, self._ensure_welcome_page_height)

    def apply_theme(self, theme=None):
        self._active_theme = theme or self.theme_manager.current_theme()
        t = self._active_theme
        self.setStyleSheet(
            f"""
            QDialog {{
                background: transparent;
            }}
            QFrame#MainContainer {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {t['panel_deep_bg']}, stop:0.3 {t['panel_bg']}, stop:0.7 {t['window_bg']}, stop:1 {t['panel_deep_bg']});
                border: 2px solid {t['border']};
                border-radius: 16px;
            }}
            QLabel#BrandTitle {{
                color: {t['text_primary']};
                font-size: 28px;
                font-weight: 800;
                letter-spacing: 1px;
                margin-bottom: 4px;
            }}
            QLabel#BrandSubtitle {{
                color: {t['text_secondary']};
                font-size: 14px;
                font-weight: 400;
                letter-spacing: 0.5px;
            }}
            QLabel#BrandDescription {{
                color: {t['text_muted']};
                font-size: 12px;
                line-height: 1.5;
                margin-top: 8px;
            }}
            QLabel#FormTitle {{
                color: {t['text_primary']};
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 8px;
            }}
            QLabel#FormSubtitle {{
                color: {t['text_secondary']};
                font-size: 14px;
                margin-bottom: 24px;
            }}
            QLabel#ErrorLabel {{
                color: #fca5a5;
                background: {t['card_bg']};
                border: 1px solid {t['danger']};
                border-radius: 8px;
                padding: 12px 16px;
                font-weight: 500;
            }}
            QFrame#BrandPanel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {t['menu_bg']}, stop:0.5 {t['accent_soft']}, stop:1 {t['menu_bg']});
                border: 1px solid {t['border']};
                border-radius: 12px;
            }}
            QLineEdit {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t['panel_alt_bg']}, stop:1 {t['panel_bg']});
                color: {t['text_primary']};
                border: 2px solid {t['border']};
                border-radius: 10px;
                padding: 14px 16px;
                font-size: 14px;
                font-weight: 500;
            }}
            QLineEdit:focus {{
                border: 2px solid {t['accent']};
                background: {t['card_bg']};
            }}
            QPushButton[variant="primary"] {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t['accent_hover']}, stop:1 {t['accent']});
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 14px 20px;
                font-weight: 700;
                font-size: 15px;
                letter-spacing: 0.5px;
            }}
            QPushButton[variant="primary"]:hover {{
                background: {t['accent_hover']};
            }}
            QPushButton[variant="secondary"] {{
                background: transparent;
                color: {t['text_secondary']};
                border: 2px solid {t['border']};
                border-radius: 10px;
                padding: 14px 20px;
                font-weight: 600;
                font-size: 14px;
            }}
            QPushButton[variant="secondary"]:hover {{
                border-color: {t['accent']};
                color: {t['text_primary']};
                background: {t['card_bg']};
            }}
            QProgressBar {{
                border: none;
                background: {t['panel_alt_bg']};
                border-radius: 3px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {t['accent']}, stop:1 {t['accent_hover']});
                border-radius: 3px;
            }}
            """
        )

    def _setup_animations(self):
        """Setup smooth animations for UI interactions"""
        # Fade in animation for startup
        self.fade_in_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in_animation.setDuration(600)
        self.fade_in_animation.setStartValue(0)
        self.fade_in_animation.setEndValue(1)
        self.fade_in_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Error label height animation
        self.error_height_animation = QPropertyAnimation(self.error_label, b"maximumHeight")
        self.error_height_animation.setDuration(300)
        self.error_height_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.error_height_animation.finished.connect(self._on_error_animation_finished)
        
        # Error fade animation
        self.error_fade_animation = QPropertyAnimation(self.error_label, b"windowOpacity")
        self.error_fade_animation.setDuration(200)
        
        # Button animation group for loading state
        self.button_animation_group = QParallelAnimationGroup()

    def _show_error(self, message):
        """Show error with smooth animation"""
        self.error_height_animation.stop()
        self._hide_error_pending = False
        self.error_label.setText(message)
        self.error_label.setVisible(True)

        # Measure the alert at its natural size before animating it open.
        self.error_label.setMaximumHeight(16777215)
        self._error_label_target_height = max(
            self._error_banner_min_height,
            self.error_label.sizeHint().height(),
        )
        self.error_label.setMaximumHeight(0)
        self._ensure_welcome_page_height(extra_height=self._error_label_target_height)
        
        # Animate height from 0 to content height
        self.error_height_animation.setStartValue(self.error_label.maximumHeight())
        self.error_height_animation.setEndValue(self._error_label_target_height)
        self.error_height_animation.start()

    def _hide_error(self):
        """Hide error with smooth animation"""
        self.error_height_animation.stop()
        self._hide_error_pending = True
        self.error_height_animation.setStartValue(self.error_label.maximumHeight())
        self.error_height_animation.setEndValue(0)
        self.error_height_animation.start()

    def _on_error_animation_finished(self):
        if self._hide_error_pending and self.error_height_animation.endValue() == 0:
            self.error_label.setVisible(False)
            self._hide_error_pending = False

    def _ensure_welcome_page_height(self, extra_height=0):
        """Grow the dialog enough to fit the full login form in all states."""
        layout = self.layout()
        if layout is None:
            return

        layout_minimum = layout.totalMinimumSize()
        target_width = max(self._minimum_dialog_size.width(), layout_minimum.width())
        target_height = max(
            self._minimum_dialog_size.height(),
            layout_minimum.height() + extra_height,
        )

        if self.minimumWidth() != target_width or self.minimumHeight() != target_height:
            self.setMinimumSize(target_width, target_height)

        new_width = max(self.width(), target_width, self._default_dialog_size.width())
        new_height = max(self.height(), target_height, self._default_dialog_size.height())
        if new_width != self.width() or new_height != self.height():
            self.resize(new_width, new_height)

    def _set_loading_state(self, loading=True):
        """Set UI to loading state with progress animation"""
        self.button_login.setEnabled(not loading)
        self.line_edit_username.setEnabled(not loading)
        self.line_edit_password.setEnabled(not loading)
        
        if loading:
            self.button_login.setText("Signing In...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
        else:
            self.button_login.setText("Sign In")
            self.progress_bar.setVisible(False)

    def _toggle_checkbox(self):
        """Toggle checkbox and update icon"""
        self._update_checkbox_icon()
    
    def _update_checkbox_icon(self):
        """Update checkbox icon based on state"""
        if self.checkbox_button.isChecked():
            # Checked - show filled check square
            icon = qta.icon('fa5s.check-square', color='#3b82f6')
        else:
            # Unchecked - show empty square (regular style)
            icon = qta.icon('fa5.square', color='#64748b')
        
        self.checkbox_button.setIcon(icon)
        self.checkbox_button.setIconSize(self.checkbox_button.size())

    def _get_login_config_path(self) -> str:
        if os.name == "nt":
            base_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
        else:
            base_dir = os.path.join(os.path.expanduser("~"), ".aipacs")
        os.makedirs(base_dir, exist_ok=True)
        return os.path.join(base_dir, "login_config.json")

    def _load_saved_credentials(self) -> None:
        try:
            config_file = self._get_login_config_path()
            if not os.path.exists(config_file):
                self.checkbox_button.setChecked(False)
                self._update_checkbox_icon()
                return

            with open(config_file, "r") as handle:
                config = json.load(handle)

            remember_me = bool(config.get("remember_me"))
            self.checkbox_button.setChecked(remember_me)
            self._update_checkbox_icon()

            if remember_me:
                username = config.get("username", "")
                password = config.get("password", "")
                if username:
                    self.line_edit_username.setText(username)
                if password:
                    self.line_edit_password.setText(password)
        except Exception as e:
            logger.warning("Error loading saved credentials: %s", e)
            self.checkbox_button.setChecked(False)
            self._update_checkbox_icon()

    def _save_credentials(self, username: str, password: str) -> None:
        try:
            config_file = self._get_login_config_path()
            if self.checkbox_button.isChecked():
                config = {
                    "username": username,
                    "password": password,
                    "remember_me": True,
                }
                with open(config_file, "w") as handle:
                    json.dump(config, handle)
            else:
                if os.path.exists(config_file):
                    os.remove(config_file)
        except Exception as e:
            logger.warning("Error saving credentials: %s", e)
    
    def _update_license_info(self):
        """Update license information display"""
        try:
            license_manager = LicenseManager()
            is_valid, message = license_manager.check_license()
            
            if is_valid and "days remaining" in message.lower():
                # Extract days from message
                import re
                days_match = re.search(r'(\d+)\s+days?\s+remaining', message, re.IGNORECASE)
                if days_match:
                    days = int(days_match.group(1))
                    
                    # Color based on days remaining
                    if days > 30:
                        color = "#10b981"  # Green
                        bg_color = "rgba(16, 185, 129, 0.1)"
                        border_color = "rgba(16, 185, 129, 0.3)"
                        icon = "✓"
                    elif days > 7:
                        color = "#f59e0b"  # Orange
                        bg_color = "rgba(245, 158, 11, 0.1)"
                        border_color = "rgba(245, 158, 11, 0.3)"
                        icon = "⚠"
                    else:
                        color = "#ef4444"  # Red
                        bg_color = "rgba(239, 68, 68, 0.1)"
                        border_color = "rgba(239, 68, 68, 0.3)"
                        icon = "⚠"
                    
                    self.license_info_label.setText(f"{icon} License: {days} days left")
                    self.license_info_label.setStyleSheet(f"""
                        color: {color}; 
                        font-weight: 600; 
                        font-size: 12px;
                        background: {bg_color};
                        border: 1px solid {border_color};
                        border-radius: 4px;
                        padding: 4px 10px;
                    """)
                    self.license_info_label.setVisible(True)
                else:
                    self.license_info_label.setVisible(False)
            else:
                self.license_info_label.setVisible(False)
        except Exception as e:
            logger.warning("Error updating license info: %s", e)
            self.license_info_label.setVisible(False)
    
    def _toggle_password(self):
        if self.btn_toggle_password.isChecked():
            self.line_edit_password.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_password.setIcon(qta.icon('fa5s.eye-slash', color='#cbd5e1'))
            self.btn_toggle_password.setToolTip("Hide Password")
        else:
            self.line_edit_password.setEchoMode(QLineEdit.Password)
            self.btn_toggle_password.setIcon(qta.icon('fa5s.eye', color='#cbd5e1'))
            self.btn_toggle_password.setToolTip("Show Password")

    def _toggle_local_login(self):
        """Toggle local-login checkbox and update its icon."""
        self._update_local_login_icon()

    def _update_local_login_icon(self):
        """Refresh the local-login toggle icon to match its checked state."""
        if self.btn_local_login.isChecked():
            icon = qta.icon('fa5s.check-square', color='#10b981')
        else:
            icon = qta.icon('fa5.square', color='#64748b')
        self.btn_local_login.setIcon(icon)
        self.btn_local_login.setIconSize(self.btn_local_login.size())
    
    def _show_server_settings(self):
        """Show server settings dialog"""
        from modules.network.server_settings_dialog import ServerSettingsDialog
        dialog = ServerSettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # Server settings updated, could show notification
            pass

    def login(self):
        username = self.line_edit_username.text().strip()
        password = self.line_edit_password.text().strip()

        # Hide any existing errors
        if self.error_label.isVisible():
            self._hide_error()

        # Set loading state
        self._set_loading_state(True)

        # Simulate login process with timer (replace with actual authentication)
        QTimer.singleShot(1500, lambda: self._complete_login(username, password))

    def _complete_login(self, username, password):
        """Complete the login process after authentication"""
        self._set_loading_state(False)

        # Local login mode — skip server authentication entirely
        if self.btn_local_login.isChecked():
            self._save_credentials(username, password)
            self.auth_token = None
            self.auth_user = {
                "username": username or "local",
                "full_name": username or "Local User",
                "role": "local",
            }
            logger.info("Local login enabled; bypassing server authentication")
            fade_out = QPropertyAnimation(self, b"windowOpacity")
            fade_out.setDuration(300)
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.0)
            fade_out.setEasingCurve(QEasingCurve.OutCubic)
            self.fade_animation = fade_out
            fade_out.finished.connect(self._open_main_window)
            fade_out.start()
            return

        # Try socket authentication first
        success, message = self._authenticate_with_socket(username, password)
        
        # If socket fails, try demo mode
        if not success:
            success = self._authenticate_user(username, password)
            if success:
                message = "Login successful (Demo Mode)"
        
        if success:
            self._save_credentials(username, password)
            # Success - fade out and open main window
            fade_out = QPropertyAnimation(self, b"windowOpacity")
            fade_out.setDuration(300)  # Shorter duration
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.0)
            fade_out.setEasingCurve(QEasingCurve.OutCubic)
            
            # Store animation reference to prevent garbage collection
            self.fade_animation = fade_out
            fade_out.finished.connect(self._open_main_window)
            fade_out.start()
        else:
            # Show error
            self._show_error(f"Login failed: {message}")
    
    def _authenticate_with_socket(self, username: str, password: str) -> tuple:
        """
        Authenticate user with Socket server
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Get socket client
            client = self.socket_service._ensure_client()
            if not client:
                return False, "Could not create socket client"
            
            # Try to connect
            if not client.connected:
                if not client.connect():
                    return False, "Could not connect to server"
            
            # Attempt login
            success, message, token, user = client.login(username, password)
            
            if success:
                self.auth_token = token
                self.auth_user = user
                
                # Store token in TokenManager for use in all socket requests
                token_manager = get_socket_token_manager()
                token_manager.set_token(token, user)
                
                logger.info("Authenticated as: %s (%s)", user.get('full_name'), user.get('role'))
                logger.info("Token stored in TokenManager for socket requests")
                return True, message
            else:
                return False, message
                
        except Exception as e:
            logger.warning("Socket authentication error: %s", e)
            return False, f"Authentication error: {str(e)}"
    
    def _authenticate_user(self, username, password):
        """Authenticate user credentials - Replace with actual authentication logic"""
        
        # Demo mode: Allow empty credentials for testing
        if username.strip() == "" and password.strip() == "":
            return True
            
        # Prevent single empty field (both must be empty or both must be filled)
        if not username.strip() or not password.strip():
            return False
            
        # Add your authentication logic here
        # For now, accepting common demo credentials or you can integrate with your auth system
        valid_credentials = [
            ("admin", "admin"),
            ("user", "user"),
            ("doctor", "doctor"),
            ("radiologist", "password"),
            ("test", "test")
        ]
        
        # Check against valid credentials
        for valid_user, valid_pass in valid_credentials:
            if username.lower() == valid_user and password == valid_pass:
                return True
                
        # TODO: Replace this with actual authentication system
        # For example: database lookup, LDAP, OAuth, etc.
        # return self.authenticate_with_database(username, password)
        # return self.authenticate_with_ldap(username, password)
        
        return False

    def _open_main_window(self):
        """Open the main application window"""
        try:
            is_local = self.btn_local_login.isChecked()
            if not is_local and not self.auth_token:
                self._show_error("Login required: authentication did not complete")
                return
            self.main_page = MainWindowWidget(
                auth_user=self.auth_user,
                auth_token=self.auth_token,
                startup_import_folder=self.startup_import_folder,
            )
            self.main_page.showMaximized()
            self.hide()
            self.deleteLater()
        except Exception as e:
            logger.exception("Error opening main window: %s", e)
            import traceback
            traceback.print_exc()
            # Keep login window open if there's an error
            QMessageBox.critical(self, "Error", f"Failed to open main window: {str(e)}")

    def mousePressEvent(self, event):
        """Enable window dragging"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle window dragging"""
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.line_edit_username.hasFocus():
                self.line_edit_password.setFocus()
            elif self.line_edit_password.hasFocus():
                self.login()
        super().keyPressEvent(event)
