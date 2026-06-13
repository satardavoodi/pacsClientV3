# Patient 45932 — Document/attachment series visible in DICOMweb, missing in the Workstation

**Date:** 2026-06-11
**Status:** Root cause isolated to the **server/socket-query layer** (upstream of the
workstation). One server-side data point is needed to pick between the two remaining
sub-causes. **No workstation code was changed** — the workstation has no filter that
drops document series, and a blind change here would risk the working-attachment
behaviour for every other patient.

---

## 1. Symptom

Patient **45932** has a scanned/dicomized clinical-history *document* attachment. The
DICOMweb viewer (`http://81.16.117.196:8000/`) shows it; the AI-PACS Workstation does
not. This is an **exception** — document attachments display correctly for almost all
other patients.

## 2. What the Workstation actually received (evidence)

### 2a. Local DB (`user_data/database/dicom.db`)
- 45932 (`patient_pk=3480`) has **one** study locally: `study_pk=1034`, modality `MR`,
  **44 series** — #2–#40 (MR imaging) + #100–#104 (`SUB_…` subtraction MR). All
  `modality='MR'`. **No `#100000` "Documents" series, no DOC series, no second study.**

### 2b. Live open trace — `download_diagnostics.log`, 2026-06-11 12:15:07–09
Study `1.3.12.2.1107.5.2.46.174759.30000026061007461957900000055`:
```
phase=plus_entry            study_uids_count=1
phase=right_panel_cache_gate  server_series=44  grew=1
NET_TIMING endpoint=GetStudyThumbnails  payload_bytes=626189
phase=right_panel_socket_done thumbnail_count=44
NET_TIMING endpoint=GetPatientList ...        # per-modality enumeration re-query
phase=right_panel_cache_gate  server_series=44  grew=0   # final: same study, 44, cache hit
```
So: the server resolved **one** study for the patient, `GetStudyThumbnails` returned
**exactly 44 series with no `#100000`**, and the per-modality enumeration found **no
second study/modality**. The document never entered the workstation at any stage.

## 3. Why this is NOT a workstation filtering/parsing/rendering bug

- There is **no series-number cap and no modality filter** in the discovery path
  (`_resolve_patient_study_uids` / `_enumerate_studies_for_row` / the right-panel cache
  gate). Study UIDs come straight from the `GetPatientList` row; series come straight
  from `GetStudyThumbnails`.
- The viewer **explicitly supports** `#100000` document series (single-image
  scanned/reception pages: `vtk_widget/_vw_series.py`, `_vc_backend.py`,
  `_vw_interactor.py`), and the home summary deliberately **merges** DOC into the parent
  modality (`patient_table_widget._modality_summary_label`). Nothing discards it.
- Proof the stack renders documents when the server sends them: **151 patients** hold
  DOC series in the DB. In the working cases the server reports the study modality as
  **`"MR, DOC"`** and `GetStudyThumbnails` returns the `#100000` series *inside* the
  imaging study (e.g. PID 44031 study 835 = 40 series incl. `#100000`; 44943, 45391,
  45002 …). 45932's study came back as plain **`"MR"`**, 44 series, no `#100000`.

The disappearance is therefore at the **AI-PACS reception/socket server**, not the
client.

## 4. Root cause

For the working patients the reception server **associated the dicomized document with
the imaging study** (study modality becomes `"MR, DOC"` and the `#100000` series is part
of that study's series set). For **45932 that association did not happen**, so:
- `GetStudyThumbnails(…055)` returns only the 44 MR series, and
- `GetPatientList` reports the patient as a single modality (`MR`) / single study, so the
  workstation's per-modality enumeration (`_enumerate_studies_for_row`, which only fires
  when `len(modalities) > 1`) short-circuits and never looks for a DOC study.

DICOMweb (QIDO-RS) enumerates the underlying DICOM store by PatientID/Study directly, so
it still sees the document instance regardless of the reception server's MR↔DOC
association metadata. That is exactly why this is an exception case rather than a general
failure.

## 5. CONFIRMED: Case A — a separate DOC study the server never links to the patient

User-supplied DICOMweb read for PatientID 45932:
- **Document study:** `StudyInstanceUID = 1.2.826.0.1.3680043.8.498.45766249966305326468078524795397575317`
- **Imaging (MR) study:** `StudyInstanceUID = 1.3.12.2.1107.5.2.46.174759.30000026061007461957900000055`

