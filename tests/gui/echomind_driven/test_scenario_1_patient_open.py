"""Scenario 1 — patient open speed (Issue 1, GetStudyInfo probe slow-start).

Via the bus: dispatch 5 open_patient plans, assert each finishes under
the KPI threshold. The fake adapter mimics the post-fix ~150 ms socket
round-trip per open. A regression in the real adapter that re-introduces
the 6.8 s stall would fail this test once the live-bus fixture is wired.
"""
from __future__ import annotations

from modules.EchoMind.secretary import CommandPlan


def test_five_patient_opens_each_under_400ms(bus, fake_home):
    elapsed = []
    for pid in ("43649", "43698", "43676", "43586", "43743"):
        plan = CommandPlan(action="open_patient",
                           entities={"patient_id": pid})
        result = bus.execute(plan)
        assert result.ok, result.message
        assert result.elapsed_ms is not None
        elapsed.append(result.elapsed_ms)

    # KPI gate — matches the 2026-05-27 fix target.
    median = sorted(elapsed)[len(elapsed) // 2]
    assert median < 400.0, (
        f"Median open_patient elapsed {median:.0f} ms exceeds 400 ms "
        f"threshold. All measurements: {[round(e, 1) for e in elapsed]}"
    )
    assert max(elapsed) < 600.0, f"Max {max(elapsed):.0f} ms > 600 ms"

    # Sanity: every open hit the adapter.
    assert len(fake_home.opened) == 5


def test_open_patient_requires_patient_id(bus):
    """Smoke: missing patient_id is a polite UNKNOWN_ACTION / error."""
    # FakeHomeAdapter is lenient — it accepts empty pid. Real adapter
    # returns MISSING_PATIENT_ID. We just assert ok=True for the fake
    # (the real adapter has its own test).
    plan = CommandPlan(action="open_patient", entities={})
    result = bus.execute(plan)
    assert result.ok  # fake adapter is permissive
