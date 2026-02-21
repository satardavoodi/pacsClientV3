from __future__ import annotations

import typing as t
import os, json, tempfile, time
import requests
import uuid
from datetime import datetime
from PySide6.QtCore import Qt, QSize, QTimer, QEvent, Signal
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QFont, QTextCursor, QColor, QPen, QTextDocument,QFontMetrics, QGuiApplication, QTextOption, QCursor, QTextBlockFormat
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QInputDialog, QLineEdit, QMessageBox, QMenu, QToolButton, QLabel, QSlider, QSizePolicy, QStyle
)
from PacsClient import utils as U
from PacsClient.utils.database import (
    load_token_usage,
    save_token_usage,
    add_token_usage_delta,
    add_api_token_usage_delta,
    add_transcript_usage_delta,
    add_api_transcript_usage_delta,
    load_api_transcript_usage_for_key,
    ai_save_reception_report,
)

from .openai_reporter import reporter, translate_report, standardize, standard_assist_search, correction,translate_text_to_persian
import re
try:
    from PacsClient.utils import ICON_PATH
except Exception:
    ICON_PATH = "."
from dataclasses import dataclass
from html import escape
from .api_manager import  APIKeyManager,Manage


safe = escape("<div>")
from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QPushButton,
    QPlainTextEdit, QScrollArea, QMenu, QFileDialog, QSpacerItem,QFrame,QSizePolicy,
    QDialog, QDialogButtonBox, QTextEdit,QComboBox, QMenu,QGraphicsOpacityEffect

)

from .ai_chat_helpers import _set_icon, _safe_fa_connection_error, extract_plain_text_from_html
from .ai_chat_api import ChatApiClient, ChatController, ApiWorker
from .ai_chat_widgets import ChatHistory, UnifiedComposer, MessageBubble, PATIENT_SCROLLBAR_QSS
from .ai_chat_config import CLR_BG, CLR_BG_PANEL, CLR_TEXT, CLR_BORDER, CLR_ACCENT,URL_GEN_TRANSCRIPT,URL_GEN_REPORT,URL_CHAT,URL_GEN_ASSISTANT,URL_STATUS,URL_SESSIONS,URL_HEALTH,URL_EXPORT_ALL,URL_SEARCH,URL_SESSION_GET


