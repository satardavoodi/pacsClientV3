from __future__ import annotations

import types
from types import SimpleNamespace
import importlib

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QWidget

import PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor as _vw_interactor
import PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series as _vw_series_mod
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series import _VWSeriesMixin
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer


def _build_reset_bridge_stub(slice_count: int, current_slice: int = 0):
    bridge = SimpleNamespace()
    bridge.metadata = {}
    bridge._slice_count = slice_count
    bridge._current_slice = current_slice
    bridge._wl_scroll_cache_ww = 111.0
    bridge._wl_scroll_cache_wc = 22.0
    bridge.qt_viewer = SimpleNamespace(
        _current_slice_index=current_slice,
        set_modality_hint=lambda _mod: None,
        reset_view_called=0,
    )

    def _reset_view():
        bridge.qt_viewer.reset_view_called += 1

    bridge.qt_viewer.reset_view = _reset_view

    def _build_mock_vtk_data():
        bridge._slice_count = int((bridge.metadata or {}).get("series", {}).get("image_count", bridge._slice_count) or 0)

    bridge._build_mock_vtk_data = _build_mock_vtk_data

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge.reset_image_viewer = types.MethodType(QtViewerBridge.reset_image_viewer, bridge)
    return bridge


class _FakeTimer:
    def __init__(self):
        self._active = False
        self.start_count = 0
        self.stop_count = 0

    def stop(self):
        self._active = False
        self.stop_count += 1

    def start(self):
        self._active = True
        self.start_count += 1


class _FakeSignal:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, handler):
        self.disconnected.append(handler)


def _build_bridge_stub(slice_count: int = 200):
    bridge = SimpleNamespace()
    bridge._current_slice = 0
    bridge._slice_count = slice_count
    bridge._stack_drag_active = True
    bridge._protected_drag_active = True
    bridge._last_stack_sync_ms = 0.0
    bridge._last_stack_reference_ms = 0.0
    bridge._last_stack_target_slice = None
    bridge._interaction_settle_timer = _FakeTimer()
    bridge._set_slice_calls = []
    bridge._slice_hint_calls = []
    bridge._drag_metrics = None
    bridge._last_set_slice_ui_lag_ms = 0.0
    bridge.last_index_slice_saved = 0
    bridge.vtk_widget = None
    bridge._mark_interaction_event = lambda: None
    bridge.qt_viewer = SimpleNamespace(
        set_total_slices_hint=lambda count: bridge._slice_hint_calls.append(("qt", int(count))),
    )
    bridge.pipeline = SimpleNamespace(
        set_interaction_slice_count_hint=lambda count: bridge._slice_hint_calls.append(("pipe", int(count))),
    )

    def _set_slice(idx, fast_interaction=False, *, interaction_type=''):
        bridge._current_slice = idx
        bridge._set_slice_calls.append((idx, fast_interaction, interaction_type))

    bridge.set_slice = _set_slice

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge._apply_interaction_target = types.MethodType(QtViewerBridge._apply_interaction_target, bridge)
    bridge._on_qt_scroll = types.MethodType(QtViewerBridge._on_qt_scroll, bridge)
    bridge._on_stack_drag_target = types.MethodType(QtViewerBridge._on_stack_drag_target, bridge)
    bridge._get_interaction_slice_count_hint = types.MethodType(QtViewerBridge._get_interaction_slice_count_hint, bridge)
    bridge._sync_interaction_slice_count_hint = types.MethodType(QtViewerBridge._sync_interaction_slice_count_hint, bridge)
    return bridge


