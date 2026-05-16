"""Ownership regression tests for FAST sync / reference-line contract.

Architecture contract (C4-hotfix + reference-line fix):
  - _apply_interaction_target is the SOLE owner of per-tick sync and reference-
    line for ALL user-driven FAST interactions (wheel + stack drag).
  - _vw_scroll.py is NOT called for FAST wheel/drag from QtSliceViewer.
  - _on_slice_changed_cb MUST be called from _apply_interaction_target, throttled
    at 100ms using the shared vtk_widget._last_lock_sync_ms timestamp.
    This handles Lock Sync (multi-viewer position sync) when Lock Sync is ON.
  - _schedule_reference_line_update MUST also be called directly from
    _apply_interaction_target every tick (same as _vw_scroll.py line 652).
    This handles reference-line updates whether Lock Sync is ON or OFF.
    _schedule_reference_line_update has its own 50 ms debounce so calling at
    mouse-event rate is safe: manage_reference_line(repaint=False) runs at most
    20 Hz and the repaint round-robin fires every 50 ms.
  - _flush_non_clock_side_effects_on_settle unconditionally fires _on_slice_changed_cb
    AND _schedule_reference_line_update at settle time (no throttle).

Run:  .venv\\Scripts\\python.exe -m pytest tests/viewer/test_sync_reference_line_ownership.py -v
"""
from __future__ import annotations

import time
import types
from types import SimpleNamespace


# ─── Fake infrastructure ──────────────────────────────────────────────────────

class _FakeTimer:
    def __init__(self):
        self._active = False
        self.start_count = 0
        self.stop_count = 0

    def start(self):
        self._active = True
        self.start_count += 1

    def stop(self):
        self._active = False
        self.stop_count += 1

    def isActive(self):
        return self._active

    def setInterval(self, value):
        pass

    def interval(self):
        return 0


class _FakeSlider:
    def __init__(self):
        self.value = 0
        self.set_count = 0
        self._blocked = False

    def blockSignals(self, blocked):
        self._blocked = bool(blocked)

    def setValue(self, value):
        self.value = int(value)
        self.set_count += 1


# ─── Bridge stub builder ──────────────────────────────────────────────────────

def _build_ownership_stub():
    """Build a minimal bridge stub exercising the non-clock path side-effects.

    Binds _apply_interaction_target and _flush_non_clock_side_effects_on_settle
    from the real QtViewerBridge so the tests catch real regressions.

    Stub supplies:
      * _present_trace_register_request / _present_trace_mark_terminal as
        no-op lambdas (observation-only infrastructure, not under test here).
      * _fast_render_clock_enabled_cached = False to force the non-clock path.
      * vtk_widget._last_lock_sync_ms = 0.0 (shared throttle timestamp).
      * Counters: bridge._sync_calls (how many times _on_slice_changed_cb fired),
        bridge._reference_calls (how many times _schedule_reference_line_update
        was called directly from the vtk_widget.patient_widget path).
    """
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    bridge = SimpleNamespace()

    # ── Core slice state ──────────────────────────────────────────────────────
    bridge._current_slice = 0
    bridge._slice_count = 256
    bridge._stack_drag_active = False
    bridge._protected_drag_active = False
    bridge._last_stack_sync_ms = 0.0
    bridge._last_sync_ms = 0.0
    bridge._last_stack_reference_ms = 0.0
    bridge._last_stack_target_slice = None
    bridge._drag_metrics = None
    bridge._last_set_slice_ui_lag_ms = 0.0
    bridge.last_index_slice_saved = 0
    bridge._mark_interaction_event = lambda: None
    bridge._sync_interaction_slice_count_hint = lambda: None
    bridge._settle_arm_seq = 0
    bridge._last_settle_reason = ""
    bridge._fast_present_trace_active_request_id = 0

    # ── Pending side-effect flags ─────────────────────────────────────────────
    bridge._fast_pending_slider_value = None
    bridge._fast_pending_sync_update = False
    bridge._fast_pending_reference_update = False

    # ── Settle timer ──────────────────────────────────────────────────────────
    bridge._interaction_settle_timer = _FakeTimer()

    # ── Present-trace stubs (no-ops; observation-only infra, not under test) ─
    bridge._present_trace_register_request = lambda **kw: 1
    bridge._present_trace_mark_terminal = lambda req_id, **kw: None

    # ── Render clock disabled: set cached=False so _fast_clock_enabled()
    #    returns False without reading the environment variable.  This forces
    #    _apply_interaction_target into the non-clock (synchronous) path. ──────
    bridge._fast_render_clock_enabled_cached = False
    bridge._fast_clock_fallback_active = False
    bridge._fast_latest_requested_slice = None

    # ── Counters for assertions ────────────────────────────────────────────────
    bridge._set_slice_calls = []
    bridge._sync_calls = 0
    bridge._reference_calls = 0

    # ── VTK widget stub ───────────────────────────────────────────────────────
    slider = _FakeSlider()
    patient_widget = SimpleNamespace(
        _schedule_reference_line_update=lambda: setattr(
            bridge, '_reference_calls', bridge._reference_calls + 1
        )
    )
    bridge.vtk_widget = SimpleNamespace(
        slider=slider,
        patient_widget=patient_widget,
        image_viewer=None,
        _on_slice_changed_cb=lambda _vw: setattr(
            bridge, '_sync_calls', bridge._sync_calls + 1
        ),
        _last_lock_sync_ms=0.0,  # shared throttle with _vw_scroll.py
    )

    # ── set_slice stub ────────────────────────────────────────────────────────
    def _set_slice(idx, fast_interaction=False, *, interaction_type=""):
        bridge._current_slice = int(idx)
        bridge._set_slice_calls.append((int(idx), bool(fast_interaction), str(interaction_type)))

    bridge.set_slice = _set_slice

    # ── Bind real methods from QtViewerBridge ─────────────────────────────────
    bridge._apply_interaction_target = types.MethodType(
        QtViewerBridge._apply_interaction_target, bridge
    )
    bridge._fast_clock_enabled = types.MethodType(
        QtViewerBridge._fast_clock_enabled, bridge
    )
    bridge._flush_non_clock_side_effects_on_settle = types.MethodType(
        QtViewerBridge._flush_non_clock_side_effects_on_settle, bridge
    )

    return bridge


