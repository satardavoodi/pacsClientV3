# Lumbar native regional input preparation — 2026-09-11

## Result

Prepared **291 cases**, **1,885 native multiview candidate packets**, and **5,859
NIfTI volumes** on the control PC's C drive. One existing source-hold case was
excluded. Eighteen prepared cases retain priority image-quality review status.
All earlier DICOM, reception reports, geometry groups, cards and the initial
five-level pilot were preserved. No clinical target was activated and no clinical
training run was started.

A candidate packet represents a complete axial acquisition group paired with
compatible sagittal T2 and optional T1 groups. It is **not** a numbered disc level.
The number of packets must not be interpreted as a count of independent patients
or labeled anatomical levels. Multiple groups can belong to one disc level.

## Geometry and quality

The builder uses a shared frame of reference and physical overlap; it does not
assign anatomy by list order. Eight axial groups lacked a suitable multiplane
sagittal T2 group in the same reference. Another 425 potential sagittal pairings
had no overlap; these pairings were recorded and omitted. Rejected pairings are
not rejected whole cases.

Axial full FOV and every acquired axial plane remain present. Sagittal derivatives
retain full AP and lateral coverage with 24 mm SI context around the projected
axial FOV. No slice-axis interpolation or concatenation across acquisitions is
performed. These conservative candidate crops still need anatomical and image
quality review. Shared coordinates do not prove motion registration. The current
cohort's 962 sagittal groups all have their dominant in-plane SI axis along native
j; this was checked before accepting the builder's SI crop convention.

Every exported volume passed pixel equality against its source ROI and coordinate
round-trip checks during preparation. A separate audit checked all **5,859 hashes
and headers**, all **1,885 packet contracts**, **291 review templates**, and
**2,531 unique source volumes**, including exact native-k membership, ROI bounds,
origin, direction, spacing and RAS affine matrices. There were **zero failures**.
This technical audit is not a radiologist's review of pathology or coverage.

Nine focused tests cover crop geometry, incompatible coordinate frames, native
pixel preservation, masked unknown labels, reference evidence, missing anatomical
review and same-acquisition ROI union. Three real candidate packets (9 native
groups, 80 planes total) passed the existing full MONAI DenseNet121 worker on the
A100 after driver repair. All 15 output heads were finite; no clinical predictions
were saved. Forward execution alone is not evidence of diagnostic accuracy.

## Review and training path

Open `C:\AI-PACS-Datasets\REGIONAL_DATASET_REVIEW.html`. It links the 12 prioritized
review cases and the complete cohort. Each case contains candidate images,
complete contact sheets, the reception report link, source geometry provenance,
report candidates and a five-level/15-target review template.

The review-to-release instructions are stored at
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\training\REGIONAL_REVIEW_TO_TRAINING.md`.
The local `export_reviewed_regional_release.py` tool accepts explicit reviewed
level mappings, target classes and zero-based native-plane evidence, plus a
patient-separated split mapping. It rejects unreviewed targets, unresolved
priority quality holds, missing views, invalid evidence and absent train or
validation partitions. Existing development-only patients are preserved as held
out. Overlapping ROIs from the exact same source acquisition are combined once;
different axial slabs remain separate.

No reviewed release was exported during this work because reviewed clinical
references and train/validation assignments are still missing. The new candidates
do not replace the existing level registry's five pending pilot inputs or turn
its other 1,455 expected level rows into confirmed anatomical samples. The A100
development environment also still inherits shared dependency conflicts; isolate
and pin that environment before a long reproducible training run.

## Evidence paths

```text
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\regional-candidates\latest.json
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\regional-candidates\candidates_20260911T093840Z_d89bc0\summary.json
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\regional-candidates\candidates_20260911T093840Z_d89bc0\technical_audit.json
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\infrastructure-readiness-20260911\candidate-input-probe-result.json
```

No patient identifiers, report contents, image data or private credentials are
embedded in this repository report. A matching report is maintained in the
control-node documentation directory.
