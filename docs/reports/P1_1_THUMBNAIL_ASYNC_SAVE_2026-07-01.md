# P1.1 — Off-GUI-thread thumbnail disk write (2026-07-01)

Phase 1.1 of `docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md`. First stability
fix for the measured main-thread blocking. **Flag-gated, default-on, byte-identical kill switch.**
Implemented + offscreen-verified; **NEEDS live source-build verification** (checklist below).

## Root cause

Both live-log reviews put `save_thumbnail` / `save_thumbnail_with_bytes` in the main-thread stall
traces. `_hp_series.save_thumbnail` (socket-fetch path) loops over every series and, for each,
base64-decodes the payload and calls `save_thumbnail_with_bytes` → `mkdir` + `open().write()` — a
synchronous disk write on the GUI thread. On a study with many series (and under antivirus/slow-disk
latency) this blocks the event loop.

## Change (minimal, reversible)

- `PacsClient/pacs/patient_tab/utils/utils.py`: new `save_thumbnail_with_bytes_async(...)` +
  `canonical_thumbnail_path(...)` + a lazily-created single-worker `ThreadPoolExecutor`
  (`thumb-write`). The async writer returns the **canonical path immediately** and performs the
  mkdir+write on the worker via the **same** `save_thumbnail_with_bytes` (no duplicated write logic).
  Flag `AIPACS_THUMB_SAVE_ASYNC` (default on); `=0` delegates straight to the synchronous writer
  (byte-identical). Any dispatch failure also falls back to a synchronous write, so a thumbnail is
  never silently dropped.
- `PacsClient/pacs/patient_tab/utils/__init__.py`: export `save_thumbnail_with_bytes_async`.
- `_hp_series.py`: the one hot call site now uses `save_thumbnail_with_bytes_async(...)`. The base64
  **decode stays on the main thread** (microseconds; it decides whether a file_path is set — semantics
  unchanged); only the disk I/O is offloaded.

## Why it is safe (invariants preserved)

- **Canonical path unchanged.** `canonical_thumbnail_path` and the sync writer both build
  `THUMBNAIL_PATH/<study_uid>/<series>.png` — one definition, pinned by the guard test.
- **Return contract preserved.** The caller still receives the dict with `file_path` set to the exact
  path the file will occupy; `save_series_info_to_database` uses dict fields, not file existence.
- **Display gap covered.** The right-panel consumer reads "canonical PNG → base64 fallback" and the
  base64 stays in the dict, so a millisecond-late write shows the base64 in the interim.
- **Reuse, not fork.** The actual write is the unchanged `save_thumbnail_with_bytes`; the other callers
  of it (`_pw_thumbnails`, `_pw_previous_exams`) are untouched.
- **Kill switch.** `AIPACS_THUMB_SAVE_ASYNC=0` restores the exact prior synchronous behavior.
- **No clinical-image risk.** Thumbnails are regenerable; a dropped write on hard-exit is re-fetched
  on next open. No DICOM/`dicom.db` path touched. FAST viewer untouched (no VTK).

## Verification done (offscreen)

- All three edited files `py_compile` clean.
- Guard test `tests/code/ui_services/test_thumbnail_async_save.py`: **5 source-pins pass**, behavioral
  test skipped (PySide6 absent in sandbox — runs on the Windows lane).
- Behavioral design proven with a faithful copy: async returns the canonical path immediately, the
  file lands after the worker flush, the kill switch writes synchronously, path parity holds.

## Live-verify checklist (source build — human-assisted)

1. Launch the source build; open several patients (MRI, yesterday / two days ago). **Thumbnails must
   still appear** in the right panel (single-study, multi-study, and previous-exam patients).
2. Confirm PNGs land on disk at `user_data/patients/thumbnails/<study_uid>/<series>.png` shortly after
   a patient is clicked.
3. Run the KPI analyzer before/after over the fresh run:
   `.venv\Scripts\python.exe tools\performance\kpi_session_report.py --print`
   Expect: `save_thumbnail` / `save_thumbnail_with_bytes` **no longer in the stall traces**, fewer
   patient-open stalls, lower `table_refresh` correlation. Decode/TTFI unchanged.
4. Regression sweep: patient switching, drag-drop, and the download-status border still work.
5. Kill-switch sanity: set `AIPACS_THUMB_SAVE_ASYNC=0`, relaunch → behavior identical to before P1.1.

## Not included (separate Phase-1 tickets)

- **P1.2** DM status refresh + `build_local_manifest` off-thread.
- **P1.3** `_render_multistudy_grouped` deferred rebuild.
- **P1.4** startup `add_AIPacs_tab` (2.4 s, EchoMind registry init).

Fold a one-line as-built note into `CLAUDE.md` (thumbnail-pipeline section) and
`docs/pipelines/thumbnail-pipeline.md` §2 producers once live-verified.

## Live-verify result (source build, pid 193028, 2026-07-01 15:49–15:53)

- **`save_thumbnail` / `save_thumbnail_with_bytes` are GONE from the main-thread stall traces**
  (0 occurrences), vs the pre-P1.1 fresh run where they were top freeze frames (7× + 7×).
- **No `async thumbnail write failed` errors** in any log; thumbnails still active (44
  `FAST-THUMB-STATE` events in the run) — no visual regression reported.
- Latest-run stall summary: count=54, p50=159, p95=469, **max=2804 ms**, 16 `table_refresh`-correlated.
  The remaining stalls are now dominated by `notify` / tab-switch (`set_tab_active`/`on_tab_changed`) /
  `_on_patient_double_clicked_async` / `_open_main_window` and the `table_refresh` path — i.e. the
  **P1.2/P1.3/P1.4 offenders**, not thumbnail save.
- **Verdict:** P1.1 is safe and its target frame is eliminated; overall responsiveness still needs
  P1.2 (DM status-refresh / `build_local_manifest`) which owns the 16 `table_refresh` stalls.
  (Caveat: workloads differ per run, so this is a consistency check, not a controlled A/B.)
