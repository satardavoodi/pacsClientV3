from __future__ import annotations

import typing as t
import re
import os, tempfile, time, threading
import numpy as np
import sounddevice as sd
import soundfile as sf
from .ai_chat_helpers import _set_icon,extract_plain_text_from_html
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QObject, Signal, Slot, QThread,Qt,QSize, QUrl,QTimer, QMimeData, QEvent
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QPushButton,
    QPlainTextEdit, QScrollArea, QMenu, QFileDialog, QSpacerItem,QFrame,QSizePolicy,
    QDialog, QDialogButtonBox, QTextEdit,QComboBox, QMenu,QGraphicsOpacityEffect,QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QLabel, QSlider, QSizePolicy, QStyle

)
from PySide6.QtGui import (
    QMouseEvent, QPainter,QAction,QTextCursor, QTextOption, QColor, QPen, QTextDocument, QFontMetrics, QGuiApplication
)

from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from .ai_chat_config import (
    CLR_BG, CLR_BG_PANEL, CLR_TEXT, CLR_BORDER, CLR_ACCENT, CLR_BUBBLE_USER, CLR_BUBBLE_BOT
)
# Qt (same symbol as old file)
QWIDGETSIZE_MAX = 16777215
class ClickToSeekSlider(QSlider):
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            x = e.position().x() if hasattr(e, "position") else e.x()
            ratio = max(0.0, min(1.0, x / max(1, self.width())))
            self.setValue(int(ratio * (self.maximum() - self.minimum()) + self.minimum()))
            self.sliderMoved.emit(self.value())
            self.sliderReleased.emit()
            return  # --- PATCH: نذار والد دوباره رویداد را پردازش کند (لگ/پرش نگیرد)
        super().mousePressEvent(e)

class VoiceMessageBubble(QWidget):
    def __init__(self, audio_path: str, who: str, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.who = who

        self.setObjectName("VoiceMessageBubble")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(32, 32)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(100)
        self.slider.setSingleStep(1)

        lay.addWidget(self.btn_play)
        lay.addWidget(self.slider)

        # Player backend
        self.player = QMediaPlayer(self)
        self.player.setSource(QUrl.fromLocalFile(self.audio_path))
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)

        self.btn_play.clicked.connect(self.toggle_play)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("▶")
        else:
            self.player.play()
            self.btn_play.setText("⏸")

    def _on_position(self, pos):
        if self.player.duration():
            p = int((pos / self.player.duration()) * 100)
            self.slider.setValue(p)

    def _on_duration(self, d):
        self.slider.setValue(0)

class MessageBubble(QWidget):
    """
    Chat message bubble widget.

    Features:
    - Header row with:
        • Sender label (who)
        • Font size controls: "A-" (smaller) and "+A" (larger) per bubble
    - Body:
        • RichText QLabel for the message content
        • Word-wrap, clickable links, selectable/copyable
    - Footer:
        • Copy button (copies both rich HTML and cleaned plain text with bullets)
        • Edit button (optional, only visible if on_edit callback is provided)
        • Persian button (optional, only visible for AI report bubbles with callback)
        • Retry button (hidden by default, can be shown on errors)
    - Font size is clamped between 10px and 40px per bubble.
    """

    def __init__(
        self,
        who: str,
        text: str,
        parent=None,
        on_edit: t.Callable[['MessageBubble'], None] | None = None,
        on_persian: t.Callable[['MessageBubble'], None] | None = None,
        on_send_reception: t.Callable[['MessageBubble'], None] | None = None,
    ):
        super().__init__(parent)
        self.who = who
        self._raw_text = text or ""
        self._on_edit_cb = on_edit
        self._on_persian_cb = on_persian
        self._on_send_reception_cb = on_send_reception
        self._msg_id: int | None = None

        self._is_user = who.strip().lower().startswith("you")
        self._font_size: int = 16  # default font size in px

        # --- layout/reflow (IMPORTANT): prevent clipping on long reports or large font (+A) ---
        # We dynamically adapt bubble width to the available viewport width and recompute the
        # label minimum height from the rendered (rich) text.
        self._reflow_pending: bool = False
        self._max_bubble_width_cap_px: int = 1200
        self._min_bubble_width_px: int = 320

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 8)
        outer.setSpacing(4)

        # ----- header (who + A-/+A) -----
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        who_lbl = QLabel(who)
        who_lbl.setObjectName("who")
        who_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.addWidget(who_lbl, 0, Qt.AlignLeft | Qt.AlignVCenter)

        header.addStretch(1)

        # Font size controls: A- and +A
        self.btnFontDec = QToolButton(self)
        self.btnFontDec.setText("A-")
        self.btnFontDec.setToolTip("Decrease font size")
        self.btnFontDec.setCursor(Qt.PointingHandCursor)
        self.btnFontDec.setAutoRaise(True)

        self.btnFontInc = QToolButton(self)
        self.btnFontInc.setText("A+")
        self.btnFontInc.setToolTip("Increase font size")
        self.btnFontInc.setCursor(Qt.PointingHandCursor)
        self.btnFontInc.setAutoRaise(True)

        # Simple style to match the rest of the UI
        font_btn_css = """
            QToolButton {
                color: #dcdcdc;
                padding: 1px 6px;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                background: rgba(255,255,255,0.03);
                font-size: 11px;
            }
            QToolButton:hover {
                background: rgba(255,255,255,0.08);
            }
            QToolButton:pressed {
                background: rgba(255,255,255,0.12);
            }
        """
        self.btnFontDec.setStyleSheet(font_btn_css)
        self.btnFontInc.setStyleSheet(font_btn_css)

        header.addWidget(self.btnFontDec, 0, Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.btnFontInc, 0, Qt.AlignRight | Qt.AlignVCenter)

        outer.addLayout(header)

        # ----- bubble box -----
        box = QFrame(self)
        box.setObjectName("bubbleBox")
        box.setFrameShape(QFrame.StyledPanel)
        box.setFrameShadow(QFrame.Plain)
        # NOTE:
        # QSizePolicy.Maximum on the vertical axis makes the box refuse to grow beyond sizeHint,
        # which causes text to get clipped when the content is long or the font is enlarged.
        # Use Preferred/Preferred and explicitly compute a correct minimum height.
        box.setMinimumWidth(self._min_bubble_width_px)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)


        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(14, 10, 14, 10)
        box_lay.setSpacing(6)

        self.lbl = QLabel(self._raw_text, box)
        self.lbl.setObjectName("msg")
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setOpenExternalLinks(True)
        self.lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._apply_font_size()  # apply default size
        box_lay.addWidget(self.lbl, 0)

        # Keep refs for reflow.
        self._box = box
        self._box_lay = box_lay

        # ----- footer buttons -----
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(6)
        footer.addStretch(1)

        # Copy
        self.btnCopy = QToolButton(box)
        self.btnCopy.setText("Copy")
        self.btnCopy.setToolTip("Copy this message")
        self.btnCopy.setCursor(Qt.PointingHandCursor)
        self.btnCopy.setAutoRaise(True)
        self.btnCopy.setStyleSheet("""
            QToolButton {
                color: #dcdcdc; padding: 2px 8px; border: 1px solid #3a3a3a;
                border-radius: 6px; background: rgba(255,255,255,0.03);
            }
            QToolButton:hover { background: rgba(255,255,255,0.08); }
            QToolButton:pressed { background: rgba(255,255,255,0.12); }
        """)
        footer.addWidget(self.btnCopy, 0, Qt.AlignRight)

        # Edit (only if callback provided)
        self.btnEdit = QToolButton(box)
        self.btnEdit.setText("Edit")
        self.btnEdit.setToolTip("Edit this message")
        self.btnEdit.setCursor(Qt.PointingHandCursor)
        self.btnEdit.setAutoRaise(True)
        self.btnEdit.setStyleSheet(self.btnCopy.styleSheet())
        self.btnEdit.setVisible(self._on_edit_cb is not None)
        footer.addWidget(self.btnEdit, 0, Qt.AlignRight)

        # Persian (only for AI responses with callback)
        self.btnPersian: QToolButton | None = None
        if (not self._is_user) and (self._on_persian_cb is not None):
            self.btnPersian = QToolButton(box)
            self.btnPersian.setText("Persian")
            self.btnPersian.setToolTip("Translate report to Persian")
            self.btnPersian.setCursor(Qt.PointingHandCursor)
            self.btnPersian.setAutoRaise(True)
            self.btnPersian.setStyleSheet("""
                QToolButton {
                    color: #f4e1b8; padding: 2px 8px;
                    border: 1px solid #557a95;
                    border-radius: 6px;
                    background: rgba(255,255,255,0.05);
                }
                QToolButton:hover { background: rgba(255,255,255,0.10); }
                QToolButton:pressed { background: rgba(255,255,255,0.15); }
            """)
            footer.addWidget(self.btnPersian, 0, Qt.AlignRight)
        
        # Send to Reception button (only for AI responses with callback)
        self.btnSendReception: QToolButton | None = None
        if (not self._is_user) and (self._on_send_reception_cb is not None):
            self.btnSendReception = QToolButton(box)
            self.btnSendReception.setText("Send to Reception")
            self.btnSendReception.setToolTip("Send report to reception")
            self.btnSendReception.setCursor(Qt.PointingHandCursor)
            self.btnSendReception.setAutoRaise(True)
            self.btnSendReception.setStyleSheet("""
                QToolButton {
                    color: #b8f4e1; padding: 2px 8px;
                    border: 1px solid #55957a;
                    border-radius: 6px;
                    background: rgba(255,255,255,0.05);
                }
                QToolButton:hover { background: rgba(255,255,255,0.10); }
                QToolButton:pressed { background: rgba(255,255,255,0.15); }
            """)
            footer.addWidget(self.btnSendReception, 0, Qt.AlignRight)

        # Retry (hidden by default)
        self.btnRetry = QToolButton(box)
        self.btnRetry.setText("Retry")
        self.btnRetry.setVisible(False)
        self.btnRetry.setCursor(Qt.PointingHandCursor)
        self.btnRetry.setAutoRaise(True)
        self.btnRetry.setStyleSheet(self.btnCopy.styleSheet())
        footer.addWidget(self.btnRetry, 0, Qt.AlignRight)

        box_lay.addLayout(footer, 0)
        outer.addWidget(box, 0)

        # Base stylesheet
        self.setStyleSheet("""
            QLabel#who { color: #ffd48a; font-weight: 600; padding-left: 6px; }
            QFrame#bubbleBox { background: #2b2b2b; border: 1px solid #3a3a3a; border-radius: 12px; }
            QLabel#msg { color: #e6e6e6; }
        """)

        # ----- signals -----
        self.btnCopy.clicked.connect(self._on_copy_clicked)

        if self._on_edit_cb:
            self.btnEdit.clicked.connect(lambda: self._on_edit_cb(self))

        if self.btnPersian is not None:
            self.btnPersian.clicked.connect(lambda: self._on_persian_cb(self))
        
        if self.btnSendReception is not None:
            self.btnSendReception.clicked.connect(lambda: self._on_send_reception_cb(self))

        # Font size controls
        self.btnFontInc.clicked.connect(self.increase_font_size)
        self.btnFontDec.clicked.connect(self.decrease_font_size)

        # First pass: after widget is laid out, compute bubble width/height so nothing clips.
        self._schedule_reflow()

    # ----------------- Font size logic -----------------
    def _ensure_html_text(self, s: str) -> str:
        """Ensure we always render as safe HTML (QLabel is RichText)."""
        s = s or ""
        if not s.strip():
            return ""
        # If it's already (probably) HTML, keep it as-is.
        if self._is_probably_html(s):
            return s
        # Plain text → escape + preserve newlines
        return escape(s).replace("\n", "<br>")

    def _wrap_scale_html(self, inner_html: str, size_px: int) -> str:
        """Wrap HTML with a single font-size container.

        Qt RichText CSS support is limited; using inline style on a wrapper div is the most reliable.
        To make +A / A- always work, we also strip any inline font-size directives that may override the wrapper.
        """
        import re

        size_px = int(size_px)
        html = inner_html or ""

        # Remove font-size declarations that would override the wrapper.
        html = re.sub(r"(?i)font-size\s*:\s*[^;\"']+\s*;?", "", html)

        # Remove <font size="..."> overrides (keep tag, drop size attr).
        html = re.sub(
            r"(?i)<font\b([^>]*?)\s+size\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)([^>]*)>",
            r"<font\1\2>",
            html,
        )

        # Clean empty style attributes that may remain like style=""
        html = re.sub(r"\sstyle\s*=\s*(?:\"\s*\"|'\s*')", "", html)

        return f"""<div style="font-size:{size_px}px; line-height:1.35;">{html}</div>"""

    def _refresh_display(self) -> None:
        """Re-render the bubble text with current font size + RTL/LTR enforcement."""
        size = max(10, min(int(self._font_size), 40))
        self._font_size = size

        base = self._raw_text or ""
        html = self._ensure_html_text(base)
        html = self._wrap_scale_html(html, size)

        if self._has_rtl_chars(base):
            self.lbl.setLayoutDirection(Qt.RightToLeft)
            self.lbl.setAlignment(Qt.AlignRight | Qt.AlignTop)
            self.lbl.setText(self._wrap_rtl_html(html))
        else:
            self.lbl.setLayoutDirection(Qt.LeftToRight)
            self.lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.lbl.setText(html)

        # Content/font has changed → recompute geometry.
        self._schedule_reflow()

    def _apply_font_size(self):
        """
        Apply current font size to the message label with clamping.

        NOTE: For RichText, QLabel stylesheet doesn't reliably scale all HTML (e.g., inline-styled paragraphs).
        We re-wrap HTML with a scaling container + CSS to force inheritance.
        """
        self._refresh_display()


    def set_font_size(self, size: int):
        """Set font size programmatically and apply to label."""
        self._font_size = size
        self._apply_font_size()
        self._schedule_reflow()

    def increase_font_size(self):
        """Handler for +A button."""
        self.set_font_size(self._font_size + 2)

    def decrease_font_size(self):
        """Handler for A- button."""
        self.set_font_size(self._font_size - 2)

    # ----------------- Geometry / reflow (fix clipping) -----------------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Parent viewport size may have changed (window resize, splitter resize, etc.).
        self._schedule_reflow()

    def _schedule_reflow(self):
        """Coalesce reflow calls (many events can fire during resizing / font changes)."""
        if getattr(self, "_reflow_pending", False):
            return
        self._reflow_pending = True
        QTimer.singleShot(0, self._do_reflow)

    def _do_reflow(self):
        self._reflow_pending = False
        try:
            self._apply_responsive_width()

            # Layout را مجبور کن تا عرض/ارتفاع واقعی بچه‌ها (lbl) settle شود
            try:
                if getattr(self, "_box_lay", None):
                    self._box_lay.invalidate()
                    self._box_lay.activate()
            except Exception:
                pass

            # چند پاس اندازه‌گیری (Qt گاهی در 0ms هنوز عرض واقعی lbl را نداده)
            QTimer.singleShot(0, self._recalc_min_heights)
            QTimer.singleShot(30, self._recalc_min_heights)
            QTimer.singleShot(120, self._recalc_min_heights)

            # ✅ PATCH: برای Assist/متن‌های بلند، یک پاس دیرتر هم لازم است
            QTimer.singleShot(250, self._recalc_min_heights)

        except Exception:
            pass



    def _apply_responsive_width(self):
        """Set bubble max-width relative to the available scroll viewport width."""
        try:
            from PySide6.QtWidgets import QScrollArea
            w = self.parentWidget()
            scroll = None
            while w is not None:
                if isinstance(w, QScrollArea):
                    scroll = w
                    break
                w = w.parentWidget()

            if scroll is not None:
                vw = max(1, scroll.viewport().width())
            else:
                vw = max(1, (self.parentWidget().width() if self.parentWidget() else self.width()))

            # occupy ~92% of viewport, but clamp
            target = int(vw * 0.92)
            target = max(self._min_bubble_width_px, min(target, self._max_bubble_width_cap_px))

            # Apply max width (layout will pick a smaller width if needed).
            self._box.setMaximumWidth(target)
        except Exception:
            return

    def _recalc_min_heights(self):
        """Compute fixed heights from the *actual* rendered RichText width so the label never clips."""
        try:
            if not getattr(self, "_box", None) or not getattr(self, "_box_lay", None) or not getattr(self, "lbl", None):
                return

            import math
            from PySide6.QtGui import QTextDocument, QFontMetrics
            from PySide6.QtCore import QTimer

            # 0) مطمئن شو layout اعمال شده تا width واقعی باشد
            try:
                self._box_lay.invalidate()
                self._box_lay.activate()
            except Exception:
                pass

            # ✅ PATCH: قبل از محاسبه ارتفاع، قفل‌های ارتفاع قبلی را آزاد کن
            try:
                self.lbl.setMinimumHeight(0)
                self.lbl.setMaximumHeight(QWIDGETSIZE_MAX)
            except Exception:
                pass

            # 1) عرض واقعی را طوری بگیر که اگر lbl هنوز settle نشده، از box کمک بگیریم
            #    (اصلی‌ترین علت "نصفه افتادن متن" همین under-estimation عرض است)
            lbl_w = int(self.lbl.contentsRect().width())
            box_w = int(self._box.contentsRect().width())

            # پدینگ افقی داخل bubbleBox: (چپ 14 + راست 14) ≈ 28
            # یک مقدار امن/محافظه‌کارانه:
            safe_inner_pad = 28

            text_w = max(lbl_w, box_w - safe_inner_pad)
            if text_w <= 120:
                # هنوز settle نشده؛ کمی بعد دوباره
                QTimer.singleShot(35, self._recalc_min_heights)
                return

            html = self.lbl.text() or ""

            # 2) اندازه‌گیری دقیق RichText با QTextDocument
            doc = QTextDocument()
            doc.setDefaultFont(self.lbl.font())
            doc.setDocumentMargin(0.0)
            doc.setHtml(html)
            doc.setTextWidth(float(text_w))

            doc_h = float(doc.documentLayout().documentSize().height())
            content_h = int(math.ceil(doc_h))

            fm = QFontMetrics(self.lbl.font())

            # 3) پدینگ امن برای جلوگیری از بریدن خط آخر
            safe_pad = max(12, fm.descent() + int(fm.lineSpacing() * 0.6))
            content_h = max(content_h + safe_pad, fm.lineSpacing() + safe_pad)

            # 4) اعمال ارتفاع لیبل
            if self.lbl.minimumHeight() != content_h or self.lbl.maximumHeight() != content_h:
                self.lbl.setFixedHeight(content_h)

            # 5) حالا ارتفاع box را از sizeHint واقعی layout (شامل footer) بساز
            try:
                self._box_lay.invalidate()
                self._box_lay.activate()
            except Exception:
                pass

            m = self._box_lay.contentsMargins()
            box_h_hint = int(self._box_lay.sizeHint().height())
            min_box_h = int(content_h + m.top() + m.bottom())
            box_h = max(box_h_hint, min_box_h) + 8  # حاشیه‌ی امن اضافی

            if self._box.minimumHeight() != box_h or self._box.maximumHeight() != box_h:
                self._box.setFixedHeight(box_h)

            # 6) propagate geometry updates upward (برای QScrollArea/Container)
            self.lbl.updateGeometry()
            self._box.updateGeometry()
            self.updateGeometry()

            p = self.parentWidget()
            hops = 0
            while p is not None and hops < 6:
                try:
                    p.updateGeometry()
                except Exception:
                    pass
                p = p.parentWidget()
                hops += 1

        except Exception:
            return

    # --- RTL detection helpers -------------------------------------------------
    @staticmethod
    def _is_probably_html(s: str) -> bool:
        try:
            return bool(Qt.mightBeRichText(s))
        except Exception:
            # fallback ساده
            return "<" in (s or "") and ">" in (s or "")

    @classmethod
    def _wrap_rtl_html(cls, s: str) -> str:
        """
        RTL را روی خروجی enforce می‌کند (حتی اگر RichText باشد).
        همچنین لیست‌ها (ul/ol) را برای RTL اصلاح می‌کند.

        نکته: قبلاً اگر متن dir=rtl داشت، early-return می‌کرد و rtl-wrap/CSS اعمال نمی‌شد.
        این باعث می‌شد Persian translate که خودش dir=rtl دارد، باز هم بد چیدمان شود.
        """
        s = s or ""
        if not s.strip():
            return s

        low = s.lower()

        # اگر قبلاً با rtl-wrap wrap شده، دوباره wrap نکن
        if "rtl-wrap" in low:
            return s

        # اگر متن plain است، به HTML امن تبدیل کن
        if not cls._is_probably_html(s):
            s = escape(s).replace("\n", "<br>")

        rtl_css = """
        <style>
            /* enforce RTL + right align */
            .rtl-wrap { direction: rtl; text-align: right; unicode-bidi: plaintext; }
            /* lists in RTL should indent on right, not left */
            .rtl-wrap ul, .rtl-wrap ol { margin-right: 18px; margin-left: 0; padding-right: 0; padding-left: 0; }
            .rtl-wrap li { text-align: right; }
        </style>
        """

        return rtl_css + "<div class='rtl-wrap' dir='rtl'>" + s + "</div>"

        
    @staticmethod
    def _has_rtl_chars(text: str) -> bool:
        """
        Returns True if text contains any RTL (e.g. Persian/Arabic) characters.
        """
        if not text:
            return False
        for ch in text:
            code = ord(ch)
            # Persian/Arabic ranges
            if (
                0x0600 <= code <= 0x06FF or  # Arabic, Persian
                0x0750 <= code <= 0x077F or  # Arabic Supplement
                0x08A0 <= code <= 0x08FF or  # Arabic Extended-A
                0xFB50 <= code <= 0xFDFF or  # Arabic Presentation Forms-A
                0xFE70 <= code <= 0xFEFF    # Arabic Presentation Forms-B
            ):
                return True
        return False

    def _apply_directionality(self) -> None:
        txt = self._raw_text or ""
        is_rtl = self._has_rtl_chars(txt)

        if is_rtl:
            self.lbl.setLayoutDirection(Qt.RightToLeft)
            self.lbl.setAlignment(Qt.AlignRight | Qt.AlignTop)
            # مهم: اگر کسی از بیرون setText زده باشد، دوباره RTL را enforce کن
            shown = self.lbl.text() or ""
            if "rtl-wrap" not in shown:
                self.lbl.setText(self._wrap_rtl_html(shown))
        else:
            self.lbl.setLayoutDirection(Qt.LeftToRight)
            self.lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    # ----------------- Content helpers -----------------
    def _looks_like_html(self, s: str) -> bool:
        s = (s or "").lstrip()
        return s.startswith("<") and (">" in s)

    def _ensure_rtl_html_wrapper(self):
        """
        QLabel وقتی RichText است، AlignRight و LayoutDirection همیشه کافی نیست.
        باید خود HTML هم dir/align داشته باشد.
        """
        html = self._raw_text or ""
        low = html.lower()

        # اگر قبلاً RTL شده، دوباره wrap نکن
        if "dir='rtl'" in low or 'dir="rtl"' in low or "direction: rtl" in low:
            return

        # فقط وقتی HTML داریم wrap کنیم (اگر plain باشد، QLabel خودش می‌چیند ولی باز هم بهتر است)
        if self._looks_like_html(html):
            self._raw_text = (
                "<div dir='rtl' style='direction: rtl; text-align: right; unicode-bidi: plaintext;'>"
                f"{html}"
                "</div>"
            )
            self.lbl.setText(self._raw_text)


    def set_html(self, html: str):
        # Keep the original HTML/plain text (used for copy/export), but render a scaled version.
        self._raw_text = html or ""
        self._apply_font_size()
        self._schedule_reflow()

    def get_html(self) -> str:
        return self._raw_text

    # ----------------- Retry helpers -----------------
    def show_retry(self, on_click: t.Callable[[], None] | None = None, reason: str | None = None):
        if reason:
            self.setStyleSheet(self.styleSheet() + " QFrame#bubbleBox { border-color: #9b4a4a; }")
        self.btnRetry.setVisible(True)
        if on_click:
            try:
                self.btnRetry.clicked.disconnect()
            except Exception:
                pass
            self.btnRetry.clicked.connect(on_click)

    def clear_retry(self):
        self.btnRetry.setVisible(False)
        self.setStyleSheet("""
            QLabel#who { color: #ffd48a; font-weight: 600; padding-left: 6px; }
            QFrame#bubbleBox { background: #2b2b2b; border: 1px solid #3a3a3a; border-radius: 12px; }
            QLabel#msg { color: #e6e6e6; }
        """)

    # ----------------- Copy logic -----------------
    def _on_copy_clicked(self):
        """
        Copy both:
        - Full HTML (for rich destinations)
        - Clean plain-text with bullets and indentation (for simple destinations)
        """
        html = self._raw_text or ""

        # Build clean plain text from QTextDocument
        doc = QTextDocument()
        doc.setHtml(html)

        lines = []
        block = doc.begin()
        while block.isValid():
            txt = block.text().strip()
            if txt:
                lst = block.textList()
                if lst is not None:
                    level = max(0, lst.format().indent() - 1)
                    bullet = "•"
                    lines.append(("  " * level) + f"{bullet} {txt}")
                else:
                    lines.append(txt)
            block = block.next()
        plain = "\n".join(lines).strip()

        # Put both formats onto clipboard
        md = QMimeData()
        md.setHtml(html)
        md.setText(plain)
        QGuiApplication.clipboard().setMimeData(md)

        # UI feedback
        old = self.btnCopy.text()
        self.btnCopy.setText("Copied!")
        self.btnCopy.setEnabled(False)
        QTimer.singleShot(900, lambda: (self.btnCopy.setText(old), self.btnCopy.setEnabled(True)))

    @staticmethod
    def _is_probably_html(s: str) -> bool:
        try:
            return bool(Qt.mightBeRichText(s))
        except Exception:
            # fallback ساده
            return "<" in (s or "") and ">" in (s or "")

    @classmethod
    def _wrap_rtl_html(cls, s: str) -> str:
        """
        RTL را روی خروجی enforce می‌کند (حتی اگر RichText باشد).
        همچنین لیست‌ها (ul/ol) را برای RTL اصلاح می‌کند.
        """
        s = s or ""
        if not s.strip():
            return s

        # اگر قبلاً RTL شده، دوباره wrap نکن
        low = s.lower()
        if "dir='rtl'" in low or 'dir="rtl"' in low or "direction: rtl" in low:
            return s

        # اگر متن plain است، به HTML امن تبدیل کن
        if not cls._is_probably_html(s):
            s = escape(s).replace("\n", "<br>")

        rtl_css = """
        <style>
            /* enforce RTL + right align */
            .rtl-wrap { direction: rtl; text-align: right; unicode-bidi: plaintext; }
            /* lists in RTL should indent on right, not left */
            .rtl-wrap ul, .rtl-wrap ol { margin-right: 18px; margin-left: 0; padding-right: 0; padding-left: 0; }
            .rtl-wrap li { text-align: right; }
        </style>
        """

        return (
            rtl_css +
            "<div class='rtl-wrap' dir='rtl'>"
            f"{s}"
            "</div>"
        )

