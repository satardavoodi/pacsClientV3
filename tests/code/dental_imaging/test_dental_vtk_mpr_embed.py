# -*- coding: utf-8 -*-
"""Guard: Dental Imaging embeds the standard (Zeta) MPR VTK pipeline (2026-06-23).

The numpy ortho-orientation approach didn't reliably match standard MPR, so the module
now embeds the SAME ``StandardMPRViewer`` the toolbar 'MPR' button opens — constructed
the SAME way (canonicalize → StandardMPRViewer(vtk_image_data, parent, ww, wc)) — so
geometry / orientation / L-R / scroll / crosshairs are identical to standard MPR (the
unified-MPR directive). Flag `AIPACS_DENTAL_VTK_MPR` (default on; static-QImage grid is
the fallback). Clean VTK teardown on reload + close. The two-level split still holds: the
PROFESSIONAL module reuses the STANDARD MPR viewer, never the SIMPLE curved engine.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def test_embeds_standard_mpr_viewer():
    s = _read(WORKSPACE)
    assert "AIPACS_DENTAL_VTK_MPR" in s
    assert "from modules.mpr.zeta_mpr.mpr_viewer.widget import StandardMPRViewer" in s
    assert "StandardMPRViewer(" in s
    # constructed like toggle_zeta_mpr: canonicalize (flag-gated) then the viewer
    assert "canonicalize_volume" in s and "canonicalize_enabled" in s
    for sym in ("def _build_vtk_mpr", "def _mount_vtk_mpr", "def _teardown_vtk_mpr", "def closeEvent"):
        assert sym in s, f"missing {sym}"


def test_clean_vtk_teardown_on_reload_and_close():
    s = _read(WORKSPACE)
    # teardown finalizes the viewer (cleanup) and is called on reload + close
    assert "viewer.cleanup()" in s or ".cleanup()" in s
    assert "self._teardown_vtk_mpr()" in s
    # guarded against already-deleted Qt objects (the teardown-race class)
    assert "except RuntimeError" in s


def test_two_level_split_preserved():
    # professional module embeds the STANDARD MPR viewer, never the SIMPLE curved engine
    s = _read(WORKSPACE)
    assert "zeta_mpr.curved_mpr" not in s
    assert "mpr.curved_mpr" not in s
    # falls back to the static grid (no hard dependency on VTK succeeding)
    assert "_render_ortho_previews" in s
