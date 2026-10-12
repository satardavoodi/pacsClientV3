# B81: Existing geometry reused in a bilateral development pilot

## Objective and identity

Completed 2026-10-07. Research evaluation only, no fitting or deployment. Test the
B80 reuse proposal with actual detector candidates and existing pure 3D Cursor
geometry. This is a CC bilateral pilot, not the complete CC/MLO matching workflow.
No live workstation or Razi service change. Owner requested execution after B80.

Protected artifacts: `C:/AI-PACS-Datasets/breast-review/point-review-20261003/`
and Linux candidate root, directory `b81-anatomy-development-20261007`.
Windows staging: `D:/Enhanced_Mammo_B81` on wina100. Scripts: stage.py, infer.py,
compare.py, verify.py, and copied engine modules. Receipts: protocol.json,
staging.json, inference.json, results.json, verification.json. Private manifests,
features, pixel cache and review montage stay outside the repository.

## Cohort and preprocessing

VinDr publisher TRAIN: 32 studies with CC reference boxes and 32 studies with
explicit-normal CC pairs, selected by SHA256(`B81:` + study identifier) ordering
within strata among complete available bilateral CC pairs. 64 studies,128 images:
32 boxed-positive images with34 unique boxes,83 explicit BI-RADS1/No Finding images,
13 unresolved images. Zero invalid-box images. All128 have pixel spacing. No box
does not imply normal; unresolved images are not negative endpoints. BI-RADS2
reference omissions remain a source limitation.

Study and image identifier overlap with B76 TEST: zero. Patient-level linkage,
pixel duplicates and historical detector training exposure are unverified. This
is enriched development data, not an independent screening performance estimate.
No model or threshold was fitted; the protocol recorded score0.4, area0.002,
NCC cutoffs0.85/0.90/0.95 and IoU0.3 before execution.

Reused the audited Razi DICOM-to-uint8 function and antialiased512 resize from B76.
Spacing is transformed for the resized image, using PixelSpacing or, if absent,
ImagerPixelSpacing. The latter is detector-plane spacing, not guaranteed tissue
scale. VOI processing emitted the existing float-input warning; no decode failed.
Native-resolution calcification morphology is outside this coarse context pilot.

## Implementation

Copied unchanged `geometry.py`, `nipple_detect.py`, `pnl_normalization.py` from
`modules/ai_imaging/ai_module_ui/cursor_3d/` into the isolated research engine.
Module SHA256 values are recorded in results.json. Used the existing mask/nipple
functions with largest-component cleanup and image-derived chest-wall orientation.
Canonicalize both breasts to chest wall left. Construct `MammogramGeometry` with
physical pixel spacing and the CC tissue-boundary-to-nipple reference distance.
Automatic geometry available for126/128 images; no manual reference landmarks.

For identical candidate lists, compare:

1. Breast-bounding-rectangle relative position (simple comparator).
2. Absolute physical nipple-relative depth/height using existing geometry.
3. Existing PNL depth normalization; scale nipple-relative height by the PNL ratio.
4. PNL with another study as sham control.

Target patch size is scaled consistently with each coordinate mapping. Search
within40 target512 pixels around the mapped center, require80% tissue coverage and
nonflat patches, then use NCC. Missing correspondence retains the candidate. Real
pairs are strictly same-study/opposite-side. Features are saved before references
are opened by the evaluator. This reuses pure geometry, not the stored-lesion
contralateral score or its UI integration. No trained reranker exists in this run.

Fixed high-NCC suppression is a diagnostic ablation only, not an approved runtime
rule that symmetry proves normality. Current search uses a fixed pixel radius,
and nipple/PNL landmark accuracy lacks physician adjudication.

## Results

All rows below use the same128 images and threshold0.4 detector proposals. Reference
matching is one-to-one maximum-cardinality IoU0.3. False marks count only83 explicit
normal images. Paired lesion identity sets were checked, not just aggregate counts.

| Path, NCC cutoff0.85 | Matched /34 | Normal marks | Reduction | Baseline lesion identities lost |
|---|---:|---:|---:|---:|
| No comparison | 20 | 127 | reference | 0 |
| Simple relative position | 20 | 119 | 6.30% | 0 |
| Absolute nipple-relative geometry | 20 | 122 | 3.94% | 0 |
| PNL-scaled geometry | 20 | 121 | 4.72% | 0 |
| Different-study PNL control | 20 | 125 | 1.57% | 0 |

PNL removes14 total proposals, of which6 are on explicit normal images; do not call
the other8 false positives without adjudication. There are230 valid actual-pair
candidate comparisons versus212 sham comparisons. At0.90, PNL removes no normal
marks and retains20 matches; at0.95 it removes no proposals. Simple comparison at
0.90 removes one normal mark. Full prespecified grid is in results.json.

Conditional study-bootstrap2000 draws: PNL normal-mark reduction95% interval
0.75-10.71%; its difference versus the simple comparator is -4.03 to0.00 percentage
points. Small enriched development sample and multiple diagnostic comparisons
preclude a general superiority claim. This is not directly comparable to B79's
different TEST cohort and four-view sample.

## Verification, resources and limitations

Seven checks passed: identical textured patch for each of three mappings, missing
partner, out-of-bounds patch, flat patch, and all actual pairs same study. Initial
synthetic identity fixture placed the box anterior to its borrowed nipple; corrected
the fixture to a defined synthetic anatomy before passing all checks. Three existing
IoU assignment guards also executed. No runtime bug fix or GUI acceptance claimed.

Four high-NCC pairs were rendered privately and visually inspected. They concentrate
near the nipple/retroareolar region. This is a biased spot-check, not lesion-level
correspondence ground truth or proof of broader parenchymal registration accuracy.

Staging40.14s on wina100; FCOS inference3.27s for128 images on A10040GB,
FP32 torch2.11.0+cu130/torchvision0.26.0+cu130, peak allocated195829248 bytes.
Geometry/feature/evaluation script1.89s, excluding DICOM decode and detector.
No total Razi CPU latency claim. GPU had12147MiB free and0% utilization before run.
Checkpoint SHA256:
`9f8746666dccb5e22840a8bfdcb22b9eacb1e3a4b31b61b6b2ec6cd005679901`.
Detector source SHA256:
`aace508a4264f76b79a4848b02a3bf60674a6d2550b226f12e85ebb4bed0bd83`.
Training/optimizer/checkpoint updates: not applicable, none performed.

## Decision and next action

Reuse is technically feasible but anatomical coordinates plus raw-intensity NCC
do not improve over the simple comparator here. Do not deploy or invest in more
NCC cutoff tuning. Retain geometry as a search prior, not a normality classifier.
The next discriminating experiment is a study-separated learned candidate verifier
with local morphology versus local plus bilateral patches and a sham arm. Before
fitting, build a larger TRAIN candidate cohort and review landmark/correspondence
failures; annotate uncertain correspondence rather than assuming mapped tissue is
the same structure. Keep missing-view fallback and separately evaluate CC/MLO once
pectoral references can be obtained reliably. No claim that anatomy-aware learned
comparison has been tested or rejected by this pilot.
