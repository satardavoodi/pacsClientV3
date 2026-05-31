# AI-PACS Reliability / Soak Audit — 2026-05-31

Scope: reliability, stability and performance of the **repeated session workflow**
(click patient → download → open → view → annotate/measure → close → repeat) and
**long-running sessions**. Method: static audit of all major subsystems (four parallel
code audits), analysis of existing `user_data/logs/`, a set of safe code fixes, and two
new soak-test tools. This document is the as-built record; pair it with the existing
`docs/architecture/FREEZE_BOTTLENECK_ANALYSIS.md`, root `CRASH_ANALYSIS_2026-05-25.md`,
and `docs/development/NEXT_AGENT_DO_NOT_REPEAT.md`.

> **Verification caveat.** This pass ran in a sandbox whose network mount served *stale,
> truncated copies* of two freshly-edited files, so `py_compile` could not be trusted for
> them. `main.py` and `database/_pool.py` compiled clean; `widget.py` and `_vc_warmup.py`
> were verified valid by direct file read. **Full `pytest` + GUI soak must be run on the
> Windows venv** (commands in §7). All edits are additive/reversible.

---

## 1. Executive summary

The workstation is functionally healthy, but two **systemic reliability defects** dominate
long, repeated use — both already suspected, now **quantified from the current source build's
own logs**:

1. **Monotonic memory leak + thread leak across the open/view/close loop.** Process RSS
   never returns to baseline between patients/series; thread count climbs steadily. Worst
   observed session: **RSS 322 MB → 936 MB and threads 32 → 128 over ~11.7 h**; another
   reached **~1.46 GB**. Across 66 main-app sessions in the logs, **31 show >200 MB net RSS
   growth** and **15 show >20-thread growth**. This is the "slows down / auto-closes after a
   while with heavy images" symptom.

2. **Silent native fail-fast (`0xC0000409`, Qt6Core.dll)** during FAST-viewer
   series-switch / stack-drag / tab-teardown. This is a **GIL-released C-level data race**
   in the `pydicom_2d` backend (render vs. worker volume-slice writes) — see
   `NEXT_AGENT_DO_NOT_REPEAT.md`; Python locks/keepalive/render-gates were tried and failed.
   The memory leak is a *stressor* that shortens time-to-crash.

Supporting log evidence:

| Signal | Source | Count / value |
|---|---|---|
| `0x8001010d` (RPC_E_WRONGTHREAD, COM call from wrong thread) | `native_fault.log` | **40+** recurring entries |
| `wrapped C/C++ object … deleted` (PySide6 use-after-delete) | `app.log.1` | 1 confirmed |
| `database is locked` | `db_diagnostics.log` | **0** (DB backoff healthy in practice) |
| Abrupt terminations (SESSION_START w/o SESSION_END) | all logs | **6** |

A major contributing cause of the leak is now pinpointed: **every patient tab connects ~10
child widgets to the application-lifetime singleton `ThemeManager.themeChanged` signal and
never disconnects on close**, so each closed tab leaves ~10 live slots pinning its entire
widget/viewer object graph. Per-tab thread pools and a parentless timer add to it.

---

## 2. What was fixed this session (safe, additive, reversible)

All five are behaviour-neutral and isolated; none touch the FAST render hot path, the
download protocol, the DB schema, or any clinical feature.

