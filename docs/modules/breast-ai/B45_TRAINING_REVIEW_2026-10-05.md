# B45: Matched supervised full-ROI adaptation

Date: 2026-10-05. Status: six real training runs completed; reject promotion.
Research only. No production changes.

## Objective and rationale

B44 completed42 fits without an acceptable replacement. Frozen generic features,
auxiliary metadata heads, central calcium features and low-resolution global companion
features did not preserve Mass while improving minority typing sufficiently.
Test actual task-specific image representation learning, rather than another
concatenation or weighting sweep. Output remains reference-ROI Mass/FA/Asymmetry.

## Prespecified comparison

Use all1,189 eligible B38/B41 rows, same594study groups and seeds17/29/43, unchanged
TRAIN/development indices. Compare two freshly initialized three-class heads on the
same ImageNet ResNet-18 checkpoint: backbone frozen versus last residual block
(`layer4`) plus head trainable. Six fits in total, not a parameter search.

Extract each full reference box, preserving aspect ratio at224pixels, with B40
per-image percentile normalization, polarity/rescale and padding handling. Store
float32 one-channel pixels in[0,1]; repeat channels and apply ImageNet normalization
inside the trainer. Do not reuse central512 tiles from the calcium experiment.
Bind source hashes, target row order, source geometry and split identity. Direct
embedding parity against B40 is a requested preflight check.

Fixed15epochs, batch16, float32 without AMP, AdamW headLR0.001/layer4LR0.00001,
weight decay0.01, inverse-study weighted cross-entropy, no class rebalancing or
augmentation. Same head initialization and batch order in each matched seed.
All encoder BatchNorm running statistics remain frozen. Final epoch only, no
development-selected checkpoint. One-GPU-hour budget,3GB allocator cap, no service
interruption. Record actual rather than estimated resource use after completion.

## Execution and guards

Protected location: `P/typing-supervised-local-20261005`, mirrored under the existing
Windows candidate root and Linux R. Dataset agent owns staging; training agent owns
trainer/checkpoints; independent review checks fairness and source/target binding.
No labels/coordinates or patient images belong in repository artifacts.

Before fitting: verify target equality with source CSV, exact row/split/checkpoint
hashes and seed list. Discard a separate synthetic optimizer/reload smoke model.
During fitting: record finite loss/gradients, actual successful steps and source
coverage. After fitting: verify real layer4 parameter changes only in the adaptation
arm, nonzero head changes, fixed BN statistics and exact checkpoint reload outputs.

## Evaluation and decision contract

Report TRAIN and development macroF1, each class recall/precision, confusion,
prediction collapse, paired Mass loss/recovery and runtime for both arms. Compare
against each other and B38/B41. Retain failed outcomes. No independently qualified
clinical result can be inferred from repeatedly used TRAIN development splits.
Fixed15epochs do not establish convergence or optimal hyperparameters. A local
ROI model also does not resolve cross-view lesion correspondence by construction.

## Results and decision

| Mean metric across three fixed splits | Frozen control | Layer4 adaptation | B41 comparator |
|---|---:|---:|---:|
| Development macro F1 | 38.29% | 42.18% | 41.41% |
| Mass recall | 95.10% | 89.65% | 95.20% |
| Focal Asymmetry recall | 20.12% | 30.26% | 23.51% |
| Asymmetry recall | 0.00% | 3.33% | 3.33% |
| Fitting macro F1 | 56.38% | 99.74% | Not evaluated here |
| Fitting log loss | 0.450 | 0.022 | Not evaluated here |
| Development log loss | 0.659 | 1.133 | Not evaluated here |

Adaptation improves FA recall by10.15 percentage points against its matched frozen
control but loses5.45 Mass recall points. Against B41 it gains6.75FA points while
losing5.55Mass points. Reject promotion. The near-perfect fitting score, much lower
development score and worse development log loss provide evidence of overfitting,
not a reason to keep training indefinitely. This is not proof that all fine-tuning
recipes fail; it rejects this specific fixed-budget adaptation for replacement.

Paired Mass lost/recovered versus the matched frozen arm is16/0,6/7,16/4 for
seeds17/29/43; paired FA lost/recovered is0/14,3/4,2/2. Gains are not consistent
across classes or partitions. Split-specific observations must not be pooled as
independent people. Private summary retains corresponding B41 comparisons.

