# STACK_ORDER_ARCHITECTURE_RECOMMENDATION

## Architecture Options for Canonical Stack Traversal — AIPacs v3.0.2

**Investigation date:** 2026-05-14
**Based on:** DICOM_TO_DISPLAY_ORDER_CHAIN.md, DISPLAY_TRAVERSAL_AUDIT.md, SIMPLEITK_VTK_ORDERING_INVESTIGATION.md
**Constraint:** Do NOT implement another arbitrary flip. This document covers analysis only.

---

## Problem Statement

The Advanced (VTK) pipeline produces `k_increasing → I→S` for axial HFS CT because:
1. `canonical_sort_instances` sorts by ascending IPP (I→S for axial HFS).
2. This order propagates through SimpleITK → numpy → VTK unchanged.
3. VTK `SetSlice(k)` renders k=0 = Inferior.
4. Clinical canonical requires k=0 = Superior (S→I traversal).

The FAST pipeline accidentally produces the correct S→I direction for typical CT (InstanceNumber 1 = Superior) but has no geometry-based guarantee. It is therefore:
- Correct for typical HFS CT scanners
- Wrong for acquisitions where InstanceNumber=1 is at the Inferior end

---

## Option A: Display-Layer K-flip via DisplayGeometry (Already Implemented)

### What it does

```
canonical_sort → k=0=Inferior (raw) → DisplayGeometry.apply_k_flip_for_stack_order(N)
→ display_k=0=Superior (corrected)
```

**Key property:** Raw voxel memory (`vtkImageData`) is NOT modified. The K-flip lives ONLY in:
- `DisplayGeometry.effective_display_ijk_to_lps_4x4` (the active display transform)
- All geometry-dependent subsystems (reference lines, markers, sync) that consume this contract

### Code locations (already written, prior session)

- `modules/viewer/geometry/display_geometry.py`:
  - `_k_flip_4x4(n_slices)` — 4×4 matrix for k remapping
  - `apply_k_flip_for_stack_order(n_slices, reason)` — applies flip to effective affine
  - `audit_stack_order_convention(plane, body_part)` — detects need for flip
- `modules/viewer/advanced/viewer_2d.py`:
  - `_bind_geometry_contract()` — calls audit + applies flip if needed
  - Logs `[STACK_ORDER_CONVENTION_AUDIT]` and `[DISPLAY_STACK_ORDER_POLICY]`
- Plugin package copies (must stay in sync):
  - `builder/plugin package/packages/viewer/payload/python/modules/viewer/geometry/display_geometry.py`
  - `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py`

### Pros

- **Non-destructive:** Raw VTK memory (numpy array, origin, spacing) stays in canonical_sort order.
  Reverting is trivial — just do not call `apply_k_flip_for_stack_order`.
- **Isolated:** All corrections are localized to the `DisplayGeometry` contract layer.
- **MPR-safe for display:** The `effective_display_ijk_to_lps_4x4` matrix propagates automatically to
  all geometry consumers (reference lines, sync, markers) — no per-subsystem fix needed.
- **Auditable:** `[STACK_ORDER_CONVENTION_AUDIT]` logs show exactly when and why a flip is applied.
- **Already implemented and tested** (8 synthetic tests pass).
- **Does NOT affect the FAST pipeline** — FAST has its own separate path; the K-flip is only applied
  in `_bind_geometry_contract` which is Advanced-only.

### Cons and Risks

1. **VTK SetSlice mismatch:** The raw VTK k index and the "display_k" reported by `GetSlice()` still
   differ. `GetSlice()` returns the raw VTK index (0 = Inferior), not the display-canonical index
   (0 = Superior). Any code that reads `GetSlice()` and treats it as a "slice number" for display
   will be wrong by (N-1 - raw_k).
   - **Mitigation:** All display-facing slice number reporting must go through `DisplayGeometry`
     to convert raw VTK k to display_k. Current code (corner labels, slider) uses `GetSlice()`
     directly — this is a residual bug.

2. **Slider ↔ raw VTK k mismatch:** The slider currently maps directly to raw VTK k.
   After K-flip, slider position 0 means "raw_k=0 (Inferior)" but display-canonical position 0
   should be the Superior slice. The slider will appear visually backwards.
   - **Mitigation:** Invert slider values in the slider-change and `set_slice` handlers:
     `raw_k = (N-1) - slider_value` when K-flip is active.

