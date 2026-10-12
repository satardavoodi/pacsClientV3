# Breast AI development: current state and continuation guide

Last reconciled: 2026-10-07 (Asia/Tehran). Owner: Breast AI / Eagle Eye model-development workstream.

**Start here for every Breast AI continuation.** This document owns the current research
state, stage gates, decisions and next action. The [experiment ledger](BREAST_AI_EXPERIMENT_LEDGER.md)
owns the chronological summary. Earlier dated reports remain evidence for their own
experiments, not competing current plans. Update both documents in the same work session
as an experiment, physician review, data correction or decision.

## 1. Current state in plain language

**October 10 B96 deployment incident:** The active `20261010-ordinary-human-r2`
snapshot omitted the separate calcium payload binding. The latest Breast envelope
reported `calcium_bundle_not_installed` while classification completed; this is
an availability failure, not a negative finding or demonstrated model failure.
The preserved B95 payload matches local: 445 sealed files, zero hash differences.
Canonical eight-model Developer preflight and four fail-before guards now prevent
silent omission. Controlled candidate integration, service activation and actual
client/Server calcium acceptance are pending. See [B96](breast-ai/B96_CALCIUM_PAYLOAD_RUNTIME_INCIDENT_2026-10-10.md).

**October 8 B95 performance continuation:** [B95](breast-ai/B95_PEAK_LATENCY_2026-10-08.md)
accelerates physical candidate extraction while retaining B94 neural scheduling.
B95 measured 193.8967 -> 139.4573 seconds (28.08% further reduction); all
659511 intermediate peaks and 334 final support points/scores/filter results match.
Accepted as Developer candidate; original weights and thresholds retained.
No clinical activation; see B93 remaining gates.


**October 8 separate viewer layers:** [B91](breast-ai/B91_SEPARATE_DISPLAY_LAYERS_2026-10-08.md)
adds independent parenchymal and microcalcification controls in Breast source UI.
Legacy FCOS calcium labels are filtered for display without deleting detections or
rewriting human labels. The new native-point sink is identity-bound and unavailable
until its dedicated result arrives. Thirty focused tests pass; live GUI and B90's
authenticated calcium artifact connection remain pending, not a completed rollout.

**October 8 dual-branch implementation:** [B90](breast-ai/B90_DUAL_BRANCH_INTEGRATION_2026-10-08.md)
implements a research request that preserves FCOS/stacked classification and runs
the frozen calcium localizer in a separate CPU process. Both actual models completed
a synthetic parallel request; 11 integrity/geometry tests pass. No clinical client
route or service activation yet. Native reproduction, CPU study budget and server
artifact/display integration remain separate gates. This owner-requested integration
proceeds alongside B82 data reconciliation; it does not authorize another training sweep.
Native calcium CPU check: 205.781 seconds for 4096x3328; 621/622 reviewed output
points reproduced. One score crossed the frozen cutoff under the new runtime;
this is numerical portability evidence, not a new sensitivity estimate. CPU cost
and that discrepancy remain blockers to claiming the requested clinical rollout.
Both actual branches also passed a synthetic request on the Razi Developer candidate
(35.747 seconds); 11 guards pass on both hosts. Declared 8,170-file source inventory
and additive dependency archive match. Active r4 and the clinical client are unchanged.

**October8 requested deployment:** [B89 promotion readiness](breast-ai/B89_PROMOTION_READINESS_2026-10-08.md)
staged10 calcium research assets on local/Razi with matching hashes. Activation is
BLOCKED: no production FPN adapter, missing worker dependencies, no complete CPU or
client acceptance. Local synthetic helpers pass; tissue replacement not justified.
Active Razi remains r4. Research readiness below is not production qualification.

### Active decision map (owner consolidation, October 7)

**Owner-approved output contract (October 7):** finding presence, finding type and
malignancy assessment are separate outputs; calcium and parenchymal processing are
separate paths. B83's technical follow-up specifies masked supervision, benign
retention and a candidate-negative data ablation. Uncalibrated suspicion is not a
clinical probability or BI-RADS. This contract is approved, not yet implemented as
a qualified multi-output model; the data-readiness gate below still applies.

This map is the operational entry point. B82 supplies the detailed rationale; the
dated summaries below preserve history, not parallel instructions to start work.
**Only active action: reconcile the reference and candidate dataset. No new fit
is queued until its readiness record is complete.** Consolidation is complete as
documentation; the data reconciliation itself is not yet complete.

| Owner need | Current evidence | Missing evidence | Next permitted action |
|---|---|---|---|
| Describe a detected lesion as Mass, AD or asymmetry family | B72: macro-F1 at most49.06% among tested pipelines; minority recognition inadequate | Reliable exact-ROI references, rare-class support, actual detector-crop performance | Reconcile existing physician feedback and audit class coverage |
| Avoid marking normal tissue while retaining real findings | B78:78.73% reference matching at0.20 with60.68 marks/normal image; B81 only small reduction | Reviewed detector false alarms and a task-matched presence verifier | Build study-grouped positive/normal/unknown candidate records |
| Describe shape/margin and eventually assessment | B50 source attribute pretraining; no qualified target descriptor or BI-RADS output | Descriptor labels, view/context and separate assessment truth | Inventory available labels; do not infer BI-RADS from type alone |
| Preserve useful calcium behavior | B25-B34 physician acceptance on eight exposed cases, including edge adjudication | Independent cohort and morphology qualification | Preserve candidate and feedback; do not retrain incidentally |
| Serve with acceptable CPU latency | Some partial research timings exist | Full target-host study latency and resource budget | Measure only a retained complete candidate; do not extrapolate GPU timings |

### Lessons that constrain future work

**B83 commercial evidence review (October 7):**
[Hologic, Siemens/Transpara, iCAD and Lunit](breast-ai/B83_COMMERCIAL_AI_REVIEW_2026-10-07.md)
support staged detection/scoring and richer outcome-linked reference categories.
Their cancer-screening and reader endpoints do not establish our exact lesion-typing
accuracy. Preserve benign finding presence separately from suspicion; longitudinal
priors remain data-dependent. No new fit or local performance result; B82 stage1
reference reconciliation remains the only active action.

| Tested route / records | What we learned | Disposition and reopening condition |
|---|---|---|
| Class weights/resampling, B38/B50 | Minority gains often cost Mass recall | Stop repeating recipes; reopen with changed supervision and a matched tradeoff test |
| Calcium feature transfer into tissue typing, B41/B44 | Shared decoding saves work; shared classification gain was not established | Retain engineering reuse; no new calcium-feature fusion without distinct evidence |
| Generic scalar/spatial features, B39/B57/B58 | Class distributions overlap; measured fusion gains were negligible | Archive tested recipes; reopen only for a specific reviewed failure mechanism |
| Short encoder adaptations, B45/B64/B65/B69/B70 | Some class tradeoffs, overfitting or no reliable gain; not architecture ceilings | No arbitrary backbone sweep; require distinct representation and adequate training rationale |
| Source shape/margin pretraining, B50/B62 | Already performed; not a new proposed solution | Retain as comparator; joint validated descriptor outputs would be a different task |
| Calcium hard-negative/constrained scoring, B11/B17-B20 | Training negatives can fall while true held lesions are lost | Do not generalize training success; require identity retention on held groups |
| Bilateral NCC and anatomy, B79-B81 | Geometry is reusable; similarity thresholds did not provide sufficient rejection | Stop hard-filter tuning; geometry may supply a later learned search prior |
| Physician reviews, B26/B33/B55/B63 | Unmatched predictions can be real; partial exports can conflict | Preserve originals and review provenance; unresolved is not negative truth |
| Publisher TEST, B71/B72/B76 | Useful comparisons but now exposed; endpoints are different | Keep results; never relabel the same cohort as fresh independent confirmation |

### Ordered work queue and completion evidence

[B88 targeted review](breast-ai/B88_TARGETED_REFERENCE_REVIEW_2026-10-07.md) is ready:
24 native-source regions from24 studies, six per normal-score band plus six
reference-overlapping low-score candidates.48 images and24 float crops retrieved.
First layout inspection raised a reference concern in a publisher-normal region;
no diagnosis or relabeling inferred. Physician region judgments are the next input.
Do not treat the127 publisher-normal marks as adjudicated false positives or fit
them as hard negatives before reference reconciliation.

**Current continuation route after B87 (owner confirmed):** the score analysis
supports the existing presence-verifier work; it is not a new threshold-tuning
workstream. Stage1 is in progress. B86 completed technical box-to-source binding;
clinical region scope, split/exposure reconciliation and reviewed negatives remain.

1. Audit study/person and fitting exposure for the candidate pool and reviewed
   positives. Preserve fitting-exposed cases for development, not confirmation.
