# B57: Core, boundary, channel and radial morphology experiment

Date: 2026-10-06. Research implementation of the
[B56 hypothesis](B56_SPATIAL_MORPHOLOGY_RESEARCH_2026-10-06.md).
Completed: source extraction and 15 fixed classifier fits. No clinical deployment
or B55 feedback replacement. Execution receipts and negative result are below.

## Objective and comparators

Test whether deterministic spatial descriptors add useful information to the
existing B50 split-specific learned representation. Target remains source-annotated
Mass, architectural distortion and asymmetric-tissue family on reference ROIs.
No normal cohort, autonomous localization, malignancy or final multiview terminology.

Preserve 1,270 target rows, 624 studies and 1,150 images if source verification passes;
923 Mass, 87 AD and 260 family rows. Exact B50 train/development partitions for
seeds 17/29/43 are required. Study grouping does not establish person independence.
Previously exposed development data remain exploratory, not a final test.

Five planned arms per seed: core/boundary/channel only, radial only, joint spatial,
frozen B50 embedding with a regularized head, and embedding plus joint spatial
features with the same head. The original B50 checkpoint is separately replayed.
Compare fusion with its matched regularized embedding head, not only the original
neural head, to avoid attributing a classifier change to spatial features.

## Prospective comparison contract

The evaluator freezes logistic regression C=0.1, L-BFGS, 5,000 maximum iterations,
tolerance 1e-4, no class weighting or development search. Standardization uses
fitting rows only; inverse-study row weights give equal base study contribution.
Each split uses its own frozen B50 transfer encoder; no cross-split checkpoint
substitution and no stacker trained on in-sample probabilities. Original model
replay must match saved development probabilities within CPU tolerance 1e-5 and
retain exact argmax decisions.

Predictions use argmax. Paired bootstrap resamples whole development studies,
2,000 draws per seed, with absent-class draws excluded and reported. Repeated splits
overlap and cannot be pooled as independent patients. Report per-class recall,
precision, confusion, macro F1, log loss and Brier; undefined precision remains null.

Before evaluation, the engineering retention screen requires a mean macro-F1 gain
of at least 2 percentage points and AD recall gain of at least 5 points over the
matched embedding head, with mean Mass/family recall decreases no larger than
2 points each. These are bounded research choices, not medical standards.
Intervals crossing zero leave an improvement unproven; no clinical promotion.

## Implementation interpretation

The prototype has 20 core/boundary/channel descriptors and 12 radial descriptors.
Source-derived local/context crops are analyzed with a maximum side of 384; smaller
crops are not enlarged. This is bounded-resolution analysis, not a claim to retain
every native pixel. Relative local/context intensity normalization, candidate-core
growth, convex-hull channel proxies, boundary contrast and multiscale Hessian
orientation are not clinical segmentation labels.

A smoothed central maximum anchors the prototype and may follow a vessel or clip.
Low-signal regions inside a candidate convex hull are not verified fat. Boundary
support is partly conditioned on intensity-derived contour selection. Hessian
orientation measures can respond to non-spicular structures; a radial score is not
proof of architectural distortion. Synthetic checks assess implementation behavior,
not medical accuracy or full photometric invariance.

## Protected evidence and qualification boundary

Artifacts belong under `P/b57-spatial-morphology-20261006` and the matching `R`
research directory. Source images, source-row references and per-case predictions
remain outside repository documentation. No review browser or server is modified.
Record source identity, synthetic guards, extraction failures/timing, fitting and
reload checks, results and decision here after the corresponding work completes.

## Completed extraction and evaluation

All 1,150 source images passed byte-hash verification; all 1,270 ROIs produced 32
finite, nonconstant features with zero failures, missing rows or flat-input cases.
The mandatory identity gate passed exact source/geometry/row/split bindings before
fitting. Feature serialization and all 15 fitted model reloads passed exact checks.
All five arms converged on all three seeds. The reviewer independently verified
the final artifacts and unchanged extractor protocol.

| Arm | Mean training macro F1 | Mean development macro F1 | Mass recall | AD recall | Family recall |
|---|---:|---:|---:|---:|---:|
| Core/boundary/channel | 45.37% | 35.53% | 96.12% | 0.00% | 14.22% |
| Radial | 31.86% | 29.31% | 99.09% | 0.00% | 0.95% |
| Joint spatial | 50.98% | 44.96% | 94.62% | 14.58% | 19.90% |
| Matched embedding head | 99.97% | 51.20% | 89.15% | 21.25% | 35.93% |
| Embedding plus spatial | 99.97% | 51.52% | 88.44% | 22.92% | 35.65% |
| Original B50 transfer | 90.29% | 52.12% | 84.03% | 22.50% | 50.30% |

