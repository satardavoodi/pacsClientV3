# -*- coding: utf-8 -*-
"""Guard: ruler measurement (line + value) renders immediately in Dental Curve MPR
(2026-06-23).

Bug: in the Curved/FAST MPR the viewer is an ``ImageViewerWrapper`` whose
``vtk_widget`` is the raw ``QVTKRenderWindowInteractor`` (not a ``VTKWidget``), so
``auto_deactivate_tool()``'s deferred ``update_slice()`` + render never runs after the
2nd ruler click — the green line + value stay hidden until the ruler is toggled. Fix:
on completion, force ``update_slice()`` + a render-window refresh (the same refresh the
toggle performs).

Source-pin (the interactor is VTK-heavy and can't run offscreen) + source↔mirror parity
(`ruler_interactorstyle.py` is plugin-mirrored).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "modules" / "viewer" / "interactor_styles" / "ruler_interactorstyle.py"
MIRROR = (
    REPO / "builder" / "plugin package" / "packages" / "viewer" / "payload"
    / "python" / "modules" / "viewer" / "interactor_styles" / "ruler_interactorstyle.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


def _assert_fix_present(src: str):
    # flag, default on
    assert "_RULER_RENDER_ON_COMPLETE" in src
    assert '"AIPACS_RULER_RENDER_ON_COMPLETE", "1"' in src
    # the completion path forces the re-show + render the toggle used to do
    assert "self.update_slice()" in src
    assert "self.image_viewer.GetRenderWindow()" in src
    assert "render_window.Render()" in src
    # the render block lives in place_point_event, AFTER auto_deactivate_tool()
    body = src[src.find("def place_point_event"):]
    i_complete = body.find("self.auto_deactivate_tool()")
    i_guard = body.find("if _RULER_RENDER_ON_COMPLETE:")
    assert i_complete != -1 and i_guard != -1 and i_guard > i_complete


def test_source_renders_ruler_on_complete():
    _assert_fix_present(_read(SRC))


def test_mirror_matches_source_fix():
    _assert_fix_present(_read(MIRROR))
