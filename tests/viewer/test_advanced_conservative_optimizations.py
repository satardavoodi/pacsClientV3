from types import SimpleNamespace

from modules.viewer.advanced.viewer_2d import CustomCombineImageViewers, ImageViewer2D


def test_set_slice_skips_overlay_sync_when_no_overlays():
    calls = {
        "set_slice": 0,
        "corners": 0,
        "overlay_sync": 0,
        "render": 0,
    }

    def _set_slice(value):
        state.current_raw_k = int(value)
        calls["set_slice"] += 1

    def _get_slice():
        return int(state.current_raw_k)

    state = SimpleNamespace(
        current_raw_k=0,
        _display_geometry_contract=None,
        _emit_orientation_audit_active=lambda **_kwargs: None,
        _emit_advanced_vtk_orientation_audit=lambda _idx: None,
        _emit_axial_stack_order_policy_audit=lambda _idx: None,
        flag_set_custom_window_level=True,
        update_corners_actors=lambda: calls.__setitem__("corners", calls["corners"] + 1),
        _sync_all_overlays_extent=lambda: calls.__setitem__("overlay_sync", calls["overlay_sync"] + 1),
        Render=lambda: calls.__setitem__("render", calls["render"] + 1),
        SetSlice=_set_slice,
        GetSlice=_get_slice,
        _last_fast_annotation_update_ms=0.0,
        _last_fast_overlay_sync_ms=0.0,
        _fast_corner_overlay_interval_ms=100.0,
        _overlays=[],
        metadata={},
        orientation_markers=None,
    )

    ImageViewer2D._set_slice_impl(state, 5, fast_interaction=False, force_annotations=False)

    assert calls["set_slice"] == 1
    assert calls["corners"] == 1
    assert calls["render"] == 1
    assert calls["overlay_sync"] == 0


