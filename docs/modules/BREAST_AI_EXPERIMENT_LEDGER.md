# Breast AI experiment and decision ledger

Reconciled through 2026-10-06. Current decisions and next actions belong to
[Breast AI development](BREAST_AI_DEVELOPMENT.md). Rows summarize distinct experiments;
they are not one comparable accuracy curve. Use the linked report for exact settings.
`P` and `R` refer to the protected research roots defined in the current-state document.

## Latest lesion-typing evidence and decisions: October 6

B66: [Independent ROI classifier review](breast-ai/B66_STANDALONE_ROI_CLASSIFIER_REVIEW_2026-10-06.md).
Primary literature separates local finding typing from mass shape/BI-RADS and
asymmetry malignancy classification. Author artifact availability audited. Keep
detector fixed; prioritize paired EfficientNetV2 ROI comparator, then conditional
metric-learning experiment, with descriptor and detector-box gates separate.
B65 fusion deferred. No fit, inference, runtime change or improvement claim.

B65: [DINOv2 representation challenge](breast-ai/B65_DINOV2_REPRESENTATION_REVIEW_2026-10-06.md).
Verified official pinned source/weights/license, nine converged frozen probes and
three actual last-two-block adaptations. DINO macro51.24% vs matched control50.87%;
AD/family recall gains accompany19.44-point Mass recall loss. One fixed equal blend
macro53.46% still loses7.61Mass points; no promotion. Source-nonmass Mass overcalls
39.69%control vs10.58%DINO, distinct from normal-tissue false positives. Exact reload
and finite-update checks pass. Retain B50; next calibrated/cross-fitted combination
and reference-disagreement audit, no development weight sweep or deployment.

B64: [Native context comparison](breast-ai/B64_NATIVE_CONTEXT_TRAINING_REVIEW_2026-10-06.md).
Prospective paired control/detail protocol registered. Original staging stopped on
missing source; audit117 missing images/123 rows. Amended both arms to common1,147
ROIs, excluding whole studies with unavailable inputs before fitting. Same source
supervision, split assignments and labels. All2,294 parity checks passed; twelve fits
completed across five/ten epochs. Five-epoch macro-F1 50.87%control versus51.70%384,
gain0.83points with interval spanning zero. Ten-epoch47.83%control versus44.88%384;
family recall falls39.03%to30.24%. Both gates fail. Retain B50; no deployment. Exact
first-five-epoch replay and checkpoint reload pass. B50 retrospective card completed.

B63: [Supplemental replay](breast-ai/B63_SUPPLEMENTAL_REPLAY_2026-10-06.md).
Actual frozen B50 CPU inference on four new view-specific physician boxes: Mass in
all four for each of three seeds. Two original-input reconstructions pass 1e-6 parity;
checkpoint hashes and exact reload predictions pass. Not independent evaluation,
not detection and no improved accuracy claim. Reconciled three feedback snapshots
as a protected 24-case union without overwriting partial records; retained unresolved
field alternatives outside training. No fitting or deployment. B62 detail ablation
remains next after staging/run-card readiness.

B62: [Retrospective and implementation plan](breast-ai/B62_RETROSPECTIVE_AND_IMPLEMENTATION_PLAN_2026-10-06.md).
Audited prior experiments and primary external methods, including task/rights/exposure
limitations. Corrects B61 novelty: B50 already used shape/margin auxiliary pretraining.
Keep B50 control; reconcile references and score supplemental ROIs before training.
Next controlled fit is native context detail; bounded encoder and retained descriptor
or region supervision follow only if justified. Failed balancing/padding/proxy routes
remain rejected. Proposed gates, compute cap, independent-test and CPU timing needs
recorded. Documentation/research only: no new fit, inference or deployment.

B61: [Classification-first continuation](breast-ai/B61_CLASSIFICATION_FIRST_PLAN_2026-10-06.md).
Owner prioritizes already-localized lesion type, then mass attributes, then assessment.
Evidence favors reference reconciliation and controlled detail/descriptor supervision
over repeating failed spatial proxies. B50 retained; current ACR vocabulary versioning,
CBIS limitations, benign coverage and deferred BI-RADS gates recorded. No new fit,
inference, accuracy improvement or deployment in this decision review.

B60 benign annotation-scope check: official VinDr documentation confirms BI-RADS 2
findings are unboxed. Physician identifies the additional masses as BI-RADS 2.
Inspected B50/B54 selection has no explicit BI-RADS cutoff; B55 shows source ROIs,
not detector output. This supports a missing-reference explanation, not proof of
runtime benign suppression. No inference or production-filter audit in this check.

B60 additional-box intake: two byte-identical physician exports received; four boxes
across two cases/two views each. Provenance, signal hashes and bounds verified, native
crop overlays inspected. Both primary regions are separate from original reference
ROIs. Four view boxes are not four confirmed distinct lesions. No new model scoring
or automatic training; preserved evidence and next input-specific inference in B60.

