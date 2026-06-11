"""bus_factory — one-stop CommandBus wiring used by:

* ``main.py`` at app startup (production path)
* test fixtures (with mocks)
* the AI-agent SDK

This is the **single integration point** between the running app and
the unified Command Layer. Callers that want to extend the bus
register additional adapters; callers that want to read state
introspect ``bus.actions()``.

Design notes
------------

- Every parameter is optional. ``build_command_bus()`` with no args
  returns a bus that has only the always-safe adapters (SystemAdapter
  — psutil probes). This is what tests use when they don't care about
  the GUI surface.
- ``home_widget`` / ``dm_widget`` / ``patient_widget_factory`` are
  passed in; the factory NEVER imports the production GUI directly.
  That keeps this module CI-runnable without PySide6.
- The returned bus is ready for use: register the bus on the
  ``home_widget`` (e.g. ``home_widget.command_bus = bus``) so the chat
  orb and agent SDK can reach it.

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §5.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .command_bus import CommandBus
from .registry import AdapterRegistry

logger = logging.getLogger(__name__)


def build_command_bus(
    *,
    home_widget: Any = None,
    dm_widget: Any = None,
    module_launchers: Optional[dict[str, Callable[[dict], Any]]] = None,
    get_active_patient_tab: Optional[Callable[[], Any]] = None,
    get_main_tab_widget: Optional[Callable[[], Any]] = None,
    orchestrator: Any = None,
    enable_viewer_write: bool = False,
    task_engine_getter: Optional[Callable[[], Any]] = None,
) -> CommandBus:
    """Construct a fully-wired ``CommandBus``.

    Parameters
    ----------
    home_widget
        Live ``HomePanel`` widget. When provided, registers
        ``HomeCommandAdapter`` (list_patients, open_patient,
        download_patient).
    dm_widget
        Live ``DownloadManagerWidget``. When provided, registers
        ``DownloadCommandAdapter`` (status, list, cancel, pause,
        resume, statistics).
    module_launchers
        Mapping ``module_name → callable(entities) -> window``. When
        provided, registers ``ModuleCommandAdapter`` with these
        launchers wired in.
    orchestrator
        Legacy ``SecretaryOrchestrator`` for the parse path. When
        ``None``, ``bus.parse()`` always returns ``None`` and callers
        must construct CommandPlans directly (agent SDK / tests do
        this anyway).

    Returns
    -------
    CommandBus
        Ready for use. ``bus.actions()`` enumerates everything
        registered.
    """
    reg = AdapterRegistry()

    # ── SystemAdapter — always wire it; it has no GUI dependency ────
    from .adapters import SystemCommandAdapter
    reg.register("system", SystemCommandAdapter(), actions={
        "snapshot_resources":        "snapshot_resources",
        "count_aipacs_processes":    "count_aipacs_processes",
        "count_native_faults_since": "count_native_faults_since",
        "probe_idle_cpu":            "probe_idle_cpu",
    })

    # ── HomeAdapter — only when a home widget is available ──────────
    if home_widget is not None:
        try:
            from .adapters.home_command_adapter import HomeCommandAdapter
            from .adapters.home_widget_adapter import HomeWidgetAdapter
            legacy_home = HomeWidgetAdapter(home_widget=home_widget)
            home_adapter = HomeCommandAdapter(legacy_home)
            reg.register("home", home_adapter, actions={
                "list_patients":    "list_patients",
                "open_patient":     "open_patient",
                "select_patient":   "select_patient",
                "download_patient": "download_patient",
            })
        except Exception:
            logger.exception("bus_factory: HomeAdapter registration failed")

    # ── DownloadAdapter — only when a DM widget is available ────────
    if dm_widget is not None:
        try:
            from .adapters import DownloadCommandAdapter
            dl_adapter = DownloadCommandAdapter(dm_widget=dm_widget)
            reg.register("download", dl_adapter, actions={
                "cancel_download":       "cancel_download",
                "pause_download":        "pause_download",
                "resume_download":       "resume_download",
                "check_download_status": "check_download_status",
                "list_downloads":        "list_downloads",
                "download_statistics":   "download_statistics",
            })
        except Exception:
            logger.exception("bus_factory: DownloadAdapter registration failed")

    # ── ModuleAdapter — only when launchers are supplied ────────────
    if module_launchers:
        try:
            from .adapters.module_command_adapter import ModuleCommandAdapter
            mod_adapter = ModuleCommandAdapter(launchers=module_launchers)
            reg.register("modules", mod_adapter, actions={
                "open_module":    "open_module",
                "list_modules":   "list_modules",
                "toggle_eagle":   "toggle_eagle",
                "open_mpr":       "open_mpr",
                "open_printing":  "open_printing",
                "open_education": "open_education",
            })
        except Exception:
            logger.exception("bus_factory: ModuleAdapter registration failed")

    # ── Browser / Education adapters (2026-06-11) ────────────────────
    # Deep module control for the voice assistant, built on the SAME
    # launchers the ModuleAdapter uses (activate-or-create singleton tab,
    # returns the live widget). Browser: Google search / URL / back /
    # forward / refresh. Education: consultation, courses, case of the
    # day, library search. Both degrade to typed MODULE_UNAVAILABLE
    # envelopes when the launcher yields no widget.
    if module_launchers and "web_browser" in module_launchers:
        try:
            from .adapters.browser_command_adapter import (
                BROWSER_ACTIONS,
                BrowserCommandAdapter,
            )
            br_adapter = BrowserCommandAdapter(
                open_browser_launcher=module_launchers["web_browser"],
                engine_getter=task_engine_getter,
            )
            reg.register("browser", br_adapter, actions=dict(BROWSER_ACTIONS))
        except Exception:
            logger.exception("bus_factory: BrowserAdapter registration failed")

    # ── AgentAdapter — background workflows (2026-06-11) ──────────────
    # Only when a task engine is wired (production home panel). Login
    # needs the browser launcher; education content search is engine-only.
    if task_engine_getter is not None:
        try:
            from .adapters.agent_command_adapter import (
                AGENT_ACTIONS,
                AgentCommandAdapter,
            )
            ag_adapter = AgentCommandAdapter(
                browser_launcher=(module_launchers or {}).get("web_browser"),
                engine_getter=task_engine_getter,
            )
            reg.register("agent", ag_adapter, actions=dict(AGENT_ACTIONS))
        except Exception:
            logger.exception("bus_factory: AgentAdapter registration failed")

    if module_launchers and "education" in module_launchers:
        try:
            from .adapters.education_command_adapter import (
                EDUCATION_ACTIONS,
                EducationCommandAdapter,
            )
            edu_adapter = EducationCommandAdapter(
                open_education_launcher=module_launchers["education"],
            )
            reg.register("education", edu_adapter,
                         actions=dict(EDUCATION_ACTIONS))
        except Exception:
            logger.exception("bus_factory: EducationAdapter registration failed")

    # ── ViewerAdapter — read-only viewer-state probe (Phase C.2) ───
    if get_active_patient_tab is not None or get_main_tab_widget is not None:
        try:
            from .adapters import ViewerCommandAdapter
            v_adapter = ViewerCommandAdapter(
                get_active_patient_tab=get_active_patient_tab,
                get_main_tab_widget=get_main_tab_widget,
            )
            reg.register("viewer", v_adapter, actions={
                "get_active_tab":      "get_active_tab",
                "list_open_tabs":      "list_open_tabs",
                "get_thumbnails_data": "get_thumbnails_data",
                "get_active_series":   "get_active_series",
                "get_multistudy_info": "get_multistudy_info",
            })
        except Exception:
            logger.exception("bus_factory: ViewerAdapter registration failed")

    # ── ViewerWriteAdapter — SAFE subset, opt-in (2026-06-06 bridge) ──
    # Promoted from test-server-only so the voice assistant can navigate
    # series/tabs ("load series 3", "switch tab"). Only the non-destructive
    # actions are registered here; ``close_patient_tab`` stays test-only
    # (test_server.py registers the full adapter surface itself).
    if enable_viewer_write and (
        get_active_patient_tab is not None or get_main_tab_widget is not None
    ):
        try:
            from .adapters.viewer_write_adapter import ViewerWriteCommandAdapter
            vw_adapter = ViewerWriteCommandAdapter(
                get_active_patient_tab=get_active_patient_tab,
                get_main_tab_widget=get_main_tab_widget,
            )
            reg.register("viewer_write", vw_adapter, actions={
                "change_series":        "change_series",
                "query_viewport_state": "query_viewport_state",
                "switch_tab":           "switch_tab",
                "get_series_info":      "get_series_info",
                "change_layout":        "change_layout",
                "scroll_slices":        "scroll_slices",
            })
        except Exception:
            logger.exception("bus_factory: ViewerWriteAdapter registration failed")

    # ── EchoMindAdapter — reporting workflow on the active tab ───────
    # (2026-06-06 bridge phase 2) start_report / transcribe_voice /
    # generate_report drive the same EchoMind UI the user clicks;
    # send_report_to_pacs opens the interactive reception dialog (the
    # clinical human gate is preserved — never a silent send).
    if get_active_patient_tab is not None:
        try:
            from .adapters.echomind_command_adapter import (
                ECHOMIND_ACTIONS,
                EchoMindCommandAdapter,
            )
            em_adapter = EchoMindCommandAdapter(
                get_active_patient_tab=get_active_patient_tab,
            )
            reg.register("echomind", em_adapter, actions=dict(ECHOMIND_ACTIONS))
        except Exception:
            logger.exception("bus_factory: EchoMindAdapter registration failed")

    bus = CommandBus(registry=reg, orchestrator=orchestrator)
    logger.info(
        "bus_factory: built CommandBus with %d action(s) across %d adapter(s)",
        len(reg.list_actions()), len(reg.list_adapters()),
    )
    return bus


__all__ = ["build_command_bus"]