2. Stratify review by [0.40,0.45), [0.45,0.50) and >=0.50, including both true
   findings and suspected normal mistakes. Keep all cases from a person together.
   Reuse completed reviews; request only missing target-specific adjudication.
3. Freeze references and comparison partitions, then run B84 E1 at equal budget.
   Keep0.45 as an important threshold-only comparator, alongside0.40 and0.50;
   it is not declared the optimal threshold or applied to production here.
4. Measure whether the verifier retains useful lower-score findings while rejecting
   normal marks, and whether it also fixes high-score false marks. Compare at matched
   sensitivity and locked operating points; report all new misses and CPU cost.
5. Continue detector-crop typing and separate/shared-head tests only with sufficient
   region labels. Malignancy assessment requires linked outcomes; calcium remains
   a separate retained branch throughout.

B87 score bands serve sampling and error analysis. They must not become pathology
labels, automatic-normal rules, BI-RADS or calibrated malignancy probabilities.
The B82/B84 20% mark-reduction target is a research signal, not final product
acceptance: reducing127 marks to roughly102 on83 normal images is still a substantial
burden. Final acceptance needs an explicitly agreed operating point and independent
evidence; no new numerical clinical target is inferred from this discussion.

[B87 score-band replay](breast-ai/B87_SCORE_BAND_REPLAY_2026-10-07.md): on the same
development cohort, thresholds0.50/0.45/0.40 yield12/16/20 matches out of34 and
11/46/127 marks on83 publisher-normal images. Use bands for targeted review;
compare later verifier with threshold-only controls. No production threshold change.

[B86 scope and candidate replay](breast-ai/B86_SCOPE_AND_CANDIDATE_REPLAY_2026-10-07.md)
verified24 reference-box/source-row bindings (documented rounding), all fitting
exposed. Replayed B81 at0.4:20/34 matches,127 marks on83 publisher-normal images;
saved127 provenance-bound candidate records for review, not automatic negatives.
Next study/exposure audit and targeted unresolved review; E1 training not started.

[B85 field-level audit](breast-ai/B85_REFERENCE_READINESS_AUDIT_2026-10-07.md)
executed:24 stored cases,23 finished,23 dominant-appearance consensus records;
17 have other export-field differences. Historical next action was technical ROI
binding, completed in B86; semantic clinical scope and training eligibility remain
unresolved. Follow the current continuation route above, not this historical step.

[B84 controlled experiment protocol](breast-ai/B84_CONTROLLED_EXPERIMENT_PROTOCOL_2026-10-07.md)
now defines readiness gaps, E0-E5 comparisons, equal-budget negative sampling,
locked-threshold/paired uncertainty rules and CPU measurement. It operationalizes
B82/B83; no manifest reconciliation, new harness or fit is completed by this record.
Next remains the protected reference audit, then E0 and E1 after readiness.

| Stage | Status | Deliverable required to advance |
|---|---|---|
| 0. Consolidate history and decisions | Completed documentation; B82 and this map | Source-linked lessons, retained/rejected routes and explicit unknowns |
| 1. Reconcile data and references | IN PROGRESS; B85-B87 partial audits complete | Versioned protected manifest, merged review provenance, unresolved-field list, class/study/view/negative/unknown counts, source availability and exposure report |
| 2. Targeted missing-label review | Pending stage1 | Reuse completed reviews; present only unresolved/new informative regions with full-view context; preserve benign versus normal distinction |
| 3. Freeze benchmark and protocol | Pending stage2 | Study/person grouping, calibration partition, unexposed confirmation reserve, paired endpoints, numerical retention guardrails and compute cap |
| 4. One controlled data/representation experiment | Not started | Same candidates and splits; local presence/type baseline, data ablation, eligible distinct representation only if available; per-class results and FROC |
| 5. Continue or stop | Pending stage4 | B82 research gates plus uncertainty, lost-lesion review and whole-pipeline CPU cost; no promotion from one favorable metric |

Every new experiment must state: which need it addresses; which existing result it
builds on; what has materially changed; the fixed comparator/data/metric; and the
stop rule. If those fields are missing, do not start it. Amend the active row after
each result, including null/negative findings. Add a new report only when there is
new substantive evidence or a distinct decision, not to restate the same plan.
Do not pool unlike cohorts or multiply repeated seeds into independent subjects.
Requests for clinician input must identify the exact unresolved reference question
and preserve completed work. This map does not claim data or model completion.

**B82 program reassessment controls next work (October 7):**
[Data-first decision and stopping rules](breast-ai/B82_PROGRAM_REASSESSMENT_2026-10-07.md).
Pause immediate fitting from B81. Neither adequate soft-tissue typing nor useful
false-mark reduction is qualified; no technology ceiling established. Most typing
cohorts lack normal-reference candidates; limited AD supervision and short pilots
do not settle architecture capability. Reconcile existing physician feedback and
actual detector hard negatives before one data-versus-representation experiment.
Mammo-FM is a distinct domain-pretraining lead, but listed weights forbid industry
evaluation without written permission and clinical use; no download or qualification.
Do not repeat scalar-feature/NCC/short-backbone sweeps. Keep benign finding presence
separate from cancer suspicion. New adjudicated data and an unexposed reserve are
prerequisites to a credible next training decision.

**B81 anatomy-aware bilateral pilot completed (October 7):**
[Existing geometry development test](breast-ai/B81_ANATOMY_DEVELOPMENT_PILOT_2026-10-07.md).
64 TRAIN studies/128 CC images,34 reference boxes,83 explicit normal images. Existing
3D Cursor geometry reused: PNL+NCC retains the same20 matched lesions and reduces
normal marks127->121 (4.72%); simple position comparison127->119 (6.30%). No added
benefit from anatomical mapping established. Seven checks pass;126 automatic anchors,
four high-NCC pairs visually inspected, no physician correspondence qualification.
Stop hard NCC-filter tuning; retain geometry as search prior for a learned local versus
bilateral verifier after larger TRAIN correspondence review. No production change.

**B80 existing localization reuse selected (October 7):**
[3D Cursor source audit](breast-ai/B80_EXISTING_LOCALIZATION_REUSE_2026-10-07.md).
Existing nipple/chest-wall/PNL geometry and contralateral record matcher were not
used in B79. Reuse pure components through a study-scoped offline adapter; extract
opposite-side tissue even without a detected finding. GUI bilateral gate defaults
off; installed Razi parity is unverified. Existing tests:50 passed,2 expected failures.
No new clinical metrics. Next landmark/correspondence review on TRAIN/development,
then local-only versus anatomy-aware verifier; no symmetry-based hard deletion.

**B79 bilateral feasibility completed (October 7):**
[Deterministic pairing screen](breast-ai/B79_BILATERAL_FEASIBILITY_2026-10-07.md).
No fitting: same-view contralateral local NCC on B76 proposals at0.4. Cutoff0.85:
normal marks3751->3631 (3.20%), matched lesions198->197/362. Cutoff0.9:26 fewer marks,
matched count198 retained. Sham different-study control reduces marks only0.80% at0.85.
Small exploratory signal, below20% engineering target; no deployment. Not the trained
B78 verifier or CC/MLO test. Next TRAIN-only paired candidate manifest and anatomy-aware
correspondence review before local versus bilateral reranker fitting.

**B78 bilateral/multiview verifier priority (October 7):**
[Evidence, code audit and experiment contract](breast-ai/B78_BILATERAL_MULTIVIEW_REVIEW_2026-10-07.md).
All843 available studies have a unique standard four-view quartet. Existing pairing
can use labels or first available ROIs; it is not a validated anatomical comparator.
Threshold diagnostic:0.45->0.40 increases matching161->198/362 but normal marks
1305->3751;0.20 matches285/362 with137005 marks. Prioritize label-blind bilateral and
ipsilateral verifier ablations on TRAIN/development, retaining single-view fallback.
No bilateral benefit measured locally yet; no TEST-based training or threshold adoption.

**B77 prior detector challenge completed (October 7):**
[YOLOX native-image results and external access audit](breast-ai/B77_PRIOR_DETECTOR_CHALLENGE_2026-10-07.md).
75 calcification-positive/128 normal images,80 clusters. Adapted-BN prior YOLOX finds
54/80 at0.01 but4405 normal marks versus Razi22/80 and67 marks. At0.1 YOLOX19/80
with436 marks; other pilot0/80. No useful superiority established. Calcification-only
matching differs from B76; do not compare these percentages with all-lesion44.48%.
External YOLOv5 mass weights not obtained due Kaggle location denial. General-lesion
external comparison remains open; next retained native calcium verifier evaluation.