B60: [Supplementary physician boxes](breast-ai/B60_ADDITIONAL_LESION_BOXES_2026-10-06.md).
User requests localizing additional masses in two B55 cases. Native full-view box
drawing retains B59 windowing and existing diagnostic answers; supplementary regions
have their own source-bound storage and JSON export. No new physician coordinates
or model accuracy results have yet been received. See B60 for verification status.

B55 physician feedback intake (October 6): two exports validated and retained;
latest 24 records/23 finished, no earlier IDs lost. Two comments report three
additional masses. Keep supplemental findings separate from original-ROI typing;
locations and one correctness/type conflict remain unresolved. No automatic training
labels, detector-miss counts or new accuracy claim. See B55 intake documentation.

B59: [Native review windowing](breast-ai/B59_NATIVE_WINDOW_REVIEW_2026-10-06.md).
User reports reviewing through case 11 and poor zoomed window/level. Root cause is
post-conversion CSS brightness/contrast on 8-bit PNGs, despite native spatial size.
Native-source display repair preserves B55 identity, model scores and clinical
answers; this is not training or an accuracy improvement. See the linked report
for source coverage, guards and the separate visual-acceptance status.

B58: [Direct spatial inspection](breast-ai/B58_SPATIAL_INTENSITY_SURFACES_2026-10-06.md).
18 native boxes/18 common-fitting studies, six per source class (Mass/FA/Asymmetry).
Crop/surface/contour/profiles and all source/array/panel hashes verified. Central
contrast medians 0.137/0.051/0.097; all measured class ranges overlap. Exact shuffling
preserves histograms and destroys spatial correlation. No fit or improvement claim.
Clipping, presentation processing, crop extent and cohort imbalance remain confounds.
Next inspect unclipped signal/context on the same cases; preserve B50 and B55.

B57: [Completed spatial morphology experiment](breast-ai/B57_SPATIAL_MORPHOLOGY_EXPERIMENT_2026-10-06.md).
32 source-derived features for all 1,270 ROIs, zero extraction failures; 15 fixed
fits with exact source identity and reload guards. Fusion macro F1 51.20->51.52%
versus matched embedding head, AD21.25->22.92%, Mass89.15->88.44%, family35.93->35.65%.
All paired macro intervals include zero; predeclared retention gate fails. Preserve
original B50 (52.12%). Core/radial/joint-only macroF1 35.53/29.31/44.96%.
482.28 seconds source staging, 1.09 seconds classifier fits/reloads; not serving cost.
CUDA baseline replay exact; CPU probability mismatch preserved. No deployment or
calcium change; next targeted reference review, not an uncontrolled feature search.

B56: [Spatial morphology literature and test design](breast-ai/B56_SPATIAL_MORPHOLOGY_RESEARCH_2026-10-06.md).
User's intensity-surface hypothesis maps to central continuity, low-signal channel
topology and multiscale radial orientation. Published Gabor/phase-portrait and
radial-gradient methods support a bounded experiment, not a guaranteed class rule.
Separate coherent core from distortion; fat and spicule length are not absolute
discriminators. B39 generic statistics failed; new topology/orientation route is
not implemented or evaluated yet. B55 review unchanged; no new fit or accuracy gain.
Same-day refinement: retrieved concentric-layer mass detection and smooth/texture
decomposition studies; prioritize a persistent core, partial boundary support and
internal channel topology alongside radial lines. No fixed visible-margin percentage
or universal fat exclusion; no new extraction or fit in this research follow-up.

B55: [Model-assisted physician correction](breast-ai/B55_MODEL_ASSISTED_REVIEW_2026-10-06.md).
User requests model outputs visible during the single review pass. Frozen B50
unweighted transfer seed17 inference completed on all 24 B54 reference ROIs;
7 Mass / 8 AD / 9 family predictions are not accuracy counts. Reload and probability
guards passed, 2.59 seconds CPU verification. Separate assisted-feedback version
preserves B54 and records model exposure, correctness and corrections. No training,
independent evaluation, new clinical gain or production change.

B54: [Source, input and reference readiness](breast-ai/B54_SOURCE_INPUT_AND_REFERENCE_READINESS_2026-10-06.md).
Three parallel workstreams: 73/73 CBIS AD triplets pass pixel/geometry QC; historical
reserves leave 65 rows / 42 people for source-label research. Native audit of 24
common-fitting studies supports testing context384 with local224 unchanged, not a
classification gain. A separate 24-study blinded physician bundle with 96 native-spatial
images is built; source labels and feedback remain separate. Seven core UI guards pass;
server launch and local-file browser opening were policy-blocked, so live acceptance
and physician review remain pending. No fit, deployment or new performance percentage.

