# Deployment Safety Record - Eagle Eye band review - 2026-09-26

**Change:** Reversible MS-only smooth paired-band review in the native 2D lesion route.
**Gate result:** BLOCKED for active Razi promotion; source candidate verified.

## Workstation and server checks

- CONFIRMED - Automated source verification: 157 related tests, exit 0; 472 mirror pairs match; sync dry run reports no drift.
- CONFIRMED - Scoped seven-file candidate: compiled and passed 35 focused tests. Preserves the remote baseline's unrelated 3D and manual-correction behavior.
- CONFIRMED - Full source DICOM/model/filter/PDF execution: 127.68 seconds; raw-mask reproducibility and exact lossless partition verified. Nine PDF pages rendered and reviewed.
- CONFIRMED - Backup preparation: six affected active source files captured under the versioned Razi validation directory with a local before archive. Candidate receipt records before/after SHA256 values; recheck active hashes before any activation.
- CONFIRMED - Viewer features and metadata algorithms are outside the code changes. No viewer domain, model, acquisition policy or patient identity logic was changed.
- N/A - FAST/VTK rendering optimization: none is included.
- BLOCKED - New native source GUI analysis/export and session-scoped health acceptance. Test bridge responds, but another examination was active; permission to take over that session remains pending. Earlier unfiltered-route GUI acceptance is not reused.
- BLOCKED - Expert acceptance of retained/separated bands and false-negative review. Engineering thresholds are exploratory, not a validated normality classifier.

## Boundary, privacy and approval

- CONFIRMED - Raw, separated and retained native masks are owned by the server; client receives allowlisted checksum-bound artifacts. No new external destination or DICOM/model export.
- CONFIRMED - Method, scientific sources, parameters, provenance, manual overrides and context restoration documented in the 2D owner record.
- CONFIRMED - Private case artifacts, patient identifiers and credentials excluded from this record and committed fixtures.
- PENDING - Final activation approval after the concrete GUI/clinical review gates. Existing authorization covers development; no active promotion was performed here.

## Scoped candidate and rollback

Candidate root: `C:/Temp/ee-band-filter/candidate`; receipt: `receipt.json`.
Remote before archive: `D:/Eagle Eye Server/validation/band-filter-20260926/before.zip`.
Changed existing files: `lesions_2d.py`, `lesion_report_2d.py`, `lesion_report.py`,
`lesion_indication.py`, `manual_review.py` in the Brain package and
`eagle_eye_remote/artifacts.py`. New file: `periventricular_band_filter.py`.

Before activation, verify queue drain, service ownership and every before hash.
Do not synchronize an entire dirty package. If rollback is needed, drain only the
Eagle Eye service, restore the six versioned originals, remove only the candidate's
new module after checking its hash/path, and restart only the owned Eagle Eye service.
Preserve all jobs, original reports and raw masks. Recheck authenticated capabilities
and a controlled analysis. Do not touch PACS/CRM services.

## Sign-off

Active promotion: NOT PERFORMED. New installer and clinical qualification: NOT CLAIMED.
