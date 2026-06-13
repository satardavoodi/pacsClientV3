"""AipacsWebSignInDialog — sign-in dialog for the AI-PACS Consultation system.

ADR-0008 + unified login (owner directive 2026-06-11): the ONE user-facing
step is "Sign in with Google" — a transient Google OAuth (openid+email scopes
ONLY, embedded browser by default) verifies the account; the verified email
goes to the local Laravel backend, which authorizes it against the
consultation database. No Gmail pre-typing, no second username/password
prompt. A not-registered 422 surfaces the server's message verbatim in a
QMessageBox. No personal Google identity is stored. The legacy
email+password / pairing-code exchange is kept ONLY as a collapsed
"Administrator sign-in options…" fallback for admin/testing. All
network/OAuth work runs on QThread workers so the GUI never blocks.
Credentials are never persisted — only the returned token is stored
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
    """Runs the transient Google attestation + backend link off the GUI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, gmail: str = "", parent=None):
        super().__init__(parent)
        self._service = service
        self._gmail = gmail

    def run(self):
        try:
            self.done.emit(self._service.connect_aipacs_web_via_google(self._gmail))
        except Exception as exc:
            self.failed.emit(str(exc))


class AipacsWebSignInDialog(QDialog):
    """One-step Google sign-in (primary) or admin email+password / pairing code.

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
        # MODELESS (live bug 2026-06-12): the Google consent page opens in the
        # DOCKED Web Browser module (same top-level window). A modal exec()
        # would grab input and block the user from clicking their Google account
        # in the docked browser behind this dialog. Stay non-modal so the user
        # can complete consent in the browser tab and have this update via the
        # worker's done/failed signals. Callers MUST use open_signin_dialog()/
        # show(), never exec().
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        # Keep this companion above the docked browser without covering it; the
        # caller repositions it to a non-covering corner via open_signin_dialog.
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        # ── PRIMARY: one-step Google sign-in (owner directive 2026-06-11) ──────
        # No Gmail pre-typing: Google verifies the account, the server
        # authorizes the verified email against the consultation database.
        self.verify_btn = QPushButton("Sign in with Google")
        self.verify_btn.setDefault(True)
        self.verify_btn.setMinimumHeight(44)
        self.verify_btn.setStyleSheet("font-size:14px;font-weight:600;")
        self.verify_btn.clicked.connect(self._on_verify_google)
        root.addWidget(self.verify_btn)

        # The intro text adapts to the OAuth surface: when sign-in will open in
        # the embedded DOCKED browser (the default), tell the user to complete
        # consent there and come back — this dialog updates automatically. For
        # the system-browser fallback the generic line is fine.
        intro = QLabel(self._intro_text())
        intro.setWordWrap(True)
        root.addWidget(intro)

        # ── collapsed fallback: admin/testing sign-in (demoted link-style) ─────
        self.advanced_toggle = QPushButton("Administrator sign-in options…")
        self.advanced_toggle.setFlat(True)
        self.advanced_toggle.setCursor(Qt.PointingHandCursor)
        self.advanced_toggle.setStyleSheet(
            "text-align:left;border:none;background:transparent;"
            "font-size:11px;color:#888;text-decoration:underline;padding:0;"
        )
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

    # ── surface-aware copy ────────────────────────────────────────────────────
    @staticmethod
    def _embedded_surface() -> bool:
        """True when the Google sign-in will open in the embedded docked browser.

        Reuses the OAuth surface resolution so the copy matches reality. Never
        raises — defaults to False (system-browser wording) if anything fails.
        """
        try:
            from modules.Identity.providers.google.oauth_flow import (
                _resolve_oauth_surface,
            )

            use_embedded, _reason = _resolve_oauth_surface()
            return bool(use_embedded)
        except Exception:  # pragma: no cover - defensive
            return False

    def _intro_text(self) -> str:
        if self._embedded_surface():
            return (
                "Complete the Google sign-in in the AI-PACS browser tab, then "
                "come back — this window updates automatically. Your Google "
                "account identifies you to the AI-PACS Consultation system."
            )
        return (
            "Your Google account identifies you to the AI-PACS Consultation "
            "system."
        )

    # ── advanced toggle ──────────────────────────────────────────────────────
    def _toggle_advanced(self):
        show = not self.advanced_box.isVisible()
        self.advanced_box.setVisible(show)
        self.adjustSize()

    # ── one-step Google sign-in (primary) ────────────────────────────────────
    def _on_verify_google(self):
        if self._attest_worker is not None and self._attest_worker.isRunning():
            return
        self.verify_btn.setEnabled(False)
        if self._embedded_surface():
            self.status.setText(
                "Opening Google sign-in in the AI-PACS browser tab — choose "
                "your account there, then return here. This window updates "
                "automatically."
            )
        else:
            self.status.setText(
                "Opening Google sign-in — choose your account, then return here…"
            )
        # Empty gmail: the Google-verified email is authorized by the server.
        self._attest_worker = _AttestWorker(self._service, "", self)
        self._attest_worker.done.connect(self._on_attest_done)
        self._attest_worker.failed.connect(self._on_attest_failed)
        self._attest_worker.start()

    def _on_attest_done(self, identity):
        self.identity = identity
        link = (getattr(identity, "extra", None) or {}).get("link") or {}
        gmail = link.get("gmail_email") or getattr(identity, "handle", "") or ""
        name = link.get("profile_name") or getattr(identity, "display_name", "") or ""
        msg = f"Connected as {gmail}" + (f" ({name})" if name else "")
        self.status.setText(msg)
        self.verify_btn.setEnabled(False)
        # Let the user read the confirmation, then close.
        QTimer.singleShot(1600, self.accept)

    def _on_attest_failed(self, message: str):
        self.verify_btn.setEnabled(True)
        # Server 422 / mismatch / cancelled-OAuth messages are already
        # user-presentable — show them verbatim.
        text = message or "Google sign-in failed."
        self.status.setText(text)
        # Not-registered (owner directive): the server's message must surface
        # as a popup, not just inline text.
        if "not registered" in text.lower():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Consultation access", text)

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

    # ── clean teardown (modeless: cancel must not leave a hung worker) ─────────
    def _abandon_workers(self):
        """Detach from the running OAuth/pairing workers so closing the dialog
        cannot crash. The loopback consent thread can't be hard-killed, so we
        disconnect its signals and orphan it (parented to the dialog → Qt keeps
        it alive until it finishes, then it is reaped). Never raises."""
        for attr in ("_attest_worker", "_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if w.isRunning():
                    # Disconnect so a late done/failed can't touch a dead dialog.
                    try:
                        w.done.disconnect()
                    except Exception:  # pragma: no cover - already disconnected
                        pass
                    try:
                        w.failed.disconnect()
                    except Exception:  # pragma: no cover - already disconnected
                        pass
            except Exception:  # pragma: no cover - defensive
                pass

    def reject(self):
        self._abandon_workers()
        super().reject()

    def closeEvent(self, event):
        self._abandon_workers()
        super().closeEvent(event)


# ── modeless launcher (live bug 2026-06-12) ───────────────────────────────────
# QApplication property that keeps a strong reference to the live sign-in dialog
# so a modeless show() is not garbage-collected the moment the caller returns.
_LIVE_SIGNIN_DIALOG_ATTR = "_aipacs_live_signin_dialog"


def open_signin_dialog(service, parent=None, *, on_success=None, on_finished=None):
    """Open :class:`AipacsWebSignInDialog` MODELESS and return it.

    This is the supported entry point for every caller — never a modal blocking
    open (which grabs input and blocks the docked browser where the Google
    consent page renders; live bug 2026-06-12). The dialog is shown with
    ``show()``, kept alive via a QApplication-level strong reference (so it
    isn't GC'd), repositioned to a non-covering corner of the parent, and its
    result is delivered via callbacks instead of a blocking return value:

    * ``on_success(identity)`` — fires when the dialog is accepted (sign-in OK);
    * ``on_finished(accepted: bool)`` — fires on close either way (accepted or
      cancelled), e.g. to refresh a card.

    Never raises into the caller.
    """
    from PySide6.QtWidgets import QApplication

    dlg = AipacsWebSignInDialog(service, parent=parent)

    def _on_finished(result):
        try:
            accepted = bool(result == QDialog.Accepted)
            if accepted and callable(on_success):
                on_success(getattr(dlg, "identity", None))
            if callable(on_finished):
                on_finished(accepted)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("sign-in finished callback failed: %s", exc)
        finally:
            # Drop the strong reference so the dialog can be collected.
            app = QApplication.instance()
            if app is not None and getattr(app, _LIVE_SIGNIN_DIALOG_ATTR, None) is dlg:
                try:
                    setattr(app, _LIVE_SIGNIN_DIALOG_ATTR, None)
                except Exception:  # pragma: no cover - defensive
                    pass

    dlg.finished.connect(_on_finished)

    # Keep a strong reference so the modeless dialog survives the return.
    app = QApplication.instance()
    if app is not None:
        try:
            setattr(app, _LIVE_SIGNIN_DIALOG_ATTR, dlg)
        except Exception:  # pragma: no cover - defensive
            pass

    dlg.show()
    dlg.raise_()
    _position_non_covering(dlg, parent)
    return dlg


def _position_non_covering(dlg, parent):
    """Move the modeless dialog to the top-right of the parent window so it does
    NOT cover the docked browser's account-chooser area. Best-effort; never
    raises."""
    try:
        dlg.adjustSize()
        win = None
        if parent is not None and hasattr(parent, "window"):
            win = parent.window()
        if win is not None and win.isVisible():
            top_right = win.mapToGlobal(win.rect().topRight())
            x = max(0, top_right.x() - dlg.width() - 24)
            y = top_right.y() + 24
            dlg.move(x, y)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("sign-in dialog positioning failed: %s", exc)
