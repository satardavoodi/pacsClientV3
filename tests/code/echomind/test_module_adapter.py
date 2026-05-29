"""ModuleCommandAdapter unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

from modules.EchoMind.secretary import (  # noqa: E402
    AdapterRegistry, CommandBus, CommandPlan,
)
from modules.EchoMind.secretary.adapters import ModuleCommandAdapter  # noqa: E402


class _FakeWindow:
    def __init__(self, name): self.name = name


def _bus_with_modules(launchers):
    adapter = ModuleCommandAdapter(launchers=launchers)
    reg = AdapterRegistry()
    reg.register("modules", adapter, actions={
        "open_module":    "open_module",
        "list_modules":   "list_modules",
        "toggle_eagle":   "toggle_eagle",
        "open_mpr":       "open_mpr",
        "open_printing":  "open_printing",
        "open_education": "open_education",
    })
    return CommandBus(registry=reg, orchestrator=None), adapter


def test_list_modules_returns_registered_names():
    bus, _ = _bus_with_modules({
        "eagle_ai": lambda e: _FakeWindow("eagle"),
        "mpr":      lambda e: _FakeWindow("mpr"),
    })
    r = bus.execute(CommandPlan(action="list_modules"))
    assert r.ok
    assert sorted(r.data["modules"]) == ["eagle_ai", "mpr"]


def test_open_module_happy_path_records_window_class():
    bus, _ = _bus_with_modules({
        "eagle_ai": lambda e: _FakeWindow("eagle"),
    })
    r = bus.execute(CommandPlan(action="open_module",
                                entities={"module": "eagle_ai"}))
    assert r.ok
    assert r.data["module"] == "eagle_ai"
    assert r.data["window_class"] == "_FakeWindow"
    assert r.data["opened"] is True


def test_open_module_missing_module_returns_missing_module():
    bus, _ = _bus_with_modules({})
    r = bus.execute(CommandPlan(action="open_module"))
    assert r.ok is False
    assert r.error_code == "MISSING_MODULE"


def test_open_module_unregistered_returns_not_registered():
    bus, _ = _bus_with_modules({"eagle_ai": lambda e: None})
    r = bus.execute(CommandPlan(action="open_module",
                                entities={"module": "ghost_module"}))
    assert r.ok is False
    assert r.error_code == "MODULE_NOT_REGISTERED"
    assert "eagle_ai" in r.message  # lists what IS available


def test_launcher_crash_returns_launch_failed():
    def _boom(entities):
        raise RuntimeError("simulated launcher crash")
    bus, _ = _bus_with_modules({"eagle_ai": _boom})
    r = bus.execute(CommandPlan(action="toggle_eagle"))
    assert r.ok is False
    assert r.error_code == "MODULE_LAUNCH_FAILED"
    assert "simulated" in r.message


def test_convenience_aliases_route_to_canonical_module():
    calls: list[str] = []
    bus, _ = _bus_with_modules({
        "eagle_ai":  lambda e: (calls.append("eagle_ai"),  _FakeWindow("e"))[1],
        "mpr":       lambda e: (calls.append("mpr"),       _FakeWindow("m"))[1],
        "printing":  lambda e: (calls.append("printing"),  _FakeWindow("p"))[1],
        "education": lambda e: (calls.append("education"), _FakeWindow("ed"))[1],
    })
    assert bus.execute(CommandPlan(action="toggle_eagle")).ok
    assert bus.execute(CommandPlan(action="open_mpr")).ok
    assert bus.execute(CommandPlan(action="open_printing")).ok
    assert bus.execute(CommandPlan(action="open_education")).ok
    assert calls == ["eagle_ai", "mpr", "printing", "education"]


def test_register_module_can_extend_after_construction():
    adapter = ModuleCommandAdapter()
    assert not adapter.has_module("eagle_ai")
    adapter.register_module("eagle_ai", lambda e: _FakeWindow("e"))
    assert adapter.has_module("eagle_ai")
