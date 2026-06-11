"""Shared building blocks for the Education ▸ Consultation sections (ADR-0007).

Every section is constructed cheaply up-front but loads its data **lazily on
first activation** (switching the page tab) and always on a QThread worker —
no network ever runs on the UI thread, and a missing aipacs_web sign-in shows
a friendly empty state instead of an error.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ClientCallWorker(QThread):
    """Run ``fn(client)`` against the :class:`AipacsWebClient` off the UI thread.

    Emits ``not_signed_in`` when no aipacs_web identity is linked so sections
    can render the sign-in empty state instead of an error.
    """

    done = Signal(object)
    failed = Signal(str)
    not_signed_in = Signal()

    def __init__(self, aipacs_user: str, fn, parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._fn = fn

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                self.not_signed_in.emit()
                return
            self.done.emit(self._fn(client))
        except Exception as exc:
            self.failed.emit(str(exc))


class ConsultationSection(QWidget):
    """Base section: lazy first load, worker bookkeeping, signed-out state."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page
        self._p = page._p  # shared palette
        self._worker = None
        self._loaded = False
        self._build()

    # ── subclass contract ────────────────────────────────────────────────────
    def _build(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def _load(self):  # pragma: no cover - abstract
        raise NotImplementedError

    # ── lifecycle ────────────────────────────────────────────────────────────
    def activate(self):
        """Called when the section becomes the current tab. First visit loads."""
        if not self._loaded:
            self.refresh()

    def refresh(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._loaded = True
        try:
            self._load()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("section load failed: %s", exc)

    def start_worker(self, fn, on_done):
        """Start a :class:`ClientCallWorker`; failure/sign-out handled here."""
        self._worker = ClientCallWorker(self._page._aipacs_user(), fn, self)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(self.show_error)
        self._worker.not_signed_in.connect(self.show_signed_out)
        self._worker.start()

    # ── shared UI helpers ────────────────────────────────────────────────────
    def make_scroll_list(self):
        """A scroll area hosting a vertical list layout (stretch at the end)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lay.addStretch(1)
        scroll.setWidget(host)
        return scroll, lay

    @staticmethod
    def clear_list(lay):
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def muted_label(self, text: str, *, padding: int = 14) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color:{self._p['text_muted']};font-size:13px;padding:{padding}px;"
        )
        return lbl

    def card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("card")
        return f

    # default sink: subclasses with a list layout can set ``_message_list``
    _message_list = None

    def show_error(self, message: str):
        lay = self._message_list
        if lay is None:
            logger.warning("section error: %s", message)
            return
        self.clear_list(lay)
        lay.insertWidget(0, self.muted_label(
            f"Could not reach the consultation server: {message}"))

    def show_signed_out(self):
        lay = self._message_list
        if lay is None:
            return
        self.clear_list(lay)
        lay.insertWidget(0, self.muted_label(
            "Sign in to the AI-PACS Consultation system to use this section."))
        btn = QPushButton("Sign in to AI-PACS Consultation…")
        btn.clicked.connect(self._sign_in_then_refresh)
        lay.insertWidget(1, btn)

    def _sign_in_then_refresh(self):
        try:
            self._page._sign_in_aipacs_web(on_success=self.refresh)
        except TypeError:  # pragma: no cover - older page signature
            self._page._sign_in_aipacs_web()
