"""Regression guard: resync-on-reopen — server-vs-local study completeness (45611).

A multi-study patient (45611: an MR study + a DOC study) whose MR study GAINED
series on the server after first download (6 -> 18 series over a few days) kept
showing the stale local set on the home page. Two compounding causes:

* the multi-study GROUPED path (`_show_grouped_patient_studies`) renders local
  thumbnails and only queries the server when NONE exist locally, and
* the single-click "server grew" gate is fed by `_server_series_count_by_study`,
  which is deliberately suppressed for multi-study patients (the 44534 guard),
  so multi-study patients had NO growth detection at all.

The fix adds a smart, throttled, background server completeness check on
(re)select plus a forced manual "Refresh / Sync from server" right-click action.
It compares each study's OWN per-series list (never the patient-aggregate
count_of_series, so 44534 stays fixed), enqueues only the missing series for
background download (the DM resume-scan dedups), and re-renders with a
server-thumbnail merge so the new series appear without a manual cache wipe.

These tests pin that logic without the full Qt app (same stub pattern as
`test_resolve_patient_study_uids_scope.py`).
"""
import asyncio
import os
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_series as mod  # noqa: E402

_Mixin = mod._HPSeriesMixin

REPO_ROOT = Path(__file__).resolve().parents[3]
HOME_UI = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _isolate_growth_detection(monkeypatch):
    """These tests pin the per-series GROWTH detection + grouped reveal — NOT the
    disk-aware file check. The disk-aware check (_RESYNC_DISK_AWARE) reads the REAL
    disk via the sync manifest, but the stub models only DB series counts (no files),
    so it would report every stub study as 'files missing' and dominate the
    needs_sync decision. Disk completeness is covered by the storage manifest /
    open-skip suites; isolate it here so the growth logic is what's under test."""
    monkeypatch.setattr(mod, "_RESYNC_DISK_AWARE", False)


# ── pure growth detection (study's OWN per-series list, never the aggregate) ──
def test_detect_growth_new_series():
    grew, new, grown = _Mixin._detect_study_growth(
        {"1": 30, "2": 25, "3": 40}, {"1": 30})
    assert grew is True
    assert set(new) == {"2", "3"}
    assert grown == []


def test_detect_growth_more_instances_same_series():
    # 44113 shape: same series number, server has far more images locally absent.
    grew, new, grown = _Mixin._detect_study_growth({"1": 1408}, {"1": 30})
    assert grew is True
    assert new == []
    assert grown == ["1"]


def test_detect_growth_current_is_not_growth():
    grew, new, grown = _Mixin._detect_study_growth(
        {"1": 30, "2": 25}, {"1": 30, "2": 25})
    assert grew is False
    assert new == [] and grown == []


def test_detect_growth_local_ahead_is_not_false_grew():
    # Server image_count unknown (0) while we hold more locally must NOT read as
    # growth — otherwise every reopen would loop a pointless re-fetch.
    grew, _new, _grown = _Mixin._detect_study_growth({"1": 0, "2": 0}, {"1": 30, "2": 25})
    assert grew is False


# ── smart-check throttle ─────────────────────────────────────────────────────
def _throttle_stub():
    obj = types.SimpleNamespace()
    obj._study_due_for_resync = _Mixin._study_due_for_resync.__get__(obj)
    obj._mark_study_resync_checked = _Mixin._mark_study_resync_checked.__get__(obj)
    return obj


def test_throttle_first_due_then_suppressed_then_force():
    obj = _throttle_stub()
    assert obj._study_due_for_resync("U1") is True       # never checked → due
    obj._mark_study_resync_checked("U1")
    assert obj._study_due_for_resync("U1") is False       # within TTL → skip
    assert obj._study_due_for_resync("U1", force=True) is True  # manual overrides


def test_throttle_force_works_even_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(mod, "_RESYNC_ON_REOPEN_ENABLED", False)
    obj = _throttle_stub()
    assert obj._study_due_for_resync("U1") is False            # auto path off
    assert obj._study_due_for_resync("U1", force=True) is True  # manual still runs