| # | File:line | Change | Why | Risk |
|---|---|---|---|---|
| 1 | `main.py` (after `sys.excepthook=` ) | Install **`threading.excepthook`** → logs to `aipacs.crash` | Background-thread exceptions currently **vanish silently** (no log), leaving inflight flags stuck → "function stops working". This surfaces them. | none (pure logging) |
| 2 | `main.py` (same block) | Install **`qInstallMessageHandler`** → routes Qt C++ messages to `aipacs.qt` | Captures Qt-side `"QObject::~QObject: Timers cannot be stopped from another thread"` / `"object already deleted"` — early warning of the lifetime faults suspected in the fail-fast. | none (logs only) |
| 3 | `database/_pool.py:269` | Cap connect-retry backoff: `min((2**attempt)+rand, 10.0)` | `2**14 ≈ 4.5 h` sleep was possible on a locked DB; `busy_timeout=120 s` already handles real lock waits. Prevents an indefinite freeze. | very low (only bounds a sleep) |
| 4 | `patient_widget_core/widget.py:335` | `QTimer()` → **`QTimer(self)`** for `_priority_display_timer` | Parentless 500 ms timer keeps firing into a half-torn-down widget if the exit path is skipped (tab-bar close) — a QObject-lifetime hazard + retention. Parenting guarantees stop/delete with the widget. | very low (standard Qt) |
| 5 | `_vc_warmup.py` `clear_all_caches_for_close()` | **Shut down `_header_fill_executor`** on tab close | Per-tab single-thread pool was never shut down; its worker holds a closure referencing the controller → one leaked thread per patient opened (a direct contributor to the 32→128 thread growth). | low (additive cleanup) |

Rollback: `git checkout HEAD -- main.py database/_pool.py PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py`

### 2b. Continuation — applied + verified live on the Windows venv (2026-05-31)

After the audit, more fixes were applied and verified directly on the user's machine (compile +
guards run via the local MCP on the real `.venv` Python 3.13.5, bypassing the sandbox stale-mount):

- **P5** — DB pool dead-thread eviction (`database/_pool.py`).
- **P2** — per-series `ThreadPoolExecutor` shut down in `_pw_series.py::_load_and_display_series_async` (`finally: executor.shutdown(wait=False)`).
- **P3** — `_vc_switch.py::_schedule_async_load_and_switch._worker` now wraps the `_queue_on_ui_thread(_finish_on_ui)` marshal in try/except that clears the inflight guards on failure (stops a viewport going permanently dead).
- **P1 (3 of 10 sites)** — `themeChanged` disconnect added to existing teardown methods: viewer-controller (`_vc_warmup.clear_all_caches_for_close`), patient-widget-core (`_pw_lifecycle.closeEvent`), thumbnail-manager (`thumbnail_manager.cleanup`).

**Verification:** `py_compile` of all 8 edited files → `ALL_OK`; guard suites pass —
`tests/code/database` + `test_diagnostic_logging_catchall` = **8 passed/0 failed**, and
`test_2026_05_27_regression_guards` (incl. `change_series` signature) + `tests/code/database` =
**16 passed/0 failed**.

**Live soak baseline** (sampler attached to the running app, PID 666096, while the user drove ~6
open/view/close cycles): RSS **405.9 → 601 MB (+195, +48%)**, threads **44 → 88 (peak 91)**,
handles **1964 → 2172**; none recovered after the cycles stopped (flat at 601 MB for 45 s) —
the leak reproduced live. No crash, no new `native_fault.log` entry during the cycles.

**Also applied + verified (wave 2, 2026-05-31):** P4 (task-reconstruct off the UI thread),
P6 (apply-error elevated to WARNING), P7 (auto-retry exponential capped backoff), P9 (VoiceWidget
`removeEventFilter` + signal disconnect + stream release on close), P12 (HomePanel pool capped at 4),
P13 (startup sweep of stale `aipacs_lazy_*.bin` temp files), P14 (non-blocking DM close with a
fallback guard), P15 (log-rotation size floor), and P1 at a 4th site (`thumbnail_panel.cleanup_timers`).
Full re-verify on the venv: 15 edited files `py_compile` → **ALL_OK**; guards
`test_2026_05_27_regression_guards` + `tests/code/database` + `test_diagnostic_logging_catchall`
= **23 passed / 0 failed**.

**Deliberately deferred — need runtime verification, do NOT apply blind:**
- **P1 at the remaining 6 widget sites** (`header_widget`, `reception_panel_widget`,
  `toolbar_manager`, `patient_tab_widget`, `sidebar_widget`, `service_tab_widget`) — these are
  QWidget children of the patient tab, so Qt should auto-disconnect their `themeChanged` slots when
  the tab's C++ object is destroyed. Confirm via the post-restart re-soak whether the
  controller/manager-level disconnects already applied suffice before editing 6 more files.
- **P10** (PyDicom2DBackend `_executor`) — shut down only in the backend's real teardown, NOT
  `close_series` (which runs on every series-switch); locate that teardown first.