All six fits completed 15 epochs:915successful steps in each seed17 arm and900
in each seed29/43 arm, totaling5,430 actual optimizer steps. Gradients/losses were
finite; heads changed; BN buffers remained unchanged. Frozen layer4 squared
parameter delta is0; adapted deltas are2.989/3.034/2.855. All six checkpoint reloads
produce identical development probabilities. No test-based checkpoint selection.

GPU fitting/evaluation/reload wall time42.19seconds; peak allocated memory
510,069,248bytes. These are research batch measurements, not Razi serving time.
Recorded runtime versions: Torch2.11.0+cu130, NumPy2.2.6; full environment lock
not recorded. The actual small run did not require an H200 or additional allocation.

Protected receipts: `P/typing-supervised-local-20261005/{results.json,summary.json,
protocol.json,training.log,synthetic-guard.json}`. Six final checkpoints remain at
`R/typing-supervised-local-20261005/{frozen,layer4}-{17,29,43}-final.pt`.
Results SHA256: `65a95dac38881d935428f7e07bd5aee9cb65159acdaa0e3e2247fec13d88cc75`.

## Continuation decision

Across B44/B45,48 actual fits have not yielded a replacement preserving Mass and
improving the minority types. Retain the B41 research comparator and existing
production models. Stop generic frozen-feature concatenations, metadata-auxiliary
sweeps and simply extending this local fine-tuning run.

Next discriminating work is a compact review of persistent FA-to-Mass and Asymmetry-
to-Mass disagreements with both original views and source annotations, followed by
a task-specific local-to-companion-view representation experiment. Do not create
lesion matches from annotation absence or target labels. The global companion
ablation contains complementary information but does not establish spatial pairing.
Resolve label/context uncertainty before a larger training sweep. Independently held
patient-linked qualification data and full CPU serving measurements remain required
for claims beyond this repeatedly exposed research cohort.

## Execution issue retained before training

The first staging run completed image decoding but failed its final strict[0,1]
range assertion before serialization. Actual range was not recorded by that failed
process, so floating-point interpolation overshoot is a hypothesis, not a diagnosed
cause. No clinical-model fit occurred. Preserve the failed script/receipt; restart
with source/protocol-bound per-image persistent staging and measured range before
acceptance. Do not silently clip pixels or relax guards without the measured evidence
and frozen B40 embedding parity. A separate GPU synthetic update/reload preflight
passed; this demonstrates executable training, not an accuracy result.

Subsequent measured evidence: input minimum0.0, maximum1.0000003576278687,
all finite;60,987 values slightly above1 and zero below0. A small float32 bilinear
antialias reproduction also exceeds1 by a few1e-7. This identifies numerical
interpolation roundoff at the range guard. Accept a documented1e-6 range tolerance
without clipping or otherwise changing pixels. The restart uses a flushed memmap
with atomic completion markers bound to script/protocol/row/checkpoint hashes and
rechecks source hashes before reuse. Frozen-embedding parity was subsequently verified.

## Completed input verification

All 1,189 full ROIs from 1,083 images staged without geometry clipping. Shape
`(1189,1,224,224)`, float32, lossless NPZ165,234,805bytes. Successful staging took
493.67seconds; failed/restarted attempts are excluded, so this is not total project
wall time. NPZ SHA256:
`45347f3f3b4f9fb398d7bb0751c55a3cfd0d46bcb598f8e9a3b5d41959d6d2f5`.
Source binding count is1,083; geometry indices cover0-1188 exactly once. Serialization
is exact. Frozen B40 local embeddings match exactly on18checked rows (max error0).
Data/weights/receipts transferred to Linux R before fitting.

Local contact-sheet inspection found visible tissue with variable brightness and
replicated padding bands in narrow boxes, consistent with fixed B40 preparation.
This is technical inspection, not confirmation of clinical labels. Padding fraction
median is13.39%Mass,18.30%FA,13.84%Asymmetry; more than50%padding affects13/927,
5/190,2/72 respectively. Native median height/width is246/236,361.5/327.5,229/220pixels.
Only5/1/0boxes have a native short side below64pixels, none below32. Box size and
padding may be confounders; these aggregates do not prove an error mechanism.
Evidence: `b40-input-parity.json`, `staging-results.json` and
`padding-dimension-qc-aggregate.json` in the protected run directory.

No runtime integration or GUI change occurred. Model execution and document checks
are reported separately; no live GUI acceptance, deployment or release claimed.