# ─── Architecture guard tests (source-level, no Qt needed) ───────────────────

def test_apply_interaction_target_calls_on_slice_changed_cb():
    """Arch guard: _apply_interaction_target MUST contain _on_slice_changed_cb.

    _vw_scroll.py is NOT called for FAST wheel/drag from QtSliceViewer.
    The sync callback is the only path that delivers live reference-line
    updates during drag.  If this fails, live sync is permanently broken.
    """
    import inspect
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    src = inspect.getsource(QtViewerBridge._apply_interaction_target)
    assert "_on_slice_changed_cb" in src, (
        "Architecture violation: _apply_interaction_target must call "
        "_on_slice_changed_cb for live sync and reference-line during "
        "FAST wheel and stack drag. _vw_scroll.py is NOT called for "
        "user-driven FAST interactions."
    )


def test_apply_interaction_target_calls_schedule_reference_line_update():
    """Arch guard: _apply_interaction_target MUST call _schedule_reference_line_update.

    Reference lines must animate live during FAST stack drag regardless of whether
    Lock Sync is enabled.  _on_slice_changed_cb only fires when Lock Sync is ON;
    the direct _schedule_reference_line_update call covers the Lock Sync OFF case.

    This mirrors _vw_scroll.py line 652 which calls _schedule_reference_line_update
    on every VTK scroll tick.  _schedule_reference_line_update has its own 50 ms
    leading+trailing debounce, so calling at mouse-event rate is safe — geometry
    update runs at most 20 Hz and repaint round-robin fires every 50 ms.

    Regression: removing this call causes reference lines to be frozen during
    FAST drag and only update at drag-release (settle flush).
    """
    import inspect
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    src = inspect.getsource(QtViewerBridge._apply_interaction_target)
    # Strip comment-only lines so we test for a real call site, not a mention.
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    src_code_only = "\n".join(non_comment_lines)
    assert "_schedule_reference_line_update" in src_code_only, (
        "Architecture regression: _apply_interaction_target must call "
        "_schedule_reference_line_update so reference lines animate live "
        "during FAST stack drag (Lock Sync ON or OFF).  "
        "Without this, reference lines only update at drag-release settle."
    )


# ─── Behaviour tests (stub-based, no Qt/VTK needed) ──────────────────────────

