import os
from types import SimpleNamespace

from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge, _wl_unchanged
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import toolbar_manager as toolbar_mod


def test_wl_unchanged_helper_tolerates_tiny_float_noise():
    assert _wl_unchanged((400.0, 40.0), (400.0, 40.0)) is True
    assert _wl_unchanged((400.0, 40.0), (400.0 + 1e-7, 40.0 - 1e-7)) is True
    assert _wl_unchanged((400.0, 40.0), (401.0, 40.0)) is False


def test_set_window_level_skips_pipeline_work_when_unchanged():
    state = {
        "pipeline_set": 0,
        "render": 0,
        "image": 0,
        "annotations": 0,
    }

    class _Pipeline:
        def set_window_level(self, *_args, **_kwargs):
            state["pipeline_set"] += 1

        def get_rendered_frame(self, _idx):
            state["render"] += 1
            return SimpleNamespace(qimage=None, window_width=400.0, window_center=40.0)

    bridge = SimpleNamespace(
        metadata={},
        _current_slice=0,
        _window=400.0,
        _level=40.0,
        flag_set_custom_window_level=False,
        _wl_scroll_cache_ww=None,
        _wl_scroll_cache_wc=None,
        pipeline=_Pipeline(),
        qt_viewer=SimpleNamespace(set_image=lambda _img: state.__setitem__("image", state["image"] + 1)),
        _update_annotations=lambda *_args, **_kwargs: state.__setitem__("annotations", state["annotations"] + 1),
        _current_window_level=lambda: (400.0, 40.0),
        _sync_window_level_from_pipeline=lambda default=None: default or (400.0, 40.0),
    )

    QtViewerBridge.set_window_level(bridge, 400.0, 40.0, flag_default=False)

    assert state["pipeline_set"] == 0
    assert state["render"] == 0
    assert state["image"] == 0
    assert state["annotations"] == 0


def test_qt_wl_changed_skips_work_when_unchanged():
    state = {
        "pipeline_set": 0,
        "render": 0,
        "image": 0,
        "annotations": 0,
    }

    class _Pipeline:
        def set_window_level(self, *_args, **_kwargs):
            state["pipeline_set"] += 1

        def get_rendered_frame(self, _idx):
            state["render"] += 1
            return SimpleNamespace(qimage=None, window_width=400.0, window_center=40.0)

    bridge = SimpleNamespace(
        _current_slice=0,
        _window=400.0,
        _level=40.0,
        flag_set_custom_window_level=False,
        pipeline=_Pipeline(),
        qt_viewer=SimpleNamespace(set_image=lambda _img: state.__setitem__("image", state["image"] + 1)),
        _update_annotations=lambda *_args, **_kwargs: state.__setitem__("annotations", state["annotations"] + 1),
        _current_window_level=lambda: (400.0, 40.0),
        _sync_window_level_from_pipeline=lambda default=None: default or (400.0, 40.0),
    )

    QtViewerBridge._on_qt_wl_changed(bridge, 400.0, 40.0)

    assert state["pipeline_set"] == 0
    assert state["render"] == 0
    assert state["image"] == 0
    assert state["annotations"] == 0


def test_toolbar_audio_counter_uses_mtime_cache(monkeypatch, tmp_path):
    attach_root = tmp_path / "attachments"
    study_uid = "study-1"
    study_dir = attach_root / study_uid
    study_dir.mkdir(parents=True, exist_ok=True)

    calls = {"scan": 0}

    def _fake_list_files_in_folder(*_args, **_kwargs):
        calls["scan"] += 1
        return ["a.wav", "b.wav"]

    monkeypatch.setattr(toolbar_mod, "ATTACHMENT_PATH", attach_root)
    monkeypatch.setattr(toolbar_mod, "list_files_in_folder", _fake_list_files_in_folder)

    mic_counts = []
    manager = SimpleNamespace(
        _audio_counter_cache_study_uid="",
        _audio_counter_cache_dir_mtime_ns=-1,
        _audio_counter_cache_count=0,
        tool_access=SimpleNamespace(MICROPHONE="MIC"),
        tools_button={"MIC": SimpleNamespace(setCount=lambda n: mic_counts.append(int(n)))},
        _mic_menu_btn=None,
        _get_study_uid=lambda: study_uid,
    )

    toolbar_mod.ToolbarManager.update_audio_counter(manager)
    toolbar_mod.ToolbarManager.update_audio_counter(manager)

    assert calls["scan"] == 1
    assert mic_counts == [2, 2]

    (study_dir / "new.wav").write_bytes(b"x")
    prev_ns = int(study_dir.stat().st_mtime_ns)
    os.utime(study_dir, ns=(prev_ns + 1_000_000_000, prev_ns + 1_000_000_000))
    toolbar_mod.ToolbarManager.update_audio_counter(manager)

    assert calls["scan"] == 2


