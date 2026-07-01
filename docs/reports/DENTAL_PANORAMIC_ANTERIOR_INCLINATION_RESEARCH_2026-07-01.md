# Improving Dental Arch (Panoramic Curve) Reconstruction for Inclined Anterior Teeth — Research & Feasibility

**Date:** 2026-07-01
**Scope:** How commercial CBCT software and the peer-reviewed literature handle the loss of crown/apex on forward-inclined anterior teeth in panoramic (curved planar reformation) reconstruction, and which techniques are implementable in the AI-PACS `curved_mpr` engine.
**Method:** Deep-research fan-out (5 search angles), then adversarial verification of the two load-bearing claims against primary sources (PubMed abstract + manufacturer brochure + VTK/3D-Slicer source).

---

## Implementation status (2026-07-01)

**UPDATE — now shipped in BOTH dental surfaces and DEFAULT ON (user-validated).** After the
simple Dental Curve MPR dual-arch was confirmed live ("it's great"), it was (a) added to the
**professional Dental Imaging module** (Advanced Analysis pop-up) and (b) flipped ON by default:
- Professional module engine `modules/dental_imaging/core/curved_reconstruction.py`: flag
  `AIPACS_DENTAL_DUAL_ARCH` **default 1**; `_generate_panoramic_uncropped` tilts each column via the
  shared `compute_oblique_slice_axes`, `_apical_origins_for` aligns the apical arch, and
  `build_panoramic_image` / `build_curved_reconstruction` accept `apical_world_points`. (Reuses the
  zeta engine classes via the sanctioned adapter; the two-level split — no viewer/display import —
  is intact.)
- Professional workspace `modules/dental_imaging/workspace.py`: an **"Apical Arch"** toggle in the
  Tools cell (beside Pick Arch / Undo / Clear / Rebuild Panoramic), a second `_apical_arch_points`
  set with crown/apical routing, the apical arch drawn on the axial in magenta, and the apical arch
  threaded into the panoramic build + recon cache key.
- Simple Dental Curve MPR flag `AIPACS_CURVED_MPR_DUAL_ARCH` flipped **0 → 1** (default ON).
- Tests: `tests/code/viewer/test_curved_mpr_dual_arch.py` (+ professional source-pins) and the full
  `tests/code/dental_imaging` suite — 76 green; all four edited files compile on `.venv`.
- Kill switches kept: `AIPACS_DENTAL_DUAL_ARCH=0` / `AIPACS_CURVED_MPR_DUAL_ARCH=0` restore
  single-arch. Single-arch output is byte-identical. **Still needs a live source-build eyeball** of
  the professional module's oblique panoramic on a proclined-incisor CBCT.

---

**Phase 2 ENGINE CORE — LANDED & offline-verified (originally default OFF; now default ON).**
`modules/mpr/zeta_mpr/curved_mpr.py` now contains the oblique/dual-arch reconstruction:
- `compute_oblique_slice_axes(tangent, normal, binormal, tilt_vec)` — tilts the per-column
  vertical (Binormal) sampling axis to follow the crown→apex vector, keeping the basis
  orthonormal + right-handed and the arch tangent (hence along-arch geometry/measurements)
  unchanged. Degenerate/along-arch tilt = no change.
- `resample_polyline_arclength(points, n)` — aligns a second arch to the crown frames.
- `generate_panoramic_image_slicer_method(..., apical_origins=None)` — per-column oblique
  sampling when the flag is on AND an aligned apical curve is supplied; else byte-identical.
- `CurvedMPRGenerator.set_apical_centerline(points)` + `generate_panoramic_view` thread the
  apical arch through (samples it with the same framer → column correspondence).
- Flag `AIPACS_CURVED_MPR_DUAL_ARCH` (default OFF); `AIPACS_CURVED_MPR_DUAL_ARCH_MIN_TILT`
  (mm, default 0.5). Guard: `tests/code/viewer/test_curved_mpr_dual_arch.py` (13 green incl.
  the existing quality suite; pure tilt math + wiring source-pins). Compiles clean on `.venv`.

