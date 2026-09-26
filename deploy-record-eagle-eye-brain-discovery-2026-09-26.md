# Eagle Eye Brain discovery repair - 2026-09-26

Scope: owner-requested repair of model discovery in the existing Razi Eagle Eye development service. No release build or broad workstation deployment.

## Pre-activation evidence
- Explicit user authorization: fix the server model package discovery first and retry analysis.
- Code: two exact discovery blocks plus extended Windows paths for hashing; no transport, UI, DICOM, inference, threshold, report, or model changes. Frozen asset discovery unchanged; Windows hashing supports long paths.
- Regression: 2 fail before / 2 protected behaviors pass; 93 focused tests pass after, exit 0. Mirrors: 472 match.
- Real lesion model manifest: every file hash passed on Razi.
- Anatomy deployment audit: 146 paths appeared missing through ordinary Windows APIs; all 146 exist and match the manifest through extended paths. The attempted additive restoration stopped before writing any model file. No model files need replacing. Restore only the existing manifest-bound qualification receipt, omitted from the source export.
- Backup: exact remote before bytes and SHA256 receipts in validation/brain-bundle-discovery-20260926. No concurrent analysis jobs at initial check; recheck before activation.
- Data/API ownership unchanged. No patient identifiers or secrets enter this record or patch. No clinical database changes.
- Viewer, FAST, measurements, overlays, sidebars: untouched by this worker-only resolution change.
- Live acceptance plan: authenticated existing Client submits a new job for the same selected study; inspect the actual LocalService worker outcome. Existing 2D rejection must remain intact. This is input-gate verification, not completed inference.
- Source GUI: existing documented bridge unavailable; GUI acceptance pending. No app restart or test-flag change.
- Rollback: when no analysis is active, restore the two remote .before files. Remove only the newly restored qualification receipt if reverting the deployment; do not remove model files.

Activation state: scoped repair activated after full hashes passed, all service jobs were terminal, and source hashes were rechecked. Original qualification receipt restored. No model files changed. Worker subprocesses import fresh source for each job; no supervisor/listener restart required. Authenticated client retry is complete; expected 2D-input rejection verified.

Final service verification: a new request through the paired authenticated Python Client completed its PACS retrieval and lesion manifest validation under the actual LocalService worker. After 32.38 seconds it stopped in images.read_volume with `This protocol requires a 3D MR acquisition.` This is the expected unchanged input gate, replacing the previous bundle-not-installed failure. No segmentation or PDF was produced, and no completed inference/clinical accuracy is claimed. Service remains Running under LocalService. Actual source-GUI click acceptance remains pending because its documented control bridge was unavailable. The repair is server/worker verified, not GUI- or installer-verified.
