# EagleEye Mammography 3D Cursor — Accuracy & Precision Plan (2026-07-14)

**Scope:** the CC↔MLO lesion-correspondence tool in the EagleEye AI module
(`modules/ai_imaging/ai_module_ui/cursor_3d/`, button wired in
`service_tab/imaging_tab.py:1314`). This is **not** the 2D-viewer "3D cursor" —
no code is shared.

**Status:** PLAN ONLY. No code changed. Every phase below is flag-gated,
default-OFF until validated in the clinical lane, with the legacy path preserved
as a kill switch.

**Companion:** the as-built code review of the same module (structure, workflow,
dead code, bug list) — this document assumes it.

---

## 1. TL;DR — the single most important finding

> **We draw an Annular-Band (arc) locus using a Straight-Strip (axial) radius.**
> It is a chimera that honours neither published method's assumption. And the
> arc — the geometry we render — is the **weakest** of the three published
> methods, confirmed independently by two studies (n=200 and n=711).

The good news is the corollary: **the quantity our code already computes
(`compute_lesion_depth_mm`, the perpendicular/axial distance) is the input to
the *best* of the two cheap methods.** We are computing the right number and
drawing the wrong shape. The highest-value near-term fix is therefore small,
not large.

---

## 2. Evidence base (all citations verified 2026-07-14)

### 2.1 The two cheap geometric methods, precisely defined

Both originate in Zheng et al., *Acad Radiol* 2009 (the paper that coined the
comparison), and are re-used verbatim by the 2025 BMC study:

- **AB — Annular Band.** An arc centred on the nipple, assuming the **radial**
  distance `dr` (= √(X²+Y²), i.e. the classic Kopans nipple-to-lesion distance,
  "NOD") is preserved between CC and MLO.
- **SS — Straight Strip.** A line parallel to the chest wall, assuming the
  **axial** distance `dl` — the lesion's projection onto the centreline through
  the nipple perpendicular to the chest wall — is preserved between views.

Our `geometry.compute_lesion_depth_mm()` computes **`dl`** (it projects onto a
chest-wall normal, tilted by the pectoral angle in MLO). That is the SS
quantity, and it is arguably a *better* SS than the naive one, because we tilt
the MLO centreline by the real pectoral angle instead of assuming horizontal.

`correspondence_arc.compute_correspondence_arc()` then feeds that `dl` in as the
**radius of an arc** — which is AB geometry. Hence the chimera.

### 2.2 Measured accuracy — the numbers that should drive our decisions

**Wang S, Xu Z, Zheng B, et al., BMC Med Imaging 25:322 (2025)** — 711 patients
(499 calcification + 212 mass pairs), reference standard = two senior
radiologists' bounding boxes. Metric = **absolute error (AE)**: the shortest
distance from the true lesion centre to the predicted curve.

| Method | Median AE | IQR | Max (= band for 100% sensitivity) | AE > 10 mm |
|---|---|---|---|---|
| **GM** (3D uncompress → rotate → recompress) | **3.03 mm** | 1.45–5.55 | ±19.5 mm | **7 %** |
| **SS** (straight strip) | 4.59 mm | 1.91–8.19 | ±32.2 mm | 15.5 % |
| **AB** (annular band / arc — *what we draw*) | 5.78 mm | 2.44–10.71 | ±39.3 mm | **27.4 %** |

All pairwise differences P < 0.001. Cross-view correlation was **0.923 for the
axial distance** vs **0.917 for the radial** — the SS assumption holds slightly
better than the AB assumption in real anatomy. GM reversibility was confirmed
(CC→MLO 2.96 mm vs MLO→CC 2.86 mm, P = 0.749).

**Zheng B, Tan J, Ganott MA, Chough DM, Gur D., Acad Radiol 16(11):1338-47
(2009)** — 200 positive + 200 negative exams, independent cohort, independent
decade. Same verdict:

- Search-area width needed to capture **all** 200 paired masses:
  **28 mm (SS)** vs **68 mm (AB)** — the arc needs a search area ~2.4× wider.
- False positives eliminated by the two-view search: **25.0 % (SS)**,
  14.5 % (mixed), **11.9 % (AB)**.
