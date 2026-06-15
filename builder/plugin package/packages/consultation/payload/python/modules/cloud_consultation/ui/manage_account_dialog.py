"""ManageAccountDialog — account management hub (owner directive 2026-06-11).

Opened from the account dropdown's "Manage Account" button. Four blocks:

* **Identity** — the connected gmail + profile name and the Disconnect action
  (disconnect moved HERE from the dropdown card to keep the dropdown clean).
* **Hub Configuration** — "Current Hub: AI-PACS Cloud Hub (Google Drive)" with
  status, and the relocated hub actions ("Set up hub storage…" /
  "Disconnect hub"). The hub is deployment setup, configured by AI-PACS
  during installation/activation — never a user login.
* **Storage Usage** — quota summary (reuses the popup's cached
  ``/me/storage`` helper + background worker) and the storage-dashboard deep
  link (Education ▸ Consultation ▸ Storage).
* **Profile Settings** — "Edit my consultant profile" deep link
  (Education ▸ Consultation ▸ My Profile).

Presentation + derived state only: all actions reuse the existing Identity
engine (``IdentityService.connect/disconnect``) and the existing launcher deep
links — no engine/transport/poller changes. Everything is worker-loaded and
guarded; the dialog renders fine with nothing configured.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ._theme import palette
from .account_popup import _cached_storage, _ConnectWorker, _StorageWorker

logger = logging.getLogger(__name__)

_HUB_NOTE = "Configured by AI-PACS during installation/activation."
_HUB_NOT_CONFIGURED = (
    "Not configured — managed by your AI-PACS representative during installation"
)


class ManageAccountDialog(QDialog):
    """Identity / hub / storage / profile management in one place."""

    def __init__(self, auth_user=None, parent=None):
        super().__init__(parent)
        self.auth_user = dict(auth_user or {})
        self._connect_worker = None
        self._storage_worker = None
        self._storage_value = None
        self._storage_bar = None
        self._p = palette()
        self.setWindowTitle("Manage Account")
        # NON-MODAL (live bug 2026-06-13): never grab global input. A modal
        # exec() freezes the docked Web Browser where the hub / identity Google
        # login renders, so the user cannot complete sign-in. Opened via show()
        # (see account_popup._open_manage_account); the connect flows also
        # lower() this dialog so the browser stays reachable.
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(460)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(18, 16, 18, 16)
        self._root.setSpacing(12)
        self._apply_style()
        self._rebuild()

    # ── services / identities (all guarded) ──────────────────────────────────
    def _service(self):
        from modules.Identity.identity_service import IdentityService

        return IdentityService(IdentityService.resolve_aipacs_user(self.auth_user))

    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self.auth_user)

    def _aipacs_web_identity(self):
        try:
            from modules.Identity.providers.aipacs_web import find_aipacs_web_identity

            return find_aipacs_web_identity(self._aipacs_user())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("aipacs_web identity lookup failed: %s", exc)
        return None

    def _google_identity(self):
        try:
            for ident in self._service().list_identities():
                if ident.provider == "google":
                    return ident
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("listing identities failed: %s", exc)
        return None

    # ── build ─────────────────────────────────────────────────────────────────
    def _clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild(self):
        self._clear()
        self._storage_value = None
        self._storage_bar = None
        for builder in (self._identity_section, self._hub_section,
                        self._storage_section, self._profile_section):
            try:
                self._root.addWidget(builder())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("manage-account section failed: %s", exc)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self._root.addLayout(row)
        self.adjustSize()

    # ── Identity ──────────────────────────────────────────────────────────────
    def _identity_section(self) -> QFrame:
        p = self._p
        box, v = self._section("Identity")
        ident = self._aipacs_web_identity()
        if ident is None:
            none = QLabel("No Google identity is connected.")
            none.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
            v.addWidget(none)
            btn = QPushButton("Connect Google Account")
            btn.setObjectName("primary")
            btn.clicked.connect(self._connect_identity)
            v.addWidget(btn)
            return box

        link = (getattr(ident, "extra", None) or {}).get("link") or {}
        gmail = str(link.get("gmail_email") or ident.handle or "").strip()
        prof = str(
            link.get("profile_name") or ident.display_name or ident.handle or ""
        ).strip() or "Connected account"
        card, row = self._card_row()
        info = QVBoxLayout()
        info.setSpacing(1)
        name = QLabel(prof)
        name.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:600;")
        info.addWidget(name)
        if gmail:
            mail = QLabel(gmail)
            mail.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            info.addWidget(mail)
        status = QLabel("Status: Connected ✓ (verified)")
        status.setStyleSheet(f"color:{p['success']};font-size:11px;")
        info.addWidget(status)
        row.addLayout(info, 1)
        btn = QPushButton("Disconnect")
        btn.setObjectName("danger")
        btn.clicked.connect(lambda _=False, i=ident: self._disconnect_identity(i))
        row.addWidget(btn, 0, Qt.AlignTop)
        v.addWidget(card)
        return box

    def _connect_identity(self):
        # MODELESS (live bug 2026-06-12): a modal exec() grabs input and blocks
        # the docked browser where the Google consent page renders. Rebuild the
        # card on the dialog's finished callback instead of after exec().
        try:
            from modules.Identity.ui.aipacs_web_dialog import open_signin_dialog

            open_signin_dialog(
                self._service(),
                parent=self,
                on_finished=lambda _accepted: self._rebuild(),
            )
            self._lower_for_browser_login()
        except Exception as exc:
            logger.warning("aipacs_web sign-in failed to open: %s", exc)
            self._rebuild()

    def _disconnect_identity(self, ident):
        if ident is None:
            return
        if QMessageBox.question(
            self, "Disconnect identity",
            f"Disconnect {ident.handle or 'this account'}? "
            "Your AI-PACS login is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self._service().disconnect("aipacs_web", ident.subject_id)
        except Exception as exc:
            logger.warning("aipacs_web disconnect failed: %s", exc)
        self._rebuild()

    # ── Hub Configuration ─────────────────────────────────────────────────────
    def _hub_section(self) -> QFrame:
        p = self._p
        box, v = self._section("Hub Configuration")
        ident = self._google_identity()
        card, row = self._card_row()
        info = QVBoxLayout()
        info.setSpacing(1)
        title = QLabel("Current Hub: AI-PACS Cloud Hub (Google Drive)")
        title.setStyleSheet(f"color:{p['text']};font-size:13px;")
        info.addWidget(title)
        if ident is not None:
            status = QLabel(
                "● Connected" + (f" — {ident.handle}" if ident.handle else "")
            )
            status.setStyleSheet(f"color:{p['success']};font-size:11px;")
        else:
            status = QLabel(_HUB_NOT_CONFIGURED)
            status.setWordWrap(True)
            status.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        info.addWidget(status)
        row.addLayout(info, 1)
        if ident is not None:
            btn = QPushButton("Disconnect hub")
            btn.setObjectName("danger")
            btn.clicked.connect(lambda _=False, i=ident: self._disconnect_hub(i))
        else:
            btn = QPushButton("Set up hub storage…")
            btn.clicked.connect(self._connect_hub)
        row.addWidget(btn, 0, Qt.AlignTop)
        v.addWidget(card)
        note = QLabel(_HUB_NOTE)
        note.setStyleSheet(f"color:{p['text_muted']};font-size:10px;")
        v.addWidget(note)
        return box

    def _connect_hub(self):
        if self._connect_worker is not None and self._connect_worker.isRunning():
            return
        self._connect_worker = _ConnectWorker(self._service(), self)
        self._connect_worker.done.connect(lambda _ident: self._rebuild())
        self._connect_worker.failed.connect(
            lambda m: QMessageBox.warning(self, "Google connection failed", m))
        self._connect_worker.start()
        self._lower_for_browser_login()

    def _lower_for_browser_login(self):
        """Drop behind the docked Web Browser so the Google login is reachable.

        The dialog is already non-modal (never blocks input); lowering it just
        moves it out of the way while the user completes consent in the browser.
        It stays alive and refreshes via the connect worker's done signal / the
        sign-in dialog's on_finished callback.
        """
        try:
            self.lower()
            self.clearFocus()
        except Exception:  # pragma: no cover - defensive
            pass

    def _disconnect_hub(self, ident):
        if ident is None:
            return
        if QMessageBox.question(
            self, "Disconnect hub",
            f"Disconnect {ident.handle or 'the hub Google account'}? "
            "Your AI-PACS login is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self._service().disconnect("google", ident.subject_id)
        except Exception as exc:
            logger.warning("hub disconnect failed: %s", exc)
        self._rebuild()

    # ── Storage Usage ─────────────────────────────────────────────────────────
    def _storage_section(self) -> QFrame:
        p = self._p
        box, v = self._section("Storage Usage")
        self._storage_bar = QProgressBar()
        self._storage_bar.setRange(0, 100)
        self._storage_bar.setTextVisible(False)
        self._storage_bar.setFixedHeight(8)
        self._storage_bar.setVisible(False)
        v.addWidget(self._storage_bar)
        self._storage_value = QLabel("Loading storage usage…")
        self._storage_value.setWordWrap(True)
        self._storage_value.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        v.addWidget(self._storage_value)
        self._populate_storage()
        link = QPushButton("Open storage dashboard")
        link.setObjectName("ghost")
        link.clicked.connect(lambda: self._open_education(section="storage"))
        v.addWidget(link)
        return box

    def _populate_storage(self):
        """Cached render first; refresh via the popup's background worker."""
        if self._aipacs_web_identity() is None:
            if self._storage_value is not None:
                self._storage_value.setText(
                    "Connect your Google account to see storage usage.")
            return
        cached = _cached_storage()
        if cached is not None:
            self._render_storage(cached)
            return
        try:
            if self._storage_worker is not None and self._storage_worker.isRunning():
                return
            self._storage_worker = _StorageWorker(
                self._aipacs_user(), parent=QApplication.instance() or self)
            self._storage_worker.done.connect(self._render_storage)
            self._storage_worker.start()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("storage section worker skipped: %s", exc)

    def _render_storage(self, data):
        label = self._storage_value
        if label is None:
            return
        if not isinstance(data, dict):
            label.setText("Storage usage is unavailable right now.")
            return
        try:
            from modules.education.online_consultation.dashboard_core import (
                format_bytes,
                storage_summary,
            )

            p = self._p
            summary = storage_summary(data)
            if summary["fraction"] is None:
                used = summary.get("used")
                label.setText(
                    f"{format_bytes(used)} used (no quota configured)"
                    if used is not None else "No storage quota is configured."
                )
                return
            pct = int(round(100 * summary["fraction"]))
            used = format_bytes(summary["used"])
            quota = format_bytes(summary["quota"])
            if summary.get("alert"):
                color, suffix = p["danger"], " — almost full"
            elif summary.get("warn"):
                color, suffix = p["warning"], ""
            else:
                color, suffix = p["text"], ""
            label.setText(f"{used} of {quota} used ({pct}%){suffix}")
            label.setStyleSheet(f"color:{color};font-size:12px;")
            if self._storage_bar is not None:
                self._storage_bar.setValue(max(0, min(100, pct)))
                self._storage_bar.setStyleSheet(
                    f"QProgressBar{{background:{p['surface2']};border:1px solid "
                    f"{p['border']};border-radius:4px;}}"
                    f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
                )
                self._storage_bar.setVisible(True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("storage render failed: %s", exc)

    # ── Profile Settings ──────────────────────────────────────────────────────
    def _profile_section(self) -> QFrame:
        box, v = self._section("Profile Settings")
        btn = QPushButton("Edit my consultant profile")
        btn.setObjectName("ghost")
        btn.clicked.connect(lambda: self._open_education(section="profile"))
        v.addWidget(btn)
        return box

    def _open_education(self, section: str):
        try:
            from modules.education.online_consultation.launcher import (
                open_online_consultation,
            )

            self.accept()
            open_online_consultation(section=section)
        except Exception as exc:
            logger.warning("education deep link failed: %s", exc)

    # ── small builders / presentation ─────────────────────────────────────────
    def _section(self, caption: str):
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(7)
        lbl = QLabel(caption)
        lbl.setStyleSheet(f"color:{p['text_muted']};font-size:11px;font-weight:600;")
        v.addWidget(lbl)
        return box, v

    def _card_row(self):
        p = self._p
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};"
            f"border-radius:9px;}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        return card, row

    def _apply_style(self):
        p = self._p
        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QLabel {{ background:transparent; }}
            QPushButton {{ background:{p['accent']}; color:{p['button_text']};
                border:none; border-radius:8px; padding:8px 14px; font-size:13px; }}
            QPushButton#ghost {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; }}
            QPushButton#danger {{ background:transparent; color:{p['danger']};
                border:1px solid rgba(248,113,113,0.35); padding:6px 11px; }}
            QPushButton#primary {{ background:{p['accent']}; }}
            QPushButton:hover {{ border:1px solid {p['accent']}; }}
            """
        )
