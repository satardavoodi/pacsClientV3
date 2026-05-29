"""DownloadCommandAdapter unit tests with mocked DM widget + state store."""
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
    AdapterRegistry, CommandBus, CommandPlan, CommandResult,
)
from modules.EchoMind.secretary.adapters import DownloadCommandAdapter  # noqa: E402


# ── mocks that mimic the DM widget + state store ─────────────────────

class _FakeState:
    def __init__(self, study_uid, status="PENDING", **kw):
        self.study_uid = study_uid
        self.status = status
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeStateStore:
    def __init__(self, states=None):
        self._by_uid = {s.study_uid: s for s in (states or [])}
        self.calls: list[str] = []

    def get(self, uid):
        self.calls.append(f"get:{uid}")
        return self._by_uid.get(uid)

    def get_all(self):
        return list(self._by_uid.values())

    def get_statistics(self):
        return {"total": len(self._by_uid), "active": 1, "completed": 0}


class _FakeDM:
    def __init__(self, state_store):
        self.state_store = state_store
        self.calls: list[tuple[str, str]] = []

    def cancel_study(self, uid): self.calls.append(("cancel", uid))
    def pause_study(self, uid):  self.calls.append(("pause", uid))
    def resume_study(self, uid): self.calls.append(("resume", uid))


def _bus_with_download(states=None):
    store = _FakeStateStore(states or [
        _FakeState("UID-A", status="DOWNLOADING", patient_name="A"),
        _FakeState("UID-B", status="PENDING", patient_name="B"),
        _FakeState("UID-C", status="COMPLETED", patient_name="C"),
    ])
    dm = _FakeDM(store)
    reg = AdapterRegistry()
    reg.register("download", DownloadCommandAdapter(dm_widget=dm, state_store=store),
                 actions={
                     "cancel_download":       "cancel_download",
                     "pause_download":        "pause_download",
                     "resume_download":       "resume_download",
                     "check_download_status": "check_download_status",
                     "list_downloads":        "list_downloads",
                     "download_statistics":   "download_statistics",
                 })
    bus = CommandBus(registry=reg, orchestrator=None)
    return bus, dm, store


def test_check_status_for_known_uid():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="check_download_status",
                                entities={"study_uid": "UID-A"}))
    assert r.ok, r.message
    assert r.data["state"]["status"] == "DOWNLOADING"
    assert r.data["state"]["patient_name"] == "A"


def test_check_status_missing_uid_returns_unknown_study():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="check_download_status",
                                entities={"study_uid": "GHOST"}))
    assert r.ok is False
    assert r.error_code == "UNKNOWN_STUDY"


def test_check_status_missing_arg_returns_missing_study_uid():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="check_download_status"))
    assert r.ok is False
    assert r.error_code == "MISSING_STUDY_UID"


def test_list_downloads_no_filter_returns_all():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="list_downloads"))
    assert r.ok
    assert r.data["count"] == 3
    assert sorted(row["study_uid"] for row in r.data["rows"]) == ["UID-A", "UID-B", "UID-C"]


def test_list_downloads_status_filter():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="list_downloads",
                                entities={"status": "downloading"}))
    assert r.ok
    assert r.data["count"] == 1
    assert r.data["rows"][0]["study_uid"] == "UID-A"


def test_download_statistics():
    bus, _, _ = _bus_with_download()
    r = bus.execute(CommandPlan(action="download_statistics"))
    assert r.ok
    assert r.data.get("total") == 3


def test_cancel_pause_resume_dispatch_to_dm():
    bus, dm, _ = _bus_with_download()
    bus.execute(CommandPlan(action="cancel_download", entities={"study_uid": "UID-A"}))
    bus.execute(CommandPlan(action="pause_download",  entities={"study_uid": "UID-B"}))
    bus.execute(CommandPlan(action="resume_download", entities={"study_uid": "UID-C"}))
    assert dm.calls == [("cancel", "UID-A"), ("pause", "UID-B"), ("resume", "UID-C")]


def test_no_dm_widget_returns_clean_error():
    reg = AdapterRegistry()
    reg.register("download", DownloadCommandAdapter(dm_widget=None, state_store=None),
                 actions={"cancel_download": "cancel_download",
                          "check_download_status": "check_download_status"})
    bus = CommandBus(registry=reg, orchestrator=None)

    r = bus.execute(CommandPlan(action="cancel_download",
                                entities={"study_uid": "X"}))
    assert r.ok is False
    assert r.error_code == "NO_DM_WIDGET"

    r = bus.execute(CommandPlan(action="check_download_status",
                                entities={"study_uid": "X"}))
    assert r.ok is False
    assert r.error_code == "NO_STATE_STORE"
