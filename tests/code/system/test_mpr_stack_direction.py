"""Guards for MPR stack-drag DIRECTION + toolbar stack smoothness (2026-06-09).

Direction spec (user): dragging the image DOWN must INCREASE the displayed slice
number; dragging UP must DECREASE it — for ANY series orientation. The displayed
number is slice_num = (current_position[axis]-origin[axis])/spacing[axis], and
_move_along_stack moves current_position by scroll_dir*delta_mm. Because
scroll_dir's sign comes from the DICOM direction matrix (varies per series), a
fixed mm sign was unreliable; _stack_delta_mm computes the mm needed to realise a
DESIRED slice-number change, so the direction is correct by construction.

Smoothness: the toolbar interactor style's _move_along_stack now coalesces the
cross-pane sync through the same frame-cadence throttle as the crosshair style.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_V = _ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
_ORIENT = _V / "_mpr_orientation.py"
_CROSSHAIR = _V / "_mpr_crosshair_interact.py"
_INTERACTORS = _V / "_interactor_styles.py"


def _method_slice(src: str, name: str) -> str:
    start = src.index(f"def {name}")
    nxt = src.index("\n    def ", start + 1)
    return src[start:nxt]


def _load_method(path, name):
    block = _method_slice(path.read_text(encoding="utf-8", errors="ignore"), name)
    fn_src = "    " + block.rstrip() + "\n"
    ns = {}
    exec("class _H:\n" + fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_H"]


class _Viewer:
    """Minimal stand-in exposing what _stack_delta_mm reads."""
    def __init__(self, sd_sign, spacing_axis2=2.0):
        self.spacing = [1.0, 1.0, spacing_axis2]
        self._sd_sign = sd_sign

    def _get_scroll_direction(self, view_name):
        v = [0.0, 0.0, 0.0]
        v[2] = self._sd_sign  # look axis = 2 (axial)
        return v


def _resulting_slice_delta(viewer, axis, delta_mm):
    # mirror the engine: Δslice = scroll_dir[axis]*delta_mm / spacing[axis]
    sd = viewer._get_scroll_direction("axial")[axis]
    return (sd * delta_mm) / viewer.spacing[axis]


def test_drag_down_increases_slice_number_for_either_orientation():
    """desired_slices > 0 (drag DOWN) must increase the displayed slice number
    whether the DICOM scroll direction is +Z or -Z."""
    H = _load_method(_ORIENT, "_stack_delta_mm")
    axis = 2
    for sd_sign in (+1.0, -1.0):
        v = _Viewer(sd_sign)
        delta_mm = H._stack_delta_mm(v, "axial", axis, +3)   # drag down → +3 slices
        assert round(_resulting_slice_delta(v, axis, delta_mm)) == 3, sd_sign
        delta_mm_up = H._stack_delta_mm(v, "axial", axis, -3)  # drag up → -3 slices
        assert round(_resulting_slice_delta(v, axis, delta_mm_up)) == -3, sd_sign


def test_stack_delta_mm_degenerate_scroll_dir_falls_back():
    H = _load_method(_ORIENT, "_stack_delta_mm")

    class _Degenerate(_Viewer):
        def _get_scroll_direction(self, view_name):
            return [0.0, 0.0, 0.0]  # no look-axis component

    v = _Degenerate(0.0)
    # must not raise / divide-by-zero; returns a finite fallback
    delta = H._stack_delta_mm(v, "axial", 2, +3)
    assert delta == 3 * v.spacing[2]


def test_both_change_stack_use_desired_slice_helper_not_fixed_sign():
    cross = _method_slice(_CROSSHAIR.read_text(encoding="utf-8", errors="ignore"), "_change_stack")
    tool = _method_slice(_INTERACTORS.read_text(encoding="utf-8", errors="ignore"), "_change_stack")
    for body in (cross, tool):
        assert "_stack_delta_mm(self.view_name, axis_index, -step_slices)" in body
        # the old fixed-sign mm computation must be gone
        assert "-step_slices * spacing_mm" not in body


def test_toolbar_move_along_stack_is_throttled():
    mas = _method_slice(_INTERACTORS.read_text(encoding="utf-8", errors="ignore"),
                        "_move_along_stack")
    assert "_request_interaction_update('move')" in mas
    assert "_interaction_budget_ms() > 0" in mas
