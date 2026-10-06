# B63: Frozen supplemental-ROI replay and feedback reconciliation

Date: 2026-10-06. Status: evaluation-only diagnostic step; no fitting or deployment.
Implements Stage 0 of B62 in part. It does not claim Stage 1 training has run.

## Objective and identity

Test the unchanged B50 unweighted transfer classifiers on the four new view-specific
physician rectangles, rather than attach original-reference predictions to them.
The owner describes these additional findings as benign masses. These are reviewed,
fitting-exposed studies, not an independent detection or classification test.
Four rectangles across two cases are not four established independent lesions.

Protected artifacts: P/b63-supplemental-replay-20261006 and the matching directory
under R, as defined in BREAST_AI_DEVELOPMENT.md. Preparation/replay/reconciliation
scripts are P/b63-prepare.py, P/b63-replay.py and P/b63-reconcile.py. Source exports
are preserved under feedback-snapshots; coordinates and identities stay protected.
The private replay records exact script/input/checkpoint hashes and probabilities.

## Method and verification

Decoded source-bound float32 native assets and valid-pixel masks; verified signal
hashes and geometry. Used the original whole-image valid stride4 percentile1/99
normalization, local and 2x context, float32 bilinear antialias aspect-fit224 and
replicate padding. Display window settings are not model inputs.

Reconstructed two original reference inputs against saved B50 tensors. Initial
checks detected missing explicit float32 conversion and the use of rounded display
rectangles. Corrected both before inference: exact source annotation coordinates
are required for the reference replay. Final maximum absolute input discrepancies
were 1.7881393432617188e-7 and 1.1920928955078125e-7, below the original 1e-6 gate.
No tolerance was relaxed to pass this check.

Loaded transfer seed17/29/43 checkpoints with weights_only=True and verified each
against the original B50 result hash. Strict state loading, finite normalized
probabilities and exact repeat predictions after checkpoint reload passed.

## Results and limits

All three classifiers predicted Mass for all four supplementary view regions:
12 of 12 checkpoint-region outputs. Uncalibrated Mass probabilities ranged from
0.825 to approximately 1.000. This agrees with the physician's supplied appearance
description. It is not an estimate of population sensitivity, calibrated confidence,
BI-RADS accuracy or autonomous localization. These new regions do not demonstrate
improvement over B50 because B50 itself produced the result without retraining.

CPU replay took 2.25 seconds for the script's three checkpoint loads/inference/reload
checks after staging. This is on Linux A100 host CPU with two Torch threads; not Razi
hardware, not full mammography latency and not GPU inference. Staging, native decoding
and full-image detection are outside that timing. Fresh GPU inventory showed about
12 GiB free; no active service was stopped and no GPU training job was launched.

## Feedback reconciliation

Validated three feedback snapshots against the original case and inference hashes.
Their union preserves 24 cases, with 23 finished in at least one snapshot. No completed
case was erased by the later 19-record partial snapshot. Every alternative survives.

Conservative field comparison flags 17 cases for reconciliation: coexisting-label
differences in 16 cases, certainty in one, correctness in one (fields may overlap).
Coexisting differences include populated lists versus empty lists; an empty exported
list does not establish deliberate retraction of earlier findings. These are export
state differences, not 17 proven clinical disagreements. Dominant appearance has no
cross-snapshot difference in the checked fields. The previously noted reference-ROI
scope conflict remains separate from export consistency.

No feedback was imported into training; no unknown tissue was labeled negative.
Detailed versions/field alternatives are saved in feedback-reconciled-private.json
and feedback-conflicts-private.json, with an aggregate receipt. Do not replace these
with a last-file-wins merge or ask the physician to repeat all completed reviews.

## Decision and next discriminating action

Retain B50. The additional benign findings are classifiable as Mass once their ROIs
are provided, supporting the distinction between missing reference boxes and typing
failure. No new detection conclusion is justified.

Next prepare the B62 matched native-context ablation on unchanged publisher labels
and frozen groups; keep unresolved physician feedback out of fitting. Complete the
B50 retrospective run card and verify native staging parity and optimizer/reload
guards before that experiment. B63 neither changes source labels nor resolves all
Stage 0 reference questions. Shape/margin and region-supervision changes remain separate.

Validation: real source-input parity, 3 checkpoint hash checks, exact checkpoint
reload predictions, probability checks, and feedback provenance/union checks passed.
No application runtime changed; no GUI pass or clinical qualification is claimed.
