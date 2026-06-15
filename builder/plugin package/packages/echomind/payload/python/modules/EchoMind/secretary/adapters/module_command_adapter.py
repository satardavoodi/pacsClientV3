"""ModuleCommandAdapter — open AI-PACS modules via the CommandBus.

Module launchers in AI-PACS are scattered (AiMainWindow is lazy-loaded
in home_panel; MPR opens via a per-patient-tab toolbar; Printing has
its own entry point). Rather than hard-coding each launcher's path,
this adapter takes a ``launchers`` dict at construction time:

    launchers = {
        "eagle_ai":   home_widget.launch_eagle_ai,
        "mpr":        patient_widget.show_mpr_dropdown,
        "printing":   home_widget.open_print_module,
        "education":  home_widget.open_education_case,
    }

Each launcher is ``callable(entities: dict) -> Any`` — returning the
window/widget that was opened, or ``None`` on failure. This indirection
keeps the adapter free of GUI imports while still letting the agent +
tests open every module the catalog references.

Actions exposed
---------------
``open_module``    — generic launcher; ``entities.module`` selects which
``toggle_eagle``   — convenience alias for ``open_module module=eagle_ai``
``open_mpr``       — convenience alias; passes study/series entities
``open_printing``  — convenience alias
``open_education`` — convenience alias (case of the day)
``list_modules``   — return the names of registered modules

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §6.4
and ``modules/EchoMind/secretary/catalog/modules/`` for what each
module supports.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


# Type alias for clarity. A launcher takes a dict of entities and
# returns anything (typically a window) or None.
ModuleLauncher = Callable[[dict[str, Any]], Any]


class ModuleCommandAdapter:
    """Catalog-style module launcher proxy.

    The host (production main.py / home_widget construction site or
    tests) supplies the ``launchers`` mapping; this adapter routes
    plan-shaped commands to the right callable.
    """

    SUPPORTED_ACTIONS: tuple[str, ...] = (
        "open_module",
        "list_modules",
        "toggle_eagle",
        "open_mpr",
        "open_printing",
        "open_education",
    )

    # Mapping from convenience action → canonical module name
    _ACTION_TO_MODULE = {
        "toggle_eagle":  "eagle_ai",
        "open_mpr":      "mpr",
        "open_printing": "printing",
        "open_education": "education",
    }

    def __init__(self, launchers: Optional[dict[str, ModuleLauncher]] = None):
        # Defensive copy — mutating the original later shouldn't change
        # the adapter's resolution table.
        self._launchers: dict[str, ModuleLauncher] = dict(launchers or {})

    # ── registration helpers (mutate after construction if needed) ──
    def register_module(self, name: str, launcher: ModuleLauncher) -> None:
        self._launchers[name] = launcher

    def has_module(self, name: str) -> bool:
        return name in self._launchers

    # ── action: list_modules ─────────────────────────────────────────
    def list_modules(self, plan: CommandPlan, state: dict) -> CommandResult:
        names = sorted(self._launchers.keys())
        return CommandResult(
            ok=True, action="list_modules",
            message=f"{len(names)} module(s) registered",
            data={"modules": names},
        )

    # ── action: open_module ──────────────────────────────────────────
    def open_module(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        name = str(ent.get("module") or "").strip()
        if not name:
            return CommandResult(
                ok=False, action="open_module",
                message="open_module requires entities.module",
                error_code="MISSING_MODULE",
            )
        return self._dispatch(name, plan, action="open_module")

    # ── convenience aliases ──────────────────────────────────────────
    def toggle_eagle(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._dispatch("eagle_ai", plan, action="toggle_eagle")

    def open_mpr(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._dispatch("mpr", plan, action="open_mpr")

    def open_printing(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._dispatch("printing", plan, action="open_printing")

    def open_education(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._dispatch("education", plan, action="open_education")

    # ── core dispatch ────────────────────────────────────────────────
    def _dispatch(self, module: str, plan: CommandPlan, *,
                  action: str) -> CommandResult:
        launcher = self._launchers.get(module)
        if launcher is None:
            available = ", ".join(sorted(self._launchers.keys())) or "(none)"
            return CommandResult(
                ok=False, action=action,
                message=(f"No launcher registered for module {module!r}. "
                         f"Registered: {available}"),
                error_code="MODULE_NOT_REGISTERED",
            )
        try:
            window = launcher(plan.entities or {})
        except Exception as exc:
            logger.exception("ModuleAdapter: %s launcher raised", module)
            return CommandResult(
                ok=False, action=action,
                message=f"{module} launcher crashed: {exc}",
                error_code="MODULE_LAUNCH_FAILED",
            )
        return CommandResult(
            ok=True, action=action,
            message=f"Opened module {module}",
            data={"module": module,
                  "window_class": type(window).__name__ if window is not None else None,
                  "opened": window is not None},
        )


__all__ = ["ModuleCommandAdapter", "ModuleLauncher"]