3. **`SetSlice(k)` inversion requirement:** For the viewer to render the correct patient location
   when `display_k` is requested, the call must be:
   ```python
   raw_k = display_geometry.display_k_to_raw_k(display_k)
   self.SetSlice(raw_k)
   ```
   Currently `set_slice` passes display_k directly to `SetSlice`. The mapping is not applied.
   - **Status:** This inversion is the remaining work needed to complete Option A.
   - **Scope:** ~10 lines in `_set_slice_impl` + slider handlers.

4. **FAST/Advanced index agreement:** FAST uses display_k directly (InstanceNumber order).
   Advanced raw k is IPP order. They disagree on what "k=10" means for the same patient slice.
   Cross-backend sync (lock-sync, reference lines) must use patient LPS coordinates as the
   canonical interop currency — NOT raw k values.

### MPR Implications of Option A

`vtkImageReslice` (used in Advanced MPR/cursor) uses the raw VTK k-axis. For a K-flipped display:
- Coronal/sagittal reconstruction slices through the raw volume are physically correct.
- However, when the MPR window reports "current axial slice = k_raw", it is reporting I→S position.
- The MPR "axial" position indicator would show the wrong clinical position.
- **Fix for MPR:** MPR window must translate its raw_k to display_k using the same `DisplayGeometry`
  contract before showing the position indicator.
- **Alternative:** Build MPR directly on `effective_display_ijk_to_lps_4x4` (it already contains
  the K-flip) and always work in patient LPS coordinates.

---

## Option B: Physically Reverse Voxel Memory Order Before VTK

### What it does

```
canonical_sort → k=0=Inferior (numpy) → arr_reversed = arr[::-1, :, :]
→ k=0=Superior → store in VTK → SetSlice(0) = Superior
```

Implement in `convert_itk2vtk` just after the Y-flip:
```python
arr = arr[:, ::-1, :]   # existing Y-flip
arr = arr[::-1, :, :]   # NEW: reverse Z order to make k=0 = Superior
# Update origin: new_origin_z = old_origin_z + (N-1) * spacing_z
# Update spacing_z: remains the same magnitude (but logical "next higher k" is now inferior)
```

### Pros

- **SetSlice(k) is direct:** `SetSlice(0)` renders Superior; `SetSlice(N-1)` renders Inferior.
  `GetSlice()` returns canonical display_k directly. No mapping layer needed.
- **Slider mapping is trivial:** Slider value 0 = SetSlice(0) = Superior. No inversion needed.
- **MPR is correct by default:** `vtkImageReslice` reconstructed planes use correct k directions.
- **Most subsystems work without change:** Corner label slice number, sync raw k, all work correctly.

### Cons and Risks

1. **Breaks `SourceGeometry.sop_uid_to_k` mapping:** `SourceGeometry` builds `sop_uid_to_k` based on
   ascending IPP sort. After B-reversal, VTK k=0 is the SOP UID that was at position N-1 in the
   IPP sort. The `sop_uid_to_k` lookup table becomes inverted — it needs to be rebuilt or inverted.

2. **Breaks `canonical_sort_instances` ↔ VTK k correspondence everywhere:** Any code that uses
   `canonical_sort` order to build per-k metadata (IPP arrays, per-slice W/L, CornerLabel geometry)
   must reverse or re-index.

3. **Breaks stored DirectionMatrix:** The existing Y-flip updates row 1 of the direction matrix.
   A Z-flip would require negating row 2 (the k/Z direction cosines). The field data direction
   matrix must also be updated correctly or downstream code will incorrectly compute patient
   coordinates.
   - `direction_matrix.SetElement(2, col, -direction_matrix.GetElement(2, col))` for each col.

4. **Origin shift required:** After Z-reversal, the VTK origin (z-coordinate of k=0 slice) changes
   from `IPP_z_min` to `IPP_z_max`. `convert_itk2vtk` must compute the new origin.
   ```python
   # origin_z_new = origin_z_old + (N-1) * spacing_z
   new_origin = list(itk_image.GetOrigin())
   new_origin[2] = new_origin[2] + (N - 1) * spacing[2]
   vtk_image_data.SetOrigin(*new_origin)
   ```
   If this is wrong, every `SetSlice(k)` renders the wrong Z position.

