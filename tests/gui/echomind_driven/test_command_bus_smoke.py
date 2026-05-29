"""End-to-end smoke: build a bus, dispatch a plan, get a typed result.

Runs in CI via the FakeHomeAdapter — proves the wiring works without a
live AI-PACS window. When the source build is up, the same tests run
against the real adapter via the live-bus fixture.
"""
from __future__ import annotations

from modules.EchoMind.secretary import CommandPlan


def test_smoke_list_patients(bus, fake_home):
    plan = CommandPlan(
        action="list_patients",
        entities={"modality": "MR", "date_from": "20260526",
                  "date_to": "20260526"},
    )
    result = bus.execute(plan)
    assert result.ok, result.message
    assert result.action == "list_patients"
    assert result.data["count"] == 20
    assert fake_home.searched_count == 1
    assert result.elapsed_ms is not None and result.elapsed_ms > 0


def test_smoke_open_patient(bus, fake_home):
    plan = CommandPlan(action="open_patient",
                       entities={"patient_id": "43743"})
    result = bus.execute(plan)
    assert result.ok
    assert result.data["patient_id"] == "43743"
    assert result.data["series_count"] == 7
    assert fake_home.opened == ["43743"]


def test_smoke_unknown_action_returns_error_envelope(bus):
    plan = CommandPlan(action="reticulate_splines")
    result = bus.execute(plan)
    assert result.ok is False
    assert result.error_code == "UNKNOWN_ACTION"
