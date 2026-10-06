# B61: Classification-first continuation

Continuation notice: [B62 retrospective](B62_RETROSPECTIVE_AND_IMPLEMENTATION_PLAN_2026-10-06.md)
supersedes the experiment ordering below. B50 already used shape/margin auxiliary
pretraining; only retained descriptor heads, validated region supervision or another
specified change would constitute a distinct experiment. Preserve this report as history.

Date: 2026-10-06. Decision and evidence review only; no new fit, inference or accuracy
gain. The owner prioritizes classifying already localized soft-tissue findings, then
mass characterization, then supported assessment. Detection is held fixed for these
experiments; the owner's favorable detection impression is not a measured sensitivity.
Calcium physician acceptance remains separate from validated morphology grading.

## Evidence determining the next step

B50 research comparator: mean development macro-F1 52.12%, Mass recall 84.03%, AD
22.50%, asymmetry-family 50.30%. These are repeated development/source-label results,
not Razi production accuracy. B57 spatial-proxy fusion failed its retention gate;
B58 surfaces preserve useful spatial information but show overlapping class ranges.
Do not repeat an uncontrolled proxy search or claim a second correlated classifier
is independent confirmation. B55 feedback and B60 new regions offer targeted reference
repair, not an independent test cohort. Preserve all exports and resolve per-record
conflicts: later partial exports must not erase earlier completed annotations.

## Output contract and supervision

1. Reference/proposed ROI appearance: Mass, asymmetric tissue family, standalone AD,
   and explicit uncertain/other handling. Do not force a class from inadequate data.
2. Conditional mass characterization: region support, shape, margin and relative
   density, each with known-label masks and an unassessable state. A region mask is
   auxiliary supervision, not proof that every margin is visible or a prerequisite
   that can silently discard indistinct masses. Rectangles are not contour truth.
3. View reconciliation: confirm lesion correspondence before naming focal asymmetry
   versus single-view asymmetry. Same-study CC/MLO alone does not establish matching.
4. Later assessment support: combine validated descriptors, associated findings,
   view evidence, relevant priors and clinical information. Preserve incomplete
   assessment; no fixed spiculation-to-category rule, no category6 without biopsy
   history, and no conversion of uncalibrated softmax into cancer risk.

The [ACR v2025 mammography summary](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/BI-RADS/BI-RADS-Summary-Form-Mammography.pdf)
separates shape, margin, density and assessment. Version the output vocabulary:
v2025 includes lobulated shape and lists four margin categories; do not blindly
publish older CBIS microlobulated or compound descriptors as current categories.
Keep raw legacy labels and clinician-reviewed mapping, with unknown mapping allowed.

VinDr supports finding types/boxes and view context, but lacks audited shape/margin
columns and omits BI-RADS2 finding boxes. CBIS supplies morphology labels and region
masks, with digitized-film shift and legacy semantics; audited masks are not validated
fine-boundary ground truth. See B47-B50 for exact eligibility and QC. Benign masses
remain positive Mass appearances, separate from assessment. Two supplemental cases
cannot establish representative benign support. Dataset information:
[TCIA CBIS-DDSM](https://www.cancerimagingarchive.net/collection/cbis-ddsm/).

## Ordered experiments and decisions

First reconcile physician feedback for the exact reference ROI separately from new
regions and record uncertainty. Run the unchanged B50 comparator on new regions;
do not attach original-ROI probabilities to them. Freeze reviewed references before
comparison. Never treat surrounding unboxed tissue as automatically normal.

Then compare on identical grouped splits and fixed ROI inputs:

- Control: replay B50 with unchanged preprocessing and checkpoint identity.
- Detail arm: the same compact local/context design, changing only native-source
  contextual detail (the pending local224/context384 comparison). No assumption that
  UI window adjustments improve model inputs; display and training are separate.
- Descriptor arm, after label readiness: same selected input/encoder with known-only
  CBIS shape/margin/region auxiliary losses and reviewed digital adaptation. Preserve
  the underlying image embedding; do not reduce the whole lesion to scalar proxies.

Shared encoding can reduce repeated computation; actual CPU latency and per-task
negative transfer must be measured. Use bounded, fitting-only class sampling/weights
without oversampling validation. More Mass examples alone do not solve minority AD.
Before fitting, freeze numerical budgets, loss weights and acceptance thresholds in
a run protocol. These values are not selected in this planning record.

Report per-class precision/recall/F1, confusion matrix, Mass overcalls on asymmetric
tissue, AD misses, descriptor-specific performance with denominators, abstention
coverage, grouped uncertainty and target CPU latency. Region overlap does not alone
validate spicule/boundary detail. Require a paired benefit without hidden class loss;
if detail/descriptor arms fail, retain B50 and investigate labels/domain before more
architecture tuning. Fresh independent digital cases are required for qualification.

BI-RADS fitting is deferred until verified descriptor and assessment labels, adequate
benign coverage and an independent calibration/evaluation cohort exist. Current work
does not establish a qualified classification or BI-RADS system.
