# -*- coding: utf-8 -*-
"""Guard: Dental Curve MPR dual-arch / oblique panoramic (anterior-inclination fix,
2026-07-01).

Forward-inclined anterior teeth lose crown/apex in a single-arch panoramic because the
reslice samples straight down the Binormal. With a second (apical) arch, the per-column
crown->apex vector is the tooth long axis; `compute_oblique_slice_axes` tilts the vertical
sampling axis to follow it — keeping the basis orthonormal + right-handed and the arch
tangent (hence along-arch geometry / measurements) unchanged. Flag-gated
(AIPACS_CURVED_MPR_DUAL_ARCH), default off; no apical arch => byte-identical legacy output.

The tilt MATH is unit-tested headless (numpy only, mirroring the engine, kept in lock-step
by the source-pins); the VTK wiring is source-pinned (engine uses VTK + a large module ->
not importable here), matching test_curved_mpr_panoramic_quality.py.
"""
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "modules" / "mpr" / "zeta_mpr" / "curved_mpr.py"
TOOLBAR = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
PRO_ENGINE = REPO / "modules" / "dental_imaging" / "core" / "curved_reconstruction.py"
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


# --- mirror of the engine's pure helpers (lock-stepped by the source-pins) --------
def _compute_oblique_slice_axes(tangent, normal, binormal, tilt_vec, min_tilt=0.5):
    t = np.asarray(tangent, dtype=float)
    n = np.asarray(normal, dtype=float)
    b = np.asarray(binormal, dtype=float)
    v = np.asarray(tilt_vec, dtype=float)
    t_norm = np.linalg.norm(t)
    if t_norm < 1e-9:
        return n, b
    t = t / t_norm
    v_plane = v - np.dot(v, t) * t
    mag = np.linalg.norm(v_plane)
    if mag < float(min_tilt):
        return n, b
    b_new = v_plane / mag
    if np.dot(b_new, b) < 0.0:
        b_new = -b_new
    n_new = np.cross(b_new, t)
    n_mag = np.linalg.norm(n_new)
    if n_mag < 1e-9:
        return n, b
    return n_new / n_mag, b_new


def _resample_polyline_arclength(points, n):
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(pts) == 0 or n <= 0:
        return np.zeros((max(0, int(n)), 3), dtype=float)
    if len(pts) == 1 or n == 1:
        return np.repeat(pts[:1], int(n), axis=0)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total < 1e-9:
        return np.repeat(pts[:1], int(n), axis=0)
    targets = np.linspace(0.0, total, int(n))
    out = np.empty((int(n), 3), dtype=float)
    for a in range(3):
        out[:, a] = np.interp(targets, cum, pts[:, a])
    return out


# right-handed frame matching the engine (X=normal, Y=binormal, Z=tangent; normal x binormal = tangent)
_T = np.array([1.0, 0.0, 0.0])   # along-arch tangent
_N = np.array([0.0, 1.0, 0.0])   # radial / thickness
_B = np.array([0.0, 0.0, 1.0])   # vertical (superior-inferior)


def test_frame_convention_is_right_handed():
    assert np.allclose(np.cross(_N, _B), _T)


def test_oblique_axes_follow_crown_to_apex_and_stay_orthonormal():
    # apex leans radially (+Y) and superiorly (+Z) relative to the crown -> in-slice-plane tilt
    tilt = np.array([0.0, 3.0, 10.0])   # mm, no along-arch (X) component
    n_new, b_new = _compute_oblique_slice_axes(_T, _N, _B, tilt)
    # vertical axis now follows the tooth long axis
    assert np.allclose(b_new, tilt / np.linalg.norm(tilt), atol=1e-6)
    # orthonormal
    assert abs(np.dot(n_new, b_new)) < 1e-9
    assert abs(np.linalg.norm(n_new) - 1.0) < 1e-9
    assert abs(np.linalg.norm(b_new) - 1.0) < 1e-9
    # right-handed with the SAME tangent (normal' x binormal' == tangent) -> along-arch unchanged
    assert np.allclose(np.cross(n_new, b_new), _T, atol=1e-6)
    # superior sense preserved (still points "up")
    assert b_new[2] > 0.0


def test_along_arch_tilt_component_is_dropped():
    # a tilt with a big along-arch (X) part must NOT skew the arch: only the in-plane part tilts
    tilt = np.array([50.0, 0.0, 10.0])
    n_new, b_new = _compute_oblique_slice_axes(_T, _N, _B, tilt)
    # the X (tangent) component is projected out -> b_new has no tangent component
    assert abs(np.dot(b_new, _T)) < 1e-9
    assert np.allclose(np.cross(n_new, b_new), _T, atol=1e-6)


