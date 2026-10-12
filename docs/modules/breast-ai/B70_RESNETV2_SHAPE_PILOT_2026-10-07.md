# B70: ResNetV2 mass-shape feasibility and training pilot

Date: 2026-10-07. Owner requested a real test of the published mass descriptor
approach before addition to Eagle Eye. This is a separate four-shape task, not
Mass/asymmetry/AD typing. Clinical integration is not performed.

## Paper and artifact audit

[Author paper](https://deustoteka.deusto.es/server/api/core/bitstreams/629672a2-ca70-41f2-8259-a6eb8e764abb/content)
reports83.84% CBIS BI-RADS in Table9 and90.02% shape in Table12; Table13 distinguishes
segmentation-enabled performance. These are ensemble results, not a generic
ResNetV2 guarantee. Image-random80/10/10 partitioning is described; patient grouping
and augmentation-family separation are not established. This is a limitation, not
proof of leakage. The described recipe includes augmentation, regularization,
longer fitting and three ResNetV2 members.

[Author code](https://github.com/AsmaBaccouche/Stacked-Ensemble-of-Residual-Neural-Networks)
commit aa94881630b80e1ce45eada14ddca823d40515d4 has scripts but no published releases
or task weights in its root. Stacker expects external50/101/152V2 H5 weights.
Inspected shape script actually starts with ResNet101V2's ImageNet classifier output,
adds dense1024/dropout0.3, and makes BatchNorm layers trainable. Our pooled50V2 pilot
differs materially. Source license not verified; scripts were inspected, not reused
as our implementation. A fresh independently authored pilot follows official Keras APIs.

## Data and partition contract

Protected B50 CBIS staging contains1,015 local/context pairs and four shape labels.
Select1,005 rows with exactly one known shape; exclude10 multilabel rows without
relabeling them. All four attributes were known for these source rows. Shape order:
ROUND, OVAL, LOBULATED, IRREGULAR (legacy source vocabulary).
Use local224 only; no lesion segmentation/mask in this pilot. Three group-disjoint
80/20 development splits, seeds17/29/43, saved before fitting. Group identity comes
from the existing manifest; authoritative person linkage not newly verified.
This source pool was previously used for auxiliary training, so results are development
evidence, not an untouched independent test. BI-RADS is absent from this staged tensor
schema; no BI-RADS training or accuracy claim is made here. It requires separate source
label binding. Source hashes and private split indices are in protocol.json.

## Implementation, provenance and deviations

Official Keras ResNet50V2 ImageNet no-top weights, global average pooling, independently
initialized2048-to1024-ReLU-to4 head. RGB repeats of grayscale, normalized[-1,1].
Train conv5 non-BatchNorm layers and head, all calls training=False so BN statistics
remain fixed. AdamW decay0.01, encoderLR1e-5/headLR1e-3, batch8, FP32, five fixed
epochs, no scheduler/augmentation/dropout/label smoothing. Inverse training-group
row weighting, no class weighting. Final epoch only, no checkpoint selection on
development. One-hour cap; no ensemble/stacker fitted. This is not paper reproduction.

Isolated b70-keras-env inherits system packages; Keras3.12.4, PyTorch backend with
torch2.11.0+cu130, A10040GB. The unavailable3.13.2 pin failed before installation;
3.12.4 installed inside the new environment, without changing existing environments.
Environment freeze is stored with receipts. Initial Google-hosted weight retrieval
returned403 before training. Retry uses official keras-team/keras-applications GitHub
release, with Keras file-hash validation at load. SHA256:
5ad0f9ca220e40926a2394d52e0f9f1ea135b8022560747c85e0d82ae699a6d9.
Initial pre-fit protocol remains preserved; successful retry uses suffix-r1.

## Evaluation and execution guards

Report ordinary accuracy, macro-F1, every shape recall and train-selected majority
baseline on the same development rows. Groups cannot cross a split; repeated splits
are not independent cohorts. Per-epoch objective, finite gradients and probability
checks are recorded. Final encoder/head updates and exact full-development checkpoint
reload are asserted. No separate discarded synthetic optimizer guard was performed
for this pilot; real-run assertions are not retrospectively described as one.

## Results and decision

Three fits completed with exact final development checkpoint reload. Seed17 uses
813/192 train/development rows; seed29 820/185; seed43 815/190. Each has440/110
disjoint groups (550 total). Total single-label support114/283/278/330 in shape order.

| Metric | Mean across three splits |
|---|---:|
| Shape accuracy | 38.83% |
| Macro-F1 | 31.80% |
| Final training accuracy | 96.89% |
| Training-selected majority baseline accuracy | 30.16% |
| Round recall | 9.45% |
| Oval recall | 38.82% |
| Lobulated recall | 23.81% |
| Irregular recall | 65.76% |

Per-split accuracy35.94/40.54/40.00%. No confidence interval or independent test.
The large train/development gap is consistent with poor generalization. This pilot
does not establish failure of the published ensemble. It shows that this adapted
single member is not ready for physician-facing classification. No promotion.

Execution amendment: r1 completed seed17, then exceeded its5GiB process memory cap
during seed29 evaluation. Its completed checkpoint and partial receipts are retained.
r2 restarted29/43 with unchanged fitting recipe, evaluation batch16-to8 and explicit
Keras/global-memory cleanup between models. Both completed. No unrelated service
stopped. Failed partial fitting is not an extra successful replicate. r2 took207.28s
with peak allocated CUDA3,550,199,296bytes; total elapsed including interruption was
not measured in one receipt. OOM traceback was not saved as a full run log.
Aggregate.json reconciles the three completed fits. Private predictions stay protected.

Next: audit local crop versus validated CBIS mask/contour and bind original assessment
labels separately before adding ensemble members. Freeze segmentation-aware descriptor
training with regularization and grouped inner selection. A box is not a true contour.
Exact paper reproduction, the three-model ensemble and BI-RADS training remain undone;
no84/90% capability is established on our data.

## Artifact and qualification scope

Protected P/R roots from current-state document: b70-shape.py,
b70-resnetv2-shape-20261007-r1, b70-author-audit (P), b70-keras-env (R).
Retry artifacts: b70-shape-r2.py, b70-aggregate.py,
b70-resnetv2-shape-20261007-r2. JSON receipts copied to P; checkpoints remain on R.
Predictions, group keys and image rows stay outside the repository. No GUI changes,
clinical deployment, physician acceptance or target-CPU qualification performed.
