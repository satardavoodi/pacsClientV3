"""Guard: the manual Download button must download the patient's FULL study set.

Root cause (field report, 2026-07-23): checking a patient in the list and
clicking Download enqueued ONLY the study_uid carried by each table row.
GetPatientList returns just the LATEST study UID per patient, grouped rows carry
a `study_uids` list that the download path IGNORED (and that can be stale), and
`add_downloads` rejects any study with an existing DM state — including stale
COMPLETED. Net effect: a multi-study patient's newest study (typically the
scanned-document study) was silently skipped by the explicit Download and only
appeared later when the OPEN path's reconcile/back-fill discovered it — two
different discovery pipelines for the same user intent.

These tests pin the unification (`_hp_download.py`, 2026-07-23):

  * `_expand_selection_to_patient_studysets` routes discovery through the SAME
    authority the open/single-click paths use (`_reconcile_patient_studies_on_click`,
    falling back to `_resolve_patient_study_uids`), owner-filtered via the
    canonical `merge_study_uids`.
  * `_reset_stale_terminal_dm_state` mirrors the open back-fill / resync
    stale-COMPLETED unblock so a study that GREW on the server is re-accepted.
  * `_manual_download_with_patient_discovery` enriches every study fresh
    (force_refresh), applies the cross-patient guard, and enqueues ALL of the
    patient's studies — never losing the user's click on any internal failure.
  * Kill switch AIPACS_MANUAL_DL_PATIENT_DISCOVERY=0 / no running loop restores
    the legacy row-only behavior (`_start_manual_download_with_discovery` -> False).

Headless: no Qt widgets, no server, no DB — collaborators are stubbed on a
plain object that mixes in the real `_HPDownloadMixin` methods.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_download as hpdl


P1 = "PID-100"
S_IMG_OLD = "1.2.826.0.1.999.1"      # older imaging study (row primary)
S_IMG_2 = "1.2.826.0.1.999.2"        # second study carried on the grouped row
S_DOC_NEW = "1.2.826.0.1.999.3.docs"  # newest scanned-document study (server-only)
S_FOREIGN = "1.2.826.0.1.999.4.leak"  # belongs to a different patient


class _FakeState:
    def __init__(self, status_name):
        self.status = type("S", (), {"name": status_name, "value": status_name})()


class _FakeStateStore:
    def __init__(self, states=None):
        self._states = dict(states or {})
        self.reset_calls = []

    def get(self, uid):
        return self._states.get(uid)

    def reset(self, uid):
        self.reset_calls.append(uid)
        self._states.pop(uid, None)


class _FakeZetaManager:
    def __init__(self, states=None):
        self.state_store = _FakeStateStore(states)
        self.add_calls = []

    def add_downloads(self, studies, start_immediately=False):
        self.add_calls.append((list(studies), start_immediately))


class _Panel(hpdl._HPDownloadMixin):
    """Real mixin methods + stubbed collaborators (no Qt, no server)."""

    def __init__(self, *, reconcile_result=None, reconcile_raises=False,
                 resolver_result=None, owner_map=None, series_info=None,
                 series_info_raises=False):
        self._reconcile_result = list(reconcile_result or [])
        self._reconcile_raises = reconcile_raises
        self._resolver_result = list(resolver_result or [])
        self._owner_map = dict(owner_map or {})
        self._series_info = dict(series_info or {})
        self._series_info_raises = series_info_raises
        self.trace_events = []
        self.reconcile_calls = []

    async def _reconcile_patient_studies_on_click(self, pid, pname, primary):
        self.reconcile_calls.append((pid, pname, primary))
        if self._reconcile_raises:
            raise RuntimeError("server unreachable")
        return list(self._reconcile_result)

    def _resolve_patient_study_uids(self, pid, primary):
        return list(self._resolver_result)

    def _study_owner_patient_id(self, uid):
        return self._owner_map.get(uid)

    def _log_open_trace(self, uid, event, **kw):
        self.trace_events.append((event, uid, kw))

    def _get_or_fetch_series_info(self, uid, pid, force_refresh=False):
        if self._series_info_raises:
            raise RuntimeError("socket down")
        return self._series_info.get(uid)


def _row(uid=S_IMG_OLD, uids=(S_IMG_OLD, S_IMG_2), pid=P1, name="TEST^PATIENT"):
    return {"patient_id": pid, "patient_name": name,
            "study_uid": uid, "study_uids": list(uids)}


def _info(uid, pid=P1, n=2):
    return {"patient_id": pid, "study_date": "20260723",
            "study_description": f"info-{uid[-6:]}",
            "count_of_series": n,
            "series": [{"series_number": str(i + 1), "image_count": 3}
                       for i in range(n)]}


# ── expansion ───────────────────────────────────────────────────────────────

def test_expansion_discovers_full_patient_studyset():
    """The reported bug: server knows a newer (scanned-doc) study the row does
    not carry — expansion must include it exactly once, rows first."""
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_IMG_2, S_DOC_NEW])
    out = asyncio.run(panel._expand_selection_to_patient_studysets([_row()]))

    uids = [s["study_uid"] for s in out]
    assert uids == [S_IMG_OLD, S_IMG_2, S_DOC_NEW]
    assert panel.reconcile_calls == [(P1, "TEST^PATIENT", S_IMG_OLD)]
    # the discovered dicts carry the patient identity for the DM payload
    added = out[-1]
    assert added["patient_id"] == P1 and added["patient_name"] == "TEST^PATIENT"
    events = [e for e, _, _ in panel.trace_events]
    assert "manual_download_expanded" in events


def test_expansion_ignored_row_study_uids_are_now_used():
    """Even with reconcile unavailable, the grouped row's `study_uids` tail
    (previously ignored entirely) must be enqueued."""
    panel = _Panel(reconcile_raises=True, resolver_result=[])
    out = asyncio.run(panel._expand_selection_to_patient_studysets([_row()]))
    assert [s["study_uid"] for s in out] == [S_IMG_OLD, S_IMG_2]


def test_expansion_falls_back_to_local_resolver_when_reconcile_fails():
    panel = _Panel(reconcile_raises=True,
                   resolver_result=[S_IMG_OLD, S_IMG_2, S_DOC_NEW])
    out = asyncio.run(panel._expand_selection_to_patient_studysets([_row()]))
    assert S_DOC_NEW in [s["study_uid"] for s in out]


def test_expansion_owner_filter_drops_foreign_study():
    """Clinical isolation: a study positively owned by ANOTHER patient must not
    ride into this patient's download set."""
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_DOC_NEW, S_FOREIGN],
                   owner_map={S_FOREIGN: "OTHER-PATIENT"})
    out = asyncio.run(panel._expand_selection_to_patient_studysets([_row()]))
    uids = [s["study_uid"] for s in out]
    assert S_FOREIGN not in uids
    assert S_DOC_NEW in uids


