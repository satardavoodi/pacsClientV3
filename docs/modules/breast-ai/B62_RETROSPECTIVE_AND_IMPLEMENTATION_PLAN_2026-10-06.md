# B62: Retrospective, external-method compatibility and implementation plan

Date: 2026-10-06. Status: evidence review and proposed protocol, not a training run.
Owner: Breast AI / Eagle Eye model-development workstream.
This supersedes the experiment ordering in B61. No weights, production behavior,
reference labels or patient images were changed. No new accuracy was measured.

## Decision

Keep the detector and accepted calcium research branch stable. Improve classification
of an identified soft-tissue ROI first, then its supported descriptors, then assessment.
Retain B50 unweighted transfer as the research control. Reconcile physician references
and score the newly drawn regions with the unchanged control before fitting anything.
The first training experiment should test native contextual detail, not repeat already
tested auxiliary pretraining. A compact alternative encoder is the bounded fallback.

This is a targeted evidence review, not an exhaustive systematic review or evidence
that one architecture is globally best. Published endpoints and cohorts differ.

## What our evidence actually establishes

Percentages below are development results from their own reports; rows are not one
shared leaderboard. Percentage-point differences require a matched within-run control.
The original Razi detector is distinct from the B50 reference-ROI research classifier.
Historical Razi reference-ROI typing estimates do not establish current end-to-end
detection sensitivity above 90%. No fresh paired Razi-versus-candidate qualification
has been completed. Physician calcium acceptance is not validated morphology grading.

| Work | Finding | Consequence |
|---|---|---|
| B38 balancing | FA recall improved with weighting, but Mass recall fell 6.40 points; resampling lost 8.06 Mass points | Do not repeat these recipes as a general solution |
| B39-B41 representations | Native statistics failed; frozen local/context embeddings helped some endpoints but reduced Mass recall; removal of old calcium proxies helped | Preserve full image representation; calcium transfer is not automatically useful |
| B44 shared/multitask routes | View/density heads, calcium features, PCA fusion and global companion features failed replacement gates | Sharing decoding is useful engineering; shared classification benefit remains unproven |
| B45 adaptation | Development macro-F1 42.18%, with training 99.74% and a Mass tradeoff | More fitting alone is not proof of generalization |
| B50 transfer | Target-only macro-F1 46.49% versus unweighted transfer 52.12%; AD recall 10.42% to 22.50%; family 46.86% to 50.30%; Mass 84.39% to 84.03% | Best retained research control; paired improvement intervals include zero |
| B50 weighted transfer | About 0.11-point macro-F1 gain, with 5.69-point Mass recall loss versus unweighted transfer | Reject this weighting recipe |
| B51 padding | Macro-F1 51.21%, AD recall 17.50%, below B50 | Neutral padding did not solve the problem |
| B52 frozen encoder | Macro-F1 40.78%, AD recall 2.08% | Reject this fixed-budget freezing strategy |
| B54 detail inspection | Native context contains detail lost at 224 pixels | Supports testing local224/context384; no accuracy gain demonstrated yet |
| B57 spatial features | Embedding plus features added only 0.325 macro-F1 points; gates failed | Do not launch another unrestricted scalar-feature search |
| B58 spatial surfaces | Central density/variation patterns sometimes fit the hypothesis, but all class ranges overlap | Useful visualization and hypothesis generation, not a validated classifier |
| B55/B59/B60 review | Display corrected; additional boxes are distinct from original reference ROIs; exports differ in completeness | Repair exact reference scope; do not reuse old ROI predictions for new boxes |

### Critical correction to B61

B50 already used CBIS supervision for four shape and five margin targets, with
known-label masks, before VinDr adaptation. Those auxiliary heads were discarded
for target typing. Simply proposing shape/margin multitask pretraining repeats B50.
Genuinely distinct tests would retain and validate descriptor outputs during adaptation,
introduce valid region supervision, or add audited source-AD supervision. Each needs
its own control. B44 also already tested view/density auxiliary heads.

B50 used ImageNet ResNet18, shared local/context encoding, 224-pixel aspect-fit inputs,
five source and five target epochs, and three seeds. These were fixed-budget pilots,
not evidence of convergence. Changing architecture and training duration together
would not isolate the cause of improvement. Training curves and longer-budget control
are required if a new method receives more optimization than the old control.

## Data and reference constraints

- B50 used 1,015 QC-passed CBIS source ROIs from 553 people and 1,270 VinDr target
  ROIs from 624 studies. Study grouping must not be called verified person grouping
  unless the authoritative person linkage has been established.
- VinDr has finding boxes but no audited shape/margin targets. Its omission of
  BI-RADS 2 finding boxes explains a coverage gap; it does not prove runtime suppression.
  Benign Mass must remain a Mass appearance, separate from malignancy or assessment.
- CBIS provides legacy shape/margin and masks, but scanned-film domain shift and
  mask quality matter. Audited JPEG masks are not precise clinical boundary truth.