- A third **"mixed"** area was tested — bounded by a straight line on the
  chest-wall side and an annular arc on the nipple side. It landed *between* the
  two. **It did not beat SS.**
- Authors' conclusion: *the straight strip required a smaller search area and
  achieved the highest CAD performance.*

**Kita Y, Highnam R, Brady M., Comput Vis Image Underst 83(1):38-56 (2001)** —
the curved-epipolar deformation model, and the origin of the MLO-angle finding:

- Mean (max) distance of the mass centre to the predicted epipolar curve:
  **4.1 mm (12.4 mm) when the MLO angle is KNOWN** (11 cases) vs
  **6.8 mm (27.8 mm) when it is UNKNOWN** (37 cases).
- Caveat we must state honestly: small n, and the two groups are different
  cases — this is suggestive, not a controlled comparison. But it is the only
  direct measurement of the value of the MLO angle, and it points the same way
  as common sense.

**Implication for us:** we already ask the radiologist to *draw* the pectoral
line in the guided workflow. That is a **better** angle source than DICOM
metadata. The Kita finding therefore validates our existing design — the
remaining exposure is only the *fallback* path (hard-coded 45°/50°) when no line
is drawn.

### 2.3 The 3D geometric model (GM) — our real accuracy ceiling

Construction (BMC 2025 §"Geometric model", detailed in **Duan X, Qin G, Ling Q,
et al., IEEE Access 7:31586-97, 2019**):

1. Reconstruct an **uncompressed 3D breast** from the breast contours extracted
   from *both* the CC and MLO images.
2. Represent the ROI centre by **three points** in that 3D breast (this is what
   turns a point into a *curve* rather than a point, absorbing the depth
   ambiguity).
3. **Rotate** the 3D breast to simulate the CC→MLO orientation change
   (typically 30°–60° — i.e. exactly the pectoral/MLO angle we already collect).
4. **Re-compress** in the MLO direction.
5. Project the three points by X-ray projection principles and **interpolate
   them into a continuous curve with a quadratic**.

Result: the radiologist clicks the lesion in CC; a predicted curve appears in
MLO. Median AE 3.03 mm; >10 mm failures drop from 27.4 % (AB) to 7 %.

**We already possess every input this needs**: live breast-contour segmentation
(`breast_contour.segment_breast_contour`, the one auto-detector actually running
today), a manually-picked nipple, and a manually-drawn pectoral angle. What is
missing is only steps 1–5, and those are pure NumPy — **no VTK, no new
dependency, no viewer coupling.**

### 2.4 Landmark auto-detection — why manual picking must stay

Recent DL nipple segmentation reports a mean error of **~7.4 mm** against a
radiologist reference (1,080 images). **Nipple error propagates ~1:1 into the
predicted locus.** A 7.4 mm nipple error would, on its own, exceed the entire
median AE of the GM (3.03 mm) and swamp the SS/AB difference we are trying to
exploit.

**Conclusion: the guided manual nipple pick is not a stopgap — it is a
correctness requirement.** Do not replace it with auto-detection. Auto-detection
belongs only as a *pre-seed* (a draggable suggested marker) and as a fallback.

### 2.5 The learned approach, and why it is not our next step

**CL-Net — "Check and Link", MICCAI 2022, arXiv:2209.05809** (note: an earlier
internal note cited arXiv 1807.00637 — that ID is wrong). CL-Net learns pairwise
lesion correspondence directly and is SOTA on DDSM. **TransReg**
(arXiv:2311.05192) uses a cross-transformer as an auto-registration module
between CC/MLO ROIs.

The blocker is stated plainly by CL-Net's own authors: **DDSM has no
correspondence labels; they had to add them by hand with a radiologist.** There
is no public CC/MLO correspondence-labelled dataset. Any learned approach here
requires us to build the labelled set first — which is exactly what Phase 0
below does. **This is why the DL route is Phase 5, not Phase 1.**

---

## 3. Current implementation — where the error actually comes from

Ranked by expected contribution to AE, from the code review:

