from __future__ import annotations

import types
from types import SimpleNamespace

from PySide6.QtCore import Qt

from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import _VWInteractorMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_scroll import _VWScrollMixin
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeStyleBase:
    def __init__(self, image_viewer):
        self.image_viewer = image_viewer
        self.widgets_by_slice = {}
        self.signal_emitter = SimpleNamespace(interactionOccurred=_FakeSignal())
        self.deactivate_called = 0

    def deactivate(self):
        self.deactivate_called += 1


class _FakeRequestedStyle(_FakeStyleBase):
    pass


class _FakeDefaultStyle(_FakeStyleBase):
    def reset_events(self):
        self.reset_events_called = True

    def On(self):
        self.on_called = True


class _FakeInteractor:
    def __init__(self):
        self.styles = []

    def SetInteractorStyle(self, style):
        self.styles.append(style)


class _InteractorHarness(_VWInteractorMixin):
    def __init__(self):
        self._qt_bridge_active = False
        self.image_viewer = SimpleNamespace(lock_camera_state=lambda *_args, **_kwargs: None, Render=lambda: None)
        self.current_style = _FakeStyleBase(self.image_viewer)
        self.style = _FakeDefaultStyle(self.image_viewer)
        self.interactor = _FakeInteractor()
        self.change_container_border = lambda *_args, **_kwargs: None

    def _freeze_render_window(self):
        return None

    def _capture_camera_state(self):
        return None

    def _restore_camera_state(self, _state):
        return None

    def _schedule_camera_restore(self, _state):
        return None

    def set_widgets_on_new_interactorstyle(self, new_interactorstyle):
        return new_interactorstyle

    def _ensure_interactor_style_enabled(self):
        return None


class _ScrollBase:
    def __init__(self):
        self.super_called = False

    def keyPressEvent(self, event):
        self.super_called = True


class _ScrollHarness(_VWScrollMixin, _ScrollBase):
    def __init__(self, current_style):
        _ScrollBase.__init__(self)
        self.image_viewer = SimpleNamespace(curved_mpr_mode=False)
        self.current_style = current_style


class _FakeEvent:
    def __init__(self, key, modifiers=Qt.NoModifier):
        self._key = key
        self._modifiers = modifiers
        self.accepted = False

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def _build_wl_bridge_stub():
    bridge = SimpleNamespace()
    bridge.metadata = {}
    bridge._current_slice = 3
    bridge._slice_count = 12
    bridge.flag_set_custom_window_level = False
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
    bridge._sync_window_level_from_pipeline = lambda default=None: default
    bridge.pipeline = SimpleNamespace(
        set_window_level=lambda *_args, **_kwargs: None,
        get_rendered_frame=lambda _idx: SimpleNamespace(
            qimage=None,
            window_width=111.0,
            window_center=22.0,
        ),
    )
    bridge.set_window_level = types.MethodType(QtViewerBridge.set_window_level, bridge)
    return bridge


def test_set_new_interactorstyle_deactivates_previous_style():
    widget = _InteractorHarness()
    previous = widget.current_style

    widget.set_new_interactorstyle(_FakeRequestedStyle)

    assert previous.deactivate_called == 1
    assert isinstance(widget.current_style, _FakeRequestedStyle)


def test_restore_default_interactorstyle_deactivates_previous_style():
    widget = _InteractorHarness()
    previous = widget.current_style

    widget.restore_default_interactorstyle()

    assert previous.deactivate_called == 1
    assert widget.current_style is widget.style


def test_escape_is_forwarded_to_current_style_before_super():
    handled = []
    style = SimpleNamespace(handle_key_press=lambda key: handled.append(key) or True)
    widget = _ScrollHarness(style)
    event = _FakeEvent(Qt.Key_Escape)

    widget.keyPressEvent(event)

    assert handled == ['Escape']
    assert event.accepted is True
    assert widget.super_called is False


def test_manual_qt_window_level_marks_custom_flag():
    bridge = _build_wl_bridge_stub()

    bridge.set_window_level(1500.0, -600.0, flag_default=False)

    assert bridge.flag_set_custom_window_level is True