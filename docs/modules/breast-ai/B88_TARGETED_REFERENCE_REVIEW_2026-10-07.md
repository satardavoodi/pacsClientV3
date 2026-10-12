# B88: Targeted reference review prepared from actual candidate errors

Status: selected and rendered24 native-source review regions; physician reference
pending. No new fit, new accuracy or deployment. This is the next concrete B84
readiness deliverable, not another model comparison.

## Decision and completed action

Prioritize reference correction over another small fit on assumed negatives.
Selected6 candidates from each publisher-normal score band >=0.50, [0.45,0.50),
[0.40,0.45), plus6 lower-score candidates overlapping a reference at IoU0.3.
All24 regions come from distinct studies; patient independence is not established.
Selection prioritizes score within each stratum, so it is intentionally enriched,
not a random accuracy sample. No region is automatically training eligible.

Decoded the original DICOMs on Windows A100, verified native dimensions against
the manifest and applied modality rescale/polarity correction. Saved native float
context crops, three static percentile display variants per region and a separate
full-primary-view context. No model score or publisher category is drawn on the
review images. Static displays do not replace interactive diagnostic windowing;
uncertain remains a valid response. No new web server or browser workaround used.

First visual layout check found a conspicuous bounded structure in a purported
normal candidate. This is a reference concern, NOT an adjudicated mass or model
true positive. It makes physician review particularly important before using
publisher-normal candidates as hard negatives. Previous counts remain marks on
publisher-normal images, not127 clinically proven false findings. No reference
label has been changed from agent visual inspection.

## Artifacts and verification

Protected local root:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003/b88-targeted-review-20261007`.
Entry: REVIEW_INDEX.md. review/ contains24 region images,24 full-view context images,
24 native float crops, instructions and an empty response template. Selection and
render receipts retain coordinates, source hashes and source categories privately.
Scripts b88_prepare.py and b88_render.py remain in the protected parent directory.
Windows staging: `D:/Enhanced_Mammo_B88`. No clinical production changes.

Verified24 rendered records,48 PNG files and24 signal arrays after local retrieval.
One region image visually inspected for display/layout; no exhaustive diagnostic
review or acceptance of other images is claimed. Original data and annotations
remain unchanged. The Linux research asset check succeeded; no GPU job was started.

## Next action and contribution to the larger plan

Obtain real finding / normal tissue / uncertain judgments for these regions, with
appearance only when supported. Bind answers to region IDs and source versions.
Reconcile reference disagreements before constructing the E1 negative pool. Use
the selected cases for development/reference repair, not a new independent test.
If a substantial fraction are real findings, quantify that reference problem and
reevaluate the baseline on corrected references before claiming a verifier gain.
Then expand sufficient study-grouped positives/negatives and execute the equal-budget
E1 comparison. The24-region batch is a labeling audit, not enough by itself to
qualify sensitivity, specificity or malignancy assessment.
