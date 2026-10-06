"""Actual decoder order, not InstanceNumber, owns the MPR anatomical axes.

All DICOMs and pixels are synthetic. No application, PACS or database is opened.
"""
import itertools
from unittest.mock import patch

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, MRImageStorage, ExplicitVRLittleEndian, generate_uid
from vtkmodules.util.numpy_support import vtk_to_numpy

from PacsClient.pacs.patient_tab.utils.image_io import get_itk_image
from PacsClient.pacs.patient_tab.utils.utils import convert_itk2vtk
from modules.mpr.zeta_mpr import _mpr_canonicalize as canonical
from modules.mpr.zeta_mpr.mpr_viewer._mpr_orientation import _MprOrientationMixin


def write_stack(folder, *, modality="CT", row=(1, 0, 0), col=(0, 1, 0), count=5):
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    normal = np.cross(row, col)
    paths = []
    for k in range(count):
        sop_class = CTImageStorage if modality == "CT" else MRImageStorage
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = sop_class
        meta.MediaStorageSOPInstanceUID = generate_uid()
        path = folder / f"slice-{k}.dcm"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.SOPClassUID, ds.SOPInstanceUID = sop_class, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.Modality, ds.PatientPosition, ds.InstanceNumber = modality, "HFS", k + 1
        ds.ImageOrientationPatient = list(row) + list(col)
        ds.ImagePositionPatient = (np.array([11., -22., 33.]) + normal * k * 2.5).tolist()
        ds.PixelSpacing = [1.2, .7]
        ds.Rows, ds.Columns = 8, 10
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.PixelRepresentation, ds.SamplesPerPixel = 1, 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = (np.arange(80, dtype=np.int16).reshape(8, 10) + k * 100).tobytes()
        ds.save_as(path, write_like_original=False)
        paths.append(str(path))
    return paths


def anatomy(image):
    values = image.GetFieldData().GetArray("ZetaAnatA")
    assert values is not None
    return vtk_to_numpy(values).reshape(3, 3)


