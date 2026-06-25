# Panoramic Reconstruction Quality — Review & Improvement Plan (2026-06-23)

**Scope:** the *lightweight* Dental Curve MPR viewer (Patient-Tab, MPR dropdown) —
the panoramic image only. **Analysis only; no reconstruction code changed.**
Cross-section quality is out of scope (it is a direct reslice and already adequate).

**Engine reviewed:** `modules/mpr/zeta_mpr/curved_mpr.py`
(`CurvedMPRGenerator` → `ResliceEngine`), display in
`modules/mpr/curved_mpr/curved_mpr_panoramic_view.py`.

---

## 1. Current reconstruction pipeline (as-built)

```
User arch points (axial)
   ↓                        toolbar_manager._generate_curved_mpr_from_points
Path3D  (Catmull-Rom spline, tension 0.5)            curved_mpr.py Path3D
   ↓   arc-length re-parameterized (uniform by length)   _compute_arc_lengths :209
Sampling along curve: num_positions frames          generate_panoramic_view :1549
   num_positions = max(100, min(500, total_len*3))               :1580
   ↓
PlaneGenerator.generate_frames(num_positions)        :330
   parallel-transport frames (origin,tangent,normal,binormal)
   ↓
Per-position orthogonal slice (radial × vertical)    _extract_orthogonal_slice_for_panoramic :1092
   vtkImageReslice, CUBIC, 2D, single Z              SetInterpolationModeToCubic() :1127
   output spacing = min(input spacing) on X & Y      :1152
   ↓
Straightened volume  (num_positions × height × thickness)   :917
   ↓
Projection across radial axis  → MEAN (default)      np.mean(..., axis=2) :958
   ↓
Vertical flip (superior on top)                      np.flip(axis=1) :985
   ↓
Auto-crop empty borders + per-axis spacing           :990, :1043
   ↓
vtkImageData → vtkImageViewer2 (display), camera Zoom 3×
```

Note there is also a **fallback** panoramic (`_create_mip_image`,
`curved_mpr_panoramic_view.py`) used only when the engine returns nothing — it does
a slab-MIP then a 10× vertical `scipy.ndimage.zoom(order=1)` (bilinear) upsample,
which is **very** soft. The true engine path above is the normal one; the fallback's
10× bilinear stretch is a second, separate softness source if it ever triggers.

---

## 2. Current interpolation method

**Cubic** (`vtkImageReslice.SetInterpolationModeToCubic()`, `:1127`, and the
cross-section/curved reslice at `:1277`, `:2058`). This is already the best-practice
choice for MPR/CBCT reformations (cubic / cubic-B-spline). **Interpolation is NOT the
bottleneck** — raising it further (e.g., windowed-sinc) yields marginal gains at real
CPU cost. Do not spend effort here.

## 3. Current projection method

**Mean intensity projection** across the radial slab (`np.mean(straightened_volume,
axis=2)`, `:958`); `'max'` (MIP) is supported but not used by the caller. Mean over a
thick slab is the **primary cause of the soft/low-contrast look** (see §5).

## 4. Current spacing / resolution analysis

| Quantity | Current value | Code |
|---|---|---|
| Output pixel spacing (radial & vertical) | `min(input spacing)` — e.g. 0.30 mm on a 0.3 mm CBCT | `:887`, `:1152` |
| Along-curve samples | `max(100, min(500, total_len × 3))` ≈ 3/mm, **capped at 500** | `:1580` |
| Along-curve (X) pixel spacing | `total_len / num_positions` ≈ 0.33 mm (≈ 3.0 mm on a long arch once capped) | derived |
| Slab thickness | 10 mm default (`_curved_mpr_thickness_mm`, panel slider 2–30 mm) → ~34 radial samples @0.3 mm | `:1551`, panel |
| Vertical height | **caller passes 80 mm** (toolbar) but wrapper default is **150 mm** | `:1369` / `:1552` |
| Output resolution (typical 130 mm arch, 80 mm height) | ≈ 390 × 268 px | derived |
| Anti-alias on along-curve resample | none (point samples at frame centers) | — |

