"""Guards for the 2026-08-21 colour-decode fix (ALPINION E-CUBE i7 breast US).

Two independent defects made a colour ultrasound render as coloured static:

  1. 39 of the study's 45 instances declare PhotometricInterpretation
     YBR_FULL_422 but ship FULL, non-subsampled pixel data. pydicom 2.4.5 warns
     and then applies the 4:2:2 -> 4:4:4 resample anyway, after truncating the
     buffer to two thirds — every output sample becomes a rotating mix of
     Y/Cb/Cr from neighbouring pixels.
  2. The FAST pipeline painted multi-sample frames as RGB without ever
     converting YBR -> RGB.

These guards pin BOTH corrections and, just as importantly, pin that neither
touches grayscale, true RGB, palette, compressed, or genuinely subsampled data.
"""
import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileMetaDataset          # noqa: E402
from pydicom.pixel_data_handlers.util import convert_color_space  # noqa: E402
from pydicom.uid import (                                      # noqa: E402
    ExplicitVRLittleEndian,
    JPEGBaseline8Bit,
)

import modules.viewer.fast.dicom_color as dc                   # noqa: E402

ROWS, COLS = 8, 8


# ───────────────────────────── fixtures ──────────────────────────────────

def _ybr_bytes(rows=ROWS, cols=COLS):
    """Interleaved Y/Cb/Cr with structure in BOTH axes (so a stride error shows)."""
    buf = bytearray()
    for r in range(rows):
        for c in range(cols):
            buf.append((17 * r + 29 * c) % 200 + 20)   # Y
            buf.append(100)                            # Cb
            buf.append(200)                            # Cr
    return bytes(buf)


def _dataset(photometric, pixel_bytes, *, samples=3, bits=8,
             transfer_syntax=ExplicitVRLittleEndian, rows=ROWS, cols=COLS):
    sop_class = "1.2.840.10008.5.1.4.1.1.6.1"      # Ultrasound Image Storage
    sop_instance = "1.2.826.0.1.3680043.8.498.99999"
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = transfer_syntax
    ds.file_meta.MediaStorageSOPClassUID = sop_class
    ds.file_meta.MediaStorageSOPInstanceUID = sop_instance
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_instance
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = samples
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = bits
    ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PixelRepresentation = 0
    if samples >= 3:
        ds.PlanarConfiguration = 0
    ds.PixelData = pixel_bytes
    return ds


def _write(tmp_path, ds, name="frame.dcm"):
    path = tmp_path / name
    ds.save_as(str(path), write_like_original=False)
    return str(path)


@pytest.fixture(autouse=True)
def _fresh_flags(monkeypatch):
    """Every test starts from the shipped defaults (both fixes ON)."""
    monkeypatch.delenv("AIPACS_DICOM_YBR422_FIX", raising=False)
    monkeypatch.delenv("AIPACS_DICOM_YBR_TO_RGB", raising=False)
    monkeypatch.delenv("AIPACS_DICOM_COLOR", raising=False)
    importlib.reload(dc)
    yield
    importlib.reload(dc)


# ─────────────────── normalize_ybr_subsampling: it fires ──────────────────

def test_mislabelled_422_is_corrected_to_ybr_full():
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    assert dc.normalize_ybr_subsampling(ds) is True
    assert ds.PhotometricInterpretation == "YBR_FULL"


def test_corrected_dataset_decodes_to_the_true_pixel_grid():
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    dc.normalize_ybr_subsampling(ds)
    arr = np.asarray(ds.pixel_array)
    expected = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    assert arr.shape == (ROWS, COLS, 3)
    assert np.array_equal(arr, expected)


def test_uncorrected_dataset_decodes_to_scrambled_samples():
    """The bug itself, pinned: without the fix pydicom does NOT return the grid."""
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    with pytest.warns(UserWarning):
        arr = np.asarray(ds.pixel_array)
    expected = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    assert not np.array_equal(arr, expected)


# ─────────────── normalize_ybr_subsampling: it stays out of the way ───────

def test_genuinely_subsampled_422_is_left_alone():
    """Real 4:2:2 carries 2 bytes/pixel — pydicom's expansion is CORRECT there."""
    ds = _dataset("YBR_FULL_422", bytes(ROWS * COLS * 2))
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "YBR_FULL_422"


def test_rgb_is_left_alone():
    ds = _dataset("RGB", _ybr_bytes())
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "RGB"


def test_ybr_full_is_left_alone():
    ds = _dataset("YBR_FULL", _ybr_bytes())
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "YBR_FULL"


def test_monochrome_is_left_alone():
    ds = _dataset("MONOCHROME2", bytes(ROWS * COLS), samples=1)
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "MONOCHROME2"


def test_compressed_transfer_syntax_is_left_alone():
    """For encapsulated pixel data the codec owns subsampling, not the tag."""
    ds = _dataset("YBR_FULL_422", _ybr_bytes(), transfer_syntax=JPEGBaseline8Bit)
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "YBR_FULL_422"


def test_16_bit_colour_is_left_alone():
    ds = _dataset("YBR_FULL_422", bytes(ROWS * COLS * 3 * 2), bits=16)
    assert dc.normalize_ybr_subsampling(ds) is False


def test_ybr422_fix_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_DICOM_YBR422_FIX", "0")
    importlib.reload(dc)
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    assert dc.normalize_ybr_subsampling(ds) is False
    assert ds.PhotometricInterpretation == "YBR_FULL_422"


def test_master_colour_kill_switch_also_disables_the_422_fix(monkeypatch):
    monkeypatch.setenv("AIPACS_DICOM_COLOR", "0")
    importlib.reload(dc)
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    assert dc.normalize_ybr_subsampling(ds) is False