def test_stack_drag_duplicate_pending_target_skips_scheduler_and_pipeline(monkeypatch):
    from modules.viewer.fast import qt_viewer_bridge as bridge_mod

    scheduler_calls = []
    begin_calls = []
    clock_calls = []
    trace_reasons = []

    class _FakeScheduler:
        def target(self, target_slice, slice_count, series_uid):
            scheduler_calls.append((int(target_slice), int(slice_count), str(series_uid)))
            return SimpleNamespace(
                accepted=True,
                generation=2,
                direction=0,
                work_items=[],
            )

    monkeypatch.setattr(bridge_mod, "StackInteractionScheduler", _FakeScheduler)

    bridge = SimpleNamespace(
        _slice_count=64,
        _current_slice=10,
        _stack_drag_active=True,
        _stack_scheduler=None,
        _last_stack_target_slice=None,
        _last_stack_direction=0,
        _drag_metrics=None,
        _fast_pending_slider_value=None,
        _fast_pending_sync_update=False,
        _fast_pending_reference_update=False,
        last_index_slice_saved=10,
        _mark_interaction_event=lambda: None,
        vtk_widget=None,
        qt_viewer=None,
        pipeline=SimpleNamespace(
            _series_uid="series-uid",
            begin_stack_drag_target=lambda *args, **kwargs: begin_calls.append((args, kwargs)),
        ),
        _sync_interaction_slice_count_hint=lambda: None,
        _present_trace_register_request=lambda **_kwargs: 1,
        _present_trace_mark_terminal=lambda _request_id, **kwargs: trace_reasons.append(str(kwargs.get("reason", ""))),
        _fast_clock_enabled=lambda: True,
        _request_clocked_slice=lambda *args, **kwargs: clock_calls.append((args, kwargs)) or True,
    )

    changed_first = QtViewerBridge._apply_interaction_target(
        bridge,
        27,
        interaction_type="drag",
        request_queued_mono_ms=1.0,
    )
    changed_second = QtViewerBridge._apply_interaction_target(
        bridge,
        27,
        interaction_type="drag",
        request_queued_mono_ms=2.0,
    )

    assert changed_first is True
    assert changed_second is False
    assert scheduler_calls == [(27, 64, "series-uid")]
    assert len(begin_calls) == 1
    assert len(clock_calls) == 1
    assert "duplicate_pending_target" in trace_reasons


def test_clock_duplicate_target_keeps_alive_without_generation_churn():
    ensure_calls = []
    terminal_reasons = []

    bridge = SimpleNamespace(
        _slice_count=64,
        _current_slice=10,
        vtk_widget=None,
        _fast_latest_requested_slice=12,
        _fast_pending_interaction_type="drag",
        _fast_latest_interaction_ts_ms=100.0,
        _fast_request_generation=5,
        _fast_clock_last_request_mono_ms=100.0,
        _fast_last_presented_generation=3,
        _fast_clock_tick_interval_ms=33.0,
        _fast_clock_missed_tick_count=0,
        _fast_clock_superseded_count=0,
        _drag_session_id="test-session",
        _fast_clock_enabled=lambda: True,
        _present_trace_mark_terminal=lambda _request_id, **kwargs: terminal_reasons.append(
            str(kwargs.get("reason", ""))
        ),
        _ensure_render_clock_running=lambda: ensure_calls.append(True),
    )

    changed = QtViewerBridge._request_clocked_slice(
        bridge,
        12,
        interaction_type="drag",
        reason="interaction_target",
        request_id=99,
    )

    assert changed is True
    assert bridge._fast_request_generation == 5
    assert bridge._fast_clock_superseded_count == 0
    assert bridge._fast_latest_requested_slice == 12
    assert bridge._fast_latest_interaction_ts_ms > 100.0
    assert bridge._fast_clock_last_request_mono_ms > 100.0
    assert ensure_calls == [True]
    assert "clock_duplicate_target" in terminal_reasons


def test_clock_side_effects_skip_redundant_slider_set():
    class _Slider:
        def __init__(self, value):
            self.value = int(value)
            self.set_count = 0
            self._blocked = False
            self.block_calls = []

        def blockSignals(self, blocked):
            self._blocked = bool(blocked)
            self.block_calls.append(bool(blocked))

        def setValue(self, value):
            self.value = int(value)
            self.set_count += 1

    slider = _Slider(42)
    bridge = SimpleNamespace(
        _fast_clock_enabled=lambda: True,
        _fast_clock_fallback_active=False,
        vtk_widget=SimpleNamespace(
            slider=slider,
            patient_widget=None,
            image_viewer=None,
            _on_slice_changed_cb=None,
        ),
        _stack_drag_active=False,
        _last_stack_sync_ms=0.0,
        _last_sync_ms=0.0,
        _last_stack_reference_ms=0.0,
        _fast_pending_slider_value=42,
        _fast_pending_sync_update=False,
        _fast_pending_reference_update=False,
        _fast_last_presented_slice=None,
        _drag_session_id="test-session",
    )

    QtViewerBridge._apply_present_side_effects(
        bridge,
        presented_slice=42,
        reason="unit_test",
        force=False,
    )

    assert slider.set_count == 0
    assert slider.block_calls == []
    assert bridge._fast_last_presented_slice == 42