Spacing handling itself is **sound**: output spacing follows the minimum input
spacing (no undersampling at the pixel level) and per-axis spacing is recomputed
after crop (`:1043`) so measurements stay metric. The weak points are sampling
*density* on long arches and the projection, not the spacing math.

---

## 5. Quality bottlenecks (ranked)

1. **Mean projection over a fixed 10 mm slab — dominant.** Averaging ~34 radial
   samples blends the structure of interest with off-plane bone/air. The literature
   is explicit: *"panoramic images generally have low contrast because excessive
   non-interest tissue participates in the reconstruction."* Lamina dura, periodontal
   ligament space, fine cortical lines and apices are exactly the thin features that a
   thick mean wipes out.
2. **No post-reconstruction sharpening.** Even a correct reconstruction looks soft on
   screen without a light unsharp mask; every commercial dental panoramic applies one.
3. **Slab is fixed, not adaptive.** A single flat 10 mm trough can't follow a tilted
   arch (buccal cortex of one region + lingual of another fall in/out of the slab),
   so different teeth are differently blurred.
4. **Along-curve sampling cap (500).** On arches > ~167 mm the X step grows past the
   pixel spacing → along-curve blur / aliasing of inter-proximal detail.
5. **Height default mismatch (150 mm wrapper vs 80 mm caller).** Harmless to geometry
   but means the wrapper default is not what ships; worth aligning so tuning is
   predictable.
6. **Fallback `_create_mip_image` 10× bilinear upsample.** If the engine ever falls
   back, the panoramic is heavily blurred by the 10× vertical bilinear stretch.
7. **Display zoom 3× on a ~0.3 mm image** with linear display interpolation — minor,
   but compounds the perceived softness.

Interpolation (cubic), spacing math, and the curve fit are **not** bottlenecks.

---

## 6. Recommended reconstruction improvements

Ordered by impact-per-risk. All are **appearance/sampling** changes — none alter the
volume geometry, coordinate system, spacing/origin/orientation, or the cross-section.

| # | Change | What | Expected effect |
|---|---|---|---|
| R1 | **Projection: mean → thin-slab + ray-sum/MIP hybrid** | Keep mean as a "thick/overview" option, but default to a **thinner effective trough** combined with a sharper projector. Two good options: (a) **soft-MIP** (max over a thin slab — emphasizes enamel/cortical/lamina dura, the dental standard); (b) **percentile/ray-sum** (e.g. 80th-percentile or weighted ray-sum that down-weights soft tissue). | **Largest** sharpness/contrast gain on roots, lamina dura, apices. |
| R2 | **Thickness presets (thin/medium/thick)** | Map the existing 2–30 mm slider to named presets — thin ≈ 3–5 mm (detail), medium ≈ 8–10 mm (current), thick ≈ 15–30 mm (overview). Default **medium-thin**. | Lets the reader trade detail vs coverage; thin recovers fine structures. |
| R3 | **Raise along-curve sampling cap** | Make density follow output spacing (≈ `total_len / output_spacing`, not a hard 500 cap); keep an upper safety bound (e.g. 1500) for performance. | Removes along-curve blur on long/adult arches. |
| R4 | **Adaptive/curved trough (later)** | Center the slab on the detected arch per-column rather than a flat 10 mm — reduces non-interest tissue. Pairs with the curve-adjustment work in §9. | Uniform sharpness across the whole arch. |
| R5 | **Keep cubic; add optional anti-alias only if downsampling** | No change to interpolation order. Only add a 1-px Gaussian pre-filter *if* a future thick-slab path downsamples (avoids aliasing). | Neutral; prevents artifacts. |
| R6 | **Align height default (150→80 mm)** and **retire the 10× bilinear fallback** (use cubic / true engine) | Predictable tuning; removes the catastrophic-soft fallback. | Removes a latent soft path. |

**Recommended default after the plan:** thin-to-medium slab (≈ 6 mm) + soft-MIP (or
weighted ray-sum) + density tied to spacing + a mild unsharp mask (§7). All
flag-gated, mean+10 mm preserved as the legacy/overview mode.