def test_sync_cb_fires_during_fast_interaction_not_only_at_settle(monkeypatch):
    """Sync callback must fire from _apply_interaction_target during the tick.

    If this fails, reference-line is frozen during drag and only updates at
    settle — the regression that C4-hotfix was written to fix.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()

    # _last_lock_sync_ms = 0.0 means the throttle window has long expired.
    bridge.vtk_widget._last_lock_sync_ms = 0.0

    bridge._apply_interaction_target(7, interaction_type="wheel", request_queued_mono_ms=0.0)

    assert bridge._sync_calls == 1, (
        "Sync callback must fire once from _apply_interaction_target during the "
        "tick itself (not only at settle).  If this fails, live reference-line "
        "is frozen during drag — the C4-hotfix regression."
    )


def test_sync_cb_throttled_at_100ms_rapid_ticks(monkeypatch):
    """Sync callback must be throttled to ~100 ms during rapid scroll ticks.

    Firing on every tick would produce ~50 Hz _on_slice_changed_cb calls.
    Each call ends with _schedule_reference_line_update restarting its 50 ms
    timer → trailing edge never fires → manage_reference_line at 50 Hz.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()

    # First tick: sync should fire (last_lock_sync_ms = 0.0 → far in the past).
    bridge.vtk_widget._last_lock_sync_ms = 0.0
    bridge._apply_interaction_target(5, interaction_type="wheel", request_queued_mono_ms=0.0)
    assert bridge._sync_calls == 1, "First tick: sync callback must fire."

    # Rapid second tick (vtk_widget._last_lock_sync_ms was just updated to ~now).
    # The 100 ms window has NOT elapsed → sync must NOT fire a second time.
    bridge._apply_interaction_target(10, interaction_type="wheel", request_queued_mono_ms=0.0)
    assert bridge._sync_calls == 1, (
        "Rapid tick within 100 ms: sync callback must be suppressed by the "
        "throttle (vtk_widget._last_lock_sync_ms check)."
    )

    # Simulate 200 ms elapsed by back-dating the shared timestamp.
    bridge.vtk_widget._last_lock_sync_ms -= 200.0
    bridge._apply_interaction_target(15, interaction_type="wheel", request_queued_mono_ms=0.0)
    assert bridge._sync_calls == 2, (
        "After 100 ms has elapsed, sync callback must fire again on the next tick."
    )


def test_sync_uses_shared_last_lock_sync_ms_to_prevent_double_fire(monkeypatch):
    """Throttle guard uses vtk_widget._last_lock_sync_ms (shared with _vw_scroll.py).

    When _vw_scroll.py fires _on_slice_changed_cb for a slider-drag event and
    sets _last_lock_sync_ms = now, a FAST scroll tick arriving within 100 ms
    must not fire _on_slice_changed_cb a second time.  This prevents double
    lock-sync when slider drag and Qt scroll interleave.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()

    # Simulate _vw_scroll.py having fired the sync callback very recently.
    bridge.vtk_widget._last_lock_sync_ms = time.perf_counter() * 1000.0  # just now

    bridge._apply_interaction_target(7, interaction_type="wheel", request_queued_mono_ms=0.0)

    assert bridge._sync_calls == 0, (
        "When _last_lock_sync_ms was set to 'now' (simulating a recent "
        "_vw_scroll.py sync), _apply_interaction_target must NOT fire "
        "_on_slice_changed_cb again within the 100 ms throttle window."
    )


def test_settle_flush_fires_sync_unconditionally(monkeypatch):
    """Settle flush must fire _on_slice_changed_cb regardless of the 100 ms throttle.

    The per-tick throttle prevents double-firing during rapid scroll, but the
    final-settle flush must deliver the exact settled state to lock-sync and
    reference-line unconditionally.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()

    # Simulate the throttle having JUST fired (within the 100 ms window).
    bridge.vtk_widget._last_lock_sync_ms = time.perf_counter() * 1000.0
    bridge._fast_pending_slider_value = 12

    bridge._flush_non_clock_side_effects_on_settle()

    assert bridge._sync_calls == 1, (
        "Settle flush must fire _on_slice_changed_cb unconditionally (no throttle). "
        "The settled slice must reach lock-sync even if a tick fired just before settle."
    )


def test_settle_flush_fires_reference_line_unconditionally(monkeypatch):
    """Settle flush must call _schedule_reference_line_update directly once.

    The direct call from _flush_non_clock_side_effects_on_settle is correct
    here because it runs ONCE at settle (not per-tick).  This ensures the final
    reference-line position is always repainted after drag release regardless of
    whether the throttled _on_slice_changed_cb path happened to fire.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()
    bridge._fast_pending_slider_value = 12

    bridge._flush_non_clock_side_effects_on_settle()

    assert bridge._reference_calls == 1, (
        "Settle flush must call _schedule_reference_line_update once directly. "
        "This is the correct settle-only path (not per-tick, so no timer storm)."
    )


def test_settle_flush_clears_pending_flags(monkeypatch):
    """Pending flags must be cleared by _flush_non_clock_side_effects_on_settle.

    If the flags are not cleared the next tick may try to re-flush stale data.
    """
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_ownership_stub()
    bridge._fast_pending_slider_value = 7
    bridge._fast_pending_sync_update = True
    bridge._fast_pending_reference_update = True

    bridge._flush_non_clock_side_effects_on_settle()

    assert bridge._fast_pending_slider_value is None
    assert bridge._fast_pending_sync_update is False
    assert bridge._fast_pending_reference_update is False
