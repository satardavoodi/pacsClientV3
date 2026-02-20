import sys
import json
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeyEvent, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, \
    QStackedWidget, QMenuBar, QMenu, QMessageBox, QCheckBox
from PacsClient.utils import IMAGES_LOGIN_PATH
from PacsClient.components.socket_service import SocketService
from PacsClient.utils.socket_token_manager import get_socket_token_manager

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
        msg.setText("Please enter both username and password.")
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

        # Remember Me checkbox
        self.remember_me_checkbox = QCheckBox("Remember Me")
        self.remember_me_checkbox.setChecked(True)
        layout.addWidget(self.remember_me_checkbox)

        # Login button
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.on_login_clicked)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

    def load_saved_credentials(self):
        """Load saved credentials if 'Remember Me' was checked previously"""
        try:
            config_file = self._get_login_config_path()
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    if config.get("remember_me"):
                        username = config.get("username", "")
                        password = config.get("password", "")
                        self.username_input.setText(username)
                        self.password_input.setText(password)
                        self.remember_me_checkbox.setChecked(True)
                        self._auto_login_if_possible(username, password)
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

    def save_credentials(self, username: str, password: str):
        """Save credentials if 'Remember Me' is checked"""
        try:
            if self.remember_me_checkbox.isChecked():
                config_file = self._get_login_config_path()
                
                config = {
                    "username": username,
                    "password": password,
                    "remember_me": True
                }
                
                with open(config_file, 'w') as f:
                    json.dump(config, f)
            else:
                # Remove saved credentials if unchecked
                config_file = self._get_login_config_path()
                if os.path.exists(config_file):
                    os.remove(config_file)
        except Exception as e:
            print(f"Error saving credentials: {e}")

    def _handle_successful_login(self, username: str, password: str):
        self.save_credentials(username, password)
        if self.parent() and hasattr(self.parent(), 'setCurrentIndex'):
            self.parent().setCurrentIndex(1)
        else:
            self.close()

    def _auto_login_if_possible(self, username: str, password: str):
        if not username or not password:
            return

        success, message, token, user = self.authenticate_with_socket(username, password)
        if success:
            self._handle_successful_login(username, password)
        else:
            if "could not connect" in (message or "").lower():
                show_error_message('connection_error', message)
            else:
                show_error_message('user_password', message)

    def on_login_clicked(self):
        # Get credentials
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        # Validate that both fields are filled
        if not username or not password:
            show_error_message('empty_fields')  # Show error message for empty fields
            return

        # Authenticate with socket server
        success, message, token, user = self.authenticate_with_socket(username, password)

        if success:
            self._handle_successful_login(username, password)
        else:
            # Determine the type of error and show appropriate message
            if "could not connect" in message.lower():
                show_error_message('connection_error', message)
            else:
                show_error_message('user_password', message)  # Show error message with details if login fails





