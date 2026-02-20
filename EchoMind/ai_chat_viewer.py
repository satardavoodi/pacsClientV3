from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QLabel, QLineEdit, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, Signal

from .ai_chat_app import OneChatPage, ModePickerPage, ChatGPTPage
from PacsClient.utils import IMAGES_LOGIN_PATH
from .api_manager import APIKeyManager
from .settings_store import get_echomind_api_key, set_echomind_api_key
from .api_manager import Manage


class EchoMindLoginPage(QWidget):
    logged_in = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EchoMindLoginPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(16)

        title = QLabel("EchoMind Login", self)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:20px;font-weight:700;color:#f0f3f6;")

        subtitle = QLabel("Enter your EchoMind access key to continue.", self)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#b9c1c9;font-size:12px;")

        self.status_lbl = QLabel("", self)
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet("color:#f0c674;font-size:12px;")

        self.key_input = QLineEdit(self)
        self.key_input.setPlaceholderText("EchoMind access key")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setStyleSheet(
            "QLineEdit{background:#2f353b;color:#f7f9fb;border:1px solid #1f2226;"
            "border-radius:8px;padding:10px 12px;font-size:13px;}"
        )

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        self.btn_login = QPushButton("Login", self)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.setStyleSheet(
            "QPushButton{background:#3a4148;color:#f7f9fb;border:1px solid #1f2226;"
            "border-radius:8px;padding:8px 22px;font-size:13px;}"
            "QPushButton:hover{background:#485057;}"
            "QPushButton:pressed{background:#343b41;}"
        )
        btn_row.addWidget(self.btn_login, 0, Qt.AlignRight)

        root.addStretch(1)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.key_input)
        root.addWidget(self.status_lbl)
        root.addLayout(btn_row)
        root.addStretch(2)

        self.btn_login.clicked.connect(self._attempt_login)
        self.key_input.returnPressed.connect(self._attempt_login)

        self._prefill_key()

    def _prefill_key(self):
        saved_key = (get_echomind_api_key() or "").strip()
        if not saved_key:
            return
        self.key_input.setText(saved_key)
        self.status_lbl.setText("Saved key detected. Click Login to continue.")

    def _attempt_login(self):
        api_key = (self.key_input.text() or "").strip()
        if not api_key:
            self.status_lbl.setText("Please enter a valid access key.")
            return

        manager = APIKeyManager.instance()
        ok, center, error = manager.validate_key(api_key)
        if not ok:
            self.status_lbl.setText(error or "Invalid access key.")
            return

        set_echomind_api_key(api_key)
        try:
            Manage.instance().detect_center(api_key)
        except Exception:
            pass

        self.status_lbl.setText(f"Login OK: {center or 'Unknown'}")
        self.logged_in.emit()



class AIChatViewer(QWidget):
    """Multi-mode AI surface: shows ModePicker first, then locked OneChatPage."""
    def __init__(self, parent=None, study_uid=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.Window, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("AI Chat")
        self.resize(1100, 720)

        self.study_uid = study_uid

        self.stack = QStackedWidget(self)
        self.login_page = EchoMindLoginPage(self)
        self.picker = ModePickerPage(self)
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.picker)

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        root.addWidget(self.stack)

        self.picker.chosen.connect(self._open_mode_page)
        self.login_page.logged_in.connect(self._open_mode_picker)
        QTimer.singleShot(0, self._bring_to_front)

        # --- background image ---
        echo_mind_path = f'{IMAGES_LOGIN_PATH}/Echo-Mind2.png'
        print(echo_mind_path)

        # لازم برای اعمال استایل پس‌زمینه روی QWidget
        self.setObjectName("AIChatViewerRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)

        # شفاف کردن بچه‌ها تا بک‌گراندِ والد دیده شود
        self.stack.setAttribute(Qt.WA_StyledBackground, True)
        self.stack.setStyleSheet("background: transparent;")

        # استفاده از border-image برای حالت cover
        p = echo_mind_path.replace("\\", "/")  # مسیر سازگار با QSS
        self.setStyleSheet(f"""
            #AIChatViewerRoot {{
                border-image: url("{p}") 0 0 0 0 stretch stretch;
                background-color: #0b0d10;  /* رنگ پس‌زمینه‌ی fallback */
            }}
        """)


    def _open_mode_page(self, mode_name: str):
        if getattr(self, "_page", None) is not None:
            idx = self.stack.indexOf(self._page)
            if idx >= 0:
                w = self.stack.widget(idx)
                self.stack.removeWidget(w)
                w.deleteLater()

        if mode_name == "ChatGPT":
            self._page = ChatGPTPage(study_uid=self.study_uid)
        else:
            self._page = OneChatPage(study_uid=self.study_uid, page_mode=mode_name)

        self.stack.addWidget(self._page)
        self.stack.setCurrentWidget(self._page)

        def go_back():
            self.stack.setCurrentWidget(self.picker)
        try:
            self._page.backRequested.connect(go_back)
        except Exception:
            pass

    def _open_mode_picker(self):
        self.stack.setCurrentWidget(self.picker)


    def showEvent(self, e):
        super().showEvent(e)
        self._bring_to_front()

    def _bring_to_front(self):
        try:
            self.raise_()
            self.activateWindow()
            if self.windowHandle():
                self.windowHandle().requestActivate()
        except Exception:
            pass
