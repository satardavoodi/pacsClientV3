# B49: Two-dataset support audit and controlled balancing design

Date: 2026-10-05. Status: fresh remote VinDr TRAIN metadata audit and aggregate
balancing illustration completed; no new fit, inference or accuracy gain.
Continues [B48](B48_DISTORTION_AND_MORPHOLOGY_TASK_2026-10-05.md).

## Evidence and population units

Fresh Windows A100 source: `F:/Aisan-Rahimi-part2/MammoDicomData/original data/finding_annotations.csv`.
SHA256 `59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc`.
Read TRAIN only: 16,391 rows / 4,000 studies. Aggregate protected receipt:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003/typing-taxonomy-20261005/vindr-all-training-labels.json`.
The same folder contains `balance-design.json`; B48's CBIS aggregate is unchanged.
No raw identifiers or images were printed or sent to external research services.

| Finding | VinDr inclusive rows | VinDr studies | CBIS nonreserved source rows / people |
|---|---:|---:|---|
| Mass / standard mass-shape | 989 | 469 | 1,092 / 593 |
| Focal Asymmetry | 216 | 108 | Part of 39 legacy asymmetry-family rows / 26 people |
| Asymmetry | 77 | 76 | Same legacy family; not an additional 39 rows |
| Architectural Distortion | 95 | 52 | 73 pure descriptor rows / 46 people |
| Lymph node | 46 suspicious-node rows | 43 | 25 generic node rows / four people |

These are source support counts, not a harmonized training cohort. VinDr counts are
inclusive and studies may contribute multiple categories. A study is not proven to
be a unique patient. CBIS generic lymph node is not equivalent to VinDr suspicious
lymph node. Mixed CBIS rows remain review candidates, not automatically new class truth.
VinDr has another 20 Global Asymmetry rows / 10 studies; do not merge them silently
into Focal Asymmetry. Target grouping and view-confirmation follow B48.

VinDr AD is concentrated in density C: 86/95 annotation rows; D seven and B two.
Mass has 811/989 density-C rows. Density is breast-level context, not a typing target
or a shortcut feature proving pathology. Stratify supported evaluation slices by
density and report their denominators; these counts alone do not measure bias.
All 46 suspicious-node rows are MLO; view availability can become a shortcut.
Age, device/site strata and complete image/box QC were not audited in this step.

VinDr `No Finding` appears on 14,589 images across 3,974 studies; this cannot mean
3,974 entirely normal studies because other images in a study may contain findings.
The [publisher](https://physionet.org/content/vindr-mammo/1.0.0/) also states benign
BI-RADS 2 findings are unboxed. Neither unboxed tissue nor this image label supplies
exhaustive negative truth for every morphology target. Build reviewed hard negatives.

## Why naive pooling is not the selected route

Adding CBIS predominantly adds Mass examples, so pooling does not automatically
repair minority support. Its digitized-film derivatives, legacy descriptors and
masks differ from VinDr digital mammograms and box labels. A source classifier can
become an unintended disease classifier when category and source are correlated.
Keep source tags for audit and task routing, not clinical prediction features.

Use CBIS for eligible region/shape/margin auxiliary pretraining, then adapt on
VinDr for digital-image appearance and available finding targets. This is the first
transfer comparison, not a claim that sequential transfer is universally optimal.
AD review support in both datasets can contribute once mapped and QC-approved.
Missing shape/margin labels in VinDr remain unknown, not negative supervision.
Preserve original descriptors alongside a versioned mapping; do not pool generic
and suspicious nodes or legacy asymmetry subtypes as if they were identical.

## Balancing policy and actual design calculation

Select subjects/studies before lesions so multiple views and crops do not grant one
person excessive influence. Freeze all views/derived samples of a group together;
keep the CBIS union publisher-test person reserve and historical partitions intact.
Use independent namespace keys for sources; cross-source duplicate audit remains
required. Fit weights, learned preprocessing and thresholds inside fitting/calibration
partitions only. Evaluation retains its defined distribution, without oversampling.

For the first balancing arm, compare group-normalized loss alone against group-normalized
loss with bounded square-root class-group weighting. Do not simultaneously add weighted
sampling, focal loss and class weights. Candidate factor:
`min(3, sqrt(maximum fitting class-group support / target fitting class-group support))`.
Zero-support targets are unavailable, not infinite-weight classes. For multilabel
outputs, calculate known-target denominators separately; no label-count multiplication
for coannotations. Normalize loss per known target and record realized group exposure.

The aggregate-only illustration gives Mass 1.00, FA 2.08, Asymmetry 2.48 and AD 3.00.
These are **not training weights**: they include the entire publisher TRAIN metadata,
precede label harmonization/QC and must be recomputed inside each eventual fitting
partition. The apparent Mass:AD group ratio changes from 469:52 (9.02:1) to 469:156
(3.01:1) in this arithmetic illustration. It does not create 156 AD studies, predict
accuracy or represent exact multilabel minibatch exposure. AD still has 52 studies.

Safe augmentation may broaden appearance but does not add independent subjects.
Use small, label-preserving geometric changes with matched box/mask transforms;
avoid elastic distortion that creates the target AD pattern, anatomy-invalid flips,
or crops that remove its context. Review mined hard negatives from fitting data only.
No generic SMOTE or synthetic patient-count inflation. Tiny groups such as four CBIS
node patients need additional independent reference support, not stronger oversampling.

## Matched comparison and prior negative evidence

[B38](B38_TYPING_WEIGHT_PILOT_2026-10-05.md) already tested related class weighting
and sampling: FA recall rose from 21.08% to 31.24% with weighting, but Mass recall
fell from 94.31% to 87.91%. Those old three-way ROI experiments do not settle B48,
but prove that balancing alone was not an established improvement. Do not repeat
the same sweep and present it as a new solution. The old Mass-only promotion gate
was subsequently superseded; per-class tradeoffs still need explicit assessment.

After label and geometry readiness, freeze three matched arms on the B48 task:

1. VinDr-only compact local/context control with group normalization.
2. CBIS auxiliary morphology pretraining followed by identical VinDr adaptation.
3. Same transfer with the bounded fitting-only weighting intervention above.

Keep target split, input resolution, initialization where comparable, adaptation
update budget, inference inputs and calibration protocol matched. Count extra CBIS
updates/time explicitly: this compares practical transfer, not equal total compute.
If transfer helps, a compute-matched target-only follow-up can test that confound.
No test labels select the winner. Actual hyperparameters and compute cap remain to
be frozen after mask/label QC, before any fit. Prefer this small comparison over a
large unbounded search. Source-balanced joint learning is a fallback experiment if
sequential adaptation loses useful morphology, not an additional current fit.

Primary evaluation: classwise precision/recall and PR curves, false Mass calls,
AD misses, uncertainty coverage and calibration. Compare paired cases with group
uncertainty, and report each source separately. Complete-image sensitivity at fixed
false positives per image remains distinct from reference-ROI typing. Scar, overlap,
dense normal tissue and spiculated Mass are essential reviewed confounders.
Do not infer target-population PPV from a balanced/enriched validation set.

## Readiness and next action

Completed: local support counts, density/view checks, source-compatibility decision,
prospective balancing artifact and reconciliation with earlier failed balancing.
Pending: full CBIS mask QC, VinDr AD file/box/label audit, paired-view adjudication,
patient linkage where available, negative coverage and frozen fitting protocol.
No training telemetry, checkpoint or clinical acceptance applies to this step.
No production or calcium-model changes. Next execute the readiness checks on the
minority AD and ambiguous morphology pool, then run the bounded comparison.