**B76 full-image replay completed (October 7):**
[Results and run record](breast-ai/B76_FULL_IMAGE_DETECTION_REPLAY_2026-10-07.md).
3372 images inferred, zero decode failures;5 invalid-reference images excluded from
localization. Both original0.002 area filter and research removal:161/362 lesions
matched (44.48%, IoU0.3);1081/2258 negative images marked (47.87%). Zero measured gain
from filter removal. IoU0.5 recall29.83% warrants native geometry review. This is Razi
source/weight GPU replay, not verified live CPU service. Dedicated calcium branch
not included. Next review misses/box geometry then test frozen native calcium path.

**B75 full-image detection benchmark selected (October 7):**
[Dataset selection and verified inventory](breast-ai/B75_DETECTION_BENCHMARK_SELECTION_2026-10-07.md).
VinDr TEST locally has3372 images/843 complete studies:295 boxed-positive images,
2258 explicit BI-RADS1/No Finding negative candidates,819 unresolved/unboxed images.
Available368 annotation rows need geometry/deduplication QC.628 TEST images unavailable.
Primary next endpoint is class-agnostic full-image localization plus false marks,
not reference-ROI typing. VinDr omits BI-RADS2 boxes; external INbreast candidate
and CBIS complementary lesions do not remove exposure/access limitations. No inference
in B75. Freeze scoped manifest after QC; keep production untouched.

**B74 Razi source replay executed (October 7):**
Owner clarified the primary endpoint as any-lesion detection regardless of type.
Corrected legacy positive-head union covers263/272 supplied reference boxes (96.69%);
this is not full-image detection recall. Research forced typing has no normal class.
Direct class-agnostic localization comparison remains unmeasured in B72/B74.
[Replay and corrected diagnostic](breast-ai/B74_RAZI_TEST_REPLAY_2026-10-07.md).
The copied Razi worker rejects its loaded stackers:4 expected inputs versus9 saved.
Classification unavailable for the272-ROI intended batch; no accuracy assigned and
no live-request claim. Separate corrected legacy code matches all272 reference rows:
Mass191/199 found but39/73 non-Mass overcalled; FA32/40 found;39 Mass/FA conflicts.
These are precomputed-feature diagnostics, not deployed performance. No promotion.
Next verify live response status and qualify an isolated full preprocessing replay.

**B73 Razi comparison audit (October 7):**
[Deployed comparator provenance](breast-ai/B73_RAZI_COMPARATOR_AUDIT_2026-10-07.md).
All14 classifier assets in the October4 service revision match the local legacy
assets, but classifier code differs from the corrected local implementation.
Legacy labels lack distortion; B72 is not a Razi comparison. Research superiority
over Razi remains unmeasured. Next reproduce the deployed path off-host with explicit
classification failure accounting, then compare supported endpoints on common ROIs.
No production changes or new accuracy measurement in this audit.

**B72 publisher TEST evaluated (October 7):**
[Six pipelines,18 checkpoints](breast-ai/B72_PUBLISHER_TEST_EVALUATION_2026-10-07.md).
272 available reference ROIs/138studies,199Mass/18AD/55family;53missing-source rows
explicitly excluded. TRAIN study/image/exact-file overlap checks pass; patient,
historical Razi and broad pretraining independence unproven. B64 accuracy67.28%,
EfficientNet68.26%, DINO56.25%; B50 transfer70.83% but AD7.41%. Weighted B50 macro49.06%
is numerically highest, no clear paired macro superiority. No promotion or TEST tuning.
This evaluation consumes the new benchmark; later tuning needs independent confirmation.

**B71 owner priority: independent shared benchmark (October 7):**
[Benchmark contract and provenance audit](breast-ai/B71_INDEPENDENT_BENCHMARK_CONTRACT_2026-10-07.md).
Separate VinDr lesion typing from CBIS mass shape. Existing cohorts are development;
publisher TEST is only a candidate until historical exposure, identity/duplicate and
source audits pass. Original Razi training exposure remains a distinct unknown.
Next freeze an eligible protected manifest before new test inference or tuning.
No test run or new accuracy in B71; this supersedes immediate fitting plans below.

**B70 ResNetV2 shape pilot completed (October 7):**
[Paper audit and real fits](breast-ai/B70_RESNETV2_SHAPE_PILOT_2026-10-07.md).
Independent Keras ResNet50V2 on1,005 single-shape CBIS regions/550groups, three
grouped splits: accuracy38.83%, macro31.80%, training96.89%; majority30.16%.
Exact reload passed; memory-capped interruption recovered with preserved receipts.
Not a reproduction of the paper's three-model segmented-ROI ensemble or BI-RADS
result. No promotion. Next audit segmentation/assessment label readiness before
further descriptor architecture expansion; B69 typing findings remain separate.

**B69 completed; no promotion (October 7):**
Majority baseline clarification: always-Mass mean split accuracy76.42%, with zero
AD/family recall; the reference70.00% alone is not evidence of strong typing.
Accuracy clarification: mean development split correct-label accuracy is70.00% for
the matched research reference and69.46% for EfficientNet; not original Razi accuracy.
[EfficientNetV2-S actual training review](breast-ai/B69_EFFICIENTNET_TRAINING_REVIEW_2026-10-07.md).
Three five-epoch fits on the matched1,147-ROI cohort completed with exact checkpoint
replay. Macro-F1 50.80% vs50.87% control; Mass75.50 vs76.31, AD29.37 vs23.10,
family52.47 vs58.13. Gate failed; all paired difference intervals include zero.
Keep production and research reference unchanged. Next: controlled training-only
class balance/reference audit, then conditional hard-example supervision, not another
unstructured backbone or longer-epoch sweep. This supersedes B66-B68 next-fit wording.

**B68 practical compatibility checked (October 6):**
[Code/interface and CPU check](breast-ai/B68_ARCHITECTURE_COMPATIBILITY_2026-10-06.md).
EfficientNetV2-S fits the existing paired ROI/context typing interface. Actual
synthetic CPU forwards passed: 99.96 ms per pair versus ResNet18 40.68 ms on lina100,
two threads, random weights; not Razi/end-to-end timing or accuracy evidence.
Select it as first new training comparator, not proven winner. No new fitting.

**B67 MONAI and staged-classifier review (October 6):**
[Inventory and stage contract](breast-ai/B67_MONAI_AND_STAGED_CLASSIFICATION_2026-10-06.md).
Official breast bundle classifies density A-D; it does not type lesions or assign
lesion BI-RADS. No ready Mass/asymmetry/AD typing bundle identified in the inspected
catalog. Keep B66 comparator first; test conditional descriptor/type experts only
for incremental benefit with routing errors and CPU cost included. No new training.

**B66 current decision: independent second-stage classifier (October 6):**
[Literature and architecture review](breast-ai/B66_STANDALONE_ROI_CLASSIFIER_REVIEW_2026-10-06.md).
Keep localization fixed. Published ROI typing exists, but mass malignancy/BI-RADS
results do not establish Mass/asymmetry/distortion separation. B50/B64/B65 already
used supplied ROIs; no proven winner yet. Next: a paper-informed compact
EfficientNetV2 paired comparator, then a separately controlled metric-learning arm
if needed. Descriptor supervision and production-box robustness remain distinct
gates. B65 calibration/fusion is deferred. This ordering supersedes historical next
actions below. No new training or accuracy gain in this literature review.

**B65 completed independent representation challenge (October 6):**
[DINOv2 results](breast-ai/B65_DINOV2_REPRESENTATION_REVIEW_2026-10-06.md).
Official ViT-S/14 downloaded/pinned and actually run. Nine frozen probes and three
last-two-block adaptations completed on the B64 common cohort. Adapted DINO macro-F1
51.24% versus50.87%control; AD41.51% versus23.10%, family85.92% versus58.13%, but
Mass recall56.88% versus76.31%. Equal probability fusion macro53.46%, Mass68.70%:
both fail retention. DINO reduces source-nonmass Mass overcalls, not measured normal
false positives. Retain B50/production; no deployment. Next: group-disjoint calibration
or cross-fitted combination with disagreement/reference audit, not outer-development
weight tuning. This is the current next experiment after B62-B64's completed stages.

**B64 completed, retain B50 (October 6):**
[Run card](breast-ai/B64_NATIVE_CONTEXT_TRAINING_REVIEW_2026-10-06.md).
Native source audit found117 unavailable images/123 rows, so the paired experiment
uses1,147 retained ROIs with whole-study exclusions applied equally to both arms.
Original split assignments and labels stay fixed; cached224 inputs did not replace
missing native detail. All2,294 input parity checks passed. Twelve actual fits compare
five and ten epochs: native384 macro-F1 51.70% versus matched224 50.87% at five epochs
(+0.83points, interval includes zero); at ten epochs44.88% versus47.83%, with family
recall30.24% versus39.03%. Both retention gates fail; longer fitting overfits and
increases Mass preference. No replacement/deployment. Next B62 compact independent
representation challenge after readiness checks; do not repeat this resolution sweep.
This amended cohort cannot be directly compared with original B50's52.12%. See the
run card and the
[B50 retrospective comparator card](breast-ai/B50_RETROSPECTIVE_RUN_CARD_2026-10-06.md).