def test_non_clock_settle_flush_skips_redundant_slider_set():
    class _Slider:
        def __init__(self, value):
            self.value = int(value)
            self.set_count = 0
            self._blocked = False
            self.block_calls = []

        def blockSignals(self, blocked):
            self._blocked = bool(blocked)
            self.block_calls.append(bool(blocked))

        def setValue(self, value):
            self.value = int(value)
            self.set_count += 1

    slider = _Slider(21)
    bridge = SimpleNamespace(
        vtk_widget=SimpleNamespace(
            slider=slider,
            patient_widget=None,
            image_viewer=None,
            _on_slice_changed_cb=None,
        ),
        _current_slice=21,
        _fast_pending_slider_value=21,
        _fast_pending_sync_update=False,
        _fast_pending_reference_update=False,
    )

    QtViewerBridge._flush_non_clock_side_effects_on_settle(bridge)

    assert slider.set_count == 0
    assert slider.block_calls == []
    assert bridge._fast_pending_slider_value is None
    assert bridge._fast_pending_sync_update is False
    assert bridge._fast_pending_reference_update is False


def test_non_clock_interaction_skips_redundant_live_slider_set():
    class _Slider:
        def __init__(self, value):
            self.value = int(value)
            self.set_count = 0
            self._blocked = False
            self.block_calls = []

        def blockSignals(self, blocked):
            self._blocked = bool(blocked)
            self.block_calls.append(bool(blocked))

        def setValue(self, value):
            self.value = int(value)
            self.set_count += 1

    class _Timer:
        def stop(self):
            return None

        def start(self):
            return None

    set_slice_calls = []
    slider = _Slider(15)
    bridge = SimpleNamespace(
        _mark_interaction_event=lambda: None,
        _slice_count=64,
        _current_slice=3,
        _stack_drag_active=False,
        _sync_interaction_slice_count_hint=lambda: None,
        _present_trace_register_request=lambda **_kwargs: 1,
        _present_trace_mark_terminal=lambda *_args, **_kwargs: None,
        _settle_arm_seq=0,
        _last_settle_reason="",
        _interaction_settle_timer=_Timer(),
        _fast_clock_enabled=lambda: False,
        vtk_widget=SimpleNamespace(
            slider=slider,
            image_viewer=None,
            patient_widget=None,
            _on_slice_changed_cb=None,
        ),
        set_slice=lambda idx, fast_interaction=False, interaction_type="": set_slice_calls.append(
            (int(idx), bool(fast_interaction), str(interaction_type))
        ),
        _last_sync_ms=0.0,
        _last_stack_sync_ms=0.0,
        _last_stack_reference_ms=0.0,
        _fast_pending_slider_value=None,
        _fast_pending_sync_update=False,
        _fast_pending_reference_update=False,
        last_index_slice_saved=0,
    )

    changed = QtViewerBridge._apply_interaction_target(
        bridge,
        15,
        interaction_type="wheel",
        request_queued_mono_ms=0.0,
    )

    assert changed is True
    assert set_slice_calls == [(15, True, "wheel")]
    assert slider.set_count == 0
    assert slider.block_calls == []


def test_clock_side_effects_skip_redundant_image_viewer_rebind():
    class _Widget:
        def __init__(self):
            self._image_viewer = None
            self.assign_count = 0
            self.slider = None
            self.patient_widget = None
            self._on_slice_changed_cb = None

        @property
        def image_viewer(self):
            return self._image_viewer

        @image_viewer.setter
        def image_viewer(self, value):
            self.assign_count += 1
            self._image_viewer = value

    widget = _Widget()
    bridge = SimpleNamespace(
        _fast_clock_enabled=lambda: True,
        _fast_clock_fallback_active=False,
        vtk_widget=widget,
        _stack_drag_active=False,
        _last_stack_sync_ms=0.0,
        _last_sync_ms=0.0,
        _last_stack_reference_ms=0.0,
        _fast_pending_slider_value=None,
        _fast_pending_sync_update=False,
        _fast_pending_reference_update=False,
        _fast_last_presented_slice=None,
        _drag_session_id="test-session",
    )
    widget.image_viewer = bridge
    widget.assign_count = 0

    QtViewerBridge._apply_present_side_effects(
        bridge,
        presented_slice=7,
        reason="unit_test",
        force=False,
    )

    assert widget.assign_count == 0
