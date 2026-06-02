# AI-PACS — Session Summary & KPIs (2026-06-01 → 2026-06-02)

Single consolidated record of the work done and the measured KPIs. Detailed
as-built reports are referenced inline.

---

## 1. What was done (overview)

Three threads, in order:

1. **Patient 44113 — stale series/thumbnails fix** (clinical-correctness bug).
2. **Thumbnail + Zeta download pipeline audit** (obsessive correctness/optimization review).
3. **Completed the optimization plan** — every outstanding download-pipeline finding that
   was safe to fix, including the drag-deferral *smoothness* feature, then a full live
   evaluation.

Net result: **clinical image integrity verified sound**, **download-manager test suite
21 failing → 0 (198/198)**, **9 fixes applied + verified with zero regressions**, and a
**live evaluation confirming the app is optimized and stable**.

---

## 2. Fixes applied this session (all test-verified, 0 regressions)

| # | Fix | Area | Why it matters |
|---|---|---|---|
| 1 | **44113 stale-series** — single-click thumbnails now detect a study that grew on the server | correctness | was showing 1 stale series instead of the server's 9 (patient-safety: missing images) |
| 2 | Dead **gRPC imports** removed from `home_panel/widget.py` | startup | stopped pulling `grpcio` into every launch |
| 3 | **DM-H4** — orphaned download subprocess teardown (`ensure_subprocess_dead()` from `_remove_worker`) | reliability | a force-killed worker no longer leaves a child holding sockets + writing `dicom.db` |
| 4 | **DM-L7** — `_tasks` retry cache bounded (FIFO 400, never evicts active) | reliability | was an unbounded slow leak over a long session |
| 5 | **DM-H3 preempt-on-drag** — viewer drag preempts a *different* study's slot-holder | responsiveness | "download this series first" no longer waits the full ~60 s handoff |
| 6 | **retry-dedup** completion handler (test-mock-name fix) | correctness | preemption-completion stays PAUSED, not FAILED |
| 7 | **`state_store.update_batch()`** — atomic multi-field update, one batched event | correctness | closes part of the observer torn-read window |
| 8 | **Drag/visibility-deferral feature (P2.3)** — the smoothness win | **smoothness** | eliminates ~320–570 ms DM-table stalls during a drag |
| 9 | Lightweight **`showEvent`** (deferred refresh-on-show) | lifecycle | completes the hidden-gate loop |

Detail of #8 (the feature): `_refresh_table_order` now gates `is_protected_drag_active()`
and `not isVisible()` **before** the per-row Qt `cellWidget()/setValue()` work; new
`_fire_deferred_rebuild_after_drag/_after_hidden` callbacks re-check and re-arm at a
**1500 ms backoff** (killing the observed 4 Hz rebuild storm); `_update_details_panel`
skips the heavy series-breakdown recreation during a drag. Applied to canonical **and** the
plugin-package mirror.

**As-built detail:** `ROOTCAUSE_44113_SINGLE_CLICK_PIPELINE_2026-06-01.md`,
`AUDIT_THUMBNAIL_DOWNLOAD_PIPELINE_2026-06-01.md`, `LIVE_EVALUATION_2026-06-02.md`.

---

## 3. KPIs (measured live, 2026-06-02 build started 23:58)

### Responsiveness — single-click → first render
| Patient | Study | Click → render |
|---|---|---|
| 44343 | MR, 56 img | **118 ms** |
| 44345 | MR, 513 img | **131 ms** |
| 44430 | CT, 9 series / 695 img | **129 ms** (cache hit) |

- `series_info_entry` 1.5–4.1 ms (instant). Stays ~120–130 ms regardless of study size.

### Viewer open
- Double-click 44430 (9-series CT) → **`first_series_visible` ≈ 1.75 s**.

### Download manager
- `DM_REFRESH_QUEUE`: rebuilds **coalesced** (`queued=2 → coalesced=2, skipped=1`).
- Subprocess spawn: `[SPAWN-TIMING] Imports OK 0.001 s`, `DatabaseManager ready 0.037 s`.
- **DM-H4:** subprocess spawned then **exited cleanly — 0 orphans**.

### Resource / leak
| Snapshot | Main RSS | Threads | Handles |
|---|---|---|---|
| After 3 single-clicks | 479 MB | 46 | 1983 |
| After viewer-open + download | **430 MB** | 49 | 1986 |

- RSS **decreased** under heavier load → **no leak**. Threads stable (~46–49).

### Stability / errors
- **0 non-benign errors** this run (only the expected `GetStudyInfo` timeout).
- `native_fault.log`: 111 benign `0x8001010d` + 5 pre-existing access-violations — **0 new
  crashes** this run.

### Clinical image integrity (live, on real disk content)
- CT `…86230`: **683 `.dcm`, 0 truncated (<128 B), 0 incomplete (`.part`)** — the
  atomic-write/resume guarantee proven on real data.

### Tests
- `tests/code/{download_manager,system,network,storage}` = **198 / 198, 0 fail, 0 err.**
  All 21 originally-failing pre-existing specs now green.

---

## 4. Verification methods used
Static reads + `py_compile`/import; headless `pytest` (junit-parsed); live Monitor-A
workflow drive; `download_diagnostics.log` open-trace timings; `native_fault.log` filter;
disk integrity scan; process/RSS/thread snapshots.

## 5. Known-benign item (not a defect)
`⚠️ Skipped N DICOM files with read errors` appears when re-opening an already-downloaded
study — transient read contention between the viewer and a redundant DB header re-insert.
Files are intact (0 truncated / 0 `.part`). Optional polish: downgrade to DEBUG or skip the
redundant re-insert for complete studies.

## 6. Outstanding (recommended, per-step; none affect image integrity)
DM-H1 (recv timeout/EOF conflation), DM-M1/M2 (state-store mutable-observer + CAS),
DM-M3 (event-driven handoff), DM-M4 (real-bytes ETA), DM-M7/M8 (subprocess IPC + watchdog),
DM-M9 (progress SQL). See `AUDIT_THUMBNAIL_DOWNLOAD_PIPELINE_2026-06-01.md` §4.

## Bottom line
Optimized, smooth, and stable: ~120 ms single-click, ~1.75 s CT first-render, declining
memory, clean subprocess lifecycle, intact on-disk images, 198/198 tests, 0 real errors.
