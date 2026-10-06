# B48: Distortion-aware morphology task and source-evidence manifest

Date: 2026-10-05. Status: task/source review and executable metadata preparation;
no new training, image inference, accuracy gain or production change.
Extends [B47](B47_LOCAL_DATASET_MORPHOLOGY_AUDIT_2026-10-05.md) and supersedes a
binary Mass-versus-asymmetry target as the complete soft-tissue classification task.

## Clinical contract

The owner requires distinct treatment of Mass, Architectural Distortion (AD),
asymmetry-family findings and other findings. These must not be collapsed into Mass
or normal. Localization and morphology errors remain separate outcomes.

The [ACR v2025 summary](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/BI-RADS/BI-RADS-Summary-Form-Mammography.pdf)
defines standalone AD by disturbed parenchymal architecture without a definite
visible mass. Spiculated mass margins must not automatically become standalone AD.
Represent local evidence and uncertainty first, then reconcile the dominant finding
with view evidence. Asymmetry versus focal asymmetry cannot be inferred solely from
one crop. Preserve mixed source descriptors for review rather than treating legacy
compound labels as proof of two independent modern clinical diagnoses.

Proposed outputs: localized finding; mass-like appearance score; distortion-pattern
score; asymmetric-tissue appearance score; other/indeterminate status; available
shape/margin attributes; separate view-confirmed terminology. Source labels and
clinical decisions remain distinct. No unmentioned attribute becomes a negative.
Malignancy/BI-RADS is a separate task, not inferred from morphology alone.

## Executed preparation and support

Protected root: `C:/AI-PACS-Datasets/breast-review/point-review-20261003`.
Executed `prepare-typing-taxonomy-20261005.py` against B47's private source manifest.
Outputs: `typing-taxonomy-20261005/aggregate.json` and
`typing-taxonomy-20261005/descriptor-evidence-private.json`.
Input SHA256: `b1a5c579f9b4aca002cb8457b054c3a36b7778a2832a66de3c8ccd9ef9fec584`.
Source descriptors, row identity and test-person reserve are preserved.
All clinical-type targets remain unknown and all training-ready flags remain false.
Synthetic assertions distinguish pure AD, irregular mass, mixed AD and unknown.

| Nonreserved original CBIS TRAIN source group | Rows | People contributing |
|---|---:|---:|
| Standard mass-shape descriptors only | 1,092 | 593 |
| Architectural distortion only | 73 | 46 |
| Legacy asymmetry family only | 39 | 26 |
| Lymph node only | 25 | 4 |
| Mixed descriptors requiring review | 58 | 37 |
| Unknown | 4 | 2 |

These 1,291 rows exclude 27 rows belonging to publisher-test people. Person counts
across groups are not additive. In particular, 25 lymph-node rows represent only four
people: oversampling cannot manufacture independent diversity. Do not claim a robust
lymph-node classifier from this support. The 73 AD rows are candidates, not adjudicated
modern AD truth. The previous binary exclusions are retained for their original
experiment, but are now preserved in a separate positive review pool, not discarded.
This manifest alone cannot train a discriminative classifier: it contains descriptor
evidence and unknowns, not a reviewed set of positive and negative clinical targets.

## Published method review and selection

| Primary study | Relevant method | Decision / limitation |
|---|---|---|
| [Liu et al. 2023](https://pubmed.ncbi.nlm.nih.gov/37035200/) | Mask-RCNN with several backbones on FFDM; 349 AD patients; region delineation and malignant-AD assessment | Supports an AD-specific region/morphology experiment. Reported malignancy metrics are not evidence of Mass-versus-AD performance in our population. No qualified downloadable replacement was established here. |
| [AD gland-distribution study](https://pubmed.ncbi.nlm.nih.gov/32485700/) | Uses surrounding gland distribution as prior information in DBT, addressing typical and atypical AD | Supports testing surrounding context beyond radial patterns. DBT findings do not establish FFDM effectiveness. |
| [Directional context study](https://pubmed.ncbi.nlm.nih.gov/35338787/) | Context and anatomical information for false-positive reduction in DBT | A rationale for contextual rechecking, not a ready 2D component or transferable accuracy claim. |
| [Adaptive receptive field study](https://pubmed.ncbi.nlm.nih.gov/36595312/) | Deformable-convolution context for atypical AD in DBT | Do not hard-gate AD on a perfect radial star; retain as later architecture option, not the first larger model to train. |

Prefer a compact local-plus-surrounding-context encoder with separately supervised
region and attribute outputs. Reuse compatible image preparation. A calcium bright-peak
gate is not an AD gate: radial convergence, orientation coherence and disrupted tissue
continuity are candidate features to ablate, not sufficient diagnostic rules.

## Concrete experiment order and stopping rules

1. Extend the existing VinDr manifest to include AD and coannotations, auditing exact
   local TRAIN counts, geometry and person/study grouping. Do not infer local counts
   from publisher tables. Complete B47 mask QC and reconcile historical partitions.
2. Review paired-view examples across pure and mixed groups. Prioritize AD versus
   spiculated Mass, irregular Mass versus asymmetric tissue, and scar/overlap versus
   AD. Include reviewed normal hard negatives. Retain uncertainty and annotation
   completeness flags. Never assign normal to unboxed tissue by default.
3. Freeze grouped development/calibration partitions and a matched three-arm protocol:
   compact local image classifier; same encoder with surrounding-context branch;
   same context model with eligible region/shape/margin auxiliary supervision.
   Use known-label masks and separately report mixed/indeterminate cases. Architecture,
   update budget and operating thresholds must be frozen before fitting; no numerical
   training budget has yet been selected in this preparation stage.
4. Use patient-aware capped sampling or bounded loss weighting derived only from fitting
   support; do not oversample validation. No blind replication of the dominant Mass class
   and no synthetic-count claim for minority patient diversity. Compare classwise PR,
   Mass overcalls, AD misses, calibration and abstention coverage on the same cases.
5. Evaluate detection on full images and typing on both reference and predicted ROIs.
   Report AD sensitivity at a fixed false-positive budget and paired class confusions;
   a high global accuracy or Mass recall alone cannot promote a model. Bootstrap by
   person where linkage exists, otherwise disclose study-level grouping limitations.

Stop a training arm for numerical failure or a predeclared overfit/compute limit;
reject promotion if improvements depend on excessive false AD calls, class collapse,
or materially worse finding retention. If labels cannot support the comparison,
finish targeted adjudication before more training. Keep calcium and production
models unchanged. This turn completed the metadata grouping and research decision,
not these downstream fitting and qualification gates.
