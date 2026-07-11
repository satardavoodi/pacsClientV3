# Viewport Overlay Metadata Unification & Reliability

As-built + review record. Created 2026-07-09. Tracks the OPT item for the
four-corner viewport overlay metadata (patient name/id, slice count, sequence
name/type, slice thickness, …) being inconsistent across viewports and between
current/previous exams.

## 1. Review findings (verified against code)

### 1.1 Two independent overlay renderers; MPR has none
- **FAST** (`pydicom_qt`): `CornerAnnotations.update_from_metadata`
  (`modules/viewer/fast/qt_slice_viewer.py:246`), fed by `_build_annotation_metadata`
  (`modules/viewer/fast/qt_viewer_bridge.py:1917`).
- **Advanced** (`vtk_simpleitk`): per-corner `vtkTextActor`s via `load_*_actors` +
  `_update_corners_actors_impl` (`modules/viewer/advanced/viewer_2d.py:1159-1350`);
  helper `make_corner_actor` (`PacsClient/pacs/patient_tab/utils/corner_labels.py:27`).
- **MPR** (zeta / orthogonal / curved): render only anatomical A/P/L/R/S/I
  orientation labels; **no** patient/series overlay (curved MPR's
  `update_corners_actors` is a no-op stub). So MPR is out of scope for text
  unification — but the two 2-D renderers reading different dicts is the core of
  "different viewports show it differently."

### 1.2 Where each field is read from
- Patient identity + study block: `self.metadata_fixed`.
- Series info (name/description/thickness/modality): `self.metadata['series']`
  (built from DICOM at load in `image_io.py`).
- Per-slice geometry (rows/cols): `self.metadata['instances'][k]`.

`metadata_fixed` is populated by **two different builders**, chosen by a
`len(metadata_fixed) < 3` guard:
- **DB path**: `_pw_metadata.check_and_add_meta_fixed` → `get_patient_by_patient_pk`
  / `get_studies_by_patient_pk` (raw `SELECT *`, DB column names).
- **Live-DICOM path**: `_vc_load.py:1237` → `utils.get_meta_fixed(first_instance)`
  (`utils.py:602-661`).

### 1.3 Root cause — Patient name Persian vs English
There is **no `PersonName` component selection anywhere** in the app. Every read
is a blanket `str(PatientName)` (`utils.py:610`, `:289`), which emits whatever
script the sender stored (alphabetic=ideographic groups joined by `=`). Compounded
by:
- Two in-app `metadata_fixed` origins (DB copy captured at import vs a live DICOM
  re-read) that can disagree, chosen non-deterministically.
- A charset fix (`_maybe_fix_charset_inplace`) that runs on only some import paths.
- The tab title, patient list, thumbnails, and **previous-exams** use the
  **server/RIS reception name** (often Persian), while the image overlay uses the
  **DICOM/DB name** (often English) — for the SAME patient.

### 1.4 Root cause — "NA"
The literal string `"N/A"` is the default in `get_meta_fixed` (every field) and at
import (`get_or_create_patient`). The overlay guards are `x or ""` / `if not x`
(`qt_slice_viewer.py:262-274`, `qt_viewer_bridge.py:1928-1944`) — they only blank
**empty/None**. `"N/A"` is truthy, so it prints verbatim even when a real value
exists in another source. Advanced adds a **key mismatch**: it reads
`patient_sex`/`patient_age` but the DB columns are `sex`/`age`, forcing those to
`N/A`.

### 1.5 Current vs previous exam
Previous exams are assembled by a separate server/RIS pipeline
(`PacsClient/utils/previous_exams.py`) but, when opened, the bridge is still handed
the **current** patient's `metadata_fixed` — so a prior study can paint the current
patient's identity until its own metadata is rebuilt. Different logic, different
source, from the RIS name shown in the list.

### 1.6 Mixed sources (the structural defect)
For a single field (`patient_name`) the display can be fed by four unreconciled
sources — local DB, live DICOM re-read, server/RIS name, server thumbnail name —
with **no canonical normalization point**.