**B63 execution result (October 6):**
[Supplemental replay and feedback reconciliation](breast-ai/B63_SUPPLEMENTAL_REPLAY_2026-10-06.md).
Unchanged B50 seed17/29/43 all classify the four additional physician view regions
as Mass (12 checkpoint-region outputs). Source-reference input parity and exact
checkpoint reload passed. This supports ROI typing on these exposed cases, not
independent detection performance or a new accuracy gain. Three feedback exports
preserved as 24-case union; partial snapshots do not erase prior reviews. Conflicting
or empty-vs-populated fields remain protected alternatives, not training labels.
Next: native-context ablation readiness on unchanged source labels/splits under B62;
no new training has run in B63. Historical ordering below remains subject to B62.

**Active owner priority B62 (October 6):**
[Retrospective and implementation plan](breast-ai/B62_RETROSPECTIVE_AND_IMPLEMENTATION_PLAN_2026-10-06.md).
Historical experiments and external methods reviewed before further training. B50
already used four shape/five margin auxiliary targets; do not repeat this as a new
multitask proposal. Reconcile exact physician ROI references and replay unchanged B50
on supplemental boxes first. Then test native local224/context384 against the matched
control. A compact DINOv2 alternative and retained descriptor/valid region supervision
are conditional later experiments, with explicit gates and CPU timing. No new fit,
inference or performance gain in B62. This is the sole active ordering; dated entries
below preserve their historical evidence and do not override it.

**Historical owner priority B61 (October 6):**
[Classification-first plan](breast-ai/B61_CLASSIFICATION_FIRST_PLAN_2026-10-06.md).
Hold localization fixed and improve ROI appearance typing, then supervised mass
shape/margin characterization, with BI-RADS assessment a later separate task.
Reconcile all physician exports per record, preserve supplemental ROI identities,
then compare the retained B50 control with native-detail and eligible descriptor
supervision in separate controlled arms. B57 proxies were not a proven improvement.
Version legacy/current vocabulary; no blind assessment from softmax or descriptors.
This plan supersedes older next-action wording below; no new training ran in B61.

**B60 annotation scope clarification:** physician describes the additional masses
as BI-RADS 2. VinDr publisher excludes BI-RADS 2 finding boxes; B50 crops use existing
annotated boxes and B55 is reference-ROI classification, not autonomous detection.
No explicit BI-RADS cutoff found in inspected B50/B54 selection; do not interpret
absent B55 reference boxes as runtime suppression or established detection misses.
All-mass typing needs benign appearance coverage separately from suspicion grading.

**B60 boxes received (October 6):** two identical exports validated and preserved.
Four view-specific boxes across two cases match native source hashes and geometry.
Both primary boxes are outside the original reference ROIs, so prior model scores
must not be attributed to these new regions. Cross-view lesion counts remain unknown.
See B60 intake evidence; no new classifier inference/training or accuracy claim yet.

**B60 additional-finding localization (October 6):**
[Supplementary boxes](breast-ai/B60_ADDITIONAL_LESION_BOXES_2026-10-06.md).
The physician authorizes drawing additional lesion boxes. Extend the same B55 page
with full-primary/companion native-coordinate rectangles, separate storage/export,
and direct case navigation. Existing reference labels and clinical answers remain
unchanged. Await the new exported locations before any localization or training claim.

**B55 feedback received (October 6):** both physician exports validated and preserved.
The latest contains 24 records/23 finished; an unfinished record is not a negative.
Two comments report three additional masses, with localization pending. A reference
ROI versus additional-lesion label conflict requires clarification before any label
conversion or scoring. See the B55 report intake section and protected receipt.

**Immediate review-quality correction, B59 (October 6):**
[Native window/level review](breast-ai/B59_NATIVE_WINDOW_REVIEW_2026-10-06.md).
The physician reports reviewing through case 11. The old B55 controls filtered an
8-bit PNG, so they could not recover discarded signal differences. Replace display
controls with retained native-signal windowing while preserving feedback identity.
This is a display-only correction; physician answers have not yet been imported or
counted as model evaluation. B58 classification research remains the next research
route after adequate physician review images are available.

**Active continuation after B58 (October 6):** [Direct spatial surfaces](breast-ai/B58_SPATIAL_INTENSITY_SURFACES_2026-10-06.md).
18 native boxes/18 common-fitting studies, six each Mass, Focal Asymmetry and
Asymmetry. Central contrast medians 0.137/0.051/0.097 and adjacent variation support
the proposed pattern in some examples, but all measured class ranges overlap.
No fit or accuracy gain. Next inspect unclipped signal and surrounding context on
these same cases before another classifier. Preserve B50 and pending B55 correction.
This takes priority over the historical next-action statements below.

**Active decision after B57 completed experiment (October 6):** [Spatial morphology results](breast-ai/B57_SPATIAL_MORPHOLOGY_EXPERIMENT_2026-10-06.md). Reject this tested feature fusion; preserve B50. Continue [B55 model-assisted correction](breast-ai/B55_MODEL_ASSISTED_REVIEW_2026-10-06.md), with [B54 readiness](breast-ai/B54_SOURCE_INPUT_AND_REFERENCE_READINESS_2026-10-06.md) and [B53 gates](breast-ai/B53_EVIDENCE_REVIEW_AND_NEXT_GATES_2026-10-06.md) preserved.
Keep B50 unweighted transfer as the soft-tissue research comparator. The CBIS audit
now yields 65 eligible legacy-AD rows / 42 people after source QC and person reserves.
A separate model-assisted review version now uses actual frozen B50 seed17 outputs
on all 24 common-fitting studies, visible from the outset at the user's request.
The prior blinded bundle remains preserved; physician correction and live browser
acceptance are still pending. This is not Razi baseline or independent evaluation.
B57 extracted 32 source-derived features for all 1,270 ROIs / 1,150 images and
completed 15 fixed classifier fits. Fusion macro F1 51.52% versus matched head
51.20% is below the retention gate; all paired intervals include zero. Original
B50 remains 52.12%. This rejects the tested proxy/classifier combination, not every
possible morphology representation. The large fitting/development gap and uncertain
source references argue for targeted physician correction before more feature sweeps.
The native-detail audit supports a separate local224/context384 experiment regenerated
from DICOM; source-AD supervision is another separate follow-up. Neither ran in B57.
No 30-40% boundary cutoff or fat-equals-nonmass rule is adopted.
No new fit in B53-B56; B57 adds 15 lightweight fits without changing CNN weights.
Independent full-image/normal evaluation remains a separate qualification gate.
Calcium localization and its physician-approved edge feedback remain preserved,
not a demonstrated general clinical result.

**Reading rule:** the dated summaries below retain what was known and proposed at
that time. Their old 'next' statements are historical; the B62 priority order above
is the active continuation route. Detailed run reports and the ledger preserve evidence.

**B51/B52 completed, retain B50:** [Padding ablation](breast-ai/B51_PADDING_ABLATION_2026-10-06.md)
and [frozen-source-encoder comparison](breast-ai/B52_FROZEN_TRANSFER_2026-10-06.md)
add six actual fits with exact baseline replay and update/reload guards. Neutral
target padding reduces macro F1 from52.12% to51.21%, AD22.50% to17.50%; freezing
the entire CBIS encoder reduces macroF1 to40.78%, AD to2.08%. Neither is promoted.
Extreme padding is absent from held AD rows, so it does not explain most misses.
Next prioritize minority AD/reference review and a single native-resolution/context
comparison. No deployment, new clinical gain or normal specificity claim.

**B50 completed actual transfer pilot:** [Training review and uncertainty](breast-ai/B50_TRANSFER_TRAINING_REVIEW_2026-10-05.md).
Twelve real fits on 1,270 VinDr ROIs compare target-only with CBIS morphology
pretraining from 1,015 QC-passed source ROIs. Unweighted transfer improves mean
macro F1 46.49 to 52.12%, AD recall 10.42 to 22.50%, family 46.86 to 50.30%;
Mass recall 84.39 to 84.03%. Weighting adds little macro F1 and drops Mass to78.34%.
Retain unweighted transfer as research candidate, not clinical replacement; all
three macro-F1 bootstrap intervals include zero, and AD performance remains low.
65 CBIS mask geometry failures excluded; 12 historical nontraining rows reserved.
All 7,695 update/BN/reload guards pass; GPU work93.54s, peak606MB. Next review
AD/spiculated-Mass confusions and input resolution/context before more training.

