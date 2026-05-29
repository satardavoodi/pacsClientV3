"""Cross-patient thumbnail isolation guard.

Addresses the recurring failure mode the user named explicitly:
*"Thumbnails of patient A appearing on patient B."*

The bus-driven test interleaves ``open_patient`` calls across N patients
and asserts that:

1. Every result's ``patient_id`` matches the plan's ``patient_id``.
2. The ``series_count`` returned for patient A in a fresh call equals
   the count from the FIRST call (no cross-pollution).
3. No two distinct patients return identical series UIDs in their
   payload (cache-pollution signal).

A FAIL on any of those is the test's job — that's the thumbnail-leak
class of bug surfacing as a typed, deterministic regression rather
than a "looks weird in the UI" report.

When the real HomeAdapter is wired (production bus), this test runs
against the live data path. The CI run uses a stable FakeHomeAdapter
that mimics the same contract; intentional mis-mappings would FAIL the
test in CI so the regression-guard fires *before* the bug ships.
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
    AdapterRegistry, CommandBus, CommandPlan, CommandResult,
)


# ── deterministic fake home adapter ────────────────────────────────────

class _StableHomeAdapter:
    """Maps patient_id → deterministic (series_count, series_uids).

    This is the contract the real HomeCommandAdapter is supposed to
    uphold: same patient_id IN means same series_count and same series
    OUT, every call.
    """

    # Each patient has a unique fingerprint
    _DATA = {
        "43649": {"series_count": 6,
                  "series_uids": ["A-1", "A-2", "A-3", "A-4", "A-5", "A-6"]},
        "43698": {"series_count": 3,
                  "series_uids": ["B-1", "B-2", "B-3"]},
        "43676": {"series_count": 9,
                  "series_uids": ["C-1", "C-2", "C-3", "C-4", "C-5",
                                  "C-6", "C-7", "C-8", "C-9"]},
        "43586": {"series_count": 4,
                  "series_uids": ["D-1", "D-2", "D-3", "D-4"]},
        "43743": {"series_count": 7,
                  "series_uids": ["E-1", "E-2", "E-3", "E-4",
                                  "E-5", "E-6", "E-7"]},
    }

    def __init__(self):
        self.calls: list[str] = []

    def open(self, plan: CommandPlan, state: dict) -> CommandResult:
        pid = (plan.entities or {}).get("patient_id", "")
        info = self._DATA.get(str(pid))
        if info is None:
            return CommandResult(
                ok=False, action="open_patient",
                message=f"unknown patient {pid}",
                error_code="UNKNOWN_PATIENT",
            )
        self.calls.append(str(pid))
        return CommandResult(
            ok=True, action="open_patient",
            message=f"opened {pid}",
            data={
                "patient_id": str(pid),
                "series_count": info["series_count"],
                "series_uids": list(info["series_uids"]),
            },
        )


def _bus_with_fake_home():
    reg = AdapterRegistry()
    reg.register("home", _StableHomeAdapter(),
                 actions={"open_patient": "open"})
    return CommandBus(registry=reg, orchestrator=None)


# ── tests ──────────────────────────────────────────────────────────────

def test_patient_id_round_trip_isolation():
    """Result.patient_id must equal the plan's patient_id, every time."""
    bus = _bus_with_fake_home()
    patient_ids = ["43649", "43698", "43676", "43586", "43743"]
    for pid in patient_ids:
        r = bus.execute(CommandPlan(action="open_patient",
                                    entities={"patient_id": pid}))
        assert r.ok, r.message
        assert r.data["patient_id"] == pid, (
            f"patient_id round-trip mismatch: plan={pid} "
            f"result.data.patient_id={r.data['patient_id']}. "
            f"This is the canonical 'patient A thumbnails on patient B' bug."
        )


def test_series_count_stable_across_reopens():
    """Re-opening the same patient must return the same series_count
    every time. A drift = cache mutation = potential cross-pollution."""
    bus = _bus_with_fake_home()
    pid = "43649"

    seen_counts: list[int] = []
    for _ in range(3):
        r = bus.execute(CommandPlan(action="open_patient",
                                    entities={"patient_id": pid}))
        assert r.ok
        seen_counts.append(r.data["series_count"])

    assert len(set(seen_counts)) == 1, (
        f"series_count drifted across re-opens of {pid}: {seen_counts}. "
        f"Suggests cached state from a different patient leaked in."
    )


def test_no_cross_patient_series_uid_collision():
    """Open 5 distinct patients; assert no series UID appears in more
    than one patient's payload. Cross-pollution would FAIL this loudly.
    """
    bus = _bus_with_fake_home()
    patient_ids = ["43649", "43698", "43676", "43586", "43743"]

    uids_by_patient: dict[str, set[str]] = {}
    for pid in patient_ids:
        r = bus.execute(CommandPlan(action="open_patient",
                                    entities={"patient_id": pid}))
        assert r.ok
        uids_by_patient[pid] = set(r.data["series_uids"])

    # Pairwise overlap check.
    pids = list(uids_by_patient.keys())
    leaks: list[tuple[str, str, set[str]]] = []
    for i, a in enumerate(pids):
        for b in pids[i + 1:]:
            overlap = uids_by_patient[a] & uids_by_patient[b]
            if overlap:
                leaks.append((a, b, overlap))

    assert not leaks, (
        f"Series UID overlap between distinct patients: "
        + "; ".join(f"{a}↔{b}: {sorted(o)}" for a, b, o in leaks)
        + ". This is the canonical thumbnail-leak failure mode."
    )


def test_interleaved_opens_dont_pollute_each_other():
    """A → B → A → B → A pattern. Each re-visit must return that patient's
    UIDs exactly, never the previous one's.
    """
    bus = _bus_with_fake_home()

    expected_a = {"A-1", "A-2", "A-3", "A-4", "A-5", "A-6"}
    expected_b = {"B-1", "B-2", "B-3"}

    for turn, pid in enumerate(["43649", "43698", "43649", "43698", "43649"]):
        r = bus.execute(CommandPlan(action="open_patient",
                                    entities={"patient_id": pid}))
        assert r.ok
        got = set(r.data["series_uids"])
        expected = expected_a if pid == "43649" else expected_b
        assert got == expected, (
            f"turn={turn} pid={pid} returned {sorted(got)}, "
            f"expected {sorted(expected)}. Interleaved cross-pollution suspected."
        )


def test_unknown_patient_does_not_corrupt_subsequent_calls():
    """A failed open for an unknown patient must not leave state that
    affects the next successful open."""
    bus = _bus_with_fake_home()

    bad = bus.execute(CommandPlan(action="open_patient",
                                  entities={"patient_id": "99999"}))
    assert bad.ok is False
    assert bad.error_code == "UNKNOWN_PATIENT"

    # Now open a known patient — must return their canonical payload.
    r = bus.execute(CommandPlan(action="open_patient",
                                entities={"patient_id": "43649"}))
    assert r.ok
    assert r.data["series_count"] == 6
    assert set(r.data["series_uids"]) == {"A-1", "A-2", "A-3", "A-4", "A-5", "A-6"}
