# Deployment Safety Record - Eagle Eye lesion distribution - 2026-09-24

Change: require anatomical distribution in every white-matter lesion result.
Gate result: BLOCKED for active service deployment; isolated candidate staging only.

- CONFIRMED: scoped source changes preserve DICOM identity and clinician context; synthetic regression and artifact tests exercised.
- CONFIRMED: source MRI remains server-side; nested distribution and PDF travel in the existing checked archive.
- CONFIRMED: no viewer/FAST/navigation changes; no model weights or clinical thresholds changed.
- CONFIRMED: current Razi service source identified and all 11 sampled job states terminal before staging.
- BLOCKED: affected live client result/PDF workflow is unavailable; documented control client connection fails.
- N/A: clinical database migration, model installation and release build; none performed.

No active service source or process was changed. Candidate includes baseline hashes. Activation requires fresh empty-queue/baseline checks and a scoped backup, as documented in LESION_DISTRIBUTION_2026-09-24.md. User requested implementation; no further general permission is being inferred as necessary. The unresolved item is verification, not authorization.