class ModePickerPage(QWidget):
    chosen = Signal(str)  # "Chat" | "Report" | "Assist" | "ChatGPT"

    def __init__(self, parent=None, *, left_offset: int = 85, top_offset: int = 129, gap: int = 32):
        super().__init__(parent)

        self._api_checked = False
        self._api_retry_count = 0
        self._api_prompt_cancelled = False
        self._api_prompt_inflight = False

        self._left_px = int(left_offset)
        self._top_px  = int(top_offset)
        self._gap_px  = int(gap)

        self._left_ratio = None
        self._top_ratio  = None
        self._gap_ratio  = None

        self.setStyleSheet(f"""
            QWidget {{ background: transparent; }}
            QPushButton#modeBtn {{
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 12px;
                padding: 14px 16px;
                font-size: 18px;
                font-weight: 600;
                text-align: center;
                background-color: rgba(255,255,255,0.06);
            }}
            QPushButton#modeBtn:hover {{
                border-color: {CLR_ACCENT};
                background-color: rgba(255,255,255,0.10);
            }}
            QPushButton#modeBtn:disabled {{
                color: rgba(220,220,220,0.35);
                border-color: rgba(68,68,68,0.45);
                background-color: rgba(255,255,255,0.02);
            }}
        """)

        # ریشه: ستون چپ + فضای کشسان راست
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(self._left_px, 16, 16, 16)
        self._root.setSpacing(0)

        # ستون چپ
        self.left_wrap = QWidget(self)
        self.left_wrap.setFixedWidth(260)
        self.left = QVBoxLayout(self.left_wrap)
        self.left.setContentsMargins(8, 8, 8, 8)
        self.left.setSpacing(12)

        def mk_btn(text: str) -> QPushButton:
            b = QPushButton(text, self.left_wrap)
            b.setObjectName("modeBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(54)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda: self.chosen.emit(text))
            return b

        self.btn_chat   = mk_btn("Chat")
        self.btn_report = mk_btn("Report")
        self.btn_assist = mk_btn("Assist")
        self.btn_chatgpt = mk_btn("ChatGPT")

        # --- فاصله‌ها و ترتیب ---
        self.spacer_top = QWidget(self.left_wrap); self.spacer_top.setFixedHeight(self._top_px)
        self.gap_1 = QWidget(self.left_wrap); self.gap_1.setFixedHeight(self._gap_px)
        self.gap_2 = QWidget(self.left_wrap); self.gap_2.setFixedHeight(self._gap_px)
        self.gap_3 = QWidget(self.left_wrap); self.gap_3.setFixedHeight(self._gap_px)

        self.left.addWidget(self.spacer_top)
        self.left.addWidget(self.btn_chat)
        self.left.addWidget(self.gap_1)
        self.left.addWidget(self.btn_report)
        self.left.addWidget(self.gap_2)
        self.left.addWidget(self.btn_assist)
        self.left.addWidget(self.gap_3)
        self.left.addWidget(self.btn_chatgpt)
        self.left.addStretch(1)

        # راست: پیام قفل/راهنما
        right_spacer = QWidget(self)
        self._right_layout = QVBoxLayout(right_spacer)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.addStretch(1)

        self._lock_lbl = QLabel(right_spacer)
        self._lock_lbl.setWordWrap(True)
        self._lock_lbl.setAlignment(Qt.AlignCenter)
        self._lock_lbl.setStyleSheet("""
            QLabel{
                color: rgba(230,230,230,0.85);
                padding: 18px;
                border: 1px dashed rgba(150,150,150,0.35);
                border-radius: 14px;
                background: rgba(255,255,255,0.03);
                font-size: 13px;
                line-height: 1.25;
            }
        """)
        self._lock_lbl.setVisible(False)
        self._right_layout.addWidget(self._lock_lbl, 0, Qt.AlignCenter)
        self._right_layout.addStretch(1)

        self._root.addWidget(self.left_wrap, 0, Qt.AlignTop | Qt.AlignLeft)
        self._root.addWidget(right_spacer, 1)

        # وضعیت اولیه: تا validate نشده، قفل
        self._apply_access_state()

    # امکان تغییر فاصله‌ی افقی از چپ در زمان اجرا (مانند قبل)
    def set_left_offset(self, px: int):
        self._left_px = max(0, int(px))
        m = self._root.contentsMargins()
        self._root.setContentsMargins(self._left_px, m.top(), m.right(), m.bottom())
        # اگر نسبت قبلاً محاسبه شده، آن را هم بروز کنیم تا ریسپانسیو بماند
        if self.width() > 0:
            self._left_ratio = self._left_px / float(self.width())

    # در اولین نمایش، نسبت‌ها را از اندازه‌های فعلی می‌گیریم
    def showEvent(self, e):
        super().showEvent(e)

        # هر بار نمایش: وضعیت دسترسی را سینک کن
        self._apply_access_state()

        if not self._api_checked:
            self._api_checked = True
            QTimer.singleShot(100, self._prompt_api_key)

        try:
            if self.width() > 0:
                self._left_ratio = self._left_px / float(self.width())
            if self.left_wrap.height() > 0:
                h = float(self.left_wrap.height())
                self._top_ratio = self.spacer_top.height() / h
                self._gap_ratio = self.gap_1.height() / h
        except Exception:
            pass


    def _set_modes_enabled(self, enabled: bool, *, tooltip: str = ""):
        """Enable/disable all mode buttons as a single access gate."""
        try:
            for b in getattr(self, "_mode_buttons", []) or []:
                b.setEnabled(bool(enabled))
                if tooltip:
                    b.setToolTip(tooltip)
        except Exception:
            pass

    def _hard_lock_api(self, reason: str):
        """
        Hard lock: triggered after Cancel or 3 invalid attempts.
        The user must restart the app to try again (as requested: NO access at all).
        """
        from PySide6.QtWidgets import QMessageBox, QApplication

        self._api_hard_locked = True
        self._api_prompt_cancelled = True  # keep the existing guard behavior
        self._set_modes_enabled(False, tooltip=reason)

        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Critical)
        mb.setWindowTitle("⛔ Access Blocked")
        mb.setText(
            "Because you cancelled the API key entry or entered an invalid API key 3 times, "
            "access to the application has been blocked.\n\n"
            "To try again, you must close the application and restart it."
        )
        btn_exit = mb.addButton("Exit Application", QMessageBox.DestructiveRole)
        mb.exec()

        if mb.clickedButton() == btn_exit:
            QApplication.instance().quit()


    def _on_mode_clicked(self, mode: str):
        """
        Single entry point for ALL mode buttons.
        If the API key is not validated -> do not navigate.
        If hard-locked -> do nothing except show an access denied message.
        """
        from PySide6.QtWidgets import QMessageBox
        from .api_manager import APIKeyManager

        # If already hard-locked (Cancel or 3 failed attempts), deny access
        if getattr(self, "_api_hard_locked", False) or getattr(self, "_api_prompt_cancelled", False):
            mb = QMessageBox(self)
            mb.setIcon(QMessageBox.Critical)
            mb.setWindowTitle("⛔ Access Denied")
            mb.setText("Access to AI features is blocked. Please restart the application.")
            mb.exec()
            return

    def _set_ai_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """
        When enabled=False:
        - all AI modes are locked (disabled)
        - the lock reason message is shown
        """
        for btn in (self.btn_chat, self.btn_report, self.btn_assist, self.btn_chatgpt):
            try:
                btn.setEnabled(bool(enabled))
            except Exception:
                pass

        if enabled:
            self._lock_lbl.setVisible(False)
            self._lock_lbl.setText("")
        else:
            self._lock_lbl.setVisible(True)
            self._lock_lbl.setText(
                reason
                or "🔒 A valid API key is required to use AI features.\n"
                "Please go back to the login page and enter the correct key."
            )


    def _apply_access_state(self) -> None:
        """
        Sync the UI state based on whether the API key is validated.
        """
        try:
            from .api_manager import APIKeyManager
            m = APIKeyManager.instance()

            if m.is_validated():
                self._set_ai_enabled(True)
            else:
                # If previously cancelled/locked, keep the existing lock message (if any)
                if getattr(self, "_api_prompt_cancelled", False):
                    self._set_ai_enabled(False, self._lock_lbl.text() or None)
                else:
                    self._set_ai_enabled(False, "🔑 Please enter a valid API key to enable AI features.")
        except Exception:
            self._set_ai_enabled(False, "🔒 Unable to verify the API key status. Please try again.")


    def _apply_access_state(self) -> None:
        """
        Sync the UI access state based on whether the API key is validated.
        """
        try:
            from .api_manager import APIKeyManager
            m = APIKeyManager.instance()

            if m.is_validated():
                self._set_ai_enabled(True)
            else:
                # If previously cancelled/locked, keep the existing lock message (if any)
                if getattr(self, "_api_prompt_cancelled", False):
                    self._set_ai_enabled(False, self._lock_lbl.text() or None)
                else:
                    self._set_ai_enabled(False, "🔑 Please enter a valid API key to enable AI features.")
        except Exception:
            self._set_ai_enabled(False, "🔒 Unable to verify the API key status. Please try again.")


    def _prompt_api_key(self):
        """Prompt user for API key if not validated (NO infinite loop; limited retries; HARD LOCK on cancel/fail)."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        from PySide6.QtCore import QTimer
        from .api_manager import APIKeyManager

        # --- anti-loop / anti re-entry guards ---
        if getattr(self, "_api_prompt_cancelled", False):
            return
        if getattr(self, "_api_prompt_inflight", False):
            return
        self._api_prompt_inflight = True

        try:
            manager = APIKeyManager.instance()

            # If already validated: unlock UI and show welcome
            if manager.is_validated():
                self._set_ai_enabled(True)
                center = manager.get_current_center()
                api_key = None
                try:
                    for attr in (
                        "get_current_key", "get_current_api_key", "current_key",
                        "api_key", "_current_key", "_api_key"
                    ):
                        if hasattr(manager, attr):
                            v = getattr(manager, attr)
                            api_key = v() if callable(v) else v
                            if api_key:
                                break
                except Exception:
                    api_key = None

                self._show_welcome(center, api_key=api_key)
                return

            # Keep UI locked until validated
            self._set_ai_enabled(False, "🔑 Please enter a valid API key to enable AI features.")

            MAX_RETRIES = 3
            self._api_retry_count = int(getattr(self, "_api_retry_count", 0))

            # If retries already exceeded: hard lock
            if self._api_retry_count >= MAX_RETRIES:
                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Critical)
                mb.setWindowTitle("❌ Too Many Attempts")
                mb.setText(
                    "You have reached the maximum number of retry attempts.\n\n"
                    "AI features are now locked.\n"
                    "Please return to the login page and enter a valid API key, or contact support."
                )
                mb.exec()

                self._api_prompt_cancelled = True
                self._set_ai_enabled(
                    False,
                    "🔒 AI features are locked due to 3 invalid attempts.\n"
                    "Please go back to the login page and set a valid API key."
                )
                return

            # Show dialog
            dlg = QInputDialog(self)
            dlg.setWindowTitle("🔑 API Key Required")
            dlg.setLabelText(
                "Please enter your IRANNOBAT API key:\n\n"
                "This key will be used for all AI features\n"
                "(Chat, Reports, Assistant, etc.)."
            )
            dlg.setTextEchoMode(QLineEdit.Password)
            dlg.resize(420, 210)

            ok = bool(dlg.exec())
            if not ok:
                # Cancel => hard lock until a valid key is set through the proper flow
                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Warning)
                mb.setWindowTitle("API Key Required")
                mb.setText(
                    "You cancelled API key entry.\n\n"
                    "AI features are locked until a valid key is set."
                )
                mb.exec()

                self._api_prompt_cancelled = True
                self._set_ai_enabled(
                    False,
                    "🔒 You cancelled API key entry.\n"
                    "Reports/Chat/Assistant are disabled until a valid API key is set."
                )
                return

            api_key = (dlg.textValue() or "").strip()
            if not api_key:
                self._api_retry_count += 1
                remaining = max(0, MAX_RETRIES - self._api_retry_count)

                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Warning)
                mb.setWindowTitle("⚠️ Empty API Key")
                mb.setText(
                    f"No API key was entered.\n\n"
                    f"Please try again. ({remaining} attempt(s) remaining)"
                )
                btn_retry = mb.addButton("🔁 Try again", QMessageBox.AcceptRole)
                mb.exec()

                if mb.clickedButton() == btn_retry and remaining > 0:
                    QTimer.singleShot(0, self._prompt_api_key)
                elif remaining <= 0:
                    self._api_prompt_cancelled = True
                    self._set_ai_enabled(
                        False,
                        "🔒 AI features are locked due to 3 invalid/empty attempts.\n"
                        "Please go back to the login page and set a valid API key."
                    )
                return

            success, center, error = manager.validate_key(api_key)
            if success:
                self._api_retry_count = 0
                self._api_prompt_cancelled = False
                self._set_ai_enabled(True)
                self._show_welcome(center, api_key=api_key)
                return

            # Invalid key
            self._api_retry_count += 1
            remaining = max(0, MAX_RETRIES - self._api_retry_count)

            mb = QMessageBox(self)
            mb.setIcon(QMessageBox.Critical)
            mb.setWindowTitle("❌ Invalid API Key")

            if remaining > 0:
                mb.setText(
                    f"{error}\n\n"
                    f"Please try again. ({remaining} attempt(s) remaining)\n\n"
                    "If you have forgotten your API key, please contact support."
                )
                btn_retry = mb.addButton("🔁 Try again", QMessageBox.AcceptRole)
                mb.exec()
                if mb.clickedButton() == btn_retry:
                    QTimer.singleShot(0, self._prompt_api_key)
                return

            # Retries exhausted => hard lock
            mb.setText(
                f"{error}\n\n"
                "You have reached the maximum number of retry attempts.\n\n"
                "AI features are now locked.\n"
                "Please return to the login page and enter a valid API key, or contact support."
            )
            mb.exec()

            self._api_prompt_cancelled = True
            self._set_ai_enabled(
                False,
                "🔒 AI features are locked due to 3 invalid attempts.\n"
                "Please go back to the login page and set a valid API key."
            )

        finally:
            self._api_prompt_inflight = False

    def _show_welcome(self, center: str, api_key: t.Optional[str] = None):
        from PySide6.QtWidgets import QMessageBox

        usage_html = "<i>No usage data available.</i>"
        real_api_key = None

        try:
            from .api_manager import Manage
            m = Manage.instance()
            if api_key and isinstance(api_key, str) and api_key.strip():
                real_api_key = api_key.strip()
            else:
                real_api_key = (m.get_irannobat_key() or "").strip()
        except Exception:
            try:
                real_api_key = Manage.instance().get_last_api_key()
            except Exception:
                real_api_key = None

        if real_api_key:
            try:
                from PacsClient.utils.database import get_api_usage_summary_html
                usage_html = get_api_usage_summary_html(real_api_key)
            except Exception as e:
                usage_html = f"<i>Error loading usage summary: {str(e)}</i>"
        else:
            usage_html = "<i>API key is not available for usage lookup.</i>"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("✅ API Key Validated - AIPacs")

        msg.setText(
            f"<div style='font-size:12px;line-height:1.25'>"
            f"<div style='font-size:14px;font-weight:700;margin:0 0 4px 0'>"
            f"Welcome to {center} Center"
            f"</div>"
            f"<div style='color:#bbb;margin:0 0 8px 0'>API key validated. AI features are enabled.</div>"

            f"<div style='font-weight:700;margin:0 0 4px 0'>Usage Summary</div>"
            f"{usage_html}"

            f"<div style='color:#aaa;margin-top:6px'>"

            f"<hr>"
            f"<div><b>Enabled features:</b></div>"
            f"<ul style='margin:6px 0 0 18px'>"
            f"<li>💬 Chat</li>"
            f"<li>📄 Report Generation</li>"
            f"<li>🤖 Assistant</li>"
            f"<li>🔍 Search</li>"
            f"<li>🌟 ChatGPT</li>"
            f"</ul>"
            )

        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        lw_h = max(1, self.left_wrap.height())

        # اگر نسبت‌ها هنوز محاسبه نشده‌اند، از مقادیر پیکسلی اولیه استفاده کن
        top_h = int((self._top_ratio or (self._top_px / lw_h)) * lw_h)
        gap_h = int((self._gap_ratio or (self._gap_px / lw_h)) * lw_h)
        left_m = int((self._left_ratio or (self._left_px / max(1, self.width()))) * max(1, self.width()))

        self.spacer_top.setFixedHeight(top_h)
        self.gap_1.setFixedHeight(gap_h)
        self.gap_2.setFixedHeight(gap_h)

        m = self._root.contentsMargins()
        self._root.setContentsMargins(left_m, m.top(), m.right(), m.bottom())

class OneChatPage(QWidget):
    """
    Locked-to-mode page:
      page_mode in {"Chat","Report","Assist"}
      - Chat: send => Chat
      - Report: send => Report
      - Assist: send => small menu [Assist | Search]
    """

    # ✅ سیگنال درست در سطح کلاس
    backRequested = Signal()

    def __init__(self, study_uid: str = None, page_mode: str = "Chat"):
        super().__init__()
        if not hasattr(OneChatPage, "last_selected_modality"):
            OneChatPage.last_selected_modality = None
        self.controller = ChatController(ChatApiClient())
        self._bubble_origin_hint = None
        self.study_uid = study_uid
        pm = (page_mode or "Chat").strip()
        pm_l = pm.lower()
        if pm_l == "chatgpt" or pm_l == "chat-gpt" or pm_l == "chat_gpt":
            pm = "ChatGPT"
        elif pm_l == "chat":
            pm = "Chat"
        elif pm_l == "report":
            pm = "Report"
        elif pm_l in ("assist", "assistant"):
            pm = "Assist"
        elif pm_l == "search":
            pm = "Search"
        else:
            # keep as-is (preserve casing), but normalize first letter
            pm = pm[:1].upper() + pm[1:]
        self.page_mode = pm

        # --- runtime state ---
        self._busy_count = 0  # ← برای قفل/آنلاک دکمه‌ها در _run_async
        self._workers = []  # ← لیست نخ‌های فعال
        self.sessions = {}  # sid -> [(who, html)]
        self.current_session_id = None

        # --- namespace per page (to isolate sessions per page) ---
        # هر صفحه سشن‌های خودش را خواهد داشت: chat-*, report-*, assist-*
        self.ns = self.page_mode.lower()  # "chat" | "report" | "assist"

        # ----- LEFT -----
        self.left = QVBoxLayout()
        self.btn_back = QPushButton(" ← Back")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet(
            f"QPushButton{{background:{CLR_BG_PANEL};color:{CLR_TEXT};border:1px solid {CLR_BORDER};border-radius:10px;padding:10px 14px;margin:6px}}"
            f"QPushButton:hover{{border-color:{CLR_ACCENT}}}"
        )

        self.btn_new = QPushButton()
        _set_icon(self.btn_new, "newchat.png", 18, "New Chat")
        self.btn_new.setText(" New Chat")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setStyleSheet(
            f"QPushButton{{background:{CLR_BG_PANEL};color:{CLR_TEXT};border:1px solid {CLR_BORDER};border-radius:10px;padding:10px 14px;margin:6px}}"
            f"QPushButton:hover{{border-color:{CLR_ACCENT}}}"
        )

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget{{background:{CLR_BG_PANEL};color:{CLR_TEXT};border:1px solid {CLR_BORDER};border-radius:10px;margin:6px}}"
            "QListWidget::item{padding:10px;border-bottom:1px solid #2a2a2a}"
            "QListWidget::item:selected{background:#2b2b2b}"
            f"{PATIENT_SCROLLBAR_QSS}"
        )
        self.left.addWidget(self.btn_back)
        self.left.addWidget(self.btn_new)
        self.left.addWidget(self.list, 1)

        left_wrap = QWidget(); left_wrap.setLayout(self.left)
        left_wrap.setFixedWidth(260)
        left_wrap.setStyleSheet(f"background:{CLR_BG_PANEL};border-right:1px solid {CLR_BORDER}")

        # ----- RIGHT -----
        self.history = ChatHistory()
        ph = {
            "Chat":   "Write your message…",
            "Report": "Write/paste report text",
            "Assist": "Write clinical text to analyze or search…",
        }.get(self.page_mode, "Write your message…")

        self.composer = UnifiedComposer(ph)

        self.composer.sendClicked.connect(self._on_send_clicked)
        self.composer.transcribeRequested.connect(self._transcribe_now)
        self.composer.standardizeClicked.connect(self._standardize_now)
        self.composer.apply_side_padding(16, 16)

        self.composer.btn_modality.clicked.connect(self._show_modality_menu)

        right = QVBoxLayout(); right.setContentsMargins(0,0,0,10); right.setSpacing(0)
        right.addWidget(self.history, 1); right.addWidget(self.composer, 0)
        right_wrap = QWidget(); right_wrap.setLayout(right)
        right_wrap.setStyleSheet(f"background:{CLR_BG};")

        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(left_wrap, 0); root.addWidget(right_wrap, 1)

        # متغیر کلاسی برای نگهداری مودالیتی انتخاب شده (persistent در سطح کلاس)
        if not hasattr(OneChatPage, "last_selected_modality"):
            OneChatPage.last_selected_modality = None
            
        # نمایش دکمه مودالیتی فقط در حالت Report
        self.composer.btn_modality.setVisible(self.page_mode in ["Report", "ChatGPT"])
        # تنظیم مودالیتی ذخیره شده
        if OneChatPage.last_selected_modality:
            self._set_modality_text(OneChatPage.last_selected_modality)
        
        try:
            self.composer.btn_all_modality_hq.setVisible(self.page_mode in ["Report", "ChatGPT"])
            self.composer.btn_all_modality_hq.clicked.connect(self._on_hq_all_modality_clicked)
        except Exception:
            pass        
        # اتصال سیگنال جدید
        self.composer.modalitySelected.connect(self._on_modality_selected)
        
        try:
            self.composer.install_attachment_overlay(self.history.scroll.viewport())
            self.history.scroll.viewport().installEventFilter(self)
        except Exception:
            pass
        
        self._current_modality = OneChatPage.last_selected_modality

        self.controller.messageReady.connect(self._append_bubble)
        self.controller.sessionChanged.connect(self._on_session_changed)
        self.btn_new.clicked.connect(self._new_chat)
        self.list.itemClicked.connect(self._open_session)
        self._pending_retry: dict | None = None  # {'mode': str, 'text': str, 'bubble': MessageBubble|None}

        # ✅ اتصال صحیح دکمه Back
        self.btn_back.clicked.connect(self.backRequested.emit)

        # === DB bootstrap ===
        U.ai_ensure_schema()
        self._loaded_any = self._load_from_db_and_render()
        if not self._loaded_any:
            welcome = {
                "Chat":   "Ready. Type and press Send to Chat.",
                "Report": "Ready. Paste report text then Send to generate Report.",
                "Assist": "Ready. Type and press Send. Use the dropdown to run Assist or Search.",
            }.get(self.page_mode, "Ready.")
            self.controller.bubble("AI ChatBot", welcome)
    # --- new: handle send depending on locked page_mode ---

    # ====== OneChatPage: helpers for AI-Chat persistence ======
    def _open_report_modality_menu(self, text: str):
        """Show dropdown for selecting modality before sending report."""
        menu = QMenu(self)
        modalities = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]
        for mod in modalities:
            act = QAction(mod, menu)
            act.triggered.connect(
                lambda checked, m=mod, t=text: self._send_with_mode(t, "Report", modality=m)
            )
            menu.addAction(act)
        # Position menu under the Send button
        btn = self.composer.btn_send
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
    def _read_json_file(self, path: str) -> dict:
        """خواندن امن JSON؛ در خطا خروجی خالی می‌دهد."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json
                return json.load(f) or {}
        except Exception:
            return {}

    def eventFilter(self, obj, ev):
        """Keep the floating attachment bar pinned to the bottom of the chat viewport."""
        try:
            vp = getattr(getattr(self, "history", None), "scroll", None)
            vp = vp.viewport() if vp is not None else None
            if vp is not None and obj is vp:
                if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                    QTimer.singleShot(0, self.composer._reposition_attachment_overlay)
        except Exception:
            pass
        return super().eventFilter(obj, ev)


    def _load_saved_ai_chat_texts(self, sid: str):
        """
        اگر فایل‌های <AI-Chat>/<sid>-standard.json و/یا <sid>-transcribe.json وجود داشته باشند،
        محتوا را داخل تب‌های مربوطه می‌ریزد و تب مناسب را انتخاب می‌کند.

        Fix:
        - Load BOTH standard languages (text_en/text_fa) if available.
        - Legacy fallback: if only "text" exists, detect FA vs EN and place into correct buffer.
        """
        import os, re
        if not sid:
            return

        def _looks_persian(s: str) -> bool:
            s = s or ""
            # Arabic/Persian blocks
            return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", s))

        base = self._ai_chat_dir()
        std_file = os.path.join(base, f"{sid}-standard.json")
        tr_file  = os.path.join(base, f"{sid}-transcribe.json")
        tpl_file = os.path.join(base, f"{sid}-normal_template.json")

        std_data = {}
        std_txt = ""
        tr_txt  = ""
        tpl_txt = ""

        if os.path.exists(std_file):
            std_data = self._read_json_file(std_file) or {}
            std_txt = (std_data.get("text") or "").strip()

        if os.path.exists(tr_file):
            tr_data = self._read_json_file(tr_file) or {}
            tr_txt = (tr_data.get("text") or "").strip()

        if os.path.exists(tpl_file):
            tpl_data = self._read_json_file(tpl_file) or {}
            tpl_txt = (tpl_data.get("text") or "").strip()

        # ---------- Standard: load both langs ----------
        en_std = (std_data.get("text_en") or "").strip()
        fa_std = (std_data.get("text_fa") or "").strip()

        # Legacy fallback: only "text" existed (old files)
        if not en_std and not fa_std and std_txt:
            if _looks_persian(std_txt):
                fa_std = std_txt
            else:
                en_std = std_txt

        if en_std or fa_std:
            self.composer.install_lang_buttons()
            self.composer.set_standard_result(
                en_text=(en_std or None),
                fa_text=(fa_std or None),
            )
        else:
            self.composer.set_tab_text("standard", "")

        # Transcribe tab
        self.composer.set_tab_text("transcribe", tr_txt or "")

        # Normal Template tab
        self.composer.set_tab_text("normal_template", tpl_txt or "")

        if en_std or fa_std:
            self.composer.switch_tab("standard")
        elif tr_txt:
            self.composer.switch_tab("transcribe")
        elif tpl_txt:
            self.composer.switch_tab("normal_template")

        # cursor to end
        c = self.composer.box.textCursor()
        c.movePosition(QTextCursor.End)
        self.composer.box.setTextCursor(c)

        def _extract_display_text(raw_output, lang: str) -> str:
            """
            Minimal extractor (same spirit as _standardize_now) for disk-loaded raw/parsed.
            lang: 'en' or 'fa'
            """
            obj = _try_json(raw_output)

            if isinstance(obj, str):
                return obj.strip()

            if isinstance(obj, list):
                parts = [str(x).strip() for x in obj if str(x).strip()]
                return "\n".join(parts).strip()

            if isinstance(obj, dict):
                # nested "english"/"persian"
                if lang == "en" and "english" in obj:
                    return _extract_display_text(obj["english"], "en")
                if lang == "fa" and "persian" in obj:
                    return _extract_display_text(obj["persian"], "fa")

                # language-specific finals
                en_keys = ("final_report_english", "final_report_en", "report_english", "standard_report_english")
                fa_keys = ("final_report_persian", "final_report_fa", "final_report_pa", "report_persian", "standard_report_persian")

                for k in (en_keys if lang == "en" else fa_keys):
                    v = obj.get(k, None)
                    if isinstance(v, str) and v.strip():
                        return v.replace("\\n", "\n").strip()

                # final_report could be dict with langs
                final = obj.get("final_report", None)
                if isinstance(final, dict):
                    cand = None
                    if lang == "en":
                        cand = final.get("english") or final.get("en")
                    else:
                        cand = final.get("persian") or final.get("fa") or final.get("pa")
                    if isinstance(cand, str) and cand.strip():
                        return cand.replace("\\n", "\n").strip()

                # cleaned sentences
                arr = obj.get("cleaned_sentences_english" if lang == "en" else "cleaned_sentences_persian", None)
                if isinstance(arr, list):
                    parts = [str(x).strip() for x in arr if str(x).strip()]
                    base = "\n".join(parts).strip()
                    if base:
                        return base

                # last: generic final_report string
                if isinstance(final, str) and final.strip():
                    return final.replace("\\n", "\n").strip()

            return ""

        base = self._ai_chat_dir()
        std_file = os.path.join(base, f"{sid}-standard.json")
        tr_file  = os.path.join(base, f"{sid}-transcribe.json")
        tpl_file = os.path.join(base, f"{sid}-normal_template.json")

        std_txt = ""
        tr_txt  = ""
        tpl_txt = ""

        std_data = {}
        if os.path.exists(std_file):
            std_data = self._read_json_file(std_file) or {}
            std_txt = (std_data.get("text") or "").strip()

        if os.path.exists(tr_file):
            tr_data = self._read_json_file(tr_file) or {}
            tr_txt = (tr_data.get("text") or "").strip()

        if os.path.exists(tpl_file):
            tpl_data = self._read_json_file(tpl_file) or {}
            tpl_txt = (tpl_data.get("text") or "").strip()

        # ---------- Standard: load both langs ----------
        en_std = (std_data.get("text_en") or "").strip()
        fa_std = (std_data.get("text_fa") or "").strip()

        # If not present, try reconstruct from parsed/raw
        if not en_std and not fa_std and std_data:
            parsed = std_data.get("parsed", None)
            raw_s = std_data.get("raw_standardize_output", None)

            # 1) parsed preferred (already dict)
            if isinstance(parsed, dict):
                en_raw = parsed.get("english") or parsed.get("en")
                fa_raw = parsed.get("persian") or parsed.get("fa") or parsed.get("pa")
                en_std = _extract_display_text(en_raw, "en").strip()
                fa_std = _extract_display_text(fa_raw, "fa").strip()

            # 2) raw string next (json-dumps({"en":..., "fa":...}))
            if (not en_std and not fa_std) and isinstance(raw_s, str) and raw_s.strip():
                try:
                    raw_obj = json.loads(_strip_fences(raw_s))
                except Exception:
                    raw_obj = None
                if isinstance(raw_obj, dict):
                    en_std = _extract_display_text(raw_obj.get("en"), "en").strip()
                    fa_std = _extract_display_text(raw_obj.get("fa"), "fa").strip()

        # Legacy fallback: only "text" existed
        if not en_std and not fa_std and std_txt:
            if _looks_persian(std_txt):
                fa_std = std_txt
            else:
                en_std = std_txt

        # Apply to composer
        if en_std or fa_std:
            self.composer.install_lang_buttons()
            self.composer.set_standard_result(en_text=(en_std or None), fa_text=(fa_std or None))
        else:
            self.composer.set_tab_text("standard", "")

        # ---------- Transcribe ----------
        self.composer.set_tab_text("transcribe", tr_txt or "")

        # ---------- Normal Template ----------
        self.composer.set_tab_text("normal_template", tpl_txt or "")

        # Select best tab
        if en_std or fa_std:
            self.composer.switch_tab("standard")
        elif tr_txt:
            self.composer.switch_tab("transcribe")
        elif tpl_txt:
            self.composer.switch_tab("normal_template")

        # cursor end
        c = self.composer.box.textCursor()
        c.movePosition(QTextCursor.End)
        self.composer.box.setTextCursor(c)


    def _show_modality_menu(self):
        """Open the modality dropdown.

        Allowed in:
        - Report pages (page_mode == "Report")
        - ChatGPT page only when ChatGPT sub-mode == "report" (page_mode == "ChatGPT")
        """
        allow = False
        try:
            if str(getattr(self, "page_mode", "")).lower() == "report":
                allow = True
            elif str(getattr(self, "page_mode", "")).lower() == "chatgpt" and getattr(self, "_chatgpt_mode", None) == "report":
                allow = True
        except Exception:
            allow = False

        if not allow:
            return

        menu = QMenu(self)
        # Match the style/appearance used in other dropdowns (e.g., Report quality menu)
        try:
            menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 16px;
                color: #ddd;
                background-color: transparent;
                border-radius: 4px;
                margin: 2px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
                color: #fff;
            }
            QMenu::item:hover {
                background-color: #4a4a4a;
            }
        """)
        except Exception:
            pass

        current_mod = getattr(self, "_current_modality", None)
        for mod in ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]:
            act = QAction(mod, menu)
            act.setCheckable(True)
            if mod == current_mod:
                act.setChecked(True)
            act.triggered.connect(lambda checked, m=mod: self._select_modality(m))
            menu.addAction(act)

        # Use the same popup behavior everywhere (Report + ChatGPT) for identical UX
        try:
            anchor = self.composer.btn_modality
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            try:
                menu.exec(QCursor.pos())
            except Exception:
                pass


    def _is_network_or_server_down(self, raw: str) -> bool:
        s = (raw or "").lower()
        markers = [
            "httpconnectionpool", "httpsconnectionpool",
            "max retries exceeded",
            "failed to establish a new connection",
            "connection refused", "winerror 10061",
            "a socket operation was attempted to an unreachable host", "winerror 10065",
            "timed out", "timeout", "connecttimeout", "readtimeout",
            "name resolution error", "failed to resolve", "getaddrinfo failed", "errno 11001",
            "temporary failure in name resolution",
            "bad gateway", "service unavailable", "gateway time-out",
            "502", "503", "504",
        ]
        return any(m in s for m in markers)

    def _scrub_sensitive_net_info(self, raw: str) -> str:
        import re
        s = raw or ""
        # hide full URLs
        s = re.sub(r"(?i)https?://[^\s'\"<>]+", "<URL>", s)
        # hide host/port patterns from urllib3
        s = re.sub(r"host='[^']+'", "host='<hidden>'", s)
        s = re.sub(r"port=\d+", "port=<hidden>", s)
        # hide endpoint in "with url: /xxx"
        s = re.sub(r"with url:\s*/[^\s)]+", "with url:<hidden>", s)
        # hide naked IPs if any appear
        s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<IP>", s)
        return s

    def _safe_user_error(self, raw: str) -> str:
        if self._is_network_or_server_down(raw):
            return "❌ Connection failed. Please check your internet connection or contact support."
        return self._scrub_sensitive_net_info(raw)

    def _refresh_correction_reports_dropdown(self):
        """
        پر کردن dropdown ریپورت‌های Correction برای سشن فعلی،
        بدون نیاز به ترک چت / تعویض سشن.
        """
        sid = getattr(self, "current_session_id", None) or getattr(self.controller, "session_id", None)
        if not sid:
            return

        # preserve current selection if any
        try:
            prev = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            prev = ""

        report_items: list[tuple[str, str | None]] = []

        # 1) Prefer ai_reports
        try:
            fn = getattr(U, "ai_fetch_reports_for_session", None)
            if callable(fn):
                for _, msg_id, label, raw_en, _ in (fn(sid) or []):
                    if isinstance(raw_en, str) and raw_en.strip():
                        report_items.append((raw_en, label if isinstance(label, str) else None))
        except Exception:
            pass

        # 2) Fallback: derive from report bubbles in ai_messages (old sessions)
        if not report_items:
            try:
                rows = U.ai_fetch_messages_full(sid) or []
            except Exception:
                rows = []

            try:
                insert_fn = getattr(U, "ai_insert_report", None)
            except Exception:
                insert_fn = None

            n = 0
            for msg_id, who, html, origin in (rows or []):
                if origin != "report":
                    continue
                if not isinstance(html, str) or not html.strip():
                    continue

                n += 1
                raw = html.strip()

                try:
                    plain = self._html_to_plain_text(raw) if raw else ""
                    first_line = next((ln.strip() for ln in (plain or "").splitlines() if ln.strip()), "")
                    label = (first_line[:80] if first_line else f"Report {n}")
                except Exception:
                    label = f"Report {n}"

                report_items.append((raw, label))

                # backfill so next time dropdown works directly from ai_reports too
                if callable(insert_fn):
                    try:
                        insert_fn(
                            sid,
                            int(msg_id) if msg_id is not None else None,
                            raw,
                            study_uid=getattr(self, "study_uid", None),
                            label=label,
                            kind="report",
                        )
                    except Exception:
                        pass

        # 3) Fill dropdown
        try:
            self.composer.clear_correction_reports()
            for raw, label in report_items:
                self.composer.register_correction_report(raw, label=label)
        except Exception:
            return

        # 4) restore previous selection if possible
        if prev:
            try:
                cmb = self.composer.cmb_corr_reports
                for i in range(1, cmb.count()):
                    if (cmb.itemData(i) or "").strip() == prev:
                        cmb.setCurrentIndex(i)
                        break
            except Exception:
                pass


    def _session_roles(self):
        """Custom roles for sidebar items."""
        base_title_role = int(Qt.UserRole) + 10
        pinned_role = int(Qt.UserRole) + 11
        return base_title_role, pinned_role

    def _session_pins_path(self) -> str:
        import os
        return os.path.join(self._ai_chat_dir(), "_session_pins.json")

    def _load_pinned_sids(self) -> list[str]:
        """
        NEW: pinned state comes from DB (ai_sessions.pinned).
        Fallback: if DB has no pins but legacy _session_pins.json exists, migrate it into DB once.
        """
        # 1) DB pins (persistent across restarts / cwd changes)
        try:
            study_uid = getattr(self, "study_uid", None)
            pins = U.ai_fetch_pinned_sids(study_uid) if study_uid else U.ai_fetch_pinned_sids(None)
            if isinstance(pins, list) and pins:
                return [str(x) for x in pins if str(x).strip()]
        except Exception:
            pins = []

        # 2) Legacy file fallback + one-time migration to DB
        try:
            path = self._session_pins_path()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            legacy = data.get("pinned", [])
            if isinstance(legacy, list):
                legacy = [str(x) for x in legacy if str(x).strip()]
            else:
                legacy = []
            if legacy:
                try:
                    study_uid = getattr(self, "study_uid", None)
                    U.ai_set_pinned_bulk(study_uid if study_uid else None, legacy)
                except Exception:
                    pass
            return legacy
        except Exception:
            return []


    def _save_pinned_sids(self, pinned: list[str]) -> None:
        """
        NEW: persist pins into DB.
        (Optional) keeps writing legacy file only if DB update fails.
        """
        pinned = [str(x) for x in (pinned or []) if str(x).strip()]

        # DB persist (preferred)
        try:
            study_uid = getattr(self, "study_uid", None)
            U.ai_set_pinned_bulk(study_uid if study_uid else None, pinned)
            return
        except Exception:
            pass

        # Legacy file fallback (best-effort)
        import time
        payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pinned": pinned,
        }
        try:
            self._atomic_write_json(self._session_pins_path(), payload)
        except Exception:
            try:
                with open(self._session_pins_path(), "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                pass


    def _is_session_pinned(self, sid: str) -> bool:
        if not sid:
            return False
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
            self._pinned_sids = pins
        return sid in set(pins)

    def _set_session_pinned(self, sid: str, pinned: bool) -> None:
        if not sid:
            return
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
        pins = [x for x in pins if x != sid]
        if pinned:
            pins.insert(0, sid)  # newest pin on top
        self._pinned_sids = pins
        self._save_pinned_sids(pins)

    def _find_sidebar_item_by_sid(self, sid: str) -> QListWidgetItem | None:
        if not sid:
            return None
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it and it.data(Qt.UserRole) == sid:
                return it
        return None

    def _get_item_base_title(self, it: QListWidgetItem) -> str:
        base_title_role, _ = self._session_roles()
        try:
            v = it.data(base_title_role)
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            pass
        # fallback: strip pin prefix
        t = (it.text() or "").strip()
        if t.startswith("📌 "):
            t = t[2:].strip()
        return t or "New Chat"

    def _apply_item_title_and_style(self, it: QListWidgetItem, base_title: str, *, sid: str | None = None):
        """Set displayed title with pin prefix (if pinned) and keep base title in item data."""
        base_title_role, pinned_role = self._session_roles()
        base_title = (base_title or "").strip() or "New Chat"

        if sid is None:
            sid = it.data(Qt.UserRole)

        pinned = self._is_session_pinned(str(sid)) if sid else False

        try:
            it.setData(base_title_role, base_title)
            it.setData(pinned_role, bool(pinned))
        except Exception:
            pass

        shown = f"📌 {base_title}" if pinned else base_title
        it.setText(shown)

        # subtle emphasis for pinned (bold)
        try:
            from PySide6.QtGui import QFont
            f = it.font()
            f.setBold(bool(pinned))
            it.setFont(f)
        except Exception:
            pass

    def _ensure_sessions_context_menu(self):
        """Bind context menu once."""
        if getattr(self, "_session_ctx_bound", False):
            return
        self._session_ctx_bound = True
        try:
            self.list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.list.customContextMenuRequested.connect(self._on_sessions_context_menu)
        except Exception:
            pass

    def _on_sessions_context_menu(self, pos):
        """Right-click on chat list => Pin/Unpin, Rename, Delete."""
        try:
            it = self.list.itemAt(pos)
            if not it:
                return
            sid = it.data(Qt.UserRole)
            if not sid:
                return

            pinned = self._is_session_pinned(sid)

            menu = QMenu(self)
            act_pin = QAction("📌 Pin" if not pinned else "📌 Unpin", menu)
            act_ren = QAction("✏️ Rename", menu)
            act_del = QAction("🗑️ Delete", menu)

            act_pin.triggered.connect(lambda _=False, s=sid: self._toggle_pin_session(s))
            act_ren.triggered.connect(lambda _=False, s=sid: self._rename_session_by_sid(s))
            act_del.triggered.connect(lambda _=False, s=sid: self._delete_session_by_sid(s))

            menu.addAction(act_pin)
            menu.addSeparator()
            menu.addAction(act_ren)
            menu.addAction(act_del)

            menu.exec(self.list.viewport().mapToGlobal(pos))
        except Exception:
            pass

    def _toggle_pin_session(self, sid: str):
        cur_sid = getattr(self, "current_session_id", None)
        new_state = not self._is_session_pinned(sid)
        self._set_session_pinned(sid, new_state)
        self._rebuild_sidebar_only(keep_selected_sid=cur_sid)

    def _rename_session_by_sid(self, sid: str):
        it = self._find_sidebar_item_by_sid(sid)
        if not it:
            return

        old = self._get_item_base_title(it)

        try:
            from PySide6.QtWidgets import QInputDialog, QLineEdit
            new_title, ok = QInputDialog.getText(
                self,
                "Rename chat",
                "New name:",
                QLineEdit.Normal,
                old
            )
        except Exception:
            return

        if not ok:
            return
        new_title = (new_title or "").strip()
        if not new_title:
            return

        # persist to DB (best-effort)
        try:
            U.ai_upsert_session(sid, new_title, getattr(self, "study_uid", None))
        except Exception:
            pass

        # update UI item (keeps pin prefix)
        self._apply_item_title_and_style(it, new_title, sid=sid)

    def _delete_session_by_sid(self, sid: str):
        if not sid:
            return
        try:
            from PySide6.QtWidgets import QMessageBox
            ans = QMessageBox.question(
                self,
                "Delete chat",
                "Are you sure you want to delete this chat?\n(This cannot be undone)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                return
        except Exception:
            return

        # 1) try DB delete if available in U (best-effort, safe)
        deleted_db = False
        for fn_name in (
            "ai_delete_session_and_messages",
            "ai_delete_session",
            "ai_remove_session",
            "ai_purge_session",
        ):
            fn = getattr(U, fn_name, None)
            if callable(fn):
                try:
                    fn(sid, getattr(self, "study_uid", None))
                    deleted_db = True
                    break
                except TypeError:
                    try:
                        fn(sid)
                        deleted_db = True
                        break
                    except Exception:
                        pass
                except Exception:
                    pass

        if not deleted_db:
            # try separate message purge + session row (still best-effort)
            for fn_name in ("ai_delete_messages_for_session", "ai_purge_session_messages", "ai_delete_messages"):
                fn = getattr(U, fn_name, None)
                if callable(fn):
                    try:
                        fn(sid)
                    except Exception:
                        pass
            for fn_name in ("ai_delete_session_row", "ai_delete_session_only"):
                fn = getattr(U, fn_name, None)
                if callable(fn):
                    try:
                        fn(sid, getattr(self, "study_uid", None))
                    except TypeError:
                        try:
                            fn(sid)
                        except Exception:
                            pass
                    except Exception:
                        pass

        # 2) delete persisted side files for that session (AI-Chat/<sid>-*.json)
        try:
            import os, glob
            pat = os.path.join(self._ai_chat_dir(), f"{sid}-*.json")
            for fp in glob.glob(pat):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        except Exception:
            pass

        # 3) remove from pins
        try:
            pins = getattr(self, "_pinned_sids", None)
            if not isinstance(pins, list):
                pins = self._load_pinned_sids()
            pins = [x for x in pins if x != sid]
            self._pinned_sids = pins
            self._save_pinned_sids(pins)
        except Exception:
            pass

        # 4) remove from UI + cache
        try:
            self.sessions.pop(sid, None)
        except Exception:
            pass

        # if deleting current open session => switch to another
        was_current = (getattr(self, "current_session_id", None) == sid)

        # remove list item
        try:
            it = self._find_sidebar_item_by_sid(sid)
            if it:
                row = self.list.row(it)
                self.list.takeItem(row)
        except Exception:
            pass

        if was_current:
            # pick next available
            if self.list.count() > 0:
                self.list.setCurrentRow(0)
                nxt = self.list.currentItem()
                if nxt:
                    self._open_session(nxt)
            else:
                # no session left => create new
                try:
                    self._new_session()
                except Exception:
                    self.controller.reset_session()
                    self.history.clear()


    def _rebuild_sidebar_only(self, *, keep_selected_sid: str | None = None):
        """Rebuild only the left list (does NOT re-render history)."""
        self._ensure_sessions_context_menu()

        # fetch sessions
        try:
            if getattr(self, "study_uid", None):
                sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
            else:
                sessions = U.ai_fetch_all_sessions() or []
            sessions = [(sid, title) for (sid, title) in sessions
                        if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]
        except Exception:
            sessions = []

        # apply pin ordering
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
        sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}

        cleaned_pins = [p for p in pins if p in sid_to_title]
        if cleaned_pins != pins:
            self._pinned_sids = cleaned_pins
            self._save_pinned_sids(cleaned_pins)

        ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
        pinned_set = set(cleaned_pins)
        ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

        # rebuild list without firing open_session
        try:
            self.list.blockSignals(True)
            self.list.clear()
            for sid, title in ordered:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)
        finally:
            try:
                self.list.blockSignals(False)
            except Exception:
                pass

        # restore selection (no open)
        target = keep_selected_sid or getattr(self, "current_session_id", None)
        if target:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it and it.data(Qt.UserRole) == target:
                    self.list.setCurrentItem(it)
                    break


    def _ai_chat_dir(self) -> str:
        """
        Returns the folder path for current study's AI-Chat data:
          <project_cwd>/attachment/<study_uid>/AI-Chat
        Creates it if needed.
        """
        from pathlib import Path
        import os

        study_uid = getattr(self, "study_uid", None) or "unknown"
        base = Path(os.getcwd()) / "attachment" / study_uid / "AI-Chat"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _atomic_write_json(self, file_path: str, data: dict):
        """
        Atomically writes JSON to file_path (UTF-8, pretty, safe replace).
        """
        import json, tempfile, shutil, os

        parent = os.path.dirname(file_path)
        os.makedirs(parent, exist_ok=True)

        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            shutil.move(tmp, file_path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _persist_transcribe(self, tr_text: str):
        """
        Saves the transcribe text to:
          <AI-Chat>/<session_id>-transcribe.json
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"
        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "transcribe",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": tr_text or ""
        }
        dst = os.path.join(self._ai_chat_dir(), f"{sid}-transcribe.json")
        self._atomic_write_json(dst, data)


    def _persist_normal_template(self, tpl_text: str):
        """
        Saves the normal template text to:
          <AI-Chat>/<session_id>-normal_template.json
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"
        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "normal_template",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": tpl_text or ""
        }
        dst = os.path.join(self._ai_chat_dir(), f"{sid}-normal_template.json")
        self._atomic_write_json(dst, data)

    def _persist_standard(
        self,
        std_text: str,
        *,
        text_en: str | None = None,
        text_fa: str | None = None,
        raw: str | None = None,
        parsed: dict | None = None
    ):
        """
        Saves the standard structured text and optional raw/parsed fields to:
        <AI-Chat>/<session_id>-standard.json

        Fix:
        - also store text_en / text_fa explicitly so EN/FA never collapse after reload.
        - keep legacy "text" for backward compatibility / quick preview.
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"

        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "standard",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": std_text or "",
        }

        # ✅ store BOTH language buffers (even if empty) so reload is deterministic
        if text_en is not None:
            data["text_en"] = text_en or ""
        if text_fa is not None:
            data["text_fa"] = text_fa or ""

        if raw is not None:
            data["raw_standardize_output"] = raw
        if parsed is not None:
            data["parsed"] = parsed

        dst = os.path.join(self._ai_chat_dir(), f"{sid}-standard.json")
        self._atomic_write_json(dst, data)


    def _continue_send_after_voices(self, user_text: str, tr_text: str, server_sid: t.Optional[str], mode: str):
        """
        بعد از آپلود چند ویس و دریافت متن ترنسکرایب:
          - متن‌های user و transcript را با هم merge می‌کنیم
          - در حالت Report طبق سیاست جدید: همان merged مستقیماً ارسال می‌شود (بدون استانداردسازی)
          - در حالت Assist/Chat مثل قبل
        """
        merged = (user_text or "").strip()
        tr = (tr_text or "").strip()

        if merged and tr:
            merged = f"{merged}\n{tr}"
        elif tr and not merged:
            merged = tr

        if mode == "Assist":
            self._open_assist_menu(merged)
            return

        if mode == "Report":
            # سیاست جدید: مستقیم همان متن را برای ساخت گزارش بفرست
            self._send_with_mode(merged, "Report")
            return

        # Chat و سایر
        self._send_with_mode(merged, "Chat")


    # متد جدید برای انتخاب مودالیتی
    def _select_modality(self, modality):
        self._current_modality = modality
        OneChatPage.last_selected_modality = modality  # class-level persistence
        self._set_modality_text(modality)

    def _set_modality_text(self, modality):
        short_text = modality[:4] + "..." if len(modality) > 4 else modality
        self.composer.btn_modality.setText(f"{short_text}")



    def _upload_voices_then(self, file_paths: t.List[str],
                            cont: t.Callable[[str, t.Optional[str]], None]):
        """
        Upload queued voice files as a multi-file request to the transcript API.
        Always calls: cont(transcript_text, session_id).
        """
        # ⬅️ همین که تایپینگ/بابل جدیدی قرار است اضافه شود، خوشامد را حذف کن
        self._drop_welcome_if_any()

        if not file_paths:
            cont("", None)
            return

        typing_b = self.history.add_typing("AI ChatBot", "Uploading voices")
        try:
            self.composer.set_enabled(False)
        except Exception:
            pass

        def cleanup_ui():
            try:
                self.history.remove_widget(typing_b)
            except Exception:
                pass
            try:
                self.composer.set_enabled(True)
            except Exception:
                pass

        def work():
            files = []
            try:
                for p in file_paths:
                    if not (p and os.path.exists(p)):
                        continue
                    files.append(("audio_files", open(p, "rb")))
                if not files:
                    raise Exception("No valid audio files to upload.")
                data = {"quality_mode": getattr(self.composer, "_transcribe_quality_mode", "clear")}
                r = requests.post(URL_GEN_TRANSCRIPT, files=files, data=data, timeout=360)
                r.raise_for_status()
                return r.json()
            finally:
                for _, fh in files:
                    try:
                        fh.close()
                    except Exception:
                        pass
        worker = ApiWorker(work, parent=self)
        if not hasattr(self, "_workers"):
            self._workers = []
        self._workers.append(worker)

        def _finish_worker():
            try:
                if worker in self._workers:
                    self._workers.remove(worker)
            except Exception:
                pass
            try:
                worker.deleteLater()
            except Exception:
                pass

        def ok(resp: dict):
            # ✅ Track transcript minutes for multi-file transcription
            try:
                self._log_irannobat_transcript_usage(resp, file_paths)
            except Exception:
                pass
            server_sid = resp.get("session_id")
            tr_text = (resp.get("transcript") or "").strip()

            if server_sid:
                try:
                    self.controller.switch_session(server_sid)
                except Exception:
                    pass

            try:
                self.composer.clear_pending_voices()
            except Exception:
                try:
                    self.composer.clear_attachment()
                except Exception:
                    pass

            # ------ 🔥 Bubble واقعی ویس (اصلاح اصلی) ------
            for p in file_paths:
                try:
                    self.history.add_voice("You", p)
                except Exception as e:
                    print("VoiceMessageBubble error:", e)

            # پس اگر ترنسکریپت از AI آمد → متنش را هم نشان بده
            if tr_text:
                self.controller.bubble("AI ChatBot", tr_text)

            cleanup_ui()
            _finish_worker()

        #    cont(tr_text, server_sid)

        def er(msg: str):
            try:
                safe = self._safe_user_error(msg)
                # اگر اینترنت/سرور قطع باشد، safe خودش پیام فارسی ثابت است
                self.controller.bubble("AI ChatBot", f"⚠️ <i>{safe}</i>")
            except Exception:
                pass
            cleanup_ui()
            _finish_worker()
            cont("", None)


        worker.done.connect(ok)
        worker.failed.connect(er)
        worker.start()


    def _send_report_correction(self, correction_note: str):
        """Correction tab: apply user's correction note to a selected report and display corrected report."""
        from .api_manager import APIKeyManager

        manager = APIKeyManager.instance()
        if not manager.is_validated():
            print("[Correction] blocked: API key not validated")
            self.controller.bubble("AI ChatBot", "❌ API Key not validated. Access denied.")
            return
        
        note = (correction_note or "").strip()
        try:
            # Get the ENTIRE original JSON report (not just plain text)
            report_text = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            report_text = ""
        
        if not report_text:
            print("[Correction] blocked: report not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a report from the Correction dropdown.</i>")
            return
        
        if not note:
            print("[Correction] blocked: empty note")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please write your correction notes in the box below.</i>")
            return

        print(f"[Correction] sending note_len={len(note)} report_len={len(report_text)}")
        
        # Show user's correction note
        self.controller.bubble("You (✅ Correction)", note)
        
        center_key = os.environ.get("CENTER_Key", "") or ""
        
        def work():
            return correction(
                user_report=report_text,  # Full JSON report
                correction_note=note,
                CENTER_Key=center_key,
                model="gpt-4.1-mini",
            )
        
        def ok(res):
            try:
                # Handle result
                sid_new = res.get("session_id") if isinstance(res, dict) else None
                if sid_new:
                    try:
                        self.controller.switch_session(sid_new)
                    except Exception:
                        pass
                
                # Extract corrected report
                corrected_text = res["content"].strip() if isinstance(res, dict) else str(res).strip()
                
                # Remove <|end|> if present
                if "<|end|>" in corrected_text:
                    corrected_text = corrected_text.split("<|end|>", 1)[0].strip().strip('```json').strip()
                
                # Parse the JSON to ensure it's valid
                import json
                try:
                    corrected_json = json.loads(corrected_text)
                    # Render as HTML report
                    html = self._render_kv_report_html([corrected_json])
                    self._bubble_origin_hint = "report"
                    self.controller.bubble("AI ChatBot", html)
                    
                    # Register corrected report for further corrections
                    raw_json = json.dumps(corrected_json, ensure_ascii=False, indent=2)
                    self.composer.register_correction_report(raw_json)
                except json.JSONDecodeError as e:
                    # Fallback if JSON is invalid
                    self.controller.bubble("AI ChatBot", f"⚠️ <i>Invalid JSON format in corrected report: {str(e)}</i>")
                    self.controller.bubble("AI ChatBot", f"<pre>{corrected_text}</pre>")
            
            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Error processing correction: {str(e)}")
        
        def er(msg: str):
            self.controller.bubble("AI ChatBot", f"❌ Correction failed: {self._safe_user_error(msg)}")
        
        self._run_async(work, ok, er, lock_btn=getattr(self.composer, "btn_send", None), typing="Applying corrections...")
        
    def _on_send_clicked(self, text: str):
        """
        رفتار جدید Send:
          - در حالت Report:
              * اگر تب فعال 'standard' و متن استاندارد داریم → همان را بفرست
              * اگر تب فعال 'transcribe' و متن ترنسکرایب داریم → همان را بفرست (بدون استانداردسازی)
              * در غیر این صورت، اگر ویس در صف است → اول ترنسکرایب، بعد «همان متن ترنسکرایب شده» را بفرست
              * اگر هیچ‌کدام نبودند → مثل قبل، متن جعبه را بفرست
          - سایر مودها (Chat / Assist / Search) مثل قبل با یک تفاوت: تغییری ندادیم
        """
        txt = text or ""
        mode = self.page_mode
        
        # متن‌های هر تب (و سینک بافر تب فعال)
        std_text, tr_text = self.composer.get_tab_texts()
        std_text = (std_text or "").strip()
        tr_text = (tr_text or "").strip()
        active_tab = self.composer.get_active_tab()
        
        # صف ویس‌ها
        try:
            voices = self.composer.get_pending_voices()
        except Exception:
            voices = []

        # ✅ Correction tab override (no voice support here)
        try:
            active_tab = self.composer.get_active_tab()
        except Exception:
            active_tab = ""

        if active_tab == "correction":
            if voices:
                self.controller.bubble(
                    "AI ChatBot",
                    "⚠️ <i>Correction does not support voice input. Please remove voice chips or switch tab.</i>",
                )
                return

            # Correction is a Report-tab feature (report selected from dropdown + note in textbox)
            if mode == "Report":
                self._send_report_correction(txt)
            else:
                self.controller.bubble("AI ChatBot", "⚠️ <i>Correction is only available in Report mode.</i>")
            return

            
        # --- منطق ویژه برای Report ---
        if mode == "Report":
            # ✅ Correction tab: user selects report from dropdown + writes correction note.
            if active_tab == "correction":
                self._send_report_correction(txt)
                return

            # Always use the persisted modality — no menu anymore
            modality = getattr(self, "_current_modality", None)
            if not modality:
                self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a modality first.</i>")
                return

            if active_tab == "standard" and std_text:
                self._send_with_mode(std_text, "Report", modality=modality)
                return
            if active_tab == "transcribe" and tr_text:
                self._send_with_mode(tr_text, "Report", modality=modality)
                return
            if active_tab == "normal_template":
                if tr_text:
                    self._send_with_mode(tr_text, "Report", modality=modality)
                    return
                if std_text:
                    self._send_with_mode(std_text, "Report", modality=modality)
                    return

            if voices:
                def cont_with_modality(tr, sid):
                    merged = (txt or "").strip()
                    tr = (tr or "").strip()
                    if merged and tr:
                        merged = f"{merged}\n{tr}"
                    elif tr:
                        merged = tr
                    self._send_with_mode(merged, "Report", modality=modality)
                self._upload_voices_then(file_paths=voices, cont=cont_with_modality)
                return
            self._send_with_mode(txt.strip(), "Report", modality=modality)
            return
                    
            # اگر مودالیتی انتخاب نشده باشد، منوی انتخاب نمایش داده شود
            if active_tab == "standard" and std_text:
                self._open_report_modality_menu(std_text)
                return
            if active_tab == "transcribe" and tr_text:
                self._open_report_modality_menu(tr_text)
                return
            if voices:
                def cont_with_menu(tr, sid):
                    merged = (txt or "").strip()
                    tr = (tr or "").strip()
                    if merged and tr:
                        merged = f"{merged}\n{tr}"
                    elif tr:
                        merged = tr
                    self._open_report_modality_menu(merged)
                self._upload_voices_then(file_paths=voices, cont=cont_with_menu)
                return
            self._open_report_modality_menu(txt.strip())
            return
        
        # --- سایر مودها مثل قبل ---
        if voices:
            self._upload_voices_then(
                file_paths=voices,
                cont=lambda tr_text2, server_sid: self._continue_send_after_voices(
                    user_text=txt, tr_text=tr_text2, server_sid=server_sid, mode=mode
                )
            )
            return
        if mode == "Assist":
            self._open_assist_menu(txt)
        elif mode in ("Chat", "Report"):
            self._send_with_mode(txt, mode)
        else:
            self._send_with_mode(txt, "Chat")


    def _on_hq_all_modality_clicked(self):
        from .api_manager import APIKeyManager
        manager = APIKeyManager.instance()
        
        # ✅ Check validation
        if not manager.is_validated():
            print("[Turbo] blocked: API key not validated")
            self.controller.bubble(
                "AI ChatBot",
                "❌ API Key not validated. Please restart application."
            )
            return
        
        # Get current key
        center_key = manager.get_current_key()

        if str(getattr(self, "page_mode", "")).lower() not in ("report", "chatgpt"):
            print("[Turbo] blocked: invalid page_mode")
            return

        # متن را مشابه منطق Send انتخاب کن
        std_text, tr_text = self.composer.get_tab_texts()
        std_text = (std_text or "").strip()
        tr_text  = (tr_text  or "").strip()
        active_tab = self.composer.get_active_tab()

        if active_tab == "standard" and std_text:
            user_msg = std_text
        elif active_tab == "transcribe" and tr_text:
            user_msg = tr_text
        elif active_tab == "normal_template":
            # هنگام ادیت Template، متن اصلی را از Transcribe (یا Standard) بگیر
            if tr_text:
                user_msg = tr_text
            elif std_text:
                user_msg = std_text
            else:
                user_msg = ""
        else:
            user_msg = (self.composer.box.toPlainText() or "").strip()

        # Always use the persisted modality — no menu anymore
        modality = getattr(self, "_current_modality", None)
        if not modality:
            print("[Turbo] blocked: modality not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a modality first.</i>")
            return
        try:
            normal_template = (self.composer.get_normal_template_plain_text() or "").strip() or None
        except Exception:
            normal_template = None
        center_key = os.environ.get("CENTER_Key", "") or ""

        # برای لاگ/تاریخچه
        self.controller.bubble("You (⚡Turbo Mode)", user_msg or "(session-based)")
        print(
            f"[Turbo] sending text_len={len((user_msg or '').strip())} modality={modality}"
        )

        def work():

            return reporter(
                user_msg=user_msg,
                modality=modality,
                normal_template=(normal_template or None),
                CENTER_Key=center_key,  
                model="gpt-4.1-mini",
            )

        def ok(res):
            try:
                if isinstance(res, dict) and "usage" in res:
                    sid_new = res.get("session_id")
                    if sid_new:
                        try:
                            self.controller.switch_session(sid_new)
                        except Exception:
                            pass

                rep_raw_clean = self._normalize_report_like_payload(res)

                if not rep_raw_clean.strip():
                    self.controller.bubble("AI ChatBot", "⚠️ Empty output.")
                    return

                self._pending_report_raw_en = rep_raw_clean
                items = self._parse_jsonish_list(rep_raw_clean)

                # ✅ Filter out non-report / reasoning keys (we only want report-like fields)
                try:
                    import re
                    keep_keys = {
                        "Report Title", "Pathological Findings", "Normal Findings",
                        "Recommendations", "Recommendation",
                        "Impression", "Impressions", "Conclusion",
                        "عنوان گزارش", "یافته‌های پاتولوژیک", "یافته های پاتولوژیک",
                        "یافته‌های طبیعی", "یافته های طبیعی",
                        "توصیه‌ها", "توصیه ها", "پیشنهادات", "پیشنهادها", "ریکامندیشن",
                        "نتیجه گیری", "ایمپرشن"
                    }

                    filtered_items = []
                    for d in (items or []):
                        if not isinstance(d, dict):
                            continue
                        if any(k in d for k in keep_keys):
                            nd = {k: d[k] for k in d.keys() if k in keep_keys}
                            filtered_items.append(nd or d)
                        else:
                            noisy_pat = re.compile(
                                r"(?i)(^step_\d+|reasoning|knowledge|mode|clinical|primary diagnoses|terminology|differential)"
                            )
                            nd = {k: v for k, v in d.items() if not noisy_pat.search(str(k).strip())}
                            filtered_items.append(nd if nd else d)
                    items = filtered_items or items
                except Exception:
                    pass
                html = self._render_kv_report_html(items)
                self._bubble_origin_hint = "report"
                self.controller.bubble("AI ChatBot", html)

            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Render error: {e}")

        def er(msg: str):
            # msg از _run_async از قبل امن شده
            self.controller.bubble("AI ChatBot", msg)



        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self.composer, "btn_send", None),
                typing="HQ Model…"
            )
        )


    def _open_assist_menu(self, text: str):
        menu = QMenu(self)
        has_text = bool(text.strip()) or bool(self.controller.session_id)

        items = [
            ("Assistant", has_text, "Enter some text or use an existing session."),
            ("Search", bool(text.strip()), "For Search, you must enter text."),
        ]

        for name, enabled, tip in items:
            act = QAction(name, menu)
            act.setEnabled(enabled)
            if enabled:
                act.triggered.connect(lambda _=False, n=name, t=text: self._send_with_mode(t, "Assistant" if n=="Assistant" else "Search"))
            else:
                act.setToolTip(tip)
            menu.addAction(act)

        btn = self.composer.btn_send
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _log_irannobat_usage_from_resp(self, resp: object, model_name: str = "Irannobat") -> None:
        """
        Count + persist token usage for responses coming from the local IRANNOBAT server
        (e.g., 87.236.166.66 endpoints). Server responses typically include:
            prompt_tokens, completion_tokens, total_tokens
        This updates BOTH:
        - api_usage.json (via Manage)
        - SQLite token tables (for Welcome UI)
        """
        try:
            if not isinstance(resp, dict):
                return

            # accept either flat fields or nested `usage`
            usage = resp.get("usage")
            src = usage if isinstance(usage, dict) else resp

            def _as_int(x) -> int:
                try:
                    return int(x)
                except Exception:
                    return 0

            p = _as_int(src.get("prompt_tokens"))
            c = _as_int(src.get("completion_tokens"))
            t = _as_int(src.get("total_tokens"))

            # if only split exists, compute total
            if t <= 0 and (p > 0 or c > 0):
                t = p + c

            if t <= 0:
                return

            m = Manage.instance()
            if not m.is_validated():
                return

            # Prefer split if available
            if p > 0 or c > 0:
                m.update_usage(model=model_name, prompt_tokens=p, completion_tokens=c)
            else:
                m.update_usage_total(model=model_name, total_tokens=t)

        except Exception:
            # never break UI for logging failures
            return


    def _log_irannobat_transcript_usage(
        self,
        resp: dict | None,
        file_paths: list[str] | None,
    ) -> None:
        """
        FIX: Do NOT use quality_report.criteria.* for duration (it's usually a constant threshold).
        We log usage from local audio duration; response duration is fallback only.
        """
        try:
            import os, re
            import soundfile as sf
        except Exception:
            return

        center = (
            getattr(self, "center", None)
            or getattr(self, "center_name", None)
            or getattr(self, "current_center", None)
            or "<unknown>"
        )
        model_name = "irannobat transcript model"

        # Use the same key source as Welcome (avoid mismatch)
        api_key = ""
        try:
            from .api_manager import Manage
            m = Manage.instance()
            api_key = (m.get_irannobat_key() or "").strip() or (m.get_last_api_key() or "").strip()
        except Exception:
            api_key = ""
        if not api_key:
            api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return

        def _duration_seconds_from_file(path: str) -> float:
            try:
                if not path or not os.path.exists(path):
                    return 0.0

                # soundfile (wav/flac/ogg/…)
                try:
                    info = sf.info(path)
                    dur = float(getattr(info, "duration", 0.0) or 0.0)
                    if dur > 0:
                        return dur
                    frames = float(getattr(info, "frames", 0.0) or 0.0)
                    sr = float(getattr(info, "samplerate", 0.0) or 0.0)
                    if frames > 0 and sr > 0:
                        return frames / sr
                except Exception:
                    pass

                # built-in WAV fallback
                if str(path).lower().endswith(".wav"):
                    try:
                        import wave
                        with wave.open(path, "rb") as wf:
                            frames = wf.getnframes()
                            rate = wf.getframerate()
                            if frames > 0 and rate > 0:
                                return float(frames) / float(rate)
                    except Exception:
                        pass

                # optional pydub fallback (mp3/m4a/…)
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment.from_file(path)
                    return float(len(seg)) / 1000.0
                except Exception:
                    return 0.0
            except Exception:
                return 0.0

        # 1) Prefer local duration (REAL duration)
        local_total = 0.0
        if file_paths:
            for p in list(file_paths):
                local_total += _duration_seconds_from_file(p)

        total_seconds = int(round(local_total)) if local_total > 0 else 0

        # 2) Fallback: derive from response, but IGNORE quality_report.criteria
        if total_seconds <= 0:
            resp = resp or {}
            target_keys = {
                "duration", "duration_s", "duration_sec", "duration_secs", "duration_seconds",
                "speech_seconds", "audio_seconds", "seconds",
                "duration_ms", "audio_ms", "speech_ms", "audio_duration_ms", "total_duration_ms",
            }

            def _as_seconds(v) -> float:
                try:
                    if v is None:
                        return 0.0
                    if isinstance(v, (int, float)):
                        x = float(v)
                    elif isinstance(v, str):
                        m = re.search(r"[-+]?\d*\.?\d+", v.strip())
                        if not m:
                            return 0.0
                        x = float(m.group(0))
                    else:
                        return 0.0
                    return (x / 1000.0) if x > 200 else x  # heuristic: big numbers are ms
                except Exception:
                    return 0.0

            def _best_or_sum(node) -> float:
                # dict: take max best duration found (avoid double-count keys)
                # list: sum best duration per item (for per-file lists)
                try:
                    if isinstance(node, dict):
                        best = 0.0
                        for k, vv in node.items():
                            kl = str(k).lower()
                            if kl == "criteria":  # <-- critical: ignore thresholds
                                continue
                            if kl in target_keys:
                                best = max(best, _as_seconds(vv))
                            else:
                                best = max(best, _best_or_sum(vv))
                        return best
                    if isinstance(node, list):
                        return sum(_best_or_sum(it) for it in node)
                    return 0.0
                except Exception:
                    return 0.0

            resp_seconds = _best_or_sum(resp)
            if resp_seconds > 0:
                total_seconds = int(round(resp_seconds))

        if total_seconds <= 0:
            return

        # persist
        try:
            add_transcript_usage_delta(center, model_name, total_seconds)
        except Exception:
            pass
        try:
            add_api_transcript_usage_delta(
                api_key=api_key,
                center_name=center,
                model_name=model_name,
                seconds_delta=total_seconds,
            )
        except Exception:
            pass


    def _refresh_sessions_for_current_study(self):
        self._ensure_sessions_context_menu()
        self.list.clear()

        # fallback
        if not self.study_uid:
            try:
                sessions = U.ai_fetch_all_sessions() or []
            except Exception:
                sessions = []
            sessions = [(sid, title) for (sid, title) in sessions
                        if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]

            self._pinned_sids = self._load_pinned_sids()
            # order pins
            sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
            cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
            if cleaned_pins != self._pinned_sids:
                self._pinned_sids = cleaned_pins
                self._save_pinned_sids(cleaned_pins)

            ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
            pinned_set = set(cleaned_pins)
            ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

            for sid, title in ordered:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)
            return

        # study-specific
        sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
        if not sessions:
            sid = f"local-{uuid.uuid4().hex[:8]}"
            U.ai_upsert_session(sid, "New Chat", study_uid=self.study_uid)
            U.ai_set_last_session_for_study(self.study_uid, sid)
            sessions = [(sid, "New Chat")]

        # order pins
        self._pinned_sids = self._load_pinned_sids()
        sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
        cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
        if cleaned_pins != self._pinned_sids:
            self._pinned_sids = cleaned_pins
            self._save_pinned_sids(cleaned_pins)

        ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
        pinned_set = set(cleaned_pins)
        ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

        for sid, title in ordered:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, sid)
            self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
            self.list.addItem(it)

        # select last
        last_sid = U.ai_get_last_session_for_study(self.study_uid)
        if last_sid:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == last_sid:
                    self.list.setCurrentItem(it)
                    self._open_session(it)
                    break
                
    def _make_title_from_text(self, text: str, max_len: int = 28) -> str:
        """
        از اولین خطِ متن، یک عنوان کوتاه می‌سازد.
        اگر طول بیشتر از max_len باشد، با «…» کوتاه می‌کند.
        برای متون فارسی/RTL هم مشکلی ندارد.
        """
        if not text:
            return "New Chat"
        first_line = text.strip().splitlines()[0]
        # حذف فاصله‌های اضافی ابتدا/انتها
        s = first_line.strip()
        return (s if len(s) <= max_len else (s[:max_len].rstrip() + "…"))

    def _html_to_plain_text(self, html: str) -> str:
        """Convert stored bubble HTML to plain text suitable for correction dropdown."""
        s = (html or "").strip()
        if not s:
            return ""
        try:
            from PySide6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(s)
            out = (doc.toPlainText() or "").strip()
            return out
        except Exception:
            import re
            return re.sub(r"<[^>]+>", "", s).strip()


    def _retry_last_send(self):
        """Re-send the last failed user message with its original mode."""
        try:
            if not self._pending_retry:
                return
            mode = self._pending_retry.get("mode")
            text = self._pending_retry.get("text", "")
            bub = self._pending_retry.get("bubble")
            if bub:
                bub.clear_retry()
            # reset so در _append_bubble دوباره bubble نگه‌داری شود
            self._pending_retry = {"mode": mode, "text": text, "bubble": None}
            self._send_with_mode(text, mode)
        except Exception:
            pass

    def _ensure_local_session(self, title_hint: str = "New Chat") -> str:
        import uuid, time
        if self.current_session_id and str(self.current_session_id).startswith("local-"):
            return self.current_session_id

        local_sid = f"{self.ns}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.current_session_id = local_sid
        self.sessions.setdefault(local_sid, [])

        it = QListWidgetItem(self._make_title_from_text(title_hint or "New Chat", max_len=28))
        it.setData(Qt.UserRole, local_sid)
        self.list.insertItem(0, it)
        self.list.setCurrentItem(it)

        try:
            # ⬅️ study_uid هم ذخیره می‌شود
            U.ai_upsert_session(local_sid, title_hint or "New Chat", self.study_uid)
            if self.study_uid:
                U.ai_set_last_session_for_study(self.study_uid, local_sid)
            else:
                U.ai_set_last_session(local_sid)
        except Exception:
            pass

        return local_sid

    def _standardize_now(self, text: str):
        """
        Standardize current text and show both EN/FA in Standard tab.

        Fixes:
        - Use the real text to send (to_send), not the raw 'text' arg.
        - Support BOTH response schemas:
            A) {"standardize_output_english": "<json>", "standardize_output_persian": "<json>", ...}
            B) {"content": {... or "<json>"}, "usage": {...}}
        - If final_report is missing but cleaned_sentences_* exists, join them.
        - ✅ Robustness: if server swaps EN/FA occasionally, detect by charset and auto-swap.
        - ✅ Persist BOTH langs (text_en/text_fa) so reload never mixes them.
        """
        import json, re

        std_text, tr_text = self.composer.get_tab_texts()
        to_send = (tr_text or text or "").strip()
        if not to_send:
            print("[Standardize] blocked: empty text")
            self.controller.bubble("AI ChatBot", "⚠️ <i>No text to standardize.</i>")
            return
        print(f"[Standardize] sending text_len={len(to_send)}")

        def _strip_fences(s: str) -> str:
            s = (s or "").strip()
            s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.I)
            s = re.sub(r"\s*```\s*$", "", s)
            return s.strip()

        def _try_json(x):
            if x is None:
                return None
            if isinstance(x, (dict, list)):
                return x
            if not isinstance(x, str):
                return x
            s = _strip_fences(x)
            if not s:
                return ""
            try:
                return json.loads(s)
            except Exception:
                return s  # raw string

        def _looks_persian(s: str) -> bool:
            s = s or ""
            return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", s))

        def _looks_english(s: str) -> bool:
            s = s or ""
            return bool(re.search(r"[A-Za-z]", s)) and not _looks_persian(s)

        def _unpack_raw_outputs(resp: dict):
            """
            Returns: (en_raw, fa_raw) where each can be dict/list/str.
            """
            if not isinstance(resp, dict):
                return resp, resp

            # Schema A
            if ("standardize_output_english" in resp) or ("standardize_output_persian" in resp):
                return resp.get("standardize_output_english", "{}"), resp.get("standardize_output_persian", "{}")

            # Schema B
            content = resp.get("content", None)
            content = _try_json(content)

            if isinstance(content, dict):
                if ("english" in content) or ("persian" in content):
                    return content.get("english", ""), content.get("persian", "")
                if ("cleaned_sentences_english" in content) or ("cleaned_sentences_persian" in content):
                    return content, content
                if "final_report" in content:
                    return content, content

            if ("cleaned_sentences_english" in resp) or ("cleaned_sentences_persian" in resp) or ("final_report" in resp):
                return resp, resp

            return content if content is not None else resp, content if content is not None else resp

        def _extract_display_text(raw_output, lang: str) -> str:
            """
            lang: 'en' or 'fa'
            """
            obj = _try_json(raw_output)

            if isinstance(obj, str):
                return obj.strip()

            if isinstance(obj, list):
                parts = [str(x).strip() for x in obj if str(x).strip()]
                return "\n".join(parts).strip()

            if isinstance(obj, dict):
                if lang == "en" and "english" in obj:
                    return _extract_display_text(obj["english"], "en")
                if lang == "fa" and "persian" in obj:
                    return _extract_display_text(obj["persian"], "fa")

                base = ""
                final = obj.get("final_report", None)
                if isinstance(final, str) and final.strip():
                    base = final.replace("\\n", "\n").strip()
                else:
                    arr = obj.get("cleaned_sentences_english" if lang == "en" else "cleaned_sentences_persian", None)
                    if isinstance(arr, list):
                        parts = [str(x).strip() for x in arr if str(x).strip()]
                        base = "\n".join(parts).strip()

                if lang == "en":
                    impr = obj.get("impression_english", None)
                    reco = obj.get("recommendation_english", None)
                    impr_label = "Impression"
                    reco_label = "Recommendations"
                else:
                    impr = obj.get("impression_persian", None)
                    reco = obj.get("recommendation_persian", None)
                    impr_label = "نتیجه‌گیری"
                    reco_label = "توصیه‌ها"

                def _join_block(x):
                    if x is None:
                        return ""
                    if isinstance(x, list):
                        xs = [str(t).strip() for t in x if str(t).strip()]
                        return "\n".join(xs).strip()
                    if isinstance(x, str):
                        return x.strip()
                    return str(x).strip()

                impr_txt = _join_block(impr)
                reco_txt = _join_block(reco)

                extra = []
                if impr_txt:
                    extra.append(f"{impr_label}:\n{impr_txt}")
                if reco_txt:
                    extra.append(f"{reco_label}:\n{reco_txt}")

                if extra:
                    base = (base.strip() + "\n\n" + "\n\n".join(extra)).strip() if base else "\n\n".join(extra).strip()

                return base.strip()

            return ""

        def work():
            m = Manage.instance()
            if not m.is_validated():
                print("[Standardize] blocked: API key not validated")
                raise RuntimeError("❌ API key is not set. Please enter it only on the login page.")

            info = m.ensure_detected()
            center_key = info.irannobat_key

            if self.page_mode in ("Assist", "Search") and callable(globals().get("standard_assist_search", None)):
                print("[Standardize] using standard_assist_search")
                return standard_assist_search(user_msg=to_send, CENTER_Key=center_key)
            print("[Standardize] using standardize")
            return standardize(user_msg=to_send, CENTER_Key=center_key)

        def ok(resp: dict):
            print(f"\n{'='*80}")
            print("[STD] ✅ SUCCESS - Response received")
            print(f"{'='*80}")
            print(f"[STD] Response keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp)}")

            en_raw, fa_raw = _unpack_raw_outputs(resp)

            en_final_text = _extract_display_text(en_raw, "en")
            fa_final_text = _extract_display_text(fa_raw, "fa")

            if not en_final_text and not fa_final_text:
                raw_preview = ""
                try:
                    raw_preview = json.dumps(resp, ensure_ascii=False)[:1200]
                except Exception:
                    raw_preview = str(resp)[:1200]
                self.controller.bubble(
                    "AI ChatBot",
                    "⚠️ <i>Standardization returned empty output.</i>\n\n"
                    f"<pre>{raw_preview}</pre>"
                )
                return

            # ---------------------------
            # ✅ AUTO-SWAP if server mixed EN/FA
            # ---------------------------
            en_is_fa = _looks_persian(en_final_text)
            fa_is_fa = _looks_persian(fa_final_text)
            en_is_en = _looks_english(en_final_text)
            fa_is_en = _looks_english(fa_final_text)

            # Case 1: both present but swapped by charset
            if en_final_text and fa_final_text and en_is_fa and fa_is_en:
                print("[STD] ⚠️ Detected swapped EN/FA by charset -> swapping.")
                en_final_text, fa_final_text = fa_final_text, en_final_text
                en_raw, fa_raw = fa_raw, en_raw

            # Case 2: only one present but clearly belongs to the other slot
            elif en_final_text and not fa_final_text and en_is_fa:
                print("[STD] ⚠️ EN slot contains Persian while FA empty -> moving to FA.")
                fa_final_text, en_final_text = en_final_text, ""
                fa_raw, en_raw = en_raw, ""
            elif fa_final_text and not en_final_text and fa_is_en:
                print("[STD] ⚠️ FA slot contains English while EN empty -> moving to EN.")
                en_final_text, fa_final_text = fa_final_text, ""
                en_raw, fa_raw = fa_raw, ""

            # (If both are Persian or both are English, we don't guess; we keep as-is.)

            # --- set into composer (both langs) ---
            self.composer.set_standard_result(en_text=en_final_text, fa_text=fa_final_text)
            self.composer._is_standardized = True
            self.composer.switch_tab("standard")

            # --- persist: ✅ store BOTH langs so EN/FA never collapse after reload ---
            preferred_lang = getattr(self.composer, "_std_lang", "pa")
            text_to_persist = fa_final_text if preferred_lang == "pa" and fa_final_text else (en_final_text or "")

            try:
                self._persist_standard(
                    text_to_persist,
                    text_en=en_final_text,
                    text_fa=fa_final_text,
                    raw=json.dumps({"en": en_raw, "fa": fa_raw}, ensure_ascii=False),
                    parsed={"english": _try_json(en_raw), "persian": _try_json(fa_raw)},
                )
            except Exception as e:
                print(f"[STD-PERSIST] ❌ Persist failed: {type(e).__name__}: {e}")

            print(f"\n{'='*80}")
            print("[STD] ✅✅✅ STANDARDIZATION COMPLETE")
            print(f"{'='*80}\n")

        def er(msg: str):
            print(f"\n{'='*80}")
            print(f"[STD] ❌❌❌ ERROR: {msg}")
            print(f"{'='*80}\n")
            self.controller.bubble("AI ChatBot", f"⚠️ <i>{msg}</i>")

        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self, "composer", None) and getattr(self.composer, "btn_send", None),
                typing="Standardizing…"
            )
        )

    def _load_from_db_and_render(self) -> bool:
        loaded_any = False
        self._ensure_sessions_context_menu()

        try:
            try:
                U.ai_backfill_sessions_from_messages()
            except Exception:
                pass

            # 1) sessions
            try:
                if getattr(self, "study_uid", None):
                    sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
                else:
                    sessions = U.ai_fetch_all_sessions() or []

                # keep only our namespace sessions (e.g. "AIChat-...")
                try:
                    sessions = [(sid, title) for (sid, title) in (sessions or [])
                                if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]
                except Exception:
                    sessions = []
            except Exception:
                sessions = []

            # 1.5) apply pin ordering (persist pins under AI-Chat)
            self._pinned_sids = self._load_pinned_sids()
            sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
            cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
            if cleaned_pins != self._pinned_sids:
                self._pinned_sids = cleaned_pins
                self._save_pinned_sids(cleaned_pins)

            ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
            pinned_set = set(cleaned_pins)
            ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

            # 2) reset UI/cache
            self.sessions = {}
            self.list.clear()
            self.history.clear()

            # 3) build list + cache messages
            for sid, title in ordered:
                try:
                    rows = U.ai_fetch_messages_full(sid)
                except Exception:
                    rows = []

                self.sessions[sid] = [(who, html) for _, who, html, _ in (rows or [])]
                if rows:
                    loaded_any = True

                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)

            # 4) pick target
            try:
                if getattr(self, "study_uid", None):
                    last = U.ai_get_last_session_for_study(self.study_uid)
                else:
                    last = U.ai_get_last_session()
            except Exception:
                last = None

            target_sid = None
            if last and (last in self.sessions):
                target_sid = last
            elif self.sessions:
                target_sid = next(iter(self.sessions.keys()))

            if not target_sid:
                self.current_session_id = None
                self.controller.reset_session()
                return loaded_any

            # 5) select item
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == target_sid:
                    self.list.setCurrentItem(it)
                    break

            # 6) set current sid
            self.current_session_id = target_sid
            self.controller.switch_session(target_sid)

            # 7) load reports (raw EN) -> correction dropdown + attach to report bubbles
            report_map: dict[int, str] = {}
            report_list: list[str] = []
            try:
                fn = getattr(U, "ai_fetch_reports_for_session", None)
                if callable(fn):
                    for _, msg_id, _, raw_en, _ in (fn(target_sid) or []):
                        if isinstance(raw_en, str) and raw_en.strip():
                            report_list.append(raw_en)
                        try:
                            if msg_id is not None:
                                report_map[int(msg_id)] = raw_en
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                self.composer.clear_correction_reports()
                for raw in report_list:
                    self.composer.register_correction_report(raw)
            except Exception:
                pass

            # 8) render bubbles
            self.history.clear()
            try:
                rows = U.ai_fetch_messages_full(target_sid)
            except Exception:
                rows = []

            for msg_id, who, html, origin in rows:
                if not html:
                    continue
                is_user = who.strip().lower().startswith("you")
                # Enable buttons for all reports (not just origin=="report"), read from database
                on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
                on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
                # Enable send_to_reception for all non-user messages that have content
                on_send_reception = self._send_to_reception if (not is_user and html) else None

                b = self.history.add_bubble(who, html, on_edit=on_edit, on_persian=on_persian, on_send_reception=on_send_reception)
                b._origin = origin 
                try:
                    b._msg_id = int(msg_id)
                except Exception:
                    b._msg_id = msg_id

                # ✅ attach raw JSON to report bubbles so Persian/Edit works for old sessions
                try:
                    if origin == "report" and (not is_user):
                        raw = report_map.get(int(msg_id))
                        if raw:
                            b.raw_report_json = raw
                except Exception:
                    pass

            return loaded_any

        except Exception:
            return loaded_any

    def _send_to_reception(self, bubble: "MessageBubble"):
        """Send report to reception - reads from database for persistence."""
        import logging
        from datetime import datetime
        logger = logging.getLogger(__name__)
        
        # Print to console for visibility
        print("\n" + "="*100)
        print("🔴 USER CLICKED 'SEND TO RECEPTION' BUTTON")
        print("="*100)
        print(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        
        # Logging
        logger.info("\n" + "="*100)
        logger.info("🔴 USER CLICKED 'SEND TO RECEPTION' BUTTON")
        logger.info("="*100)
        logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        logger.info(f"Study UID: {self.study_uid}")
        
        # Get HTML from bubble
        html_content = ""
        try:
            html_content = (bubble.get_html() or "").strip()
            print(f"✅ HTML content extracted: {len(html_content)} characters")
            logger.info(f"✅ HTML content extracted: {len(html_content)} characters")
        except Exception as e:
            print(f"❌ Error extracting HTML: {e}")
            logger.error(f"❌ Error extracting HTML: {e}")
            return

        if not html_content:
            print("❌ Report content is empty!")
            logger.error("❌ Report content is empty!")
            QMessageBox.warning(self, "Error", "Report content is empty!")
            return

        # Get patient ID from database
        print("\n📊 Fetching patient information from database...")
        logger.info("📊 Fetching patient information from database...")
        
        patient_id = None
        if self.study_uid:
            try:
                from PacsClient.utils import db_manager as db

                study_data = db.get_study_by_study_uid(self.study_uid)
                if study_data:
                    patient_fk = study_data.get('patient_fk')
                    print(f"✅ Found - patient_fk: {patient_fk}")
                    logger.info(f"✅ Found - patient_fk: {patient_fk}")
                    
                    if patient_fk:
                        patient_data = db.get_patient_by_patient_pk(patient_fk)
                        if patient_data:
                            patient_id = patient_data.get('patient_id') or patient_data.get('patient_pk')
                            print(f"✅ Patient ID from database: {patient_id}")
                            logger.info(f"✅ Patient ID from database: {patient_id}")
            except Exception as e:
                print(f"❌ Error fetching patient: {e}")
                logger.error(f"❌ Error fetching patient: {e}")

        if not patient_id:
            default_value = (self.study_uid or "").strip()
            patient_id, ok = QInputDialog.getText(
                self,
                "Patient ID Required",
                "Automatic access to the patient ID is not available.\n"
                "Please enter the patient ID directly to send.",
                QLineEdit.Normal,
                default_value,
            )
            if not ok:
                logger.info("Patient ID entry canceled by user.")
                return
            patient_id = (patient_id or "").strip()

        if not patient_id:
            print("❌ Patient ID is invalid!")
            logger.error("❌ Patient ID is invalid!")
            QMessageBox.warning(
                self,
                "Patient ID Required",
                "Patient ID cannot be empty. Please enter a valid patient ID.",
            )
            return

        patient_validated = False
        try:
            base_url = "http://81.16.117.196:8080"
            validate_url = f"{base_url}/api/pacs/patients/{patient_id}"
            masked_url = "http://<host>/api/pacs/patients/<patient_id>"
            masked_id = "<patient_id>"
            t0 = time.perf_counter()
            logger.info(f"[RECEPTION_SERVER] → GET {masked_url} id={masked_id}")
            response = requests.get(validate_url, timeout=20)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                f"[RECEPTION_SERVER] ← status={response.status_code} elapsed_ms={elapsed_ms} content_type={response.headers.get('Content-Type')} content_length={response.headers.get('Content-Length')}"
            )

            if not response.ok:
                logger.warning("[RECEPTION_SERVER] ❌ Patient ID not found: <patient_id>")
                QMessageBox.warning(
                    self,
                    "Patient ID Not Found",
                    "The patient ID was not found on the server.\nPlease check and try again.",
                )
                return

            patient_validated = True
            try:
                response_json = response.json()
                logger.info(f"[RECEPTION_SERVER]   patient_json_keys={list(response_json.keys()) if isinstance(response_json, dict) else type(response_json)}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[RECEPTION_SERVER] ❌ Patient validation failed: {e}")
            QMessageBox.warning(
                self,
                "Patient ID Validation Failed",
                "Unable to validate the patient ID with the server.\nPlease try again.",
            )
            return

        # Save to database
        print(f"\n💾 Saving report to database...")
        print(f"   Patient ID: {patient_id}")
        logger.info(f"💾 Saving report to database...")
        logger.info(f"   Patient ID: {patient_id}")
        
        try:
            session_id = self.controller.session_id if hasattr(self, 'controller') else None
            msg_id = getattr(bubble, '_msg_id', None)
            modality = getattr(self, '_current_modality', 'Unknown')
            sender_info = f"Modality: {modality}, Mode: {getattr(self, 'page_mode', 'Report')}"

            print(f"   Session ID: {session_id}")
            print(f"   Message ID: {msg_id}")
            print(f"   Modality: {modality}")
            logger.info(f"   Session ID: {session_id}")
            logger.info(f"   Message ID: {msg_id}")
            logger.info(f"   Modality: {modality}")
            
            # Call save function
            print(f"→ Calling ai_save_reception_report...")
            logger.info(f"→ Calling ai_save_reception_report...")
            
            report_id = ai_save_reception_report(
                patient_id=patient_id,
                html_content=html_content,
                study_uid=self.study_uid or patient_id,
                session_id=session_id,
                msg_id=msg_id,
                sender_info=sender_info
            )

            if report_id:
                # --- Send to Reception Server (same server) ---
                server_sent = False
                server_status = None
                server_message = "Not sent"
                try:
                    from PacsClient.utils.socket_token_manager import get_socket_token_manager

                    token_manager = get_socket_token_manager()
                    token = token_manager.get_token() if token_manager else None

                    if not token:
                        server_message = "Missing auth token"
                        logger.warning("[RECEPTION_SERVER] ❌ Missing auth token; skipping server send")
                    else:
                        base_url = "http://81.16.117.196:8080"
                        url = f"{base_url}/api/pacs/update-report"

                        reception_id = patient_id
                        try:
                            reception_id = int(patient_id) if str(patient_id).isdigit() else patient_id
                        except Exception:
                            reception_id = patient_id

                        payload = {
                            "receptionId": reception_id,
                            "content": html_content,
                            "findings": html_content,
                            "status": "pending",
                        }

                        logger.info(f"[RECEPTION_SERVER] → POST {url}")
                        logger.info(f"[RECEPTION_SERVER]   receptionId={reception_id}, content_len={len(html_content)}")

                        response = requests.post(
                            url,
                            json=payload,
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {token}",
                            },
                            timeout=30,
                        )

                        server_status = response.status_code
                        response_text = (response.text or "").strip()

                        logger.info(f"[RECEPTION_SERVER] ← status={server_status}")
                        try:
                            logger.info(f"[RECEPTION_SERVER]   headers={dict(response.headers)}")
                        except Exception:
                            pass
                        if response_text:
                            logger.info(f"[RECEPTION_SERVER]   body={response_text[:2000]}")

                        response_json = None
                        try:
                            response_json = response.json()
                            logger.info(f"[RECEPTION_SERVER]   json={response_json}")
                            # Print complete JSON response to console
                            print(f"\n{'='*80}")
                            print("[RECEPTION_SERVER] ✅ Full Server Response JSON:")
                            print(f"{'='*80}")
                            print(json.dumps(response_json, indent=2, ensure_ascii=False))
                            print(f"{'='*80}\n")
                        except Exception:
                            response_json = None

                        if response.ok and (response_json is None or response_json.get("success", True)):
                            server_sent = True
                            server_message = (response_json or {}).get("message", "OK") if response_json else "OK"
                        else:
                            server_message = (response_json or {}).get("message", response_text[:200]) if response_text else "Server error"

                except Exception as e:
                    server_message = f"Exception: {e}"
                    logger.error(f"[RECEPTION_SERVER] ❌ Exception while sending: {e}")

                print("\n" + "="*100)
                print("✅ ✅ ✅ SUCCESS! Report saved to database")
                print("="*100)
                print(f"📌 Report ID: {report_id}")
                print(f"👤 Patient ID: {patient_id}")
                print(f"🔬 Modality: {modality}")
                print(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
                print(f"• Server message: {server_message}")
                print("="*100 + "\n")
                
                logger.info("="*100)
                logger.info("✅ ✅ ✅ SUCCESS! Report saved to database")
                logger.info("="*100)
                logger.info(f"📌 Report ID: {report_id}")
                logger.info(f"👤 Patient ID: {patient_id}")
                logger.info(f"🔬 Modality: {modality}")
                logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
                logger.info("="*100)

                QMessageBox.information(
                    self,
                    "✅ Report Saved Successfully",
                    f"📝 The report has been saved successfully.\n\n"
                    f"📌 Report ID: {report_id}\n"
                    f"👤 Patient ID: {patient_id}\n"
                    f"⏱️ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"📨 Status:\n"
                    f"• Saved to database\n"
                    f"• Patient ID validated: {'✅' if patient_validated else '❌'}\n"
                    f"• Sent to reception: {'✅' if server_sent else '❌'}\n"
                    f"• Server status: {server_status if server_status is not None else 'N/A'}\n"
                )


            else:
                print("\n" + "="*100)
                print("❌ ❌ ❌ FAILED! Database save failed")
                print("="*100 + "\n")
                
                logger.error("="*100)
                logger.error("❌ ❌ ❌ FAILED! Database save failed")
                logger.error("="*100)
                
                QMessageBox.warning(self, "Error", "Failed to save report!")

        except Exception as e:
            print("\n" + "="*100)
            print(f"❌ ❌ ❌ Exception Occurred!")
            print(f"Error: {str(e)}")
            print("="*100 + "\n")
            
            logger.error("="*100)
            logger.error(f"❌ ❌ ❌ Exception Occurred!")
            logger.error(f"Error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            logger.error("="*100)

            QMessageBox.critical(self, "Error", f"Error: {str(e)}")

    def _persian_bubble(self, bubble: "MessageBubble"):
        import logging
        from datetime import datetime
        logger = logging.getLogger(__name__)
        
        print("\n" + "="*100)
        print("🔵 USER CLICKED 'PERSIAN TRANSLATE' BUTTON")
        print("="*100)
        print(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        
        logger.info("\n" + "="*100)
        logger.info("🔵 USER CLICKED 'PERSIAN TRANSLATE' BUTTON")
        logger.info("="*100)
        logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")

        origin = getattr(bubble, "_origin", None)
        is_assistant = (origin == "assistant")

        # server-side session (فعلاً نگه می‌داریم برای سازگاری)
        server_sid = self.controller.session_id
        modality = getattr(self, "_current_modality", None)

        # ─────────────────────────────────────────────
        # 1) Get the EN payload from this bubble (RAW if exists, else from HTML snapshot)
        # ─────────────────────────────────────────────
        english_payload = ""
        src = ""

        # ✅ FIX: For assistant bubbles, always extract from HTML (not raw_report_json)
        #         For report bubbles, prefer raw_report_json if available
        if is_assistant:
            # Assistant => extract from HTML/text
            html = ""
            try:
                html = (bubble.get_html() or "").strip()
            except Exception:
                html = (getattr(bubble, "_raw_text", "") or "").strip()

            if not html:
                msg = "⚠ Cannot translate to Persian: this bubble has no content."
                print(f"❌ {msg}")
                logger.error(f"❌ {msg}")
                self.controller.bubble("AI ChatBot", msg)
                return

            try:
                english_payload = extract_plain_text_from_html(html).strip()
            except Exception:
                english_payload = ""

            if not english_payload:
                english_payload = html  # last resort
            src = "bubble.get_html() [assistant]"
            print(f"✅ Content extracted from: {src}")
            logger.info(f"✅ Content extracted from: {src}")
        else:
            # Report => prefer raw_report_json if available
            raw = getattr(bubble, "raw_report_json", None)
            if isinstance(raw, str) and raw.strip():
                english_payload = raw.strip()
                src = "bubble.raw_report_json [report]"
                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")
            else:
                html = ""
                try:
                    html = (bubble.get_html() or "").strip()
                except Exception:
                    html = (getattr(bubble, "_raw_text", "") or "").strip()

                if not html:
                    msg = "⚠ Cannot translate to Persian: this bubble has no content."
                    print(f"❌ {msg}")
                    logger.error(f"❌ {msg}")
                    self.controller.bubble("AI ChatBot", msg)
                    return

                try:
                    english_payload = extract_plain_text_from_html(html).strip()
                except Exception:
                    english_payload = ""

                if not english_payload:
                    english_payload = html  # last resort
                src = "bubble.get_html() [report]"
                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")

                try:
                    bubble.raw_report_json = english_payload
                except Exception:
                    pass

        if not english_payload.strip():
            msg = "⚠ Cannot translate to Persian: extracted content is empty."
            print(f"❌ {msg}")
            logger.error(f"❌ {msg}")
            self.controller.bubble("AI ChatBot", msg)
            return

        print(f"→ English content extracted: {len(english_payload)} characters")
        logger.info(f"→ English content extracted: {len(english_payload)} characters")

        # 🔍 LOG FULL ENGLISH PAYLOAD BEING SENT
        print("\n" + "="*100)
        print("📤 ENGLISH PAYLOAD BEING SENT TO API:")
        print("="*100)
        print(english_payload)
        print("="*100 + "\n")
        logger.info("\n" + "="*100)
        logger.info("📤 ENGLISH PAYLOAD BEING SENT TO API:")
        logger.info("="*100)
        logger.info(english_payload)
        logger.info("="*100)

        # ─────────────────────────────────────────────
        # 2) Worker (API call)
        # ─────────────────────────────────────────────
        print("→ Translating to Persian...")
        logger.info("→ Translating to Persian...")
        
        def work():
            m = Manage.instance()
            if not m.is_validated():
                self.history.add_bubble("AI ChatBot", "❌ API Key not configured. Please enter it on the login page only.")
                return

            try:
                info = m.ensure_detected()
                center_key = info.irannobat_key
            except Exception as e:
                self.history.add_bubble("AI ChatBot", f"❌ No valid API Key: {e}")
                QTimer.singleShot(100, self._prompt_for_api_key)
                return

            # 🔍 LOG TRANSLATION TYPE
            translation_type = "ASSISTANT (free text)" if is_assistant else "REPORT (structured)"
            print(f"\n🔄 Translation type: {translation_type}")
            logger.info(f"🔄 Translation type: {translation_type}")

            # ✅ Assistant => translate free text
            if is_assistant:
                result = translate_text_to_persian(user_msg=english_payload, CENTER_Key=center_key)
                print("\n" + "="*100)
                print("📥 RAW API RESPONSE (translate_text_to_persian):")
                print("="*100)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                print("="*100 + "\n")
                logger.info("\n" + "="*100)
                logger.info("📥 RAW API RESPONSE (translate_text_to_persian):")
                logger.info("="*100)
                logger.info(json.dumps(result, ensure_ascii=False, indent=2))
                logger.info("="*100)
                return result
            # ✅ Report => translate structured report
            else:
                result = translate_report(user_msg=english_payload, CENTER_Key=center_key)
                print("\n" + "="*100)
                print("📥 RAW API RESPONSE (translate_report):")
                print("="*100)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                print("="*100 + "\n")
                logger.info("\n" + "="*100)
                logger.info("📥 RAW API RESPONSE (translate_report):")
                logger.info("="*100)
                logger.info(json.dumps(result, ensure_ascii=False, indent=2))
                logger.info("="*100)
                return result

        # ─────────────────────────────────────────────
        # 3) Handle success
        # ─────────────────────────────────────────────
        def ok(resp: dict):
            print("\n" + "="*100)
            print("✅ ✅ ✅ SUCCESS! Persian translation received")
            print("="*100 + "\n")
            logger.info("="*100)
            logger.info("✅ ✅ ✅ SUCCESS! Persian translation received")
            logger.info("="*100)

            # (translate_text_to_persian معمولاً session_id ندارد، ولی برای سازگاری نگه می‌داریم)
            new_sid = resp.get("session_id") if isinstance(resp, dict) else None
            if new_sid:
                try:
                    self.controller.switch_session(new_sid)
                except Exception:
                    pass

            if is_assistant:
                # ✅ plain text rendering
                from html import escape
                txt = (resp.get("content") if isinstance(resp, dict) else "") or ""
                txt = txt.strip()
                if not txt:
                    self.controller.bubble("AI ChatBot", "⚠ Empty Persian assistant translation.")
                    logger.warning("⚠ Empty Persian assistant translation.")
                    return

                html = (
                    "<div dir='rtl' style='direction: rtl; text-align: right;'>"
                    "<pre style='white-space: pre-wrap; margin:0;'>"
                    f"{escape(txt)}"
                    "</pre></div>"
                )
                self._bubble_origin_hint = "assistant"
                self.controller.bubble("AI ChatBot (Persian)", html)
                logger.info("✅ Persian assistant translation displayed")
                return

            # ✅ report-style rendering (مثل قبل)
            rep_raw_clean = self._normalize_report_like_payload(resp)
            if not (rep_raw_clean or "").strip():
                print("[REPORT-FA] Empty translation payload. keys=", list(resp.keys()) if isinstance(resp, dict) else type(resp))
                logger.error("[REPORT-FA] Empty translation payload.")
                self.controller.bubble("AI ChatBot", "⚠ Empty Persian report.")
                return

            items = self._parse_jsonish_list(rep_raw_clean)
            inner_html = self._render_kv_report_html(items)

            html = (
                "<div dir='rtl' style='direction: rtl; text-align: right;'>"
                f"{inner_html}"
                "</div>"
            )

            self._bubble_origin_hint = "report"
            self.controller.bubble("AI ChatBot (Persian)", html)
            logger.info("✅ Persian report translation displayed")

        # ─────────────────────────────────────────────
        # 4) Handle error
        # ─────────────────────────────────────────────
        def er(msg: str):
            print(f"\n❌ Translation error: {msg}")
            print("="*100 + "\n")
            logger.error(f"❌ Translation error: {msg}")
            self.controller.bubble("AI ChatBot", f"❌ Persian translation failed: {msg}")

        self._run_async(work, ok, er, typing="Translating to Persian…")

    def _edit_bubble(self, bubble: MessageBubble):
        """
        بدون سیگنال: یک دیالوگ ساده باز می‌کنیم، HTML را ادیت می‌گیریم،
        Bubble را آپدیت می‌کنیم و همان رکورد DB را به‌روزرسانی می‌کنیم.
        فقط برای پیام‌های Report فعال است (origin='report').
        """
        if bubble is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit message")
        v = QVBoxLayout(dlg)
        te = QTextEdit(dlg)
        te.setAcceptRichText(True)
        te.setHtml(bubble.get_html() or "")
        te.setMinimumSize(720, 420)
        v.addWidget(te, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        v.addWidget(btns, 0)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.Accepted:
            new_html = te.toHtml().strip()
            old_html = bubble.get_html().strip()
            if new_html and (new_html != old_html):
                # 1) UI
                bubble.set_html(new_html)
                # 2) DB (با استفاده از دیتابیس اصلی)
                try:
                    if getattr(bubble, "_msg_id", None) is not None:

                        U.ai_update_message(int(bubble._msg_id), new_html)  # ⬅️ جایگزین self.store.update_message
                    # 3) کش درون‌حافظه‌ای را بی‌اعتبار کن تا باز کردن مجدد سشن از DB بخواند
                    if self.current_session_id:
                        self.sessions.pop(self.current_session_id, None)
                except Exception:
                    pass

    def _run_async(self, work: t.Callable, ok: t.Callable[[dict], None],
                   err: t.Callable[[str], None] | None = None,
                   lock_btn: QPushButton | None = None, typing="Thinking"):
        # ⬅️ مهم: هر بابل جدیدی (حتی تایپینگ) می‌آید، خوشامد را بردار
        self._drop_welcome_if_any()

        typing_b = self.history.add_typing("AI ChatBot", typing)
        if lock_btn: lock_btn.setEnabled(False)
        self._busy_count += 1
        try:
            self.btn_new.setEnabled(False)
            self.composer.set_enabled(False)
        except Exception:
            pass

        worker = ApiWorker(work)
        self._workers = getattr(self, "_workers", [])
        self._workers.append(worker)

        def cleanup():
            self.history.remove_widget(typing_b)
            typing_b.stop()
            if lock_btn: lock_btn.setEnabled(True)
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            self._busy_count = max(0, self._busy_count - 1)
            if self._busy_count == 0:
                try:
                    self.btn_new.setEnabled(True)
                    self.composer.set_enabled(True)
                except Exception:
                    pass

        def _ok(res: dict):
            cleanup()
            ok(res)

        def _er(msg: str):
            cleanup()
            safe = _safe_fa_connection_error(msg)
            (err(safe) if err else self.controller.bubble("AI ChatBot", safe))


        worker.done.connect(_ok)
        worker.failed.connect(_er)
        worker.start()

    @Slot(str, str)
    def _append_bubble(self, who: str, text: str) -> None:
        """
        Adds a chat bubble and persists it, with a special rule for the very first
        welcome bubble:
          - Welcome bubbles are shown but NOT persisted (no DB / no cache).
          - As soon as ANY new bubble (user or bot) is added, the welcome bubble
            is removed from the UI.
        """
        # --- 0) اگر قبلاً یک خوش‌آمد نمایش داده‌ایم و الان هر پیام جدیدی می‌آید، حذفش کن
        try:
            if getattr(self, "_welcome_bubble", None) is not None:
                self.history.remove_widget(self._welcome_bubble)
                self._welcome_bubble = None
        except Exception:
            pass

        # --- 1) تشخیص خوش‌آمد ---
        norm = (text or "").strip().lower()
        welcome_texts = {
            "ready. type and press send to chat.",
            "ready. paste report text then send to generate report.",
            "ready. type and press send. use the dropdown to run assist or search.",
            "new chat. choose a mode on send.",
        }
        is_welcome = (who.strip() == "AI ChatBot") and (norm in welcome_texts)

        # اگر خوش‌آمد است: فقط نشان بده، ذخیره/کش نکن و رفرنس نگه‌دار تا بعداً حذف شود
        if is_welcome:
            b = self.history.add_bubble(who, text, on_edit=None)
            self._welcome_bubble = b
            # اگر هنوز سشن محلی نداریم یکی بساز تا سایدبار خالی نباشد
            if not self.current_session_id:
                sid = self._ensure_local_session("New Chat")
                self.current_session_id = sid
            return

        # --- 2) تعیین sid ---
        sid = self.current_session_id or self.controller.session_id
        if not sid:
            is_user = who.strip().lower().startswith("you")
            hint = (text.strip().splitlines()[0][:40] if (is_user and text) else "New Chat")
            sid = self._ensure_local_session(hint)

        # --- 3) منبع پاسخ غیرکاربر (برای فعال شدن Edit در Report) ---
        origin = None
        is_user = who.strip().lower().startswith("you")
        if not is_user:
            origin = getattr(self, "_bubble_origin_hint", None)
            self._bubble_origin_hint = None

        # --- 3.5) report raw (for DB persistence) ---
        raw_report_for_db: str | None = None
        # --- 4) کش درون‌حافظه‌ای ---
        self.sessions.setdefault(sid, [])
        self.sessions[sid].append((who, text))

        # --- 5) نمایش UI ---
        on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
        on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
        # Enable send_to_reception for all non-user messages
        on_send_reception = self._send_to_reception if (not is_user and text) else None

        b = self.history.add_bubble(
            who,
            text,
            on_edit=on_edit,
            on_persian=on_persian,
            on_send_reception=on_send_reception,
        )

        # 🔹 If this is a freshly generated report bubble, attach the raw EN JSON
        if origin == "report" and not is_user:
            raw_en = getattr(self, "_pending_report_raw_en", None)
            raw_report_for_db = raw_en if isinstance(raw_en, str) else None
            if raw_en:
                try:
                    b.raw_report_json = raw_en
                except Exception:
                    pass
                # Add to Correction dropdown
                try:
                    self.composer.register_correction_report(raw_en)
                except Exception:
                    pass

                # consume it so it won't leak to later bubbles
                self._pending_report_raw_en = None

        # 🔹 If this is a freshly generated assistant bubble, attach the raw EN "report JSON"
        if origin == "assistant" and not is_user:
            raw_en = getattr(self, "_pending_assistant_raw_en", None)
            if raw_en:
                try:
                    b.raw_report_json = raw_en
                except Exception:
                    pass
                # consume it so it won't leak to later bubbles
                self._pending_assistant_raw_en = None

        # --- 6) سشن در UI ---
        try:
            if not self.current_session_id:
                self.current_session_id = sid
        except Exception:
            self.current_session_id = sid

        # --- 7) ذخیره در DB ---
        try:
            U.ai_upsert_session(sid, None, self.study_uid)
            msg_id = U.ai_append_message(sid, who, text, origin=origin)
            b._msg_id = msg_id
            # ✅ persist report JSON separately (collections/corrections must not depend on UI bubbles)
            try:
                if origin == "report" and (not is_user) and raw_report_for_db:
                    fn = getattr(U, "ai_insert_report", None) or getattr(U, "ai_upsert_report", None)
                    if callable(fn):
                        fn(sid, int(msg_id), raw_report_for_db, study_uid=getattr(self, "study_uid", None))
            except Exception:
                pass
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # --- 8) عنوان سشن از اولین پیام کاربر ---
        try:
            sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
            if who.strip().lower().startswith("you"):
                item = self._find_sidebar_item_by_sid(sid)
                if item:
                    base = self._get_item_base_title(item)
                    if (not base) or (base == "New Chat"):
                        snippet = self._make_title_from_text(text, max_len=28)
                        if snippet:
                            self._apply_item_title_and_style(item, snippet, sid=sid)
                            try:
                                U.ai_upsert_session(sid, snippet, getattr(self, "study_uid", None))
                            except Exception:
                                pass
        except Exception:
            pass

    def _on_session_changed(self, server_sid: str):
        """
        سرور آیدیِ سشن خودش را اعلام کرده است.
        نگاشت (local sid -> server_sid) را در DB اصلی ذخیره می‌کنیم.
        """
        if not server_sid:
            return
        local_sid = self.current_session_id
        if not local_sid:
            return
        try:
            U.ai_upsert_session(local_sid)  # ensure exists
            U.ai_set_server_sid(local_sid, server_sid)
            U.ai_set_last_session(local_sid)
        except Exception:
            pass

    # تغییر در متد _new_chat برای حفظ مودالیتی
    def _new_chat(self):
        # 1) Reset session
        self.controller.reset_session()
        self.current_session_id = None

        # 2) Clear history
        self.history.clear()

        # 3) Reset composer
        try:
            self.composer.clear_attachment()
            self.composer.set_tab_text("standard", "")
            self.composer.set_tab_text("transcribe", "")
            self.composer.set_tab_text("normal_template", "")
            self.composer.set_tab_text("correction", "")  # ← این خط جدید
            if hasattr(self.composer, "_std_lang_texts"):
                self.composer._std_lang_texts = {"en": "", "fa": ""}
            if hasattr(self.composer, "_std_lang"):
                self.composer._std_lang = "fa"
            self.composer._update_lang_buttons_visibility()
            self.composer.switch_tab("transcribe")
            self.composer.box.clear()
        except Exception:
            pass

        # ✅ Correction: clear dropdown for new chat
        try:
            self.composer.clear_correction_reports() 
        except Exception:
            pass


        # 4) Restore modality in Report mode
        if str(getattr(self, "page_mode", "")).lower() == "report":
            if OneChatPage.last_selected_modality:
                self._current_modality = OneChatPage.last_selected_modality
                self._set_modality_text(OneChatPage.last_selected_modality)
            else:
                # Clear if none was ever selected
                if hasattr(self, "_current_modality"):
                    delattr(self, "_current_modality")

        # 5) Create new local session
        local_sid = self._ensure_local_session("New Chat")
        self.sessions[local_sid] = []

        # 6) Show welcome message
        if str(getattr(self, "page_mode", "")).lower() == "report":
            mod = getattr(self, "_current_modality", "Not selected")
            welcome_msg = f"Ready. Selected modality: {mod}. Paste report text then Send."
        else:
            welcome_msg = "New chat. Choose a mode on Send."
        self.controller.bubble("AI ChatBot", welcome_msg)
        
    # متد جدید برای پاسخ به انتخاب مودالیتی
    def _on_modality_selected(self, modality):
        self._current_modality = modality
        OneChatPage.last_selected_modality = modality  # ذخیره در سطح کلاس
        self._set_modality_text(modality)

    def _new_session(self):
        sid = f"{self.ns}-{uuid.uuid4().hex[:8]}"
        title = "New Chat"
        U.ai_upsert_session(sid, title, study_uid=getattr(self, "study_uid", None))

        it = QListWidgetItem()
        it.setData(Qt.UserRole, sid)
        self._apply_item_title_and_style(it, title, sid=sid)

        self.list.addItem(it)
        self.list.setCurrentItem(it)
        self._open_session(it)


    def _open_session(self, item):
        sid = item.data(Qt.UserRole)

        # 0) set local current sid
        self.current_session_id = sid
        self.controller.switch_session(sid)

        # 1) persist last session (per-study + global)
        try:
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # 2) update sidebar title style (pin prefix)
        try:
            base = self._get_item_base_title(item)
            self._apply_item_title_and_style(item, base, sid=sid)
        except Exception:
            pass

        # 3) if empty => show welcome
        rows = []
        try:
            rows = U.ai_fetch_messages_full(sid)
        except Exception:
            rows = []

        if not rows:
            try:
                self.history.clear()
                self.controller.bubble("AI ChatBot", "New chat. Choose a mode on Send.")
                return
            except Exception:
                return

        def _looks_like_json_payload(s: str) -> bool:
            s = (s or "").lstrip()
            if not s:
                return False
            if s.startswith("{") or s.startswith("["):
                return True
            if "```" in s and ("{" in s or "[" in s):
                return True
            if '"Report Title"' in s or '"عنوان گزارش"' in s:
                return True
            return False

        # 4) Load persisted reports (raw EN JSON) from DB
        #    + Fallback for old sessions: derive from report bubbles HTML and backfill ai_reports
        report_map: dict[int, str] = {}
        report_items: list[tuple[str, str | None]] = []  # (raw, label)

        try:
            fn = getattr(U, "ai_fetch_reports_for_session", None)
            if callable(fn):
                for _, msg_id, label, raw_en, _ in (fn(sid) or []):
                    if isinstance(raw_en, str) and raw_en.strip():
                        report_items.append((raw_en, label if isinstance(label, str) else None))
                    # keep map (but we'll attach to bubble only if JSON-like)
                    try:
                        if msg_id is not None:
                            report_map[int(msg_id)] = raw_en
                    except Exception:
                        pass
        except Exception:
            pass

        # ✅ Fallback: if DB has no reports (old sessions), use ai_messages report bubbles
        if not report_items:
            try:
                insert_fn = getattr(U, "ai_insert_report", None)
            except Exception:
                insert_fn = None

            n = 0
            for msg_id, who, html, origin in (rows or []):
                if origin != "report":
                    continue
                if not isinstance(html, str) or not html.strip():
                    continue

                n += 1
                raw = html.strip()

                # label from plain text (better than "<div ...")
                try:
                    plain = self._html_to_plain_text(raw) if raw else ""
                    first_line = next((ln.strip() for ln in (plain or "").splitlines() if ln.strip()), "")
                    label = (first_line[:80] if first_line else f"Report {n}")
                except Exception:
                    label = f"Report {n}"

                report_items.append((raw, label))

                # backfill into ai_reports so next time dropdown works from DB too
                if callable(insert_fn):
                    try:
                        insert_fn(
                            sid,
                            int(msg_id) if msg_id is not None else None,
                            raw,
                            study_uid=getattr(self, "study_uid", None),
                            label=label,
                            kind="report",
                        )
                    except Exception:
                        pass

        # 4.5) Fill Correction dropdown
        try:
            self.composer.clear_correction_reports()
            for raw, label in report_items:
                self.composer.register_correction_report(raw, label=label)
        except Exception:
            pass

        # 4.6) Render history from DB
        self.history.clear()
        try:
            rows = U.ai_fetch_messages_full(sid)  # [(id, who, html, origin)]
        except Exception:
            rows = []

        for msg_id, who, html, origin in rows:
            if not html:
                continue

            is_user = who.strip().lower().startswith("you")
            on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
            on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
            # Enable send_to_reception for all non-user messages
            on_send_reception = self._send_to_reception if (not is_user and html) else None

            b = self.history.add_bubble(
                who,
                html,
                on_edit=on_edit,
                on_persian=on_persian,
                on_send_reception=on_send_reception,
            )
            try:
                b._msg_id = int(msg_id)
            except Exception:
                b._msg_id = msg_id

            # ✅ attach raw EN JSON only if it looks JSON-like (avoid attaching fallback HTML)
            try:
                if origin == "report" and (not is_user):
                    raw = report_map.get(int(msg_id))
                    if raw and _looks_like_json_payload(raw):
                        b.raw_report_json = raw
            except Exception:
                pass

        # 5) ثبت آخرین سشن (per-study + global)
        try:
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # 6) اگر عنوان سشن هنوز "New Chat" است و اولین پیام کاربر داریم، عنوان را آپدیت کن
        try:
            base = self._get_item_base_title(item)
            if (not base) or (base == "New Chat"):
                for _, who, html, origin in rows:
                    if who and str(who).strip().lower().startswith("you"):
                        plain = self._html_to_plain_text(html) if html else ""
                        snippet = self._make_title_from_text(plain or html or "", max_len=28)
                        if snippet:
                            self._apply_item_title_and_style(item, snippet, sid=sid)
                            try:
                                U.ai_upsert_session(sid, snippet, getattr(self, "study_uid", None))
                            except Exception:
                                pass
                        break
        except Exception:
            pass


    def _first_nonempty_line(s: str) -> str:
        s = (s or "").strip()
        for ln in s.splitlines():
            ln = (ln or "").strip()
            if ln:
                return ln
        return ""

        def _try_load_dict(s: str) -> dict | None:
            import json as _json
            try:
                obj = _json.loads(s)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None

        def _try_load_fenced_json(s: str) -> dict | None:
            s = s or ""
            import re as _re
            m = _re.search(r"```(?:json)?\s*({.*?})\s*```", s, flags=_re.S)
            if not m:
                return None
            return _try_load_dict(m.group(1))

        def _coerce_to_dict(payload: str) -> dict:
            s = (payload or "").strip()

            # 1) اگر fenced بود
            obj = _try_load_fenced_json(s)
            if obj is not None:
                return obj

            # 2) اگر با { شروع می‌شد
            if s.startswith("{") and s.endswith("}"):
                obj = _try_load_dict(s)
                if obj is not None:
                    return obj

            # 3) اگر کل خروجی JSON تمیز بود
            obj = _try_load_dict(s)
            if obj is not None:
                return obj

            # 4) اگر "Final Output" داشت، از همان بخش به بعد تلاش کن (معمولاً JSON نهایی آنجاست)
            low = s.lower()
            idx = low.rfind("final output")
            if idx != -1:
                tail = s[idx:]
                obj = _try_load_dict(tail)
                if obj is not None:
                    return obj

            # 5) اگر آخرین بلاک JSON را می‌خواهی:
            try:
                import re as _re
                matches = list(_re.finditer(r"{", s))
                for m in reversed(matches):
                    cand = s[m.start():]
                    obj = _try_load_dict(cand)
                    if obj is not None:
                        return obj
            except Exception:
                pass

            # 6) fallback: به جای regex greedy، از استخراج‌گر بالانس‌شده‌ی خودت استفاده کن
            # (این کمک می‌کند اگر متن دور JSON زیاد باشد)
            try:
                # توجه: _normalize_report_like_payload «اولین» JSON را ترجیح می‌دهد،
                # اما ما اینجا بعد از امتحانِ "آخرین fenced" از آن استفاده می‌کنیم.
                norm = self._normalize_report_like_payload(s)
                obj = _try_load_dict(norm)
                if obj is not None:
                    return obj
            except Exception:
                pass

            # 7) ناامید شدیم → Raw
            return {"Raw": s}


    # ===== composer actions =====
    def _open_mode_menu(self, text: str):
        menu = QMenu(self)

        has_text = bool(text.strip())
        has_session = bool(self.controller.session_id)

        items = [
            ("Chat", has_text, "For Chat, you must enter some text."),
            ("Report", has_text or has_session, "Enter text or use an existing session."),
            ("Assistant", has_text or has_session, "Provide text/report or use an existing session."),
            ("Search", has_text, "For Search, enter text or keywords."),
        ]


        for name, enabled, tip in items:
            act = QAction(name, menu)
            act.setEnabled(enabled)
            if not enabled:
                act.setToolTip(tip)
            # فقط وقتی فعال است، ارسال را انجام بده
            if enabled:
                act.triggered.connect(lambda _=False, n=name, t=text: self._send_with_mode(t, n))
            menu.addAction(act)

        btn = self.composer.btn_send
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _transcribe_now(self, payload: dict):
        """
        Immediate transcription with full numerical quality-report support.
        Handles:
        • accepted audio
        • rejected audio + detailed criteria
        • silence
        • displays metrics bubble
        • removes voice chip only when success
        """
        # --- helper: normalize path from payload (file_path OR paths[0]) ---
        def _extract_file_path(pl: dict) -> t.Optional[str]:
            try:
                if not pl:
                    return None
                fp = pl.get("file_path")
                if fp:
                    return fp
                paths = pl.get("paths")
                if isinstance(paths, (list, tuple)) and paths:
                    return paths[0]
            except Exception:
                pass
            return None

        # ✅ keep the requested file path so we can remove exactly THIS attachment on success
        requested_path = _extract_file_path(payload)

        # --- ذخیره تب فعلی قبل از شروع ترنسکریپت ---
        current_tab = self.composer.get_active_tab()

        # --- Remove welcome (if exists) ---
        self._drop_welcome_if_any()

        # --- Create typing bubble ---
        typing_b = self.history.add_typing("AI ChatBot", "Transcribing…")
        self._tr_typing = typing_b
        self._tr_cancelled = False

        # --- Disable UI (except cancel) ---
        self.composer.show_cancel(True)
        self.composer.btn_plus.setEnabled(False)
        self.composer.btn_mic.setEnabled(False)
        self.composer.btn_send.setEnabled(False)

        # -----------------------------
        # Cleanup helper (UI restore)
        # -----------------------------
        def cleanup_ui():
            if self._tr_typing:
                try:
                    self._tr_typing.stop()
                except Exception:
                    pass
                self.history.remove_widget(self._tr_typing)
                self._tr_typing = None
            self.composer.btn_plus.setEnabled(True)
            self.composer.btn_mic.setEnabled(True)
            self.composer.btn_send.setEnabled(True)
            self.composer.show_cancel(False)
            try:
                self.composer._apply_mic_mode("record")
            except Exception:
                pass

            # --- بازگشت به تب اصلی در صورتی که در تب Correction بودیم ---
            if current_tab == "correction":
                try:
                    self.composer.switch_tab("correction")
                except Exception:
                    pass

        # -----------------------------
        # Worker: network request
        # -----------------------------
        def work():
            import os, requests
            file_path = _extract_file_path(payload)
            if not file_path or not os.path.exists(file_path):
                raise Exception("Audio file not found for transcription.")
            files = [("audio_files", open(file_path, "rb"))]
            data = {"quality_mode": getattr(self.composer, "_transcribe_quality_mode", "clear")}
            try:
                r = requests.post(
                    URL_GEN_TRANSCRIPT,
                    files=files,
                    data=data,
                    timeout=360,
                )
                r.raise_for_status()
                return r.json()
            finally:
                for _, fh in files:
                    try:
                        fh.close()
                    except Exception:
                        pass

        # -----------------------------
        # Worker OK callback
        # -----------------------------
        def ok(resp: dict):
            # ✅ ALWAYS track transcript minutes (even if user pressed cancel; request still consumed)
            try:
                self._log_irannobat_transcript_usage(resp, [requested_path] if requested_path else None)
            except Exception:
                pass
            if self._tr_cancelled:
                cleanup_ui()
                return

            cleanup_ui()   # stop typing bubble + unlock buttons

            tr = (resp.get("transcript") or "").strip()
            report_list = resp.get("quality_report", [])
            file_report = report_list[0] if report_list else None

            # ===========================================
            # 1. Handle REJECTED audio
            # ===========================================
            if file_report and file_report.get("accepted") is False:
                crit = file_report.get("criteria", {})
                msg = (
                    "⚠ **Voice Rejected**\n"
                    f"• Reason: {crit.get('reason')}\n"
                    f"• Energy: {crit.get('energy'):.8f}\n"
                    f"• ZCR: {crit.get('zcr'):.4f}\n"
                    f"• dBFS: {crit.get('dbfs'):.1f}\n"
                    f"• Duration: {crit.get('speech_ms')} ms\n"
                )
                self.controller.bubble("AI ChatBot", msg)
                return

            # ===========================================
            # 2. Handle ACCEPTED + GOOD AUDIO
            # ===========================================
            if tr:
                # --- تعیین تب هدف بر اساس تب فعلی ---
                target_tab = "correction" if current_tab == "correction" else "transcribe"

                # ✅ FIX: read the REAL buffer of the target tab
                try:
                    existing = self.composer.get_tab_text(target_tab) or ""
                except Exception:
                    std, trans = self.composer.get_tab_texts()
                    existing = trans if target_tab == "transcribe" else ""

                # --- اضافه کردن متن ترنسکریپت به تب هدف ---
                sep = "\n" if (existing and not existing.endswith("\n")) else ""
                new_text = existing + sep + tr
                self.composer.set_tab_text(target_tab, new_text)

                # ✅ NEW: after successful transcription, remove the voice attachment chip
                try:
                    if requested_path:
                        self.composer.remove_voice_attachment(requested_path)
                    else:
                        # fallback: if path is unknown, clear all pending voices
                        self.composer.clear_pending_voices()
                except Exception:
                    try:
                        self.composer.clear_attachment()
                    except Exception:
                        pass

            # ===========================================
            # 3. Handle SILENCE ONLY
            # ===========================================
            else:
                self.controller.bubble(
                    "AI ChatBot",
                    """
                    <div style="direction:ltr;text-align:left;">
                    ⚠️ <b>No clear speech detected.</b> 🎧🗣️<br><br>

                    <b>Common causes:</b> 🔇 muted/wrong mic 🎙️, 🔉 low volume/quality, 🌪️ heavy noise, 🔐 missing mic permission.<br>
                    <b>Try:</b> 🧪 test mic, 🔧 select correct input, 📈 raise input/record louder, 🤫 reduce noise, ✅ allow mic access.<br><br>

                    If needed, use <b>Noisy Voice</b> 🟡 from the lower menu 👇
                    </div>
                    """

                )

        # -----------------------------
        # Worker Error callback
        # -----------------------------
        def err(e):
            cleanup_ui()
            self.controller.bubble("AI ChatBot", f"❌ Error: {e}")

        # -----------------------------
        # Start background worker
        # -----------------------------
        worker = ApiWorker(work, parent=self)
        worker.done.connect(ok)
        worker.failed.connect(err)
        worker.start()

        # -----------------------------
        # Cancel button handler
        # -----------------------------
        def on_cancel():
            self._tr_cancelled = True
            cleanup_ui()
            try:
                self.composer.cancelClicked.disconnect(on_cancel)
            except Exception:
                pass

        self.composer.cancelClicked.connect(on_cancel)

    def _send_with_mode(self, text: str, mode: str, modality: str = None):
        """
        ارسال بر اساس مود انتخاب شده.
        - اگر درخواست fail شود، روی آخرین حباب کاربر دکمه Retry ظاهر می‌شود.
        - موفق که شد، حالت Retry پاک می‌شود.
        - تغییر مهم: در حالت Report هیچ‌گاه جعبهٔ متن پاک نمی‌شود (برای حفظ Transcribe/Standard).
        """

        # ✅ HARD GATE: do not allow ANY AI action without validated API key
        if mode in ("Chat", "Report", "Assistant", "Search", "ChatGPT"):
            manager = APIKeyManager.instance()
            if not manager.is_validated():
                self.controller.bubble("AI ChatBot", "❌ API Key not validated. Access denied.")
                return
        if not text and mode in ("Chat", "Search"):
            return

        sent_text = (text or "").strip()
        self._pending_retry = {"mode": mode, "text": sent_text, "bubble": None}

        print(f"\n[MODE] {mode} | session_id={self.controller.session_id!r}")
        if sent_text:
            print(f"[PAYLOAD] text={sent_text[:120]}{'...' if len(sent_text) > 120 else ''}")

        def _er_for(target_mode: str):
            def er(msg: str):
                # msg اینجا از _run_async قبلاً sanitize شده
                if (msg or "").startswith("❌"):
                    self.controller.bubble("AI ChatBot", msg)
                else:
                    self.controller.bubble("AI ChatBot", f"⚠️ <i>{msg}</i>")

                try:
                    if self._pending_retry and self._pending_retry.get("mode") == target_mode:
                        bub = self._pending_retry.get("bubble")
                        if bub:
                            bub.show_retry(on_click=lambda: self._retry_last_send(),
                                           reason=f"{target_mode.lower()}-failed")
                except Exception:
                    pass

            return er

        def _clear_retry_if(target_mode: str):
            try:
                if self._pending_retry and self._pending_retry.get("mode") == target_mode:
                    bub = self._pending_retry.get("bubble")
                    if bub:
                        bub.clear_retry()
                self._pending_retry = None
            except Exception:
                pass

        # ---------- CHAT ----------
        def ok_chat(resp: dict):
            print("[CHAT] Parsed JSON:", json.dumps(resp, ensure_ascii=False, indent=2))
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW
            _clear_retry_if("Chat")
            self.controller.handle_chat_response(resp)


        if mode == "Chat":
            if not sent_text:
                return
            self.controller.bubble("You", sent_text)
            # پاک‌کردن جعبه در Chat
            self.composer.box.clear()

            def work():
                if self.controller.session_id:
                    payload = {"session_id": self.controller.session_id, "user_message": sent_text}
                else:
                    payload = {"user_message": sent_text}
                print(f"[CHAT] POST {URL_CHAT}\n[CHAT] Payload:", json.dumps(payload, ensure_ascii=False))
                r = requests.post(URL_CHAT, json=payload, timeout=300)
                print(f"[CHAT] Status={r.status_code}\n[CHAT] Response text:\n{r.text}")
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_chat, _er_for("Chat"), typing="Thinking"))
            return

        # ---------- REPORT ----------
        def ok_report(resp: dict):
            print("[REPORT] Parsed JSON:", json.dumps(resp, ensure_ascii=False, indent=2))
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW
            _clear_retry_if("Report")

            sid_new = resp.get("session_id")
            if sid_new:
                self.controller.switch_session(sid_new)

            rep_raw_clean = self._normalize_report_like_payload(resp)

            if not (rep_raw_clean or "").strip():
                self.controller.bubble("AI ChatBot", "⚠️ Empty report output.")
                return

            # ✅ store normalized JSON for bubble attachment + later Persian translation
            self._pending_report_raw_en = rep_raw_clean

            items = self._parse_jsonish_list(rep_raw_clean)
            html = self._render_kv_report_html(items)
            self._bubble_origin_hint = "report"
            self.controller.bubble("AI ChatBot", html)



        if mode == "Report":
            self.controller.bubble("You (Report)", sent_text or "(session-based)")


            # Inside the if mode == "Report": section of _send_with_mode
            def work():
                payload = {}
                if sent_text:
                    payload["text"] = sent_text
                if modality:  # ← critical
                    payload["modality"] = modality
                # Optional normal template (send only when non-empty)
                try:
                    normal_template_plain = (self.composer.get_normal_template_plain_text() or "").strip()
                except Exception:
                    normal_template_plain = ""

                if normal_template_plain:
                    payload["normal_template"] = normal_template_plain
                    # persist plain text (keeps sessions clean; avoids saving HTML skeleton/style)
                    try:
                        self._persist_normal_template(normal_template_plain)
                    except Exception:
                        pass
                    except Exception:
                        pass
                if self.controller.session_id:
                    payload["session_id"] = self.controller.session_id
                try:
                    gpu_id = int(os.environ.get("PACS_AI_GPU", "").strip() or 0)
                    payload["gpu_id"] = gpu_id
                except Exception:
                    pass
                print(f"[REPORT] POST {URL_GEN_REPORT}\n[REPORT] Payload:", json.dumps(payload, ensure_ascii=False))
                r = requests.post(URL_GEN_REPORT, json=payload, timeout=300)
                print(f"[REPORT] Status={r.status_code}\n[REPORT] Response text:\n{r.text}")
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_report, _er_for("Report"),
                                                         typing="Generating report"))
            return

        # ---------- ASSISTANT ----------
        def ok_assistant(resp: dict):
            print("[ASSISTANT] Parsed JSON:", json.dumps(resp, ensure_ascii=False, indent=2))
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW

            sid_new = resp.get("session_id")
            if sid_new:
                self.controller.switch_session(sid_new)

            out = (resp.get("assistant_output") or resp.get("assistant") or resp.get("data") or resp)
            _clear_retry_if("Assistant")

            data = self._parse_assistant_dict(out)
            html = self._render_assistant_html(data)

            # ✅ برای Persian ترجمهٔ "متن آزاد" لازم داریم، نه report-json
            try:
                if isinstance(out, str):
                    plain_out = out.strip()
                else:
                    plain_out = json.dumps(out, ensure_ascii=False, indent=2).strip()
            except Exception:
                plain_out = ("" if out is None else str(out)).strip()

            self._bubble_origin_hint = "assistant"
            self._pending_assistant_raw_en = plain_out or None  # ✅ plain text (assistant output)

            self.controller.bubble("AI ChatBot", html)

        if mode == "Assistant":
            if not (sent_text or self.controller.session_id):
                self.controller.bubble("AI ChatBot", "⚠️ <i>Please provide text or open a session first.</i>")
                return
            self.controller.bubble("You (Assistant)", sent_text or "(session-based)")
            if sent_text:
                self.composer.box.clear()

            def work():
                payload = {}
                if sent_text:
                    payload["text"] = sent_text
                if self.controller.session_id:
                    payload["session_id"] = self.controller.session_id

                print(f"[ASSISTANT] POST {URL_GEN_ASSISTANT}\n[ASSISTANT] Payload:",
                      json.dumps(payload, ensure_ascii=False))
                r = requests.post(URL_GEN_ASSISTANT, json=payload, timeout=300)
                print(f"[ASSISTANT] Status={r.status_code}\n[ASSISTANT] Response text:\n{r.text}")
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_assistant, _er_for("Assistant"),
                                                         typing="Generating assistant output"))
            return

        # ---------- SEARCH ----------
        def ok_search(resp: dict):
            print("[SEARCH] Parsed JSON:", json.dumps(resp, ensure_ascii=False, indent=2))
            self._log_irannobat_usage_from_resp(resp) 
            _clear_retry_if("Search")

            # /search typically returns an envelope:
            #   {"response": "<json string OR dict>", "prompt_tokens":..., "completion_tokens":..., "total_tokens":...}
            try:
                if isinstance(resp, dict):
                    # take tokens (optional)
                    tok = {}
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        if k in resp:
                            tok[k] = resp.get(k)

                    # unwrap payload
                    payload = None
                    for key in ("response", "result", "data", "output"):
                        if key in resp:
                            payload = resp.get(key)
                            break
                    if payload is None:
                        payload = resp

                    # parse inner JSON robustly (handles dict, json-string, fenced json, double-encoded json, etc.)
                    parsed = self._parse_assistant_dict(payload)

                    data = parsed if isinstance(parsed, dict) else {"Raw": parsed}

                    # attach tokens as extras (so they show at bottom)
                    for k, v in tok.items():
                        if v is not None and k not in data:
                            data[k] = v
                else:
                    parsed = self._parse_assistant_dict(resp)
                    data = parsed if isinstance(parsed, dict) else {"Raw": str(resp)}

            except Exception as e:
                print("[SEARCH] Failed to unwrap/parse search response:", e)
                data = resp if isinstance(resp, dict) else {"Raw": str(resp)}

            html = self._render_search_html(data)
            self.controller.bubble("AI ChatBot", html)


        if mode == "Search":
            if not sent_text:
                return
            self.controller.bubble("You (Search)", sent_text)
            self.composer.box.clear()

            def work():
                payload = {"user_query": sent_text}
                print(f"[SEARCH] POST {URL_SEARCH}\n[SEARCH] Payload:", json.dumps(payload, ensure_ascii=False))
                r = requests.post(URL_SEARCH, json=payload, timeout=300)
                print(f"[SEARCH] Status={r.status_code}\n[SEARCH] Response text:\n{r.text}")
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_search, _er_for("Search"), typing="Searching"))
            return

    # pretty printer
    def _pretty_jsonish(self, s: str) -> str:
        try:
            obj = json.loads(s)
            if isinstance(obj, str):
                try:
                    return json.dumps(json.loads(obj), ensure_ascii=False, indent=2)
                except Exception:
                    return obj
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return s

    def _parse_assistant_dict(self, out) -> dict:
        import json, ast, re

        if isinstance(out, dict):
            return out

        if isinstance(out, list):
            return {"Items": out}

        s = "" if out is None else str(out)
        s = s.strip()
        if not s:
            return {"Raw": ""}

        def _try_load_dict(text: str):
            """Try JSON -> double-encoded JSON -> python-literal. Return dict or None."""
            if not text:
                return None
            t = text.strip()

            # strip outer fences if user pasted them
            t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.I)
            t = re.sub(r"\s*```\s*$", "", t)

            # JSON
            try:
                obj = json.loads(t)
                if isinstance(obj, dict):
                    return obj
                if isinstance(obj, str):  # دوبار رشته شده
                    try:
                        obj2 = json.loads(obj)
                        if isinstance(obj2, dict):
                            return obj2
                    except Exception:
                        pass
            except Exception:
                pass

            # Python-literal (single quotes, etc.)
            try:
                obj = ast.literal_eval(t)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

            return None

        # 3) اگر کل خروجی JSON تمیز بود
        obj = _try_load_dict(s)
        if obj is not None:
            return obj

        # 4) اگر "Final Output" داشت، از همان بخش به بعد تلاش کن (معمولاً JSON نهایی آنجاست)
        low = s.lower()
        idx = low.rfind("final output")
        if idx != -1:
            tail = s[idx:]
            obj = _try_load_dict(tail)
            if obj is not None:
                return obj

        # 5) مهم‌ترین: همه code-fenceهای ```json ...``` را پیدا کن و از آخری به اولی parse کن
        fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        for block in reversed(fenced):
            obj = _try_load_dict(block)
            if obj is not None:
                return obj

        # 6) fallback: به جای regex greedy، از استخراج‌گر بالانس‌شده‌ی خودت استفاده کن
        # (این کمک می‌کند اگر متن دور JSON زیاد باشد)
        try:
            # توجه: _normalize_report_like_payload «اولین» JSON را ترجیح می‌دهد،
            # اما ما اینجا بعد از امتحانِ "آخرین fenced" از آن استفاده می‌کنیم.
            norm = self._normalize_report_like_payload(s)
            obj = _try_load_dict(norm)
            if obj is not None:
                return obj
        except Exception:
            pass

        # 7) ناامید شدیم → Raw
        return {"Raw": s}


    def _drop_welcome_if_any(self):
        """Remove the initial welcome bubble if it's on screen."""
        try:
            if getattr(self, "_welcome_bubble", None) is not None:
                self.history.remove_widget(self._welcome_bubble)
                self._welcome_bubble = None
        except Exception:
            pass

    # --- داخل کلاس OneChatPage ---
    def _parse_jsonish_list(self, value) -> list[dict]:

        import json

        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)] or [{"Raw": json.dumps(value, ensure_ascii=False)}]

        if isinstance(value, dict):
            return [value]

        # assume string
        s = self._normalize_report_like_payload(value)

        # try JSON loads (single or double encoded)
        try:
            obj = json.loads(s)
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except Exception:
                    return [{"Raw": s}]
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)] or [{"Raw": s}]
            if isinstance(obj, dict):
                return [obj]
            return [{"Raw": s}]
        except Exception:
            return [{"Raw": s}]


    def _extract_first_json_block(self, s: str) -> str:
        """
        Extract the first balanced JSON object/array from a messy string.
        Handles text around JSON and ignores braces inside quoted strings.
        Returns original string if no JSON start found.
        """
        import re

        if not s:
            return ""

        # If there's a fenced block anywhere, prefer its inside content
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        if m:
            s = (m.group(1) or "").strip()

        # Find first '{' or '['
        i_obj = s.find("{")
        i_arr = s.find("[")
        if i_obj == -1 and i_arr == -1:
            return s

        if i_obj == -1:
            start = i_arr
        elif i_arr == -1:
            start = i_obj
        else:
            start = min(i_obj, i_arr)

        # Scan for matching close using a stack, while respecting JSON strings
        stack = []
        in_str = False
        esc = False

        for i in range(start, len(s)):
            ch = s[i]

            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue

            # not in string
            if ch == '"':
                in_str = True
                continue

            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    continue
                opener = stack.pop()
                # best-effort match (ignore mismatch silently)
                if not stack:
                    return s[start:i + 1]

        # If not fully closed, return from start (best effort)
        return s[start:].strip()


    def _normalize_report_like_payload(self, raw) -> str:
        """Normalize HQ/Report/Translate payloads into a clean JSON-ish string.

        Used for report, HQ, and Persian translation parsing.
        It:
        - unwraps common wrapper keys: content/report/response/message/result/output/data
        - strips fenced code blocks
        - fixes broken HTML entities like '& q u o t ;'
        - removes invisible separators (ZW chars, U+2028/2029)
        - extracts the first balanced JSON object/array when possible
        """
        import json
        import re
        from html import unescape

        if raw is None:
            return ""

        def _unwrap(obj):
            for _ in range(6):
                if isinstance(obj, dict):
                    for k in ("content", "report", "response", "message", "result", "output", "data"):
                        if k in obj and obj[k] is not None:
                            obj = obj[k]
                            break
                    else:
                        return obj
                else:
                    return obj
            return obj

        raw = _unwrap(raw)

        # stringify dict/list
        if isinstance(raw, (dict, list)):
            try:
                s = json.dumps(raw, ensure_ascii=False)
            except Exception:
                s = str(raw)
        else:
            s = str(raw)

        s = (s or "").strip()
        if not s:
            return ""

        # Prefer fenced payload if present
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        if m:
            s = (m.group(1) or "").strip()

        # Remove nasty separators / zero-width chars
        s = s.replace("\ufeff", "").replace("\u2028", "").replace("\u2029", "")
        s = re.sub(r"[\u200b\u200c\u200d\u2060]", "", s)

        # Fix broken HTML entities where characters are separated by whitespace/LS/ZW
        def _fix_entity(m):
            body = m.group(1) or ""
            body = re.sub(r"[\s\u200b\u2028\u2029\u2060]+", "", body)
            return "&" + body + ";"

        s = re.sub(r"&\s*([A-Za-z](?:[A-Za-z\s\u200b\u2028\u2029\u2060]*[A-Za-z])?)\s*;", _fix_entity, s)
        s = re.sub(
            r"&#\s*([0-9][0-9\s\u200b\u2028\u2029\u2060]*)\s*;",
            lambda m: "&#" + re.sub(r"[\s\u200b\u2028\u2029\u2060]+", "", m.group(1)) + ";",
            s,
        )

        # Unescape HTML entities
        try:
            s = unescape(s)
        except Exception:
            pass

        s = s.strip()

        # Extract first JSON block (handles extra text)
        s2 = self._extract_first_json_block(s).strip()
        return s2 or s

    def _render_kv_report_html(self, items: list[dict]) -> str:
        import re, json, ast

        # --------- RTL auto-detect (برای اینکه indent ها RTL درست شوند) ---------
        try:
            flat = []
            for obj in items:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        flat.append("" if k is None else str(k))
                        flat.append("" if v is None else str(v))
            is_rtl = MessageBubble._has_rtl_chars(" ".join(flat))
        except Exception:
            is_rtl = False

        # Indent styles (LTR vs RTL)
        ul_margin_0 = "margin:0 16px 4px 0; padding:0;" if is_rtl else "margin:0 0 4px 16px; padding:0;"
        ul_margin_4 = "margin:4px 16px 4px 0; padding:0;" if is_rtl else "margin:4px 0 4px 16px; padding:0;"
        inner_margin = "margin-right:4px; margin-left:0; line-height:1.5;" if is_rtl else "margin-left:4px; line-height:1.5;"

        # --------- helpers ---------
        def _strip_unwanted_punct(s: str) -> str:
            if not s:
                return ""
            return (
                s.replace("{", "")
                .replace("}", "")
                .replace(";", "")
                .replace("؛", "")
                .replace("•", "")
            )

        def esc(s: str) -> str:
            s = s or ""
            s = _strip_unwanted_punct(s)
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        _bullet_pat = re.compile(r"^\s*(?:[\u2022\u25CF\-\*\u00B7]|\d+[.)])\s*")

        def _normalize_quotes(s: str) -> str:
            # handle smart quotes that may come from model/server
            return (s or "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

        def _maybe_parse_listish(v: object) -> list[str] | None:
            """Parse python-list-like or json-array-like payloads into list[str]."""
            if v is None:
                return None

            if isinstance(v, (list, tuple, set)):
                out = []
                for x in v:
                    xs = "" if x is None else str(x).strip()
                    if xs:
                        out.append(xs)
                return out

            if not isinstance(v, str):
                return None

            s = _normalize_quotes(v).strip()
            if not s:
                return None

            # Strong heuristics to avoid touching normal "(2.3 cm)" style parentheses.
            looks_like_json_array = (s.startswith("[") and s.endswith("]"))
            looks_like_py_collection = (
                (s.startswith("[") and s.endswith("]")) or
                (s.startswith("(") and s.endswith(")") and re.search(r"['\"]\s*,\s*['\"]", s))
            )

            if not (looks_like_json_array or looks_like_py_collection):
                return None

            # Try JSON first for arrays
            if looks_like_json_array:
                try:
                    obj = json.loads(s)
                    if isinstance(obj, list):
                        out = []
                        for x in obj:
                            xs = "" if x is None else str(x).strip()
                            if xs:
                                out.append(xs)
                        return out
                except Exception:
                    pass

            # Fallback: python literal (safe)
            try:
                obj = ast.literal_eval(s)
                if isinstance(obj, (list, tuple, set)):
                    out = []
                    for x in obj:
                        xs = "" if x is None else str(x).strip()
                        if xs:
                            out.append(xs)
                    return out
            except Exception:
                pass

            return None

        def _strip_list_syntax_line(s: str) -> str:
            """Remove only edge list-syntax artifacts like [ '  ,  ] without harming inner parentheses."""
            s = (s or "").strip()
            if not s:
                return ""

            # If the whole line is just wrappers/commas/quotes -> drop it
            if re.fullmatch(r"[\s\[\]\(\)\{\},;'\"]+", s):
                return ""

            # strip leading artifacts
            while True:
                before = s
                s = s.lstrip()

                if s and s[0] in "[{(":
                    s = s[1:]
                    continue
                if s and s[0] in "\"'":
                    s = s[1:]
                    continue
                if s and s[0] in ",;":
                    s = s[1:]
                    continue

                if s == before:
                    break

            # strip trailing artifacts
            while True:
                before = s
                s = s.rstrip()

                if s and s[-1] in "]})":
                    s = s[:-1]
                    continue
                if s and s[-1] in "\"'":
                    s = s[:-1]
                    continue
                if s and s[-1] in ",;":
                    s = s[:-1]
                    continue

                if s == before:
                    break

            return s.strip()

        def _clean_line(s: str) -> str:
            s = _normalize_quotes(s or "")
            s = _strip_list_syntax_line(s)
            s = _bullet_pat.sub("", s).strip()
            s = _strip_unwanted_punct(s)

            # remove invisible separators (just in case)
            s = (
                s.replace("\ufeff", "")
                .replace("\u2028", "")
                .replace("\u2029", "")
            )
            s = re.sub(r"[\u200b\u200c\u200d\u2060]", "", s)

            s = _strip_list_syntax_line(s)
            return s.strip()

        def _split_lines_or_sentences(raw: object) -> list[str]:
            # If it is list / list-like string, normalize to lines first
            seq = _maybe_parse_listish(raw)
            if seq is not None:
                out: list[str] = []
                for x in seq:
                    x = (x or "").replace("\\n", "\n").strip()
                    if not x:
                        continue
                    out.extend([ln.strip() for ln in x.split("\n") if ln.strip()])
                return out

            raw_s = "" if raw is None else str(raw)
            raw_s = _normalize_quotes(raw_s).replace("\\n", "\n").strip()
            if not raw_s:
                return []

            lines = [ln.strip() for ln in raw_s.split("\n") if ln.strip()]
            if len(lines) > 1:
                return lines

            parts = [p.strip() for p in re.split(r"\.(?!\d)", raw_s) if p.strip()]
            if parts:
                fixed = []
                for p in parts:
                    fixed.append(p if p.endswith(".") else (p + "."))
                return fixed

            return [raw_s]

        def to_items(val: object) -> list[str]:
            out: list[str] = []
            for ln in _split_lines_or_sentences(val):
                cl = _clean_line(ln)
                if not cl:
                    continue
                e = esc(cl)
                # drop pure punctuation artifacts
                if e.strip() in (",", "،", "'", '"'):
                    continue
                out.append(e)
            return out

        def to_paragraph_with_breaks(val: object) -> str:
            items2 = to_items(val)
            return "<br>".join(items2) if items2 else ""

        def parse_headed_bullets(val: object):
            groups: list[tuple[str, list[str]]] = []
            lone: list[str] = []
            current_title = None
            bucket: list[str] = []

            for raw_ln in _split_lines_or_sentences(val):
                raw_ln = _strip_unwanted_punct(_normalize_quotes(raw_ln))
                raw_ln = _strip_list_syntax_line(raw_ln)

                # عنوان اگر با ":" تمام شود (و طولش خیلی بلند نباشد)
                is_title = raw_ln.strip().endswith(":") and len(raw_ln.strip()) <= 80

                if is_title:
                    # flush قبلی
                    if current_title is None:
                        lone.extend(esc(_clean_line(x)) for x in bucket)
                    else:
                        groups.append((esc(_clean_line(current_title)), [esc(_clean_line(x)) for x in bucket]))
                    current_title = raw_ln.strip().rstrip(":")
                    bucket = []
                else:
                    cl = _clean_line(raw_ln)
                    if cl:
                        bucket.append(cl)

            # flush آخر
            if bucket:
                if current_title is None:
                    lone.extend(esc(_clean_line(x)) for x in bucket)
                else:
                    groups.append((esc(_clean_line(current_title)), [esc(_clean_line(x)) for x in bucket]))

            return groups, lone

        html_parts: list[str] = []

        for obj in items:
            if not isinstance(obj, dict):
                continue

            for key, val in obj.items():
                if val is None:
                    continue

                # اگر مقدار dict باشد: تبدیل به خطوط "Title: text"
                if isinstance(val, dict):
                    lines = []
                    for subk, subv in val.items():
                        if subv is None:
                            continue
                        subv_str = _strip_unwanted_punct(str(subv).strip())
                        subk_str = _strip_unwanted_punct(str(subk).strip())
                        if not subv_str and not subk_str:
                            continue
                        lines.append(f"{subk_str}: {subv_str}")
                    raw_val = "\n".join(lines).strip()

                # ✅ FIX: اگر لیست واقعی بود، به جای str(list) آن را line-by-line کنیم
                elif isinstance(val, (list, tuple, set)):
                    parts = [str(x).strip() for x in val if str(x).strip()]
                    raw_val = "\n".join(parts).strip()

                else:
                    raw_val = str(val).strip()

                if not raw_val:
                    continue

                key_norm = (key or "").lower().strip()

                # --- Report Title ---
                if key_norm in ("report title", "title"):
                    html_parts.append(
                        "<h2 style='margin:0 0 8px 0; font-size:20px; color:#1f3b77;'>"
                        f"{esc(raw_val)}</h2>"
                    )
                    continue

                # --- Pathological Findings ---
                if key_norm.startswith("pathological"):
                    inner = to_paragraph_with_breaks(raw_val)
                    if not inner:
                        continue
                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#b00020;'>"
                        f"{esc(str(key))}:</div>"
                        f"<div style='{inner_margin}'>{inner}</div>"
                        "</div>"
                    )
                    continue

                # --- Normal Findings ---
                if key_norm.startswith("normal"):
                    groups, lone = parse_headed_bullets(raw_val)
                    section: list[str] = [
                        "<div style='margin-top:8px;'>",
                        "<div style='font-weight:bold; margin-bottom:4px; color:#00695c;'>"
                        f"{esc(str(key))}:</div>",
                    ]

                    for title, bullets in groups:
                        section.append(f"<div style='margin:4px 0 0 0;'><b>{title}</b></div>")
                        if bullets:
                            section.append(f"<ul style='{ul_margin_0}'>")
                            for b in bullets:
                                section.append(f"<li>{b}</li>")
                            section.append("</ul>")

                    if lone:
                        section.append(f"<ul style='{ul_margin_4}'>")
                        for b in lone:
                            section.append(f"<li>{b}</li>")
                        section.append("</ul>")

                    section.append("</div>")
                    html_parts.append("".join(section))
                    continue

                # --- Recommendations (optional) ---
                if (
                    key_norm.startswith("recommend")
                    or key_norm.startswith("follow-up")
                    or key_norm.startswith("follow up")
                    or ("recommend" in key_norm)
                ):
                    low = (raw_val or "").strip().lower()
                    if low in ("none", "n/a", "na", "null", "-"):
                        continue
                    items_clean = to_items(raw_val)
                    if not items_clean:
                        continue

                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#6d4c41;'>"
                        f"{esc(str(key))}:</div>"
                    )
                    if len(items_clean) == 1:
                        html_parts.append(f"<div style='{inner_margin}'>{items_clean[0]}</div></div>")
                    else:
                        html_parts.append(f"<ul style='{ul_margin_0}'>")
                        for line in items_clean:
                            html_parts.append(f"<li>{line}</li>")
                        html_parts.append("</ul></div>")
                    continue

                # --- Impression (optional) ---
                if key_norm.startswith("impression") or key_norm == "impressions":
                    low = (raw_val or "").strip().lower()
                    if low in ("none", "n/a", "na", "null", "-"):
                        continue
                    inner = to_paragraph_with_breaks(raw_val)
                    if not inner:
                        continue

                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#283593;'>"
                        f"{esc(str(key))}:</div>"
                        f"<div style='{inner_margin}'>{inner}</div>"
                        "</div>"
                    )
                    continue

                # --- سایر فیلدها ---
                items_clean = to_items(raw_val)
                if not items_clean:
                    continue

                if len(items_clean) == 1:
                    html_parts.append(
                        "<p style='margin:6px 0 4px 0;'>"
                        "<b style='color:#37474f;'>"
                        f"{esc(str(key))}:</b> {items_clean[0]}"
                        "</p>"
                    )
                else:
                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#37474f;'>"
                        f"{esc(str(key))}:</div>"
                        f"<ul style='{ul_margin_0}'>"
                    )
                    for line in items_clean:
                        html_parts.append(f"<li>{line}</li>")
                    html_parts.append("</ul></div>")

        if not html_parts:
            return "<p><i>No structured report content.</i></p>"

        # root: اگر RTL است، direction/align را همینجا هم enforce کن
        root_style = "line-height:1.5; font-size:15px;"
        if is_rtl:
            root_style += " direction: rtl; text-align: right; unicode-bidi: plaintext;"

        return "<div style='" + root_style + "'>" + "\n".join(html_parts) + "</div>"


    def _render_assistant_html(self, data: dict) -> str:
        import typing as t, re

        def esc(s: t.Any) -> str:
            return ("" if s is None else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def is_long_paragraph(s: str) -> bool:
            return isinstance(s, str) and (len(s) > 160 or "\n" in s)

        def render_list(items: list) -> str:
            if not items:
                return ""
            lis = []
            for x in items:
                if isinstance(x, (list, dict)):
                    lis.append(f"<li>{render_value(x)}</li>")
                else:
                    lis.append(f"<li>{esc(x)}</li>")
            return "<ul class='bullets'>" + "".join(lis) + "</ul>"

        def render_kv(d: dict) -> str:
            if not d:
                return ""
            out = []
            for k, v in d.items():
                out.append(f"<div class='minihead'>{esc(k)}</div>")
                out.append(render_value(v))
            return "".join(out)

        def render_imaging(v: t.Union[dict, list, str]) -> str:
            if isinstance(v, dict):
                order = [
                    "General Features",
                    "Ultrasound Findings",
                    "Radiologic Findings",
                    "CT Scan Findings",
                    "MRI Findings",
                ]
                html = []
                for key in order:
                    if key in v:
                        html.append(f"<div class='minihead'>{esc(key)}</div>")
                        html.append(render_value(v[key]))
                for k, vv in v.items():
                    if k not in order:
                        html.append(f"<div class='minihead'>{esc(k)}</div>")
                        html.append(render_value(vv))
                return "".join(html) if html else render_value(v)
            return render_value(v)

        def render_value(v) -> str:
            if v is None:
                return ""
            if isinstance(v, dict):
                return render_kv(v)
            if isinstance(v, list):
                return render_list(v)
            if isinstance(v, str):
                if is_long_paragraph(v):
                    parts = [p.strip() for p in re.split(r"\n{2,}", v.strip()) if p.strip()]
                    if len(parts) > 1:
                        return "".join(f"<p class='para'>{esc(p)}</p>" for p in parts)
                    return f"<p class='para'>{esc(v)}</p>"
                return f"<p class='para'>{esc(v)}</p>"
            return f"<p class='para'>{esc(v)}</p>"

        title = esc(data.get("Mode") or data.get("Title") or "Assistant Analysis")
        context = esc(data.get("Clinical and Radiologic Context") or data.get("Context") or "")
        prim = data.get("Primary Diagnoses") or data.get("Primary Diagnosis")
        step1 = data.get("Step_1_From_Input") or data.get("Step1") or {}
        step2 = data.get("Step_2_Knowledge_Retrieved") or data.get("Step2") or {}
        step3 = data.get("Step_3_Summary") or data.get("Step3") or {}

        step1_html = ""
        if isinstance(step1, dict):
            if step1.get("Extracted_Main_Context"):
                step1_html += f"<div class='minihead'>Extracted Main Context</div>{render_value(step1['Extracted_Main_Context'])}"
            if step1.get("Reasoning"):
                step1_html += f"<div class='minihead'>Reasoning</div>{render_value(step1['Reasoning'])}"
            for k, v in step1.items():
                if k in ("Extracted_Main_Context", "Reasoning"):
                    continue
                step1_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step1_html = render_value(step1)

        step2_html = ""
        if isinstance(step2, dict):
            ordered = [
                "Diagnosis", "Terminology", "Clinical Findings",
                "Imaging Findings", "Differential Diagnosis",
                "Pathology", "Clinical Issues"
            ]
            for k in ordered:
                if k in step2:
                    if k == "Imaging Findings":
                        step2_html += f"<div class='minihead'>{k}</div>{render_imaging(step2[k])}"
                    else:
                        step2_html += f"<div class='minihead'>{k}</div>{render_value(step2[k])}"
            for k, v in step2.items():
                if k not in ordered:
                    step2_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step2_html = render_value(step2)

        step3_html = ""
        if isinstance(step3, dict):
            if step3.get("Summary"):
                step3_html += f"<div class='minihead'>Summary</div>{render_value(step3['Summary'])}"
            if step3.get("Follow_up_Recommendations"):
                step3_html += f"<div class='minihead'>Follow-up Recommendations</div>{render_value(step3['Follow_up_Recommendations'])}"
            for k, v in step3.items():
                if k in ("Summary", "Follow_up_Recommendations"):
                    continue
                step3_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step3_html = render_value(step3)

        used_top = {
            "Mode", "Title", "Clinical and Radiologic Context", "Context",
            "Primary Diagnoses", "Primary Diagnosis",
            "Step_1_From_Input", "Step1", "Step_2_Knowledge_Retrieved", "Step2",
            "Step_3_Summary", "Step3"
        }
        extras_html = []
        for k, v in data.items():
            if k in used_top:
                continue
            extras_html.append(f"<div class='subttl'>{esc(k)}</div>{render_value(v)}")

        html = [
            "<style>",
            ".assistant-card{max-width:900px;width:100%;margin:12px 0;background:#1e1f22;border:1px solid #2e2e2e;border-radius:10px;padding:16px 18px;font-size:15px;}",
            ".title{font-weight:800;color:#eaeaea;margin:0 0 8px;letter-spacing:.3px;font-size:16px;}",
            ".subttl{font-weight:800;margin:12px 0 8px;color:#e0e0e0;font-size:15px;}",
            ".minihead{font-weight:700;margin:8px 0 4px;color:#d0d0d0;font-size:14px;}",
            ".stephdr{font-weight:900;font-size:17px;letter-spacing:.2px;margin:14px 0 6px;}",
            ".para{color:#ddd;line-height:1.6;margin:0 0 8px;font-size:15px;}",
            ".bullets{list-style:disc;list-style-position:inside;margin:0 0 6px 2px;padding:0;color:#dddddd;line-height:1.6;font-size:15px;}",
            ".bullets li{margin:2px 0}",
            ".hr{border-top:1px solid rgba(255,255,255,.08);margin:12px 0}",
            ".step1{color:#e6e6e6;} .step1 .para,.step1 .bullets{color:#dddddd;}"
            ".step1-h{color:#e0e0e0;}"

            ".step2{color:#86b7ff;} .step2 .para,.step2 .bullets{color:#86b7ff;}"
            ".step2-h{color:#93c1ff;}"

            ".step3{color:#ff9b9b;} .step3 .para,.step3 .bullets{color:#ff9b9b;}"
            ".step3-h{color:#ffa6a6;}"
            "</style>",
            "<div class='assistant-card'>",
            f"<div class='title'>{title}</div>",
        ]
        if context:
            html += ["<div class='subttl'>Clinical/Radiologic Context</div>", f"<p class='para'>{context}</p>",
                     "<div class='hr'></div>"]
        if prim:
            html += ["<div class='subttl'>Primary Diagnoses</div>", render_value(prim)]

        if step1_html:
            html += [f"<div class='stephdr step1-h'>Step 1 — From Input</div>",
                     f"<div class='step step1'>{step1_html}</div>"]
        if step2_html:
            html += [f"<div class='stephdr step2-h'>Step 2 — Knowledge Retrieved</div>",
                     f"<div class='step step2'>{step2_html}</div>"]
        if step3_html:
            html += [f"<div class='stephdr step3-h'>Step 3 — Summary</div>",
                     f"<div class='step step3'>{step3_html}</div>"]

        if extras_html:
            html += ["<div class='hr'></div>"] + extras_html
        html.append("</div>")
        return "".join(html)

    def _render_search_html(self, data: dict) -> str:
        """
        Render nice HTML card for /search JSON:
          - Original/Rewritten question
          - Relevant sections
          - Relevant imaging modalities (CT/MRI/US/Radiographic ...)
          - Short answer + reasoning
          - Any extra keys not covered -> at bottom
        """
        import typing as t

        def esc(s: t.Any) -> str:
            s = "" if s is None else str(s)
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def bullets(items: t.Iterable) -> str:
            if not items:
                return ""
            lis = []
            for it in items:
                if isinstance(it, (list, dict)):
                    lis.append(f"<li>{kv(it)}</li>")
                else:
                    lis.append(f"<li>{esc(it)}</li>")
            return "<ul class='bullets'>" + "".join(lis) + "</ul>"

        def kv(d: dict) -> str:
            if not isinstance(d, dict) or not d:
                return ""
            out = []
            for k, v in d.items():
                out.append(f"<div class='minihead'>{esc(k)}</div>")
                out.append(render(v))
            return "".join(out)

        def render(v) -> str:
            if v is None:
                return ""
            if isinstance(v, dict):
                return kv(v)
            if isinstance(v, list):
                return bullets(v)
            return f"<p class='para'>{esc(v)}</p>"

        # known top-level keys
        orig_q = data.get("Original_Question")
        rew_q = data.get("Rewritten_Question")
        rel_sec = data.get("Relevant_Sections")
        rel_modal = data.get("Relevant_Imaging_Modalities") or {}
        short_ans = data.get("Short_Answer")
        reasoning = data.get("Reasoning_and_Summary")

        used = {
            "Original_Question", "Rewritten_Question", "Relevant_Sections",
            "Relevant_Imaging_Modalities", "Short_Answer", "Reasoning_and_Summary"
        }

        # modalities pretty order (then any others)
        mod_order = ["General", "CT Scan", "MRI", "Ultrasound", "Radiographic"]
        mod_html = []
        if isinstance(rel_modal, dict):
            # ordered known
            for m in mod_order:
                if m in rel_modal:
                    mod_html.append(f"<div class='subttl'>{esc(m)}</div>")
                    mod_html.append(render(rel_modal[m]))
            # remaining
            for k, v in rel_modal.items():
                if k not in mod_order:
                    mod_html.append(f"<div class='subttl'>{esc(k)}</div>")
                    mod_html.append(render(v))

        # extras
        extras = []
        for k, v in data.items():
            if k in used:
                continue
            extras.append(f"<div class='subttl'>{esc(k)}</div>{render(v)}")

        html = [
            "<style>",
            ".search-card{max-width:900px;width:100%;margin:12px 0;background:#1e1f22;",
            "border:1px solid #2e2e2e;border-radius:10px;padding:16px 18px}",
            ".title{font-weight:800;color:#e6e6e6;margin:0 0 6px;letter-spacing:.3px}",
            ".subttl{font-weight:700;margin:10px 0 6px;color:#d9d9d9}",
            ".minihead{font-weight:600;margin:8px 0 4px;color:#cfcfcf}",
            ".bullets{list-style:disc;list-style-position:inside;margin:0 0 4px 2px;padding:0;color:#dddddd;line-height:1.55}",
            ".bullets li{margin:1px 0}",
            ".para{color:#ddd;line-height:1.55;margin:0 0 8px}",
            ".hr{border-top:1px solid rgba(255,255,255,.07);margin:12px 0}",
            "</style>",
            "<div class='search-card'>",
            "<div class='title'>Search Results</div>",
        ]
        if orig_q:
            html += ["<div class='subttl'>Original Question</div>", f"<p class='para'>{esc(orig_q)}</p>"]
        if rew_q:
            html += ["<div class='subttl'>Rewritten Question</div>", f"<p class='para'>{esc(rew_q)}</p>"]
        if rel_sec:
            html += ["<div class='subttl'>Relevant Sections</div>", render(rel_sec)]
        if mod_html:
            html += ["<div class='subttl'>Relevant Imaging Modalities</div>"] + mod_html
        if short_ans:
            html += ["<div class='subttl'>Short Answer</div>", f"<p class='para'>{esc(short_ans)}</p>"]
        if reasoning:
            html += ["<div class='subttl'>Reasoning & Summary</div>", f"<p class='para'>{esc(reasoning)}</p>"]
        if extras:
            html += ["<div class='hr'></div>"] + extras

        html.append("</div>")
        return "".join(html)

class ChatGPTPage(OneChatPage):
    """ChatGPT mode — now fully uses global API from input page and never prompts for API."""
    GPT_MODELS = [
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-5.1-mini",
        "gpt-5.1",
        "gpt-4o"
    ]

    def __init__(self, study_uid: str = None):
        super().__init__(study_uid=study_uid, page_mode="ChatGPT")
        self.setWindowTitle("AI Chat – ChatGPT")
        self._current_model = "gpt-4.1-mini"
        self._chatgpt_mode = "chat"
        print(
            f"[ChatGPT] init study_uid={study_uid!r} model={self._current_model} mode={self._chatgpt_mode}"
        )

        # --- Load global API ---
        manager = APIKeyManager.instance()
        if not manager.is_validated():
            self.global_api_key = None
            self.global_center = None
        else:
            self.global_api_key = manager.get_current_key()
            self.global_center = manager.get_current_center()
        print(
            f"[ChatGPT] init api_valid={manager.is_validated()} center={self.global_center!r}"
        )

        # --- Layout Setup ---
        right_panel = self.layout().itemAt(1).widget()
        right_layout = right_panel.layout()

        self.model_selector_container = QWidget(self)
        model_layout = QHBoxLayout(self.model_selector_container)
        model_layout.setContentsMargins(12, 6, 12, 6)
        model_layout.setSpacing(8)

        # MODE TOGGLE BUTTON
        button_style = f"""
            QToolButton {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                padding:4px 10px;
                min-height:32px;
                font-size:13px;
                font-weight:500;
            }}
            QToolButton:hover {{
                background:#4a4a4a;
                border-color:{CLR_ACCENT};
            }}
        """

        self.btn_mode_toggle = QToolButton(self.model_selector_container)
        self.btn_mode_toggle.setText("💬 Chat")
        self.btn_mode_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mode_toggle.setPopupMode(QToolButton.InstantPopup)
        self.btn_mode_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_mode_toggle.setArrowType(Qt.DownArrow)
        self.btn_mode_toggle.setStyleSheet(button_style)
        menu_mode = QMenu(self)

        from PySide6.QtGui import QPixmap, QPainter, QFont

        # --- ایموجی -> آیکون (برای align شدن) ---
        def _emoji_icon(emoji: str, size: int = 18) -> QIcon:
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(int(size * 0.90))
            p.setFont(f)
            p.drawText(pm.rect(), Qt.AlignCenter, emoji)
            p.end()
            return QIcon(pm)

        menu_mode.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }

            QMenu::icon {
                width: 18px;
                height: 18px;
                margin-left: 8px;
                margin-right: 6px;
            }

            QMenu::item {
                padding: 7px 12px 7px 36px;   
                color: #ddd;
                background-color: transparent;
                border-radius: 6px;
                margin: 2px;
            }
            QMenu::item:selected { background-color: #3a3a3a; color: #fff; }
            QMenu::item:hover    { background-color: #4a4a4a; }
        """)

        items = [
            ("💬", "Chat", "chat"),
            ("📄", "Report", "report"),
            ("🖼️", "Image Artifact Analyzer", "image"),
            (None, "Breast Expert Assistant", "breast"),
        ]

        for emoji, text, mode in items:
            if mode == "breast":
                # ✅ دقیقا استفاده از همان تابع _set_icon
                tmp = QPushButton()
                _set_icon(tmp, "breast.jpeg", size=18, tooltip=text)
                act = QAction(tmp.icon(), text, menu_mode)
            else:
                act = QAction(_emoji_icon(emoji, 18), text, menu_mode)

            act.setIconVisibleInMenu(True)
            act.triggered.connect(lambda _, m=mode: self._set_chatgpt_mode(m))
            menu_mode.addAction(act)

        self.btn_mode_toggle.setMenu(menu_mode)

        # MODEL SELECTOR
        self.btn_model = QToolButton(self.model_selector_container)
        self.btn_model.setText(self._current_model)
        self.btn_model.setCursor(Qt.PointingHandCursor)
        self.btn_model.setPopupMode(QToolButton.InstantPopup)
        self.btn_model.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_model.setArrowType(Qt.DownArrow)
        self.btn_model.setStyleSheet(button_style)
        self.btn_model.clicked.connect(self._show_model_menu)

        model_layout.addWidget(self.btn_mode_toggle)
        model_layout.addWidget(self.btn_model)
        model_layout.addStretch(1)

        right_layout.insertWidget(right_layout.count() - 1, self.model_selector_container)

        # TOKEN LABEL
        self.lbl_tokens = QLabel("Tokens: –")
        self.lbl_tokens.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                padding: 4px 8px;
            }
        """)
        self.lbl_tokens.setAlignment(Qt.AlignRight)
        right_layout.insertWidget(right_layout.count() - 1, self.lbl_tokens)

        self._token_usage = load_token_usage()
        self._update_token_display()

        # Ensure UI matches current ChatGPT sub-mode (default: chat)
        try:
            self._set_chatgpt_mode(self._chatgpt_mode)
        except Exception:
            pass

    def _norm_center_name(self, center: str | None) -> str:
        if not center:
            return "Unknown"
        c = center.strip()
        if c.upper() == "RAZI":
            return "Razi"
        if c.upper() == "MEHR":
            return "Mehr"
        return c

    def _load_global_api(self) -> tuple[str | None, str | None]:
        m = Manage.instance()
        if not m.is_validated():
            return None, None
        try:
            info = m.ensure_detected()
            return info.center_display, info.irannobat_key
        except Exception:
            return None, None

    def _set_chatgpt_mode(self, mode):
        self._chatgpt_mode = mode
        print(f"[ChatGPT] mode set -> {mode}")

        labels = {
            "chat":   "Chat",
            "report": "Report",
            "image":  "Image Artifact Analyzer",
            "breast": "Breast Expert Assistant",
        }

        label_text = labels.get(mode, "Chat")
        self.btn_mode_toggle.setText(label_text)

        # سپس آیکون (فقط برای breast)
        try:
            if mode == "breast":
                # روش 1: استفاده از مسیر کامل
                icon_path = os.path.join(ICON_PATH, "feather", "breast.jpeg")
                
                # بررسی وجود فایل
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        self.btn_mode_toggle.setIcon(icon)
                        self.btn_mode_toggle.setIconSize(QSize(18, 18))
                        self.btn_mode_toggle.setText(label_text)
                        self.btn_mode_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                    else:
                        print(f"[ICON] Icon is null: {icon_path}")
                        self.btn_mode_toggle.setIcon(QIcon())  # پاک کردن آیکون
                else:
                    print(f"[ICON] File not found: {icon_path}")
                    self.btn_mode_toggle.setIcon(QIcon())  # پاک کردن آیکون
            else:
                # برای مودهای دیگر، آیکون را پاک کن
                self.btn_mode_toggle.setIcon(QIcon())
                self.btn_mode_toggle.setIconSize(QSize(0, 0))
        except Exception as e:
            print(f"[ICON] Error loading icon: {e}")
            import traceback
            traceback.print_exc()
            self.btn_mode_toggle.setIcon(QIcon())

        # باقی کدها (بدون تغییر)
        try:
            if hasattr(self.composer, "attach_frame"):
                self.composer.attach_frame.setVisible(mode != "breast")
            if hasattr(self.composer, "_image_attachments") and mode == "breast":
                self.composer._image_attachments.clear()
        except Exception:
            pass

        try:
            show_modality = (mode == "report")
            if hasattr(self.composer, "btn_modality"):
                self.composer.btn_modality.setVisible(show_modality)
            if hasattr(self.composer, "btn_all_modality_hq"):
                self.composer.btn_all_modality_hq.setVisible(show_modality)
        except Exception:
            pass

    def _init_api_key_input(self):
        self._global_center, self._global_key = self._load_global_api()
        if self._global_key:
            self._show_welcome_message()
        else:
            try:
                self.history.add_bubble("AI ChatBot", "❌ API key is not set. Please enter it on the login page only.")
            except Exception:
                pass


    def _prompt_for_api_key(self):
        try:
            self.history.add_bubble("AI ChatBot", "❌ The API key can only be set on the login page.")
        except Exception:
            pass


    def _detect_and_set_center(self, api_key=None):
        self._global_center, self._global_key = self._load_global_api()
        if self._global_key:
            self._show_welcome_message()


    def _show_welcome_message(self):
        center = getattr(self, "_global_center", None) or "Unknown"
        api_key = getattr(self, "_global_key", None) or ""
        api_key = (api_key or "").strip()

        total_tokens = 0
        total_transcript_minutes = 0.0
        usage_html = "<i>No usage data.</i>"

        try:
            from PacsClient.utils.database import (
                get_api_usage_summary_html,
                load_api_token_usage_for_key,
                load_api_transcript_usage_for_key,
            )
            if api_key:
                models = load_api_token_usage_for_key(api_key)
                total_tokens = sum(int(v or 0) for v in models.values())

                tr_models = load_api_transcript_usage_for_key(api_key)  # ✅ minutes
                total_transcript_minutes = sum(float(v or 0.0) for v in tr_models.values())

                usage_html = get_api_usage_summary_html(api_key)
        except Exception:
            pass

        current_model = getattr(self, "_current_model_name", None) or getattr(self, "current_model", None) or "<unknown>"

        msg = (
            f"🎉 <b>Welcome to {center} Center ChatGPT</b><br>"
            f"<b>Current model:</b> {current_model}<br>"
            f"<b>Total tokens (this API):</b> {total_tokens:,}<br><br>"
        )
        if total_transcript_minutes > 0:
            msg += f"<b>Total transcript (this API):</b> {total_transcript_minutes:.1f} min<br><br>"
        msg += f"{usage_html}"

        self.history.clear()
        self.history.add_bubble("AI ChatBot", msg)

    def _update_token_display(self):
        # ✅ robust center name resolver (no get_detected_center_display)
        center = getattr(self, "_global_center", None)

        if not center:
            try:
                info = Manage.instance().ensure_detected()
                center = getattr(info, "center_display", None) or getattr(info, "center", None)
            except Exception:
                center = None

        center = self._norm_center_name(center)
        model = self._current_model
        tokens = self._token_usage.get(center, {}).get(model, 0)
        self.lbl_tokens.setText(f"📊 {model}: {tokens:,} tokens")


    def _show_model_menu(self):
        print("[ChatGPT] open model menu")
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 16px;
                color: #ddd;
                background-color: transparent;
                border-radius: 4px;
                margin: 2px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
                color: #fff;
            }
            QMenu::item:hover {
                background-color: #4a4a4a;
            }
            QMenu::item:checked {
                background-color: #505050;
                color: #ffd48a;
                font-weight: 600;
            }
        """)

        for model in self.GPT_MODELS:
            act = QAction(model, menu)
            act.setCheckable(True)
            if model == self._current_model:
                act.setChecked(True)
            act.triggered.connect(lambda checked, m=model: self._select_model(m))
            menu.addAction(act)

        menu.exec(self.btn_model.mapToGlobal(self.btn_model.rect().bottomLeft()))

    def _select_model(self, model):
        self._current_model = model
        self.btn_model.setText(model)
        self._update_token_display()
        print(f"[ChatGPT] model set -> {model}")

    def _show_modality_menu(self):
        print("[ChatGPT] open modality menu")
        return super()._show_modality_menu()


    def _send_correction(self, text: str):
        """Correction tab in ChatGPT mode: apply note to selected report."""
        print("[ChatGPT] correction send")
        note = (text or "").strip()
        try:
            report_text = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            report_text = ""

        if not report_text:
            print("[ChatGPT] correction blocked: report not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a report from the Correction dropdown.</i>")
            return
        if not note:
            print("[ChatGPT] correction blocked: empty note")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please write your correction notes in the box below.</i>")
            return

        self.controller.bubble("You (✅ Correction)", note)

        center_key = os.environ.get("CENTER_Key", "") or ""
        model = getattr(self, "_current_model", None) or "gpt-4.1-mini"

        def work():
            return correction(
                user_report=report_text,
                correction_note=note,
                CENTER_Key=center_key,
                model=model,
            )

        def ok(res):
            try:
                rep_raw_clean = self._normalize_report_like_payload(res)
                if not rep_raw_clean.strip():
                    self.controller.bubble("AI ChatBot", "⚠️ Empty output.")
                    return

                self._pending_report_raw_en = rep_raw_clean
                items = self._parse_jsonish_list(rep_raw_clean)
                html = self._render_kv_report_html(items)
                self._bubble_origin_hint = "report"
                self.controller.bubble("AI ChatBot", html)
            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Render error: {e}")

        def er(msg: str):
            self.controller.bubble("AI ChatBot", msg)

        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self.composer, "btn_send", None),
                typing="Correcting…"
            )
        )



    def _on_send_clicked(self, text: str):
        """Handle text and voice input (override parent)"""
        try:
            voices = self.composer.get_pending_voices()
        except Exception:
            voices = []
        print(
            f"[ChatGPT] send_clicked voices={len(voices)} text_len={len((text or '').strip())} mode={self._chatgpt_mode}"
        )

        if voices:
            current_tab = self.composer.get_active_tab()
            typing_b = self.history.add_typing("AI ChatBot", "Transcribing…")
            self.composer.set_enabled(False)

            def cleanup_ui():
                try:
                    self.history.remove_widget(typing_b)
                    typing_b.stop()
                except Exception:
                    pass
                try:
                    self.composer.set_enabled(True)
                except Exception:
                    pass


            def cont_with_transcript(tr_text: str, server_sid: str | None):
                cleanup_ui()
                merged = (text or "").strip()
                tr_text = (tr_text or "").strip()

                if merged and tr_text:
                    merged = f"{merged}\n{tr_text}"
                elif tr_text:
                    merged = tr_text
                elif not tr_text:
                    self.controller.bubble(
                        "AI ChatBot",
                        """
                        <div style="direction:ltr;text-align:left;">
                        ⚠️ <b>No clear speech detected.</b> 🎧🗣️<br><br>

                        <b>Common causes:</b> 🔇 muted/wrong mic 🎙️, 🔉 low volume/quality, 🌪️ heavy noise, 🔐 missing mic permission.<br>
                        <b>Try:</b> 🧪 test mic, 🔧 select correct input, 📈 raise input/record louder, 🤫 reduce noise, ✅ allow mic access.<br><br>

                        If needed, use <b>Noisy Voice</b> 🟡 from the lower menu 👇
                        </div>
                        """

                    )

                    return

                self._on_send_chatgpt(merged)

            self._upload_voices_then(file_paths=voices, cont=cont_with_transcript)
        else:
            self._on_send_chatgpt(text)

    def _on_send_chatgpt(self, text: str):
        """Send message and track token usage (Chat / Report / Image / Breast modes)"""

        print(
            f"[ChatGPT] send mode={getattr(self, '_chatgpt_mode', None)} model={getattr(self, '_current_model', None)} text_len={len((text or '').strip())}"
        )

        m = Manage.instance()
        if not m.is_validated():
            print("[ChatGPT] blocked: API key not validated")
            self.history.add_bubble("AI ChatBot", "❌ API key is not set. Please enter it only on the login page.")
            return

        try:
            # ✅ single source of truth
            info = m.ensure_detected()
            center_key = info.irannobat_key
            print(f"[ChatGPT] detected center={getattr(info, 'center_display', None)} key_valid=1")
        except Exception as e:
            print(f"[ChatGPT] detect failed: {e}")
            self.history.add_bubble("AI ChatBot", f"❌ No valid API Key: {e}")
            QTimer.singleShot(100, self._prompt_for_api_key)
            return

        # 🔹 Breast Expert Assistant (TEXT-ONLY, NO IMAGE)
        if self._chatgpt_mode == "breast":
            user_text = (text or "").strip()
            if not user_text:
                print("[ChatGPT] breast blocked: empty text")
                return

            self.history.add_bubble("You", f" Breast Question:\n{user_text}")
            self.composer.box.clear()

            typing = self.history.add_typing("ChatGPT", "Consulting Breast Expert.")
            model = self._current_model

            def work():
                try:
                    from .openai_reporter import BreastExpertAssistant
                    return BreastExpertAssistant(
                        user_msg=user_text,
                        CENTER_Key=center_key,   # هنوز پاس می‌دهیم ولی global است
                        model=model,
                    )
                except Exception as e:
                    return {"content": f"❌ Breast Expert Error: {str(e)}", "usage": None}

            def done(result: dict):
                self.history.remove_widget(typing)
                typing.stop()

                content = result.get("content", "")
                usage = result.get("usage")

                if usage:
                    center = usage["center"]
                    model_name = usage["model"]
                    total = usage["total_tokens"]

                    # ✅ 1) Center+Model usage (DB)  +  ✅ 2) API-Key+Model usage (DB)
                    add_token_usage_delta(center, model_name, total)
                    add_api_token_usage_delta(
                        api_key=center_key,
                        center_name=center,
                        model_name=model_name,
                        tokens_delta=total,
                    )

                    # Refresh UI
                    self._token_usage = load_token_usage()
                    self._update_token_display()

                if content.startswith("❌"):
                    self.history.add_bubble("ChatGPT", self._safe_user_error(content))
                else:
                    html = f"""
                    <div style='border-left: 3px solid #ff6f61; padding-left: 12px; margin: 10px 0;'>
                        <h3 style='color: #ff6f61'> Breast Expert Assistant</h3>
                        <div style='background: #2b2b2b; padding: 12px; border-radius: 6px; margin-top: 8px;'>
                            {content.replace(chr(10), '<br>')}
                        </div>
                    </div>
                    """
                    self.history.add_bubble("ChatGPT", html)

            worker = ApiWorker(work, parent=self)
            worker.done.connect(done)
            worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
            worker.start()
            return

        # -----------------------------
        # Image Analyzer (WITH IMAGE UPLOAD)
        # -----------------------------
        if self._chatgpt_mode == "image":
            file_path = None
            if hasattr(self.composer, "get_last_image_attachment"):
                file_path = self.composer.get_last_image_attachment()

            if not file_path:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select Image for Analysis",
                    "",
                    "Images (*.png *.jpg *.jpeg *.bmp *.dcm);All Files (*.*)",
                )
                if not file_path:
                    print("[ChatGPT] image blocked: no file selected")
                    return

            filename = os.path.basename(file_path)
            user_note = (text or "").strip()

            display_msg = f"🖼️ Analyzing: {filename}" + (f"\n📝 Note: {user_note}" if user_note else "")
            self._append_bubble("You", display_msg)

            if hasattr(self.composer, "clear_image_attachments"):
                self.composer.clear_image_attachments()

            typing = self.history.add_typing("ChatGPT", "Analyzing Image Quality.")
            model = self._current_model

            def work():
                try:
                    from .openai_reporter import ImageQualityAnalyzer
                    return ImageQualityAnalyzer(
                        user_msg=user_note,
                        CENTER_Key=center_key,
                        model=model,
                        image_path=file_path,
                    )
                except Exception as e:
                    return {"content": f"❌ Error: {str(e)}", "usage": None}

            def done(result: dict):
                self.history.remove_widget(typing)
                typing.stop()

                content = result.get("content", "")
                usage = result.get("usage")

                if usage:
                    center = usage["center"]
                    model_name = usage["model"]
                    total = usage["total_tokens"]

                    # ✅ 1) Center+Model usage (DB)  +  ✅ 2) API-Key+Model usage (DB)
                    add_token_usage_delta(center, model_name, total)
                    add_api_token_usage_delta(
                        api_key=center_key,
                        center_name=center,
                        model_name=model_name,
                        tokens_delta=total,
                    )

                    # Refresh UI
                    self._token_usage = load_token_usage()
                    self._update_token_display()

                if content.startswith("❌"):
                    self._append_bubble("ChatGPT", self._safe_user_error(content))
                else:
                    html = f"""
                    <div style='border-left: 3px solid #4a90e2; padding-left: 12px; margin: 10px 0;'>
                        <h3 style='color: #4a90e2'>🖼️ Image Quality Analysis</h3>
                        <div style='background: #2b2b2b; padding: 12px; border-radius: 6px; margin-top: 8px;'>
                            {content.replace(chr(10), '<br>')}
                        </div>
                    </div>
                    """
                    self._bubble_origin_hint = "image"
                    self._append_bubble("ChatGPT", html)

            worker = ApiWorker(work, parent=self)
            worker.done.connect(done)
            worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
            worker.start()
            return

        # -----------------------------
        # Chat / Report (NO IMAGE)
        # -----------------------------
        # In ChatGPT report mode, enforce selecting modality before sending
        modality = None
        normal_template = None
        if self._chatgpt_mode == "report":
            modality = getattr(self, "_current_modality", None)
            if not modality:
                print("[ChatGPT] report blocked: modality not selected")
                self.history.add_bubble("ChatGPT", "⚠️ <i>Please select a modality first.</i>")
                try:
                    # Open dropdown immediately to match Report pages UX
                    self._show_modality_menu()
                except Exception:
                    pass
                return
            try:
                normal_template = (self.composer.get_normal_template_text() or "").strip() or None
            except Exception:
                normal_template = None

        user_text = (text or "").strip()
        if not user_text:
            print("[ChatGPT] blocked: empty text")
            return

        self.history.add_bubble("You", user_text)
        self.composer.box.clear()

        typing = self.history.add_typing("ChatGPT", "Thinking.")
        model = self._current_model
        mode = self._chatgpt_mode  # "chat" | "report"

        # In ChatGPT "Report" sub-mode we require a modality selection before sending
        modality = None
        normal_template = None
        if mode == "report":
            modality = getattr(self, "_current_modality", None)
            if not modality:
                print("[ChatGPT] report blocked: modality not selected (late check)")
                # Ask user to select modality first (same behavior as Report pages)
                try:
                    self.history.add_bubble("ChatGPT", "⚠️ <i>Please select a modality first.</i>")
                except Exception:
                    pass
                try:
                    self._show_modality_menu()
                except Exception:
                    pass
                return
            try:
                normal_template = (self.composer.get_normal_template_text() or "").strip() or None
            except Exception:
                normal_template = None

        def work():
            try:
                if mode == "chat":
                    print(f"[ChatGPT] call gapgpt chat model={model}")
                    from .openai_reporter import chat
                    return chat(user_msg=user_text, CENTER_Key=center_key, model=model)
                else:
                    print(f"[ChatGPT] call gapgpt report model={model} modality={modality}")
                    from .openai_reporter import reporter
                    return reporter(
                        user_msg=user_text,
                        modality=modality,
                        normal_template=normal_template,
                        CENTER_Key=center_key,
                        model=model,
                    )
            except Exception as e:
                return {"content": f"❌ Error: {str(e)}", "usage": None}

        def done(result: dict):
            self.history.remove_widget(typing)
            typing.stop()

            content = result.get("content", "")
            usage = result.get("usage")
            print(content)
            print(usage)
            if usage:
                center = usage["center"]
                model_name = usage["model"]
                total = usage["total_tokens"]

                # ✅ 1) Center+Model usage (DB)  +  ✅ 2) API-Key+Model usage (DB)
                add_token_usage_delta(center, model_name, total)
                add_api_token_usage_delta(
                    api_key=center_key,
                    center_name=center,
                    model_name=model_name,
                    tokens_delta=total,
                )

                # Refresh UI
                self._token_usage = load_token_usage()
                self._update_token_display()

            if content.startswith("❌"):
                self._append_bubble("ChatGPT", self._safe_user_error(content))
                return

            cleaned = (content or "").strip()
            if "<|end|>" in cleaned:
                cleaned = cleaned.split("<|end|>", 1)[0].strip()

            if mode == "report":
                try:
                    # ✅ دقیقا مثل صفحه Report: normalize → parse → render
                    rep_raw_clean = self._normalize_report_like_payload(result)

                    # fallback (اگر به هر دلیلی result چیزی نداد)
                    if not (rep_raw_clean or "").strip():
                        rep_raw_clean = self._normalize_report_like_payload(cleaned)

                    if not (rep_raw_clean or "").strip():
                        self.history.add_bubble("ChatGPT", "⚠️ <i>Empty report output.</i>")
                        return

                    # برای Persian/Edit (اگر داری) ذخیره کن
                    self._pending_report_raw_en = rep_raw_clean
                    items = self._parse_jsonish_list(rep_raw_clean)
                    html = self._render_kv_report_html(items)

                    self._bubble_origin_hint = "report"

                    on_edit = getattr(self, "_edit_bubble", None)
                    on_persian = getattr(self, "_persian_bubble", None)
                    on_send_reception = getattr(self, "_send_to_reception", None)

                    bub = self.history.add_bubble("ChatGPT", html, on_edit=on_edit, on_persian=on_persian, on_send_reception=on_send_reception)
                    try:
                        bub.raw_report_json = rep_raw_clean
                    except Exception:
                        pass

                except Exception:
                    from html import escape
                    self.history.add_bubble(
                        "ChatGPT",
                        f"<pre style='background:#2b2b2b;padding:12px;border-radius:6px;'>{escape(cleaned)}</pre>"
                    )
            else:
                self.history.add_bubble("ChatGPT", cleaned)


        worker = ApiWorker(work, parent=self)
        worker.done.connect(done)
        worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
        worker.start()