# B47: Local VinDr and CBIS morphology readiness audit

Date: 2026-10-05. Status: metadata and bounded pixel audit completed; no fit,
deployment or accuracy improvement claimed. Continues [B46](B46_TASK_DEFINITION_AND_MASS_BIAS_2026-10-05.md).

## Objective and evidence

Determine whether the existing Windows A100 datasets support the owner's corrected
task: localize a finding, characterize mass-like versus asymmetric-tissue-like
appearance with uncertainty, then use view evidence for final terminology.
The original label is preserved; a folder named mass is not a binary reference standard.

Verified host: WIN-I5E5QM7V2R2. Protected receipts are under
`C:/AI-PACS-Datasets/breast-review/point-review-20261003/cbis-morphology-audit-20261005`:
`aggregate.json`, `candidate-counts-aggregate.json`, `vindr-source-recheck.json`,
`train-readiness-manifest-private.json`, and `pixel-geometry-private.json`.
Only aggregates enter this report. Training configuration, gradients, checkpoints,
inference latency and GUI acceptance are not applicable to this audit.

## Located sources and cohort

| Dataset on Windows A100 | Verified TRAIN support | Useful supervision | Limitation |
|---|---|---|---|
| VinDr: `F:/Aisan-Rahimi-part2/MammoDicomData/original data` | 16,391 annotation rows, 16,000 image records, 4,000 studies | Finding boxes, view/laterality, density, Mass and asymmetry-family labels | No shape or margin columns; this was a metadata recheck, not another complete pixel audit |
| CBIS: `D:/AisanRahimi/mamography/mamographic data set/CBIS-DDSM/archive` | Original mass TRAIN: 1,318 rows, 691 people, 1,231 unique full images | Full images, crops, ROI masks, shape and margin descriptors | Digitized-film domain; local JPEG derivatives and legacy vocabulary require care |

VinDr inclusive annotation counts are 989 Mass, 216 Focal Asymmetry and 77
Asymmetry; these include coannotations and are not mutually exclusive. The prior
eligible typing cohort remains 1,189 rows, 1,083 images and 594 study groups.
Unboxed tissue is not exhaustive normal truth. Study grouping is not verified
person linkage. Existing exposed development cases are not a new independent test.

CBIS original rows partition conservatively as follows:

| Original shape group | Rows | Use |
|---|---:|---|
| Standard mass shapes, including combinations | 1,110 | Candidate morphology auxiliary supervision |
| Pure legacy asymmetry family | 39 | Review only: 19 focal asymmetric density and 20 asymmetric breast tissue |
| Distortion, lymph node, or mixed excluded descriptors | 165 | Preserve source labels; exclude from forced binary mapping |
| Unknown shape | 4 | Exclude from shape targets |

Test patient membership from both original Mass and Calcification CSVs was read
only to enforce a union reserve; test labels were not analyzed or used for tuning.
This reserves 13 mass-TRAIN people / 27 rows, including 18 standard-shape rows.
Remaining candidate morphology support is **1,092 rows / 593 people / 1,034 full
images**. The 39 legacy asymmetry rows remain review-only. All manifest entries
retain `training_ready=false` pending full geometry and historical split checks.

## Original versus modified CBIS

The modified CSV has 1,226 rows / 643 people: 92 original keys omitted, no new
keys. Shared keys have four shape and 42 margin changes, all `N/A` to empty;
other label fields are unchanged. All paths were rewritten and `bbx` was added.
This is not evidence of semantic relabeling. Omitted descriptors: OVAL 41,
LOBULATED 23, IRREGULAR 14, ROUND 9, ASYMMETRIC_BREAST_TISSUE 3,
FOCAL_ASYMMETRIC_DENSITY 1, ARCHITECTURAL_DISTORTION 1.
Do not silently discard these rows or assume why the derivative omitted them.

All 1,318 original full/crop/mask triplets resolve uniquely to existing files when
series identity **and SeriesDescription** are used. Series identity alone was
ambiguous for 1,226 rows because crop and mask share a series. The initial audit
was retained separately; the final receipt uses the corrected role resolver.

Twenty-four TRAIN triplets were decoded. All 24 mask dimensions match the full
image and indexed dimensions. Masks are JPEG with 15-18 grayscale values, not
native binary contour truth. This supports provisional region supervision, not
fine-boundary accuracy or full-cohort alignment. Full mask QC remains outstanding.

## Decision and next controlled experiment

Use the datasets for complementary purposes, not one undifferentiated training pool:

1. Complete mask/image geometry, foreground-area and overlay QC; reconcile all
   historical internal partitions with the union person reserve. Preserve original
   descriptors, provenance, known-target masks and a versioned vocabulary mapping.
2. Use eligible CBIS masks and shape/margin labels for auxiliary morphology learning.
   A compact local-plus-context encoder can learn region, shape and margin targets;
   loss terms apply only where labels are known. Do not force a clear closed border:
   obscured and indistinct margins remain valid mass appearances.
3. Adapt on VinDr digital mammograms with reviewed mass-like versus asymmetric
   appearance labels. Keep uncertain findings and separate view confirmation.
   Legacy CBIS asymmetry labels are not automatically equivalent to modern VinDr
   labels. Dense normal tissue and overlap need reviewed negatives, not missing boxes.
4. Freeze a same-architecture comparison: VinDr-only control versus CBIS morphology
   pretraining followed by identical VinDr adaptation. Use matched split, budget
   and downstream training settings. Compare Mass precision, asymmetry-family
   recall, balanced performance, calibration and uncertainty coverage. Record
   fitting/development gaps; do not use Mass recall alone as the acceptance gate.
5. Evaluate complete-image finding sensitivity and false positives per image
   separately. ROI typing does not establish >90% finding-versus-normal detection.

The next hypothesis is that explicit morphology supervision reduces Mass overcalling;
it is not established by this audit. Freeze the detailed run budget and protocol
after QC, before fitting. If transfer does not improve the matched development
tradeoff, retain the control and prioritize adjudication of persistent morphology
disagreements rather than additional blind epoch or feature-fusion sweeps.
Keep the successful calcium work and production inference unchanged.

## Source bindings and qualification

| Source | SHA256 |
|---|---|
| VinDr finding annotations | `59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc` |
| CBIS original mass TRAIN CSV | `a4bcc1c32bfd040212737e6e8c304819334abe717cfefff56431dc50ae6db723` |
| CBIS modified mass TRAIN CSV | `aedcdcbc81b9e9528f47bdc57366af581e4b88148b106d11ac9380aa65511307` |
| CBIS original image index | `c07de9bb22bf5b85d20cf54f41729a7f8c4f20d3f34a6afdc3c3e5f1c3029829` |

Dataset and clinical-definition sources were reviewed in B46:
[VinDr](https://physionet.org/content/vindr-mammo/1.0.0/) and
[CBIS publisher](https://www.cancerimagingarchive.net/collection/cbis-ddsm/).
Local counts above come from actual local receipts, not publisher totals.
No new literature performance claim is made. Fine contour validity, complete
geometry, source-to-target domain transfer, target population coverage, clinical
qualification and model/weight redistribution rights remain unestablished.
