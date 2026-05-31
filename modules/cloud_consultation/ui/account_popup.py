"""AccountPopup — the account hub that opens under the top-right user pill.

Shows the unchanged AI-PACS server identity, connected external accounts (Google),
a consultations summary, and notifications. All blocking work (Google connect) runs
on a worker thread; everything is defensive so a failure can never break the title bar.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._theme import palette

logger = logging.getLogger(__name__)


class _ConnectWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def run(self):
        try:
            self.done.emit(self._service.connect("google"))
        except Exception as exc:
            self.failed.emit(str(exc))


class AccountPopup(QWidget):
    def __init__(self, auth_user=None, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.auth_user = auth_user or {}
        self._worker = None
        self.setObjectName("AccountPopup")
        self.setFixedWidth(382)
        self._p = palette()
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(14, 14, 14, 14)
        self._root.setSpacing(12)
        self._apply_style()
        self._refresh()

    # ── services ─────────────────────────────────────────────────────────────
    def _service(self):
        from modules.Identity.identity_service import IdentityService

        return IdentityService(IdentityService.resolve_aipacs_user(self.auth_user))

    def _google_identity(self):
        try:
            for ident in self._service().list_identities():
                if ident.provider == "google":
                    return ident
        except Exception as exc:
            logger.debug("listing identities failed: %s", exc)
        return None

    # ── build ────────────────────────────────────────────────────────────────
    def _clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh(self):
        self._clear()
        self._root.addWidget(self._header())
        self._root.addWidget(self._accounts_section())
        try:
            from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

            if cloud_consultation_enabled():
                self._root.addWidget(self._consultations_section())
        except Exception as exc:
            logger.debug("consultation section skipped: %s", exc)
        self._root.addWidget(self._footer())
        self.adjustSize()

    def _header(self) -> QWidget:
        p = self._p
        f = QFrame()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(11)
        name = str(self.auth_user.get("full_name") or self.auth_user.get("username") or "User")
        role = str(self.auth_user.get("role") or "user").upper()
        avatar = QLabel((name[:1] or "U").upper())
        avatar.setFixedSize(42, 42)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background:{p['accent_soft']};color:{p['accent']};border:1px solid {p['accent']};"
            f"border-radius:21px;font-size:16px;font-weight:600;"
        )
        lay.addWidget(avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        nm = QLabel(name)
        nm.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
        sub = QLabel("AI-PACS server account")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        col.addWidget(nm)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        badge = QLabel(role)
        badge.setStyleSheet(
            f"background:rgba(59,130,246,0.18);color:#93c5fd;font-size:10px;"
            f"padding:3px 9px;border-radius:10px;"
        )
        lay.addWidget(badge, 0, Qt.AlignTop)
        return f

    def _accounts_section(self) -> QWidget:
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._label("Connected accounts"))

        ident = self._google_identity()
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};border-radius:9px;}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        g = QLabel("G")
        g.setFixedSize(22, 22)
        g.setAlignment(Qt.AlignCenter)
        g.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
        row.addWidget(g)
        info = QVBoxLayout()
        info.setSpacing(1)
        if ident is not None:
            title = QLabel(ident.handle or ident.display_name or "Google account")
            title.setStyleSheet(f"color:{p['text']};font-size:13px;")
            status = QLabel("● Connected · Profile + Drive")
            status.setStyleSheet(f"color:{p['success']};font-size:11px;")
        else:
            title = QLabel("Google account")
            title.setStyleSheet(f"color:{p['text']};font-size:13px;")
            status = QLabel("Not connected")
            status.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        info.addWidget(title)
        info.addWidget(status)
        row.addLayout(info, 1)

        if ident is not None:
            btn = QPushButton("Disconnect")
            btn.setObjectName("danger")
            btn.clicked.connect(lambda: self._disconnect_google(ident))
        else:
            btn = QPushButton("Connect")
            btn.clicked.connect(self._connect_google)
        row.addWidget(btn)
        v.addWidget(card)

        manage = QPushButton("Manage connected accounts…")
        manage.setObjectName("ghost")
        manage.clicked.connect(self._open_identity_panel)
        v.addWidget(manage)
        return box

    def _consultations_section(self) -> QWidget:
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._label("Consultations"))

        inbox_n = sent_n = 0
        try:
            from database import consultation_db

            inbox_n = len([c for c in consultation_db.list_consultations(direction="incoming")
                           if c.get("status") not in ("closed",)])
            sent_n = len(consultation_db.list_consultations(direction="outgoing"))
        except Exception as exc:
            logger.debug("consultation counts failed: %s", exc)

        chips = QHBoxLayout()
        chips.setSpacing(9)
        chips.addWidget(self._stat("Inbox", inbox_n, p["warning"]))
        chips.addWidget(self._stat("Sent", sent_n, p["text"]))
        v.addLayout(chips)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        new_btn = QPushButton("New consultation")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._new_consultation)
        open_btn = QPushButton("Open inbox")
        open_btn.setObjectName("ghost")
        open_btn.clicked.connect(self._open_inbox)
        actions.addWidget(new_btn, 1)
        actions.addWidget(open_btn)
        v.addLayout(actions)
        return box

    def _footer(self) -> QWidget:
        p = self._p
        f = QFrame()
        f.setStyleSheet(f"QFrame{{border-top:1px solid {p['border']};}}")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(0, 10, 0, 0)
        unread = 0
        try:
            from modules.cloud_consultation.notifications import inbox

            unread = inbox.unread_count()
        except Exception as exc:
            logger.debug("unread count failed: %s", exc)
        bell = QLabel(f"●  {unread} new notifications" if unread else "No new notifications")
        bell.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        lay.addWidget(bell, 1)
        if self._google_identity() is not None:
            out = QPushButton("Sign out of Google")
            out.setObjectName("ghost")
            out.clicked.connect(lambda: self._disconnect_google(self._google_identity()))
            lay.addWidget(out)
        return f

    # ── small builders ─────────────────────────────────────────────────────────
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{self._p['text_muted']};font-size:11px;font-weight:500;")
        return lbl

    def _stat(self, label: str, value: int, color: str) -> QWidget:
        p = self._p
        f = QFrame()
        f.setStyleSheet(f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};border-radius:9px;}}")
        v = QVBoxLayout(f)
        v.setContentsMargins(11, 9, 11, 9)
        v.setSpacing(1)
        num = QLabel(str(value))
        num.setStyleSheet(f"color:{color};font-size:19px;font-weight:600;")
        cap = QLabel(label)
        cap.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        v.addWidget(num)
        v.addWidget(cap)
        return f

    # ── actions ──────────────────────────────────────────────────────────────
    def _open_identity_panel(self):
        try:
            from modules.Identity.ui.identity_panel import IdentityPanel

            self.close()
            IdentityPanel(self._service(), parent=self.parent()).exec()
        except Exception as exc:
            logger.warning("open identity panel failed: %s", exc)

    def _connect_google(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _ConnectWorker(self._service(), self)
        self._worker.done.connect(lambda _ident: self._refresh())
        self._worker.failed.connect(self._on_connect_failed)
        self._worker.start()

    def _on_connect_failed(self, message: str):
        QMessageBox.warning(self, "Google connection failed", message)

    def _disconnect_google(self, ident):
        if ident is None:
            return
        if QMessageBox.question(
            self, "Disconnect Google",
            f"Disconnect {ident.handle or 'this Google account'}? Your AI-PACS login is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self._service().disconnect("google", ident.subject_id)
        except Exception as exc:
            logger.warning("disconnect failed: %s", exc)
        self._refresh()

    def _new_consultation(self):
        try:
            from .compose_dialog import ConsultationComposeDialog

            self.close()
            ConsultationComposeDialog(auth_user=self.auth_user, parent=self.parent()).exec()
        except Exception as exc:
            logger.warning("open compose dialog failed: %s", exc)

    def _open_inbox(self):
        try:
            from .inbox_widget import ConsultationInbox

            self.close()
            ConsultationInbox(auth_user=self.auth_user, parent=self.parent()).exec()
        except Exception as exc:
            logger.warning("open inbox failed: %s", exc)

    # ── presentation ─────────────────────────────────────────────────────────
    def _apply_style(self):
        p = self._p
        self.setStyleSheet(
            f"""
            QWidget#AccountPopup {{ background:{p['surface']};
                border:1px solid {p['accent']}; border-radius:12px; }}
            QPushButton {{ background:{p['accent']}; color:{p['button_text']}; border:none;
                border-radius:8px; padding:8px 14px; font-size:13px; }}
            QPushButton#ghost {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; }}
            QPushButton#danger {{ background:transparent; color:{p['danger']};
                border:1px solid rgba(248,113,113,0.35); padding:6px 11px; }}
            QPushButton#primary {{ background:{p['accent']}; }}
            QPushButton:hover {{ border:1px solid {p['accent']}; }}
            """
        )

    def show_under(self, anchor: QWidget):
        try:
            self.adjustSize()
            bottom_right = anchor.mapToGlobal(anchor.rect().bottomRight())
            self.move(max(0, bottom_right.x() - self.width()), bottom_right.y() + 6)
        except Exception as exc:
            logger.debug("popup positioning failed: %s", exc)
        self.show()
        self.raise_()