def test_expansion_dedupes_across_rows_and_never_loses_rows():
    """Two checked rows of the same patient -> one reconcile, no duplicate
    dicts; rows without a patient_id pass through untouched."""
    row_a = _row(uid=S_IMG_OLD, uids=(S_IMG_OLD,))
    row_b = _row(uid=S_IMG_2, uids=(S_IMG_2,))
    orphan = {"patient_id": "", "patient_name": "", "study_uid": "1.2.3.orphan"}
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_IMG_2, S_DOC_NEW])
    out = asyncio.run(panel._expand_selection_to_patient_studysets(
        [row_a, row_b, orphan]))
    uids = [s["study_uid"] for s in out]
    assert uids.count(S_IMG_OLD) == 1 and uids.count(S_IMG_2) == 1
    assert "1.2.3.orphan" in uids
    assert uids.count(S_DOC_NEW) == 1
    assert len(panel.reconcile_calls) == 1  # one reconcile per patient


def test_expansion_total_failure_returns_input_unchanged():
    """The click must never be lost: if expansion itself blows up, the raw
    selection is returned."""
    panel = _Panel()

    async def _boom(*a, **k):
        raise RuntimeError("boom")

    panel._reconcile_patient_studies_on_click = _boom
    panel._resolve_patient_study_uids = None  # not callable -> inner except
    rows = [_row()]
    out = asyncio.run(panel._expand_selection_to_patient_studysets(rows))
    assert [s["study_uid"] for s in out][:1] == [S_IMG_OLD]


# ── stale-terminal reset ────────────────────────────────────────────────────

