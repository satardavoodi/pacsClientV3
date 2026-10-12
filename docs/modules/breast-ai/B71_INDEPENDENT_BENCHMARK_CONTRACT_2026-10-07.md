# B71: Independent evaluation benchmark contract

Date: 2026-10-07. Owner requests a shared unseen-data reference for deciding which
model to trust. Status: provenance review and protocol; no final-test inference,
new training or claim of a locked image manifest. Supersedes immediate fitting as
the next priority. Preserve test eligibility before further experiment selection.

## Evidence inspected

Read B50 VinDr audit-summary.json and independent-split-check.json on R, plus CBIS
aggregate.json and B50/B54 reports. VinDr staged typing pool is publisher TRAIN only:
1,270 ROIs/624 studies, later reduced to the B64 common available-source cohort.
Its partitions are study/image-disjoint but patient independence is unproven.
These repeatedly evaluated cases are development, not final test.
CBIS staging preserves publisher-test-person exclusion and12 historical reserved
rows/6people. These12 are neither a sufficiently representative benchmark nor
automatically untouched evaluation cases. Their prior evaluation exposure must be
audited. B70 draws from the staged training pool, not publisher test.

Publisher TEST is a candidate pool, not proof of independence from every checkpoint.
Original Razi training lineage and general-backbone pretraining exposure are separate
unknowns. Previously documented legacy train/test overlap must not be erased by
renaming a partition. Do not promise that all internet models never saw public data.

## Two separate tasks and cohorts

1. Primary: reference-ROI Mass / AD / asymmetry-family typing. Candidate source is
   untouched VinDr publisher TEST, subject to full historical exposure, original
   training lineage, source completeness, person/group and duplicate audits.
   Comparators: frozen B64 reference, B65 DINO and B69 EfficientNet, retaining all
   three already-trained seeds and reporting each plus a prespecified mean. No
   test-based seed selection, probability blending or threshold search.
2. Secondary: four-class CBIS mass shape. Candidate source is publisher TEST with
   union-person exclusion across mass/calcification, duplicate and exposure audits.
   B70 can be evaluated here but is not a competitor in the three-type task. Assess
   a genuinely matched shape baseline before calling it an improvement.

Each model gets identical reference boxes and source pixels within its task; its
own frozen trained preprocessing remains part of the evaluated pipeline. Native
images, polarity, geometry and reference mappings must be verified. Reference boxes
do not measure localization. Actual detector-box/end-to-end testing is a subsequent
separate endpoint, including detection misses.

## Release of test data and labels

Before prediction, create a protected versioned manifest with source/patient/study/
image/ROI lineage, split-role and prior exposure status; verify identity overlap,
exact and near-duplicate images against all training/development/review pools.
All views and repeat exams from one person stay together; unresolved linkage is an
explicit limitation or exclusion, not proven independence. Bind model, preprocessing,
label-map and manifest hashes. Preserve exclusions with reasons before seeing scores.
Do not expose reference labels to model fitting or change labels to match predictions.
No fresh model selection on final-test outcomes followed by reuse as an independent
test. Subsequent tuned candidates need a new reserve or a disclosed reused benchmark.

## Metrics and interpretation

Primary metrics: macro-F1 and each class recall/precision, confusion matrix, raw
correct/total accuracy, balanced accuracy, calibration and failure/abstention counts.
Always report majority-class baseline and class support. Use paired group-bootstrap
intervals and disclose patient-linkage limits. Preserve natural test distribution;
any deliberately enriched minority challenge set is reported separately, never
pooled into a population accuracy. Minority support determines precision: report wide
intervals rather than promise precision from a fixed arbitrary total sample count.
For reference typing, retain B69 gate as an engineering screen (>=3 macro points,
Mass recall loss<=2points, no AD/family decline), not clinical qualification.
No imaging-AI literature headline is a comparator without the same task and cohort.

## External confirmation and next action

A later temporally collected, independently annotated local cohort can examine
scanner/site generalization beyond public data. This requires authorized cohort
availability and blinded reference review; this record does not claim it exists or
export clinical data. User annotation should ideally precede candidate overlays.

Next action: locate publisher TEST image/annotation inventories and reconcile them
against all historical exposure manifests, especially original Razi training. Freeze
the eligible manifest and report class support/coverage before unlocking evaluation.
If original model exposure cannot be established, label its result as an exposure-
unknown comparison, not an independent generalization estimate. No currently studied
model earns trust solely from the existing70% accuracy or this protocol.

## Verification

Read-only receipt audit completed. No image benchmark was run and no accuracy was
generated in B71. Document links checked. Private identifiers remain outside repo.
