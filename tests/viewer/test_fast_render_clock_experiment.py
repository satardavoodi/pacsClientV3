from __future__ import annotations

import time
from types import SimpleNamespace
import types


class _FakeTimer:
    def __init__(self):
        self._active = False
        self._interval = 0
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
        self._interval = int(value)

    def interval(self):
        return int(self._interval)


class _FakeSlider:
    def __init__(self):
        self.value = 0
        self.set_count = 0
        self._blocked = False
        self.recursive_emit_count = 0

    def blockSignals(self, blocked):
        self._blocked = bool(blocked)

    def setValue(self, value):
        self.value = int(value)
        self.set_count += 1
        if not self._blocked:
            self.recursive_emit_count += 1


def _build_bridge_stub():
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    bridge = SimpleNamespace()
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
    bridge.vtk_widget = None
    bridge._mark_interaction_event = lambda: None
    bridge._sync_interaction_slice_count_hint = lambda: None
    bridge._interaction_settle_timer = _FakeTimer()

    bridge._drag_session_id = "test-session"
    bridge._fast_render_clock_timer = _FakeTimer()
    bridge._fast_render_clock_enabled_cached = None
    bridge._fast_clock_fallback_active = False
    bridge._fast_latest_requested_slice = None
    bridge._fast_pending_interaction_type = ""
    bridge._fast_latest_interaction_ts_ms = 0.0
    bridge._fast_request_generation = 0
    bridge._fast_last_presented_generation = 0
    bridge._fast_clock_last_tick_mono_ms = 0.0
    bridge._fast_clock_last_request_mono_ms = 0.0
    bridge._fast_clock_tick_interval_ms = 33.0
    bridge._fast_clock_missed_tick_count = 0
    bridge._fast_clock_superseded_count = 0

    bridge._set_slice_calls = []
    bridge._sync_calls = 0
    bridge._reference_calls = 0

    slider = _FakeSlider()
    patient_widget = SimpleNamespace(
        _schedule_reference_line_update=lambda: setattr(bridge, '_reference_calls', int(getattr(bridge, '_reference_calls', 0)) + 1)
    )
    bridge.vtk_widget = SimpleNamespace(
        slider=slider,
        patient_widget=patient_widget,
        image_viewer=None,
        _on_slice_changed_cb=lambda _vw: setattr(bridge, '_sync_calls', int(getattr(bridge, '_sync_calls', 0)) + 1),
    )

    def _set_slice(idx, fast_interaction=False, *, interaction_type=""):
        bridge._current_slice = int(idx)
        bridge._set_slice_calls.append((int(idx), bool(fast_interaction), str(interaction_type)))

    bridge.set_slice = _set_slice

    def _set_slice_impl(idx, fast_interaction=False, interaction_type=""):
        bridge._current_slice = int(idx)
        bridge._set_slice_calls.append((int(idx), bool(fast_interaction), str(interaction_type)))

    bridge._set_slice_impl = _set_slice_impl

    bridge._apply_interaction_target = types.MethodType(QtViewerBridge._apply_interaction_target, bridge)
    bridge._fast_clock_enabled = types.MethodType(QtViewerBridge._fast_clock_enabled, bridge)
    bridge._request_clocked_slice = types.MethodType(QtViewerBridge._request_clocked_slice, bridge)
    bridge._ensure_render_clock_running = types.MethodType(QtViewerBridge._ensure_render_clock_running, bridge)
    bridge._on_fast_render_clock_tick = types.MethodType(QtViewerBridge._on_fast_render_clock_tick, bridge)
    bridge._present_latest_requested_slice = types.MethodType(QtViewerBridge._present_latest_requested_slice, bridge)
    bridge._stop_render_clock_if_idle = types.MethodType(QtViewerBridge._stop_render_clock_if_idle, bridge)
    bridge._force_present_pending_on_settle = types.MethodType(QtViewerBridge._force_present_pending_on_settle, bridge)
    bridge._apply_present_side_effects = types.MethodType(QtViewerBridge._apply_present_side_effects, bridge)
    bridge._flush_final_side_effects_on_settle = types.MethodType(QtViewerBridge._flush_final_side_effects_on_settle, bridge)
    return bridge


def test_default_mode_immediate_present(monkeypatch):
    monkeypatch.delenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", raising=False)
    bridge = _build_bridge_stub()

    applied = bridge._apply_interaction_target(7, interaction_type="drag", request_queued_mono_ms=0.0)

    assert applied is True
    assert bridge._current_slice == 7
    assert len(bridge._set_slice_calls) == 1
    assert bridge._fast_request_generation == 0
    assert bridge.vtk_widget.slider.set_count == 1