**B49 two-source balance audit:** [Support and transfer design](breast-ai/B49_TWO_DATASET_BALANCE_2026-10-05.md).
Fresh VinDr TRAIN audit verifies Mass 989 rows/469 studies and AD 95/52; FA 216/108,
Asymmetry 77/76. Sources cannot be naively pooled as equivalent targets. Prefer
CBIS morphology auxiliary pretraining then VinDr adaptation, compared with target-only
control and a bounded group-class weighting arm. Aggregate weights are illustrative,
not fitted weights; B38 already showed balancing alone trades FA gain for Mass loss.
No new fit. Next minority-label/geometry readiness before the matched comparison.

**B48 distortion-aware task:** [Morphology contract and source preparation](breast-ai/B48_DISTORTION_AND_MORPHOLOGY_TASK_2026-10-05.md).
Extend the binary appearance task to preserve AD and other findings independently.
Nonreserved CBIS includes 73 pure AD descriptor rows / 46 people, 39 asymmetry rows,
25 lymph-node rows / only four people, and 58 mixed rows requiring review.
An executable protected descriptor-evidence manifest preserves unknown clinical labels;
no model fit or gain claimed. Next extend VinDr AD coverage, complete mask/label QC,
then compare compact local, local-context and morphology-supervised arms.

**B47 local dataset audit:** [VinDr and CBIS morphology readiness](breast-ai/B47_LOCAL_DATASET_MORPHOLOGY_AUDIT_2026-10-05.md).
Both datasets verified on Windows A100. CBIS original mass TRAIN has 1,318 rows;
not all are Mass: 39 pure legacy asymmetry-family and 165 distortion/lymph-node/mixed
rows require different treatment. After reserving all publisher-test people across
Mass and Calcification, 1,092 standard-shape rows remain candidate morphology support.
All original file triplets resolve; only 24 have bounded pixel/geometry checks.
JPEG masks are provisional region supervision. No fit or improvement claimed.
Next complete mask QC and partition reconciliation, then compare CBIS morphology
pretraining plus VinDr adaptation against a matched VinDr-only control under B46.

**B46 task correction and verified Mass bias:** [Definition and evidence audit](breast-ai/B46_TASK_DEFINITION_AND_MASS_BIAS_2026-10-05.md)
separates class-agnostic finding localization, mass-like morphology with uncertainty,
and one-view versus multi-view confirmation. Mandatory single-crop three-way naming
is superseded as the primary clinical objective. B41 predicts Mass in85.3-93.8%
of development rows although reference Mass prevalence is70.2-78.8%. No inspected
evidence establishes >90% end-to-end soft-tissue finding-versus-normal detection.
Next audit full-image detection separately and review paired-view morphology labels.
Replace the absolute Mass-recall-only gate with balanced morphology errors,
uncertainty coverage and independent localization retention. No runtime change.

**B45 completed, no promotion:** [Supervised adaptation results](breast-ai/B45_TRAINING_REVIEW_2026-10-05.md)
six actual full-ROI fits show that layer4 adaptation raises FA recall from 20.12%
to 30.26% against its matched frozen control, but reduces Mass from 95.10% to 89.65%.
Fitting macro F1 99.74% versus development 42.18% indicates strong overfit.
All update/BN/reload checks passed; 42.19 seconds GPU work, about 510 MB allocated.
B44+B45 total 48 fits, none accepted as a replacement. Retain B41 as research
comparator. Next audit persistent typing disagreements using both original views
and source labels before a task-specific local-to-companion representation experiment;
stop generic feature concatenation and blind training-duration sweeps.

**B44 actual parallel experiments:** [Training review](breast-ai/B44_TRAINING_REVIEW_2026-10-05.md)
Forty-two fits completed: auxiliary view prediction raises mean macro F1 to 44.54%
but Mass recall falls to 91.42%, so it is not accepted over B41. Density auxiliary,
generic embedding fusion and a bounded regularization follow-up do not repair the
tradeoff. Actual calcium FPN score/decoder transfer also failed to improve typing;
it tested central 256-pixel descriptors from native 512-pixel tiles, with explicit missing inputs.
Label-blind companion views exist for all 1,189 ROIs; a controlled current-global
versus current+companion-global experiment completed: 38.51% macro F1 versus 35.52%
current-global control, both below B41's 41.41%. No tested replacement accepted.
The subsequent supervised adaptation also failed the replacement gate (B45 above).
No production replacement or independent accuracy claim.

**B43 measured efficiency:** [Shared preparation benchmark](breast-ai/B43_SHARED_PREPARATION_TIMING_2026-10-05.md)
five warm-cache rounds reduced median eight-image preparation from 2.1156 to
1.8963 seconds (10.37%) with exact input/crop parity. This excludes neural inference
and is not full-study Razi latency or a typing accuracy gain. Retain the preparation
prototype. B44 subsequently tested cross-task classification without a useful gain.

**B42 implemented research prototype:** [Shared native input and association](breast-ai/B42_SHARED_INPUT_PROTOTYPE_2026-10-05.md)
passed exact input/crop and cached-calcium-output parity on eight exposed cases / 18
review ROIs. Missing-output and source-binding guards passed. No new FPN inference
or classification fit occurred in B42. The subsequent typed-cohort comparison with
source-bound calcium outputs and explicit exposure limitations is recorded in B44.
The prototype is not a production worker integration or measured accuracy gain.

**B41 shared-analysis decision:** [Shared processing and calcium context](breast-ai/B41_SHARED_ANALYSIS_AND_CALCIUM_CONTEXT_2026-10-05.md).
Share compatible native image preparation first, then test actual calcium predictions
as auxiliary typing features. Removing four old brightness proxies increases mean
macro F1 to 41.41% and Mass recall to 95.20%, but FA improves inconsistently.
Exploratory comparator only; no joint model, speedup or deployment claimed.

**B40 completed result:** [Frozen image encoder experiment](breast-ai/B40_FROZEN_IMAGE_ENCODER_2026-10-05.md)
decoded 1,083 images and fitted six heads. Local ImageNet embeddings improve mean
FA recall to 30.61% but reduce Mass recall to 83.34% versus B38 A0 94.31%; adding
context does not repair the loss. Both rejected. Private discordant-row review is
prepared; next inspect crop/label failures before bounded supervised fine-tuning.
No independent clinical improvement or production replacement has been established.

**B39 architecture decision:** [Architecture and method review](breast-ai/B39_TYPING_ARCHITECTURE_REVIEW_2026-10-05.md)
reopens model selection after failed weighting and native-context-statistics pilots.
The latter gives macro F1 36.86% versus A0 38.28%; reject this descriptor addition.
Next compare a compact image encoder on local plus context crops, then label-blind
multi-view fusion. Reviewed mammography foundation models have task/access/license
limitations; none is a qualified drop-in three-type classifier. Reuse calcification
workflow and review methods, not its bright-peak gate as a mass detector.

**B38 completed pilots:** [Actual typing pilots](breast-ai/B38_TYPING_WEIGHT_PILOT_2026-10-05.md)
completed nine compact fits on 1,189 rows / 594 studies. Weighting and sampling
failed the Mass recall retention gate. Neither is promoted. Next improve native
local/context representation and label-blind view context. Missing sources and
bounds issues remain explicitly excluded and unresolved.

**B37 baseline anchor:** [Typing baseline and imbalance protocol](breast-ai/B37_TYPING_BASELINE_AND_IMBALANCE_2026-10-05.md)
freshly reproduces the legacy reference-ROI diagnostic: Mass recall/PPV 95.78%/75.42%,
FA 84.91%/37.50%; generic Asymmetry remains unsupported. This is not independent
or deployed Razi accuracy. A training-only study sampling audit and six synthetic
guards passed. Compare unweighted control, capped class loss weights and tempered
study sampling separately after source/geometry resolution and grouped split freeze.
No new classifier training or measured improvement occurred in B37.

**B36 data readiness:** [Existing data audit for lesion typing](breast-ai/B36_LESION_TYPING_DATA_AUDIT_2026-10-05.md)
keeps non-calcification localization as the baseline and targets Mass/FA/Asymmetry
classification. Fresh TRAIN counts are989/216/77rows;20boxes cross image bounds,
62of1162expected source files were not found at the canonical path, and all target
studies intersect recovered legacy TRAIN. Eighteen review nominees are prepared as
metadata only. Next resolve source/geometry, render paired context examples and
obtain explicit type/ambiguity labels before a bounded classifier experiment.