# ── full async resync behaviour ──────────────────────────────────────────────
def _panel_stub(server_by_uid, local_by_uid, *, owner_by_uid=None, active=True):
    """Fake home panel recording save / enqueue / render calls."""
    obj = types.SimpleNamespace()
    rec = {"saved": [], "enqueued": [], "rendered": [], "traces": []}
    obj._rec = rec
    obj._study_due_for_resync = _Mixin._study_due_for_resync.__get__(obj)
    obj._mark_study_resync_checked = _Mixin._mark_study_resync_checked.__get__(obj)
    obj._resync_patient_studies_from_server = _Mixin._resync_patient_studies_from_server.__get__(obj)
    obj._detect_study_growth = _Mixin._detect_study_growth  # staticmethod
    obj._local_series_counts = lambda uid: dict(local_by_uid.get(uid, {}))

    def _fetch(uid, pid, force):
        sd = server_by_uid.get(uid)
        if sd is None:
            return None
        series = [{"series_number": sn, "image_count": c} for sn, c in sd.items()]
        owner = (owner_by_uid or {}).get(uid, pid)
        return {
            "patient_id": owner, "study_uid": uid, "count_of_series": len(series),
            "series": series, "study_date": "", "study_description": "", "modality": "",
        }

    obj._get_or_fetch_series_info = _fetch
    obj.save_complete_study_info = lambda uid, pid, study_info=None: rec["saved"].append(uid)

    class _DM:
        def add_downloads(self, items, start_immediately=False):
            rec["enqueued"].append(items[0]["study_uid"])

    obj._get_or_create_download_manager_tab = lambda activate_tab=False: _DM()
    obj._is_active_patient_selection = lambda pid, uid: active

    async def _grouped(pid, name, uids, force_server_merge=False):
        rec["rendered"].append(("grouped", tuple(uids), bool(force_server_merge)))

    obj._show_grouped_patient_studies = _grouped

    async def _show(info):
        rec["rendered"].append(("single", info.get("StudyInstanceUID")))

    obj.show_patient_studies = _show
    obj._log_open_trace = lambda *a, **k: rec["traces"].append((a, k))
    return obj, rec


def test_grown_multistudy_enqueues_missing_and_reveals():
    # MR grew (3 -> 4 series); DOC unchanged. Only MR is saved/enqueued; the
    # multi-study view re-renders WITH the server merge so new series appear.
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30, "4": 30},
                       "UID_DOC": {"100000": 1}},
        local_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30},
                      "UID_DOC": {"100000": 1}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR", "UID_DOC"], force=True))
    assert rec["saved"] == ["UID_MR"]
    assert rec["enqueued"] == ["UID_MR"]
    assert ("grouped", ("UID_MR", "UID_DOC"), True) in rec["rendered"]


def test_current_studies_do_nothing():
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30}},
        local_by_uid={"UID_MR": {"1": 30, "2": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=True))
    assert rec["saved"] == [] and rec["enqueued"] == [] and rec["rendered"] == []


def test_cross_patient_study_never_persisted_or_downloaded():
    # The server says this study belongs to a DIFFERENT patient → isolation guard
    # must skip it entirely (no save, no enqueue) and log the skip.
    obj, rec = _panel_stub(
        server_by_uid={"UID_LEAK": {"1": 30, "2": 30, "3": 30}},
        local_by_uid={"UID_LEAK": {"1": 30}},
        owner_by_uid={"UID_LEAK": "99999"},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_LEAK"], force=True))
    assert rec["saved"] == [] and rec["enqueued"] == []
    assert any(a[1] == "resync_cross_patient_skip" for (a, k) in rec["traces"])


def test_single_study_path_reveals_via_show_patient_studies():
    obj, rec = _panel_stub(
        server_by_uid={"UID_ONE": {"1": 30, "2": 30}},
        local_by_uid={"UID_ONE": {"1": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_ONE"], force=True))
    assert ("single", "UID_ONE") in rec["rendered"]


def test_throttle_blocks_second_auto_call():
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30}},
        local_by_uid={"UID_MR": {"1": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=False))
    assert rec["saved"] == ["UID_MR"]
    # second auto reselect within the TTL is throttled — no duplicate work
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=False))
    assert rec["saved"] == ["UID_MR"]
    # Single-click (auto, force=False) is SELECT/preview only — it persists the
    # refreshed metadata and reveals the grown series, but must NOT start a
    # download (regression fix: single-click was starting downloads). The
    # download happens on OPEN (double-click) / manual Refresh. So: no enqueue.
    assert rec["enqueued"] == []


def test_env_gate_blocks_auto_but_manual_force_runs(monkeypatch):
    monkeypatch.setattr(mod, "_RESYNC_ON_REOPEN_ENABLED", False)
    obj, rec = _panel_stub(
        server_by_uid={"U": {"1": 1, "2": 1}},
        local_by_uid={"U": {"1": 1}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["U"], force=False))
    assert rec["saved"] == []          # auto path gated off
    _run(obj._resync_patient_studies_from_server("45611", "X", ["U"], force=True))
    assert rec["saved"] == ["U"]        # manual refresh bypasses the gate