def test_reset_stale_terminal_state_mirrors_open_backfill():
    zm = _FakeZetaManager(states={
        S_IMG_OLD: _FakeState("COMPLETED"),
        S_IMG_2: _FakeState("DOWNLOADING"),
        S_DOC_NEW: _FakeState("CANCELLED"),
    })
    panel = _Panel()
    n = panel._reset_stale_terminal_dm_state(
        zm, [{"study_uid": u} for u in (S_IMG_OLD, S_IMG_2, S_DOC_NEW)])
    assert n == 2
    assert sorted(zm.state_store.reset_calls) == sorted([S_IMG_OLD, S_DOC_NEW])
    # an ACTIVE download is never reset
    assert S_IMG_2 not in zm.state_store.reset_calls


# ── full flow ───────────────────────────────────────────────────────────────

def test_full_flow_enqueues_every_study_enriched_and_reset():
    """End-to-end: 1 checked row -> 3 studies enqueued in ONE add_downloads call,
    each enriched with fresh server series info; stale COMPLETED reset first."""
    infos = {u: _info(u) for u in (S_IMG_OLD, S_IMG_2, S_DOC_NEW)}
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_IMG_2, S_DOC_NEW],
                   series_info=infos)
    zm = _FakeZetaManager(states={S_IMG_OLD: _FakeState("COMPLETED")})

    asyncio.run(panel._manual_download_with_patient_discovery([_row()], zm))

    assert len(zm.add_calls) == 1
    studies, start = zm.add_calls[0]
    assert start is True
    uids = [s["study_uid"] for s in studies]
    assert uids == [S_IMG_OLD, S_IMG_2, S_DOC_NEW]
    for s in studies:
        assert s["series"], "every study must be enriched with fresh series info"
        assert s["series_count"] == 2
    assert zm.state_store.reset_calls == [S_IMG_OLD]
    enq = [(e, u) for e, u, _ in panel.trace_events if e == "DownloadEnqueued"]
    assert len(enq) == 3


def test_full_flow_cross_patient_guard_drops_foreign_info():
    """If the server's study-info attributes a study to ANOTHER patient, it is
    dropped from the enqueue (same guard as resync/reconcile)."""
    infos = {S_IMG_OLD: _info(S_IMG_OLD),
             S_DOC_NEW: _info(S_DOC_NEW, pid="OTHER-PATIENT")}
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_DOC_NEW], series_info=infos)
    zm = _FakeZetaManager()

    asyncio.run(panel._manual_download_with_patient_discovery(
        [_row(uids=(S_IMG_OLD,))], zm))

    studies, _ = zm.add_calls[0]
    uids = [s["study_uid"] for s in studies]
    assert S_DOC_NEW not in uids and S_IMG_OLD in uids
    events = [e for e, _, _ in panel.trace_events]
    assert "manual_download_cross_patient_skip" in events


def test_full_flow_series_fetch_failure_still_enqueues():
    """A dead socket must not lose the click: studies enqueue un-enriched
    (legacy shape) instead of vanishing."""
    panel = _Panel(reconcile_result=[S_IMG_OLD, S_IMG_2],
                   series_info_raises=True)
    zm = _FakeZetaManager()
    asyncio.run(panel._manual_download_with_patient_discovery(
        [_row(uids=(S_IMG_OLD,))], zm))
    studies, _ = zm.add_calls[0]
    assert {s["study_uid"] for s in studies} == {S_IMG_OLD, S_IMG_2}


# ── gating / kill switch ────────────────────────────────────────────────────

def test_kill_switch_restores_legacy_path(monkeypatch):
    monkeypatch.setattr(hpdl, "_MANUAL_DL_PATIENT_DISCOVERY", False)
    panel = _Panel()
    assert panel._start_manual_download_with_discovery([_row()], _FakeZetaManager()) is False


def test_no_running_loop_falls_back_to_legacy_path():
    panel = _Panel()
    # No asyncio loop is running in this test process' main thread.
    assert panel._start_manual_download_with_discovery([_row()], _FakeZetaManager()) is False


def test_running_loop_schedules_discovery_task():
    panel = _Panel(reconcile_result=[S_IMG_OLD])
    zm = _FakeZetaManager()

    async def _drive():
        started = panel._start_manual_download_with_discovery([_row(uids=(S_IMG_OLD,))], zm)
        assert started is True
        await panel._manual_dl_discovery_task

    asyncio.run(_drive())
    assert len(zm.add_calls) == 1