@pytest.mark.parametrize("modality", ["CT", "MR"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("row,col", [
    ((1, 0, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, -1)), ((1, 0, 0), (0, 0, -1)),
])
def test_actual_decoded_order_controls_all_anatomical_views(tmp_path, modality, reverse, row, col):
    paths = write_stack(tmp_path, modality=modality, row=row, col=col)
    ordered = paths[::-1] if reverse else paths
    volume = convert_itk2vtk(get_itk_image(ordered))
    original_pixels = vtk_to_numpy(volume.GetPointData().GetScalars()).copy()
    expected = np.column_stack((-np.array(row), -np.array(col), np.cross(row, col) * (-1 if reverse else 1)))
    with patch.object(canonical, "probe", lambda *_: None):
        output = canonical.canonicalize_volume(volume, str(tmp_path))
    np.testing.assert_allclose(anatomy(output), expected, atol=1e-10)
    viewer = _MprOrientationMixin()
    viewer._anat_A, viewer.center = anatomy(output), volume.GetCenter()
    for view, (_, up_target, right_target) in viewer._ANAT_PLANE_TARGETS.items():
        pos, focal, up = map(np.asarray, viewer._anatomical_camera(view))
        assert (expected @ up) @ up_target > 0
        assert (expected @ np.cross(focal - pos, up)) @ right_target > 0
    np.testing.assert_array_equal(vtk_to_numpy(output.GetPointData().GetScalars()), original_pixels)
    assert output.GetSpacing() == volume.GetSpacing()
    assert output.GetOrigin() == volume.GetOrigin()
    assert output.GetExtent() == volume.GetExtent()


def test_renumbering_or_removing_source_files_cannot_reorient_built_volume(tmp_path):
    paths = write_stack(tmp_path)
    volume = convert_itk2vtk(get_itk_image(paths))
    with patch.object(canonical, "probe", lambda *_: None):
        expected = anatomy(canonical.canonicalize_volume(volume, str(tmp_path))).copy()
        for i, path in enumerate(paths):
            ds = pydicom.dcmread(path)
            ds.InstanceNumber = len(paths) - i
            ds.save_as(path, write_like_original=False)
        np.testing.assert_array_equal(anatomy(canonical.canonicalize_volume(volume, str(tmp_path))), expected)
        np.testing.assert_array_equal(anatomy(canonical.canonicalize_volume(volume, None)), expected)


@pytest.mark.parametrize("modality", ["CT", "MR"])
def test_filters_and_disk_and_ipc_preserve_receipt_and_pixels(tmp_path, modality):
    from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import values_from_vtk, geometry_status
    from modules.zeta_boost.disk_cache import ZetaBoostDiskCache
    from modules.zeta_boost.warmup_subprocess import WarmupResult, result_to_vtk
    paths = write_stack(tmp_path, modality=modality)
    source = get_itk_image(paths[::-1])
    settings = tmp_path / "filters.json"
    settings.write_text('{}')
    filtered = apply_filters(source, {"series": {"modality": modality}}, settings, max_itk_threads=1)
    volume = convert_itk2vtk(filtered)
    assert geometry_status(volume) == "valid"
    pixels = vtk_to_numpy(volume.GetPointData().GetScalars()).copy()
    receipt = values_from_vtk(volume)
    assert receipt == values_from_vtk(convert_itk2vtk(source))
    cache = ZetaBoostDiskCache.__new__(ZetaBoostDiskCache)
    cache._write_payload(tmp_path / "volume.npz", tmp_path / "volume.json", volume, {})
    restored, _ = cache._read_payload(tmp_path / "volume.npz", tmp_path / "volume.json")
    warm = WarmupResult(series_number="1", success=True, numpy_array=pixels,
                        dimensions=volume.GetDimensions(), spacing=volume.GetSpacing(),
                        origin=volume.GetOrigin(), mpr_stack_geometry=receipt,
                        direction=tuple(vtk_to_numpy(volume.GetFieldData().GetArray("DirectionMatrix"))))
    ipc, _ = result_to_vtk(warm)
    import vtkmodules.all as vtk
    copied = vtk.vtkImageData()
    copied.ShallowCopy(volume)
    from modules.mpr.zeta_mpr.mpr_volume_prep import prepare_radiological_volume
    flipped = prepare_radiological_volume(volume)
    assert values_from_vtk(flipped) == receipt
    for result in (restored, ipc, copied):
        assert geometry_status(result) == "valid"
        assert values_from_vtk(result) == receipt
        np.testing.assert_array_equal(vtk_to_numpy(result.GetPointData().GetScalars()), pixels)


@pytest.mark.parametrize("defect", ["irregular", "repeated_position", "mixed_series", "varying_plane", "missing_ipp", "shear"])
def test_inconsistent_stack_has_explicit_invalid_receipt(tmp_path, defect):
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import geometry_status
    paths = write_stack(tmp_path)
    ds = pydicom.dcmread(paths[2])
    if defect == "irregular":
        ds.ImagePositionPatient[2] += .5
    elif defect == "repeated_position":
        ds.ImagePositionPatient = pydicom.dcmread(paths[1]).ImagePositionPatient
    elif defect == "mixed_series":
        ds.SeriesInstanceUID = generate_uid()
    elif defect == "varying_plane":
        ds.ImageOrientationPatient = [0, 1, 0, 1, 0, 0]
    elif defect == "missing_ipp":
        del ds.ImagePositionPatient
    elif defect == "shear":
        for k, path in enumerate(paths):
            shifted = pydicom.dcmread(path)
            shifted.ImagePositionPatient[0] += k * .5
            shifted.save_as(path, write_like_original=False)
    if defect != "shear":
        ds.save_as(paths[2], write_like_original=False)
    image = convert_itk2vtk(get_itk_image(paths))
    assert geometry_status(image) == "invalid"


def test_stale_grid_is_rejected(tmp_path):
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import geometry_status
    image = convert_itk2vtk(get_itk_image(write_stack(tmp_path)))
    image.SetSpacing(1, 1, 1)
    assert geometry_status(image) == "invalid"


@pytest.mark.parametrize("path", ["orthogonal", "curved"])
def test_legacy_cached_volume_rebuilds_once_without_guessing(tmp_path, path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import FIELD_NAME
    import vtkmodules.all as vtk
    fresh = convert_itk2vtk(get_itk_image(write_stack(tmp_path)))
    legacy = vtk.vtkImageData()
    legacy.DeepCopy(fresh)
    legacy.GetFieldData().RemoveArray(FIELD_NAME)
    state = SimpleNamespace(_emit_mpr_launch_route=Mock(), _load_full_vtk_for_mpr=Mock(return_value=fresh))
    with patch('PacsClient.utils.vtk_volume_service.build_or_get_mpr_volume', side_effect=AssertionError('legacy cache must be bypassed')):
        result, route = ToolbarManager._resolve_mpr_volume_for_route(state,
            series_data={"vtk_image_data": legacy, "metadata": {"series": {"viewer_backend": "vtk_simpleitk"}}},
            series_number="1", mpr_path=path)
    assert result is fresh
    assert state._load_full_vtk_for_mpr.call_count == 1
    assert route["reason"] == "loaded_full_volume"


def test_rebuild_without_valid_geometry_stops_without_retry_loop(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import FIELD_NAME
    volume = convert_itk2vtk(get_itk_image(write_stack(tmp_path)))
    volume.GetFieldData().RemoveArray(FIELD_NAME)
    state = SimpleNamespace(_emit_mpr_launch_route=Mock(), _load_full_vtk_for_mpr=Mock(return_value=volume))
    result, route = ToolbarManager._resolve_mpr_volume_for_route(state,
        series_data={"vtk_image_data": volume, "metadata": {"series": {"viewer_backend": "vtk_simpleitk"}}},
        series_number="1", mpr_path="orthogonal")
    assert result is None and route["reason"] == "invalid_buffer_geometry"
    assert state._load_full_vtk_for_mpr.call_count == 1


def orientation_cases():
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            basis = np.eye(3)[:, permutation] @ np.diag(signs)
            if np.linalg.det(basis) < 0:
                continue
            for angle in (0, 17):
                theta = np.deg2rad(angle)
                rotation = np.array([[1, 0, 0], [0, np.cos(theta), -np.sin(theta)], [0, np.sin(theta), np.cos(theta)]])
                axes = rotation @ basis
                for reverse in (False, True):
                    yield axes[:, 0], axes[:, 1], reverse


@pytest.mark.parametrize("row,col,reverse", list(orientation_cases()))
def test_signed_and_oblique_acquisitions_preserve_working_camera_rule(tmp_path, row, col, reverse):
    paths = write_stack(tmp_path, modality="MR", row=row, col=col)
    image = convert_itk2vtk(get_itk_image(paths[::-1] if reverse else paths))
    with patch.object(canonical, "probe", lambda *_: None):
        output = canonical.canonicalize_volume(image, str(tmp_path))
    expected = np.column_stack((-row, -col, np.cross(row, col) * (-1 if reverse else 1)))
    np.testing.assert_allclose(anatomy(output), expected, atol=1e-8)
    old, new = _MprOrientationMixin(), _MprOrientationMixin()
    old._anat_A, new._anat_A = expected, anatomy(output)
    old.center = new.center = image.GetCenter()
    for view in ("axial", "sagittal", "coronal"):
        # Exact camera equality to the existing rule with correct input axes.
        np.testing.assert_array_equal(old._anatomical_camera(view), new._anatomical_camera(view))


def test_warmup_worker_exports_build_receipt(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import image_io
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import values_from_vtk
    from modules.zeta_boost.warmup_subprocess import WarmupRequest, _load_series_in_subprocess
    image = convert_itk2vtk(get_itk_image(write_stack(tmp_path)[::-1]))
    monkeypatch.setattr(image_io, "load_single_series_by_number", lambda **_: iter([(image, {}, (None, None))]))
    request = WarmupRequest(study_path=str(tmp_path), series_number="1")
    result = _load_series_in_subprocess(request)
    assert result.success
    assert result.mpr_stack_geometry == values_from_vtk(image)


def test_explicit_legacy_kill_switch_keeps_existing_route(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import FIELD_NAME
    image = convert_itk2vtk(get_itk_image(write_stack(tmp_path)))
    image.GetFieldData().RemoveArray(FIELD_NAME)
    monkeypatch.setenv("AIPACS_ZETA_MPR_CANONICALIZE", "0")
    state = SimpleNamespace(_emit_mpr_launch_route=Mock())
    result, route = ToolbarManager._resolve_mpr_volume_for_route(state,
        series_data={"vtk_image_data": image, "metadata": {"series": {"viewer_backend": "vtk_simpleitk"}}},
        series_number="1", mpr_path="orthogonal")
    assert result is image and route["reason"] == "using_existing_volume"


@pytest.mark.parametrize("cached", [False, True])
def test_fast_route_missing_receipt_is_rebuilt_at_most_once(tmp_path, monkeypatch, cached):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    from PacsClient.pacs.patient_tab.utils.mpr_stack_geometry import FIELD_NAME
    import PacsClient.utils.vtk_volume_service as service
    image = convert_itk2vtk(get_itk_image(write_stack(tmp_path)))
    image.GetFieldData().RemoveArray(FIELD_NAME)
    def cached_or_build(study, series, factory, **kwargs):
        return image if cached else factory()
    monkeypatch.setattr(service, 'build_or_get_mpr_volume', cached_or_build)
    state = SimpleNamespace(_emit_mpr_launch_route=Mock(), _load_full_vtk_for_mpr=Mock(return_value=image))
    result, route = ToolbarManager._resolve_mpr_volume_for_route(state,
        series_data={"vtk_image_data": image, "metadata": {"series": {"viewer_backend": "pydicom_qt"}}},
        series_number="1", mpr_path="orthogonal")
    assert result is None and route["reason"] == "invalid_buffer_geometry"
    assert state._load_full_vtk_for_mpr.call_count == 1
