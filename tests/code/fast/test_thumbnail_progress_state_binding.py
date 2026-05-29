"""
FAST-THUMB-STATE: update_series_progress must bind progress % to the widget's
progress border without altering the ready or downloading flags.

The [FAST-THUMB-STATE] log emitted in ThumbnailManager.update_series_progress
confirms this in production; this suite validates the state contract in isolation.
"""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("pct", [0.0, 1.0, 25.0, 50.0, 75.0, 99.0, 100.0])
def test_progress_value_stored_on_border(tm, pct):
    """update_series_progress stores the correct percentage on progress_border."""
    tm.register_series(1)
    tm.start_series_download(1)
    tm.update_series_progress(1, pct)
    assert tm.series_widgets["1"].progress_border._progress == pytest.approx(pct)


def test_progress_does_not_set_ready(tm):
    """update_series_progress must NOT set _is_ready — that is completion's job."""
    tm.register_series(1)
    tm.start_series_download(1)
    tm.update_series_progress(1, 50.0)
    assert not tm.series_widgets["1"].progress_border._is_ready


def test_progress_keeps_downloading_true(tm):
    """Downloading flag must remain True while progress updates are in flight."""
    tm.register_series(1)
    tm.start_series_download(1)
    tm.update_series_progress(1, 50.0)
    assert tm.series_widgets["1"].progress_border._downloading


def test_progress_update_for_unknown_series_is_silent(tm):
    """update_series_progress for an unregistered series must not raise."""
    tm.update_series_progress(999, 50.0)  # no widget — must silently ignore


def test_rapid_progress_updates_all_land(tm):
    """100 progress calls all apply; final value is 100.0."""
    tm.register_series(1)
    tm.start_series_download(1)
    for pct in range(101):
        tm.update_series_progress(1, float(pct))
    assert tm.series_widgets["1"].progress_border._progress == pytest.approx(100.0)


def test_progress_updates_independent_across_series(tm):
    """Progress updates to series A do not affect series B."""
    tm.register_series(1)
    tm.register_series(2)
    tm.start_series_download(1)
    tm.start_series_download(2)
    tm.update_series_progress(1, 60.0)
    tm.update_series_progress(2, 30.0)

    assert tm.series_widgets["1"].progress_border._progress == pytest.approx(60.0)
    assert tm.series_widgets["2"].progress_border._progress == pytest.approx(30.0)


def test_progress_monotonically_increasing_scenario(tm):
    """Simulated 0→100% stream; state must evolve correctly throughout."""
    tm.register_series(42)
    tm.start_series_download(42)

    steps = [0.0, 10.0, 25.5, 50.0, 74.9, 99.0, 100.0]
    for p in steps:
        tm.update_series_progress(42, p)
        assert not tm.series_widgets["42"].progress_border._is_ready, (
            f"_is_ready must be False at progress={p}"
        )
    assert tm.series_widgets["42"].progress_border._progress == pytest.approx(100.0)


def test_real_thumbnail_manager_progress_is_deferred_until_admitted(monkeypatch):
    from PacsClient.pacs.patient_tab.utils import thumbnail_manager as _tm_mod

    scheduled = []
    fake_tm = SimpleNamespace(
        _resolve_series_key=lambda sn: str(sn),
        _progress_update_last_ts={},
        _progress_update_pending={},
        _progress_update_timer_active=False,
        _progress_update_interval_ms=lambda: 500.0,
        _schedule_progress_flush=lambda delay_ms: scheduled.append(delay_ms),
    )

    monkeypatch.setattr(_tm_mod, "_ui_should_admit", lambda *a, **kw: False)

    _tm_mod.ThumbnailManager.update_series_progress(fake_tm, 7, 42.0, "5/10")

    assert fake_tm._progress_update_pending == {"7": (7, 42.0, "5/10")}
    assert scheduled == [500.0]
