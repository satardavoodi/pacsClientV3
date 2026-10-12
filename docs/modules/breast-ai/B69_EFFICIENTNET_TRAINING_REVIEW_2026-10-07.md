# B69: EfficientNetV2-S paired ROI training review

Reported 2026-10-07 (Asia/Tehran). Three actual fits completed; candidate rejected
for promotion. Artifact directory retains its initiation suffix 20261006. No clinical
model, detector, calcification pipeline or physician references were modified.

## 1. Objective and evidence identity

Test the B66-B68 independent typing candidate on fixed reference boxes: Mass, AD,
asymmetry family. This is not lesion detection, malignancy, focal-versus-one-view
asymmetry assessment or BI-RADS. Compare against B64's matched context224 control,
not original Razi inference. Fresh head fits with official ImageNet initialization.

Official weights downloaded by torchvision with hash checking from
https://download.pytorch.org/models/efficientnet_v2_s-dd5fe13b.pth
SHA256: dd5fe13b1d60ec15317ccc8ca158186e134d3366c3dde9cb9a4e301f2dc66c74.
Training uses lina100 /usr/bin/python3, torch 2.11.0+cu130 and torchvision
0.26.0+cu130, A100 40 GB. Full environment lock not recorded. No new dependency
installation or service interruption. Before launch GPU free memory was 12,147 MiB.

P and R (protected roots in current-state guide) contain b69-adapt.py,
b69-compare.py and b69-efficientnet-adaptation-20261006 JSON receipts. R also holds
three final checkpoints and the discarded synthetic checkpoint. Protocol binds
input/reference/split/eligible-index/script hashes; results bind checkpoint hashes.
Protocol was saved before fits. Completed result and comparison receipts copied to P.

## 2. Cohort readiness

Same B64 eligible cohort: 1,147 reference ROIs, 561 study groups, Mass834/AD79/
family234. Original seed17/29/43 group assignments unchanged; no within-split study
overlap. Patient linkage remains unproven. Train/development counts: 923/224,
939/208, 921/226. Development AD counts: 12/20/14. Whole studies with unavailable
native sources were excluded equally from both pipelines, as documented in B64.
Source references unchanged; no unresolved physician labels imported. No normal
reference class. Scanner/site/age/density subgroup results not measured in B69.
This is repeatedly exposed development data, not an independent final test.

## 3. Configuration and execution verification

Shared EfficientNetV2-S encoder on local224/context224 grayscale repeated to RGB,
ImageNet normalization. Original classifier replaced by identity; two 1280-dimensional
vectors concatenated into a fresh 2560-to3 linear head. Features stages6/7 and head
trainable; earlier stages frozen. All BatchNorm running statistics frozen, eval mode.
AdamW head LR0.001, trainable encoder LR0.00001, decay0.01, FP32, batch8 ROI pairs,
five fixed epochs, no augmentation/scheduler/accumulation. Cross entropy weighted by
inverse study ROI count, normalized in training; no class reweighting. Seeds17/29/43.
Argmax output; final epoch selected prospectively, no favorable-epoch selection.
This bounded adaptation is not an optimized EfficientNet recipe or exact reproduction
of the published multilabel paper. The control has CBIS auxiliary pretraining whereas
this candidate has ImageNet only: compare pipelines, not architecture in isolation.

Real discarded synthetic update, finite gradients, normalized outputs and exact reload
passed. Actual fits verified changed head/encoder parameters and unchanged BN buffers.
All final prediction reloads exact. Successful optimizer updates: 580/590/580.
No nonfinite failure observed. Per-epoch objectives, gradient maxima, train/development
metrics and confusion matrices are in results.json. Peak allocated CUDA memory
1,181,176,832 bytes; recorded execution124.22 seconds includes model initialization/
download after the script timer, guards, training/evaluation/checkpoint IO, excluding
input audit/loading before the timer and remote staging. Peak host RAM not recorded.

## 4. Results and selection contract

Mean of the same three development splits; percentages:

