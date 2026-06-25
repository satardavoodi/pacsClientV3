"""S0 contract tests for the viewer-unification spine (pure, unwired).

Covers ``PacsClient/utils/viewer_identity.py`` (ViewerHandle + SeriesRequest) and
``PacsClient/utils/series_state_store.py`` (SeriesState + SeriesStateStore). These modules are
introduced UNUSED in S0; these tests lock the contract before any production wiring (S1+).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md
"""
import threading

import pytest

from PacsClient.utils.viewer_identity import ViewerHandle, SeriesRequest
from PacsClient.utils.series_state_store import (
    SeriesState, SeriesStateStore, can_transition,
)


# --------------------------------------------------------------------------- #
# ViewerHandle — identity is the uuid; slot is diagnostic only (the A1 fix)
# --------------------------------------------------------------------------- #

def test_handle_unique_and_identity_is_uuid():
    a, b = ViewerHandle.new(), ViewerHandle.new()
    assert a != b and a.uuid != b.uuid
    assert a == ViewerHandle(uuid=a.uuid)


def test_handle_slot_does_not_affect_identity():
    h = ViewerHandle.new(slot_hint=0)
    moved = h.with_slot(3)            # viewport dragged to another grid cell
    assert moved == h                 # SAME identity despite different slot
    assert moved.slot_hint == 3 and h.slot_hint == 0
    # Two different handles that happen to occupy the same slot are NOT equal.
    assert ViewerHandle.new(slot_hint=0) != ViewerHandle.new(slot_hint=0)


# --------------------------------------------------------------------------- #
# SeriesRequest — normalization, keys, isolation predicates
# --------------------------------------------------------------------------- #

def _req(pid="P1", study="S1", series="U1", key=None, handle=None, intent="display"):
    return SeriesRequest.create(patient_id=pid, study_uid=study, series_uid=series,
                                display_key=key, viewer_handle=handle, intent=intent)


def test_request_normalizes_and_defaults_display_key():
    r = SeriesRequest.create(patient_id=" P1 ", study_uid=" S1 ", series_uid=" U1 ")
    assert r.patient_id == "P1" and r.study_uid == "S1" and r.series_uid == "U1"
    assert r.display_key == "U1"          # defaults to series_uid when absent
    assert r.intent == "display" and r.viewer_handle is not None


def test_request_keys():
    r = _req(key="1000203")
    assert r.identity_key == ("P1", "S1", "U1")     # patient-scoped (isolation)
    assert r.series_scope_key == ("S1", "U1")        # globally-unique (disk/state)
    assert r.display_key == "1000203"                 # multi-study offset key (UI only)


def test_request_validity():
    assert _req().is_valid()
    assert not SeriesRequest.create(patient_id="", study_uid="S", series_uid="U").is_valid()
    assert not SeriesRequest.create(patient_id="P", study_uid="", series_uid="U").is_valid()


def test_same_series_vs_same_target():
    h1, h2 = ViewerHandle.new(slot_hint=0), ViewerHandle.new(slot_hint=0)
    a = _req(handle=h1)
    b = _req(handle=h2)                  # same series, DIFFERENT viewport (same slot!)
    assert a.is_same_series(b)
    assert not a.is_same_target(b)       # the A1 fix: same grid slot ≠ same request
    assert a.is_same_target(a.for_handle(h1))


def test_cross_patient_isolation_predicate():
    r = _req(pid="P1")
    assert r.belongs_to_patient("P1")
    assert not r.belongs_to_patient("P2")
    assert not _req(pid="").belongs_to_patient("")   # empty never belongs


# --------------------------------------------------------------------------- #
# can_transition — the pure state machine
# --------------------------------------------------------------------------- #

def test_transition_forward_skip_idempotent():
    assert can_transition(SeriesState.REQUESTED, SeriesState.DOWNLOADING)     # skip QUEUED
    assert can_transition(SeriesState.DOWNLOADING, SeriesState.DISPLAYED)     # skip ahead
    assert can_transition(SeriesState.DISPLAYED, SeriesState.DISPLAYED)       # idempotent


def test_transition_backward_blocked_except_refetch():
    assert not can_transition(SeriesState.DISPLAYED, SeriesState.DECODING)
    assert not can_transition(SeriesState.DECODING, SeriesState.QUEUED)
    # the single sanctioned backward edge: server-grew re-fetch
    assert can_transition(SeriesState.DISPLAYED, SeriesState.DOWNLOADING)
    assert can_transition(SeriesState.PARTIAL_ON_DISK, SeriesState.DOWNLOADING)


