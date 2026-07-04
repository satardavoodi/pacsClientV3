"""Tests for the Stage-1 lifecycle SHADOW observer.

Confirms the observer is a strict no-op when disabled (byte-identical legacy),
observes + parks when enabled, and never raises out of a public method.
Pure: no Qt / VTK.
"""
from __future__ import annotations

import logging
import os

from PacsClient.utils import lifecycle_shadow as LS
from PacsClient.utils.patient_load_lifecycle import LoadStage


def _fresh(enabled: bool) -> LS.LifecycleShadow:
    os.environ["AIPACS_LIFECYCLE_THUMBS"] = "shadow" if enabled else "0"
    # Build directly so we control the flag independent of the process singleton.
    return LS.LifecycleShadow()


def test_disabled_is_noop():
    os.environ["AIPACS_LIFECYCLE_THUMBS"] = "0"
    assert LS.is_enabled() is False
    sh = LS.LifecycleShadow()
    # None of these do anything or raise when disabled.
    sh.note_selection("P", "S", open_intent=False)
    sh.note_series_set("S", [{"series_number": "1", "series_uid": "u1", "image_count": 3}])
    sh.note_thumbs_rendered("S")
    sh.note_discard("S", "stale_token")
    assert sh._model is None  # never even built the model when off


def test_enabled_observes_and_parks():
    sh = _fresh(True)
    assert LS.is_enabled() is True
    sh.note_selection("P", "S", open_intent=False)
    sh.note_series_set("S", [
        {"series_number": "1", "series_uid": "u1", "image_count": 3},
        {"series_number": "2", "series_uid": "u2", "image_count": 5},
    ])
    sh.note_thumbs_rendered("S")
    study = sh._model.study("S")
    assert study is not None
    assert len(study.series) == 2
    assert study.stage == LoadStage.THUMBS_READY  # preview terminal reached


def test_discard_logs_parked_state(caplog):
    sh = _fresh(True)
    sh.note_selection("P", "S", open_intent=False)
    sh.note_series_set("S", [{"series_number": "1", "series_uid": "u1", "image_count": 3}])
    with caplog.at_level(logging.INFO, logger="aipacs.lifecycle_shadow"):
        sh.note_discard("S", "stale_token")
    # The observer records that the model still holds the study parked.
    assert any("LIFECYCLE-SHADOW" in r.getMessage() and "parked_series=1" in r.getMessage()
               for r in caplog.records)


def test_render_before_selection_still_registers():
    sh = _fresh(True)
    # A render can arrive without a prior observed selection — must not raise and
    # must still register the study so nothing is lost.
    sh.note_series_set("S2", [{"series_number": "1", "series_uid": "uX", "image_count": 2}])
    assert sh._model.study("S2") is not None


def test_public_methods_never_raise_on_bad_input():
    sh = _fresh(True)
    # Deliberately malformed inputs — telemetry must swallow everything.
    sh.note_selection(None, None)
    sh.note_series_set("S", [None, 123, {"weird": True}])
    sh.note_thumbs_rendered(None)
    sh.note_discard(None, None)


def test_download_progress_secondary_study_is_first_class(caplog):
    sh = _fresh(True)
    # A previous-exam series arrives under its OWN study_uid ("PREV"), which the
    # legacy grow lane dropped (sn is None). The model must still track it.
    with caplog.at_level(logging.INFO, logger="aipacs.lifecycle_shadow"):
        sh.note_download_progress("PRIMARY", "PREV", "uidP", 1, 30, dropped=True)
        sh.note_download_progress("PRIMARY", "PREV", "uidP", 30, 30, dropped=True)
    study = sh._model.study("PREV")
    assert study is not None and len(study.series) == 1
    rec = list(study.series.values())[0]
    assert rec.on_disk == 30 and rec.disk_complete is True   # converged on disk
    assert any("grow_lane_drop" in r.getMessage() for r in caplog.records)


def test_download_complete_marks_disk_complete():
    sh = _fresh(True)
    sh.note_download_progress("P", "S", "u1", 3, 5, dropped=False)
    sh.note_download_complete("P", "S", "u1")
    rec = list(sh._model.study("S").series.values())[0]
    assert rec.disk_complete is True


