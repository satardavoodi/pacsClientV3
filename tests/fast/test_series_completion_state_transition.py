"""
FAST-THUMB-STATE — Gap-1 regression suite.

Before the fix, complete_series_download only added to ready_series but
never called apply_border_states_new() unless parent_widget was set.
parent_widget is never set in production, so the green border never appeared.

This file is the permanent regression guard for that fix.
"""
import pytest


# ─── core regression tests ────────────────────────────────────────────────────

def test_complete_sets_border_ready(tm):
    """Gap-1 core: complete_series_download turns progress_border green."""
    tm.register_series(1)
    tm.start_series_download(1)
    tm.complete_series_download(1)

    border = tm.series_widgets["1"].progress_border
    assert border._is_ready, "progress_border._is_ready must be True after completion"


def test_complete_clears_downloading_flag(tm):
    """complete_series_download must clear the downloading flag."""
    tm.register_series(1)
    tm.start_series_download(1)
    tm.complete_series_download(1)

    assert not tm.series_widgets["1"].progress_border._downloading


def test_complete_adds_to_ready_series_set(tm):
    """series key must appear in ready_series after completion."""
    tm.register_series(1)
    tm.complete_series_download(1)
    assert "1" in tm.ready_series


def test_apply_border_states_called_during_completion(tm):
    """apply_border_states_new must be invoked by complete_series_download."""
    tm.register_series(1)
    count_before = tm._apply_count
    tm.complete_series_download(1)
    assert tm._apply_count > count_before, (
        "apply_border_states_new was not called during complete_series_download"
    )


# ─── edge cases ──────────────────────────────────────────────────────────────

def test_complete_without_prior_start(tm):
    """complete_series_download works even without a prior start_series_download call."""
    tm.register_series(5)
    tm.complete_series_download(5)
    assert "5" in tm.ready_series
    assert tm.series_widgets["5"].progress_border._is_ready


def test_complete_for_unregistered_series_does_not_raise(tm):
    """complete_series_download for an unknown series must not raise."""
    tm.complete_series_download(999)
    assert "999" in tm.ready_series  # still added to set even without widget


def test_register_after_complete_replays_ready_state(tm):
    """A thumbnail created after completion must immediately bind to ready state."""
    tm.complete_series_download(999, total_images=12)

    widget = tm.register_series(999)

    assert widget.progress_border._is_ready
    assert not widget.progress_border._downloading
    assert widget.count_label_text == "12/12"


def test_complete_is_idempotent(tm):
    """Calling complete_series_download twice must not crash or flip state."""
    tm.register_series(1)
    tm.complete_series_download(1)
    apply_count = tm._apply_count
    tm.complete_series_download(1)
    assert tm.series_widgets["1"].progress_border._is_ready
    assert tm._apply_count == apply_count


# ─── multi-series isolation ───────────────────────────────────────────────────

def test_complete_series_a_does_not_affect_series_b(tm):
    """Completing series A must leave series B unchanged."""
    tm.register_series(1)
    tm.register_series(2)
    tm.start_series_download(1)
    tm.start_series_download(2)
    tm.complete_series_download(1)

    assert tm.series_widgets["1"].progress_border._is_ready
    assert not tm.series_widgets["2"].progress_border._is_ready
    assert tm.series_widgets["2"].progress_border._downloading


def test_complete_multiple_series_in_order(tm):
    """Completing five series one by one marks each green independently."""
    for sn in range(1, 6):
        tm.register_series(sn)
        tm.start_series_download(sn)

    for sn in range(1, 6):
        # Before completion, not yet ready
        assert not tm.series_widgets[str(sn)].progress_border._is_ready
        tm.complete_series_download(sn)
        assert tm.series_widgets[str(sn)].progress_border._is_ready


def test_all_completed_series_in_ready_set(tm):
    """After completing all series the ready_series set contains every key."""
    keys = [11, 22, 33, 44, 55]
    for sn in keys:
        tm.register_series(sn)
    for sn in keys:
        tm.complete_series_download(sn)

    assert tm.ready_series == {str(k) for k in keys}


def test_complete_uses_stable_total_for_final_label(tm):
    tm.register_series(42)
    tm.start_series_download(42, total_images=145)
    tm.complete_series_download(42, total_images=999)

    assert tm.series_widgets["42"].count_label_text == "145/145"


def test_start_after_complete_begins_new_projection_cycle(tm):
    tm.register_series(9)
    tm.complete_series_download(9, total_images=10)

    tm.start_series_download(9, total_images=10)

    assert not tm.series_widgets["9"].progress_border._is_ready
    assert tm.series_widgets["9"].progress_border._downloading
