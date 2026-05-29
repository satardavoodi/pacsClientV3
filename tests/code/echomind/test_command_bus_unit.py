"""CommandBus parse / execute / dispatch behaviour (Phase 3 acceptance)."""
from __future__ import annotations

import time

import pytest

from modules.EchoMind.secretary import (
    AdapterRegistry, CommandBus, CommandPlan, CommandRequest, CommandResult,
)


class _EchoAdapter:
    """Adapter that returns a CommandResult echoing its input — useful for
    asserting payload pass-through."""

    def echo(self, plan: CommandPlan, state: dict) -> CommandResult:
        return CommandResult(
            ok=True, action=plan.action,
            data={"entities": plan.entities, "state": state},
        )


def _bus_with_echo():
    reg = AdapterRegistry()
    reg.register("echo", _EchoAdapter(), actions={"echo": "echo"})
    return CommandBus(registry=reg, orchestrator=None)


# ── coercion ────────────────────────────────────────────────────────────
def test_coerce_request_str():
    req = CommandBus._coerce_request("hi")
    assert req.text == "hi"


def test_coerce_request_dict():
    req = CommandBus._coerce_request({"text": "x", "language": "en"})
    assert req.text == "x"
    assert req.language == "en"


def test_coerce_request_envelope():
    src = CommandRequest(text="x")
    req = CommandBus._coerce_request(src)
    assert req is src


def test_coerce_request_rejects_other_types():
    with pytest.raises(TypeError):
        CommandBus._coerce_request(42)


# ── parse ───────────────────────────────────────────────────────────────
def test_parse_returns_none_when_no_orchestrator():
    bus = _bus_with_echo()
    assert bus.parse("anything") is None


# ── execute ─────────────────────────────────────────────────────────────
def test_execute_fills_elapsed_ms():
    bus = _bus_with_echo()
    plan = CommandPlan(action="echo", entities={"k": "v"})
    result = bus.execute(plan)
    assert result.ok is True
    assert result.elapsed_ms is not None
    assert result.elapsed_ms >= 0
    assert result.data == {"entities": {"k": "v"}, "state": {}}


def test_execute_accepts_dict_plan():
    bus = _bus_with_echo()
    result = bus.execute({"action": "echo", "entities": {"a": 1}})
    assert result.ok is True
    assert result.data["entities"] == {"a": 1}


def test_execute_unknown_action():
    bus = _bus_with_echo()
    result = bus.execute(CommandPlan(action="ghost"))
    assert result.ok is False
    assert result.error_code == "UNKNOWN_ACTION"


def test_execute_state_passed_through():
    bus = _bus_with_echo()
    result = bus.execute(CommandPlan(action="echo"), state={"sess": "abc"})
    assert result.data["state"] == {"sess": "abc"}


# ── dispatch ────────────────────────────────────────────────────────────
def test_dispatch_unparsed_when_no_orchestrator():
    bus = _bus_with_echo()
    result = bus.dispatch("anything")
    assert result.ok is False
    assert result.error_code == "UNPARSED"
    assert result.action == "<unparsed>"


# ── introspection ───────────────────────────────────────────────────────
def test_actions_lists_registered_action_names():
    bus = _bus_with_echo()
    assert bus.actions() == ["echo"]


# ── async ───────────────────────────────────────────────────────────────
def test_dispatch_async_unparsed_smoke():
    import asyncio
    bus = _bus_with_echo()
    result = asyncio.get_event_loop().run_until_complete(
        bus.dispatch_async("anything")
    ) if False else None
    # Skip — asyncio test plumbing varies by harness. Smoke via
    # asyncio.new_event_loop:
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(bus.dispatch_async("anything"))
    finally:
        loop.close()
    assert result.ok is False
    assert result.error_code == "UNPARSED"
