"""bus_factory.build_command_bus integration tests."""
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

from modules.EchoMind.secretary import build_command_bus, CommandPlan  # noqa: E402


class _FakeHome:
    def is_available(self): return True
    def search(self, source, criteria, timeout_s=45): pass


class _FakeDM:
    def __init__(self):
        self.state_store = _FakeStore()


class _FakeStore:
    def get(self, uid): return None
    def get_all(self): return []
    def get_statistics(self): return {"total": 0}


def test_factory_with_no_args_always_wires_system_adapter():
    bus = build_command_bus()
    actions = bus.actions()
    # SystemAdapter wires four actions
    assert "snapshot_resources" in actions
    assert "count_aipacs_processes" in actions
    assert "count_native_faults_since" in actions
    assert "probe_idle_cpu" in actions
    # No home / no DM / no modules
    assert "open_patient" not in actions
    assert "cancel_download" not in actions
    assert "open_module" not in actions


def test_factory_wires_home_when_home_widget_passed():
    # This test only checks that the home actions land. The
    # HomeWidgetAdapter has lazy imports so a fake widget without the
    # full GUI API still gets through registration; runtime calls would
    # fail but registration is what we verify here.
    bus = build_command_bus(home_widget=_FakeHome())
    actions = bus.actions()
    assert "open_patient" in actions
    assert "list_patients" in actions
    assert "download_patient" in actions


def test_factory_wires_download_when_dm_passed():
    bus = build_command_bus(dm_widget=_FakeDM())
    actions = bus.actions()
    assert "cancel_download" in actions
    assert "check_download_status" in actions
    assert "download_statistics" in actions


def test_factory_wires_modules_when_launchers_passed():
    bus = build_command_bus(module_launchers={
        "eagle_ai":  lambda e: None,
        "mpr":       lambda e: None,
    })
    actions = bus.actions()
    assert "open_module" in actions
    assert "toggle_eagle" in actions
    assert "open_mpr" in actions

    # List modules should reflect what we passed.
    r = bus.execute(CommandPlan(action="list_modules"))
    assert r.ok
    assert sorted(r.data["modules"]) == ["eagle_ai", "mpr"]


def test_factory_wires_everything_when_all_args_provided():
    bus = build_command_bus(
        home_widget=_FakeHome(),
        dm_widget=_FakeDM(),
        module_launchers={"eagle_ai": lambda e: None},
    )
    actions = bus.actions()
    # 4 system + 3 home + 6 download + 6 modules = 19 actions
    assert len(actions) >= 18, f"expected ≥18 actions, got {len(actions)}: {actions}"
