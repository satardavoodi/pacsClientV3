# Romexis-inspired CBCT Dental Workstation — Web Evaluation & Fit Assessment

**Date:** 2026-06-23 · **Type:** research + feasibility (no code yet)
**Companion docs:** `docs/pipelines/dental-curve-mpr.md`,
`docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`

---

## 0. Bottom line

- The feature set you specced is **exactly Romexis's "3D imaging" (diagnostic)
  module** — panoramic + cross-sections from the CBCT volume, nerve-canal
  tracing, measurement/annotation, optional 3D render. Your "do not implement"
  list correctly carves off the **3D Implantology**, **CMF Surgery**, and **AI
  segmentation** modules, which Romexis sells/licenses *separately* on top of the
  3D module. So your scope is coherent and matches how Planmeca itself splits the
  product.
- **You are not starting from zero.** Your existing **Dental Curve MPR** already
  does arch-curve → panoramic (OPG) → perpendicular cross-sections from a VTK
  volume. Milestones 2–3 are ~60% built; the work is *hardening + re-homing*, not
  green-field.
- **The single biggest risk is geometry accuracy, and you already documented it.**
  The current Dental Curve engine reslices from raw `GetSpacing/GetOrigin`,
  ignores `slice_height`, forces isotropic spacing, and biases the arch normal to
  the axial plane — your own `UNIFIED_MPR_3D_PIPELINE_DIRECTION` doc flags this as
  causing L/R mirror / oblique mis-orientation. **Millimetre measurements built on
  that engine would be wrong.** Milestone 1 must therefore be "re-home onto the
  standard-MPR geometry contract," not "new viewports."

---

## 1. What Romexis is (and which slice is "yours")

Planmeca Romexis is a modular dental imaging platform. Relevant modules:

| Romexis module | What it does | Relevant to you? |
|---|---|---|
| **3D imaging** | CBCT viewing + **auto panoramic & cross-sectional slices**, measuring/annotation incl. **nerve-canal tracing**, 3D rendering | ✅ **This is your target** |
| 3D Implantology | Implant planning, **implant library (130+ makers)**, surgical-guide design | ❌ you excluded |
| CMF Surgery | Orthognathic planning, splints | ❌ excluded |
| AI tools | Auto-segmentation of teeth/nerves/jaws/airways/sinuses, tooth-number nav | ❌ excluded for v1 (Romexis does it; you defer) |
| 2D/3D Ceph, Ortho Sim, Smile Design, CAD/CAM, Dental PACS | Out of scope | ❌ |

Key confirmations from Planmeca's own 3D-module page:

- The 3D module converts volumes "**automatically into panoramic images and
  cross-sectional slices**," with "measuring and annotation tools – such as
  **nerve canal tracing**." That is your Milestones 2–5, almost verbatim.
- Implant planning + surgical guides are explicitly described as the module
  "**expanded**" into the separate Implantology workflow — i.e. a different
  license tier. Your exclusion list lines up with that boundary exactly.

**Romexis nerve tracing is semi-automated:** the operator places control points
along the canal on cross-sectional slices; the software interpolates a smooth
path and inflates it to a fixed-diameter tube (commonly **1.5 mm or 3.0 mm**).
Your "manual point tracing first, auto later" plan is precisely the manual half of
this — a sound, clinically-recognised approach.

**Positioning note:** Planmeca also ships a **free Romexis Viewer**. Your value-add
isn't to clone Romexis wholesale — it's to put a focused, accurate
**diagnosis-and-measurement** dental view *inside your own PACS*, so the dental
arch / nerve-distance read happens where your studies already live.

---

## 2. Spec ↔ Romexis ↔ your codebase (feature map)

