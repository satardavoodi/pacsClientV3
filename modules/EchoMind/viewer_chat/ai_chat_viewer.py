from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Qt, QTimer

from .ai_chat_app import OneChatPage, ModePickerPage, ChatGPTPage
from PacsClient.utils import IMAGES_LOGIN_PATH
from .api_manager import APIKeyManager



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
        self.picker = ModePickerPage(self)
        self.stack.addWidget(self.picker)

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        root.addWidget(self.stack)

        self.picker.chosen.connect(self._open_mode_page)
        QTimer.singleShot(0, self._bring_to_front)

        # --- background image ---
        echo_mind_path = f'{IMAGES_LOGIN_PATH}/Echo-Mind2.png'

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