def test_clock_mode_request_only_until_tick(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    applied = bridge._apply_interaction_target(11, interaction_type="drag", request_queued_mono_ms=0.0)

    assert applied is True
    assert bridge._current_slice == 0
    assert len(bridge._set_slice_calls) == 0
    assert bridge._fast_request_generation == 1
    assert bridge._fast_latest_requested_slice == 11
    assert bridge._fast_render_clock_timer.isActive() is True
    assert bridge.vtk_widget.slider.set_count == 0


def test_clock_mode_no_slider_set_per_input_event(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(3, interaction_type="drag", request_queued_mono_ms=0.0)
    bridge._apply_interaction_target(8, interaction_type="drag", request_queued_mono_ms=0.0)
    bridge._apply_interaction_target(12, interaction_type="drag", request_queued_mono_ms=0.0)

    assert bridge.vtk_widget.slider.set_count == 0
    assert bridge._sync_calls == 0
    assert bridge._reference_calls == 0


def test_clock_mode_latest_target_wins(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(5, interaction_type="drag", request_queued_mono_ms=0.0)
    bridge._apply_interaction_target(9, interaction_type="drag", request_queued_mono_ms=0.0)
    bridge._apply_interaction_target(13, interaction_type="drag", request_queued_mono_ms=0.0)

    bridge._on_fast_render_clock_tick()

    assert bridge._current_slice == 13
    assert len(bridge._set_slice_calls) == 1
    assert bridge._set_slice_calls[0][0] == 13
    assert bridge._fast_clock_superseded_count >= 2
    assert bridge.vtk_widget.slider.value == 13
    assert bridge.vtk_widget.slider.set_count == 1


def test_clock_mode_side_effects_apply_on_present(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(19, interaction_type="drag", request_queued_mono_ms=0.0)
    assert bridge.vtk_widget.slider.set_count == 0

    bridge._on_fast_render_clock_tick()

    assert bridge.vtk_widget.slider.value == 19
    assert bridge.vtk_widget.slider.set_count == 1
    assert bridge._sync_calls == 1
    assert bridge._reference_calls == 1


def test_force_present_on_settle(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(17, interaction_type="drag", request_queued_mono_ms=0.0)
    assert bridge._current_slice == 0

    bridge._force_present_pending_on_settle(reason="test_settle")

    assert bridge._current_slice == 17
    assert len(bridge._set_slice_calls) == 1
    assert bridge.vtk_widget.slider.value == 17


def test_final_slider_value_forced_on_settle(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(23, interaction_type="drag", request_queued_mono_ms=0.0)
    assert bridge.vtk_widget.slider.set_count == 0

    bridge._force_present_pending_on_settle(reason="settle")

    assert bridge.vtk_widget.slider.value == 23
    assert bridge.vtk_widget.slider.set_count >= 1


def test_sync_reference_not_spammed_per_input(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    for idx in (6, 7, 8, 9):
        bridge._apply_interaction_target(idx, interaction_type="drag", request_queued_mono_ms=0.0)

    assert bridge._sync_calls == 0
    assert bridge._reference_calls == 0

    bridge._on_fast_render_clock_tick()
    assert bridge._sync_calls == 1
    assert bridge._reference_calls == 1


def test_final_sync_reference_flush_occurs(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(31, interaction_type="drag", request_queued_mono_ms=0.0)
    assert bridge._sync_calls == 0
    assert bridge._reference_calls == 0

    bridge._force_present_pending_on_settle(reason="settle_flush")

    assert bridge._sync_calls >= 1
    assert bridge._reference_calls >= 1


def test_slider_signal_recursion_prevented(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._apply_interaction_target(14, interaction_type="drag", request_queued_mono_ms=0.0)
    bridge._on_fast_render_clock_tick()

    assert bridge.vtk_widget.slider.recursive_emit_count == 0


def test_clock_timer_stops_when_idle(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    bridge._fast_render_clock_timer.start()
    bridge._fast_request_generation = 3
    bridge._fast_last_presented_generation = 3
    bridge._fast_latest_interaction_ts_ms = (time.perf_counter() * 1000.0) - 500.0

    bridge._stop_render_clock_if_idle()

    assert bridge._fast_render_clock_timer.isActive() is False
    assert bridge._fast_render_clock_timer.stop_count >= 1


def test_fallback_disables_clock_mode(monkeypatch):
    monkeypatch.setenv("AIPACS_FAST_RENDER_CLOCK_EXPERIMENT", "1")
    bridge = _build_bridge_stub()

    assert bridge._fast_clock_enabled() is True
    bridge._fast_clock_fallback_active = True
    assert bridge._fast_clock_enabled() is False