**B35 non-calcification workstream:** [Mass/asymmetry review](breast-ai/B35_LEGACY_LESION_TYPING_REVIEW_2026-10-05.md)
confirms the incumbent lacks a generic Asymmetry output and its opposite-view ROI
selection can depend on finding labels or row order. Synthetic reproductions passed.
Next prepare a label-blind, patient-grouped typing baseline and compare compact local
and multi-view context models, retaining Mass performance and the separate calcification
branch. Historical reference-ROI metrics are not live Razi or independent accuracy.

**B34 owner interpretation:** [Model dots represent localization support](breast-ai/B34_POINT_SEMANTICS_AND_CONTEXT_CROPS_2026-10-05.md),
not necessarily distinct calcifications or exact centers. Surrounding marks are
acceptable and useful for native context crops. Do not require tighter segmentation
or one-dot-per-focus cleanup before morphology experiments. The current generator
uses local image-minus-Gaussian maxima followed by learned scoring; an explanation
based specifically on gradient response is unproven. B33 edge-error adjudications
remain valid and separate from this accepted neighborhood marking.

**Separate calcium workstream status:** the physician reviewed the retained candidate on all eight displayed cases
and reports very good lesion finding, only one incorrectly marked skin region, and
real tiny calcifications among the additional model points not previously annotated.
Therefore the large unmatched-point count on these cases must not be described as
confirmed false marking. See the [B26 physician assessment](breast-ai/B26_PHYSICIAN_VISUAL_REVIEW_2026-10-05.md).
Making the scorer more selective previously removed known true support. Retain the
reviewed candidate, locate the skin error and assess separate unseen positives/normals
before further adaptation. No production replacement or independent clinical qualification
has resulted from this work.

| Current question | Evidence and status |
|---|---|
| Does candidate generation find marked points? | On two development images, 65/68 physician references have raw one-to-one matches within 0.2 mm. This is proposal capacity, not final sensitivity. |
| What does the retained research candidate keep? | 54/68: 48/61 and 6/7 on those same images. Fourteen misses are available for visual review. |
| Where are those 14 misses lost? | Three have no raw candidate within 0.2 mm; eleven have raw support but no accepted candidate within that radius. Exact identities, not only count subtraction, were verified. |
| Is unwanted marking solved? | Physician reports only one skin-region error on the eight displayed cases; other added marks were real calcifications. Separate normal16 output burden is 4,100 inside-mask points and was not adjudicated in this review. General specificity remains unmeasured. |
| Did the cited calcium scorer adaptation help? | No. The constrained scorer kept its 62 training anchors and suppressed training negatives, but development hits fell from 54/68 to 34/68. It was rejected; this is not the later soft-tissue training result. |
| What is the calcium status? | B33 records physician-confirmed removal support for 16 edge-filter flags on the eight exposed cases. B34 accepts surrounding localization marks for context crops. Preserve this branch; B50-B52 separately completed soft-tissue fits. No production replacement claimed. |
| What remains unproven? | Independent generalization, broader normal-case burden, clinical acceptability beyond these examples, complete CPU latency on Razi and production qualification. |

The 54/68 denominator belongs to two repeatedly exposed development images. It is not
an estimate of population screening sensitivity, cancer accuracy, PPV or NPV. Missing
a tiny focus and missing a clinically important cluster are different endpoints.

## 2. Model names and comparison boundaries

| Lineage | Role | Do not confuse it with |
|---|---|---|
| Original Eagle Eye breast FCOS and context/classification pipeline | Existing product lineage; detector/classifier recovery and diagnostic evaluations recorded in the [engineering record](EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md) | The current HDoG research comparator |
| Dedicated FCOS/P2 and compact detector pilots | Calcification-region training and transfer experiments | Adequately trained or qualified representatives of every detector family |
| DeepMiCa research checkpoint and adaptations | Segmentation/candidate and verifier experiments; excessive activation/grouping failures investigated | A clinically validated point detector merely because upstream classification results are strong |
| Original HDoGReg/FPN research checkpoint | Reproducible reference used by the recent native-resolution research family | Original deployed Eagle Eye weights |
| Retained native512 head-only research candidate | Same 54/68 identities as original HDoGReg on the current two positives, with a modest reduction of normal-image point burden | A globally best model, the rejected constrained head, or a deployed replacement |
| Earlier detail/context CNN (historically called dual-view) | Useful architecture reference; its old weights overlap the current development groups | CC/MLO pairing, bilateral analysis or an independent current-split comparator |

Retained checkpoint SHA256:
`00392b28a3dc8a725a2657c810f413219df19f6fd2e0e76661891c5daed8e436`.
Frozen selection SHA256:
`988e24ce9123f81b2325726dff6b329a8bed9ca330aa09d4e2871c4cab56c038`.
Score cutoff: `0.000316227766`, specific to this research recipe and not a calibrated
clinical probability. No matched comparison of original deployed Eagle Eye against
this candidate on the same 68 points has been established.

### Requested comparison with the initial Razi model (2026-10-05)

**Fresh artifact recovery (2026-10-05):** read-only SSH hashing reconfirmed the
128,790,086-byte delivered detector with SHA256
`9f8746666dccb5e22840a8bfdcb22b9eacb1e3a4b31b61b6b2ec6cd005679901`
at all these locations:

- Razi: `D:/FCOS_AR/best_fcos_csv_delivery.pth`.
- Razi historical source revision: `D:/Eagle Eye Server/revisions/20260930-echomind/source/generated-files/eagle-eye/breast/weights/best_fcos_csv_delivery.pth`.
- Windows A100: `F:/Aisan-Rahimi-part2/MammoDicomData/modified/FINAL_MAMMOPROJECT_DELIVERY/Final_Delivery/FCOS-DoctorAlizadehServer/best_fcos_csv_delivery.pth`.
- Windows A100 research copy: `D:/Enhanced Mammography/candidates/20261001-calcification/best_fcos_csv_delivery.pth`.
- This checkout: `generated-files/eagle-eye/breast/weights/best_fcos_csv_delivery.pth`.

The `FCOS_SERVER_COMPATIBLE` sibling has a different hash
`e43bede3729d88ee91fbc3cc8a142cdcad4fa364b36c1663a119497f8b0bbddf`;
do not substitute it because its filename also says delivery.
Fresh Linux hashes remain different:
`/home/gadmin/Mammography/best_fcos_csv.pth` =
`25752d8aa0679921ed32c344777114cffac3a345da0cb7074cce18684bc82b3a`,
and `/home/gadmin/Mammography/Enhanced Mammography/best_fcos_csv.pth` =
`9dd16a3bbd3b1917091d79ed2be54f816d4bd9b581b6374c24547fd25a1b622e`.
The bounded search does not prove these are all training checkpoints or establish
which training run generated the delivered bytes.

This recovered `.pth` is the general lesion detector, not a standalone punctum
classifier. The legacy cascade additionally uses the structured classifier assets
and `Suspicious Calcification` label. Their October 1 lineage audit remains separate;
classifier hashes, runtime routing, operating thresholds and authenticated inference
were not freshly exercised in this recovery. No server or model was changed.
The recovered matching local detector can support an isolated paired benchmark;
accurate original end-to-end reproduction also requires the matching original code,
classifier/preprocessing contract and documented operating settings.

The October 1 source/weight audit bound the delivered FCOS assets to the then-active
Razi revision. Its offline detector diagnostic at input512/score0.45 matched10/115
calcification region boxes (IoU>=0.5), with42 class-agnostic boxes on100 annotated
normal images. The separately corrected classifier cascade at detector0.40 and
calcification-classifier0.275 localized and typed10/115 regions, with26 calcification
boxes on19/100 normal images. That corrected isolated cascade is NOT an untouched
live-Razi end-to-end baseline. Neither diagnostic is a current service re-verification.

Current54/68 measures individual physician points on different development images
within0.2mm; the4,100 normal-image outputs are points, not region boxes. Therefore
neither detection improvement nor false-mark improvement versus initial Razi can be
assigned a valid percentage from these records. Unknown comparative improvement is
not measured zero improvement, and it is not proof of superiority or regression.

The valid recent paired statement is narrower: relative to original HDoG research
weights, retained head-only point matches remain54/68 (zero change on those cases),
while inside-mask normal-image point burden falls14.14%. The rejected constrained
head drops54/68 to34/68 (20points,29.41percentage points,37.04%relative loss of matched
points), and was not substituted for the retained candidate. The historical59.7%
component reduction belongs to another experiment, not a Razi comparison.

