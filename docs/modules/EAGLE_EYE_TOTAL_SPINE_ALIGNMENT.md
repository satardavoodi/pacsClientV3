# Eagle Eye Total Spine Alignment

Implementation and research review, 2026-09-17. Source implementation and synthetic
verification are available. Fresh-source live GUI and clinical accuracy acceptance
are pending. No installer was built or released.

## Relationship to the existing alignment conversation

The Codex thread `alignment` was reviewed, including the initial local SGR model
integration, primary-series assignment, automatic draft PDF, manual correction,
reference context and the subsequent Stitching handoff review. Relevant documents:

- [Lower-limb implementation](EAGLE_EYE_ALIGNMENT_VIEW.md)
- [Stitching boundary](EAGLE_EYE_ALIGNMENT_STITCHING_HANDOFF.md)
- [Orthopaedic/Slicer correction review](EAGLE_EYE_ALIGNMENT_ORTHOPAEDIC_REVIEW.md)
- [Eagle Eye ownership contract](EAGLE_EYE_DEVELOPMENT_CONTRACT.md)

Total Spine reuses the study-owned popup pattern, background task ownership,
DX/CR identity validation, private report export and Brain PDF furniture. It has
independent images, state, geometry and model weights. Lower-limb SGR weights do
not detect spine landmarks. No Fast/Advanced/VTK execution boundary was changed.
Native Qt point editing is implemented; a Slicer round trip is not implemented.

## Research and choice

