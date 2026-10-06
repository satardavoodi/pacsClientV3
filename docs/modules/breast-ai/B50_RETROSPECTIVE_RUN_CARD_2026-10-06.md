# B50: Retrospective comparator run card

Reconstructed 2026-10-06 from protected B50 protocol, results, runtime-versions,
summary, paired-bootstrap and closure receipts. This is not a new experiment or
a prospectively completed card. Detailed immutable hashes are in those receipts.

## 1. Objective and evidence identity

Source-label ROI appearance typing: Mass, AD, asymmetry family. Original Razi FCOS
is a separate comparator. B50 arms: target_only, transfer, transfer_weighted, seeds
17/29/43, plus three CBIS auxiliary source fits (12 actual fits). Protected P and R
directories: b50-transfer-20261005, b50-vindr-20261005, b50-cbis-qc-20261005.
Fresh target fitting, not exact-resume training. Checkpoints include protocol hashes.

## 2. Cohort readiness

VinDr publisher TRAIN: 1,270 ROIs, 1,150 images, 624 studies; person linkage not proven.
CBIS: 1,015 eligible QC-passed source ROIs, 553 people, historical/person test reserves
excluded. Target study-group splits fixed per seed, 5-fold construction using one
development fold per seed. Split seeds are not independent test populations.
Shape/margin source targets have explicit known masks. No derived normal negatives.
Age/site/vendor representativeness and external qualification not established.

## 3. Training configuration and telemetry

ImageNet ResNet18 shared encoder; concatenated local/context features (1024), target
linear 3-class head. Local ROI and 2x context fit224, aspect preservation, replicate
padding; ImageNet channel normalization. CBIS source 4-shape/5-margin BCE heads are
discarded before target adaptation. Frozen BatchNorm running statistics, trainable
layer4 affine/weights and head. AdamW head LR 0.001, layer4 LR 0.00001, decay 0.01,
batch8 pairs, FP32, no augmentation or scheduler. Five source and five target epochs;
final fixed epoch, not best/converged selection. Group inverse-frequency row weights;
weighted arm adds capped square-root class-group weights.

Version receipt: Python3.10.12, torch2.11.0+cu130, torchvision0.26.0+cu130,
numpy2.2.6, sklearn1.7.2. Full environment lock not recorded. Protocol and checkpoint
hashes recorded. Source JPEG and target DICOM normalization differ; no harmonized
photometry claim. Synthetic update/reload, real trainable-weight change, frozen BN,
finite gradients and exact saved-checkpoint prediction replay recorded as passing.
Transfer successful updates: 640/655/635 for seeds17/29/43. Raw epoch telemetry exists.

## 4. Metric and selection contract

Macro-F1, per-class recall/precision/AP, confusion, log loss and Brier on known source
labels. No calibrated clinical operating point. Paired group-bootstrap receipts exist;
three transfer-vs-target macro-F1 improvement intervals include zero. Development was
reused for research selection, so these are not final clinical estimates.

## 5. Results and interpretation

Target-only macro-F1 46.49%; unweighted transfer 52.12%. Transfer recall:
Mass84.03%, AD22.50%, family50.30%. Weighted transfer provides negligible macro gain
while losing Mass recall. Retain unweighted transfer as research control, not deployment
qualification. High fitting performance relative to development suggests generalization
and reference/coverage constraints; does not prove a single cause or sufficient epochs.

## 6. Resources

Actual entire B50 run: 93.54 seconds, peak allocated GPU605,842,432 bytes. Transfer
fit receipts approximately7.4-7.6 seconds each, excluding reused input preparation.
These timings are A100 research execution, not Razi CPU/end-to-end latency. Closure
records process exit0, unchanged readiness inputs and no remaining owned training jobs.

## 7. Decision and next experiment

Retain B50 and all historical failed comparators. Follow B62 and B64 for the distinct
native-context experiment; do not call another identical attribute-pretraining run new.

## 8. Missing evidence and qualification

No independent normal/detection evaluation, whole-pipeline latency, current attribute
output validation, calibrated BI-RADS prediction, full environment lock or clinical
qualification. Physician review is fitting-exposed and separate from source truth.
This card adds documentation only; no GUI or runtime changes.
