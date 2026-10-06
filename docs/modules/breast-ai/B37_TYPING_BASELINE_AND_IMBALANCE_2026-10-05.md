# B37: Reproduced typing diagnostic and controlled imbalance protocol

Date: 2026-10-05. Status: legacy diagnostic rerun completed; metadata sampling audit
completed; no new fitting, independent validation, integration or deployment.

## Question and comparator

Improve Mass / Focal Asymmetry / Asymmetry typing while retaining useful localization.
Freeze the existing detector for the first experiment. Compare classification on the
same reference regions separately from classification on detected regions. A good
reference-region score cannot establish whole-image cascade performance.

Fresh Windows A100 execution of evaluate_breast_classifier.py loaded the existing
models_stacked using Python 3.12.3, LightGBM 3.3.5 and sklearn 1.4.2. Exit code 0.
The diagnostic used 4,095 precomputed feature rows from 1,000 publisher test studies.
These data have been repeatedly exposed; independent training lineage is unverified.
Opposite-view features may use label-assisted selection identified in B35. This is
a reproducibility anchor, not a clean estimate of deployed Razi accuracy.

| Output | TP / FN / FP / TN | Sensitivity | PPV | Average precision | Threshold |
|---|---|---:|---:|---:|---:|
| Mass | 227 / 10 / 74 / 3784 | 95.78% | 75.42% | 86.72% | 0.35 |
| Focal Asymmetry | 45 / 8 / 75 / 3967 | 84.91% | 37.50% | 46.90% | 0.30 |
| Asymmetry | Unsupported output | Unavailable | Unavailable | Unavailable | None |

These reproduce the previous diagnostic; no improvement has yet been measured.
Do not merge unsupported Asymmetry into No Finding or report a three-class accuracy.
Focal Asymmetry's low PPV is the clearest observed classification weakness, subject
to reference completeness and precomputed-feature limitations.

## Executed imbalance audit

The metadata audit reads TRAIN only and counts study presence rather than boxes.
Two rows with conflicting target types are deferred from forced single-type learning.
The remaining metadata includes 630 unique target studies: Mass 468, FA 108,
Asymmetry 75. Class counts overlap because a study can have separate lesion types.
These differ from B36's full inventory of 469 / 108 / 76 because of the deferred rows.
Companion calcification labels are not removed or converted into target-type conflicts.

| Candidate | Group sampling | Training loss |
|---|---|---|
| A0 control | Uniform eligible study | Unweighted |
| A1 loss weighting | Same uniform studies | Inverse square-root study frequency, cap 3 |
| A2 sampling | Mean of class factors per study, normalized to probabilities | Unweighted |

Metadata factors are Mass 1.00, FA 2.08, Asymmetry 2.50. They are provisional:
recompute using the actual fitting partition after source/geometry resolution and
grouped split freeze. Never estimate these factors using development or test labels.
Do not combine A1 and A2 initially: isolate which intervention helps.

In expectation per 1,000 study draws, A0 includes Mass in 742.9 draws, FA in 171.4,
Asymmetry in 119.0; A2 changes those to 568.5, 257.4 and 214.3. These overlapping
class-presence counts describe the sampler, not new independent cases or accuracy.
Duplicating a view does not increase study weight. Within a selected study, use
balanced lesion selection and paired views of the selected finding where available;
do not turn every crop into an independent patient. Keep unrelated target lesions
separate, preserve unknown masks and do not train unboxed tissue as proven normal.

Six synthetic checks passed: duplicate-view invariance, exclusion of evaluation
rows, normalized probabilities, capped rare weights, ambiguous-row deferral and
failure on missing target classes. No real optimizer or pixel loader was tested.

## Locked comparison design and remaining gates

1. Resolve 62 missing canonical source paths and 20 out-of-bounds annotations from
   B36. Record corrections or explicit exclusions; do not silently clip or discard.
   Verify native decoding and geometry before defining the final eligible cohort.
2. Rebuild label-blind ROI/context features. Keep annotations for supervision and
   evaluation only; do not feed target labels to opposite-view candidate selection.
   Compare the unchanged incumbent and a compact candidate on identical eligible
   inputs, with changed-feature compatibility reported separately.
3. Freeze study-grouped fit/development/calibration partitions, preserving all views
   and crops together. Seek patient-level linkage for repeated studies. Existing
   target studies were in legacy TRAIN, so this is development evidence for the
   incumbent, not independent qualification. Reserve an unexposed cohort separately.
4. Compare A0/A1/A2 with identical architecture, inputs, seed list (17, 29, 43),
   training update budget and augmentations. Freeze the numeric budget in each run
   card before fitting after a resource smoke check. Hold the detector fixed.
   Use a compact local-plus-context head first; assess multi-view fusion separately.
5. Primary selection: three-class macro F1 on adjudicated, eligible target ROIs;
   report per-class recall, PPV, PR curves and confusion matrix. Require no observed
   Mass recall loss on the paired development cohort for initial screening; report
   paired study-bootstrap uncertainty rather than claiming population equivalence.
   Unknown/ambiguous and rejected inputs must have explicit coverage counts.
6. Fix calibration and operating thresholds on calibration groups, with natural
   class prevalence; evaluate the locked candidate once on the independent cohort.
   Report percentage-point changes and relative changes separately, lost/gained
   lesion identities, dense-breast/view subgroups, false outputs per image, and CPU
   latency for the full cascade on the serving host. Do not rebalance evaluation.

Reject a variant that increases minority recall only by excessive misclassification
or damages Mass detection/typing. More epochs or repeated rare images do not create
additional population coverage. Scarce Asymmetry and density subgroups may require
new adjudicated cases even when weighted optimization converges.

## Reproducibility and documentation

Protected root P is defined in the master document. Artifacts:

- P/lesion-typing-data-audit-20261005/lesion-typing-baseline-reproduction-20261005.json
- Same directory: lesion-typing-baseline-bindings-20261005.json (19 SHA-256 bindings:
  evaluator, classifier, feature contract, feature CSV, annotation CSV, model files).
- P/prepare_lesion_typing_imbalance_20261005.py and the audit directory's
  imbalance-audit.json / imbalance-study-probabilities-private.json.
- Source annotation SHA-256:
  59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc.

An initial PowerShell path-assembly receipt was invalid and retained with the
failed-pathassembly suffix on Windows A100. The corrected receipt has 19 valid
hashes; the failed bookkeeping did not alter models or the successful evaluation.
Host package versions above are observed, not a complete environment lock.
GUI acceptance is not applicable to this research/documentation change.

Method support: [TensorFlow's imbalance tutorial](https://www.tensorflow.org/tutorials/structured_data/imbalanced_data)
describes loss weighting and oversampling as alternatives; the square-root cap and
study-level protocol here are experimental choices, not published performance claims.
[VinDr-Mammo publisher documentation](https://physionet.org/content/vindr-mammo/1.0.0/)
defines the source annotation scope; absent boxes do not imply exhaustive normal truth.