- **P11** (socket per-batch wall-clock deadline) — needs a slow/half-open-server test to tune and
  verify; exact diff is in the patchset.
- **P-misc** (`_mask_actors`, `_series_download_completed` clears) — low value.

**Next step to confirm the fixes work:** restart the app from VS Code (loads all applied fixes —
the diagnostic hooks and teardown fixes only take effect on a fresh process), then re-run the same
soak (`tools/reliability/process_soak_sampler.py`) over S1/S2 and compare against the baseline
above. Expectation: RSS/threads return near baseline after each close.

---

## 3. Findings by subsystem

Severity: **Critical / High / Med / Low**. Confidence: **High / Med / Low**. Line numbers
marked *(reported)* came from the static audit and should be re-confirmed against the live
tree before editing; the leak/crash conclusions are corroborated by the log evidence in §1.

### 3.1 Memory / resource cleanup across the loop  *(the leak)*

- **R-1 [Critical/High] ThemeManager singleton never disconnected on tab close.** ~10 connect
  sites — `thumbnail_manager.py:696`, `header_widget.py:63`, `reception_panel_widget.py:64`,
  `patient_widget_viewer_controller.py:202`, `toolbar_manager.py:757`, `patient_tab_widget.py:56`,
  `patient_widget_core/widget.py:350`, `thumbnail_panel.py:69`, `sidebar_widget.py:79`,
  `service_tab_widget.py:40` — none disconnect. Each closed tab leaves live slots on the
  app-lifetime singleton, pinning the whole tab graph. **Primary leak driver.** → Proposal P1.
- **R-2 [High] Per-call `ThreadPoolExecutor` in `_load_and_display_series_async`** —
  `patient_widget_core/_pw_series.py:597-598` *(reported)*: a new pool per series load, never
  shut down. → P2.
