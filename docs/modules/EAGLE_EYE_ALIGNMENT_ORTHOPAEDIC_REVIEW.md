# Alignment: orthopaedic measurements and manual review architecture

Research and source review, 2026-09-14. This document distinguishes existing
capabilities from proposed work. It does not implement a surgical planner or a
Slicer round trip, and contains no patient data.

## Decision

Keep routine two-dimensional landmark correction inside Eagle Eye. Offer a
separate, optional **Advanced correction in Slicer** workflow for additional
axes, segment-based deformity analysis and later volumetric planning. Both
surfaces must use the same authoritative measurement engine and versioned
landmark data. Opening Slicer is not itself a completed correction workflow.

Current Alignment inference is an isolated PyTorch process, not headless Slicer.
The application also has separate Slicer analysis and viewer roles. Preserve
that separation; do not promote a running analysis job into an interactive
editor or replace a viewer scene containing another examination.

## Measurements worth adding

The [ESSKA formal consensus](https://doi.org/10.1002/ksa.12256) supports systematic
deformity analysis of weight-bearing axis, periarticular orientation and joint
lines before planning osteotomy. Correction level and joint-line consequences
matter; a single HKA value is insufficient. Clinical targets depend on the
indication, joint condition and soft-tissue contribution. No universal automatic
target or procedure recommendation is proposed here.

| Addition | Use | Required input and present status |
|---|---|---|
| WBL ratio / mechanical-axis crossing percentage | Quantify where the hip-to-ankle line crosses the tibial plateau | Verified medial/lateral plateau edges and hip/ankle centers. Not implemented. Do not assume SGR joint-line endpoints are the exact outer plateau edges. |
| Separate femoral/tibial knee centers | Explicit axis definitions when the joint is subluxed, severely deformed or operated | Additional reviewed landmarks. Current geometry uses one shared knee center; changing the convention requires a report version and comparison checks. |
| Femoral anatomical-mechanical angle (FVA), anatomical tibiofemoral angle | Relate shaft and mechanical axes | At least two reviewed shaft-axis points per relevant segment; not obtainable reliably from the current eight landmarks alone. Not implemented. |
| CORA, angulation and translation per deformity | Localize post-fracture malunion or multi-apical deformity | User-defined proximal/distal segment axes and, where needed, additional segments. Not implemented. Parallel/coincident axes require explicit handling. |
| Proximal femoral orientation / neck-shaft measures | Extend assessment to proximal femoral deformity | Additional trochanteric/neck/shaft landmarks and correct projections. Not implemented. |
| Verified LDTA and ankle-center construction | Improve ankle-level assessment | Review true plafond endpoints and the chosen ankle-center definition. AI points must not silently be treated as validated plafond landmarks. Current LDTA remains based on editable supplied endpoints. |
| Floor-referenced joint-line inclination | Describe the joint line relative to a verified horizontal reference | Explicit image/reference orientation. Keep distinct from arithmetic CPAK JLO already reported as MPTA + mLDFA. Not implemented. |
| CPAK phenotype | Descriptive native knee alignment category | aHKA/JLO exist; automatic classification does not. Native/operated status, applicability and boundary uncertainty need explicit treatment. It is not a surgical prescription. |
| Hinge-based correction simulation | Compare user-selected osteotomy scenarios | Hinge, osteotomy level, target WBL/HKA and calibration; output predicted projected angles, translation and gap. Not implemented; must remain separate from measured findings. |

[WBL ratio](https://pmc.ncbi.nlm.nih.gov/articles/PMC10510285/) uses medial plateau
edge = 0% and lateral edge = 100%. The intersection must use the plateau line,
not an arbitrary horizontal image row. Values outside 0-100% must be preserved,
not clamped. The ratio is dimensionless, but anatomical endpoints still require
review; millimeter MAD and wedge size require patient-plane calibration.

[Paley et al.](https://pubmed.ncbi.nlm.nih.gov/8028886/) define CORA through
intersecting segment axes. For fracture malunion, moving one joint point cannot
replace segment-level analysis. [Posttraumatic planning](https://pmc.ncbi.nlm.nih.gov/articles/PMC12742510/)
also illustrates why flexion/rotation and sagittal imaging matter. A single AP
image cannot establish torsion, posterior tibial slope or a complete 3D deformity.

[2025 alignment reporting terminology](https://pubmed.ncbi.nlm.nih.gov/40757805/)
reinforces explicit angle conventions. Report measured values and simulated
post-correction values in separate tables. In particular, arithmetic JLO around
180 degrees must not be compared with a floor-inclination threshold around a few
degrees; those are different quantities.

## Existing native correction

`eagle_eye_alignment/widget.py` already provides draggable landmark handles,
zoom/pan, explicit point placement, recalculation on release and invalidation of
the current PDF after an edit. `geometry.py` owns the numerical calculations;
`report.py` generates new versions from immutable image/point snapshots.
Original AI coordinates are retained separately from final coordinates.

This supports ordinary corrections even when AI localization fails. It does not
yet provide undo/redo, per-point restoration, a named correction workspace,
persistent resumable edit sessions, fragment axes or a surgical simulation.
Those should not be described as existing functionality. Clinical and source-live
acceptance remain distinct from synthetic code guards.

Recommended next native slice:

1. A clear **Manual correction** entry showing the full image and linked hip,
   knee and ankle close-ups, with selected point name and its definition.
2. Move, replace, lock, undo/redo and restore-original-AI-point actions.
3. Optional known-length marker calibration and separately named added landmarks.
4. Immediate numerical preview; explicit Apply/Recalculate commits an edit
   revision and invalidates prior PDF review. Regenerate a new report without
   rerunning AI. Preserve original input and earlier report revisions.

## Optional Slicer bridge

[Slicer Markups](https://slicer.readthedocs.io/en/latest/user_guide/modules/markups.html)
supports draggable control points, lines, angles, locking and saved markup data.
[Scripting support](https://slicer.readthedocs.io/en/latest/developer_guide/script_repository/markups.html)
can observe point changes. These are appropriate primitives for an advanced
editor, but their stock measurements should not become a second competing
definition of AI-PACS HKA/MAD/lengths.

Verified local integration constraints:

- `resident_service.py` starts analysis with `--no-main-window`; viewer is a
  separate owned role. The viewer can be shown on request.
- `AIPacsBackgroundRuntime.py` currently allows viewer status/show/hide/load_dicom.
  There is no Alignment landmark import, result revision or Apply-back command.
- Loading DICOM rejects an already occupied volume scene. Preserve that boundary;
  never clear an existing user's scene automatically for Alignment.

Proposed round-trip contract:

1. Start or obtain an explicitly owned Alignment editing session through the
   existing launcher architecture, keeping other viewer scenes intact.
2. Transfer only the exact selected image plus named points, calibration, source
   SHA-256, Study/Series/SOP identity and immutable result revision in a private
   local job folder. Do not use directory position or series number as identity.
3. Represent the radiograph as a single image plane. Define and verify the
   pixel-IJK-to-RAS mapping, pixel spacing, image flip and inverse mapping.
   Missing DICOM orientation must not be replaced with claimed patient 3D geometry.
   Constrain all 2D alignment handles to that plane.
4. A customized panel offers point selection, correction and extra segment axes.
   Change observers update a preview using the same geometry definitions.
5. **Apply and return to Eagle Eye** exports a new point revision atomically.
   Validate identity, image hash, revision, finite bounds, anatomical labels and
   plane membership. Reject stale edits if the study/image changed meanwhile.
6. Eagle Eye recalculates, displays the changed points/values and creates a new
   reviewed PDF when requested. Cancelling the editor leaves the prior accepted
   revision untouched. No retraining or AI inference is needed for an edit.

Required acceptance before advertising the bridge: exact numerical round-trip
under anisotropic spacing/flip; point edit visible in Eagle Eye and its PDF;
wrong-image and stale-revision rejection; cancel/close/reopen behavior; preservation
of another Slicer scene; fresh-source native UI pass. Volumetric osteotomy planning
would additionally require appropriate CT or other 3D acquisition and validation.

## Delivery order

First strengthen the native correction workspace and add reviewed WBL ratio.
Next add explicit segment axes/CORA and optional Slicer editing. Develop
surgeon-controlled planning simulations as a separate capability after the
measurement and coordinate-transfer contracts pass validation. All advanced
additions in this document remain proposals, not capabilities added by this review.

## External three-joint report comparison (2026-09-15)

Two user-supplied photographs show the same report template and its enlarged
angle list, with blank bilateral values. They support a terminology/capability
comparison, not numerical validation. No patient data or photographs are copied here.
Template points are A (head center), B (neck center), C (knee center), and D
(ankle center); T1 is the distal femoral tangent and T2 the tibial plateau tangent.

| Template angle | Current coverage | Definition and addition decision |
|---|---|---|
| Alpha 1, AB versus BC | Missing | Intended neck-shaft angle (NSA). Add reviewed neck and proximal shaft landmarks; a neck-center-to-knee line is not automatically a validated shaft axis. |
| Alpha 2, BC versus T1 | Missing | Intended anatomical distal femoral orientation. Add aLDFA from a reviewed distal shaft axis, with lateral angle convention explicitly shown. Do not simply rename mLDFA. |
| Alpha 3, AC versus T1 | Existing mLDFA, conditional on angle side | Same axis/line pair; the template does not specify medial versus lateral or supplementary-angle convention. Numerical equivalence requires that convention. |
| Alpha 4, BC versus CD | Missing anatomical tibiofemoral angle | Add aTFA from reviewed shaft axes. Keep distinct from arithmetic aHKA = MPTA - mLDFA. CD is a knee-to-ankle mechanical line and may not represent the shaft in tibial bowing or malunion. |
| Alpha 5, AC versus CD | Existing HKA axis pair | Current HKA is signed deviation from neutral zero; another report may use an included angle near 180 degrees. Do not directly compare numbers without the convention. |
| Alpha 6, AC versus T2 | Not separately reported; existing points suffice | Femoral mechanical axis versus tibial plateau tangent. This is not MPTA, whose axis is CD. An optional compatibility measure needs a named side/direction and its own reference context; do not borrow the MPTA range. |

The extra landmark requirements are substantive. The existing SGR model supplies
neither femoral neck centers nor shaft-axis points. Initial additions should use
explicit manual input with unavailable values until landmarks are supplied, not
fabricated AI coordinates. A femoral mechanical-anatomical angle (FVA/HKS) can
also be measured after shaft landmarks are available. For bowing or malunion,
use proximal and distal segment axes instead of one whole-bone chord.

Primary methodological support:
[NSA measurement reliability](https://pubmed.ncbi.nlm.nih.gov/30001859/) distinguishes
neck-axis construction from shaft-axis construction;
[diaphyseal femoral deformity study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10085644/)
separately measures mechanical/anatomical distal orientation, NSA and bowing.
The template supplies no normal ranges or angle-side definitions; it cannot be
used as a reference-range source. Existing MAD, MPTA, JLCA, LDTA, lengths/LLD and
CPAK-derived quantities extend beyond the six angles listed in these photographs.
This comparison changes documentation only; none of the missing measurements
has been implemented by this amendment.