| Candidate | Verified finding | Decision |
|---|---|---|
| [Yi et al., ISBI 2020](https://github.com/yijingru/Vertebra-Landmark-Detection) | Published vertebra-focused landmark method, MIT repository, author-linked checkpoint archive publicly downloadable. Single vertebra class and 17 proposals. | Initial executable research baseline; no claim of best clinical accuracy. |
| [SpineTK](https://github.com/abhisuri97/SpineTK) | README describes a Detectron2 training/annotation workflow and local trained model loading. A ready checkpoint was not established in that inspection. | Potential alternative; not substituted on the strength of a third-party model-card description. |
| [VLTENet](https://github.com/NBU-CVMI/VLTENet) | Source tree includes training/model code. The inspected README does not provide a pretrained weight link. | Research candidate, not a ready local inference integration. |
| [Slicer Markups](https://slicer.readthedocs.io/en/latest/user_guide/modules/markups.html) | Interactive geometry primitives. | Possible advanced editor, not itself an automatic radiographic detector. |

The Yi checkpoint was downloaded from the README-linked Google Drive archive.
Source revision: `b9fc05c215ea2b006564a3feb509634183a63f82`.
Checkpoint SHA-256:
`6a779e01b9a41601334e0a9541278fc557a95bd650c6c8de311204821509d19b`.
Source MIT license and attribution are retained. Separate weight/data redistribution
terms were not established. Local research execution was implemented; no commercial
distribution permission, clinical certification or acceptance receipt is claimed.

## Slicer extension review (2026-09-17)

The official [ExtensionsIndex](https://github.com/Slicer/ExtensionsIndex) was
inspected at revision `b346b2a7c7709c9e2a5189136034368b119e4e2b`, followed by
the upstream documentation and relevant source. This review did not establish a
ready Slicer extension with pretrained, automatic per-vertebra segmentation and
anatomical numbering for full-length AP/PA and lateral radiographs. This is a
bounded search finding, not a claim that no such research exists. An index entry
does not prove compatibility with our bundled Slicer or clinical suitability.

| Extension/project | Verified input and behavior | Relevance to Total Spine radiographs |
|---|---|---|
| [Scoliosis](https://github.com/SlicerIGT/Scoliosis) | Present in the official index. `SpinalCurvatureMeasurement.py` consumes named ruler annotations and calculates projected superior/inferior vertebral angles. The reviewed revision is `e8051009c7f74c71a0febe9d3924d4ab3c27d6a6`. | Measurement reference, not an automatic radiograph segmentation model. Runtime compatibility was not tested. |
| [IGSpineDeformity](https://github.com/SenonETS/SlicerIGSpineDeformity) | Present in the index. Freehand 3D ultrasound workflow using lamina landmarks and projected spinal curves. | Different acquisition modality; its ultrasound methods cannot be treated as radiograph weights. |
| [SlicerSpine](https://github.com/Spine-Biomechanics-Group-Alkalay-Lab/SlicerSpine) | `SegmentAxisAlignment` takes an existing segmentation and computes alignment from segment bounding-box/principal axes. Reviewed revision `9dac63da955a7765f1e7f011145602dbe06c4354`. | Useful after segmentation in a volume workflow; does not itself detect radiographic vertebrae. |
| [SlicerCervicalSpine](https://github.com/MedicalImageAnalysisTutorials/SlicerCervicalSpine) | Indexed cervical atlas/Elastix workflow with volume input and manually supplied vertebral locations. Its authors describe segmentation as an initial estimate requiring improvement. | No demonstrated whole-spine radiograph detector was established. |
| [SegmentWithSAM](https://github.com/mazurowski-lab/SlicerSegmentWithSAM) | Indexed extension with SAM/SAM2 integration. The documented workflow creates labels, selects the current slice, supplies point/box prompts and edits the resulting mask in Segment Editor. | Concrete candidate for interactive contour assistance. It is not a dedicated vertebral numbering or automatic Cobb system; quality on our radiographs remains untested. |
| [TotalSegmentator](https://github.com/lassoan/SlicerTotalSegmentator) / [MONAIAuto3DSeg](https://github.com/lassoan/SlicerMONAIAuto3DSeg) | Available automatic volume-segmentation extensions; their inspected documentation describes CT and/or MR model workflows. | No dedicated pretrained Total Spine plain-radiograph model was established in this review. |

### A relevant radiograph model outside the Slicer catalog

[SpineFM](https://github.com/sjsimons/SpineFM), by Simons and Papiez, is a more
direct segmentation research candidate: its [paper](https://arxiv.org/abs/2411.00326)
and repository target cervical and lumbar radiographs using Medical-SAM-Adaptor
and sequential vertebral localization. It is not a ready Slicer extension, and
the documented scope does not establish performance on full thoracic scoliosis
radiographs or our complete coronal/lateral workflow.

The [weights instructions](https://github.com/sjsimons/SpineFM/blob/master/weights/README.md)
link NHANES and CSXA model folders on Google Drive plus base SAM ViT-B weights.
Those links were identified; the checkpoints were not downloaded or executed in
this review. The repository specifies Python 3.10.8 and GPL-3.0 source licensing.
Weight permissions and product integration requirements remain to be established.

### Engineering decision from this review

Retain the current radiograph landmark baseline while evaluating segmentation as
a separate candidate capability. SegmentWithSAM is the first Slicer candidate
for an interactive correction experiment; SpineFM is a candidate for a separate
cervical/lumbar automatic-mask experiment. Neither is a verified replacement for
the current full-length coronal detector. Mask quality alone would not establish
endplate accuracy, vertebral numbering, apex selection or rotation measurement.

A useful next comparison must measure corrected endplate/Cobb error, missed or
merged vertebrae, numbering failures, correction time and latency on authorized
local images, with AP/PA and lateral results kept separate. No extension was
installed, no runtime was changed, and no patient image was uploaded for this
review. This subsection records research only; it adds no automated-test or live
GUI acceptance claim.

## Measurement after SAM: follow-up review (2026-09-18)

The user accepts SegmentWithSAM as the segmentation direction and asks what can
measure scoliosis and sagittal curves afterwards. Segmentation approval does not
establish that an automatic mask-to-endplate connection has been implemented.

The required interface is: separate vertebral-body masks and reviewed anatomical
labels, followed by superior/inferior endplate candidates in original image
coordinates, followed by selected measurement endpoints. Once those lines exist,
angle calculation is deterministic geometry and requires no additional AI weights.
The difficult unimplemented bridge is reliable mask-to-endplate extraction and
numbering. A whole-spine silhouette, centroid curve, principal axis or minimum-area
rectangle is not interchangeable with anatomical endplates, particularly in wedged
vertebrae. This is our engineering assessment of the inspected algorithms.

| Resource | Verified availability | Integration assessment |
|---|---|---|
| [Slicer official two-line angle example](https://slicer.readthedocs.io/en/latest/developer_guide/script_repository/markups.html#measure-angle-between-two-markup-lines) | Python/VTK example computes the angle and observes changes to line markups. | Reusable interaction pattern once endplates are known; it does not find them. Preserve projection, pixel aspect, endpoint direction and measurement convention. |
| [LijunRio/Spine-cobb-angle-measurement](https://github.com/LijunRio/Spine-cobb-angle-measurement) | Both Python scripts inspected. Coronal code thresholds, finds contours and uses `minAreaRect`; sagittal code approximates polygons, assumes point ordering and hard-codes T2/T5/T10/L2 endpoints. | Relevant mask-to-geometry prototype, not a reliable drop-in. The README's Hough-line description differs from the inspected implementation. Fixed pixel thresholds, sequential labels and acute-angle slope arithmetic need replacement, not blind reuse. No reuse license was established. |
| [ScolioVis](https://github.com/Blankeos/scoliovis) | AP radiograph Keypoint R-CNN and Cobb pipeline; GitHub release API confirms `keypointsrcnn_weights.pt`, 236,680,079 bytes, under `scoliovis-training` tag `latest`. | Concrete pretrained coronal alternative, operating on images rather than consuming SAM masks. Checkpoint execution and redistribution permission were not tested/established. No lateral capability is claimed. |
| [CurvNet, formerly SG-LRA](https://github.com/Ernestchenchen/CurvNet) | Research code for radiographic landmarks/Cobb; README expects `work_dirs/spinal_det/latest.pth`. No `.pth`, `.pt` or `.ckpt` file was found in the inspected main tree, and the README did not establish a downloadable pretrained checkpoint. | Research alternative with old Python 3.7/PyTorch 1.8 dependencies; not a verified ready-weight integration. |
| [DIAGNijmegen Cobb algorithm](https://github.com/DIAGNijmegen/cobb-angle-algorithm) | Actual `compute-Cobb-angle.py` exists despite stale README text. It processes 3D MRI disc masks using marching cubes and fitted planes. | Useful geometric reference, not directly compatible with 2D SAM vertebral-body masks. |
| [Medical SpinePose, Harake et al.](https://arxiv.org/abs/2402.06185) | Whole-spine lateral radiograph landmark model for LL, SVA, PI, PT, SS, T1PA and L1PA. | Directly relevant research for sagittal automation; this search did not establish downloadable medical model weights. The similarly named DFKI human-pose package is a different project. Thoracic kyphosis is not among the paper's listed outputs. |

Proposed implementation direction: reuse the existing tested Eagle Eye angle
engine and editable points; develop per-body mask-to-endplate proposals using
contours plus original image evidence, with explicit rejection/review of ambiguous
boundaries. For AP automatic initialization, compare the existing Yi baseline with
ScolioVis before switching models. For lateral measurements, retain editable
endplates and explicit levels until a suitable detector is locally evaluated.
SAM alone does not supply S1, femoral-head landmarks, anatomical numbering or
pedicle-based rotation assessment automatically.

This follow-up changed documentation only. No new model was downloaded, executed,
installed or represented as clinically validated.

## SAM and ScolioVis implementation (2026-09-18)

The research-only status in the preceding follow-up is superseded for these two
models: both weights are now downloaded, pinned, prepared and executed locally.
The official SAM engine is integrated in the native Eagle Eye editor; the Slicer
extension UI is not installed or launched. No generic OpenCV demo, unverified
SpinePose checkpoint, SpineFM model or CurvNet training environment is substituted.

### User workflow

- On coronal images, choose Yi ISBI 2020 or **ScolioVis Keypoint R-CNN**, then use
  **Suggest T1-L5 corners with AI**. Exactly 17 valid ordered detections are required;
  extra/missing bodies are rejected instead of silently truncated or renumbered.
  Both models require explicit reader verification of the assumed T1-L5 sequence.
- In either projection, choose a C1-L5 level, click **Select body box for SAM**,
  then click two opposite corners around one vertebral body. Confirm acquisition
  and click **Segment selected body**. The box is transformed into a context crop
  and all returned geometry is translated back to original image coordinates.
- Inspect the green mask and orange endplate proposals. **Use proposed endplates
  for selected level** explicitly replaces that level's landmarks. The preview
  graphics are then removed so they cannot obscure subsequent blue-handle edits.
  Add the desired curve using explicit end vertebrae and endplates. The existing
  Cobb/kyphosis/lordosis and report engines recompute from the editable lines.
- S1 is intentionally manual: a sacral silhouette is not a vertebral body with two
  interchangeable endplates. Anatomical numbering, apex confirmation and Nash-Moe
  rotation remain reader tasks. SAM quality is an uncalibrated model score, not a
  probability of clinical correctness; the model can return scores above 1.

### Endplate contract and lifecycle

`mask_geometry.py` fits superior and inferior contour envelopes independently,
using the central 70% of horizontal support and robust residual rejection. It
retains wedging rather than replacing the body with a rotated rectangle. Returned
points are endplate line handles within the fitting support, not automatically
verified anatomical corners. Weak mask scores, multiple substantial components,
crop-edge contact, large holes, internal gaps, unsuitable proportions, irregular
boundaries and masks substantially outside the selected box prevent application.
These thresholds are conservative engineering heuristics, not clinically tuned
performance criteria. An accepted mask can still be anatomically wrong.

The original image, visible mask and explicit reader review supply the assessment;
there is no separate image-edge refinement model in this version. Rebox an
unsatisfactory body or correct the applied endplate handles manually.

Inference and mask processing run in the owned background executor/subprocess.
Cancellation, failure and completion remove temporary pixels. Image identity,
source hash, projection, dimensions and selected level bind the returned preview.
Applying/editing points invalidates review and report access. Private report JSON
retains per-level prompt, weight/mask hashes, fitting diagnostics and reader edits;
the raw mask is a transient preview, not a persisted DICOM SEG artifact.

### Assets and preparation

Run `.venv/Scripts/python.exe tools/eagle_eye/prepare_total_spine_assist.py` after
the existing Alignment runtime and Total Spine base bundle are available. This
creates `generated-files/eagle-eye/total-spine/assist/`, without pip installs or
changes to the application venv or shared portable runtime. Local CPU execution
uses torch 2.8.0 and torchvision 0.23.0, strict state dictionaries and
`weights_only=True`; no pretrained-backbone download or remote image API is used.

| Asset | Pin |
|---|---|
| SAM source | `dca509fe793f601edb92606367a655c15ac00fdf`, official Meta repository; Apache-2.0 license retained |
| SAM ViT-B weights | 375,042,383 bytes; SHA-256 `ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912` |
| ScolioVis architecture reference | `1edbe566c4acd4df33e0834db0f4cb9fa357ba2c`; independent torchvision loader, no upstream service code bundled |
| ScolioVis released weights | 236,680,079 bytes; SHA-256 `990f3ad661f07dc8975dc655876e2fc3bfa64c8da941c485465589083448c32b` |

The optional nested assist package has a strict file manifest and separate
model-bound distribution acceptance. ScolioVis redistribution rights remain
unresolved; no customer acceptance receipt was fabricated. The existing edition
rules exclude Eagle Eye models from Standard/ARM. No installer/release was made.

### Verification

Final focused/adjacent selection: **148 passed**, direct pytest exit 0, with 10
existing SWIG/QMouseEvent deprecation warnings. All 17 assist manifest files and
the worker/source match verified; 468 existing plugin mirror pairs match. No new
Python mirror applies to this Eagle Eye feature tree. Tests include two
reproduced-before-fix preview/checkbox regressions, invalid masks, aspect-aware
wedging, explicit application, native-coordinate offscreen clicks, stale binding,
running-process cancellation/cleanup, model seals and nested payload acceptance.

Real SAM weights produced a mask and endplate proposal on a synthetic rectangular
input through the complete owned service. Initial cold end-to-end time was
284.92 s, including full runtime validation. In a subsequent already-warm disk
session, first use took 36.85 s and a second prompt took 17.38 s. A window-owned
runtime seal snapshot avoids repeated full hashing when all sealed-file metadata
is unchanged; any change invalidates it. No clinical-image latency is claimed.

ScolioVis strictly loaded the released weights and completed inference, returning
zero detections on the nonanatomical synthetic image. This is expected execution
evidence, not a sensitivity/accuracy test. The SAM mask/preview and applied UI
were inspected offscreen with synthetic input. Real mouse-coordinate dispatch is
covered by an offscreen QTest guard, not a live PACS acceptance receipt.

The existing control client could not reach the source app. Human source launch
and sign-in with `AIPACS_TEST_SERVER=1`, an authorized radiograph, and real GUI
review remain required. No patient image was uploaded or used as a fixture.

## Current workflow

1. Open a DX/CR study in Eagle Eye and choose **Total Spine Alignment | Coronal + Lateral**.
2. Assign a series and image separately in the coronal and lateral tabs. Loading
   requires the selected Study/Series/SOP identity. Conflicting AP/PA versus lateral
   ViewPosition tags are rejected. Missing tags require explicit reader confirmation.
3. Confirm upright standing acquisition, projection and anatomical orientation.
   Review any acquisition-system stitching. Use **Clear projection** to omit a view.
4. For a complete coronal T1-L5 image, run **Suggest T1-L5 corners with AI**.
   The model produces 17 unlabelled bodies; sequential T1-L5 assignment is an explicit
   assumption, not learned numbering. Any weak, out-of-bounds, degenerate or unordered
   proposal rejects automatic application. Incomplete or transitional anatomy needs
   manual placement and numbering. No hidden point clamping is used for AI output.
5. Valid proposals produce a maximum endplate-difference curve proposal and an
   unreviewed draft PDF, provided every loaded projection has valid measurements.
   This is not automatic structural-curve or Lenke classification.
6. Inspect points with zoom/pan. Place or drag corners, choose upper/lower vertebrae,
   select the lower endplate, add up to five curves and record the reader-selected
   body/disc apex. Remove/replace a proposed curve when its endpoints are unsuitable.
7. On lateral images, use reviewed SAM body proposals or manual landmarks, with S1
   placed manually. Kyphosis defaults to T4 superior to
   T12 inferior; endpoints are editable and explicitly printed. Lordosis defaults
   to L1 superior to S1 superior. Endpoint protocols must match longitudinal comparisons.
8. Optional C7 and sacral landmarks provide balance. Optional Nash-Moe grade and
   direction are recorded as a reader assessment on the coronal image only.
9. Confirm landmark/numbering review and generate the reviewed PDF. Every image,
   point, scale, orientation, curve or impression change invalidates active report
   access. Private versioned PDF/HTML/JSON results are retained, and PDF copies use
   the existing atomic export service. Reports remain unsigned.

## Measurement contract

Coordinates are native image x/y, with y downward. Corner names refer to image
left/right, not anatomical laterality. Row/column spacing corrects pixel aspect
before angles. Complete vertebral outlines must be finite, convex, ordered and
inside the image. Superior and inferior endpoints are not interchangeable.

| Measurement | Implemented behavior |
|---|---|
| Coronal Cobb | Difference between upper superior and selected lower endplate tilts; no acute-angle folding, preserving severe angles over 90 degrees. Explicit endpoints retained. |
| Apex | Reader-selected vertebral body or adjacent disc. A separate geometric candidate maximizes body-centroid distance from the end-centroid chord; it is not presented as confirmed anatomy. |
| Kyphosis/lordosis | Lateral, reader-named unsigned endplate angle with explicit levels. The algorithm does not diagnose the sagittal curve type from its magnitude. |
| Coronal balance | Horizontal C7-center minus sacral-center offset; sign mapped to patient right after reader orientation confirmation. |
| SVA | Horizontal C7-center minus S1 posterior-superior corner; positive anterior after orientation confirmation. |
| Rotation | Reader-entered Nash-Moe grade 0-4 and side. Grade 0 requires no side. No numerical axial degree estimate is invented from endplate corners. |

Distances remain native pixels until patient-plane scale is verified; detector
spacing alone is insufficient. No universal normal ranges, surgical targets,
automatic diagnosis, PI/PT/SS or PI-LL mismatch, bending-curve flexibility, Risser,
Lenke classification or 3D rotation are implemented. Those require additional
landmarks, acquisition/context and validation, not just reuse of the 17-body model.

Clinical method references:
[SRS glossary](https://www.srs.org/Education/Glossary),
[SDSG radiographic manual](https://www.srs.org/Files/Research/Manuals-and-Publications/sdsg-radiographic-measuremnt-manual.pdf),
[RSNA scoliosis imaging](https://pubs.rsna.org/doi/10.1148/rg.307105061),
[DICOM calibration](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_10.7.html).

## Runtime, privacy and packaging

`modules/ai_imaging/eagle_eye_total_spine/` contains pure geometry, snapshot
validation, background services, native UI, inference entry and private reports.
No database/schema, configuration family or installer module identity is added.
The feature belongs to Advanced MPR's existing Eagle Eye edition at
`advanced_mpr/eagle_eye/total-spine`. Standard/ARM exclude the entire Eagle Eye
model asset tree. The separate spine model reuses Alignment's already installed
portable CPU interpreter; it does not modify that runtime or the application venv.

Prepare the model with:

```powershell
.\.venv\Scripts\python.exe tools/eagle_eye/prepare_total_spine.py
```

The preparation tool pins source revision and checkpoint hash, preserves license
and notice, removes the optional pretrained-network download path, and seals a
strict file allowlist. Runtime uses an owned subprocess, `weights_only=True`,
strict state-dict loading, CPU execution, cancellation and a 180-second inference
deadline. No images are sent to an external AI service. Temporary pixels and model
results remain local and are removed when the job ends.

Preprocessing adapts the original OpenCV resize to PIL bilinear resizing of a
replicated grayscale image at 512x1024, with `/255 - 0.5` normalization. This is a
documented implementation difference that requires clinical validation; published
accuracy numbers cannot be transferred to this adaptation.

`builder/eagle_eye_total_spine_payload.py` stages only manifest-listed model files
and requires the Alignment runtime. Customer distribution requires model-bound
offline inference, live GUI and distribution-rights acceptance. Synthetic test
receipts only exist in temporary test fixtures. No real receipt was fabricated.

## Verification and remaining acceptance

- Focused and adjacent selection: **117 passed**, direct pytest exit 0; six existing
  SWIG deprecation warnings. Includes geometry, DICOM projection/series mismatch,
  patient/study binding, cancellation, automatic draft dispatch, stale-report
  invalidation, PDF pagination/atomic publication, existing Alignment/workspace
  behavior, model integrity and edition staging.
- The full background service, including verification of the shared 16,887-file
  Alignment runtime seal, completed on the synthetic input in **276.97 seconds**.
  This is end-to-end cold preparation/inference time, not model-only latency.
  Runtime seal verification is a material current startup cost; it runs off Qt.
- Synthetic checkpoint execution loaded strictly and returned 17 finite candidate
  sets. Confidence was low (approximately 0.03-0.11); automatic measurement application
  rejects that input. This is a model-execution check, not anatomical accuracy evidence.
- The synthetic coronal/lateral PDF was rendered with Poppler and all three pages
  inspected. A separate offscreen native-widget snapshot was inspected. These do
  not replace live application input or clinical review.
- Existing packaged mirrors: 468 pairs match. These Eagle Eye source files have no
  existing plugin-Python mirror; the model bundle has its own hash manifest.
- The documented Test Control client `ping` could not reach the source application
  during this task. No startup/login, process recovery, installed executable or
  production Agent Gateway was used. Fresh human source launch/sign-in with
  `AIPACS_TEST_SERVER=1` and an authorized Total Spine study are still required.

Next live acceptance: select both real series, verify rendered identities and
projection, run coronal inference, review all 17 body proposals and numbering,
correct a point using actual mouse input, verify recalculation/report invalidation,
measure a lateral curve, compare with independent clinician measurements, export
PDF, switch series, and close/reopen the owned popup. Keep real identifiers and
images in private User Data; do not add them to this document or committed fixtures.


## Selected-endplate workflow update (2026-09-18)

This update supersedes the automatic T1-L5 assignment and automatic draft workflow
above. Select a spine region using two image clicks before running either detector.
Inference remains in the owned worker; crop coordinates are restored to the source
image. Yi still expects complete thoracolumbar coverage; ScolioVis supports variable
candidate counts. All candidates are marked as needing anatomical review, regardless
of detector confidence. Candidate proposals are not clinical certainty estimates.
Select a candidate, choose its actual level, and assign it explicitly. Existing
points cannot be overwritten by assignment; discard bad detections, remove a wrong
level or place missing endplates manually. No new checkpoint was added in this update.

Superior endplates are blue; inferior endplates are yellow. Visible line labels and
the placement status identify the level and endplate. Placement advances left to right,
then returns to pan/drag mode. Curve controls state exactly which two endplates are
required and provide direct edit buttons for each. Only those four endpoints are
needed for Cobb/kyphosis/lordosis geometry. Body centroids and apex proposals remain
optional and need complete usable body outlines. A maximum-angle pair can be proposed
from assigned levels, but is not automatically accepted as the clinical curve.

Each recorded curve has an explicit endplate/numbering confirmation. Its fingerprint
includes the source image identity, selected coordinates, levels, spacing, acquisition
and orientation. Changes to those invalidate its confirmation; unused body points do
not enter the fingerprint. The overall review checkbox still covers acquisition,
scale, balance and rotation when present. Reviewed exports reject unconfirmed curves.
Report evidence follows the same blue/yellow convention. SAM mask quality gates are
unchanged; no continuity threshold was relaxed based on a single clinical case.

Automated coverage includes offscreen mouse clicks and report rendering with only two
endplates. Offscreen evidence is not live application acceptance. The documented local
Test Control ping was unavailable during this implementation; a fresh human source
launch/sign-in is still needed to exercise the updated workflow on the authorized case.


### Coronal field-of-view refinement (2026-09-19)

After selecting a coronal region, each top/bottom/left/right boundary can be reset
with one image click. Guidance asks the reader to retain the intended thoracic and
lumbar endplates through L5 while excluding the head, sacrum, pelvis and unrelated
lateral artifacts. This is reader-defined anatomy, not automatic sacrum detection.
Moving an edge clears unassigned proposals from the old ROI and preserves manually
assigned landmarks. The actual cropped pixels, not merely a post-inference overlay,
are passed to the detector. S1 remains available for lateral manual lordosis input.
Two additional synthetic guards cover lower-edge refinement/state ownership and
prove that pixels below the cutoff never reach the predictor. Focused suite: 67
passed. This change has not yet passed live source GUI or clinical acceptance.

### Annotated scoliosis evidence (2026-09-19)

Selected endplate segments and their clipped extensions now share source-coordinate
geometry between the editable canvas and report images. Superior is blue, inferior
is yellow, CSVL is green and C7/balance references are pink. Labels identify curve,
vertebral level, plate and angle. Exports preserve pixel aspect and include a
translated-direction angle diagram; severe angles are not folded to acute values.
Reports include dedicated evidence pages and per-projection annotated PNGs bound
by SHA-256 in the atomic JSON/PDF output. Open annotated images opens the private
report folder. Draft/review state is explicit on each image.

Coronal assessment adds reader-selected stable, neutral and last-touched vertebrae.
Separate proposals use available numbered bodies: apex by displacement from CSVL,
stable by normalized centering among distal touched bodies, and last-touched by
the most cephalad touched T11-L5 level. This limited-outline heuristic must not be
used as an automatic surgical-level recommendation. Neutral proposals require an
explicit reader-recorded Nash-Moe zero grade below the apex; endplate tilt is not
rotation. Missing body outlines or references remain unassessed. Original sacral
reference coordinates remain available even when excluded from the detector ROI.

Verification: 71 focused synthetic tests passed, including offscreen overlay
refresh/clear, physical aspect, reference proposals and PNG digest binding.
Synthetic PNG and rendered PDF evidence inspected. Local Test Control ping and
list_actions succeeded, but native control is unavailable in this agent session;
this implementation has not passed an affected-workflow live GUI acceptance or
patient-specific anatomical confirmation. No clinical measurement was certified.

### Literature output audit (2026-09-19)

See [literature-based report specification](EAGLE_EYE_TOTAL_SPINE_REPORT_SPEC.md).
The audit identifies outstanding reference/protocol issues: all-curve CSVL apex
proposals are not thoracic AVT, normalized-centering SV is a heuristic, touched
candidates lack curve-specific coverage, and named sagittal protocols are needed.
Existing passing geometry tests do not validate these clinical semantics. The
specification distinguishes routine outputs from conditional planning parameters.


### Direct reader correction and visible pedicle evidence (2026-09-19)

The Total Spine canvas now permits whole-endplate translation and endpoint rotation,
with live line previews. A clickable body badge between the two endplates opens an
anchor numbering preview. Known numbering gaps are preserved; duplicate targets,
reversed ordering, out-of-range sequences and evidence collisions are rejected.
Unassigned detector candidates have a separate ordered-anchor preview requiring
explicit confirmation of complete, non-duplicate coverage; existing bodies cannot
be overwritten. Applying numbering updates curve endpoints, disc/body apex,
SV/NV/LTV selections, rotation records and pedicle evidence together. It revokes
review. Thirty local undo transactions retain corrections without restoring prior
clinical approval. New images, detector results and ROI changes clear history.

Coronal pedicle centers can be placed and dragged independently, using image-left
and image-right labels. Body midline and half-body thirds are visual aids only.
No automatic Nash-Moe classifier or validated pedicle detector was added. A reader
records the ordinal grade; editing its body or pedicle landmarks removes the stale
grade. SAM application follows the same invalidation contract. Pedicle coordinates
are retained in the report snapshot/JSON and visible in PNG/PDF evidence. Stable,
neutral and last-touched body outlines now show reader/proposal status on-image.
The clinical limitations in the report specification remain open.

Unbounded endplate extensions have been replaced by a curve-linked, translated
perpendicular construction inside the image, including right-angle squares and
an angle arc. Translation is explicitly labeled; these are not falsely presented
as normals intersecting at the original vertebral locations. Calculations, arc and
native display respect physical pixel aspect; angles above 90 degrees are retained.
Multiple curve constructions receive separate vertical slots. The original colored
endplates retain their curve/level/plate labels.

Scope: implementation is in Total Spine. The correction contract is appropriate
for other Eagle Eye measurement tools, but this change does not claim a universal
mask/landmark editor or retrofit of every module.

Verification: four new feature guards first failed before implementation. The focused
suite passed 84 tests including offscreen mouse segment drag, endpoint drag, body
badge numbering, undo, physical normals, pedicle validation and report/builder guards.
Offscreen input is not native GUI acceptance. Plugin mirror verification: 468 pairs
matched, zero plugin-only entries. Native source test-control ping/list_actions were
reachable. In the affected source workflow, the coronal thumbnail double-click left
Advanced empty; native drag remained a drag preview and was cancelled with Escape.
The Eagle Eye function picker exposed only disabled generic entries, so Total Spine
could not be opened. No application restart/hot reload or viewer-domain fix was
attempted. Live correction acceptance remains blocked at that entry boundary.
Local clinical preview uses existing unnumbered detections only; no pedicle or level
was invented for the patient and no clinical measurements were certified.


### Classic Cobb display and embedded workspace (2026-09-19 follow-up)

The default Cobb overlay now extends the actual selected endplates to the feet of
two perpendiculars meeting inside the source image. Right-angle squares document
both connections; the angle arc is between consistently oriented normal rays so
obtuse measurements are retained. The intersection location is chosen for in-image
feasibility in physical coordinates, then orthogonally projected onto each endplate.
No source point or measured angle is moved. If extreme cropping prevents a valid
construction, the exceptional translated diagram is explicitly labeled. The side
panel remains a supplementary translated angle key, not the primary construction.
Reference: SRS Boston Brace Manual (2003), PDF page 27 / printed page 23,
https://www.srs.org/Files/Research/Manuals-and-Publications/SRS_Boston_Brace.2003.pdf .

A direct **Total Spine Alignment** button is now present in the Eagle Eye header
whenever a study identity exists, independently of Advanced Viewer readiness or
its modality metadata. It opens a persistent tab immediately after Imaging Tools.
The existing picker routes to the same editor. A host without a tab container
retains the owned popup fallback. Repeat opening preserves the same worker/editor
and does not rescan or discard corrections. The initial scan is background-only;
DX/CR filtering and Study/Series/SOP validation remain in the image service. Opening
the panel is not permission to infer from a different study or from an unsupported
modality. Workspace destruction cancels its owned analysis.

User route: Eagle Eye > Total Spine Alignment > Find study images (initially runs
automatically) > select coronal/lateral series and Load selected image. Confirm the
acquisition, select the ROI and request proposals. All unnumbered candidates now
remain visible, with the selected candidate emphasized. Assign a body or review an
anchor sequence, then drag endplates, edit body labels and record measurements in
the same panel. Report export is a separate final action. SAM/ScolioVis/Yi run in
owned background processes; no interactive Slicer application is required. The
import of the Slicer package's ProcessJob helper is process-lifecycle reuse, not
execution of Slicer UI.

Verification: two fail-before guards reproduced the disconnected construction and
popup-only route. The focused suite passed 126 tests covering source-connected
physical geometry, real workspace button input before viewer readiness, tab reuse,
all-candidate visibility, existing correction/report/worker contracts and payload
validation. The private patient preview reuses existing unnumbered detections;
no new AI run, anatomical confirmation or clinical rotation was manufactured.
A source-widget offscreen preview was visually inspected; it is not live acceptance.
The running Test Control server responds, but the existing UI predates the entry
change. A human fresh source launch/sign-in was requested under AGENTS.md; no hot
reload, restart or second app instance was attempted. Live acceptance remains pending.


### Fresh source native entry receipt (2026-09-19)

The user explicitly requested launch with the test flag. No source main.py process
or application window remained, so one .venv source instance was launched with
AIPACS_TEST_SERVER=1. Authentication was not automated. Home became ready; fresh
ping and 77-action discovery succeeded. Native Eagle Eye navigation showed the new
header button. Clicking it opened the embedded Total Spine tab before Advanced had
loaded any pixels. Background discovery returned eligible radiographs. Native
selection/loading rendered both requested coronal and lateral source images, and
switching projections preserved the loaded coronal image. Patient identifiers and
receipts remain private. This verifies native entry, independent loading and display;
it does not certify native endplate dragging, numbering changes, inference or export
in this run. Those interaction/geometry contracts have automated/offscreen guards.
The editor remains open for reader correction. No clinical result was signed.


### Choose Function and results-first review (2026-09-19)

This supersedes the preceding direct-header-button flow. Total Spine is selected
through Choose Function alongside the existing DX/CR functions. The picker can
resolve study modalities from the local catalog on an owned background worker
before the viewer loads. Mixed-modality catalogs ask which image type to use.
The separate Total Spine header button is removed.

The preparation window requests a coronal image and a two-corner spine region;
that second corner automatically runs the local ScolioVis detector. This minimal
input is still required: projection descriptions alone are not reliable enough,
and no validated automatic spine-region detector is installed. No acquisition or
numbering confirmation is fabricated. Results include unnumbered endplates and a
physical-pixel-aspect maximum-angle proposal with classic Cobb construction.
Only successful nonempty results reveal the reusable Total Spine Alignment tab,
appended after Reception Data. Cancellation or failure keeps preparation retryable.
Lateral angles, rotation and clinical curve selection still require reader input;
the coronal model does not silently run on a lateral image.

Review controls use collapsible sections: numbering and endplate correction are
expanded, while detection, calibration and detailed assessment are collapsed.
Source image switching, report evidence gates and manual corrections are preserved.

Regression: test_total_spine_workspace.py failed three new behavior guards before
implementation (extra header button, premature tab, missing automatic transition).
It also covers canceled/empty results, off-thread catalog resolution, physical-angle
ordering and narrow-sidebar layout. Focused code suite: 131 passed, six third-party
deprecation warnings. Mirror verification: 468 pairs match, no plugin-only files.
Private offscreen preview reuses existing source-image proposals and was inspected;
it is not a new AI inference receipt or live application acceptance. The existing
source session responds to ping/list_actions but predates this revision. Fresh
source launch/sign-in and native Choose Function -> preparation -> result-tab
acceptance remain pending. No process restart or authentication was automated.


### Native results-first acceptance observation (2026-09-19)

Following the explicitly authorized fresh source launch and human login, ping and
list_actions succeeded. Actual native clicks verified Choose Function with DX
options and no separate Total Spine header button. Preparation discovered eight
eligible radiographs. Loading the authorized coronal source and marking two ROI
corners started fresh local inference without a separate run-button click. The app
remained responsive to Test Control ping. Successful inference closed preparation
and appended Total Spine Alignment after Reception Data; proposed endplates and
the source-connected angle construction were visible. The requested lateral source
also rendered, and switching back retained the coronal proposals. No anatomical
numbering, acquisition approval, reviewed report or clinical sign-off was fabricated.
Patient-specific values and identities are confined to private local test receipts.

Two presentation defects were observed, not fixed or claimed passed in this lap:
(1) moving from preparation to the smaller embedded viewport retains the previous
zoom until Fit image is clicked; (2) expanding Acquisition and scale produces
horizontal scrolling in the narrow sidebar because the two spacing controls share
a row. The initial collapsed sidebar fits. The native input/processing/tab-routing
path is verified, but overall presentation acceptance remains partial. Native
endplate dragging/numbering and clinical measurement accuracy were not certified.


### Direct candidate editing and left naming panel (2026-09-19)

Unnumbered AI candidates previously used paint-only graphics with mouse input
disabled. Only assigned anatomy used the interactive endplate primitives. The
review editor now uses those same segment/endpoint primitives for unnumbered
candidates, plus clickable body outlines and badges. Clicking selects the matching
candidate in the left naming panel; dragging a body translates all four corners,
dragging an endplate translates its pair, and dragging an endpoint changes tilt.
Edits validate source bounds and body geometry, update the geometric angle proposal,
retain reader-modified provenance on assignment, support Undo and never invent levels
or clinical confirmation. Labels sit beside the bodies to leave endplates accessible.

The left panel owns level selection, candidate assignment, numbering preview and
assigned-number correction. The right keeps endplate correction and measurement
review, with detection, acquisition and additional assessments collapsed. Orange
ROI corners resize the field of view and its border translates it. A changed valid
ROI invalidates unassigned detections; a click without motion preserves them and an
invalid resize restores its handles. Assigned landmarks are preserved. Acquisition
spacing controls are stacked to fit the narrow panel. A widget-owned queued fit
runs after results are reparented into their tab.

Validation: the real Qt mouse candidate-selection guard failed before the fix;
an ROI no-op guard also failed before its correction. Endpoint, line, whole-body,
ROI-corner, Undo, invalid-geometry, reparent-fit and expanded-calibration tests pass.
The focused Total Spine/workspace/background/builder suite passed 137 tests with
six third-party deprecation warnings and process exit 0. All 468 mirror pairs match;
these source files have no existing plugin Python mirror. The private offscreen
preview was regenerated and inspected. No new patient inference was run for that
preview. The source app is no longer running and Test Control ping is unavailable;
this interaction revision still requires a fresh source native GUI test. Prior
native results-first acceptance does not certify these new mouse interactions.

## Visible analysis actions (2026-09-20)

The preparation/review surface now exposes Select spine region, Detect vertebrae
(AI), and Measure angles in an always-visible top row. Detection is enabled only
for a loaded coronal image with a valid ROI and no running worker. An explicit
button request starts proposals without marking acquisition or measurements as
reviewed. ROI completion retains the existing automatic first-run behavior.
Measure angles reveals the end-vertebra/endplate controls; Add curve from selected
endplates creates the requested angle, which updates with subsequent endpoint
correction. It does not rerun landmark detection.

The shared dismiss button now says Hide window / return to PACS and explicitly
states that it does not start analysis. Running computation still continues when
hidden; pending selector dismissal keeps its established cancellation behavior.

Two guards in `tests/code/ai_imaging/test_total_spine_analysis_actions.py` failed
before the changes and now pass. The focused spine/editing/annotation/workspace/
background/builder selection passed 78 tests, exit 0, with six third-party warnings.
All 468 existing plugin mirrors match. Local Test Control ping is currently
unreachable, so fresh-source native action/progress acceptance is blocked, not
passed. No application restart or live inference was improvised.


## Completed-stage progress and assigned anchors (2026-09-20)

Total Spine detection and SAM preview now publish thread-safe completed-stage
snapshots. The native review panel and shared background dialog show percentages
of completed stages, the current phase, and the remaining stage count. Detection
tracks region preparation, model execution, coordinate validation, and editable
result application. SAM tracks package/input preparation, model execution, mask
validation/endplate fitting, and preview application. Completion reaches 100% only
after the GUI accepts the result. Cancellation/error never fabricates completion.
Stage durations differ; these percentages are not elapsed-time fractions or ETA.
Other modules without completed-work instrumentation retain indeterminate activity.

The numbering action now combines assigned bodies with remaining candidates, in
image vertical order. A selected assigned L4 remains a valid anchor after assignment.
The review table permits individual anatomical exceptions, rejects duplicate names,
remaps existing curve/pedicle evidence, records numbering exceptions, invalidates
clinical approval, and preserves a single undo transaction. The reader must verify
upright orientation, body coverage, duplicates and missing/variant levels.

Verification: three initial guards failed before implementation; 81 focused and
adjacent tests pass (exit 0, six third-party warnings), with AIPACS_TEST_SERVER=0.
All 468 existing mirrors match. Local Test Control ping is unavailable; native
fresh-source GUI acceptance remains pending. No restart, login, live inference,
clinical data export, or test-server enablement was performed for this slice.


## Measurement-specific guided review (2026-09-20)

The right panel lists each curve's angle, apex, apical rotation, neutral, stable,
and last-touched assessment, plus projection balance. States are Missing data,
Needs review and Ready; no complete-spine naming requirement is introduced.
The left task card explains the selected missing evidence, offers edit/confirm/
next-review actions and hosts the relevant existing controls. Selecting a body
result focuses the same image canvas. Balance placement uses the full image and
asks for the missing S1 reference before C7; millimeter review requires calibration.
Pedicle and reader grade controls are grouped together; SAM is hidden during the
pedicle review task. No automatic pedicle detector or rotation classifier is implied.

Existing geometry supplies editable apex/stable/neutral/last-touched proposals;
proposals are never automatically committed as reader choices. Clinical assessment
selection is applied through Update selected curve. Independent confirmation
signatures are stored in existing provenance and undo snapshots, bound to image
identity and relevant evidence. Endplate confirmation now fingerprints only the
angle/endplate specification, so editing an apex or other assessment does not
revoke unchanged Cobb evidence. Overall report review remains explicit.
Optional incomplete assessments do not block an otherwise valid curve export.

Verification: two initial new-flow guards and the existing endplate-confirmation
regression failed before their fixes. Four guided-review guards plus adjacent
geometry/editing/workspace/progress/builder guards pass: 82 tests, exit 0, six
third-party warnings, AIPACS_TEST_SERVER=0. A synthetic offscreen layout was
inspected; this is not native application acceptance. Test Control ping remains
unavailable and no running app was restarted or hot-reloaded. Global mirror
verification found five unrelated EchoMind mismatches among 468 pairs; these were
not synchronized or modified by this slice. New spine code has no existing mirror.
