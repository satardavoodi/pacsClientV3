# P1.2 — Cooperative chunking of the download-status refresh (2026-07-01)

Phase 1.2 of `docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md`.
**Flag-gated, default-on, byte-identical kill switch.** Implemented + offscreen-verified;
**NEEDS live source-build verification** (checklist below).

## Root cause + evidence note

`patient_table_widget.refresh_download_statuses` clears the status cache then loops over every
visible study calling `update_study_download_status` → `_check_study_download_status` →
`check_study_complete` → `build_local_manifest` (a per-study **disk walk**), all in one synchronous
GUI-thread loop. For N studies that is N disk scans back-to-back → a main-thread freeze.

Log evidence (recent runs): this path is **workload-variable** — it appeared in the stall traces of
run 191348 (`refresh_download_statuses`×4, `build_local_manifest`×4) but not in the two most recent
runs (it only fires when the refresh/status path is exercised). It is a real latent GUI-thread
disk-scan hazard; the more *consistent* freezes (startup `add_AIPacs_tab`, patient-open/tab-switch)
are separate, Qt-main-thread-bound tickets (P1.3/P1.4). This fix removes the latent hazard with the
lowest-risk technique available.

## Change (minimal, reversible, no threads)

`refresh_download_statuses`: when `AIPACS_STATUS_REFRESH_CHUNKED` is on (default), the per-row
synchronous loop is replaced by `_refresh_statuses_chunked(study_uids, 0, token)` — it processes the
studies in small chunks (`AIPACS_STATUS_REFRESH_CHUNK`, default 2) and re-schedules itself with
`QTimer.singleShot(0, …)` between chunks, so the event loop breathes between studies. A
per-refresh `_status_refresh_token` cancels a stale chain if a newer refresh supersedes it. `=0`
restores the byte-identical synchronous loop.

## Why it is safe

- **Everything stays on the main thread.** No worker threads and no cross-thread access to
  `_download_status_cache` — only the *scheduling* of the existing per-study updates changes. So
  there are no new race conditions.
- **Same work, same results.** Each study still goes through the unchanged
  `update_study_download_status` → `check_study_complete`; cross-patient isolation and the
  complete/partial/not_downloaded semantics are untouched. Statuses now appear progressively
  (row-by-row) instead of all-at-once.
- **Report refresh unchanged.** The report-column re-pull (`reportRefreshRequested.emit()`) still
  fires; it never depended on the disk-scan loop completing.
- **`refresh_download_statuses_local_only` is untouched** (rare post-storage-clear path; returns a
  synchronous count its callers may rely on).
- **Kill switch:** `AIPACS_STATUS_REFRESH_CHUNKED=0` → exact prior behavior.

## Verification done (offscreen)

- `patient_table_widget.py` `py_compile` clean.
- Guard test `tests/code/ui_services/test_status_refresh_chunked.py`: **5 passed** (source-pins +
  mirror-behavioral). The mirror proves the driver processes every study exactly once, in order,
  honors the chunk size, and cancels a stale chain on token-supersede.

## Live-verify checklist (source build — human-assisted)

1. Launch the source build, load a patient list with several studies.
2. **Click the Refresh button** in the patient list (this is what triggers
   `refresh_download_statuses`). The download-status badges should update **without a visible
   freeze**; badges may fill in progressively row-by-row (expected).
3. Confirm the badges are correct (green = complete, partial, not-downloaded) — same as before.
4. Run the KPI analyzer over the fresh run:
   `.venv\Scripts\python.exe tools\performance\kpi_session_report.py --print`
   Expect: `refresh_download_statuses` / `build_local_manifest` **absent from stall traces** even
   after clicking refresh; no new stalls introduced.
5. Kill-switch sanity: set `AIPACS_STATUS_REFRESH_CHUNKED=0`, relaunch, click refresh → the old
   (single-freeze) behavior returns.

## Not included (separate Phase-1 tickets)

- **P1.3** patient-open thumbnail sidebar (`_pw_thumbnails` → `_pw_panels`, ~723 ms on open).
- **P1.4** startup `add_AIPacs_tab` (~1.4 s) + theme application (~2.5 s).
