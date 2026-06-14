"""DICOM overlay-plane (group 60xx) rendering guards (patient 46382, 2026-06-14).

`modules/viewer/fast/dicom_overlay.py::extract_overlay_mask` returns a combined
HxW (0/1) overlay mask, or None when an image has no overlay. The FAST backend
composites it in a highlight colour so graphics-only frames render their content.

Patient 46382 series 100/101: the last two slices are Siemens "CSA BLACK IMAGE"
secondary captures with all-zero PixelData; the mean-curve result-table chart is
in overlay group (6000,3000) type G. Rendering the overlay reveals the chart.
"""
import os
from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import Dataset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import modules.viewer.fast.dicom_overlay as ov  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FAST_DIR = REPO_ROOT / "modules" / "viewer" / "fast"


def _ds_with_overlay(rows=8, cols=8, lit=(), group=0x6000, origin=None):
    ds = Dataset()
    ds.Rows = rows
    ds.Columns = cols
    ds.add_new((group, 0x0010), "US", rows)            # Overlay Rows
    ds.add_new((group, 0x0011), "US", cols)            # Overlay Columns
    ds.add_new((group, 0x0040), "CS", "G")             # Overlay Type = Graphics
    ds.add_new((group, 0x0100), "US", 1)               # Overlay Bits Allocated
    ds.add_new((group, 0x0102), "US", 0)               # Overlay Bit Position
    if origin is not None:
        ds.add_new((group, 0x0050), "SS", list(origin))  # Overlay Origin (1-based)
    bits = np.zeros((rows, cols), np.uint8)
    for (r, c) in lit:
        bits[r, c] = 1
    # DICOM overlay data is packed LSB-first (PS3.5); pydicom unpacks little.
    packed = np.packbits(bits.ravel(), bitorder="little")
    ds.add_new((group, 0x3000), "OW", packed.tobytes())
    return ds, bits


def test_overlay_mask_extracted():
    ds, _ = _ds_with_overlay(8, 8, lit=[(0, 0), (7, 7), (3, 4)])
    mask = ov.extract_overlay_mask(ds, 8, 8)
    assert mask is not None and mask.shape == (8, 8)
    assert mask[0, 0] == 1 and mask[7, 7] == 1 and mask[3, 4] == 1
    assert int(mask.sum()) == 3


def test_no_overlay_returns_none():
    ds = Dataset()
    ds.Rows = 8
    ds.Columns = 8
    assert ov.extract_overlay_mask(ds, 8, 8) is None


def test_empty_overlay_returns_none():
    ds, _ = _ds_with_overlay(8, 8, lit=[])      # overlay present but nothing lit
    assert ov.extract_overlay_mask(ds, 8, 8) is None


def test_gate_off_disables_overlay(monkeypatch):
    monkeypatch.setattr(ov, "_OVERLAY_ENABLED", False)
    ds, _ = _ds_with_overlay(8, 8, lit=[(1, 1)])
    assert ov.extract_overlay_mask(ds, 8, 8) is None


def test_overlay_color_env(monkeypatch):
    monkeypatch.setenv("AIPACS_DICOM_OVERLAY_COLOR", "10,20,30")
    assert ov.overlay_color() == (10, 20, 30)
    monkeypatch.setenv("AIPACS_DICOM_OVERLAY_COLOR", "bogus")
    assert ov.overlay_color() == (0, 255, 0)     # falls back to default green


def test_smaller_overlay_placed_at_origin():
    # A 4x4 overlay declared at origin (3,3) (1-based) lands at [2:6, 2:6].
    ds, _ = _ds_with_overlay(4, 4, lit=[(0, 0)], origin=[3, 3])
    mask = ov.extract_overlay_mask(ds, 8, 8)
    assert mask is not None and mask.shape == (8, 8)
    assert mask[2, 2] == 1 and int(mask.sum()) == 1


# ── real 46382 data ──────────────────────────────────────────────────────────
_BASE = (REPO_ROOT / "user_data" / "patients" / "dicom" /
         "1.3.12.2.1107.5.2.46.174759.30000026061404440799700000019")


@pytest.mark.skipif(not _BASE.exists(), reason="46382 study not present")
def test_real_46382_black_chart_slice_has_overlay():
    import pydicom
    fp = _BASE / "101" / "Instance_0006.dcm"
    if not fp.exists():
        pytest.skip("file missing")
    ds = pydicom.dcmread(str(fp), force=True)
    mask = ov.extract_overlay_mask(ds, int(ds.Rows), int(ds.Columns))
    assert mask is not None
    assert int(mask.sum()) > 1000          # the mean-curve table is substantial


# ── backend wiring ───────────────────────────────────────────────────────────
def test_source_backend_composites_overlay():
    src = (FAST_DIR / "pydicom_2d_backend.py").read_text(encoding="utf-8")
    assert "from .dicom_overlay import extract_overlay_mask, overlay_color" in src
    assert "self._overlay_cache" in src
    assert "extract_overlay_mask(ds, sm.rows, sm.cols)" in src
    assert "_apply_overlay" in src
    assert "self._overlay_cache.clear()" in src      # cleared on close_series