B53: [Evidence reconciliation and next gates](breast-ai/B53_EVIDENCE_REVIEW_AND_NEXT_GATES_2026-10-06.md).
Documentation review only. Preserve B50, separate calcium/typing endpoints, retire
stale current-state wording. Prioritize morphology adjudication and unused CBIS AD
source QC before task-matched supervision; resolution follows an actual information-loss
audit, not automatic upsampling. No new fit, metric gain or production change.

B52: [Frozen source encoder](breast-ai/B52_FROZEN_TRANSFER_2026-10-06.md).
Three actual matched fits/1,930 updates: macroF1 52.12->40.78%, AD22.50->2.08%,
Mass84.03->88.40%. All encoder weights/buffers unchanged, heads updated, replay/reload
exact.19.37s/434MBpeak. Reject fixed-budget frozen strategy; retain B50.

B51: [Neutral target padding](breast-ai/B51_PADDING_ABLATION_2026-10-06.md).
Three matched fits/1,930 updates: macroF1 52.12->51.21%, AD22.50->17.50%.
All2,540padding masks verified; normalized content unchanged; original baseline
probabilities replay exactly.26.37s/524MBpeak. Inconsistent seed gains, reject.
Descriptive error audit does not support extreme padding as the main AD failure.

B50: [Actual CBIS-to-VinDr transfer training](breast-ai/B50_TRANSFER_TRAINING_REVIEW_2026-10-05.md).
Completed 12 fits/7,695 updates, exact reload and BN guards. 1,015 CBIS morphology
ROIs after65geometry exclusions and12historical reserves; 1,270 VinDr targetROIs.
Transfer macroF1 46.49->52.12%, AD recall10.42->22.50%, Mass84.39->84.03%.
Weighted transfer52.23%macroF1 but Mass78.34%; retain unweighted research route.
All paired macro-F1 intervals crosszero; no clinical promotion.93.54sGPUwork,
606MBpeak, separate552sVinDr/726sCBISstaging. Next targeted AD error/input review.

B49: [Two-dataset balance audit](breast-ai/B49_TWO_DATASET_BALANCE_2026-10-05.md).
Fresh VinDr TRAIN aggregate: 95 AD rows/52 studies versus 989 Mass/469; density/view
coverage and image-level No Finding limitations recorded. Prepared aggregate-only
capped-weight illustration, not training weights. Selected controlled CBIS auxiliary
transfer versus VinDr-only, then one balancing arm; no new fit or gain claimed.

B48: [Distortion-aware task and metadata preparation](breast-ai/B48_DISTORTION_AND_MORPHOLOGY_TASK_2026-10-05.md).
Prepared source-bound descriptor evidence for all 1,318 CBIS rows without forced
modern labels. Nonreserved support: 1,092 mass-shape, 73 pure AD, 39 asymmetry,
25 lymph-node, 58 mixed and four unknown rows. AD/context literature reviewed;
binary morphology is not the complete clinical task. No fit; next label/geometry
QC and matched local/context/auxiliary-supervision comparison.

B47: [Local dataset morphology audit](breast-ai/B47_LOCAL_DATASET_MORPHOLOGY_AUDIT_2026-10-05.md).
Verified VinDr on F and CBIS on D of Windows A100. CBIS original 1,318 TRAIN rows
include legacy asymmetric and mixed descriptors; 1,092 standard-shape candidates
remain after union Mass/Calc test-person reservation. All file triplets resolve;
24/24 sampled mask geometries match, but JPEG contours and full QC remain limitations.
Modified CSV omits 92 rows; shared label changes are missing-value normalization only.
No fit. Next full QC, then matched morphology-supervised transfer versus control.

B46: [Task-definition and Mass-bias correction](breast-ai/B46_TASK_DEFINITION_AND_MASS_BIAS_2026-10-05.md).
Owner clarifies morphology versus view-confirmed type. Fresh B41 posthoc audit
shows85.3-93.8%Mass predictions versus70.2-78.8%reference prevalence. No >90%
end-to-end non-calcification detection evidence found. Current ACR definitions,
VinDr/INbreast/CBIS label fitness and morphology-supervision literature reviewed.
No new fit. Supersede forced single-view three-way clinical naming; separate
localization, uncertain morphology and view confirmation with a balanced typing gate.

B45: [Matched supervised adaptation](breast-ai/B45_TRAINING_REVIEW_2026-10-05.md).
Completed six real full-ROI fits, same three study splits and 15 fixed epochs.
Adaptation macro F1 42.18% versus frozen 38.29%; FA recall rises 20.12% to 30.26%
but Mass falls 95.10% to 89.65%. Strong fitting/development gap; reject promotion.
All 5,430 optimizer steps, fixed-BN and exact reload guards pass. GPU work 42.19s,
510 MB allocated; separate from input staging. B44+B45 total 48 actual fits.