def test_transition_failed_always_and_retry():
    for s in SeriesState:
        assert can_transition(s, SeriesState.FAILED)
    assert can_transition(SeriesState.FAILED, SeriesState.DOWNLOADING)


# --------------------------------------------------------------------------- #
# SeriesStateStore — ownership, monotonic counts, isolation
# --------------------------------------------------------------------------- #

def test_request_claims_ownership():
    store = SeriesStateStore()
    r = _req()
    rec = store.request(r, expected=8)
    assert rec.state == SeriesState.REQUESTED
    assert rec.expected_count == 8
    assert store.is_owner(r.study_uid, r.series_uid, r.viewer_handle)


def test_require_owner_blocks_stale_worker():
    """A stale worker (old handle) cannot mutate a series a newer request took over — the
    F1 / ownership-leak class, made structural."""
    store = SeriesStateStore()
    old = _req(handle=ViewerHandle.new())
    store.request(old)
    new = old.for_handle(ViewerHandle.new())
    store.request(new)                   # ownership handed over to the new handle
    ok, reason = store.transition(old.study_uid, old.series_uid, SeriesState.DOWNLOADING,
                                  by_handle=old.viewer_handle, require_owner=True)
    assert not ok and reason == "not_owner"
    ok2, _ = store.transition(new.study_uid, new.series_uid, SeriesState.DOWNLOADING,
                              by_handle=new.viewer_handle, require_owner=True)
    assert ok2


def test_release_owner_is_atomic_no_leak():
    store = SeriesStateStore()
    r = _req()
    store.request(r)
    ok, _ = store.transition(r.study_uid, r.series_uid, SeriesState.DISPLAYED,
                             by_handle=r.viewer_handle, displayed=8, disk=8, release_owner=True)
    assert ok
    assert not store.is_owner(r.study_uid, r.series_uid, r.viewer_handle)   # released atomically


def test_displayed_count_is_monotonic():
    """The 99→8 downgrade guard, structural: a smaller displayed count is ignored."""
    store = SeriesStateStore()
    r = _req()
    store.request(r)
    store.transition(r.study_uid, r.series_uid, SeriesState.DISPLAYED, displayed=99, disk=99)
    store.transition(r.study_uid, r.series_uid, SeriesState.DISPLAYED, displayed=8)
    rec = store.get(r.study_uid, r.series_uid)
    assert rec.displayed_count == 99


def test_refetch_resets_counts_on_server_grew():
    store = SeriesStateStore()
    r = _req()
    store.request(r)
    store.transition(r.study_uid, r.series_uid, SeriesState.DISPLAYED, displayed=8, disk=8)
    # server grew → re-fetch resets to the new truth
    ok, _ = store.transition(r.study_uid, r.series_uid, SeriesState.DOWNLOADING,
                             disk=8, expected=20)
    assert ok
    rec = store.get(r.study_uid, r.series_uid)
    assert rec.expected_count == 20 and rec.target_count == 20


def test_target_count_and_settled():
    store = SeriesStateStore()
    r = _req()
    store.request(r, expected=10)
    store.transition(r.study_uid, r.series_uid, SeriesState.DOWNLOADING, disk=4)
    rec = store.get(r.study_uid, r.series_uid)
    assert rec.target_count == 10 and not rec.is_settled
    store.transition(r.study_uid, r.series_uid, SeriesState.DISPLAYED, disk=10, displayed=10)
    assert store.get(r.study_uid, r.series_uid).is_settled


def test_clear_patient_isolation():
    store = SeriesStateStore()
    a = _req(pid="P1", study="S1", series="U1")
    b = _req(pid="P2", study="S2", series="U2")
    store.request(a)
    store.request(b)
    assert store.clear_patient("P1") == 1
    assert store.get("S1", "U1") is None
    assert store.get("S2", "U2") is not None


def test_unknown_series_transition_is_safe():
    store = SeriesStateStore()
    ok, reason = store.transition("Sx", "Ux", SeriesState.DOWNLOADING)
    assert not ok and reason == "unknown_series"


def test_thread_safety_smoke():
    """Concurrent advances must not crash or strand the record; final state is consistent."""
    store = SeriesStateStore()
    r = _req()
    store.request(r, expected=50)

    def worker(n):
        for i in range(50):
            store.transition(r.study_uid, r.series_uid, SeriesState.DOWNLOADING, disk=i, displayed=i)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rec = store.get(r.study_uid, r.series_uid)
    assert rec.disk_count == 49 and rec.displayed_count == 49      # monotonic max held
    assert rec.state == SeriesState.DOWNLOADING
