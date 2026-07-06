from __future__ import annotations

from types import SimpleNamespace

from modules.EchoMind.secretary.adapters.viewer_write_adapter import (
    ViewerWriteCommandAdapter,
)
from modules.EchoMind.secretary.command_envelope import CommandPlan
from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.store import ToolStore


class _Spinner:
    def show_loading(self, _text: str) -> None:
        pass


class _Vtk:
    id_vtk_widget = "ut"

    def __init__(self) -> None:
        self.viewport_spinner = _Spinner()
        self.calls = []
        self.image_viewer = SimpleNamespace(
            metadata={"series": {"series_number": "101"}, "preview_only": False},
            metadata_fixed={"patient_id": "PID"},
        )

    def method_change_series_on_viewer(self, **kwargs) -> None:
        self.calls.append(kwargs)

    def get_count_of_slices(self) -> int:
        return 7


def _tab():
    vtk = _Vtk()
    tab = SimpleNamespace(
        study_uid="STUDY",
        lst_nodes_viewer=[SimpleNamespace(vtk_widget=vtk, slider=None)],
        _server_series_info={
            "101": {
                "series_uid": "UID101",
                "image_count": 5,
                "series_description": "first",
            },
            "205": {
                "series": {
                    "series_uid": "UID205",
                    "image_count": 9,
                    "series_description": "second",
                }
            },
        },
    )
    return tab, vtk


def _run(adapter: ViewerWriteCommandAdapter, entities: dict):
    return adapter.change_series(
        CommandPlan(action="change_series", entities=entities), {})


def test_change_series_accepts_series_number_directly():
    tab, vtk = _tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = _run(adapter, {"series_number": 101, "viewport": 0})

    assert result.ok is True
    assert result.data["series_number"] == 101
    assert vtk.calls[-1]["series_index"] == 101


def test_change_series_resolves_zero_based_series_index():
    tab, vtk = _tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = _run(adapter, {"series_index": 1, "viewport": 0})

    assert result.ok is True
    assert result.data["series_number"] == 205
    assert vtk.calls[-1]["series_index"] == 205


def test_change_series_resolves_series_uid():
    tab, vtk = _tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = _run(adapter, {"series_uid": "UID205", "viewport": 0})

    assert result.ok is True
    assert result.data["series_number"] == 205
    assert vtk.calls[-1]["series_index"] == 205


def test_change_series_bad_series_index_is_typed_error():
    tab, _vtk = _tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = _run(adapter, {"series_index": 9, "viewport": 0})

    assert result.ok is False
    assert result.error_code == "BAD_SERIES_INDEX"


def test_get_series_info_includes_uid_for_followup_resolution():
    tab, _vtk = _tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = adapter.get_series_info(
        CommandPlan(action="get_series_info", entities={}), {})

    assert result.ok is True
    assert result.data["series"][0]["series_uid"] == "UID101"
    assert result.data["series"][1]["series_uid"] == "UID205"


class _Point:
    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self._x = x
        self._y = y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class _Pipeline:
    def get_slice_meta(self, slice_index: int):
        return SimpleNamespace(
            path=r"C:\dicom\image001.dcm",
            rows=100,
            cols=100,
            pixel_spacing=(0.5, 0.5),
            iop=(1, 0, 0, 0, 1, 0),
            ipp=(0, 0, float(slice_index)),
            slice_thickness=1.0,
            spacing_between_slices=1.0,
        )

    def image_xy_to_patient_xyz(self, x: float, y: float, slice_index: int):
        return (float(x) * 0.5, float(y) * 0.5, float(slice_index))


class _QtViewer:
    _zoom = 1.0
    _pan_offset = _Point()
    _rotation_angle = 0
    _flip_h = False
    _flip_v = False
    _image_width = 100
    _image_height = 100
    _display_scale_x = 1.0
    _display_scale_y = 1.0
    _current_slice_index = 3

    def __init__(self) -> None:
        self._coord_backend = _Pipeline()
        self.tool_controller = ToolController(ToolStore(), SimpleNamespace())
        self.updated = False

    def width(self) -> int:
        return 500

    def height(self) -> int:
        return 400

    def update(self) -> None:
        self.updated = True


def _fast_tab():
    tab, vtk = _tab()
    qv = _QtViewer()
    vtk._qt_viewer_widget = qv
    return tab, vtk, qv


def test_get_viewport_context_includes_dicom_geometry_and_capabilities():
    tab, _vtk, _qv = _fast_tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = adapter.get_viewport_context(
        CommandPlan(action="get_viewport_context", entities={"viewport": 0}), {})

    assert result.ok is True
    assert result.data["viewport"]["backend"] == "fast_qt"
    assert result.data["viewport"]["slice_index"] == 3
    assert result.data["slice_meta"]["pixel_spacing"] == [0.5, 0.5]
    assert result.data["slice_meta"]["path"] == "image001.dcm"
    assert result.data["capabilities"]["distance_measurement"] is True
    assert "patient_corners_lps_mm" in result.data["geometry"]


def test_measure_distance_uses_fast_tool_store_and_patient_geometry():
    tab, _vtk, qv = _fast_tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = adapter.measure_distance(
        CommandPlan(action="measure_distance", entities={
            "viewport": 0,
            "slice_index": 3,
            "points_image": [[10, 10], [16, 18]],
            "label": "orbital distance",
        }),
        {},
    )

    assert result.ok is True
    measurement = result.data["measurement"]
    assert measurement["type"] == "ruler"
    assert measurement["label_text"] == "orbital distance"
    assert measurement["distance_mm"] == 5.0
    assert qv.updated is True


def test_get_measurements_reads_current_slice_tool_store():
    tab, _vtk, _qv = _fast_tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)
    adapter.measure_distance(
        CommandPlan(action="measure_distance", entities={
            "viewport": 0,
            "points_image": [[0, 0], [0, 10]],
        }),
        {},
    )

    result = adapter.get_measurements(
        CommandPlan(action="get_measurements", entities={"viewport": 0}), {})

    assert result.ok is True
    assert result.data["slice_index"] == 3
    assert len(result.data["measurements"]) == 1
    assert result.data["measurements"][0]["distance_mm"] == 5.0


def test_measure_distance_rejects_slice_mismatch():
    tab, _vtk, _qv = _fast_tab()
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)

    result = adapter.measure_distance(
        CommandPlan(action="measure_distance", entities={
            "viewport": 0,
            "slice_index": 2,
            "points_image": [[0, 0], [1, 1]],
        }),
        {},
    )

    assert result.ok is False
    assert result.error_code == "CONTEXT_MISMATCH"