5. **Risk of breaking reference lines and MPR:** Reference line computation uses IPP from
   `SourceGeometry` which was built with the OLD (IPP-ascending) k index. After reversal,
   the VTK k index is inverted relative to `SourceGeometry.sop_uid_to_k`. This would break
   any code that calls `display_geometry.k_to_sop_uid(vtk_k)` without the inversion.

6. **Difficult to verify:** A subtle off-by-one in origin update or direction matrix will produce
   patient coordinate errors that appear visually correct but are geometrically wrong. Verifying
   requires checking actual patient coordinates against DICOM headers.

7. **Invasive change:** `convert_itk2vtk` is a critical shared function used by all Advanced-mode
   series loads. Any regression here affects all series, all modalities.

### MPR Implications of Option B

After Option B, `vtkImageReslice` works natively with k=0=Superior. MPR axial reconstructions
appear in canonical order automatically. No post-correction needed in MPR widgets.
However, if `SourceGeometry.sop_uid_to_k` is not updated, MPR slice-position reporting is wrong.

---

## Option C: Reslice-Driven Canonical Display Planes

### What it does

Use `vtkImageReslice` with explicit `SetResliceAxesDirectionCosines` to define a display
plane that has "canonical" orientation independent of the raw voxel memory:

```python
# Currently in ImageReslice.__init__ (commented out):
# self.SetResliceAxesDirectionCosines(1, 0, 0, 0, -1, 0, 0, 0, 1)  # Roll 180 degrees (RAI)

# Canonical axial with S→I stack direction:
# Row direction: [1, 0, 0] (L→R)
# Col direction: [0, -1, 0] (S→I, i.e. column runs superiorly in negative sense)
# Normal: cross = [0, 0, 1] BUT with col inverted means effective k goes S→I
self.SetResliceAxesDirectionCosines(
    1, 0, 0,   # row: L→R
    0, -1, 0,  # col: inverted (S→I column direction)
    0, 0, 1    # normal: same
)
```

Alternatively, use `SetResliceAxesDirectionCosines` to make the k-axis run S→I by choosing
normal direction pointing Inferiorly:
```python
self.SetResliceAxesDirectionCosines(
    1, 0, 0,   # row: L→R
    0, 1, 0,   # col: P→A
    0, 0, -1   # normal pointing Inferior = k increases Inferiorly = S→I ✓
)
```

### Pros

- **Clean separation:** Display orientation is entirely controlled by the reslice axes.
  Raw voxel memory can be in any order (IPP ascending or descending).
- **MPR-natural:** MPR reslicing already works this way in advanced 3D tools.
- **No memory modification:** Raw vtkImageData unchanged.

### Cons and Risks

1. **Only works for fixed-plane viewers:** `vtkImageReslice` with explicit direction cosines
   defines a fixed oblique/axial/sagittal/coronal view. For arbitrary-angle MPR, this complicates
   the reslice orientation math.

2. **`SetSliceOrientationToXY/YZ/XZ` becomes incorrect:** VTK's built-in orientation helpers
   assume the voxel k-axis runs in a standard direction. If you override with direction cosines,
   the `SetSliceOrientationToXY` call and `SetSlice(k)` no longer have a clean 1:1 relationship.
   Each call to `SetSlice(k)` advances along the **reslice normal**, not the voxel k-axis.
   This means `k` in `SetSlice(k)` now counts along the reslice normal's direction,
   which may not match the number of slices in the original volume.

3. **Requires reslice origin management:** The origin of the reslice plane must be set to
   the "first" canonical slice (e.g. Superior-most), and `SetSlice(k)` must advance in the
   correct anatomical direction. This is non-trivial to configure correctly across all patient
   orientations.

4. **ImageReslice currently has direction cosines commented out:** Uncommenting with incorrect
   values would produce blank or corrupted images (the original comment shows a 180-degree roll
   attempt that was abandoned). This is high-risk.

5. **Does not solve FAST pipeline inconsistency:** FAST uses pixel-level rendering, not
   `vtkImageReslice`. So FAST and Advanced would still have separate (inconsistent) ordering logic.

---

## Recommendation

### **Option A is the correct choice.**

Reasons:

