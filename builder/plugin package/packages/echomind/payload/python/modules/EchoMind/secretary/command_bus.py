"""CommandBus — unified entry point for the Command Layer.

Same call site for chat, voice, AI agent, and GUI tests. Callers enter
through one of:

    bus.parse(text_or_dict_or_req)   → CommandPlan | None
    bus.execute(plan_or_dict)         → CommandResult
    bus.dispatch(text_or_dict_or_req) → CommandResult     # parse + execute
    bus.dispatch_async(...)           → awaitable CommandResult (qasync)

The bus delegates parsing to a legacy ``SecretaryOrchestrator`` until
Phase 2 lands (which swaps in a PydanticAI parser). It delegates
execution to an ``AdapterRegistry``.

See ``docs/plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md`` §3.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, Union

from .command_envelope import CommandPlan, CommandRequest, CommandResult
from .registry import AdapterRegistry

logger = logging.getLogger(__name__)


class CommandBus:
    """Unified control layer.

    Wrap a ``SecretaryOrchestrator`` (or ``None`` for pure-test use)
    and an ``AdapterRegistry``. Every caller in the system goes through
    this class.
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        orchestrator: Any = None,
    ):
        self.registry = registry
        # The orchestrator provides parsing (rule parser + LLM fallback +
        # repair loop). Pass ``None`` to disable text parsing — callers
        # that always construct a CommandPlan directly (AI agent, tests)
        # don't need it.
        self._orchestrator = orchestrator

    # ── parse ────────────────────────────────────────────────────────
    def parse(
        self,
        req: Union[CommandRequest, dict, str],
    ) -> Optional[CommandPlan]:
        """Convert text input into a CommandPlan."""
        req_obj = self._coerce_request(req)
        if self._orchestrator is None:
            logger.debug("CommandBus.parse: no orchestrator wired — "
                         "callers must construct CommandPlan directly")
            return None
        try:
            plan_td = self._orchestrator._parse_plan(req_obj.to_typeddict(), "")
        except Exception:
            logger.exception("CommandBus.parse: orchestrator raised")
            return None
        return CommandPlan.from_typeddict(plan_td)

    # ── execute ──────────────────────────────────────────────────────
    def execute(
        self,
        plan: Union[CommandPlan, dict],
        state: Optional[dict] = None,
    ) -> CommandResult:
        """Run a CommandPlan through the AdapterRegistry."""
        if isinstance(plan, dict):
            plan = CommandPlan.model_validate(plan)
        t0 = time.monotonic()
        result = self.registry.dispatch(plan, state or {})
        if result.elapsed_ms is None:
            result.elapsed_ms = (time.monotonic() - t0) * 1000.0
        return result

    # ── parse + execute ──────────────────────────────────────────────
    def dispatch(
        self,
        req: Union[CommandRequest, dict, str],
    ) -> CommandResult:
        """Convenience: parse + execute in one call."""
        plan = self.parse(req)
        if plan is None:
            return CommandResult(
                ok=False,
                action="<unparsed>",
                message="Could not parse command",
                error_code="UNPARSED",
            )
        return self.execute(plan)

    async def dispatch_async(
        self,
        req: Union[CommandRequest, dict, str],
    ) -> CommandResult:
        """qasync-friendly variant: parsing happens off the Qt thread."""
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, self.parse, req)
        if plan is None:
            return CommandResult(
                ok=False,
                action="<unparsed>",
                message="Could not parse command",
                error_code="UNPARSED",
            )
        return self.execute(plan)

    # ── introspection ────────────────────────────────────────────────
    def actions(self) -> list[str]:
        return self.registry.list_actions()

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _coerce_request(req) -> CommandRequest:
        if isinstance(req, CommandRequest):
            return req
        if isinstance(req, dict):
            return CommandRequest.model_validate(req)
        if isinstance(req, str):
            return CommandRequest(text=req)
        raise TypeError(
            f"Unsupported CommandBus request type {type(req).__name__}"
        )


__all__ = ["CommandBus"]
