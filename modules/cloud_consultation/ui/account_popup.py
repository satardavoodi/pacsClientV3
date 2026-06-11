"""AccountPopup — the identity & notification hub under the top-right user pill
(ADR-0007).

Status-only + notifications + deep links: the unchanged AI-PACS server
identity, connection states (AI-PACS Consultation / Google), the unread
consultation notifications, and a cached storage line. Management lives in
Education ▸ Consultation — every block deep-links there. All blocking work
(Google connect, storage fetch) runs on worker threads; the popup renders
instantly from cached/empty data and fills in when a worker lands. Everything
is defensive so a failure can never break the title bar.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
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

# ADR-0007: friendly kind labels for the notification rows in the hub.
_KIND_LABELS = {
    "consultation_assigned": "Assignment",
    "invitation": "Invitation",
    "consultation_updated": "Update",
    "response_received": "Response",
    "upload_done": "Upload",
    "download_done": "Download",
    "sync_error": "Error",
}

# /me/storage result cached on the QApplication object (popup opens must render
# instantly — the worker refreshes the cache at most every 5 minutes).
_STORAGE_CACHE_ATTR = "_aipacs_storage_cache"  # (monotonic_ts, dict)
_STORAGE_CACHE_TTL_SEC = 300.0


def _cached_storage():
    app = QApplication.instance()
    cached = getattr(app, _STORAGE_CACHE_ATTR, None) if app is not None else None
    if not cached:
        return None
    ts, data = cached
    if (time.monotonic() - ts) > _STORAGE_CACHE_TTL_SEC:
        return None
    return data


def _store_storage_cache(data):
    app = QApplication.instance()
    if app is not None and isinstance(data, dict):
        setattr(app, _STORAGE_CACHE_ATTR, (time.monotonic(), data))


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


class _StorageWorker(QThread):
    """Background ``/me/storage`` fetch; caches on the QApplication object.

    Best-effort: any failure emits None and the storage line simply stays
    hidden. Parented to the QApplication so a closed popup never tears down a
    running thread; the popup slot auto-disconnects with the popup.
    """

    done = Signal(object)

    def __init__(self, aipacs_user: str, parent=None):
        super().__init__(parent)
        self._user = aipacs_user

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                self.done.emit(None)
                return
            data = client.my_storage() or {}
            _store_storage_cache(data)
            self.done.emit(data)
        except Exception as exc:  # pragma: no cover - best-effort by contract
            logger.debug("storage fetch failed: %s", exc)
            self.done.emit(None)


class AccountPopup(QWidget):
    def __init__(self, auth_user=None, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.auth_user = auth_user or {}
        self._worker = None
        self._storage_worker = None
        self._storage_label = None
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

    def _aipacs_web_identity(self):
        try:
            from modules.Identity.providers.aipacs_web import find_aipacs_web_identity
            from modules.Identity.identity_service import IdentityService

            return find_aipacs_web_identity(
                IdentityService.resolve_aipacs_user(self.auth_user)
            )
        except Exception as exc:
            logger.debug("aipacs_web identity lookup failed: %s", exc)
        return None

    # ── build ────────────────────────────────────────────────────────────────
    def _refresh(self):
        self._clear()
        self._root.addWidget(self._header())
        self._root.addWidget(self._accounts_section())
        try:
            # Consultation system (AI-PACS web pairing, ADR-0006). Guarded so the
            # popup renders unchanged when the backend is not configured or the
            # provider module is unavailable.
            from modules.Identity.providers.aipacs_web import aipacs_web_configured

            if aipacs_web_configured():
                self._root.addWidget(self._consultation_system_section())
        except Exception as exc:
            logger.debug("consultation system section skipped: %s", exc)
        try:
            from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

            if cloud_consultation_enabled():
                self._root.addWidget(self._notifications_section())
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

    def _consultation_system_section(self) -> QWidget:
        """AI-PACS Consultation (web backend) sign-in state — ADR-0006."""
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._label("Consultation system"))

        ident = self._aipacs_web_identity()
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};border-radius:9px;}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        mark = QLabel("☁")
        mark.setFixedSize(22, 22)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f"color:{p['text']};font-size:14px;")
        row.addWidget(mark)
        info = QVBoxLayout()
        info.setSpacing(1)
        if ident is not None:
            # ADR-0008: a Gmail-attested link shows "Linked: <gmail> (Dr. X)".
            link = (getattr(ident, "extra", None) or {}).get("link") or {}
            gmail = str(link.get("gmail_email") or "").strip()
            prof = str(link.get("profile_name") or ident.display_name or "").strip()
            if gmail:
                text = f"Linked: {gmail}" + (f" ({prof})" if prof else "")
            else:
                text = ident.handle or ident.display_name or "AI-PACS account"
            title = QLabel(text)
            title.setStyleSheet(f"color:{p['text']};font-size:13px;")
            status = QLabel("● Connected · Consultants + registry")
            status.setStyleSheet(f"color:{p['success']};font-size:11px;")
        else:
            title = QLabel("AI-PACS Consultation")
            title.setStyleSheet(f"color:{p['text']};font-size:13px;")
            status = QLabel("Not signed in")
            status.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        info.addWidget(title)
        info.addWidget(status)
        row.addLayout(info, 1)

        if ident is not None:
            btn = QPushButton("Disconnect")
            btn.setObjectName("danger")
            btn.clicked.connect(lambda: self._disconnect_aipacs_web(ident))
        else:
            btn = QPushButton("Sign in…")
            btn.clicked.connect(self._sign_in_aipacs_web)
        row.addWidget(btn)
        v.addWidget(card)
        return box

    def _sign_in_aipacs_web(self):
        try:
            from modules.Identity.ui.aipacs_web_dialog import AipacsWebSignInDialog

            self.close()
            dlg = AipacsWebSignInDialog(self._service(), parent=self.parent())
            dlg.exec()
        except Exception as exc:
            logger.warning("aipacs_web sign-in failed to open: %s", exc)

    def _disconnect_aipacs_web(self, ident):
        if ident is None:
            return
        if QMessageBox.question(
            self, "Disconnect AI-PACS Consultation",
            f"Disconnect {ident.handle or 'this account'}? Your AI-PACS login is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self._service().disconnect("aipacs_web", ident.subject_id)
        except Exception as exc:
            logger.warning("aipacs_web disconnect failed: %s", exc)
        self._refresh()

    # ── notifications + storage (ADR-0007: the hub) ───────────────────────────
    def _notifications_section(self) -> QWidget:
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        unread_total = 0
        rows: list[dict] = []
        try:
            from modules.cloud_consultation.notifications import inbox

            unread_total = inbox.unread_count()
            rows = inbox.list_notifications(status="unread", limit=5)
        except Exception as exc:
            logger.debug("notification fetch failed: %s", exc)
        caption = (f"Notifications ({unread_total} unread)" if unread_total
                   else "Notifications")
        v.addWidget(self._label(caption))

        if rows:
            for n in rows:
                v.addWidget(self._notification_row(n))
        else:
            none = QLabel("No new notifications")
            none.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
            v.addWidget(none)

        # Storage line — cached/empty render first; the worker fills it in.
        self._storage_label = QLabel("")
        self._storage_label.setVisible(False)
        v.addWidget(self._storage_label)
        self._populate_storage_line()

        v.addWidget(self._deep_link_button(section="requests"))
        return box

    def _notification_row(self, n: dict) -> QWidget:
        p = self._p
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};border-radius:9px;}}"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(9)
        kind = str(n.get("kind") or "")
        chip = QLabel(_KIND_LABELS.get(kind, "Notification"))
        chip.setStyleSheet(
            f"color:{p['accent']};border:1px solid {p['accent']};border-radius:8px;"
            f"padding:1px 7px;font-size:9px;font-weight:600;"
        )
        lay.addWidget(chip, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel(str(n.get("title") or "Notification"))
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{p['text']};font-size:12px;")
        col.addWidget(title)
        body = str(n.get("body") or "").strip()
        if body:
            sub = QLabel(body)
            sub.setWordWrap(True)
            sub.setStyleSheet(f"color:{p['text_muted']};font-size:10px;")
            col.addWidget(sub)
        lay.addLayout(col, 1)
        mark = QPushButton("Mark read")
        mark.setObjectName("ghost")
        mark.setStyleSheet("font-size:10px;padding:3px 8px;")
        mark.clicked.connect(lambda _=False, nid=n.get("id"): self._mark_read(nid))
        lay.addWidget(mark, 0, Qt.AlignTop)
        return card

    def _mark_read(self, notification_id):
        try:
            from modules.cloud_consultation.notifications import inbox

            if notification_id is not None:
                inbox.mark_read(int(notification_id))
        except Exception as exc:
            logger.debug("mark read failed: %s", exc)
        self._refresh()

    def _populate_storage_line(self):
        """Render the cached storage line; refresh the cache in the background.

        Never blocks the UI thread; shows nothing when not signed in to the
        consultation backend or when no quota is configured (fails silent)."""
        cached = _cached_storage()
        if cached is not None:
            self._render_storage_line(cached)
            return
        try:
            from modules.Identity.identity_service import IdentityService
            from modules.Identity.providers.aipacs_web import (
                find_aipacs_web_identity,
            )

            user = IdentityService.resolve_aipacs_user(self.auth_user)
            if find_aipacs_web_identity(user) is None:
                return  # not signed in — show nothing
            if self._storage_worker is not None and self._storage_worker.isRunning():
                return
            self._storage_worker = _StorageWorker(
                user, parent=QApplication.instance() or self)
            self._storage_worker.done.connect(self._render_storage_line)
            self._storage_worker.start()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("storage line skipped: %s", exc)

    def _render_storage_line(self, data):
        label = self._storage_label
        if label is None or not isinstance(data, dict):
            return
        try:
            from modules.education.online_consultation.dashboard_core import (
                format_bytes,
                storage_summary,
            )

            summary = storage_summary(data)
            if summary["fraction"] is None:
                return  # no quota configured — show nothing (gate fails open)
            p = self._p
            pct = int(round(100 * summary["fraction"]))
            used = format_bytes(summary["used"])
            quota = format_bytes(summary["quota"])
            if summary.get("alert"):
                label.setText(f"⛔ Storage {pct}% used ({used} of {quota}) — almost full")
                label.setStyleSheet(
                    f"color:{p['danger']};font-size:11px;font-weight:600;")
            elif summary["warn"]:
                label.setText(f"⚠ Storage {pct}% used ({used} of {quota})")
                label.setStyleSheet(
                    f"color:{p['warning']};font-size:11px;font-weight:600;")
            else:
                label.setText(f"Storage: {used} of {quota} used ({pct}%)")
                label.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            label.setVisible(True)
            self.adjustSize()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("storage line render failed: %s", exc)

    def _deep_link_button(self, section: str, caption: str = "Open Education ▸ Consultation") -> QPushButton:
        btn = QPushButton(caption)
        btn.setObjectName("ghost")
        btn.clicked.connect(
            lambda _=False, s=section: self._open_online_consultation(section=s))
        return btn

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

        # Creation stays one click away; ALL management lives in
        # Education ▸ Consultation (ADR-0007) — no inline inbox here anymore.
        new_btn = QPushButton("New consultation")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._new_consultation)
        v.addWidget(new_btn)
        v.addWidget(self._deep_link_button(section="consultations"))
        return box

    def _footer(self) -> QWidget:
        p = self._p
        f = QFrame()
        f.setStyleSheet(f"QFrame{{border-top:1px solid {p['border']};}}")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(0, 10, 0, 0)
        hint = QLabel("Manage everything in Education ▸ Consultation")
        hint.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        lay.addWidget(hint, 1)
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
            # Prefer the Education submodule (it provides study selection); the
            # bare compose dialog stays as a fallback.
            if self._open_online_consultation():
                return
            from .compose_dialog import ConsultationComposeDialog

            self.close()
            ConsultationComposeDialog(auth_user=self.auth_user, parent=self.parent()).exec()
        except Exception as exc:
            logger.warning("open compose dialog failed: %s", exc)

    def _open_online_consultation(self, section: str | None = None) -> bool:
        """Deep link into Education ▸ Consultation (ADR-0007 hub → destination)."""
        try:
            from modules.education.online_consultation.launcher import (
                open_online_consultation,
            )

            self.close()
            try:
                return bool(open_online_consultation(section=section))
            except TypeError:  # pragma: no cover - older launcher signature
                return bool(open_online_consultation())
        except Exception as exc:
            logger.warning("open online consultation failed: %s", exc)
            return False

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
