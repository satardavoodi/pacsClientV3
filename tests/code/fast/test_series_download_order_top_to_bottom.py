"""
FAST-SERIES-DOWNLOAD-START: download must follow top-to-bottom (queue) order
and must handle the race condition where a DM signal arrives before the
thumbnail widget is created (Gap-4 / _pending_download_series deferred path).
"""
import pytest


def test_start_download_order_matches_registration_order(tm):
    """start_series_download calls arrive in the same order as registration."""
    ordered = [1, 2, 3, 4, 5]
    for sn in ordered:
        tm.register_series(sn)

    call_order: list[str] = []
    _original = tm.start_series_download

    def _tracking(sn):
        call_order.append(str(sn))
        _original(sn)

    tm.start_series_download = _tracking
    for sn in ordered:
        tm.start_series_download(sn)

    assert call_order == [str(s) for s in ordered], (
        f"Expected top-to-bottom order {ordered}, got {call_order}"
    )


def test_deferred_start_fires_on_registration(tm):
    """DM starts download before widget exists → deferred, then applied on registration."""
    tm.start_series_download(99)
    assert "99" in tm._pending_download_series
    assert "99" not in tm.series_widgets

    w = tm.register_series(99)
    assert "99" not in tm._pending_download_series, "Deferred entry must be consumed"
    assert w.progress_border._downloading, (
        "Deferred start_series_download did not apply downloading state on registration"
    )


def test_deferred_start_cleared_from_pending_set(tm):
    """After deferred relay, _pending_download_series must not retain the key."""
    tm.start_series_download(55)
    assert "55" in tm._pending_download_series
    tm.register_series(55)
    assert "55" not in tm._pending_download_series


def test_start_download_only_affects_target_series(tm):
    """Starting series A must not change the state of series B."""
    tm.register_series(1)
    tm.register_series(2)
    tm.start_series_download(1)

    assert tm.series_widgets["1"].progress_border._downloading
    assert not tm.series_widgets["2"].progress_border._downloading


def test_start_download_twice_is_idempotent(tm):
    """Calling start_series_download twice for the same series must not crash."""
    tm.register_series(1)
    tm.start_series_download(1)
    apply_count = tm._apply_count
    tm.start_series_download(1)  # second call — must not raise
    assert tm.series_widgets["1"].progress_border._downloading
    assert tm._apply_count == apply_count


def test_five_series_deferred_all_applied(tm):
    """Five series queued before widgets exist must all apply downloading state."""
    series = [10, 20, 30, 40, 50]
    for sn in series:
        tm.start_series_download(sn)
    for sn in series:
        tm.register_series(sn)

    for sn in series:
        assert tm.series_widgets[str(sn)].progress_border._downloading, (
            f"Series {sn} deferred state not applied"
        )


def test_start_persists_stable_total_count_label(tm):
    tm.register_series(7)
    tm.start_series_download(7, total_images=145)
    tm.start_series_download(7, total_images=999)

    assert tm.series_widgets["7"].count_label_text == "145 images"
