# AI-PACS — Threading & Subprocess Architecture Review

**Date:** 2026-07-23 · **App:** v3.5.4 (source) · **Machine:** dralizadeh workstation
**Method:** full-codebase concurrency inventory (`user_data/test_reports/2026-07-23/concurrency_inventory.txt`), live process measurement (`live_process_snapshot.json`), today's main-thread stall probes (F8/F11), master-plan KPI history, targeted source reads of every major worker.

---

## 1. Verdict up front

The architecture follows the correct model for a Python/Qt medical workstation, and it is the *right* division of labor:

> **GUI thread** = rendering + input + orchestration (qasync event loop) → **threads** for I/O and GIL-releasing C-extension work → **separate processes** for GIL-bound heavy CPU (pixel decode, downloads, VTK warmup) → **separate applications** for the heaviest subsystems (Slicer MPR, Chromium).

It is largely optimized *by measurement, not by accident* — the OPT-01…OPT-41 series moved every profiled main-thread hotspot off-thread and each move is pinned by guard tests. The residual main-thread work is known, bounded, and tracked (§6). **No unsafe pattern (GUI updates from workers, cross-thread DB sharing, unbounded worker growth) was found. No architectural change is warranted at current measurements** — the remaining wins are specific tracked optimizations, not a redesign.

Live idle measurement (today, app running 3+ hours): main process **68 threads, 531 MB RSS, 0.0 % CPU**; decode subprocess **21 threads, 291 MB, 0.0 %**; **zero orphaned workers** (`strays: []`). Idle CPU 0 % proves the 68 threads are parked pools, not spinners. RSS is inside the KPI registry's warn threshold (1000 MB).

---

## 2. Process map — what runs OUTSIDE the GUI process (and why)

| Process | Workload | Why a process | Caps / lifecycle | Verdict |
|---|---|---|---|---|
| **Decode service** (`modules/viewer/fast/decode_service.py`, B3.11) | Heavy DICOM pixel decode (JPEG2000 etc.) | GIL-bound CPU — a thread would stall the app | `ProcessPoolExecutor(spawn)`, workers=`_resolve_decode_workers()`; `max_tasks_per_child=200` (memory guard); hard-failure streak (3) → bounded restart (≤2) → in-process fallback; `shutdown_decode_service()` called at app exit (`main.py:1363`) | ✅ Correct. Restart machinery **observed working live today** (`[B3.11] … restarting pool (1/2)`). Master-plan KPI: decode p50 <1 ms, cache hit 100 % — explicitly do-not-touch. |
| **Download worker** (`download_process_worker.py` + `download_process_entry.py`) | Series download: network + gzip + disk write | Full isolation of network/compression CPU from the GUI process | One `multiprocessing.Process` per active study, `MAX_CONCURRENT_STUDIES=1` (R11); Queue IPC + QThread bridge (bridge does *no heavy Python*); `daemon=True`; **DM-H4 orphan guard**: terminate→join(2 s)→kill→join after any bridge termination | ✅ Correct, deliberately serial (radiology UX: current patient first; preempt = pause-for-resume). Orphaning is guarded twice (daemon + DM-H4). |
| **ZetaBoost warmup** (`zeta_boost/warmup_subprocess.py`) | VTK volume pre-build for instant patient switching | VTK CPU + memory kept out of the GUI process | spawn; bounded queues (32); disk cache capped 20 GB / 600 entries; `set_global_download_active()` throttles it during any download; shutdown wired via viewer close (`_vc_warmup`/`_vc_load`) | ✅ Correct, well-throttled. |
| **Chromium** (QtWebEngineProcess) | Web browser tab / prewarm | Chromium's own multi-process model | OPT-41/41b: prewarm gated on real inter-interaction idle; ~350 MB aux files pre-read off-thread; warm view held to `loadFinished` | ✅ Handled this session; warm boot measured ~1.0 s. |
| **Slicer MPR** (`launch_slicer.py`) | Advanced 3D/MPR/VRT | Entire heavyweight app isolated | Launched via subprocess; separate lifecycle | ✅ Correct (the bundled `python-install/Lib/test` files that dominate raw grep counts are vendored CPython — not app code). |
| **Auto-update helper** | Apply update after exit | Must outlive the app | Waits-never-kills + rollback (OPT-38) | ✅ |
| EchoMind app | AI secretary | Separate product process; sets its own Chromium flags | — | ✅ |

**Simultaneous-workload safety** is by construction: one study downloading (R11) + warmup throttled during downloads (`set_global_download_active`) + booster threads at `THREAD_PRIORITY_IDLE` + progressive-grow batch caps (16 entries/tick, 6 under heavy interaction) + decode subprocess restarts under pressure. The existing GUI-lane tests (`test_long_session_workload`, `test_idle_resource_budget`, `test_dm_preempt_on_drag`) pin these interactions and passed this week (16/16).

## 3. Thread map — what runs inside the GUI process

**Event loop:** qasync (asyncio on the Qt GUI thread). All orchestration (open, resync, reconcile, OPT-40 manual download) is async; blocking I/O hops out via `asyncio.to_thread` / `run_in_executor` (37 + 47 sites) with bounded semaphores and timeouts. This is the standard modern pattern for this app class.