1. **Already implemented:** The K-flip logic in `DisplayGeometry` is working, tested, and
   architecturally clean. The `audit_stack_order_convention` function correctly detects when
   a flip is needed for each anatomical plane.

2. **Minimal risk:** All changes are in the display-only layer. The raw voxel data is preserved
   in its canonical IPP-ascending order, which is geometrically correct for reference line
   computation, SourceGeometry k-indices, and MPR reslicing.

3. **Option B is too invasive:** Reversing the numpy array in `convert_itk2vtk` creates cascading
   inconsistencies in `SourceGeometry.sop_uid_to_k`, direction matrix, and VTK origin — all of
   which are subtle and likely to introduce hard-to-diagnose geometry errors.

4. **Option C is over-engineered:** The reslice-direction approach solves a fixed-plane display
   problem but creates a new set of problems for MPR and arbitrary-angle reconstruction. It is
   the right approach for MPR tools (which already use it), but wrong for the 2D stack viewer.

### Remaining Work to Complete Option A

The K-flip is architecturally in place, but two integration gaps remain:

**Gap 1: `SetSlice(k)` does not apply the display-to-raw-k mapping.**

In `_set_slice_impl` (viewer_2d.py line 1453):
```python
self.SetSlice(slice_index)  # currently: slice_index = display_k (wrong — needs raw_k)
```

When K-flip is active, the correct call is:
```python
raw_k = self._display_geometry_contract.display_k_to_raw_k(slice_index) if self._display_geometry_contract else slice_index
self.SetSlice(raw_k)
```

Where `display_k_to_raw_k` is a method on `DisplayGeometry`:
```python
def display_k_to_raw_k(self, display_k: int) -> int:
    if self._k_flip_n_slices is None:
        return display_k
    return (self._k_flip_n_slices - 1) - display_k
```

**Gap 2: Slider ↔ display_k mapping.**

The slider currently drives `SetSlice(slider_value)` directly. When K-flip is active,
slider value = display_k, so the slider-to-raw-k mapping must also be applied.
In `queue_interactive_slice_target`:
```python
target = max(0, min(int(slice_index), int(max_slice - 1)))
# ... passes target (= display_k) to set_slice which must convert to raw_k
```
This is handled automatically IF Gap 1 is fixed (set_slice converts display_k to raw_k internally).

**Gap 3: `GetSlice()` returns raw_k, not display_k.**

Code that reads `image_viewer.GetSlice()` to determine "current position" gets the raw VTK k
(Inferior-first index), not the display_k. This affects:
- `last_index_slice_saved` assignments
- Slider initialization (`self.slider.setValue(int(self.image_viewer.GetSlice()))`)
- Sync/reference-line current-slice queries

**Fix:** Introduce `display_geometry.raw_k_to_display_k(GetSlice())` at each call site, or wrap
`GetSlice()` with a `get_display_slice()` helper on `ImageViewer2D`.

### Implementation Plan (when the user is ready)

1. Add `display_k_to_raw_k(n)` and `raw_k_to_display_k(n)` to `DisplayGeometry`.
2. In `_set_slice_impl`: convert display_k → raw_k before `self.SetSlice(raw_k)`.
3. In all `GetSlice()` read sites: convert raw_k → display_k using `DisplayGeometry`.
4. Test with axial HFS CT: verify SetSlice(0) renders Superior slice.
5. Test with coronal CT: verify same (K-flip also needed for coronal).
6. Verify FAST pipeline is unaffected (it does not use ImageViewer2D.SetSlice).
7. Update plugin package copies (display_geometry.py, viewer_2d.py).

**Estimated scope:** 3–5 files, ~30–50 lines of targeted changes. No data pipeline changes needed.

---

## Additional Risk: FAST vs Advanced Index Agreement

**Current state:** FAST uses InstanceNumber order (typically S→I). Advanced uses IPP order (I→S).

This means the "current slice number k" reported by FAST and Advanced for the SAME patient
position is different. Synchronization currently uses patient LPS coordinates (via reference
lines) rather than raw k indices, so this asymmetry does not directly break sync.

However, any feature that converts "current k" to a "slice number" for display to the user
will show different numbers for the same patient position depending on which backend is active.
The correct fix is to always express "current position" in patient LPS coordinates, not in
raw k indices, when communicating between backends.

This is a medium-term architectural hygiene item; it does not block the Option A completion.
