# DICOMDIR on interchange media — as-built (2026-07-11)

One implementation, two workflows. **Do not fork it.**

| | |
|---|---|
| **Implementation** | `modules/dicom_media/dicomdir.py` — `DicomDirBuilder` (**CORE**) |
| **CD burner** | `modules/cd_burner/dicomdir_builder.py` — thin **re-export shim** |
| **Offline Sync** | `PacsClient/utils/offline_cloud.py::build_offline_cloud_dicomdir` |

Core placement is **required**: `modules.cd_burner` is excluded from the engine
(`appA_workstation.spec` `optional_prefixes`) and only ships inside the optional
`run_cd` plugin payload, so core code cannot import from it. The shim keeps every
existing cd_burner import byte-identical.

**Build pin:** Offline Sync imports the builder LAZILY (inside a function), so
`modules.dicom_media[.dicomdir]` is pinned in the spec's `hiddenimports` — same
reason as the `modules.network.ino_*` pins. Without it, DICOMDIR generation dies
with `ModuleNotFoundError` **in the frozen build only**.

---

## THE constraint that shapes everything

A DICOM **File ID component is <= 8 chars of `[A-Z0-9_]`** (PS3.10). Therefore:

* a `StudyInstanceUID` (`1.2.840.113619…`) can **never** be a valid File ID, and
* a readable name like `Michael_Brown` can **never** be a File ID either.

**Consequence:** a *single media-root* DICOMDIR can only reference machine-named
folders (`PT000000/…`) — readable folder names and one root DICOMDIR are
**mutually exclusive**. The way to get both readability *and* compliance is to put
the DICOMDIR **inside** the readable folder, so its File IDs are relative to that
folder and the readable names sit *above* it, where the rule does not apply.

---

## CD burner — already compliant, unchanged

