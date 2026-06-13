"""Attach the AccountPopup (and the v2 notification badge) to the top-right user pill.

Replaces the Phase-1 bare "Connected Accounts…" menu with the richer popup. Installed
from ``mainwindow_ui.py`` behind the identity feature flag, inside a try/except, so it
can never break the title bar and is a no-op when the flag is off.

Workflow v2 (2026-06-12): a small red numeric badge on the pill shows
``pending received consultations + unread HIGH/CRITICAL notifications``
(Qt-free count in :mod:`badge_core`). The count is computed on a throttled
QThread worker with a QApplication-level cache (≥60 s, same pattern as the
popup's storage cache); it renders NOTHING when zero or not signed in, and the
pill's click behaviour is untouched (the badge is a transparent-for-mouse
child label).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# (monotonic_ts, count) cached on the QApplication object — survives popup and
# badge teardown; ≥60 s between registry fetches.
_BADGE_CACHE_ATTR = "_aipacs_pill_badge_cache"
_BADGE_CACHE_TTL_SEC = 60.0
_BADGE_TIMER_INTERVAL_MS = 90_000

# QApplication-level handles so a successful identity connect (fired from the
# sign-in dialog's on_success callback) can live-update the title-bar account
# area without a manual reopen (2026-06-12).
_ACCOUNT_PILL_ATTR = "_aipacs_account_pill"
_ACCOUNT_AUTH_ATTR = "_aipacs_account_auth_user"


def attach_account_popup(user_container, auth_user=None, parent_window=None):
    """Open the AccountPopup when ``user_container`` is clicked. Idempotent."""
    from PySide6.QtCore import QEvent, QObject, Qt

    if getattr(user_container, "_account_popup_filter", None) is not None:
        return

    user_container.setCursor(Qt.PointingHandCursor)
    user_container.setToolTip(user_container.toolTip() or "Account, connected identities & consultations")

    class _PopupFilter(QObject):
        def eventFilter(self, obj, event):
            try:
                if event.type() == QEvent.MouseButtonPress:
                    self._open()
                elif event.type() == QEvent.Resize:
                    _position_pill_badge(user_container)
            except Exception as exc:
                logger.debug("account popup open error: %s", exc)
            return False  # do not consume — preserve existing behaviour

        def _open(self):
            # DEFER (live bug 2026-06-12): the popup uses Qt.Popup, which grabs
            # the mouse and auto-closes on the first press/release that lands
            # outside it. Opening it synchronously from the pill's
            # MouseButtonPress means the in-flight release (delivered at the
            # pill, i.e. outside the popup) instantly dismisses it — the popup
            # "flashes open then closes". Opening on the next clean event-loop
            # turn lets the press/release cycle finish first, so the grab is
            # stable. Also collapses a still-open popup (click = toggle).
            from PySide6.QtCore import QTimer

            existing = getattr(user_container, "_account_popup", None)
            if existing is not None:
                try:
                    if existing.isVisible():
                        existing.close()
                        user_container._account_popup = None
                        return
                except Exception:  # pragma: no cover - defensive
                    pass
            QTimer.singleShot(0, self._open_now)

        def _open_now(self):
            from .account_popup import AccountPopup

            popup = AccountPopup(auth_user=auth_user, parent=parent_window or user_container.window())
            popup.show_under(user_container)
            user_container._account_popup = popup   # keep a reference alive

    flt = _PopupFilter(user_container)
    user_container.installEventFilter(flt)
    user_container._account_popup_filter = flt
    # Expose the opener + register the pill on the QApplication so a successful
    # sign-in can reopen the Connected card and refresh the badge instantly.
    user_container._account_popup_open = flt._open
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            setattr(app, _ACCOUNT_PILL_ATTR, user_container)
            setattr(app, _ACCOUNT_AUTH_ATTR, auth_user)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("account pill registration skipped: %s", exc)

    # ── v2 pill badge (guarded; never breaks the title bar) ───────────────────
    try:
        _attach_pill_badge(user_container, auth_user)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("pill badge attach skipped: %s", exc)

    # Start the consultation notification poller for an already-connected Google
    # identity (idempotent; no-op when the cloud-consultation flag is off or no
    # identity is linked yet — the Education page re-arms it after a connect).
    try:
        from modules.cloud_consultation.notifications.autostart import (
            ensure_consultation_poller,
        )

        ensure_consultation_poller(auth_user)
    except Exception as exc:  # never break the title bar
        logger.debug("consultation poller autostart skipped: %s", exc)


# ── v2 pill badge ──────────────────────────────────────────────────────────────
def _badge_cached_count():
    """The cached badge count, or None when stale/absent. Never raises."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        cached = getattr(app, _BADGE_CACHE_ATTR, None) if app is not None else None
        if not cached:
            return None
        ts, count = cached
        if (time.monotonic() - ts) > _BADGE_CACHE_TTL_SEC:
            return None
        return int(count)
    except Exception:  # pragma: no cover - defensive
        return None


def _badge_store_count(count):
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            setattr(app, _BADGE_CACHE_ATTR, (time.monotonic(), int(count)))
    except Exception:  # pragma: no cover - defensive
        pass


