# B65: Independent compact representation challenge

Date: 2026-10-06. Nine frozen probes, three neural adaptations and one fixed fusion
evaluation completed. Neither direct replacement nor equal fusion passes retention.
No production changes. Follows B62 selection and B64 failed native-detail experiment.

## 1. Objective, provenance and readiness

Improve reference-ROI Mass/AD/asymmetry-family appearance typing, not detection,
malignancy or BI-RADS. Test a distinct representation rather than repeat B64.
[Official DINOv2 source](https://github.com/facebookresearch/dinov2) and its model
card identify standard ViT-S/14 as a21M-parameter public backbone, Apache2.0.
This is not XRay-DINO or Cell-DINO and their separate licenses do not apply here.

Actual source cloned and pinned at7764ea0f912e53c92e82eb78a2a1631e92725fc8.
Official weight URL:
https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth
Downloaded SHA256 b938bf1bc15cd2ec0feacfe3a1bb553fe8ea9ca46a7e1d8d00217f29aef60cd9.
Strict weights_only state loading succeeds. Source/version and local hash are recorded;
exact LVD142M overlap with our medical cohort has not been independently audited.
No dependency installation or service interruption. xFormers explicitly disabled;
existing PyTorch inference path used. Full environment lock not recorded.

Protected R artifacts: b65-dinov2-source, b65-dinov2-vits14.pth,
b65-frozen-probe-20261006 and b65-dino-adaptation-20261006. P contains copies of
results and scripts b65-probe.py/b65-adapt.py. Protocols bind input/split/script hashes.

## 2. Cohort and reference standard

Same B64 available-source cohort:1,147 ROIs from561 studies, Mass834/AD79/family234.
Original seed17/29/43 study partitions retained. Grouping is not proven patient
linkage. Development has224/208/226 ROIs, including12/20/14 AD examples. Source
labels unchanged, unresolved physician corrections excluded. Repeated development
selection, no independent test; unavailable-source selection bias remains.

## 3. Frozen-probe protocol

Identical original local224/context224 image tensors and ImageNet normalization.
Concatenate two DINO CLS embeddings (768 values), or two ResNet pooled embeddings
(1024 values). Three encoder sources: ImageNet ResNet18, seed-matched CBIS auxiliary
ResNet18, official DINOv2-S. CBIS encoders have no target fitting in this probe.
Frozen encoder extraction for all rows uses no labels or learned cohort normalization.

Fit StandardScaler only on each fitting partition, divide by sqrt(feature dimension),
then fixed LogisticRegression C1, lbfgs, max2000 iterations. Normalize inverse-study
row sample weights within fitting split; no class weighting or parameter search.
All nine solvers converge and serialized probe predictions reload exactly. This is
a deliberately simple regularized probe, not the best possible head or backbone fit.

| Mean development metric | ImageNet frozen | CBIS frozen | DINOv2 frozen |
|---|---:|---:|---:|
| Macro-F1 | 38.94% | 42.25% | 45.10% |
| Mass recall | 96.02% | 94.78% | 93.06% |
| AD recall | 0.00% | 1.67% | 2.78% |
| Asymmetry-family recall | 21.83% | 29.33% | 40.29% |

DINO's frozen representation is more promising on family typing under this fixed
probe, but rare AD remains poorly learned even in training. This probe alone cannot
rule out feature/head regularization limitations. None replaces B64's adapted control
(50.87% macro-F1 on the same cohort). No claim of architecture superiority or independent
clinical improvement. Extraction plus nine fits took5.96seconds on the research host,
excluding downloads; not complete serving latency.

## 4. Bounded adaptation protocol

Before observing adaptation results: three seeds, final fixed epoch5, local224/context224,
official initial DINO encoder, freshly initialized768-to3 head. Freeze all except last
two transformer blocks and head; final norm stays frozen. AdamW headLR0.001,
last-blocksLR0.00001, decay0.01, batch8 pairs, FP32, no augmentation/scheduler.
No CBIS pretraining for DINO: compare representation pipelines, not a pretraining-
matched architecture ablation. Original B64 context224 five-epoch control is retained
on identical indices and labels, with exact reproducibility established in B64.

Use real discarded synthetic optimizer/reload check; finite gradients, actual head/
last-block changes, normalized probabilities and exact checkpoint reload. Log each
epoch's comparable train/development metrics. No favorable intermediate-epoch selection.
Reuse B62 retention gate: >=3-point macro-F1 gain versus adapted control, Mass loss
<=2points, no AD/family recall decline, with paired group uncertainty and limitations.
This five-epoch pilot is not a claim of optimal DINO tuning or convergence.

## 5. Adaptation results

| Mean development metric | Adapted B64 control | Adapted DINO | Equal probability fusion |
|---|---:|---:|---:|
| Macro-F1 | 50.87% | 51.24% | 53.46% |
| Mass recall | 76.31% | 56.88% | 68.70% |
| AD recall | 23.10% | 41.51% | 33.02% |
| Asymmetry-family recall | 58.13% | 85.92% | 76.25% |
| False Mass among reference non-Mass ROIs | 39.69% | 10.58% | 21.96% |
| Mass precision | 87.22% | 95.21% | 91.85% |

False Mass here means a source AD/asymmetry ROI called Mass; it is NOT a normal-tissue
false-positive rate. There are no normal-reference ROIs in this cohort. Metrics are
means across the same repeated study partitions, not independent population estimates.

Adapted DINO changes the tradeoff: macro+0.37points, Mass recall-19.44, AD+18.41,
family+27.79. Mass precision improves while true Mass recall deteriorates. It fails
the Mass preservation gate despite better minority typing and less Mass overcalling.

After seeing aggregate complementary errors, but before evaluating fused predictions,
defined one equal0.5/0.5 probability average; no weight search or threshold tuning.
It gains2.60macro points but loses7.61Mass recall points, also failing the gate.
Uncalibrated probabilities from different models are a further fusion limitation.
This exploratory extension is not retrospectively described as an original hypothesis.

Paired study bootstrap uses shared study weights across seed partitions,1,993 valid
replicates from2,000 attempts. Macro difference95% intervals: DINO[-5.95,+6.94]points;
fusion[-2.71,+7.85]. Mass-recall differences: DINO[-24.36,-14.50];
fusion[-11.68,-3.79]. No independent qualification or statistical guarantee.

All three actual adaptations completed, with real synthetic optimizer/reload guard,
finite gradients/probabilities, parameter changes and exact final checkpoint replay.
Execution100.97seconds excludes download, staging and full serving workflow. Full
CPU/Razi timing remains unmeasured. No service was interrupted or model deployed.

## 6. Interpretation and next action

Keep B50 as research reference and the production model unchanged. DINO is a useful
research challenger with complementary errors, not an accepted replacement. Reject
the tested equal blend. Do not choose an apparently favorable blend weight by another
outer-development sweep.

Next discriminating protocol: retain the outer partitions; within each fitting
partition create group-disjoint base-fit and calibration/meta-fit subsets. Retrain
both models only on base-fit, obtain truly held-out predictions for calibration,
and learn a small regularized combination or disagreement/abstention rule there.
Then assess once on the unchanged outer development partition, including retained
coverage and Mass/AD/family tradeoffs. Existing model predictions on their own fitting
rows are not valid meta-training evidence. Use nested/cross-fitted predictions if
needed to conserve rare AD support; predeclare support and stopping gates first.

In parallel, inspect model disagreements against reference scope and physician
annotation, preserving unknown and mixed findings. Source non-Mass labels are not
automatically adjudicated truth and single-view ambiguity remains. A learned router
is only a hypothesis; if it fails, prioritize targeted reference/rare-class supervision
instead of another bigger backbone. No router training ran in B65. CPU full-study
qualification, external data and validated mass descriptors remain separate requirements.

## 7. Qualification status

Actual downloaded assets/load/frozen extraction and probe fits pass. Application GUI,
Razi CPU pipeline, clinical qualification and deployment not performed. Private input
identities, features and geometry remain on authorized research storage.