## 2. Chosen policy (with the user, 2026-07-09)
- Patient Name/ID **source precedence**: DICOM (image) → local DB → server/RIS.
- PersonName **component**: prefer the ALPHABETIC / Latin (English) group, fall
  back to the ideographic/phonetic (Persian) group.
- **Missing**: `""`, `"N/A"`, `"NA"`, `none`, `null`, `-`, `unknown` all treated as
  missing so a better source wins; rendered `NA` only when truly absent everywhere.

## 3. Implemented (this pass)
- **Canonical provider (trunk, pure stdlib):**
  `PacsClient/utils/overlay_metadata.py` — `build_overlay_metadata(dicom, db,
  server, series, name_pref)` + `normalize_person_name`. No Qt/VTK/pydicom/DB
  imports, so it cannot couple the viewer domains; each domain *calls* it. Scope is
  **descriptive overlay text only** — it never decides series identity/number,
  geometry, slice order, or the slice counter (those stay downstream, per the
  architecture rule). Unit tests: `tests/code/viewer/test_overlay_metadata.py`
  (16, incl. English-component pick, precedence, `NA`-only-when-missing, DB
  `sex`/`age` alias).
- **FAST wired as first consumer** (flag-gated, DEFAULT OFF): in
  `qt_viewer_bridge._build_annotation_metadata`, when
  `AIPACS_CANONICAL_OVERLAY_METADATA=1`, the descriptive fields (patient
  name/id/sex/age, study_date, institution, series_description) are resolved
  through the provider. Flag off = byte-identical legacy. Default off because it
  changes clinically-visible identity text — opt in to validate, then flip.
  Wrapped in try/except so it can never break the paint path.

`qt_viewer_bridge.py` is plugin-mirrored (`packages/viewer/payload/...`); the
mirror sync of this file is pending (run `tools/dev/sync_plugin_mirrors.py` on
Windows). `overlay_metadata.py` lives under `PacsClient/utils` (main app tree) and
is not part of the viewer payload.

## 4. Staged next (NOT done — each independently flag-gated, live-validate first)
1. **Advanced viewer** (`viewer_2d.py` `load_*_actors` + `_update_corners_actors_impl`):
   route the same descriptive fields through `build_overlay_metadata`; also fixes
   the `patient_sex`/`patient_age` vs `sex`/`age` key mismatch. Same flag.
2. **Previous-exam / cross-study**: give each opened previous-exam series its OWN
   `metadata_fixed` (built from that series' DICOM), and pass the server/RIS name
   as the `server=` fallback so the overlay stops painting the current patient's
   identity for a prior study.
3. **`image_io` default cleanup**: the series builder defaults
   `series_description="Series {n}"`, `series_thk="1.0"`, `modality="CT"` pre-mask
   missingness. Decide whether to keep as friendly placeholders or emit `NA` via
   the provider (the provider already treats them as present; changing the builder
   defaults is the riskier edit).
4. **Slice-count unification**: FAST uses widget `_slice_count` /
   `get_count_of_slices()`, Advanced uses VTK dims — reconcile to one rule
   (expected/authoritative on-disk count) so the `k / N` counter matches.
5. Flip `AIPACS_CANONICAL_OVERLAY_METADATA` to default-on after live validation.

## 5. Validation
Pure provider: 16 unit tests green (headless). FAST wiring: source-pinned;
compile confirmed via the Read tool (the sandbox FUSE mount truncates the 3600+
line bridge, so in-sandbox `py_compile`/pytest collection is unreliable for it —
authoritative parse is the Read-verified edit region + Windows `.venv`).
NEEDS live source-build verify with `AIPACS_CANONICAL_OVERLAY_METADATA=1`: open a
bilingual-name patient in the FAST viewer → overlay shows the English name, no
stray `NA`, consistent across layouts; confirm flag-off is unchanged.
