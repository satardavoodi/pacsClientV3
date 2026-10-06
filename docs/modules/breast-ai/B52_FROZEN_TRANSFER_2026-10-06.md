# B52: Freeze the source-pretrained encoder during target adaptation

Date: 2026-10-06 (Asia/Tehran). Completed: three actual fits. Directory suffixes
retain the existing 20261005 run namespace. No production or clinical change.
Follows the failed [B51 padding ablation](B51_PADDING_ABLATION_2026-10-06.md).

## Objective and fixed comparison

The [B50 transfer](B50_TRANSFER_TRAINING_REVIEW_2026-10-05.md) fitting/development
macro-F1 gap (90.29% versus 52.12%) motivates testing reduced target-adaptation capacity.
Freeze the complete CBIS-pretrained encoder and train the same fresh target head.
This is not the earlier ImageNet-only frozen representation experiment: the encoder
contains B50 shape/margin auxiliary training. Only target encoder trainability changes.

Reuse the original B50 replicated-padding inputs, source encoder per seed, target-head
initialization, 1,270 ROI / 624 study cohort, three saved grouped splits, row shuffle,
inverse-study weights and fixed five epochs. Same head AdamW LR0.001/decay0.01,
batch eight local/context pairs, float32, no augmentation or threshold tuning.
The baseline's layer4 LR0.00001 is inapplicable because all encoder parameters freeze.
Known source-label and reference-ROI scope, minority support, study-not-person linkage,
historical exposure and absence of normal controls remain unchanged from B50.

## Actual verification

Before fitting, all original B50 full-development probabilities replay exactly.
Input/split/checkpoint hashes and initial head hashes bind the comparison. Synthetic
optimizer/reload checks pass. Three real fits total 1,930 optimizer updates; all head
parameters change, all encoder weights and buffers remain exactly unchanged, and
reloaded checkpoints reproduce probabilities exactly. No source pretraining rerun.
Protocol was saved before fitting, with final epoch five selected without validation
selection. The inherited B50 environment remains unchanged.

## Results and interpretation

Arithmetic means of three overlapping development splits:

| Metric | B50 trainable layer4 | B52 frozen encoder |
|---|---:|---:|
| Development macro F1 | 52.12% | 40.78% |
| Mass recall | 84.03% | 88.40% |
| AD recall | 22.50% | 2.08% |
| FA/Asymmetry-family recall | 50.30% | 35.48% |
| Fitting macro F1 | 90.29% | 61.46% |

AD correct counts are 1/16, 0/20 and 0/16. Two seeds predict no AD; precision is
undefined there, not perfect and not silently included in a mean. Macro F1 drops
in every seed: -8.97, -4.21 and -20.85 percentage points. Paired study-bootstrap
95% intervals from 2,000 draws: [-19.46,1.05], [-11.12,1.83], [-31.84,-7.42] points.
These are exploratory repeated-development intervals, not independent clinical proof.

The smaller fitting/development gap did not improve the task: minority recognition
collapsed. Possible head underfitting at five epochs remains a competing explanation;
this test does not rule out all frozen-encoder strategies. It does rule out promoting
this exact fixed-budget candidate. No posthoc training-duration rescue was attempted.

## Decision and next action

Reject B52 as a replacement. B51 and B52 add six real fits without improving the
preferred tradeoff; preserve B50 unweighted transfer as the research comparator.
Keep partial target adaptation; do not freeze everything or aggressively rebalance
merely to reduce a training gap. No clinical adequacy claim follows B50 retention.

The descriptive error audit in `P/b51-error-audit` retains mixed-source cases and
correct/missed/false-AD examples for targeted morphology review. Extreme padding is
not the dominant observed AD error explanation. Next prioritize verified minority
AD/reference support and a single native-resolution/context comparison; do not
chain uncontrolled changes or keep sweeping epochs on exposed development cases.
Any future source-AD augmentation must first pass its own geometry and semantic
mapping checks rather than inherit the standard-mass source cohort's readiness.

## Resources, artifacts and qualification

19.37 seconds actual replay/training/evaluation/checkpoint work; peak GPU allocation
about 433.8 MB. No input restaging needed. Not a whole-study CPU timing. Job exit0,
no owned fitting job remains. GPU free memory at closure was 6,096 MiB versus
12,147 MiB before the run because concurrent usage changed; do not claim full device
memory restoration. No other service was interrupted.

Protected artifacts: `P/b52-frozen-transfer-20261005/` with `protocol.json`,
`results.json`, `summary.json`, `predictions-private.json`, `paired-bootstrap.json`,
baseline replay, synthetic evidence, training log and closure. Linux research weights
are in the matching R directory. P/R roots are defined in B50. Primary independently
computed paired counts/intervals with `P/b52-paired-bootstrap-20261005.py`.

Results SHA256: `a456f4ff946b9d49f2190461822215a41b828780d5059d2f5a1c0354f78f9f3a`.
Actual model update/reload and data checks passed. No clinical reference adjudication,
independent test, live GUI acceptance or deployment took place; runtime was unchanged.
