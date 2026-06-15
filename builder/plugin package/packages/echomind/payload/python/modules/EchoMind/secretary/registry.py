"""AdapterRegistry — maps action names to adapter methods.

Every callable surface (chat orb, AI agent, GUI test) reaches the
running app through a registered adapter. Adapters expose Python methods
that take ``(plan: CommandPlan, state: dict)`` and return either a
``CommandResult``, a dict (auto-validated), or anything else (wrapped
as ``data``).

See ``docs/plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md`` §4.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Maps action_name → (adapter_name, callable).

    Registration is idempotent — re-registering an action with a
    different adapter replaces the previous binding (useful in tests).
    """

    def __init__(self):
        self._adapters: dict[str, Any] = {}
        self._actions: dict[str, tuple[str, Callable]] = {}

    # ── registration ─────────────────────────────────────────────────
    def register(
        self,
        name: str,
        adapter: Any,
        actions: dict[str, str],
    ) -> None:
        """Register an adapter's actions.

        Parameters
        ----------
        name : str
            Human-readable adapter name (e.g. ``"home"``, ``"viewer"``).
        adapter : object
            The adapter instance. Must have a callable method for each
            value in ``actions``.
        actions : dict[str, str]
            ``action_name -> method_name`` on the adapter.
        """
        self._adapters[name] = adapter
        for action_name, method_name in actions.items():
            method = getattr(adapter, method_name, None)
            if method is None or not callable(method):
                raise ValueError(
                    f"Adapter {name!r} has no callable method {method_name!r}"
                )
            self._actions[action_name] = (name, method)
        logger.info(
            "AdapterRegistry.register: adapter=%s actions=%d total_actions=%d",
            name, len(actions), len(self._actions),
        )

    # ── introspection ────────────────────────────────────────────────
    def adapter(self, name: str) -> Optional[Any]:
        return self._adapters.get(name)

    def has_action(self, action_name: str) -> bool:
        return action_name in self._actions

    def list_actions(self) -> list[str]:
        return sorted(self._actions.keys())

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters.keys())

    # ── dispatch ─────────────────────────────────────────────────────
    def dispatch(
        self,
        plan: CommandPlan,
        state: dict,
    ) -> CommandResult:
        """Run the adapter method for ``plan.action`` and normalize result."""
        if plan.action not in self._actions:
            available = ", ".join(self.list_actions()[:8]) or "(none registered)"
            return CommandResult(
                ok=False,
                action=plan.action,
                message=(
                    f"No adapter registered for action {plan.action!r}. "
                    f"Known actions: {available}"
                ),
                error_code="UNKNOWN_ACTION",
            )

        adapter_name, method = self._actions[plan.action]
        try:
            raw = method(plan, state)
        except Exception as exc:
            logger.exception(
                "AdapterRegistry.dispatch: adapter=%s action=%s crashed",
                adapter_name, plan.action,
            )
            return CommandResult(
                ok=False,
                action=plan.action,
                message=f"{adapter_name} adapter crashed: {exc}",
                error_code="ADAPTER_ERROR",
            )

        return self._normalize_result(raw, plan)

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _normalize_result(raw: Any, plan: CommandPlan) -> CommandResult:
        """Coerce whatever the adapter returned into a CommandResult."""
        if isinstance(raw, CommandResult):
            return raw
        if raw is None:
            return CommandResult(
                ok=True, action=plan.action, message="(no payload)",
            )
        if isinstance(raw, dict):
            # If the dict already looks like a CommandResult, validate it.
            if "ok" in raw and "action" in raw:
                try:
                    return CommandResult.model_validate(raw)
                except Exception:
                    pass
            # Otherwise treat the whole dict as the payload.
            return CommandResult(
                ok=bool(raw.get("ok", True)),
                action=plan.action,
                message=str(raw.get("message") or ""),
                data=raw.get("data", raw),
                error_code=raw.get("error_code"),
            )
        # Arbitrary payload (list, str, int) — wrap as data.
        return CommandResult(ok=True, action=plan.action, data=raw)


__all__ = ["AdapterRegistry"]
