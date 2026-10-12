# B95: exact peak extraction acceleration (OPT-51)

## Contract
Continue B94 CPU optimization without changing candidate thresholds, model weights,
native resolution, contextual tiles, preprocessing, or skin filtering. Comparator:
B94 complete same-case dual request, 193.8967 seconds. This is a performance replay,
not an independent clinical accuracy or sensitivity experiment.

## Method
Vectorize singleton regional maxima and their equal-valued nonmaximum-neighbor
shoulder checks. Multi-pixel plateaus retain the original centroid, tie breaking,
dilation and shoulder logic. Candidate sorting and physical-distance greedy NMS
are unchanged. Preserve the frozen original helper and its hash; store an exact
reference copy in source and package the accelerated helper separately in an
immutable calcium-b95 bundle. No quantization, resizing or points discarded for speed.

## Verification
The isolated Breast CPU Python runtime is needed (source .venv lacks scipy).
Three unittest methods cover 320 randomized masked/discrete configurations,
plateaus, shoulders, boundary/tie distance and invalid arguments. Import failed
before the new helper existed; all pass after implementation. This initial red
run is missing-implementation evidence, not a behavioral regression reproduction.
Full native peak arrays and final point arrays must match exactly, including order
and score. Target-host results and final parity receipts follow below.

## Evidence and boundaries
Protected local evidence: C:/AI-PACS-Datasets/breast-review/point-review-20261003/b95-peak-speed-20261008.
Target-host evidence: D:/Eagle Eye Server/staging/breast-b95-20261008.
No patient identifiers or coordinates are included here. Current clinical service
remains r4. B93 source GUI and clinical-output acceptance/activation gates remain;
a successful performance experiment does not complete those gates.

## Measured target-host result and decision
All 659511 ordered intermediate rows (x, y, residual score) were exactly equal on
four frozen native inputs: 137451, 150097, 181001 and 190962. Reference extraction
seconds: 14.078, 15.297, 18.484, 19.437; accelerated: 2.453, 2.656, 3.125, 3.125.
The extraction-only comparison totals 67.297 -> 11.359 seconds (83.12% reduction).

Full parallel tissue/calcium request: **193.8967 -> 139.4573 seconds**, a further
28.08% reduction relative to B94 (1.390x). Relative to B93's 555.5265 seconds, total
reduction is 74.90%, about 3.98x faster. Both branches completed. All 334 support
points (50,55,134,95), their order and scores, and all skin-filter removal counts
are exactly equal. Internal calcium elapsed time was 125.453 seconds. No missed
or added point and no score drift were observed on this replay. This preserves
outputs on the tested case; it is not universal accuracy or throughput evidence.

Accept B95 as the Developer performance candidate. Preserve B94 and B93 bundles.
445 sealed files are bound by the calcium-b95 manifest SHA256:
889df3e37ca6e7991e6190fe887f0ad8f16bb34fb7a7a1055959c51209ff10c6.
Local 64 integration guards and 3 exact-peak unittest methods pass; 517 mirror pairs
match. Target-host checks and final complete inventory parity are retained in
protected receipts. Two unrelated local append-only history/manifest changes were
inspected against the server and preserved during reconciliation, not reverted.

Next action: existing source GUI/clinical review and controlled activation gates
from B93. Additional optimization should target measured neural cost only after
these results; do not trade sensitivity for a lower latency number. No service
restart, production selection, installed application or GPU change was made.

Final checks: Razi also passed 64 integration guards and all 3 peak-equivalence
unittest methods. Detection and classification each retain 4 rows; every field
matches B94 except the expected per-run output image paths (`png_full_path` and
`lesion_image`). Source inventory contains 8186 files with no missing/different
entries at reconciliation; final drift and sealed asset receipts are retained.