B44: [Parallel training review](breast-ai/B44_TRAINING_REVIEW_2026-10-05.md).
Forty-two actual fits compare single-task/view/density heads, stronger regularization,
frozen-image PCA fusion and actual frozen calcium score/decoder transfers on exact
saved study splits. View auxiliary macro F1 44.54% but Mass recall91.42%; none passes
replacement gates. Calcium transfer macro F1 falls to36.71-38.72% versus41.41%control.
Label-blind companion context gives38.51%macroF1 versus35.52%current-global control;
both fail againstB41. All completed; no promotion. Next bounded task-specific
last-block fine-tuning versus a matched frozen encoder control (B45).

B43: [Shared preparation timing](breast-ai/B43_SHARED_PREPARATION_TIMING_2026-10-05.md).
Five alternating-order warm-cache rounds: median 2.1156 to 1.8963 seconds per eight
images, 10.37% preparation reduction, exact pixel/crop parity. No full inference
timing or accuracy improvement claimed. Retain prototype for controlled integration.

B42: [Shared-input prototype](breast-ai/B42_SHARED_INPUT_PROTOTYPE_2026-10-05.md)
implemented outside runtime. Eight images / 18 ROIs pass exact input/crop and
cached-output parity; source/missingness guards pass. No new FPN or typing fit.
Next populate the typed cohort with exposure-controlled calcium predictions.

B41: [Shared analysis and calcium-feature audit](breast-ai/B41_SHARED_ANALYSIS_AND_CALCIUM_CONTEXT_2026-10-05.md).
Three matched fits removing four old calcium proxies yield mean macro F1 41.41%,
Mass recall 95.20%; FA is inconsistent across splits. Retain research comparator.
Plan shared native decode plus separately evaluated cross-task features; no deployment.

B40: [Frozen ResNet-18 local/context probes](breast-ai/B40_FROZEN_IMAGE_ENCODER_2026-10-05.md).
1,083 decoded images, six fitted and reloaded heads, exact paired split checks.
Local macro F1 40.38% but Mass recall 83.34% versus A0 94.31%; local+context also
fails retention. Reject both. No backbone fine-tuning or production model change.

B39: [Architecture review and native-context ablation](breast-ai/B39_TYPING_ARCHITECTURE_REVIEW_2026-10-05.md).
Three native-statistics-augmented fits reduced mean macro F1 to 36.86% versus A0
38.28%; rejected. Reviewed GMIC, Mammo-CLIP, Mammo-FM, GLAM and multi-view studies.
Prefer bounded local/context image-encoder comparison; exact task fit, assets and
rights prevent treating literature cancer scores as a ready lesion-typing solution.

B38: [Nine real compact typing fits](breast-ai/B38_TYPING_WEIGHT_PILOT_2026-10-05.md)
completed. A1 raised FA recall by 10.16 points but lost 6.40 Mass recall points;
A2 lost 8.06 Mass points. Both rejected for promotion. Native source audit retained
1,189 single-target feature rows / 594 studies; no clinical deployment change.

| ID | Observed result | Decision and evidence |
|---|---|---|
| B37: Baseline reproduction and imbalance audit | Fresh legacy reference-ROI inference reproduces Mass recall/PPV 95.78%/75.42%, FA 84.91%/37.50%; no Asymmetry head. Metadata sampler audit: 630 target studies after two mixed-target rows deferred; six synthetic checks passed. | [B37 protocol](breast-ai/B37_TYPING_BASELINE_AND_IMBALANCE_2026-10-05.md). Compare A0 uniform control, A1 capped loss weighting, A2 tempered study sampling. No fit or improvement claim. Resolve source/geometry and label-assisted features first; legacy exposure prevents independent baseline claims. |

## Historical phases: September to October 3