**Phase 1 PICK UI — LANDED in the simple Dental Curve MPR panel (flag-gated, default OFF; NEEDS
LIVE GUI VERIFY).** `PacsClient/.../patient_toolbar/toolbar_manager.py`: when
`AIPACS_CURVED_MPR_DUAL_ARCH=1`, the Dental Curve MPR panel shows a **Crown (occlusal) / Apical
(root)** arch toggle. The panel orchestrates two point sets over the single `DentalCurvePicker`
(`_set_curved_mpr_active_arch` stashes/restores each arch — no picker change), and
`_generate_curved_mpr` passes the apical arch to `generator.set_apical_centerline(...)` before
`generate_panoramic_view`. With the flag off the panel is byte-identical (no toggle, single
arch). Guard: the toolbar wiring is source-pinned in `test_curved_mpr_dual_arch.py` (14 green);
`toolbar_manager.py` compiles clean on `.venv`.

**To verify live (source build):** set `AIPACS_CURVED_MPR_DUAL_ARCH=1`, open Dental Curve MPR,
trace the crown arch (mid-crown axial slice), switch to **Apical**, scroll to the apex level and
trace the root apices, then Generate — the panoramic should keep inclined anterior crowns AND
apices sharp at a thin slab. Compare against the flag-off single-arch panoramic.

**Still open:** Phase 0 reorientation; Phase 3 (ray-sum + adaptive slab); optionally exposing
dual-arch in the professional Dental Imaging module (needs a panoramic path there first).

**Pre-existing unrelated test staleness (not from this work):** `test_curved_mpr_inplace_viewport.py`
(3) and `test_dental_curve_panel_polish.py::test_panoramic_thickness_control_wired_to_generation`
pin the pre-2026-06-23 constants (slab `10.0`, in-place flag default `"0"`); they fail on pristine
HEAD too (verified via `git stash`). Fixing them is a separate small cleanup.

---

## 1. Bottom line

The problem is real, well-documented, and has a clean published solution that maps almost directly onto our existing engine.

1. **The single-arch, straight-down "vertical curtain" reslice is the root cause.** A conventional panoramic samples a slab straight down the axial (Z) axis along one arch spline. A tooth that is *inclined* relative to that axis (proclined maxillary incisors, and to a lesser degree mandibular anteriors) has its crown and apex on *different* arch positions, so a single vertical slab cannot contain both — the facial/lingual crown or the root apex falls outside the focal trough and blurs or disappears. Thickening the slab pulls them back in but averages in off-target anatomy → blur. This is confirmed across the literature.

2. **The user's two hypotheses are correct and, in fact, converge into one technique.** "Two arches (crown arch + apical arch)" and "tilt the reconstruction plane to follow tooth inclination" are the *same* algorithm: the vector from the crown-arch point to the apical-arch point, per column, **is** the local oblique/long-axis sampling direction. Sweeping that tilted line along the arch produces a lofted, non-planar reconstruction surface. This is precisely the method validated in PLOS One 2016 (Luo et al.), which builds "the long axial curves of the upper and lower teeth ... to create a 3D panoramic curved surface" and reports it shows the **whole dentition at a thinner slice** than single-curve methods — i.e. it fixes the crown/apex loss *without* the thickness-blur penalty. According to PubMed ([DOI 10.1371/journal.pone.0156976](https://doi.org/10.1371/journal.pone.0156976)).

3. **Commercial precedent exists for multi-arch**, though narrower than the full method. Carestream CS 3D Imaging (v3.10.43, Jan 2024) traces **two arches simultaneously — a maxillary and a mandibular one** — plus a nerve "Canal Arch," verified from the manufacturer brochure. Volume **reorientation** before tracing (level the occlusal plane) is near-universal (Dolphin 3D, OnDemand3D, Anatomage Invivo, Planmeca Romexis, DTX Studio). What is *not* shipping in any manual we could open is a per-tooth **oblique/tilted panoramic surface** — that remains a research technique, which is our differentiation opportunity.

4. **Feasibility in AI-PACS: HIGH, and bounded.** Our `ResliceEngine.generate_panoramic_image_slicer_method` already builds the straightened volume by sampling, per arch position, along a **Binormal ("vertical, superior-inferior")** direction. Making the panoramic oblique is a localized change: replace that straight-up Binormal with a per-column tilt vector derived from a second (apical) arch. Everything downstream — the thickness slab, the `mean`/`max`/`weighted` projection, the sharpening — is untouched. Dual-arch, oblique surface, adaptive slab, and projection modes are all expressible in the current pipeline (or via `vtkImageReslice` slab modes).

