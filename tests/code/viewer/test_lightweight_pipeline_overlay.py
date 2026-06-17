"""FAST *active* pipeline overlay/colour rendering guards (patient 46630, 2026-06-17).

Root cause of the 46630 bug: the live FAST viewer renders through
``modules/viewer/fast/lightweight_2d_pipeline.py`` (the ``pydicom_qt`` backend),
NOT ``pydicom_2d_backend.py`` (the ``lazy_backend`` where the 46382 overlay/colour
fix originally landed). The lightweight pipeline built its QImage straight from
PixelData, so Siemens BREAST dynaVIEWS derived frames — ROI-annotation result
images and the "CSA BLACK IMAGE" mean-curve charts whose graphics live in a
``(6000,3000)`` overlay plane over all-zero pixels — showed as grayscale-without-
annotation / pure black.

These guards lock in that the lightweight pipeline now composites overlay planes
(and palette/embedded colour) via the shared dicom_overlay / dicom_color modules,
while ordinary grayscale series stay on the untouched Format_Grayscale8 path.
"""
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pydicom  # noqa: E402
from pydicom.dataset import Dataset, FileMetaDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

import modules.viewer.fast.lightweight_2d_pipeline as lw  # noqa: E402
from modules.viewer.fast.lightweight_2d_pipeline import (  # noqa: E402
    Lightweight2DPipeline,
    PipelineConfig,
    SliceMeta,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── synthetic DICOM helpers ────────────────────────────────────────────────
def _write_dcm(path, pixels, overlay_lit=None):
    rows, cols = pixels.shape
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.WindowCenter, ds.WindowWidth = 200, 400
    ds.PixelData = pixels.astype("<u2").tobytes()
    if overlay_lit is not None:
        ds.add_new((0x6000, 0x0010), "US", rows)          # Overlay Rows
        ds.add_new((0x6000, 0x0011), "US", cols)          # Overlay Columns
        ds.add_new((0x6000, 0x0040), "CS", "G")           # Overlay Type = Graphics
        ds.add_new((0x6000, 0x0100), "US", 1)             # Overlay Bits Allocated
        ds.add_new((0x6000, 0x0102), "US", 0)             # Overlay Bit Position
        bits = np.zeros((rows, cols), np.uint8)
        for (r, c) in overlay_lit:
            bits[r, c] = 1
        packed = np.packbits(bits.ravel(), bitorder="little")  # DICOM LSB-first
        ds.add_new((0x6000, 0x3000), "OW", packed.tobytes())
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path), write_like_original=False)
    return path


def _meta(path, rows, cols, instance_number):
    return SliceMeta(
        path=str(path), rows=rows, cols=cols, pixel_spacing=(1.0, 1.0),
        iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0), ipp=(0.0, 0.0, float(instance_number)),
        slice_thickness=1.0, spacing_between_slices=1.0, photometric="MONOCHROME2",
        bits_allocated=16, pixel_representation=0, samples_per_pixel=1,
        window_width=400.0, window_center=200.0, slope=1.0, intercept=0.0,
        instance_number=int(instance_number), is_rgb=False,
    )


def _render(pipeline, idx, arr):
    # Seed the pixel cache so decode never touches the disk pixel cache; the
    # overlay/colour extraction still reads the dataset header from sm.path.
    pipeline._pixel_cache[idx] = arr.astype(np.int16)
    return pipeline._render_frame_uncached(idx, 400.0, 200.0, False, record_metrics=False)


def _qimg_to_rgb(qimg):
    img = qimg.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = bytes(img.constBits())[: bpl * h]
    return np.frombuffer(buf, np.uint8).reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)


def _green_px(rgb):
    return int(np.count_nonzero((rgb[..., 0] < 60) & (rgb[..., 1] > 180) & (rgb[..., 2] < 60)))


def _new_pipeline(tmp_path, slices):
    p = Lightweight2DPipeline(
        PipelineConfig(pixel_cache_size=16, frame_cache_size=16, adaptive_cache_sizing=False)
    )
    p._series_path = str(tmp_path)
    p._is_open = True
    p._slices = slices
    return p


# ── module-helper probe ────────────────────────────────────────────────────
def test_dataset_extras_probe_overlay_and_plain(tmp_path):
    plain = pydicom.dcmread(_write_dcm(tmp_path / "plain.dcm", np.full((4, 4), 500, np.uint16)))
    over = pydicom.dcmread(
        _write_dcm(tmp_path / "over.dcm", np.full((4, 4), 500, np.uint16), overlay_lit=[(1, 1)])
    )
    assert lw._dataset_has_dicom_extras(plain) is False
    assert lw._dataset_has_dicom_extras(over) is True


