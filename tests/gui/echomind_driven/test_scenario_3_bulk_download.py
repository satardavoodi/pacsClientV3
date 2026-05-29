"""Scenario 3 — multi-patient Download queue (Issue 3, parallel prefetch).

Via the bus: dispatch one download_patient plan with 20 patient IDs;
assert queue populates fast and contains all 20. A regression that
re-introduced the sequential prefetch loop would cause `elapsed_ms` to
balloon from ~150 ms to 6-30 s.
"""
from __future__ import annotations

from modules.EchoMind.secretary import CommandPlan


def test_bulk_download_20_patients_under_3s(bus, fake_home):
    patient_ids = [f"4365{i:02d}" for i in range(20)]
    plan = CommandPlan(
        action="download_patient",
        entities={"patient_ids": patient_ids, "modality": "MR"},
    )
    result = bus.execute(plan)

    assert result.ok, result.message
    assert result.elapsed_ms is not None
    # Post-fix budget: < 3000 ms for 20 patients (we expect ~150 ms with
    # the fake adapter; the real one should land < 2000 ms with the
    # ThreadPoolExecutor fix).
    assert result.elapsed_ms < 3000.0, (
        f"Bulk download with 20 patients took {result.elapsed_ms:.0f} ms "
        f"(>3 s threshold) — parallel prefetch regression suspected."
    )
    assert result.data["count"] == 20
    assert result.data["queue_size"] == 20
    # Every id ended up in the fake queue exactly once.
    assert sorted(fake_home.queue) == sorted(patient_ids)


def test_bulk_download_single_patient_still_works(bus, fake_home):
    plan = CommandPlan(
        action="download_patient",
        entities={"patient_id": "43743"},
    )
    result = bus.execute(plan)
    assert result.ok
    assert result.data["count"] == 1
    assert fake_home.queue == ["43743"]
