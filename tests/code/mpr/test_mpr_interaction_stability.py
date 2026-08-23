"""Guards: MPR interaction stability — jitter, latency, tool state (2026-08-23).

Owner report, verbatim: *"When the mouse cursor moves over the center of the MPR
crosshair, the cursor/crosshair begins to shake or jitter"*, *"when starting to
rotate the VRT image, there is currently a small initial delay"*, and *"when MPR
is active and we select certain toolbar tools the MPR view closes"*.

Explicitly NOT a geometry change — the owner confirmed the geometry is correct,
and `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`
records why touching the oblique camera would regress v1.09.Fix-E.

Every window here is bounded at the next ``def``, never a fixed character count:
that trap has produced bogus failures in this suite at least four times.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_MPRV = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
INTERACT = _MPRV / "_mpr_crosshair_interact.py"
RENDER = _MPRV / "_mpr_crosshair_render.py"
LAYOUT = _MPRV / "_mpr_layout.py"
OBLIQUE = _MPRV / "_mpr_oblique.py"
ORIENT = _MPRV / "_mpr_orientation.py"
STYLES = _MPRV / "_interactor_styles.py"
TOOLBAR = (ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "patient_toolbar" / "toolbar_manager.py")


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _def_body(src: str, marker: str) -> str:
    """Source of one definition, bounded at the next definition AT THE SAME
    INDENT. Same-indent matters: bounding at any ``class`` would stop at a
    nested worker class, and bounding at a fixed character count is the trap
    that has produced bogus failures in this suite four times."""
    start = src.index(marker)
    indent = len(marker) - len(marker.lstrip("\n").lstrip())
    pat = re.compile(r"\n" + " " * indent + r"(?:@|def |class )")
    m = pat.search(src, start + len(marker))
    return src[start:m.start() if m else len(src)]


def _code_only(body: str) -> str:
    """Drop whole-line ``#`` comments so an assertion cannot be satisfied — or
    defeated — by prose. The comments here deliberately quote the old API."""
    return "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
    )


# ---------------------------------------------------------------------------
# 1. Crosshair hover jitter
# ---------------------------------------------------------------------------

def test_hover_never_uses_the_deferred_vtk_cursor_api():
    """THE jitter bug. The hover path drove the cursor through Qt (synchronous)
    AND `RenderWindow.SetCurrentCursor` (applied a full event-loop turn later by
    QVTKRenderWindowInteractor's `QTimer.singleShot(0, ShowCursor)`). In the
    centre zone the two writes DISAGREED — Qt got "no cursor", VTK got
    "crosshair" — so the pointer alternated between two glyphs every frame."""
    body = _code_only(_def_body(_src(INTERACT), "    def check_handle_hover("))
    assert "SetCurrentCursor" not in body, (
        "the hover path must use exactly ONE cursor API; SetCurrentCursor is "
        "applied a turn late and fought the synchronous Qt write"
    )
    assert "_apply_hover_cursor(" in body


def test_hover_cursor_is_applied_only_when_it_changes():
    body = _def_body(_src(INTERACT), "    def _apply_hover_cursor(")
    assert "_last_hover_shape" in body
    assert "return" in body, "an unchanged shape must short-circuit"
    assert "_set_view_cursor" in body


def test_hover_zones_have_hysteresis():
    """The 20 px centre disc is entirely inside the 15 px line bands
    (20/sqrt(2) = 14.1 < 15), so without a dead-band a 1 px move flips the zone
    — and display coordinates are integers, so hand tremor is 1 px."""
    body = _def_body(_src(INTERACT), "    def check_handle_hover(")
    assert "center_limit" in body and "line_limit" in body
    assert "26" in body and "19" in body, "exit radii must exceed the enter radii"
    assert "_last_hover_zone" in body


def test_hover_state_is_cleared_on_release():
    body = _def_body(_src(INTERACT), "    def on_left_button_release(")
    assert "_reset_hover_cursor_state()" in body, (
        "a drag can move the cursor behind the hover path's back; the cached "
        "shape must not suppress the first post-drag update"
    )


def test_every_drag_branch_requires_the_button():
    """`dragging_center` lives on the PARENT and is shared by all three panes.
    A missed release would let a buttonless hover keep re-centring the crosshair
    on the pointer — the crosshair visibly chasing the mouse."""
    body = _def_body(_src(INTERACT), "    def on_mouse_move(")
    for guard in (
        "if self.left_button_down and self.dragging_handle and self.current_handle:",
        "if self.left_button_down and self.dragging_line:",
        "if self.left_button_down and self.parent.dragging_center:",
    ):
        assert guard in body, f"missing button guard: {guard}"


def test_hover_kill_switch_defaults_on():
    src = _src(INTERACT)
    assert 'os.getenv("AIPACS_MPR_HOVER_STABLE", "1")' in src


def test_all_hover_shapes_resolve_to_a_real_cursor():
    body = _def_body(_src(RENDER), "    def _get_hover_cursor(")
    src = _src(RENDER)
    assert "_HOVER_CURSOR_SHAPES" in src
    for shape in ("arrow", "cross", "sizeall", "sizever", "sizehor"):
        assert f"'{shape}'" in src, f"hover shape {shape} has no QCursor mapping"
    assert "ArrowCursor" in body, "an unknown shape must fall back, not crash"


# ---------------------------------------------------------------------------
# 2. Interaction latency
# ---------------------------------------------------------------------------

def test_setting_the_already_active_view_is_a_noop():
    """Every press and every wheel notch called `_set_active_view` TWICE (Qt
    event filter, then the interactor style). Each call restyled all four view
    containers, and a container stylesheet change re-polishes its
    QVTKRenderWindowInteractor child, whose paintEvent is a full Render()."""
    body = _def_body(_src(LAYOUT), "    def _set_active_view(")
    assert "_active_view_noop_guard()" in body
    assert "return" in body
    guard = _def_body(_src(LAYOUT), "def _active_view_noop_guard(")
    assert 'os.getenv("AIPACS_MPR_ACTIVE_VIEW_NOOP_GUARD", "1")' in guard


def test_highlight_restyles_only_the_two_containers_that_changed():
    body = _def_body(_src(LAYOUT), "    def _update_view_highlights(")
    assert "changed_only" in body
    assert "self._view_containers" in body
    # Called with no argument it must still style everything — _register_view
    # depends on that for a newly added pane.
    assert "names = self._view_containers.keys()" in body


def test_vrt_press_arms_rotation_before_restyling():
    """`super().OnLeftButtonDown()` is what calls StartRotate(), which switches
    the window from StillUpdateRate to DesiredUpdateRate. Restyling first meant
    the queued repaint ran at STILL quality before rotation was armed."""
    body = _def_body(_src(STYLES), "    def OnLeftButtonDown(self):\n        # Arm the rotate state FIRST")
    sup = body.index("super().OnLeftButtonDown()")
    # The non-pan path must set the active view only AFTER super().
    assert body.index("self.parent._set_active_view('3d')", sup) > sup


def test_oblique_validator_is_gated():
    """It ran on every oblique frame — camera snapshots, numpy allocations, ten
    checks and a log record, synchronously on the GUI thread inside the
    crosshair rotation loop — and three of its checks are stale (they measure
    the camera's plane, which has not selected the slice since v1.09.Fix-E)."""
    body = _def_body(_src(OBLIQUE), "    def _set_oblique_camera(")
    assert "_oblique_validate_enabled()" in body
    gate = _def_body(_src(OBLIQUE), "def _oblique_validate_enabled(")
    assert "ZETA_MPR_DIAG" in gate, "turning diagnostics on must turn validation on"
    assert "AIPACS_MPR_OBLIQUE_VALIDATE" in gate


def test_a_new_gesture_is_not_throttled_by_the_previous_one():
    body = _def_body(_src(ORIENT), "    def _finalize_interaction_update(")
    assert "self._interaction_last_ms = 0.0" in body, (
        "the final update resets the throttle clock; without clearing it a "
        "re-press inside the 16 ms budget has its first event deferred"
    )


def test_no_reset_camera_was_added_to_any_interaction_path():
    """Documented invariant — pinned here too because this change set touched
    four interaction files."""
    for path in (INTERACT, LAYOUT, STYLES, ORIENT):
        src = _src(path)
        for fn in ("_set_active_view", "_update_view_highlights",
                   "_apply_hover_cursor", "_finalize_interaction_update"):
            marker = f"    def {fn}("
            if marker in src:
                assert "ResetCamera(" not in _def_body(src, marker), (
                    f"{path.name}:{fn} must not reset the camera")


# ---------------------------------------------------------------------------
# 3. Toolbar tools must not close MPR
# ---------------------------------------------------------------------------

def test_tool_selection_no_longer_closes_mpr_by_default():
    body = _def_body(_src(TOOLBAR), "    def check_and_deactivate_tools(")
    assert "close_mpr" in body, "the close must be opt-in per caller"
    assert "_may_close" in body
    assert "self.toggle_zeta_mpr()" in body, "the close path itself must survive"
    flag = _def_body(_src(TOOLBAR), "    def _mpr_preserve_on_tool_select(")
    assert 'getenv("AIPACS_MPR_PRESERVE_ON_TOOL_SELECT", "1")' in flag


def test_the_callers_that_need_the_cell_still_close_mpr():
    """Curve MPR, Dental Curve MPR and the post-series-switch reset genuinely
    need the grid cell freed. If they stopped closing MPR, two MPR pipelines
    would fight over one cell — the duplicate-pipeline memory class the
    re-entrancy guard exists to prevent."""
    src = _src(TOOLBAR)
    assert src.count("check_and_deactivate_tools(close_mpr=True)") >= 3, (
        "expected explicit closes for curve MPR, curved MPR and turn_off_all_tools"
    )
    assert "close_mpr=True" in _def_body(src, "    def turn_off_all_tools(")


def test_text_tool_has_an_mpr_branch():
    """`activate_caption()` has existed in the MPR measurement tools since the
    refactor and nothing ever called it, so picking Text closed MPR instead."""
    body = _def_body(_src(TOOLBAR), "    def toggle_text(")
    assert "is_mpr_viewer(selected_widget)" in body
    assert "activate_caption()" in body
    assert "_register_mpr_tool_auto_exit" in body
    # The MPR branch must return before the 2D path's check_and_deactivate_tools.
    assert body.index("activate_caption()") < body.index("can_use_tool")


def test_arrow_updates_its_toolbar_button_in_mpr():
    """Without this the button stayed unchecked after a successful activation,
    so the next click took the deactivate branch — 'the arrow tool doesn't
    work in MPR'."""
    body = _def_body(_src(TOOLBAR), "    def toggle_arrow(")
    mpr_branch = body[:body.index("# Normal VTKWidget mode")]
    assert "self.handle_buttons_checked()" in mpr_branch


def test_tools_without_an_mpr_implementation_say_so():
    """Preserving MPR while the tool silently no-ops on the hidden 2D widget
    underneath would be worse than the original bug, not better."""
    src = _src(TOOLBAR)
    helper = _def_body(src, "    def _tool_unavailable_in_mpr(")
    assert "is_mpr_viewer" in helper and "return True" in helper
    for fn, label in (("toggle_roi", "ROI"),
                      ("toggle_circle_roi", "Circle ROI"),
                      ("toggle_ai_chat", "AI Chat"),
                      ("toggle_two_line_angle", "Two-Line Angle")):
        body = _def_body(src, f"    def {fn}(")
        assert f'_tool_unavailable_in_mpr(selected_widget, "{label}")' in body, (
            f"{fn} must refuse politely inside MPR rather than closing it")


# ---------------------------------------------------------------------------
# 4. One loading indicator, one lifecycle
# ---------------------------------------------------------------------------

def test_the_flip_step_reuses_the_build_dialog():
    """Two modals were stacked mid-open: the build dialog, then a second one on
    top of it, which restarted the marquee from phase 0 and revealed the first
    again when it closed. That is the reported open/close/reappear/restart."""
    body = _def_body(_src(TOOLBAR), "    def _prepare_mpr_flip_offthread(")
    assert "existing_dlg" in body
    assert "_owns_dlg" in body
    assert "if _owns_dlg:" in body, "a borrowed dialog must not be closed here"
    # The literals the OPT-48 guard test pins must survive.
    assert "WindowModality.ApplicationModal" in body
    assert "setCancelButton(None)" in body


def test_the_open_path_hands_its_dialog_through():
    src = _src(TOOLBAR)
    assert "_prepare_mpr_flip_offthread(\n                    vtk_image_data, existing_dlg=_build_dlg)" in src \
        or "existing_dlg=_build_dlg" in src
