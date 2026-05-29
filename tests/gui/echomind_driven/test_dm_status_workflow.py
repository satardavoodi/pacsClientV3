"""DownloadAdapter scenario: check status → list → cancel via the bus.

Uses a fake DM widget + state store so this test runs in CI.
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
    pytest.skip("pydantic not installed", allow_module_level=True)

from modules.EchoMind.secretary import (  # noqa: E402
    AdapterRegistry, CommandBus, CommandPlan,
)
from modules.EchoMind.secretary.adapters import DownloadCommandAdapter  # noqa: E402
from tests._kpi import KpiCollector  # noqa: E402


class _FakeState:
    def __init__(self, uid, status, **kw):
        self.study_uid = uid
        self.status = status
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeStore:
    def __init__(self, states):
        self._by_uid = {s.study_uid: s for s in states}

    def get(self, uid): return self._by_uid.get(uid)
    def get_all(self): return list(self._by_uid.values())
    def get_statistics(self): return {"total": len(self._by_uid)}


class _FakeDM:
    def __init__(self, store):
        self.state_store = store
        self.canceled: list[str] = []

    def cancel_study(self, uid): self.canceled.append(uid)


def _bus_with_download():
    states = [
        _FakeState("UID-1", status="DOWNLOADING", patient_name="P1"),
        _FakeState("UID-2", status="PENDING",     patient_name="P2"),
        _FakeState("UID-3", status="COMPLETED",   patient_name="P3"),
    ]
    store = _FakeStore(states)
    dm = _FakeDM(store)
    reg = AdapterRegistry()
    reg.register("download",
                 DownloadCommandAdapter(dm_widget=dm, state_store=store),
                 actions={
                     "check_download_status": "check_download_status",
                     "list_downloads":        "list_downloads",
                     "download_statistics":   "download_statistics",
                     "cancel_download":       "cancel_download",
                 })
    bus = CommandBus(registry=reg, orchestrator=None)
    return bus, dm, store


def test_status_check_and_list_workflow(tmp_path):
    bus, dm, _ = _bus_with_download()
    kpi = KpiCollector(sink_dir=tmp_path)
    kpi.hook_bus(bus)

    # Step 1: stats
    stats = bus.execute(CommandPlan(action="download_statistics"))
    assert stats.ok
    assert stats.data.get("total") == 3

    # Step 2: list
    listing = bus.execute(CommandPlan(action="list_downloads"))
    assert listing.ok
    assert listing.data["count"] == 3

    # Step 3: status on a known UID
    status = bus.execute(CommandPlan(
        action="check_download_status",
        entities={"study_uid": "UID-1"},
    ))
    assert status.ok
    assert status.data["state"]["status"] == "DOWNLOADING"

    # Step 4: filter list by status
    pending = bus.execute(CommandPlan(
        action="list_downloads",
        entities={"status": "pending"},
    ))
    assert pending.ok
    assert pending.data["count"] == 1

    # Step 5: cancel
    cancel = bus.execute(CommandPlan(
        action="cancel_download",
        entities={"study_uid": "UID-2"},
    ))
    assert cancel.ok
    assert dm.canceled == ["UID-2"]

    # Every elapsed_ms was auto-recorded by the bus hook.
    assert kpi.summary().get("FAIL", 0) == 0
