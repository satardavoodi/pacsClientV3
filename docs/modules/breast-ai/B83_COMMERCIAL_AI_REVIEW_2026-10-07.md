# B83: Commercial mammography AI and transferable decisions

Date: 2026-10-07. Evidence review only; no training, product execution, local
benchmark, weight download or deployment. B82 still controls the work queue.
Public manufacturer documents, regulatory summaries and primary studies were
reviewed; proprietary implementations were not inspected. This is a targeted
review, not a systematic review or proof that every commercial product was covered.

## What the commercial evidence actually supports

| Product / evidence | Verified public detail | Relevance and limitation |
|---|---|---|
| Hologic Genius AI Detection, technical white paper [1] | Separate calcium and soft-tissue detection/classification paths, followed by case analysis; training includes normal, dismissed recalls, benign biopsies and malignancies. Its Mass mark also covers densities and distortion. | Supports a cascade and explicit negative spectrum; the mark is not an exact morphology label. Native DBT differs from our 2D crops. |
| Hologic Genius AI Detection 2.0, FDA summary [2] | DBT suspicious-region localization, lesion certainty and case scoring; soft-tissue scope includes masses, distortion and asymmetries. | Do not interpret regulatory region detection as validated Mass/AD/family classification. Do not transfer this version's evidence to newer Detection PRO. |
| Siemens breast AI integration [3] | Next-Gen AI offers ScreenPoint Transpara powered by FusionAI. | Siemens and Transpara must not be counted as independent algorithms in that integration. |
| Transpara 1.7.0, MASAI randomized study [4] | Among 105,915 analyzed participants, AI-supported screening detected 6.4 versus 5.0 cancers per 1,000. False-positive rate ratio 1.01 (95% CI 0.91-1.11); reading workload fell 44.2%. | Evidence for AI plus a changed reader workflow, not standalone box typing. False recalls are not normal-image mark counts. |
| iCAD ProFound AI, Conant reader study [5] | In 260 DBT examinations, including 65 cancers, 24 readers improved sensitivity from 77% to 85% and specificity from 62.7% to 69.6% with AI. | Enriched retrospective reader experiment; not population screening or our FFDM FROC endpoint. |
| Lunit INSIGHT MMG, official product FAQ [6] | The stated target is malignant lesions; benign findings need not be highlighted. | Suppressing benign findings may suit cancer screening but conflicts with our requirement to describe benign masses. |
| Lunit development study [7] | Development and validation collectively used 170,230 examinations from five institutions, including malignant, benign and normal categories. | The total is not a training-only count. It does not establish exact three-way typing on our cohort. |
| Transpara temporal comparison [8] | Manufacturer describes comparison with up to three prior examinations; its cited specificity evidence includes an ECR 2025 presentation. | A plausible later direction, with weaker evidence here than MASAI; no local benefit established. Longitudinal comparison differs from our bilateral NCC filters. |

Sources were checked on the reporting date. Manufacturer descriptions establish
advertised functionality, not independent validation. No task-matched published
confusion matrix for our exact three-way ROI classification was verified in these
sources. This is an evidence gap, not a claim that commercial typing is impossible.
No downloadable, licensed commercial checkpoint suitable for direct use was verified.

## Changes to our design rationale

These are our engineering inferences and proposed tests, not disclosed vendor recipes.

1. Separate finding presence, finding appearance and cancer suspicion. A real benign
   mass is positive for finding presence even if its cancer suspicion is low. A
   suspicion score cannot be relabeled as BI-RADS without an assessment-specific
   reference and sufficient study context.
2. Reconcile detector-proposed regions with region-level truth. Normal tissue,
   recalled-but-benign regions, actual benign lesions and malignant lesions must
   remain distinguishable. A benign case outcome does not label every box benign;
   pathology needs lesion linkage. This is the immediate B82 data task.
3. After data readiness, test a local learned verifier on actual detector candidates
   at fixed recall, then evaluate appearance typing separately. Preserve calcium
   processing and compare against the existing tissue baseline. Earlier calcium
   hard-negative failures remain evidence; a cascade is not itself a new discovery
   or a guarantee of improvement.
4. Case/view aggregation is a later ablation after a useful local verifier exists.
   Do not infer that the failed B79/B81 NCC recipes tested a fully trained commercial
   multi-view approach. Conversely, published commercial success does not validate
   our geometry or a proposed fusion implementation.
5. Put longitudinal priors on a data-dependent watchlist. Require paired historical
   examinations, reliable identity/view linkage and adjudicated outcomes before
   training. Similarity or stability must not become a hard normality rule.

The reviewed products support continued development, but do not establish which
architecture will work best here. Large, outcome-linked, heterogeneous data and
task definition are plausible differentiators; their causal contribution cannot
be isolated from these reports. Commercial DBT performance cannot be purchased
with a 2D architecture swap alone because the available input information differs.

## Evaluation contract and next action

Keep the B82 stage order. Add the above reference categories to the pending manifest
audit; record missing labels rather than silently inventing them. Do not launch
another fit from this literature review.

Future comparisons must report finding recall versus false marks per normal image,
per-class precision/recall and macro-F1, benign-finding retention, uncertainty and
full study CPU latency. Fix the same candidate set, patient grouping and calibration
partition for comparisons. Reserve unexposed confirmation data. Measure cancer
assessment and clinical recall separately when outcome labels are available.

No new accuracy, specificity improvement, clinical qualification or Razi production
parity is claimed. Training configurations, checkpoints, telemetry and local cohort
results are not applicable because no experiment was run. Document validation checks
local links and decision consistency; a GUI or clinical test is not applicable.

## Owner-approved outputs and training-method follow-up