## 7. Recommended sharpening strategy

- **Method: single-pass Unsharp Mask** on the final 2-D panoramic (after projection,
  before display). `sharp = img + amount × (img − Gaussian(img, σ))`.
  - σ ≈ 0.8–1.2 px (≈ 0.3 mm), **amount ≈ 0.4–0.7** (conservative).
  - Clip to the input range; compute in float; apply **before** windowing.
- **Optional later: 2-scale (multi-scale) unsharp** (small σ for micro-edges + larger
  σ for macro-contrast) for a more "commercial" look — only if single-pass is
  insufficient.
- **Guardrails (do not oversharpen):** cap `amount`; never sharpen MIP output as
  hard as mean output (MIP is already high-frequency); make it a flag with an
  intensity control; document that sharpening is a **display enhancement**, not a
  measurement input (measurements use the unsharpened pixel/world geometry).
- **Avoid:** aggressive edge-enhancement / high-pass that manufactures lamina-dura-like
  lines (false diagnostic structure) — explicitly out of scope.

Estimated effect: unsharp alone makes the *current* mean panoramic look markedly
crisper; combined with R1 it reaches "confident visual assessment" territory.

## 8. Left/Right orientation validation method

The panoramic X axis is the **curve-traversal direction**; whether image-left = patient-
right depends on (a) the order the user placed points and (b) the volume's patient
orientation. This must be resolved from DICOM, not assumed.

**Authority:** the volume already carries the geometry contract — the `DirectionMatrix`
field-data array built from **Image Orientation Patient (0020,0037)** +
**Image Position Patient (0020,0032)** (see `pydicom_lazy_volume.py::_to_iop_matrix`
and `docs/pipelines/mpr-geometry-pipeline.md`). The Dental Curve VTK host already
reslices the **StandardMPRViewer's radiologically X-flipped** volume, so the axial the
user traces on is already in a known patient frame.

**Validation procedure (recommended):**
1. Take the first/last arch points in **world/patient coordinates** and project the
   curve-traversal vector onto the volume's **patient L→R axis** (column of the
   DirectionMatrix / LPS X). The sign tells you which end of the panoramic is the
   patient's right vs left.
2. Render **"R" and "L" markers** at the two ends accordingly (and a midline tick),
   derived from that sign — never from pixel index alone.
3. **Self-test:** reconstruct a volume with known IOP/IPP (or the synthetic test
   volume) and assert the R marker lands on the patient-right end for both
   left→right and right→left point ordering (the marker must follow patient space,
   not click order).
4. Regression guard: a unit test that feeds a known DirectionMatrix + curve direction
   and checks the computed L/R sign (pure, no VTK).

This makes L/R a **derived, validated** label, satisfying "must be validated using
DICOM orientation metadata rather than assumptions."

## 9. Recommended curve-adjustment workflow

Goal: let the reconstruction plane follow root direction / jaw anatomy when a single
axial curve isn't enough. Evaluation of the four options:

| Option | What | Pros | Cons | Verdict |
|---|---|---|---|---|
| **C — global tilt/offset** | one tilt + Z-offset for the whole slab | trivial, immediate, low risk | can't follow local variation | **Phase 1** (cheap win) |
| **A — per-point Z offset** | each arch point stores X,Y,**Z** | local control, fits existing point model, moderate effort | needs a 2nd interaction to set Z | **Phase 2** (best value) |
| **B — adjust from sagittal** | drag the plane in a sagittal view | intuitive | needs a synced sagittal view + cross-widget plumbing | **Phase 2 UX** (pairs with A) |
| **D — second sagittal reference curve** | full 3-D arch from two curves | most accurate (true 3-D trough) | most complex; new geometry surface | **Phase 3** (defer) |

