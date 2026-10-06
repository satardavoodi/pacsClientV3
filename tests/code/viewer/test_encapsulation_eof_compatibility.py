"""Synthetic complete-fragment EOF recovery; never touch clinical data."""
import hashlib
import struct

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, RLELossless, generate_uid

from PacsClient.utils.dicom_reader import read_dicom


def make_image(tmp_path, *, missing=True):
    path = tmp_path / 'synthetic.dcm'
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = 'MR'
    ds.Rows = ds.Columns = 16
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.ImagePositionPatient = [0, 0, 0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [1, 1]
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    expected = np.arange(256, dtype=np.uint16).reshape(16, 16)
    ds.PixelData = expected.tobytes()
    ds.compress(RLELossless)
    ds.save_as(path, write_like_original=False)
    raw = path.read_bytes()
    assert raw.endswith(struct.pack('<HHI', 0xfffe, 0xe0dd, 0))
    if missing:
        path.write_bytes(raw[:-8])
    return path, expected


def test_complete_fragments_without_delimiter_decode_without_writing(tmp_path):
    path, expected = make_image(tmp_path)
    before = hashlib.sha256(path.read_bytes()).digest()
    ds = read_dicom(path)
    assert 'PixelData' in ds, 'Complete compressed image must not become metadata-only'
    np.testing.assert_array_equal(ds.pixel_array, expected)
    assert ds.file_meta.TransferSyntaxUID == RLELossless
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_valid_encapsulation_and_header_only_read_are_unchanged(tmp_path):
    path, expected = make_image(tmp_path, missing=False)
    np.testing.assert_array_equal(read_dicom(path).pixel_array, expected)
    assert 'PixelData' not in read_dicom(path, stop_before_pixels=True)
    assert 'PixelData' not in read_dicom(path, specific_tags=['Rows'])


@pytest.mark.parametrize('damage', ['truncated', 'oversized', 'odd', 'extra_tag', 'undefined_item'])
def test_malformed_or_truncated_fragments_are_not_recovered(tmp_path, damage):
    path, _ = make_image(tmp_path)
    raw = bytearray(path.read_bytes())
    start = raw.index(b'\xe0\x7f\x10\x00OB') + 12
    bot_length = struct.unpack_from('<I', raw, start + 4)[0]
    fragment = start + 8 + bot_length
    if damage == 'truncated':
        raw = raw[:-2]
    elif damage == 'oversized':
        struct.pack_into('<I', raw, fragment + 4, len(raw) * 2)
    elif damage == 'odd':
        struct.pack_into('<I', raw, fragment + 4, len(raw) - fragment - 9)
    elif damage == 'undefined_item':
        struct.pack_into('<I', raw, fragment + 4, 0xffffffff)
    else:
        raw += b'\x10\x00\x20\x00LO\x02\x00XX'
    path.write_bytes(raw)
    assert 'PixelData' not in read_dicom(path)


def test_fast_decode_worker_uses_recovery(tmp_path):
    from modules.viewer.fast.decode_service import _decode_worker
    path, expected = make_image(tmp_path)
    actual = _decode_worker(str(path), 16, 16, 1, 0, 'MONOCHROME2', 1)
    np.testing.assert_array_equal(actual, expected)


def test_advanced_gdcm_reads_same_complete_pixels(tmp_path):
    import SimpleITK as sitk
    path, expected = make_image(tmp_path)
    actual = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))[0]
    np.testing.assert_array_equal(actual, expected)


def test_legacy_pydicom_backend_reads_complete_pixels(tmp_path):
    from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
    path, expected = make_image(tmp_path)
    backend = PyDicom2DBackend()
    try:
        backend.open_series(str(tmp_path))
        np.testing.assert_array_equal(backend.get_pixel_array(0), expected)
    finally:
        backend.close_series()


def test_fast_pipeline_decode_without_live_cache(tmp_path, monkeypatch):
    from modules.viewer.fast import lightweight_2d_pipeline as lw
    from types import SimpleNamespace
    path, expected = make_image(tmp_path)
    cache = SimpleNamespace(get=lambda **kw: None, put=lambda *args, **kw: None)
    monkeypatch.setattr(lw, 'get_disk_pixel_cache', lambda: cache)
    pipeline = lw.Lightweight2DPipeline(config=lw.PipelineConfig(prefetch_radius=0))
    try:
        pipeline.open_series(str(tmp_path), metadata={
            'series': {'series_number': '1', 'modality': 'MR'},
            'instances': [{'instance_path': str(path), 'rows': 16, 'columns': 16,
                           'instance_number': 1}],
        })
        np.testing.assert_array_equal(pipeline._decode_slice(0), expected)
    finally:
        pipeline.close_series()


def test_manifest_does_not_misclassify_complete_pixels(tmp_path):
    from modules.storage.sync_manifest import _pixelless_stub_count
    path, _ = make_image(tmp_path)
    assert _pixelless_stub_count(tmp_path) == 0


def test_recovery_respects_payload_limit(tmp_path, monkeypatch):
    from PacsClient.utils import dicom_reader
    path, _ = make_image(tmp_path)
    monkeypatch.setattr(dicom_reader, '_MAX_VALUE_BYTES', 16)
    assert 'PixelData' not in read_dicom(path)


def test_import_conversion_preserves_pixels_and_original(tmp_path):
    from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (
        _decompress_file_to_destination,
    )
    path, expected = make_image(tmp_path)
    before = path.read_bytes()
    dest = tmp_path / 'normalized.dcm'
    success, reason = _decompress_file_to_destination(path, dest)
    assert success, reason
    np.testing.assert_array_equal(pydicom.dcmread(dest).pixel_array, expected)
    assert path.read_bytes() == before


def test_invalid_basic_offset_table_is_not_recovered(tmp_path):
    path, _ = make_image(tmp_path)
    raw = bytearray(path.read_bytes())
    start = raw.index(b'\xe0\x7f\x10\x00OB') + 12
    assert struct.unpack_from('<I', raw, start + 4)[0] == 4
    struct.pack_into('<I', raw, start + 8, 999999)
    path.write_bytes(raw)
    assert 'PixelData' not in read_dicom(path)