Before reporting an overall before/after claim, bind the initial Razi code/weights/
thresholds and the retained candidate, run both label-blind on identical reviewed
images, and use a shared physician-defined region/cluster endpoint plus a separate
point endpoint where supported. Record unwanted marks on the same reviewed negatives,
per-case changes, operating points and source-level uncertainty. Do not shrink a
region box into invented point truth or count hundreds of points as hundreds of boxes.

## 3. Scope and stage gates

Two workstreams are tracked: preserved microcalcification localization with fewer
unwanted marks, and active soft-tissue appearance typing (Mass, AD and asymmetric
family). B50 is the latter's research comparator, with low AD performance and no
clinical promotion. Preserve coexisting/unknown labels; benign is not background.
View-confirmed terminology, malignancy assessment and full-image localization have
separate evidence requirements. The following S0-S7 table describes the calcium branch;
the active soft-tissue gates are specified in B53 above.

| Stage | Work and exit evidence | Current status |
|---|---|---|
| S0: Baseline and lineage | Identify actual model, preprocessing, output meaning, hash and comparator | Research lineage bound; legacy same-cohort comparison missing |
| S1: Data and truth | Verify source geometry, label semantics, patient grouping, known-negative scope and split exposure | Original physician dots preserved; broader precise supervision and independent cohort remain gaps |
| S2: Sensitive candidates | Native-resolution, label-blind proposal generation; measure point coverage and computational cost separately | 65/68 on two development images; not general screening proof |
| S3: Candidate confirmation | Reduce unwanted outputs while measuring lost/gained reference identities and per-image effects | Retained 54/68 comparator; several adaptations rejected |
| S4: Physician error review | Show actual misses, context, full accepted output and separate clinical importance judgments | Eight-case visualization reviewed positively (B26); skin feedback linked in B28 and all16selected edge flags adjudicated in B33. Broader miss importance/generalization remain unresolved. |
| S5: New bounded experiment | Use reviewed failure categories, training-only sampling and fixed selection protocol; preserve original comparator | Await useful reviewed input or verified additional point/contour data; no arbitrary repeat sweep |
| S6: Independent evaluation | Lock model/threshold before unseen grouped test; report point, cluster and image endpoints with subgroup uncertainty | Not reached |
| S7: Serving and integration | Measure entire pipeline on target CPU; qualify geometry, resources, source GUI and authenticated Eagle Eye Server routing | Not reached for this research candidate; no deployment |

The intended two-stage design is screening followed by more selective confirmation.
Current upstream FPN still scans the full image. Small downstream crop footprint does
not prove early computational exclusion of half the breast. The owner's requirement
to substantially reduce tissue passed to stage two must be measured without hiding
full-image upstream work or expansion of context windows.

## 4. Data state and label rules

Soft-tissue current support: B50 1,270 VinDr ROIs /624studies (923Mass,87AD,260family),
plus1,015CBISstandard-shape auxiliary ROIs /553people. Source AD73rows/46people remain
an unused readiness pool, not trained clinical truth. No reviewed normal cohort,
independent qualification or proven VinDr person linkage. The bullets below describe
the separate calcium annotation history and must not be used as soft-tissue denominators.

- Original physician annotation: 143 dots across eight reviewed images; current split
  has 75 TRAIN references and 68 development references. Preserve this file and its
  SHA256 `210f402d7d3060983c744c730a20ba3e4d2b00459b596b931d77697a04262f39`.
- Current point-positive coverage is narrow (CC / Lorad Selenia in this cohort).
  More crops of the same images are not more independent patients.
- Six pending MLO review views belong to the same TRAIN groups; they broaden view
  coverage, not patient independence.
- Six separately nominated VinDr source crops cover three scanner models and both
  CC/MLO views. Existing physician boxes are regional positives, not dense masks or
  proof that every enclosed pixel is calcium. Four sources have unknown PixelSpacing;
  do not substitute ImagerPixelSpacing or claim millimetre accuracy for them.
- CBIS converted ROI masks support region supervision, not individual punctum centers.
  The existing preparation workflow preserves cross-category patient partitioning.
- Only the author's small INbreast sample was verified available: two TRAIN images
  contain 32 singleton mask components and two larger components. Do not invent centers
  for larger shapes or infer that all other pixels are confirmed normal. Full DICOM/XML
  availability is unresolved; bounded searches are not proof of universal absence.
- Non-mammography examples 026/027 were excluded from the relevant review lineage.
  Original green boxes mean physician-positive regions. Empty incomplete reviews are
  unknown. Explicit complete normal reviews apply only to their verified scope.
- Current selected negative-group provenance was checked against publisher BI-RADS 1;
  preserve the documented dataset-version crosswalk limitations.
- Repeated development access and historical training overlap must remain visible.
  Old detail/context CNN weights used both current positive development groups in
  optimizer fitting and all four current negative development groups in fit/selection.
  Reusing those weights cannot create an independent test.

## 5. Current physician handoff

Protected local root (`P`):
`C:/AI-PACS-Datasets/breast-review/point-review-20261003`.

| Bundle under P | Physician task | Status at reconciliation |
|---|---|---|
| `eight-case-point-comparison-20261005/offline-review.html` | View all eight original cases: yellow physician references, green matched model points, red unmatched model points, individual toggles and zoom | [B25](breast-ai/B25_EIGHT_CASE_VISUAL_COMPARISON_2026-10-05.md) data/code verified; [B26](breast-ai/B26_PHYSICIAN_VISUAL_REVIEW_2026-10-05.md) physician confirms viewing and positive visual assessment; original143 preserved; no automated browser pass |
| `held-miss-review-20261005/offline-review.html` | Inspect 14 exact misses and full-image accepted point overlays; rate importance/type and case-level research acceptability | Built; exact identity/geometry and 14 native crops independently verified; export/import tests passed; manual browser check pending |
| `vindr-point-review-20261005/offline-review.html` | Add typed points within existing/new boxes on six scanner/view-diverse crops; preserve display adjustments | Built and synthetic validation passed; no real exported annotations processed |
| `train-mlo-point-review-20261005` | Existing six-view point-review queue | Last persisted check: zero points, six incomplete records |
| `train-point-adjudication-20261005` | Clarify 12 ambiguous TRAIN reference/candidate relationships | Last persisted check: one draft, eleven untouched, zero center corrections |

The miss-review page does not require redrawing the original dots. Opinions are stored
separately: important miss, tiny/low-contrast tolerable miss, uncertain, with unreviewed
default. An opinion does not silently delete a reference or change 54/68. After review,
report a clinician-defined important-focus endpoint separately, including its denominator.
Acceptance of these examples is not broad clinical qualification or automatic deployment.

Offline autosave belongs to one browser; explicit JSON export is required for intake
and transfer. Validate source binding, geometry, types and revision before creating a
versioned proposed intake; never merge directly into truth or start training automatically.
No new HTTP review URL is promised: persistent service launch was rejected by execution
policy; browser automation rejects local file URLs. Neither denial was bypassed. Human
manual opening is required. Do not present synthetic tests as GUI acceptance.

## 6. Decisions to retain, stop and defer

**Retain:** native detail, explicit coordinate/polarity checks, separate proposal/scorer/
output attribution, actual pipeline hard negatives, source-balanced sampling, physician
miss review and separate sensitivity versus unwanted-output measurements.

**Stop repeating without new evidence:** longer versions of rejected head training,
development-threshold rescue, brightness/slope/size as unconditional exclusion rules,
box shrinking as a substitute for discrimination, and layers without a specific error
hypothesis. Excellent TRAIN loss/negative rejection does not establish generalization.

**Defer for the current calcification-localization branch:** bilateral/CC-MLO matching,
malignancy classifiers and larger hardware. B35 separately opens view-context review
for Mass/asymmetry typing; this does not imply a calcification-pipeline change.
The owner opened a separate morphology/distribution workstream in B29; its descriptor
contract and dataset audit are implemented, but supervised classification is not trained.
Do not claim every YOLO, FCOS, MONAI or segmentation architecture has been fairly tested.

