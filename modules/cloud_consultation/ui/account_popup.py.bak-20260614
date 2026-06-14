"""AccountPopup — the identity & notification hub under the top-right user pill
(ADR-0007; dropdown redesign per owner directive 2026-06-11).

Dropdown shape, top to bottom (exactly ONE identity action):

* **Connected Identity** — not connected → a single "Connect Google Account"
  button (the existing one-button Google dialog); connected → identity card
  (profile name, gmail, "Status: Connected ✓ (verified)") plus the DERIVED
  consultation status line (:mod:`derived_status`).
* **Manage Account** — opens :class:`ManageAccountDialog` (identity disconnect,
  hub configuration, storage usage, profile settings all live THERE — the hub
  section was removed from the dropdown entirely).
* **Notifications** — unread list + mark-read + deep link, unchanged. The
  storage line renders ONLY as a compact warning row at ≥80 % used; normal
  usage moved to Manage Account.

All blocking work (Google connect, storage fetch) runs on worker threads; the
popup renders instantly from cached/empty data and fills in when a worker
lands. Everything is defensive so a failure can never break the title bar.
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._theme import palette

logger = logging.getLogger(__name__)

# ADR-0007: friendly kind labels for the notification rows in the hub.
# (Fallback only — severity-tier rows prefer models.category_for, 2026-06-11.)
_KIND_LABELS = {
    "consultation_assigned": "Assignment",
    "invitation": "Invitation",
    "consultation_updated": "Update",
    "response_received": "Response",
    "upload_done": "Upload",
    "download_done": "Download",
    "sync_error": "Error",
    "upload_failed": "Urgent",
    "auth_failed": "Urgent",
    "quota_exceeded": "Urgent",
    "system_info": "System",
    "browser_info": "Browser",
    "education_info": "Education",
}

# One-shot QUOTA_EXCEEDED dedupe: the QApplication property holds the usage pct
# already notified, so re-opening the popup at the same level never re-notifies.
_QUOTA_NOTIFIED_ATTR = "_aipacs_quota_notified_pct"

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
    """Google (hub Drive) connect off the UI thread.

    Used by :class:`ManageAccountDialog` (the hub actions moved there, owner
    directive 2026-06-11); kept here so both UI surfaces share one worker."""

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
        # STAY-OPEN (live bug 2026-06-12): Qt.Popup auto-dismisses the instant the
        # parent window loses foreground. On this desktop background apps
        # (Grammarly/Chrome) steal focus constantly, so a Qt.Popup "flashes open
        # then closes" before the user can read it. A frameless Qt.Tool window does
        # NOT auto-close on deactivation; we add explicit outside-click dismissal
        # (see eventFilter) to keep the dropdown feel without the vanishing.
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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
        try:
            # Connected Identity — the ONE user-facing identity action (unified
            # login, owner directive 2026-06-11). Guarded so the popup renders
            # unchanged when the backend is not configured or the provider
            # module is unavailable.
            from modules.Identity.providers.aipacs_web import aipacs_web_configured

            if aipacs_web_configured():
                self._root.addWidget(self._connected_identity_section())
        except Exception as exc:
            logger.debug("connected identity section skipped: %s", exc)
        self._root.addWidget(self._manage_account_button())
        try:
            # Workflow v2 (2026-06-12): deep link to the Consultation source
            # page (module tab) right under the Manage Account line. Guarded —
            # renders nothing when the consultation module is unavailable.
            from modules.education.online_consultation import (
                online_consultation_available,
            )

            if online_consultation_available():
                self._root.addWidget(self._consultation_source_button())
        except Exception as exc:
            logger.debug("consultation source link skipped: %s", exc)
        try:
            from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

            if cloud_consultation_enabled():
                self._root.addWidget(self._notifications_section())
        except Exception as exc:
            logger.debug("notifications section skipped: %s", exc)
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

    def _connected_identity_section(self) -> QWidget:
        """Connected Identity — the dropdown's single identity block.

        Not connected → exactly one button ("Connect Google Account").
        Connected → identity card with the derived consultation status line;
        disconnect lives in :class:`ManageAccountDialog` (only a small
        "Manage" affordance here keeps the dropdown clean).
        """
        p = self._p
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._label("Connected Identity"))

        ident = self._aipacs_web_identity()
        if ident is None:
            btn = QPushButton("Connect Google Account")
            btn.setObjectName("primary")
            btn.clicked.connect(self._sign_in_aipacs_web)
            v.addWidget(btn)
            return box

        link = (getattr(ident, "extra", None) or {}).get("link") or {}
        gmail = str(link.get("gmail_email") or ident.handle or "").strip()
        prof = str(
            link.get("profile_name") or ident.display_name or ident.handle or ""
        ).strip() or "Connected account"

        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {p['border']};border-radius:9px;}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
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
        info.addWidget(self._consultation_status_label())
        row.addLayout(info, 1)

        manage = QPushButton("Manage")
        manage.setObjectName("ghost")
        manage.setStyleSheet("font-size:11px;padding:4px 10px;")
        manage.clicked.connect(self._open_manage_account)
        row.addWidget(manage, 0, Qt.AlignTop)
        v.addWidget(card)
        return box

    def _consultation_status_label(self) -> QLabel:
        """The derived consultation-mode line (Qt-free logic, guarded)."""
        p = self._p
        text = ""
        try:
            from .derived_status import consultation_capabilities

            from modules.Identity.identity_service import IdentityService

            caps = consultation_capabilities(
                IdentityService.resolve_aipacs_user(self.auth_user),
                identity_linked=True,  # we are rendering a linked identity card
            )
            text = caps["status_text"]
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("derived consultation status failed: %s", exc)
        lbl = QLabel(text)
        lbl.setVisible(bool(text))
        lbl.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        return lbl

    def _manage_account_button(self) -> QPushButton:
        btn = QPushButton("Manage Account")
        btn.setObjectName("ghost")
        btn.clicked.connect(self._open_manage_account)
        return btn

    def _consultation_source_button(self) -> QPushButton:
        btn = QPushButton("Open Consultation source")
        btn.setObjectName("ghost")
        btn.clicked.connect(self._open_consultation_source)
        return btn

    def _open_consultation_source(self):
        """Workflow v2: open the AI-PACS Consultation source page module tab."""
        try:
            from modules.education.online_consultation.launcher import (
                open_consultation_source,
            )

            self.close()
            open_consultation_source()
        except Exception as exc:
            logger.warning("open consultation source failed: %s", exc)

    def _open_manage_account(self):
        try:
            from .manage_account_dialog import ManageAccountDialog

            self.close()
            ManageAccountDialog(auth_user=self.auth_user, parent=self.parent()).exec()
        except Exception as exc:
            logger.warning("open manage account failed: %s", exc)

    def _sign_in_aipacs_web(self):
        # MODELESS (live bug 2026-06-12): a modal exec() grabs input and blocks
        # the docked browser where the Google consent page renders. open_signin
        # _dialog shows it non-modally and delivers the result via callback.
        #
        # INSTANT UPDATE (2026-06-12): on success we refresh the title-bar
        # account area in place (pill badge + poller re-arm + reopen the
        # Connected card) so the signed-in state shows without a manual reopen.
        try:
            from modules.Identity.ui.aipacs_web_dialog import open_signin_dialog

            parent = self.parent()
            auth_user = getattr(self, "auth_user", None)

            def _on_success(_identity=None):
                try:
                    from modules.cloud_consultation.ui.account_hook import (
                        refresh_account_area_after_connect,
                    )

                    refresh_account_area_after_connect(auth_user)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("post-connect account refresh skipped: %s", exc)

            self.close()
            open_signin_dialog(self._service(), parent=parent, on_success=_on_success)
        except Exception as exc:
            logger.warning("aipacs_web sign-in failed to open: %s", exc)

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
            # Latest 4, unread first then read, newest first (2026-06-11).
            rows = inbox.latest_notifications(limit=4)
        except Exception as exc:
            logger.debug("notification fetch failed: %s", exc)
        caption = (f"Notifications ({unread_total} unread)" if unread_total
                   else "Notifications")
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(self._label(caption), 1)
        if unread_total:
            clear = QPushButton("Clear all")
            clear.setObjectName("ghost")
            clear.setStyleSheet("font-size:10px;padding:3px 9px;")
            clear.clicked.connect(self._clear_all_notifications)
            head.addWidget(clear, 0)
        v.addLayout(head)

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
        """One feed row, styled by severity tier (derived from kind, 2026-06-11):

        CRITICAL → danger accent + bold + "●" badge ("Urgent" chip);
        HIGH → accent + bold + category chip (e.g. "Consultation");
        NORMAL → the standard row; LOW → muted, smaller.
        """
        p = self._p
        kind = str(n.get("kind") or "")
        prio = str(n.get("priority") or "")
        if not prio:
            try:
                from modules.cloud_consultation.notifications.models import priority_for

                prio = priority_for(kind).value
            except Exception:  # pragma: no cover - defensive
                prio = "normal"
        try:
            from modules.cloud_consultation.notifications.models import category_for

            category = str(n.get("category") or category_for(kind))
        except Exception:  # pragma: no cover - defensive
            category = _KIND_LABELS.get(kind, "Notification")
        is_unread = (str(n.get("status") or "unread") == "unread")

        card = QFrame()
        border = p["border"]
        if prio == "critical":
            border = "rgba(248,113,113,0.45)"
        card.setStyleSheet(
            f"QFrame{{background:{p['surface2']};border:1px solid {border};border-radius:9px;}}"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(9)

        chip_color = {"critical": p["danger"], "high": p["accent"],
                      "low": p["text_muted"]}.get(prio, p["accent"])
        chip_text = ("● " + category) if prio == "critical" else category
        chip = QLabel(chip_text)
        chip.setStyleSheet(
            f"color:{chip_color};border:1px solid {chip_color};border-radius:8px;"
            f"padding:1px 7px;font-size:9px;font-weight:600;"
        )
        lay.addWidget(chip, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel(str(n.get("title") or "Notification"))
        title.setWordWrap(True)
        if prio == "critical":
            title.setStyleSheet(f"color:{p['danger']};font-size:12px;font-weight:700;")
        elif prio == "high":
            title.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:700;")
        elif prio == "low":
            title.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        else:
            title.setStyleSheet(f"color:{p['text']};font-size:12px;")
        col.addWidget(title)
        body = str(n.get("body") or "").strip()
        if body:
            sub = QLabel(body)
            sub.setWordWrap(True)
            sub.setStyleSheet(
                f"color:{p['text_muted']};font-size:{9 if prio == 'low' else 10}px;")
            col.addWidget(sub)
        lay.addLayout(col, 1)
        if is_unread:
            mark = QPushButton("Mark read")
            mark.setObjectName("ghost")
            mark.setStyleSheet("font-size:10px;padding:3px 8px;")
            mark.clicked.connect(lambda _=False, nid=n.get("id"): self._mark_read(nid))
            lay.addWidget(mark, 0, Qt.AlignTop)
        else:
            seen = QLabel("read")
            seen.setStyleSheet(f"color:{p['text_muted']};font-size:9px;")
            lay.addWidget(seen, 0, Qt.AlignTop)
        return card

    def _clear_all_notifications(self):
        """'Clear all' = mark every unread read; the feed keeps recent history."""
        try:
            from modules.cloud_consultation.notifications import inbox

            inbox.clear_all()
        except Exception as exc:
            logger.debug("clear all failed: %s", exc)
        self._refresh()

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
            # Owner directive 2026-06-11: the dropdown shows storage ONLY as a
            # compact warning row (≥80 % warn / ≥95 % alert). Normal usage
            # lives in Manage Account ▸ Storage Usage.
            if summary.get("alert"):
                label.setText(f"⛔ Storage {pct}% used ({used} of {quota}) — almost full")
                label.setStyleSheet(
                    f"color:{p['danger']};font-size:11px;font-weight:600;")
                self._notify_quota_alert_once(pct, used, quota)
            elif summary["warn"]:
                label.setText(f"⚠ Storage {pct}% used ({used} of {quota})")
                label.setStyleSheet(
                    f"color:{p['warning']};font-size:11px;font-weight:600;")
            else:
                return  # below the warn threshold — nothing in the dropdown
            label.setVisible(True)
            self.adjustSize()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("storage line render failed: %s", exc)

    def _notify_quota_alert_once(self, pct: int, used: str, quota: str):
        """One-shot CRITICAL QUOTA_EXCEEDED at the popup's alert state (≥95 %).

        Deduped via a QApplication property holding the last notified pct, so
        the same usage level never notifies twice in a session (best-effort,
        never raises — 2026-06-11)."""
        try:
            app = QApplication.instance()
            if app is None:
                return
            if getattr(app, _QUOTA_NOTIFIED_ATTR, None) == pct:
                return
            from modules.cloud_consultation.notifications import inbox
            from modules.cloud_consultation.notifications.models import NotificationKind

            inbox.notify(
                NotificationKind.QUOTA_EXCEEDED,
                body=f"Cloud storage {pct}% used ({used} of {quota}). "
                     "Free space in Education ▸ Consultation ▸ Storage.",
            )
            setattr(app, _QUOTA_NOTIFIED_ATTR, pct)
        except Exception as exc:  # pragma: no cover - best-effort by contract
            logger.debug("quota notification skipped: %s", exc)

    def _deep_link_button(self, section: str, caption: str = "Open Education ▸ Consultation") -> QPushButton:
        btn = QPushButton(caption)
        btn.setObjectName("ghost")
        btn.clicked.connect(
            lambda _=False, s=section: self._open_online_consultation(section=s))
        return btn

    def _footer(self) -> QWidget:
        # No "Sign Out" row: the workstation/server session has no sign-out
        # action in this popup today, and the owner directive says omit rather
        # than invent one. Hub teardown lives in ManageAccountDialog.
        p = self._p
        f = QFrame()
        f.setStyleSheet(f"QFrame{{border-top:1px solid {p['border']};}}")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(0, 10, 0, 0)
        hint = QLabel("Manage everything in Education ▸ Consultation")
        hint.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        lay.addWidget(hint, 1)
        return f

    # ── small builders ─────────────────────────────────────────────────────────
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{self._p['text_muted']};font-size:11px;font-weight:500;")
        return lbl

    # ── actions ──────────────────────────────────────────────────────────────
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
        # Bring the popup forward and install outside-click dismissal so it stays
        # open (it is a Qt.Tool, not a Qt.Popup) until the user clicks elsewhere.
        try:
            self.activateWindow()
        except Exception:  # pragma: no cover - defensive
            pass
        self._install_outside_dismiss()

    # ── stay-open dropdown dismissal (replaces Qt.Popup auto-close) ────────────
    def _install_outside_dismiss(self):
        try:
            from PySide6.QtWidgets import QApplication

            if getattr(self, "_outside_filter_installed", False):
                return
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._outside_filter_installed = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("outside-dismiss install failed: %s", exc)

    def _remove_outside_dismiss(self):
        try:
            from PySide6.QtWidgets import QApplication

            if not getattr(self, "_outside_filter_installed", False):
                return
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._outside_filter_installed = False
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("outside-dismiss remove failed: %s", exc)

    def eventFilter(self, obj, event):
        try:
            from PySide6.QtCore import QEvent

            if event.type() == QEvent.MouseButtonPress and self.isVisible():
                gp = event.globalPosition().toPoint() if hasattr(event, "globalPosition") \
                    else event.globalPos()
                if not self.frameGeometry().contains(gp):
                    # A press anywhere outside the popup dismisses it (dropdown feel)
                    # — but NOT a focus steal by a background app, which is the bug
                    # Qt.Popup had. Re-clicking the pill toggles via account_hook.
                    self.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("outside-dismiss filter error: %s", exc)
        return False  # never consume — let the click reach its target

    def closeEvent(self, event):
        self._remove_outside_dismiss()
        try:
            super().closeEvent(event)
        except Exception:  # pragma: no cover - defensive
            pass

    def hideEvent(self, event):
        self._remove_outside_dismiss()
        try:
            super().hideEvent(event)
        except Exception:  # pragma: no cover - defensive
            pass