# ───────────────────────── ybr_samples_to_rgb ─────────────────────────────

def test_ybr_samples_are_converted_to_rgb():
    ds = _dataset("YBR_FULL", _ybr_bytes())
    arr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    out = dc.ybr_samples_to_rgb(ds, arr)
    expected = np.clip(convert_color_space(arr, "YBR_FULL", "RGB"), 0, 255).astype(np.uint8)
    assert np.array_equal(out, expected)
    assert not np.array_equal(out, arr)          # a conversion really happened


def test_rgb_samples_pass_through_byte_identical():
    ds = _dataset("RGB", _ybr_bytes())
    arr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    out = dc.ybr_samples_to_rgb(ds, arr)
    assert np.array_equal(out, arr)


def test_grayscale_passes_through_untouched():
    ds = _dataset("MONOCHROME2", bytes(ROWS * COLS), samples=1)
    arr = np.arange(ROWS * COLS, dtype=np.uint16).reshape(ROWS, COLS)
    out = dc.ybr_samples_to_rgb(ds, arr)
    assert out is arr


def test_ybr_to_rgb_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_DICOM_YBR_TO_RGB", "0")
    importlib.reload(dc)
    ds = _dataset("YBR_FULL", _ybr_bytes())
    arr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    assert dc.ybr_samples_to_rgb(ds, arr) is arr


def test_conversion_is_skipped_when_a_handler_already_converted():
    """pydicom rewrites the tag to RGB when a codec did the conversion."""
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    ds.PhotometricInterpretation = "RGB"          # what pydicom leaves behind
    arr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    assert np.array_equal(dc.ybr_samples_to_rgb(ds, arr), arr)


# ──────────────────── end-to-end through the real decoder ─────────────────

def test_decode_worker_returns_the_true_rgb_image(tmp_path):
    """The whole point: the subprocess decoder must produce the real picture."""
    from modules.viewer.fast.decode_service import _decode_worker
    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    path = _write(tmp_path, ds)

    out = _decode_worker(path, ROWS, COLS, 1.0, 0.0, "YBR_FULL_422", 3)

    ybr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    expected = np.clip(convert_color_space(ybr, "YBR_FULL", "RGB"), 0, 255).astype(np.uint8)
    assert out.shape == (ROWS, COLS, 3)
    assert np.array_equal(out, expected)


def test_decode_worker_leaves_true_rgb_untouched(tmp_path):
    from modules.viewer.fast.decode_service import _decode_worker
    payload = _ybr_bytes()
    ds = _dataset("RGB", payload)
    path = _write(tmp_path, ds)
    out = _decode_worker(path, ROWS, COLS, 1.0, 0.0, "RGB", 3)
    assert np.array_equal(
        out, np.frombuffer(payload, dtype=np.uint8).reshape(ROWS, COLS, 3))


def test_decode_worker_leaves_grayscale_untouched(tmp_path):
    from modules.viewer.fast.decode_service import _decode_worker
    payload = np.arange(ROWS * COLS, dtype=np.uint16)
    ds = _dataset("MONOCHROME2", payload.tobytes(), samples=1, bits=16)
    path = _write(tmp_path, ds)
    out = _decode_worker(path, ROWS, COLS, 1.0, 0.0, "MONOCHROME2", 1)
    assert np.array_equal(np.asarray(out).ravel().astype(np.int64),
                          payload.astype(np.int64))


def test_decode_worker_honours_the_kill_switches(tmp_path, monkeypatch):
    """With both switches off the decoder reproduces the ORIGINAL (broken) output."""
    monkeypatch.setenv("AIPACS_DICOM_YBR422_FIX", "0")
    monkeypatch.setenv("AIPACS_DICOM_YBR_TO_RGB", "0")
    importlib.reload(dc)
    import modules.viewer.fast.decode_service as svc
    importlib.reload(svc)

    ds = _dataset("YBR_FULL_422", _ybr_bytes())
    path = _write(tmp_path, ds)
    out = svc._decode_worker(path, ROWS, COLS, 1.0, 0.0, "YBR_FULL_422", 3)

    ybr = np.frombuffer(_ybr_bytes(), dtype=np.uint8).reshape(ROWS, COLS, 3)
    expected = np.clip(convert_color_space(ybr, "YBR_FULL", "RGB"), 0, 255).astype(np.uint8)
    assert not np.array_equal(out, expected)
    importlib.reload(svc)


# ───────────────────────── source-wiring guards ───────────────────────────

def _ast_calls(path, func_name):
    """Names of every function called anywhere inside *func_name* (comment-proof)."""
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        names.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        names.add(fn.attr)
            return names
    raise AssertionError("%s not found in %s" % (func_name, path))


def test_decode_worker_is_wired_to_both_helpers():
    calls = _ast_calls(_ROOT / "modules" / "viewer" / "fast" / "decode_service.py",
                       "_decode_worker")
    assert "_norm_ybr" in calls, "decode_service must normalise YBR_FULL_422"
    assert "_ybr_rgb" in calls, "decode_service must convert YBR -> RGB"


def test_lightweight_pipeline_is_wired_to_both_helpers():
    calls = _ast_calls(
        _ROOT / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py",
        "_decode_slice")
    assert "normalize_ybr_subsampling" in calls
    assert "ybr_samples_to_rgb" in calls


def test_normalisation_runs_before_the_pixel_data_is_touched():
    """Ordering is load-bearing: pydicom caches the (mis)decoded array."""
    src = (_ROOT / "modules" / "viewer" / "fast" / "decode_service.py").read_text(
        encoding="utf-8", errors="replace")
    body = src.split("def _decode_worker", 1)[1]
    assert body.index("_norm_ybr(ds)") < body.index("ds.pixel_array")
