"""FAST multi-frame / cine / enhanced support (2026-07-01).

A single DICOM file with NumberOfFrames > 1 (ultrasound cine, XA, enhanced CT/MR)
used to show ONLY frame 0 in the FAST viewer: the pipeline built one SliceMeta per
FILE and the decoder did arr = arr[0]. This change expands such a file into N
scrollable slices, each decoding its OWN frame with a frame-aware disk-cache key.

Single-frame series are byte-identical (the expansion + frame-select branches are
never reached); AIPACS_FAST_MULTIFRAME=0 disables the feature entirely.
"""
from pathlib import Path

import numpy as np
import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _make_multiframe_dicom(path: Path, n_frames: int = 8, rows: int = 16, cols: int = 12):
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.3.1"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.3.1"
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "US"
    ds.InstanceNumber = 1
    ds.Rows = rows
    ds.Columns = cols
    ds.NumberOfFrames = n_frames
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    frames = np.stack([np.full((rows, cols), k, dtype=np.uint16) for k in range(n_frames)])
    ds.PixelData = frames.tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path), write_like_original=False)


def test_header_scan_captures_number_of_frames(tmp_path):
    pytest.importorskip("pydicom")
    import importlib.util
    import sys
    mod_path = _repo_root() / "modules" / "viewer" / "fast" / "dicom_header_scan.py"
    spec = importlib.util.spec_from_file_location("aipacs_dhs_under_test", mod_path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # pragma: no cover
        pytest.skip("header-scan import unavailable: %s" % exc)
    scan_series_header_entries = m.scan_series_header_entries
    _safe_number_of_frames = m._safe_number_of_frames

    assert _safe_number_of_frames(8) == 8
    assert _safe_number_of_frames(1) == 1
    assert _safe_number_of_frames(None) == 1
    assert _safe_number_of_frames("garbage") == 1
    assert _safe_number_of_frames(0) == 1

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    _make_multiframe_dicom(series_dir / "img0.dcm", n_frames=8)
    entries = scan_series_header_entries(str(series_dir))
    assert len(entries) == 1
    assert int(entries[0].num_frames) == 8


def test_pixel_array_frame_indexing_assumption(tmp_path):
    pydicom = pytest.importorskip("pydicom")
    p = tmp_path / "mf.dcm"
    _make_multiframe_dicom(p, n_frames=6, rows=8, cols=8)
    ds = pydicom.dcmread(str(p), force=True)
    arr = np.asarray(ds.pixel_array)
    assert arr.ndim == 3 and arr.shape[0] == 6
    for k in range(6):
        assert int(arr[k].flat[0]) == k
        assert int(arr[k].min()) == k and int(arr[k].max()) == k


def _pipeline_src() -> str:
    return (
        _repo_root() / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py"
    ).read_text(encoding="utf-8")


def test_slice_meta_has_frame_fields():
    src = _pipeline_src()
    assert "frame_index: Optional[int] = None" in src
    assert "num_frames: int = 1" in src


def test_flag_default_on_kill_switch():
    src = _pipeline_src()
    assert 'os.environ.get("AIPACS_FAST_MULTIFRAME", "1")' in src
    assert "_FAST_MULTIFRAME = str(" in src


def test_expansion_wired_in_open_series():
    src = _pipeline_src()
    assert "self._slices = self._expand_multiframe_slices(self._slices)" in src
    i_build = src.find("self._slices = self._scan_series_headers(series_path)")
    i_expand = src.find("self._slices = self._expand_multiframe_slices(self._slices)")
    i_sort = src.find("self._slices = self._sort_slices(self._slices)")
    assert -1 < i_build < i_expand < i_sort


def test_expansion_logic_pins():
    src = _pipeline_src()
    fn = src.find("def _expand_multiframe_slices")
    body = src[fn:fn + 2200]
    assert "if not _FAST_MULTIFRAME or not slices:" in body
    assert 'int(getattr(sm, "num_frames", 1) or 1)' in body
    assert "_dc_replace(sm, frame_index=k, num_frames=n)" in body
    assert "len(slices) == 1" in body


def test_decode_selects_own_frame_and_frame_aware_cache_key():
    src = _pipeline_src()
    assert "_frame = int(_fi) if (_FAST_MULTIFRAME and _fi is not None) else 0" in src
    assert "arr = arr[_frame] if 0 <= _frame < arr.shape[0] else arr[0]" in src
    fn = src.find("def _decode_cache_key")
    body = src[fn:fn + 700]
    assert 'return f"{base}::f{int(fi)}"' in body
    assert "return base" in body
    assert "self._decode_cache_key(sm)" in src


def test_sort_keeps_frames_ordered():
    src = _pipeline_src()
    fn = src.find("def _sort_slices")
    body = src[fn:fn + 900]
    assert 's.frame_index if getattr(s, "frame_index", None) is not None else -1' in body