| # | Defect | Location | Effect on accuracy |
|---|---|---|---|
| **D1** | **Chimera geometry** — AB locus drawn with SS radius | `correspondence_arc.py:145` | Neither method's assumption holds. Systematically undersized arc (dl ≤ dr always). |
| **D2** | **Left-breast arc mirror** — `center_angle = chest_wall_angle − θ_pec` applied to both sides; for L this points the arc **inferiorly** instead of superiorly | `correspondence_arc.py:286` | **Left-breast projections biased into the wrong quadrant.** Contradicts the file's own comment and `geometry._depth_normal_unit_vector` (which correctly uses `π+θ` for L). |
| **D3** | **Over-confident uncertainty band** — ±10 % of radius (≈ ±5 mm at r=50 mm) | `visualization.py:341` | Literature says an arc needs **±39 mm** for 100 % sensitivity and misses by >10 mm in 27 % of cases. We draw a tight, confident band around the least reliable method. **This is the clinical-safety item.** |
| **D4** | **Anisotropic spacing collapsed** — `radius_px = mm / ((sx+sy)/2)` | `correspondence_arc.py:149` | Distorts the locus whenever row/col spacing differ. |
| **D5** | Fallback pectoral angle conflict — 45° (`validation.py:30`) vs 50° (`correspondence_arc.py:281`) | two files | Only affects the no-line-drawn path, but it is an unforced inconsistency. |
| **D6** | `angle_margin_deg` is a **dead parameter**; the angular span is hard-coded **±70°** | `correspondence_arc.py:289,345` | The search span is not tunable and is not derived from data. |
| **D7** | Heatmap **actor leak** — `draw_arc_probability_heatmap` never clears prior actors | `visualization.py:458` | Stability, not accuracy. Accumulates across re-runs within a series. |
| **D8** | Probability heatmap (6 features) is **unvalidated** — no literature support, never measured | `arc_probability.py` | Unknown. Could be helping or hurting. We cannot currently tell. |

**Dead code that matters:** `correlator_v2.py` (true NOD radius + Hungarian
optimal matching + quadrant-consistency penalty, clipped by the real pectoral
line) is fully written, unit-tested, and **wired to nothing.** Note carefully:
wiring it would fix D1 by making us a *correct AB* — which the evidence says is
still the **worst** tier (5.78 mm). It is not the answer on its own.

---

## 4. The plan

Five phases. **Phase 0 is non-negotiable and comes first** — without it, every
subsequent change is an opinion.

### Phase 0 — Ground truth + the AE harness *(the enabler; do this first)*

Nothing below can be justified, tuned, or defended without a number.

**0a. Collect correspondence ground truth from our own PACS — using the tool
itself.**

Add a **"Confirm correspondence"** mode to the existing 3D Cursor UI: after the
radiologist picks the landmarks, they click the *same* lesion in both CC and
MLO; the pair is written to a labels store
(`user_data/mg_correspondence/<study_uid>.json`) with both boxes, both
lateralities, the nipple picks, the pectoral line, and pixel spacing.

This is the highest-leverage item in the whole plan:

- It solves the exact blocker CL-Net's authors hit (no public labels).
- It reuses the guided picker we already built — small UI delta.
- It builds, as a by-product of normal clinical use, the dataset needed for
  Phase 4 validation **and** any future Phase 5 learning.
- Target: **≥ 100 lesion pairs** for a credible median + IQR (BMC used 711; 100
  is enough to rank methods, not enough to publish).

**0b. Implement the AE metric offline.**

New pure module `cursor_3d/accuracy_eval.py` (stdlib + NumPy only, no Qt/VTK, so
it runs in the sandbox verify lane):

```
absolute_error_mm(predicted_locus_points_px, true_center_px, pixel_spacing)
    = min over locus points of euclidean_mm(point, true_center)
```

This is *exactly* the BMC/Zheng metric, so our numbers become directly
comparable to the published ones. Report **median AE, IQR, max, % > 10 mm** —
the same four figures as the table in §2.2.

**0c. Baseline our current arc.** Run the harness against today's
`arc.arc_points_px`.