**Bounded executors (singletons or per-pipeline, all capped):** FAST viewer decode/frame/grow pools (`prefetch_workers` / 2–4 / 1); header-fill (`_vc_cache`); series-load (`_pw_series`: N / 1 / 1); ITK instance build (`min(8, cpu)`, or 2 in Mode B); thumbnail write (1, `AIPACS_THUMB_SAVE_ASYNC`, OPT-01); home-panel pool (4); DM header prefetch; AI segmentation (2); module manager; relay WebSocket. pydicom/pylibjpeg/numpy/SimpleITK release the GIL in C code, so threads are the *correct* model for these — the truly GIL-bound decode lives in the subprocess.

**41 QThread subclasses:** almost all one-shot, dialog-scoped I/O workers (consultation/identity/education/reception/CD-burn/stitching/upload API calls). Appropriate model; the one lifecycle bug in this class (UploadManager worker leak → 0xC0000409) was found and fixed this session with a drain (S1), and `UploadManager.shutdown()` is wired to `aboutToQuit`.

**Daemon utilities:** F8/F11 stall probes, resource monitor (2 s cadence), queue-based logging, image-slice booster (OS idle priority), prewarm import/file-warm. All bounded, all daemon.

**Thread-safety spot checks:** workers never touch widgets directly — results marshal back via Qt signals (queued), `QTimer.singleShot`, or the qasync loop; the one worker-thread→UI bridge that needed care (`_ZetaDownloadBridge`) exists precisely because `QTimer.singleShot` doesn't fire from bare threads. Duplicate-job protection: `add_downloads` state-store dedup + reconcile per-patient inflight set + prewarm `_scheduled` + resync TTL throttle. Exceptions: every worker body observed wraps and logs (the DM logs skipped/failed per study).

## 4. Database threading model

`database/_pool.py`: **per-thread connection pool** (`threading.local` + pool keyed by thread id), `check_same_thread=False` only to allow pooled return, **WAL journal mode**, standard PRAGMAs, and dead-thread pruning so exited workers can't leak file descriptors or WAL read locks. Writers follow the commit contract (project memory). WAL means readers never block the GUI behind a writer. ✅ Correct model; no cross-thread connection sharing found.

## 5. Measured performance (this machine)

| Metric | Value | Source |
|---|---|---|
| Idle CPU (main + decode) | 0.0 % / 0.0 % | live psutil snapshot today |
| Idle RSS | 531 MB + 291 MB decode | same (warn threshold 1000 MB) |
| Threads | 68 main / 21 decode | same |
| Orphaned workers | 0 | same |
| Decode latency | p50 <1 ms (cache 100 %) | master plan §15 (07-04 live) |
| Frame / TTFI | p50 17.9 ms / 22.8 ms | same |
| During-use stalls | 4 stalls / 2 min, max 355 ms (healthy run) | 07-03 probe |
| Stack-drag ui_lag | p50 255 ms / p95 849 ms | 07-04 live — **open item** |
| Startup stalls today | window.show ~5.9 s; tab construction ~1.3 s | today's F11 probe |
| Chromium warm boot | ~1.0 s warm / 15 s cold (now pre-warmed off-thread) | OPT-41b bench |

## 6. Ranked residual findings (all tracked; none require redesign)

1. **Startup construction on the GUI thread** (~5.9 s `window.show` + ~1.3 s `add_AIPacs_tab`) — Qt widget construction is inherently main-thread; the tracked fix is *deferral* (OPT-01 P1.4 / OPT-12: lazy EchoMind/tab init), not threading. Highest-value remaining item.
2. **Stack-drag main-thread contention** (p95 849 ms during drag) — render is fast; contention is queued main-thread work during interaction. Tracked in master plan §9; candidate: extend the interaction-aware deferral (B34) to the remaining emitters.
3. **Occasional generic GC stalls** (5.9 s + 2.4 s `notify` stalls on 07-04, no deeper frame) — OPT-05 candidate (GC tuning / deferred GC on close already shipped; the residual needs a deeper trace).
4. **68 idle threads** — parked and harmless (0 % CPU), but per-widget executors (e.g. the AI viewer's 2-worker seg executor) are per-instance; worth a one-line audit if many AI tabs are opened in one session. Observation only.
5. **Decode pool size = 1 on this machine** — adequate per KPIs (do-not-touch per master plan); revisit only if multi-series first-load latency ever profiles hot.

## 7. What was checked against the user's checklist

Expensive-operation placement: DICOM parse/decode → subprocess+GIL-releasing threads ✅ · thumbnails → server-provided + async write ✅ · server comms → async/to_thread ✅ · downloads → subprocess ✅ · DB sync → executor + WAL ✅ · image processing/ITK → GIL-releasing thread pools ✅ · VTK calc → warmup subprocess / Slicer app ✅ · compression → download subprocess ✅ · directory scanning → chunked/off-thread (OPT-01, OPT-27) ✅ · DICOMDIR build → CD/offline flows off the GUI thread ✅ · report sync → QThread workers ✅. Remaining exceptions are §6 items 1–3.

Lifecycle: start-on-demand ✅ (DM tab, decode service, prewarm all lazy) · reuse ✅ (singletons + pools) · clean stop ✅ (aboutToQuit + exit hooks + DM-H4 + dead-thread pruning) · crash orphans ✅ (daemon flags + kill guards; zero measured) · duplicate-start guards ✅.

---

*Related fixes shipped during this review series: OPT-40 (manual download unified), OPT-41/41b (prewarm gate + file warm), S1 (UploadManager thread drain). Master plan §9/§15 remains the canonical backlog for §6 items.*