def test_dataset_extras_probe_embedded_palette():
    ds = Dataset()
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SamplesPerPixel = 1
    ds.add_new(0x00281101, "US", [256, 0, 16])              # Red Palette LUT Descriptor
    ds.add_new(0x00281201, "OW", (b"\x00\x00" * 256))       # Red Palette LUT Data
    assert lw._dataset_has_dicom_extras(ds) is True


# ── pipeline render integration ────────────────────────────────────────────
def test_plain_mono_stays_grayscale(tmp_path):
    arr = np.full((4, 4), 500, np.uint16)
    _write_dcm(tmp_path / "p0.dcm", arr)
    p = _new_pipeline(tmp_path, [_meta(tmp_path / "p0.dcm", 4, 4, 0)])
    frame = _render(p, 0, arr)
    assert frame.qimage.format() == QImage.Format.Format_Grayscale8
    assert _green_px(_qimg_to_rgb(frame.qimage)) == 0
    p.close_series()


def test_overlay_on_monochrome_composited(tmp_path):
    arr = np.full((4, 4), 500, np.uint16)
    lit = [(0, 0), (1, 1), (2, 2), (3, 3)]
    _write_dcm(tmp_path / "o0.dcm", arr, overlay_lit=lit)
    p = _new_pipeline(tmp_path, [_meta(tmp_path / "o0.dcm", 4, 4, 0)])
    frame = _render(p, 0, arr)
    assert frame.qimage.format() == QImage.Format.Format_RGB888
    assert _green_px(_qimg_to_rgb(frame.qimage)) == len(lit)
    p.close_series()


def test_black_secondary_capture_overlay_not_black(tmp_path):
    """The 46630 mean-curve case: all-zero pixels, chart in the overlay plane."""
    arr = np.zeros((4, 4), np.uint16)
    lit = [(0, 1), (1, 2), (2, 3)]
    _write_dcm(tmp_path / "b0.dcm", arr, overlay_lit=lit)
    p = _new_pipeline(tmp_path, [_meta(tmp_path / "b0.dcm", 4, 4, 0)])
    frame = _render(p, 0, arr)
    rgb = _qimg_to_rgb(frame.qimage)
    assert frame.qimage.format() == QImage.Format.Format_RGB888
    assert _green_px(rgb) == len(lit)                 # chart pixels visible
    assert int(np.count_nonzero(rgb.sum(axis=2) > 10)) == len(lit)  # rest stays black
    p.close_series()


def test_gate_off_disables_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "_FAST_DICOM_EXTRAS_ENABLED", False)
    arr = np.full((4, 4), 500, np.uint16)
    _write_dcm(tmp_path / "g0.dcm", arr, overlay_lit=[(1, 1)])
    p = _new_pipeline(tmp_path, [_meta(tmp_path / "g0.dcm", 4, 4, 0)])
    frame = _render(p, 0, arr)
    assert frame.qimage.format() == QImage.Format.Format_Grayscale8  # untouched path
    p.close_series()


# ── real 46630 data (skipped when the study is not on this machine) ─────────
_BASE = (REPO_ROOT / "user_data" / "patients" / "dicom" /
         "1.3.12.2.1107.5.2.46.174759.30000026061604302027000000090")


@pytest.mark.skipif(not _BASE.exists(), reason="46630 study not present on this machine")
@pytest.mark.parametrize("series", [100, 101, 102, 103, 104, 105])
def test_real_46630_overlays_render(series):
    series_dir = _BASE / str(series)
    if not series_dir.exists():
        pytest.skip(f"series {series} not present")
    p = Lightweight2DPipeline(
        PipelineConfig(pixel_cache_size=8, frame_cache_size=8, adaptive_cache_sizing=False)
    )
    try:
        p.open_series(str(series_dir))
        assert p.slice_count == 5
        green_total = 0
        for idx in range(p.slice_count):
            frame = p.get_rendered_frame(idx)
            green_total += _green_px(_qimg_to_rgb(frame.qimage))
        # ROI annotation (slice 3) + two mean-curve charts (slices 4-5) all
        # carry overlay graphics — there must be a substantial green footprint.
        assert green_total > 5000
    finally:
        p.close_series()