def _build_cleanup_bridge_stub():
    bridge = SimpleNamespace()
    bridge.qt_viewer = SimpleNamespace(
        window_level_changed=_FakeSignal(),
        slice_scroll_requested=_FakeSignal(),
        stack_drag_target_requested=_FakeSignal(),
        stack_drag_state_changed=_FakeSignal(),
        _scroll_stop_timer=_FakeTimer(),
        cleared=False,
    )
    bridge._interaction_settle_timer = _FakeTimer()
    bridge._stack_drag_active = True
    bridge._last_stack_target_slice = 9

    def _clear():
        bridge.qt_viewer.cleared = True

    bridge.qt_viewer.clear = _clear
    bridge.pipeline = SimpleNamespace(shutdown_called=False)

    def _shutdown():
        bridge.pipeline.shutdown_called = True

    bridge.pipeline.shutdown = _shutdown

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge._on_qt_wl_changed = types.MethodType(QtViewerBridge._on_qt_wl_changed, bridge)
    bridge._on_qt_scroll = types.MethodType(QtViewerBridge._on_qt_scroll, bridge)
    bridge._on_stack_drag_target = types.MethodType(QtViewerBridge._on_stack_drag_target, bridge)
    bridge._on_stack_drag_state = types.MethodType(QtViewerBridge._on_stack_drag_state, bridge)
    bridge._disconnect_viewer_signals = types.MethodType(QtViewerBridge._disconnect_viewer_signals, bridge)
    bridge.cleanup = types.MethodType(QtViewerBridge.cleanup, bridge)
    return bridge


def _build_end_fast_bridge_stub():
    bridge = SimpleNamespace()
    bridge._current_slice = 42
    bridge._last_settle_reason = 'stack_drag_stop'
    bridge._last_stack_direction = -1
    bridge._warmup_calls = []
    bridge._thumbnail_states = []
    bridge._annotations = []

    frame = SimpleNamespace(
        qimage=object(),
        window_width=350.0,
        window_center=45.0,
        decode_ms=1.0,
        filter_ms=2.0,
        wl_ms=3.0,
    )
    bridge.pipeline = SimpleNamespace(
        set_fast_interaction=lambda active: setattr(bridge, '_pipeline_fast', active),
        get_rendered_frame=lambda idx: frame,
        prepare_stack_settle_warmup=lambda idx, direction=0: bridge._warmup_calls.append((idx, direction)) or 7,
    )
    bridge.qt_viewer = SimpleNamespace(
        set_image=lambda qimage: setattr(bridge, '_image', qimage),
        set_window_level_values=lambda ww, wc: setattr(bridge, '_wl', (ww, wc)),
        update=lambda: setattr(bridge, '_updated', True),
    )
    bridge._set_thumbnail_scroll_active = lambda active: bridge._thumbnail_states.append(active)
    bridge._resume_booster = lambda: setattr(bridge, '_booster_resumed', True)
    bridge._update_annotations = lambda *args: bridge._annotations.append(args)

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge.end_fast_interaction = types.MethodType(QtViewerBridge.end_fast_interaction, bridge)
    return bridge


def _build_window_level_bridge_stub():
    bridge = SimpleNamespace()
    bridge.metadata = {}
    bridge._current_slice = 3
    bridge._slice_count = 12
    bridge._window = 400.0
    bridge._level = 40.0
    bridge._wl_scroll_cache_ww = None
    bridge._wl_scroll_cache_wc = None
    bridge.qt_viewer = SimpleNamespace(
        set_image=lambda _img: None,
        set_window_level_values=lambda _ww, _wc: None,
        annotations=SimpleNamespace(update_from_metadata=lambda **_kwargs: None),
        get_zoom=lambda: 1.0,
        update=lambda: None,
    )
    bridge._update_annotations = lambda *_args, **_kwargs: None
    bridge._sync_window_level_from_pipeline = lambda default=None: default or (bridge._window, bridge._level)
    bridge._rendered_frames = []
    bridge.pipeline_calls = []
    bridge.pipeline = SimpleNamespace(
        set_window_level=lambda ww, wc, trigger_prefetch=True: bridge.pipeline_calls.append((ww, wc, trigger_prefetch)),
        get_rendered_frame=lambda idx: bridge._rendered_frames.append(idx) or SimpleNamespace(
            qimage=None,
            window_width=111.0,
            window_center=22.0,
        ),
    )

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge.set_window_level = types.MethodType(QtViewerBridge.set_window_level, bridge)
    return bridge