| ID / phase | Work and observed result | Decision / evidence |
|---|---|---|
| B01: Product recovery | Recovered missing 60 interaction features and nine-input stacker contract; classification failures must be unavailable, not No Finding. Corrected Focal Asymmetry calibration direction. Legacy cascade diagnostic: 15/115 regions localized at detector 0.40, only 10/115 localized and typed Suspicious Calcification at classifier 0.275. | [Engineering and recovery record](EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md). Original Eagle Eye lineage. Reference-ROI classification is not end-to-end sensitivity. |
| B02: Dedicated calcification-region data | Prepared CBIS/VinDr targets, source/ROI geometry checks and cross-category patient partitions; isolated synthetic optimizer/reload proof followed by real A100 pilots. Region labels do not supply punctum truth. | [Training workflow](BREAST_CALCIFICATION_TRAINING_WORKFLOW.md). Preserve mass coannotations and unknown-negative handling. |
| B03: Detector pilots and transfer | Initial native1024 FCOS pilot: CBIS 4/10 region matches at 0.40 with 250 boxes; digital transfer 4/18 with 149 control boxes. Additional 500 updates reduced CBIS 4 to 1 and digital 4 to 3. Expanded cohorts and P2/P3 screens had mixed outcomes. | [Workflow](BREAST_CALCIFICATION_TRAINING_WORKFLOW.md) retains exact cohort-specific counts. Reject that continuation, not all detector families. |
| B04: DeepMiCa and tiling | Native high-resolution segmentation/tiling and physician region review exposed broad activation and oversized/merged boxes. Grouping contributed, but removing grouping alone left thousands of proposals. | [Tiling](BREAST_TILING_EXPERIMENT_2026-10-02.md), [failure diagnosis](BREAST_CALCIFICATION_FAILURE_DIAGNOSIS_2026-10-03.md). Reject cosmetic box correction as sufficient. |
| B05: Compact verifier | Strong patch-level scores did not transfer directly to whole-image candidate confirmation; one full-image cascade retained 118/157 provisional references versus teacher 151/157. | [Verifier experiments](BREAST_VERIFIER_EXPERIMENTS_2026-10-02.md), [expanded training](BREAST_KIOS_EXPANDED_TRAINING_2026-10-03.md), failure diagnosis. Patch sensitivity is not screening sensitivity. |
| B06: HDoG research reproduction | Native bright-object proposals and FPN confirmation supplied a reproducible research route. On a four-image subset, candidates covered 31/31 provisional references with 53,818 components on two negative images; FPN setting retained 25/31 with 70 negative components. | [Initial execution](BREAST_HDOGREG_INITIAL_EXECUTION_2026-10-03.md), [route decision](BREAST_CALCIFICATION_ROUTE_DECISION_2026-10-03.md). High raw recall requires confirmation. |
| B07: Intensity/shape/gradient features | Histogram, peak and spatial descriptors were examined. Particular hard contrast rules reduced 31 references to 5 or 0; mathematical features remain hypotheses, not universal absence tests. | [Histogram review](BREAST_HISTOGRAM_FEATURE_REVIEW_2026-10-03.md), [peak ablation](BREAST_HISTOGRAM_PEAK_ABLATION_2026-10-03.md), [methods review](BREAST_MICROCALCIFICATION_METHODS_REVIEW_2026-10-03.md). |
| B08: Candidate feature scorer | Historical ten-image development result reduced negative components 144 to 58 (59.7%) with 56/62 aggregate hits, but one old hit was lost and one gained. | [Candidate feature experiment](BREAST_CANDIDATE_FEATURE_EXPERIMENT_2026-10-03.md). This is the historical approximately 60% component reduction, NOT a 60-point sensitivity gain. |
| B09: Physician feedback | Preserved completed region boxes and display corrections; reconciled non-mammograms and reference semantics; later collected 143 physician dots. | [Attestation](BREAST_PHYSICIAN_ATTESTATION_2026-10-03.md), [region review](BREAST_PHYSICIAN_REGION_REVIEW_2026-10-03.md), [supervision recipe](BREAST_CALCIFICATION_SUPERVISION_RECIPE_2026-10-03.md). Existing labels remain versioned evidence. |

Additional historical references: [research shortlist](BREAST_MICROCALCIFICATION_RESEARCH_2026-10-02.md),
[same-domain verifier](BREAST_SAME_DOMAIN_VERIFIER_2026-10-03.md),
[HDoG joint experiments](BREAST_HDOGREG_JOINT_EXPERIMENTS_2026-10-03.md),
[October 3 execution plan](BREAST_CALCIFICATION_EXECUTION_PLAN_2026-10-03.md).
Their future-tense instructions are subordinate to the current-state document.

## October 4: broader research, then reset

| ID | Observation | Decision and report under P |
|---|---|---|
| B10: Detail/context and alternate anchors | Historical reused 29-image result: negative components 477 to 381 while retaining 77/80 provisional hits. Added veto CPU time was incremental only, excluding upstream FPN/candidate work. | Preserve useful geometry/context lessons, not a clinical performance claim. `IMAGING_MODEL_LESSONS_AND_EXPERIMENT_INDEX.md`. |
| B11: Positive expansion and hard-negative variants | 1,922 additional positive crops did not outperform matched control; later full-image hard-negative operating point lost seven parent hits on an additional cohort. | More patches/epochs alone not supported. `RESEARCH_RESET_AND_PRIORITY_PLAN_2026-10-04.md`. |
| B12: Broad two-stage routing | Proposals covered 195/195 provisional references; confirmation retained 189/195 with 15,007 negative components and median incoming crop coverage 98.92% of breast proxy. | Reject as efficient screening. Same reset report; candidate coverage is not final clinical success. |
| B13: Restricted context | Strict regional context retained 175/195 with 2,936 negative components; only 28/37 images met the area budget. Eligibility losses occurred before CNN scoring too. | Reject implementation; audit inputs and supervision before further gates. Same reset report. |

## October 5: corrected physician-point comparison

