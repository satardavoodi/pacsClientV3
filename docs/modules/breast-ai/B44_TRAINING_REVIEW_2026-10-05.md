# B44: Parallel lesion-typing experiments

Date: 2026-10-05. Status: forty-two typing fits evaluated; none promoted.
Research only. No production model, clinical workflow or calcium detector changed.

## 1. Objective and evidence identity

Test whether auxiliary tasks, complementary image representations or actual calcium
features improve Mass / Focal Asymmetry / Asymmetry typing without sacrificing Mass.
This is classification of reference ROIs, not an end-to-end localization experiment.
Three parallel work streams were explicitly requested by the owner.

Protected evidence root P is defined in the current-state document. Run directories:

- `P/multitask-typing-probe-20261005`: protocol, results, summary, private predictions,
  and nine fresh fitted checkpoints.
- `P/multitask-typing-regularized-20261005`: separate protocol, results, summary,
  private predictions and six fresh checkpoints. This follow-up was specified after
  observing the initial generalization gap; it is not an independently selected test.
- `P/typing-error-fusion-20261005`: protocol, results, embedding-integrity audit,
  private predictions and three serialized fitted estimators.

Scripts of the corresponding names reside alongside these directories. Protocols
bind source, script, row order, split and embedding hashes. Frozen B40 ResNet-18
embeddings SHA256: `bd86b0b179cffa808c5a8aeb179a173f6155f4e269ed059079f2ae61517db651`.
No encoder fine-tuning occurred in these eighteen fits. Windows CPU, two Torch
threads for neural heads; environment inherited the B40 Windows training environment.
Complete environment lock and peak memory: not recorded for these new runs.

Verified local result receipt SHA256 values:

| Run | Results receipt SHA256 |
|---|---|
| Initial multitask | `d69365bf9a02843abf899d9e2ff1e16890f91c8ad59312310af1f7c84d9dd6a6` |
| Regularized follow-up | `cda59c3d64e6eb9de86d40544f9f48b09692f1271fe2586521093981cb39b7e4` |
| Generic fusion | `e8519fb3d98ee662b5dd345a25db340e24b7e073178a7c64cb51e2b43ee85aa1` |

## 2. Cohort readiness

Same 1,189 reference ROIs, 594 study groups and 1,083 images as B38/B41.
Counts: Mass927, Focal Asymmetry190, Asymmetry72. Seeds17/29/43 retain exact
saved fitting/development indices. No study crosses its split. Repeated partitions
overlap and have been repeatedly examined; they are not three independent tests.
Authoritative person linkage and pixel-level near-duplicate exclusion are unavailable.
All target studies come from previously exposed legacy TRAIN, not independent Razi cases.

Audit found zero duplicate source ROI keys, nonunique joins or label disagreements,
and zero empty or exact-duplicate local embeddings. One row has ten unavailable
LBP features; the histogram boosting estimator handles them natively, with no drop.
Density C dominates all three classes. Asymmetry is55MLO/17CC, while FA is94MLO/96CC.
This imbalance is descriptive evidence, not permission to use view as a label shortcut.
Unboxed tissue and absent calcium annotations were not assigned normal/calcium-negative truth.

## 3. Training configuration and telemetry

Matched neural arms use frozen local+context1024-dimensional embeddings, a TRAIN-only
weighted scaler, inverse-study row weights and identical main-head initialization.
Single-task control versus auxiliary CC/MLO or breast-density prediction: hidden128,
dropout0.2, AdamW learning rate0.001, weight decay0.01,120fixed epochs, auxiliary loss
weight0.2. Auxiliary labels enter fitting loss only, never inference inputs.
No development-selected epoch, operating threshold or checkpoint was used.

One bounded follow-up uses hidden32, dropout0.5, learning rate0.0003, weight decay0.01,
20fixed epochs; compare single task with view auxiliary0.2. This changes several
regularization/budget factors together, so it does not isolate their individual effects.
Successful updates, finite gradients, decreasing losses and exact checkpoint reloads
were checked for all fifteen neural fits. Nine initial fits took6.84seconds and six
follow-up fits1.79seconds; these exclude the prior image decode/embedding extraction.