def _build_mock_vtk_bridge_stub():
    bridge = SimpleNamespace()
    bridge._slice_count = 0
    bridge.qt_viewer = SimpleNamespace(set_pixel_spacing=lambda _spacing: None)
    bridge.renderer = SimpleNamespace(_camera=SimpleNamespace(_parallel_scale=0.0))
    bridge._sync_window_level_from_pipeline = lambda default=None: default
    bridge._sync_interaction_slice_count_hint = lambda: bridge._slice_count
    bridge.pipeline_calls = []
    bridge.pipeline = SimpleNamespace(
        slice_count=12,
        get_slice_meta=lambda _idx: SimpleNamespace(
            cols=512,
            rows=256,
            pixel_spacing=(1.0, 1.0),
            ipp=(0.0, 0.0, 0.0),
            slice_thickness=1.0,
        ),
        get_scalar_range=lambda _idx: (0.0, 4095.0),
        get_default_window_level=lambda _idx: (400.0, 40.0),
        set_window_level=lambda ww, wc, trigger_prefetch=True: bridge.pipeline_calls.append((ww, wc, trigger_prefetch)),
    )

    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge._build_mock_vtk_data = types.MethodType(QtViewerBridge._build_mock_vtk_data, bridge)
    return bridge


class _FakeRenderWindow:
    def SetOffScreenRendering(self, _flag):
        pass

    def SetSize(self, *_args):
        pass

    def SetShowWindow(self, _flag):
        pass


class _FakeQtViewer:
    def __init__(self):
        self.geometry = None
        self.shown = False
        self.raised = False
        self.updated = False
        self.geometry_updated = False
        self.repainted = False

    def setGeometry(self, rect):
        self.geometry = rect

    def show(self):
        self.shown = True

    def raise_(self):
        self.raised = True

    def update(self):
        self.updated = True

    def updateGeometry(self):
        self.geometry_updated = True

    def repaint(self):
        self.repainted = True


class _FakeBridge:
    def __init__(self, slice_count=12):
        self._slice_count = slice_count
        self._current_slice = 0
        self.primed_slice_calls = []
        self.slice_calls = []
        self.default_calls = []
        self.events = []
        self.zoom_to_fit_calls = 0

    def SetSlice(self, idx):
        self._current_slice = idx
        self.primed_slice_calls.append(idx)
        self.events.append(("prime", idx))

    def get_count_of_slices(self):
        return self._slice_count

    def set_slice(self, idx):
        self.slice_calls.append(idx)
        self.events.append(("slice", idx))

    def apply_default_window_level(self, idx):
        self.default_calls.append(idx)
        self.events.append(("wl", idx))

    def zoom_to_fit(self):
        self.zoom_to_fit_calls += 1
        self.events.append(("fit", self._slice_count))
        return 321.0


class _FakeQtBridgeStyle:
    def __init__(self, vtk_widget):
        self.vtk_widget = vtk_widget


class _FakeSeriesWidget(_VWSeriesMixin):
    def __init__(self, old_bridge=None, old_qt_viewer=None):
        self._qt_bridge_active = old_bridge is not None or old_qt_viewer is not None
        self._qt_viewer_widget = old_qt_viewer
        self.image_viewer = old_bridge
        self._active_backend = _vw_series_mod.BACKEND_PYDICOM_QT
        self._pending_tool_style_cls = None
        self.slider = None
        self.render_window = _FakeRenderWindow()
        self.cleanup_calls = []
        self.saved_status_camera = None
        self.current_style = None
        self._protected_parallel_scale = None

    def _update_backend_badge(self):
        self.backend_badge_updated = True

    def cleanup_image_viewer(self, preserve_bound_backend=False):
        self.cleanup_calls.append(bool(preserve_bound_backend))
        if self.image_viewer is not None and hasattr(self.image_viewer, 'cleanup'):
            self.image_viewer.cleanup()
        self.image_viewer = None
        self._qt_viewer_widget = None
        self._qt_bridge_active = False

    def setAttribute(self, *_args, **_kwargs):
        pass

    def rect(self):
        return (0, 0, 128, 128)

    def save_status_camera(self, image_viewer):
        self.saved_status_camera = image_viewer


