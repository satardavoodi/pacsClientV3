"""Synthetic local-import thumbnails must not require a spatial viewer volume."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    ExplicitVRLittleEndian,
    EnhancedMRImageStorage,
    DigitalMammographyXRayImageStorageForPresentation,
    MRImageStorage,
    UltrasoundImageStorage,
    generate_uid,
)


@pytest.fixture
def repair_context(tmp_path, monkeypatch):
    from PacsClient.utils import data_paths
    import database._pool as pool
    with pool._pool_lock:
        pool._connection_pool.clear()
    monkeypatch.setattr(data_paths, 'DATABASE_FILE', tmp_path / 'isolated.db')
    from PacsClient.pacs.patient_tab.utils import utils
    import database.manager as manager
    for name in ('find_patient_pk', 'find_series_pk', 'find_study_pk_with_study_uid'):
        monkeypatch.setattr(manager, name, lambda *_: 1)
    published = []
    monkeypatch.setattr(utils, 'THUMBNAIL_PATH', tmp_path / 'thumbs')
    monkeypatch.setattr(utils, 'update_series_thumbnail_path', lambda pk, path: published.append(Path(path)))
    yield utils, published
    with pool._pool_lock:
        pool._connection_pool.clear()


def make_enhanced(folder, *, study_uid=None, series_uid=None):
    folder.mkdir(parents=True)
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = EnhancedMRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(str(folder / 'image.dcm'), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = EnhancedMRImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.Modality = 'MR'
    ds.Rows = ds.Columns = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.NumberOfFrames = 3
    shared = Dataset()
    orientation = Dataset(); orientation.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    shared.PlaneOrientationSequence = Sequence([orientation])
    spacing = Dataset(); spacing.PixelSpacing = [1, 1]; spacing.SliceThickness = 1
    shared.PixelMeasuresSequence = Sequence([spacing])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])
    ds.PerFrameFunctionalGroupsSequence = Sequence([])
    for index in range(3):
        frame = Dataset(); position = Dataset(); position.ImagePositionPatient = [0, 0, index]
        frame.PlanePositionSequence = Sequence([position])
        ds.PerFrameFunctionalGroupsSequence.append(frame)
    ds.PixelData = np.arange(192, dtype='<u2').reshape(3, 8, 8).tobytes()
    ds.save_as(folder / 'image.dcm', write_like_original=False)
    return ds


def make_single_frame_mr(folder, *, study_uid=None, series_uid=None):
    """Create a conventional image object suitable for a one-file thumbnail."""
    folder.mkdir(parents=True, exist_ok=True)
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    path = folder / 'image.dcm'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.Modality = 'MR'
    ds.InstanceNumber = 1
    ds.Rows = ds.Columns = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, 0]
    ds.PixelSpacing = [1, 1]
    ds.SliceThickness = 1
    ds.WindowWidth = 64
    ds.WindowCenter = 32
    ds.PixelData = np.arange(64, dtype='<u2').reshape(8, 8).tobytes()
    ds.save_as(path, write_like_original=False)
    return ds


def make_same_series_raw_data(folder, image):
    """Create a metadata-only object that must remain stored but never decoded."""
    from pydicom.uid import RawDataStorage

    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = RawDataStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    path = folder / '00000_raw.dcm'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = RawDataStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = image.StudyInstanceUID
    ds.SeriesInstanceUID = image.SeriesInstanceUID
    ds.Modality = image.Modality
    ds.InstanceNumber = 0
    ds.save_as(path, write_like_original=False)
    return path


def make_nonspatial_single_frame_series(folder, *, modality, sop_class, count=4):
    """Create a conventional multi-object series without volume geometry."""
    study_uid = generate_uid()
    series_uid = generate_uid()
    datasets = []
    for index in range(count):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = sop_class
        meta.MediaStorageSOPInstanceUID = generate_uid()
        path = folder / f'image_{index + 1:03d}.dcm'
        folder.mkdir(parents=True, exist_ok=True)
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = sop_class
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.Modality = modality
        ds.InstanceNumber = index + 1
        ds.Rows = ds.Columns = 8
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.WindowWidth = 64
        ds.WindowCenter = 32
        ds.PixelData = (np.arange(64, dtype='<u2') + index).reshape(8, 8).tobytes()
        ds.save_as(path, write_like_original=False)
        datasets.append(ds)
    return datasets


def test_enhanced_mr_without_top_level_geometry_gets_local_png(tmp_path, repair_context):
    utils, published = repair_context
    folder = tmp_path / 'study' / '16_collision'
    ds = make_enhanced(folder)
    path = utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))
    assert path, 'Pixel-bearing Enhanced MR must produce a thumbnail'
    assert Path(path).name == '16_collision.png'
    pixels = np.asarray(Image.open(path))
    assert pixels.shape == (8, 8)
    assert np.ptp(pixels) > 0
    assert published == [Path(path)]


def test_enhanced_mr_thumbnail_skips_same_series_raw_data(tmp_path, repair_context):
    utils, published = repair_context
    folder = tmp_path / 'study' / '16_collision'
    ds = make_enhanced(folder)
    raw_path = make_same_series_raw_data(folder, ds)
    path = utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))
    assert path and raw_path.is_file()
    pixels = np.asarray(Image.open(path))
    assert pixels.shape == (8, 8) and np.ptp(pixels) > 0
    assert published == [Path(path)]


def test_same_missing_thumbnail_repair_is_single_flight(
        tmp_path, repair_context, monkeypatch):
    """Home and Patient Tab may request one cache miss concurrently."""
    utils, published = repair_context
    folder = tmp_path / 'study' / '16_collision'
    ds = make_enhanced(folder)
    real_preview = utils._local_multiframe_thumbnail_preview
    count_lock = threading.Lock()
    preview_calls = 0

    def delayed_preview(*args, **kwargs):
        nonlocal preview_calls
        with count_lock:
            preview_calls += 1
        time.sleep(0.05)
        return real_preview(*args, **kwargs)

    monkeypatch.setattr(utils, '_local_multiframe_thumbnail_preview', delayed_preview)

    def repair():
        return utils.repair_local_series_thumbnail(
            str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
            {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _index: repair(), range(2)))

    assert paths[0] == paths[1] and Path(paths[0]).is_file()
    assert preview_calls == 1
    assert published == [Path(paths[0])]


def test_local_thumbnail_rejects_mismatched_series_identity(tmp_path, repair_context):
    utils, published = repair_context
    folder = tmp_path / 'study' / '16'
    ds = make_enhanced(folder)
    assert utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': generate_uid()}, folder.name, str(folder)) == ''
    assert published == []


@pytest.mark.parametrize('kind', ['enhanced', 'dx'])
def test_import_preparation_repairs_multiframe_before_patient_open(tmp_path, repair_context, kind):
    import ast
    utils, published = repair_context
    study_uid, series_uid = generate_uid(), generate_uid()
    folder = tmp_path / study_uid / '16_collision'
    if kind == 'enhanced':
        make_enhanced(folder, study_uid=study_uid, series_uid=series_uid)
    else:
        ds = make_dx(folder)
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.save_as(folder / 'image.dcm', write_like_original=False)
    source = Path('PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py')
    method = next(n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig')))
                  if isinstance(n, ast.FunctionDef) and n.name == '_prepare_imported_study_for_fast_open')
    scope = dict(SOURCE_PATH=tmp_path, THUMBNAIL_PATH=utils.THUMBNAIL_PATH,
                 find_patient_pk=lambda _: 1, find_study_pk_with_study_uid=lambda _: 1,
                 find_series_pk=lambda _: 1, load_series_preview=lambda **_: None,
                 clear_study_cache=lambda _: None)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
    info = {'study_uid': study_uid, 'patient_id': 'synthetic', 'series': [
        {'series_uid': series_uid, 'series_number': '16', 'folder_key': folder.name}]}
    assert scope[method.name](None, info) == 1
    assert len(published) == 1 and published[0].is_file()


def test_ordinary_single_frame_falls_back_after_existing_preview_failure(
        tmp_path, repair_context, monkeypatch):
    utils, published = repair_context
    folder = tmp_path / 'study' / '16'
    ds = make_enhanced(folder)
    ds.NumberOfFrames = 1
    ds.PixelData = ds.PixelData[:128]
    ds.save_as(folder / 'image.dcm', write_like_original=False)
    from PacsClient.pacs.patient_tab.utils import image_io
    called = []
    monkeypatch.setattr(image_io, 'load_series_preview', lambda **kw: called.append(kw))
    path = utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))
    assert path and Path(path).is_file()
    assert len(called) == 1 and called[0]['series_number'] == folder.name
    assert published == [Path(path)]


def test_single_frame_thumbnail_ignores_same_series_raw_data(
        tmp_path, repair_context, monkeypatch):
    """Metadata-only companions must not poison a pixel-bearing series thumbnail."""
    utils, published = repair_context
    folder = tmp_path / 'study' / '301'
    ds = make_single_frame_mr(folder)
    raw_path = make_same_series_raw_data(folder, ds)
    from PacsClient.pacs.patient_tab.utils import image_io
    monkeypatch.setattr(image_io, 'load_series_preview', lambda **_: None)

    path = utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))

    assert path, 'A metadata-only companion must not suppress the image thumbnail'
    assert raw_path.is_file(), 'Thumbnail repair must never delete the companion object'
    pixels = np.asarray(Image.open(path))
    assert pixels.shape == (8, 8) and np.ptp(pixels) > 0
    assert published == [Path(path)]


@pytest.mark.parametrize(
    ('modality', 'sop_class'),
    [
        ('MG', DigitalMammographyXRayImageStorageForPresentation),
        ('US', UltrasoundImageStorage),
    ],
)
def test_nonspatial_multifile_series_decodes_one_representative_thumbnail(
        tmp_path, repair_context, monkeypatch, modality, sop_class):
    """A non-volume image series still needs one bounded worker thumbnail."""
    utils, published = repair_context
    folder = tmp_path / 'study' / '1'
    datasets = make_nonspatial_single_frame_series(
        folder, modality=modality, sop_class=sop_class)
    from PacsClient.pacs.patient_tab.utils import image_io
    monkeypatch.setattr(
        image_io, 'load_series_preview',
        lambda **_: pytest.fail('Import repair must not repeat a failed spatial preview'))
    real_read = utils.sitk.ReadImage
    decoded = []

    def tracked_read(path):
        decoded.append(Path(path).name)
        return real_read(path)

    monkeypatch.setattr(utils.sitk, 'ReadImage', tracked_read)
    first = datasets[0]
    path = utils.repair_local_series_thumbnail(
        str(first.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(first.SeriesInstanceUID)}, folder.name, str(folder),
        spatial_preview_failed=True)

    assert path, 'Nonspatial pixel-bearing MG/US must produce a thumbnail'
    assert len(decoded) == 1, 'Thumbnail repair must decode one representative object only'
    pixels = np.asarray(Image.open(path))
    assert pixels.shape == (8, 8) and np.ptp(pixels) > 0
    assert published == [Path(path)]


def make_dx(folder):
    from pydicom.uid import DigitalXRayImageStorageForPresentation
    ds = make_enhanced(folder)
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    ds.Modality = 'DX'
    ds.NumberOfFrames = 1
    del ds.SharedFunctionalGroupsSequence
    del ds.PerFrameFunctionalGroupsSequence
    ds.PixelData = ds.PixelData[:128]
    ds.WindowWidth = 64
    ds.WindowCenter = 32
    ds.save_as(folder / 'image.dcm', write_like_original=False)
    return ds


def test_dx_without_geometry_gets_local_png(tmp_path, repair_context):
    utils, published = repair_context
    folder = tmp_path / 'study' / '1_collision'
    ds = make_dx(folder)
    path = utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder))
    assert path, 'Single-frame DX presentation must produce a thumbnail'
    assert Path(path).name == '1_collision.png'
    pixels = np.asarray(Image.open(path))
    assert pixels.shape == (8, 8) and np.ptp(pixels) > 0
    assert published == [Path(path)]


@pytest.mark.parametrize('mismatch', ['study', 'series'])
def test_dx_thumbnail_rejects_wrong_identity(tmp_path, repair_context, mismatch):
    utils, published = repair_context
    folder = tmp_path / 'study' / '1'
    ds = make_dx(folder)
    assert utils.repair_local_series_thumbnail(
        generate_uid() if mismatch == 'study' else str(ds.StudyInstanceUID),
        {'patient_id': 'synthetic'},
        {'series_uid': generate_uid() if mismatch == 'series' else str(ds.SeriesInstanceUID)},
        folder.name, str(folder)) == ''
    assert published == []


def test_dx_thumbnail_does_not_decode_multiple_objects(tmp_path, repair_context, monkeypatch):
    utils, published = repair_context
    folder = tmp_path / 'study' / '1'
    ds = make_dx(folder)
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.save_as(folder / 'second.dcm', write_like_original=False)
    from PacsClient.pacs.patient_tab.utils import advanced_presentation
    def unexpected_decode(*args, **kwargs):
        pytest.fail('Thumbnail must not prepare a multi-object presentation sequence')
    monkeypatch.setattr(advanced_presentation, 'load_presentation_sequence', unexpected_decode)
    assert utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder)) == ''
    assert published == []
