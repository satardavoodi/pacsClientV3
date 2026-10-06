# B29: Skin-error ablation and calcification descriptor foundation

Date: 2026-10-05. Status: CPU research implementation and exploratory audit completed;
blanket boundary suppression rejected; morphology classifier not trained or qualified.

## Objective and frozen baseline

The physician requested implementation of the feedback-driven correction structure
and investigation of BI-RADS calcification morphology classification. Preserve the
B26-reviewed detector. Detection, anatomical/artifact confirmation, morphology,
distribution and final clinical assessment are separate tasks. A skin calcification
can be a real benign calcification; a skin-edge artifact is not the same label.

Use the B25 frozen checkpoint `00392b28...8e436`, manifest `0a9110b3...c35a0`,
original 143 dots and B28 validated export `e5d43b03...22e20`. The export identifies
three distinct erroneous predictions in one reviewed case. Six cases are TRAIN and
two are exposed development; this is not independent generalization evidence.

## Implemented research components

Protected local root P:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003`.
Linux research root R:
`/home/gadmin/Mammography/candidates/calcification-pilot-20261001`.

- `morphology_stage_20261005.py`: explicit separate morphology/distribution records,
  adequacy and lexicon-version fields, mixed descriptors, no automatic assessment
  category; physical group extents and axis ratio with anisotropic spacing and
  duplicate-point handling; crude silhouette-distance evidence, not a skin detector.
- `test_morphology_stage_20261005.py`: six passing synthetic tests, including physical
  spacing, immutable task semantics, unresolved classifications and failed-mask rejection.
- `audit_skin_morphology_20261005.py`: frozen-output CPU ablation over eight native
  full images and TRAIN-only CBIS descriptor inventory. No new neural inference.
- `skin-morphology-audit-20261005/{protocol.json,aggregate.json,geometry-private.json}`:
  source/code/feedback bindings, aggregate results and protected per-point measurements.

No clinical source code, UI, weights or automatic removal rule changed. No new
training run occurred. Runtime was 12.05 seconds for this CPU audit, not a complete
inference latency benchmark. Initial local/training-environment dependency probes
found SciPy unavailable; existing Linux system Python had the needed dependencies.
Tests and the audit ran there without package installation or service interruption.

## Skin experiment and rejection

Before execution, fixed four distance bands and a conservative rule against deleting
matched support or other unadjudicated predictions. The mask uses native normalized
intensity above 0.01, its largest connected component and filled holes. It confounds
the skin boundary, image edge and chest wall; it is not anatomical segmentation.

| Exclusion distance | All displayed points removed | Three physician-error points removed | Originally matched reference supports removed | Other points removed |
|---|---:|---:|---:|---:|
| 0.2 mm | 1 | 0 | 0 | 1 |
| 0.5 mm | 3 | 0 | 0 | 3 |
| 1.0 mm | 29 | 3 | 1 | 25 |
| 2.0 mm | 49 | 3 | 2 | 44 |

Denominator: 1,519 displayed predictions, including 116 unique matched supports for
143 physician references. Counts concern the original fixed pairs; post-removal
rematching was not performed, so support losses are not asserted as final sensitivity
changes. Other points cannot be called false positives; B26 judged additional red
marks mostly genuine. No band meets the declared gate. Reject blanket suppression;
do not tune a band to this single complaint or encode case-specific coordinates.
Next error-reduction hypothesis: distinguish compact local peaks from extended edge
responses using native patch context plus anatomical proximity as a feature, with
near-skin positives in the preservation set. Obtain a broader confirmed artifact
sample before fitting; three correlated points in one region are not three independent
negative cases. Record borderline predictions for review rather than deleting them.

## Dataset evidence for descriptor classification

Fresh read of the existing official CBIS TRAIN descriptor CSV found 1,546 rows from
602 patient IDs, 261 mixed-morphology rows and 20 missing-morphology rows. These are
image/abnormality rows, not 1,546 independent patients. Exact raw counters and CSV
hash are in the aggregate receipt. No test descriptors or images were read this run.

Pure raw categories include PLEOMORPHIC 664, AMORPHOUS 138, PUNCTATE 106,
FINE_LINEAR_BRANCHING 77 and COARSE 35. These counts exclude mixed rows. Distribution
is missing in 376 rows. Preserve raw terms and missingness; do not convert silence
to a negative class. COARSE does not establish coarse heterogeneous. Legacy
PLEOMORPHIC cannot silently be asserted as modern fine pleomorphic. Punctate/round,
milk-of-calcium/layering and other edition changes need an explicit reviewed crosswalk.

The eight-case physician dots label location only, not shape. A center coordinate
does not provide a punctum outline, width or branching. Existing CBIS JPEG derivatives
also require source/ROI linkage, physical scale and image-fidelity verification before
fine morphology training. Group every view, lesion and repeated source of one person;
audit prior experiment exposure before nominating a holdout. Mixed descriptors need
multilabel or explicit mixed-pattern targets. Missing labels need masked loss.

## Research findings and selected next experiment

1. ACR's public [calcification AI use case](https://www.acr.org/Data-Science-and-Informatics/AI-in-Your-Practice/AI-Use-Cases/Use-Cases/Calcification-Morphology-Follow-Up)
   distinguishes morphology and distribution. Its follow-up definitions cite the fifth
   edition; the current [ACR manual is v2025](https://www.acr.org/Clinical-Resources/Clinical-Tools-and-Reference/Reporting-and-Data-Systems/BI-RADS).
   This research vocabulary is not a complete certified implementation of that manual.
   Coarse and coarse heterogeneous remain separate, as do fine-linear morphology and
   linear distribution. Final BI-RADS assessment is not assigned from a shape alone.
2. [Du et al., 2023](https://pubmed.ncbi.nlm.nih.gov/37027577/), DOI
   10.1109/JBHI.2023.3249404, directly studied both descriptors with a multitask graph
   model. Reported morphology AUC was 0.663/0.700 on private/public datasets, versus
   distribution AUC 0.812/0.873. This supports investigating spatial relationships,
   not a claim that high localization performance implies near-perfect morphology.
3. [YOLO-AMDF, 2023](https://link.springer.com/article/10.1186/s12938-023-01115-w)
   classified benign versus malignant calcifications using magnification images and
   descriptor-assisted fusion. Its reported two-view AUC 0.888 is a different endpoint
   and population, not evidence of multiclass morphology accuracy on our screening data.
4. [Random histogram equalization, 2022](https://arxiv.org/html/2205.01684)
   studied follow-up/pathology classes rather than morphology types. Always equalizing
   patches degraded performance in that experiment. Histogram augmentation remains an
   ablation, not a canonical appearance conversion or morphology label generator.

Selected sequence: verify native ROI linkage and the label crosswalk; prepare a small
diverse clinician-labeled TRAIN sample at cluster level with separate morphology,
distribution, mixed/unknown and assessability fields; compare a compact patch/context
encoder with two independent masked multilabel heads against a simple descriptor
baseline. A graph model is a subsequent comparator if group context remains limiting.
Retain original native detail, provide cluster context, and permit unassessable output
where detail is insufficient. Do not infer shape solely from brightness histograms,
bounding-box dimensions or PCA axis ratio. Optical magnification is not recreated by
digital zoom. If needed, the physician reviews original or magnification views.

Evaluation: patient-grouped partitions, per-class precision/recall and macro-F1,
multilabel errors, calibration and abstention coverage; separate oracle-localized
descriptor performance from the full detection-to-description pipeline. Measure
CPU latency after a trained classifier exists. No accuracy estimate is available yet.

## Decision and next action

Keep the current detector and all original labels. The boundary exclusion hypothesis
failed its preservation gate. The descriptor contract and CPU measurement foundation
are implemented; supervised morphology remains data-preparation work. Next produce
a reviewed legacy-to-current label crosswalk and source-bound native cluster examples,
then launch the bounded compact classifier comparison. No production promotion.