**B30 update:** [Directional air-versus-tissue context](breast-ai/B30_DIRECTIONAL_AIR_CONTEXT_2026-10-05.md)
was implemented and audited. At 1/2/4 mm, it flags the three reported errors without
flagging any original matched reference support, but also flags 13 other predictions.
Retain as a review feature only; these other points cannot be assumed false. A
compactness guard catches only one of the three errors. Both versions and failed
V1 results are preserved; five synthetic tests per version passed. Broader near-skin
positive and artifact evidence is required before any learned or rule-based deletion.
B31 additionally intersected this feature with 1 mm and 2 mm silhouette bands; both
retain the same 16 flags (three errors, zero matched supports, 13 others). Thus the
owner's narrower-band condition is tested but does not resolve the remaining flags.
Preserve review-only status and use relative mammography signal, never a CT HU cutoff.
B32 exposes these 13 additional flags in the same offline viewer as cyan numbered
rings (two in case 004, eleven in 006), with three prior errors in orange squares.
Historical B32 next action was physician review of cyan points; that request was
subsequently fulfilled in B33 below. Original feedback/layers were preserved. B32 code
checks passed; automated GUI acceptance was not established by those checks.
B33: physician explicitly confirmed all 13 cyan points are false marks and their
removal is correct. Separate bound adjudications are saved under P as
`physician-air-filter-adjudication-20261005.json`. All 16 selected points now have
removal support on this exposed eight-case cohort; prior unknown status is superseded.
This is not independent clinical qualification. No automatic model/truth rewrite.
Display-source inspection verifies that
colored rings/squares are fixed-size glyphs, not calcification masks; apparent
surrounding coverage does not by itself prove contour or gradient oversegmentation.
Morphology work must use native image detail and independent boundary/descriptor
supervision, with local and cluster context retained separately.

**B29 update:** [Skin ablation and descriptor foundation](breast-ai/B29_SKIN_AND_MORPHOLOGY_2026-10-05.md)
rejects blanket boundary suppression: at 1 mm it removes three reported errors plus
one matched support and 25 other predictions. Six CPU component tests passed; detector
and labels unchanged. Prepare source-bound native cluster examples and a reviewed
legacy label crosswalk before a compact morphology/distribution classifier experiment.
Evaluate edge context with near-skin positives, not distance-only deletion.

**B28 evidence retained:** inspect the skin-error mechanism localized by validated
physician feedback: three incorrect-model clicks linked to three distinct predictions
in review case 006, with no missed-calcification clicks supplied. The export was
received and a separate protected proposal saved; original references and predictions
remain unchanged. Zero missed clicks is not proof of zero misses. The physician used
the [click-feedback tools](breast-ai/B27_CLICK_FEEDBACK_2026-10-05.md); automated GUI
acceptance remains unverified. Preserve the approved research checkpoint and avoid
training away red marks the physician judged real. Prepare separate unseen positive
and normal-case assessment using the frozen model; reconcile clinically important misses
only where needed. Validate any new typed-point export separately. Initial Razi paired
comparison and full target-CPU timing remain outstanding. Further adaptation must follow
an observed error hypothesis, not raw unmatched-point count alone.

## 7. Evidence locations and working environment

Linux research root (`R`):
`/home/gadmin/Mammography/candidates/calcification-pilot-20261001`.
Use the infrastructure skill before connecting; refresh availability/resource state.
Linux A100 is the established training worker; Windows A100 is a data/management host
without that GPU. CPU serving remains a goal, not a measured complete Razi benchmark.
H200 is not a demonstrated requirement. Model/source licensing remains a separate gate
before distributing upstream weights.

Keep private images, person/source identifiers, coordinates, manifests and predictions
on authorized research storage, outside this repository. Commit only aggregate narratives
and non-patient artifact bindings. The following report basenames under P locate the
October 4-5 evidence; R holds the bound caches/checkpoints:

- `RESEARCH_RESET_AND_PRIORITY_PLAN_2026-10-04.md`
- `DUAL_VIEW_CURRENT_READINESS_2026-10-05.md`
- `HEADONLY512_NORMAL16_DEVELOPMENT_2026-10-05.md`
- `CONSTRAINED_HEAD_DECISION_ROUND_2026-10-05.md`
- `CONSTRAINED_REPRESENTATION_ATTRIBUTION_2026-10-05.md`
- `REPRESENTATION_AND_DATA_COVERAGE_REVIEW_2026-10-05.md`
- `HEADONLY_MISS_IDENTITY_AUDIT_2026-10-05.md`
- `held-miss-review-20261005/independent-bundle-verification.json`
- `held-miss-review-20261005/readiness.json`
- `review-intake-validator-20261005/aggregate.json`
- `ACTIVE_GOAL_ROOT_CAUSE_LEDGER_2026-10-05.md` (detailed research history)

Readiness files and old process IDs are historical receipts, not evidence of a currently
running job or live page. Inspect actual state before waiting, restarting or claiming progress.

## 8. Documentation maintenance contract

Apply the [training and evaluation reporting contract](BREAST_AI_REPORTING_STANDARD.md),
adapted from the radiology-model-development skill. Every new fit needs a structured
run review in `breast-ai/`; B19 has a [filled evidence-based example](breast-ai/B19_TRAINING_REVIEW_2026-10-05.md).
Historical ledger entries remain summaries until their detailed evidence is reconciled.
Missing fields are explicit gaps, not assumed defaults or documentation passes.

For every continuation, read this document and the ledger before choosing work. After work:

1. Update the current-state date, stage, candidate identity and exact next action here.
2. Append a ledger entry with hypothesis, data/split/exposure, comparator, intervention,
   endpoint and denominator, results, runtime/resources if measured, decision and evidence.
3. Record failed/stopped runs and corrections as well as improvements. Preserve prior
   receipts; identify superseded claims without silently rewriting historical results.
4. Distinguish proposed, prepared, running (verified live), trained, evaluated, rejected,
   awaiting physician input, integration candidate and qualified. Never infer completion
   from a plan, checkpoint filename or passing synthetic test.
5. Separate code/data checks, model evidence, physician opinion, GUI acceptance and deployment.
   Include per-case losses/gains, point versus cluster versus image units, and baseline lineage.
6. Keep the next reader able to resume without conversation history. If a new report is
   created, link it here or in the ledger; do not create another competing master plan.

This consolidation is documentation-only. Relative document links, evidence existence and
aggregate values are checked; no runtime tests, live GUI pass, release or deployment are
claimed by the documentation update.


### 2026-10-08: Developer source/bundle reconciliation (no research-stage change)

The retained original Eagle Eye Breast engine source was refreshed from canonical
worker/vendor code, including the existing feature contract; current Breast
weights were not replaced. Actual-model synthetic smoke passed with one synthetic
input. Razi received an isolated candidate, preserving the active engine and
rollback baseline. This is execution/packaging evidence, not a new clinical
metric, physician acceptance or promotion of a research comparator. B82 reference
reconciliation remains the research next action; no new fit or B-ID was created.
Target qualification/activation is tracked by the Eagle Eye Developer report.


### B92: Active classification runtime incident (2026-10-08)

[Runtime incident evidence](breast-ai/B92_CLASSIFICATION_RUNTIME_INCIDENT_2026-10-08.md).
Active r4 rejects four base inputs versus nine-feature stackers before classification;
reproduced with its actual weights. Reconciled Developer schema passes. Latest
retained four-image result is detection-only; screenshot/request identity is not
independently linked. No active deployment or accuracy change. Next: controlled
corrected-bundle qualification/activation and affected-workflow GUI verification.


### B93: Dual result delivery (2026-10-08)

[Server/client delivery](breast-ai/B93_DUAL_RESULT_DELIVERY_2026-10-08.md).
Normal Breast adapter now starts FCOS and a sealed calcium candidate on the server;
returned points persist by detection run and load asynchronously into the separate
viewer layer. Explicit branch failures and cancellation preserve result meaning.
43 focused tests and local synthetic model/transfer smoke passed. Clinical activation,
live GUI and complete source parity remain distinct gates; no new accuracy claim.

B93 final native evidence: four images completed both branches in 555.5265 seconds;
four regions received four classification rows. Calcium support points totaled 334
(not individual calcifications). Native artifact publish/checksum-unpack/run-bound
reload passed. Final focused suite: 56 passed on both hosts; 517 mirror pairs match.
Serving latency and source GUI/physician acceptance remain open; active r4 unchanged.


### B94: CPU serving latency (2026-10-08, OPT-51)

[Exact sparse scoring experiment](breast-ai/B94_CPU_LATENCY_2026-10-08.md).
B93's tissue branch took approximately 56 seconds; calcium dominated its 555.5-second
complete request. Retain all physical candidates but evaluate only their final-owner
context tiles (191 instead of 520), with a bounded four-thread CPU budget. Calcium
worker time decreased 544.265 -> 180.218 seconds (3.020x). All 334 final support points,
scores and edge-removal counts match exactly on the same four-image replay. No new
accuracy claim, changed threshold or new model. Full combined timing is recorded in
B94 after completion; clinical activation/GUI gates remain those of B93.

B94 complete same-case dual computation: **555.5265 -> 193.8967 seconds** (2.865x,
65.10% reduction). Both branches completed; all 334 point coordinates, order,
scores and edge-removal counts were identical. Accept as Developer performance
candidate; no clinical rollout. 64 tests passed on each host, 517 mirror pairs
match, 444-file calcium manifest matches. Remaining action is the existing B93
source GUI/clinical-output and controlled activation acceptance, not more training.
