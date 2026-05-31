"""Regression guard: a viewer drag-drop preempts the single download slot.

Issue (observed live 2026-05-31): dragging a series into a viewport before its
study held the download slot only marked the series CRITICAL and then waited in
the retry chain (``Priority handoff stalled … recovery_exhausted``) because a
DIFFERENT study occupied the single slot (MAX_CONCURRENT_STUDIES=1). The home-page
thumbnail path already preempted via ``start_priority_download_immediately`` →
``_pause_all_active_downloads``; the viewer-drag path (``request_critical_series_download``)
did not.

Fix: ``request_critical_series_download`` now gracefully preempts (request_cancel →
series-boundary stop → auto-pause-for-resume) ONLY when a *different* study holds
the slot, so the dragged series' study gets the slot and loads. It must NOT preempt
when this study is already the active worker or the slot is idle (no churn), and it
must still always apply CRITICAL intent + start the series retry.
"""
import types

from modules.download_manager.ui.widget._dm_priority import _DMPriorityMixin


def _stub(active_uids):
    s = types.SimpleNamespace()
    s.calls = {"request_critical": 0, "pause_all": 0, "on_retry": 0}
    s.intent_coordinator = types.SimpleNamespace(
        request_critical_series=lambda u, sn: s.calls.__setitem__(
            "request_critical", s.calls["request_critical"] + 1))
    s.worker_pool = types.SimpleNamespace(
        get_all_workers=lambda: [(u, object()) for u in active_uids])
    s._pause_all_active_downloads = lambda: s.calls.__setitem__(
        "pause_all", s.calls["pause_all"] + 1)
    s._on_series_retry = lambda u, sn, su=None: s.calls.__setitem__(
        "on_retry", s.calls["on_retry"] + 1)
    s.request_critical_series_download = (
        _DMPriorityMixin.request_critical_series_download.__get__(s))
    return s


def test_drag_preempts_when_different_study_holds_slot():
    s = _stub(["OTHER_STUDY"])
    s.request_critical_series_download("THIS_STUDY", "3")
    assert s.calls["pause_all"] == 1
    assert s.calls["request_critical"] == 1 and s.calls["on_retry"] == 1


def test_drag_does_not_preempt_when_same_study_active():
    s = _stub(["THIS_STUDY"])
    s.request_critical_series_download("THIS_STUDY", "3")
    assert s.calls["pause_all"] == 0
    assert s.calls["request_critical"] == 1 and s.calls["on_retry"] == 1


def test_drag_does_not_preempt_when_slot_idle():
    s = _stub([])
    s.request_critical_series_download("THIS_STUDY", "3")
    assert s.calls["pause_all"] == 0
    assert s.calls["request_critical"] == 1 and s.calls["on_retry"] == 1