class TypingBubble(QWidget):
    def __init__(self, who: str, base_text: str = "Thinking"):
        super().__init__()
        root = QHBoxLayout(self);
        root.setContentsMargins(0, 8, 0, 8)
        card = QFrame();
        card.setObjectName("bubbleBot");
        card.setFrameShape(QFrame.NoFrame)
        card.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        v = QVBoxLayout(card);
        v.setContentsMargins(14, 10, 14, 10);
        v.setSpacing(6)
        self.name = QLabel(who);
        self.name.setObjectName("nameBot")
        self.msg = QLabel(base_text);
        self.msg.setWordWrap(True)
        v.addWidget(self.name);
        v.addWidget(self.msg)
        card.setMaximumWidth(760);
        root.addStretch();
        root.addWidget(card);
        root.addStretch()
        self.setStyleSheet(f"""
            QFrame#bubbleBot {{ background:{CLR_BUBBLE_BOT}; border:1px solid {CLR_BORDER}; border-radius:12px; color:{CLR_TEXT}; }}
            QLabel#nameBot  {{ color:#ffd48a; font-size:12px; }}
        """)
        self._base, self._dots = base_text, 0
        self._timer = QTimer(self);
        self._timer.timeout.connect(self._tick);
        self._timer.start(400)

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.msg.setText(self._base + ("." * self._dots))

    def stop(self): self._timer.stop()

class ChatHistory(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"""
            QScrollArea{{border:none;background:{CLR_BG};}}
            QScrollArea>QWidget>QWidget{{background:{CLR_BG};}}
            QScrollBar:vertical{{background:transparent;width:14px;margin:0}}
            QScrollBar::handle:vertical{{background:rgba(255,255,255,0.2);min-height:30px;border-radius:7px}}
            QScrollBar::handle:vertical:hover{{background:rgba(255,255,255,0.3)}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;background:transparent;border:none}}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:none}}
        """)

        self.container = QWidget()
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setContentsMargins(16, 16, 16, 16)
        self.vbox.setSpacing(0)

        # Spacer انتهاییِ ثابت (همیشه باید آخرِ لِی‌آوت بماند)
        self._tail_spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.vbox.addItem(self._tail_spacer)

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def _stick_to_bottom(self, w: QWidget | None = None):
        """
        بعد از اضافه شدن پیام جدید/typing/voice:
        - چند پاس اسکرول می‌زنیم تا اگر Qt دیر range را آپدیت کرد هم
        نهایتاً روی آخرین آیتم قفل شود.
        """

        def _do_scroll():
            try:
                # 1) مطمئن شو layout آپدیت شده
                try:
                    self.vbox.invalidate()
                    self.vbox.activate()
                except Exception:
                    pass

                sb = self.scroll.verticalScrollBar()

                # 2) اگر ویجت مشخصی داریم، اول مطمئن شو دیده می‌شود
                if w is not None:
                    try:
                        self.scroll.ensureWidgetVisible(w)
                    except Exception:
                        pass

                # 3) بعد حتماً برو ته
                sb.setValue(sb.maximum())
            except Exception:
                pass

        # چند پاس برای وقتی که Qt دیرتر range را آپدیت می‌کند
        for delay in (0, 30, 120, 250):
            QTimer.singleShot(delay, _do_scroll)

    def add_voice(self, who: str, audio_path: str, row: int | None = None):
        """
        فقط «بابل ویس» همیشه سمت راست باشد (چه کاربر چه بات).
        """
        vb = VoiceMessageBubble(audio_path, who, self.container)

        wrap = QWidget(self.container)
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(0)

        # همیشه سمت راست
        lay.addStretch(1)
        lay.addWidget(vb, 0, Qt.AlignRight | Qt.AlignTop)
        lay.addSpacing(4)

        self.vbox.removeItem(self._tail_spacer)
        if row is None:
            self.vbox.addWidget(wrap, 0, Qt.AlignTop)
        else:
            self.vbox.insertWidget(max(0, row), wrap, 0, Qt.AlignTop)
        self.vbox.addItem(self._tail_spacer)

        self._stick_to_bottom(wrap)
        return vb


    def add_bubble(
        self,
        who: str,
        text: str,
        on_edit=None,
        on_persian=None,
        on_send_reception=None,
        force_right: bool | None = None,   # جدید: فقط برای موارد خاص مثل تصویر
    ) -> MessageBubble:
        """
        - متن‌های معمولی: کاربر سمت راست، بات سمت چپ (مثل قبل)
        - اگر force_right=True باشد: حتی بات هم سمت راست می‌آید (فقط برای موارد خاص مثل «تصویر»)
        """
        bubble = MessageBubble(
            who,
            text,
            parent=self.container,
            on_edit=on_edit,
            on_persian=on_persian,
            on_send_reception=on_send_reception,
        )

        wrap = QWidget(self.container)
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(0)

        is_user = who.lower().startswith("you")
        align_right = bool(force_right) or is_user

        if align_right:
            lay.addStretch(1)
            lay.addWidget(bubble, 0, Qt.AlignRight | Qt.AlignTop)
            lay.addSpacing(4)
        else:
            lay.addSpacing(4)
            lay.addWidget(bubble, 0, Qt.AlignLeft | Qt.AlignTop)
            lay.addStretch(1)

        self.vbox.removeItem(self._tail_spacer)
        self.vbox.addWidget(wrap, 0, Qt.AlignTop)
        self.vbox.addItem(self._tail_spacer)

        self._stick_to_bottom(wrap)
        return bubble

            
    def add_typing(self, who: str = "AI ChatBot", text: str = "Thinking"):

        w = TypingBubble(who, text)
        self.vbox.removeItem(self._tail_spacer)
        self.vbox.addWidget(w, 0, Qt.AlignTop)
        self.vbox.addItem(self._tail_spacer)
        self._stick_to_bottom(w)
        return w

    def remove_widget(self, w: QWidget | None):
        if not w:
            return
        for i in range(self.vbox.count()):
            it = self.vbox.itemAt(i)
            if it and it.widget() is w:
                it = self.vbox.takeAt(i)
                if it.widget():
                    it.widget().deleteLater()
                break
        self._stick_to_bottom()

    def clear(self):
        """
        همه‌ی ویجت‌ها را پاک می‌کنیم ولی Spacer انتهایی را نگه می‌داریم.
        """
        for i in reversed(range(self.vbox.count())):
            it = self.vbox.itemAt(i)
            w = it.widget() if it else None
            if w is not None:
                self.vbox.removeWidget(w)
                w.deleteLater()
        # مطمئن شو Spacer هست
        if self.vbox.itemAt(self.vbox.count() - 1) is not self._tail_spacer:
            try:
                self.vbox.removeItem(self._tail_spacer)
            except Exception:
                pass
            self.vbox.addItem(self._tail_spacer)
        self._stick_to_bottom()

