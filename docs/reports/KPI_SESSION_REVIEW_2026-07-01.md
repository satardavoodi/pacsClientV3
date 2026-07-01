# AI-PACS Live Log / KPI Performance Review — 2026-07-01

**Type:** Live-log / KPI review (read-only; no code changed).
**Method:** AI-PACS Conference Loop (Person A → B → C → Final), grounded in today's live logs.
**Reviewer output status:** Findings + recommended plan. The plan is **not yet implemented** — it is
recorded here for approval/scheduling.

---

## 1. Evidence base

Single live session captured in today's rotated logs under `user_data/logs/`:

- `viewer_diagnostics.log` — 5,211 lines, span **2026-07-01 13:31:52.274721 → 13:51:53.470346** (~20 min).
- `download_diagnostics.log`, `db_diagnostics.log`, `app.log` (today's rotation; `app.log.1` rolled 12:08).

Session workload: normal **2D FAST** viewing — series `6` and a multi-study offset-key series `1100000`.
**No Dental Imaging or MPR markers were emitted today** → this is a *whole-viewer* profile, not a
Dental-specific one.

Expected standards used for comparison are the repo's own targets:
`docs/performance/FAST_VIEWER_KPI_CATALOG.md` and `docs/plans/performance/CURRENT_KPIS_v2.3.6.md`.

> Note on log levels: `download_diagnostics.log` uses **WARNING as its telemetry level** (17,014 of 17,137
> lines) — the `_emit` / `log_stage_timing` / `download_series` records are structured KPI telemetry, **not
> faults**. The genuine faults are `ERROR=92` (mostly dated 2026-06-30) + 3 tracebacks in the download/socket
> network layer — see §6.

---

## 2. KPI panel — measured vs. expected

| KPI | Source marker | Today p50 / p95 / max | Target | Verdict |
|---|---|---|---|---|
| DICOM decode | `[KPI] ttd_ms` / `decode_ms` | 4.5 / 9.4 / 12.0 ms | (low) | ✅ excellent |
| First image visible | `[KPI] TTFI total_ms` | 18.8 / 93.2 / 114.4 ms | <80 ms | ✅ p50 great; p95 slightly over on offset-key switch |
| Render (frame) | `FAST_SET_SLICE_STAGE frame_ms` | 16.1 / 28.7 / 39.2 ms | (low) | ✅ ~1 frame |
| Cached slice display (total) | `FAST_SET_SLICE_STAGE total_ms` | 18.9 / 95.1 / 114.4 ms | <15 ms | ⚠ borderline (frame+WL dominate) |
| Scroll stack | `FAST_QT_SCROLL_STAGE total_ms` | 17.1 ms (n=1) | (low) | ✅ (thin sample) |
| Layout switch → 1st image | `VIEWER_SWITCH total_ms` | 18.8 / 93.2 / 114.4 ms | <80 ms | ✅ mostly |
| **Drag event interval** | `FAST_DRAG_KPI event_p95_ms` | 157.7 / 454.8 / **725.2 ms** | **<120 ms** | ❌ **FAIL (≈3.8× at p95)** |
| **Drag UI lag** | `FAST_DRAG_KPI ui_lag_max_ms` | 216.3 / 943.2 / **1054.6 ms** | **<200 ms** | ❌ **FAIL (median already over)** |
| **Main-thread stalls** | `MAIN_THREAD_STALL stall_duration_ms` | 175.5 / 548.5 / **1421.2 ms** | **0 during interaction** | ❌ **FAIL — 63 freezes >100 ms in 20 min** |
| DB stage timing | `db_diagnostics duration` | 1.62 / 287.6 / 561.1 (max 1691) ms | read<10 / write<50 | ⚠ tail is echoed stage-timing, not pure SQL (see §4) |
| Disk write batch | `dicom_file_write_batch duration_ms` | 65.7 / 385.5 / **1736.2 ms** | (low) | ⚠ off-GUI (download subprocess) |
| Process RSS | `rss_mb` | ~930 MB | bounded | ✅ no spike / OOM |
| CPU / GPU | — | **not sampled in live logs** | — | ⛔ instrumentation gap |

**Drag internals (why the FAIL is not a rendering problem):** during the laggy drags the *handler* is fast
(`handler_p95 ≈ 5.7–13.4 ms`) and *paint* is fast (`paint_p95 ≈ 1.4 ms`). Input events queue up
(`event_p95` up to 725 ms, `ui_lag_max` up to 1055 ms) because the **main thread is blocked elsewhere**, not
because slice rendering is slow.

**Healthy KPIs (PASS):** decode, first-image, render/frame, scroll, layout-switch. Decode/render are **not**
the bottleneck.

---

## 3. Primary bottleneck — main-thread blocking on the download-status / manifest-scan path

`MAIN_THREAD_STALL` fired **63 times >100 ms** in ~20 min (p95 548 ms, **max 1421 ms**; 22 ≥250 ms, 5 ≥500 ms,
2 ≥1000 ms). Breakdown by state: `fast_drag_inactive` n=51 (max 1421, p95 693), `switch_complete` n=8 (max
365), `fast_drag_active` n=4 (max 116).

`MAIN_THREAD_STALL_TRACE` top-of-stack frames (the actual freeze locations) cluster on the
**download-status refresh + synchronous filesystem manifest scan**, executed on the GUI thread:

| Responsible function | Location |
|---|---|
| `refresh_download_statuses` | `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:2948` |
| `_check_study_download_status` | `patient_table_widget.py:2910` |
| `update_study_download_status` | `patient_table_widget.py:2868` |
| `check_study_complete` | `PacsClient/pacs/patient_tab/utils/utils.py:1409` |
| `build_local_manifest` → `Path.iterdir()` | `modules/storage/sync_manifest.py:239` (disk walk on GUI thread) |
| `_run_deferred_close_gc` (GC pause) | `PacsClient/.../patient_widget_core/_pw_lifecycle.py:37` |

(The trace line numbers land a few lines *inside* each function — e.g. `refresh_download_statuses`@2984,
`build_local_manifest`@275 — consistent with the `def` sites above.)

**Correlation confirms it:** 13 of 63 stalls sit next to a `TABLE_REFRESH` event (worst
`TABLE_REFRESH#1630@687.4 ms`, `#1249@539.8 ms`), 6 next to `viewer_switch`, 4 next to `fast_drag`. Worst two
stalls (1421 ms, 1251 ms) had no nearest-event attribution.

**Classification:** UI-thread blocking caused by **synchronous disk I/O (directory/manifest scan) + per-study
DB status checks during the DM / patient-table refresh**. This directly violates the KPI catalog targets
`main_thread_disk_scan_ms_during_fast_drag = 0` and `main_thread_blocking_io_ms = 0 during interaction`.

**Scope — whole viewer, not Dental:** the offending code is in the **home / patient-table + storage layer**,
shared by all viewer usage regardless of modality. It would *compound* in Dental/MPR sessions (which add their
own known open-freeze, e.g. `MPR_OPEN_FREEZE_OPTIMIZATION_PLAN_2026-06-27.md`) but is not caused by them.

---

## 4. Secondary findings

- **Disk write batch spikes to 1.7 s** (`dicom_file_write_batch` max 1736 ms, p95 385 ms) but runs in the
  **download subprocess** (`role=download-subprocess`) — it delays download completion, not GUI smoothness.
- **DB tail is misleading:** the `db_diagnostics` "max 1691 ms" belongs to `series_downloader.log_stage_timing`
  (n=1035) — i.e. the **timing logger echoing download stage durations**, not a SQL query. Real pool timing
  (`database._pool.log_stage_timing`, n=352) is p95 17.6 ms. A future analyzer must split these or it will
  report false DB slowness.
- **~13 MB single log record** was present in `viewer_diagnostics.log` while scanning. Because the file was
  live-rotating I could **not** definitively re-identify its emitter → **low confidence**, but a multi-MB
  single log write is itself a main-thread hazard worth a defensive size cap.
- **No CPU/GPU sampling** exists in the live logs (the `CURRENT_KPIS` resource table was collected out-of-band).
- **RSS ~930 MB**, stable — no memory spike or OOM evidence this session.

---

## 5. Recommended plan (Conference Loop — Final)

The runtime instrumentation is already comprehensive (stall probe with stack traces, `[KPI] TTFI`,
`[FAST_DRAG_KPI]`, `[UX_FIRST_IMAGE_VISIBLE]`, `[VIEWER_SWITCH]`, `[FAST_SET_SLICE_STAGE]`, download
`stage-timing`, `db_diagnostics`). The gap is **synthesis**, not collection. Analyzers already exist but are
fragmented: `tools/performance/stall_correlation_report.py`, `parse_ab_logs.py`,
`clearcanvas_aipacs_kpi_harness.py`, and ~8 `tools/dev/_analyze_*.py` scratch scripts.

**Ship (offline, read-only, zero clinical risk):** one consolidated report generator
`tools/performance/kpi_session_report.py` that parses today's four logs, computes the p50/p95/max panel,
compares each metric to a single thresholds table (`tools/performance/kpi_targets.py`, sourced from the KPI
catalog), runs the stall→nearest-event correlation (**reusing** `stall_correlation_report.py` helpers, not
duplicating them), and writes `docs/reports/KPI_SESSION_REVIEW_<date>.md` + a sibling `.json`. Guard test in
`tests/code/performance/` against a fixture log; expose via a VS Code task + `/kpi-review` prompt.

Hardening required (from Person B): byte-length guard + streaming reads (real logs contain 13 MB / 13 k-char
lines); rotation-aware "today" selection (`app.log` + `app.log.1`); split true-DB vs echoed stage timings;
thresholds single-source with catalog provenance; **never open the live `dicom.db`** (read only the log files).

**Follow-up tickets (separate passes, not part of the reporter):**

- **T1 — root-cause fix (the actual stall):** move `build_local_manifest` / download-status refresh off the
  GUI thread (worker or cached snapshot), so `refresh_download_statuses` / `check_study_complete` no longer do
  synchronous `iterdir` during interaction. Guarded subsystem (patient-table + storage) → run via
  `aipacs-root-cause-fix` with a flag-gated, default-on change and a guard test. **Do not** ride this along
  with the reporter.
- **T2 — instrumentation gaps:** add CPU/GPU sampling to the KPI stream; add a defensive log-record size cap
  once the 13 MB emitter is confirmed on a non-rotating capture.

**What must NOT change (restated):** FAST viewer must never instantiate VTK render windows; no removal of
metadata/overlays/measurements/sync/reference-lines/sidebars/patient-workflows; cross-patient study isolation
and multi-study vs. single-study gating intact; never write to the live `dicom.db`; Fast/Advanced/VTK domain
separation preserved.

---

## 6. Appendix — reproduce this review

Log-driven KPI extraction was performed with ad-hoc Python over the current-day rotation. Key aggregations:

- **Stalls:** `[MAIN_THREAD_STALL]` → `stall_duration_ms`, grouped by `active_viewer_state`, counted against
  `nearest_*` correlation fields.
- **TTFI / render:** `[KPI] kind=TTFI` (`ttd_ms`, `ttr_ms`, `total_ms`), `[FAST_SET_SLICE_STAGE]`
  (`decode_ms`, `wl_ms`, `frame_ms`, `display_ms`), `[VIEWER_SWITCH] phase=first_image_visible`.
- **Drag:** `[FAST_DRAG_KPI]` (`event_p95_ms`, `ui_lag_max_ms`, `handler_p95_ms`, `paint_p95_ms`,
  `background_decode_count`).
- **DB:** `db_diagnostics.log` `duration` grouped by `fn=` (separate `log_stage_timing` echoes from real pool).
- **Download:** `download_diagnostics.log` `stage-timing duration_ms` grouped by `stage=`.

Faults observed (for separate triage, not the responsiveness bottleneck): `download_diagnostics.log`
`ERROR=92` + 3 tracebacks in `modules.network.socket_client.send_request` / `get_report_status` /
`series_downloader.download_all_series` (mostly 2026-06-30; a handful today) — download/socket network layer.

**Worst-case samples (today):** stall 1421.2 ms (state `fast_drag_inactive`); drag `ui_lag_max` 1054.6 ms;
drag `event_p95` 725.2 ms; TTFI `total` 114.4 ms; `dicom_file_write_batch` 1736.2 ms.
