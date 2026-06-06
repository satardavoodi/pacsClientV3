"""
Headless math tests for the Zeta MPR canonicalization pre-filter.

These tests import ONLY the pure-geometry helpers (numpy only) — no VTK, no Qt,
no render window — so they run in the offscreen/headless CI without segfaulting
the VTK viewer suite. The VTK resampling path (`canonicalize_volume`) is gated
OFF by default and is validated live (CT + 44534 shoulder MR), not here.

Fixtures are the real ImageOrientationPatient values measured on disk
(see docs/reports/ZETA_MPR_ORIENTATION_INVESTIGATION_2026-06-02.md §1).
"""

import os

import numpy as np
import pytest

from modules.mpr.zeta_mpr._mpr_canonicalize import (
    canonicalize_enabled,
    classify_acquisition_plane,
    compute_canonical_reslice_axes,
    decode_direction_field_data,
    needs_canonicalization,
    parse_iop,
    slice_axis_sign,
)

# --- Real measured IOPs ----------------------------------------------------
IOP_CT_AXIAL = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
IOP_MR_TRA = [0.883, -0.014, -0.469, 0.0, 0.9995, -0.031]      # 44534 oblique-axial
IOP_MR_COR = [0.884, -0.092, -0.459, -0.464, -0.050, -0.884]   # 44534 coronal
IOP_MR_SAG = [-0.018, 0.999, -0.045, -0.461, -0.048, -0.886]   # 44534 sagittal


def _to_iop_matrix_reference(iop):
    """Replica of pydicom_lazy_volume._to_iop_matrix (columns=row,col,normal; row1 negated)."""
    row = np.asarray(iop[0:3], float)
    col = np.asarray(iop[3:6], float)
    row = row / np.linalg.norm(row)
    col = col / np.linalg.norm(col)
    normal = np.cross(row, col)
    normal = normal / np.linalg.norm(normal)
    M = np.eye(4)
    M[0:3, 0] = row
    M[0:3, 1] = col
    M[0:3, 2] = normal
    M[1, 0:3] = -M[1, 0:3]
    return M


# --- Plane classification --------------------------------------------------
@pytest.mark.parametrize("iop,expected", [
    (IOP_CT_AXIAL, "axial"),
    (IOP_MR_TRA, "axial"),      # oblique but Z-dominant
    (IOP_MR_COR, "coronal"),
    (IOP_MR_SAG, "sagittal"),
])
def test_classify_acquisition_plane(iop, expected):
    plane, axis, dominance = classify_acquisition_plane(iop)
    assert plane == expected
    assert 0.0 <= dominance <= 1.0


# --- needs_canonicalization (CT no-op vs oblique) --------------------------
def test_ct_axial_is_noop():
    assert needs_canonicalization(IOP_CT_AXIAL) is False


@pytest.mark.parametrize("iop", [IOP_MR_TRA, IOP_MR_COR, IOP_MR_SAG])
def test_oblique_mr_needs_canonicalization(iop):
    assert needs_canonicalization(iop) is True


def test_near_axial_within_tolerance_is_noop():
    # ~1 degree tilt should still be treated as axis-aligned at the 2-degree tol.
    theta = np.deg2rad(1.0)
    iop = [np.cos(theta), 0.0, np.sin(theta), 0.0, 1.0, 0.0]
    assert needs_canonicalization(iop, tol_deg=2.0) is False


# --- decode_direction_field_data round-trip -------------------------------
@pytest.mark.parametrize("iop", [IOP_CT_AXIAL, IOP_MR_TRA, IOP_MR_COR, IOP_MR_SAG])
def test_decode_round_trip(iop):
    M = _to_iop_matrix_reference(iop)
    values16 = [float(M[r, c]) for r in range(4) for c in range(4)]
    row, col, normal = decode_direction_field_data(values16)

    exp_row, exp_col, exp_normal = parse_iop(iop)
    assert np.allclose(row, exp_row, atol=1e-6)
    assert np.allclose(col, exp_col, atol=1e-6)
    assert np.allclose(normal, exp_normal, atol=1e-6)


