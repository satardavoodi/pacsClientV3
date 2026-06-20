import sys
import json
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeyEvent, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, \
    QStackedWidget, QMenuBar, QMenu, QMessageBox, QCheckBox, QComboBox
from PacsClient.utils import IMAGES_LOGIN_PATH
from modules.network.socket_service import SocketService
from modules.network.socket_token_manager import get_socket_token_manager

def show_error_message(topic_error, detailed_message=None):
    if topic_error == 'user_password':  # it means username or password is not correct
        # Create a message box to show error message
        msg = QMessageBox()
        msg.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Login Failed")
        msg.setText("Incorrect username or password. Please try again.")
        if detailed_message:
            msg.setDetailedText(detailed_message)
        msg.exec()
    elif topic_error == 'empty_fields':
        msg = QMessageBox()
        msg.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Missing Information")
        msg.setText("Please enter username, password, and center.")
        msg.exec()
    elif topic_error == 'connection_error':
        msg = QMessageBox()
        msg.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Connection Error")
        msg.setText("Could not connect to the server. Please check your connection and try again.")
        if detailed_message:
            msg.setDetailedText(detailed_message)
        msg.exec()


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.socket_service = SocketService()
        # Multi-server: remember which center the app STARTED with (its data root
        # + socket target were resolved from this at startup). Picking a different
        # center at login requires a restart to re-resolve them cleanly.
        self.server_combo = None
        self._profile_ids = []
        try:
            from PacsClient.utils import server_profiles as _sp
            self._startup_active_id = (
                _sp.get_active_profile_id() if _sp.server_profiles_enabled() else ""
            )
        except Exception:
            self._startup_active_id = ""
        self.setup_ui()
        self.load_saved_credentials()

    def _get_login_config_path(self) -> str:
        if os.name == "nt":
            base_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
        else:
            base_dir = os.path.join(os.path.expanduser("~"), ".aipacs")
        os.makedirs(base_dir, exist_ok=True)
        return os.path.join(base_dir, "login_config.json")

    def setup_ui(self):
        self.setWindowTitle("Login Page")
        self.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))

        # Create layout
        layout = QVBoxLayout()

        # Server selector (multi-server). Only shown when the feature is enabled.
        self._build_server_selector(layout)

        # Username input
        self.username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_input)

        # Password input
        self.password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)  # To hide the password
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_input)

        # Center input
        self.center_label = QLabel("Center:")
        self.center_input = QLineEdit()
        layout.addWidget(self.center_label)
        layout.addWidget(self.center_input)

        # Remember Me checkbox
        self.remember_me_checkbox = QCheckBox("Remember Me")
        self.remember_me_checkbox.setChecked(True)
        layout.addWidget(self.remember_me_checkbox)

        # Login button
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.on_login_clicked)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

    # ── Multi-server selector ────────────────────────────────────────────────
    def _build_server_selector(self, layout):
        """Add a 'Server' dropdown listing saved profiles (multi-server feature).

        Hidden entirely when the feature is off → login stays byte-identical.
        """
        try:
            from PacsClient.utils import server_profiles as _sp
            if not _sp.server_profiles_enabled():
                return
            profiles = [p for p in _sp.list_profiles() if p.enabled]
            if not profiles:
                return
            self.server_label = QLabel("Server:")
            self.server_combo = QComboBox()
            self._profile_ids = []
            active = _sp.get_active_profile_id()
            active_index = 0
            for i, prof in enumerate(profiles):
                self.server_combo.addItem(prof.display_name)
                self._profile_ids.append(prof.id)
                if prof.id == active:
                    active_index = i
            self.server_combo.setCurrentIndex(active_index)
            layout.addWidget(self.server_label)
            layout.addWidget(self.server_combo)
        except Exception as exc:
            print(f"[login] server selector unavailable: {exc}")
            self.server_combo = None

    def _selected_profile_id(self) -> str:
        try:
            if self.server_combo is not None:
                idx = self.server_combo.currentIndex()
                if 0 <= idx < len(self._profile_ids):
                    return self._profile_ids[idx]
        except Exception:
            pass
        return ""

    def _apply_server_selection_or_restart(self) -> bool:
        """If the user picked a different center than the app started with, set it
        active and ask for a restart (data root + socket resolve at startup).

        Returns True if a restart was triggered (caller must stop the login).
        """
        try:
            from PacsClient.utils import server_profiles as _sp
            if self.server_combo is None or not _sp.server_profiles_enabled():
                return False
            picked = self._selected_profile_id()
            if not picked:
                return False
            current = self._startup_active_id or _sp.get_active_profile_id()
            if picked == current:
                return False  # same center — proceed with normal login
            _sp.set_active_profile_id(picked)
            prof = _sp.get_profile(picked)
            name = prof.display_name if prof else picked
            QMessageBox.information(
                self, "Switch Server",
                f"Switching to {name}.\n\nAI-PACS will now close — please reopen it "
                f"to load this center's data and connection.",
            )
            QApplication.quit()
            return True
        except Exception as exc:
            print(f"[login] server switch failed: {exc}")
            return False

    def load_saved_credentials(self):
        """Load saved credentials if 'Remember Me' was checked previously"""
        try:
            config_file = self._get_login_config_path()
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    remember_me = bool(config.get("remember_me"))
                    self.remember_me_checkbox.setChecked(remember_me)
                    if remember_me:
                        username = config.get("username", "")
                        password = config.get("password", "")
                        self.username_input.setText(username)
                        self.password_input.setText(password)
                        self._auto_login_if_possible(username, password)
                    center = config.get("center", "")
                    if center:
                        self.center_input.setText(center)
        except Exception as e:
            print(f"Error loading saved credentials: {e}")

    def keyPressEvent(self, event: QKeyEvent):
        # Check if the key pressed is Enter (Return)
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.on_login_clicked()  # Call the login function when Enter is pressed
        else:
            super().keyPressEvent(event)  # Handle other key events normally

    def check_user_password(self):
        """Deprecated: Old method for credential validation - replaced with socket authentication"""
        # This method is deprecated and should not be used
        username = self.username_input.text()
        password = self.password_input.text()
        if username == '' and password == '':
            return True
        return False

    def authenticate_with_socket(self, username: str, password: str):
        """
        Authenticate user with Socket server

        Returns:
            tuple: (success: bool, message: str, token: str, user: dict)
        """
        try:
            # Get socket client
            client = self.socket_service._ensure_client()
            if not client:
                return False, "Could not create socket client", None, None

            # Try to connect
            if not client.connected:
                if not client.connect():
                    return False, "Could not connect to server", None, None

            # Attempt login
            success, message, token, user = client.login(username, password)

            if success:
                # Store token in TokenManager for use in all socket requests
                token_manager = get_socket_token_manager()
                token_manager.set_token(token, user)

                print(f"✅ Authenticated as: {user.get('full_name')} ({user.get('role')})")
                print(f"✅ Token stored in TokenManager for socket requests")
                return True, message, token, user
            else:
                # Return the specific error message from the server
                return False, message or "Invalid username or password", None, None

        except Exception as e:
            print(f"❌ Socket authentication error: {e}")
            return False, f"Authentication error: {str(e)}", None, None

    def save_credentials(self, username: str, password: str, center: str):
        """Save login settings, including center value"""
        try:
            config_file = self._get_login_config_path()
            remember_me = self.remember_me_checkbox.isChecked()

            config = {
                "username": username if remember_me else "",
                "password": password if remember_me else "",
                "remember_me": remember_me,
                "center": center
            }

            with open(config_file, 'w') as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Error saving credentials: {e}")

    def _handle_successful_login(self, username: str, password: str, center: str):
        self.save_credentials(username, password, center)
        if self.parent() and hasattr(self.parent(), 'setCurrentIndex'):
            self.parent().setCurrentIndex(1)
        else:
            self.close()

    def _auto_login_if_possible(self, username: str, password: str):
        if not username or not password:
            return

        success, message, token, user = self.authenticate_with_socket(username, password)
        if success:
            center = self.center_input.text().strip()
            self._handle_successful_login(username, password, center)
        else:
            if "could not connect" in (message or "").lower():
                show_error_message('connection_error', message)
            else:
                show_error_message('user_password', message)

    def on_login_clicked(self):
        # Get credentials
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        center = self.center_input.text().strip()

        # Validate that both fields are filled
        if not username or not password or not center:
            show_error_message('empty_fields')  # Show error message for empty fields
            return

        # Multi-server: if the user picked a different center, switch + restart
        # (data root / socket / endpoints resolve at startup).
        if self._apply_server_selection_or_restart():
            return

        # Authenticate with socket server
        success, message, token, user = self.authenticate_with_socket(username, password)

        if success:
            self._handle_successful_login(username, password, center)
        else:
            # Determine the type of error and show appropriate message
            if "could not connect" in message.lower():
                show_error_message('connection_error', message)
            else:
                show_error_message('user_password', message)  # Show error message with details if login fails





