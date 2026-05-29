import copy

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager


class _PointData:
    def __init__(self, scalars):
        self._scalars = scalars

    def GetScalars(self):
        return self._scalars


class _VtkData:
    def __init__(self, scalars):
        self._point_data = _PointData(scalars)

    def GetPointData(self):
        return self._point_data


def _make_toolbar_stub():
    toolbar = ToolbarManager.__new__(ToolbarManager)
    toolbar.patient_widget = type("PatientWidgetStub", (), {"study_uid": "study-001"})()
    toolbar._events = []

    def _emit(**kwargs):
        toolbar._events.append(kwargs)

    toolbar._emit_mpr_launch_route = _emit
    return toolbar


def test_fast_route_loads_full_volume_and_logs_route_ready():
    toolbar = _make_toolbar_stub()
    full_vtk = _VtkData(scalars=object())
    calls = {}

    def _load_full_vtk_for_mpr(series_number, preferred_series_path=None):
        calls["series_number"] = series_number
        calls["preferred_series_path"] = preferred_series_path
        return full_vtk

    toolbar._load_full_vtk_for_mpr = _load_full_vtk_for_mpr

    series_data = {
        "vtk_image_data": _VtkData(scalars=None),
        "metadata": {
            "series": {
                "viewer_backend": "pydicom_qt",
                "series_path": "C:/dicom/study/12",
            },
            "instances": [
                {"instance_number": 5},
                {"instance_number": 1},
                {"instance_number": 3},
            ],
        },
    }

    before_instances = copy.deepcopy(series_data["metadata"]["instances"])

    vtk_data, route = ToolbarManager._resolve_mpr_volume_for_route(
        toolbar,
        series_data=series_data,
        series_number="12",
        mpr_path="orthogonal",
    )

    assert vtk_data is full_vtk
    assert route["source_backend"] == "pydicom_qt"
    assert route["reason"] == "loaded_full_volume"
    assert calls == {
        "series_number": "12",
        "preferred_series_path": "C:/dicom/study/12",
    }
    assert series_data["metadata"]["instances"] == before_instances
    assert toolbar._events[-1]["status"] == "route_ready"
    assert toolbar._events[-1]["mpr_path"] == "orthogonal"


def test_fast_route_blocks_when_full_volume_cannot_be_loaded():
    toolbar = _make_toolbar_stub()
    toolbar._load_full_vtk_for_mpr = lambda series_number, preferred_series_path=None: None

    series_data = {
        "vtk_image_data": _VtkData(scalars=None),
        "metadata": {
            "series": {
                "viewer_backend": "pydicom_qt",
                "series_path": "C:/dicom/study/88",
            }
        },
    }

    vtk_data, route = ToolbarManager._resolve_mpr_volume_for_route(
        toolbar,
        series_data=series_data,
        series_number="88",
        mpr_path="orthogonal",
    )

    assert vtk_data is None
    assert route["source_backend"] == "pydicom_qt"
    assert route["reason"] == "full_volume_load_failed"
    assert toolbar._events[-1]["status"] == "blocked"
    assert toolbar._events[-1]["reason"] == "full_volume_load_failed"


def test_advanced_route_uses_existing_vtk_without_fallback_load():
    toolbar = _make_toolbar_stub()

    def _must_not_load(*_args, **_kwargs):
        raise AssertionError("_load_full_vtk_for_mpr must not be called for valid advanced volume")

    toolbar._load_full_vtk_for_mpr = _must_not_load
    existing_vtk = _VtkData(scalars=object())

    series_data = {
        "vtk_image_data": existing_vtk,
        "metadata": {
            "series": {
                "viewer_backend": "vtk_simpleitk",
                "series_path": "C:/dicom/study/5",
            }
        },
    }

    vtk_data, route = ToolbarManager._resolve_mpr_volume_for_route(
        toolbar,
        series_data=series_data,
        series_number="5",
        mpr_path="curved",
    )

    assert vtk_data is existing_vtk
    assert route["source_backend"] == "vtk_simpleitk"
    assert route["reason"] == "using_existing_volume"
    assert toolbar._events[-1]["status"] == "route_ready"
    assert toolbar._events[-1]["mpr_path"] == "curved"


def test_block_message_maps_to_real_failure_reasons():
    assert "no image volume data" in ToolbarManager._mpr_route_block_message("no_vtk_data").lower()
    assert "full decoded volume" in ToolbarManager._mpr_route_block_message("full_volume_load_failed").lower()