# --- reslice axes properties ----------------------------------------------
@pytest.mark.parametrize("iop", [IOP_CT_AXIAL, IOP_MR_TRA, IOP_MR_COR, IOP_MR_SAG])
def test_reslice_axes_orthonormal_and_maps_normal_to_z(iop):
    row, col, normal = parse_iop(iop)
    axes = compute_canonical_reslice_axes(row, col, normal)

    # Orthonormal, right-handed.
    assert np.allclose(axes @ axes.T, np.eye(3), atol=1e-6)
    assert pytest.approx(1.0, abs=1e-6) == float(np.linalg.det(axes))

    # The slice normal maps onto the output +Z axis (=> reconstructed axial).
    mapped = axes @ np.asarray(normal, float)
    assert np.allclose(mapped, [0.0, 0.0, 1.0], atol=1e-6)

    # Row maps to +X exactly (row is the Gram-Schmidt anchor).
    assert np.allclose(axes @ np.asarray(row, float), [1.0, 0.0, 0.0], atol=1e-6)
    # Col maps to ~+Y. The fixtures are rounded to 3-4 decimals so the raw col is
    # not perfectly orthogonal to row (row.col ~ 5e-4); allow that residual.
    assert np.allclose(axes @ np.asarray(col, float), [0.0, 1.0, 0.0], atol=5e-3)


def test_slice_axis_sign_override_flips_z():
    row, col, normal = parse_iop(IOP_MR_TRA)
    axes_pos = compute_canonical_reslice_axes(row, col, normal, slice_axis_lps=normal)
    axes_neg = compute_canonical_reslice_axes(row, col, normal, slice_axis_lps=-np.asarray(normal))
    # +normal maps to +Z; -normal maps to -Z (scroll direction inverted).
    assert np.allclose(axes_pos @ normal, [0, 0, 1], atol=1e-6)
    assert np.allclose(axes_neg @ normal, [0, 0, -1], atol=1e-6)


# --- feature flag ----------------------------------------------------------
def test_slice_axis_sign():
    n = [0.0, 0.0, 1.0]
    assert slice_axis_sign([0, 0, 0], [0, 0, 10], n) == 1     # advances +Z (+normal)
    assert slice_axis_sign([0, 0, 0], [0, 0, -10], n) == -1   # advances -Z (-normal)
    # Oblique normal: sign follows the projection onto the normal.
    nn = [0.470, 0.027, 0.883]
    assert slice_axis_sign([0, 0, 0], [4.7, 0.27, 8.83], nn) == 1
    assert slice_axis_sign([0, 0, 0], [-4.7, -0.27, -8.83], nn) == -1


def test_reslice_axes_sign_uses_slice_axis_lps():
    # With slice_axis_lps = -normal, output +Z maps to -normal => scroll inverted.
    row, col, n = parse_iop(IOP_CT_AXIAL)
    axes = compute_canonical_reslice_axes(row, col, n, slice_axis_lps=[-x for x in n])
    assert np.allclose(axes @ np.asarray(n, float), [0, 0, -1], atol=1e-6)


@pytest.fixture
def _isolated_user_config(monkeypatch, tmp_path):
    """Isolate canonicalize_enabled() from the LIVE user config.

    Test-isolation fix (2026-06-04, RELIABILITY_STABILITY_REVIEW §13): when
    the env var is unset/empty the function falls through to
    `<USER_DATA_ROOT>/config/zeta_mpr.json` — and this workstation
    intentionally runs with {"canonicalize": true} (enabled 06-03 after live
    validation), which made these tests fail against user state rather than
    code. Point USER_DATA_ROOT at an empty temp dir for the test.
    """
    import PacsClient.utils.data_paths as _dp
    monkeypatch.setattr(_dp, "USER_DATA_ROOT", str(tmp_path), raising=False)


def test_flag_default_off(monkeypatch, _isolated_user_config):
    monkeypatch.delenv("AIPACS_ZETA_MPR_CANONICALIZE", raising=False)
    assert canonicalize_enabled() is False


def test_flag_config_file_toggle(monkeypatch, tmp_path, _isolated_user_config):
    """The config-file fallback itself still works (covers the live setup)."""
    import json as _json
    monkeypatch.delenv("AIPACS_ZETA_MPR_CANONICALIZE", raising=False)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "zeta_mpr.json").write_text(
        _json.dumps({"canonicalize": True}), encoding="utf-8")
    assert canonicalize_enabled() is True
    # Explicit env OFF must beat the config file.
    monkeypatch.setenv("AIPACS_ZETA_MPR_CANONICALIZE", "0")
    assert canonicalize_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("", False), ("off", False), ("no", False),
])
def test_flag_env_parsing(monkeypatch, val, expected, _isolated_user_config):
    monkeypatch.setenv("AIPACS_ZETA_MPR_CANONICALIZE", val)
    assert canonicalize_enabled() is expected