class MiniWaveform(QWidget):
    """Waveform مینیمال شبیه GPT: چند ده میله‌ی عمودی از خط وسط."""

    def __init__(self, parent=None, bars: int = 96):
        super().__init__(parent)
        self._bars = bars
        self._levels = [0.0] * bars
        self.setMinimumHeight(36)
        self.setMaximumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def clear(self):
        self._levels = [0.0] * self._bars
        self.update()

    def push(self, level: float):
        lvl = 0.0 if level is None else max(0.0, min(1.0, float(level)))
        self._levels.pop(0);
        self._levels.append(lvl)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self);
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width();
        h = self.height()
        margin = 8;
        mid = h // 2
        # خط مرکزی کمرنگ
        pen_base = QPen(QColor(255, 255, 255, 50));
        pen_base.setWidth(1);
        p.setPen(pen_base)
        p.drawLine(margin, mid, w - margin, mid)
        # میله‌ها
        step = max(1.0, (w - 2 * margin) / self._bars)
        max_amp = (h - 6) / 2.0
        pen_bar = QPen(QColor(255, 255, 255, 180))
        pen_bar.setWidthF(max(1.0, step * 0.5));
        p.setPen(pen_bar)
        x = margin + step * 0.5
        for lvl in self._levels:
            amp = lvl * max_amp
            p.drawLine(int(x), int(mid - amp), int(x), int(mid + amp))
            x += step
        p.end()