**Recommendation:** Phase 1 = Option C (global tilt/offset slider) — small, safe,
already useful for tilted arches. Phase 2 = Option A (per-point Z) with Option B's
sagittal handle as the editing UX (the VTK host from the FAST fix already gives you a
synced sagittal pane to drag in). Defer Option D until A/B are validated. In all cases
the Z/tilt only re-positions the **sampling frames** — it must flow through the *same*
`PlaneGenerator`/`ResliceEngine` so geometry stays single-source (see §10).

## 10. Estimated diagnostic-quality improvement per change

Subjective scale (Δ on a 1–5 "confident assessment" scale), effort, risk:

| Change | Quality Δ | Effort | Risk | Notes |
|---|---|---|---|---|
| **R7 Unsharp mask (§7)** | **+1.0–1.5** | S | Low | Biggest gain for least work; flag-gated, display-only |
| **R1 Thin-slab + soft-MIP/ray-sum** | **+1.0–1.5** | M | Med | The structural fix for root/lamina-dura softness; keep mean as legacy |
| **R2 Thickness presets** | +0.5 | S | Low | Reader control; mostly UI over existing slider |
| **R3 Sampling density tied to spacing** | +0.3–0.7 (long arches) | S | Low | Removes along-curve blur on adult arches |
| **R6 Align height default + retire 10× fallback** | +0.2 (and removes a soft failure mode) | S | Low | Predictability + safety |
| **R4 Adaptive curved trough** | +0.5–1.0 | L | Med | Uniform sharpness; pairs with §9 |
| **§9 Curve Z/tilt (C→A→B)** | +0.5–1.5 (tilted arches) | M→L | Med | Phased; biggest for non-planar arches |
| Interpolation order ↑ (sinc) | ~0 | M | Low | **Not recommended** — cubic already adequate |

**Suggested sequencing:** R7 + R6 first (1 small flag-gated PR, immediate visible win),
then R1 + R2 (the structural sharpness fix), then R3, then §9 Phase 1 (tilt) and L/R
markers (§8), then R4 / §9 Phase 2.

---

## Architecture alignment (your §5 requirement)

Every recommendation above stays on the existing geometry foundation — **no parallel
pipeline**:

- Reconstruction keeps using `CurvedMPRGenerator` / `ResliceEngine` /
  `PlaneGenerator` and the volume's existing spacing/origin/**DirectionMatrix**
  (IOP/IPP). Projection, thickness, sampling-density and sharpening are
  **post/within-sampling** changes — they do not touch coordinates.
- On the FAST viewer the picking + volume already come from the **StandardMPRViewer**
  host (`dental_curve_vtk_host.py`), i.e. the standard-MPR geometry — the panoramic is
  built from that same trusted, X-flipped volume, so L/R (§8) and any curve Z/tilt
  (§9) resolve in one coordinate system.
- All changes ship **flag-gated, default-preserving** (mean + 10 mm + no-sharpen
  remains the kill-switch baseline), each with a guard test, per repo convention.
- This is consistent with `UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md` (reuse the
  standard MPR base; don't fork geometry) and the Dental Curve MPR as-built
  (`docs/pipelines/dental-curve-mpr.md`).

**Do-not-do:** independent geometry/resampling system; HU-based fixed windows (CBCT
gray values aren't standardized HU — keep the robust percentile windowing already
landed); aggressive high-pass that fabricates edges; any change that alters the
cross-section or the measurement world-coordinates.

---

## Sources

- [CBCT image acquisition & reconstruction (Dentalcare CE)](https://www.dentalcare.com/en-us/ce-courses/ce531/image-acquisition-and-reconstruction)
- [CBCT basics & applications in dentistry (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5750833/)
- [Automatic high-contrast panoramic reconstruction from dental CBCT (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0169260719303384)
- [Low-dose CBCT: cubic B-spline interpolation + denoising (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7878746/)
- [CBCT gray values vs Hounsfield units — not applicable (PubMed)](https://pubmed.ncbi.nlm.nih.gov/25315442/)
- Internal: `modules/mpr/zeta_mpr/curved_mpr.py`, `docs/pipelines/dental-curve-mpr.md`,
  `docs/pipelines/mpr-geometry-pipeline.md`,
  `docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`