| Metric | B64 matched control | EfficientNetV2-S | Change, percentage points |
|---|---:|---:|---:|
| Macro-F1 | 50.87 | 50.80 | -0.06 |
| Mass recall | 76.31 | 75.50 | -0.82 |
| AD recall | 23.10 | 29.37 | +6.27 |
| Asymmetry-family recall | 58.13 | 52.47 | -5.66 |

Prospective gate: macro-F1 gain >=3points, Mass recall loss <=2points, no decline
in AD/family recall. FAILED macro gain and family retention. No threshold or ensemble
rescue performed. Identical indices, truth and group order asserted before comparison.
Shared-study bootstrap across splits: 1,993 valid of2,000 replicates. Difference95%
intervals in points: macro[-6.87,+6.54], Mass[-5.35,+3.59], AD[-9.46,+20.69],
family[-17.53,+6.64]. These do not establish any reliable gain; not patient-independent.

## 5. Interpretation

Majority baseline audit (October 7): always predicting Mass yields183/224,
156/208 and164/226 correct, mean76.42% accuracy on these same development splits.
Thus the reference's70.00% accuracy alone does not demonstrate strong performance.
The constant predictor has zero AD/family recall; the trained model's minority
recognition must be evaluated using macro-F1 and per-class metrics. Prior accuracy
clarification was numerically correct but incomplete without this baseline.

Literature comparison: [2023 AD identification study](https://www.frontiersin.org/journals/oncology/articles/10.3389/fonc.2023.1119743/full)
reports80% validation accuracy/66% sensitivity for AD identification, and84% accuracy
for malignant AD diagnosis. These are different endpoints and cohort, not our three-
class VinDr ROI benchmark. B66 records a closer VinDr local-finding study and a CBIS
mass descriptor study. Higher published numbers exist for related tasks, but no
direct ranking against our70% is established. No new fitting in this audit.

Owner-requested accuracy clarification (October 7): recomputed trace/total from
saved final development confusion matrices. Matched reference correct counts are
173/224, 128/208, 161/226; mean split accuracy70.00%. EfficientNet counts are
166/224, 132/208, 160/226; mean69.46%. Pooled prediction-event fractions are
462/658=70.21% and458/658=69.60%; these are not658 unique independent lesions because
development groups can recur across splits. Prefer mean split accuracy alongside
per-class recall and macro-F1. These reference-ROI numbers do not establish accuracy
of the original Razi detector or measure detection sensitivity. No new inference.

Final train/development macro-F1 by seed: 97.25/45.64, 85.65/50.39, 88.31/56.38%.
Large gaps are consistent with limited generalization/overfitting; class scarcity,
label ambiguity and the bounded optimization recipe are competing explanations.
The data do not prove an intrinsic failure of EfficientNet. More epochs alone are
not justified given this gap and B64's failed longer fitting. AD gains are uncertain
and accompanied by worse family typing. No normal-tissue false-positive rate can
be computed from this lesion-only cohort. No per-case physician adjudication ran.

## 6. Decision and next experiment

Retain the existing research reference and production model. Do not deploy B69.
Changing encoder alone has not solved the typing problem. Next priority is a
controlled training-supervision experiment on a fixed encoder: training-only class
balance and then hard-example/contrastive supervision as separate interventions,
with the same retention gate. Audit minority labels/support and freeze grouped inner
selection before tuning. Do not use outer development scores to repeatedly pick
weights, epochs or routing thresholds. New independent evaluation is required for
promotion after accumulated development exposure. No balancing or contrastive run
is claimed here; no new physician marking is requested until disagreement audit
identifies consequential uncertain examples. CPU whole-study qualification remains
open; B68 synthetic timing is not a trained Razi serving benchmark.

## 7. Qualification

Input/source hash checks, actual optimization and checkpoint replay: passed.
Comparative retention gate: failed. Independent clinical test, live GUI, target CPU
pipeline qualification, physician acceptance and deployment: not performed. Source
rights/clinical qualification are not established by successful loading. Private
identities and coordinates stay in protected artifacts. No private data entered docs.
