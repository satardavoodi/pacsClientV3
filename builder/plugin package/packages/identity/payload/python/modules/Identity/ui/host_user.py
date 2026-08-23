"""Find the workstation's logged-in user — ONE resolver for every module.

WHY THIS EXISTS (live bug 2026-08-22). The AI-PACS identity is stored per
workstation user: ``IdentityService.resolve_aipacs_user(auth_user)`` turns the
login dict into the key everything else is filed under. Get the dict, get the
right account; miss it, and the SAME signed-in operator resolves to ``"local"``
and every lookup comes back empty.

That is exactly what happened. Four places needed the login dict and each found
it its own way:

  * ``_hp_offline.py``        → ``self.mainwindow.host_window.auth_user``   ✓
  * ``patient_table_widget``  → ``self.window().auth_user``                 ✓
  * the Settings tab          → scan ``QApplication.topLevelWidgets()``     ✓
  * ``_hp_modules.open_aipacs_chat`` → ``getattr(self, 'auth_user', None)`` ✗

The fourth read an attribute ``HomePanelWidget`` never sets, so it always
passed ``None``. The chat console then looked up identity ``"local"``, found
nothing, and reported "Not signed in to AI-PACS" — on a workstation whose
Settings page, two clicks away, showed the same person signed in with chat
access granted. One console said signed out, the other said signed in, and
both were reading honestly from different keys.

So: one resolver, tried in the order most-specific-to-least, and every caller
uses it. Never raises — a widget tree that cannot answer yields ``None``, which
``resolve_aipacs_user`` maps to ``"local"`` on purpose.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _dict_or_none(value: Any) -> dict | None:
    return dict(value) if isinstance(value, dict) and value else None


def resolve_host_auth_user(widget: Any = None) -> dict | None:
    """Return the workstation login dict (``username``/``full_name``/``role``).

    ``widget`` is any live widget to start the search from; omit it to search
    the application's top-level windows only. Never raises.
    """
    # 1) The window this widget lives in — the pattern patient_table_widget
    #    uses, and the cheapest correct answer when there is a widget.
    if widget is not None:
        try:
            window = widget.window() if hasattr(widget, "window") else None
            found = _dict_or_none(getattr(window, "auth_user", None))
            if found:
                return found
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("host auth_user: window() lookup failed: %s", exc)

        # 2) The mainwindow → host_window chain (_hp_offline's pattern), for
        #    widgets parented inside the docked main window rather than the
        #    top-level shell.
        try:
            mainwindow = getattr(widget, "mainwindow", None)
            host_window = getattr(mainwindow, "host_window", None)
            found = _dict_or_none(getattr(host_window, "auth_user", None))
            if found:
                return found
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("host auth_user: host_window lookup failed: %s", exc)

    # 3) Any top-level window carrying the login — the broadest answer, and the
    #    one that works from a Settings page with no useful parent chain.
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return None
        for top in QApplication.topLevelWidgets():
            found = _dict_or_none(getattr(top, "auth_user", None))
            if found:
                return found
            ui = getattr(top, "ui", None)
            found = _dict_or_none(getattr(ui, "auth_user", None))
            if found:
                return found
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("host auth_user: top-level scan failed: %s", exc)
    return None


def resolve_host_aipacs_user(widget: Any = None) -> str:
    """The identity key for the signed-in workstation user, or ``"local"``.

    The one call a module should make when it needs to know which AI-PACS
    account this workstation is acting as.
    """
    try:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(resolve_host_auth_user(widget))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("host aipacs_user resolution failed: %s", exc)
        return "local"
