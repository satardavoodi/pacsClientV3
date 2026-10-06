# B25 eight-case physician/model point visualization

Date: 2026-10-05. Status: frozen inference and offline viewer completed; manual GUI
acceptance pending. Follows the [reporting contract](../BREAST_AI_REPORTING_STANDARD.md).

## 1. Objective and evidence identity

Owner request: show original physician points in yellow, matched model points in green,
and unmatched model points in red across all eight reviewed cases. Comparator is the
retained research head-only checkpoint, NOT the recovered initial Razi detector.
Checkpoint SHA256: `00392b28a3dc8a725a2657c810f413219df19f6fd2e0e76661891c5daed8e436`.
Original annotation SHA256: `210f402d7d3060983c744c730a20ba3e4d2b00459b596b931d77697a04262f39`.
Inference script SHA256: `ab80fa4cd97a4a8fad4e8c76629c18e86b052448085a2aa13950453728dffa18`.
Protocol SHA256: `21a8e044985ef22685810a72e70617683d8ef5e59cfb6dc855419aa371e60a51`.
Public review manifest SHA256: `0a9110b366b17f4a92a34e1b26e17146ec6342532d366301e4b7ad2b1d2c35a0`.

## 2. Cohort readiness

Eight original physician-reviewed crops contain 143 points: six TRAIN cases/75 points
and two previously exposed development cases/68 points. Group roles are shown in the UI.
Original 1024-pixel PNGs, brightness/contrast, dots and added boxes are preserved;
their display rendering is distinct from canonical network input preprocessing.
No new patient grouping or independent cohort claim is established by this operation.

## 3. Execution configuration and telemetry

Evaluation only: optimizer, learning rate, augmentation and training curves are not
applicable. Native full-image inference on six TRAIN sources; reuse two frozen development
maps. Same cutoff0.000316227766, tile512/stride256/trim128, original reconstruction,
corrected keep-bright residual proposals and0.1mm separation. No label-ROI inference.
Linux A100 fresh free-memory check,3GiB process cap, two threads. Successful run148.88s;
peak allocated GPU memory303,196,160bytes. This is research inference/export timing,
not full Razi CPU serving latency. Environment-lock completeness is not newly assessed.

Initial run stopped after a box round-trip equality guard; its output was preserved.
The guard now permits1e-9pixel arithmetic roundoff for box conversion only. Clinical
matching tolerance, points, weights and scores did not change. The successful run
repeated the first TRAIN image; it did not resume optimization or train a model.

## 4. Metric and display contract

One-to-one matching within0.2mm in reviewed support, with unchanged reference coordinates.
Yellow rings remain at every physician reference. Green marks remain at actual matched
prediction coordinates, with optional connecting lines to yellow references. Red crosses
are all unmatched displayed predictions, not adjudicated false positives. Unknown tissue
outside reviewed boxes remains unknown; duplicate nearby predictions may also be unmatched.
All matched pairs were checked to remain representable inside the displayed crops.

## 5. Interpretation

TRAIN62/75 and development54/68 are reproduced. The combined116/143 is only an overlay
inventory, not held-out sensitivity. There are27 unmatched reference points across the
eight displayed cases. No performance improvement follows from recoloring markers.

## 6. Comparison and verification

Displayed predictions partition into116 matched green and1,403 unmatched red points
(1,519 total). These are crop-visible points, not whole-image totals or false cluster
counts. Independent asset verification passed original PNG hashes, all143 reference
coordinates, added boxes, display settings, one-to-one distances and prediction partition.
Node synthetic tests passed toggles/hide, actual green coordinates, invalid pairing,
bounds and window math; actual-data checks passed8cases/143refs and exact partitions.
Embedded JavaScript syntax passed. No automated browser-rendering acceptance is claimed.

## 7. Decision and next action

Deliver the read-only comparison page for physician visual review. Original annotations
are not edited. Existing14-miss opinion and six-source annotation tools remain separate.
Physician comments inform a next experiment; no training, threshold tuning or production
replacement occurred. Initial Razi-versus-candidate benchmarking remains separate work.

## 8. Artifacts and qualification

Under protected P defined in [current state](../BREAST_AI_DEVELOPMENT.md):
`eight-case-point-comparison-20261005/` contains `offline-review.html`, `protocol.json`,
`aggregate.json`, `comparison-manifest.json`, `independent-assets-verification.json`,
viewer source/tests and readiness receipt. Private source bindings remain outside Git.
Original143 hash is unchanged. Self-contained offline delivery requires human manual
opening; no new service launch or automated file-URL browser workaround was attempted.
Reporting completeness, clinician opinion and independent clinical qualification remain
separate. This operation does not establish performance across other scanners/patients.
