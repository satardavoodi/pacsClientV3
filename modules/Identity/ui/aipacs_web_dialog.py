"""AipacsWebSignInDialog — sign-in dialog for the AI-PACS Consultation system.

ADR-0008: the PRIMARY path is **Gmail attestation** — the user (already logged
into the workstation) enters their Gmail and clicks "Verify with Google"; a
transient Google OAuth (openid+email scopes ONLY) proves ownership, the ID
token goes to the local Laravel backend, and the returned Sanctum token links
the account. No personal Google identity is stored. The legacy email+password /
pairing-code exchange is kept under a collapsed "Advanced (admin) sign-in"
section. All network/OAuth work runs on QThread workers so the GUI never
blocks. Credentials are never persisted — only the returned token is stored
(OS keychain via secure_store).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class _PairWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, credentials: dict, parent=None):
        super().__init__(parent)
        self._service = service
        self._credentials = credentials

    def run(self):
        try:
            self.done.emit(
                self._service.connect_with_credentials("aipacs_web", self._credentials)
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class _AttestWorker(QThread):
    """Runs the transient Gmail attestation + backend link off the GUI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, gmail: str, parent=None):
        super().__init__(parent)
        self._service = service
        self._gmail = gmail

    def run(self):
        try:
            self.done.emit(self._service.connect_aipacs_web_via_google(self._gmail))
        except Exception as exc:
            self.failed.emit(str(exc))


class AipacsWebSignInDialog(QDialog):
    """Gmail attestation (primary) or admin email+password / pairing code.

    ``self.identity`` is set on success.
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._worker = None
        self._attest_worker = None
        self.identity = None
        self.setWindowTitle("Sign in to AI-PACS Consultation")
        self.setMinimumWidth(420)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        # ── PRIMARY: Connect with Google (ADR-0008 Gmail attestation) ──────────
        head = QLabel("Connect with Google")
        head.setStyleSheet("font-weight:600;")
        root.addWidget(head)

        intro = QLabel(
            "Enter the Gmail address registered for you by the administrator, "
            "then verify it with Google. A browser window will open — sign in "
            "with that exact Google account. Your AI-PACS login is unaffected."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.gmail = QLineEdit()
        self.gmail.setPlaceholderText("your.name@gmail.com")
        root.addWidget(self.gmail)

        self.verify_btn = QPushButton("Verify with Google")
        self.verify_btn.setDefault(True)
        self.verify_btn.clicked.connect(self._on_verify_google)
        root.addWidget(self.verify_btn)

        # ── collapsed: Advanced (admin) sign-in — the legacy pairing path ──────
        self.advanced_toggle = QPushButton("Advanced (admin) sign-in ▸")
        self.advanced_toggle.setFlat(True)
        self.advanced_toggle.setCursor(Qt.PointingHandCursor)
        self.advanced_toggle.setStyleSheet("text-align:left;border:none;")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        root.addWidget(self.advanced_toggle)

        self.advanced_box = QWidget()
        adv = QVBoxLayout(self.advanced_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(10)

        adv_intro = QLabel(
            "Sign in with your AI-PACS web account (email + password), "
            "or paste a pairing code from the website."
        )
        adv_intro.setWordWrap(True)
        adv.addWidget(adv_intro)

        self.email = QLineEdit()
        self.email.setPlaceholderText("Email")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        adv.addWidget(self.email)
        adv.addWidget(self.password)

        or_lbl = QLabel("— or —")
        or_lbl.setAlignment(Qt.AlignCenter)
        adv.addWidget(or_lbl)

        self.pairing_code = QLineEdit()
        self.pairing_code.setPlaceholderText("Pairing code")
        adv.addWidget(self.pairing_code)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect)
        adv.addWidget(self.connect_btn)

        self.advanced_box.setVisible(False)
        root.addWidget(self.advanced_box)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        root.addLayout(btns)

    # ── advanced toggle ──────────────────────────────────────────────────────
    def _toggle_advanced(self):
        show = not self.advanced_box.isVisible()
        self.advanced_box.setVisible(show)
        self.advanced_toggle.setText(
            "Advanced (admin) sign-in ▾" if show else "Advanced (admin) sign-in ▸"
        )
        self.adjustSize()

    # ── Gmail attestation (primary) ──────────────────────────────────────────
    def _on_verify_google(self):
        if self._attest_worker is not None and self._attest_worker.isRunning():
            return
        gmail = self.gmail.text().strip()
        if not gmail or "@" not in gmail:
            self.status.setText("Enter the Gmail address you want to link.")
            return
        self.verify_btn.setEnabled(False)
        self.status.setText(
            "Opening Google sign-in in your browser — sign in as "
            f"{gmail}, then return here…"
        )
        self._attest_worker = _AttestWorker(self._service, gmail, self)
        self._attest_worker.done.connect(self._on_attest_done)
        self._attest_worker.failed.connect(self._on_attest_failed)
        self._attest_worker.start()

    def _on_attest_done(self, identity):
        self.identity = identity
        link = (getattr(identity, "extra", None) or {}).get("link") or {}
        gmail = link.get("gmail_email") or getattr(identity, "handle", "") or ""
        name = link.get("profile_name") or getattr(identity, "display_name", "") or ""
        msg = f"Linked: {gmail}" + (f" ({name})" if name else "")
        self.status.setText(msg + " — you're connected.")
        self.verify_btn.setEnabled(False)
        # Let the user read the confirmation, then close.
        QTimer.singleShot(1600, self.accept)

    def _on_attest_failed(self, message: str):
        self.verify_btn.setEnabled(True)
        # The server's 422 messages (e.g. "This Gmail is not registered by the
        # administrator yet…") and the account-mismatch / cancelled-OAuth
        # messages from attest_gmail are already user-presentable — verbatim.
        self.status.setText(message or "Google verification failed.")

    # ── legacy pairing (advanced) ────────────────────────────────────────────
    def _credentials(self) -> dict | None:
        code = self.pairing_code.text().strip()
        if code:
            return {"pairing_code": code}
        email = self.email.text().strip()
        password = self.password.text()
        if email and password:
            return {"email": email, "password": password}
        return None

    def _on_connect(self):
        if self._worker is not None and self._worker.isRunning():
            return
        creds = self._credentials()
        if creds is None:
            self.status.setText("Enter email + password, or a pairing code.")
            return
        self.connect_btn.setEnabled(False)
        self.status.setText("Connecting…")
        self._worker = _PairWorker(self._service, creds, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, identity):
        self.identity = identity
        self.status.setText("Connected.")
        self.accept()

    def _on_failed(self, message: str):
        self.connect_btn.setEnabled(True)
        self.status.setText(message or "Sign-in failed.")
