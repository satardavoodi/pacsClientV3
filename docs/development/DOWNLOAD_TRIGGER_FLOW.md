# Zeta Download Trigger Flow — Fix & Reference

> **Date:** 2026-05-24 · **Area:** patient list → Zeta Download Manager
> **Status:** Fixed and verified live (studies queue and download correctly).

This document covers the "Download" button on the patient table — selecting
studies in the patient list and sending them to the Zeta Download Manager
queue. It exists because that path broke in a non-obvious way and the fix
involves a Qt threading rule that is easy to regress.

---

## Summary

Pressing **Download** on selected patient studies did nothing — the Download
Manager tab opened but its queue stayed empty (0 studies), so no download
started. Two independent bugs combined to cause this, plus one UI-freeze
issue. All three are now fixed.

---

## What changed

| Area | Change |
|---|---|
| `_hp_modules.py` — `_on_zeta_download_requested` | Series-info enrichment for selected studies now runs on a **worker thread** so the UI no longer freezes on slow socket calls. |
| `_hp_modules.py` — `_ZetaDownloadBridge` | **New.** A tiny `QObject` with a `finished` signal that hands the worker's result back to the UI thread safely. Replaces `QTimer.singleShot`, which does **not** work from a worker thread. |
| `patient_table_widget.py` — `_programmatic_sort` | Sorting now **preserves the checkbox selection by Study UID**. Previously a sort desynced the checkboxes from the row data. |
| `patient_table_widget.py` — `_extract_row_data` | Falls back to the `UserRole` Study-UID list when the visible Study-UID cell is empty, so a validly-selected row is not silently dropped. |
| `_hp_study_save.py` — `get_series_info_from_server` | Per-session negative cache (`_GETSTUDYINFO_UNSUPPORTED`) skips the 3 s `GetStudyInfo` probe on servers known to never answer it. |
| `patient_table_widget.py` / `_hp_layout.py` / `_hp_modules.py` | Stale internal name **"Zeta NPR" renamed to "Zeta Download"** (signal `zetaDownloadRequested`, handlers `_on_zeta_download_*`). It was always one feature — the Zeta Download Manager — not a separate "NPR" module. |
| `_hp_modules.py` | `[ZDL_DIAG]` WARNING-level diagnostic logging across the trigger path (kept as a permanent debugging aid — see below). |

---

## Why it was changed (the bugs)

### Bug 1 — sorting desynced the selection
The patient table is a `QTableWidget` that mixes plain `QTableWidgetItem`
cells (Patient Name, Images, Study UID…) with `setCellWidget` widgets (the
row **checkbox**, Status, Report, Assign). `QTableWidget.sortItems()` reorders
the *items* but the *cell widgets* do not travel with them reliably. Selection
was gathered purely by physical row index (`get_selected_rows()` reads the
checkbox at row N, `_extract_row_data()` reads the data at row N), so after a
sort the checked rows and the study data no longer lined up. The selected set
came back wrong — or empty.

### Bug 2 — the worker callback never fired (the main bug)
To keep the UI responsive, series-info enrichment was moved onto a
`threading.Thread`. The worker handed its result back to the UI thread with
`QTimer.singleShot(0, _finish_zeta_download)`.

**`QTimer.singleShot()` does not fire when called from a plain Python worker
thread.** A `QTimer` needs a Qt event loop *in the thread that created it*; a
`threading.Thread` has none, so the timer never triggers. `_finish_zeta_download`
— which calls `download_manager.add_downloads(...)` — was therefore never
reached. The series fetch *succeeded* (the `[ZDL_DIAG]` log showed all studies
enriched with their series), but the studies were never handed to the queue.

### Issue 3 — UI froze on the GetStudyInfo probe
`get_series_info_from_server` probes the `GetStudyInfo` endpoint first (3 s
timeout). On servers where that endpoint is unsupported it always times out,
wasting ~3 s per study. The negative cache records the first timeout and skips
the probe for the rest of the session.

---

## How the download flow works now

