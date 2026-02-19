# Zeta MPR — Engineering Journal

**Module:** `PacsClient/pacs/patient_tab/zeta mpr/`  
**Created:** 2026-02-17  
**Last Updated:** 2026-02-17  
**Primary file:** `standard_mpr_viewer.py` (~5 000 lines)  
**Sister docs:**  
- `ZETA_MPR_PIPELINE_REFERENCE.md` — architecture & tool index  
- `ZETA_MPR_ROTATION_ITK_VTK_STATUS.md` — rotation version log  
- `docs/IMAGE_PIPELINE_REFERENCE.md` — full DICOM → screen pipeline  

---

## Purpose of this Document

This is the **learning diary** for the ZetaMPR oblique-reconstruction subsystem.

It records:
1. What we tried and why.
2. What we read (links, blogs, official docs) and what was useful.
3. What we learned — including things we thought were true but turned out to be wrong.
4. Open questions we know exist but cannot yet answer.
5. Step-by-step history so future work starts where we left off, not from scratch.

**Why this matters:**  
Camera-driven oblique MPR in VTK is an unusual approach.  Most open-source
viewers (3D Slicer, OHIF, Cornerstone3D, ITK-SNAP) use `vtkImageReslice` with
explicit transform matrices, not camera repositioning with `SliceFacesCameraOn`.
That means:
- There are very few blog posts or forum threads that describe our exact architecture.
- The simpler camera-only examples found online generally work for axis-aligned
  views but break (flip, mirror) once you go oblique.
- The industrial-grade implementations (3D Slicer `vtkMRMLSliceNode` → `SliceToRAS`)
  are too deeply coupled to Slicer's scene graph to lift directly.

Without a written record, every developer (human or AI) repeats the same wrong
paths and loses weeks.

---

## Table of Contents

