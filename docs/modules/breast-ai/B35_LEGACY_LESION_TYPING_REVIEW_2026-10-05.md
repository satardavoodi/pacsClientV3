# B35: Mass and asymmetry upgrade review

Date: 2026-10-05. Scope: review the existing non-calcification localization/typing
pipeline and identify evidence-backed upgrade priorities. Status: source inspection,
synthetic behavioral reproduction and literature review complete. No model training,
runtime patch, production access or new clinical accuracy experiment this turn.

## Actual architecture and supported task

The canonical local engine first runs a one-class FCOS ResNet50-FPN detector with
512-square configuration. Detector boxes are generic abnormal regions, not typed
mass/asymmetry findings. The worker then extracts ROI, single-view and paired-view
features and applies saved stacked classifiers and calibrators. Saved branches are
SINGLE, MV, BL and BOTH. Multiple label thresholds are evaluated independently.

Both source LABELS and delivered label_order.txt contain only No Finding, Mass,
Suspicious Calcification and Focal Asymmetry. Generic Asymmetry, Global Asymmetry,
Architectural Distortion and Developing Asymmetry are not independent outputs.
Changing thresholds cannot add those learned classes. No Finding is derived from
absence of positive supported class decisions, not a classifier trained to exclude
every possible breast finding. Do not treat an unsupported category as ruled out.

Reviewed current canonical source:
`modules/ai_imaging/eagle_eye_engines/{worker.py,vendor/breast/FCOS_INFERENCE.py,vendor/breast/TWO_VIEW_FEATURES.py,vendor/breast/XGBOOST_INFERENCE.py}`.
Generated delivery copies were used for label comparison, not edited as source.
The existing original detector hash recovery is documented in the master record;
this review did not re-verify live Razi routing, source parity or deployment state.

## Reproduced correspondence weaknesses

The actual `_pick_cc_mlo_opposite` function uses overlap in finding_categories when
available, otherwise the first indexed opposite-view row. `_pick_contralateral_roi_row`
also selects the first indexed available ROI rather than proving anatomical matching.
The fallback mirror crop reflects raw image coordinates and clips bounds; it is not
registered nipple/chest-wall correspondence across differently positioned breasts.

A read-only AST extraction executed the two real picker functions on synthetic rows:

1. The same rows select a different opposite-view ROI when finding labels are removed.
2. Without labels, changing row indices changes which opposite-view ROI is chosen.
3. Contralateral ROI selection likewise changes with row indices.
4. Source label extraction confirms the absence of an Asymmetry output.

All assertions passed, confirming the described behavior. This establishes a design
weakness and potential training/inference mismatch, not proof of historical training
leakage or a quantified cause of patient-level errors. Do not simply change pairing
under frozen feature-based weights; that changes the model's input distribution and
requires a separately evaluated candidate/recalibration or retraining.

Protected P artifacts: `audit_legacy_lesion_typing_20261005.py` and
`legacy-lesion-typing-audit-20261005.json`. P is
`C:/AI-PACS-Datasets/breast-review/point-review-20261003`. Receipt includes source
hashes. No private cases/images were used in this reproduction.

## Historical evidence and its limits

The [October 1 engineering record](../EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md)
already reports diagnostic classification of 4,095 reference-ROI feature rows from
1,000 publisher-test study groups:

| Class | TP/FN | FP/TN | Sensitivity | PPV |
|---|---|---|---:|---:|
| Mass | 227/10 | 74/3784 | 95.8% | 75.4% |
| Focal Asymmetry, corrected calibration | 45/8 | 75/3967 | 84.9% | 37.5% |

These are historical diagnostic numbers, not a fresh run or production performance.
They use precomputed reference-ROI features, uncertain original training exposure and
potentially label-assisted pairing. They do not establish end-to-end detection recall,
independent accuracy, or which alternate category caused each error. Prior calibration
repair greatly changed Focal Asymmetry false outputs; verify intended calibration and
feature schema before attributing every error to insufficient training.

Existing annotation audit recorded 1,226 Mass rows/584 studies, 269 Focal Asymmetry
rows/134 studies and 97 Asymmetry rows/96 studies. These are historical local inventory
counts, not refreshed patient counts this turn. The smaller classes require grouped
splits, balanced sampling and per-class reporting, not total accuracy alone.

## Research and build-versus-adapt choice

- [Official VinDr-Mammo dataset](https://physionet.org/content/vindr-mammo/1.0.0/)
  provides digital mammography findings including masses, asymmetries and distortion
  with multi-view examinations. Existing authorized local data is the first candidate;
  verify individual target labels, patient grouping and previous model exposure before
  training. CBIS mass data can supplement mass morphology but cannot manufacture an
  asymmetry class or remove film-to-digital domain differences.
- [Act Like a Radiologist, Liu et al.](https://arxiv.org/abs/2105.10160) studies anatomical
  ipsilateral and bilateral relations for mass detection. This supports testing genuine
  view correspondence. Its reported mass detection improvements do not prove our
  mass-versus-asymmetry typing task or justify immediately adopting a graph model.

Retain the incumbent detector as a comparator; first test improved typing/context.
Compare: (A) frozen existing stack; (B) compact single-view ROI-plus-context classifier
with explicit supported targets; (C) the same classifier with verified same-breast
CC/MLO and bilateral context, missing-view masks and abstention when evidence is
insufficient. Branch C must outperform B on grouped independent evidence to justify
extra compute. A registered/learned correspondence or whole-breast context avoids
pretending the first opposite-view ROI is the same lesion. Developing asymmetry, if
later in scope, requires appropriate prior-study evidence and its own labels.

## Ordered experiments and gates

1. Freeze original weights, feature/calibration schema, thresholds, code and dataset
   lineage. Refresh the actual local TRAIN inventory without selecting on test labels.
2. Assemble patient-grouped reviewed Mass/Focal Asymmetry/Asymmetry examples plus
   normal and difficult parenchymal negatives, views and available priors. Record
   ambiguous/mixed labels; do not force mutually exclusive classes without a task
   definition. Preserve the calcification branch and its independent review history.
3. Regenerate label-blind features from reference ROIs for classifier-only evaluation;
   compare against predicted ROIs and the full-image cascade to isolate localization
   misses, crop/context defects and incorrect type decisions. Do not use reference
   labels to find matching views during either training feature generation or inference.
4. Train B as a bounded CPU-serving-oriented baseline on A100 only after data/labels
   and split checks; compare C by ablation. Add supported classes through a versioned
   label/schema change, not renaming Focal Asymmetry or stretching a threshold.
5. Report per-class precision/recall, confusion or multilabel errors, PR-AUC,
   calibration, detection FROC, missing-view behavior and CPU end-to-end latency.
   Require Mass preservation and material improvement in the targeted typing errors;
   do not reuse microcalcification point metrics as lesion-typing evidence.

Conclusion: there are concrete upgrade opportunities, especially unsupported targets
and unverified correspondence. No improvement percentage is yet demonstrated. The
next deliverable is a source-bound, label-blind baseline comparison protocol and
cohort, not an unqualified replacement of the working Razi model.
