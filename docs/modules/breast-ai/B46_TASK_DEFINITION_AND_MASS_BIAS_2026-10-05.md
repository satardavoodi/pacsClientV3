# B46: Separate finding detection, mass morphology and view confirmation

Date: 2026-10-05. Status: source review and posthoc prediction audit completed.
No new training or production change. This task contract supersedes mandatory
single-crop Mass/FA/Asymmetry naming as the primary clinical target of B38-B45.
Those runs remain valid measurements of their stated experiments, not evidence
that a single view can definitively establish the three clinical categories.

## Owner clarification and terminology

The immediate concern is excessive Mass naming among detected soft-tissue findings.
Distinguish local mass morphology from whether a finding is present on one or multiple
projections. A one-view crop cannot supply an unobserved companion-view finding.
Keep uncertainty rather than forcing every localized region into a definite class.

The current [ACR mammography summary](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/BI-RADS/BI-RADS-Summary-Form-Mammography.pdf)
describes a mass as space-occupying, with three-dimensional evidence from projections
or consecutive DBT slices, and wholly or partly outward-convex form. A radiodense
mass tends to be denser centrally. An asymmetry is a one-projection finding; a focal
asymmetry persists across views without satisfying mass morphology, often containing
interspersed fat. A mass need not have a fully visible or sharp margin. Lack of a
sharp boundary therefore must not become a deterministic non-mass exclusion rule.
No physical volume can be measured reliably from a lone two-dimensional ROI.

Version the lexicon: VinDr labels use the fifth edition. The official
[v2025 changes](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/BI-RADS/BIRADS-v2025-Whats-New.pdf)
restore lobulated as a shape descriptor and remove mammographic microlobulated
margin, mapping it to indistinct; DBT may establish a mass from one projection.
Do not confuse shape and margin, silently rewrite legacy labels, or apply an FFDM
two-view requirement to DBT volumes. A non-mass-appearing finding is not synonymous
with normal tissue or benign pathology. Morphology, malignancy and management are
separate outputs. Additional views/US can resolve uncertainty; absence of a US
correlate must not automatically erase a suspicious mammographic finding.

## What our data and predictions actually show

B36 original TRAIN labels:989Mass,216FA,77Asymmetry rows. All108FA breast sides
have the target annotated in both CC/MLO; none of76Asymmetry sides does. These
annotation patterns support the semantic distinction, not lesion correspondence.
There are no individual cross-view lesion IDs or mass shape/margin truth columns.
After prior exclusions, the B38-B45 cohort contains927Mass,190FA,72Asymmetry rows:
78.0% of its1,189 rows are Mass and **zero are normal reference rows**.

Fresh posthoc B41 analysis, no refit or new threshold:

| Seed | Actual Mass share | Predicted Mass share | Asymmetry-family miscalled Mass / family support |
|---|---:|---:|---:|
| 17 | 153/218 (70.18%) | 186/218 (85.32%) | 42/65 |
| 29 | 190/241 (78.84%) | 226/241 (93.78%) | 42/51 |
| 43 | 187/240 (77.92%) | 222/240 (92.50%) | 45/53 |

Here family combines FA and Asymmetry solely for a descriptive reanalysis.
Family recall after collapsing predictions is35.38%,17.65%,15.09%; this is not a
newly trained binary classifier. The folds overlap and cannot be pooled as separate
patients. Mass overprediction is verified; imbalance, absent context, representation
and label quality are competing explanations, not individually established causes.
Evidence: `P/typing-error-fusion-20261005/b41-mass-family-posthoc-audit.json`.

**No valid >90% end-to-end non-calcification finding-versus-normal detection claim
was found in the inspected baseline/runtime and B35-B45 evidence.** Legacy95.8%
is227/237 known Mass ROIs typed correctly; B41's95.2% is also conditional typing.
Neither includes the denominator of lesions the detector never proposed or a normal
cohort. Existing end-to-end calcium measurements cannot fill this gap for soft tissue.

The old absolute no-Mass-recall-loss rule must not alone govern morphology selection:
overcalling Mass can inflate that recall. Separate localization retention from typing
tradeoffs. Evaluate Mass PPV/recall, family PPV/recall, false Mass labels, uncertainty
coverage and retained finding localization. Freeze any new operating point on fitting/
calibration data, then test independently; do not choose it on these exposed folds.

## Published methods and dataset fitness

