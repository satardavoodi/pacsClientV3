"""
FAST-THUMB-OVERVIEW: thumbnails must be registered (state=pending) the moment
set_server_series_info completes — no download signal required.

These tests verify that the thumbnail overview path is completely independent of
download execution.  The [FAST-THUMB-OVERVIEW] log emitted in
_hp_patient_open._on_patient_double_clicked_async confirms timing in
production; this suite validates the state contract in isolation.
"""
import pytest


def test_thumbnails_registered_before_download(tm):
    """Registering a batch of series creates pending widgets with no DM signal."""
    for sn in [101, 102, 103, 104, 105]:
        w = tm.register_series(sn)
        assert w is not None, f"No widget created for series {sn}"
    assert len(tm.series_widgets) == 5


def test_new_widget_is_not_ready_not_downloading(tm):
    """A freshly registered series is neither ready nor downloading."""
    w = tm.register_series(1)
    assert not w.progress_border._is_ready
    assert not w.progress_border._downloading


def test_widgets_exist_before_any_dm_signal(tm):
    """series_widgets is populated before start_series_download is ever called."""
    tm.register_series(10)
    tm.register_series(20)
    assert "10" in tm.series_widgets
    assert "20" in tm.series_widgets
    assert len(tm.ready_series) == 0


def test_ready_series_empty_after_overview_only(tm):
    """ready_series stays empty when only thumbnails are registered (no download)."""
    for sn in range(1, 11):
        tm.register_series(sn)
    assert len(tm.ready_series) == 0


def test_100_series_overview_registration(tm):
    """Registering 100 series all succeed without error."""
    for sn in range(1, 101):
        tm.register_series(sn)
    assert len(tm.series_widgets) == 100


def test_re_registration_overwrites_widget(tm):
    """Re-registering the same series key replaces the widget entry."""
    w1 = tm.register_series(7)
    w2 = tm.register_series(7)
    assert tm.series_widgets["7"] is w2
    assert tm.series_widgets["7"] is not w1
