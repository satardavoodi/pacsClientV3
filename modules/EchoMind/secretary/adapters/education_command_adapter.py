"""EducationCommandAdapter — voice-command access to the Education module.

2026-06-11: lets the Secretary/EchoMind voice assistant open and navigate
the Education module through module-level calls (NEVER synthetic clicks):

* ``open_consultation``        — Education → Online Consultation tab
* ``show_consultant_profiles`` — Online Consultation → Consultant Directory
* ``open_courses``             — Education → My Courses tab
* ``open_case_of_day``         — Education → Case of the Day tab
* ``search_education``         — Education → Library tab + search query

(``open_education`` itself stays on the existing ModuleCommandAdapter.)

The adapter is constructed with a single ``open_education`` launcher —
``callable(entities: dict) -> EducationModuleRedesigned | None`` — supplied
by the home panel (``HomePanelWidget._launcher_education``). The launcher
is idempotent (activate-or-create singleton tab); each action resolves the
live widget through it, then uses the widget's own navigation API
(``tab_widget.setCurrentWidget`` on the page attributes, and
``show_online_consultation(section=...)`` for the flag-gated consultation
tab — see the triple gate in docs/pipelines/online-consultation-education.md).

Failure modes are typed, recoverable envelopes — ``MODULE_UNAVAILABLE``
when Education can't open, ``CONSULTATION_UNAVAILABLE`` when the Online
Consultation tab is gated off — never a silent failure.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)

# action_id → handler method name
EDUCATION_ACTIONS: dict[str, str] = {
    "open_consultation":        "open_consultation",
    "show_consultant_profiles": "show_consultant_profiles",
    "open_courses":             "open_courses",
    "open_case_of_day":         "open_case_of_day",
    "search_education":         "search_education",
}


def _err(action: str, code: str, msg: str) -> CommandResult:
    return CommandResult(ok=False, action=action, error_code=code, message=msg)


def _unavailable(action: str) -> CommandResult:
    return _err(
        action, "MODULE_UNAVAILABLE",
        "The Education module is not available on this workstation "
        "(not installed, disabled, or it failed to open).",
    )


class EducationCommandAdapter:
    """Education navigation bound to the home panel's singleton Education tab."""

    def __init__(
        self,
        open_education_launcher: Optional[Callable[[dict], Any]] = None,
    ) -> None:
        self._launch = open_education_launcher or (lambda _entities: None)

    # ── helpers ──────────────────────────────────────────────────────
    def _widget(self, entities: Optional[dict] = None):
        """Open/activate the Education tab and return the live widget (or None)."""
        try:
            widget = self._launch(dict(entities or {}))
        except Exception:
            logger.exception("education adapter: launcher raised")
            return None
        # The launcher must return the EducationModuleRedesigned instance
        # (it exposes tab_widget + the page attributes). Anything else is
        # treated as unavailable so we never poke a foreign widget.
        if widget is None or not hasattr(widget, "tab_widget"):
            return None
        return widget

    def _switch_to_page(self, action: str, page_attr: str,
                        ok_msg: str) -> CommandResult:
        widget = self._widget()
        if widget is None:
            return _unavailable(action)
        page = getattr(widget, page_attr, None)
        if page is None:
            return _err(action, "SECTION_UNAVAILABLE",
                        f"Education section '{page_attr}' is not available.")
        try:
            widget.tab_widget.setCurrentWidget(page)
        except Exception as exc:
            logger.exception("education adapter: %s failed", action)
            return _err(action, "ACTION_FAILED", f"{action} failed: {exc}")
        logger.info("education adapter: %s ok", action)
        return CommandResult(ok=True, action=action, message=ok_msg)

    # ── action: open_consultation ────────────────────────────────────
    def open_consultation(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._open_consultation_section(
            "open_consultation",
            str((plan.entities or {}).get("section") or "") or None,
            "Online Consultation opened.",
        )

    # ── action: show_consultant_profiles ─────────────────────────────
    def show_consultant_profiles(self, plan: CommandPlan,
                                 state: dict) -> CommandResult:
        return self._open_consultation_section(
            "show_consultant_profiles", "directory",
            "Consultant directory opened.",
        )

    def _open_consultation_section(self, action: str, section: Optional[str],
                                   ok_msg: str) -> CommandResult:
        widget = self._widget()
        if widget is None:
            return _unavailable(action)
        page = getattr(widget, "online_consultation_page", None)
        if page is None:
            # Triple gate (identity + cloud_consultation flags + module
            # registry) left the tab unbuilt — tell the user plainly.
            return _err(
                action, "CONSULTATION_UNAVAILABLE",
                "Online Consultation is not enabled on this workstation.",
            )
        try:
            widget.show_online_consultation(section=section)
        except Exception as exc:
            logger.exception("education adapter: %s failed", action)
            return _err(action, "ACTION_FAILED", f"{action} failed: {exc}")
        logger.info("education adapter: %s ok section=%s", action, section)
        return CommandResult(ok=True, action=action, message=ok_msg,
                             data={"section": section} if section else None)

    # ── action: open_courses ─────────────────────────────────────────
    def open_courses(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._switch_to_page("open_courses", "mycourses_page",
                                    "My Courses opened.")

    # ── action: open_case_of_day ─────────────────────────────────────
    def open_case_of_day(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._switch_to_page("open_case_of_day", "case_of_day_tab",
                                    "Case of the Day opened.")

    # ── action: search_education ─────────────────────────────────────
    def search_education(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        query = str(ent.get("query") or ent.get("text") or "").strip()
        if not query:
            return _err("search_education", "MISSING_QUERY",
                        "search_education requires entities.query.")
        widget = self._widget()
        if widget is None:
            return _unavailable("search_education")
        page = getattr(widget, "library_page", None)
        search_input = getattr(page, "search_input", None) if page else None
        if page is None or search_input is None:
            return _err("search_education", "SECTION_UNAVAILABLE",
                        "Education library search is not available.")
        try:
            widget.tab_widget.setCurrentWidget(page)
            # setText fires textChanged → LibraryPage.on_search_changed
            # (debounced apply_filters) — the exact path typing takes.
            search_input.setText(query)
        except Exception as exc:
            logger.exception("education adapter: search_education failed")
            return _err("search_education", "ACTION_FAILED",
                        f"Education search failed: {exc}")
        logger.info("education adapter: search_education ok query=%r", query)
        return CommandResult(
            ok=True, action="search_education",
            message=f"Searching Education library for '{query}'.",
            data={"query": query},
        )


__all__ = ["EducationCommandAdapter", "EDUCATION_ACTIONS"]
