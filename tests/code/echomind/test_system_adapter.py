"""SystemCommandAdapter unit tests."""
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
from modules.EchoMind.secretary.adapters import SystemCommandAdapter  # noqa: E402


def _bus_with_system():
    reg = AdapterRegistry()
    reg.register("system", SystemCommandAdapter(), actions={
        "snapshot_resources":        "snapshot_resources",
        "count_aipacs_processes":    "count_aipacs_processes",
        "count_native_faults_since": "count_native_faults_since",
        "probe_idle_cpu":            "probe_idle_cpu",
    })
    return CommandBus(registry=reg, orchestrator=None)


def test_snapshot_resources_returns_typed_data():
    bus = _bus_with_system()
    result = bus.execute(CommandPlan(action="snapshot_resources"))
    # psutil may or may not be installed in the test env
    if result.error_code == "DEP_MISSING":
        return  # acceptable in minimal sandbox
    assert result.ok, result.message
    d = result.data
    assert "rss_mb" in d and d["rss_mb"] > 0
    assert "cpu_pct" in d
    assert "threads" in d and d["threads"] > 0
    assert "pid" in d and d["pid"] == __import__("os").getpid()


def test_count_aipacs_processes_returns_counts():
    bus = _bus_with_system()
    result = bus.execute(CommandPlan(action="count_aipacs_processes"))
    if result.error_code == "DEP_MISSING":
        return
    assert result.ok, result.message
    counts = result.data["counts"]
    assert "python_exe" in counts and "aipacs_exe" in counts
    assert result.data["total"] == counts["python_exe"] + counts["aipacs_exe"]


def test_count_native_faults_handles_missing_file():
    """When native_fault.log doesn't exist the adapter returns ok=True
    with total=0 rather than failing — tests should still get a useful
    answer in CI sandboxes that have no log directory."""
    bus = _bus_with_system()
    result = bus.execute(CommandPlan(action="count_native_faults_since"))
    assert result.ok
    assert "total" in result.data
    assert isinstance(result.data["total"], int)


def test_count_native_faults_filter_by_code():
    bus = _bus_with_system()
    result = bus.execute(CommandPlan(
        action="count_native_faults_since",
        entities={"code": "0x8001010d"},
    ))
    assert result.ok
    # Both counts must be ints; code_filtered ≤ total
    assert result.data["code_filtered"] <= result.data["total"]


def test_probe_idle_cpu_short_window():
    """Tiny window for unit-test speed."""
    bus = _bus_with_system()
    result = bus.execute(CommandPlan(
        action="probe_idle_cpu",
        entities={"seconds": 0.3, "interval": 0.1},
    ))
    if result.error_code == "DEP_MISSING":
        return
    assert result.ok, result.message
    assert "median_pct" in result.data
    assert result.data["median_pct"] >= 0
    assert result.data["duration_s"] >= 0.2
