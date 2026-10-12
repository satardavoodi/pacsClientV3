# B79: Deterministic bilateral feasibility experiment

## Objective and scope

Owner requests an actual test of the bilateral idea. Completed2026-10-07 using B76
saved full-image proposals. This is a cheap deterministic feasibility screen before
the TRAIN-fitted verifier proposed in B78, not execution of that entire plan.
No training, calibration, new neural network or clinical integration. TEST is already
exposed; thresholds were written before feature extraction but this remains exploratory.

Protected artifacts: point-review local root and Linux candidate root,
`b79-bilateral-pilot-20261007`: run.py, verify.py, protocol.json, views-private.csv,
features-private.json, results.json, verification.json. Metadata came from the native
VinDr breast-level CSV and includes only study/image identity, laterality and view;
finding labels are absent from the pairing input.

## Method and cohort

Same3372 full-image pixel cache as B76,843 study quartets. Select candidates using
fixed original area0.002 rule and score>=0.4. Infer approximate chest-wall orientation
from occupancy of the largest foreground component; normalize its bounding rectangle
to256x256. Corresponding candidate location is searched within20 pixels in the
opposite-side same-view normalized image. Measure maximum normalized cross-correlation
of the candidate intensity patch. This does not provide nipple-based or deformable
anatomical registration. Working resolution is deliberately coarse for tissue/mass
context, not a microcalcification detector.

Nonflat texture, adequate mask coverage and bounded patch size required. Missing or
low-quality correspondence retains the original candidate.3366 image normalizations
available;5398 candidate comparisons meet checks. Same-view/side cyclic pairing with
the next sorted different study provides a sham comparator (5227 valid comparisons).
Pairing and feature extraction precede any use of reference boxes. Labels enter only
the unchanged IoU0.3 one-to-one evaluator. The diagnostic suppresses candidates above
fixed similarity cutoffs0.85/0.90/0.95; this hard suppression is not approved runtime
behavior and does not supersede B78's learned, uncertainty-aware combination proposal.

Full B76 denominator retained:362 reference boxes,2258 explicit negative images;
5 invalid-reference images remain excluded. Unknown/unboxed cases not normal targets.

## Results

| Path | Lesions matched/362 | Marks on2258 normal images | Normal-mark reduction |
|---|---:|---:|---:|
| Score0.4 baseline | 198 | 3751 | reference |
| Own contralateral, NCC>=0.85 suppressed | 197 | 3631 | 3.20% |
| Own contralateral, NCC>=0.90 suppressed | 198 | 3725 | 0.69% |
| Own contralateral, NCC>=0.95 suppressed | 198 | 3750 | 0.027% |
| Different-study control, NCC>=0.85 | 197 | 3721 | 0.80% |
| Different-study control, NCC>=0.90 | 198 | 3745 | 0.16% |

At0.85, one net matched lesion is lost (0.276 percentage points recall);120 normal
marks removed. At0.90,26 normal marks removed and matched count unchanged. Unchanged
count is not yet a verified unchanged lesion-identity set. Per-lesion identity and
physician review of removed true findings remain outstanding.

Paired study bootstrap2000 draws gives2.56-3.90% interval for normal-mark reduction
at0.85 and1.82-3.04 percentage points for the additional reduction versus sham,
using baseline normal marks as denominator. Conditional exploratory intervals do not
resolve multiple-cutoff comparison, patient linkage, reference omissions or historical
exposure. The observed same-person advantage is small; it does not meet the proposed
20% reduction target in B78. No claim of zero missed lesions or clinical qualification.

## Verification and limits

Four synthetic guards passed: identical textured patches match, absent counterpart
returns unavailable, out-of-bounds candidate returns unavailable, flat template returns
unavailable. Existing B76 matching guards reused. No application GUI pass applicable.
Feature matching plus evaluation took about2.4s after normalized-image cache creation;
this excludes DICOM decode, cache normalization and detector inference, so is not
complete CPU latency. No uncertainty interval for clinical sensitivity established.
No registration image review or CC/MLO comparator was performed. Six images without
usable normalization fall back to unchanged predictions.

## Decision and next action

Do not deploy this similarity filter. The simple own-breast comparator reduces normal
marks more than sham, but too weakly to solve the problem. This neither validates
nor rejects a trained anatomical bilateral/ipsilateral verifier. Next use TRAIN-only
predicted candidates, inspect nipple/chest-wall-aware correspondence visually, and
fit local-only versus local+bilateral rerankers with study-separated calibration.
Retain sham control, candidate recall ceiling and per-lesion retention accounting.
Keep strong local morphology and a missing-view fallback; do not treat symmetry as
proof of normality. Do not tune this prototype further on the exposed TEST to claim
independent improvement. Production remains unchanged.