| Your spec | Romexis equivalent | In AI-PACS today | Gap |
|---|---|---|---|
| Axial + arch-curve editing | 3D module arch tool | **Dental Curve MPR** point-pick on `ImageViewer2D` | curve edit/handles, persistence |
| Panoramic from curve | Auto panoramic | `CurvedMPRGenerator.generate_panoramic_view` (Slicer 2-step) | spacing/thickness controls, accuracy |
| Perpendicular cross-sections | Auto cross-sections | `generate_curved_mpr` (N× `vtkImageReslice`) | adjustable spacing/thickness/#, **`slice_height` currently ignored** |
| 4-view synchronized cursor | Linked views | Standard **Zeta MPR** has the synced 3-plane foundation | wire dental views into the same cursor bus |
| Optional 3D VRT | 3D render | `vtkGPUVolumeRayCastMapper` in MPR/3D stack | lower priority, reuse |
| mm ruler, 2 endpoints | Measure tool | **none in Dental Curve MPR** (stub only) | net-new, must use world coords |
| Buccal-lingual / vertical bone, crest→canal, apex→canal | Measure presets | none | net-new |
| Manual nerve polyline overlay | Nerve tracing | none | net-new |
| Scale rulers, R/L A/P Buccal/Lingual labels | Orientation overlays | standard MPR has orientation logic | port to dental views |
| Same geometry pipeline, single source of truth, IOP/IPP/spacing, no hardcoded axes | (Romexis internal) | **Your `UNIFIED_MPR_3D_PIPELINE_DIRECTION`** mandates exactly this | the re-home work itself |

**Reuse verdict:** Milestones 1–3 are mostly *integration + hardening* of
Dental Curve MPR + Standard MPR. Milestones 4–5 (measurement, nerve tracing) are
genuinely new but small and self-contained.

---

## 3. The accuracy problem you must solve first (most important section)

Your spec's accuracy clauses — *"measurement using real voxel spacing," "cross-
section perpendicularity test," "panoramic/cross-section coordinate consistency,"
"no hardcoded axial/coronal/sagittal," "single source of truth for volume
coordinate system / curve / planes / measurement world coords"* — are **the same
requirements your own unified-MPR directive already imposes**, and the current
Dental Curve engine **violates several of them** (documented in
`dental-curve-mpr.md` §7 as open risks):

1. `slice_height` is ignored → cross-section slices are square, so a "vertical
   bone height" read on a cross-section is geometrically suspect.
2. Output spacing is forced isotropic on the curved stack → mm calibration drift.
3. The arch normal is **biased to the axial plane** (`_initial_normal`) → wrong on
   tilted volumes; contributes to the L/R-mirror / oblique issue your unified doc
   calls out.
4. It reslices from raw `GetSpacing/GetOrigin`, **bypassing the LPS/IPP/IOP
   geometry contract** that Standard (Zeta) MPR uses.

**Consequence:** if you build the ruler on top of today's engine, you'll measure
on a subtly distorted reconstruction. For crest→canal / apex→canal distances that
inform whether a drill is safe near the inferior alveolar nerve, that is exactly
the wrong place to be approximate.

**Therefore Milestone 1 should be reframed:** not just "load + 4 views + synced
cursor," but "**dental views derive from the Standard-MPR volume + geometry
contract** (`PyDicomLazyVolume.vtk_image_data`, LPS triad, IPP slice-sign), so all
four viewports and every later measurement share one patient-space coordinate
system." This is also the **A0 → B3 first target already named in your unified
directive**, so this work is on your roadmap regardless — the dental module is the
forcing function to finish it.

---

## 4. Feasibility & risk per milestone

| MS | Scope | Feasibility | Main risk |
|---|---|---|---|
| 1 | CBCT load + 4-view + synced cursor **on the unified geometry contract** | Medium | re-homing dental views onto Standard-MPR volume; FAST-mode VTK rule (see §5) |
| 2 | Editable arch curve → panoramic | **High (reuse)** | curve edit UX + regenerate; keep panoramic spacing correct |
| 3 | Perpendicular cross-sections, adjustable spacing/thickness/# | **High (reuse)** | fix `slice_height`/anisotropic spacing so thickness is real mm |
| 4 | mm ruler + annotation mgmt, z-order, undo/select/edit | Medium | world-coordinate math; overlay z-order above image layer; "invalidate on geometry change" |
| 5 | Manual nerve polyline + crest/apex→canal distance | Medium | 3-D polyline shared across all views; distance from point to polyline in patient space |

