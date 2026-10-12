# B74: Razi classifier replay and corrected legacy diagnostic

## Objective and identity

Date: 2026-10-07. Requested comparison on the existing B72 TEST cohort. No fitting,
threshold selection, deployment or modification to the clinical server.
Copied Razi October 4 source from B73 was imported without edits on Windows A100.
All 14 model assets used here match the Razi hashes recorded in B73.
Protected artifacts: `C:/AI-PACS-Datasets/breast-review/point-review-20261003/b74-razi-test-20261007/`;
execution mirror: `D:/Enhanced Mammography/candidates/20261001-calcification/b74-razi-test-20261007/`.
Files: run.py, razi_worker.py, razi_XGBOOST_INFERENCE.py, corrected/, results.json,
predictions-private.json, research-mass-endpoint.json (local), deployed-log.txt (execution host).

## Cohort and input contract

Same 272 B72 reference ROIs / 138 studies: 199 Mass, 18 architectural distortion,
55 asymmetry-family. All 272 matched one-to-one to precomputed legacy feature rows
using study/image identity and all four box coordinates (absolute tolerance 1e-5,
zero relative tolerance). Zero missing or ambiguous matches. Coordinates remain private.

This is conditional classification of reference boxes, not detector or normal-tissue
screening evaluation. Legacy features contain multiview/context pairing whose
label independence is unverified; these are not freshly generated runtime features.
Razi historical exposure and patient-level independence remain unverified. B72 source
exclusions and test reuse restrictions still apply. The 55 family rows include only
40 explicit Focal Asymmetry labels; the remainder must not be relabeled as FA.

## Exact source replay: result

Weights loaded, but the copied worker's `validate_stacker_schema` raised ValueError:
`Breast classifier weights and inference feature schema do not match.`
The code expects 4 base-kind inputs; all four saved stackers require 9.
This is the unchanged worker's pre-classification gate, independent of image content.
Consequently none of the 272 intended reference regions receives a classification
through this replay path: status unavailable, accuracy undefined, not 0% accuracy.
The original worker catches this exception and can still return detector boxes.
No 272-image end-to-end detector run was performed; the single shared gate prevents
classification for this batch. This is a reproduction of inspected source/assets,
not a verified live request or proof of the in-memory state of the clinical service.

## Separate corrected legacy diagnostic

An explicitly separate run used the already-existing local feature-contract and
calibrator corrections with the same weights, precomputed matched features and saved
thresholds. It is NOT deployed Razi. All probabilities finite.

| Endpoint | TP | FN | FP | TN | Recall | Specificity | Saved threshold |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mass | 191 | 8 | 39 | 34 | 95.98% | 46.58% | 0.35 |
| Explicit Focal Asymmetry | 32 | 8 | 37 | 195 | 80.00% | 84.05% | 0.30 |

39 regions exceed both Mass and FA thresholds: this multilabel classifier does not
force a unique lesion type. Mass recall alone therefore overstates typing quality.
Specificity here means rejecting Mass among other selected lesions, not recognizing
normal breasts. The incidental calcification head has TP15/FN5/FP48/TN204, but this
lesion-typing subset is unsuitable for judging the separate microcalcification pipeline.
No architectural-distortion head exists in these legacy assets.

For context, collapsing the existing B72 three-class argmax predictions into Mass
versus other gives the following fixed-three-seed means. Same ROI denominator,
different input information and decision rules; not a controlled architecture ablation.

| Research pipeline | Mass recall | Non-Mass correctly rejected as Mass |
|---|---:|---:|
| B50 target-only | 83.75% | 48.40% |
| B50 transfer | 83.25% | 47.49% |
| B50 weighted | 78.22% | 59.36% |
| B64 reference | 74.54% | 61.19% |
| B65 DINO | 52.60% | 86.76% |
| B69 EfficientNet | 77.55% | 54.79% |

No overall superiority established: models that reject more non-Mass lesions also
miss more actual Mass lesions at their existing operating rule. No paired confidence
interval or threshold-matched comparison was performed in B74.

## Environment, verification and decision

### Owner clarification: any finding rather than correct type

Recounting the saved corrected-legacy predictions using the union of the three
original positive heads at their saved thresholds gives263/272 positive reference
regions (96.69%) and9/272 with no positive head. This is conditional positive-label
coverage after supplying the correct reference box, not autonomous detection recall.
There are no normal reference regions here, so no normal-tissue false-positive rate
can be calculated. A finding label is not a histological malignancy label.
The research classifiers force a choice among three lesion types and have no normal
class; their automatic assignment of a lesion type to every supplied ROI is not
100% detection sensitivity. Neither B72 nor B74 measured class-agnostic full-image
Razi-versus-research localization. That comparison requires predicted boxes matched
to reference lesions on the same complete images, with false positives reported.

CPU Python3.12.3, NumPy2.0.2, sklearn1.4.2, LightGBM3.3.5, XGBoost2.1.4.
This differs from the Razi service interpreter; full dependency/runtime parity is
unverified. The observed schema mismatch is explicit Python logic and loaded model
metadata. Gate time0.84s, complete script3.39s excluding image decoding, feature
generation and detection; not mammography end-to-end latency. GPU not used.
Training, optimizer and telemetry fields not applicable. No clinical GUI acceptance.

Decision: no promotion or live fix. Source replay exposes a classification contract
failure; corrected diagnostic confirms overcalling Mass on this selected cohort.
Next bind an actual Razi response to its classification status, then qualify the
existing contract correction in an isolated complete pixel-to-result replay. For
typing improvements, use development data to reduce Mass/FA conflicts and false Mass
calls while retaining Mass recall; do not tune thresholds on this exposed TEST.
