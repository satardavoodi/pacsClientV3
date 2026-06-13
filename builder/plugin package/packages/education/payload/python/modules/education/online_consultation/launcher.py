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


def open_consultation_source() -> bool:
    """Open (or activate) the "AI-PACS Consultation" source page module tab.

    Workflow v2 (2026-06-12): the page opens through the home panel's module-tab
    mechanism (``HomePanelWidget.open_consultation_source`` →
    ``activate_or_create_module_tab`` — the exact Web Browser pattern). The
    PACS server-selection/socket pipeline is untouched by design. Returns True
    when the tab was reached. Never raises.
    """
    try:
        from modules.education.online_consultation import (
            online_consultation_available,
        )

        if not online_consultation_available():
            logger.info(
                "consultation source launcher: feature unavailable (gate off)")
            return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("availability pre-check failed: %s", exc)

    home = _find_home_panel()
    if home is None or not hasattr(home, "open_consultation_source"):
        logger.info("consultation source launcher: home panel not found")
        return False
    try:
        return home.open_consultation_source() is not None
    except Exception as exc:
        logger.warning("open_consultation_source failed: %s", exc)
        return False


def open_online_consultation(section: str | None = None) -> bool:
    """Open (or activate) the Education tab and switch to Online Consultation.

    ``section`` optionally deep-links into one of the ADR-0007 sections
    (``directory`` / ``profile`` / ``consultations`` / ``requests`` /
    ``storage`` / ``shared``). Returns True when the Education module was
    reached.
    """
    try:
        from modules.education.online_consultation import online_consultation_available

        if not online_consultation_available():
            # ADR-0003: mirror the printing-module pattern — explain instead of
            # silently doing nothing when the module is not installed/enabled.
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox

                if QApplication.instance() is not None:
                    QMessageBox.information(
                        None,
                        "Online Consultation",
                        "The Online Consultation module is not installed or not "
                        "enabled for this workstation.",
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("not-installed notice skipped: %s", exc)
            logger.info("online consultation launcher: feature unavailable (gate off)")
            return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("availability pre-check failed: %s", exc)

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
                    inst.show_online_consultation(section=section)
                except TypeError:  # pragma: no cover - older module signature
                    inst.show_online_consultation()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("show_online_consultation failed: %s", exc)

        # The education widget may have been created this very call; let the tab
        # finish constructing first.
        QTimer.singleShot(0, _switch)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("online consultation tab switch skipped: %s", exc)
    return True
