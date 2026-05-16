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
    # Stub returns current_slice=11 from GetSlice().
    # reset_slider now reads mid_slices = GetSlice() (raw_k domain) and uses it
    # for both slider.setValue and apply_default_window_level.
    harness = _Harness()
    slider = _SliderStub()
    viewer = _ViewerStub(qt_bridge_active=False, current_slice=11)

    harness.reset_slider(viewer, slider)

    assert slider.minimum() == 0
    assert slider.maximum() == 21
    # slider tracks the display-slice position (= GetSlice() here because no
    # get_display_slice() on the stub → falls back to GetSlice() = 11).
    assert slider.value() == 11
    assert harness.slider_events == [(viewer, 11)]
    # apply_default_window_level must receive raw_k (= GetSlice() = 11),
    # NOT the old mid_slices=0 that poisoned the WL-preset lookup.
    assert viewer.image_viewer.default_wl_calls == [11]


def test_reset_slider_wl_receives_raw_k_not_display_k():
    """Fix 4 contract: apply_default_window_level always gets raw_k=GetSlice().

    Before Fix 4, the code passed mid_slices (display_k) to
    apply_default_window_level, which indexes metadata['instances'][raw_k].
    Passing a display_k value (e.g. N-1 under K-flip) would index the wrong
    instance WL preset.  After the fix, we pass GetSlice() which is always
    raw_k after a series switch (R16 FirstRender consumption resets to raw_k=0;
    later calls have whatever raw_k the viewer actually sits at).
    """
    harness = _Harness()
    slider = _SliderStub()
    # Simulate: 20-slice series, viewer currently at raw_k=5.
    viewer = _ViewerStub(qt_bridge_active=False, count_slices=20, current_slice=5)

    harness.reset_slider(viewer, slider)

    # WL must use GetSlice() = 5 (raw_k), not any display_k variant.
    assert viewer.image_viewer.default_wl_calls == [5]
    # Slider value is also driven by GetSlice() = 5 (the display position
    # the viewer already holds, since stub has no get_display_slice()).
    assert slider.value() == 5


def test_reset_slider_wl_not_called_for_qt_bridge():
    """Qt bridge path exits early — apply_default_window_level must not fire."""
    harness = _Harness()
    slider = _SliderStub()
    viewer = _ViewerStub(qt_bridge_active=True, current_slice=7)

    harness.reset_slider(viewer, slider)

    assert viewer.image_viewer.default_wl_calls == []