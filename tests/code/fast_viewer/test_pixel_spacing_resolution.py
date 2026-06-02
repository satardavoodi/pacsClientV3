"""Tests for DICOM-correct pixel-spacing resolution (measurement calibration).

Guards the fix for the radiography 10x measurement error (patient 44534, DX hand):
projection radiography (CR/DX/MG) omits PixelSpacing (0028,0030) and carries
ImagerPixelSpacing (0018,1164) instead. The viewer must resolve spacing with the
DICOM precedence PixelSpacing -> ImagerPixelSpacing -> NominalScannedPixelSpacing,
and only fall back to (1,1) when none is present.

Pure Python — pydicom only, no Qt / VTK.
"""

from __future__ import annotations

import os
import sys

import pytest
from pydicom.dataset import Dataset

# ── Ensure project root is importable (tests/code/fast_viewer -> repo root) ────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from modules.viewer.fast.dicom_header_scan import (  # noqa: E402
    entry_from_dataset,
    resolve_measurement_pixel_spacing,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _ds(modality="OT", *, pixel_spacing=None, imager=None, nominal=None,
        rows=512, cols=512):
    ds = Dataset()
    ds.Modality = modality
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = 1
    if pixel_spacing is not None:
        ds.PixelSpacing = list(pixel_spacing)
    if imager is not None:
        ds.ImagerPixelSpacing = list(imager)
    if nominal is not None:
        ds.NominalScannedPixelSpacing = list(nominal)
    return ds


# ══════════════════════════════════════════════════════════════════════════════
# resolve_measurement_pixel_spacing — precedence
# ══════════════════════════════════════════════════════════════════════════════

def test_pixel_spacing_used_when_present():
    ds = _ds("MR", pixel_spacing=[0.46484375, 0.46484375])
    assert resolve_measurement_pixel_spacing(ds) == (0.46484375, 0.46484375)


def test_imager_pixel_spacing_fallback_for_projection():
    # DX hand 44534 shape: no PixelSpacing, ImagerPixelSpacing = 0.1 mm.
    ds = _ds("DX", imager=[0.1, 0.1])
    assert resolve_measurement_pixel_spacing(ds) == (0.1, 0.1)


def test_pixel_spacing_wins_over_imager_when_both_present():
    # Vendor-calibrated DX: PixelSpacing must take precedence (DICOM CP-586).
    ds = _ds("DX", pixel_spacing=[0.3, 0.3], imager=[0.1, 0.1])
    assert resolve_measurement_pixel_spacing(ds) == (0.3, 0.3)


def test_nominal_scanned_is_third_fallback():
    ds = _ds("OT", nominal=[0.2, 0.25])
    assert resolve_measurement_pixel_spacing(ds) == (0.2, 0.25)


def test_anisotropic_spacing_preserved_as_row_col():
    ds = _ds("DX", imager=[0.139, 0.143])
    assert resolve_measurement_pixel_spacing(ds) == (0.139, 0.143)


def test_none_when_uncalibrated():
    ds = _ds("DX")  # no spacing tags at all
    assert resolve_measurement_pixel_spacing(ds) is None


def test_zero_or_negative_spacing_rejected():
    assert resolve_measurement_pixel_spacing(_ds("DX", pixel_spacing=[0.0, 0.0])) is None
    assert resolve_measurement_pixel_spacing(_ds("DX", imager=[-0.1, 0.1])) is None
    # invalid PixelSpacing must not block a valid ImagerPixelSpacing fallback
    ds = _ds("DX", pixel_spacing=[0.0, 0.0], imager=[0.1, 0.1])
    assert resolve_measurement_pixel_spacing(ds) == (0.1, 0.1)


# ══════════════════════════════════════════════════════════════════════════════
# entry_from_dataset — the FAST header-scan producer
# ══════════════════════════════════════════════════════════════════════════════

def test_entry_from_dataset_dx_uses_imager_pixel_spacing():
    ds = _ds("DX", imager=[0.1, 0.1], rows=2833, cols=2035)
    entry = entry_from_dataset("dx.dcm", ds)
    assert entry.pixel_spacing == (0.1, 0.1)  # was (1.0, 1.0) before the fix


def test_entry_from_dataset_mr_unchanged():
    ds = _ds("MR", pixel_spacing=[0.46484375, 0.46484375], rows=168, cols=256)
    entry = entry_from_dataset("mr.dcm", ds)
    assert entry.pixel_spacing == (0.46484375, 0.46484375)


def test_entry_from_dataset_uncalibrated_defaults_to_unit():
    # No spacing anywhere -> legacy (1,1) default preserved (behavior unchanged).
    ds = _ds("DX")
    entry = entry_from_dataset("x.dcm", ds)
    assert entry.pixel_spacing == (1.0, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# Real-data regression — patient 44534 (skips when clinical data absent)
# ══════════════════════════════════════════════════════════════════════════════

_REPO = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_DX_44534 = os.path.join(
    _REPO, "user_data", "patients", "dicom",
    "1.2.826.0.1.3680043.2.876.14581.1.5.1.20260602114328.0.98", "1", "Instance_0001.dcm",
)
_MR_44534 = os.path.join(
    _REPO, "user_data", "patients", "dicom",
    "1.3.12.2.1107.5.2.46.174759.30000026060104193663400000099", "3", "Instance_0001.dcm",
)


@pytest.mark.skipif(not os.path.isfile(_DX_44534), reason="44534 DX data not present")
def test_real_44534_dx_resolves_to_detector_pitch():
    import pydicom
    ds = pydicom.dcmread(_DX_44534, stop_before_pixels=True, force=True)
    assert "PixelSpacing" not in ds  # confirms the projection-radiography case
    assert resolve_measurement_pixel_spacing(ds) == (0.1, 0.1)


@pytest.mark.skipif(not os.path.isfile(_MR_44534), reason="44534 MR data not present")
def test_real_44534_mr_unchanged():
    import pydicom
    ds = pydicom.dcmread(_MR_44534, stop_before_pixels=True, force=True)
    assert resolve_measurement_pixel_spacing(ds) == (0.46484375, 0.46484375)