Fusion adds32 nonwhitened PCA components of local512 embeddings to B41's55features.
PCA uses fitting rows only, unweighted; HGB fitting uses study weights. Same B38
configuration:120iterations,7leaves,min leaf15,learning rate0.06,L2=5,no early stopping.
Three fitting/PCA/serialization runs took2.70seconds, excluding feature extraction
and loading. Reload probabilities matched. No hyperparameter sweep was performed.

## 4. Metric and selection contract

Argmax three-class predictions; macro F1 and per-class recall on the exact saved
development rows. Means below average three split metrics rather than pooling repeated
rows. Paired predictions are retained privately. Existing promotion guard requires
Mass recall preservation in every split against B38 A0, plus useful minority gains.
These small repeated development partitions cannot establish clinical sensitivity.

| Method | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| B38 A0 comparator | 38.28% | 94.31% | 21.08% | 0.00% |
| B41 no old calcium proxies | 41.41% | 95.20% | 23.51% | 3.33% |
| Frozen embeddings, single task | 43.92% | 90.76% | 30.33% | 7.04% |
| Frozen embeddings, view auxiliary | 44.54% | 91.42% | 30.70% | 7.04% |
| Frozen embeddings, density auxiliary | 43.16% | 90.41% | 28.85% | 7.04% |
| Regularized single task | 40.56% | 89.93% | 21.68% | 13.33% |
| Regularized view auxiliary | 40.23% | 89.58% | 24.34% | 11.11% |
| B41 + local embedding PCA | 39.00% | 95.03% | 22.10% | 0.00% |

## 5. Interpretation and decisions

View auxiliary versus its matched neural control changes macro F1 by+1.91,-0.84,+0.79
percentage points across seeds: small and inconsistent. Density auxiliary worsens all
three. The best mean macro F1 is not sufficient: view auxiliary loses3.78Mass recall
points against B41 while gaining7.19FA recall points. Reject replacement.

Initial fitting macro F1 is approximately99.9% versus43-45%development. The bounded
follow-up reduces this gap to6.90/7.65points but lowers development F1. Therefore,
removing apparent overfit alone did not produce useful generalization; further
indiscriminate training duration or regularization sweeps are not justified here.

Fusion fails to improve on B41 and violates the Mass gate in seed29: five previously
correct Mass rows are lost and three gained versus B38. Reject this concatenation.
Join or empty-embedding errors do not explain the weak minority results in this audit.
Limited representation and missing cross-view evidence remain hypotheses to test.

Error attribution is more specific than overall F1: B41 FA-to-Mass errors are29/35/36
for seeds17/29/43, while FA-to-Asymmetry errors are only1/0/1. View auxiliary gives
31/30/32 FA-to-Mass errors. Relative to B41 it corrects/loses10/11,8/3,9/4 FA rows,
but corrects/loses only4/10,5/13,8/14 Mass rows. No demonstrated gate protects Mass.
Across seven compared arms,14/50,23/41,20/44 FA observations remain unanimously
called Mass. Do not pool these repeated-split counts as independent patients or
turn an oracle combination of correct answers into a deployable ensemble claim.

## 6. Actual calcium transfer: completed and rejected

Actual frozen calcium FPN transfer completed on native512 ROI-center tiles. An
initial extraction explicitly stopped at an unsupported polarity/rescale contract;
the failure receipt is retained. Restart retains unavailable rows as NaN plus an
availability flag, with a matched availability-only control to prevent crediting
scanner/protocol missingness to the learned calcium features. This is
a bounded central-region transfer experiment, not full-image branch equivalence or
whole-lesion calcium coverage. There are1,025 supported rows from944images and164
unavailable rows from139MONOCHROME1images. Unavailable class counts:137Mass,14FA,13Asym.
No unsupported normalization was guessed. The source stage took431.5seconds on restart;
the failed first attempt is separately retained, not included in that timing.

Fresh frozen FPN inference took15.4seconds for1,025tiles on A100, with312MB peak
allocated GPU memory. It extracts eight score/bright-peak descriptors from the central
256square plus256 frozen decoder mean/std features from the corresponding field.
This is neither end-to-end serving latency nor physically matched calcification counts.
Central256 ROI coverage is limited: median75.3%, first quartile43%, and some border
ROIs have zero overlap because the512crop was shifted to remain inside the image.
The contact sheet was inspected locally; it does not verify each descriptor's ROI alignment.