class UnifiedComposer(QWidget):
    """
    Textbox + controls با نوار عمودیِ ضمیمه‌های صوتی در سمت چپ.
    - ستون چپ: voice attachments (chips) به‌صورت عمودی
    - ستون راست: tabs + textarea + controls (همان رفتار قبلی)
    """
    sendClicked = Signal(str)
    transcribeRequested = Signal(dict)
    cancelClicked = Signal()
    standardizeClicked = Signal(str)
    modalitySelected = Signal(str) 
    
    def __init__(self, placeholder: str = "Write/paste report text"):
        super().__init__()
        # ---------- tab state ----------
        self._active_tab = "transcribe"
        self._buf_standard = ""
        self._buf_transcribe = ""
        self._buf_normal_template = ""  
        self._is_standardized = False
        # ---------- normal-template JSON source ----------
        self._nt_loaded_path: str | None = None
        self._nt_templates: list[dict] = []
        self._nt_name_to_html: dict[str, str] = {}


        # ---------- standardization cache ----------
        # Standard should NOT regenerate just because user switches tabs.
        # It regenerates only when source text changes OR user explicitly presses retry.
        self._std_source_hash: str | None = None
        self._std_pending_source_hash: str | None = None
        self._std_pending_source_text: str | None = None
        self._std_last_source_text: str = ""
        self.setAcceptDrops(True)
        # ---------- state ----------
        self._rec_running = False
        self._rec_paused = False
        self._rec_fs = 44100
        self._rec_frames = []
        self._rec_thread = None
        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._on_rec_tick)
        self._rec_start_ts = None
        self._rec_level = 0.0
        self._rec_level_smooth = 0.0
        self._agc_peak = 0.10
        self._noise_floor = 0.015
        self._voice_src_path = None
        self._mic_mode = "record"  # "record" | "confirm"
        # متغیر برای نگهداری مودالیتی انتخاب شده
        self._selected_modality = None
        self._modality_options = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]
        self._transcribe_quality_mode = "clear" 
        # --- chip audio player (for voice chips) ---
        self._chip_player = QMediaPlayer(self)
        self._chip_audio = QAudioOutput(self)
        self._chip_player.setAudioOutput(self._chip_audio)
        self._chip_playing_path: str | None = None
        self._chip_duration_ms: int = 0
        self._chip_user_seeking: bool = False
        self._chip_active_slider: ClickToSeekSlider | None = None
        self._chip_active_time_lbl: QLabel | None = None
        self._chip_player.playbackStateChanged.connect(self._on_chip_state_changed)
        self._chip_player.durationChanged.connect(self._on_chip_duration)
        self._chip_player.positionChanged.connect(self._on_chip_position)
        # ---------- نوار ضمیمه‌های صوتی (بالای textarea، چسبیده به چپ) ----------
        self.attach_frame = QFrame(self)
        self.attach_frame.setObjectName("chip")
        self.attach_frame.setVisible(False)
        self.attach_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.attach_frame.setStyleSheet("""
            QFrame#chip { background: transparent; border: none; margin-bottom: 6px; }
        """)
        # سازگاری با ارجاعات قدیمی
        self.lbl_file = QLabel("")
        self.btn_chip_x = QPushButton("✕", self.attach_frame)
        self.btn_chip_x.setObjectName("chipx")
        self.btn_chip_x.hide()
        self._buf_correction = ""
        # When installed as an overlay on the history viewport, it floats and won't push the chat upward.
        self._attach_overlay_host: QWidget | None = None
        self._attach_overlay_margin_px: int = 12
        self._attach_opacity_fx = QGraphicsOpacityEffect(self.attach_frame)
        self._attach_opacity_fx.setOpacity(0.60)  # lower = more "in the back"
        self.attach_frame.setGraphicsEffect(self._attach_opacity_fx)
        try:
            self.attach_frame.setAttribute(Qt.WA_TranslucentBackground, True)
        except Exception:
            pass
        # ---------- شِل (textbox + controls) ----------
        self.input_shell = QFrame(self)
        self.input_shell.setObjectName("shell")
        self.input_shell.setStyleSheet(f"""
            QFrame#shell {{ background:{CLR_BG}; border:1px solid {CLR_BORDER}; border-radius:12px; }}
            QTextEdit#composerEdit {{ background:transparent; border:none; color:#ddd; }}
        """)
        shell = QVBoxLayout(self.input_shell)
        shell.setContentsMargins(12, 12, 12, 12)
        shell.setSpacing(0)
        # Tabs
        tabs_bar = QFrame(self.input_shell)
        tabs_bar.setObjectName("tabsbar")
        tabs_bar.setStyleSheet(f"""
            QFrame#tabsbar {{ border: none; }}

            /* unified tab style (match tool buttons) */
            QToolButton[role="tab"] {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                min-height:30px;
                min-width:40px;
                padding:0 10px;
                font-size:13px;
                font-weight:600;
                margin-right: 10px;
            }}
            QToolButton[role="tab"]:hover {{
                border-color:{CLR_ACCENT};
                background:#4a4a4a;
            }}
            QToolButton[role="tab"]:pressed {{ background:#2d2d2d; }}
            QToolButton[role="tab"][active="true"] {{
                background:#4a4a4a;
                color:#fff;
                font-weight:700;
                border-color:#666;
            }}

            /* ------------------------------
               Standard + Retry = segmented tab (same height/shape)
               ------------------------------ */
            QFrame#stdTabGroup {{ background: transparent; border: none; margin-right: 10px; }}

            /* left part (Standard) */
            QToolButton[role="tab"][group="std"][side="left"] {{
                margin-right: 0px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
            }}

            /* right part (Retry) */
            QToolButton[role="tab_retry"][group="std"][side="right"] {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 12px;
                border-bottom-right-radius: 12px;
                min-height:30px;
                min-width:30px;
                padding:0;
            }}
            QToolButton[role="tab_retry"][group="std"][side="right"]:hover {{
                border-color:{CLR_ACCENT};
                background:#4a4a4a;
            }}
            QToolButton[role="tab_retry"][group="std"][side="right"]:pressed {{ background:#2d2d2d; }}
        """)
        tabs_lay = QHBoxLayout(tabs_bar)
        tabs_lay.setContentsMargins(0, 0, 0, 0)
        tabs_lay.setSpacing(8)

        # ✅ Define tab buttons ONCE
        self.btn_tab_trans = QToolButton(tabs_bar)
        self.btn_tab_trans.setText("Transcribe")
        self.btn_tab_trans.setProperty("role", "tab")
        self.btn_tab_trans.setFixedHeight(30)
        self.btn_tab_trans.setMinimumWidth(132)
        self.btn_tab_trans.setCursor(Qt.PointingHandCursor)
        self.btn_tab_trans.clicked.connect(lambda: self.switch_tab("transcribe"))

        self.btn_tab_normal = QToolButton(tabs_bar)
        self.btn_tab_normal.setText("Normal Template")
        self.btn_tab_normal.setProperty("role", "tab")
        self.btn_tab_normal.setFixedHeight(30)
        self.btn_tab_normal.setMinimumWidth(132)
        self.btn_tab_normal.setCursor(Qt.PointingHandCursor)
        self.btn_tab_normal.clicked.connect(lambda: self.switch_tab("normal_template"))


        # --- Standard + Retry as a visually grouped control ---
        self.std_tab_group = QFrame(tabs_bar)
        self.std_tab_group.setObjectName("stdTabGroup")
        _std_lay = QHBoxLayout(self.std_tab_group)
        _std_lay.setContentsMargins(0, 0, 0, 0)
        _std_lay.setSpacing(0)

        self.btn_tab_standard = QToolButton(self.std_tab_group)
        self.btn_tab_standard.setText("Standard")
        self.btn_tab_standard.setProperty("role", "tab")
        self.btn_tab_standard.setProperty("group", "std")
        self.btn_tab_standard.setProperty("side", "left")
        self.btn_tab_standard.setFixedHeight(30)
        self.btn_tab_standard.setMinimumWidth(60)
        self.btn_tab_standard.setCursor(Qt.PointingHandCursor)
        self.btn_tab_standard.clicked.connect(self._handle_standard_tab_click)

        # 🔁 Retry (do NOT auto-regenerate on tab switching; only on explicit retry)
        self.btn_tab_standard_retry = QToolButton(self.std_tab_group)
        self.btn_tab_standard_retry.setProperty("role", "tab_retry")
        self.btn_tab_standard_retry.setProperty("group", "std")
        self.btn_tab_standard_retry.setProperty("side", "right")
        self.btn_tab_standard_retry.setCursor(Qt.PointingHandCursor)
        self.btn_tab_standard_retry.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_tab_standard_retry.setToolTip("Retry standardization")
        try:
            self.btn_tab_standard_retry.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        except Exception:
            self.btn_tab_standard_retry.setText("⟳")
        self.btn_tab_standard_retry.setIconSize(QSize(18, 18))
        self.btn_tab_standard_retry.setFixedSize(30, 30)
        self.btn_tab_standard_retry.clicked.connect(self._handle_standard_retry_click)

        _std_lay.addWidget(self.btn_tab_standard)
        _std_lay.addWidget(self.btn_tab_standard_retry)

        self.btn_tab_correction = QToolButton(tabs_bar)
        self.btn_tab_correction.setText("✅ Correction")
        self.btn_tab_correction.setProperty("role", "tab")
        self.btn_tab_correction.setFixedHeight(30)
        self.btn_tab_correction.setMinimumWidth(132)
        self.btn_tab_correction.setCursor(Qt.PointingHandCursor)
        self.btn_tab_correction.clicked.connect(lambda: self.switch_tab("correction"))


        # ✅ Add each button ONLY ONCE, in correct order, aligned left
        tabs_lay.addWidget(self.btn_tab_trans, 0, Qt.AlignLeft)
        tabs_lay.addWidget(self.btn_tab_normal, 0, Qt.AlignLeft)
        tabs_lay.addWidget(self.std_tab_group, 0, Qt.AlignLeft)
        tabs_lay.addWidget(self.btn_tab_correction, 0, Qt.AlignLeft)

        tabs_lay.addStretch(1)
        tabs_bar.setLayoutDirection(Qt.LeftToRight)


        # ---------- Normal Template JSON toolbar (only visible in normal_template tab) ----------
        # Expected JSON: list[{"Name": "...", "Html": "..."}]
        # We keep the Html string as the effective Normal Template.
        self._nt_loaded_path = None
        self._nt_templates = []
        self._nt_name_to_html = {}
        self.nt_bar = QFrame(self.input_shell)
        self.nt_bar.setObjectName("ntbar")
        self.nt_bar.setVisible(False)


        self._composer_box_max_h = 140 
        self._nt_bar_fixed_h = 44  
        self.nt_bar.setFixedHeight(self._nt_bar_fixed_h)

        self.nt_bar.setFixedHeight(self._nt_bar_fixed_h)
        self.nt_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


        
        self.nt_bar.setStyleSheet(f"""
            QFrame#ntbar {{
                background: transparent;
                border: none;
            }}

            /* Make the NT toolbar buttons visually consistent with tabs/controls */
            QToolButton {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                padding: 0 10px;
                min-height:30px;
                min-width:110px;
                font-size:13px;
                font-weight:700;
            }}
            QToolButton:hover {{ border-color:{CLR_ACCENT}; background:#4a4a4a; }}
            QToolButton:pressed {{ background:#2d2d2d; }}


            QToolButton[nt_action="upload"]:hover {{
                background: rgba(255, 212, 138, 0.22);
            }}

            QToolButton[nt_action="clear"] {{
                min-width:70px;
                font-weight:600;
            }}

            QComboBox {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                padding: 4px 10px;
                min-height:30px;
            }}
            QComboBox:hover {{ border-color:{CLR_ACCENT}; background:#4a4a4a; }}
            QComboBox::drop-down {{ border: none; }}

            QLabel#ntinfo {{
                color: rgba(220,220,220,0.75);
            }}
        """)


        nt_lay = QHBoxLayout(self.nt_bar)
        nt_lay.setContentsMargins(8, 4, 8, 4)
        nt_lay.setSpacing(10)

        self.btn_nt_upload = QToolButton(self.nt_bar)
        self.btn_nt_upload.setText("📁 Upload JSON")
        self.btn_nt_upload.setProperty("role", "tab")  
        self.btn_nt_upload.setCursor(Qt.PointingHandCursor)
        self.btn_nt_upload.setToolTip("First, upload the Normal Template (JSON) file.")
        self.btn_nt_upload.clicked.connect(self._on_nt_upload_clicked)

        self.cmb_nt_names = QComboBox(self.nt_bar)
        self.cmb_nt_names.setEditable(False)
        self.cmb_nt_names.addItem("Upload JSON first…")
        self.cmb_nt_names.currentIndexChanged.connect(self._on_nt_name_changed)
        self.cmb_nt_names.setEnabled(False)

        self.lbl_nt_info = QLabel("Upload JSON first…", self.nt_bar)
        self.lbl_nt_info.setObjectName("ntinfo")
        self.lbl_nt_info.setStyleSheet("color: rgba(220,220,220,0.7);")

        self.btn_nt_clear = QToolButton(self.nt_bar)
        self.btn_nt_clear.setText("Clear")
        self.btn_nt_clear.setProperty("nt_action", "clear")
        self.btn_nt_clear.setToolTip("Clear files and selections")
        self.btn_nt_clear.setProperty("role", "tool")
        self.btn_nt_clear.setProperty("kind", "text")
        self.btn_nt_clear.setCursor(Qt.PointingHandCursor)
        self.btn_nt_clear.clicked.connect(self._on_nt_clear_clicked)
        self.btn_nt_clear.setEnabled(False)

        nt_lay.addWidget(self.btn_nt_upload, 0, Qt.AlignLeft)
        nt_lay.addWidget(self.cmb_nt_names, 1)
        nt_lay.addWidget(self.lbl_nt_info, 0, Qt.AlignLeft)
        nt_lay.addWidget(self.btn_nt_clear, 0, Qt.AlignLeft)

        # ---------- Correction toolbar (only visible in correction tab) ----------
        # User selects a previously generated report from dropdown and writes correction notes below.
        self._corr_reports = []  # list[(label:str, report_text:str)]
        self._corr_id_counter = 0

        self.corr_bar = QFrame(self.input_shell)
        self.corr_bar.setObjectName("corrbar")
        self.corr_bar.setVisible(False)

        self._corr_bar_fixed_h = 44
        self.corr_bar.setFixedHeight(self._corr_bar_fixed_h)
        self.corr_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.corr_bar.setStyleSheet(f"""
            QFrame#corrbar {{
                background: transparent;
                border: none;
            }}

            QComboBox {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                padding: 4px 10px;
                min-height:30px;
            }}
            QComboBox:hover {{ border-color:{CLR_ACCENT}; background:#4a4a4a; }}
            QComboBox::drop-down {{ border: none; }}

            QLabel#corrinfo {{
                color: rgba(220,220,220,0.75);
            }}
        """)

        corr_lay = QHBoxLayout(self.corr_bar)
        corr_lay.setContentsMargins(8, 4, 8, 4)
        corr_lay.setSpacing(10)

        self.cmb_corr_reports = QComboBox(self.corr_bar)
        self.cmb_corr_reports.setEditable(False)
        self.cmb_corr_reports.addItem("Select report…")
        self.cmb_corr_reports.currentIndexChanged.connect(self._on_corr_report_changed)

        self.lbl_corr_info = QLabel("", self.corr_bar)
        self.lbl_corr_info.setObjectName("corrinfo")
        self.lbl_corr_info.setStyleSheet("color: rgba(220,220,220,0.7);")

        corr_lay.addWidget(self.cmb_corr_reports, 1)
        corr_lay.addWidget(self.lbl_corr_info, 0, Qt.AlignLeft)

        # Text box
        self.box = QTextEdit(self.input_shell)
        self.box.setObjectName("composerEdit")
        f = self.box.font()
        f.setPointSize(14)
        self.box.setFont(f)
        # keep a cached input font size (for A-/+A on main controls)
        self._input_font_pt = int(getattr(f, "pointSize", lambda: 14)() or 14)
        # Keep per-tab placeholders
        self._ph_transcribe = placeholder
        self._ph_standard = "Standardized text…"
        self._ph_normal_template = "Normal Template (optional)…"
        self.box.setPlaceholderText(placeholder)
        self.box.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.box.setMaximumHeight(self._composer_box_max_h)
        self.box.installEventFilter(self)
        try:
            self.box.viewport().installEventFilter(self)
        except Exception:
            pass
        # keep RTL/AlignRight live while typing/pasting
        try:
            self.box.textChanged.connect(self._apply_box_direction)
        except Exception:
            pass
        # Controls bar
        controls = QFrame(self.input_shell)
        controls.setObjectName("controls")
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        controls.setMinimumHeight(52)
        controls.setStyleSheet(f"""
            QFrame#controls {{ background:transparent; border-top:1px solid rgba(255,255,255,0.06); margin-top:8px; }}

            /* unified tool buttons (send/+ and all text tools) */
            QToolButton[role="tool"] {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                min-width:40px;
                min-height:40px;
                padding:0;
                font-size:13px;
                font-weight:600;
            }}

            /* wide text tools (Voice Quality / Modalities / Turbo) */
            QToolButton[role="tool"][kind="text"] {{
                min-width:80px;
                min-height:40px;
                padding: 0 10px;
            }}
            QToolButton[role="tool"][kind="text"]::menu-indicator {{
                subcontrol-position: right center;
                subcontrol-origin: padding;
                left: -4px;
            }}

            QToolButton[role="tool"]:hover  {{ border-color:{CLR_ACCENT}; background:#4a4a4a; }}
            QToolButton[role="tool"]:pressed{{ background:#2d2d2d; }}
        """)
        ctl = QHBoxLayout(controls)
        ctl.setContentsMargins(12, 6, 12, 6)
        ctl.setSpacing(10)

        # HUD ضبط
        self.rec_panel = QFrame(controls)
        self.rec_panel.setObjectName("recHUD")
        self.rec_panel.setVisible(False)
        _rec_h = QHBoxLayout(self.rec_panel)
        _rec_h.setContentsMargins(0, 0, 0, 0)
        _rec_h.setSpacing(8)
        self.lbl_rec_time = QLabel("00:00", self.rec_panel)
        self.lbl_rec_time.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self.wave = MiniWaveform(self.rec_panel)
        _rec_h.addWidget(self.lbl_rec_time, 0, Qt.AlignVCenter)
        _rec_h.addWidget(self.wave, 1, Qt.AlignVCenter)

        self.btn_pause = QToolButton(controls)
        self.btn_pause.setProperty("role", "tool")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setFixedSize(30, 40)
        self.btn_pause.setVisible(False)
        self.btn_pause.clicked.connect(self._toggle_pause_record)
        _rec_h.addWidget(self.btn_pause, 0, Qt.AlignVCenter)

        icon_sz = QSize(20, 20)
        # ➕ دکمه اضافه کردن فایل
        self.btn_plus = QToolButton(controls)
        self.btn_plus.setProperty("role", "tool")
        self.btn_plus.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_plus.setCursor(Qt.PointingHandCursor)
        self.btn_plus.setIconSize(icon_sz)
        self.btn_plus.setFixedSize(30, 40)
        _set_icon(self.btn_plus, "plus.png", icon_sz.width(), "Add voice/file")
        self.btn_plus.clicked.connect(self._choose_file)

        # 🎙️ دکمه میکروفون
        self.btn_mic = QToolButton(controls)
        self.btn_mic.setProperty("role", "tool")
        self.btn_mic.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_mic.setCursor(Qt.PointingHandCursor)
        self.btn_mic.setIconSize(icon_sz)
        self.btn_mic.setFixedSize(30, 40)
        self.btn_mic.clicked.connect(self._on_mic_clicked)
        self._apply_mic_mode("record")

        # 🔽 دکمه Dropdown کیفیت ترنسکریپت
        self.btn_transcribe_quality = QToolButton(controls)
        self.btn_transcribe_quality.setProperty("role", "tool")
        self.btn_transcribe_quality.setText("🎙️Voice Quality")
        self.btn_transcribe_quality.setCursor(Qt.PointingHandCursor)
        self.btn_transcribe_quality.setProperty("kind", "text")
        self.btn_transcribe_quality.setFixedHeight(40)
        self.btn_transcribe_quality.setFixedWidth(140)
        self.btn_transcribe_quality.clicked.connect(self._show_transcribe_quality_menu)

        # 📋 دکمه مودالیتی
        self.btn_modality = QToolButton(controls)
        self.btn_modality.setProperty("role", "tool")
        self.btn_modality.setText("Modalities")
        self.btn_modality.setCursor(Qt.PointingHandCursor)
        self.btn_modality.setProperty("kind", "text")
        self.btn_modality.setFixedHeight(40)
        self.btn_modality.setFixedWidth(140)
        self.btn_modality.setVisible(False)

        self.btn_all_modality_hq = QToolButton(controls)
        self.btn_all_modality_hq.setProperty("role", "tool")
        self.btn_all_modality_hq.setText("⚡Turbo")
        self.btn_all_modality_hq.setCursor(Qt.PointingHandCursor)
        self.btn_all_modality_hq.setToolTip("Run high-quality model")
        self.btn_all_modality_hq.setProperty("kind", "text")
        self.btn_all_modality_hq.setFixedHeight(40)
        self.btn_all_modality_hq.setFixedWidth(140)
        self.btn_all_modality_hq.setVisible(False)
        
        # ⏸️ دکمه پوز
        self.btn_pause = QToolButton(controls)
        self.btn_pause.setProperty("role", "tool")
        self.btn_pause.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setIconSize(icon_sz)
        self.btn_pause.setFixedSize(30, 40)
        _set_icon(self.btn_pause, "pause.png", icon_sz.width(), "Pause/Resume Recording")
        self.btn_pause.setVisible(False)
        self.btn_pause.clicked.connect(self._toggle_pause_record)

        # ❌ دکمه کنسل
        self.btn_cancel = QToolButton(controls)
        self.btn_cancel.setProperty("role", "tool")
        self.btn_cancel.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setIconSize(icon_sz)
        self.btn_cancel.setFixedSize(30, 40)
        _set_icon(self.btn_cancel, "window_close.png", icon_sz.width(), "Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)

        # 📤 دکمه ارسال
        self.btn_send = QToolButton(controls)
        self.btn_send.setProperty("role", "tool")
        self.btn_send.setObjectName("send")
        self.btn_send.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setIconSize(icon_sz)
        self.btn_send.setFixedSize(30, 40)
        _set_icon(self.btn_send, "send.png", icon_sz.width(), "Send")
        self.btn_send.clicked.connect(self._emit_send)

        # ✅ ترتیب دکمه‌ها در layout
        ctl.addWidget(self.btn_plus, 0, Qt.AlignVCenter)
        ctl.addWidget(self.rec_panel, 1, Qt.AlignVCenter)
        ctl.addStretch(1)
        ctl.addWidget(self.btn_pause, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_cancel, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_mic, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_transcribe_quality, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_modality, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_all_modality_hq, 0, Qt.AlignVCenter)
        ctl.addWidget(self.btn_send, 0, Qt.AlignVCenter)

        shell.addWidget(tabs_bar, 0)
        shell.addWidget(self.nt_bar, 0) 
        shell.addWidget(self.corr_bar, 0)
        shell.addWidget(self.box, 1)
        shell.addWidget(controls, 0)

        # ---------- بیرونی ----------
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addWidget(self.input_shell, 0)
        self._apply_tab_styles()
        self.box.setPlainText(self._buf_standard)
        self._update_attach_width()

        # Force-create EN/PA buttons early
        QTimer.singleShot(0, self.install_lang_buttons)

    def get_normal_template_plain_text(self) -> str:
        """Normal Template را به متن خالص تبدیل می‌کند (برای ارسال به مدل‌ها).

        نکته: UI می‌تواند RichText/HTML داشته باشد (رنگ/فونت/...) اما برای مدل باید فقط متن برود.
        """
        try:
            html_or_text = (self.get_normal_template_text() or "").strip()
        except Exception:
            html_or_text = (getattr(self, "_buf_normal_template", "") or "").strip()

        if not html_or_text:
            return ""

        # اگر RichText باشد، به متن خالص تبدیل کن.
        try:
            if Qt.mightBeRichText(html_or_text):
                out = extract_plain_text_from_html(html_or_text)
            else:
                out = html_or_text
        except Exception:
            out = extract_plain_text_from_html(html_or_text)

        return (out or "").strip()


    # ---------- Correction helpers ----------
    def _on_corr_report_changed(self, idx: int):
        try:
            if idx <= 0:
                self.lbl_corr_info.setText("")
                return
            txt = self.cmb_corr_reports.currentText() or ""
            self.lbl_corr_info.setText(txt[:60])
        except Exception:
            pass

    def install_attachment_overlay(self, host: QWidget) -> None:
        """Make attach_frame a floating overlay on top of `host` (typically history.scroll.viewport()).
        نتیجه:
        - attach_frame دیگر در layout جا نمی‌گیرد و فضا اشغال نمی‌کند.
        - مثل یک لایه شیشه‌ای روی history قرار می‌گیرد و متن پشت آن قابل خواندن است.
        """
        if host is None:
            return
        self._attach_overlay_host = host
        try:
            self.attach_frame.setParent(host)
            self.attach_frame.raise_()  # keep usable (buttons/slider clickable)
        except Exception:
            pass
        self._reposition_attachment_overlay()

    def _reposition_attachment_overlay(self) -> None:
        """Position floating attach_frame at the bottom-right of the overlay host."""
        host = getattr(self, "_attach_overlay_host", None)
        if host is None:
            return

        try:
            if not self.attach_frame.isVisible():
                return

            m = int(getattr(self, "_attach_overlay_margin_px", 12))

            # make sure layout has computed children geometry
            try:
                lay = self.attach_frame.layout()
                if lay:
                    lay.activate()
            except Exception:
                pass

            try:
                self.attach_frame.adjustSize()
            except Exception:
                pass

            hint = self.attach_frame.sizeHint()
            hint_w = int(hint.width() or 0)
            hint_h = int(hint.height() or 0)

            avail_w = max(140, int(host.width()) - 2 * m)
            avail_h = max(60, int(host.height()) - 2 * m)

            if hint_w <= 0:
                hint_w = avail_w
            if hint_h <= 0:
                try:
                    hint_h = max(1, int(self.attach_frame.minimumSizeHint().height() or 1))
                except Exception:
                    hint_h = 60

            w = max(140, min(hint_w, avail_w))
            h = max(1, min(hint_h, avail_h))

            # ✅ قبلاً: x = m  (bottom-left)
            # ✅ حالا: bottom-right
            x = max(m, int(host.width()) - w - m)
            y = max(m, int(host.height()) - h - m)

            self.attach_frame.setFixedWidth(w)
            self.attach_frame.resize(w, h)
            self.attach_frame.move(x, y)
            self.attach_frame.raise_()
        except Exception:
            pass


    def clear_correction_reports(self):
        """Clears correction dropdown (usually when starting a fresh session)."""
        try:
            self._corr_reports = []
            self._corr_id_counter = 0
        except Exception:
            pass
        try:
            self.cmb_corr_reports.blockSignals(True)
            self.cmb_corr_reports.clear()
            self.cmb_corr_reports.addItem("Select report…")
            self.cmb_corr_reports.setCurrentIndex(0)
        finally:
            try:
                self.cmb_corr_reports.blockSignals(False)
            except Exception:
                pass
        try:
            self.lbl_corr_info.setText("")
        except Exception:
            pass

    def register_correction_report(self, report_text: str, label: str | None = None):
        """Add a report to Correction dropdown. report_text is the raw report (JSON-like or plain)."""
        report_text = (report_text or "").strip()
        if not report_text:
            return

        # Preserve current selection if possible
        try:
            prev = self.get_selected_correction_report_text()
        except Exception:
            prev = None

        # Make a short label if not provided
        if not label:
            t = report_text
            # Try JSON keys first
            m = re.search(r'"(?:Report Title|عنوان گزارش)"\s*:\s*"([^"]{1,120})"', t)
            if m:
                label = m.group(1).strip()
            else:
                # First non-empty line
                first_line = next((ln.strip() for ln in t.splitlines() if ln.strip()), "")
                label = first_line[:80] if first_line else None

        self._corr_id_counter = int(getattr(self, "_corr_id_counter", 0) or 0) + 1
        if not label:
            label = f"Report {self._corr_id_counter}"
        else:
            label = f"#{self._corr_id_counter} {label}" if not str(label).lstrip().startswith("#") else str(label)

        # Prevent duplicates (same report text)
        try:
            if any((rt == report_text) for _, rt in getattr(self, "_corr_reports", [])):
                return
        except Exception:
            pass

        try:
            self._corr_reports.append((label, report_text))
        except Exception:
            self._corr_reports = [(label, report_text)]

        # Update combo
        try:
            self.cmb_corr_reports.addItem(label, report_text)
            self.cmb_corr_reports.setCurrentIndex(self.cmb_corr_reports.count() - 1)
        except Exception:
            pass

        # Restore selection if user had one
        if prev:
            try:
                for i in range(1, self.cmb_corr_reports.count()):
                    if (self.cmb_corr_reports.itemData(i) or "").strip() == (prev or "").strip():
                        self.cmb_corr_reports.setCurrentIndex(i)
                        break
            except Exception:
                pass

    def get_selected_correction_report_text(self) -> str:
        try:
            if self.cmb_corr_reports.currentIndex() <= 0:
                return ""
            return (self.cmb_corr_reports.currentData() or "").strip()
        except Exception:
            return ""

    def _update_attach_width(self):
        try:
            max_w = int(getattr(self, "_chip_bar_max_w", 340) or 340)

            # اگر چیپی نداریم، همون max را اعمال کن
            target_w = max_w

            # اگر چیپ‌ها ساخته شده‌اند، عرض را بر اساس بزرگترین چیپ clamp کن
            if getattr(self, "_chips_layout", None) is not None:
                widest = 0
                for i in range(self._chips_layout.count()):
                    it = self._chips_layout.itemAt(i)
                    w = it.widget() if it else None
                    if w:
                        widest = max(widest, w.sizeHint().width())
                # +16 برای margin چپ/راست (۸+۸ در _ensure_chips_layout) :contentReference[oaicite:6]{index=6}
                target_w = min(max_w, max(220, widest + 16))

            self.attach_frame.setMinimumWidth(0)
            self.attach_frame.setMaximumWidth(target_w)

            # اسکرول هم دقیقاً همین عرض را بگیرد تا نوار واقعاً جمع شود
            if hasattr(self, "_chips_scroll") and self._chips_scroll:
                self._chips_scroll.setFixedWidth(target_w)

        except Exception:
            pass

    def get_last_image_attachment(self) -> str | None:
        """بازگرداندن مسیر آخرین تصویر پیوست‌شده (در صورت وجود)"""
        if not hasattr(self, "_image_attachments"):
            self._image_attachments = []
        if self._image_attachments:
            return self._image_attachments[-1]  
        return None

    def add_image_attachment(self, path: str) -> None:
        """
        Add an image attachment chip to the attach bar.
        (بدون override کردن max width، تا مثل قبل جمع‌وجور بماند)
        """
        import os
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QFontMetrics

        if not path:
            return

        if not hasattr(self, "_image_attachments"):
            self._image_attachments = []
        self._image_attachments.append(path)

        self._ensure_chips_layout()
        self.attach_frame.setVisible(True)

        chip = QFrame(self._chips_wrap)
        chip.setObjectName("imageChip")
        chip._img_path = path

        chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        lay = QHBoxLayout(chip)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)

        full_name = os.path.basename(path)
        root, ext = os.path.splitext(full_name)
        if len(full_name) > 18:
            short_name = (root[:3] + ".") + ext
        else:
            short_name = full_name

        lbl = QLabel(short_name)
        lbl.setObjectName("chipText")
        lbl.setToolTip(full_name)
        lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        max_text_w = 170
        fm = QFontMetrics(lbl.font())
        lbl.setText(fm.elidedText(lbl.text(), Qt.ElideRight, max_text_w))
        lbl.setMaximumWidth(max_text_w)

        lay.addWidget(lbl)

        btn_preview = QToolButton(chip)
        btn_preview.setObjectName("chipAction")
        btn_preview.setText("👁")
        btn_preview.setToolTip("Preview image")
        btn_preview.setFixedSize(26, 22)
        btn_preview.clicked.connect(lambda _=False, p=path: self._preview_image(p))
        lay.addWidget(btn_preview)

        btn_remove = QToolButton(chip)
        btn_remove.setObjectName("chipClose")
        btn_remove.setText("✕")
        btn_remove.setToolTip("Remove image")
        btn_remove.setFixedSize(26, 22)
        btn_remove.clicked.connect(lambda _=False, c=chip: self._remove_image_chip(c))
        lay.addWidget(btn_remove)

        max_bar_w = int(getattr(self, "_chip_bar_max_w", 340) or 340)
        chip.setMaximumWidth(min(max_text_w + 26 + 26 + 6 + 6 + 18, max(220, max_bar_w - 16)))

        self._chips_layout.addWidget(chip, 0, Qt.AlignTop | Qt.AlignLeft)

        try:
            self._update_attach_width()
        except Exception:
            pass

        QTimer.singleShot(0, self._reposition_attachment_overlay)

    def _preview_image(self, path: str) -> None:

        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt

        if not path or not os.path.exists(path):
            # You can replace this with a toast / message box if desired
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(os.path.basename(path))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(container)

        label = QLabel(container)
        label.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(label)

        ext = os.path.splitext(path)[1].lower()
        if ext == ".dcm":
            # For DICOM we just inform the user
            label.setText(
                "DICOM preview is not available in this window.\n"
                "Please use the PACS viewer to inspect this study."
            )
        else:
            pix = QPixmap(path)
            if pix.isNull():
                label.setText("Cannot load image for preview.")
            else:
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    g = screen.availableGeometry()
                    max_w = min(900, g.width() - 100) if g.width() > 0 else 900
                    max_h = min(900, g.height() - 100) if g.height() > 0 else 900
                else:
                    max_w = max_h = 900

                scaled = pix.scaled(
                    max_w,
                    max_h,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                label.setPixmap(scaled)

        dlg.resize(800, 600)
        dlg.exec()


    def get_all_image_attachments(self) -> list[str]:
        """همه‌ی مسیرهای تصویرهای attach شده را برمی‌گرداند."""
        if not hasattr(self, "_image_attachments"):
            self._image_attachments = []
        return list(self._image_attachments)

    def clear_image_attachments(self):
        """پاک کردن فقط چیپ‌های تصویر و خالی‌کردن لیست مسیرها."""
        if hasattr(self, "_image_attachments"):
            self._image_attachments.clear()

        if hasattr(self, "_chips_layout"):
            # فقط چیپ‌های imageChip را پاک کن، voiceChip ها بمانند
            for i in reversed(range(self._chips_layout.count())):
                item = self._chips_layout.itemAt(i)
                w = item.widget() if item else None
                if w is not None and w.objectName() == "imageChip":
                    self._chips_layout.removeWidget(w)
                    w.deleteLater()

            # اگر دیگر هیچ چیپی نیست، نوار Attach را ببند
            if self._chips_layout.count() == 0:
                self.attach_frame.setVisible(False)
    def _mime_has_image(self, mime: QMimeData) -> bool:
        """چک می‌کند آیا QMimeData شامل تصویر (مستقیم یا فایل تصویر) است یا نه."""
        if mime is None:
            return False

        # مستقیم تصویر (copy از Snipping Tool, Photoshop و غیره)
        if mime.hasImage():
            return True

        # فایل‌ها (drag & drop از Explorer / Desktop)
        if mime.hasUrls():
            image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".dcm"}

            for url in mime.urls():
                path = url.toLocalFile()
                if not path:
                    continue
                ext = os.path.splitext(path)[1].lower()
                if ext in image_exts:
                    return True
        return False

    def _save_image_from_mime(self, mime: QMimeData) -> list[str]:
        """
        عکس موجود در mime را به فایل موقت ذخیره می‌کند و مسیرها را برمی‌گرداند.
        هم imageData مستقیم و هم لیست فایل‌های تصویر را پشتیبانی می‌کند.
        """
        from PySide6.QtGui import QImage, QPixmap
        import tempfile, time

        saved_paths: list[str] = []

        # ۱) imageData مستقیم
        if mime.hasImage():
            img = mime.imageData()
            qimg = None
            if isinstance(img, QImage):
                qimg = img
            elif isinstance(img, QPixmap):
                qimg = img.toImage()

            if qimg is not None and not qimg.isNull():
                tmp_dir = tempfile.gettempdir()
                filename = f"pacs_clip_{int(time.time() * 1000)}.png"
                path = os.path.join(tmp_dir, filename)
                if qimg.save(path, "PNG"):
                    saved_paths.append(path)

        # ۲) فایل‌های لوکال که تصویر هستند (drag & drop از Explorer / Desktop)
        if mime.hasUrls():
            image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".dcm"}
            for url in mime.urls():
                path = url.toLocalFile()
                if not path:
                    continue
                ext = os.path.splitext(path)[1].lower()
                if ext in image_exts:
                    saved_paths.append(path)

        return saved_paths

    def _apply_box_direction(self):
        cur = (self.box.toPlainText() or "")
        tab = getattr(self, "_active_tab", "transcribe")
        if tab == "standard":
            is_rtl = (getattr(self, "_std_lang", "pa") == "pa")
        else:
            is_rtl = MessageBubble._has_rtl_chars(cur)  # ← شامل normal_template شود

        direction = Qt.RightToLeft if is_rtl else Qt.LeftToRight
        self.box.setLayoutDirection(direction)
        try:
            opt = self.box.document().defaultTextOption()
            opt.setTextDirection(direction)
            opt.setAlignment(Qt.AlignRight if is_rtl else Qt.AlignLeft)
            self.box.document().setDefaultTextOption(opt)
        except Exception:
            pass
        
    def _handle_mime_as_image_attachments(self, mime: QMimeData) -> bool:
        """
        اگر mime شامل تصویر باشد، آن را به عنوان image attachment اضافه می‌کند.
        خروجی: True اگر حداقل یک تصویر attach شد.
        """
        if not self._mime_has_image(mime):
            return False

        for path in self._save_image_from_mime(mime):
            self.add_image_attachment(path)

        return True

    def _handle_clipboard_paste(self) -> bool:
        """
        تلاش می‌کند تصویر موجود در کلیپ‌بورد را به attachها اضافه کند.
        اگر موفق شد → True (و paste متن پیش‌فرض را بلاک می‌کنیم).
        """
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()
        return self._handle_mime_as_image_attachments(mime)



    def eventFilter(self, obj, ev):
        """
        هندل کردن:
        - Enter بدون Shift → Send
        - Ctrl+V / Paste → اگر تصویر بود به‌صورت attachment، نه متن
        - Drag & Drop تصویر → به‌صورت attachment، نه آدرس در باکس
        روی خود box و viewport داخلی‌اش.
        """
        # target viewport (برای drag/drop)
        viewport = None
        try:
            viewport = self.box.viewport()
        except Exception:
            viewport = None

        if obj is self.box or obj is viewport:
            et = ev.type()

            # -------------------------------
            # 1) KeyPress روی خود box
            # -------------------------------
            if et == QEvent.KeyPress and obj is self.box:
                # Ctrl+V → سعی کن تصویر از کلیپ‌بورد به attachment تبدیل شود
                if ev.key() == Qt.Key_V and (ev.modifiers() & Qt.ControlModifier):
                    if self._handle_clipboard_paste():
                        return True  # نذار QPlainTextEdit متن/آدرس را paste کند

                # Enter بدون Shift → send
                if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
                    self._emit_send()
                    return True


            if et == QEvent.Paste:
                if self._handle_clipboard_paste():
                    return True 

            if et in (QEvent.DragEnter, QEvent.DragMove):
                mime = ev.mimeData()
                if self._mime_has_image(mime):
                    ev.acceptProposedAction()
                    return True 

            elif et == QEvent.Drop:
                mime = ev.mimeData()
                if self._handle_mime_as_image_attachments(mime):
                    ev.acceptProposedAction()
                    return True

        # بقیه‌ی رویدادها را عادی بده به والد
        return super().eventFilter(obj, ev)

    def _remove_image_chip(self, chip):
        path_to_remove = getattr(chip, "_img_path", None)
        if path_to_remove and hasattr(self, "_image_attachments"):
            if path_to_remove in self._image_attachments:
                self._image_attachments.remove(path_to_remove)
        chip.deleteLater()
        if self._chips_layout.count() == 0:
            self.attach_frame.setVisible(False)

    # ---------- helpers for voice chips ----------

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        ms = max(0, int(ms))
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    def _find_chip_for_path(self, path: str | None):
        """بر اساس مسیر فایل، خودِ چیپ (QFrame) را پیدا می‌کند."""
        if not path or not hasattr(self, "_chips_layout"):
            return None
        for i in range(self._chips_layout.count()):
            item = self._chips_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and getattr(w, "_voice_path", None) == path:
                return w
        return None

    def _on_chip_duration(self, d: int):
        """وقتی duration صدا مشخص شد، رنج اسلایدر و تایمر چیپ جاری را ست می‌کنیم."""
        try:
            dur = int(d)
        except Exception:
            dur = 0
        self._chip_duration_ms = dur

        chip = self._find_chip_for_path(self._chip_playing_path)
        if not chip:
            return

        slider = getattr(chip, "_slider", None)
        lbl = getattr(chip, "_time_lbl", None)
        if slider is not None:
            slider.setRange(0, dur)
        if lbl is not None:
            # فعلاً مدت کل فایل را نشان می‌دهیم
            lbl.setText(self._fmt_ms(dur))


    def _handle_standard_tab_click(self):
        """Switch to Standard tab.

        IMPORTANT UX RULE:
        - If the current source text was already standardized once, do NOT re-run
          standardization just because user switched tabs.
        - Re-run only when source text changed, or when user presses the explicit
          retry (⟳) button next to Standard.
        """
        if self._maybe_standardize(force=False):
            return  # wait for result
        self.switch_tab("standard")

    def _handle_standard_retry_click(self):
        """Explicit retry requested by user (⟳)."""
        # Even if already on Standard, retry should re-run using latest source text.
        self._maybe_standardize(force=True)

    # ---------- Standardization cache helpers ----------
    @staticmethod
    def _hash_text_for_standardize(text: str) -> str:
        import hashlib
        s = (text or "").strip().encode("utf-8", errors="ignore")
        return hashlib.sha1(s).hexdigest()

    def _standardize_source_text(self) -> str:
        """Choose which text should be standardized.

        - If user is on Normal Template tab: standardize transcript, not template.
        - If user is on Transcribe tab: standardize what's currently in the box.
        - If user is on Standard tab: standardize last known source (fallback to transcript).
        """
        if self._active_tab == "normal_template":
            return (self._buf_transcribe or "").strip()
        if self._active_tab == "transcribe":
            return (self.box.toPlainText() or "").strip()
        # active standard
        return (self._std_last_source_text or self._buf_transcribe or "").strip()

    def _maybe_standardize(self, *, force: bool) -> bool:
        """Starts standardization if needed.

        Returns True if a standardization request was emitted.
        """
        # If a standardization request is already in-flight, don't enqueue another.
        if getattr(self, "_std_pending_source_hash", None) and not force:
            return True

        src = self._standardize_source_text()
        if not src:
            # Nothing to standardize; just show whatever standard tab has.
            if not force:
                return False
            return False

        h = self._hash_text_for_standardize(src)

        # If not forced: avoid re-running when already standardized for same source.
        if (not force) and self._is_standardized and self._std_source_hash and self._std_source_hash == h:
            return False

        # If we don't have a source hash (e.g., loaded from disk), still avoid
        # re-running on mere tab switches; require force OR text change (we don't
        # know baseline) => fall back to "force only".
        if (not force) and self._is_standardized and not self._std_source_hash:
            return False

        # Emit request and remember what it was for.
        self._std_pending_source_hash = h
        self._std_pending_source_text = src
        self._std_last_source_text = src
        self.standardizeClicked.emit(src)
        return True

    def _show_transcribe_quality_menu(self):
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
        """)
        
        high_act = QAction("Clear Voice", menu)
        low_act = QAction("Noisy Voice", menu)
        
        high_act.triggered.connect(lambda: self._set_transcribe_quality("clear"))
        low_act.triggered.connect(lambda: self._set_transcribe_quality("noisy"))
        
        menu.addAction(high_act)
        menu.addAction(low_act)
        
        menu.exec(self.btn_transcribe_quality.mapToGlobal(
            self.btn_transcribe_quality.rect().bottomLeft()
        ))
        
    def _set_transcribe_quality(self, mode: str):
        self._transcribe_quality_mode = mode
        label = "Clear Voice" if mode == "clear" else "Noisy Voice"
        self.btn_transcribe_quality.setText(label)

    def _toggle_pause_record(self):
        if not self._rec_running:
            return
        self._rec_paused = not self._rec_paused
        if self._rec_paused:
            self._rec_timer.stop()
            self._apply_pause_icon(True)
        else:
            self._rec_timer.start(100)
            self._apply_pause_icon(False)

    def _apply_pause_icon(self, is_paused: bool):
        if is_paused:
            _set_icon(self.btn_pause, "play.png", 20, "Resume recording")  # Play icon when paused
            self.btn_pause.setToolTip("Resume recording")
        else:
            _set_icon(self.btn_pause, "pause.png", 20, "Pause recording")  # Pause icon when playing
            self.btn_pause.setToolTip("Pause recording")
        self.btn_pause.setVisible(True)
        QTimer.singleShot(0, self._reposition_attachment_overlay)
    def _on_chip_position(self, pos: int):
        """آپدیت اسلایدر و تایمر برای فایل در حال پخش."""
        chip = self._find_chip_for_path(self._chip_playing_path)
        if not chip:
            return

        slider = getattr(chip, "_slider", None)
        lbl = getattr(chip, "_time_lbl", None)
        user_seeking = getattr(chip, "_user_seeking", False)

        if slider is not None and not user_seeking:
            try:
                slider.setValue(int(pos))
            except Exception:
                pass

        # اگر کاربر در حال درَگ‌کردن است، تایمر در _on_chip_slider_moved آپدیت می‌شود
        if lbl is not None and not user_seeking:
            # در صورت تمایل این‌جا می‌توانی elapsed را نمایش دهی
            # فعلاً همون elapsed:
            lbl.setText(self._fmt_ms(int(pos)))

    def _on_chip_slider_released(self, chip):
        """بعد از رها کردن اسلایدر، پوزیشن پلیر تنظیم می‌شود."""
        if not chip:
            return
        chip._user_seeking = False
        if self._chip_playing_path and getattr(chip, "_voice_path", None) == self._chip_playing_path:
            slider = getattr(chip, "_slider", None)
            if slider is not None:
                try:
                    self._chip_player.setPosition(slider.value())
                except Exception:
                    pass

    def _on_chip_slider_moved(self, chip, val: int):
        """حین درَگ‌کردن، فقط تایمر چیپ را آپدیت می‌کنیم (بدون تغییر پلیر)."""
        if not chip:
            return
        chip._user_seeking = True
        lbl = getattr(chip, "_time_lbl", None)
        if lbl is not None:
            lbl.setText(self._fmt_ms(int(val)))


    def _on_chip_slider_pressed_for(self, slider: ClickToSeekSlider):
        """شروع Seek روی اسلایدر چیپ فعلی."""
        if slider is not self._chip_active_slider:
            return
        self._chip_user_seeking = True

    def _on_chip_slider_released_for(self, slider: ClickToSeekSlider):
        """پایان Seek → جابه‌جایی پلیر به پوزیشن جدید."""
        if slider is not self._chip_active_slider:
            return
        self._chip_user_seeking = False
        try:
            self._chip_player.setPosition(slider.value())
        except Exception:
            pass

    def _on_chip_slider_moved_for(self, slider: ClickToSeekSlider, lbl: QLabel, val: int):
        """در حین Seek متن تایمر را به موقعیت جدید بروزرسانی می‌کند."""
        if slider is not self._chip_active_slider:
            return
        if not self._chip_user_seeking:
            return
        lbl.setText(self._fmt_ms(int(val)))



    # ---------- public helpers ----------
    def set_enabled(self, en: bool):
        self.btn_plus.setEnabled(en);
        self.btn_mic.setEnabled(en);
        self.btn_send.setEnabled(en);
        self.box.setEnabled(en)
        try:
            self.btn_all_modality_hq.setEnabled(en)
        except Exception:
            pass
        # cancel در هنگام ترنسکرایب از بیرون کنترل می‌شود

    def append_text(self, more: str):
        if not more:
            return
        cur = self.box.toPlainText()
        new_text = (cur + ("\n" if cur else "") + more).strip()
        self.box.setPlainText(new_text)
        c = self.box.textCursor()
        c.movePosition(QTextCursor.End)
        self.box.setTextCursor(c)
        # NEW: invalidate standardization
        self._is_standardized = False  # ← ADD THIS
        if self._active_tab == "standard":
            self._buf_standard = new_text
        elif self._active_tab == "normal_template":
            self._buf_normal_template = new_text
        elif self._active_tab == "correction":
            self._buf_correction = new_text
        else:
            self._buf_transcribe = new_text

    # ---------- Tabs helpers (NEW) ----------
    def switch_tab(self, tab: str):
        if tab not in ("standard", "transcribe", "normal_template", "correction") or tab == self._active_tab:
            self._update_lang_buttons_visibility()
            return

        # -----------------------------
        # 1) Save current tab text
        # -----------------------------
        if self._active_tab == "normal_template":
            # QTextEdit.toHtml() returns an HTML skeleton even when empty → treat as empty.
            try:
                plain = (self.box.toPlainText() or "").strip()
                if not plain:
                    current_text = ""
                else:
                    current_text = self.box.toHtml()
                    if self._nt_html_is_effectively_empty(current_text):
                        current_text = ""
            except Exception:
                current_text = (self.box.toPlainText() or "").strip()
        else:
            current_text = (self.box.toPlainText() or "")

        if self._active_tab == "standard":
            try:
                if getattr(self, "_std_lang", "pa") == "en":
                    self._std_lang_texts["en"] = current_text
                else:
                    self._std_lang_texts["fa"] = current_text
            except Exception:
                pass
            self._buf_standard = current_text

        elif self._active_tab == "transcribe":
            self._buf_transcribe = current_text

        elif self._active_tab == "normal_template":
            self._buf_normal_template = current_text

        elif self._active_tab == "correction":
            self._buf_correction = current_text

        # -----------------------------
        # 2) Switch active tab
        # -----------------------------
        self._active_tab = tab

        # toolbars visibility
        try:
            self.nt_bar.setVisible(tab == "normal_template")
        except Exception:
            pass
        try:
            self.corr_bar.setVisible(tab == "correction")
        except Exception:
            pass

        # keep height stable
        self._sync_composer_heights_for_tab(tab)

        # -----------------------------
        # 3) Load new tab text into editor
        # -----------------------------
        if tab == "standard":
            try:
                if getattr(self, "_std_lang", "pa") == "en":
                    txt = self._std_lang_texts.get("en", "") or self._buf_standard or ""
                else:
                    txt = self._std_lang_texts.get("fa", "") or self._buf_standard or ""
            except Exception:
                txt = self._buf_standard or ""
            self.box.setPlainText(txt)

        elif tab == "transcribe":
            self.box.setPlainText(self._buf_transcribe or "")

        elif tab == "normal_template":
            nt = self._buf_normal_template or ""
            try:
                if nt and Qt.mightBeRichText(nt):
                    self.box.setHtml(nt)
                else:
                    self.box.setPlainText(nt)
            except Exception:
                self.box.setPlainText(nt)

        elif tab == "correction":
            self.box.setPlainText(self._buf_correction or "")

        # placeholder text per tab
        try:
            if tab == "standard":
                self.box.setPlaceholderText(getattr(self, "_ph_standard", "Standardized text…"))
            elif tab == "transcribe":
                self.box.setPlaceholderText(getattr(self, "_ph_transcribe", "Write/paste report text"))
            elif tab == "normal_template":
                self.box.setPlaceholderText(getattr(self, "_ph_normal_template", "Normal Template (optional)…"))
            else:
                self.box.setPlaceholderText(getattr(self, "_ph_correction", "Write correction notes…"))
        except Exception:
            pass

        self._update_lang_buttons_visibility()

        # ✅ FIX: entering Correction must refresh dropdown once (if empty)
        if tab == "correction":
            try:
                QTimer.singleShot(0, self._request_parent_refresh_correction_reports)
            except Exception:
                # fallback (no timer)
                try:
                    self._request_parent_refresh_correction_reports()
                except Exception:
                    pass

    def _request_parent_refresh_correction_reports(self):
        """
        وقتی برای اولین بار وارد Correction می‌شویم و dropdown خالی است،
        از parent page می‌خواهیم از DB ریپورت‌ها را بارگذاری کند.
        """
        try:
            cmb = getattr(self, "cmb_corr_reports", None)
            if cmb is not None and cmb.count() > 1:
                return  # already has reports
        except Exception:
            pass

        p = self.parent()
        for _ in range(16):
            if p is None:
                break
            fn = getattr(p, "_refresh_correction_reports_dropdown", None)
            if callable(fn):
                fn()
                return
            p = p.parent()



    def install_lang_buttons(self):
        if hasattr(self, "btn_lang_en"):
            return
        controls = self.input_shell.findChild(QFrame, "controls")
        if not controls or not controls.layout():
            return
        lay = controls.layout()
        # وضعیت زبان انتخاب‌شده برای استاندارد (pa = فارسی)
        self._std_lang = "pa" # پیش‌فرض فارسی
        self._std_lang_texts = {"en": "", "fa": ""} # دو بافر جدا
        # دکمه انگلیسی
        self.btn_lang_en = QToolButton(controls)
        self.btn_lang_en.setText("En")
        self.btn_lang_en.setProperty("role", "tool")
        self.btn_lang_en.setMinimumWidth(44)
        self.btn_lang_en.setCursor(Qt.PointingHandCursor)
        self.btn_lang_en.clicked.connect(lambda: self._switch_std_lang("en"))
        # دکمه فارسی
        self.btn_lang_pa = QToolButton(controls)
        self.btn_lang_pa.setText("فا")  # تغییر به "فا"
        self.btn_lang_pa.setProperty("role", "tool")
        self.btn_lang_pa.setMinimumWidth(44)
        self.btn_lang_pa.setCursor(Qt.PointingHandCursor)
        self.btn_lang_pa.clicked.connect(lambda: self._switch_std_lang("pa"))
        css = """
            QToolButton[role="tool"] {
                font-weight:600; color:#ddd; border:1px solid #444;
                border-radius:8px; padding:2px 8px;
            }
            QToolButton[role="tool"][active="true"] {
                background:#505050; color:#ffd48a; border-color:#ffd48a;
                font-weight:700;
            }
        """
        self.btn_lang_en.setStyleSheet(css)
        self.btn_lang_pa.setStyleSheet(css)
        # قرار دادن قبل از دکمه Send (مثل قبل)
        lay.insertWidget(lay.count()-3, self.btn_lang_en) # قبل از btn_std
        lay.insertWidget(lay.count()-3, self.btn_lang_pa)
        # همیشه وقتی تب standard است، دکمه‌ها دیده شوند
        self._update_lang_buttons_visibility()
        # Style for language buttons
        css = """
            QToolButton[lang='btn'] {
                font-weight: 600;
                color: #ddd;
            }
            QToolButton[lang='btn'][active='true'] {
                border-color: #ffd48a;
                background: #505050;
                font-weight: 700;
                color: #ffd48a;
            }
        """
        self.btn_lang_en.setStyleSheet(css)
        self.btn_lang_pa.setStyleSheet(css)
        # Insert buttons next to [+] button (indices 1 and 2)
        lay.insertWidget(1, self.btn_lang_en, 0, Qt.AlignVCenter)
        lay.insertWidget(2, self.btn_lang_pa, 0, Qt.AlignVCenter)
        # Apply initial styles
        self._apply_lang_styles()
    
    def _switch_std_lang(self, code: str):
        """
        سوییچ بین En و PA.
        
        ⚠️ CRITICAL: فقط در صورتی متن فعلی را ذخیره می‌کنیم که:
        1. کاربر دستی تایپ کرده باشد (متن با بافر ذخیره‌شده فرق داشته باشد)
        2. یا بافر هدف خالی باشد و متن فعلی پر باشد
        
        این مانع از پاک شدن نتایج استانداردسازی هنگام سوییچ می‌شود.
        """
        if code not in ("en", "pa"):
            return
        if self._std_lang == code:
            return

        # 1. بررسی نیاز به ذخیره متن فعلی
        if self._active_tab == "standard":
            current_text = self.box.toPlainText().strip()
            current_lang_key = "fa" if self._std_lang == "pa" else "en"
            stored_text = self._std_lang_texts.get(current_lang_key, "").strip()
            
            # ✅ فقط اگر متن تغییر کرده باشد، ذخیره کن
            # این مانع از پاک شدن بافر زبان دیگر می‌شود
            if current_text and current_text != stored_text:
                self._std_lang_texts[current_lang_key] = current_text
                print(f"[LANG-SWITCH] Saved modified text to '{current_lang_key}': {len(current_text)} chars")
            else:
                print(f"[LANG-SWITCH] No save needed - text unchanged for '{current_lang_key}'")

        # 2. زبان جدید را فعال کن
        old_lang = self._std_lang
        self._std_lang = code
        self._apply_lang_button_styles()
        
        print(f"[LANG-SWITCH] Switching from '{old_lang}' to '{code}'")
        print(f"[LANG-SWITCH] Stored EN: {len(self._std_lang_texts.get('en', ''))} chars")
        print(f"[LANG-SWITCH] Stored FA: {len(self._std_lang_texts.get('fa', ''))} chars")

        # 3. ✅ متن زبان جدید را نمایش بده
        if self._active_tab == "standard":
            display_text = self._std_lang_texts["fa"] if code == "pa" else self._std_lang_texts["en"]
            self.box.setPlainText(display_text or "")
            self._apply_box_direction()
            print(f"[LANG-SWITCH] Displaying text: {len(display_text)} chars")
            
            # کرسور به انتها
            cursor = self.box.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.box.setTextCursor(cursor)
                    
    def _apply_lang_button_styles(self):
        self.btn_lang_en.setProperty("active", "true" if self._std_lang == "en" else "false")
        self.btn_lang_pa.setProperty("active", "true" if self._std_lang == "pa" else "false")
        self.btn_lang_en.style().polish(self.btn_lang_en)
        self.btn_lang_pa.style().polish(self.btn_lang_pa)

    def _update_lang_buttons_visibility(self):
        show = (self._active_tab == "standard")
        self.btn_lang_en.setVisible(show)
        self.btn_lang_pa.setVisible(show)
        if show:
            self._apply_lang_button_styles()
            
    def _apply_lang_styles(self):
        """Highlight active language button. 'pa' maps to fa internally."""
        for btn, code in ((getattr(self, "btn_lang_en", None), "en"),
                          (getattr(self, "btn_lang_pa", None), "pa")):
            if not btn:
                continue
            btn.setProperty("active", str(self._std_lang == code).lower())
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_lang_clicked(self, code: str):
        if code not in ("en", "pa"):
            return
    
        self._std_lang = code
        self._apply_lang_styles()
        # If we're on the standard tab, immediately switch to show the selected language
        if self.get_active_tab() == "standard":
            if code == "pa":
                txt = (self._std_lang_texts.get("fa") or "هیچ متن فارسی موجود نیست.").strip()
            else:
                txt = (self._std_lang_texts.get("en") or "No English text available.").strip()
        
            # Only update if we have text, otherwise keep current content
            if txt:
                self.set_tab_text("standard", txt)
                            
    def set_standard_result(self, en_text: str | None = None, fa_text: str | None = None):
        """
        Stores both English and Persian standardized texts and ensures they're
        immediately available for toggling via language buttons.
        Always switches to the 'standard' tab and displays the appropriate language.
        """
        # Normalize inputs to empty strings if None
        en_text = (en_text or "").strip()
        fa_text = (fa_text or "").strip()

        # Ensure language buttons exist
        self.install_lang_buttons()

        self._std_lang_texts["en"] = en_text
        self._std_lang_texts["fa"] = fa_text


        try:
            self._is_standardized = True
            if getattr(self, "_std_pending_source_hash", None):
                self._std_source_hash = self._std_pending_source_hash
            elif not getattr(self, "_std_source_hash", None):
                # best-effort: tie to current transcript buffer (helps when loading from disk)
                src_guess = (getattr(self, "_std_pending_source_text", None) or self._buf_transcribe or "").strip()
                if src_guess:
                    self._std_source_hash = self._hash_text_for_standardize(src_guess)
            if getattr(self, "_std_pending_source_text", None):
                self._std_last_source_text = self._std_pending_source_text or self._std_last_source_text
        finally:
            # clear pending markers
            self._std_pending_source_hash = None
            self._std_pending_source_text = None

        # Debug logging
        print(f"\n{'='*80}")
        print("[COMPOSER-SET] set_standard_result called")
        print(f"{'='*80}")
        print(f"[COMPOSER-SET] Input EN text: {len(en_text)} chars")
        print(f"[COMPOSER-SET] Input FA text: {len(fa_text)} chars")
        print(f"[COMPOSER-SET] Stored EN: {len(self._std_lang_texts['en'])} chars")
        print(f"[COMPOSER-SET] Stored FA: {len(self._std_lang_texts['fa'])} chars")
        
        # ✅ نمایش محتوای واقعی برای دیباگ
        if en_text:
            print(f"[COMPOSER-SET] EN content preview: {en_text[:60]}...")
        if fa_text:
            print(f"[COMPOSER-SET] FA content preview: {fa_text[:60]}...")

        # Always switch to 'standard' tab so user sees the result
        if self._active_tab != "standard":
            print(f"[COMPOSER-SET] Switching from '{self._active_tab}' to 'standard'")
            self.switch_tab("standard")
        else:
            print(f"[COMPOSER-SET] Already on 'standard' tab")

        # ✅ Auto-select language: Persian if available, otherwise English
        if fa_text:
            print(f"[COMPOSER-SET] Auto-selecting Persian (FA text available)")
            self._switch_std_lang("pa")  # 'pa' = Persian
        elif en_text:
            print(f"[COMPOSER-SET] Auto-selecting English (EN text available, FA empty)")
            self._switch_std_lang("en")
        else:
            print(f"[COMPOSER-SET] No text available for either language")
            # Neither text is available — keep current language but show empty
            if self._active_tab == "standard":
                txt = self._std_lang_texts["fa"] if self._std_lang == "pa" else self._std_lang_texts["en"]
                self.box.setPlainText(txt or "")
                cur = self.box.textCursor()
                cur.movePosition(QTextCursor.End)
                self.box.setTextCursor(cur)

        # ✅ Ensure language buttons are visible and styled correctly
        self._update_lang_buttons_visibility()
        self._apply_lang_button_styles()
        self._apply_box_direction()

        print(f"[COMPOSER-SET] Final state:")
        print(f" - Active tab: {self._active_tab}")
        print(f" - Current lang: {self._std_lang}")
        print(f" - EN buffer: {len(self._std_lang_texts.get('en', ''))} chars")
        print(f" - FA buffer: {len(self._std_lang_texts.get('fa', ''))} chars")
        print(f" - Displayed text: {len(self.box.toPlainText())} chars")
        print(f"[COMPOSER-SET] ✅ Language and tab updated")
        print(f"{'='*80}\n")


    def _apply_tab_styles(self):
        """Visual on/off for tabs (attribute 'active' used in stylesheet)."""
        self.btn_tab_standard.setProperty("active", str(self._active_tab == "standard").lower())
        self.btn_tab_trans.setProperty("active", str(self._active_tab == "transcribe").lower())
        try:
            self.btn_tab_normal.setProperty("active", str(self._active_tab == "normal_template").lower())
        except Exception:
            pass

        try:
            self.btn_tab_correction.setProperty("active", str(self._active_tab == "correction").lower())
        except Exception:
            pass

        # ریفرش استایل
        for b in (self.btn_tab_standard, self.btn_tab_trans, getattr(self, "btn_tab_normal", None), getattr(self, "btn_tab_correction", None)):
            if not b:
                continue
            b.style().unpolish(b)
            b.style().polish(b)


    def _sync_composer_heights_for_tab(self, tab: str | None = None) -> None:
        """
        Keeps the overall input area height stable across tabs.
        Normal Template / Correction tabs show a toolbar (nt_bar / corr_bar),
        so we reduce editor max-height by the same amount.
        """
        try:
            tab = tab or getattr(self, "_active_tab", "transcribe")
            base = int(getattr(self, "_composer_box_max_h", 140) or 140)
            nt_h = int(getattr(self, "_nt_bar_fixed_h", 0) or 0)
            corr_h = int(getattr(self, "_corr_bar_fixed_h", 0) or 0)

            if tab == "normal_template" and nt_h > 0:
                self.box.setMaximumHeight(max(90, base - nt_h))
            elif tab == "correction" and corr_h > 0:
                self.box.setMaximumHeight(max(90, base - corr_h))
            else:
                self.box.setMaximumHeight(base)

            self.box.updateGeometry()
        except Exception:
            pass

    def get_active_tab(self) -> str:
        """Returns 'standard' or 'transcribe'."""
        return self._active_tab

    def get_tab_texts(self) -> tuple[str, str]:
        """(standard_text, transcribe_text) — backward compatible."""
        cur = self.box.toPlainText()
        if self._active_tab == "standard":
            self._buf_standard = cur
        elif self._active_tab == "transcribe":
            self._buf_transcribe = cur
        elif self._active_tab == "normal_template":
            self._buf_normal_template = cur
        elif self._active_tab == "correction":
            self._buf_correction = cur
        return self._buf_standard, self._buf_transcribe


    def get_tab_text(self, tab: str) -> str:
        """
        Return the current buffer for a specific tab (standard/transcribe/normal_template/correction).
        Always syncs the currently active editor content into its corresponding buffer first.

        This fixes cases where callers incorrectly used get_tab_texts() (which only returns
        (standard, transcribe)) for Correction.
        """
        try:
            active = getattr(self, "_active_tab", "transcribe")

            # --- sync active editor into its own buffer ---
            if active == "normal_template":
                # keep HTML semantics for normal_template
                try:
                    _ = self.get_normal_template_text()  # updates _buf_normal_template safely
                except Exception:
                    self._buf_normal_template = (self.box.toPlainText() or "")
            else:
                cur = (self.box.toPlainText() or "")
                if active == "standard":
                    # keep per-language buffers consistent
                    try:
                        if getattr(self, "_std_lang", "pa") == "en":
                            self._std_lang_texts["en"] = cur
                        else:
                            self._std_lang_texts["fa"] = cur
                    except Exception:
                        pass
                    self._buf_standard = cur
                elif active == "transcribe":
                    self._buf_transcribe = cur
                elif active == "correction":
                    self._buf_correction = cur
        except Exception:
            pass

        # --- return requested tab buffer ---
        if tab == "standard":
            return getattr(self, "_buf_standard", "") or ""
        if tab == "transcribe":
            return getattr(self, "_buf_transcribe", "") or ""
        if tab == "correction":
            return getattr(self, "_buf_correction", "") or ""
        if tab == "normal_template":
            try:
                return self.get_normal_template_text() or ""
            except Exception:
                return getattr(self, "_buf_normal_template", "") or ""
        return ""


    def set_tab_text(self, tab: str, text: str):
        """Set text buffer of a tab; if it's current tab, update box too."""
        if tab == "standard":
            self._buf_standard = text or ""
            # keep lang buffers consistent if possible
            try:
                if getattr(self, "_std_lang", "pa") == "pa":
                    self._std_lang_texts["fa"] = self._buf_standard
                else:
                    self._std_lang_texts["en"] = self._buf_standard
            except Exception:
                pass
            if self._active_tab == "standard":
                self.box.setPlainText(self._buf_standard)
        elif tab == "transcribe":
            self._buf_transcribe = text or ""

            # If we already have a standardized result but cache hash is unknown
            # (e.g., loaded from disk before transcribe text was set), bind it now.
            if getattr(self, "_is_standardized", False) and not getattr(self, "_std_source_hash", None):
                try:
                    src = (self._buf_transcribe or "").strip()
                    if src:
                        self._std_source_hash = self._hash_text_for_standardize(src)
                        self._std_last_source_text = src
                except Exception:
                    pass

            if self._active_tab == "transcribe":
                self.box.setPlainText(self._buf_transcribe)
        elif tab == "correction":
            self._buf_correction = text or ""
            if self._active_tab == "correction":
                self.box.setPlainText(self._buf_correction)
        elif tab == "normal_template":
            self._buf_normal_template = text or ""
            if self._active_tab == "normal_template":
                self.box.setPlainText(self._buf_normal_template)

    def _nt_html_is_effectively_empty(self, html: str) -> bool:
        """Treat Qt's default empty QTextEdit HTML as empty."""
        if not html:
            return True
        try:
            import re
            s = str(html)
            # remove script/style blocks
            s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", "", s)
            # ignore breaks/paragraph ends
            s = re.sub(r"(?is)<br\\s*/?>", " ", s)
            s = re.sub(r"(?is)</p\\s*>", " ", s)
            # strip remaining tags
            s = re.sub(r"(?is)<[^>]+>", "", s)
            s = s.replace("&nbsp;", " ").replace("\xa0", " ")
            return (s.strip() == "")
        except Exception:
            return (str(html).strip() == "")

    def _normalize_nt_html(self, html: str) -> str:
        html = html or ""
        return "" if self._nt_html_is_effectively_empty(html) else html

    def get_normal_template_text(self) -> str:
        """Returns Normal Template (HTML) buffer; empty when nothing is selected/typed."""
        if getattr(self, "_active_tab", "") == "normal_template":
            try:
                # ✅ اگر متن قابل مشاهده خالی است، اصلاً HTML اسکلت را ذخیره نکن
                plain = (self.box.toPlainText() or "").strip()
                if not plain:
                    self._buf_normal_template = ""
                else:
                    self._buf_normal_template = self.box.toHtml()
            except Exception:
                try:
                    self._buf_normal_template = self.box.toPlainText()
                except Exception:
                    pass

        # ✅ اگر یک HTML اسکلت بود، صفرش کن
        self._buf_normal_template = self._normalize_nt_html(self._buf_normal_template)
        return self._buf_normal_template

    def _on_nt_clear_clicked(self):
        self._nt_loaded_path = None
        self._nt_templates = []
        self._nt_name_to_html = {}
        try:
            self.cmb_nt_names.blockSignals(True)
            self.cmb_nt_names.clear()
            self.cmb_nt_names.addItem("Upload JSON first…")
        finally:
            self.cmb_nt_names.blockSignals(False)

        self.lbl_nt_info.setText("Upload JSON first…")

        try:
            self.cmb_nt_names.setEnabled(False)
            self.btn_nt_clear.setEnabled(False)
        except Exception:
            pass

        # clear current normal template
        self._buf_normal_template = ""
        if getattr(self, "_active_tab", "") == "normal_template":
            try:
                self.box.setHtml("")
            except Exception:
                self.box.setPlainText("")

    def _on_nt_upload_clicked(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Normal Template JSON",
            "",
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not path:
            return

        try:
            text = None
            for enc in ("utf-8-sig", "utf-8", "cp1256"):
                try:
                    with open(path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except Exception:
                    pass
            if text is None:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()

            items = self._parse_templates_payload(text)
            if not items:
                QMessageBox.warning(self, "Invalid JSON", "No valid items with Name/Html found in file.")
                return

            self._nt_loaded_path = path
            self._nt_templates = items

            # build name->html (handle duplicates)
            name_to_html = {}
            name_counts = {}
            for it in items:
                name = str(it.get("Name", "")).strip()
                html = it.get("Html", "")
                if not name or not isinstance(html, str):
                    continue
                if name in name_to_html:
                    name_counts[name] = name_counts.get(name, 1) + 1
                    unique = f"{name} ({name_counts[name]})"
                    name_to_html[unique] = html
                else:
                    name_to_html[name] = html

            self._nt_name_to_html = name_to_html

            # populate combo
            names = list(self._nt_name_to_html.keys())
            names.sort()

            try:
                self.cmb_nt_names.blockSignals(True)
                self.cmb_nt_names.clear()
                self.cmb_nt_names.addItem("Upload JSON first…")
                self.cmb_nt_names.addItems(names)
            finally:
                self.cmb_nt_names.blockSignals(False)

            self.lbl_nt_info.setText(f"{len(names)} templates loaded")

            try:
                self.cmb_nt_names.setEnabled(True)
                self.btn_nt_clear.setEnabled(True)
            except Exception:
                pass

        except Exception as e:
            QMessageBox.warning(self, "Load error", f"Could not load templates:\n{e}")

    def _parse_templates_payload(self, text: str) -> list[dict]:
        """
        Accepts:
        - strict JSON (recommended)
        - python-literal list/dict (your pasted example uses single quotes)
        Returns list[dict].
        """
        import json, ast

        payload = None
        # 1) JSON
        try:
            payload = json.loads(text)
        except Exception:
            payload = None

        # 2) python literal fallback (for single-quote pseudo-json)
        if payload is None:
            try:
                payload = ast.literal_eval(text)
            except Exception:
                payload = None

        # normalize
        if isinstance(payload, dict):
            # allow {"items":[...]} or {"data":[...]} etc
            for k in ("items", "data", "templates", "reports"):
                if isinstance(payload.get(k), list):
                    payload = payload[k]
                    break

        if not isinstance(payload, list):
            return []

        out = []
        for it in payload:
            if isinstance(it, dict) and ("Name" in it) and ("Html" in it):
                out.append(it)
        return out

    def _on_nt_name_changed(self, idx: int):
        if idx <= 0:
            return
        name = self.cmb_nt_names.currentText().strip()
        if not name:
            return
        html = self._nt_name_to_html.get(name, "")
        if not html:
            return

        # ✅ RTL wrapper اعمال شود اگر متن فارسی/عربی داشت
        if MessageBubble._has_rtl_chars(html) and "rtl-wrap" not in html.lower():
            html = MessageBubble._wrap_rtl_html(html)

        self._buf_normal_template = html
        if getattr(self, "_active_tab", "") == "normal_template":
            try:
                self.box.setHtml(html)
            except Exception:
                self.box.setPlainText(html)
            cur = self.box.textCursor()
            cur.movePosition(QTextCursor.End)
            self.box.setTextCursor(cur)
            self._apply_box_direction()  # ← این هم مهم است

    def clear_attachment(self):
        """
        Clears all queued voice files and hides the attachment chip.
        Backward-compatible: also resets old single-file fields.
        """
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []

        self._voice_queue.clear()
        self._voice_src_path = None  # legacy single-file path

        try:
            self.lbl_file.clear()
            self.attach_frame.setVisible(False)
        finally:
            if not getattr(self, "_rec_running", False):
                self._apply_mic_mode("record")

    def show_cancel(self, on: bool):
        self.btn_cancel.setVisible(on)

    # ---------- events ----------

    # ---------- input font controls (main page A-/+A) ----------
    def _apply_input_font(self) -> None:
        try:
            f = self.box.font()
            f.setPointSize(int(self._input_font_pt))
            self.box.setFont(f)
            # Also update the document default font (better consistency for pasted rich text)
            self.box.document().setDefaultFont(f)
        except Exception:
            pass

    def _change_input_font(self, delta: int) -> None:
        """Increase/decrease the input QPlainTextEdit font size."""
        try:
            cur = int(getattr(self, "_input_font_pt", 14) or 14)
        except Exception:
            cur = 14
        new = max(10, min(28, cur + int(delta)))
        self._input_font_pt = new
        self._apply_input_font()

    def eventFilter(self, obj, ev):
        if obj is self.box and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
                self._emit_send();
                return True
        return super().eventFilter(obj, ev)

    def _emit_send(self):
        # txt = self.box.toPlainText().strip()
        # if txt: self.sendClicked.emit(txt)

        # جدید: حتی با متن خالی هم ارسال کن
        txt = self.box.toPlainText().strip()
        self.sendClicked.emit(txt)

    def _emit_standardize(self):
        txt = (self.box.toPlainText() or "").strip()
        if not txt:
            return
        self.standardizeClicked.emit(txt)

    def _ensure_chips_layout(self):
        """
        ساخت ظرف چیپ‌ها در نوار Attachments.
        """
        if getattr(self, "_chips_wrap", None) is not None:
            return

        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QAbstractScrollArea
        from PySide6.QtCore import Qt

        col = QVBoxLayout(self.attach_frame)
        col.setContentsMargins(8, 0, 8, 0)
        col.setSpacing(6)

        title = QLabel("Attachments")
        title.setStyleSheet("color:#cfcfcf; font-weight:700; letter-spacing:.2px;")
        col.addWidget(title, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self._chips_scroll = QScrollArea(self.attach_frame)
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # ✅ let sizeHint follow contents, but cap height so it doesn't eat the page
        self._chips_scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self._chips_scroll.setMaximumHeight(160)

        self._chips_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;} "
            "QScrollArea>QWidget>QWidget{background:transparent;}"
        )
        col.addWidget(self._chips_scroll, 1)

        self._chip_bar_max_w = 340
        self.attach_frame.setMinimumWidth(0)
        self.attach_frame.setMaximumWidth(self._chip_bar_max_w)
        self.attach_frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        self._chips_wrap = QWidget(self._chips_scroll)
        self._chips_layout = QVBoxLayout(self._chips_wrap)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_scroll.setWidget(self._chips_wrap)

        self._chips_wrap.setStyleSheet("""
            QFrame#voiceChip, QFrame#imageChip {
                background: #3a3a3a;
                border: 1px solid #4a4a4a;
                border-radius: 10px;
            }
            QLabel#chipText {
                color: #ddd;
                padding: 6px 8px;
                font-size: 12px;
            }
            QToolButton#chipAction, QToolButton#chipClose {
                min-width: 20px; min-height: 20px;
                border: none;
            }
        """)


        # فقط یک‌بار، سیگنال‌های پلیر چیپ را وصل می‌کنیم
        if not hasattr(self, "_chip_signals_wired"):
            self._chip_player.durationChanged.connect(self._on_chip_duration)
            self._chip_player.positionChanged.connect(self._on_chip_position)
            self._chip_signals_wired = True

    def _choose_file(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select file",
                "",
                (
                    "Audio/Images (*.wav *.mp3 *.m4a *.aac *.flac "
                    "*.png *.jpg *.jpeg *.bmp *.gif *.dcm);;"
                    "All Files (*.*)"
                ),
            )
            if not path:
                return

        ext = os.path.splitext(path)[1].lower()

        # -------------------------
        #  ✔️ Image file → attachment (no auto-send)
        # -------------------------
        if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".dcm"):
            # Just attach the image. Image Analyzer mode will pick it up.
            self.add_image_attachment(path)
            return

        # -------------------------
        #  ✔️ Audio file → transcription
        # -------------------------
        self.add_voice_attachment(path)
        payload = {
            "paths": [path],
            "quality_mode": getattr(self, "_transcribe_quality_mode", "clear"),
        }
        self.transcribeRequested.emit(payload)
        self.switch_tab("transcribe")
            

    def add_voice_attachment(self, path: str):
        """
        Adds a voice file to the multi-file queue (up to 4).
        Resets legacy single-file state and updates the chip summary.
        """
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []
        max_count = 4
        if len(self._voice_queue) >= max_count:
            # Optionally show a toast/tooltip: "Maximum 4 voice files."
            return

        self._voice_queue.append(path)
        self._voice_src_path = None  # legacy single-file path (neutralized)

        self._render_voice_chips()
        # After finishing recording, Cancel is no longer needed
        self.show_cancel(False)
        # Return mic UI to "record" mode
        self._apply_mic_mode("record")

    def remove_voice_attachment(self, path: str):
        """
        Removes exactly ONE occurrence of the given voice file from the queue
        and refreshes the chips UI (does NOT clear all).
        همچنین اگر همین فایل در حال پخش باشد، پخش را متوقف می‌کند.
        """
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []

        try:
            import os
            tgt = os.path.normpath(path or "")
            # اگر همین فایل در حال پخش است، Stop کن
            if self._chip_playing_path and os.path.normpath(self._chip_playing_path) == tgt:
                try:
                    self._chip_player.stop()
                except Exception:
                    pass
                self._chip_playing_path = None

            for i, p in enumerate(list(self._voice_queue)):
                if os.path.normpath(p) == tgt:
                    del self._voice_queue[i]
                    break
        except Exception:
            pass

        self._render_voice_chips()

    def _on_chip_close(self):
        """
        Close handler for a single chip's × button.
        Finds the chip's bound path and removes only that item.
        """
        try:
            btn = self.sender()
            chip = btn.parent() if btn else None
            path = getattr(chip, "_voice_path", None)
            if path:
                self.remove_voice_attachment(path)
            else:
                # fallback: فقط UI را رفرش کنیم، صف دست‌نخورده می‌ماند
                self._render_voice_chips()
        except Exception:
            pass

    def get_pending_voices(self) -> t.List[str]:
        """
        Returns a copy of the current queue of voice file paths.
        """
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []
        return list(self._voice_queue)

    def clear_pending_voices(self):
        """
        Clears the voice queue and hides the attachment chip.
        همچنین هر پخش فعالی را متوقف می‌کند.
        """
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []
        try:
            self._chip_player.stop()
        except Exception:
            pass
        self._chip_playing_path = None
        self._voice_queue.clear()
        self._render_voice_chips()

    def _resend_voice_for_transcribe(self, path: str):
        """
        Re-sends a single queued voice file to /generate_transcript
        using the same immediate single-file flow as the mic recording.
        """
        payload = self._payload_from_path(path)
        if payload:
            self.transcribeRequested.emit(payload)

    # ---------- chip player helpers ----------
    def _chip_play(self, path: str):
        """
        پخش فایل مشخص‌شده. اگر فایل دیگری در حال پخش باشد، ابتدا متوقف می‌شود.
        """
        try:
            import os
            tgt = os.path.normpath(path or "")
            cur = os.path.normpath(self._chip_playing_path or "") if self._chip_playing_path else None

            if not cur or cur != tgt:
                self._chip_player.stop()
                self._chip_player.setSource(QUrl.fromLocalFile(path))
                self._chip_playing_path = path

            self._chip_player.play()
        except Exception:
            pass

        # برای به‌روزرسانی آیکون Play/Pause روی چیپ‌ها
        QTimer.singleShot(0, self._render_voice_chips)

    def _chip_pause(self):
        """توقف موقت پخش."""
        try:
            self._chip_player.pause()
        except Exception:
            pass
        QTimer.singleShot(0, self._render_voice_chips)

    def _chip_stop(self):
        """ایست کامل پخش و ریست اسلایدر."""
        try:
            self._chip_player.stop()
        except Exception:
            pass
        self._chip_playing_path = None
        QTimer.singleShot(0, self._render_voice_chips)

    def _on_chip_state_changed(self, state):
        """
        زمانی که state پلیر عوض می‌شود (Playing / Paused / Stopped).
        این‌جا مطمئن می‌شویم بعد از Stopped، اسلایدر برای پلیِ بعدی گیر نکند.
        """
        if state == QMediaPlayer.StoppedState:
            # ریست فلاگ درَگ‌کردن و برگرداندن اسلایدر به ابتدا
            chip = self._find_chip_for_path(self._chip_playing_path)
            if chip:
                chip._user_seeking = False
                slider = getattr(chip, "_slider", None)
                lbl = getattr(chip, "_time_lbl", None)
                if slider is not None:
                    slider.setValue(0)
                if lbl is not None:
                    # بعد از توقف، زمان را می‌توانی به مدت کل یا 00:00 برگردانی
                    lbl.setText(self._fmt_ms(self._chip_duration_ms if hasattr(self, "_chip_duration_ms") else 0))

            # وقتی صدا تمام شد، مسیر در حال پخش را پاک می‌کنیم
            self._chip_playing_path = None

        # در هر حال، آیکون‌ها باید به‌روز شوند
        QTimer.singleShot(0, self._render_voice_chips)



    def _render_voice_chips(self):
        """
        رندر چیپ‌های ویس بدون دست‌زدن به چیپ‌های تصویر
        (قبلاً همه چیپ‌ها پاک می‌شدند و تصویر هم از بین می‌رفت)
        """
        import os
        from PySide6.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout, QHBoxLayout, QSlider
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtMultimedia import QMediaPlayer

        def trim_filename(fname: str, max_len: int = 22) -> str:
            fname = (fname or "").strip()
            if not fname:
                return ""
            if len(fname) <= max_len:
                return fname
            name, ext = os.path.splitext(fname)
            head = (name[:3] if name else fname[:3])
            ext_no = (ext[1:] if ext.startswith(".") else ext)[:6]
            return f"{head}.{ext_no}" if ext_no else f"{head}."

        # ---------- Ensure structures ----------
        if not hasattr(self, "_voice_queue"):
            self._voice_queue = []
        self._ensure_chips_layout()

        # ---------- Remove ONLY old voice chips ----------
        try:
            for i in reversed(range(self._chips_layout.count())):
                it = self._chips_layout.itemAt(i)
                w = it.widget() if it else None
                if w is not None and w.objectName() == "voiceChip":
                    self._chips_layout.removeWidget(w)
                    w.deleteLater()
        except Exception:
            pass

        # اگر ویسی نداریم: فقط وقتی نوار را ببند که هیچ چیپ دیگری (مثل تصویر) هم نیست
        if len(self._voice_queue) == 0:
            any_other = False
            try:
                for i in range(self._chips_layout.count()):
                    it = self._chips_layout.itemAt(i)
                    w = it.widget() if it else None
                    if w is not None and w.objectName() in ("imageChip",):
                        any_other = True
                        break
            except Exception:
                pass

            try:
                if hasattr(self, "lbl_file"):
                    self.lbl_file.clear()
                self.attach_frame.setVisible(bool(any_other))
                QTimer.singleShot(0, self._reposition_attachment_overlay)
            except Exception:
                pass
            return

        cur_path = getattr(self, "_chip_playing_path", None)
        cur_state = getattr(self, "_chip_player", None) and self._chip_player.playbackState()

        chip_style = """
            QFrame#voiceChip {
                background: rgba(255, 255, 255, 18);
                border-radius: 18px;
                border: 1px solid rgba(255, 255, 255, 80);
                padding: 8px;
                background-image: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,35),
                    stop:0.5 rgba(255,255,255,10),
                    stop:1 rgba(255,255,255,25)
                );
            }
            QFrame#voiceChip:hover {
                background-color: rgba(255, 255, 255, 30);
                border: 1px solid rgba(255, 255, 255, 120);
            }
            QLabel#chipText { font-size: 13px; font-weight: 500; color: #1e1e1e; }
            QToolButton#chipAction {
                background: rgba(255,255,255,35);
                border: 1px solid rgba(255,255,255,80);
                border-radius: 8px;
                padding: 2px 6px;
            }
            QToolButton#chipAction:hover { background: rgba(255,255,255,65); }
            QToolButton#chipClose {
                background: rgba(255, 70, 70, 35);
                border: 1px solid rgba(255, 70, 70, 90);
                border-radius: 10px;
                padding: 2px 7px;
                font-size: 14px;
                font-weight: 600;
                color: #b00000;
            }
            QToolButton#chipClose:hover { background: rgba(255, 70, 70, 60); }
        """

        # ---------- Insert voice chips BEFORE image chips ----------
        def _first_image_index() -> int:
            for i in range(self._chips_layout.count()):
                it = self._chips_layout.itemAt(i)
                w = it.widget() if it else None
                if w is not None and w.objectName() == "imageChip":
                    return i
            return self._chips_layout.count()

        insert_at = _first_image_index()

        max_bar_w = int(getattr(self, "_chip_bar_max_w", 340) or 340)
        max_chip_w = max(220, max_bar_w - 16)

        for path in self._voice_queue:
            chip = QFrame(self._chips_wrap)
            chip.setObjectName("voiceChip")
            chip.setStyleSheet(chip_style)
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            chip.setMaximumWidth(max_chip_w)

            chip._voice_path = path
            chip._user_seeking = False

            vbox = QVBoxLayout(chip)
            vbox.setContentsMargins(10, 6, 10, 6)
            vbox.setSpacing(4)

            row_top = QHBoxLayout()
            row_top.setSpacing(6)

            row_bottom = QHBoxLayout()
            row_bottom.setSpacing(4)

            vbox.addLayout(row_top)
            vbox.addLayout(row_bottom)

            base = os.path.basename(path)
            trimmed = trim_filename(base)

            lbl = QLabel(trimmed, chip)
            lbl.setObjectName("chipText")
            row_top.addWidget(lbl, 1)

            same = cur_path and (os.path.normpath(cur_path) == os.path.normpath(path))
            is_playing_this = bool(same and (cur_state == QMediaPlayer.PlayingState))

            btn_play = QToolButton(chip)
            btn_play.setObjectName("chipAction")
            btn_play.setCursor(Qt.PointingHandCursor)
            btn_play.setText("⏸" if is_playing_this else "▶")
            btn_play.clicked.connect(self._chip_pause if is_playing_this else (lambda _, p=path: self._chip_play(p)))
            row_top.addWidget(btn_play, 0)

            btn_stop = QToolButton(chip)
            btn_stop.setObjectName("chipAction")
            btn_stop.setText("■")
            btn_stop.clicked.connect(self._chip_stop)
            row_top.addWidget(btn_stop, 0)

            btn_send = QToolButton(chip)
            btn_send.setObjectName("chipAction")
            btn_send.setText("↻")
            btn_send.clicked.connect(lambda _, p=path: self._resend_voice_for_transcribe(p))
            row_top.addWidget(btn_send, 0)

            btn_close = QToolButton(chip)
            btn_close.setObjectName("chipClose")
            btn_close.setText("×")
            btn_close.clicked.connect(self._on_chip_close)
            row_top.addWidget(btn_close, 0)

            slider = QSlider(Qt.Horizontal, chip)
            slider.setFixedHeight(14)
            duration_ms = int(getattr(self, "_chip_duration_ms", 0) or 0) if is_playing_this else 0
            slider.setMinimumWidth(60 if duration_ms == 0 else 120)
            slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    background: rgba(255,255,255,0.35);
                    height: 4px;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    width: 12px;
                    margin: -4px 0;
                    border-radius: 6px;
                    background: rgba(255,255,255,0.65);
                }
            """)
            slider.setRange(0, duration_ms)
            slider.setSingleStep(1000)
            slider.setPageStep(4000)
            slider.setFocusPolicy(Qt.NoFocus)
            row_bottom.addWidget(slider, 1)

            time_lbl = QLabel(self._fmt_ms(duration_ms), chip)
            time_lbl.setFixedWidth(42)
            time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            time_lbl.setStyleSheet("font-size:11px; color:#444;")
            row_bottom.addWidget(time_lbl)

            chip._slider = slider
            chip._time_lbl = time_lbl

            slider.sliderPressed.connect(lambda ch=chip: setattr(ch, "_user_seeking", True))
            slider.sliderReleased.connect(lambda ch=chip: self._on_chip_slider_released(ch))
            slider.sliderMoved.connect(lambda v, ch=chip: self._on_chip_slider_moved(ch, v))

            self._chips_layout.insertWidget(insert_at, chip, 0, Qt.AlignTop | Qt.AlignLeft)
            insert_at += 1

        try:
            self.attach_frame.setVisible(True)
            self._update_attach_width()
            QTimer.singleShot(0, self._reposition_attachment_overlay)
        except Exception:
            pass


    # ---------- mic logic ----------
    def _apply_mic_mode(self, mode: str):
        self._mic_mode = mode
        if mode == "record":
            _set_icon(self.btn_mic, "mic.png", 20, "Record voice")
            # Hide pause button when in record mode
            self.btn_pause.setVisible(False)
        elif mode == "confirm":
            _set_icon(self.btn_mic, "check.png", 20, "Finish & Transcribe")
            # Show pause button when in confirm mode (after recording started)
            self.btn_pause.setVisible(True)
        else:
            _set_icon(self.btn_mic, "mic.png", 20, "Record voice")
            self.btn_pause.setVisible(False)

    def _on_mic_clicked(self):
        if self._mic_mode == "record":
            self._start_record();
            # Show pause button when recording starts
            self.btn_pause.setVisible(True)
            return
        if self._mic_mode == "confirm":
            # پایان ضبط و شروع خودکار ترنسکرایب
            self._finish_record_and_transcribe();
            # Hide pause button when finishing recording
            self.btn_pause.setVisible(False)
            return

    def _on_cancel_clicked(self):
        if self._rec_running:
            self._rec_running = False
            self._rec_paused = False
            self._rec_timer.stop()
            self._rec_frames = []
            self._rec_start_ts = None
            try:
                self.rec_panel.setVisible(False)
                self.wave.clear()
                self.lbl_rec_time.setText("00:00")
                self.btn_pause.setVisible(False)  # ✅ hide pause button
            except Exception:
                pass
            if self._rec_thread:
                self._rec_thread.join(timeout=1.0)
                self._rec_thread = None
            self.clear_attachment()
            self._apply_mic_mode("record")
            self.show_cancel(False)
        else:
            self.cancelClicked.emit()
    # ---------- recording ----------
    def _start_record(self):
        self._rec_running = True
        self._rec_paused = False  # ✅ reset pause
        self._rec_frames = []
        self._rec_start_ts = time.time()
        self._rec_level = 0.0
        self._rec_level_smooth = 0.0
        try:
            self.wave.clear()
            self.rec_panel.setVisible(True)
            self.btn_pause.setVisible(True)       # ✅ show
            self._apply_pause_icon(False)         # ✅ set to Pause icon
        except Exception:
            pass
        self._apply_mic_mode("confirm")
        self.show_cancel(True)
        self._rec_timer.start(100)
        def worker():
            try:
                with sd.InputStream(samplerate=self._rec_fs, channels=1, dtype='int16', callback=self._rec_callback):
                    while self._rec_running:
                        sd.sleep(100)
            except Exception:
                self._rec_running = False
                self._apply_mic_mode("record")
                self.show_cancel(False)
        self._rec_thread = threading.Thread(target=worker, daemon=True)
        self._rec_thread.start()

    def _rec_callback(self, indata, frames, time_info, status):
        if self._rec_paused:
            return
        self._rec_frames.append(indata.copy())
        try:
            data = indata.astype(np.float32)
            peak = float(np.max(np.abs(data))) / 32768.0
            rms = float(np.sqrt(np.mean(data * data))) / 32768.0
            level = max(0.0, min(1.0, 0.7 * peak + 0.3 * rms))
            self._rec_level = level
        except Exception:
            pass

    def _on_rec_tick(self):
        if self._rec_paused or self._rec_start_ts is None:
            return
        elapsed = int(time.time() - self._rec_start_ts)
        self.lbl_rec_time.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        self._rec_level_smooth = 0.6 * self._rec_level_smooth + 0.4 * float(self._rec_level)
        self._agc_peak = max(self._agc_peak * 0.97, self._rec_level_smooth)
        norm = (self._rec_level_smooth - self._noise_floor) / (self._agc_peak - self._noise_floor + 1e-6)
        norm = max(0.0, min(1.0, norm))
        vis = norm ** 0.6
        self.wave.push(vis)

    def _finish_record_and_transcribe(self):
        # ✅ remember where the user was recording (fix: don't jump from Correction)
        tab_before = getattr(self, "_active_tab", "transcribe")

        self._rec_running = False
        self._rec_paused = False
        self._rec_timer.stop()
        self._rec_start_ts = None
        try:
            self.rec_panel.setVisible(False)
            self.wave.clear()
            self.lbl_rec_time.setText("00:00")
            self.btn_pause.setVisible(False)  # ✅ hide pause button
        except Exception:
            pass

        if self._rec_thread:
            self._rec_thread.join(timeout=2.0)
            self._rec_thread = None

        if not getattr(self, "_rec_frames", None):
            self._apply_mic_mode("record")
            self.show_cancel(False)
            return

        tmp = os.path.join(tempfile.gettempdir(), f"rec_{int(time.time())}.wav")
        try:
            audio = np.concatenate(self._rec_frames, axis=0)
            sf.write(tmp, audio, self._rec_fs)
            self.add_voice_attachment(tmp)

            payload = {"file_path": tmp, "filename": os.path.basename(tmp)}
            self.transcribeRequested.emit(payload)

            # ✅ FIX: do NOT auto-switch to Transcribe when recording in Correction tab
            if tab_before != "correction":
                self.switch_tab("transcribe")

        except Exception:
            self._apply_mic_mode("record")
            self.show_cancel(False)

    # ---------- payload ----------
    def _payload_from_path(self, path: str) -> t.Optional[dict]:
        try:
            return {"file_path": path, "filename": os.path.basename(path)}
        except Exception:
            return None

    def apply_side_padding(self, left: int = 16, right: int = 16):
        """
        به ورودی (Composer) پدینگ افقی می‌دهد تا به لبه‌های صفحه نچسبد.
        استفاده: composer.apply_side_padding()
        """
        # اگر روی خود ویجت لایه‌ای تنظیم شده باشد، از همان استفاده کن
        lay = self.layout()
        if lay is not None:
            l, t, r, b = lay.contentsMargins().left(), lay.contentsMargins().top(), lay.contentsMargins().right(), lay.contentsMargins().bottom()
            lay.setContentsMargins(left, t, right, b)
            return
        # در غیر این صورت، از margin ویجت استفاده کن
        try:
            self.setContentsMargins(left, 0, right, 0)
        except Exception:
            pass
