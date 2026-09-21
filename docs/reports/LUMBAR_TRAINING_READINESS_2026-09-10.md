# Lumbar dataset training-readiness audit - 2026-09-10

## Decision

Saved source and geometry integrity checks passed, but the dataset is **not
ready for supervised diagnostic training**. No training run was started and
EchoMind was not stopped for this audit.

This record is also stored in the control-node project at
`D:\control pc node\docs\infrastructure\LUMBAR_TRAINING_READINESS_2026-09-10.md`.

## Freshly verified evidence

| Check | Result |
|---|---:|
| Patient packages audited | 292 |
| DICOM objects present | 20,552 |
| Distinct declared files hashed | 39,665 |
| Native-derived volume headers checked against recorded geometry | 3,713 |
| Technical integrity discrepancies | 0 |
| Saved report hashes matched | 292 |
| Saved candidate-extraction hashes matched | 292 |
| Cross-package reception identity-token collisions | 0 |
| SQLite integrity / foreign keys | Passed / zero errors |
| Synthetic report-contract guards | 12 passed |
| Synthetic level/split and delayed-study-link guards | 12 passed |

The audit checks declared source/preparation artifacts and NIfTI dimensions,
origin, direction and spacing. The earlier full DICOM decode QC remains separate
evidence. Hash integrity is not clinical image quality, anatomical numbering,
registration or confirmed report-study linkage. Reception-person identity is
verified for 291 packages; the familiar development package retains its pending
identity-review state. No source identity values were exported.

## Remaining training blockers

| Requirement | Current state |
|---|---|
| Expected five-level records | 1,460 |
| Levels with regional input packets | 5, all from the familiar development case |
| Levels still missing regional inputs | 1,455 |
| Image-reviewed active supervision | Zero for every one of the 15 targets |
| Training-eligible level samples | 0 |
| Split assignment | 5 development-only; 1,455 unassigned |
| Reviewed train/validation release | None |
| Case quality dispositions | 273 retained pending protocol review; 18 priority image-quality reviews; 1 source recovery/replacement hold |

The real GPU worker's manifest validator rejected the current input with
`reviewed_train_and_validation_splits_required`. Its manifest hash matches the
local pilot. No model was allocated on GPU by that preflight.

Report-derived candidate counts must not be described as supervised class
balance. For example, 140 cases have positive unspecified-canal report candidates;
these cannot automatically become central-canal severity labels. Unmentioned
levels remain unknown, not normal. The owner's previously supplied first-case
findings remain preserved in the private reference draft; attach reviewed image
evidence and coverage before activating masks.

## Concrete preparation output

A 12-case annotation queue was selected for report-category diversity from the
retained technical-QC pool. It links each case's saved report, quality review and
level records. This queue is neither a train/validation partition nor new ground
truth. No labels, patient splits or eligibility flags were changed.

Required sequence: resolve the source hold and priority QC cases; complete and
review anatomical mapping and regional packets; record per-target positive and
negative image evidence with unknown masks preserved; create a patient-separated
reviewed release; prepare the pinned isolated GPU environment; then launch the
real worker in a bounded, recoverable EchoMind maintenance window.

The previous full-backbone synthetic GPU capacity test remains valid as an
execution test. It does not replace these data prerequisites or integrate the
MON-AI application's simulated executor.

## Local evidence and navigation

- Main entry: `C:\AI-PACS-Datasets\TRAINING_READINESS.html`.
- Current audit pointer: `C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\training-readiness\latest.json`.
- Audit outputs: `summary.json`, `case_readiness.json`, `technical_failures.json`
  and `gpu-training-preflight.json` under the directory resolved by that pointer.
- Review queue and source-association audit:
  `C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\training-readiness\annotation-batch-20260910\`.
- Reusable audit: `C:\AI-PACS-Datasets\lumbar-mri\v0.1\tools\audit_training_release_readiness.py`.

Patient records and evidence remain in the protected C-drive dataset. This
repository record contains aggregate results only. No new provider requests,
patient-image transfer, source changes or clinical training occurred.