class TestQtPresentationSync:
    def test_sync_qt_viewer_presentation_refits_and_updates_scale(self):
        widget = _FakeSeriesWidget()
        widget.slider = SimpleNamespace(raise_=lambda: setattr(widget, "slider_raised", True))
        widget.slider_raised = False
        widget._qt_viewer_widget = _FakeQtViewer()
        widget.image_viewer = _FakeBridge(slice_count=9)

        widget._sync_qt_viewer_presentation(refit_view=True)

        assert widget._qt_viewer_widget.geometry == (0, 0, 128, 128)
        assert widget._qt_viewer_widget.raised is True
        assert widget.slider_raised is True
        assert widget.image_viewer.zoom_to_fit_calls == 1
        assert widget._protected_parallel_scale == 321.0


class _SelectionParent(QWidget):
    def __init__(self):
        super().__init__()
        self.selection_calls = 0

    def change_container_border(self):
        self.selection_calls += 1


class TestQtSelectionForwarding:
    def test_mouse_press_notifies_parent_view_selection(self):
        app = QApplication.instance() or QApplication([])
        parent = _SelectionParent()
        viewer = QtSliceViewer(parent=parent)

        press_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(10.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        viewer.mousePressEvent(press_event)

        assert app is not None
        assert parent.selection_calls == 1

    def test_resize_keeps_fit_to_viewport_until_manual_interaction(self):
        app = QApplication.instance() or QApplication([])
        viewer = QtSliceViewer()
        viewer._image_width = 512
        viewer._image_height = 512
        viewer._zoom = 0.5
        viewer._pan_offset = QPointF(12.0, 8.0)
        viewer._fit_to_viewport = True
        viewer._calculate_fit_zoom = lambda: 1.75

        resize_event = QResizeEvent(QSize(300, 300), QSize(150, 150))

        viewer.resizeEvent(resize_event)

        assert app is not None
        assert viewer._zoom == 1.75
        assert viewer._pan_offset == QPointF(0.0, 0.0)


class TestQtViewerFactoryConfig:
    def test_factory_uses_pooyan_filter_json_settings(self, monkeypatch):
        vw_globals = importlib.import_module(
            'PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals'
        )

        captured = {}

        class _FakePipeline:
            def __init__(self, config=None):
                captured['config'] = config

            def open_series(self, series_path, metadata=None):
                captured['series_path'] = series_path
                captured['metadata'] = metadata

        class _FakeQtViewerFactory:
            def __init__(self, parent=None):
                self.parent = parent
                self.geometry = None

            def setGeometry(self, rect):
                self.geometry = rect

        class _FakeBridgeFactory:
            def __init__(self, qt_viewer=None, pipeline=None, metadata=None, metadata_fixed=None, vtk_widget=None):
                captured['qt_viewer'] = qt_viewer
                captured['pipeline'] = pipeline
                captured['metadata_fixed'] = metadata_fixed
                captured['vtk_widget'] = vtk_widget

        monkeypatch.setattr(
            'PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline.load_pooyan_filter_params_from_json',
            lambda: SimpleNamespace(
                enabled=True,
                sigma_x=1.25,
                alpha=1.6,
                beta=-0.4,
                invert=True,
                small_threshold=300,
                preserve_dimensions=False,
            ),
        )
        monkeypatch.setattr(
            'modules.viewer.fast.lightweight_2d_pipeline.Lightweight2DPipeline',
            _FakePipeline,
        )
        monkeypatch.setattr(
            'modules.viewer.fast.qt_slice_viewer.QtSliceViewer',
            _FakeQtViewerFactory,
        )
        monkeypatch.setattr(
            'modules.viewer.fast.qt_viewer_bridge.QtViewerBridge',
            _FakeBridgeFactory,
        )

        fake_widget = SimpleNamespace(rect=lambda: (0, 0, 200, 100))
        metadata = {
            'instances': [
                {'instance_path': 'C:/tmp/study/201/Instance_0001.dcm'}
            ]
        }

        bridge, qt_viewer = vw_globals._create_qt_viewer_bridge(fake_widget, metadata, {'fixed': True})

        cfg = captured['config']
        assert cfg.opencv_filter_enabled is True
        assert cfg.opencv_sigma_x == 1.25
        assert cfg.opencv_alpha == 1.6
        assert cfg.opencv_beta == -0.4
        assert cfg.opencv_invert is True
        assert cfg.opencv_small_threshold == 300
        assert cfg.opencv_preserve_dimensions is False
        assert captured['series_path'].replace('\\', '/').endswith('/study/201')
        assert captured['metadata'] is metadata
        assert captured['metadata_fixed'] == {'fixed': True}
        assert qt_viewer.geometry == (0, 0, 200, 100)
        assert captured['qt_viewer'] is qt_viewer
        assert isinstance(bridge, _FakeBridgeFactory)


class TestQtStackDragBridge:
    def test_stack_drag_applies_atomic_multi_slice_delta(self):
        bridge = _build_bridge_stub()

        bridge._on_qt_scroll(4)

        assert bridge._current_slice == 4
        assert bridge._set_slice_calls == [(4, True, 'drag')]

    def test_stack_drag_does_not_drop_followup_small_delta(self):
        bridge = _build_bridge_stub()

        bridge._on_qt_scroll(4)
        bridge._on_qt_scroll(1)
        bridge._on_qt_scroll(1)

        assert [call[0] for call in bridge._set_slice_calls] == [4, 5, 6]
        assert all(call[1] is True for call in bridge._set_slice_calls)
        assert all(call[2] == 'drag' for call in bridge._set_slice_calls)

    def test_stack_drag_clamps_to_progressive_available_slices(self):
        bridge = _build_bridge_stub(slice_count=200)
        bridge.vtk_widget = SimpleNamespace(
            _progressive_mode=True,
            _available_slice_count=2,
        )

        bridge._on_qt_scroll(4)
        bridge._on_qt_scroll(1)

        assert bridge._current_slice == 1
        assert bridge._set_slice_calls == [(1, True, 'drag')]

    def test_stack_drag_syncs_interactive_slice_hint_to_qt_and_pipeline(self):
        bridge = _build_bridge_stub(slice_count=200)
        bridge.vtk_widget = SimpleNamespace(
            _progressive_mode=True,
            _available_slice_count=40,
        )

        bridge._on_qt_scroll(4)

        assert ("qt", 40) in bridge._slice_hint_calls
        assert ("pipe", 40) in bridge._slice_hint_calls

    def test_reset_image_viewer_preserves_requested_slice_when_series_grows(self):
        bridge = _build_reset_bridge_stub(slice_count=20, current_slice=7)

        bridge.reset_image_viewer(None, {
            "series": {"image_count": 132, "modality": "CT"},
        }, preserve_slice=7)

        assert bridge._slice_count == 132
        assert bridge._current_slice == 7
        assert bridge.qt_viewer._current_slice_index == 7
        assert bridge._wl_scroll_cache_ww is None
        assert bridge._wl_scroll_cache_wc is None
        assert bridge.qt_viewer.reset_view_called == 0

    def test_reset_image_viewer_clamps_preserved_slice_to_new_range(self):
        bridge = _build_reset_bridge_stub(slice_count=20, current_slice=18)

        bridge.reset_image_viewer(None, {
            "series": {"image_count": 5, "modality": "CT"},
        }, preserve_slice=18)

        assert bridge._slice_count == 5
        assert bridge._current_slice == 4
        assert bridge.qt_viewer._current_slice_index == 4

    def test_reset_image_viewer_can_reset_qt_presentation_when_requested(self):
        bridge = _build_reset_bridge_stub(slice_count=20, current_slice=18)

        bridge.reset_image_viewer(
            None,
            {"series": {"image_count": 5, "modality": "CT"}},
            preserve_slice=4,
            reset_presentation=True,
        )

        assert bridge._slice_count == 5
        assert bridge._current_slice == 4
        assert bridge.qt_viewer._current_slice_index == 4
        assert bridge.qt_viewer.reset_view_called == 1

    def test_cleanup_disconnects_qt_viewer_signals_and_stops_timers(self):
        bridge = _build_cleanup_bridge_stub()

        bridge.cleanup()

        assert bridge._interaction_settle_timer.stop_count == 1
        assert bridge.qt_viewer._scroll_stop_timer.stop_count == 1
        assert bridge.pipeline.shutdown_called is True
        assert bridge.qt_viewer.cleared is True
        assert bridge._stack_drag_active is False
        assert bridge._last_stack_target_slice is None
        assert bridge.qt_viewer.window_level_changed.disconnected == [bridge._on_qt_wl_changed]
        assert bridge.qt_viewer.slice_scroll_requested.disconnected == [bridge._on_qt_scroll]
        assert bridge.qt_viewer.stack_drag_target_requested.disconnected == [bridge._on_stack_drag_target]
        assert bridge.qt_viewer.stack_drag_state_changed.disconnected == [bridge._on_stack_drag_state]

    def test_stack_drag_target_renders_direct_absolute_target(self):
        bridge = _build_bridge_stub(slice_count=200)

        bridge._on_stack_drag_target(27)

        assert bridge._current_slice == 27
        assert bridge._set_slice_calls == [(27, True, 'drag')]

    def test_stack_drag_target_ignores_repeated_same_target(self):
        bridge = _build_bridge_stub(slice_count=200)

        bridge._on_stack_drag_target(27)
        bridge._on_stack_drag_target(27)

        assert bridge._set_slice_calls == [(27, True, 'drag')]

    def test_stack_drag_object_requests_use_series_uid_from_pipeline(self, monkeypatch):
        monkeypatch.setattr(
            'modules.viewer.fast.object_cache.is_noop_object_cache',
            lambda: False,
        )
        bridge = _build_bridge_stub(slice_count=200)
        object_calls = []
        begin_calls = []
        bridge.pipeline = SimpleNamespace(
            _series_uid="series-uid-actual",
            _series_number="7",
            set_interaction_slice_count_hint=lambda count: bridge._slice_hint_calls.append(("pipe", int(count))),
            begin_stack_drag_target=lambda *args, **kwargs: begin_calls.append((args, kwargs)),
            has_object=lambda series_uid, slice_index: False,
            request_object=lambda priority, series_uid, slice_index: object_calls.append(
                (priority, series_uid, slice_index)
            ) or True,
        )

        bridge._on_stack_drag_target(27)

        assert object_calls
        assert {call[1] for call in object_calls} == {"series-uid-actual"}
        assert begin_calls == [((27,), {"generation": 2, "direction": 0, "p01_indices": (27, 28, 29, 26)})]

    def test_stack_drag_object_requests_skip_local_hits_via_has_object(self, monkeypatch):
        monkeypatch.setattr(
            'modules.viewer.fast.object_cache.is_noop_object_cache',
            lambda: False,
        )
        bridge = _build_bridge_stub(slice_count=200)
        has_calls = []
        object_calls = []

        def _has_object(series_uid, slice_index):
            has_calls.append((series_uid, slice_index))
            return slice_index == 27

        bridge.pipeline = SimpleNamespace(
            _series_uid="series-uid-actual",
            _series_number="7",
            set_interaction_slice_count_hint=lambda count: bridge._slice_hint_calls.append(("pipe", int(count))),
            begin_stack_drag_target=lambda *_args, **_kwargs: None,
            has_object=_has_object,
            request_object=lambda priority, series_uid, slice_index: object_calls.append(
                (priority, series_uid, slice_index)
            ) or True,
        )

        bridge._on_stack_drag_target(27)

        assert has_calls, "drag lane should probe local object availability before escalation"
        assert ("series-uid-actual", 27) in has_calls
        assert all(call[2] != 27 for call in object_calls), "local P0 target should not be re-requested"
        assert object_calls, "missing P1 neighbors should still be escalated"

    def test_stack_drag_object_requests_fallback_when_has_object_missing(self, monkeypatch):
        monkeypatch.setattr(
            'modules.viewer.fast.object_cache.is_noop_object_cache',
            lambda: False,
        )
        bridge = _build_bridge_stub(slice_count=200)
        object_calls = []
        bridge.pipeline = SimpleNamespace(
            _series_uid="series-uid-actual",
            _series_number="7",
            set_interaction_slice_count_hint=lambda count: bridge._slice_hint_calls.append(("pipe", int(count))),
            begin_stack_drag_target=lambda *_args, **_kwargs: None,
            request_object=lambda priority, series_uid, slice_index: object_calls.append(
                (priority, series_uid, slice_index)
            ) or True,
        )

        bridge._on_stack_drag_target(27)

        assert object_calls, "request_object fallback must still work when has_object is not implemented"

    def test_stack_drag_stop_end_fast_interaction_runs_settle_warmup(self):
        bridge = _build_end_fast_bridge_stub()

        bridge.end_fast_interaction()

        assert bridge._pipeline_fast is False
        assert bridge._updated is True
        assert bridge._warmup_calls == [(42, -1)]
        assert bridge._annotations

    def test_wheel_settle_does_not_run_stack_settle_warmup(self):
        bridge = _build_end_fast_bridge_stub()
        bridge._last_settle_reason = 'wheel_scroll'

        bridge.end_fast_interaction()

        assert bridge._pipeline_fast is False
        assert bridge._warmup_calls == []

    def test_start_qt_viewer_cleans_existing_bridge_before_replacement(self, monkeypatch):
        old_bridge = SimpleNamespace(cleanup_called=False)
        queued = []

        def _cleanup_old_bridge():
            old_bridge.cleanup_called = True

        old_bridge.cleanup = _cleanup_old_bridge
        widget = _FakeSeriesWidget(old_bridge=old_bridge, old_qt_viewer=SimpleNamespace())
        new_bridge = _FakeBridge(slice_count=12)
        new_viewer = _FakeQtViewer()

        monkeypatch.setattr(
            'PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series._create_qt_viewer_bridge',
            lambda vtk_widget, metadata, metadata_fixed: (new_bridge, new_viewer),
        )
        monkeypatch.setattr(_vw_interactor, '_QtBridgeStyle', _FakeQtBridgeStyle)
        monkeypatch.setattr(
            _vw_series_mod.QTimer,
            'singleShot',
            lambda delay, fn: queued.append((delay, fn)),
        )

        widget._start_qt_viewer(metadata={}, metadata_fixed={})

        assert widget.cleanup_calls == [True]
        assert old_bridge.cleanup_called is True
        assert widget.image_viewer is new_bridge
        assert widget._qt_viewer_widget is new_viewer
        assert widget._qt_bridge_active is True
        assert new_bridge.primed_slice_calls == [6]
        assert new_bridge.slice_calls == [6]
        assert new_bridge.default_calls == [6]
        assert new_bridge.events[:3] == [("prime", 6), ("wl", 6), ("slice", 6)]
        assert new_bridge.zoom_to_fit_calls == 1
        assert widget._protected_parallel_scale == 321.0
        assert new_viewer.geometry == (0, 0, 128, 128)
        assert new_viewer.raised is True
        assert [delay for delay, _ in queued] == [0, 50, 120, 220]

        queued[0][1]()

        assert new_bridge.zoom_to_fit_calls == 2
        assert widget._protected_parallel_scale == 321.0

        queued[1][1]()
        queued[2][1]()
        queued[3][1]()

        assert new_bridge.zoom_to_fit_calls == 5
        assert widget._protected_parallel_scale == 321.0

    def test_start_qt_viewer_cleans_existing_vtk_viewer_before_replacement(self, monkeypatch):
        old_viewer = SimpleNamespace(cleanup_called=False)

        def _cleanup_old_viewer():
            old_viewer.cleanup_called = True

        old_viewer.cleanup = _cleanup_old_viewer
        widget = _FakeSeriesWidget(old_bridge=old_viewer, old_qt_viewer=None)
        widget._qt_bridge_active = False
        queued = []
        new_bridge = _FakeBridge(slice_count=10)
        new_viewer = _FakeQtViewer()

        monkeypatch.setattr(
            'PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series._create_qt_viewer_bridge',
            lambda vtk_widget, metadata, metadata_fixed: (new_bridge, new_viewer),
        )
        monkeypatch.setattr(_vw_interactor, '_QtBridgeStyle', _FakeQtBridgeStyle)
        monkeypatch.setattr(
            _vw_series_mod.QTimer,
            'singleShot',
            lambda delay, fn: queued.append((delay, fn)),
        )

        widget._start_qt_viewer(metadata={}, metadata_fixed={})

        assert widget.cleanup_calls == [True]
        assert old_viewer.cleanup_called is True
        assert widget._active_backend == _vw_series_mod.BACKEND_PYDICOM_QT
        assert new_viewer.shown is True
        assert new_viewer.raised is True

    def test_cleanup_image_viewer_preserves_qt_backend_when_requested(self):
        class _CleanupWidget(_VWSeriesMixin):
            def __init__(self):
                self._qt_bridge_active = False
                self._active_backend = _vw_series_mod.BACKEND_PYDICOM_QT
                self._lazy_loader = None
                self._bound_backend_metadata = {"series": {"viewer_backend": _vw_series_mod.BACKEND_PYDICOM_QT}}
                self._series_generation_id = 1
                self._lazy_requested_generation = 1
                self._lazy_requested_slice = None
                self._qt_viewer_widget = None
                self.image_viewer = None

            def _dbg_fast_state(self, *_args, **_kwargs):
                return None

            def _hide_qt_viewer(self):
                return None

            def _release_bound_lazy_loader(self):
                self._lazy_loader = None

            def _update_backend_badge(self):
                return None

        widget = _CleanupWidget()

        widget.cleanup_image_viewer(preserve_bound_backend=True)

        assert widget._active_backend == _vw_series_mod.BACKEND_PYDICOM_QT

    def test_default_window_level_sync_does_not_trigger_prefetch(self):
        bridge = _build_window_level_bridge_stub()

        bridge.set_window_level(350.0, 30.0, flag_default=True)

        assert bridge.pipeline_calls == [(350.0, 30.0, False)]
        assert bridge._rendered_frames == []

    def test_initial_bridge_window_level_sync_skips_prefetch(self):
        bridge = _build_mock_vtk_bridge_stub()

        bridge._build_mock_vtk_data()

        assert bridge.pipeline_calls == [(400.0, 40.0, False)]

    def test_atomic_drag_delta_preserves_odd_anchor_when_bridge_is_on_slice_one(self):
        bridge = _build_bridge_stub(slice_count=200)
        bridge._current_slice = 1

        bridge._on_qt_scroll(2)

        assert bridge._current_slice == 3
        assert bridge._set_slice_calls == [(3, True, 'drag')]
