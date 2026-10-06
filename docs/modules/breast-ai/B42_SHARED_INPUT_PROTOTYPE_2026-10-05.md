# B42: Executed shared input and cross-task descriptor prototype

Date: 2026-10-05. Status: isolated research prototype implemented and eight-case
parity audit passed. Not integrated into the clinical worker; no joint training,
new FPN forward pass or classification improvement claim.

## Implementation

P/shared_breast_research_20261005.py adds a per-image object, intended to live only
within one server job. It verifies the source SHA-256, decodes once, exposes a
read-only pixel array and source-coordinate crops, and memoizes the exact frozen
calcium input adapter. The adapter retains the legacy BitsAllocated/keepbright
normalization; unsupported polarity/rescale contracts fail explicitly rather than
silently changing the calcium network input. General DICOM support is not claimed.

The association function consumes source-bound calcium coordinates and scores,
ROI bounds and pixel spacing. It returns candidate support inside the ROI, within
a 2 mm rectangular surrounding band, support per square centimeter, mean inside
score and an availability flag. These are candidate descriptors, not independent
calcification counts, morphological types or malignancy probabilities. Empty valid
output differs from an unavailable branch. Cross-image predictions, invalid spacing,
out-of-bounds/nonfinite points and invalid ROI bounds are rejected. Caller-selected
ROIs are not silently extended or used as positive masks.

## Actual verification

P/audit_shared_breast_20261005.py ran under Linux system Python on all eight prior
physician-reviewed cases. The shared path performed eight image decodes; additional
independent legacy reads were deliberately performed as comparison references.
All 18 ROI crops exactly match original pixel slices. Repeated calcium input access
returns the same cached array and exactly matches legacy normalization.

Previously saved probability maps and peaks were verified against their recorded
hashes; accepted full-image counts and displayed coordinates exactly reproduce the
prior manifest. This is cached-output replay with identical inputs, not a fresh FPN
execution or proof of clinical sensitivity. Missing-versus-empty and wrong-source
guards passed on each ROI. No masks/thresholds/weights were changed, and no skin
filter was newly enabled. The read-only array flag prevents ordinary accidental
writes; it is not a security boundary against a deliberately mutating caller.

Audit elapsed 5.69 seconds including duplicate reference reads and cache hashing;
do not report this as a speedup or serving latency. No GPU or training was used.
Module SHA-256: 6a58a9744193d7cc3f44f6c398b7ff3898546ee5380b02a0b341716b5019cc53.
Evidence: P/shared-breast-audit-20261005/summary.json and features-private.json;
remote copies under R. Patient identifiers and descriptors stay outside the repo.

## Limits and next executable gate

The 18 boxes are physician calcium-review regions, not adjudicated soft-tissue
Mass/FA/Asymmetry references. They must not be used to claim a cross-task classifier
gain. The B38/B41 cohort has typed soft-tissue ROIs but not yet the corresponding
source-bound outputs of this calcium branch. Generate those outputs after auditing
the calcium checkpoint's training exposure; use fitting-only or cross-fitted upstream
predictions as appropriate. Ground-truth calcium labels are never inference inputs.

Then fit two matched classifiers: B41 compact comparator versus the same inputs plus
actual calcium-context descriptors. Retain explicit missingness and preserve mixed
findings. Compare per-class recall/PPV, calibration and paired Mass losses on fixed
development splits; obtain separate independent qualification. Do not fit on the
eight reviewed cases merely to complete a joint-model demonstration.

For the other direction, keep mass/FA context descriptive until a calcium ablation
shows benefit. Never suppress calcium merely because no mass is detected. Shared
backbone or reciprocal model adaptation is deferred until these independent branch
comparisons preserve both endpoints. Integration into authenticated Eagle Eye still
requires production-source parity, applicable regression/mirror and GUI gates.

Decision: retain the tested shared-input/association prototype as the preparation
layer for the next paired experiment. Accuracy and end-to-end efficiency remain
unmeasured. No clinical model replacement occurred.
