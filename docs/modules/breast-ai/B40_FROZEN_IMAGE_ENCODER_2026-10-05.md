# B40: Frozen image encoder comparison

Date: 2026-10-05. Research experiment following B39. Status: extraction and six
classifier fits complete; both variants rejected for promotion.

## Contract fixed before fitting

Reuse exact B38 row order (1,189 regions, 594 studies, 1,083 images) and seed
17/29/43 fitting/development indices. Reference boxes, no new detector evaluation.
Pretrained TorchVision ResNet-18 ImageNet checkpoint already present on Windows
A100; strict state loading, frozen backbone, evaluation mode. Linux A100 has
12,147 MiB free and 28,295 MiB occupied at probe time; no job was interrupted.
This bounded frozen-feature experiment runs on Windows CPU using two threads.

Read raw DICOM, exclude padding for intensity statistics, apply linear rescale and
MONOCHROME1 polarity correction. Use 1st/99th image percentiles on stride-4 samples
for normalization, crop original-resolution arrays at reference box and twice its
width/height. Context is clipped at image boundaries. Resize each crop preserving
aspect ratio to fit 224 square, replicate-pad, repeat grayscale across RGB, apply
ImageNet channel normalization. No center crop that would discard lesion margins.
No VOI LUT or display window is applied. This is a research preprocessing contract,
not a qualification of all DICOM types. Fine detail lost at 224 remains a limitation.

Compare 512-dimensional local embeddings versus 1,024-dimensional local+context
concatenation. StandardScaler fitted with fitting-only study-balanced sample
weights; logistic regression C=1, LBFGS, maximum 2,000 iterations. Same group
weights, no class balancing, no threshold tuning; three-way argmax. Require
convergence and serialized scaler/model reload probability agreement.

This compares a new representation/classifier package with B38, not a pure encoder
ablation versus boosting. Local-versus-local+context within B40 isolates added
context under this fixed model family. No backbone fine-tuning occurs. Preserve
all extraction failures; do not silently drop or replace rows. Development groups
are repeatedly exposed and overlap legacy training; no independent clinical claim.

## Execution notes

Initial extraction emitted failures and was stopped before fitting. Input preparation
was corrected to explicitly cast image tensors to float32; the repeated initial
error cause was not captured in full and should not be claimed definitively.
A synthetic float64-image test now verifies finite float32 RGB tensors of shape
1x3x224x224. The restart begins from the same cohort. No clinical process was stopped.
Only the two verified Python processes for this isolated experiment were terminated.

Private implementation: P/typing_encoder_pilot_20261005.py. Remote candidate outputs
under typing-encoder-pilot-20261005. Receipts will bind checkpoint, script and
embeddings by SHA-256 and retain private row-linked predictions. No clinical images
or identifiers enter project documentation. No deployment or GUI change.

## Completed results

All 1,083 images decoded; no failures in the completed extraction. 1,189 regions
yielded local/context embeddings in 485.32 seconds on CPU, including DICOM I/O and
two crops per region. This is not full-study serving latency. All six logistic
fits converged in 103-154 iterations; reload probability checks passed.

Arithmetic means across three exposed development splits, percentages:

| Variant | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| B38 A0 | 38.28 | 94.31 | 21.08 | 0.00 |
| B40 local | 40.38 | 83.34 | 30.61 | 5.93 |
| B40 local + context | 39.43 | 83.83 | 27.28 | 7.04 |

Local-only gains 9.53 FA recall points but loses 10.98 Mass recall points.
Despite a higher macro F1, both candidates fail the Mass preservation criterion
in every split. Do not promote or claim a clinically meaningful improvement.
No comparison here establishes performance against the live Razi system.

Exact paired Mass row losses/gains versus A0 (do not pool overlapping splits):

| Variant | Seed 17 lost/gained | Seed 29 lost/gained | Seed 43 lost/gained |
|---|---|---|---|
| Local | 27 / 5 | 26 / 6 | 26 / 11 |
| Local + context | 15 / 5 | 28 / 2 | 34 / 13 |

These are annotation rows, not uniquely linked lesions across views. Private
discordant-rows-private.json identifies cases for error review without exposing
identifiers in documentation. Paired split identities were checked exactly.

Checkpoint SHA-256: f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec.
Embeddings SHA-256: bd86b0b179cffa808c5a8aeb179a173f6155f4e269ed059079f2ae61517db651.
Scripts and all six fitted model hashes are recorded in results.json. Local copies
under P/typing-encoder-pilot-20261005 include extraction/results, models, embeddings,
private predictions, paired-summary.json and discordant rows. Summary script:
P/summarize_typing_encoder_20261005.py. Source geometry and labels inherit B38.

## Decision

The frozen generic encoder plus linear head does not meet requirements. Context
concatenation alone does not rescue it. This does not establish that supervised
image encoders or proper multi-view reasoning fail. Do not mask the failure with
a retrospectively tuned mixture that favors Mass on the same validation labels.

Next gate before the one bounded fine-tuning experiment from B39: inspect native
crop quality and discordant cases, preserve reference labels/ambiguity, prepare
fitting-only augmentations and native multi-view context. Fine-tuning is not yet
executed. Keep existing detector and typing baseline unchanged, and hold independent
qualification outside this repeatedly explored development cohort. No request for
new physician annotations is made until a concrete ambiguity/error packet is ready.
