# MPR: reconstructed pane shakes while scrolling in the enlarged (double-click) view

**Date:** 2026-08-01 · **Report:** after double-clicking a reconstructed **coronal / sagittal**
MPR pane to enlarge it, scrolling the stack produces a slight visual shake — the image is not
completely stable. Requirement: *scrolling must change only the slice position; zoom, image
centre, camera position and displayed geometry must stay fixed.*
**Status:** two causes found and fixed, default-on, `AIPACS_MPR_STABLE_SCROLL=0` reverts both.
**Geometry / radiological canon: unchanged — see §4.**

---

## 1. How MPR scrolling actually works (the relevant mechanics)

Each 2D pane uses `vtkImageResliceMapper` with **`SliceFacesCameraOn()` + `SliceAtFocalPointOn()`**
(`_mpr_views.py`). The displayed slice is therefore selected **by the camera**: the wheel handlers
(`_mpr_crosshair_interact.py::on_mouse_wheel_forward/backward`) translate the camera focal point
(and position) one step along the pane's scroll direction. **Every scroll notch moves the camera.**

Audit of the specific items requested:

| Checked | Finding |
|---|---|
| `ResetCamera` / `ResetCameraClippingRange` during scroll | **None** — they exist only in `zoom_to_fit`, `apply_view_transform`, view creation and the 3D pane. The scroll path never re-fits. ✅ (now pinned by a test) |
| Zoom persistence | `SetParallelScale` was never touched by scroll ✅ (now explicitly pinned) |
| Focal point / position | Moved together, so direction + distance are preserved ✅ (see cause 1 for the caveat) |
| Slice dimensions / bounds between frames | Unchanged — the volume is static; only the slice plane moves ✅ |
| Actor origin / spacing | Unchanged ✅ |
| Pan / translation | Not modified by scroll ✅ |
| Interpolation / render refresh | **← cause 2** |
| Double-click enlarge path | `_mpr_layout._toggle_expand_view` only re-parents the container in the grid and locks the widget size; it touches **no camera** ✅ — enlarging does not itself move anything, it *magnifies* an existing sub-pixel instability |

## 2. Cause 1 — camera step was not a guaranteed rigid translation

`focal[i] += scroll_dir[i] * step` and `pos[i] += scroll_dir[i] * step` were applied
**independently**, with `scroll_dir` taken as-is:

- if `scroll_dir` is not exactly unit length, the step length is scaled — and any component
  perpendicular to the through-plane axis slides the image **sideways** as you scroll;
- advancing focal and position independently lets their floating-point rounding diverge, so the
  camera-to-focal distance creeps over hundreds of notches (a guard test reproduced this: after
  200 notches the distance had drifted).

**Fix** — pure helper `stable_scroll_camera_step(before_focal, before_pos, direction, step)`:
normalises the direction, moves the **focal point** by exactly `step × unit(direction)`, then
carries the camera **rigidly** by re-adding the exact pre-move offset (`pos = focal + offset`), and
the caller pins `SetParallelScale` (zoom) and `SetViewUp` (rotation) to their pre-move values.
Oblique-safe: it follows the pane's ACTUAL scroll direction, never a hardcoded world axis. A zero /
invalid direction returns the camera unchanged.

## 3. Cause 2 — camera-DEPENDENT resampling on the reconstructed panes (the shimmer)

`_apply_native_plane_interpolation()` assigned, by role:

- **native** pane → `SetInterpolationTypeToNearest()` + `SetResampleToScreenPixels(False)`
- **reconstructed** panes → `SetInterpolationTypeToLinear()` + **`SetResampleToScreenPixels(True)`**

VTK documents that option as *"the image will be resampled every time the camera changes"*. Because
the slice is selected **by moving the camera**, every notch re-derives the resampling grid from the
camera; sub-pixel differences in that grid shift the sampled image slightly = shimmer. It is
invisible in a quarter-size pane and becomes obvious once enlarged, because each voxel then covers
many screen pixels.

**This exactly explains the report: only the reconstructed (coronal/sagittal) panes, only after
enlarging** — the native pane already used `False`.

**Fix** — reconstructed panes now also use `SetResampleToScreenPixels(False)`: the mapper resamples
onto its own **data-derived, camera-independent** grid, so the same slice renders identically
regardless of camera motion. `SetInterpolationTypeToLinear()` is retained, so the smooth MPR
appearance is preserved.

## 4. Why this does not regress geometry or radiological convention

- The slice plane, slice position, spacing, origin, bounds, the direction matrix and `ZetaAnatA`
  are **not touched**. Cause 2 changes only the *sampling grid the mapper renders onto*, not what
  is sampled or where.
- The native-plane rule (nearest + native-resolution sampling, no screen resampling) is unchanged —
  pinned by a test.
- Cause 1 makes the camera motion *more* constrained than before (rigid translation along the
  pane's own direction). It cannot introduce a new orientation: the scroll direction still comes
  from `_get_scroll_direction()`, which is derived from the direction matrix / anatomical routing.
- Both fixes share one kill switch, `AIPACS_MPR_STABLE_SCROLL=0`, which restores the exact legacy
  code path.

## 5. Verification

`tests/code/viewer/test_mpr_scroll_stability.py` (10) — pure invariant maths + wiring pins:
only the through-plane coordinate changes; camera direction AND distance invariant; oblique
direction followed (not snapped to an axis); step length exact for an unnormalised direction; zero
direction = no movement; **200 consecutive notches leave the in-plane position bit-identical**;
both wheel handlers pin zoom + view-up; **no `ResetCamera` anywhere in the scroll path**;
reconstructed panes use camera-independent resampling; native-plane rule untouched.

**NEEDS LIVE CONFIRMATION** (I cannot see the screen): open a CT, double-click the coronal and the
sagittal pane, scroll the full stack, and confirm (a) the image no longer shakes, (b) zoom/centre
stay put, (c) the reconstructed images still look acceptably smooth. If the smoothness at high zoom
is now judged worse, set `AIPACS_MPR_STABLE_SCROLL=0` and tell me — cause 1 can then be kept while
cause 2 is reverted independently.