1. [Architecture Overview (How Our MPR Actually Works)](#1-architecture-overview)
2. [The Coordinate Pipeline — What We Know For Certain](#2-the-coordinate-pipeline)
3. [Chronological History of Changes (R0 → R1.2)](#3-chronological-history)
4. [Research Log — What We Read and What We Learned](#4-research-log)
5. [The Four Bugs Fixed in R1.2 (Root-Cause Analysis)](#5-the-four-bugs-fixed-in-r12)
6. [Open Questions (Things We Know We Don't Understand)](#6-open-questions)
7. [Wrong Assumptions We Corrected](#7-wrong-assumptions-we-corrected)
8. [Better Path Forward — Recommendations](#8-better-path-forward)
9. [Reference: VTK Camera Geometry Cheat-Sheet](#9-reference-vtk-camera-geometry)
10. [Reference: How Other Viewers Do Oblique MPR](#10-reference-other-viewers)
11. [Glossary](#11-glossary)

---

## 1. Architecture Overview

### 1.1 What Makes ZetaMPR Different

Most VTK-based MPR viewers work like this:

```
volume ──► vtkImageReslice(transform) ──► 2D output ──► vtkImageActor ──► screen
```

ZetaMPR works like this:

```
volume ──► vtkImageResliceMapper(SliceFacesCameraOn) ──► camera determines slice ──► screen
```

The key difference:  
- **Traditional:** you compute a 4×4 reslice matrix and feed it to `vtkImageReslice`.
  The output is a 2D image that you display with a flat mapper.  
- **ZetaMPR (R1+):** you keep the full 3D volume connected to a `vtkImageResliceMapper`
  with `SliceFacesCameraOn()` + `SliceAtFocalPointOn()`.  The mapper reads the
  **camera direction** and automatically extracts the slice perpendicular to the
  camera at the focal point.  To show an oblique plane, you just move the camera.

**Advantages of our approach:**
- No need to create temporary oblique `vtkImageData` objects.
- Smooth, real-time oblique (the mapper is GPU-accelerated).
- Orthogonal and oblique use the same code path (camera position/direction).
- Simpler code: no reslice axis matrices to compose manually.

**Disadvantages / risks:**
- Camera state (position, focal point, view-up) must be managed very carefully.
  Any accidental overwrite → wrong slice or image flip.
- The `view_up` vector defines which way is "up" in the viewport.  If it drifts
  or gets composed with the wrong sign, the image mirrors or flips.
- VTK cameras have no "handedness" concept.  Two cameras on opposite sides of the
  volume that look at the same focal point produce **mirrored** images.
- There is very little documentation or community guidance for this approach.

### 1.2 The Four 2D Views

| View | Camera looks along | Through-plane axis | CT corrections (after base setup) |
|------|-------------------|--------------------|-----------------------------------|
| Axial | −Z (feet→head) | Z | None |
| Sagittal | +X (right→left) | X | `Roll(180)` |
| Coronal | +Y (anterior→posterior) | Y | `Azimuth(180)` + `Roll(180)` |
| 3D | Trackball-free | N/A | N/A |

**Important:** The "CT corrections" (`Roll`, `Azimuth`) are applied **after**
`_get_camera_vectors_for_view()` and `ResetCamera()`.  They compose on top of
the initial camera state.  The result = the camera's **effective** position and
view-up differ from the simple vectors returned by `_get_camera_vectors_for_view`.

This is why **baseline camera capture** (R1.2) must happen *after* these
corrections, not before.

### 1.3 The `vtkImageResliceMapper` Contract

From VTK source (`vtkImageResliceMapper.cxx`):

> When `SliceFacesCameraOn()` is enabled, the mapper computes the slice plane
> from the active camera's direction of projection.  The plane passes through
> the camera's focal point if `SliceAtFocalPointOn()` is also enabled.

In practice this means:

```
slice_normal = normalize(camera_position - focal_point)
slice_origin = focal_point
```

**The mapper does the reslice internally** — tricubic or trilinear interpolation,
depending on the `vtkImageSlice` actor's `InterpolationType`.

### 1.4 The X-Flip and Direction Matrix

Before any view is created, `__init__` applies:

1. `vtkImageFlip` on axis 0 (X-flip) → radiological left-right convention.
2. Copy field data from original image (preserves `DirectionMatrix`).
3. Negate column 0 of the direction matrix (compensates for X-flip).

The direction matrix at this point has **two compensations** baked in:
- Row 1 negated (Y-flip from `convert_itk2vtk`).
- Column 0 negated (X-flip in MPR `__init__`).

**This doubly-compensated matrix is what `_get_camera_vectors_for_view` reads.**

For a standard axial CT (identity direction in DICOM), after both compensations
the matrix is:

```
D_mpr = ⎡ -1   0   0 ⎤
        ⎢  0  -1   0 ⎥
        ⎣  0   0   1 ⎦
```

Which is close to a [−1,−1,1] diagonal — i.e. both X and Y are negated, Z preserved.

---

## 2. The Coordinate Pipeline

This section summarizes the **verified** coordinate chain.  For the full formal
derivation, see `docs/IMAGE_PIPELINE_REFERENCE.md`.

### 2.1 Five Coordinate Spaces

| # | Name | Axes | Units |
|---|------|------|-------|
| CS-1 | DICOM Patient (LPS+) | X=Left, Y=Posterior, Z=Superior | mm |
| CS-2 | SimpleITK numpy | axis0=Z, axis1=Y, axis2=X | voxels |
| CS-3 | VTK after `convert_itk2vtk` | i=X, j=Y(**flipped**), k=Z | mm |
| CS-4 | VTK after `vtkImageFlip(0)` in MPR | i=X(**flipped**), j=Y(**flipped**), k=Z | mm |
| CS-5 | Display / Screen | 2D pixel | pixels |

### 2.2 The Two Flips (and Why They Exist)

| Flip | Where | What it does | Why |
|------|-------|-------------|-----|
| Y-flip | `convert_itk2vtk` | `arr[:, ::-1, :]` | VTK display expects Y increasing upward; DICOM rows increase downward |
| X-flip | `StandardMPRViewer.__init__` | `vtkImageFlip(axis=0)` | Enforces radiological convention (patient right on viewer left) |

**Critical rule:** both flips are in the pixel data.  The direction matrix is
compensated algebraically to keep `patient = origin + D * (ijk * spacing)` valid.
The origin itself is **not** adjusted — this creates the "origin problem" documented
in IMAGE_PIPELINE_REFERENCE §4.

### 2.3 What "Baseline Camera State" Actually Captures

After `_setup_ui()` completes (all views created, CT Roll/Azimuth applied, 
`ResetCamera()` called, zoom applied), `_capture_baseline_camera_state()` snapshots:

```
For each view in [axial, sagittal, coronal]:
    position      = camera.GetPosition()       # [x, y, z]
    focal         = camera.GetFocalPoint()     # [x, y, z]
    view_up       = camera.GetViewUp()         # [vx, vy, vz]
    direction     = normalized(focal - position) # unit camera direction
    distance      = |position - focal|
    parallel_scale = camera.GetParallelScale()
```

This is the **single source of truth** for oblique computations.

---

## 3. Chronological History

### R0 — Legacy `vtkImageReslice` Transform Path (pre-2026-02-08)

**Approach:** On rotation, compute a 4×4 reslice matrix, create a temporary
`vtkImageReslice` output volume, swap the mapper's input to the resliced 2D
output, set up a new mapper.

**What happened:** Center drift after rotation.  Occasional mirror/flip.
Unstable between datasets.  Occasional black output when the reslice plane
was outside the volume bounds.  Difficult to debug because each rotation was
a destructive operation on the display pipeline.

**Lesson:** Runtime mapper and volume swapping is fragile when crosshair
position, window/level, and view-up must all survive the swap.

### R0.5 — Rotation Locked (pre-2026-02-08)

`rotation_enabled = False`.  Crosshair rotation handles were disabled.
Orthogonal-only mode.  Stable, but no oblique reconstruction.

### R1 — Camera-Plane Oblique (2026-02-08)

**Approach:** Keep `vtkImageResliceMapper` with `SliceFacesCameraOn`.  To show
an oblique plane, just reposition the camera so it looks along the oblique normal.
The mapper does the reslice internally.

**Key ideas:**
- 9-point dual-tier sampling: for each rotated crosshair in a source view, compute
  the oblique normal via `cross(line_direction, slice_normal)`.
- Two tiers of sample points (¼ and ⅙ of shortest axis span) for robustness
  near volume edges.
- Camera repositioned via `_set_oblique_camera(target_view, oblique_normal)`.

**Result:** Oblique planes appeared correctly for small angles.  But at 10–20°
rotation of the axial crosshair, the **coronal view flipped** — left and right
eyes swapped.  The reconstructed line positions were also incorrect after
dragging the crosshair center while oblique was active.

### R1.1 — Direction-Matrix-Aligned Basis (2026-02-08)

Added `ROT_DEBUG` diagnostics and direction-matrix-aware camera basis selection.

**Result:** Improved accuracy of normal computation for non-identity direction
matrices, but did not fix the flip bug (which was caused by different root causes).

### R1.2 — Baseline Camera + Normal Sign + Update Ordering Fix (2026-02-16)

Four root-cause bugs fixed.  See [section 5](#5-the-four-bugs-fixed-in-r12) for
complete analysis.

**Result:** Coronal flip bug resolved.  Center drag while oblique active now
preserves the oblique plane.  Scroll + oblique works correctly.

**Backup:** `backups/zeta_mpr_backup_2026-02-16/`

---

## 4. Research Log

### 4.1 Official VTK Documentation

| Resource | URL | What we learned | Usefulness |
|----------|-----|-----------------|------------|
| `vtkImageReslice` class ref | https://vtk.org/doc/nightly/html/classvtkImageReslice.html | Detailed API: `SetResliceAxes()`, `SetResliceAxesDirectionCosines()`, `SetOutputOrigin/Spacing/Extent`. Confirmed this is the standard approach for producing a 2D oblique slice from a 3D volume. | ★★★★☆ — good for understanding the *traditional* approach, but we're not using it directly |
| `vtkImageResliceMapper` class ref | https://vtk.org/doc/nightly/html/classvtkImageResliceMapper.html | Confirms `SliceFacesCameraOn` + `SliceAtFocalPointOn` behavior. Sparse documentation — just lists the methods. | ★★☆☆☆ — confirms our approach works but gives no guidance on camera management |
| `vtkCamera` class ref | https://vtk.org/doc/nightly/html/classvtkCamera.html | Roll, Azimuth, Elevation, `SetViewUp`, `GetDirectionOfProjection`. Key insight: `GetDirectionOfProjection()` = `normalize(focal - position)`, which is the slice normal when `SliceFacesCameraOn`. | ★★★☆☆ |

### 4.2 Blog Posts & Tutorials

| Resource | URL / Source | What we learned | Usefulness |
|----------|-------------|-----------------|------------|
| David Gobbi's VTK medical imaging blog | (searched — could not find the specific oblique reslice post) | David Gobbi is the author of `vtkImageReslice` and `vtkImageResliceMapper` in VTK. His blog posts are the most authoritative explanation of the reslice internals. We were unable to locate the specific post about oblique reslicing via camera manipulation. | ★★★★★ (known to be excellent) — **TODO: find and read** |
| VTK Discourse — oblique MPR camera search | https://discourse.vtk.org | Searched for "oblique MPR camera" — no directly relevant results. The VTK forum has many questions about `vtkImageReslice` with explicit axes, but very few about using `SliceFacesCameraOn` for oblique views. | ★☆☆☆☆ — confirms our approach is uncommon |
| 3D Slicer Discourse — MPR implementation | https://discourse.slicer.org | Searched for MPR approaches — returned unrelated topics (markups, etc.). Slicer's approach is well-documented in their codebase but not in forum tutorials. | ★☆☆☆☆ |
| Kitware blog — VTK for medical imaging | (searched, general articles) | High-level articles about VTK 9 features. No specific oblique MPR guidance. | ★☆☆☆☆ |
| Stack Overflow VTK oblique reslice | (various threads) | Most answers recommend `vtkImageReslice` with `SetResliceAxes`. Some mention `vtkImageResliceMapper` for performance. No one discusses camera-driven oblique with sign management. | ★★☆☆☆ |

### 4.3 Open-Source Viewer Code (Read / Analyzed)

| Viewer | How they do oblique MPR | Relevance to us |
|--------|------------------------|-----------------|
| **3D Slicer** | `vtkMRMLSliceNode` stores a `SliceToRAS` 4×4 matrix. The slice logic builds an explicit reslice axis matrix from this. Camera is positioned from the matrix. Orientation labelling (LRAPIS) is derived from the matrix rows. Very robust, handles arbitrary oblique. | **High** — the `SliceToRAS` concept is the gold standard. But their implementation is deeply integrated with MRML scene graph, 100+ nodes of infrastructure. Cannot be extracted directly. |
| **OHIF / Cornerstone3D** | Uses `vtkImageReslice` with explicit axes derived from tool state. Orientation managed via `IImageVolume.direction` metadata. | **Medium** — web-based, different performance constraints, but the math is portable. |
| **ITK-SNAP** | Uses ITK `ResampleImageFilter` with explicit orientation. Not VTK-camera-based. | **Low** — different framework entirely. |
| **ParaView** | Uses `vtkImageReslice` for slice views. Not camera-based oblique. | **Low** |

### 4.4 Key Insights from Research

1. **Almost nobody uses `SliceFacesCameraOn` for oblique MPR.**  
   It's designed for it, but in practice everyone uses explicit reslice axes.
   This means we're in uncharted territory for camera management during oblique.

2. **3D Slicer's `SliceToRAS` concept is the correct abstraction.**  
   A 4×4 matrix that defines the slice plane in patient coordinates, separate from
   the camera.  The camera is then *derived* from the matrix, not the other way
   around.  This prevents the camera state drift problem we encountered.

3. **View-up must be derived, not read from the camera.**  
   Every robust implementation computes view-up from the slice matrix (e.g., the
   column direction of `SliceToRAS`).  Reading `camera.GetViewUp()` after oblique
   updates introduces accumulated numerical error.

4. **Cross-product sign depends on input vector ordering.**  
   `cross(A, B) = -cross(B, A)`.  The 9-point sampling code computes
   `cross(line_dir, slice_normal)` — if `line_dir` changes sign (because the
   crosshair rotated past 90° or because the handle ordering changed), the
   computed normal flips.  **This was one of the root causes of the coronal flip.**

5. **`ResetCameraClippingRange()` is essential after any camera reposition.**  
   VTK computes near/far clipping planes from the renderer's prop bounds.
   After moving the camera for oblique, the old clipping planes may exclude
   the volume entirely → black output.

---

## 5. The Four Bugs Fixed in R1.2

### Bug 1: `_update_slice_positions` Overwrote Oblique Camera State

**Symptom:** Dragging the crosshair center while oblique was active caused the
coronal view to suddenly snap back to orthogonal or flip.

**Root cause:** The interaction handler called:
```
_update_all_crosshairs()   → which called _update_oblique_reslicing()
_update_slice_positions()  → which moved camera along orthogonal axis
```

The second call destroyed the oblique camera direction set by the first.

**Question we had:** "Why does the oblique plane break only when dragging, not
when rotating?"  
**Answer:** Because rotation calls `_update_all_crosshairs` (which set oblique)
but does NOT call `_update_slice_positions`.  Dragging calls both.

**Fix:**  
- `_update_all_crosshairs` no longer calls `_update_oblique_reslicing`.  
- `_update_slice_positions` only moves the focal point (not camera position)
  when `_oblique_cameras_active` is True.  
- New `_synchronize_oblique_views()` is called as the **last** step in every
  interaction handler.

**Remaining question (open):**  
Does the focal-point-only update in oblique mode correctly handle scroll
interaction?  When the user scrolls in the axial view while oblique is active,
the focal point moves along Z.  Then `_synchronize_oblique_views` re-applies
the oblique normal.  This should work because `_update_oblique_reslicing`
reads the current focal point.  **But this has not been verified empirically
with large rotation angles (>45°).**

### Bug 2: No Baseline Camera Reference

**Symptom:** After several oblique updates, the view-up vector drifted,
causing subtle rotation of the image in the viewport.

**Root cause:** `_set_oblique_camera` read `old_up = camera.GetViewUp()` from
the current camera state.  After the first oblique update, the view-up was
already slightly rotated.  Each subsequent update read the drifted value and
composed on top of it → exponential drift.

**Question we had:** "Why does the documented `_base_camera_state` /
`_capture_base_camera_state()` not exist in the actual code?"  
**Answer:** They were planned in the ROTATION_STATUS doc (R1 section 4.4) but
never actually implemented.  The method names in the doc were aspirational.

**Fix:** Implemented `_capture_baseline_camera_state()`.  Called once after
`_setup_ui()` and again after `_reset_rendering()` / series reload.
`_set_oblique_camera` now always uses baseline `view_up` and `distance`.

**Remaining question (open):**  
For non-identity direction matrices (oblique MRI), is the baseline view-up
still correct after CT corrections?  CT corrections (`Roll(180)`, `Azimuth(180)`)
are only applied for CT modality.  For MRI, the baseline should be the raw
output of `_get_camera_vectors_for_view`.  **This path has not been tested with
real oblique MRI datasets.**

### Bug 3: Oblique Normal Sign Not Validated

**Symptom:** At ~10–20° axial rotation, the coronal view suddenly flipped —
left and right eyes swapped.

**Root cause:** The 9-point sampling computes:
```python
oblique_normal = cross(line_direction, slice_normal)
```

The cross product has two possible signs (±).  One sign places the camera on the
anterior side of the volume (correct for coronal), the other places it on the
posterior side (wrong — produces a mirrored image because VTK cameras have no
intrinsic handedness).

The sign depended on `line_direction` orientation, which could flip depending on
which crosshair handle endpoint was "positive" — an implementation detail of the
crosshair angle computation.

**Question we had:** "Is the flip deterministic or random?"  
**Answer:** Deterministic.  It depends on the sign of `sin(angle)` in the
`_calculate_crosshair_endpoints` function.  At certain angle thresholds, the
computed `line_direction` reverses, flipping the cross-product result.

**Fix:** `_set_oblique_camera` now computes `dot(oblique_normal, -baseline_direction)`.
If negative (normal points away from the baseline camera side), the normal is
negated.  This guarantees the camera always stays on the correct side.

**Remaining question (open):**  
The dot-product check uses `-baseline_direction` (which is `position - focal`,
i.e., from focal toward camera).  For compound oblique (rotation in multiple views
simultaneously), the baseline direction may not be a good reference because the
"correct side" depends on the combined rotation.  **Compound oblique is deferred
to R2, but this check may need enhancement.**

### Bug 4: Missing `ResetCameraClippingRange`

**Symptom:** Occasional black (empty) views after oblique camera repositioning.

**Root cause:** After `_set_oblique_camera` moved the camera to a new position,
the near/far clipping planes (set by `ResetCamera()` during initialization)
became stale.  The volume fell outside the clipping range.

**Fix:** `renderer.ResetCameraClippingRange()` at the end of `_set_oblique_camera`.

**No remaining questions** — this is a well-understood VTK requirement.

---

## 6. Open Questions

These are things we **know are happening** but don't fully understand yet.
Each entry includes what we **do** know, what we **don't** know, and why it
matters.

### Q1: Why Does Sagittal Need `Roll(180)` and Coronal Need `Azimuth(180) + Roll(180)`?

**What we know:**  
- For CT data, these corrections are applied after `_get_camera_vectors_for_view`
  and `ResetCamera`.  
- Without them, the sagittal and coronal images display upside-down or mirrored
  compared to clinical convention.  
- They were found empirically — someone tried different combinations until the
  images looked correct.

**What we don't know:**  
- Is there a mathematical derivation from the direction matrix + Y-flip + X-flip
  that predicts these exact corrections?  
- Would the same corrections work for FFS (feet-first supine) or HFP (head-first
  prone) datasets?  
- Could we compute the corrections from the baseline direction matrix instead of
  hardcoding them for "CT"?

**Why it matters:**  
- We captured the baseline camera state *after* these corrections.  If the
  corrections are wrong for certain scan orientations, the baseline is wrong
  and all oblique computations will mirror.  
- Moving to non-CT modalities (MR) requires understanding whether `Roll(180)`
  is needed there too.

### Q2: Is the Doubly-Compensated Direction Matrix Correct?

**What we know:**  
- `convert_itk2vtk` negates row 1 (Y-flip compensation).  
- `StandardMPRViewer.__init__` negates column 0 (X-flip compensation).  
- For identity DICOM direction, the result is `diag(-1, -1, 1)`.

**What we don't know:**  
- Is `_get_camera_vectors_for_view` using this doubly-compensated matrix
  correctly?  It reads `row_dir`, `col_dir`, `slice_dir` as rows of the matrix.  
- For non-identity DICOM direction, do the row/column negations compose
  correctly?  Matrix row negation + column negation is NOT the same as two scalar
  multiplications; it's `D' = (row1_negate) ∘ (col0_negate) = D_itk` with
  row 1 negated and column 0 negated.  
- The identity check (`_is_identity_direction`) checks the compensated matrix
  against `I`, which will never be identity for CT after both negations.  So for
  CT, `is_identity` is always `False` and `_get_camera_vectors_for_view` returns
  hardcoded vectors (not matrix-derived vectors).  **This means the direction
  matrix is effectively unused for standard CT.**

**Why it matters:**  
- For oblique MRI (non-identity direction), the camera vectors WILL use the
  direction matrix.  But we've never tested this path.  
- If the matrix is wrong, all camera setup for non-standard scans will be wrong.

### Q3: What Happens with Compound Multi-View Rotation?

**What we know:**  
- Currently, rotating axial crosshair → oblique sagittal + coronal.  
- Rotating sagittal crosshair → oblique axial + coronal.  
- Both can be non-zero simultaneously.

**What we don't know:**  
- When axial AND sagittal are both rotated, the coronal view receives two
  oblique normal updates (one from each source view's rotation).  
  The last write wins.  Is this correct?  
- Should the normals be **composed** (one rotation on top of the other)?  
- Can `cross(rotated_line_dir, rotated_slice_normal)` even produce a valid
  compound oblique normal?

**Why it matters:**  
- Users can accidentally rotate multiple views.  The current behavior is
  undefined and may produce incorrect images.  
- R2 must address this with a clear composition rule.

### Q4: Does `SliceFacesCameraOn` Use `GetDirectionOfProjection` or `Position - Focal`?

**What we know:**  
- VTK documentation says "the slice is perpendicular to the camera's
  direction of projection."  
- `GetDirectionOfProjection()` should return `normalize(focal - position)`.  
- For parallel projection, this should be identical.

**What we don't know:**  
- Does `vtkImageResliceMapper` compute the normal from `GetDirectionOfProjection`
  or from `GetViewPlaneNormal`?  (They should be the same, but in VTK's code,
  `GetViewPlaneNormal` = `-(direction of projection)` for some historical reason.)  
- Is there a difference between parallel and perspective projection for the
  slice normal calculation?

**Why it matters:**  
- If the mapper uses `GetViewPlaneNormal` instead of `GetDirectionOfProjection`,
  the sign convention for our normal computation might be off by a factor of −1.  
- We work around this with the dot-product sign check (Bug 3 fix), but
  understanding the ground truth would let us simplify the code.

### Q5: How Does Scroll Work in Oblique Mode?

**What we know:**  
- `on_mouse_wheel_forward/backward` moves both focal and position along
  `_get_scroll_direction()`.  
- `_get_scroll_direction` returns a world-axis-aligned direction based on the
  view name (axial → [0,0,1], sagittal → [1,0,0], coronal → [0,1,0]).  
- After the scroll, `_synchronize_oblique_views()` re-applies the oblique camera.

**What we don't know:**  
- When a view is oblique, scrolling along the **original** axis (e.g., Z for
  axial) moves the slice along Z in world space.  But the displayed slice is
  tilted.  Should scrolling move along the **tilted normal** instead?  
- Clinical expectation: scrolling should move through the oblique stack
  perpendicular to the displayed plane.

**Why it matters:**  
- With small angles (<10°), world-axis scroll is close enough to oblique-normal
  scroll.  At large angles, the user experience degrades — they scroll along Z
  but the oblique plane moves diagonally.  
- This is a UX decision that should be documented and possibly configurable.

### Q6: Is `_calculate_crosshair_endpoints` Consistent Across Quadrants?

**What we know:**  
- Crosshair endpoints are computed using `cos(angle)` and `sin(angle)` in the
  view's 2D coordinate plane.  
- The angle is stored as a single float in radians.

**What we don't know:**  
- When the angle crosses from Q1 to Q2 (90°), does the line direction vector
  flip sign?  If so, this could cause the cross-product in
  `_update_oblique_reslicing` to flip sign too → normal flip.  
- The R1.2 fix (dot-product check against baseline direction) should catch this,
  but it's a band-aid.  Ideally, the line direction should be consistently
  oriented (always pointing in the "positive" crosshair direction).

**Why it matters:**  
- Without consistent line direction, every angle-dependent computation
  (including future R2 compound oblique) inherits sign ambiguity.

---

## 7. Wrong Assumptions We Corrected

### Wrong: "Camera view-up is stable across oblique updates"

**What we assumed:** When `_set_oblique_camera` repositions the camera, the
existing view-up vector remains valid because we only changed the camera
position, not the view-up.

**Why it was wrong:** VTK internally re-orthogonalizes the view-up against the
new view direction.  After several rounds, the view-up accumulates numerical
error.  Also, if the oblique normal is nearly aligned with the view-up, VTK
snaps the view-up to an arbitrary perpendicular → sudden rotation.

**Correction (R1.2):** Always use baseline view-up.  Include degenerate-case
fallback (dot > 0.99 → pick alternative vector).

### Wrong: "The documented `_base_camera_state` existed in the code"

**What we assumed:** The ROTATION_STATUS doc (R1 section 4.4) listed
`_capture_base_camera_state()` and `_base_camera_state` as implemented methods.

**Why it was wrong:** They were planned but never coded.  The document was
aspirational (written before implementation was complete).

**Correction (R1.2):** Implemented `_capture_baseline_camera_state()` and
`self._baseline_camera_state`.  Updated the documentation to reflect reality.

**Lesson:** Always verify documentation claims by reading the actual code.
Documentation can describe planned features as if they exist.

### Wrong: "Call order doesn't matter for crosshair + slice + oblique"

**What we assumed:** As long as `_update_all_crosshairs`, `_update_slice_positions`,
and `_update_oblique_reslicing` are all called, the result is correct regardless
of order.

**Why it was wrong:** `_update_slice_positions` moved the camera position along
the orthogonal axis.  If called *after* `_update_oblique_reslicing` had set the
camera to an oblique position, the orthogonal move overwrote the oblique camera.
Order matters because each function reads + writes shared state (the camera).

**Correction (R1.2):** Strict ordering:
1. `_update_all_crosshairs()` — visual only, no camera changes.
2. `_update_slice_positions()` — focal point only (when oblique active).
3. `_synchronize_oblique_views()` — final oblique camera reposition.

### Wrong: "Cross-product gives a consistent normal direction"

**What we assumed:** `cross(line_dir, slice_normal)` always produces a normal
pointing toward the camera (i.e., in the same hemisphere as the baseline camera
direction).

**Why it was wrong:** `cross(A, B) = -cross(B, A)`.  The sign of `line_dir`
depends on the crosshair rotation angle.  When the angle changes sign (or the
handle ordering changes), `line_dir` flips → the cross product flips → the
camera goes to the wrong side of the volume → image mirrors.

**Correction (R1.2):** Validate the computed normal's sign against the baseline
camera direction using a dot-product check.  Negate if wrong hemisphere.

### Wrong: "VTK forums would have examples of camera-driven oblique MPR"

**What we assumed:** Since `SliceFacesCameraOn` is a VTK feature, someone must
have described how to manage cameras for oblique views.

**Why it was wrong:** This feature is used primarily for simple axis-aligned
views.  Nobody in the VTK community (that we could find) has published guidance
on managing camera sign consistency during oblique rotations.

**Lesson:** Our approach works but is genuinely novel.  We must document
everything ourselves because there is no external reference.

---

## 8. Better Path Forward

### 8.1 Short-Term (R1.3 — Stabilization)

1. **Empirical validation with real datasets:** Run the verification protocol
   (ROTATION_STATUS §6) on at least 3 CT and 1 MRI dataset.  Record screenshots.
2. **Test scroll in oblique mode** at 15°, 30°, 45°, and 90° axial rotation.
3. **Test non-CT modality** to verify that missing Roll/Azimuth corrections
   (correct for MR) don't break baseline capture.
4. **Add guard for compound rotation:** If both axial and sagittal have rotation,
   log a warning and handle the last-write-wins behavior explicitly.

### 8.2 Medium-Term (R2 — Compound Oblique)

Consider adopting the **SliceToRAS matrix** concept from 3D Slicer:
- Each 2D view stores a 4×4 matrix that defines its slice plane in patient space.
- Orthogonal = identity rows for the relevant axes.
- Oblique = rotated rows.
- Compound oblique = product of rotation matrices applied to the base SliceToRAS.
- Camera position and view-up are *derived* from this matrix, not from the
  camera itself.

This would eliminate:
- View-up drift (because view-up = column of the matrix).
- Normal sign ambiguity (because the matrix defines orientation unambiguously).
- Compound rotation bugs (because matrix multiplication is well-defined).

### 8.3 Long-Term (R3 — Oblique-Aware Scroll + Annotations)

- Scroll along the oblique normal (perpendicular to displayed plane), not along
  the world axis.
- Crosshair endpoints should project correctly onto tilted planes.
- Annotation / measurement tools need the slice matrix to convert between
  2D screen and 3D patient coordinates.

### 8.4 Research to Pursue

| Topic | Where to look | Priority |
|-------|--------------|----------|
| David Gobbi's blog on `vtkImageResliceMapper` | Google "David Gobbi VTK reslice mapper" | **High** — he wrote the code |
| 3D Slicer `vtkMRMLSliceLogic.cxx` | https://github.com/Slicer/Slicer/blob/main/Libs/MRML/Logic/vtkMRMLSliceLogic.cxx | **High** — reference implementation |
| VTK source for `vtkImageResliceMapper::UpdateResliceInformation` | VTK repository on GitHub | **Medium** — understand exact slice normal computation |
| Cornerstone3D oblique MPR | https://github.com/cornerstonejs/cornerstone3D | **Medium** — modern web-based approach |

---

## 9. Reference: VTK Camera Geometry Cheat-Sheet

```
                     view_up ↑
                             |
                             |
                     ┌───────┼───────┐
                     │       │       │
                     │   focal_point │
  camera_position ●──────────●──────────► (image plane)
                     │               │
                     │               │
                     └───────────────┘

  direction_of_projection = normalize(focal_point - position)
  view_plane_normal       = -direction_of_projection  (points toward camera)
  distance                = |position - focal_point|

  For parallel projection:
    - distance affects nothing visually (parallel rays)
    - parallel_scale determines the visible world-height of the viewport
    - slice_normal = direction_of_projection (for SliceFacesCameraOn)

  CRITICAL:
    - Two cameras on OPPOSITE sides of the focal point, looking at the same
      focal point, produce MIRRORED images.
    - The view-up vector determines which direction is "up" in the viewport.
      A 180° rotation of view-up = upside-down image.
    - Roll(180) = negate view-up (mirror vertically).
    - Azimuth(180) = move camera to opposite side (mirror horizontally).
    - Azimuth(180) + Roll(180) = same camera side but both axes mirrored.
```

### How `Roll`, `Azimuth`, and `Elevation` Compose

| Operation | Effect on camera position | Effect on view-up |
|-----------|--------------------------|-------------------|
| `Roll(θ)` | Unchanged | Rotated by θ around direction_of_projection |
| `Azimuth(θ)` | Rotated by θ around view-up | Unchanged |
| `Elevation(θ)` | Rotated by θ around cross(view-up, direction) | Rotated by θ |

**Key insight:** `Roll(180)` and `Azimuth(180)` are NOT commutative.  
`Azimuth(180) + Roll(180) ≠ Roll(180) + Azimuth(180)`.

For coronal CT: `Azimuth(180)` first, then `Roll(180)`.  
Reversing the order produces a different image orientation.

---

## 10. Reference: How Other Viewers Do Oblique MPR

### 3D Slicer (Gold Standard)

**Architecture:**
```
vtkMRMLSliceNode
  ├── SliceToRAS (4×4 matrix)  ← defines the slice plane
  ├── FieldOfView, Dimensions
  └── Orientation (Axial/Sagittal/Coronal/Reformat)

vtkMRMLSliceLogic
  ├── reads SliceToRAS
  ├── computes reslice axes from SliceToRAS
  └── feeds them to vtkImageReslice

Pipeline:
  volume → vtkImageReslice(axes from SliceToRAS) → 2D output → display
```

**Key concept:**
The slice plane is defined by a **matrix**, not by camera state.
The camera is positioned to look at the slice plane, but the matrix is
the source of truth.  This means:
- View-up = column 1 of SliceToRAS (always consistent).
- Normal = column 2 of SliceToRAS (no sign ambiguity).
- Center = column 3 (translation) of SliceToRAS.
- Scrolling = move translation along the normal.

**What we can learn:**
- Separate the "what plane to show" from "how to set up the camera."
- Use a matrix as the source of truth, not the camera state.
- Derive everything from the matrix.

### Cornerstone3D

**Architecture:**
```
volume → viewport.setCamera({ position, focalPoint, viewUp })
       → internal vtkImageResliceMapper with SliceFacesCameraOn
```

Similar to our approach!  But they manage camera state through a
viewport abstraction that stores the "intended" camera separately from
VTK's internal camera state.

**What we can learn:**
- Even in a camera-driven approach, keep an **intended** camera state
  (equivalent to our baseline) and set the VTK camera from it every frame.
- Don't read back from the VTK camera — always write to it from your
  authoritative state.

---

## 11. Glossary

| Term | Definition |
|------|-----------|
| **Baseline camera state** | Camera position/focal/view-up captured after view creation + CT corrections.  The reference for all oblique computations (R1.2+). |
| **CT corrections** | `Roll(180)` for sagittal, `Azimuth(180)+Roll(180)` for coronal.  Applied to enforce radiological convention display for CT data. |
| **Direction matrix (compensated)** | The 3×3 matrix stored in VTK field data after Y-flip row-1 negation and (in MPR) X-flip column-0 negation. |
| **Doubly-compensated** | The state of the direction matrix after both Y-flip and X-flip adjustments. |
| **Oblique normal** | The normal vector of a non-axis-aligned slice plane.  Computed as `cross(crosshair_line_dir, source_slice_normal)`. |
| **R0 / R0.5 / R1 / R1.1 / R1.2** | Version designators for the rotation implementation.  See [section 3](#3-chronological-history). |
| **SliceFacesCameraOn** | `vtkImageResliceMapper` mode where the slice plane is perpendicular to the camera direction at the focal point. |
| **SliceToRAS** | 3D Slicer concept: a 4×4 matrix defining a slice plane in patient (RAS) coordinates.  The gold-standard approach for oblique MPR. |
| **View-up** | Camera vector defining which direction is "up" in the viewport.  Must be perpendicular to the viewing direction.  If it drifts, the image rotates. |
| **9-point sampling** | R1's method for computing oblique normals: center + 2×4 sample points along crosshair lines at two distance tiers. |

---

## Update Policy

For every change to the oblique/rotation subsystem:
1. Update this journal with a new section or entry in the relevant section.
2. Update `ZETA_MPR_ROTATION_ITK_VTK_STATUS.md` version log.
3. If the change affects the coordinate pipeline, also update
   `docs/IMAGE_PIPELINE_REFERENCE.md`.
4. Include: what was changed, why, what was tested, what remains unknown.

---

## Appendix A: Diagnostic Validation System (2026-02-17)

### A.1 What We Built and Why

File: `mpr_diagnostic_validator.py`

The core problem: when something goes wrong during oblique rotation (flip, mirror,
drift), we could only diagnose it visually — "the image looks wrong."  We had no
way to programmatically detect *what* went wrong or *when* it happened.

The diagnostic validator solves this by defining **10 mathematical invariant
checks** that run automatically on every oblique camera update.  Each check
produces a PASS/FAIL with a measured value and threshold.  Failures trigger
a `WARNING` log even when detailed diagnostics are disabled.

### A.2 Activation

Set environment variable before launching:
```
ZETA_MPR_DIAG=1          # enables info logging + visual markers
ZETA_MPR_DIAG_VERBOSE=1  # adds full camera snapshot dumps on failures
```

Or call from Python debugger:
```python
self._diag.log_full_snapshot("manual check")
self._diag.install_corner_markers()     # L/R/A/P/S/I labels
self._diag.install_corner_spheres()     # colored spheres at 8 corners
self._diag.install_diag_overlays()      # live metrics in each viewport
```

### A.3 The 10 Invariant Checks

| # | Check | What it validates | Pass condition | Why it matters |
|---|-------|-------------------|----------------|----------------|
| 1 | **handedness** | `det(right, up, dir)` sign = baseline | same sign | Sign flip = image mirrored (L/R swap) |
| 2 | **normal_hemisphere** | `dot(current_dir, baseline_dir) > 0` | dot > 0 | Negative = camera jumped to opposite side |
| 3 | **viewup_ortho** | `dot(view_up, direction) ≈ 0` | < 3° | Non-orthogonal = VTK re-ortho failed |
| 4 | **viewup_stability** | angle(current_up, baseline_up) < 90° | < 90° | > 90° = image upside-down |
| 5 | **focal_at_crosshair** | ‖focal − crosshair_center‖ < 2mm | < 2mm | Drift = slice not at crosshair |
| 6 | **distance_stable** | ‖current_dist − baseline_dist‖ < 5% | < 5% | Large change = zoom corruption |
| 7 | **right_vector** | angle(current_right, baseline_right) < 120° | < 120° | > 120° = L/R swap |
| 8 | **parallel_scale** | ‖scale_change‖ < 1% | < 1% | Unexpected zoom during oblique |
| 9 | **plane_containment** | `dot(center − focal, dir) ≈ 0` | < 0.5mm | Non-zero = crosshair centre off-plane |
| 10 | **mutual_orthogonality** | pairwise dot of 3 view normals ≈ 0 | < 5° deviation from 90° | Violated = oblique corrupted triplet |

### A.4 Visual Markers

**Corner labels (L/R/A/P/S/I):** Derived from the doubly-compensated direction
matrix.  If labels appear wrong (e.g., "L" on the right side after rotation),
it means either: (a) the direction matrix is wrong, or (b) the camera
corrections (Roll/Azimuth) are incorrect for this view.

**Important limitation:** Corner labels are computed from the direction matrix
at initialisation time.  They do NOT account for the CT-specific `Roll(180)` and
`Azimuth(180)` corrections applied afterward.  This means labels may appear
wrong even when the image is correct (because the Roll/Azimuth flips the
display).  **This is itself a diagnostic signal** — it reveals that our label
computation must incorporate the camera corrections to be accurate.

**Corner spheres:** 8 colored spheres at volume corners.  In each 2D view, you
see the spheres that intersect the current slice.  If a sphere that should be
on the left appears on the right after rotation, the image is mirrored.
- RED = origin (min X, Y, Z)
- GREEN = max X
- BLUE = max Y
- YELLOW = max Z
- WHITE = max all

**Live diagnostic overlay:** Bottom-left of each view shows:
- `det=+1` or `det=-1` — handedness
- `n_err=X.X°` — camera direction angle from baseline
- `f_off=X.XXmm` — focal point distance from crosshair centre
- `ang=X.X°` — current crosshair rotation angle
- `OK` or `FAIL(n)` — number of failed checks

### A.5 How to Use for Debugging

**Scenario: "coronal view flips when I rotate axial"**

1. Set `ZETA_MPR_DIAG=1` and `ZETA_MPR_DIAG_VERBOSE=1`.
2. Launch the app, load a study, open MPR.
3. Slowly rotate the axial crosshair.
4. Watch the coronal live overlay:
   - If `det` changes from `+1` to `-1` → handedness flip (mirror).
   - If `n_err` jumps to >90° → camera went to wrong side.
   - If `f_off` increases → focal point drifted from crosshair.
5. Check the log file for `[MPR_DIAG] oblique:coronal: X/Y FAILED` lines.
6. The verbose dump shows exact camera vectors before the failure.

**Scenario: "image looks rotated/tilted after dragging crosshair centre"**

1. Same setup.
2. Enable oblique (rotate slightly), then drag the crosshair centre.
3. Check `viewup_stability` and `right_vector` — if either fails, the
   view-up or right vector changed during the drag.
4. Check `focal_at_crosshair` — if it fails, the focal point didn't
   follow the crosshair properly.

**Scenario: "reconstruction lines are in the wrong position"**

1. Check `plane_containment` — if the crosshair centre is off the
   displayed plane, the reconstruction lines will be at wrong positions.
2. Check `focal_at_crosshair` — the slice passes through the focal
   point, so if focal ≠ crosshair, everything shifts.

### A.6 Open Questions About The Validation System Itself

**Q-V1:** The `expected_corner_labels` function computes labels from the
direction matrix alone, without accounting for camera Roll/Azimuth.  Can we
enhance it to incorporate camera transforms?  This would require either:
(a) applying Roll/Azimuth to the label vectors mathematically, or
(b) using VTK's `WorldToDisplay` to find where the corner points actually
appear on screen and labelling accordingly.

**Q-V2:** Check 10 (mutual orthogonality) assumes the three views should be
~90° apart.  With oblique rotation, this is no longer true.  Should we adjust
the expected angle?  For single-axis rotation by θ degrees, two pairs should be
90° and one pair should be 90°−θ.  This is not yet implemented.

**Q-V3:** Can we add a check for the **cross-product sign consistency** of the
9-point sampling?  Specifically: does `cross(h_dir, slice_normal)` always point
in the same hemisphere as `cross(v_dir, slice_normal)` crossed with the expected
rotation axis?  This would catch the sign ambiguity in the 9-point code before
it reaches `_set_oblique_camera`.
