from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_viewers import _PWViewersMixin


class _SliderStub:
    def __init__(self):
        self._blocked = False
        self._minimum = 0
        self._maximum = 0
        self._value = 0

    def blockSignals(self, value):
        self._blocked = bool(value)

    def setRange(self, minimum, maximum):
        self._minimum = int(minimum)
        self._maximum = int(maximum)

    def setValue(self, value):
        self._value = int(value)

    def value(self):
        return self._value

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum


class _QtImageViewerStub:
    def __init__(self, current_slice=11):
        self._slice = int(current_slice)
        self.default_wl_calls = []

    def GetSlice(self):
        return self._slice

    def apply_default_window_level(self, slice_index):
        self.default_wl_calls.append(int(slice_index))


class _ViewerStub:
    def __init__(self, *, count_slices=22, qt_bridge_active=False, current_slice=11):
        self._count_slices = int(count_slices)
        self._qt_bridge_active = bool(qt_bridge_active)
        self.image_viewer = _QtImageViewerStub(current_slice=current_slice)
        self.set_slider_calls = []

    def set_slider(self, slider):
        self.set_slider_calls.append(slider)

    def get_count_of_slices(self):
        return self._count_slices


class _Harness(_PWViewersMixin):
    def __init__(self):
        self.slider_events = []

    def on_slider_value_changed(self, vtk_widget, value):
        self.slider_events.append((vtk_widget, int(value)))


def test_reset_slider_keeps_qt_bridge_current_slice_without_second_render():
    harness = _Harness()
    slider = _SliderStub()
    viewer = _ViewerStub(qt_bridge_active=True, current_slice=11)

    harness.reset_slider(viewer, slider)

    assert slider.minimum() == 0
    assert slider.maximum() == 21
    assert slider.value() == 11
    assert harness.slider_events == []
    assert viewer.image_viewer.default_wl_calls == []


def test_reset_slider_keeps_legacy_non_qt_callback_behavior():
    harness = _Harness()
    slider = _SliderStub()
    viewer = _ViewerStub(qt_bridge_active=False, current_slice=11)

    harness.reset_slider(viewer, slider)

    assert slider.minimum() == 0
    assert slider.maximum() == 21
    assert slider.value() == 0
    assert harness.slider_events == [(viewer, 0)]
    assert viewer.image_viewer.default_wl_calls == [0]