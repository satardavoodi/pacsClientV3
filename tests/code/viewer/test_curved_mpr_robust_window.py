# -*- coding: utf-8 -*-
"""Guard: Dental Curve MPR uses robust per-image Window/Level (2026-06-23).

Pins the reconstruction-contrast fix: the washed-out look came from a full
min/max window applied to BOTH the raw cross-section and the mean-projection
panoramic (different intensity domains). The fix windows each image from its OWN
1st–99th percentile (and keeps the CT-WL inherit for the cross-section).

Source-pin (VTK/Qt display path, flaky mount) + a pure percentile contract check,
and an optional real-VTK behavioural check of the helper when VTK imports.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CURVED = REPO / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


def _read_complete(p: Path, anchor: str) -> str:
    s = _read(p)
    if anchor not in s:
        pytest.skip(f"{p.name} mirror truncated (anchor missing); run on Windows")
    return s


# --- source-pin ------------------------------------------------------------
def test_robust_window_flag_and_helper_present():
    s = _read_complete(CURVED, "def _teardown_curved_mpr_vtk")
    assert "_CURVED_MPR_ROBUST_WL" in s
    assert "def _robust_window_level" in s
    assert "np.percentile" in s  # data-driven window, not min/max


def test_panoramic_and_crosssection_windowed_separately():
    s = _read_complete(CURVED, "def _teardown_curved_mpr_vtk")
    # cross-section uses its own window...
    assert "cross_window" in s and "cross_level" in s
    # ...and the panoramic uses its OWN window (not the cross/CT one)
    assert "pano_window" in s and "pano_level" in s
    assert "SetColorWindow(pano_window)" in s
    # CT-WL inherit retained for the cross-section
    assert "Inherited source CT W/L" in s


# --- pure percentile contract (no import) ----------------------------------
def _percentile_window(values, lo=1.0, hi=99.0):
    import numpy as np
    a = np.asarray(values, dtype=float)
    plo = float(np.percentile(a, lo))
    phi = float(np.percentile(a, hi))
    return phi - plo, (phi + plo) / 2.0


def test_percentile_window_ignores_outliers():
    import numpy as np
    ramp = list(np.linspace(0, 1000, 1000))
    full = ramp + [-3000, 40000]  # air + metal/enamel outliers
    w_robust, l_robust = _percentile_window(full)
    w_full = max(full) - min(full)  # naive min/max window
    # Robust window is FAR tighter than min/max → real diagnostic contrast.
    assert w_robust < w_full / 10
    assert 0 < l_robust < 1000


# --- optional real-helper behaviour (skips if VTK/Qt unavailable) ----------
def test_robust_window_level_helper_on_real_image():
    try:
        import numpy as np
        import vtk
        from vtkmodules.util import numpy_support
        from modules.mpr.curved_mpr.curved_mpr_panoramic_view import _robust_window_level
    except Exception as exc:  # heavy Qt/VTK import not available here
        pytest.skip(f"VTK/module import unavailable: {exc}")

    img = vtk.vtkImageData()
    img.SetDimensions(10, 10, 10)
    data = np.linspace(0, 1000, 1000).astype(np.int16)
    data[0] = -3000      # air outlier
    data[-1] = 30000     # metal/enamel outlier
    img.GetPointData().SetScalars(numpy_support.numpy_to_vtk(data, deep=True))

    window, level = _robust_window_level(img)
    # Full min/max would be ~33000; robust ignores the two outliers.
    assert window < 2000
    assert 300 < level < 700