Current endpoint: one-to-one matching within 0.2 mm on physician-reviewed support.
Training positives: 75 references / six groups. Development positives: 68 references /
two groups. They are excluded from the new fit, but repeatedly development-exposed.
Do not compare these numbers directly with older publisher 8-pixel or region endpoints.

| ID / intervention | TRAIN or guard result | Development result / disposition | Evidence under P |
|---|---|---|---|
| B14: Native512 head-only BCE | Fixed native input/head contract; 62 retained training identities | 54/68, same identities as original HDoG; normal-image inside-mask points 4,775 to 4,100 on 16 images. Retain for research review, not qualified. | `headonly512-heldgroup-results-20261005.json`; `HEADONLY512_NORMAL16_DEVELOPMENT_2026-10-05.md` |
| B15: Decoder and smaller-context adaptations | Real bounded adaptations and native evaluation | Native512 binary decoder 54 to 51; tiny-fit MSE 54 to 49 / BCE 54 to 24. Reject tested configurations. | `binary512-heldgroup-results-20261005.json`; `DECODER_HELDGROUP_DIAGNOSTIC_2026-10-05.md`; `BCE_HELDGROUP_DIAGNOSTIC_2026-10-05.md` |
| B16: Compact morphology scoring | Seventeen-feature alternative | 54 to 53 held development hits. Reject tested candidate. | `morphology-held-development-results-20261005.json` |
| B17a: Mixed point / weak-region precursor | 62 identities retained, fitting normals 330 to 341 and sentinels 55 to 59. Baseline cutoff 0.000316227766; candidate TRAIN-selected cutoff 0.001. | Reject. Motivated the fixed top128-negative objective ablation, not treating every positive-box pixel as true calcium. | `MIXED_WEAK_HEAD_RESULTS_2026-10-05.md` |
| B17b: Hard-negative head training | 200 updates retained 62 anchors but normal counts 330 to 331; 600 updates yielded 727. Candidate TRAIN-selected cutoff 0.001 versus baseline 0.000316227766. Both fail training selection. | No new held run or threshold rescue. Objective reduction did not imply useful low-cutoff behavior. | `HARDNEG128_HORIZON600_RESULTS_2026-10-05.md`; `NEGATIVE_TAIL_DECISION_ROUND_2026-10-05.md` |
| B18: Pairwise ranking, 200 updates | Normal counts 330 to 285 but 62 anchors became 61 at fixed cutoff | Reject before held expansion. Lost reference had true support suppressed below cutoff. | `POINT_NORMAL_PAIRWISE200_RESULTS_2026-10-05.md`; `POINT_NORMAL_RANKING_DECISION_ROUND_2026-10-05.md` |
| B19: Constrained head | 62 anchors preserved; TRAIN normal counts 330 to 7; normal sentinels 28/27 to 0/0. Native numerical parity verified. | 54/68 to 34/68: 20 lost, none gained. Reject; do not expand to normal16 or tune threshold using held failures. | `CONSTRAINED_HEAD_DECISION_ROUND_2026-10-05.md` |
| B20: Failure attribution | Read-only exact native feature/score comparison | All20 newly lost references already had accurately localized candidates. Adapted scorer suppressed them. Simple feature distances did not prove a global positive-domain shift or one cause. | `CONSTRAINED_REPRESENTATION_ATTRIBUTION_2026-10-05.md` |
| B21: Old CNN lineage audit | Read-only source/group overlap | Existing detail/context CNN fit both current positive development groups; not admissible as independent current-split comparator. | `DUAL_VIEW_CURRENT_READINESS_2026-10-05.md` |
| B22: Broader point supervision | Six VinDr native crops, 3CC/3MLO, three models; typed annotation export validator built | No actual new physician export processed. Full INbreast unresolved; author TRAIN sample has32singleton labels over2images plus2larger components. | `REPRESENTATION_AND_DATA_COVERAGE_REVIEW_2026-10-05.md`; `AUTHOR_TRAIN_POINT_CONTOUR_READINESS_2026-10-05.md` |
| B23: Retained candidate miss review | Independent exact matching, crop pixels, geometry and original annotation hash checked | 14 misses:3without raw nearby support,11removed by score. Offline review built, synthetic tests passed; human visual acceptance and importance opinions pending. | `HEADONLY_MISS_IDENTITY_AUDIT_2026-10-05.md`; `held-miss-review-20261005/readiness.json` |
| B24: In-project consolidation | Reconciled prior project reports and current research receipts | Added canonical current-state document, this ledger, discovery links and update rule. Documentation-only; no runtime or model change. | This ledger and `BREAST_AI_DEVELOPMENT.md` |

### Numerical-validation corrections in B19

Failed receipts were preserved. Float64 active-constraint residuals at arithmetic-roundoff
scale were distinguished from actual cutoff violations, and native baseline comparison
was aligned with the existing grid-sampling contract. Both contract numeric checks and
exact decision masks were required. No model threshold or optimizer was changed to
rescue the subsequent 20-reference development loss. Consult the detailed B19 receipt
before reusing its validator; a numerical fix is not evidence of clinical improvement.

