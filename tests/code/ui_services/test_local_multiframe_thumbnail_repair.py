"""Synthetic local-import thumbnails must not require a spatial viewer volume."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, EnhancedMRImageStorage, generate_uid


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


def test_ordinary_single_frame_retains_existing_preview_path(tmp_path, repair_context, monkeypatch):
    utils, published = repair_context
    folder = tmp_path / 'study' / '16'
    ds = make_enhanced(folder)
    ds.NumberOfFrames = 1
    ds.PixelData = ds.PixelData[:128]
    ds.save_as(folder / 'image.dcm', write_like_original=False)
    from PacsClient.pacs.patient_tab.utils import image_io
    called = []
    monkeypatch.setattr(image_io, 'load_series_preview', lambda **kw: called.append(kw))
    assert utils.repair_local_series_thumbnail(
        str(ds.StudyInstanceUID), {'patient_id': 'synthetic'},
        {'series_uid': str(ds.SeriesInstanceUID)}, folder.name, str(folder)) == ''
    assert len(called) == 1 and called[0]['series_number'] == folder.name
    assert published == []


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
