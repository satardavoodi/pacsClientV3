"""Guard tests — MPR stack-scroll stability in the enlarged (double-click) pane.

REPORT (2026-08-01): after double-click-enlarging a RECONSTRUCTED (sagittal /
coronal) MPR pane, scrolling the stack makes the image shake/jitter slightly.
Requirement: scrolling must change ONLY the slice position — zoom, image
centre, camera position/direction and displayed geometry must stay fixed.

TWO causes addressed, both geometry-safe:

1. **Camera invariant** — the wheel handlers now translate focal AND position by
   exactly ``step * unit(scroll_direction)`` and pin parallel scale + view-up.
   No in-plane drift, no zoom change, no rotation, distance preserved.
2. **Camera-dependent resampling** — the reconstructed panes were created with
   ``SetResampleToScreenPixels(True)``, which VTK re-evaluates *every time the
   camera changes*; since scrolling moves the camera, the sampling grid was
   re-derived per notch → sub-pixel shimmer, magnified when enlarged. The native
   pane always used ``False``, which is why only the reconstructed panes shook.

These tests pin the invariant maths (pure, no VTK needed) + the wiring.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERACT = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_crosshair_interact.py"
VIEWS = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"


def _step_fn():
    try:
        from modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_interact import (
            stable_scroll_camera_step,
        )
        return stable_scroll_camera_step
    except Exception:
        import pytest
        pytest.skip("VTK/PySide6 not importable in this environment")


# ---------------------------------------------------------------------------
# The camera invariant
# ---------------------------------------------------------------------------

def test_only_the_through_plane_coordinate_changes_for_an_axis_scroll():
    step_fn = _step_fn()
    focal0, pos0 = [10.0, 20.0, 30.0], [10.0, 20.0, 430.0]
    focal, pos = step_fn(focal0, pos0, [0.0, 0.0, -1.0], 2.5)
    # in-plane (x, y) untouched — no sideways drift
    assert focal[0] == focal0[0] and focal[1] == focal0[1]
    assert pos[0] == pos0[0] and pos[1] == pos0[1]
    # through-plane advanced by exactly one step
    assert focal[2] == focal0[2] - 2.5
    assert pos[2] == pos0[2] - 2.5


def test_camera_distance_and_direction_are_invariant():
    step_fn = _step_fn()
    focal0, pos0 = [1.0, 2.0, 3.0], [1.0, 2.0, 403.0]
    d0 = [pos0[i] - focal0[i] for i in range(3)]
    focal, pos = step_fn(focal0, pos0, [0.0, 0.0, 1.0], 7.25)
    d1 = [pos[i] - focal[i] for i in range(3)]
    assert d1 == d0, "focal->position vector (direction AND distance) must not change"


def test_oblique_direction_is_followed_not_snapped_to_an_axis():
    """An oblique/rerouted pane must advance along its OWN normal."""
    step_fn = _step_fn()
    focal0, pos0 = [0.0, 0.0, 0.0], [0.0, 0.0, 100.0]
    direction = [1.0, 1.0, 0.0]           # 45° in-plane-of-world, not an axis
    focal, pos = step_fn(focal0, pos0, direction, 2.0)
    inv_sqrt2 = 1.0 / math.sqrt(2.0)
    assert focal[0] == pytest_approx(2.0 * inv_sqrt2)
    assert focal[1] == pytest_approx(2.0 * inv_sqrt2)
    assert focal[2] == 0.0
    # translation is identical for focal and position
    assert [pos[i] - pos0[i] for i in range(3)] == [focal[i] - focal0[i] for i in range(3)]


def test_direction_is_normalised_so_step_length_is_exact():
    """An unnormalised direction must NOT scale the step (that is drift)."""
    step_fn = _step_fn()
    focal0, pos0 = [0.0, 0.0, 0.0], [0.0, 0.0, 50.0]
    focal, _ = step_fn(focal0, pos0, [0.0, 0.0, 3.0], 1.0)   # |dir| = 3
    moved = math.sqrt(sum((focal[i] - focal0[i]) ** 2 for i in range(3)))
    assert moved == pytest_approx(1.0), "step length must equal the requested step"


def test_zero_or_invalid_direction_does_not_move_the_camera():
    step_fn = _step_fn()
    focal0, pos0 = [4.0, 5.0, 6.0], [4.0, 5.0, 106.0]
    for bad in ([0.0, 0.0, 0.0], ["a", "b", "c"]):
        focal, pos = step_fn(focal0, pos0, bad, 3.0)
        assert focal == focal0 and pos == pos0


def test_repeated_steps_do_not_accumulate_in_plane_drift():
    """200 notches must leave the in-plane position bit-for-bit unchanged."""
    step_fn = _step_fn()
    focal, pos = [12.5, -3.25, 0.0], [12.5, -3.25, 400.0]
    f0, p0 = list(focal), list(pos)
    for _ in range(200):
        focal, pos = step_fn(focal, pos, [0.0, 0.0, 1.0], 0.7)
    assert focal[0] == f0[0] and focal[1] == f0[1]
    assert pos[0] == p0[0] and pos[1] == p0[1]
    # camera-to-focal distance must not creep across hundreds of notches
    # (tolerance is far below any physically meaningful value)
    for i in range(3):
        assert abs((pos[i] - focal[i]) - (p0[i] - f0[i])) < 1e-9


def pytest_approx(value, rel=1e-12):
    import pytest
    return pytest.approx(value, rel=rel)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_wheel_handlers_use_the_invariant_and_pin_zoom_and_viewup():
    src = INTERACT.read_text(encoding="utf-8", errors="replace")
    assert src.count("stable_scroll_camera_step(") == 3, (
        "both wheel handlers must use the invariant (plus its definition)"
    )
    for handler in ("def on_mouse_wheel_forward", "def on_mouse_wheel_backward"):
        start = src.index(handler)
        block = src[start: start + 2200]
        assert "scroll_camera_invariant_enabled()" in block
        assert "camera.SetParallelScale(_scale_before)" in block, "zoom must be pinned"
        assert "camera.SetViewUp(_up_before)" in block, "rotation must be pinned"
        # legacy path preserved behind the kill switch
        assert "else:" in block


def test_no_reset_camera_in_the_scroll_path():
    """ResetCamera / ResetCameraClippingRange would re-fit and visibly jump."""
    src = INTERACT.read_text(encoding="utf-8", errors="replace")
    for handler in ("def on_mouse_wheel_forward", "def on_mouse_wheel_backward"):
        start = src.index(handler)
        block = src[start: start + 2600]
        assert "ResetCamera" not in block, "scrolling must never re-fit the camera"


def test_reconstructed_panes_use_stable_camera_independent_resampling():
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    assert "def mpr_stable_scroll_enabled(" in src
    assert 'getenv("AIPACS_MPR_STABLE_SCROLL", "1")' in src
    block = src[src.index("# Reconstructed plane:"): src.index('logger.info("[ZETA_MPR] %s pane interpolation')]
    # smoothness preserved …
    assert "SetInterpolationTypeToLinear()" in block
    # … but the camera-dependent screen-pixel resample is off by default
    assert "SetResampleToScreenPixels(not _stable_scroll)" in block


def test_native_plane_rule_is_untouched():
    """The native pane must still be nearest + no screen resampling."""
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    block = src[src.index("# Native plane:"): src.index("# Reconstructed plane:")]
    assert "SetInterpolationTypeToNearest()" in block
    assert "SetResampleToScreenPixels(False)" in block