The document is a **distinct study** with its own UID — and that UID is in the exact
`1.2.826.0.1.3680043.8.498.*` family used by every dicomized-document study on this server
(e.g. 44982's DOC study `…64206…`). So this is the normal "DOC as its own study" shape,
**not** an in-study `#100000` series.

### Why it still failed — and why it works for everyone else
The workstation's per-modality discovery (`_enumerate_studies_for_row`) queries the
patient list once per modality and unions the extra study UIDs. The
`download_diagnostics.log` / `app.log` `[FAST_OPEN_TRACE] phase=study_enumerated_by_modality
modality=DOC` traces show this **succeeding for dozens of patients** — 44982, 44825,
45448, 45515, 45346, 45530, 45405, 45745, 45895 … each had its separate DOC study
discovered and pulled. **45932 never appears in those traces, and its DOC study UID
`…45766…` appears in ZERO log lines across every log file.** The workstation never
received the DOC study from any server response.

The discriminator in `_enumerate_studies_for_row` is the patient's **modality set as
reported by `GetPatientList`**: enumeration only probes a modality the server lists for
the patient (and only fires at all when the row has >1 modality). For the working
patients the server reports DOC among the patient's modalities, so the DOC probe runs and
finds the DOC study. **For 45932 the socket server does not report a DOC study/modality
for the patient at all** — even though the DOC study physically exists in the store
(DICOMweb finds it by querying studies directly, independent of the patient↔study
aggregation the socket API depends on).

### Root cause (confirmed)
A **server-side patient↔study linkage gap specific to 45932's DOC study**: the
reception/socket server's patient aggregation (`GetPatientList`) does not associate DOC
study `…45766…` with PatientID 45932, so it neither lists DOC in the patient's modality
set nor returns it. The workstation's document-discovery path is healthy and proven — it
is simply never told the study exists. Likely sub-causes on the server: the DOC study's
`PatientID` tag does not match `45932` exactly (issuer/leading-zero/name-only mismatch),
or the patient modality aggregation was not refreshed after the document was filed.

## 6. Fix

- **Primary (server-side, correct fix):** on the reception/PACS server, verify the DOC
  study `…45766…` carries `PatientID = 45932` (same issuer) and re-index / re-aggregate
  the patient so `GetPatientList` reports `DOC` among 45932's modalities — exactly as it
  already does for the working patients above. Once the server surfaces it, the
  workstation will discover, download, and render it with **no client change** (the
  `#100000`/DOC rendering and DOC→parent-modality merge already work).

- **Optional client mitigation (only if the server returns the DOC study for a
  `patient_id=45932 + modality='DOC'` query):** add a **gated, single** `DOC`-modality
  probe to `_enumerate_studies_for_row` that also runs for *single*-modality patients
  (documents are cheap 1-image studies), unioning any DOC study found. Trade-offs that
  keep it safe: gate it behind a flag, run at most one extra `DOC` probe per open, and
  keep the existing cross-patient isolation re-check on every enumerated UID. **Caveat:**
  if the server's `modality='DOC'` query for 45932 *also* returns nothing (because the
  PatientID linkage itself is broken — the more likely case here), this mitigation does
  **not** help and only the server-side fix will. So confirm the server behaviour before
  spending the change.

**Recommendation:** fix on the server (§6 primary) — that is where 45932 diverges from
every working patient, and it requires no risk to the workstation's shared discovery path.
I did **not** make a code change: an unconditional DOC probe would touch the open-latency
contract for *every* patient, and it may not even resolve this case.

---

## 8. Follow-up after the server fix — patient 46024 (2026-06-13): first-open vs reopen

The server-side fix (PatientID normalization in `socket_server.py::GetPatientList` +
`document_store.py` attach) was applied, and it **works**: for patient **46024**
(BAGHIAN^AMIRA) the workstation now discovers, downloads, and persists the DOC study.
Local DB confirms BOTH studies present:
- `study_pk=1043` MR `…30000026061104273317000000007` (12 series #2–11 + #100/#101)
- `study_pk=1054` DOC `1.2.826.0.1.3680043.8.498.11911704554218379962738311408928699750`
  (1 series **#100000 "Documents", modality DOC, 2 images**) ✅

**New, narrower client issue surfaced by the fix: the attachment only appears on the
SECOND open (close + reopen), not the first.** This is a first-open refresh-timing gap,
not a discovery gap. Open trace (`app.log` 2026-06-13 13:40:11–14, patient 46024):
```
phase=plus_entry                study_uids_count=1          # only MR known at open
phase=right_panel_cache_gate    grew=1 server_series=12
phase=right_panel_display_done  thumbnail_count=12          # 12 MR series shown, NO DOC
search_patients_sync → "Found 1 patients"                   # async re-query returns AFTER
download_process_worker … study=1.2.826…11911… series=1     # DOC study discovered + downloaded
(… no further right_panel_* / display refresh …)            # UI never re-rendered to add DOC
```
So at open, `_resolve_patient_study_uids` returns **1** UID (the MR study, the only one in
the table/DB at that moment). The DOC study is found by the **async** enumeration
(`_resolve_patient_study_uids_async` / `_reconcile_patient_studies_on_click` →
`_enumerate_studies_for_row`) and downloaded ~300–900 ms later — but the home right-panel
(and the viewer series sidebar) were already built from the 1-study resolution, and
**nothing refreshes them in-session when the late study lands**. On reopen, the DOC study
is already in the local DB (`study_pk=1054`), so it is resolved from the start and renders.

### Root cause (this sub-issue)
Pipeline stage = **UI refresh after async multi-study discovery**. Discovery, download,
registration, and persistence all now succeed; the missing step is re-rendering the
right-panel thumbnails / series sidebar for the patient once the enumeration adds a study
(and its DOC download completes) within the same session.

### Smallest safe fix (proposed, not yet implemented)
When the single-click reconcile / async resolve discovers **additional** study UIDs for
the patient that were not in the initial render set, re-trigger the patient's right-panel
thumbnail display (and, if a viewer tab for that patient is open, its series-info refresh)
— exactly the existing "server grew" refresh, but keyed on *study count grew* rather than
*series count grew*. Gate it to fire **only** when extra studies were actually found
(zero-cost for the common single-study patient), reuse the existing
`display_thumbnails` / series-info refresh entry points (no new render path), and keep the
render-coalescing signature so it does not double-render when nothing changed. This is the
real fix, not a workaround; it does not alter discovery, isolation guards, or the
single-study open-latency contract.

## 7. Invariants that must be preserved by any future fix
- Single-study / single-modality patients keep **zero** extra server queries on open.
- Cross-patient study isolation guards (server `patient_id` re-check) still run on every
  enumerated UID.
- The viewer's existing `#100000`/DOC support and the DOC→parent-modality merge in the
  home summary stay unchanged.
