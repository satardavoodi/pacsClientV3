"""Invariant tests for the canonical patient-load lifecycle authority.

These encode the reliability contract from
``docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md`` §8 as
executable assertions, plus the two specific field regressions:

  * Problem #1 — a late/slow result is PARKED and reconciled, never discarded.
  * Problem #2 — a previous-exam (secondary-study) series is first-class and
    reaches DISPLAYED_COMPLETE by DISK convergence, with no progress event and
    no second drag.

Pure: imports only the (pure) lifecycle module. No PySide6 / VTK / numpy, so it
runs in the offscreen sandbox lane and standalone.
"""
from __future__ import annotations

from pathlib import Path

from PacsClient.utils.patient_load_lifecycle import (
    CanonicalSeriesId,
    LoadAction,
    LoadStage,
    PatientLoadModel,
    SeriesLoadRecord,
    Transition,
    derive_series_stage,
    format_transition,
    reconcile_series,
)
from PacsClient.utils.patient_study_set import Intent

_REPO = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# 0. Purity guard — the authority must never pull the render/GUI stack in.
# --------------------------------------------------------------------------
def test_module_is_pure_stdlib():
    src = (_REPO / "PacsClient/utils/patient_load_lifecycle.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    for forbidden in ("import PySide6", "import vtk", "import numpy", "import pydicom",
                      "from PySide6", "QtCore", "QtWidgets"):
        assert forbidden not in src, f"lifecycle module must stay pure; found {forbidden!r}"


# --------------------------------------------------------------------------
# 1. Completeness WITH a server expected count.
# --------------------------------------------------------------------------
def test_complete_with_expected():
    rec = SeriesLoadRecord(canonical=CanonicalSeriesId("S1", "3", "uidA"))
    rec.note_expected(10)
    rec.note_disk(10)
    rec.note_decoded(10)
    assert reconcile_series(rec, Intent.OPEN_VIEWER) == LoadAction.NONE
    assert derive_series_stage(rec, Intent.OPEN_VIEWER) == LoadStage.DISPLAYED_COMPLETE


def test_incomplete_with_expected_waits_not_downgrades():
    rec = SeriesLoadRecord(canonical=CanonicalSeriesId("S1", "3", "uidA"))
    rec.note_expected(10)
    rec.note_disk(5)
    rec.note_decoded(5)          # viewer caught disk, but only 5 of 10 exist
    assert reconcile_series(rec, Intent.OPEN_VIEWER) == LoadAction.WAIT
    assert derive_series_stage(rec, Intent.OPEN_VIEWER) == LoadStage.FIRST_IMAGE


def test_disk_ahead_of_viewer_grows():
    rec = SeriesLoadRecord(canonical=CanonicalSeriesId("S1", "3", "uidA"))
    rec.note_expected(10)
    rec.note_disk(10)
    rec.note_decoded(4)          # 10 on disk, only 4 shown -> grow
    assert reconcile_series(rec, Intent.OPEN_VIEWER) == LoadAction.LOAD_OR_GROW
    assert derive_series_stage(rec, Intent.OPEN_VIEWER) == LoadStage.FIRST_IMAGE


# --------------------------------------------------------------------------
# 2. Completeness WITHOUT expected — needs a settled (stable, no .part) folder.
# --------------------------------------------------------------------------
def test_complete_without_expected_needs_settle():
    m = PatientLoadModel()
    m.on_selection("P", "S1", Intent.OPEN_VIEWER)
    cid = CanonicalSeriesId("S1", "6", "uidB")
    m.on_series_set("S1", [cid])                       # expected unknown
    # First disk observation of 8 with a .part still in flight -> not settled.
    m.on_disk_change("S1", cid, 8, has_part=True)
    m.on_decoded("S1", cid, 8)
    assert derive_series_stage(m.study("S1").series[cid.key()], Intent.OPEN_VIEWER) == LoadStage.FIRST_IMAGE
    # Folder stops changing: same count, no .part, seen twice -> settled -> complete.
    m.on_disk_change("S1", cid, 8, has_part=False)
    m.on_disk_change("S1", cid, 8, has_part=False)
    act = m.on_decoded("S1", cid, 8)
    assert m.study("S1").series[cid.key()].stage == LoadStage.DISPLAYED_COMPLETE
    assert act == LoadAction.NONE


