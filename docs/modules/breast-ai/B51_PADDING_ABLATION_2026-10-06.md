# B51: Target padding ablation and AD error audit

Report date: 2026-10-06 (Asia/Tehran). Artifact IDs retain their 20261005 creation
suffix across midnight. Completed: three real matched fits; no production change.
Comparator: [B50 unweighted CBIS transfer](B50_TRANSFER_TRAINING_REVIEW_2026-10-05.md).

## Hypothesis and source evidence

Test whether replicated-border padding is an avoidable shortcut in source-appearance
typing. B50 target cohort, labels, inputs, grouped splits and clinical limitations
are unchanged: 1,270 ROIs / 624 studies; 923 Mass, 87 AD, 260 FA/Asymmetry-family.
No normal reference set, clinical relabeling or autonomous detection is introduced.

Protected `P` is the root defined in B50. Artifacts: `P/b51-error-audit`,
`P/b51-padding-masks-20261005` and `P/b51-padding-20261005`.
Masks derive from saved native crop geometry and exact resize rounding, not intensity.
All 2,540 local/context padding footprints reconstruct exactly; seven synthetic
shape checks include square, odd and extreme aspect ratios. Content and original
NPZ stay unchanged. Mean padding is 16.44% local / 18.03% context, maxima 80.80% /
85.27%; 32 branches need no padding, 1,198 have unequal one-pixel sides.

The concurrent descriptive error audit does **not** support extreme padding as the
main AD failure mechanism. Only one of 87 AD rows exceeds 50% local padding, and
none of the held-out AD rows does. Median local padding is 13.39% Mass, 13.84% AD,
17.63% family. Median native short sides: 220/188/275 pixels. Context truncation and
moderate-padding error associations reverse across seeds; small strata cannot prove
causality. Nine deterministic correct/missed/false-AD local/context pairs show coherent
tissue, no gross blank/unrelated image, and brightness/padding variation in both correct
and incorrect cases. This is input sanity, not radiologist adjudication of source labels.

## Controlled implementation and verification

Only target padding changes: RGB ImageNet normalization first, then padding positions
become exactly zero in normalized space. Raw black masking would be a different
intervention and was not used. Source CBIS auxiliary pretraining still uses B50
replicated padding, so this tests the target adaptation transition only.

Each seed reuses its B50 auxiliary encoder and identical new target-head initialization.
Same local/context 224 input, fitting groups, row shuffle, inverse-study weights and
AdamW head LR0.001/layer4 LR0.00001/decay0.01. Batch eight pairs, five fixed epochs,
float32, frozen earlier blocks/BatchNorm running buffers. No augmentation, threshold
selection, extra epochs or validation-selected checkpoint.

All three B50 transfer checkpoints first reproduced their complete development
probability arrays exactly. Independent mask-geometry recomputation passed. Synthetic
guards verify exact neutral padding, bitwise unchanged normalized content, actual
optimizer updates and checkpoint reload. All three real fits pass nonzero intended
parameter delta, unchanged BatchNorm and exact reloaded-probability checks.

## Observed results

Means of three repeated development splits, not independent pooled patient estimates:

| Metric | B50 replication | B51 neutral padding |
|---|---:|---:|
| Macro F1 | 52.12% | 51.21% |
| Mass recall | 84.03% | 85.75% |
| AD recall | 22.50% | 17.50% |
| Family recall | 50.30% | 48.66% |
| AD average precision | 46.59% | 36.64% |
| Development log loss | 0.6814 | 0.6445 |

Macro-F1 delta by seed17/29/43: +2.81/+5.87/-11.40 percentage points.
Paired study-bootstrap 95% intervals (2,000 draws): [-3.84,10.17], [-2.47,12.97],
[-23.02,2.31] points; all include zero. AD correct counts change 4->5 of16,
1->3 of20, and6->1 of16. In seed43 all six previously correct AD rows are lost and
one previously missed row recovered. Better mean log loss does not cancel the
subtype-recognition regression. No threshold tuning or clinical improvement claim.

## Decision, resources and next test

Reject neutral target padding as the preferred B50 replacement. This result does not
prove replicated padding universally superior or neutral padding harmful in every
pipeline; source padding was unchanged and only one protocol was tested. Preserve
B50 unweighted transfer as research comparator. Do not combine resolution, photometry
and padding changes silently to rescue a result.

Three fits / 1,930 optimizer updates; 26.37 seconds training/evaluation/replay work,
about 524 MB peak GPU allocation. No owned job remains; no service interrupted.
These are not full-study CPU inference timings. Checkpoints stay under the Linux R
root in `b51-padding-20261005`, separate from production.

The next bounded hypothesis follows the large B50 fitting/development gap: freeze the
CBIS-pretrained encoder during target adaptation and train only the same decision head.
Keep original B50 padding and the same five-epoch budget, isolating trainability.
This is different from old ImageNet-only frozen-feature experiments. Underfitting
of the head is a competing explanation; no convergence claim will follow five epochs.

## Reproducibility

Mask SHA256: `4081ed4c8b3fce4848d9ef1cb0c01e1ee27f82d53aaa1137ecd7f357a72fa13e`.
Results SHA256: `dd3a878f9395ecb4a7390542ea139214a7b9ba2a4e4a798ed6ce9770117017e5`.
`protocol.json` binds source code/checkpoints, target rows/splits/geometry and masks.
Results, predictions, summary, baseline replay, synthetic guards, training log,
closure and paired-bootstrap receipts are saved in the protected results directory.
Primary independently calculated paired counts/intervals using
`P/b51-paired-bootstrap-20261005.py`. Runtime inherited from B50; no dependency change.
Code/update/data checks are distinct from clinical and live GUI acceptance; neither
clinical qualification nor runtime GUI changes occurred.
