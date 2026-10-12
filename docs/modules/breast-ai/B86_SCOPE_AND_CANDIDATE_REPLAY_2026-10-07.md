# B86: Review scope binding and candidate baseline replay

Status: executed local artifact audit and saved-prediction replay. No new inference,
training, physician adjudication or production change. Continues B85/B84 readiness.

## Actions and results

Bound all24 B55 case IDs through the inference source ROI index to B50 source rows,
image hash records and recorded split memberships. All24 reference rectangles
match the original staging conversion (integer left/top, ceiling right/bottom).
The initial strict float-coordinate equality check failed; inspected B54 staging
code explained the rounding. The audit was corrected to reproduce that documented
conversion, not to change source coordinates. All24 have recorded source hash
bindings; source DICOM bytes were not reread or rehashed in this local audit.
All24 inference records explicitly mark fitting exposure. They cannot qualify as
independent confirmation cases. Semantic scope for additional/coexisting lesions
is still distinct from successful geometry binding.

Inspected B81's TRAIN development manifest and saved predictions. At its documented
score0.4 and area0.002 settings, a fresh count replay reproduced:

| Endpoint | Result |
|---|---:|
| Images in manifest | 128 |
| Reference boxes matched at IoU0.3 | 20 / 34 |
| Explicit publisher-normal images | 83 from51 studies |
| Marks on those normal images | 127 |
| Normal images with any mark | 65 / 83 |
| Unknown images excluded from normal denominator | 13 |

These are repeated baseline counts, not new improvement. The cohort is selected,
CC-only, development-exposed and does not prove clinical specificity. Per-image
normal labels do not mean every associated study is wholly normal. The remaining
14 unmatched references cannot be recovered by a downstream verifier at this fixed
candidate contract; proposal/geometry misses must remain in end-to-end reporting.

## Persisted artifacts

Protected root: `C:/AI-PACS-Datasets/breast-review/point-review-20261003`.
Executable audit scripts: `b86_scope_audit.py`, `b86_candidate_audit.py`.
Outputs in `b86-scope-audit-20261007`: case-bindings-private.json,
normal-pool-private.json, normal-candidates-private.json, receipt.json and
candidate-replay-receipt.json. Source hashes bind the input artifacts. The127
candidate records retain study/image/box/score provenance and are NOT imported as
physician-confirmed negatives. Original records and predictions are unchanged.

## Decision and next work

Technical ROI provenance is verified for the24 reviewed cases, but additional-lesion
scope and exact clinical targets still need reconciliation. Do not discard useful
dominant-field consensus merely because other exported fields conflict.

The127 publisher-normal candidates provide a concrete review/sampling pool for E1.
Next group it by study and score, audit exposure against all positive references,
and prepare only the unresolved high-value region review. Reuse existing display
and review infrastructure subject to its recorded execution restrictions; do not
reinterpret old calcium-negative review as tissue-negative verification. Existing
publisher labels can support a separately declared weak-reference pilot, but that
would not answer the planned physician-verified hard-negative experiment.

No training starts from automatically interpreting these127 marks as adjudicated
normal. E0 count verification is partial: real input replay, updated clinical
references, patient-level grouping and end-to-end CPU parity remain outstanding.
Four synthetic matching checks passed (duplicate predictions, oversized box and
both empty-input directions). Matching computes maximum-cardinality counts;
identity tie-break parity with B76 was not tested or claimed. No clinical GUI pass.
