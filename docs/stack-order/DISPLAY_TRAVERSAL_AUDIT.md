# DISPLAY_TRAVERSAL_AUDIT

## Structured Analysis of Display-Index-to-Patient-Motion Semantics — AIPacs v3.0.2

**Purpose:** For each anatomical plane, precisely define what patient-space motion occurs when
`display_k` changes by +1 (index increases). Then evaluate whether the current pipeline output
matches the canonical clinical convention. Uses structured `[DISPLAY_TRAVERSAL_DIRECTION]` tag format.

---

## Reference Coordinate System

DICOM LPS (Left-Posterior-Superior):
- L = +X (patient's left)
- P = +Y (patient's posterior)
- S = +Z (patient's superior)

Standard Head-First Supine (HFS) Image Orientation Patient (IOP):
- Row direction: [1, 0, 0] (L→R along +X)
- Col direction: [0, 1, 0] (P→A along +Y)
- Slice normal: cross(row, col) = [0, 0, +1] (I→S along +Z)

Typical slice spacing: 5.0 mm (example)

---

## [DISPLAY_TRAVERSAL_DIRECTION] AXIAL — Advanced (VTK) Pipeline

### WITHOUT K-flip (current default before correction)

```
[DISPLAY_TRAVERSAL_DIRECTION]
  plane=AXIAL
  backend=VTK_ADVANCED
  sort_method=canonical_sort_instances (IPP ascending)
  k_flip_applied=False

  k=0:
    file=Instance_0001.dcm (or lowest IPP-Z file)
    IPP_approx=[x, y, z_INFERIOR]   # e.g. z=-100.0 mm
    patient_label=INFERIOR (feet-end)
    lps=[0.0, 0.0, -100.0]

  k=N-1:
    file=Instance_NNNN.dcm (highest IPP-Z file)
    IPP_approx=[x, y, z_SUPERIOR]   # e.g. z=+100.0 mm
    patient_label=SUPERIOR (head-end)
    lps=[0.0, 0.0, +100.0]

  transition k=0 → k=1:
    lps_before=[0.0, 0.0, -100.0]
    lps_after =[0.0, 0.0, -95.0]    # one slice_step = +5.0mm
    delta_lps =[0.0, 0.0, +5.0]
    dominant_motion_axis=Z
    motion_sign=POSITIVE (+Z = Superior direction)
    movement_label="Inferior → Superior"
    matches_canonical_policy=False
    canonical_policy="display_k increasing should move Superior → Inferior (negative Z)"

  scroll_semantics:
    physical_scroll_up   → delta>0  → step=-1 → k decreases → moves INFERIORLY
    physical_scroll_down → delta<0  → step=+1 → k increases → moves SUPERIORLY
    user_perception: "scrolling down moves up into the body" — BACKWARDS
```

### WITH K-flip applied (after DisplayGeometry.apply_k_flip_for_stack_order)

```
[DISPLAY_TRAVERSAL_DIRECTION]
  plane=AXIAL
  backend=VTK_ADVANCED
  sort_method=canonical_sort_instances (IPP ascending) + K-flip
  k_flip_applied=True

  k=0:
    file=Instance_NNNN.dcm (highest IPP-Z file — flipped to front)
    IPP_approx=[x, y, z_SUPERIOR]   # e.g. z=+100.0 mm
    patient_label=SUPERIOR (head-end)
    lps=[0.0, 0.0, +100.0]

  k=N-1:
    file=Instance_0001.dcm (lowest IPP-Z file — flipped to back)
    IPP_approx=[x, y, z_INFERIOR]   # e.g. z=-100.0 mm
    patient_label=INFERIOR (feet-end)
    lps=[0.0, 0.0, -100.0]

  transition k=0 → k=1:
    lps_before=[0.0, 0.0, +100.0]
    lps_after =[0.0, 0.0, +95.0]    # one slice_step = -5.0mm
    delta_lps =[0.0, 0.0, -5.0]
    dominant_motion_axis=Z
    motion_sign=NEGATIVE (-Z = Inferior direction)
    movement_label="Superior → Inferior"
    matches_canonical_policy=True
    canonical_policy="display_k increasing should move Superior → Inferior (negative Z)" ✓

  scroll_semantics:
    physical_scroll_up   → delta>0  → step=-1 → k decreases → moves SUPERIORLY
    physical_scroll_down → delta<0  → step=+1 → k increases → moves INFERIORLY
    user_perception: "scrolling down moves toward feet" — CORRECT
```

---

## [DISPLAY_TRAVERSAL_DIRECTION] AXIAL — FAST Pipeline (PYDICOM_QT)

```
[DISPLAY_TRAVERSAL_DIRECTION]
  plane=AXIAL
  backend=FAST_PYDICOM_QT
  sort_method=InstanceNumber ascending (scanner-defined)
  k_flip_applied=N/A (not applicable to FAST path)

  CASE A: Standard HFS CT (InstanceNumber=1 at superior, typical for most CT scanners):
    k=0: InstanceNumber=1, patient_label=SUPERIOR
    k=N-1: InstanceNumber=N, patient_label=INFERIOR
    k_increasing → S→I → matches_canonical_policy=True

  CASE B: Some MRI / non-standard acquisitions (InstanceNumber=1 at inferior):
    k=0: InstanceNumber=1, patient_label=INFERIOR
    k=N-1: InstanceNumber=N, patient_label=SUPERIOR
    k_increasing → I→S → matches_canonical_policy=False

  NOTE: FAST pipeline has NO geometry-based normalization.
  Correctness depends entirely on scanner InstanceNumber assignment convention.
  IPP-based correction is deliberately excluded (see _sort_slices docstring).
```

---

## [DISPLAY_TRAVERSAL_DIRECTION] SAGITTAL — Advanced (VTK) Pipeline

For a sagittal series:
- Row direction: [0, 1, 0] (P→A along +Y)
- Col direction: [0, 0, -1] (S→I along -Z)
- Slice normal: cross(row, col) = cross([0,1,0], [0,0,-1]) = [−1×0−0×(−1), 0×0−0×(−1), 0×(−1)−1×0] = [1, 0, 0] (+X = Right direction)

```
[DISPLAY_TRAVERSAL_DIRECTION]
  plane=SAGITTAL
  backend=VTK_ADVANCED
  slice_normal=[+1, 0, 0]  # points Right (+X in LPS = patient's right)
  canonical_sort_direction=ascending dot(IPP, [1,0,0]) = ascending X = Left→Right

  sort result:
    k=0: min X = leftmost slice = patient's LEFT side
    k=N-1: max X = rightmost slice = patient's RIGHT side

  k_increasing direction:
    movement_label="Left → Right"
    delta_lps=[+spacing_x, 0, 0]
    motion_sign=POSITIVE (+X)
    matches_canonical_policy=False
    canonical_policy="display_k increasing should move Left → Right (positive X)?
    ACTUAL canonical: L→R means display_k increasing → patient LESS left (toward Right)"

  CANONICAL FOR SAGITTAL:
    display_k increasing → Left → Right (viewing right-to-left from screen perspective)
    In LPS: Left=+X, Right=-X direction from Left
    Ascending X means first slice is most Left, last slice most Right
    This IS L→R motion (matches canonical ✓) without needing K-flip

  WITH K-flip (if applied):
    k=0 = Right side, k increasing → R→L (WRONG for sagittal if canonical wants L→R)

  CONCLUSION: For standard sagittal (slice_normal=[1,0,0], ascending X):
    NO K-flip needed; current ordering is already L→R (canonical for sagittal).
```

---

## [DISPLAY_TRAVERSAL_DIRECTION] CORONAL — Advanced (VTK) Pipeline

For a coronal series:
- Row direction: [1, 0, 0] (L→R along +X)
- Col direction: [0, 0, -1] (S→I along -Z)
- Slice normal: cross(row, col) = cross([1,0,0], [0,0,-1]) = [0×(−1)−0×0, 0×1−1×(−1), 1×0−0×1] = [0, 1, 0] (+Y = Posterior direction)

```
[DISPLAY_TRAVERSAL_DIRECTION]
  plane=CORONAL
  backend=VTK_ADVANCED
  slice_normal=[0, +1, 0]  # points Posterior (+Y in LPS)
  canonical_sort_direction=ascending dot(IPP, [0,1,0]) = ascending Y = Anterior→Posterior

  sort result:
    k=0: min Y = most anterior = patient's ANTERIOR (front)
    k=N-1: max Y = most posterior = patient's POSTERIOR (back)

  k_increasing direction:
    movement_label="Anterior → Posterior"
    delta_lps=[0, +spacing_y, 0]
    motion_sign=POSITIVE (+Y = Posterior direction)
    matches_canonical_policy=False
    canonical_policy="display_k increasing should move Posterior → Anterior (negative Y)"

  WITH K-flip:
    k=0 = Posterior, k increasing → P→A (canonical ✓ for coronal)
```

---

## Summary Matrix

| Plane | Sort Normal | k=0 WITHOUT K-flip | k_increasing WITHOUT | Canonical Target | Need K-flip? |
|-------|------------|-------------------|--------------------|-----------------|--------------|
| AXIAL (HFS) | [0,0,+1] | Inferior (min Z) | I→S (wrong) | S→I | YES |
| SAGITTAL (standard) | [+1,0,0] | Left (min X) | L→R | L→R | NO |
| CORONAL (standard) | [0,+1,0] | Anterior (min Y) | A→P (wrong) | P→A | YES |

**K-flip is needed for AXIAL and CORONAL; NOT needed for standard SAGITTAL.**

This is exactly what `audit_stack_order_convention` in `DisplayGeometry` should detect and return.

---

## Wheel Scroll Direction Validation

With canonical ordering applied (K-flip active for axial/coronal):

| Action | `angleDelta().y()` | `step` | index change | Patient motion (axial HFS) | Correct? |
|--------|-------------------|--------|-------------|---------------------------|---------|
| Physical wheel UP (forward) | > 0 | -1 | decreases | move Superiorly | ✓ |
| Physical wheel DOWN (backward) | < 0 | +1 | increases | move Inferiorly | ✓ |
| Drag slider 0→N (top→bottom) | n/a | n/a | increases | Superior→Inferior | ✓ |

**After K-flip:** Scroll direction semantics are radiologically correct.

---

## [DISPLAY_TRAVERSAL_DIRECTION] Inference from `_bind_geometry_contract` (viewer_2d.py)

The `_bind_geometry_contract` method in `viewer_2d.py` calls:
1. `DisplayGeometry.from_source_geometry(sg, metadata)` — builds effective affine
2. `display_geometry.audit_stack_order_convention(plane, body_part)` — returns 5-tuple
3. If `order_matches=False`: calls `display_geometry.apply_k_flip_for_stack_order(n_slices, reason)`

The K-flip transform is a post-multiplication of the existing `_effective_display_ijk_to_lps_4x4`:

```python
# _k_flip_4x4 builds: k_corrected = (N-1) - k_raw
# Matrix form (4x4 homogeneous):
# [1  0   0      0    ]
# [0  1   0      0    ]
# [0  0  -1   N-1    ]
# [0  0   0      1    ]
```

This means the effective display-to-patient transform now has:
- `display_k=0` → `LPS = origin + (N-1) * slice_step * slice_normal` = Superior slice
- `display_k=N-1` → `LPS = origin` = Inferior slice
- `d(LPS)/d(display_k) = -slice_step * slice_normal` = negative Z direction = S→I motion