def test_inactive_selection_syncs_data_but_does_not_render():
    # Manual refresh on a patient the user has since clicked away from: still pull
    # the new series (download), but do NOT hijack the now-active view.
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30}},
        local_by_uid={"UID_MR": {"1": 30}},
        active=False,
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=True))
    assert rec["enqueued"] == ["UID_MR"]
    assert rec["rendered"] == []


# ── single-click = SELECT/preview only (NO download); OPEN/manual downloads ──
def test_auto_resync_single_click_saves_and_reveals_but_no_download(monkeypatch):
    # force=False = the AUTO resync fired by a single-click reselect. With the
    # default (fix) it persists the refreshed metadata (for display) and reveals
    # the grown series, but must NOT enqueue a download.
    monkeypatch.setattr(mod, "_SINGLE_CLICK_DOWNLOAD_ENABLED", False)
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30, "4": 30}},
        local_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=False))
    assert rec["saved"] == ["UID_MR"]      # metadata persists (display refresh)
    assert rec["enqueued"] == []           # single-click must NOT download
    assert any(a[1] == "resync_enqueue_skipped_single_click" for (a, k) in rec["traces"])


def test_manual_force_resync_still_downloads():
    # The explicit "Refresh / Sync from server" (force=True) DOES download.
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30, "4": 30}},
        local_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=True))
    assert rec["enqueued"] == ["UID_MR"]
    assert any(a[1] == "DownloadEnqueued" for (a, k) in rec["traces"])


def test_legacy_flag_restores_auto_single_click_download(monkeypatch):
    # Reversibility: AIPACS_SINGLE_CLICK_DOWNLOAD=1 restores the legacy
    # enqueue-on-single-click behaviour for an auto (force=False) resync.
    monkeypatch.setattr(mod, "_SINGLE_CLICK_DOWNLOAD_ENABLED", True)
    obj, rec = _panel_stub(
        server_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30, "4": 30}},
        local_by_uid={"UID_MR": {"1": 30, "2": 30, "3": 30}},
    )
    _run(obj._resync_patient_studies_from_server("45611", "X", ["UID_MR"], force=False))
    assert rec["enqueued"] == ["UID_MR"]


# ── source wiring guards ─────────────────────────────────────────────────────
def test_source_wiring_present():
    series = (HOME_UI / "home_panel" / "_hp_series.py").read_text(encoding="utf-8")
    assert "AIPACS_RESYNC_ON_REOPEN" in series                 # env gate
    assert "_resync_patient_studies_from_server" in series      # core helper
    assert "resync_cross_patient_skip" in series                # isolation guard
    assert "force_server_merge=True" in series                  # reveal re-render
    assert "_detect_study_growth" in series                     # per-study compare
    # Single-click-no-download regression guard: the resync + reconcile enqueues
    # must be gated so a single-click SELECT never starts a full download.
    assert "AIPACS_SINGLE_CLICK_DOWNLOAD" in series             # env flag (default off)
    assert "_SINGLE_CLICK_DOWNLOAD_ENABLED" in series           # gate symbol
    assert "if force or _SINGLE_CLICK_DOWNLOAD_ENABLED" in series  # resync enqueue gated
    assert "resync_enqueue_skipped_single_click" in series      # auto-skip trace
    assert "reconcile_enqueue_skipped_single_click" in series   # discovery-skip trace
    assert "PatientSelectedSingleClick" in series               # single-click marker
    open_src = (HOME_UI / "home_panel" / "_hp_patient_open.py").read_text(encoding="utf-8")
    assert "PatientOpenDoubleClick" in open_src                 # double-click open marker
    assert "DownloadEnqueued" in open_src                       # open enqueue trace
    modules = (HOME_UI / "home_panel" / "_hp_modules.py").read_text(encoding="utf-8")
    assert "force_server_merge" in modules                      # grouped merge param
    table = (HOME_UI / "patient_table_widget.py").read_text(encoding="utf-8")
    assert "resyncFromServerRequested" in table                 # context-menu signal
    assert "Refresh / Sync from server" in table                # menu label
    layout = (HOME_UI / "home_panel" / "_hp_layout.py").read_text(encoding="utf-8")
    assert "resyncFromServerRequested.connect" in layout        # signal wired
