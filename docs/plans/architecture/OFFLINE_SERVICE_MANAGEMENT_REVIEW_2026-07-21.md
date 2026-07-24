# Offline Service (Offline Cloud) — Architecture Review + Management Design (2026-07-21)

Review requested: turn the Offline Service from an **export-only** tool into a full
**offline-package manager** (add / edit / delete patients, with the DB, DICOMDIR, folder
structure and DICOM hierarchy kept consistent).

This document is the as-reviewed record and the implementation plan. Nothing destructive has been
built yet — it stops at a plan for approval.

---

## 1. What exists today (as-built)

**Naming.** There is no literal "Offline Service" string. The button is **"Offline Sync"**, the
subsystem is branded **"Offline Cloud"**, and the whole engine is ONE file:
`PacsClient/utils/offline_cloud.py` (~1900 lines). `modules/offline_cloud_server/service.py` is a
`from PacsClient.utils.offline_cloud import *` facade. The DICOMDIR builder is the shared CORE
`modules/dicom_media/dicomdir.py` (cd_burner is a re-export shim).

**Flow (add path):**
`patient_table_widget.py:1588` "Offline Sync" button → `_on_offline_cloud_sync_clicked` (:2274) →
`offlineCloudSyncRequested` (:815) → `_hp_offline._on_offline_cloud_sync_requested` (:346) →
`OfflineCloudExportDialog` (a **preview/picker only** — it does not export) →
`export_studies_to_offline_cloud(server, study_uids, include_dicomdir=True)` (`offline_cloud.py:856`).

**Package on-disk layout** (`package_paths()` `:125`):
```
<folder_path>/
├── manifest.json          # envelope: format "aipacs-offline-cloud" v2, studies[], provenance, timeline, validation
├── package.db             # SQLite mirror of the local dicom.db (10 tables)
├── .aipacs_dicomdir.json  # DICOMDIR rebuild-skip signature {file_count,total_bytes}
├── patients/
│   ├── dicom/<study_uid>/…        # AUTHORITATIVE payload, keyed by StudyInstanceUID
│   ├── attachments/<study_uid>/…
│   └── thumbnails/<study_uid>/…
└── DICOM/                 # standards interchange tree (only when include_dicomdir=True)
    └── <PatientName>/<StudyInstanceUID>/PT###/ST###/SE###/IM### + DICOMDIR
```

**`package.db`** clones the local `dicom.db` DDL for: `patients, studies, series, instances,
download_progress, ai_sessions, ai_messages, ai_reports, ai_last_session, ai_reception_reports`
(`_ensure_package_schema` `:1221`). Keys: `patients.patient_id` UNIQUE, `studies.study_uid` UNIQUE
(FK `patient_fk`), `series.series_uid` (FK `study_fk`), `instances.sop_uid` (FK `series_fk`). On
export, on-disk paths are rewritten package-relative (`_rewrite_path` `:1736`).

**DICOMDIR builder** (`dicom_media/dicomdir.py`): uses pydicom's high-level `FileSet`
(`build_from_study_folders` :126). Two-pass: build a patient→study→series→file hierarchy, dedupe by
`SOPInstanceUID`, backfill Type-1 fields the server omits (`_ensure_dicomdir_fields` — UIDs/pixels
never touched), then `FileSet.write()` lays out the `PT/ST/SE/IM` tree + `DICOMDIR` (File-IDs ≤ 8
chars, which is why a separate `DICOM/` tree exists instead of referencing `patients/dicom/<uid>`).
After writing it self-validates: DICOMDIR exists, non-empty, references EXACTLY the expected SOP set,
and every referenced file exists on disk (`_validate_output_fileset` :323).

**Import / sync-back (the inverse)** is already implemented and is the template for "consistent
mutation": `sync_offline_cloud_study_to_local` → `_import_single_study` (:1502) resolves a study by
`study_uid`, patient by `patient_id`, reverses the paths, upserts rows, and mirrors the file trees
with `_copy_tree_replace` (:1654 — a destructive per-study mirror that deletes dest files absent from
source, but never removes a whole `<study_uid>` folder).

**Delete primitive already exists — but only for DB rows, internal-only:**
`_delete_rows_for_study(conn, study_uid)` (`:1313`) cascades `instances→series→studies` + all AI
tables in the **package DB**, keyed by `study_uid`. It does **not** delete the `patients` row and
does **not** touch on-disk files. It is called ONLY inside `_export_single_study` (to make re-export
idempotent). This is ~60% of a real delete.