Six predeclared variants times three seeds yielded eighteen fits with the same B41
HGB configuration and weights. Available features are finite; unavailable values remain
NaN with an availability flag. Baseline predictions and probabilities reproduce exactly;
serialized checkpoints reproduce their probabilities. Availability control itself
has the same reported metrics as baseline. No inference threshold was adjusted.

| Variant | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| B41 / availability control | 41.41% | 95.20% | 23.51% | 3.33% |
| B41 + FPN scores | 36.71% | 93.13% | 18.09% | 0.00% |
| FPN scores only | 30.40% | 96.04% | 3.72% | 0.00% |
| B41 + decoder features | 38.63% | 95.06% | 20.94% | 0.00% |
| B41 + decoder features + scores | 38.72% | 95.46% | 21.03% | 0.00% |

Reject all tested additions: no minority/macro improvement, even where mean Mass
recall rises slightly. This rejects the tested central-region descriptor method,
not all transfer learning or spatially complete mammography features. Do not confuse
this negative result with degradation of the untouched physician-reviewed calcium detector.

Exact source-hash overlap is zero against16 known adaptation fitting/sentinel images;
the publisher checkpoint training lineage remains unverified. Different file hashes
alone do not establish person-level independence or exclude transformed duplicates.
Evidence: `P/calcium-typing-transfer-20261005/` results, summary, inference, source
bindings, unsupported-input manifest and feature schema. Results SHA256:
`7cf5d3b2a210680cd5a5ba92d5c9523afd10681abeb6be93bf9afdd36e4c5351`.
Feature schema SHA256:
`7a0a5a0d9c1aa0d356b8aa16dc2cf835fe267ca7f97a88a5af68a53afe5c81a5`.

## 7. Companion-view experiment: completed

Audited availability of same-breast companion CC/MLO views without using annotated
companion ROI positions or labels to select a region. A later model can use such
image context only if source identity, view/laterality and grouped fitting are bound.
All1,189rows have exactly one valid metadata-selected companion; all1,083companion
files exist and headers match. Union of current and companion sources is1,232images.
Actual extraction completed for a six-fit current-global versus current+companion
experiment, using frozen ResNet-18, TRAIN-only PCA32perstream and fixed B41 boosting.
No companion finding label or annotated companion ROI chooses image content.
No new physician marking is requested until the exact missing evidence is identified.

| Variant | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| B41 comparator | 41.41% | 95.20% | 23.51% | 3.33% |
| B41 + current whole-image features | 35.52% | 95.02% | 14.28% | 0.00% |
| B41 + current + companion whole-image features | 38.51% | 94.99% | 18.00% | 2.22% |

The companion improves macro F1 in every split against its matched current-global
control, but neither method beats B41. Combined context loses one net Mass observation
in each of seeds17/29 against B38; reject replacement. This is a negative result for
224-pixel global pooling with frozen generic features, not a test of trained lesion
correspondence or proof that paired views are unhelpful.

All1,232images decoded without failure in650.18seconds including hashing/normalization
and CPU2-thread encoding. Six fits took5.71seconds. Both are research batch timings.
All file-content hashes are unique, including across studies; pixel near-duplicates
were not tested. B41 probability reproduction and all six model/PCA reloads passed.
Evidence: `P/typing-companion-global-20261005/`; embedding SHA256:
`74460bae3b04270d7caa08f03c2cbcb510773fe1e3b4dae92030eb310d43a71b`.

## 8. Next discriminating experiment

Stop frozen generic concatenation and auxiliary-head sweeps on these exposed folds.
Retain B41 as the Mass-preserving research comparator, without clinical qualification.
Start one bounded matched full-reference-ROI experiment: frozen ResNet-18 plus a
fresh three-class head versus supervised adaptation of its last residual block and
head. Exact source geometry, pixel preparation, split, head initialization and fixed
training budget must match; no class rebalance or development checkpoint selection.
This tests whether task-specific representation learning helps where frozen features
failed. It does not constitute a selected best architecture or a guarantee of gain.
Record the new run separately as B45 and retain all failed outcomes.

## 9. Verification and limitations

Model execution, split/identity checks and reload checks are recorded separately from
clinical qualification. No live GUI acceptance or target-Razi full inference benchmark
was performed. B43's10.37% preparation-only timing reduction remains a separate result.
No new speed gain is claimed from the neural auxiliary tasks or fusion experiments.
No checkpoint was promoted; production remains unchanged.