# --------------------------------------------------------------------------
# 3. Problem #2 — a previous-exam series is first-class & completes on DISK
#    convergence with NO progress event and NO second drag.
# --------------------------------------------------------------------------
def test_previous_exam_series_is_first_class_and_completes_by_disk():
    m = PatientLoadModel()
    # Primary study and a previous-exam study whose series NUMBER collides (both 6)
    # but whose series_uids differ. They must be distinct records.
    primary = CanonicalSeriesId("PRIMARY", "6", "uid-primary-6")
    prev = CanonicalSeriesId("PREVEXAM", "6", "uid-prev-6")
    m.on_selection("P", "PRIMARY", Intent.OPEN_VIEWER)
    m.on_selection("P", "PREVEXAM", Intent.OPEN_VIEWER)
    m.on_series_set("PRIMARY", [primary], expected={primary.key(): 30})
    m.on_series_set("PREVEXAM", [prev], expected={prev.key(): 30})
    assert primary.key() != prev.key()

    # The previous-exam series downloads to disk. NO DM progress event is bridged
    # (the historic failure) — only disk changes arrive. It must still converge.
    m.on_disk_change("PREVEXAM", prev, 1)
    act = m.on_disk_change("PREVEXAM", prev, 30)     # all 30 landed on disk
    assert act == LoadAction.LOAD_OR_GROW            # viewer behind disk -> load/grow
    # Caller loads the series; the viewport catches up.
    m.on_decoded("PREVEXAM", prev, 1)
    assert m.study("PREVEXAM").series[prev.key()].stage == LoadStage.FIRST_IMAGE
    m.on_decoded("PREVEXAM", prev, 30)
    assert m.study("PREVEXAM").series[prev.key()].stage == LoadStage.DISPLAYED_COMPLETE
    # The primary study was untouched by the previous-exam's events.
    assert m.study("PRIMARY").series[primary.key()].stage != LoadStage.DISPLAYED_COMPLETE


# --------------------------------------------------------------------------
# 4. Problem #1 — a late result for a non-active study is PARKED, not discarded.
# --------------------------------------------------------------------------
def test_late_result_is_parked_not_discarded():
    m = PatientLoadModel()
    a = CanonicalSeriesId("A", "1", "uid-a1")
    b = CanonicalSeriesId("B", "1", "uid-b1")
    m.on_selection("P", "A", Intent.OPEN_VIEWER)
    m.on_series_set("A", [a], expected={a.key(): 5})
    # User immediately selects B (A's in-flight fetch would be cancelled today).
    m.on_selection("P", "B", Intent.OPEN_VIEWER)
    m.on_series_set("B", [b], expected={b.key(): 5})
    # A's work finishes LATE — it must still update A's record (parked), not vanish.
    m.on_disk_change("A", a, 5)
    m.on_decoded("A", a, 5)
    assert m.study("A").series[a.key()].stage == LoadStage.DISPLAYED_COMPLETE
    # Re-selecting A does not reset it (idempotent; no re-fetch storm).
    m.on_selection("P", "A", Intent.OPEN_VIEWER)
    assert m.study("A").series[a.key()].stage == LoadStage.DISPLAYED_COMPLETE