5. **Clinical guardrail (important).** The literature is consistent that a reconstructed panoramic is a **survey image, not a metric one** for anterior teeth: even 3D-derived panoramics carry ≈4% length error and ≈3–4° (≈10%) angular error that head-standardization alone cannot remove. Any dual-arch/oblique feature should be presented as *improving visualization/completeness*, with cross-sectional/true-3D remaining the reference for diagnosis and measurement. This matches the existing AI-PACS rule that the panoramic reconstruction is display-only and measurements use world coordinates.

---

## 2. The problem, with evidence

A CBCT panoramic is a **curved planar reformation (CPR)**: fit a spline to the arch on an axial slice, resample it to uniform spacing, erect a local frame per point, sample a plane perpendicular to the curve, and collapse a slab of thickness *T* to one image (Kanitsar et al.'s canonical CPR taxonomy — projected / stretched / straightened). The reslicing surface, by default, is a **vertical ruled surface**: the 2D arch curve extruded straight down Z. It is therefore only correct for structures whose long axis is parallel to Z.

- **Focal-trough physics.** Structures inside the trough are sharp and geometrically accurate; anything outside blurs, and blur scales with distance from the trough. The trough is thinnest anteriorly, which is exactly where inclined incisors sit. ([Radiography, S1078817413001296](https://www.sciencedirect.com/science/article/abs/pii/S1078817413001296); [Decisions in Dentistry](https://decisionsindentistry.com/article/optimal-panorex-imaging/))
- **Proclined incisors are the classic failure.** Automatic-panoramic papers state a single fixed arch curve "often results in blurred or entirely invisible incisors," motivating per-tooth long-axis curves. ([PMC5594999](https://pmc.ncbi.nlm.nih.gov/articles/PMC5594999/); [MDPI Electronics 11/15/2404](https://www.mdpi.com/2079-9292/11/15/2404))
- **Thickness is a blur↔completeness trade.** Thin slabs show the dentition most clearly (least superimposition); thicker slabs recover apices and the canal but reintroduce blur and off-target anatomy. ([Comput Biol Med, S0169260719303384](https://www.sciencedirect.com/science/article/abs/pii/S0169260719303384))
- **Quantified fidelity limits (the caveat).** According to PubMed: CBCT-reconstructed panoramic underestimates tooth length by ≈4% (mean −1.6 mm, n=48) while conventional panoramic overestimates ≈29% ([DOI 10.1590/2176-9451.19.5.045-053.oar](https://doi.org/10.1590/2176-9451.19.5.045-053.oar)); panoramic molar-tilt error is 3.6°±5.7° (≈10% relative, n=160) even without magnification confounds ([DOI 10.1259/dmfr.20170467](https://doi.org/10.1259/dmfr.20170467)); mesiodistal root angulation differs clinically in 13/24 teeth, with ideal acquisition at Frankfort ≈3.3° nose-down ([PMID 28839482](https://pubmed.ncbi.nlm.nih.gov/28839482/)).

---

## 3. Technique catalog — the options, ranked

### A. Increase slab thickness (the status quo)
Widens the focal trough so inclined crowns/apices fall inside it. **Cheap, already implemented** (`slice_thickness_mm`), but averages in off-target anatomy → the blur the user wants to avoid. Keep as a fallback, not the answer.

### B. Global volume reorientation (level the occlusal plane, then trace)
Apply one rigid pitch rotation so the occlusal/Frankfort plane is horizontal, *then* run the normal vertical CPR. This is what most commercial products ship as "tilt correction" (Dolphin 3D, OnDemand3D, Anatomage Invivo, Romepsis head-orientation tool, DTX Studio). **Quick win, evidence-backed** (optimal ≈3.3° nose-down). **Limitation:** it only corrects *global head tilt*; a tooth inclined *relative to* the leveled occlusal plane is still lost. Necessary but not sufficient.

### C. Dual / multi-arch (separate curves)
Two independent arch curves. Two flavors:
- **Separate maxillary + mandibular arches at different heights** — this is what **Carestream CS 3D ships** ("two arches simultaneously traced: a maxillary and a mandibular one"; verified from the brochure). Solves the fact that upper and lower arches have different shapes/heights; does *not* by itself fix single-tooth inclination.
- **Crown arch + apical arch of the same jaw** — the user's idea. On its own (two separate flat panoramics) it is only a partial fix; its real power appears when the two curves are **combined** into an oblique surface (technique D).

### D. Oblique / lofted long-axis surface (the real fix — recommended)
Per arch position, define the vertical sampling direction not as world-up but as the **local tooth long axis**, tilted forward for anterior teeth. Practically, the long axis at column *i* is the line from the **crown-arch point** to the **apical-arch point** at that column — so **the dual crown/apical arch *defines* the obliquity**. Lofting those tilted lines across the arch yields a 3D "developed" surface that contains crown *and* apex of an inclined tooth at a **thin** slab.

This is exactly Luo et al. (PLOS One 2016): arch curve from MIP → per-position long-axial curves of upper and lower teeth → 3D panoramic curved surface → develop to 2D. According to PubMed, it "can clearly and completely show the whole dentition without the blur and superimposition" and "requires thinner panoramic radiographs than other existing methods" ([DOI 10.1371/journal.pone.0156976](https://doi.org/10.1371/journal.pone.0156976)). Related auto-arch fitting: [PMC4907432 companion / Bézier optimization PMC7438751](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7438751/). Patent precedent for a shaped "curved sub-volume" unfold: [US8849016B2](https://patents.google.com/patent/US8849016B2/en).

### E. Projection mode + adaptive slab (polish)
- **Projection.** Mean/ray-sum ("X-ray-like") is the diagnostic default and preserves roots, lamina dura, and soft tissue; MIP over-brightens enamel/cortex and drops low-density detail (use for arch *detection*, not the diagnostic pano); a Gaussian-**weighted** center projection keeps the arch plane sharp while spanning depth. Our engine **already has `mean`/`max`/`weighted`**; `vtkImageReslice` exposes `SetSlabModeTo{Mean,Sum,Max}` if we move to a VTK slab. ([vtkImageReslice](https://vtk.org/doc/nightly/html/classvtkImageReslice.html); [3D Slicer CurvedPlanarReformat uses mean projection](https://github.com/PerkLab/SlicerSandbox/blob/master/CurvedPlanarReformat/CurvedPlanarReformat.py))
- **Adaptive slab.** Make thickness vary along the arch (thinner anteriorly, where the trough is naturally thin), spline-driven. Complements — does not replace — obliquity.

---

## 4. Commercial landscape (what actually ships)

| Product | Editable arch | Slab thickness | Multi-arch | Oblique / reorient | Projection |
|---|---|---|---|---|---|
| **Carestream CS 3D** | Yes (AI + manual) | Yes (focal trough) | **Yes — maxillary + mandibular, verified** | Reorient unconfirmed | avg |
| **Planmeca Romexis** | Yes (Autofit) | Yes (Autofocus adaptive layer) | Unknown | **Reorient yes** (head-orientation tool) | avg (pseudo-pano) |
| **Dolphin 3D** | Yes | Yes ("refine width") | Unknown | **Reorient yes — verified** | orthogonal/perspective |
| **OnDemand3D** | Yes | **Yes — user-specified, verified** | Unknown | **Reorient yes — verified** | sharpen filter |
| **Anatomage Invivo** | Yes (Arch Spline) | Yes (#slices) | Unknown | **Reorient yes** | unknown |
| **Vatech Ez3D-i** | Yes (auto/manual) | Yes | Partial (up to 8 sectional curves) | Unknown | unknown |
| **J. Morita i-Dixel** | Yes | Yes | **Dual-MPR** (two curves; for cross-sections, not blended pano) + long-axis reslice | per-tooth long-axis | unknown |
| **DTX Studio Implant** | **Yes — user-editable, verified** | Yes | Unknown | Reorient (offset) | unknown |
| **Dentsply Sirona (Sidexis/Galileos)** | Yes | Yes (tangential/cross) | Unknown | Unknown | unknown |
| **i-CAT / Tx STUDIO** | Yes (TruPan auto) | likely | Unknown | Unknown | unknown |
| **NewTom NNT** | Yes | Yes (pan↔cross) | Unknown | Unknown | unknown |
| **Blue Sky Plan** | Yes | implied (1 mm cross) | Unknown | Unknown | unknown |
| **OsiriX / Horos (generic CPR)** | Yes (any ortho view) | Yes | No (single path; add a 2nd manually) | Reorient (generic MPR) | **ray-sum + MIP** |

**Reading of the table.** Every product does single editable arch + adjustable slab (the baseline). The genuinely-beyond-baseline, *verified* features are: **multi-arch** (Carestream maxilla+mandible; i-Dixel/Vatech multi-curve) and **volume reorientation** (Dolphin, OnDemand3D, Invivo, Romexis, DTX). A true **per-tooth oblique panoramic surface** and a **crown-arch + apical-arch blended into one oblique image** appear only in the **research literature**, not in shipping manuals — so implementing technique D would put AI-PACS ahead of the mainstream commercial baseline, not merely at parity.

---

## 5. Feasibility in AI-PACS — mapping to the existing engine

The current pipeline (`modules/mpr/zeta_mpr/curved_mpr.py`):

- **`Path3D`** — user control points → smooth interpolating spline.
- **`PlaneGenerator`** — parallel-transport frame (PTF): per arch position yields `(origin, tangent, normal, binormal)`.
- **`ResliceEngine.generate_panoramic_image_slicer_method(...)`** — for each frame, `_extract_orthogonal_slice_for_panoramic(origin, tangent, normal, binormal, thickness_pixels, height_pixels, spacing)` samples a 2D slice whose in-plane axes are **Normal (radial/thickness)** × **Binormal (vertical, superior-inferior)**; stacks into `(num_positions × height × thickness)`; then projects along the thickness axis with `mean` / `max` / `weighted`.

**The single hook point.** The `binormal` is the vertical/height sampling direction. Today it comes from the PTF of a planar axial curve, so it is ≈ world-up (Z) → the vertical curtain. **If, per column, we replace `binormal` with the local tooth long-axis vector, the reconstruction becomes oblique** and follows anterior inclination — with no change to thickness, projection, or geometry contract.

### Where each technique lands

| Technique | Change | Effort | Risk |
|---|---|---|---|
| **B. Reorientation** | Level occlusal plane before tracing (they already have volume orientation / DirectionMatrix). A pitch rotation of the sampling frame. | Low | Low — global rigid transform; measurements unaffected if done in world coords. |
| **C. Dual arch (separate)** | Second `Path3D`; run the sampler twice → two panoramics, or one merged. Mirrors Carestream. | Low–Med | Low — purely additive; single-arch path unchanged when no 2nd curve. |
| **D. Oblique/lofted (recommended)** | Add an apical `Path3D`; per column set `binormal = normalize(apical_pt − crown_pt)` and set `height` extent to span crown→apex; loft across columns. Degenerate case (no apical arch) = today's straight-up behavior byte-for-byte. | Med | Med — geometry-sensitive; must be flag-gated, default-off, guard-tested, and validated on a real inclined-incisor CBCT before default-on. |
| **E. Projection / adaptive slab** | `mean`/`max`/`weighted` already exist; add ray-sum (=sum) and per-column thickness. | Low | Low — display-only. |

### Implementation notes (VTK / numpy)
- The **grid-transform loft** used by 3D Slicer is the maintained reference for a curved/oblique surface (two lateral corners per curve sample via a parallel-transport frame, wrapped in an oriented grid transform). Prefer it over raw `vtkRuledSurfaceFilter`+`vtkProbeFilter`. ([SlicerSandbox CurvedPlanarReformat.py](https://github.com/PerkLab/SlicerSandbox/blob/master/CurvedPlanarReformat/CurvedPlanarReformat.py))
- If we keep the numpy sampler, obliquity is just per-column frame vectors — no new dependency.
- Interpolation should be **cubic** for quality (`SetInterpolationModeToCubic` in VTK, or cubic map-coordinates in numpy) — the engine's reslice is already cubic.

### Guardrails (non-negotiable, consistent with existing dental rules)
- **Flag-gated, default-off, legacy path preserved** as a kill switch (matches every prior dental change).
- **No change to the geometry contract, spacing, or world coordinates** → measurements remain valid; the oblique surface changes only *which* voxels are sampled for display.
- **Reuse the shared volume + DirectionMatrix** (single source of truth) — do not fork a second geometry pipeline (per the Unified MPR/3D directive).
- **Present as visualization, not measurement.** Label the oblique/dual-arch panoramic as a survey view; keep cross-sectional/3D as the diagnostic reference for anterior teeth (the ≈4% length / ≈3–4° angle caveat).
- **Guard test + live source-build verification** on a real proclined-incisor CBCT before default-on (I cannot see the screen).

---

## 6. Recommended path (phased)

1. **Phase 0 — reorientation quick win (technique B).** Let the user level the occlusal plane in sagittal/coronal before tracing the arch. Highest value-per-effort, matches commercial norm, low risk. Fixes the common "whole-head-tilt" case immediately.
2. **Phase 1 — second (apical) arch pick (technique C infra).** Add an "Apical arch" pick alongside the existing crown-arch picking in the Dental Imaging workspace (the arch-picking UI already exists). Ship it first as *two separate panoramics* (crown pano + apex pano) — useful on its own and de-risks the geometry.
3. **Phase 2 — oblique lofted reconstruction (technique D).** Per column, derive the tilt from crown→apex and loft into one oblique panoramic that preserves both at thin thickness. Flag-gated, default-off, guard-tested, validated live on inclined incisors. **This is the feature that closes the user's exact complaint.**
4. **Phase 3 — polish (technique E).** Add ray-sum projection option + per-column adaptive slab; expose a small "obliquity strength" / thickness control.

Each phase is independently shippable and independently revertible.

---

## 7. What we could NOT confirm (honest gaps)
- No **commercial product** documents a user-drawable **second apical arch blended into one oblique panoramic** — it's research-only (so this is novel territory, verify claims of "X already does it" skeptically).
- No study **A/B-tests dual vs single curve** on anterior completeness with reader scores, and none proves oblique reconstruction restores *measurement-grade* accuracy — it improves **visualization**, which is the honest framing.
- No canonical **numeric slab thickness (mm)** for capturing proclined incisor apices — it's patient/arch-adaptive.
- Some vendor manuals (Sirona, i-CAT, NNT) were not fully accessible; their multi-arch/oblique support is "unknown," not "absent."

---

## 8. Sources

**Peer-reviewed method & evidence (via PubMed — cite with DOIs):**
- Luo T. et al. *Automatic Synthesis of Panoramic Radiographs from Dental CBCT Data.* PLoS One 2016;11(6):e0156976. Upper+lower long-axial curves → 3D panoramic surface; whole dentition at thin slice. According to PubMed, [DOI 10.1371/journal.pone.0156976](https://doi.org/10.1371/journal.pone.0156976) ([PMC4907432](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4907432/)).
- Tooth-length accuracy, conventional vs CBCT panoramic. [DOI 10.1590/2176-9451.19.5.045-053.oar](https://doi.org/10.1590/2176-9451.19.5.045-053.oar) ([PMC4296663](https://pmc.ncbi.nlm.nih.gov/articles/PMC4296663/)).
- Geometric distortion of panoramic reconstruction in molar tilt (DMFR). [DOI 10.1259/dmfr.20170467](https://doi.org/10.1259/dmfr.20170467) ([PMC6196059](https://pmc.ncbi.nlm.nih.gov/articles/PMC6196059/)).
- Mesiodistal root angulation, standard vs CBCT panoramic; 3.3° nose-down optimal. [PMID 28839482](https://pubmed.ncbi.nlm.nih.gov/28839482/) ([PMC5543660](https://pmc.ncbi.nlm.nih.gov/articles/PMC5543660/)).
- Automatic panoramic reconstruction; incisor blur & long-axis curves. [PMC5594999](https://pmc.ncbi.nlm.nih.gov/articles/PMC5594999/).
- Fast automatic CBCT panoramic reconstruction. [MDPI Electronics 11/15/2404](https://www.mdpi.com/2079-9292/11/15/2404).
- Panoramic reconstruction via Bézier function optimization. [PMC7438751](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7438751/).
- High-contrast panoramic from CBCT; thin vs thick slab. [Comput Biol Med S0169260719303384](https://www.sciencedirect.com/science/article/abs/pii/S0169260719303384).
- Role of the focal trough / why structures blur. [Radiography S1078817413001296](https://www.sciencedirect.com/science/article/abs/pii/S1078817413001296).
- Custom focal trough in CBCT reformatted panoramic. [PMC7294321](https://pmc.ncbi.nlm.nih.gov/articles/PMC7294321/).
- Head orientation vs panoramic tooth angulation. [ScienceDirect S2212443814000198](https://www.sciencedirect.com/science/article/abs/pii/S2212443814000198).
- CBCT reconstructed panoramic accuracy, periodontal (incisors least accurate). [PLoS One pone.0329604](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0329604); [PMC11576516](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11576516/).
- Periapical/panoramic vs CBCT diagnostic accuracy. [PMC6776403](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6776403/).

**Algorithm / implementation:**
- Kanitsar et al. *CPR: Curved Planar Reformation* (taxonomy: projected/stretched/straightened). [VRVis PB-VRVis-2002-034](https://www.vrvis.at/publications/pdfs/PB-VRVis-2002-034.pdf).
- 3D Slicer *CurvedPlanarReformat* (parallel-transport frame, grid-transform loft, mean projection). [SlicerSandbox source](https://github.com/PerkLab/SlicerSandbox/blob/master/CurvedPlanarReformat/CurvedPlanarReformat.py).
- VTK `vtkImageReslice` (SlabMode Sum/Max/Mean, SlabNumberOfSlices, cubic). [class ref](https://vtk.org/doc/nightly/html/classvtkImageReslice.html); `vtkImageSlabReslice`, `vtkImageResliceMapper`, `vtkRuledSurfaceFilter`.
- Patent US8849016B2 — panoramic from CBCT via curved sub-volume unfold. [Google Patents](https://patents.google.com/patent/US8849016B2/en).

**Commercial (manufacturer docs):**
- Carestream CS 3D Imaging v3.10.43 — dual maxillary+mandibular arches (verified). [Brochure](https://pdf.medicalexpo.com/pdf/carestream-dental/cs-3d-imaging-version-31043/70654-278076.html); [User Guide ed.08](https://www.carestreamdental.com/globalassets/resource-library/software/imaging-software/cs-3d-imaging/english/sma22_cs-3d-imaging-ug_ed-08_english_en.pdf).
- Anatomage InVivoDental 4.1 (Arch Spline). [Manual](https://learn.osteoidinc.com/hubfs/Support%20Manuals/Invivo/Invivo%204.1/InVivoDental%204.1%20Manual%20ENG%20Rev%20C.pdf).
- OnDemand3D Dental (user-specified arch thickness, reslice reorient). [Manual](https://hdxwillna.com/wp-content/uploads/2022/04/OnDemand3DDental_1.0.10.7510_2018Jan-New.pdf).
- DTX Studio Implant — user-editable panoramic reslice curve. [Help](https://helpfiles.dtxstudio.com/Help/a3e9d4b2-5a72-47cb-8811-bb0ec8cbd270/3.5/EN/panoramic_reslice.htm).
- Dolphin 3D — focal-trough width + reorientation. [Ortho Practice US](https://orthopracticeus.com/archived-ce/using-3d-cbct-imaging-in-orthodontics/).
- Planmeca Romexis — Autofit/Autofocus, head-orientation. [Specifications](https://www.planmeca.com/dental-software/planmeca-romexis/specifications/).
- Vatech Ez3D — PANO curve auto/manual, sectional curves. [FAQ](https://vatechamerica.com/faq/ez3d-plus/how-do-i-create-a-pano-curve-on-ez3d-plus).
- J. Morita i-Dixel — MPR-curves, Dual-MPR, long-axis reslice. [Dental TI](https://www.dentalti.com/post/a-different-perspective-mpr-curves-in-i-dixel).
- Blue Sky Plan — panoramic curve. [User Manual](https://blueskybio.com/caffeine/uploads/files/documents/Blue%20Sky%20Bio%20Plan%20User%20Manual%20Rev%2010.pdf).
- Technical aspects of dental CBCT — state of the art (separate upper/lower curves; ray-sum & MIP). [PMC4277439](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277439/).

---

*Prepared for AI-PACS. The dual-arch/oblique reconstruction (technique D) is the recommended target: it is the peer-reviewed fix for the exact failure the user described, it converges the user's two ideas into one algorithm, it hooks into a single well-defined point in the existing `ResliceEngine` (the per-column Binormal), and it exceeds the current commercial baseline. Ship it flag-gated and default-off, and validate live on a proclined-incisor CBCT before enabling.*
