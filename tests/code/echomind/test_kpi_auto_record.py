"""CommandBus → KpiCollector auto-record hook (Phase 1 of the framework).

Proves that ``KpiCollector.hook_bus(bus)`` records elapsed_ms from
every bus.execute() call whose action is a registered KPI key.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:
    import pytest
    pytest.skip("pydantic not installed in this environment", allow_module_level=True)

from modules.EchoMind.secretary import (  # noqa: E402
    AdapterRegistry, CommandBus, CommandPlan, CommandResult,
)
from tests._kpi import KpiCollector  # noqa: E402
from tests._kpi.schema import KPI_REGISTRY  # noqa: E402


class _PatientOpenAdapter:
    """Returns a CommandResult with action='patient_open' so the hook
    records under the registered key ``patient_open.elapsed_ms``."""

    def open(self, plan, state):
        return CommandResult(ok=True, action="patient_open", elapsed_ms=123.4,
                             data={"patient_id": plan.entities.get("patient_id")})


def _bus_with_patient_open():
    reg = AdapterRegistry()
    reg.register("home", _PatientOpenAdapter(), actions={"patient_open": "open"})
    return CommandBus(registry=reg, orchestrator=None)


def test_hook_bus_records_elapsed_ms(tmp_path):
    """elapsed_ms from bus.execute() is auto-recorded as <action>.elapsed_ms."""
    assert "patient_open.elapsed_ms" in KPI_REGISTRY
    coll = KpiCollector(sink_dir=tmp_path)
    bus = _bus_with_patient_open()
    coll.hook_bus(bus)

    result = bus.execute(CommandPlan(action="patient_open",
                                     entities={"patient_id": "43743"}))
    assert result.ok
    assert result.elapsed_ms == 123.4
    # Auto-recorded under "patient_open.elapsed_ms".
    keys_recorded = [v.key for v in coll.verdicts]
    assert keys_recorded == ["patient_open.elapsed_ms"]


def test_hook_bus_skips_unknown_actions(tmp_path):
    """Actions not in the registry are NOT recorded (the bus still works)."""
    coll = KpiCollector(sink_dir=tmp_path)

    class _GhostAdapter:
        def ghost(self, plan, state):
            return CommandResult(ok=True, action="ghost", elapsed_ms=5.0)
    reg = AdapterRegistry()
    reg.register("ghost", _GhostAdapter(), actions={"ghost": "ghost"})
    bus = CommandBus(registry=reg, orchestrator=None)
    coll.hook_bus(bus)

    result = bus.execute(CommandPlan(action="ghost"))
    assert result.ok
    assert coll.verdicts == []  # ghost isn't a registered key


def test_hook_bus_is_idempotent(tmp_path):
    """Calling hook_bus twice doesn't double-record."""
    coll = KpiCollector(sink_dir=tmp_path)
    bus = _bus_with_patient_open()
    coll.hook_bus(bus)
    coll.hook_bus(bus)  # idempotent guard inside hook_bus
    bus.execute(CommandPlan(action="patient_open", entities={"patient_id": "x"}))
    assert len(coll.verdicts) == 1


def test_explicit_record_overrides_threshold(tmp_path):
    """Explicit record() of a fast value verdicts PASS."""
    coll = KpiCollector(sink_dir=tmp_path)
    v = coll.record("patient_open.elapsed_ms", 200.0)
    assert v.verdict == "PASS"


def test_explicit_record_hard_fail_raises(tmp_path):
    """Explicit record() of a slow value raises KpiHardThresholdError."""
    from tests._kpi.collector import KpiHardThresholdError
    coll = KpiCollector(sink_dir=tmp_path)
    try:
        coll.record("patient_open.elapsed_ms", 5000.0)
        raise AssertionError("expected KpiHardThresholdError")
    except KpiHardThresholdError as e:
        msg = str(e)
        assert "patient_open" in msg


def test_unknown_kpi_key_loud_fail(tmp_path):
    from tests._kpi.schema import UnknownKpiError
    coll = KpiCollector(sink_dir=tmp_path)
    try:
        coll.record("ghost.never_registered_ms", 1.0)
        raise AssertionError("expected UnknownKpiError")
    except UnknownKpiError:
        pass