def test_degenerate_tilts_leave_axes_unchanged():
    # zero tilt, pure along-arch tilt, and sub-threshold tilt all fall back to vertical
    for tilt in (np.zeros(3), np.array([25.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.2])):
        n_new, b_new = _compute_oblique_slice_axes(_T, _N, _B, tilt, min_tilt=0.5)
        assert np.allclose(n_new, _N)
        assert np.allclose(b_new, _B)


def test_downward_apex_keeps_superior_orientation():
    # mandibular-style: apex is INFERIOR to crown (-Z). The tilt must still point "up".
    tilt = np.array([0.0, 2.0, -10.0])
    _n_new, b_new = _compute_oblique_slice_axes(_T, _N, _B, tilt)
    assert b_new[2] > 0.0                       # superior sense preserved
    assert np.allclose(np.cross(_compute_oblique_slice_axes(_T, _N, _B, tilt)[0], b_new), _T, atol=1e-6)


def test_resample_polyline_arclength():
    out = _resample_polyline_arclength([[0, 0, 0], [10, 0, 0]], 11)
    assert out.shape == (11, 3)
    assert np.allclose(out[0], [0, 0, 0])
    assert np.allclose(out[-1], [10, 0, 0])
    assert np.allclose(out[5], [5, 0, 0])       # uniform arc-length
    one = _resample_polyline_arclength([[1, 2, 3], [4, 5, 6]], 1)
    assert one.shape == (1, 3) and np.allclose(one[0], [1, 2, 3])


# --- engine wiring source-pins (keep the mirror above honest) ---------------------
def test_engine_exposes_dual_arch_helpers_and_flag():
    s = _read(ENGINE)
    assert "def compute_oblique_slice_axes" in s
    assert "def resample_polyline_arclength" in s
    assert "AIPACS_CURVED_MPR_DUAL_ARCH" in s
    # the exact tilt math the mirror depends on
    assert "v_plane = v - np.dot(v, t) * t" in s
    assert "n_new = np.cross(b_new, t)" in s


def test_engine_panoramic_accepts_apical_and_gate_is_default_off():
    s = _read(ENGINE)
    # optional apical param threaded into the panoramic generator + the wrapper
    assert "apical_origins: Optional[np.ndarray] = None" in s
    assert "def set_apical_centerline" in s
    # oblique only when flag on AND an aligned apical curve supplied -> None/flag-off = legacy
    assert "use_oblique = bool(_DUAL_ARCH) and apical_origins is not None" in s
    assert "apical_origins=apical_origins" in s


# --- panel (simple Dental Curve MPR) apical-pick wiring source-pins ---------------
def test_toolbar_wires_optional_apical_pick_default_on():
    s = _read(TOOLBAR)
    # flag-gated UI, DEFAULT ON (user-validated); AIPACS_CURVED_MPR_DUAL_ARCH=0 = legacy
    assert 'os.environ.get("AIPACS_CURVED_MPR_DUAL_ARCH", "1") != "0"' in s
    assert "self._dual_arch_ui" in s
    # two-arch orchestration over the single picker + generation threading
    assert "def _set_curved_mpr_active_arch" in s
    assert "self._crown_arch_points" in s and "self._apical_arch_points" in s
    assert "def _generate_curved_mpr_from_points(self, points, image_data, apical_points=None)" in s
    assert "generator.set_apical_centerline(apical_points)" in s
    assert "apical_points=apical_points" in s


def test_engine_dual_arch_flag_default_on():
    s = _read(ENGINE)
    assert '_DUAL_ARCH = os.environ.get("AIPACS_CURVED_MPR_DUAL_ARCH", "1") != "0"' in s


# --- professional Dental Imaging module (Advanced Analysis) source-pins ------------
def test_professional_engine_oblique_wiring_default_on():
    s = _read(PRO_ENGINE)
    # dual-arch DEFAULT ON for the pro module
    assert '_DENTAL_DUAL_ARCH = os.environ.get("AIPACS_DENTAL_DUAL_ARCH", "1") != "0"' in s
    # per-column oblique reuse of the shared helper + apical alignment
    assert "compute_oblique_slice_axes" in s
    assert "def _apical_origins_for" in s
    assert "apical_origins=apical_origins" in s
    # both public builders accept the optional apical arch
    assert "apical_world_points=None" in s


def test_professional_workspace_apical_pick_wiring():
    s = _read(WORKSPACE)
    assert 'os.environ.get("AIPACS_DENTAL_DUAL_ARCH", "1") != "0"' in s
    assert "self._apical_arch_points" in s and 'self._active_arch = "crown"' in s
    for sym in ("def _toggle_apical_arch", "def _apical_world_points",
                "def _apical_display_points", "def get_apical_world_points",
                "def _active_arch_list"):
        assert sym in s, f"missing {sym}"
    # apical arch is threaded into the panoramic build + the recon cache key
    assert "apical_world_points=self._apical_world_points()" in s