```
Patient table: user sorts / checks studies / clicks Download
  │
  ├─ _on_zeta_download_clicked()            (patient_table_widget.py)
  │     get_selected_patient_data_list()    selection gathered by row;
  │                                         sort-safe because _programmatic_sort
  │                                         re-applies checks by Study UID
  │     emit zetaDownloadRequested(selected_studies)
  │
  ├─ _on_zeta_download_requested()          (_hp_modules.py, UI thread)
  │     open/raise the Download Manager tab
  │     needs_fetch = studies missing series info
  │     if none → _finish_zeta_download() directly
  │     else:
  │        bridge = _ZetaDownloadBridge()           ← created on UI thread
  │        bridge.finished.connect(_finish_zeta_download)
  │        start threading.Thread(_enrich_worker)
  │
  ├─ _enrich_worker()                       (worker thread — NOT the UI thread)
  │     for each study: _get_or_fetch_series_info()  (socket I/O, may be slow)
  │     bridge.finished.emit()              ← thread-safe queued signal
  │
  └─ _finish_zeta_download()                (UI thread, via the queued signal)
        download_manager.add_downloads(selected_studies, start_immediately=True)
        → studies enter the Zeta Download Manager queue → download starts
```

Key point: the **worker thread emits a Qt signal**; because the
`_ZetaDownloadBridge` object lives on the UI thread, the connected slot
(`_finish_zeta_download`) is delivered to the UI thread via a queued
connection. That is the correct, reliable cross-thread hand-off.

---

## Regression-prevention notes (read before touching this path)

1. **Never marshal back to the UI thread with `QTimer.singleShot` from a
   `threading.Thread`.** It silently never fires — there is no event loop in
   that thread. Use a `QObject` signal created on the UI thread (the
   `_ZetaDownloadBridge` pattern), or `QMetaObject.invokeMethod` with a
   queued connection. This rule applies to **every** worker-thread → UI
   hand-off in the codebase, not just downloads.

2. **The patient table mixes item cells and widget cells.** Any code that
   calls `sortItems()` (or otherwise reorders rows) must re-apply the
   checkbox selection by **Study UID**, not by row index. `_programmatic_sort`
   already does this — keep it that way; do not gather selection by raw row
   index across a sort.

3. **`add_downloads` rejects studies with no series.** A study handed to the
   Download Manager must have its `series` list populated first (that is what
   the enrichment worker does). If a study reaches `add_downloads` with no
   series it is silently skipped — the queue ends up empty with no error.

4. **The `download` log component is at WARNING level.** `INFO` logs on the
   download path are invisible in `download_diagnostics.log`. For any
   download-trigger diagnostics use `logger.warning(..., extra={"component":
   "download"})`. The `[ZDL_DIAG]` markers in `_on_zeta_download_requested`
   follow this rule — see below.

5. **`GetStudyInfo` is unsupported on some PACS servers.** Do not lengthen the
   3 s probe timeout, and do not remove the `_GETSTUDYINFO_UNSUPPORTED`
   negative cache — both exist to fail fast and fall back to the reliable
   `GetStudyThumbnails` endpoint.

6. **"Zeta NPR" is not a separate feature.** It is the old internal name of
   the Zeta Download action. If you find any remaining `npr`/`NPR` identifier
   tied to the download button, it is stale naming — there is one feature: the
   Zeta Download Manager.

---

## Files touched

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py`
  — `_on_zeta_download_requested`, new `_ZetaDownloadBridge`, off-thread worker.
- `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py`
  — `_programmatic_sort`, `_extract_row_data`, Zeta Download rename.
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py`
  — `zetaDownloadRequested` signal connection.
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_study_save.py`
  — `get_series_info_from_server` GetStudyInfo negative cache.

---

## How to debug the download trigger

Pressing Download writes a `[ZDL_DIAG]` trail to `download_diagnostics.log`
(WARNING level). A healthy run looks like:

```
[ZDL_DIAG] trigger selected=4 with_uid=4 with_series=0 needs_fetch=4
[ZDL_DIAG] spawning enrich worker for 4 studies
[ZDL_DIAG] worker done; enriched detail(uid,series)=[(True,33),(True,30),...]
[ZDL_DIAG] finish: about to add_downloads n=4 detail(uid,series)=[...]
[ZDL_DIAG] finish: add_downloads call completed
```

Where it breaks tells you the cause:
- `with_uid=0` → studies have no Study UID (selection / `_extract_row_data`).
- `worker done` present but no `finish:` line → the UI-thread hand-off failed
  (the `QTimer.singleShot` regression — Bug 2).
- `finish:` shows `series=0` for studies → enrichment failed to fetch series.
- `add_downloads call completed` but queue still empty → `add_downloads`
  rejected the studies (no series, duplicates, or rule-engine validation).