- There are 65 eligible source-AD rows from 42 people after reserve/QC filtering;
  eligibility alone is not proof of valid AD supervision or adequate independent support.
- Reconcile all feedback per record. A later partial export must not erase a more
  complete earlier one. B55 fitting-case, model-assisted review cannot become an
  independent test. B60 four view-specific boxes do not establish four distinct lesions.
- Unboxed tissue, unfinished reviews and ambiguous reference regions are unknown,
  not automatic negatives. Resolve the reference-ROI interpretation conflict before scoring.

## What external work contributes

Sources checked October 6, 2026. Results are source-specific, not comparable with B50.
Public availability below means advertised/read, not downloaded or reproduced here.

| Route and primary evidence | Reported evidence and exact task | Fit and decision |
|---|---|---|
| [Park et al., joint shape/margin learning, 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11535944/) | CBIS Mass benign/malignant classification; AUROC 0.8408 to 0.8522, F1 0.7697 to 0.7789; DINOv2 ViT-B ROI classifier with auxiliary descriptors | Strong support for supervised attributes, but does not solve Mass/asymmetry/AD. B50 already implements related pretraining. Adapt the distinct joint-retention idea; ready full checkpoint not verified |
| [Deep BI-RADS Network, 2024 preprint](https://arxiv.org/html/2411.10894v1) | CC/MLO images plus physician-provided descriptors; CBIS malignancy AUC 0.87 | Descriptors are inputs, not automatically extracted outputs. Not a plug-in solution to our missing descriptors; defer until predicted-input performance is tested |
| [Local-view finding classification, 2025](https://www.frontiersin.org/journals/oncology/articles/10.3389/fonc.2025.1601929/full) | Mass F1 0.7392; asymmetry recall 0.1772; AD recall 0.0417 despite AD accuracy 0.9941 | Closest task warning: overall accuracy hides rare-class failure. Use per-class and confusion metrics, not a claimed universal accuracy target |
| [Attentive multitask mass segmentation, 2021](https://pubmed.ncbi.nlm.nih.gov/33882475/) | Abstract reports five-fold Dice 0.826 INbreast, 0.863 CBIS | Region supervision is a plausible separate experiment; segmentation success is not typing success. Full reproducible checkpoint/rights not verified |
| [Gabor/phase-portrait AD analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC3046672/) and [AD image analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC3856936/) | Spatial orientation/convergence methods for AD candidate analysis | Supports the structural hypothesis, not repeating failed B57 proxies. Requires distinct local spatial maps and an ablation before adoption |
| [Official DINOv2](https://github.com/facebookresearch/dinov2) | General visual representation; standard ViT-S/14 21M parameters and public weights; standard backbone code/weights Apache 2.0 | Practical independent representation challenge; not a ready mammography classifier. Use exact-artifact license/hash review, model-appropriate preprocessing and measured CPU latency |
| [Official Mammo-CLIP](https://github.com/batmanlab/Mammo-CLIP) | Breast-specific encoders, B2/B5 checkpoints and downstream code advertised | Research option only under current CC BY-NC-SA terms; commercial restriction and possible VinDr pretraining exposure require resolution. Not the first deployment candidate |
| [MAM-CLIP](https://github.com/igulluk/MAM-CLIP) | Different project; 2,313 atlas image-caption pairs and ConvNeXt checkpoints advertised | Watchlist. Code MIT does not establish weight/data commercial rights; atlas data noncommercial. Task and provenance need verification |

Primary dataset references: [VinDr-Mammo](https://physionet.org/content/vindr-mammo/1.0.0/)
and [CBIS-DDSM](https://www.cancerimagingarchive.net/collection/cbis-ddsm/).
The [ACR v2025 summary](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/BI-RADS/BI-RADS-Summary-Form-Mammography.pdf)
provides the output vocabulary. Preserve legacy CBIS terms with versioned mappings;
do not silently convert microlobulated legacy labels into a current margin category.
No reviewed paper establishes an intensity threshold that reliably separates all
masses from asymmetry. Fat interspersion and contour are useful clues, not absolute rules.

## Ordered implementation protocol

### Stage 0: Reference and comparator readiness -- next action

Deliver an immutable reconciled review manifest, label dictionary, scope/uncertainty
table, source and split hashes, and a retrospective B50 run card under the reporting
standard. Keep physician corrections and original publisher labels separately.
Replay unchanged B50 on the newly localized regions; inspect the overlay and predictions
for the exact input, without fitting on these answers. Resolve disputed ROI identity
and interpretation. Failure to establish a reference leaves that row unknown.

Freeze detection for typing comparisons. Report reference-ROI typing separately from
predicted-ROI pipeline performance. The latter must eventually include unmatched and
missed findings; successful reference crops cannot establish detection performance.

### Stage 1: One controlled native-detail experiment

Compare B50 local224/context224 against local224/context384 from native source signal.
Keep cohort, grouping, label version, source auxiliary supervision, seeds and selection
rule fixed. Use separate runs to investigate signal normalization; do not mix it into
this resolution ablation. Model inputs are independent of physician display windowing.
Record effective resolution, context extent and spacing where trustworthy. Maintain
aspect ratio; avoid deformations that change clinical morphology.

Run three seeds with comparable update budgets and source exposure. Inspect training
and development loss, per-class recall, gradient health and convergence. If five epochs
are insufficient, predeclare a bounded extended comparison for BOTH arms. Do not select
a convenient epoch after observing the evaluation results.

### Stage 2: Bounded alternative or targeted supervision

If detail does not meet the development gate, challenge the representation using
DINOv2 ViT-S/14 on the same ROIs, with a documented patch-compatible input and matched
data exposure. Compare against an appropriately trained compact control; log differences
in optimizer and compute. Download/load, dependency, rights and exposure checks precede
the pilot. A large framework migration or training from scratch is unnecessary.

If review indicates descriptor/region errors remain the bottleneck, separately test
retained CBIS shape/margin heads with source rehearsal and unknown-label masking during
digital adaptation. Test region supervision only on masks that pass QC; do not invent
contours from rectangles. Test source-AD enrichment as a separate arm after target
semantics are verified. Stop an arm that trades unacceptable Mass loss for minority gain.
These are conditional experiments, not instructions to run all combinations.

### Stage 3: Useful output, cross-view logic and assessment

Output ROI appearance probabilities with uncertain/other handling; allow AD-associated
features alongside a Mass rather than force every mixed finding into an exclusive type.
Validate any multi-label redesign separately from the existing three-class control.
For Mass, expose only validated shape, margin and relative-density descriptors, each
with unassessable handling. Evaluate visible margins without demanding a complete contour.

Keep single-view appearance at the asymmetry-family level. Naming focal asymmetry
requires appropriate cross-view evidence; study-level companion images alone do not
prove lesion correspondence. Registered/local correspondence is distinct from failed
B44 global companion features. It is deferred until single-ROI classification improves.

BI-RADS assessment comes after these tasks and uses relevant view, associated-finding,
prior and clinical information. It is not a softmax-to-category conversion; category 6
requires biopsy history and category 0 is not a generic uncertainty label.

## Acceptance, resources and reporting

Proposed development gate, to freeze before fitting: at least 3 percentage points of
macro-F1 improvement over the matched control, no more than 2 points of Mass recall
loss, and no deterioration in AD or asymmetry-family recall. Report full confusion,
Mass overcalls among non-Mass references, per-class precision/recall/F1, calibration,
abstention coverage and performance among retained cases. These are research gates,
not clinical acceptance thresholds. Estimate paired patient-group uncertainty where
linkage is verified; otherwise explicitly use the known grouping unit. A point gain
whose interval includes no gain remains provisional.

Use train/development/calibration and untouched test roles explicitly. The repeatedly
used development set and physician-reviewed fitting cases cannot qualify the final
model. Keep unused person-linked digital cases reserved, check duplicates and source
exposure, and evaluate benign findings, density, vendor/view and available age strata.
Do not tune thresholds on the final test. Determine qualification sample size from
the desired precision and clinically accepted errors, not an arbitrary case count.

Linux A100 40 GB is sufficient infrastructure for these proposed compact pilots; no
measured memory/throughput guarantee is made. Initial proposed compute cap: four GPU
hours for the Stage 1 screening comparison, including its control, then review evidence
before expansion. Incomplete/nonconverged runs are not evidence a method fails. H200
is not a prerequisite. Check live GPU availability before scheduling any run.

Measure CPU end-to-end inference on the actual serving machine: decode, shared
preprocessing, calcium branch, detector, ROI classification and postprocessing, with
cold/warm timings, p50/p95, thread count and ROI count. Approximately 56 seconds is
the owner's desired workflow budget, not a demonstrated current result. Shared image
preparation may save time; it does not justify unvalidated shared diagnostic features.
All company-managed production inference remains behind authenticated Eagle Eye Server.

## Stop/defer list and outstanding evidence

Do not repeat balancing-only fixes, neutral-padding replacement, frozen B52 strategy,
or B57 scalar fusion without a new discriminating hypothesis. Do not replace the
detector to solve ROI typing, import physician text as an unavailable inference input,
force uncertain lesions into Mass, or deploy noncommercial weights without rights.

Missing evidence: independent clinical evaluation, a fresh original-Razi paired
comparison, real CPU end-to-end timing, precise final descriptor targets and mapping,
fine-boundary mask validity, checkpoint-specific external pretraining contamination,
and complete source-to-person linkage. No runtime/GUI test is applicable to this
documentation-only decision; links and document consistency are checked separately.

Protected source artifacts remain under P as defined in the current-state document,
including `b50-transfer-train-20261005.py` and prior run receipts. Private image geometry
and identifiers are not copied here. Historical reports B38-B61 and their immutable
receipts remain the source for detailed run parameters and denominators.