# --------------------------------------------------------------------------
# 5. Never-downgrade — a poisoned low disk count cannot shrink a shown series.
# --------------------------------------------------------------------------
def test_never_downgrade_ignores_poisoned_low_disk():
    m = PatientLoadModel()
    cid = CanonicalSeriesId("S", "2", "uid-s2")
    m.on_selection("P", "S", Intent.OPEN_VIEWER)
    m.on_series_set("S", [cid], expected={cid.key(): 99})
    m.on_disk_change("S", cid, 99)
    m.on_decoded("S", cid, 99)
    assert m.study("S").series[cid.key()].stage == LoadStage.DISPLAYED_COMPLETE
    # A colliding/poisoned metadata now reports only 8 on disk.
    m.on_disk_change("S", cid, 8)
    rec = m.study("S").series[cid.key()]
    assert rec.on_disk == 99                       # record-level monotonic guard
    assert rec.stage == LoadStage.DISPLAYED_COMPLETE  # sticky terminal


def test_reconcile_skips_downgrade_when_viewer_ahead_of_target():
    # Direct construction: viewer shows more than any known target -> keep it.
    rec = SeriesLoadRecord(canonical=CanonicalSeriesId("S", "2", "uid"))
    rec.expected = 8
    rec.on_disk = 8
    rec.decoded = 99
    assert reconcile_series(rec, Intent.OPEN_VIEWER) == LoadAction.NONE


# --------------------------------------------------------------------------
# 6. Preview vs open; study-level aggregate stage.
# --------------------------------------------------------------------------
def test_preview_reaches_thumbs_ready_and_is_settled():
    m = PatientLoadModel()
    cid = CanonicalSeriesId("S", "1", "uid")
    m.on_selection("P", "S", Intent.PREVIEW_ONLY)
    m.on_series_set("S", [cid])
    m.mark_thumbs_rendered("S")
    assert m.study("S").stage == LoadStage.THUMBS_READY
    # Preview studies contribute nothing to the non-terminal (open) set.
    assert m.is_settled() is True


def test_open_study_reaches_displayed_complete():
    m = PatientLoadModel()
    cid = CanonicalSeriesId("S", "1", "uid")
    m.on_selection("P", "S", Intent.OPEN_VIEWER)
    m.on_series_set("S", [cid], expected={cid.key(): 3})
    m.on_disk_change("S", cid, 3)
    m.on_decoded("S", cid, 3)
    assert m.study("S").stage == LoadStage.DISPLAYED_COMPLETE
    assert m.is_settled() is True
    assert m.non_terminal_series() == []


# --------------------------------------------------------------------------
# 7. Convergence sweep empties as series terminate.
# --------------------------------------------------------------------------
def test_convergence_sweep_drains():
    m = PatientLoadModel()
    c1 = CanonicalSeriesId("S", "1", "u1")
    c2 = CanonicalSeriesId("S", "2", "u2")
    m.on_selection("P", "S", Intent.OPEN_VIEWER)
    m.on_series_set("S", [c1, c2], expected={c1.key(): 2, c2.key(): 2})
    assert len(m.non_terminal_series()) == 2
    m.on_disk_change("S", c1, 2); m.on_decoded("S", c1, 2)
    assert len(m.non_terminal_series()) == 1        # c2 still open
    m.on_disk_change("S", c2, 2); m.on_decoded("S", c2, 2)
    assert m.is_settled() is True


# --------------------------------------------------------------------------
# 8. Failure is terminal and cannot un-fail or overwrite a completed series.
# --------------------------------------------------------------------------
def test_failure_is_sticky():
    m = PatientLoadModel()
    cid = CanonicalSeriesId("S", "1", "uid")
    m.on_selection("P", "S", Intent.OPEN_VIEWER)
    m.on_series_set("S", [cid], expected={cid.key(): 5})
    m.on_failure("S", cid, "download_error")
    assert m.study("S").series[cid.key()].stage == LoadStage.FAILED
    m.on_disk_change("S", cid, 5)                    # a late disk event must not un-fail
    assert m.study("S").series[cid.key()].stage == LoadStage.FAILED


