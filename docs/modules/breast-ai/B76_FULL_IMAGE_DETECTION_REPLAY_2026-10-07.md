# B76: Full-image detection replay

Status: completed2026-10-07; aggregate receipts retrieved and reviewed.

## Objective and frozen contract

Execute B75 on all3372 available TEST images. Reference boxes are evaluator-only;
the detector sees resized complete images. Compare the Razi area filter0.002 against
the existing research removal of that filter, using identical raw predictions.
This is a controlled postprocessing comparison, not a new trained detector or the
dedicated native-resolution microcalcification branch. B50/B64/B65/B69 are ROI typing
models and cannot independently find lesions; their discovery is inherited from
the supplying detector unless a later stage rejects candidates.

Protected roots: local point-review research root and Windows candidate root,
`b76-full-image-20261007`; Linux candidate root with the same directory name.
Scripts stage.py, infer.py, evaluate.py. Preserve protocol.json, staging.json,
manifest-private.json, pixels512.npy, inference.json, predictions-private.json and
evaluation.json when produced. Private images/coordinates do not enter repository.

Audited October4 Razi FCOS_INFERENCE.py and CASE_DICOM_TO_PNG.py copied read-only.
Detector weight SHA256 freshly matches the live-revision file:
`9f8746666dccb5e22840a8bfdcb22b9eacb1e3a4b31b61b6b2ec6cd005679901`.
No production files, processes or settings changed.

## Cohort, processing and metrics

All3372 existing B75 image records, grouped by study. Include explicit negative
images and keep819 unboxed/uncertain images out of normal denominators. Native pixel
decode, file hashes, metadata dimensions and box bounds checked before evaluation.
Exact duplicate box coordinates merge labels. Invalid-box images excluded from
localization denominators with counts, never silently clipped. Failures retained.

Execute the verbatim pydicom pixel conversion function from the copied source via
AST extraction; unused ITK paths are not imported. Apply original RGB uint8 tensor
antialiased resize512 before float scaling. Stage one identical channel losslessly.
An initial staging attempt failed before processing because installed pydicom uses
the older pixel_data_handlers.util import; harness corrected that import only.
Original LUT behavior/warnings preserved, not silently replaced by research windowing.

Strict FCOS weights, score floor0.2, NMS0.5, horizontal-flip TTA, final threshold0.45,
original transform512; batch1 float32 GPU reproduction. Source deployed worker is CPU;
GPU/library parity and in-memory clinical-request binding remain unverified.
No fitting or test threshold search. Lower-than0.2 operating points cannot be inferred
from these saved proposals. Native microcalcification pipeline needs a separate run.

Class-agnostic one-to-one maximum-cardinality matching at IoU0.3 primary/0.5 secondary.
Synthetic guards passed for duplicate predictions, disjoint lesions, and a whole-image
box that must not match a tiny lesion. Report reference boxes found/missed, negative
image false marks and normal-image specificity; unmatched marks on positives remain
unmatched, not automatically adjudicated clinical false positives. Study-bootstrap
recall intervals2000 draws, fixed seed76. Histological malignancy is not the endpoint.

No patient-level independence or historical Razi training-exposure claim. TEST already
exposed in B72/B74; this measures full-image localization on a shared benchmark.
BI-RADS2 annotations absent; the endpoint does not cover every benign finding.

## Completed results

All3372 images decoded and inferred; zero input failures. Five images have invalid
reference boxes and are excluded from localization metrics. Staging found363 unique
valid boxes overall; excluding all annotations on those five images leaves362 boxes
in290 positive images.2258 explicit negative images enter the normal denominator.
The819 unresolved/unboxed images remain outside these positive/negative denominators.

| Metric at fixed score0.45 | Razi source filter0.002 | Existing research filter0 |
|---|---:|---:|
| Reference lesions matched at IoU0.3 | 161/362 (44.48%) | 161/362 (44.48%) |
| Reference lesions not matched | 201 | 201 |
| Recall at IoU0.5 | 29.83% | 29.83% |
| Negative images with any mark | 1081/2258 (47.87%) | 1081/2258 (47.87%) |
| Normal-image specificity | 52.13% | 52.13% |
| Marks on negative images | 1305 (0.578/image) | 1305 (0.578/image) |
| Unmatched marks on positive images | 149 | 149 |

Study-bootstrap95% recall interval38.52-50.62% for either path. Per-reference-label
class-agnostic localization: Mass112/201, FA27/40, Asymmetry9/15, AD1/20,
Suspicious Calcification17/80. Labels can coexist on one box; these counts must not
be summed as disjoint lesions. Correct predicted type is not required for these hits.
An unmatched reference may represent absent detection or inadequate box overlap;
the IoU0.5 drop supports inspecting geometry as well as actual misses.

Staging1102.71s; GPU inference81.70s for3372 images, excluding decoding/transfer and
classification. Peak allocated GPU memory195830784bytes. Torch2.11.0+cu130,
torchvision0.26.0+cu130, A10040GB, float32. This is not Razi CPU response time.
Manifest SHA256:cc9baaec7c483c4c1d4eddb07fe68151bb9cac1828cfca2a1d1dca12a3ee5ecd.
FCOS source SHA256:aace508a4264f76b79a4848b02a3bf60674a6d2550b226f12e85ebb4bed0bd83.
Available cohort has zero study/image identity overlap with B50 training rows;
historical Razi exposure and patient linkage remain unverified.

Decision: removing the small-box filter alone provides zero measured gain here.
This does not evaluate all research routes or the dedicated high-resolution calcium
branch. Do not equate the prior96.69% reference-ROI positive coverage with detection.
Next inspect representative missed/unmatched boxes against native reference geometry,
then add the frozen native-resolution calcium pipeline with a prespecified cluster
mapping on the same full-image cohort. No threshold tuning on these TEST results,
promotion, clinical deployment or claim of live-service parity.

## Historical execution notes

Windows native-image staging was launched. A100 free memory12147MiB observed before launch;
no services evicted. GPU inference and evaluation follow validated staging completion.
No promotion or GUI acceptance. Completed receipts now supply results above.

Strict checkpoint load and actual synthetic GPU forward passed. At the latest
interim progress observation900/3372 images were staged in296s. `continue.ps1` waited
for the staging receipt, then transferred the staged full-image tensors and
private evaluation manifest between the authorized hosts, executes infer.py and
evaluate.py, and retrieved aggregate receipts. It stops on transfer/inference errors;
there is no deployment or scheduled monitor. `completed.txt` is written only after
both runs and receipt retrieval succeed. A launch is not completion.
