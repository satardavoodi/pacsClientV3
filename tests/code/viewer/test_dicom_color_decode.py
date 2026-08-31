"""Standards-based DICOM colour decode guards (patient 46382, 2026-06-14).

`modules/viewer/fast/dicom_color.py::decode_color_for_display` converts any DICOM
colour representation to an 8-bit RGB array for the FAST viewer, returning None
for genuine monochrome so the grayscale window/level path is untouched.

Covered: RGB passthrough, YBR_FULL -> RGB, PALETTE COLOR -> RGB, an embedded
Palette Colour LUT on a MONOCHROME parametric map (the 46382 series 21/22 case),
plain monochrome -> None, env gates, and the backend routing (a 3-channel decoded
slice goes to the RGB path regardless of SamplesPerPixel, so window/level never
destroys colour).
"""
import importlib
import os
from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import modules.viewer.fast.dicom_color as dc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FAST_DIR = REPO_ROOT / "modules" / "viewer" / "fast"


# ── synthetic dataset builders ───────────────────────────────────────────────
def _mono_ds(arr, photometric="MONOCHROME2", bits=16):
    ds = Dataset()
    ds.PhotometricInterpretation = photometric
    ds.SamplesPerPixel = 1
    ds.Rows, ds.Columns = int(arr.shape[0]), int(arr.shape[1])
    ds.BitsAllocated = bits
    ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PixelRepresentation = 0
    return ds


def _add_palette(ds, n=256, bits=16):
    # Set by explicit tag/VR so pydicom stores the real (0028,11xx)/(0028,12xx)
    # tags that apply_color_lut + has_embedded_palette read (the keyword form is
    # "...LookupTable...", easy to misspell).
    desc = [n, 0, bits]
    ds.add_new(0x00281101, "US", list(desc))
    ds.add_new(0x00281102, "US", list(desc))
    ds.add_new(0x00281103, "US", list(desc))
    idx = np.arange(n, dtype=np.uint16)
    scale = 257 if bits == 16 else 1
    red = (idx * scale).astype("<u2")
    grn = np.zeros(n, dtype="<u2")
    blu = ((n - 1 - idx) * scale).astype("<u2")
    ds.add_new(0x00281201, "OW", red.tobytes())
    ds.add_new(0x00281202, "OW", grn.tobytes())
    ds.add_new(0x00281203, "OW", blu.tobytes())


def _colorful(rgb):
    return int(np.abs(rgb[..., 0].astype(int) - rgb[..., 2].astype(int)).max())


# ── colour cases ─────────────────────────────────────────────────────────────
def test_rgb_passthrough():
    arr = np.zeros((4, 4, 3), np.uint8)
    arr[..., 0] = 200  # red
    ds = Dataset()
    ds.PhotometricInterpretation = "RGB"
    ds.SamplesPerPixel = 3
    out = dc.decode_color_for_display(ds, arr)
    assert out is not None and out.shape == (4, 4, 3) and out.dtype == np.uint8
    assert out[0, 0, 0] == 200 and out[0, 0, 2] == 0


def test_ybr_full_converted_to_rgb():
    # A YBR_FULL pixel with high Cr should map to a reddish RGB (R > B), and the
    # output must differ from the raw samples (i.e. conversion actually ran).
    arr = np.zeros((2, 2, 3), np.uint8)
    arr[..., 0] = 128   # Y
    arr[..., 1] = 128   # Cb
    arr[..., 2] = 255   # Cr (red)
    ds = Dataset()
    ds.PhotometricInterpretation = "YBR_FULL"
    ds.SamplesPerPixel = 3
    out = dc.decode_color_for_display(ds, arr)
    assert out is not None and out.shape == (2, 2, 3) and out.dtype == np.uint8
    assert not np.array_equal(out, arr)              # conversion happened
    assert int(out[0, 0, 0]) > int(out[0, 0, 2])     # red-dominant


def test_palette_color_photometric():
    idx = np.tile(np.arange(256, dtype=np.uint16), (4, 1))  # 4x256 indices
    ds = _mono_ds(idx, photometric="PALETTE COLOR")
    _add_palette(ds, n=256, bits=16)
    out = dc.decode_color_for_display(ds, idx)
    assert out is not None and out.shape[-1] == 3 and out.dtype == np.uint8
    assert _colorful(out) > 50


def test_embedded_palette_on_monochrome_is_colourised():
    # THE 46382 case: MONOCHROME2 parametric map carrying an embedded palette.
    idx = np.tile(np.arange(256, dtype=np.uint16), (4, 1))
    ds = _mono_ds(idx, photometric="MONOCHROME2")
    _add_palette(ds, n=256, bits=16)
    out = dc.decode_color_for_display(ds, idx)
    assert out is not None and out.shape[-1] == 3
    assert _colorful(out) > 50


def test_plain_monochrome_returns_none():
    arr = np.arange(16, dtype=np.uint16).reshape(4, 4)
    ds = _mono_ds(arr, photometric="MONOCHROME2")
    assert dc.decode_color_for_display(ds, arr) is None


def test_16bit_color_scaled_to_uint8():
    arr16 = np.zeros((2, 2, 3), np.uint16)
    arr16[..., 0] = 65535
    ds = Dataset()
    ds.PhotometricInterpretation = "RGB"
    ds.SamplesPerPixel = 3
    out = dc.decode_color_for_display(ds, arr16)
    assert out.dtype == np.uint8 and out[0, 0, 0] == 255 and out[0, 0, 2] == 0