Cross-cutting risks:

- **FAST-mode VTK rule.** Your project rule says FAST viewer must never
  instantiate VTK render windows, yet explicit MPR/dental reconstruction *is* the
  sanctioned VTK path. `CurvedMPRPanoramicView` already instantiates render
  windows; the unified directive resolves this by treating explicit MPR as the
  allowed VTK path (the QPainter idea was withdrawn). Decide this **before**
  Milestone 1 so the 4-view layout sits on the sanctioned path.
- **Destructive layout teardown.** Dental Curve MPR currently calls
  `cleanup_all_viewers()` and collapses to a 1×1 cell. A 4-view workstation needs
  a **scoped, restorable** layout — do not inherit the global wipe.
- **Synchronous heavy compute on the GUI thread** (panoramic can be hundreds of
  reslices). For an interactive workstation this must move off-thread / chunk with
  progress, or arch edits will freeze the UI.
- **Clinical/regulatory.** A measurement that guides proximity to the IAN is
  clinically load-bearing. Your validation-test list is the right instinct; add a
  **physical phantom / known-spacing dataset** check before anyone reads real mm
  off it, and keep a visible "reconstruction — verify against source slices"
  caveat.

---

## 5. Recommended approach

1. **Adopt your own unified MPR foundation as the substrate** (don't fork a second
   geometry system — your directive forbids it, and the spec's "single source of
   truth" clause demands it). The dental module = Standard-MPR foundation + a
   dental tool layer on top.
2. **Re-home Dental Curve MPR first** (geometry contract + scoped layout + off-
   thread generation), gated behind a flag with the legacy path as kill-switch —
   matching how every other change in this repo ships.
3. **Then layer dental features** in your milestone order, each with the guard
   tests you listed (voxel-spacing accuracy, perpendicularity, coordinate
   consistency, ruler z-order, synced cursor).
4. **Keep it diagnostic.** Resist scope-creep toward implant/guide/AI — that's the
   line where Romexis itself switches modules, and it's where regulatory burden
   jumps.

Suggested first deliverable: a **Milestone-1 implementation plan** (which
Standard-MPR classes to reuse, the 4-view layout widget, the shared cursor/world-
coordinate bus, and the flag/guard-test list) — I can produce that next.

---

## 6. Open questions to settle before building

1. **Coordinate authority:** confirm dental views must bind to
   `PyDicomLazyVolume.vtk_image_data` + the LPS/IPP/IOP contract (not the current
   raw-spacing reslice). (Strongly recommended — required for accurate mm.)
2. **FAST vs VTK:** ratify explicit-MPR-as-sanctioned-VTK-path for the dental
   workstation so the 4-view layout is allowed to render.
3. **Nerve tube diameter / output:** match Romexis (1.5 mm or 3.0 mm) or make it
   configurable?
4. **Where it lives:** new Patient-Tab workspace/tab vs. an expansion of the
   existing Dental Curve MPR panel?
5. **Validation dataset:** is there a known-spacing CBCT / phantom available to
   certify measurement accuracy?

---

## Sources

- [Planmeca Romexis — 3D imaging software](https://www.planmeca.com/dental-software/planmeca-romexis/3d-imaging-software/)
- [Planmeca Romexis — 3D implantology software](https://www.planmeca.com/software/software-modules/planmeca-romexis-3d-implantology/)
- [Planmeca Romexis — software modules](https://www.planmeca.com/dental-software/planmeca-romexis/modules/)
- [Planmeca Romexis — free Viewer](https://www.planmeca.com/dental-software/romexis-viewer/)
- [Visibility of the mandibular canal on CBCT cross-sectional images (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4234336/)
- [Semi-/fully-automated mandibular canal segmentation — systematic review (context for Romexis control-point tracing)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12099203/)
- Internal: `docs/pipelines/dental-curve-mpr.md`, `docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`
