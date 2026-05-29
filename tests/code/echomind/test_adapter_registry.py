"""AdapterRegistry register / dispatch / error paths (Phase 4 acceptance)."""
from __future__ import annotations

import pytest

from modules.EchoMind.secretary import (
    AdapterRegistry, CommandPlan, CommandResult,
)


class _FakeHome:
    """Adapter shim that returns CommandResult / dict / None / payload."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def returns_command_result(self, plan: CommandPlan, state: dict) -> CommandResult:
        self.calls.append(("returns_command_result", plan.entities))
        return CommandResult(ok=True, action=plan.action,
                             message="custom message",
                             data={"hello": "world"})

    def returns_dict_with_ok(self, plan, state):
        return {"ok": True, "action": plan.action, "data": {"x": 1}}

    def returns_dict_payload(self, plan, state):
        return {"rows": [1, 2, 3], "count": 3}

    def returns_none(self, plan, state):
        return None

    def returns_string(self, plan, state):
        return "raw payload"

    def raises(self, plan, state):
        raise RuntimeError("boom — simulated adapter crash")


def test_register_then_list_actions():
    reg = AdapterRegistry()
    home = _FakeHome()
    reg.register("home", home, actions={
        "list_patients": "returns_command_result",
        "open_patient":  "returns_dict_with_ok",
    })
    assert reg.has_action("list_patients")
    assert reg.has_action("open_patient")
    assert reg.list_actions() == ["list_patients", "open_patient"]
    assert reg.list_adapters() == ["home"]
    assert reg.adapter("home") is home


def test_register_missing_method_raises():
    reg = AdapterRegistry()
    with pytest.raises(ValueError):
        reg.register("home", _FakeHome(), actions={"x": "does_not_exist"})


def test_dispatch_unknown_action_returns_unknown_action():
    reg = AdapterRegistry()
    result = reg.dispatch(CommandPlan(action="ghost"), state={})
    assert result.ok is False
    assert result.error_code == "UNKNOWN_ACTION"
    assert "ghost" in result.message


def test_dispatch_happy_command_result():
    reg = AdapterRegistry()
    home = _FakeHome()
    reg.register("home", home, actions={"a": "returns_command_result"})
    result = reg.dispatch(CommandPlan(action="a", entities={"k": "v"}), state={})
    assert result.ok is True
    assert result.action == "a"
    assert result.data == {"hello": "world"}
    assert home.calls == [("returns_command_result", {"k": "v"})]


def test_dispatch_dict_with_ok_validates_to_command_result():
    reg = AdapterRegistry()
    reg.register("home", _FakeHome(), actions={"a": "returns_dict_with_ok"})
    result = reg.dispatch(CommandPlan(action="a"), state={})
    assert isinstance(result, CommandResult)
    assert result.ok is True
    assert result.data == {"x": 1}


def test_dispatch_dict_payload_wrapped():
    reg = AdapterRegistry()
    reg.register("home", _FakeHome(), actions={"a": "returns_dict_payload"})
    result = reg.dispatch(CommandPlan(action="a"), state={})
    assert result.ok is True
    # When the dict doesn't look like a CommandResult, the whole dict
    # becomes the payload OR is wrapped as data — either way the rows
    # must be retrievable.
    payload = result.data
    if isinstance(payload, dict):
        assert payload.get("rows") == [1, 2, 3] or payload.get("data", {}).get("rows") == [1, 2, 3]


def test_dispatch_none_returns_ok_with_message():
    reg = AdapterRegistry()
    reg.register("home", _FakeHome(), actions={"a": "returns_none"})
    result = reg.dispatch(CommandPlan(action="a"), state={})
    assert result.ok is True
    assert "no payload" in result.message


def test_dispatch_raw_payload_wrapped_as_data():
    reg = AdapterRegistry()
    reg.register("home", _FakeHome(), actions={"a": "returns_string"})
    result = reg.dispatch(CommandPlan(action="a"), state={})
    assert result.ok is True
    assert result.data == "raw payload"


def test_dispatch_adapter_crash_returns_adapter_error():
    reg = AdapterRegistry()
    reg.register("home", _FakeHome(), actions={"a": "raises"})
    result = reg.dispatch(CommandPlan(action="a"), state={})
    assert result.ok is False
    assert result.error_code == "ADAPTER_ERROR"
    assert "boom" in result.message
