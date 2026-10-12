# B94: CPU latency reduction without dropping candidate points

## Objective and baseline (OPT-51)
Owner target: reduce the approximately nine-minute four-image analysis to about
one third. B93 complete dual request: 555.5265 seconds. Its calcium receipt records
544.265 seconds (0.859 model loading; 134.001, 133.781, 137.516, 138.109 per image).
The tissue engine request/result timestamps span 55.933 seconds, including detection,
classification and output rendering. This is a filesystem-based stage bound, not a
new stopwatch benchmark. Classification CSV/detection CSV timestamps were rewritten
during artifact publication and must not be used as inference timings. The delay
is predominantly calcium localization, not mass classification.

## Exact computation reduction
The frozen physical candidate extraction remains unchanged: residual Gaussian sigma
3, threshold .006, physical NMS .1 mm, valid mask >.01. On all four retained inputs,
520 contextual 512-pixel tiles were previously evaluated. Only 191 final-owner tiles
contain candidate points (42,43,51,55 of 130 per image). There are 137451,150097,
181001,190962 physical candidate points before neural scoring; none is removed by
the scheduling optimization. No input is resized or downsampled.

Sparse scoring first assigns every candidate to the last tile that writes its pixel
in the existing full-map traversal, including overlapping final edge tiles. It then
runs exactly those original contextual tiles and samples their same coordinates.
This preserves the previous boundary convention, tile input, network, weights,
cutoff and air-edge filtering. It skips computation with no consumer, rather than
changing the definition of a lesion. The full-map reference remains available.

## Verification and experiment contract
Eight new tests failed before implementation and pass afterward: exact sampled
scores against full-map execution, final-edge overlap, empty-candidate zero network
calls and invalid coordinate rejection. A tile-context-dependent deterministic
network is used so wrong last-writer selection cannot pass by returning identical
pixels from every tile. The combined local suite currently has 64 passes.

Target-host experiment uses the same four B93 native sources, verified identities,
MONOCHROME1 preprocessing, frozen model/helper assets, peak thresholds and output
coordinate convention. A four-thread CPU candidate is compared against B93's two-
thread full-map receipt. The comparison must report missing/extra points, shared
score differences, edge-removal agreement, exact elapsed time and threads. This is
a development performance replay, not an independent accuracy test. Source and
protected comparison hashes are retained; no private coordinates are committed.

Decision and final timing will be appended after the target-host run. No clinical
service, installed client, production model selection or threshold has changed.
Protected evidence: C:/AI-PACS-Datasets/breast-review/point-review-20261003/b94-calcium-speed-20261008
and D:/Eagle Eye Server/staging/breast-b94-20261008.


## Four-thread target-host calcium experiment
The same four-image CPU run completed in 188.391 seconds around the worker call,
including imports/integrity/loading overhead; the worker's model elapsed time was
180.218 seconds versus B93's 544.265 seconds: 3.020x faster. Per-image totals were
39.891, 40.484, 47.953 and 51.125 seconds. Peak extraction took 14.421,15.875,18.766,
20.109 seconds; neural scoring took 22.125,21.672,26.250,28.094 seconds. The skipped
tile counts match the scheduling audit. Four CPU threads were used instead of two;
no GPU, quantization, resolution reduction or threshold change was used.

All 334 final support-point coordinates, order-independent identities and scores
match the baseline exactly: zero missing, zero added, maximum score difference 0.0.
Edge-removal counts match in all four images. This is output preservation on the
replayed case, not evidence that every point is clinically a true calcification or
that equality/generalization has been established on all scanners and inputs.
Candidate source SHA256: 5837703f8fddce874dcde2f6c0dd1dc90b88f62eac5e7bba577281e53f38378a.
The speedup includes both sparse scheduling and the thread change; no separate
causal speedup for each intervention is claimed. A full dual-request replay is
required before assigning this calcium-only measurement to the complete workflow.

The new immutable calcium-b94 bundle stores its bounded four-thread budget in the
manifest; the server validates a 1..4 integer before launching it. Prior B93 bundles
remain intact. Developer routing selects B94 only; the clinical r4 service remains
unchanged. The final baseline comparator is the same B93 experimental pathway,
not an accuracy comparison with the original deployed Razi model.


## Complete dual-request result and decision
The same native four-image request completed both branches in 193.8967 seconds,
versus 555.5265 seconds for B93: 2.865x faster, a 65.10% reduction (34.90% of the
previous time). This is approximately one third, not a literal 3.000x whole-request
speedup. Both classification and calcium completed. All four output point lists
match in coordinates, order, score and edge-removal counts: 50,55,134,95 (334 total).
No point was added or lost. This stopwatch measures server computation/validation;
it does not measure client queue, network, artifact transfer or GUI display latency.
This is one same-case comparison, not a p95 serving-time guarantee or clinical
accuracy/generalization result.

Accept B94 as the improved Developer performance candidate. Retain original
full-map reference and B93 immutable bundles for comparison/rollback. Do not change
FCOS/classification weights or thresholds, retrain, downsample or quantize to obtain
this improvement. Further speed work is optional; this request's approximate
one-third target is reached on the tested case. Prior clinical MONOCHROME1/GUI and
controlled service activation gates remain open. Active Razi service remains r4;
no installed client, service selection or production flag was changed.

Local and Razi each passed 64 focused tests (three existing dependency warnings).
All 517 plugin mirror pairs match. Calcium-b94 has 444 sealed files; the manifest
SHA256 matches on both hosts:
e57dd05c07da823a92290f25b089479c671368fb6dc714c6ca86f83fb0d33f4d.
Final complete source parity and local drift checks are retained in the protected
B94 receipts. Performance documentation extends OPT-51, not a disconnected plan.