Spatial fusion improves macro F1 by only 0.325 percentage points and AD recall by
1.667 points over its matched head, while Mass declines 0.712 points and family
declines 0.285 points. It fails the predeclared retention screen. Mean AD precision
falls from 59.26% to 58.52%, family precision from 42.06% to 40.70%; Mass precision
is effectively unchanged at 82.38/82.40%. Undefined precision in individual raw
results stays null; these percentages are not normal-study specificity.

Paired macro-F1 delta 95% study-bootstrap intervals all include zero:
seed17 [-1.60,+0.40], seed29 [-2.75,+6.45], seed43 [-1.95,+3.75] percentage points.
Fusion loses two net correct Mass rows on seed17; seed29 gains one AD row while
losing one Mass and one family row; seed43 loses one net Mass and gains one family
row. Overlapping split occurrences are not independent people or a pooled score.

The large training/development gap in both embedding arms shows that fitting-case
success cannot establish generalization. The hand-crafted-only arms also show weak
minority discrimination; their poor training performance under this fixed classifier
does not establish that all spatial representations are ineffective. This experiment
tests these 32 proxies and one regularized head, not the full clinical hypothesis.

### Cost and evidence binding

Source staging wall time was 482.28 seconds; accumulated decode/extraction time
439.84 seconds, median 0.359 and p95 0.594 seconds per image. The three GPU embedding
passes took approximately 0.760/0.487/0.462 seconds; GPU peak memory was not measured.
All 15 classifier fits/reload checks together took 1.09 seconds on two CPU threads.
These component timings exclude complete clinical serving and Razi host qualification.

- Features SHA256: `31e9ec24440323ba285a85ebb8787b4fc1fa484001357e2e0779d707956ecb2f`.
- Results SHA256: `7a19c2b58355a71baa9ac63436f1ff4b858a1ce879e1a903d27ebea63e57963e`.
- Bootstrap SHA256: `8d20ebb834dad07adc5fa46019e22850338880526ac77b95efee09e9d39b933f`.
- Protected receipts: `receipt.json`, `identity-gate.json`, `evaluation-protocol.json`,
  `prefit-backend-amendment.json`, `results.json`, `aggregate-summary.json`,
  `paired-bootstrap.json`, `reviewer-receipt.json`, and private predictions/models.

### Decision and next step

Reject this fixed spatial-feature fusion as a replacement; preserve B50. Do not run
an uncontrolled threshold/feature search on the same development groups to rescue
the result. Preserve this failure and its source-derived features for explanation.
Prioritize the already prepared B55 physician reference review to distinguish actual
Mass/AD/family disagreement from mislabeled or mixed source appearances. Any future
core/contour method needs fitting-only evidence that its extracted body matches the
intended lesion, especially with clips, obscured boundaries and multiple bright areas.
B54's native-context384 and eligible source-AD supervision remain separate bounded
experiments; neither was tested or proved by B57. No production or calcium changes.

## Prefit findings

- Initial normalized radial alignment also responded to a smooth synthetic blob.
  The extractor was corrected using ridge strength/eigenvalue structure before
  clinical-image extraction or development fitting. Hard angular-bin activity also
  showed numerical ties under affine intensity changes; continuous weighted coverage
  replaced that operation before source extraction. Synthetic debugging did not use
  development metrics; final code and protocol hashes bind the run.
- Initial CPU replay did not satisfy the prespecified B50 probability tolerance.
  The failed evaluator/protocol was archived. Repeating the original deterministic
  CUDA development-subset batch16 path with CPU softmax reproduced all three seeds
  exactly: maximum probability difference zero, no changed argmax and unchanged
  checkpoint hashes. This permits the matched experiment; it does not qualify CPU
  equivalence. A separate seed17 CPU development-subset replay measured maximum
  probability difference 0.00536209 with zero argmax changes, still failing the
  original tolerance. The initial failed all-row attempt did not record its delta;
  the numerical mechanism is not established by the GPU replay alone.
- Independent review identified that matching target vectors alone cannot prove
  row identity. Require exact row sequence, source/row/split hashes and extraction
  receipt checks before a feature matrix can be consumed by the evaluator.

Independent synthetic visualization was inspected by the reviewer and primary
agent: smooth/interrupted cores, radial/parallel lines, core plus radial lines and
a saddle control. Angular persistence can remain high with very weak ridge signal;
interpret it jointly with magnitude, not as an anatomical finding. The image and
feature receipt are protected research artifacts, without patient images.

The frozen extractor protocol uses source slope/intercept and photometric polarity,
then separate valid-pixel 5th/95th percentile normalization for local and 2x context
crops. This differs intentionally from B50's image-input normalization, as an added
feature branch. The mask excludes DICOM padding, not all air/skin. No physical
millimetre scale is asserted. Final extractor SHA256:
`ad727cfa018f759359fe8e6aa467d5bfc94dd3fc2bf474719857d4d5fc1e44df`.
The synthetic suite passes polarity, invalid-pixel substitution and affine-signal
controls; the reported pure-radial scale perturbation mean feature difference is
0.101. Do not describe this as exact scale or nonlinear photometric invariance.