**Package validation** (`validate_offline_cloud_package` :283): manifest parses + format ok,
`package.db` present, required folders present, manifest-study-set vs DB-study-set cross-check, and
**every DB study has ≥1 DICOM file on disk**. Writes `manifest["validation"]` and is run before every
import.

---

## 2. Gaps (what management needs and today lacks)

1. **No user-facing LIST of package patients in a manageable (multi-select) form.** Today: read-only
   browse (`list_offline_cloud_studies` :455), the Settings package inspector (raw manifest JSON),
   and per-package counts. Nothing lets you pick patients inside a package to act on.
2. **No DELETE of a patient/study from a package.** `_delete_rows_for_study` is rows-only, internal,
   never files, never the patient row, not exposed. `_cloud_on_delete` (server_settings) deletes only
   the *config pointer*, leaving all data on disk. **Result today: there is no supported way to remove
   a patient, and a hypothetical row-only delete would orphan the `patients/*/<uid>` folders.**
3. **No EDIT of a patient already in a package** (only whole-study re-export, or hand-editing the raw
   `manifest.json`). No path rewrites the package's DICOM headers.
4. **No files→DB orphan check.** Validation only checks DB→files. A `patients/dicom/<uid>` folder with
   no `studies` row (or a `DICOM/` interchange leftover) is invisible and never pruned.
5. **No standalone reconcile/repair.** DICOMDIR + manifest are rebuilt only as a side effect of
   export; there is no "the package changed out-of-band, make it consistent again" operation.

---

## 3. Proposed design — make it a package manager (reuse the engine, don't fork it)

Everything below is ADDITIVE to `offline_cloud.py`, reuses the existing primitives, and is
flag-gated. The guiding rules: **study_uid is the identity**; **UIDs are NEVER regenerated** (same
rule as the whole app + the demographic editor); **every mutation ends with a rebuild + validate**;
**every destructive op backs up `package.db` + `manifest.json` first and rolls back on failure**.

### 3.1 Core primitives (new functions in `offline_cloud.py`)

**A. `remove_studies_from_offline_cloud(server, study_uids, *, actor)`** — the delete building block:
1. Backup `package.db` + `manifest.json` (timestamped, in the package under `.trash/` or `backups/`).
2. Open `package.db`; for each `study_uid`: `_delete_rows_for_study` (existing) **+** delete on-disk
   `patients/{dicom,attachments,thumbnails}/<study_uid>` (and any `DICOM/` leftovers are handled by
   the rebuild, which wipes that tree).
3. **Prune orphan patient rows**: any `patients` row with no remaining `studies` row → delete.
4. `rebuild_offline_cloud_manifest` (reads the DB → manifest reflects reality).
5. `build_offline_cloud_dicomdir` (regenerates the whole `DICOM/` tree + DICOMDIR from what remains).
6. `validate_offline_cloud_package`; if not `is_complete` → restore from the backup and return an error.
7. Return `{ok, removed_study_uids, removed_patient_ids, freed_bytes, validation}`.

**B. `remove_patients_from_offline_cloud(server, patient_ids, *, actor)`** — resolve each `patient_id`
→ its package `study_uids` (query `package.db`), union them, call primitive A once. "Delete patient" =
delete all that patient's studies. Multi-select delete = union of several patients' studies, ONE
rebuild/validate at the end (not per-study).

**C. `edit_offline_cloud_patient(server, patient_id, values, *, actor)`** — the harder primitive.
REUSE the demographic-edit core already built for the main viewer
(`PacsClient/utils/dicom_demographics_edit.py`, which rewrites PatientName/ID/Institution/StudyDate/
StudyTime/Age across every image **without touching any UID**, verifies immutability, atomic
`.part`→replace, backup-first):
1. Resolve the patient's package study folders (`patients/dicom/<uid>` for each study).
2. Run the demographic-edit apply against those folders (UIDs preserved → disk layout, package.db
   keys, DICOMDIR identity all stay valid).
3. Update `package.db` rows with `force_update_*_demographics` analogues (or re-derive from the edited
   headers).
