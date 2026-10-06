# B36: Existing data for Mass / Focal Asymmetry / Asymmetry

Date: 2026-10-05. Status: fresh source-annotation audit, bounded file-existence check,
definition review and training-review nomination completed. No fitting or pixel-level
accuracy assessment. Owner prioritizes typing already detected non-calcification
regions; detection remains frozen for the first comparison.

## Task definition

The user reports useful non-calcification localization and requests correct naming
of the detected region before downstream characterization. Preserve that localization
as the first comparator. This is not a request to substitute cancer risk, breast
density or calcification morphology for lesion type.

VinDr v1 annotations follow BI-RADS fifth-edition terminology. Under that dataset
contract, Mass denotes a space-occupying finding with outward-convex contour and
established three-dimensionality; Focal Asymmetry is localized asymmetric tissue seen
on two projections without the convincing contour/conspicuity of a mass; Asymmetry
is a one-projection finding pending characterization. These definitions explain why
one cropped view cannot reliably establish every class. They are not timeless rigid
rules for every current modality: preserve the dataset's lexicon version and review
mapping to the current clinical lexicon separately. In particular, do not assign
Asymmetry merely because a detector misses its counterpart on another view.

Sources: [publisher dataset documentation](https://physionet.org/content/vindr-mammo/1.0.0/),
[dataset paper](https://doi.org/10.1038/s41597-023-02100-7), and
[ACR mammography description of mass](https://www.acr.org/-/media/ACR/Files/RADS/BI-RADS/BIRADS_CEM_2022.pdf).
The ACR document is CEM-specific corroboration, not the annotation codebook.

## Fresh observed inventory

Read Windows A100 source finding and breast-level CSVs from the established original
data directory. Protected copies, audit code and receipts are under P:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003/lesion-typing-data-audit-20261005`.
Source hashes are in aggregate.json. Target labels were interpreted only in TRAIN;
test split membership was used only for overlap checks, not label selection or tuning.

TRAIN contains 16,000 image rows and 4,000 study groups. No TRAIN/test study overlap
was found. No patient identifier column is available; study grouping is publisher
provenance, not independently proven longitudinal person linkage.

| Target | Annotation rows | Images | Studies | Breast sides | Sides with same target annotated in both CC/MLO | Boxes outside recorded bounds |
|---|---:|---:|---:|---:|---:|---:|
| Mass | 989 | 894 | 469 | 490 | 404 | 13 |
| Focal Asymmetry | 216 | 216 | 108 | 108 | 108 | 3 |
| Asymmetry | 77 | 76 | 76 | 76 | 0 | 4 |

Every target breast side has both CC and MLO image records. This is metadata
availability, not verified availability of every corresponding file. Two-view label
presence does not link individual lesions; no explicit cross-view lesion ID is
provided. One-view annotation absence is not proof that a finding is invisible.

Mass has approximately 12.8 times as many rows as Asymmetry. Density C accounts for
811/989, 174/216 and 68/77 target rows respectively. View distribution is 463CC/526MLO
for Mass, 108/108 for Focal Asymmetry and 18/59 for Asymmetry. These are sample biases
to monitor, not shortcuts the model should learn. Count by study as well as row.

There are two rows with multiple requested type labels (Mass+Asymmetry and
Mass+Focal Asymmetry). Do not arbitrarily force these into one softmax class. Review
them or explicitly mask ambiguous targets. Concurrent suspicious calcification is
present in 75 Mass, 24 Focal Asymmetry and three Asymmetry rows; do not discard mixed
findings or overwrite the separate calcification output.

Twenty target-category rows fail strict image-bound checks. Observed violations:
11 negative-left, eight right overflow, one bottom overflow; no nonpositive extents,
maximum overflow approximately 41.11 pixels. This refines the old report that boxes
had positive dimensions: positive area did not establish bounds validity. Preserve
raw geometry, inspect image dimension/orientation correspondence and record any
clipping rather than silently modifying ground truth.

## Access and exposure findings

A fresh bounded Windows existence check tested unique target TRAIN source paths:
1,100 of 1,162 expected .dicom files exist, 62 were not found at the canonical path.
This is not a claim that files are absent from all drives. No pixel decode, header
geometry check or alternate-copy reconciliation occurred. Recover/link those files
or explicitly exclude them with class/view counts before constructing a training set.

All target studies intersect the previously recovered legacy TRAIN membership:
469 Mass, 108 Focal Asymmetry and 76 Asymmetry. None intersects the recovered legacy
validation/test study lists. These files suggest prior exposure, not proof that a
particular checkpoint trained on every row. Do not present a new random subset of
these studies as an independent old-model benchmark. Use them for adaptation and
development; separately establish an unexposed qualification cohort.

## Label suitability and limits

Publisher documentation states that benign BI-RADS 2 findings were not boxed; boxes
cover findings assessed as BI-RADS 3-5. Consequently unboxed tissue and absent labels
are not an exhaustive negative reference. Even breast-level BI-RADS assessment is not
a pathology outcome. Report uncertainty and obtain reviewed difficult normal tissue.

The local columns include class, box, finding BI-RADS and breast density, but do not
provide mass shape/margin/lesion-density labels or explicit matched-lesion IDs.
Therefore the three-way typing task is supportable after data preparation; complete
downstream mass characterization needs additional labels. CBIS mass descriptors may
supplement a separate mass-shape task after domain/geometry checks, not generate an
Asymmetry label or replace FFDM validation.

Data consistency does not establish clinical label correctness. Physician review of
representative examples is still required. Eighteen provisional TRAIN review nominees
were saved (six per class from distinct study groups); source pixels are not yet
prepared, so no review viewer or visual acceptance is claimed.

## Selected upgrade sequence

1. Resolve expected-path missing files and box bounds; bind source pixels, native
   crops, laterality, view and physical spacing. Preserve raw labels/geometry.
2. Prepare native ROI plus a wider context crop and full-breast CC/MLO thumbnails for
   those 18 review nominees. Ask for type/ambiguity and counterpart information,
   not another calcification-point task. Include dense normal mimics subsequently.
3. Freeze patient/study grouping and exposure status. Start with Mass versus Focal
   Asymmetry on adjudicated examples; retain Asymmetry as an explicit target for
   the three-class comparison, with insufficient-view/uncertain output rather than
   a forced answer. Do not interpret missing counterpart detection as Asymmetry.
4. Compare the recovered stack with a compact ROI-plus-context classifier, then add
   correctly bound multiview/bilateral context. Use balanced study sampling and
   training-only weighting; masks/abstention handle missing views and ambiguous labels.
   Do not pair lesions by ground-truth category or the first opposite-view row.
5. Evaluate reference-ROI typing first, then actual detected ROIs, preserving the
   existing localization and calcification branch. Report Mass-to-FA and FA-to-Mass
   errors explicitly, per-class recall/precision, macro-F1, calibration, subgroup
   performance and CPU time. No improvement estimate is available before that run.

## Evidence and validation

`audit_lesion_typing_data_20261005.py` performs the TRAIN inventory and creates
aggregate.json and train-review-nominees-private.json in the protected directory.
`source-image-existence.json` records the Windows literal-path check. Counts match
the publisher's TRAIN class frequencies; audit assertions verify the expected totals.
No clinical runtime, inference weights, images or original annotations were edited.
No new model trained; no independent performance or clinical accuracy claim.
