"""Enhanced MR display uses pixel frame identity without inventing a volume."""
import numpy as np
import pydicom
import pytest
from vtkmodules.util.numpy_support import vtk_to_numpy
from tests.code.ui_services.test_local_multiframe_thumbnail_repair import make_enhanced
from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence


@pytest.mark.parametrize('extra_group', [False, True])
def test_enhanced_pixels_and_frame_order_survive_missing_geometry(tmp_path, extra_group):
    ds = make_enhanced(tmp_path / 'series')
    if extra_group:
        ds.PerFrameFunctionalGroupsSequence.insert(2, pydicom.Dataset())
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    result = load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)
    assert result is not None, 'Enhanced MR must reach Advanced frame presentation'
    _, metadata = result
    assert metadata['spatial_geometry_available'] is False
    assert [i['frame_index'] for i in metadata['instances']] == [0, 1, 2]
    frames = metadata['_advanced_presentation_frames']
    assert len(frames) == 3
    for k, image in enumerate(frames):
        actual = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(8, 8)
        np.testing.assert_array_equal(actual, ds.pixel_array[k, ::-1, :])


def test_ambiguous_extra_groups_with_different_transform_are_rejected(tmp_path):
    ds = make_enhanced(tmp_path / 'series')
    extra = pydicom.Dataset()
    transform = pydicom.Dataset(); transform.RescaleSlope = 2; transform.RescaleIntercept = 0
    extra.PixelValueTransformationSequence = pydicom.Sequence([transform])
    ds.PerFrameFunctionalGroupsSequence.insert(2, extra)
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    with pytest.raises(ValueError, match='Ambiguous'):
        load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)


def test_full_advanced_loader_routes_enhanced_before_spatial_geometry(tmp_path):
    make_enhanced(tmp_path / '1')
    from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
    result = list(load_single_series_by_number(str(tmp_path), 1, viewer_backend='vtk_simpleitk'))
    assert len(result) == 1
    assert len(result[0][1]['_advanced_presentation_frames']) == 3


def test_per_frame_rescale_is_applied_once(tmp_path):
    ds = make_enhanced(tmp_path / 'series')
    for k, group in enumerate(ds.PerFrameFunctionalGroupsSequence):
        transform = pydicom.Dataset()
        transform.RescaleSlope = k + 2
        transform.RescaleIntercept = -10
        group.PixelValueTransformationSequence = pydicom.Sequence([transform])
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    _, metadata = load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)
    for k, image in enumerate(metadata['_advanced_presentation_frames']):
        actual = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(8, 8)
        np.testing.assert_array_equal(actual, ds.pixel_array[k, ::-1, :].astype(float) * (k + 2) - 10)


def test_malformed_group_windows_are_not_assigned_to_wrong_frame(tmp_path):
    ds = make_enhanced(tmp_path / 'series')
    extra = pydicom.Dataset()
    voi = pydicom.Dataset(); voi.WindowWidth = 10000; voi.WindowCenter = 9000
    extra.FrameVOILUTSequence = pydicom.Sequence([voi])
    ds.PerFrameFunctionalGroupsSequence.insert(2, extra)
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    _, metadata = load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)
    assert [i['window_width'] for i in metadata['instances']] == [63, 63, 63]
    assert [i['window_center'] for i in metadata['instances']] == [31.5, 95.5, 159.5]


def test_memory_limit_rejects_before_decode(tmp_path, monkeypatch):
    make_enhanced(tmp_path / 'series')
    from PacsClient.pacs.patient_tab.utils import advanced_presentation as presentation
    monkeypatch.setattr(presentation, 'MAX_BYTES', 1)
    with pytest.raises(ValueError, match='memory limit'):
        load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)


def test_changed_identity_during_decode_is_rejected(tmp_path, monkeypatch):
    make_enhanced(tmp_path / 'series')
    original = pydicom.dcmread
    def changed(*args, **kwargs):
        ds = original(*args, **kwargs)
        if not kwargs.get('stop_before_pixels'):
            ds.SeriesInstanceUID = pydicom.uid.generate_uid()
        return ds
    monkeypatch.setattr(pydicom, 'dcmread', changed)
    with pytest.raises(ValueError, match='identity changed'):
        load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)


@pytest.mark.parametrize('extra_group', [False, True])
def test_frame_planes_retained_without_claiming_mpr_volume(tmp_path, extra_group):
    ds = make_enhanced(tmp_path / 'series')
    for k, group in enumerate(ds.PerFrameFunctionalGroupsSequence):
        content = pydicom.Dataset(); content.InStackPositionNumber = k + 1
        content.StackID = '1'; content.TemporalPositionIndex = 1
        group.FrameContentSequence = pydicom.Sequence([content])
    if extra_group:
        extra = pydicom.Dataset(); voi = pydicom.Dataset(); voi.WindowWidth = 100
        extra.FrameVOILUTSequence = pydicom.Sequence([voi])
        ds.PerFrameFunctionalGroupsSequence.insert(2, extra)
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    _, metadata = load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)
    assert metadata['spatial_geometry_available'] is False
    assert metadata['frame_geometry_available'] is True
    assert [i['image_position_patient'] for i in metadata['instances']] == [(0., 0., 0.), (0., 0., 1.), (0., 0., 2.)]
    assert [i['frame_index'] for i in metadata['instances']] == [0, 1, 2]


def test_ambiguous_spatial_group_numbers_do_not_get_guessed(tmp_path):
    ds = make_enhanced(tmp_path / 'series')
    for group in ds.PerFrameFunctionalGroupsSequence:
        content = pydicom.Dataset(); content.InStackPositionNumber = 1
        group.FrameContentSequence = pydicom.Sequence([content])
    extra = pydicom.Dataset(); voi = pydicom.Dataset(); voi.WindowWidth = 100
    extra.FrameVOILUTSequence = pydicom.Sequence([voi])
    ds.PerFrameFunctionalGroupsSequence.insert(2, extra)
    ds.save_as(tmp_path / 'series/image.dcm', write_like_original=False)
    _, metadata = load_presentation_sequence([tmp_path / 'series/image.dcm'], series_number=1)
    assert not metadata['frame_geometry_available']
    assert all(i['image_position_patient'] is None for i in metadata['instances'])
