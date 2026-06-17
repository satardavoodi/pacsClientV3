"""Guards for global drag view-intent coalescing (2026-06-17, slow-link thrash).

Production complaint: on a very slow/dropping link, an impatient user re-drags
different series/studies repeatedly. The per-(study,series) cooldowns absorb
hammering the SAME series, but ALTERNATING series/studies produce a new key each
time and bypass them — every drop fires a fresh set_viewed_series (→ coordinator
preempt) and per-series retry (→ pause-all + subprocess teardown) for the single
download slot, so nothing finishes. The fix routes the drop's DM intent through ONE
study-agnostic, last-write-wins target: rapid drops collapse to the FINAL target.

These tests pin the pure last-write-wins merge AND that the coalescer is wired into
the drop path (so it can't pass while being dead code). ``_vc_load`` pulls heavy Qt
deps, so the helper import is guarded with a skip (matching test_batch_growth.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_VC_LOAD = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py"
_VC_SWITCH = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py"
_SRC_LOAD = _VC_LOAD.read_text(encoding="utf-8")
_SRC_SWITCH = _VC_SWITCH.read_text(encoding="utf-8")


def _merge():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_load import _merge_drag_view_intent
    except Exception as exc:  # heavy Qt/viewer deps absent in this shard
        pytest.skip(f"_vc_load import unavailable: {exc}")
    return _merge_drag_view_intent


# ---- pure last-write-wins merge -----------------------------------------

def test_first_intent_records_target_and_flag():
    merge = _merge()
    assert merge(None, "5", True, False) == {"series": "5", "notify": True, "trigger": False}


def test_same_series_or_merges_flags():
    merge = _merge()
    # A notify-only then a trigger-only for the SAME final series → both take effect.
    prev = merge(None, "5", True, False)
    assert merge(prev, "5", False, True) == {"series": "5", "notify": True, "trigger": True}


def test_different_series_replaces_target_last_write_wins():
    merge = _merge()
    # The user alternates 5 → 7; only the FINAL series survives the window.
    prev = merge(None, "5", True, True)
    out = merge(prev, "7", True, False)
    assert out == {"series": "7", "notify": True, "trigger": False}
    # The replaced series' flags are NOT carried over (no stale 5 promotion).
    assert out["series"] == "7"


def test_series_coerced_to_str():
    merge = _merge()
    assert merge(None, 7, True, False)["series"] == "7"
    prev = {"series": "7", "notify": False, "trigger": True}
    assert merge(prev, 7, True, False) == {"series": "7", "notify": True, "trigger": True}


def test_final_drop_in_a_burst_is_the_one_that_survives():
    merge = _merge()
    # Simulate a 4-drop burst across two studies' series: 3, 8, 3, 12.
    pending = None
    for sn in ("3", "8", "3", "12"):
        pending = merge(pending, sn, want_notify=True, want_trigger=False)
    assert pending["series"] == "12"  # only the last settles


# ---- wiring into the drop path (catches a refactor that drops it) --------

def test_flag_defaults_on_with_zero_kill_switch():
    assert 'AIPACS_DRAGDROP_DEBOUNCE", "1"' in _SRC_LOAD  # default on; "=0" disables


def test_coalescer_methods_present():
    assert "def _coalesce_dm_view_intent(" in _SRC_LOAD
    assert "def _dispatch_coalesced_dm_view_intent(" in _SRC_LOAD
    # The debounce is a (re)started single-shot timer (last-write-wins cancel/restart).
    assert "setSingleShot(True)" in _SRC_LOAD


def test_drop_path_routes_through_coalescer():
    # All three DM-intent call sites in the switch path go through the coalescer,
    # not the raw notify/trigger methods.
    assert _SRC_SWITCH.count("_coalesce_dm_view_intent(") >= 3


def test_legacy_path_preserved_as_kill_switch():
    # When the flag is off, the coalescer dispatches immediately (the legacy
    # per-key behavior) — both raw methods still referenced inside the coalescer.
    assert "_notify_dm_viewed_series(series_number)" in _SRC_LOAD
    assert "_trigger_download_if_needed(series_number)" in _SRC_LOAD
