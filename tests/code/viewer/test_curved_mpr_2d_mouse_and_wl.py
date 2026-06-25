# -*- coding: utf-8 -*-
"""Guard: Dental Curve MPR inherits CT W/L + uses the normal 2D mouse mapping.

Pins the two simple-viewer fixes (2026-06-23):
 1. WL inheritance — the curved MPR view receives the source CT viewer's
    Window/Level and applies it (instead of auto-from-scalar-range).
 2. Default mouse — the curved MPR default interactor style is the normal 2D
    viewer's ``AbstractInteractorStyle`` (right=W/L, left+right=pan, middle=zoom,
    left=stack), reused via ``ImageViewerWrapper``; restore-to-default returns to
    it (so ruler mode → default round-trips correctly).

Source-pin (these are VTK/Qt display paths) tolerant of the flaky mount, plus a
cross-file mapping-contract check on ``AbstractInteractorStyle`` (the base whose
behavior the curved MPR now inherits).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CURVED = REPO / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"
TOOLBAR = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
ABSTRACT = REPO / "modules" / "viewer" / "interactor_styles" / "abstract_interactorstyle.py"


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


# --- WL inheritance --------------------------------------------------------
def test_curved_view_accepts_and_applies_source_wl():
    s = _read_complete(CURVED, "def _teardown_curved_mpr_vtk")
    assert "source_window=None" in s and "source_level=None" in s  # __init__ params
    assert "self._source_window" in s and "self._source_level" in s
    assert "_CURVED_MPR_INHERIT_WL" in s
    assert "Inherited source CT W/L" in s  # the override path exists


def test_toolbar_passes_source_ct_wl():
    s = _read_complete(TOOLBAR, "def _show_curved_mpr_result")
    assert "AIPACS_CURVED_MPR_INHERIT_WL" in s
    assert "get_window_level" in s
    assert "source_window=" in s and "source_level=" in s


# --- mouse mapping ---------------------------------------------------------
def test_curved_view_default_style_is_2d_abstract():
    s = _read_complete(CURVED, "def _teardown_curved_mpr_vtk")
    assert "_CURVED_MPR_2D_MOUSE" in s
    assert "def _make_curved_mpr_default_style" in s
    # helper reuses the REAL 2D base style (not a reinvented mapping)
    assert "from modules.viewer.interactor_styles.abstract_interactorstyle import" in s
    assert "AbstractInteractorStyle(image_viewer)" in s
    # default style + restore both go through the helper
    assert "_make_curved_mpr_default_style(self.image_viewer)" in s          # restore
    assert "_make_curved_mpr_default_style(pano_wrapper" in s                 # panoramic default
    assert "_make_curved_mpr_default_style(cross_wrapper" in s                # cross-section default
    # legacy style preserved as the kill-switch fallback
    assert "CurvedMPRInteractorStyle(image_viewer, viewport_id=viewport_id)" in s


# --- cross-file mapping contract (what the inherited base actually maps) ----
def test_abstract_style_mapping_contract():
    s = _read(ABSTRACT)
    assert "self.right_button_down" in s and "self.change_window_level()" in s   # right = W/L
    assert "self.middle_button_down" in s and "self.change_zoom()" in s          # middle = zoom
    assert "check_left_right_pan_start" in s and "turn_on_pan" in s              # left+right = pan
    assert "zoom in" in s and "zoom out" in s                                    # middle up=in / down=out