def _compute_badge_count(aipacs_user: str) -> int:
    """BLOCKING badge computation (worker thread only). Returns 0 when unsigned
    or anything fails — the badge then simply renders nothing."""
    from .badge_core import count_pending_received

    inbox_rows: list = []
    try:
        from modules.Identity.providers.aipacs_web import get_aipacs_web_client

        client = get_aipacs_web_client(aipacs_user)
        if client is None:
            return 0  # unsigned → render nothing
        inbox_rows = list(client.list_consultations(box="inbox"))
    except Exception as exc:
        logger.debug("badge registry fetch failed: %s", exc)
        inbox_rows = []
    notifications: list = []
    try:
        from modules.cloud_consultation.notifications import inbox
        from modules.cloud_consultation.notifications.models import priority_for

        for row in inbox.list_notifications(status="unread", limit=100) or []:
            row = dict(row or {})
            row.setdefault("priority", priority_for(row.get("kind") or "").value)
            notifications.append(row)
    except Exception as exc:
        logger.debug("badge notification fetch failed: %s", exc)
    return count_pending_received(inbox_rows, notifications)


def _attach_pill_badge(user_container, auth_user):
    """Create the badge label + throttled refresh timer on the pill. Idempotent."""
    if getattr(user_container, "_pill_badge", None) is not None:
        return
    from PySide6.QtCore import Qt, QThread, QTimer, Signal
    from PySide6.QtWidgets import QLabel

    badge = QLabel("", user_container)
    badge.setObjectName("PillNotificationBadge")
    # Transparent for mouse events: the pill's click → popup behaviour and the
    # existing event filter are untouched.
    badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    badge.setAlignment(Qt.AlignCenter)
    badge.setFixedSize(18, 18)
    badge.setStyleSheet(
        "QLabel#PillNotificationBadge { background:#ef4444; color:#ffffff;"
        " border-radius:9px; font-size:10px; font-weight:700; border:none; }"
    )
    badge.hide()
    user_container._pill_badge = badge

    class _BadgeWorker(QThread):
        done = Signal(int)

        def __init__(self, user, parent=None):
            super().__init__(parent)
            self._user = user

        def run(self):  # noqa: D401 - best-effort by contract
            count = 0
            try:
                count = _compute_badge_count(self._user)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("badge computation failed: %s", exc)
            _badge_store_count(count)
            self.done.emit(int(count))

    def _render(count):
        try:
            from .badge_core import badge_text

            text = badge_text(count)
            if not text:
                badge.hide()
                return
            badge.setText(text)
            _position_pill_badge(user_container)
            badge.show()
            badge.raise_()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("badge render failed: %s", exc)

    def _refresh():
        try:
            cached = _badge_cached_count()
            if cached is not None:
                _render(cached)
                return
            worker = getattr(user_container, "_pill_badge_worker", None)
            if worker is not None and worker.isRunning():
                return
            from modules.Identity.identity_service import IdentityService
            from PySide6.QtWidgets import QApplication

            user = IdentityService.resolve_aipacs_user(auth_user)
            owner = QApplication.instance() or user_container
            worker = _BadgeWorker(user, owner)
            worker.done.connect(_render)
            worker.finished.connect(worker.deleteLater)
            user_container._pill_badge_worker = worker
            worker.start()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("badge refresh skipped: %s", exc)

    timer = QTimer(user_container)
    timer.setInterval(_BADGE_TIMER_INTERVAL_MS)
    timer.timeout.connect(_refresh)
    timer.start()
    user_container._pill_badge_timer = timer
    # Expose a force-refresh (bypassing the 5-min cache) so a successful
    # identity connect can update the pill instantly (2026-06-12).
    user_container._pill_badge_force_refresh = _force_refresh_factory(_refresh)
    _refresh()


def _force_refresh_factory(refresh):
    """Return a callable that clears the badge cache then re-runs ``refresh``."""
    def _force():
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                setattr(app, _BADGE_CACHE_ATTR, None)  # drop the cached count
        except Exception:  # pragma: no cover - defensive
            pass
        refresh()
    return _force


def refresh_account_area_after_connect(auth_user=None) -> None:
    """Live-update the title-bar account area after a successful identity connect.

    Force-refreshes the pill badge, re-arms the consultation poller for the new
    identity, and reopens the account popup so the "Connected Identity" card
    shows the linked Gmail immediately — no manual reopen. Never raises (it is a
    best-effort UI nicety wired to the sign-in ``on_success`` callback).
    """
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        container = getattr(app, _ACCOUNT_PILL_ATTR, None)
        # weakref may be stored; resolve if callable.
        if callable(container):
            container = container()
        if container is None:
            return
        # 1) Force the pill badge to refresh now (drops the 5-min cache).
        force = getattr(container, "_pill_badge_force_refresh", None)
        if callable(force):
            force()
        # 2) Re-arm the poller for the freshly linked identity (idempotent).
        try:
            from modules.cloud_consultation.notifications.autostart import (
                ensure_consultation_poller,
            )

            ensure_consultation_poller(auth_user if auth_user is not None
                                       else getattr(app, _ACCOUNT_AUTH_ATTR, None))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("poller re-arm after connect skipped: %s", exc)
        # 3) Reopen the account popup so the Connected card is visible at once.
        opener = getattr(container, "_account_popup_open", None)
        if callable(opener):
            from PySide6.QtCore import QTimer as _QT

            _QT.singleShot(0, opener)  # next clean event-loop turn
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("refresh_account_area_after_connect skipped: %s", exc)


def _position_pill_badge(user_container):
    """Pin the badge to the pill's top-right corner. Never raises."""
    try:
        badge = getattr(user_container, "_pill_badge", None)
        if badge is None:
            return
        badge.move(max(0, user_container.width() - badge.width() - 8), 3)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("badge positioning failed: %s", exc)
