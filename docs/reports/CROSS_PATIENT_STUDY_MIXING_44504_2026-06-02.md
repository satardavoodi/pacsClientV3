# Cross-Patient Study Mixing — 44504 / 44533 (2026-06-02)

**Symptom:** patient `44504` (brain MRI) showed a *second* study — a shoulder MRI that
actually belongs to patient `44533`. Other PACS systems show only the brain study for
44504.

## Diagnosis (evidence-based)

| Source | 44504 | 44533 |
|---|---|---|
| **Server** (`search_patients_sync`) | total_studies **1** (`…084` brain) | total_studies **2** (incl. `…152`) |
| **Server** `GetStudyThumbnails(…152)` | — | **patient_id = 44533** |
| **DICOM tag** of `…152` files (ground truth) | — | **PatientID = 44533**, BodyPart SHOULDER |
| **Local DB (before fix)** | **2 studies** (`…084` + **`…152`**) ❌ | 1 study (`…149`) |

So `…152` is genuinely 44533's, but the **local DB had it filed under 44504's
`patient_fk`**, and its 101 instances were downloaded into the study folder under 44504.
The server never associated `…152` with 44504 — this was a **local mis-association**, not
a server artifact.

## Root cause
`_resolve_patient_study_uids` (`_hp_patient_open.py`) has fallbacks (the still-displayed
right-panel thumbnails of the *previous* patient, search caches) that can surface another
patient's study UID into the current patient's list. The existing cross-patient guard only
dropped studies **already attributed to another patient in the local DB** —
`_study_owner_patient_id()` returns `None` for a *fresh* (not-yet-downloaded) study, so a
leaked fresh study was **kept**, then STEP 3.5 / the single-click reconcile **downloaded +
persisted it under the wrong patient**. Once downloaded, the DB "confirmed" the wrong
owner — self-fulfilling. (Distinct from the earlier display-only `_resolve` leak; this one
*persisted*.)

## Fix — server-authoritative ownership at every persist/display point
The server's study-info carries the study's TRUE `patient_id`. Used it as the authority:

- **Fix A — `_hp_patient_open.py` STEP 3.5 (double-click):** before queueing/aggregating a
  resolved study, skip any non-clicked study whose server `patient_id` ≠ the target
  patient. (`continue` drops it from the download queue **and** the viewer series map.)
- **Fix C — `_hp_series.py` `_reconcile_patient_studies_on_click` (single-click):** same
  guard before `save_complete_study_info` + `add_downloads`.
- **Fix B — `_hp_modules.py` `_show_grouped_patient_studies` (grouped thumbnails):** drop
  any non-primary study the local DB attributes to a different patient (defense-in-depth;
  the thumbnail folder is study-UID-keyed and patient-blind).

All three log a `*_cross_patient_skip` trace when they drop a study.

## Data correction
Re-assigned the mis-filed study to its **true owner** (re-attribution, not deletion — the
images are valid 44533 data). DB backed up first to
`backups/dicom_pre-xpatfix_2026-06-02_115712.db`. After:
- **44504 → 1 study** (`…084` brain) ✅
- **44533 → 2 studies** (`…149` + `…152`) ✅ — matches the server.

## Verification
- Ground truth re-confirmed from the DICOM `PatientID` tag before re-assigning.
- 3 edited files compile + import; `tests/code/download_manager` 107/0; combined
  `download_manager + ui_services + system` = 231 tests, **0 errors**, 1 pre-existing
  unrelated failure (`test_ui_service_kpis`); the existing guard test
  `test_resolve_patient_study_uids_scope` **passes**.

## Note (pre-existing, not introduced here, no production impact)
A latent circular import in the `modules.download_manager` package (its `__init__`
imports reach `home_panel.widget → zeta_adapter` while mid-init) makes a few test files
fail to *collect* when a home-panel-importing suite is collected before `download_manager`.
It does not affect the running app (fixed import order) and is unrelated to this fix;
flagged for a separate, scoped untangling.

## Takes effect on next launch
The running instance still holds the pre-fix code + stale in-memory study lists. Restart
to load the code guards and the corrected DB; 44504 will then show only its brain study.
