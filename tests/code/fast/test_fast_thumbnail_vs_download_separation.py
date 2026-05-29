"""
FAST separation contract: thumbnail overview (instant) and series download
(stateful, ordered) operate as independent paths that share only the widget
reference.

Key invariants:
 1. Thumbnail created ≠ download started.
 2. Download started ≠ download completed (ready).
 3. Only complete_series_download produces _is_ready=True.
 4. All three phases are isolated per series.
"""
import pytest


def test_thumbnail_creation_independent_of_download(tm):
    """Thumbnails can be registered with no download activity whatsoever."""
    for sn in [1, 2, 3]:
        tm.register_series(sn)
    assert len(tm.series_widgets) == 3
    assert len(tm.ready_series) == 0


def test_download_state_absent_before_start(tm):
    """Freshly registered series has downloading=False (overview only)."""
    w = tm.register_series(1)
    assert not w.progress_border._downloading


def test_start_does_not_set_ready(tm):
    """start_series_download → downloading=True, ready=False (not complete yet)."""
    w = tm.register_series(1)
    tm.start_series_download(1)
    assert w.progress_border._downloading, "Must be downloading after start"
    assert not w.progress_border._is_ready, (
        "start_series_download must NOT set ready (only completion does)"
    )


def test_progress_updates_do_not_set_ready(tm):
    """No amount of progress updates sets ready state — completion is required."""
    w = tm.register_series(1)
    tm.start_series_download(1)
    for p in [0.0, 25.0, 50.0, 75.0, 99.5]:
        tm.update_series_progress(1, p)
        assert not w.progress_border._is_ready, (
            f"_is_ready must be False at progress={p}"
        )


def test_completion_is_exclusive_source_of_ready_state(tm):
    """Only complete_series_download produces the ready state."""
    w = tm.register_series(1)
    tm.start_series_download(1)
    tm.update_series_progress(1, 99.9)
    assert not w.progress_border._is_ready

    tm.complete_series_download(1)
    assert w.progress_border._is_ready


def test_three_phase_lifecycle(tm):
    """Verify the complete pending → downloading → complete lifecycle."""
    w = tm.register_series(42)

    # Phase 1 — pending (overview registered, download not started)
    assert not w.progress_border._downloading
    assert not w.progress_border._is_ready

    # Phase 2 — downloading
    tm.start_series_download(42)
    assert w.progress_border._downloading
    assert not w.progress_border._is_ready
    tm.update_series_progress(42, 50.0)
    assert w.progress_border._progress == pytest.approx(50.0)

    # Phase 3 — complete
    tm.complete_series_download(42)
    assert not w.progress_border._downloading
    assert w.progress_border._is_ready
    assert "42" in tm.ready_series


def test_independent_series_lifecycles(tm):
    """Multiple series run their lifecycles without interfering with each other."""
    for sn in [1, 2, 3]:
        tm.register_series(sn)
    for sn in [1, 2, 3]:
        tm.start_series_download(sn)

    # Complete only series 2
    tm.complete_series_download(2)

    # Series 1 — still downloading
    assert tm.series_widgets["1"].progress_border._downloading
    assert not tm.series_widgets["1"].progress_border._is_ready

    # Series 2 — ready
    assert tm.series_widgets["2"].progress_border._is_ready
    assert not tm.series_widgets["2"].progress_border._downloading

    # Series 3 — still downloading
    assert tm.series_widgets["3"].progress_border._downloading
    assert not tm.series_widgets["3"].progress_border._is_ready


def test_overview_count_independent_of_ready_count(tm):
    """13 thumbnails registered; only 5 completed; counts must match independently."""
    for sn in range(1, 14):
        tm.register_series(sn)
    for sn in range(1, 6):
        tm.complete_series_download(sn)

    assert len(tm.series_widgets) == 13  # all registered
    assert len(tm.ready_series) == 5     # only completions


def test_overview_and_download_paths_share_widget_reference(tm):
    """The widget returned by register_series is the same object updated by state calls."""
    w = tm.register_series(7)
    tm.start_series_download(7)

    # The widget in series_widgets IS the one we got back
    assert tm.series_widgets["7"] is w
    # And its border reflects the download-start state change
    assert w.progress_border._downloading