> **Acceptance gate:** our current chimera should score ≈ AB (median ~5.8 mm).
> **If it scores materially worse, D2 (the left-breast mirror) is confirmed
> live** — check the L-side cases separately. This is the cheapest possible
> confirmation of the most serious geometric bug.

---

### Phase 1 — Correctness fixes (no method change)

Small, safe, independently testable. These make the *current* method behave as
its own documentation says.

- **D2 — left-breast mirror.** Change to
  `center_angle = chest_wall_angle − side_sign · θ_pec`, matching
  `geometry._depth_normal_unit_vector`. Flag `AIPACS_CURSOR3D_ARC_LR_FIX`
  (default ON after harness confirms).
  *Guard test:* an L-breast lesion's arc centre must lie superior to the nipple,
  mirroring the R case. Assert R/L symmetry directly.
- **D4 — anisotropic spacing.** Sample the locus in **mm** and convert each
  point with its own axis spacing, instead of scalarising the radius.
- **D5 — one pectoral default.** Single constant, one source of truth. Keep the
  15°–60° clinical clamp.
- **D7 — heatmap actor leak.** Call `_clear_projected_actors` on the heatmap
  path, as the arc path already does.
- **D6 — retire or wire `angle_margin_deg`.** Do not leave a dead knob that
  looks live.

**Expected AE gain:** modest overall, but potentially large on left breasts.
**Risk:** low. **Everything here is flag-gated with the legacy branch intact.**

---

### Phase 2 — Fix the chimera: make the Straight Strip the primary locus

This is the **best effort-to-accuracy ratio in the entire plan.**

Two independent cohorts (n=200, n=711), two decades apart, agree: **SS beats
AB** on median error, on required search width (28 mm vs 68 mm), and on CAD
false-positive reduction (25.0 % vs 11.9 %). And the axial distance correlates
better across views (0.923 vs 0.917) than the radial one.

**We already compute the SS quantity.** The change is to the *locus*, not the
math:

1. Add `geometry.compute_lesion_radial_distance_mm()` = √(dx²+dy²) — the true
   `dr`, so that a *correct* AB becomes available for comparison (and because
   `correlator_v2` and the docstring both assume it exists).
2. In `correspondence_arc.py`, introduce a **locus abstraction**:
   `LocusStrip` (the SS line perpendicular to the centreline at distance `dl`,
   with a band) alongside the existing `CorrespondenceArc`. Both expose
   `points_px` so the AE harness, the validation clamp, and the renderer treat
   them identically.
3. Make **SS the default rendered locus**; keep AB selectable
   (`AIPACS_CURSOR3D_LOCUS = ss | ab | both`, default `ss` after validation).
4. **Keep the AB arc available as a secondary overlay.** Rationale: radiologists
   are trained on Kopans/NOD and will expect it, and showing both makes the
   overlap region visible. But — per Zheng's explicit finding, the *mixed* area
   is **not** better than SS alone — so the arc must be **display-only, never
   the predictor.** Do not let the UI imply the intersection is more accurate
   than the strip; the data does not support that.

**Expected:** median AE ~5.8 mm → ~4.6 mm, >10 mm failures 27.4 % → 15.5 %.
**Risk:** medium (changes what the radiologist sees). Gate it, validate it
against Phase 0's harness, then flip.

---

### Phase 3 — An honest uncertainty band

**This is the clinical-safety fix, and it is independent of which locus we
choose.**

Today: a ±10 % band. At a 50 mm radius that is ±5 mm — but the published data
says the *typical* method misses by 4.6–5.8 mm at the **median**, and needs
±28–39 mm to be certain. **We are drawing a confident band around a prediction
that is frequently outside it.** A radiologist trusting that band will look in
the wrong place.

Replace the fixed percentage with a **data-derived, graded band**:

- **Inner (high-confidence) band:** ≈ the IQR of our own measured AE
  (literature SS: ~±8 mm).
- **Outer (search) band:** ≈ our measured 95th-percentile / max AE
  (literature SS: ~±32 mm; AB: ~±39 mm).
- Render the outer band faint, the inner band solid. Label them honestly.
- **The band widths must come from OUR Phase-0 measurements**, not from
  hard-coded literature values — the literature numbers are the sanity check,
  not the source.

