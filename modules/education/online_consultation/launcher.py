"""Open the Education module's Online Consultation tab from anywhere.

Used by the account popup (top-right user pill) so "Consultations" leads to the
proper Education submodule instead of a detached dialog. Defensive throughout —
if the Education module can't be located, callers fall back to their own dialogs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _find_home_panel():
    """Locate the live HomePanelWidget (owns ``open_education_module``)."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        # Fast path: any top-level exposing ui.home_widget (ControlPanelInterface).
        for w in QApplication.topLevelWidgets():
            ui = getattr(w, "ui", None)
            hw = getattr(ui, "home_widget", None) or getattr(w, "home_widget", None)
            if hw is not None and hasattr(hw, "open_education_module"):
                return hw
        # Fallback: scan all widgets once (user-initiated click; acceptable).
        for w in QApplication.allWidgets():
            if w.__class__.__name__ == "HomePanelWidget" and hasattr(
                w, "open_education_module"
            ):
                return w
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("home panel lookup failed: %s", exc)
    return None


def open_online_consultation() -> bool:
    """Open (or activate) the Education tab and switch to Online Consultation.

    Returns True when the Education module was reached.
    """
    home = _find_home_panel()
    if home is None:
        logger.info("online consultation launcher: home panel not found")
        return False
    try:
        home.open_education_module()
    except Exception as exc:
        logger.warning("open_education_module failed: %s", exc)
        return False

    try:
        from PySide6.QtCore import QTimer

        from modules.education.education_module_redesigned import (
            EducationModuleRedesigned,
        )

        def _switch():
            inst = EducationModuleRedesigned.last_instance()
            if inst is not None:
                try:
                    inst.show_online_consultation()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("show_online_consultation failed: %s", exc)

        # The education widget may have been created this very call; let the tab
        # finish constructing first.
        QTimer.singleShot(0, _switch)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("online consultation tab switch skipped: %s", exc)
    return True