def test_complete_series_cannot_be_failed():
    rec = SeriesLoadRecord(canonical=CanonicalSeriesId("S", "1", "u"))
    rec.stage = LoadStage.DISPLAYED_COMPLETE
    rec.fail("late_error")
    assert rec.stage == LoadStage.DISPLAYED_COMPLETE


# --------------------------------------------------------------------------
# 9. Idempotent re-entry emits no spurious transition; instrumentation works.
# --------------------------------------------------------------------------
def test_idempotent_and_transitions_logged():
    seen = []
    m = PatientLoadModel(on_transition=seen.append)
    cid = CanonicalSeriesId("S", "1", "uid")
    m.on_selection("P", "S", Intent.OPEN_VIEWER)
    m.on_series_set("S", [cid], expected={cid.key(): 2})
    m.on_disk_change("S", cid, 2)
    m.on_decoded("S", cid, 2)
    n = len(seen)
    # Replaying the same terminal events changes nothing.
    m.on_disk_change("S", cid, 2)
    m.on_decoded("S", cid, 2)
    assert len(seen) == n
    assert any(t.to == LoadStage.DISPLAYED_COMPLETE for t in seen)
    line = format_transition(seen[-1])
    assert line.startswith("[LIFECYCLE]") and "->" in line


def test_transitions_are_bounded():
    # A long default-ON session must not grow the telemetry log without limit.
    m = PatientLoadModel()
    for i in range(2500):
        uid = f"S{i}"
        cid = CanonicalSeriesId(uid, "1", f"u{i}")
        m.on_selection("P", uid, Intent.OPEN_VIEWER)
        m.on_series_set(uid, [cid], expected={cid.key(): 1})
        m.on_disk_change(uid, cid, 1); m.on_decoded(uid, cid, 1)
    assert len(m.transitions) <= m._MAX_TRANSITIONS
    assert len(m._studies) <= m._MAX_STUDIES


def test_terminal_eviction_preserves_inflight():
    m = PatientLoadModel()
    # One in-flight (open, downloading) study that must NEVER be evicted.
    live = CanonicalSeriesId("LIVE", "1", "ulive")
    m.on_selection("P", "LIVE", Intent.OPEN_VIEWER)
    m.on_series_set("LIVE", [live], expected={live.key(): 10})
    m.on_disk_change("LIVE", live, 3)  # partial -> series_loading (non-terminal)
    # Flood with terminal preview studies to trigger eviction.
    for i in range(1500):
        uid = f"T{i}"; cid = CanonicalSeriesId(uid, "1", f"t{i}")
        m.on_selection("P", uid, Intent.PREVIEW_ONLY)
        m.on_series_set(uid, [cid]); m.mark_thumbs_rendered(uid)
    assert len(m._studies) <= m._MAX_STUDIES
    assert m.study("LIVE") is not None          # in-flight study survived
    assert m.study("LIVE").series[live.key()].on_disk == 3


def test_resolve_stale_thumbnail_action():
    from PacsClient.utils.patient_load_lifecycle import resolve_stale_thumbnail_action as R
    # Token matches -> always render (both legacy and cutover).
    assert R(token_matches=True, is_active_selection=False, cutover_enabled=False) == "render"
    assert R(token_matches=True, is_active_selection=True, cutover_enabled=True) == "render"
    # LEGACY (cutover off): a token mismatch always discards, even if still active.
    assert R(token_matches=False, is_active_selection=True, cutover_enabled=False) == "discard"
    assert R(token_matches=False, is_active_selection=False, cutover_enabled=False) == "discard"
    # CUTOVER: render a token-stale result IFF it is still the active selection
    # (the A->B->A fix); a non-active (cross-patient) result still discards.
    assert R(token_matches=False, is_active_selection=True, cutover_enabled=True) == "render"
    assert R(token_matches=False, is_active_selection=False, cutover_enabled=True) == "discard"


if __name__ == "__main__":  # allow standalone run if the test-dir conftest needs Qt
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
