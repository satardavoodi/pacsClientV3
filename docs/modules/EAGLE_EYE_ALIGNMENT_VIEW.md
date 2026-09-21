# Eagle Eye Alignment View

[Stitching handoff review](EAGLE_EYE_ALIGNMENT_STITCHING_HANDOFF.md) records the
confirmed current export/input incompatibility and the proposed immutable derived
image contract. The direct Stitching-to-Alignment bridge is not implemented.

[Orthopaedic measurements and native/Slicer correction review](EAGLE_EYE_ALIGNMENT_ORTHOPAEDIC_REVIEW.md)
records the next-step assessment, including WBL, CORA and a proposed validated
Slicer round trip. It explicitly separates current functionality from proposals.

Implementation and evidence, 2026-09-14. Source is implemented; fresh-source live
GUI acceptance remains pending. No installer or clinical accuracy claim is made.

## Research decision

Use [SGR pretrained landmark models](https://github.com/ETRO-MIT/LowerLimbMalalignment-SGR)
as the initial local research engine. The authors combine landmark heatmaps and
coordinate regression after Faster R-CNN region detection. The publication is
Sanchez, Van Overschelde and Vandemeulebroucke, IEEE Access 12 (2024), 61484-61497.
Training data are not publicly released and the models are described as research
tools. This is an executable, inspected baseline, not proven superiority over
every alternative. Existing Eagle Eye Brain segmentation is a separate workflow.

| Alternative | Finding and practical role |
|---|---|
| [Slicer Markups](https://slicer.readthedocs.io/en/latest/user_guide/modules/markups.html) | Editable points, lines and angles; not itself a trained full-leg detector or complete alignment report. |
| [VTK angle widget](https://vtk.org/doc/nightly/html/classvtkAngleWidget.html) | Interaction primitive, not an anatomical model. This feature uses native Qt graphics for independent two-dimensional review. |
| [Automated CPAK](https://github.com/pitt-cic/Automated-CPAK-Measurement) | MIT code candidate with training/export infrastructure; usable pretrained weights were not verified here. |
| [2026 Scientific Reports approach](https://www.nature.com/articles/s41598-026-49750-2) | Promising publication; a downloadable executable model was not established. Its reported accuracy is not SGR/AI-PACS accuracy. |
| [ImageBiopsy LAMA](https://www.imagebiopsy.com/use-cases/lama) | Commercial comparison target; no locally reusable weights were verified. |

## Input and mathematical contract

Input is one complete upright standing AP bilateral hip-to-ankle DX/CR DICOM.
An acquisition-system composite can be used after review. Three-exposure
stitching is not implemented. Positioning and stitching require independent
evaluation; see [radiographic stitching research](https://pmc.ncbi.nlm.nih.gov/articles/PMC11194212/).

The operator confirms patient right on image left. Horizontal flip clears points
and review state. Each leg has eight editable points: hip center, shared knee
center, lateral/medial distal femoral points, lateral/medial tibial plateau
points and lateral/medial ankle joint points. Ankle center is the mean of its
endpoints. All 16 points can alternatively be placed manually.

`geometry.py` uses image x/y coordinates with positive y downward and applies
row/column spacing before angles. Let H, K and A be hip, knee and ankle centers.
HKA is atan2(cross(K-H,A-K), dot(K-H,A-K)), multiplied by +1 for right and -1 for
left. Absolute dot products are not used, preserving obtuse joint angles.

| Result | Implemented convention |
|---|---|
| HKA | Zero neutral, negative varus, positive valgus; both mechanical axes use the shared knee center. |
| mLDFA | Proximal femoral mechanical vector versus laterally directed distal femoral joint line. |
| MPTA | Distal tibial mechanical vector versus medially directed plateau line. |
| JLCA | Unsigned acute convergence magnitude between femoral and tibial joint lines. |
| LDTA | Proximal tibial mechanical vector versus laterally directed ankle joint line. |
| aHKA | MPTA minus mLDFA. |
| JLO | MPTA plus mLDFA; arithmetic CPAK joint-line obliquity, not a floor-referenced angle. |
| MAD | Perpendicular knee distance from hip-to-ankle line; positive medial, negative lateral. |
| Femoral length | Hip center to distal femoral joint-line midpoint. |
| Tibial length | Plateau midpoint to ankle center. |
| Whole-limb length and difference | Direct projected hip-to-ankle distance; difference is right minus left. Whole length is not the sum of bone lengths. |

Interpret alongside [radiological assessment of lower-limb alignment](https://pmc.ncbi.nlm.nih.gov/articles/PMC8246117/).
No normal-range diagnosis, surgical correction plan, torsion, sagittal deformity,
FVA or CPAK classification is generated. The downloaded diaphyseal model is
reserved and unused; shaft segmentation is not an exposed capability.

Lengths use millimeters only with verified patient-plane calibration. Per the
[DICOM calibration distinction](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_10.7.html),
PixelSpacing with GEOMETRY/FIDUCIAL calibration is recognized; detector spacing
alone is insufficient. Otherwise angles use available pixel aspect and lengths
remain native pixels. The operator can enter independently verified row/column
mm per pixel; automated marker detection is not implemented. Rotation, flexion,
loading and magnification remain acquisition limitations. Detector confidence
does not establish point accuracy.

## Workflow and implementation

Open DX/CR in Eagle Eye, choose **Alignment View | Hip-Knee-Ankle**, assign the
**Primary alignment series**, then select its complete image. Study and selected
SeriesInstanceUID are rechecked before decoding, including files chosen through
Open DICOM. Changing primary series clears active points, image and report.
Confirm acquisition/orientation and run **Suggest landmarks with AI**. A draft
PDF is generated automatically after valid point extraction. Zoom and inspect
each joint, drag corrections and verify scale. Values update on release. Check
review and use **Generate reviewed PDF report** to regenerate after corrections.
**Open PDF** and **Save PDF copy** follow the existing Brain result workflow.
Every point, orientation, scale or report-text edit invalidates the active PDF.

The study-bound service rejects mismatched study identity, color, multiframe and
oversized input. Padding, modality transform and MONOCHROME1 inversion are handled
locally. Filesystem reads, decoding, hashing, inference and export run off the
Qt GUI thread. An owned subprocess isolates inference; cancellation and disposal
discard late results. The canvas owns its pixels, without modifying Fast Viewer
or VTK sessions. No patient data are sent to model providers.

Reports use the existing Brain paged PDF writer with an Alignment heading;
Brain's default heading remains unchanged. The same identity line, footer,
page numbering, typography and printable-page overflow check apply. Versioned
private study folders contain report.pdf, report.html and report.json with point
snapshots, original AI points, source hash, DICOM identity, selected series/image,
calibration, values, JLO and review status. Whole-result publication is atomic;
PDF-copy export reuses Brain's atomic exporter. Neither a draft nor a landmark
review is represented as a signed clinical report. PACS submission is not added.

### Report structure and source rationale

The [ACR communication practice parameter](https://gravitas.acr.org/PPTS/GetDocumentView?docId=74)
informs the separation of identity/examination, clinical indication, technique,
comparison, findings and impression. The interface supplies optional clinician
text fields; absent context is explicitly marked Not provided, not invented.
The core/advanced split below is an AI-PACS report design, not a universal
mandatory three-page alignment standard.

1. **Core measurements:** HKA, MAD, mLDFA, MPTA, unsigned JLCA, projected whole-leg
   length and right-minus-left difference. A full-length annotated image sits
   beside the bilateral table, scale explanation and clinician impression.
2. **Advanced measurements:** LDTA, aHKA, JLO and femoral/tibial lengths, with
   enlarged bilateral knee evidence. aHKA/JLO follow the arithmetic definitions
   in [MacDessi et al., CPAK (2021)](https://doi.org/10.1302/0301-620X.103B2.BJJ-2020-1050.R1).
   No automatic phenotype, age-specific normality or surgical target is assigned.
3. **Evidence and methodology:** bilateral hip and ankle close-ups, numbered
   point legend, mechanical/joint-line descriptions, limitations and references.

All pages are rendered from the same immutable pixel/point snapshot. Point labels
R1-R8/L1-L8 correspond to the documented landmark order. Colors identify laterality,
not abnormality. Illustrations in the demonstration PDF are synthetic, not patient
images. The actual report uses the selected radiograph.

## Models, licenses and packaging

- Code revision: `64b292e6398803082e0bd7535774efa2792c6a4b`.
- [Weight repository](https://huggingface.co/samador7/sgr-lnd-det-v1), revision
  `1e1edf999a0e51b1e47e4bfc19de6753ee5ae026`.
- Code: Apache-2.0, attribution preserved in `vendor/LICENSE` and `vendor/NOTICE`.
  Weights: CC BY-NC-SA 4.0 according to the model card. Per user instruction,
  these terms do not block authorized local implementation/inference. Commercial
  redistribution rights remain unresolved; no purchase or permission is claimed.
- Portable runtime: Python 3.13.5, torch 2.8.0+cpu, torchvision 0.23.0+cpu,
  NumPy 2.2.6, SimpleITK 2.5.2. The app environment is unchanged.
- Five checkpoints total about 866 MB, plus several GB of portable dependencies.
  Checkpoint hashes are pinned in the preparation tool. The current sealed
  manifest covers 16,887 files.
- Adapted architectures remove pretrained-backbone downloads and upstream TLS
  overrides. Loading uses `weights_only=True`; inference runs locally on CPU.

Preparation commands from the repository root:

```powershell
.\.venv\Scripts\python.exe tools/eagle_eye/prepare_alignment.py --install-runtime
.\.venv\Scripts\python.exe tools/eagle_eye/prepare_alignment.py --download
.\.venv\Scripts\python.exe tools/eagle_eye/prepare_alignment.py --seal
```

Source assets default to `generated-files/eagle-eye/alignment`;
`AIPACS_ALIGNMENT_BUNDLE` selects another sealed bundle. Existing Advanced MPR
owns `advanced_mpr/eagle_eye/alignment`: this is not a new runtime module,
configuration family or installer component. Standard/ARM profiles exclude
Eagle Eye model payloads. Staging copies manifest-listed files, excluding
research downloads, preparation environments and private patient outputs.
Distribution requires model-bound offline-inference, live-GUI and rights-review
acceptance. Local inference does not require that receipt. No real distribution
receipt has been issued and no release build was performed.

## Verification

Relative-length amendment (2026-09-15): UI and PDF include projected length
discrepancy as `100 * abs(R - L) / max(R, L)`, plus the shorter side. This is an
explicit product reporting convention, not a new clinical threshold. Lengths
use the hip-center-to-ankle-center definition and pixel aspect before taking
the ratio, including when absolute lengths remain pixels. A common scale
cancels; unequal magnification, positioning and stitching errors do not.
Reference context is zero percent for equality, with no universal normal cutoff.
JSON format 4 preserves the percentage, side and formula. Existing absolute
lengths and signed R-minus-L difference remain available. The 32-test focused
selection passed, including scale invariance, anisotropic spacing, mirrored
laterality and edit/recalculation checks. All three updated private PDF pages
and the synthetic offscreen widget were visually inspected. Mirrors: 465 pairs
match. Fresh-source live GUI acceptance remains pending.

Reference-context amendment (2026-09-14): the native measurement table and all
PDF measurement rows now share `references.py`. Adult mLDFA/MPTA (85-90 degrees),
JLCA (0-2 degrees), and LDTA (86-92 degrees) include source identifiers. HKA
neutral and CPAK bands are explicitly classifications, not surgical targets.
MAD's published 8 +/- 7 mm medial summary is not a 95% reference interval and
cannot be compared with uncalibrated pixel measurements. Bone lengths have no
universal range independent of age/stature; LLD has no universal normal cutoff.
Known children do not receive adult numeric reference text. Unknown age is
marked as unverified applicability. The versioned JSON preserves reference
definitions and sources; no automatic abnormality flags are introduced.
The focused geometry, widget, PDF and reference selection passed 29 tests.
The updated three-page private PDF was rendered for visual inspection. Fresh
source live GUI acceptance remains pending; offscreen checks do not replace it.

PDF/series workflow amendment (2026-09-14): 87 focused and adjacent guards passed,
including Brain PDF furniture/export regression coverage. The three-page synthetic
PDF was rendered with Poppler and every page visually inspected. Guards check
series mismatch rejection, series-change invalidation, automatic draft generation,
PDF pages/identity/images, JSON values, calibration and partial-publication failure.
The current source process predates these changes; test-control ping and action
discovery succeeded but are not live acceptance of the new code. A human fresh
source launch/sign-in was requested. That live gate remains pending.

- Portable pretrained hip/knee/ankle models produced finite synthetic forward
  outputs, and the ROI checkpoint loaded successfully.
- One user-selected local DX series was matched by patient/study/series identity
  before decoding. Full service/subprocess inference completed in 52.9 seconds
  and returned 16 valid in-bounds points. This establishes execution, not
  independently measured anatomical accuracy. Private artifacts remain in User
  Data; this document contains no patient identifiers, images or findings.
- Final focused selection: **155 passed**, exit 0, covering alignment, workspace
  entry, adjacent Brain, alignment staging, distribution profiles and runtime.
- Mirror synchronization completed with no drift; all 462 mirrored pairs match.
  New Python files parsed and English/document formatting checks passed.
- A single-leg uncalibrated-length guard failed before correction (scaled
  lengths mislabeled pixels) and passes afterward. Bilateral calculations were
  already protected; both public entry points now retain native pixel lengths.
- Earlier release-parity selection: 167 passed and one unrelated stale-stage
  config parity failure (`echomind_settings.json`, `printing_config.json`).
  Generated build output was not changed to hide it.
- Full builder/runtime attempt timed out in the existing codec test's pre-build
  gate while running `git fetch`; it is not a suite pass.
- Synthetic offscreen UI layout was inspected. Fresh-source affected-workflow
  live GUI, physician point review and clean-machine installer acceptance remain
  pending. Model quality cannot be inferred from passing software tests.

Guards: `tests/code/ai_imaging/test_eagle_eye_alignment.py`,
`tests/code/builder/test_eagle_eye_alignment_payload.py`, and Eagle Eye cases in
`tests/code/builder/test_distribution_profiles.py`.