`cd_burn_manager.run()` → `DicomDirBuilder.build_from_study_folders(...)` after the
final staging structure is prepared. Verified on a real burned disc (`F:\`,
2026-07-11): `DICOMDIR` (29,648 B) + `PT000000/` (120 files) at the root. A CD is
single-patient media, so machine names at the root are fine. **No changes made.**

## Offline Sync — readable layout ("Option A")

```
<package root>/
├── manifest.json, package.db
├── patients/                              ← AI-PACS payload — UNTOUCHED
│   └── dicom/<StudyInstanceUID>/…            (import contract: resolved by UID)
├── .aipacs_dicomdir.json                  ← skip-if-unchanged stamp
└── DICOM/                                 ← human-readable interchange tree
    ├── DOE_JOHN/
    │   ├── 1.2.826.0…41002/
    │   │   ├── DICOMDIR                   ← File IDs relative to HERE → compliant
    │   │   └── PT000000/ST000000/SE000000/IM000001
    │   └── 1.2.826.0…08237/               ← multiple studies per patient
    ├── SMITH_JANE/
    │   └── 1.2.826.0…83306/…
    └── BROWN_MICHAEL/
        └── 1.2.826.0…61021/…
```

* **Readable** — the patient is obvious when browsing.
* **Study UID preserved** — it *is* the study folder name, so uniqueness is intact.
* **Compliant** — each DICOMDIR's File IDs are `PT000000\ST000000\…` relative to
  its own folder. A test asserts the readable name and the absolute path never
  appear in the DICOMDIR bytes.
* **Multi-patient / multi-study** — independent folders, independent DICOMDIRs
  (explicitly allowed for per-package DICOMDIR). Verified with 10 patients.
* **Name safety** — `safe_folder_component()`: `DOE^JOHN` → `DOE_JOHN`; strips
  `<>:"/\|?*` + control chars, collapses whitespace/underscores, trims trailing
  dots/spaces (Windows), caps at 64 chars, falls back to `UNKNOWN_PATIENT`.
  **DICOM metadata is never modified** — only the folder name.
* **Collisions** — two *different* PatientIDs with the same readable name are
  disambiguated by appending the PatientID (`DOE_JOHN_P1` / `DOE_JOHN_P2`), so
  every patient keeps an independent folder.

### AI-PACS import is unaffected — by design

`_import_single_study` resolves `patients/dicom/<study_uid>` **by exact UID**.
That payload is left **byte-identical**, so *any* AI-PACS version can still import
the package. The readable tree is a *separate* interchange copy — the importer
never looks at it. **Do not rename `patients/dicom/<study_uid>`**: it would break
import, including for older installs reading a newer package.

### Cost

The interchange tree is a second copy of the DICOM payload (~2× DICOM size). This
is unavoidable (File ID rule, above) — it is why the flag is opt-in per call site.
The readable layout **replaced** the earlier flat root `PT…` tree, so net storage
is unchanged.

### Opt-in

`export_studies_to_offline_cloud(..., include_dicomdir=False)` — default **False**
so cloud-consultation / education packages (which are *uploaded*) are unchanged.
Only the Offline-Sync call sites (`_hp_offline.py`) pass `True`.

> **Call-site trap (live bug, 2026-07-12).** `_hp_offline.py` has **two** call
> sites: `_autosync_studies_to_offline_cloud` (study-state autosave) *and* the
> user-facing **"Export to Offline Cloud"** action. `include_dicomdir=True` was
> wired into the autosync one only, so the real export shipped a folder with
> `patients/` + `manifest.json` + `package.db` and nothing else — no DICOMDIR, no
> patient folders. A correct builder is worthless if the export never asks for
> it. Guard: `test_every_offline_sync_export_call_site_requests_dicomdir` fails
> if any non-import call omits the kwarg.

**Skip-if-unchanged:** a `(file_count, total_bytes)` signature is stored in
`.aipacs_dicomdir.json`. The incremental Offline-Sync autosave calls the export on
*every* study-state change; without this it would rebuild every File-set each time.
`force=True` overrides. Rebuilds are from scratch (the `DICOM/` tree — and any
legacy root `DICOMDIR`/`PT…` — are cleared first), so a removed study disappears.

---

## Builder guarantees (enforced + tested)

* Standards-compliant Media Storage Directory; **relative File IDs only**.
* All patients / studies / series / instances; multi-study, multi-patient.
* **No duplicate SOP Instance UID** entries (skipped + counted).
* Files **without a `.dcm` extension** indexed (patient media stores them so).
* `_ensure_dicomdir_fields` backfills DICOMDIR-required elements servers omit
  (StudyDate/Time, StudyID, AccessionNumber, Modality, Series/InstanceNumber) —
  **UIDs and pixel data are never touched**.
* **Fails loudly, never silently:** a 0-instance File-set is an error (the old
  empty-disc bug); validation re-opens the written DICOMDIR and checks the SOP-UID
  set matches exactly **and** every referenced file exists on disk. Any per-study
  failure fails the whole generation and is surfaced in the export's `errors[]`.
* `DicomDirBuilder.last_stats`: `files_found, patients, studies, series,
  instances_added, duplicates_skipped, unreadable, failed, failures[], ok`.

## Light Viewer — no change, no rebuild

`portable_viewer/media_scan.py` is already DICOMDIR-first (`pydicom.fileset.FileSet`,
resolves relative paths, builds the patient/study/series hierarchy, falls back to a
recursive scan). Per the build rule it was **not** modified and **not** rebuilt.

## Tests

`tests/code/dicom_media/test_offline_dicomdir.py` (13): name normalization/illegal
chars; readable folder + study UID; multiple patients; multiple studies per patient;
same-name collision disambiguation; **10 patients** keep Patient→Study→Series→Image
relationships; relative File IDs only; duplicate SOPs; extension-less files;
fail-loudly on no DICOM; **AI-PACS payload byte-identical**; skip/force/auto-rebuild;
regeneration drops removed studies.
183 green across cd_burner + dicom_media + offline_cloud_server.

## Still to verify live

Open an exported `DICOM/<Patient>/<StudyUID>/` folder and a burned CD in an
**independent** third-party DICOM viewer via DICOMDIR (the tests validate the
File-set with pydicom, not a foreign reader).