Flag `AIPACS_CURSOR3D_EMPIRICAL_BAND`. This one is worth shipping even if every
other phase slips.

---

### Phase 4 — The Geometric Model (GM): the real accuracy win

Implement Duan/BMC's GM as a new pure module `cursor_3d/geometric_model.py`
(NumPy only — **no VTK, no viewer coupling**, so it is fully testable in the
sandbox verify lane and cannot destabilise the viewer).

Pipeline, reusing what we already have:

1. **Uncompressed 3D breast** from the CC + MLO breast contours — we already run
   `segment_breast_contour` on both views every session.
2. **Three feature points** for the ROI centre (this is what yields a curve
   rather than a point).
3. **Rotate** by the CC→MLO angle — we already collect this from the drawn
   pectoral line (30°–60°, exactly the paper's range).
4. **Re-compress** in the MLO direction.
5. **Project + quadratic interpolation** → the predicted curve, emitted as
   `points_px` into the same locus abstraction from Phase 2, so the renderer,
   the validation clamp, and the AE harness need no changes.

**Expected:** median AE → ~3.0 mm; >10 mm failures → ~7 %. Roughly **halves** the
error of today's arc and cuts catastrophic misses by ~4×.
**Risk:** medium — new math, but zero coupling to the viewer/VTK/download
domains. Fully unit-testable against synthetic geometry before it ever touches a
patient.
**Reference implementation detail:** Duan X, Qin G, Ling Q, et al., *IEEE Access*
2019;7:31586-97 — obtain this paper before starting; the BMC article deliberately
defers construction details to it.

> **Honest caveat:** GM is not uniformly better. In the BMC cohort, AB beat GM in
> 209/711 cases and SS beat GM in 285/711. GM wins on the *distribution*
> (median, IQR, tail), not on every case. Keep the locus selectable; do not
> delete SS/AB.

---

### Phase 5 — Image evidence & learning *(only after 0–4)*

- **Validate the existing probability heatmap (D8).** It is our own invention
  with no literature support. With the Phase-0 harness we can finally ask the
  only question that matters: **does the heatmap's peak have a lower AE than the
  locus's geometric nominal point?** If yes, promote it. If no, demote it to a
  visual aid or remove it. Right now we simply do not know — and shipping an
  unvalidated confidence signal into a cancer-detection workflow is the wrong
  default.
  There is a legitimate precedent for image-based refinement along the locus
  (`refine_arc_with_density_correlation` already exists in our tree, dead, and
  NCC-based refinement is standard) — so this is worth measuring, not assuming.
- **Then, and only then, consider the learned route** (CL-Net-style pairwise
  correspondence, or TransReg-style cross-attention over the AI's existing
  CC/MLO ROI candidates). Phase 0's label store is the prerequisite. Note that a
  learned model can be *combined* with the geometric locus rather than replacing
  it — the locus is a strong prior that constrains the search.

---

## 5. What NOT to do

- **Do not wire `correlator_v2` as the fix for D1.** It gives a *correct AB* —
  still the worst published tier. It is useful for its Hungarian matching and
  quadrant-consistency cost (both genuinely better than the current greedy
  nearest-depth pairing) — harvest those, but not its arc-as-predictor.
- **Do not replace manual nipple picking with auto-detection.** ~7.4 mm DL error
  propagates 1:1 and would exceed the entire GM median error (§2.4).
- **Do not present the AB∩SS intersection as more accurate than SS.** Zheng
  measured the mixed area explicitly; it did not beat SS.
- **Do not read the MLO angle from DICOM in preference to the drawn pectoral
  line.** The drawn line is the better source; metadata is the fallback.
- **Do not touch the viewer/VTK/download domains.** Every module in this plan is
  pure NumPy behind the existing `ViewData` boundary. This work must not violate
  the Fast/Advanced/VTK separation rule.

---

## 6. Flags, tests, and acceptance criteria

| Phase | Flag | Guard test | Acceptance |
|---|---|---|---|
| 0 | `AIPACS_CURSOR3D_LABEL_MODE` | `test_correspondence_labels.py` | ≥100 pairs collected; harness reproduces AB ≈ 5.8 mm on literature-like data |
| 1 | `AIPACS_CURSOR3D_ARC_LR_FIX` | `test_arc_lr_symmetry.py` | L and R arcs mirror-symmetric; L-side AE ≈ R-side AE |
| 2 | `AIPACS_CURSOR3D_LOCUS` | `test_locus_strip.py` | Median AE improves vs Phase-0 baseline, P < 0.05 |
| 3 | `AIPACS_CURSOR3D_EMPIRICAL_BAND` | `test_empirical_band.py` | Band contains the true lesion in ≥95 % of labelled pairs |
| 4 | `AIPACS_CURSOR3D_GM` | `test_geometric_model.py` | Median AE ≤ 3.5 mm; >10 mm failures ≤ 10 %; CC→MLO ≈ MLO→CC (reversibility, as BMC did) |
| 5 | `AIPACS_CURSOR3D_HEATMAP_PEAK` | `test_heatmap_peak_ae.py` | Heatmap peak AE < geometric nominal AE, else demote |

All default-OFF on landing. All legacy paths preserved as kill switches. All new
modules pure (stdlib + NumPy) so they run in the offscreen sandbox verify lane;
only the rendering deltas need the Windows clinical lane.

**Primary KPI:** median absolute error (mm) on our own labelled set.
**Guardrail KPI:** % of cases with AE > 10 mm (the clinically dangerous tail).
**Secondary:** radiologist reading time and Dice — the BMC reader study showed GM
assistance improved both, most for junior readers and low-conspicuity lesions.

---

## 7. Recommended order of execution

1. **Phase 0** (harness + label mode) — nothing is defensible without it.
2. **Phase 1 D2** (left-breast mirror) — likely the single largest correctness
   bug currently shipping.
3. **Phase 3** (honest band) — the clinical-safety item; ship even if the rest
   slips.
4. **Phase 2** (SS locus) — best effort-to-accuracy ratio.
5. **Phase 4** (GM) — the real ceiling.
6. **Phase 5** — measure the heatmap; only then consider learning.

---

## 8. Open questions for the clinical owner

- Do we have (or can we cheaply produce) **≥100 CC/MLO pairs with the same
  lesion confirmed in both views**? This gates everything. Our own PACS + the
  proposed label mode is the intended route.
- Should the AB arc remain visible by default (radiologist familiarity with
  Kopans/NOD), or should SS replace it outright?
- Is per-case reading time something we want to measure, as the BMC reader study
  did? It is the metric most likely to justify the feature clinically.

---

## 9. References (verified 2026-07-14)

1. Wang S, Xu Z, Zheng B, et al. **Improvement in matching lesions in dual-view
   mammograms using a geometric model.** *BMC Med Imaging* 2025;25:322.
   doi:10.1186/s12880-025-01862-3 — the AB/SS/GM comparison, n=711.
2. Zheng B, Tan J, Ganott MA, Chough DM, Gur D. **Matching breast masses depicted
   on different views: a comparison of three methods.** *Acad Radiol*
   2009;16(11):1338-47. PMID 19632867; PMC2763994 — origin of AB/SS/mixed; SS
   wins.
3. Duan X, Qin G, Ling Q, et al. **Matching corresponding regions of interest on
   Cranio-Caudal and Medio-Lateral oblique view mammograms.** *IEEE Access*
   2019;7:31586-97 — **the GM construction; obtain before Phase 4.**
4. Kita Y, Highnam R, Brady M. **Correspondence between different view breast
   X-rays using curved epipolar lines.** *Comput Vis Image Underst*
   2001;83(1):38-56 — deformation model; MLO angle known 4.1 mm vs unknown
   6.8 mm.
5. Liu Y, et al. **Check and Link: pairwise lesion correspondence guides
   mammogram mass detection.** MICCAI 2022. arXiv:2209.05809 — learned
   correspondence; documents the absent-labels blocker.
6. **TransReg: cross-transformer as auto-registration module for multi-view
   mammogram mass detection.** arXiv:2311.05192.