def test_download_failed_sets_failed_terminal():
    from PacsClient.utils.patient_load_lifecycle import LoadStage
    sh = _fresh(True)
    sh.note_download_progress("P", "S", "u1", 1, 5, dropped=False)
    sh.note_download_failed("S", "u1", cause="retry_exhausted")
    rec = list(sh._model.study("S").series.values())[0]
    assert rec.stage == LoadStage.FAILED


def test_download_failed_study_level_no_series():
    from PacsClient.utils.patient_load_lifecycle import LoadStage
    sh = _fresh(True)
    # No prior series known — a study-level failure creates + fails a placeholder.
    sh.note_download_failed("STUDYX", None, cause="retry_exhausted")
    study = sh._model.study("STUDYX")
    assert study is not None and len(study.series) >= 1
    assert all(r.stage == LoadStage.FAILED for r in study.series.values())


def test_new_methods_disabled_are_noop():
    sh = _fresh(False)
    sh.note_download_progress("P", "S", "u", 1, 5, dropped=True)
    sh.note_download_complete("P", "S", "u")
    sh.note_download_failed("S", "u")
    assert sh._model is None


def test_watchdog_activity_counts_and_logs(caplog):
    sh = _fresh(True)
    with caplog.at_level(logging.INFO, logger="aipacs.lifecycle_shadow"):
        sh.note_watchdog_activity("resume", "2000006")
        sh.note_watchdog_activity("grow", "302")
        sh.note_watchdog_activity("resume", "1000001")
    assert sh._watchdog_counts.get("resume") == 2
    assert sh._watchdog_counts.get("grow") == 1
    assert any("watchdog_resume" in r.getMessage() for r in caplog.records)


def test_watchdog_activity_disabled_is_noop():
    sh = _fresh(False)
    sh.note_watchdog_activity("resume", "x")
    assert sh._watchdog_counts == {}


def test_should_log_throttles_per_key():
    sh = _fresh(True)
    # First call for a key logs; an immediate second call for the same key is throttled.
    assert sh._should_log(("k", "s1"), interval=100.0) is True
    assert sh._should_log(("k", "s1"), interval=100.0) is False
    # A different key is independent.
    assert sh._should_log(("k", "s2"), interval=100.0) is True
    # interval=0 always logs.
    assert sh._should_log(("k", "s1"), interval=0.0) is True


def test_grow_lane_drop_log_is_throttled(caplog):
    sh = _fresh(True)
    with caplog.at_level(logging.INFO, logger="aipacs.lifecycle_shadow"):
        # Many progress ticks for ONE series -> the model updates each time, but the
        # verbose grow_lane_drop log line is rate-limited to ~1 per interval.
        for i in range(1, 40):
            sh.note_download_progress("PRIM", "PREV", "uidThrottle", i, 123, dropped=True)
    drops = [r for r in caplog.records if "grow_lane_drop" in r.getMessage()]
    assert len(drops) <= 3, f"expected throttled logging, got {len(drops)} lines"
    # But the model still saw every event (on_disk advanced to the latest count).
    rec = list(sh._model.study("PREV").series.values())[0]
    assert rec.on_disk == 39


def test_default_is_enabled_when_env_unset():
    # Build default (2026-07-02): the observer runs unless explicitly killed.
    prev = os.environ.pop("AIPACS_LIFECYCLE_THUMBS", None)
    try:
        assert LS.is_enabled() is True
    finally:
        if prev is not None:
            os.environ["AIPACS_LIFECYCLE_THUMBS"] = prev


def test_kill_switch_disables():
    os.environ["AIPACS_LIFECYCLE_THUMBS"] = "0"
    assert LS.is_enabled() is False


def _teardown_module(module):  # pytest hook: restore default env
    os.environ["AIPACS_LIFECYCLE_THUMBS"] = "0"


if __name__ == "__main__":
    import traceback
    class _Cap:
        class _R:
            def __init__(s, m): s._m = m
            def getMessage(s): return s._m
        records = []
        def at_level(self, *a, **k):
            import contextlib; return contextlib.nullcontext()
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(_Cap()) if "caplog" in fn.__code__.co_varnames else fn()
                passed += 1; print("PASS", name)
            except Exception:
                failed += 1; print("FAIL", name); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
