"""Guards for the viewport loading-state lifecycle (2026-06-17, patient 46970).

Bug: the fail-safe spinner timeout hid the loading state UNCONDITIONALLY after
20 s, so a slow / queued / second-study series that was still downloading blanked
the viewport (and only a re-drag recovered it). The loading state must instead
persist while the viewport is still awaiting its dropped series and end only on
success, an explicit error, or replacement by another series.

These tests pin the pure timeout-decision helper and that the persistent lifecycle
+ structured logging are wired in. ``_vc_switch`` pulls heavy Qt deps, so the
import is skip-guarded (matching the other viewer tests).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SWITCH = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py"
_PROG = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"
_SRC_SWITCH = _SWITCH.read_text(encoding="utf-8")
_SRC_PROG = _PROG.read_text(encoding="utf-8")


def _action():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_switch import _spinner_timeout_action
    except Exception as exc:  # heavy Qt deps absent in this shard
        pytest.skip(f"_vc_switch import unavailable: {exc}")
    return _spinner_timeout_action


def _disk_ready():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import _disk_ready_complete
    except Exception as exc:  # heavy Qt deps absent in this shard
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    return _disk_ready_complete


# ---- pure timeout decision ----------------------------------------------

def test_still_awaiting_keeps_loading_state():
    act = _action()
    # Cap disabled (0): an awaiting viewport NEVER hides, no matter how long.
    assert act("1000302", 20_000, 0) == "wait"
    assert act("1000302", 10_000_000, 0) == "wait"


def test_not_awaiting_hides():
    act = _action()
    # Loaded / cleared / replaced (no awaiting marker) → safe to hide.
    assert act(None, 20_000, 0) == "hide"
    assert act("", 999, 0) == "hide"


def test_hard_cap_surfaces_error_only_when_enabled():
    act = _action()
    # With an opt-in cap, an over-long wait becomes an explicit error (not blank).
    assert act("1000302", 4_999, 5_000) == "wait"
    assert act("1000302", 5_000, 5_000) == "error"
    assert act("1000302", 9_999, 5_000) == "error"


def test_never_blanks_while_awaiting_regression():
    act = _action()
    # The exact regression: 20 s elapsed, still awaiting, default cap → must NOT hide.
    assert act("302", 20_000, 0) != "hide"


# ---- lifecycle + persistence wiring -------------------------------------

def test_persist_flag_defaults_on_with_kill_switch():
    assert 'AIPACS_VIEWPORT_LOADING_PERSIST", "1"' in _SRC_SWITCH


def test_timeout_uses_decision_and_rearms():
    # The arm path consults the pure decision and re-arms (does not one-shot hide).
    assert "_spinner_timeout_action(" in _SRC_SWITCH
    assert "_loading_timeout_gen" in _SRC_SWITCH  # generation guard against pile-up


def test_lifecycle_events_present():
    for event in (
        "ViewportLoadRequested",
        "RemoteSeriesDownloadAttached",
        "ViewportLoadWaitingForDownload",
        "ViewportLoadingStateCleared",
        "ViewportLoadCancelledByReplacement",
        "ViewportLoadFailed",
    ):
        assert event in _SRC_SWITCH, f"missing lifecycle event {event!r}"
    # Success is logged from the progressive apply path.
    assert "ViewportLoadSucceeded" in _SRC_PROG


def test_error_state_is_not_blank():
    # The error path shows a message via the spinner rather than hiding it.
    assert "def _enter_viewport_load_error(" in _SRC_SWITCH
    assert "Still loading" in _SRC_SWITCH


# ---- disk-readiness resume (patient 46713 DOC/Study-2) ------------------

def test_disk_ready_complete_by_expected_count():
    dr = _disk_ready()
    assert dr(4, 4, None) is True       # met expected
    assert dr(5, 4, None) is True       # exceeds expected
    assert dr(3, 4, None) is False      # below expected → not ready


def test_disk_ready_complete_by_stable_count_when_expected_unknown():
    dr = _disk_ready()
    # Expected unknown (0): ready only when the count is STABLE across two ticks.
    assert dr(4, 0, None) is False      # first sighting — not yet stable
    assert dr(4, 0, 4) is True          # unchanged since last tick → download done
    assert dr(4, 0, 2) is False         # still growing → not ready


def test_disk_ready_never_complete_with_no_files():
    dr = _disk_ready()
    assert dr(0, 4, 0) is False
    assert dr(0, 0, 0) is False


def test_disk_ready_resume_wired_into_watchdog():
    assert "def _maybe_resume_awaiting_from_disk(" in _SRC_PROG
    assert "_maybe_resume_awaiting_from_disk(vtk_w, sn)" in _SRC_PROG
    # S3b cutover 2026-06-27: the AIPACS_VIEWPORT_DISK_READY_RESUME flag was removed — the resume
    # is now UNCONDITIONAL (the watchdog always calls it; no `if flag:` gate to leave it off).
    assert 'getenv("AIPACS_VIEWPORT_DISK_READY_RESUME"' not in _SRC_PROG
    assert "ViewportLoadResumedFromDisk" in _SRC_PROG
    # Resumes via the proven display-key load path, once per awaiting episode.
    assert "change_series_on_viewer(display_key)" in _SRC_PROG
    assert "_disk_ready_resume_done" in _SRC_PROG


def test_disk_ready_resume_episode_guard_reset_on_new_await():
    # A fresh awaiting episode re-allows one resume (the guard is reset).
    assert "_disk_ready_resume_done = False" in _SRC_SWITCH
