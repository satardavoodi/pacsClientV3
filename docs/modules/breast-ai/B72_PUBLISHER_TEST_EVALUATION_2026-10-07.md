# B72: Publisher TEST evaluation of compatible lesion classifiers

Date: 2026-10-07. User explicitly requests testing all candidates on official TEST.
Task: classify a supplied reference ROI as Mass, AD or asymmetry family. No fitting,
threshold calibration, fusion or best-seed selection. B70 four-shape classifier and
MONAI density model have incompatible output targets and are not ranked here.

## Cohort and readiness

VinDr source annotation SHA256 remains
59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc.
Apply the existing B50 label/geometry rules to publisher split=test. This yields
272 available eligible reference ROIs from138 studies/253 images:199Mass,18AD,
55asymmetry-family. Ten AD studies. Other candidate rows:53 missing image paths,
6 global-asymmetry review-only,5 bounds-review,2 mixed-family review. Preserve
excluded records privately. This is an available-source subset, not the complete
publisher test cohort; missingness may bias results. No exclusion uses model scores.

Study and image ID intersection with B50 TRAIN is asserted empty before staging.
Exact source-file hash disjointness is checked before inference. Patient linkage,
near duplicates, older Razi training and broad pretraining exposure remain unproven.
Therefore call this publisher-TEST evaluation, not universally proven unseen data.
Absence of a finding box does not create normal truth. No normal-reference ROIs.

## Frozen model and input contract

Six pipelines, each existing final checkpoints seeds17/29/43 (18 evaluations):
B50 target-only, B50 CBIS-transfer, B50 transfer-weighted, B64 context224 reference,
B65 DINO and B69 EfficientNet. No new ensemble or selected best seed. Protocol binds
all checkpoint hashes before inference. Mean and individual seed results reported.
B50 and B64 have different fitting cohorts; this compares delivered pipelines rather
than isolating architectural effects. Original production FCOS not substituted for
these reference-ROI classifiers; no original Razi accuracy claim.

Reuse full-image photometry and local/context224 recipe: padding-aware float32
rescale, MONOCHROME1 correction, stride4 percentile1/99 normalization, original
unclipped reference ROI and2xcontext, aspect-fit bilinear antialias/replicate padding.
Inputs staged on Windows A100 then transferred to Linux research storage. Strict
checkpoint loading, finite probabilities and input serialization/hash checks required.
No decoder or task label changes selected from test scores.

## Metrics and interpretation

Accuracy, macro-F1, each class recall, confusion matrix and constant-Mass baseline.
Inference failures cannot be silently removed. Model selection on this newly exposed
benchmark consumes its future independence; subsequent tuning must disclose reuse
and obtain new independent confirmation. Small AD support limits precision. These
metrics exclude detector misses and do not measure screening sensitivity.

## Results

All18 evaluations completed with strict loads and finite probabilities; no fitting.
All input serialization, study/image ID and exact source-file hash checks passed.
Staging took116.50seconds; peak inference VRAM/full Razi CPU latency not recorded.
Source-derived photometry is identical across pipelines. Percentages below are
means of three fixed seed models on the same272 regions (not816 unique lesions).

| Pipeline | Accuracy | Macro-F1 | Mass recall | AD recall | Family recall |
|---|---:|---:|---:|---:|---:|
| B50 target only | 70.71 | 43.19 | 83.75 | 3.70 | 45.45 |
| B50 CBIS transfer | 70.83 | 45.49 | 83.25 | 7.41 | 46.67 |
| B50 weighted transfer | 69.49 | 49.06 | 78.22 | 16.67 | 55.15 |
| B64 matched reference | 67.28 | 46.44 | 74.54 | 11.11 | 59.39 |
| B65 DINO | 56.25 | 46.65 | 52.60 | 33.33 | 76.97 |
| B69 EfficientNet | 68.26 | 48.45 | 77.55 | 24.07 | 49.09 |

Constant Mass accuracy73.16%, with zero minority recall. Highest raw accuracy does
not make B50 transfer adequate; AD remains very weak. B50 weighted has the highest
observed macro-F1 but its paired difference versus B64 has95% interval[-0.81,+6.51]
points, not confirmed superiority. EfficientNet macro delta interval[-2.79,+6.73];
DINO[-7.79,+6.57]. Shared study-weight bootstrap2000 draws used, with zero-support
draws skipped; valid count in uncertainty.json. No multiple-comparison adjustment,
patient independence or population-wide precision claim. AD has only18regions.

B64 accuracy moved from70.00% development to67.28% publisher TEST; these are different
cohorts, not a paired degradation estimate. DINO again trades Mass for minority recall.
None demonstrates uniformly good three-class typing or meets the existing combination
of macro gain and class retention. Do not promote the numerically highest row from
this table as clinically qualified. Original Razi production performance unmeasured.

Decision: retain production unchanged. Use this benchmark as a disclosed, now-exposed
external-to-fitting check. Next diagnose shared errors on development examples and
audit label/input/rare-class supervision; do not tune on this TEST. A future candidate
must report test reuse and obtain a new independent cohort before clinical claims.
B70 shape and BI-RADS require separate task-matched TEST preparation; no results for
them are implied by the18 evaluations here.

## Artifacts

P/R roots from current-state guide: b72-stage.py, b72-evaluate.py,
b72-vindr-test-20261007 and b72-test-evaluation-20261007. Staging also resides under
the established Windows A100 candidate root. Private indices, predictions and source
geometry remain outside repository. No runtime integration or clinical deployment.