def test_sync_all_overlays_extent_skips_base_extent_lookup_without_overlays():
    calls = {"get_actor": 0}

    class _BaseActor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

    def _get_image_actor():
        calls["get_actor"] += 1
        return _BaseActor()

    state = SimpleNamespace(
        _overlays=[],
        GetImageActor=_get_image_actor,
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["get_actor"] == 0


def test_sync_all_overlays_extent_skips_redundant_actor_extent_set():
    calls = {"set_extent": 0}
    base_extent = (0, 7, 0, 7, 3, 3)

    class _BaseActor:
        def GetDisplayExtent(self):
            return base_extent

    class _OverlayActor:
        def __init__(self):
            self._extent = base_extent

        def GetDisplayExtent(self):
            return self._extent

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_skips_redundant_actor_extent_set():
    calls = {"set_extent": 0}
    expected_extent = (0, 7, 0, 5, 2, 2)

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return expected_extent

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return (8, 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_do_render_skips_redundant_slider_maximum_set():
    calls = {"set_max": 0}

    class _Slider:
        def __init__(self, max_value):
            self._max = int(max_value)

        def maximum(self):
            return self._max

        def setMaximum(self, value):
            calls["set_max"] += 1
            self._max = int(value)

    state = SimpleNamespace(
        image_reslice=SimpleNamespace(Update=lambda: None),
        UpdateDisplayExtent=lambda: None,
        Render=lambda: None,
        update_corners_actors=lambda: None,
        slider=_Slider(max_value=12),
        get_count_of_slices=lambda: 12,
        _render_pending=True,
    )

    ImageViewer2D._do_render(state)

    assert calls["set_max"] == 0
    assert state._render_pending is False


def test_change_local_series_skips_when_series_already_active():
    calls = {
        "set_input": 0,
        "set_color_mapper": 0,
        "zoom_to_fit": 0,
        "render": 0,
    }

    _reslice1 = SimpleNamespace(GetOutput=lambda: object(), metadata={"series": {"series_number": 1}})
    _reslice2 = SimpleNamespace(GetOutput=lambda: object(), metadata={"series": {"series_number": 2}})

    state = SimpleNamespace(
        image_reslice=_reslice1,
        image_reslice_1=_reslice1,
        image_reslice_2=_reslice2,
        SetInputData=lambda _data: calls.__setitem__("set_input", calls["set_input"] + 1),
        set_color_mapper=lambda: calls.__setitem__("set_color_mapper", calls["set_color_mapper"] + 1),
        zoom_to_fit=lambda **_kwargs: calls.__setitem__("zoom_to_fit", calls["zoom_to_fit"] + 1),
        image_render_window=SimpleNamespace(Render=lambda: calls.__setitem__("render", calls["render"] + 1)),
        flag_set_custom_window_level=True,
    )

    CustomCombineImageViewers.change_local_series(state, "series_1")

    assert calls["set_input"] == 0
    assert calls["set_color_mapper"] == 0
    assert calls["zoom_to_fit"] == 0
    assert calls["render"] == 0


def test_combine_set_slice_queries_first_series_count_once():
    calls = {"count1": 0, "apply_wl": 0, "set_slice": 0, "corners": 0, "render": 0}

    def _count1():
        calls["count1"] += 1
        return 10

    state = SimpleNamespace(
        skip_slices=0,
        series_showed="series_2",
        get_count_of_slice_image_1=_count1,
        change_local_series=lambda _sn: None,
        flag_set_custom_window_level=False,
        apply_default_window_level=lambda _idx: calls.__setitem__("apply_wl", calls["apply_wl"] + 1),
        SetSlice=lambda _idx: calls.__setitem__("set_slice", calls["set_slice"] + 1),
        update_corners_actors=lambda: calls.__setitem__("corners", calls["corners"] + 1),
        Render=lambda: calls.__setitem__("render", calls["render"] + 1),
    )

    CustomCombineImageViewers.set_slice(state, 11)

    assert calls["count1"] == 1
    assert calls["apply_wl"] == 1
    assert calls["set_slice"] == 1
    assert calls["corners"] == 1
    assert calls["render"] == 1


def test_combine_set_slice_skips_redundant_skip_slices_write():
    class _State:
        def __init__(self):
            self._skip_slices = 0
            self.skip_assignments = 0
            self.series_showed = "series_1"
            self.flag_set_custom_window_level = True

        @property
        def skip_slices(self):
            return self._skip_slices

        @skip_slices.setter
        def skip_slices(self, value):
            self.skip_assignments += 1
            self._skip_slices = int(value)

        def get_count_of_slice_image_1(self):
            return 10

        def change_local_series(self, _sn):
            raise AssertionError("change_local_series should not be called")

        def SetSlice(self, _idx):
            pass

        def update_corners_actors(self):
            pass

        def Render(self):
            pass

    state = _State()
    CustomCombineImageViewers.set_slice(state, 5)

    assert state.skip_assignments == 0


def test_change_local_series_uses_single_get_output_call():
    calls = {
        "get_output": 0,
        "set_input": 0,
        "set_color_mapper": 0,
        "zoom_to_fit": 0,
        "render": 0,
    }

    _output = object()

    class _Reslice:
        metadata = {"series": {"series_number": 2}}

        def GetOutput(self):
            calls["get_output"] += 1
            return _output

    state = SimpleNamespace(
        image_reslice=None,
        image_reslice_1=SimpleNamespace(GetOutput=lambda: object(), metadata={}),
        image_reslice_2=_Reslice(),
        SetInputData=lambda _data: calls.__setitem__("set_input", calls["set_input"] + 1),
        set_color_mapper=lambda: calls.__setitem__("set_color_mapper", calls["set_color_mapper"] + 1),
        zoom_to_fit=lambda **_kwargs: calls.__setitem__("zoom_to_fit", calls["zoom_to_fit"] + 1),
        image_render_window=SimpleNamespace(Render=lambda: calls.__setitem__("render", calls["render"] + 1)),
        flag_set_custom_window_level=True,
        vtk_image_data=None,
        metadata=None,
    )

    CustomCombineImageViewers.change_local_series(state, "series_2")

    assert calls["get_output"] == 1
    assert calls["set_input"] == 1
    assert calls["set_color_mapper"] == 1
    assert calls["zoom_to_fit"] == 1
    assert calls["render"] == 1
    assert state.vtk_image_data is _output


def test_change_local_series_skips_redundant_custom_wl_flag_write():
    calls = {
        "flag_writes": 0,
    }

    _output = object()

    class _Reslice:
        metadata = {"series": {"series_number": 2}}

        def GetOutput(self):
            return _output

    class _State:
        def __init__(self):
            self.image_reslice = None
            self.image_reslice_1 = SimpleNamespace(GetOutput=lambda: object(), metadata={})
            self.image_reslice_2 = _Reslice()
            self._flag = False
            self.vtk_image_data = None
            self.metadata = None
            self.image_render_window = SimpleNamespace(Render=lambda: None)

        @property
        def flag_set_custom_window_level(self):
            return self._flag

        @flag_set_custom_window_level.setter
        def flag_set_custom_window_level(self, value):
            calls["flag_writes"] += 1
            self._flag = bool(value)

        def SetInputData(self, _data):
            pass

        def set_color_mapper(self):
            pass

        def zoom_to_fit(self, **_kwargs):
            pass

    state = _State()

    CustomCombineImageViewers.change_local_series(state, "series_2")

    assert calls["flag_writes"] == 0


def test_sync_all_overlays_extent_skips_none_actor_and_updates_valid_actor():
    calls = {"set_extent": 0}
    base_extent = (0, 5, 0, 5, 1, 1)

    class _BaseActor:
        def GetDisplayExtent(self):
            return base_extent

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 5, 0, 5, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, None), (None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 1


def test_change_local_series_skips_redundant_metadata_assignment():
    calls = {"metadata_writes": 0}
    _output = object()
    _shared_metadata = {"series": {"series_number": 2}}

    class _Reslice:
        metadata = _shared_metadata

        def GetOutput(self):
            return _output

    class _State:
        def __init__(self):
            self.image_reslice = None
            self.image_reslice_1 = SimpleNamespace(GetOutput=lambda: object(), metadata={})
            self.image_reslice_2 = _Reslice()
            self._metadata = _shared_metadata
            self.vtk_image_data = None
            self.flag_set_custom_window_level = False
            self.image_render_window = SimpleNamespace(Render=lambda: None)

        @property
        def metadata(self):
            return self._metadata

        @metadata.setter
        def metadata(self, value):
            calls["metadata_writes"] += 1
            self._metadata = value

        def SetInputData(self, _data):
            pass

        def set_color_mapper(self):
            pass

        def zoom_to_fit(self, **_kwargs):
            pass

    state = _State()

    CustomCombineImageViewers.change_local_series(state, "series_2")

    assert calls["metadata_writes"] == 0


def test_change_local_series_skips_redundant_vtk_image_data_assignment():
    calls = {"vtk_image_writes": 0}
    _output = object()

    class _Reslice:
        metadata = {"series": {"series_number": 2}}

        def GetOutput(self):
            return _output

    class _State:
        def __init__(self):
            self.image_reslice = None
            self.image_reslice_1 = SimpleNamespace(GetOutput=lambda: object(), metadata={})
            self.image_reslice_2 = _Reslice()
            self._vtk_image_data = _output
            self.metadata = self.image_reslice_2.metadata
            self.flag_set_custom_window_level = False
            self.image_render_window = SimpleNamespace(Render=lambda: None)

        @property
        def vtk_image_data(self):
            return self._vtk_image_data

        @vtk_image_data.setter
        def vtk_image_data(self, value):
            calls["vtk_image_writes"] += 1
            self._vtk_image_data = value

        def SetInputData(self, _data):
            pass

        def set_color_mapper(self):
            pass

        def zoom_to_fit(self, **_kwargs):
            pass

    state = _State()

    CustomCombineImageViewers.change_local_series(state, "series_2")

    assert calls["vtk_image_writes"] == 0


def test_sync_all_overlays_extent_returns_when_base_extent_none():
    calls = {"set_extent": 0}

    class _BaseActor:
        def GetDisplayExtent(self):
            return None

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 0


def test_sync_all_overlays_extent_skips_actor_without_extent_api():
    calls = {"set_extent": 0}
    base_extent = (0, 3, 0, 3, 1, 1)

    class _BaseActor:
        def GetDisplayExtent(self):
            return base_extent

    class _NoExtentApiActor:
        pass

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 3, 0, 3, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, _NoExtentApiActor()), (None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 1


def test_sync_all_overlays_extent_returns_when_base_actor_none():
    calls = {"set_extent": 0}

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, _OverlayActor())],
        GetImageActor=lambda: None,
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_skips_actor_without_extent_api():
    class _Reslice:
        def GetOutput(self):
            return object()

    class _ActorNoExtentApi:
        pass

    class _VtkImageData:
        def GetDimensions(self):
            return (8, 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _ActorNoExtentApi(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    # Contract: missing extent API should be a no-op, not an exception path.
    ImageViewer2D._update_overlay_extent(state)


def test_sync_all_overlays_extent_returns_when_base_extent_malformed():
    calls = {"set_extent": 0}

    class _BaseActor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1)

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=[(None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_reslice_missing():
    calls = {"set_extent": 0}

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return (8, 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": None},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_dimensions_malformed():
    calls = {"set_extent": 0}

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return (8, 6)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_dimensions_non_positive():
    calls = {"set_extent": 0}

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return (0, 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_slice_invalid():
    calls = {"set_extent": 0}

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return (8, 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: None,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_dimensions_not_int_like():
    calls = {"set_extent": 0}

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    class _VtkImageData:
        def GetDimensions(self):
            return ("bad", 6, 10)

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=_VtkImageData(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_update_overlay_extent_returns_when_base_image_missing_dimensions_api():
    calls = {"set_extent": 0}

    class _Reslice:
        def GetOutput(self):
            return object()

    class _Actor:
        def GetDisplayExtent(self):
            return (0, 1, 0, 1, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlay={"actor": _Actor(), "reslice": _Reslice()},
        vtk_image_data=object(),
        GetSlice=lambda: 2,
    )

    ImageViewer2D._update_overlay_extent(state)

    assert calls["set_extent"] == 0


def test_sync_all_overlays_extent_skips_malformed_overlay_entries():
    calls = {"set_extent": 0}
    base_extent = (0, 3, 0, 3, 1, 1)

    class _BaseActor:
        def GetDisplayExtent(self):
            return base_extent

    class _OverlayActor:
        def GetDisplayExtent(self):
            return (0, 3, 0, 3, 0, 0)

        def SetDisplayExtent(self, *_args):
            calls["set_extent"] += 1

    state = SimpleNamespace(
        _overlays=["bad-entry", (None, None, _OverlayActor())],
        GetImageActor=lambda: _BaseActor(),
    )

    ImageViewer2D._sync_all_overlays_extent(state)

    assert calls["set_extent"] == 1


def test_clear_all_overlays_skips_malformed_entries_and_removes_valid_actor():
    calls = {"remove_actor": 0, "clear_overlay": 0}
    valid_actor = object()

    class _Renderer:
        def RemoveActor(self, actor):
            if actor is valid_actor:
                calls["remove_actor"] += 1

    state = SimpleNamespace(
        _overlays=["bad-entry", (None, None, valid_actor)],
        orientation_markers={"k": "v"},
        GetRenderer=lambda: _Renderer(),
        clear_overlay=lambda: calls.__setitem__("clear_overlay", calls["clear_overlay"] + 1),
    )

    ImageViewer2D.clear_all_overlays(state)

    assert calls["remove_actor"] == 1
    assert state._overlays == []
    assert state.orientation_markers == {}
    assert calls["clear_overlay"] == 1