## Append format for the next experiment or review

B36,2026-10-05: [Fresh lesion-typing dataset audit](breast-ai/B36_LESION_TYPING_DATA_AUDIT_2026-10-05.md).
TRAIN Mass989/469studies, FA216/108studies, Asymmetry77/76studies. FA annotated on both
views in all108breast sides; Asymmetry on both in none of76, with image metadata
for both views available. Found20out-of-bounds target rows, two mixed-type rows,
substantial density/class imbalance and62/1162expected image paths missing. All
target studies overlap recovered legacy TRAIN lists. Saved18TRAIN review nominees;
no pixels reviewed, new fit or clinical accuracy claim. Prioritize data/geometry,
reviewed type/context labels and label-blind paired typing before detector changes.

B35,2026-10-05: [Legacy non-calcification typing review](breast-ai/B35_LEGACY_LESION_TYPING_REVIEW_2026-10-05.md).
Confirmed one-class FCOS plus four-label feature stack; independent Asymmetry output
absent. Real picker functions reproduced label-dependent and row-order-dependent
opposite-view selection on synthetic data. Historical reference-ROI Mass/FA results
reconciled with exposure limits. Prioritize label-blind correspondence, supported
class coverage and compact ROI/context classifier ablations. No new fit, clinical
inference, code patch or improvement claim; protected source-hash receipt saved.

B34,2026-10-05: [Point semantics and context crops](breast-ai/B34_POINT_SEMANTICS_AND_CONTEXT_CROPS_2026-10-05.md).
Owner accepts surrounding marks as useful localization: one model dot is not one
independent calcification. Retain native neighborhood crops for morphology; do not
make exact segmentation or one-dot-per-focus cleanup a prerequisite. Source confirms
image-minus-Gaussian local maxima followed by FPN scoring, not a direct gradient
threshold. Signal-transition explanation remains a hypothesis. Documentation-only;
no model/labels changed, B33 edge false-mark adjudications remain valid.

B33,2026-10-05: Physician explicitly clarified that all 13 cyan points are false marks
and their removal is correct. Separate source-bound adjudications saved under P in
`physician-air-filter-adjudication-20261005.json`; with the three B28 marks, all 16
filter-selected points on these eight exposed cases have physician-confirmed removal
support. This resolves the B30/B31 unknown flags but is not independent precision or
generalization evidence. Original dots/model unchanged; no automatic training or
production suppression. Physician also notes surrounding tissue highlighted during zoom.
Source inspection confirms viewer circles/squares have fixed display sizes, not
segmented lesion boundaries: cyan radius 8 display pixels, physician ring 4.5,
matched marker 2.1. These glyphs do not establish model contour oversegmentation.
Separate native lesion appearance, local surrounding tissue and cluster context for
future morphology training; points are not contours. No model/data/UI changes.

B32,2026-10-05: Added a reversible cyan numbered overlay for the 13 additional B31
filter flags to the existing offline eight-case viewer: two in 004, eleven in 006.
Orange squares distinguish the three previously reported wrong points. No detections
were removed; these are proposed filter effects, not adjudicated false positives.
Same browser storage key, original references and predictions preserved. Backup under
P/eight-case-point-comparison-20261005/backup-before-edge-review. HTML SHA256
`2d7b631314911cec7a6879470bfa9590329f99023870f0c19475432e9fc8c0dc`.
Embedded syntax, prior viewer/manifest/feedback tests and new rendering-command tests
passed (13 native-coordinate rings, numbering, case counts, toggles, hide-all).
Human GUI acceptance pending; no browser policy bypass or service launch.

B31,2026-10-05: Owner clarified narrow 1-2 mm band plus air/tissue evidence. Cached
B29/B30 intersection at either width flags the same 16 points: three reported errors,
zero original matched supports, 13 other points. No additional discrimination versus
B30. Bound aggregate saved as `air-band-intersection-20261005.json` under P;
[B30 addendum](breast-ai/B30_DIRECTIONAL_AIR_CONTEXT_2026-10-05.md) records interpretation.
No deletion or new inference enabled; mammography signal must not be treated as CT HU.

B30,2026-10-05: [Directional exterior context](breast-ai/B30_DIRECTIONAL_AIR_CONTEXT_2026-10-05.md).
Owner suggested air-versus-internal-tissue context. Implemented connected exterior
sampling with opposing tissue rays and physical spacing. V1 flags nothing; adaptive
V2 flags all three reported errors, zero of 116 original matched supports and 13
other points. Compactness guard reduces flags but catches only one of three errors.
Five synthetic tests per version passed. Feature retained for review only; no automatic
suppression, fitting or clinical improvement claim on these exposed eight cases.

