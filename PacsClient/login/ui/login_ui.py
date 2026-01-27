import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeyEvent, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, \
    QStackedWidget, QMenuBar, QMenu, QMessageBox
from PacsClient.utils import IMAGES_LOGIN_PATH

def show_error_message(topic_error):
    if topic_error == 'user_password':  # it means username or password is not correct
        # Create a message box to show error message
        msg = QMessageBox()
        msg.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Login Failed")
        msg.setText("Incorrect username or password. Please try again.")
        msg.exec()


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

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

        # Login button
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.on_login_clicked)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

    def keyPressEvent(self, event: QKeyEvent):
        # Check if the key pressed is Enter (Return)
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.on_login_clicked()  # Call the login function when Enter is pressed
        else:
            super().keyPressEvent(event)  # Handle other key events normally

    def check_user_password(self):
        username = self.username_input.text()
        password = self.password_input.text()
        if username == '' and password == '':
            return True
        return False

    def on_login_clicked(self):
        # When login button is clicked, check user credentials
        flag_check_user = self.check_user_password()
        if flag_check_user:
            self.parent().setCurrentIndex(1)
        else:
            show_error_message('user_password')  # Show error message if login fails





