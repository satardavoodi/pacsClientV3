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

    def _teardown_page(self, page):
        """Stop the page's NATIVE audio/media resources before it is destroyed.

        CRASH FIX (2026-07-12). This window is ``WA_DeleteOnClose`` (see __init__),
        so closing it — or switching mode — destroys the page tree IMMEDIATELY. If a
        recording/transcription was in flight, ``sd.InputStream(...,
        callback=composer._rec_callback)`` had handed PortAudio a BOUND METHOD of a
        widget Qt was about to free, and PortAudio kept calling it from its own
        NATIVE audio thread → "Windows fatal exception: access violation" with
        `<no Python frame>` (native_fault.log 2026-07-12T18:17). Tearing the audio
        down FIRST removes the dangling callback. Never raises.
        """
        import logging
        lg = logging.getLogger("echomind.teardown")
        if page is None:
            lg.info("[ECHO-TEARDOWN] no page — nothing to tear down")
            return
        lg.info("[ECHO-TEARDOWN] page teardown START page=%s", type(page).__name__)

        for obj in (page, getattr(page, "composer", None)):
            if obj is None:
                continue
            fn = getattr(obj, "cleanup", None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:
                    lg.warning("[ECHO-TEARDOWN] %s.cleanup failed: %s",
                               type(obj).__name__, exc)

        # SAFETY NET — the actual crash. ApiWorker is a QThread parented to the page.
        # WA_DeleteOnClose destroys the page, Qt destroys its child QThread, and if
        # the request (transcription) is still running Qt aborts the whole process:
        #   "QThread: Destroyed while thread is still running" -> qFatal -> abort()
        # (no traceback, no faulthandler entry — app.log just stops). Detach any
        # running QThread the page's own cleanup() missed, so it can finish on its
        # own and self-delete instead of being deleted mid-run.
        try:
            from PySide6.QtCore import QThread
            from .ai_chat_pages import _ORPHANED_WORKERS, _release_orphan_worker

            stragglers = 0
            for w in page.findChildren(QThread):
                if not w.isRunning():
                    continue
                for _sig in ("done", "failed", "finished"):
                    try:
                        getattr(w, _sig).disconnect()
                    except Exception:
                        pass
                w.setParent(None)
                _ORPHANED_WORKERS.append(w)
                try:
                    w.finished.connect(lambda _w=w: _release_orphan_worker(_w))
                except Exception:
                    pass
                stragglers += 1
            lg.info("[ECHO-TEARDOWN] detached %d straggler QThread(s)", stragglers)
        except Exception as exc:
            lg.warning("[ECHO-TEARDOWN] QThread sweep failed: %s", exc)

        # Stop EVERY Qt Multimedia player under this page, not just the composer's.
        # ChatHistory creates a VoiceMessageBubble per voice message and EACH owns
        # its own QMediaPlayer (ai_chat_widgets: `self.player = QMediaPlayer(self)`).
        # WA_DeleteOnClose destroys them all at once; a player still active when its
        # C++ object dies tears down on Qt Multimedia's NATIVE backend thread ->
        # access violation. Sweep them generically so no player is ever missed.
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            from PySide6.QtCore import QUrl

            players = page.findChildren(QMediaPlayer)
            for pl in players:
                try:
                    pl.stop()
                    pl.setSource(QUrl())
                    pl.setAudioOutput(None)
                except Exception:
                    pass
            lg.info("[ECHO-TEARDOWN] released %d QMediaPlayer(s)", len(players))
        except Exception as exc:
            lg.warning("[ECHO-TEARDOWN] media sweep failed: %s", exc)

        lg.info("[ECHO-TEARDOWN] page teardown DONE")

    def closeEvent(self, e):
        # Must run BEFORE WA_DeleteOnClose frees the widget tree.
        import logging
        logging.getLogger("echomind.teardown").info(
            "[ECHO-TEARDOWN] AIChatViewer.closeEvent fired"
        )
        try:
            self._teardown_page(getattr(self, "_page", None))
        except Exception:
            pass
        super().closeEvent(e)

    def _open_mode_page(self, mode_name: str):
        from modules.EchoMind.settings_store import get_llm_backend

        if getattr(self, "_page", None) is not None:
            idx = self.stack.indexOf(self._page)
            if idx >= 0:
                w = self.stack.widget(idx)
                # Same hazard when SWITCHING mode mid-recording.
                self._teardown_page(w)
                self.stack.removeWidget(w)
                w.deleteLater()

        if mode_name == "ChatGPT":
            self._page = ChatGPTPage(study_uid=self.study_uid)
        elif get_llm_backend() == "openai" and mode_name in {"Chat", "Report"}:
            initial_mode = "report" if mode_name == "Report" else "chat"
            self._page = ChatGPTPage(study_uid=self.study_uid, initial_mode=initial_mode)
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