4. Rebuild manifest (denormalized name/id/date live there) + DICOMDIR (patient FOLDER name derives
   from PatientName/ID, so the `DICOM/<PatientName>/…` path changes — a full `DICOM/` rebuild handles
   it) + validate + rollback-on-failure.
   - **Editable fields** = exactly the demographic set the editor already supports (PatientName,
     PatientID, InstitutionName, StudyDate, StudyTime, PatientAge). **Not** UIDs, geometry, or
     series/instance structure.

**D. `reconcile_offline_cloud_package(server)`** — extend `validate_offline_cloud_package` with the
files→DB direction (orphan `patients/*/<uid>` folders with no DB row) and an optional prune, then
rebuild manifest + DICOMDIR. This is the "repair/verify" the spec's Integrity section asks for.

All of A–D are thin orchestrations over existing, tested pieces (`_delete_rows_for_study`,
`build_offline_cloud_dicomdir`, `rebuild_offline_cloud_manifest`, `validate_offline_cloud_package`,
`dicom_demographics_edit.apply_demographic_edit`). The genuinely new logic is: on-disk folder
removal, orphan-patient pruning, the files→DB orphan scan, and the backup/rollback wrapper — each
small and unit-testable against a synthetic package.

### 3.2 UI redesign

The "Offline Sync" entry opens a manager with two modes (spec's two workflows):
- **Add Selected Patient to Offline Service** — the existing export path (`OfflineCloudExportDialog`
  → `export_studies_to_offline_cloud`), unchanged.
- **Edit or Delete Existing Offline Patients** — available with NO patient selected. Pick the target
  package (server), load its patients from `package.db` into a **multi-select** table (Patient ID,
  Name, #studies, #images, dates), with **Delete selected** (multi) and **Edit** (single) actions.
  Delete confirms, shows freed space, runs primitive B, reports the post-op validation. Edit opens the
  demographic dialog (reuse `PatientEditDialog`) scoped to the package, runs primitive C.

Simplest safe placement: a new `OfflineCloudManagerDialog` (list + actions) reachable both from the
"Offline Sync" button (a mode switch) and from Settings → Offline Cloud Server (a "Manage contents…"
button next to the existing per-server row). The existing export dialog stays as the "add" mode.

### 3.3 Integrity contract (run after every add/edit/delete)

`validate_offline_cloud_package` (extended for files→DB orphans) must return `is_complete` before the
op is considered done; otherwise auto-rollback from the pre-op backup. The DICOMDIR builder's own
`_validate_output_fileset` already guarantees DICOMDIR↔files↔SOP-set consistency for what remains.
This satisfies the spec's DB / DICOMDIR / folder / hierarchy / orphan checks.

---

## 4. Suggested phasing (each flag-gated, guard-tested, no regression to export)

- **P1 — Delete (highest value, most requested):** primitives A + B + backup/rollback + files→DB
  orphan prune + the multi-select Manage dialog with Delete only. Guard tests on a synthetic package
  (delete 1 of N studies; delete a whole patient; multi-patient delete; assert rows gone, folders
  gone, no orphan patient row, DICOMDIR rebuilt, manifest matches, validation complete, unrelated
  patients untouched, rollback on injected failure).
- **P2 — Integrity/reconcile:** primitive D + surface validation status in the Manage dialog.
- **P3 — Edit:** primitive C reusing the demographic editor + wire `PatientEditDialog` to the package.
- **P4 — polish:** freed-space reporting, `.trash/` retention, undo-last-delete from backup.

## 5. Risks / constraints to honor

- **Clinical delete is irreversible for the patient's copy in that package** → backup-first +
  explicit confirm + post-op validation are mandatory; keep a short-retention `.trash/` for undo.
- **UIDs are identity** — never regenerate on edit (the demographic-edit core already guarantees this).
- **A package may be actively used as a data source** (`_on_local_study_state_changed` autosync). The
  manager must operate on the package as the authority and not race the autosync — do mutations under
  the package's own lock/backup and re-validate.
- **Transport** (`modules/cloud_consultation/package_sync.py`) mirrors the whole folder — deletes must
  happen in the package folder so a subsequent upload propagates the removal (no special casing).
- `offline_cloud.py` is NOT plugin-mirrored (single copy). The DICOMDIR builder + demographic-edit
  core ARE shared/reused — do not fork them.
