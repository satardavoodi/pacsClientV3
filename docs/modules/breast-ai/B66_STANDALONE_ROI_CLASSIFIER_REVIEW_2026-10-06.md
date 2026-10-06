# B66: Independent second-stage lesion classification

Date: 2026-10-06. Status: literature and architecture decision; no new fitting,
inference, deployment or measured improvement. Reporting contract fitting fields
are not applicable. This supersedes B65's immediate next-experiment ordering.

## Question and existing evidence

Keep the lesion detector fixed and classify its regions with an independent model.
The owner's impression that localization works well is not a measured >90% detection
baseline. B50/B64/B65 already classify supplied reference ROIs independently of the
production detector. They establish feasibility, not reliable production-box typing.
B65 changed errors rather than solving them: macro-F1 51.24% versus 50.87% matched
control; Mass recall fell from 76.31% to 56.88%. Equal fusion also failed retention.
No architectural winner has been established on an independent cohort.

## Primary literature and artifact audit

1. [Mellado et al., 2025, local-view finding classification](https://www.frontiersin.org/journals/oncology/articles/10.3389/fonc.2025.1601929/full).
   EfficientNetV2 classifies annotated VinDr crops. Final eight-label Table 3 recalls:
   Mass 75.95%, asymmetries 17.72%, architectural distortion 4.17%; respective supports
   237/79/24. This is directly relevant but does not solve rare-class typing. Its
   separate subset architecture table must not be substituted for final performance.
   No task checkpoint was verified. Reproduction would adapt the method, not claim
   equivalence to a released trained model.
2. [Baccouche et al., 2022, stacked residual mass classifiers](https://pmc.ncbi.nlm.nih.gov/articles/PMC9293883/).
   ResNet50V2/101V2/152V2 ensemble operates on mass regions for shape, BI-RADS and
   pathology. CBIS standalone BI-RADS Table 9 accuracy is 83.84%; shape Table 12
   accuracy is 90.02%. These are not Mass-versus-asymmetry results. Random image
   partitioning does not establish patient-disjoint generalization. The
   [author repository](https://github.com/AsmaBaccouche/Stacked-Ensemble-of-Residual-Neural-Networks)
   root, checked through GitHub API, contains README, ROC plotting and four model
   scripts. No root checkpoint or license file was present; usable trained weights
   and reuse rights remain unverified. A published method is not a deployable asset.
3. [AsyDisNet, IEEE TMI 2025](https://pubmed.ncbi.nlm.nih.gov/40030557/).
   Targets asymmetry and distortion detection using angle-based quadruplet loss and
   weak/semi-supervision. This motivates discriminative representation learning,
   not a claim that its detector is a ready ROI classifier. The
   [author repository](https://github.com/ML-AILab/AsyDisNet) exposes samples/figures
   and describes full-data approval as pending. An executable model/checkpoint was
   not verified. Any ROI metric-learning adaptation is a new experiment.
4. [Liao et al., 2023, DenseNet asymmetry classification](https://pmc.ncbi.nlm.nih.gov/articles/PMC10336404/).
   Endpoint is benign versus malignant asymmetric findings, not Mass versus
   asymmetry. Its AUC 0.778 cannot be used as evidence for our typing task.

No cross-paper ranking is valid: datasets, endpoints, splits and input regions differ.

## Chosen experiment sequence

1. Keep production localization and calcification processing fixed. The new head
   receives a native-derived crop plus surrounding context; exclude old class scores
   initially so the comparison measures independent image classification.
2. Add an EfficientNetV2 ROI comparator before further ensemble optimization. Choose
   a compact variant subject to CPU measurements; document variant and deviations
   from the paper explicitly. Compare with the matched B64 control on the common
   1,147-ROI cohort, same source labels and group assignments. This is a development
   comparison, not a new independent test after repeated cohort exposure.
3. Test supervised contrastive/metric learning separately if minority-class errors
   persist. Use curated confusing Mass/AD/asymmetry examples within training only.
   An AsyDisNet-inspired loss is not a reproduction without its complete protocol.
4. Retain shape/margin supervision as a separate, label-masked experiment. CBIS mass
   attributes cannot supply absent asymmetry/distortion labels or normal negatives.
   A descriptor head and later BI-RADS assessment have different reference targets.
5. Only after reference-ROI success, repeat downstream typing on frozen detector
   boxes, measuring crop mismatch and missed lesions separately. Include benign
   masses omitted by source annotation policy and uncertain/unclassifiable outputs.

Single-view output remains appearance typing with an asymmetry-family category;
do not force focal-versus-one-view asymmetry from one crop. Additional views and
clinical context belong to subsequent assessment, not hidden assumptions.

## Evaluation and stopping rules

Register configuration, grouped inner selection and numerical retention gates before
fitting. Use class recall/precision, macro-F1, confusion matrices, grouped confidence
intervals and Mass overcalls among reference nonmass lesions. Do not call that last
quantity a normal-tissue false-positive rate. Freeze an independent evaluation cohort
before clinical promotion. Report CPU whole-study latency including crop preparation,
not GPU crop-only throughput. No training/deployment is authorized by an accuracy
headline alone; user authorization for research is already present.

Calibration/cross-fitted fusion from B65 remains a deferred comparator, not the sole
next route. Review annotation disagreements before using hard negatives. Existing
physician feedback remains separate from immutable source references.

## Verification and next action

Primary articles and author artifact listings checked; documentation links checked.
No runtime code changes, application GUI test or training run occurred in B66.
Next: freeze the independent EfficientNetV2 comparator recipe and execute the paired
development experiment; report failure as well as success before selecting a model.
