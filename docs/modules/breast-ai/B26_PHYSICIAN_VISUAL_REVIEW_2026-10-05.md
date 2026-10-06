# B26 physician visual review of eight-case retained candidate

Date: 2026-10-05. Evidence: direct physician statement in this task after viewing
the [B25 eight-case comparison](B25_EIGHT_CASE_VISUAL_COMPARISON_2026-10-05.md).
Type: qualitative physician assessment, not new training or a recalculated benchmark.

## Binding and physician observation

The reviewed artifact is `eight-case-point-comparison-20261005/offline-review.html`
under protected P. Its recorded SHA256 is
`62d9c58dd866f8626d591853e828744aa47f991c23566aea7adac81db7701e15`;
manifest SHA256 is `0a9110b366b17f4a92a34e1b26e17146ec6342532d366301e4b7ad2b1d2c35a0`.
It displays the retained head-only checkpoint
`00392b28a3dc8a725a2657c810f413219df19f6fd2e0e76661891c5daed8e436`,
not original Razi weights or the rejected constrained head.

The physician reports reviewing all eight cases, judging the output very good,
identifying only one incorrectly marked skin region, and judging the other additional
model marks to be real tiny microcalcifications that had not been clicked in the
original annotation. The physician describes lesion finding as almost complete.
Record that assessment faithfully as qualitative approval of these examples.

## Consequence for reference interpretation

Unmatched red predictions are not verified false positives. The positive-region dot
annotations are incomplete for the small additional calcifications the physician now
reports. Describing all red marks as unwanted would misrepresent this review and could
drive training to suppress true findings. Do not create negative labels from those marks.

This report does not identify each added point individually. One wrong skin region is
not necessarily one wrong point. Do not calculate 1518/1519 precision or a near-100%
sensitivity from the statement. There is no newly enumerated complete positive denominator.
The original 143 references, one-to-one matching counts and 27 unmatched references
remain unchanged until explicit reference adjudication. Their clinical importance and
possible localization/reference mismatch are not individually resolved by this statement.

## Scope and verification limits

- Eight displayed cases include six TRAIN and two exposed development cases, not an
  independent screening cohort. This opinion does not establish unseen-case performance.
- The separately evaluated 16 normal images were not included in this eight-case page;
  their 4,100 inside-mask output points are not adjudicated by this review.
- Human viewing of the eight-case visualization is confirmed by the physician report.
  Automated browser testing remains unavailable; no unreported save/import interaction
  or broader GUI workflow is marked passed.
- Exact skin-error case/location is pending a targeted question. No skin mask, pruning,
  threshold or training change is justified merely by its unspecified location.
- No deployment, parameter change, point-level label merge or new fit occurred.

## Decision and next action

Retain and freeze the reviewed candidate. Replace the assumption of pervasive false
marks on these eight images with the physician's positive visual assessment. Locate
the single skin error and examine it in context before proposing a narrowly tested
correction; do not apply a blanket skin-band veto that might remove true superficial
calcifications. Separately review unseen positive and normal images with this same
frozen model. The initial Razi paired benchmark remains outstanding. Keep all-reference
point matching, physician-important-focus assessment and independent performance separate.

Original annotation SHA256 rechecked unchanged:
`210f402d7d3060983c744c730a20ba3e4d2b00459b596b931d77697a04262f39`.