# ── env gates ────────────────────────────────────────────────────────────────
def test_master_gate_off_disables_all_colour(monkeypatch):
    monkeypatch.setattr(dc, "_COLOR_ENABLED", False)
    idx = np.tile(np.arange(256, dtype=np.uint16), (4, 1))
    ds = _mono_ds(idx)
    _add_palette(ds)
    assert dc.decode_color_for_display(ds, idx) is None


def test_palette_on_mono_gate_off(monkeypatch):
    # With the finer gate off, an embedded palette on MONOCHROME stays grayscale,
    # but a true PALETTE COLOR photometric is still colourised.
    monkeypatch.setattr(dc, "_PALETTE_ON_MONO", False)
    idx = np.tile(np.arange(256, dtype=np.uint16), (4, 1))
    ds_mono = _mono_ds(idx, photometric="MONOCHROME2")
    _add_palette(ds_mono)
    assert dc.decode_color_for_display(ds_mono, idx) is None
    ds_pal = _mono_ds(idx, photometric="PALETTE COLOR")
    _add_palette(ds_pal)
    assert dc.decode_color_for_display(ds_pal, idx) is not None


# ── real 46382 data (skipped if not present) ─────────────────────────────────
_BASE = (REPO_ROOT / "user_data" / "patients" / "dicom" /
         "1.3.12.2.1107.5.2.46.174759.30000026061404440799700000019")


@pytest.mark.skipif(not _BASE.exists(), reason="46382 study not present on this machine")
@pytest.mark.parametrize("series", ["21", "22"])
def test_real_46382_parametric_map_is_colour(series):
    import pydicom
    fp = _BASE / series / "Instance_0001.dcm"
    if not fp.exists():
        pytest.skip("series file missing")
    ds = pydicom.dcmread(str(fp), force=True)
    out = dc.decode_color_for_display(ds, np.asarray(ds.pixel_array))
    assert out is not None and out.shape[-1] == 3
    assert _colorful(out) > 30          # genuinely colour, not gray


@pytest.mark.skipif(not _BASE.exists(), reason="46382 study not present on this machine")
def test_real_46382_grayscale_slice_stays_mono():
    import pydicom
    fp = _BASE / "100" / "Instance_0001.dcm"
    if not fp.exists():
        pytest.skip("series file missing")
    ds = pydicom.dcmread(str(fp), force=True)
    assert dc.decode_color_for_display(ds, np.asarray(ds.pixel_array)) is None


# ── backend wiring guards ────────────────────────────────────────────────────
def test_source_backend_routes_colour_by_ndim():
    src = (FAST_DIR / "pydicom_2d_backend.py").read_text(encoding="utf-8")
    assert "from .dicom_color import decode_color_for_display" in src
    assert "decode_color_for_display(ds, arr)" in src
    # get_frame must route colour by the decoded array being 3-D (so PALETTE /
    # embedded-palette with SamplesPerPixel==1 still take the RGB path).
    assert "if arr.ndim == 3:" in src
    assert "if sm.samples_per_pixel >= 3:" not in src  # old gate removed


def test_fast_pipeline_recovers_rgb_facts_when_db_metadata_omits_them(tmp_path, monkeypatch):
    """A colour single-frame object must not be sliced as a multi-frame stack.

    Local database projections can contain rows/columns/path without
    SamplesPerPixel or is_rgb. The DICOM header remains authoritative.
    """
    from modules.viewer.fast import lightweight_2d_pipeline as lw

    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgb[..., 0] = np.arange(20, dtype=np.uint8).reshape(4, 5) * 10
    rgb[..., 1] = 70
    rgb[..., 2] = 180

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    path = tmp_path / "rgb.dcm"
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = "TEST"
    ds.Modality = "US"
    ds.Rows, ds.Columns = rgb.shape[:2]
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = rgb.tobytes()
    ds.save_as(path, write_like_original=False)

    class _NoDiskCache:
        def get(self, **_kwargs):
            return None

        def put(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(lw, "get_disk_pixel_cache", lambda: _NoDiskCache())

    class _MetadataTrustingDecodeService:
        is_available = True

        def __init__(self):
            self.calls = 0

        def decode(self, *, rows, cols, samples_per_pixel, **_kwargs):
            self.calls += 1
            # Mirrors the failure mode: projected SamplesPerPixel=1 causes a
            # colour object to be returned as a narrow grayscale strip.
            assert samples_per_pixel == 1
            return np.zeros((cols, 3), dtype=np.uint8)

    decode_service = _MetadataTrustingDecodeService()
    monkeypatch.setattr(lw, "get_decode_service", lambda: decode_service)
    pipeline = lw.Lightweight2DPipeline(
        config=lw.PipelineConfig(prefetch_radius=0, prefetch_workers=1)
    )
    try:
        pipeline.open_series(
            str(tmp_path),
            metadata={
                "series": {"series_number": "1", "modality": "US"},
                "instances": [{
                    "instance_path": str(path),
                    "rows": 4,
                    "columns": 5,
                    "instance_number": 1,
                    # Some DB projections materialize this default even though
                    # SamplesPerPixel itself was never read from the object.
                    "is_rgb": False,
                }],
            },
        )
        assert pipeline._slices[0].pixel_facts_authoritative is False
        pipeline._current_index = 0
        pipeline._decode_into_cache(0)
        decoded = pipeline._pixel_cache.get(0)
        assert decode_service.calls == 0
        assert decoded.shape == rgb.shape
        assert np.array_equal(decoded, rgb)
        assert pipeline._slices[0].samples_per_pixel == 3
        assert pipeline._slices[0].is_rgb is True
    finally:
        pipeline.close_series()
