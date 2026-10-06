# B54: Source, input-detail and physician-reference readiness

Date: 2026-10-06. Implements B53 gates 1 and 3 in parallel. No new model fit,
threshold selection, clinical reference replacement or deployment. B50 remains the
research comparator; B50-B52 still total 18 fits. Read with the
[current state](../BREAST_AI_DEVELOPMENT.md) and [B53 decision](B53_EVIDENCE_REVIEW_AND_NEXT_GATES_2026-10-06.md).

## CBIS AD source readiness

| Gate | Observed count |
|---|---:|
| Original pure legacy AD TRAIN descriptors | 80 rows |
| After union Mass/Calcification publisher-test person reserve | 73 rows / 46 people |
| Actual full/crop/mask decoding and geometry QC | 73 / 73 passed |
| Historical nontraining reserve removed | 8 rows / 4 people |
| Source-label research candidates | **65 rows / 42 people / 62 full images** |

All candidate triplets were decoded and checked for grayscale validity, geometry,
foreground size and bounds. Original-JPEG alternatives were inspected; no mask
resizing or source repair was required. Hashes bind the source files. No identical
full-file hashes occurred across different people; pixel-level near duplicates
remain outside that claim. Seven eligible AD people overlap B50 source people:
preserve person grouping across tasks rather than treating the new rows independently.

These are legacy AD descriptor positives, not newly adjudicated modern clinical AD.
Other clinical targets remain unknown. Do not create normal or Mass-negative labels
from absence of descriptors. JPEG masks contain 15-18 intensity levels and remain
provisional region references. Basic visual inspection of 12 local/context pairs
identified brightness variation and a prominent clip-like radiopaque object for
review, without changing labels. The 65 ready rows here are unrelated to B50's
65 excluded standard-mass mask-geometry failures.

Protected evidence under `P` and `R`: `b54-cbis-ad-readiness-20261006/`.
The ready manifest SHA256 is
`77cde7fffab470121ef1a43ce7e278c4a364fc79e9d2364746062ba6372b7300`.
Aggregate, candidate audit, protocol and visual-limit receipts accompany it.

## Native input-detail audit

Selection was frozen before pixel analysis: 24 examples from 24 distinct studies,
eight per source class, drawn from the intersection of all three fitting partitions.
All source hashes were verified. No holdout examples selected the input setting.
Runtime was 12.736 seconds; no fitting occurred.

Whole-cohort AD local crops have median longest dimension 220 pixels and 46.0%
are downsampled at 224. Context crops have median longest dimension 433 pixels
and 92.0% are downsampled at 224. In eight fitting AD context crops:

| Reconstruction proxy against native input | 224 | 384 | 448 | 512 |
|---|---:|---:|---:|---:|
| Gradient cosine | 0.53427 | 0.77729 | 0.84690 | 0.86485 |
| Normalized reconstruction RMSE | 0.11148 | 0.07916 | - | - |

Median high-intensity clipping fractions were 0.00973 locally and 0.00636 in context.
Three fitting AD visual comparisons were inspected: larger context crops visibly
lose fine texture at 224; small native crops gain little from larger tensors.
These are image reconstruction proxies, including retained noise, not diagnostic
accuracy, AD recall or proof of clinical morphology preservation.

One justified future ablation is **local224 unchanged, native-source context384**
with the same 2x context extent, compared with B50 context224. Regenerate directly
from DICOM; do not upscale cached224 images. Match initialization, splits, source
supervision and target adaptation budget. Do not simultaneously alter contrast,
padding or training labels. Combined branch pixel area is approximately 1.97x;
that arithmetic is not measured GPU or CPU latency.

Protected evidence under `P`: `b54-input-detail-audit-20261006/`, including aggregate,
geometry summary, locked protocol/selection, private measurements and interpretation.

## Physician reference review

A deterministic shuffled pool contains 24 distinct common-fitting studies, eight
per source class, selected without model-output filtering. All 24 have a same-breast
opposite-view companion. The 96 PNGs preserve native spatial dimensions, with 8-bit
display normalization; these are not original DICOM intensity values. Companion
pairing is label-blind and does not establish lesion
correspondence between views. Fitting-only selection prevents this review from
being presented as independent model evaluation.

The review records dominant appearance, coexisting findings, certainty, view evidence,
region adequacy and notes independently of the source label. Source labels are hidden
initially. Unknown/indeterminate is allowed; no default normal or automatic training
truth. First blind responses and later source-label exposure must remain distinguishable.
No physician adjudication has yet been received for this new pool.

Protected selection under `P`: `b54-physician-review-20261006/`.
Selection SHA256:
`61bf3fb53db22e970fa5b53d5c353738dd1e5a60251101cc84545b62f7fc3b5d`.
The local entry point is `P/b54-physician-review-20261006/bundle/index.html`.
Embedded bundle data allows local-file loading without a server. Node syntax and
seven core logic guards passed; all 96 asset hashes match. The UI includes fit/native
zoom, display controls, guarded completion, autosave and versioned JSON export/import.
Actual model predictions are unavailable and explicitly shown as such; source-label
reveal is not a fabricated model-disagreement overlay.

**Acceptance limitation:** the actual hidden server launch on loopback port 18920
was rejected by automatic execution policy. The primary agent's local-file browser
open was then rejected because browser URL policy permits only HTTP/HTTPS. No alternate
server/browser bypass was attempted. No working HTTP URL or interactive browser pass
is claimed. The physician can open the local HTML manually; interactive image rendering,
autosave, export/import and feedback collection remain unverified in a live browser.
Delivery hashes and automated-test status are in the protected delivery receipt.

## Active continuation and stopping rules

1. Obtain the prepared morphology review, retaining original source references and
   versioned physician responses separately. Mixed findings and uncertain judgments
   are useful evidence; do not force them into a mutually exclusive clinical truth.
2. Define a task-matched AD auxiliary target using the 65 eligible source rows,
   explicit unknown-label masks and preserved person reserves. The source positives
   alone do not define a valid clinical binary classification task or its negatives.
   Compare against B50 with a compute-matched control before attributing any gain
   to AD content. Unadjudicated runs must remain source-label research.
3. Separately test native context384 once the fixed protocol and operating tradeoffs
   are recorded. Do not combine this with new supervision in the first comparison.
4. Preserve genuinely unused person groups for later whole-image detection, normal
   specificity and CPU serving qualification. These readiness audits answer none of
   those endpoints and do not increase the documented classification score.

Retain B50 until paired class-specific evidence justifies a replacement. Stop failed
protocols rather than rescuing them with thresholds selected from final-test cases.
Calcium localization and its prior physician-approved edge corrections remain intact.

## Documentation verification

The current-state document, ledger and this report passed English-language checks
and 83 local-link resolutions. Six review-bundle file hashes and three AD evidence
hashes match their receipts. This document verification is separate from the pending
interactive browser acceptance and does not constitute model evaluation.
