"""Additive account-area hook.

Attaches a small popup menu ("Connected Accounts…") to the EXISTING top-right
user container, without altering the server-user labels or any existing behaviour.
The click handler opens :class:`IdentityPanel`.

This is imported lazily and only when ``identity_module_enabled()`` is True, behind a
try/except at the call site in ``mainwindow_ui.py`` — so a problem here can never
break the title bar, and with the flag OFF nothing here runs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _open_identity_panel(auth_user, parent_window):
    from modules.Identity.identity_service import IdentityService
    from modules.Identity.ui.identity_panel import IdentityPanel

    user_key = IdentityService.resolve_aipacs_user(auth_user)
    service = IdentityService(user_key)
    dialog = IdentityPanel(service, parent=parent_window)
    dialog.exec()


def attach_identity_account_menu(user_container, auth_user=None, parent_window=None):
    """Make ``user_container`` open a small account menu on click. Idempotent."""
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QMenu

    if getattr(user_container, "_identity_menu_filter", None) is not None:
        return  # already attached

    user_container.setCursor(Qt.PointingHandCursor)
    existing_tip = user_container.toolTip()
    user_container.setToolTip(existing_tip or "Account & connected identities")

    class _AccountMenuFilter(QObject):
        def eventFilter(self, obj, event):
            try:
                if event.type() == QEvent.MouseButtonPress:
                    self._show_menu()
            except Exception as exc:  # never disturb the title bar
                logger.debug("identity account menu error: %s", exc)
            return False  # do not consume — preserve any existing behaviour

        def _show_menu(self):
            menu = QMenu(user_container)
            act = menu.addAction("Connected Accounts…")
            act.triggered.connect(
                lambda: _open_identity_panel(auth_user, parent_window or user_container.window())
            )
            menu.exec(user_container.mapToGlobal(user_container.rect().bottomLeft()))

    flt = _AccountMenuFilter(user_container)
    user_container.installEventFilter(flt)
    # Keep a strong reference so the filter is not garbage-collected.
    user_container._identity_menu_filter = flt