B29,2026-10-05: [Skin ablation and morphology foundation](breast-ai/B29_SKIN_AND_MORPHOLOGY_2026-10-05.md).
Implemented separate descriptor/adequacy contracts and physical group measurements;
six synthetic tests passed. CPU audit on eight exposed cases found 1 mm silhouette
exclusion removes all three reported errors but also one existing matched support
and 25 other points. Reject blanket suppression. TRAIN descriptor inventory: 1,546
rows/602 people, 261 mixed morphology rows, 20 missing morphology and 376 missing
distribution rows. No trained morphology classifier, new neural inference or deployment.

B28,2026-10-05: Actual physician click-feedback intake passed the bound validator.
Eight-case export contains three incorrect-model marks, all in review case 006,
linked to three distinct predictions; zero missed-calcification marks were supplied.
This localizes the previously reported skin error, but three clicks do not establish
three separate lesions or a whole-cohort precision estimate. Empty feedback is not
exhaustive negative truth. Export SHA256:
`e5d43b031525a21e3a3c7f61e2715151c22b213803e8737c9ee6fbbfd3b22e20`.
Protected intake under P: `eightcase-feedback-dryrun-20261005T113548023344Z`.
Separate aggregate and private proposal saved; no original labels or model changed,
no training import or inference. Next: inspect the localized skin-error mechanism
against retained true calcifications before proposing any suppression rule.

B27,2026-10-05: [Separate click feedback](breast-ai/B27_CLICK_FEEDBACK_2026-10-05.md).
Added incorrect-model and missed-calcification modes to the same offline eight-case
viewer, with native coordinates, undo, notes, autosave and bound JSON export/import.
Original143 references and model outputs unchanged. Viewer/manifest/feedback checks,
embedded syntax and six Python intake tests passed; human GUI acceptance pending.
No training, inference or new accuracy claim. Next: physician marks the skin error
and exports feedback for validated intake.

B26,2026-10-05: [Physician visual assessment](breast-ai/B26_PHYSICIAN_VISUAL_REVIEW_2026-10-05.md).
Owner viewed all8cases and reports only one wrongly marked skin region; other extra
marks were real tiny calcifications omitted from original clicks. Retain candidate;
do not equate unmatched red points with false positives or train them as negatives.
Near-complete finding is qualitative physician opinion, not recalculated sensitivity.
Skin case/location requested; no original labels/model changed. Independent cohort,
normal16 adjudication and Razi comparison remain open.

B25,2026-10-05: [Eight-case visualization and frozen inference](breast-ai/B25_EIGHT_CASE_VISUAL_COMPARISON_2026-10-05.md).
All143 physician dots preserved; TRAIN62/75 and development54/68 remain separate.
Yellow references, green actual matched predictions, red unmatched predictions;
red is not automatic negative truth. Original display assets and geometry verified,
viewer tests passed, human GUI check pending. No new training or Razi comparison.

Artifact recovery follow-up, 2026-10-05: read-only checks rehashed the delivered FCOS
detector on Razi, Windows A100 and this checkout; all match `9f874666...5679901`.
Two Linux training checkpoints and the Windows SERVER_COMPATIBLE delivery sibling
differ. Exact locations/hashes and limits are in the current-state document. This
finds the initial detector comparator, not a completed paired evaluation or verified
training-run provenance. No live inference, checkpoint loading or deployment occurred.

Comparison clarification, 2026-10-05: the owner requested improvement percentages
against initial Razi deployment. The current-state document now records why original
FCOS region diagnostics and current HDoG point results cannot supply that percentage.
No matched Razi-versus-candidate experiment or new inference was executed for this
report. The14.14%reduction is HDoG-to-head-only point burden; the59.7%historical reduction
is a separate component experiment. Neither is a clinical Razi improvement estimate.

Use the [reporting contract](BREAST_AI_REPORTING_STANDARD.md) for a full training review;
the [B19 run card](breast-ai/B19_TRAINING_REVIEW_2026-10-05.md) demonstrates retrospective
completion from receipts, including missing fields and inapplicable solver telemetry.
The compact ledger does not substitute for that record.

Assign the next B-ID and record:

- Date, status and hypothesis; which prior decision this tests.
- Data version, reference meaning, source/patient groups, split and prior exposure.
- Comparator and candidate hashes, preprocessing/features, thresholds and output rules.
- Exact endpoint, denominator, per-group results, lost/gained identities and unwanted marks.
- Actual runtime/resources and complete versus cached/incremental timing scope.
- Code/data validation, physician review, GUI and deployment status separately.
- Continue/reject/defer decision, reason, artifact location and next discriminating action.

Update the current-state document in the same session. A blank, unfinished or unavailable
review is not negative truth. Clinical importance feedback is not an automatic annotation
correction. Preserve both the original endpoint and any newly defined physician endpoint.