- **R-3 [High] `_header_fill_executor` never shut down** — **FIXED (§2 #5).**
- **R-4 [Med] `PyDicom2DBackend._executor` survives `close_series()`** —
  `modules/viewer/fast/pydicom_2d_backend.py:122` *(reported)*. → P10.
- **R-5 [Med] Parentless `_priority_display_timer`** — **FIXED (§2 #4).**
- **R-6 [High] `dict_tabs_widget` retains the PatientWidget** if the tab is closed via the
  tab-bar button before `exit_patient_widget` runs — `home_panel/widget.py:158` *(reported)*. → P8.
- **R-7 [Med] `_series_download_completed` "never cleared within controller lifetime"** —
  `patient_widget_viewer_controller.py:372` *(reported)*: grows across opens if the controller
  is reused; can suppress progressive display on re-open. → P-misc.
- **R-8 [Low-Med] `_mask_actors` appended per AI-tool result, never cleared** —
  `_pw_lifecycle.py:552` *(reported)*. → P-misc.

### 3.2 Background threads / processes

- **T-1 [High] DB connection pool keyed by `thread.ident` with no dead-thread eviction** —
  `database/_pool.py:50,217` *(reported)*: short-lived daemon threads (per open/enrich/load)
  leave pooled `sqlite3` connections (FDs + WAL read locks) behind. Contributes to thread/FD
  growth over long sessions. → P5.
- **T-2 [Med] HomePanel `ThreadPoolExecutor()` with default (unbounded) max_workers** —
  `home_panel/widget.py:201` *(reported)*: up to `min(32, cpu+4)` workers; rapid list cycling
  can spike concurrent DB queries against the download subprocess. → P12.
- **T-3 [Low] DM `worker_pool.stop_all()` (blocking `wait`) on widget close** —
  `download_manager/.../widget.py:449` *(reported)*: up to ~6 s blocking on close. → P14.

### 3.3 Download pipeline + freeze paths

Re-verification of the three historical freeze paths (`FREEZE_BOTTLENECK_ANALYSIS.md`):

| Path | Status |
|---|---|
| **F1** `worker.wait(5000)` on retry/pause | **Fixed** for the workflow (`cancel_all_non_blocking`); residual ~6 s only on widget *close* (T-3). |
| **F2** `shutil.rmtree` on main thread | **Fixed** — offloaded to a daemon thread + `QTimer.singleShot(0)` marshal. |
| **F3** sync metadata fetch on main thread | **STILL PRESENT** — `_reconstruct_task_from_database` → `fetch_study_metadata_sync` (`_dm_workers.py:59,184` *(reported)*), up to ~16 s UI block when a task isn't in memory. → **P4 (High).** |

- **D-1 [Med] No per-batch wall-clock deadline on socket `recv`** — `socket_client.py:225,921`
  *(reported)*: a server that stalls mid-batch can produce ~90 s of retrying before clean
  failure. → P11.
- **D-2 [Med] Multiplicative retry (≈3×3×3) with no circuit-breaker; `_check_auto_retry`
  re-queues FAILED instantly** — `_dm_workers.py:825,840` *(reported)*: a persistently failing
  server causes ~1 Hz worker respawn churn. → P7.
- Atomic `*.part` → `os.replace()` writes and socket-port resolution (50052, not DICOM 105):
  **confirmed correct.**

### 3.4 Error handling / recovery

- **E-1 [High] `threading.excepthook` was missing** — **FIXED (§2 #1).** Was the reason
  background-worker crashes were invisible.
- **E-2 [High] `_worker` in `_schedule_async_load_and_switch` has no top-level `try/finally`** —
  `_vc_switch.py:583-759` *(reported)*: if the worker raises before the UI-finish callback,
  `_async_switch_inflight` / `_interactive_load_in_progress` stay set and **every later series
  switch to that viewport is silently swallowed** for the rest of the session — a textbook
  "stops working after repeated use". → **P3 (High).**
- **E-3 [High] `_apply_loaded_series_data` swallows exceptions at DEBUG; spinner never hidden** —
  `_vc_load.py:799` *(reported)*: a stuck "loading" viewport after any apply-phase error. → P6.
- **E-4 [Med] Qt message handler was missing** — **FIXED (§2 #2).**

### 3.5 Database / disk / libraries

- **DB:** WAL + `busy_timeout=120 s` + retry: sound. Cursors not explicitly closed but the
  `get_db_connection()` rollback-on-return mitigates (Med). Backoff cap **FIXED (§2 #3)**.
  Dead-thread eviction outstanding (T-1/P5).
- **Disk:** `cleanup_stale_tmpfiles()` (`pydicom_lazy_volume.py:45`) is **only called from
  tests** — `aipacs_lazy_*.bin` mmap temp files are not swept in production; on a fail-fast they
  leak across sessions. → P13. Log rotation: 20 MB × 3 per file, fine; add a floor so a bad
  env value can't disable it (P15). Stitching temp dirs leak if closed without explicit cleanup
  (Med).
- **Libraries:** FAST/`pydicom_2d` path confirmed to instantiate **no `vtkRenderWindow`**
  (invariant holds; `vtkRenderWindow` only in the Advanced backend). `np.memmap` backing store
  is intentionally kept alive via `vtk_image_data._numpy_backing_store` — correct, but ties temp
  cleanup to GC (see Disk).

---

## 4. Prioritized proposals (NOT yet applied — need GUI/soak verification)

Apply on the Windows source build with the human-assisted workflow, then soak-test (§6) and
run the guard suite (§7). Ordered by reliability value.

1. **P1 [Critical] Disconnect `themeChanged` on tab close (the leak).** In each of the 10
   widgets in R-1, disconnect its `_on_theme_changed` slot in the widget's close/cleanup
   (wrap in `try/except (RuntimeError, TypeError)` — idempotent). Recommended: add a tiny
   `_disconnect_theme()` helper per widget and call it from the existing teardown. Verify with
   the soak sampler (§6): per-cycle RSS growth should drop sharply.
2. **P2 [High] Class-level header/series executors.** Replace the per-call
   `ThreadPoolExecutor(max_workers=1)` in `_pw_series.py:597` with one shared `self._series_executor`
   shut down in `clear_all_caches_for_close()` (mirror §2 #5).
3. **P3 [High] Wrap `_worker` (`_vc_switch.py:583`) in `try/finally`** that always marshals a
   cleanup clearing `_async_switch_inflight` + `_interactive_load_in_progress`. Flag-cleanup
   only — does **not** add locks to the render race.
4. **P4 [High] Move `_reconstruct_task_from_database` off the main thread** (F3). Simplest:
   in `_start_download_worker`, if the task is absent return early and let the existing
   background retry path reconstruct it.
5. **P5 [High] DB pool dead-thread eviction. — APPLIED 2026-05-31.** Added
   `_evict_dead_thread_connections_locked()` in `database/_pool.py` and an opportunistic call
   inside `_return_to_pool` (when the pool dict exceeds 16 slots) that closes/removes pooled
   connections whose `thread.ident` is no longer in `threading.enumerate()`. Bounds FD/connection
   growth over long sessions. (`py_compile` clean.)
6. **P6 [Med] Hide the spinner in `_apply_loaded_series_data`'s except** (`_vc_load.py:799`)
   and raise the log level to WARNING.
7. **P7 [Med] Back off `_check_auto_retry`** — `QTimer.singleShot(5000 * retry_count, …)`
   before re-queueing a FAILED study.
8. **P8 [Med] Pop `dict_tabs_widget[study_uid]`** in the tab-bar close path before
   `deleteLater()`.
9. **P9 [Med] `removeEventFilter`** for `VoiceWidget` (`voice_tool_ui.py:58-62`) on close
   (dangling C++ filter = fail-fast candidate).
10. **P10 [Med] `PyDicom2DBackend.close_series()` → `self._executor.shutdown(wait=False)`.**
11. **P11 [Med] Per-batch wall-clock deadline** on the socket receive loop.
12. **P12 [Med] Cap HomePanel pool** at `max_workers=4`.
13. **P13 [Low] Startup glob-sweep** of stale `aipacs_lazy_*.bin` (handles fail-fast leftovers
    `cleanup_stale_tmpfiles()` can't), plus call `cleanup_stale_tmpfiles()` at shutdown.
14. **P14 [Low] DM close** → `cancel_all_non_blocking()` instead of `stop_all()`.
15. **P15 [Low] Floor** `AIPACS_LOG_MAX_BYTES` at 1 MB.
16. **P-misc:** clear `_mask_actors` and reset `_series_download_completed` on close.

> **Crash (`0xC0000409`).** Not a "safe fix" — it is a C-level race; mitigations are exhausted
> (`NEXT_AGENT_DO_NOT_REPEAT.md`). The right next step is **diagnostic capture**, now enabled
> by the §2 hooks plus `AIPACS_LOG_SYNC=1` and a WER LocalDumps key (see `CRASH_ANALYSIS_2026-05-25.md`).
> Reducing the leak (P1/P2) will lengthen time-to-crash. Separately, the **`0x8001010d` COM
> wrong-thread** faults (40+ in `native_fault.log`) deserve their own pass — every cross-thread
> COM call (clipboard, shell, OLE drag-drop, TTS/`comtypes`) must be marshalled to the main
> thread (cf. the Eagle-Eye `QTimer.singleShot(0)` mirror fix).

---

## 5. Reliability scenarios (definitions)

Run each as a loop and watch RSS/threads/handles (§6) for **monotonic growth that does not
recover after close** — that is the pass/fail line, not absolute size.

- **S1 — Patient churn:** click → download → open → view (scroll full stack) → close. ×30.
  Pass: RSS returns within ~1.1× of baseline after each close; threads return to baseline ±5.
- **S2 — Series-switch storm:** open a multi-study patient, switch series 50× (drag-drop + sidebar).
  Pass: no permanently-dead viewport (guards against E-2/P3); per-switch RSS delta ≈ 0.
- **S3 — Tools loop:** open → window/level, measure, annotate, MPR/Eagle-Eye → close. ×20.
  Pass: no `0x8001010d` in `native_fault.log`; `_mask_actors`/annotation memory flat.
- **S4 — Download stress:** bulk-enqueue many patients; pause/cancel/retry repeatedly.
  Pass: no worker/thread accumulation; no UI freeze >1 s; no retry hot-loop.
- **S5 — Long idle + resume:** open a heavy patient, leave 1–2 h, resume scrolling.
  Pass: RSS slope ≈ 0 while idle; no crash on resume.
- **S6 — Overnight soak:** S1 repeated for hours. Pass: RSS slope < ~5 MB/h; 0 abrupt
  terminations. (The logs show this currently **fails** — see §1.)

---

## 6. Soak tools (delivered, tested)

Both live in `tools/reliability/` (pure Python; `psutil` already a dependency). They require
**no app changes** and are meant for the human-assisted workflow.

**A. `soak_log_analyzer.py`** — parses `user_data/logs/*.log` (the app already logs
`process_rss_mb` / `thread_count` per series-load and a periodic `resource-summary`) and reports
per main-app session: duration, clean-exit vs abrupt termination, RSS first/last/max + net
growth, thread/subprocess trend, ERROR/CRITICAL counts, and native-fault signatures. Workers are
summarised separately.

```
python tools/reliability/soak_log_analyzer.py                 # scans user_data/logs
python tools/reliability/soak_log_analyzer.py --json soak.json --all
```
Heuristics: memory-leak flag = RSS grew >200 MB to peak over a session with ≥5 samples and ≥10 min;
thread-leak flag = thread_count rose >20; abrupt termination = SESSION_START without SESSION_END.
*(Run today it flags 31/66 sessions leaking and 6 abrupt terminations — see §1.)*

**B. `process_soak_sampler.py`** — attach to the running source build and sample
RSS/threads/handles/children/CPU per interval while you drive a scenario; on exit it prints a
per-cycle growth verdict and writes CSV.

```
# second terminal on Windows, while AI-PACS source build is running:
python tools/reliability/process_soak_sampler.py --name python --csv soak.csv --cycles-from-stdin
#   do one open/view/close cycle, press Enter to mark it, repeat; Ctrl-C to finish
```
Verdict: per-cycle RSS growth > 8 MB/cycle (configurable) ⇒ "LEAK SUSPECTED". Use this to
measure P1/P2 before/after.

---

## 7. Verification status & how to finish it

| File | Syntax check |
|---|---|
| `main.py` | `py_compile` clean |
| `database/_pool.py` | `py_compile` clean |
| `patient_widget_core/widget.py` | valid (direct read; sandbox mount served a stale copy) |
| `_vc_warmup.py` | valid (direct read; sandbox mount served a stale copy) |
| `tools/reliability/*.py` | execute successfully |

Run on the **Windows venv** (per project workflow — do not test the frozen build):

```powershell
.venv\Scripts\python.exe -m py_compile main.py database\_pool.py `
  PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_core\widget.py `
  PacsClient\pacs\patient_tab\ui\patient_ui\_vc_warmup.py
.venv\Scripts\python.exe -m pytest tests\code -q          # headless guard suite
```
Then launch the source build from VS Code and run **S1/S2** (§5) with the soak sampler attached.
Confirm in `user_data\logs\download_diagnostics.log` that thumbnail/patient sockets still behave
(`right_panel_socket_done`), and that no new `native_fault.log` entries appear.

---

## 8. Does the app follow standard reliability practice for repeated-workflow software?

**Strong:** structured async logging with a catch-all handler; `faulthandler`, `sys.excepthook`
and a `QApplication.notify()` override already installed; atomic file writes; WAL + busy_timeout;
documented invariants + regression-guard tests; the freeze paths were correctly diagnosed and
mostly fixed.

**Gaps (now partly closed):** no per-cycle resource teardown discipline — the dominant
anti-pattern for loop-based apps is **acquire-without-release per cycle** (signal connects, thread
pools, timers), which is exactly the leak here; background-thread and Qt-C++ failures were
invisible (now logged); a few hot-path/teardown handlers swallow errors and leave state half-set.

**Top recommendation:** adopt a **per-tab teardown contract** — a single `cleanup()` that every
patient-tab child implements and the close path always calls: disconnect signals, stop+delete
timers, shut down executors, clear caches, drop registry entries. P1–P3 + the §2 fixes are the
first installment; the soak sampler makes the result measurable.
