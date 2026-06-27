# -*- coding: utf-8 -*-
"""Guard: annotation CREATION tools lock out existing-annotation selection (2026-06-27).

Bug: after drawing one measurement the tool turns off and the existing annotation is
correctly editable in the default/select style. But when the user activates a creation
tool again (new ruler / arrow / angle / circle / ROI / two-line angle) and tries to draw
a new annotation over or near an existing one, the FIRST click hit-tested the existing
annotation and grabbed it for dragging instead of starting the new annotation — so the
new annotation could not be drawn (e.g. a crossed measurement, or a circle over a line).

Fix: a single flag-gated predicate ``_annotation_creation_armed()`` on
``AbstractInteractorStyle`` (True while a creation tool is armed, i.e. ``is_active``);
every existing-annotation hit-test returns "no target" while armed, so the click/hover is
reserved for the new annotation. Existing annotations stay selectable/editable only in the
default/select style (which never arms). Kill switch:
``AIPACS_ANNOTATION_CREATION_LOCKOUT=0`` restores the legacy behaviour.

Source-pin (the interactor styles are VTK-heavy and can't run offscreen) + source<->mirror
parity (the viewer ``interactor_styles`` tree is plugin-mirrored).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC_DIR = REPO / "modules" / "viewer" / "interactor_styles"
MIRROR_DIR = (
    REPO / "builder" / "plugin package" / "packages" / "viewer" / "payload"
    / "python" / "modules" / "viewer" / "interactor_styles"
)

GUARD = "if self._annotation_creation_armed():"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated read of {p.name}; run on Windows / clean checkout")
    return b.decode("utf-8", "replace")


def _guard_in_method(src: str, method_def: str) -> bool:
    """True when GUARD appears inside the body of ``method_def`` (before the next def)."""
    i = src.find(method_def)
    if i == -1:
        return False
    nxt = src.find("\n    def ", i + len(method_def))
    body = src[i: nxt if nxt != -1 else len(src)]
    return GUARD in body


def _assert_abstract(src: str):
    # Flag (default on) + predicate
    assert "_ANNOTATION_CREATION_LOCKOUT" in src
    assert '"AIPACS_ANNOTATION_CREATION_LOCKOUT", "1"' in src
    assert "def _annotation_creation_armed(self)" in src
    assert "getattr(self, 'is_active', False)" in src
    # The shared base hit-test is gated
    assert _guard_in_method(src, "def _find_any_drag_target(self, mouse_pos):"), \
        "base _find_any_drag_target must early-return None while a creation tool is armed"


# (filename, [method defs that must contain the armed guard])
_TOOL_HITTESTS = {
    "ruler_interactorstyle.py": ["def _find_drag_target(self, mouse_pos):"],
    "arrow_interactorstyle.py": ["def _find_drag_target(self, mouse_pos):"],
    "angle_interactorstyle.py": ["def _find_drag_target(self, mouse_pos):"],
    "two_line_angle_interactorstyle.py": ["def _find_drag_target(self, mouse_pos):"],
    "roi_interactorstyle.py": [
        "def _find_drag_target(self, mouse_pos):",   # RoiInteractorStyle (polygon)
        "def _get_handle_hit(self, mouse_pos):",     # CircleRoiInteractorStyle
        "def _get_edge_hit(self, mouse_pos):",       # CircleRoiInteractorStyle
    ],
}


def _assert_tool(fname: str, src: str):
    for method_def in _TOOL_HITTESTS[fname]:
        assert _guard_in_method(src, method_def), \
            f"{fname}: {method_def} must early-return None while a creation tool is armed"


def _assert_roi_circle_arm(src: str):
    """ROI + Circle have no native is_active; they must set it so the predicate works."""
    # RoiInteractorStyle.activate turns the contour widget on and arms.
    assert "self.active_widget.On()\n        self.is_active = True" in src
    # CircleRoiInteractorStyle.activate resets then arms.
    assert "self._reset_active_widget()\n        self.is_active = True" in src


# ---------------------------------------------------------------- source

def test_source_abstract_has_predicate_and_gate():
    _assert_abstract(_read(SRC_DIR / "abstract_interactorstyle.py"))


@pytest.mark.parametrize("fname", sorted(_TOOL_HITTESTS))
def test_source_tool_hittests_gated(fname):
    _assert_tool(fname, _read(SRC_DIR / fname))


def test_source_roi_circle_arm_is_active():
    _assert_roi_circle_arm(_read(SRC_DIR / "roi_interactorstyle.py"))


# ---------------------------------------------------------------- mirror parity

def test_mirror_abstract_has_predicate_and_gate():
    _assert_abstract(_read(MIRROR_DIR / "abstract_interactorstyle.py"))


@pytest.mark.parametrize("fname", sorted(_TOOL_HITTESTS))
def test_mirror_tool_hittests_gated(fname):
    _assert_tool(fname, _read(MIRROR_DIR / fname))


def test_mirror_roi_circle_arm_is_active():
    _assert_roi_circle_arm(_read(MIRROR_DIR / "roi_interactorstyle.py"))
