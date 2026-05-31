"""Attach the AccountPopup to the existing top-right user pill.

Replaces the Phase-1 bare "Connected Accounts…" menu with the richer popup. Installed
from ``mainwindow_ui.py`` behind the identity feature flag, inside a try/except, so it
can never break the title bar and is a no-op when the flag is off.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
            except Exception as exc:
                logger.debug("account popup open error: %s", exc)
            return False  # do not consume — preserve existing behaviour

        def _open(self):
            from .account_popup import AccountPopup

            popup = AccountPopup(auth_user=auth_user, parent=parent_window or user_container.window())
            popup.show_under(user_container)
            user_container._account_popup = popup   # keep a reference alive

    flt = _PopupFilter(user_container)
    user_container.installEventFilter(flt)
    user_container._account_popup_filter = flt
