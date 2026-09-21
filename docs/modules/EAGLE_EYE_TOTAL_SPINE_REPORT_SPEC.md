# Total Spine: literature-based output specification

Reviewed: 2026-09-19. Scope: reporting requirements and implementation gap audit.
This is a product specification, not a certified patient report or society-endorsed
software standard. No patient images or identifiers are included.

## Evidence and applicability

- [Kim et al., RadioGraphics 2010](https://pubs.rsna.org/doi/10.1148/rg.307105061):
  publicly accessible abstract and figure captions reviewed; full article requires
  access. Covers curve anatomy, end/apical/neutral/stable vertebrae and pedicle-based
  Nash-Moe grading. [2015 erratum](https://pubs.rsna.org/doi/10.1148/rg.2015154011)
  reviewed: corrects a progression statement, not the measurement construction.
- [Radiology 2015, Pelvic Evaluation in Thoracolumbar Corrective Spine Surgery](https://pubs.rsna.org/doi/10.1148/radiol.2015142404):
  full web text reviewed. Balance, sagittal curves and pelvic compensation belong
  in a comprehensive assessment. This adult surgical context must not supply
  universal pediatric normal ranges or automatic treatment advice.
- [SRS glossary](https://www.srs.org/Education/Glossary) and
  [SDSG manual hosted by SRS](https://www.srs.org/Files/Research/Manuals-and-Publications/sdsg-radiographic-measuremnt-manual.pdf):
  manual pages 50-51, 58, 65-66 and 109 reviewed locally; diagrams on pages 51 and 58 visually checked. Thoracic
  AVT uses C7PL when decompensated; TL/L AVT uses CSVL. A body or disc can be apex.
- [AO Surgery Reference, Lenke classification](https://surgeryreference.aofoundation.org/spine/deformities/adolescent-idiopathic-scoliosis/further-reading/lenke-classification):
  standing coronal/lateral plus both supine bending views are required for the full
  classification. Its sagittal modifier uses T5-T12. A major curve is the largest;
  a minor curve can also be structural.
- [Kim et al., LTV study, 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8987554/):
  LTV and substantially touched vertebra are distinct; the latter involves pedicle
  contact. These are contextual fusion-planning observations, not a substitute for
  a general diagnostic report.
- [Morrissy et al., 1990](https://pubmed.ncbi.nlm.nih.gov/2312527/):
  original measurement-error study. Endpoint selection affects reproducibility;
  decimal display does not demonstrate subdegree clinical accuracy.

## Proposed deliverable

The following layout and workflow are our engineering synthesis, not a quoted
RSNA reporting template. Export an annotated coronal image, annotated lateral
image, concise findings/impression, and a structured measurement record.

| Report group | Required content and visible evidence |
|---|---|
| Acquisition | Standing/supine, AP/PA/lateral, orientation, brace status if relevant, comparison date, coverage and unreadable landmarks. No inference of standing from a checkbox default. |
| Each coronal curve | Region and convexity; upper/lower levels and actual endplates; Cobb angle; body/disc apex; rotation method/grade or unassessed. Show the selected segments and angle construction. |
| Coronal alignment | C7PL and CSVL, signed balance with anatomical direction; AVT with its named reference and apex marker. Keep these distinct from trunk shift. |
| Lateral alignment | TK and LL with explicit endpoint conventions; SVA with both landmarks. Offer protocol presets rather than an unlabeled universal angle. |
| Conditional pelvis | PI, PT, SS and PI-LL when appropriate landmarks are visible; pelvic obliquity on the frontal image. Preserve the original pelvis even when excluded from detector input. |
| Adolescent context | Reader maturity assessment such as Risser when assessable. Sanders cannot be derived from spine images alone. |
| Extended planning | Reader NV/SV, contextual LTV/LSTV, flexibility and classification only with required evidence. Do not put all of these into every routine impression. |
| Follow-up | Prior and current angles, dates, endpoint consistency and changes in acquisition. Avoid declaring progression from an arbitrary small numerical difference. |

## Gaps in the current implementation

These findings are not fixed by this documentation change.

1. `assessment.py` proposes an apex from distance to CSVL for every coronal curve.
   That geometric candidate must not stand in for curve-specific anatomical apex
   or a thoracic AVT measurement. Implement region-aware reference selection and
   reader-confirmed apex, including disc coordinates. Do not relabel the existing
   CSVL offset as AVT.
2. The stable candidate minimizes normalized displacement among touched bodies.
   This is an unvalidated heuristic, not an established clinical SV algorithm.
   Missing intervening levels can change its result. Neutral currently proposes a
   single caudal recorded grade-zero level, consistent with the manual
   convention only if anatomical coverage and pedicle symmetry are verified. The
   broader glossary also describes upper/lower neutral boundaries; store which
   convention is used rather than implying both were assessed.
3. The T11-L5 search for a touched candidate has no selected lowest-curve domain.
   Require an explicit applicable curve/domain and coverage review before calling
   this a clinical LTV. Do not infer LSTV from body corners alone.
4. The maximum-angle command searches all assigned levels. Add per-curve scope,
   identity and regional association so an S-shaped spine is not reduced to one
   global maximum pair.
5. TK currently defaults to T4-T12 and LL to L1-S1. Keep exact labels, add named
   protocols and prevent silent interchange with Lenke T5-T12 or other endpoints.
6. Marker names such as C7 center need a documented landmark convention. Sources
   differ between body centroid and inferior-endplate midpoint. Store the selected
   method and do not mix conventions in follow-up. The manual uses kyphosis
   positive/lordosis negative; our current unsigned values need an explicit
   convention field before interoperability or classification. Vertical references also need
   orientation/rotation review, not just an assumed image-column direction.
7. PI/PT/SS, maturity, shoulder/pelvic observations and longitudinal comparison are
   not yet implemented. Missing values must remain unassessed, never normal.
8. The exported side-panel angle sketch supplements the image. Add an in-image
   angle arc where readable, otherwise a clearly linked enlarged construction.
   Add per-curve detail crops and pedicle evidence for rotation review; all views
   must retain source-image linkage. Color is a UI convention, not a medical rule.

## Implementation order and acceptance

First correct reference semantics, curve scope and named sagittal protocols. Then
add pelvic geometry and source-linked reader rotation/maturity evidence. Add
classification only after the bending workflow and prerequisite gates exist.

Use per-parameter status: not assessable, proposal, reader corrected, reader
confirmed. Retain landmark coordinates, method, reference, source identity,
calibration, reviewer state and software/model version. Require only the landmarks
needed by selected measurements; do not force complete vertebral segmentation.

Acceptance must include synthetic known-geometry cases, incomplete coverage,
coronal decompensation, disc apices, multiple curves, pixel aspect, severe angles,
stale-review invalidation and export legibility. Patient testing requires a reader
reference and actual source GUI workflow. Report endpoint/apex identification and
measurement agreement separately; detector confidence is not clinical accuracy.


## Reader-correction implementation follow-up (2026-09-19)

The direct manipulation, anchor numbering preview and source-coordinate pedicle
marking workflow is now implemented in Total Spine; see the module guide. Item 8
has an in-image, explicitly translated perpendicular construction and visible
reader pedicle evidence. It is not an automated rotational classifier. The clinical
reference, protocol, coverage and classification gaps above remain unresolved.


### Classic construction and in-workspace review follow-up

The default source-image construction now includes the real endplate extensions,
perpendiculars from those extensions, right-angle squares and the Cobb arc. The
translated inset is retained only as an explicitly labeled fit fallback and a
supplementary report key. A direct native Eagle Eye tab exposes the source images,
editable landmarks and numbering tools; export is no longer the only demonstrable
surface. These display and access corrections do not close the clinical protocol,
reference or automated rotation limitations listed above.
