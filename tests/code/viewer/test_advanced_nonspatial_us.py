"""Synthetic single-frame US must display without fabricated patient geometry."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, UltrasoundImageStorage


def write_us(path, number, **overrides):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    values = dict(Modality="US", SOPClassUID=UltrasoundImageStorage,
                  SOPInstanceUID=f"1.2.826.0.1.3680043.10.999.3.{number}",
                  StudyInstanceUID="1.2.826.0.1.3680043.10.999.1",
                  SeriesInstanceUID="1.2.826.0.1.3680043.10.999.2",
                  SeriesNumber=1, InstanceNumber=number, Rows=8, Columns=10,
                  SamplesPerPixel=3, PhotometricInterpretation="RGB",
                  PlanarConfiguration=0, BitsAllocated=8, BitsStored=8,
                  HighBit=7, PixelRepresentation=0)
    values.update(overrides)
    for key, value in values.items():
        setattr(ds, key, value)
    ds.PixelData = np.full((8, 10, 3), number * 30, dtype=np.uint8).tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(path, write_like_original=False)
    return str(path)


def test_us_loader_preserves_frame_order_rgb_and_absent_geometry(tmp_path):
    from PacsClient.pacs.patient_tab.utils import image_io
    from vtkmodules.util.numpy_support import vtk_to_numpy
    files = [write_us(tmp_path / f"{n}.dcm", n) for n in (3, 1, 2)]
    plan, _ = image_io._get_or_build_series_geometry_index(files, source="test")
    metadata = {"series": {"orientation": [1, 0, 0, 0, 1, 0]}}
    image_io._apply_geometry_index_metadata(metadata, plan)
    assert metadata["spatial_geometry_available"] is False
    assert "series_geometry_index" not in metadata
    assert metadata["series"]["orientation"] is None
    assert [x["instance_number"] for x in metadata["instances"]] == [1, 2, 3]
    assert all(x.get("image_position_patient") is None for x in metadata["instances"])
    image = image_io.utils.convert_itk2vtk(image_io.get_itk_image(plan.dicom_files_for_itk))
    assert image.GetDimensions() == (10, 8, 3)
    pixels = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(3, 8, 10, 3)
    assert [int(frame[0, 0, 0]) for frame in pixels] == [30, 60, 90]


@pytest.mark.parametrize("overrides", [
    {"Modality": "CT"},
    {"SeriesInstanceUID": "1.2.826.0.1.3680043.10.999.99"},
    {"StudyInstanceUID": "1.2.826.0.1.3680043.10.999.99"},
    {"ImagePositionPatient": [0, 0, 0]},
    {"NumberOfFrames": 2},
])
def test_nonspatial_fallback_rejects_mixed_or_unsupported_input(tmp_path, overrides):
    from PacsClient.pacs.patient_tab.utils import image_io
    files = [write_us(tmp_path / "1.dcm", 1),
             write_us(tmp_path / "2.dcm", 2, **overrides)]
    with pytest.raises(ValueError):
        image_io._get_or_build_series_geometry_index(files, source="test")


def test_switch_to_nonspatial_clears_previous_viewport_geometry():
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    state = SimpleNamespace(metadata={"spatial_geometry_available": False},
                            _source_geometry_contract=object(),
                            _display_geometry_contract=object(),
                            _viewer_viewport_id=lambda: "synthetic-us-viewport",
                            orientation_markers=SimpleNamespace(clear=Mock()))
    registry = ImageViewer2D._viewport_geometry_registry
    registry.register("synthetic-us-viewport", object())
    try:
        ImageViewer2D._bind_geometry_contract(state)
        assert state._display_geometry_contract is None
        assert state._source_geometry_contract is None
        assert registry.get("synthetic-us-viewport") is None
        state.orientation_markers.clear.assert_called_once()
    finally:
        registry.unregister("synthetic-us-viewport")


def test_rgb_switch_does_not_inherit_ct_window_level():
    import vtkmodules.all as vtk
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    from modules.viewer.advanced.viewer_2d import ImageReslice, ImageViewer2D
    pixels = np.array([[20, 80, 220], [240, 30, 100]], dtype=np.uint8)
    image = vtk.vtkImageData()
    image.SetDimensions(2, 1, 1)
    image.GetPointData().SetScalars(numpy_to_vtk(pixels, deep=True))
    mapper = vtk.vtkImageMapToWindowLevelColors()
    mapper.SetWindow(400)
    mapper.SetLevel(40)
    state = SimpleNamespace(color_mapper=mapper,
                            image_reslice=ImageReslice(image, {}))
    ImageViewer2D.set_color_mapper(state)
    mapper.Update()
    actual = vtk_to_numpy(mapper.GetOutput().GetPointData().GetScalars())
    np.testing.assert_array_equal(actual[:, :3], pixels)


def test_filesystem_us_loader_returns_all_frames(tmp_path):
    from PacsClient.pacs.patient_tab.utils import image_io
    folder = tmp_path / "1"
    folder.mkdir()
    for number in (2, 1, 3):
        write_us(folder / f"{number}.dcm", number)
    result = image_io._load_series_from_filesystem(tmp_path, 1)
    assert result is not None
    image, metadata, _ = result
    assert image.GetDimensions() == (10, 8, 3)
    assert metadata["spatial_geometry_available"] is False
    assert len(metadata["instances"]) == 3


@pytest.mark.parametrize("route_name", ["orthogonal", "dental", "projection"])
def test_mpr_does_not_reconstruct_unrelated_us_frames(route_name):
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    volume = SimpleNamespace(GetPointData=lambda: SimpleNamespace(GetScalars=lambda: object()))
    state = SimpleNamespace(_emit_mpr_launch_route=Mock())
    data, route = ToolbarManager._resolve_mpr_volume_for_route(
        state, series_data={"metadata": {"spatial_geometry_available": False},
                            "vtk_image_data": volume},
        series_number="1", mpr_path=route_name,
    )
    assert data is None
    assert route["reason"] == "nonspatial_frame_sequence"


def test_nonspatial_viewer_cannot_enable_curved_mpr():
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    state = SimpleNamespace(metadata={"spatial_geometry_available": False},
                            curved_mpr_mode=False, curved_mpr_module=Mock(),
                            vtk_image_data=object(), _clear_curved_mpr_visuals=Mock(),
                            _show_curved_mpr_overlay=Mock(), curved_mpr_observer_id=1,
                            Render=Mock())
    ImageViewer2D.enable_curved_mpr_mode(state, True)
    assert state.curved_mpr_mode is False


def test_nonspatial_scroll_keeps_raw_frame_order_and_hides_markers():
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    state = SimpleNamespace(
        raw_k=0, _display_geometry_contract=None,
        metadata={"spatial_geometry_available": False, "instances": [{}, {}, {}]},
        orientation_markers=SimpleNamespace(clear=Mock()),
        flag_set_custom_window_level=True, _overlays=[],
        _last_fast_annotation_update_ms=0.0, _last_fast_overlay_sync_ms=0.0,
        _fast_corner_overlay_interval_ms=100.0,
        update_corners_actors=Mock(), _sync_all_overlays_extent=Mock(), Render=Mock(),
        _emit_orientation_audit_active=Mock(), _emit_advanced_vtk_orientation_audit=Mock(),
        _emit_axial_stack_order_policy_audit=Mock(), _emit_mg_parity_trace=Mock(),
    )
    state.SetSlice = lambda k: setattr(state, "raw_k", k)
    state.GetSlice = lambda: state.raw_k
    state._prepare_slice_visuals = lambda *args: ImageViewer2D._prepare_slice_visuals(state, *args)
    for frame in (0, 1, 2, 1, 0):
        ImageViewer2D._set_slice_impl(state, frame, fast_interaction=False, force_annotations=False)
        assert ImageViewer2D.get_display_slice(state) == frame
    assert state.orientation_markers.clear.call_count == 5


def test_grouped_us_loader_uses_same_order_without_database_access(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import image_io
    from PacsClient.utils import data_paths
    from database.core import cleanup_connection_pools
    cleanup_connection_pools()
    monkeypatch.setattr(data_paths, "DATABASE_FILE", tmp_path / "test-only.db")
    monkeypatch.setattr(image_io, "get_db_connection", Mock(side_effect=AssertionError("Unexpected DB access")))
    monkeypatch.setattr(image_io.utils, "get_or_create_series", Mock(return_value=1))
    monkeypatch.setattr(image_io.utils, "get_or_create_instance", Mock())
    monkeypatch.setattr(image_io, "get_instances_by_series_pk", Mock(return_value=[]))
    monkeypatch.setattr(image_io, "_get_cached_metadata", Mock(return_value={"series": {}}))
    files = [write_us(tmp_path / f"{n}.dcm", n) for n in (3, 1, 2)]
    try:
        loaded = list(image_io.process_series_groups(tmp_path, {(8, 10): files}, 1, 1))
        assert len(loaded) == 1
        image, metadata, _ = loaded[0]
        assert image.GetDimensions() == (10, 8, 3)
        assert [x["instance_number"] for x in metadata["instances"]] == [1, 2, 3]
        assert metadata["spatial_geometry_available"] is False
        image_io.get_db_connection.assert_not_called()
    finally:
        cleanup_connection_pools()


def test_db_metadata_route_preserves_us_frames(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import image_io
    from PacsClient.utils import data_paths, database
    from database.core import cleanup_connection_pools
    cleanup_connection_pools()
    monkeypatch.setattr(data_paths, "DATABASE_FILE", tmp_path / "test-only.db")
    folder = tmp_path / "1"
    folder.mkdir()
    files = [write_us(folder / f"{n}.dcm", n) for n in (3, 1, 2)]
    instances = [{"instance_path": path} for path in files]
    monkeypatch.setattr(database, "find_series_pk_by_number", Mock(return_value=1))
    monkeypatch.setattr(image_io, "get_instances_by_series_pk", Mock(return_value=instances))
    monkeypatch.setattr(image_io, "_get_cached_metadata", Mock(return_value={
        "series": {"series_number": "1"}, "instances": instances}))
    monkeypatch.setattr(image_io, "get_db_connection", Mock(side_effect=AssertionError("Unexpected DB access")))
    monkeypatch.setattr(image_io, "_load_series_from_filesystem", Mock(return_value=None))
    monkeypatch.setattr(image_io, "process_series_groups", Mock(return_value=iter(())))
    try:
        loaded = list(image_io.load_single_series_by_number(
            tmp_path, 1, patient_pk=1, study_pk=1,
            viewer_backend=image_io.BACKEND_VTK, allow_lazy_backend=False))
        assert len(loaded) == 1
        image, metadata, _ = loaded[0]
        assert image.GetDimensions() == (10, 8, 3)
        assert [x["instance_number"] for x in metadata["instances"]] == [1, 2, 3]
        assert metadata["spatial_geometry_available"] is False
        image_io._load_series_from_filesystem.assert_not_called()
        image_io.process_series_groups.assert_not_called()
        image_io.get_db_connection.assert_not_called()
    finally:
        cleanup_connection_pools()


def test_preambleless_us_is_still_eligible(tmp_path):
    from PacsClient.pacs.patient_tab.utils import image_io
    path = tmp_path / "1.dcm"
    write_us(path, 1)
    path.write_bytes(path.read_bytes()[132:])
    plan, _ = image_io._get_or_build_series_geometry_index([str(path)], source="test")
    metadata = image_io._apply_geometry_index_metadata({"series": {}}, plan)
    assert metadata["spatial_geometry_available"] is False
    assert len(metadata["instances"]) == 1