Owner confirmed on October 7: separate finding presence, finding type and malignancy
assessment outputs; separate calcium and parenchymal processing paths. This is an
approved design contract, not an implemented or validated three-head model.

Additional technical evidence:

- Kooi et al. [9] use detector-selected patches for subsequent CNN analysis, cap
  training candidates at ten per image and use balanced positive/negative minibatches.
  Their cancer endpoint counts benign abnormalities as false positives; annotated
  benign examples were excluded from training. This is related academic methodology,
  not a verified reconstruction of current Transpara internals. Borrow candidate
  sampling, not the benign-label policy or the arbitrary ten-candidate limit.
- Lunit's DBT reader study [10] describes mammography pretraining followed by DBT
  fine-tuning with expert annotations and a ResNet-34 backbone. This supports
  modality-relevant transfer, not proof that the backbone itself explains performance
  or solves our morphology task. DBT fine-tuning cannot be reproduced with FFDM alone.
- The ProFound AI 3.1 manual [11] explains that its displayed scores are referenced
  to a 50% cancer population and are not calibrated clinical malignancy probabilities.
  We must similarly distinguish an uncalibrated suspicion score from an absolute risk.
- Hologic [1] discloses the cascade and training-case spectrum, but a reproducible
  optimizer/loss/mining recipe was not established from the reviewed material.
  No exact contemporary commercial training recipe is claimed for any vendor.

### Proposed implementation contract (our design, not a vendor claim)

Preserve shared immutable DICOM decoding and geometry, followed by separate calcium
and tissue processing. Distinct outputs do not require three large encoders. For
tissue candidates, initially keep the detector fixed and benchmark the existing
compact encoder as a baseline; permit a shared encoder with task-specific heads
only as an explicit later comparison against separate heads/models.

| Output | Supervision | Missing information |
|---|---|---|
| Finding presence | Reviewed true benign/malignant findings versus reviewed normal tissue/artifacts | Unreviewed unmatched boxes stay unknown, not negative |
| Appearance type | Region-specific Mass, AD, asymmetry-family, with uncertain/multiple labels preserved | Do not force asymmetry versus focal asymmetry from one view |
| Malignancy assessment | Lesion-linked pathology or appropriate outcome adjudication | Missing outcome is masked; BI-RADS alone is not histology |

For a future joint model use separate masked loss terms. Presence may use binary
cross-entropy; type uses categorical loss only for adjudicated exclusive labels
(otherwise multilabel or masked supervision); malignancy uses linked outcome labels.
Normalize each term over eligible observations and skip absent targets, rather than
encoding unknown as zero. Select loss weights on development data; do not declare
one equal-weight sum optimal. Compare per-task retention to detect negative transfer.
Calibrate suspicion on a reserved population-relevant partition before displaying a
probability. Assessment/BI-RADS remains a separate qualification task.

### Minimal discriminating experiment after B82 data readiness

1. Freeze person-grouped splits and detector candidates; preserve existing physician
   reviews. Audit benign lesions and rare AD support before deriving patches.
2. Compare the same compact presence verifier trained with reviewed ordinary normal
   regions versus that verifier additionally trained with reviewed detector false
   alarms. Mine only TRAIN candidates; use per-person sampling caps so one difficult
   image cannot dominate. Do not mine the test set or turn unboxed regions negative.
3. Hold crops, model, updates and evaluation fixed to isolate the data effect. Use
   repeated grouped runs if support permits. Report sensitivity at matched normal
   mark burden, benign retention and confidence intervals, not raw accuracy alone.
4. Only after useful presence verification, compare separate versus jointly trained
   type heads on the same candidate set, with per-class recall and macro-F1. B50
   descriptor transfer already exists and remains a comparator, not a novel proposal.
5. Defer learned multi-view/temporal fusion until this local test succeeds and paired
   inputs are ready. Preserve B82 stopping rules; no new training was run here.

This follow-up narrows implementation choices but does not complete the protected
manifest reconciliation. Training, compute use and production behavior are unchanged.

## Source list

1. [Hologic technical white paper](https://www.hologic.com/sites/default/files/2024-10/Genius_AI%E2%84%A2_Detection_Technology_White_Paper_EUR_EN.pdf).
2. [FDA K243341: Genius AI Detection 2.0](https://www.accessdata.fda.gov/cdrh_docs/pdf24/K243341.pdf).
3. [Siemens breast AI integration](https://www.siemens-healthineers.com/fr-lu/infrastructure-it/artificial-intelligence/ai-campaign/breast-ai).
4. [MASAI 2025 primary study](https://pubmed.ncbi.nlm.nih.gov/39904652/).
5. [Conant et al., 2019 reader study](https://pubs.rsna.org/doi/10.1148/ryai.2019180096).
6. [Lunit INSIGHT MMG and FAQ](https://www.lunit.io/en/ai-radiology-software/insight-mmg/).
7. [Kim et al., 2020 development and reader study](https://pubmed.ncbi.nlm.nih.gov/33334578/).
8. [Transpara temporal comparison and its cited evidence](https://screenpoint-medical.com/transpara/temporal-comparison).
9. [Kooi et al., Large scale deep learning for computer aided detection of mammographic lesions](https://geertlitjens.nl/publication/kooi-17/kooi-17.pdf).
10. [Lunit DBT training description and reader study](https://pubs.rsna.org/radiology/doi/full/10.1148/ryai.230318).
11. [ProFound AI DBT 3.1 labeling and manual](https://www.icadmed.com/wp-content/uploads/2024/05/DTM187-ProFound-AI-DBT-3.1.-Software-Labeling-and-User-Manual-US.pdf).