| Resource | Relevant evidence | Use and limitations |
|---|---|---|
| [VinDr-Mammo publisher](https://physionet.org/content/vindr-mammo/1.0.0/) | Four-view FFDM, region labels and breast assessment; BI-RADS2 findings deliberately unboxed | Existing source for Mass versus asymmetry-family and view-aware work. Bounding boxes do not teach exact margins; unboxed tissue is not an exhaustive normal reference. |
| [INbreast original paper](https://www.inescporto.pt/~jsc/publications/journals/2012IMoreiraAcRadiology.pdf) | 115cases/410images; masses, asymmetries and other findings with detailed contours | Candidate source of contour supervision and a separate digital-image comparison; small cohort, annotation mapping and current access/rights need confirmation before reuse. Not newly downloaded. |
| [CBIS-DDSM publisher](https://www.cancerimagingarchive.net/collection/cbis-ddsm/) | Curated digitized film, ROI masks, mass shape and margin descriptors; questionable mass cases were reviewed during curation | Useful morphology supervision, but scanned-film domain differs from FFDM and labels need semantic audit. Not a ready balanced Mass-versus-FA cohort. |
| [Official TensorFlow Datasets CBIS mass-shape vocabulary](https://raw.githubusercontent.com/tensorflow/datasets/master/tensorflow_datasets/image_classification/cbis_ddsm_mass_shapes.txt) | Includes asymmetric breast tissue, focal asymmetric density and architectural distortion among legacy mass-shape values | Never equate every mass-subset entry with a strict modern BI-RADS Mass. Audit original CSV and local loader mappings before merging labels; this vocabulary alone does not prove our deployed model used an incorrect mapping. |
| [Qi et al.,2023](https://pubmed.ncbi.nlm.nih.gov/36932250/) | 596patients/four hospitals; supervised shape/margin tasks using image+mask inputs, ResNet50 and attention/balancing variants; reported accuracy approximately83.8%margin/87.4%shape | Supports explicitly supervising morphology with masks/attributes. These are already selected masses, not demonstrated Mass-versus-FA discrimination. Abstract and figure caption differ on which variant maximizes margin accuracy; do not claim attention universally improved it. |
| [Asymmetry DenseNet study,2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10336404/) | 460patients; evaluates classification/risk of asymmetries | Not a direct three-type or Mass-versus-FA benchmark. Its malignancy results cannot be imported as our task accuracy. |

The preferred research hypothesis is joint region/contour supervision plus local and
surrounding tissue context, with explicit shape evidence. Candidate measurements:
boundary visibility/continuity and confidence, outward versus inward contour segments,
central-to-peripheral density profile, internal fat, spiculation and tissue continuity.
These are proposed features to ablate, not proven diagnostic rules. Partial/obscured
margins, dense tissue and irregular masses prevent a simple closed-contour threshold.
Segmentation output alone does not prove that a genuine mass exists.

## Revised stages and execution order

1. **Audit localization independently.** Bind the deployed checkpoint and full-image
   preprocessing; use complete images from unseen positive and reviewed normal/hard-
   negative studies. Record lesion matching, misses, sensitivity/FROC, false boxes
   per image/study and union ROI coverage. BI-RADS assessment is not pathology truth.
   Report finding detection separately from cancer-risk classification.
2. **Primary morphology target.** Estimate mass-like versus asymmetric-tissue-like
   appearance, with an explicit indeterminate state. Review source labels with both
   views; do not blindly relabel every one-view Asymmetry as proven non-mass.
   Add boundary/shape training only where annotation supports it, keeping unknown
   descriptor targets masked. Preserve the detection box even when type is uncertain.
3. **Separate view-confirmation task.** Establish image-evidence-based correspondence
   and per-view observability before assigning asymmetry versus focal asymmetry.
   Missing image/detection/annotation is unknown, not proof of absence. DBT is separate.
4. **Calibration and reporting.** Fit probability calibration and abstention criteria
   on separate grouped data. Present a likely morphology with uncertainty, not100%
   certainty; additional imaging need is clinician-owned. Evaluate calibration and
   coverage, not merely the fraction of cases forced into a label.

Next concrete artifact is a paired-view error/label review and a class-agnostic
localization evaluation manifest, followed by a binary morphology baseline with
adjudicated targets. Do not immediately spend another training sweep on the old
forced three-class single-view objective. No clinical runtime changes in B46.
