# Lumbar marrow full-volume development candidate

Status: implemented in canonical source; isolated Razi calculation succeeded. Authenticated job-route, active service source parity, live result-tab and physician acceptance remain pending. No release qualification or clinical validation is claimed.

## Contract and measurements

The existing lumbar-marrow function supports legacy native T1 and an explicit multiparametric mode. Required roles are Dixon in-phase, fat, water and magnitude multi-echo; native T1/T2 are optional. All inputs must belong to one examination. F/W/IP grids must match; echo timing, geometry, field, TR, flip angle and bandwidth must be consistent across each echo train. No cross-patient or silent registration fallback is allowed.

Server inference combines the pinned vertebrae_mr per-level labels with TotalSegmentator total_mr dataset 850 vertebral-body mask. Their intersection removes posterior elements. All acquired Dixon spatial slices are retained. A 2 mm interior supplies signal statistics; full body mask supplies sampled volume. Acquisition spacing contributes to sampled volume and must not be mistaken for measured tissue in an unacquired gap. Body boundary contact is recorded. Masks remain physician-review candidates.

F/(F+W) maps represent signal fractions, not cell-volume fractions or calibrated PDFF. The six-peak magnitude multi-echo fit retains low/high fat branches with common R2*, residuals and boundary flags. It uses Gaussian ROI-mean residuals, not the full MAGORINO Rician method. Echo estimates apply only to acquired spatial planes. Optional T1/T2 outputs are native arbitrary-unit signal measurements.

Dixon comparison uses actual TR/flip angles in a spoiled-GRE sensitivity calculation. Fat T1 150â€“500 ms and water T1 400â€“2000 ms, with water T1 >= fat T1, are exploratory assumptions, not measured T1 or normal limits. Conditional branch support requires separation from the competing range and fit QC. It never establishes calibrated PDFF or hematopoietic fraction. Iron-induced water-T1 shortening, B1, differential R2* and vendor reconstruction can invalidate the assumptions. Alignment review is required before selecting even a conditional branch; both solutions remain in the report.

## Review and artifacts

The client selects series and submits DICOM references to Eagle Eye. Analysis, masks and recalculation stay server-owned. Results use the existing result tab, all-slice slider, zoom/pan, structured report, standard paged PDF exporter and Slicer correction workflow. NIfTI body labels and signal-fraction maps, per-slice previews, montage and CSV are portable artifacts. Original private input volumes and echo arrays remain server-side for recalculation and are excluded from publication.

## Models and provenance

Body supplement: Apache-2.0 TotalSegmentator dataset 850, official v2.5.0-weights release, executed in the existing pinned TotalSegmentator 2.14.0 lumbar runtime. Archive SHA256: 8c6249783a270e2f6a23c1d554e03f2643771309474c58225c984f5df3d27835. Checkpoint SHA256: 8577a4c22b5cc43e9ccc5fa6203451ee4b22f54000bf16cfc1c5625439861129. The reviewed complete file inventory is sealed in the worker and every asset is hashed before offline execution. Supplement discovery supports the explicit server asset root and the lumbar installed feature root. Installer inclusion still requires build-owner qualification.

References: https://github.com/wasserth/TotalSegmentator ; https://github.com/TJPBray/MAGORINO/blob/main/Fitting/models/MultiPeakFatSingleR2.m ; https://pmc.ncbi.nlm.nih.gov/articles/PMC4785023/

## Verification and remaining gates

Five initial fail-before guards exposed the absent contract/calculations. The focused marrow suite now passes 39 checks, including synthetic competing-solution recovery, all-slice body sampling, model-manifest rejection, legacy UI reset and standard PDF signature, five-page image pagination and private-input artifact exclusion. These do not establish live GUI acceptance.

A protected same-examination Razi run processed 32 Dixon slices and one nine-echo spatial plane. It produced five lumbar body masks, all-slice maps and conditional low-fat branch support. Private DICOM, identifiers, measurements and images remain outside documentation and committed fixtures.

The active Razi service was observed selecting 20261011-native-authority-resilience-02/source. Calculations ran in isolated SSH-owned workers; they were not submitted through the authenticated HTTP job route. Remote server.py lacked a newer local structured Secretary error envelope; preserve the local behavior during reconciliation. Full Developer snapshot and required payload parity, queue-drained candidate activation, authenticated function scenarios, live source-client result review and physician boundary/alignment acceptance remain required before completion or build handoff.

The fresh full inventory hashed 8,637 active-source files without read errors. 75 local/active file differences remain, including unrelated concurrent work. No broad overwrite, active transition or full-parity claim is allowed on the scoped overlay receipt. The scoped overlay is staged separately; it is not an executable full Developer snapshot.


## Input protocol 2 - owner correction, 2026-10-12

Required roles are primary (sagittal Dixon in-phase), opposed (sagittal
opposed-phase), t1 (sagittal native precontrast T1 without fat suppression),
and t2 (sagittal T2). STIR and magnitude multi-echo GRE are optional. Fat and
water reconstructions are optional as a matched pair. The prior protocol 1
remains readable for existing requests/results. Capability version is now 2.
The client submits counted study-bound DICOM references; the authenticated
server retrieves images, segments vertebral bodies and calculates features.

Client series inspection runs in its background executor. Sagittal metadata,
sequence names/components and distinct echo times propose unique roles only;
duplicates remain unselected. Every combo can be changed. Suggestions preserve
existing manual selections; changing any role clears input/alignment confirmation.

Without fat/water, the map is signed chemical-shift signal drop:
100*(IP-OP)/IP. It is NOT fat fraction or PDFF. Display colors saturate at
0-100%, while tables retain signed measurements. With fat/water, the existing
F/(F+W) signal-ratio map remains available. T1/T2 and optional STIR provide
per-level arbitrary-unit signal statistics with DICOM-coordinate mask transfer.
Optional multi-echo adds competing magnitude fits and decay measurements only
on acquired planes; it is not required for the core pathway. Same-study,
sagittal orientation, matching Dixon grids/scaling and consistent available
frame-of-reference identities are checked. Physician alignment review remains
necessary. There is no validated tumor/edema/hematopoietic-cell classifier in
this module, and no output is relabeled as such.

Verification: the new guard first failed on unsupported opposed-phase roles and
mandatory fat input. After the fix, 44 focused marrow tests pass (including five
new protocol guards: optional inputs, unique suggestions, manual override,
no-echo calculation/recalculation and synthetic DICOM geometry/scaling).
Live GUI remains pending: the documented control client ping cannot attach to
the current source app. This is not a GUI acceptance pass.

Razi: the running service still selects the prior immutable revision. A new
reviewed scope overlay is staged separately; no executing source is overwritten.
Full Developer parity remains blocked by the previously recorded unrelated
source drift (75 differences in the last full inventory). Scoped hash parity
is not full-source parity, activation, authenticated Function Tester acceptance
or clinical validation. No release/build is authorized by this receipt.
