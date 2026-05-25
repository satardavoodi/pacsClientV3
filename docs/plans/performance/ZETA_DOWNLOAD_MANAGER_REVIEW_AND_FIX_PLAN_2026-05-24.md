# Zeta Download Manager — Comprehensive Review & Full Fix Plan (2026-05-24)

> **Status:** Phases 1–3 partially applied (2026-05-24). Optimization paused at
> user request — **see §13 for current implementation progress** before resuming.
> **Scope:** `modules/download_manager/` (canonical runtime authority) and its
> integration surface (`modules/network/zeta_adapter.py`,
> `PacsClient/.../home_ui/home_download_service.py`, `database/download_progress_db.py`).
> **Method:** Full read of the 21k-line module across 4 parallel deep-read passes;
> every HIGH finding verified directly against the source.
> **Policy:** Conservative. No behavior change without a test gate and a rollback
> note. §1–§12 are the original review (frozen as written); §13–§15 record what
> was applied, diagnosed, and mapped on 2026-05-24.

---

## 1. Executive Summary

The Zeta Download Manager is a well-layered, recently-hardened subsystem. The core
runtime path — socket connect → metadata fetch → per-series socket download →
disk + DB persistence → Qt-signal handoff to the viewer — is sound and already
carries a lot of defensive work (cancellation-aware retry backoff, R17/R19/R19b/R20
resume logic, preemption, KPI instrumentation).

The review found **no defect that corrupts the clinical database or loses a
completed study**. The issues that matter are concentrated in five areas:

1. **Silent partial-file corruption** — DICOM/thumbnail files are written
   non-atomically and resume logic trusts file *names* without an integrity check,
   so a file truncated by mid-download preemption is never re-fetched.
2. **Preemption blind spot** — a study in `VALIDATING` holds the single download
   slot but is invisible to the preemption rule, so a CRITICAL "click thumbnail →
   download this series first" can wait out the full ~30–60 s handoff budget.
3. **Process/thread lifecycle** — a wedged or force-terminated download subprocess
   can be orphaned (keeps running, keeps writing to `dicom.db`).
4. **Structural debt** — three worker implementations coexist; two are dead code.
   Several other classes (`ConnectionPool`, `BatchProcessor`, `DatabaseWorker`) are
   exported but unused. The main implementation guide is badly out of date.
5. **Cross-process DB contention** — the download subprocess writes directly into
   the live clinical `dicom.db`; two of its three insert paths have no
   lock-retry wrapper.

None of these requires an architecture rewrite. The fix plan in §8 is phased so the
zero-risk cleanup lands first and the behavioral changes land last, each behind a
test gate.

### Severity tally

| Severity | Count | IDs |
|----------|------:|-----|
| HIGH     | 6 | DM-H1 … DM-H6 |
| MEDIUM   | 10 | DM-M1 … DM-M10 |
| LOW      | 9 | DM-L1 … DM-L9 |

---

## 2. Module Map (As-Built)

The canonical module is `modules/download_manager/` (~21,000 lines, ~60 `.py`
files). The older `PacsClient/zeta_download_manager/` referenced throughout the
implementation guide is **not** the runtime authority — see DM-M10.

| Subpackage | Key files | Responsibility |
|-----------|-----------|----------------|
| `core/` | `models.py`, `enums.py`, `constants.py`, `exceptions.py` | Dataclasses, priority/status enums, tunables |
| `network/` | `socket_client.py` (1557 ln), `grpc_client.py`, `connection_pool.py`, `health_monitor.py` | Socket DICOM transfer, gRPC metadata, health tracking |
| `coordinator/` | `series_intent_coordinator.py` (850 ln) | Viewer→DM intent handoff, priority retry ladder |
| `rules/` | `rule_engine.py`, `priority_rules.py`, `resume_rules.py`, `validation_rules.py` | R-numbered rule set (priority, R17/R19/R20 resume) |
| `state/` | `state_store.py`, `state_machine.py`, `observers.py` | `DownloadState` store, transitions, observer fan-out |
| `download/` | `executor.py`, `series_downloader.py` (979 ln), `batch_processor.py`, `progress_tracker.py` | Orchestration, per-series loop, progress |
| `workers/` | `download_process_worker.py`, `download_process_entry.py`, `subprocess_worker.py`, `download_subprocess.py`, `download_worker.py`, `worker_pool.py`, `database_worker.py` | QThread↔subprocess bridges, pool |
| `storage/` | `database_manager.py`, `file_manager.py`, `thumbnail_cache.py` | DB writes, disk I/O, thumbnail cache |
| `ui/` | `widget/_dm_*.py`, `components/`, `dialogs/` | Download Manager tab UI |

### Live pipeline (verified against code)

```
HomePanel double-click / thumbnail drag
        │
        ▼
home_download_service → DownloadManagerWidget.add_downloads (_dm_queue.py)
        │
        ▼
_dm_workers._start_download_worker → DownloadProcessWorker (QThread bridge)
        │  spawns
        ▼
multiprocessing child (download_process_entry.run)
        │
        ├─ DownloadExecutor.execute_download
        │     ├─ rule validation (R17a in-memory / R17b on-disk file count)
        │     ├─ gRPC metadata fetch (GrpcMetadataClient → socket settings)
        │     ├─ DB hierarchy init (initialize_study)
        │     └─ SeriesDownloader.download_all_series
        │           └─ per series:  SocketDicomClient.download_batch (BATCH_SIZE=10)
        │                 ├─ JSON envelope, 4-byte length prefix, base64+gzip payload
        │                 ├─ write Instance_NNNN.dcm to {SOURCE_PATH}/{study_uid}/{series_no}/
        │                 └─ batch_insert_instances → dicom.db
        │
        ▼  mp.Queue (progress / completion)
DownloadProcessWorker bridge → Qt signals
        ▼
_dm_workers handlers → studyProgressUpdated / seriesDownloadCompleted / download_completed
        ▼
home_download_service → viewer (progressive load) + thumbnail manager
```

**Note on transport:** bulk DICOM bytes travel over the **socket** protocol
(`SocketDicomClient.download_batch`, endpoint `GetSeriesImages`), not gRPC. Only
*metadata* uses gRPC. `docs/pipelines/download-pipeline.md` is otherwise accurate
but its data-flow diagram says "Series downloaded via gRPC stream" — minor drift.

---

## 3. Network Layer — Socket, Request, Receive

**What is correct.** Host/port resolution is safe: `SocketDicomClient` defaults to
`DEFAULT_SOCKET_PORT=50052` (`core/constants.py:10`), subprocess workers override via
`get_socket_server_settings()`, and no path feeds the DICOM port `105` from
`servers.json` into the socket client — the CLAUDE.md hazard does **not** occur in
this module. TCP options are set well (`SO_KEEPALIVE`, `TCP_NODELAY`,
256 KB/128 KB buffers). The wire protocol is clean: JSON envelope
(`{endpoint, params, token}`) → UTF-8 → 4-byte big-endian length prefix → payload;
response read accumulates partial reads to an exact length with a 500 MB allocation
guard. Reconnect uses exponential backoff with jitter and is cancellation-aware.

**Findings:** DM-H1, DM-L1, DM-L5 (see §7).

The single most important network defect is **DM-H1** — `_safe_recv()`
(`network/socket_client.py:910-948`) returns empty bytes `b""` for *all three* of
`socket.timeout`, connection reset, and clean EOF. The caller cannot tell a
transient 30 s stall from a dead connection, so a recoverable stall triggers a full
reconnect (and possibly a series restart) instead of a cheap recv retry.

---

## 4. Priority, Rules & Scheduling

Priority is a 4-level `IntEnum` (`LOW=0 … CRITICAL=3`). Only one study downloads at
a time (`MAX_CONCURRENT_STUDIES=1`); CRITICAL/HIGH series run sequentially,
NORMAL/LOW may run 2–3 in parallel. The rule set is R-numbered and the
`SeriesIntentCoordinator` provides a thin viewer→DM intent path plus a retry
"ladder" that keeps trying to start a promoted study until the pool slot frees.

**What is correct.** `get_next_download` sorts pending by `(-priority, -start_time)`;
the state store mutates under an `RLock` and fires observers *outside* the lock
(good — avoids the cross-thread deadlock); the V2 wall-clock handoff
(`AIPACS_INTENT_HANDOFF_V2`) is a genuine improvement over the legacy attempt-count
ladder and uses a CAS helper for `PAUSED→PENDING`.

**Findings:** DM-H3 (preemption ignores `VALIDATING`), DM-M1 (live mutable state to
observers), DM-M2 (CAS TOCTOU), DM-M3 (polling retry ladder), DM-M5 (destructive
queue selection), DM-L8 (resume keyed off study totals), DM-L9.

The headline issue is **DM-H3**: `evaluate_preemption`
(`rules/priority_rules.py:88-97`) builds `affected_downloads` only from studies with
`status == DOWNLOADING`. A study in `VALIDATING` holds the one slot but is invisible,
so a generic CRITICAL/HIGH promotion frees nothing and the new download waits out
the entire handoff budget.

---

## 5. Execution, Workers & Recovery

The download runs in a **separate OS process** for GIL isolation from the viewer.
A `DownloadProcessWorker` QThread bridges the child process to Qt signals; config
crosses as a dict, progress/completion via `mp.Queue`, cancel via `mp.Event`.
`SeriesDownloader` runs series sequentially over one persistent socket, with R20
skip, R19/R19b resume, and a 3-round per-series retry loop with `3s→6s→12s` backoff.

**What is correct.** Cancellation is cooperative and the retry/reconnect sleeps are
cancellation-aware (preempted workers stop waiting and free the slot early). Partial
failures are tracked per series and retried. The persistent-socket reuse and chunked
DB inserts are sound optimizations.

**Findings:** DM-H4 (orphaned subprocess on terminate), DM-H6 (triple worker / dead
code), DM-M6 (final progress dropped), DM-M7 (IPC queue), DM-M8 (no hang watchdog),
DM-L2/DM-L3 (dead `BatchProcessor` / `DatabaseWorker`).

---

## 6. Persistence & Viewer Handoff

**Disk paths — verified correct.** DICOM files land at
`{SOURCE_PATH}/{study_uid}/{series_number}/Instance_NNNN.dcm`; thumbnails at
`THUMBNAIL_PATH/{study_uid}/{series_number}.png`
(`download/executor.py:443,457`). No path is built from `BASE_PATH`. The CLAUDE.md
path invariants hold.

**DB.** `core/constants.py:66` imports `DATABASE_FILE` — the download subprocess
writes into the **live clinical `dicom.db`**. `insert_download_progress` has a
5-retry lock loop; `initialize_study` and `batch_insert_instances` do **not**.

**Handoff — generally good.** All Qt-widget mutations from worker signals are
deferred via `QTimer.singleShot(0, …)`; progress is throttled; no `make_pixmap…`
runs off the main thread; per-tab signal connections are cleanly torn down. FAST
viewer mode is not touched by this module (no VTK instantiation) — the
download→viewer boundary is signal-only.

**Findings:** DM-H2 (non-atomic writes + name-only resume), DM-H5 (DB contention),
DM-M9 (`INSERT OR REPLACE` churn / non-atomic progress update), DM-L4, DM-L6, DM-L7.

---

## 7. Findings Register

Each finding has an ID used by the fix plan in §8. Line numbers marked ✓ were
verified directly during this review.

### HIGH

#### DM-H1 — `_safe_recv()` conflates timeout, reset, and EOF
- **Where:** `network/socket_client.py:910-948` ✓
- **Detail:** `socket.timeout` → `return b""` (line 932-934 ✓); connection reset →
  `return b""` (line 922-931 ✓); a clean server close is also `b""`. Body/header
  read loops treat `b""` as "connection lost / closed by server".
- **Impact:** A transient 30 s network stall mid-transfer is misdiagnosed as a hard
  disconnect → unnecessary reconnect, possible series restart, spurious failures on
  congested links. Also: `connected`/`socket` are nulled from the recv path while
  other threads read them without synchronization.
- **Fix:** Distinguish the timeout case (distinct exception or sentinel). Callers
  retry the *same* recv on timeout; reconnect only on true EOF/reset. Treat
  `connected`/`socket` mutation consistently under the existing lock.

#### DM-H2 — Non-atomic file writes + name-only resume → silent partial-file corruption
- **Where:** `network/socket_client.py:1268-1271` ✓ (DICOM write),
  `:1241` ✓ (skip-by-name), `:1407-1421` ✓ (`_scan_existing_files`);
  `download/executor.py:457` (thumbnail write).
- **Detail:** `open(path,'wb'); f.write(bytes)` writes straight to the final
  `Instance_NNNN.dcm`. Downloads are preempted/cancelled mid-flight; a kill between
  `open` and a complete `write` leaves a **truncated** `.dcm`. `_scan_existing_files`
  lists `*.dcm` by name with **no size/integrity check**, and the per-instance skip
  (`if file_name in existing_files_set: continue`) treats any present name as
  complete. The truncated instance is never re-fetched; the viewer later loads a
  corrupt slice.
- **Impact:** Silent clinical-image corruption that survives resume. Highest-impact
  finding.
- **Fix:** Write to `Instance_NNNN.dcm.part`, then `os.replace()` to the final name
  (atomic on same NTFS volume). Add a minimum-size / DICOM-magic (`DICM` at offset
  128) check to `_scan_existing_files` so truncated files are re-fetched. Apply the
  same temp-then-rename to the thumbnail PNG write.

#### DM-H3 — Preemption ignores `VALIDATING` workers; the pool slot is never freed
- **Where:** `rules/priority_rules.py:88-97` ✓
- **Detail:** `evaluate_preemption` collects `affected_downloads` only where
  `status == DOWNLOADING` (line 90-91 ✓). A study in `VALIDATING` (metadata fetch /
  R17 checks) holds the single `MAX_CONCURRENT_STUDIES=1` slot but is invisible.
  `request_critical_series` patches this for one path; the generic
  `request_study_priority` / `negotiate_priority_change` do not.
- **Impact:** "Click series thumbnail → download it first" can wait out the full
  priority-handoff budget (~32 s legacy / 60 s V2) if the slot-holder is validating.
- **Fix:** Include `VALIDATING` (and any slot-holding state) in the preempt set, or
  drive `evaluate_preemption` from live `WorkerPool` truth rather than
  `state.status`.

#### DM-H4 — Orphaned download subprocess on forced `QThread.terminate()`
- **Where:** `workers/worker_pool.py:145-152` ✓; `workers/download_process_worker.py`
  `run()` `finally` block.
- **Detail:** `_remove_worker` does `quit()` → `wait(3000)` → `terminate()`.
  `quit()` is a no-op for a blocking-`run()` QThread. If the bridge does not exit
  in 3 s, `terminate()` kills the bridge thread abruptly, so `run()`'s
  `finally: self._cleanup()` (which calls `_process.terminate()`) never executes.
  The child download process keeps running — orphaned — still holding sockets and
  writing into `dicom.db`. `daemon=True` only reaps it at full-app exit.
- **Impact:** Leaked OS process, continued DB writes after the UI considers the
  download gone, slot never truly freed.
- **Fix:** Before `QThread.terminate()`, explicitly `request_cancel()` and
  `self._process.terminate()/kill()` + short `join` on the child; or move subprocess
  teardown into a `finished`-signal slot that runs regardless of how the thread
  ended.

#### DM-H5 — Download subprocess writes directly into the live clinical `dicom.db`
- **Where:** `core/constants.py:66` ✓; `storage/database_manager.py`
  (`initialize_study`, `batch_insert_instances`); `database/download_progress_db.py`.
- **Detail:** The download subprocess's DB connections resolve to production
  `dicom.db`. WAL allows one writer; the subprocess's instance/study inserts
  serialize against the main app. `insert_download_progress` has a 5-retry lock
  loop, but `initialize_study` and `batch_insert_instances` have **no** retry
  wrapper — a single `database is locked` raises `DatabaseError` and aborts the
  study insert (files on disk, no DB rows → mixed/invisible study).
- **Impact:** Intermittent study-insert failure under DB contention. Same isolation
  surface as the 2026-05-24 DB-pollution incident — handle carefully.
- **Fix (conservative):** Wrap `initialize_study` and `batch_insert_instances` in
  the same locked-retry helper already used by `insert_download_progress`.
  (Larger optional refactor in §8 Phase 4: stage instance rows in a per-download
  sqlite, merge once in a single main-process transaction.)

#### DM-H6 — Triple worker implementation; two paths are dead/stale
- **Where:** `workers/` — `download_process_worker.py`, `subprocess_worker.py` +
  `download_subprocess.py`, `download_worker.py`, `worker_pool.py:14,40` ✓
- **Detail:** `DownloadProcessWorker` is the live worker (imported by
  `ui/widget/widget.py:40` ✓, `_dm_workers.py:12` ✓, `zeta_adapter.py`).
  `SubprocessDownloadWorker` (`subprocess_worker.py`) and its entry
  `download_subprocess.py` are referenced **only by each other** — dead code.
  `DownloadWorker` (in-process QThread, `download_worker.py`) survives only as
  `worker_pool.py`'s import and the stale `active_workers: Dict[str, DownloadWorker]`
  type hint — `add_worker` is actually handed `DownloadProcessWorker` instances
  (`_dm_workers.py:216` ✓, `zeta_adapter.py:230` ✓).
- **Impact:** A fix applied to one path silently misses the others. The two entry
  modules have already diverged (`progress_pct` vs `progress_percent` key names) —
  exactly the class of bug that surfaces if the wrong bridge/entry pair is wired.
- **Fix:** Confirm-then-delete `subprocess_worker.py` + `download_subprocess.py`;
  correct `worker_pool.py`'s import and type hints to the real worker (or a shared
  base class / `Protocol`).

### MEDIUM

#### DM-M1 — Observers receive the live, mutable `DownloadState` object
- **Where:** `state/state_store.py:216-228` ✓
- **Detail:** `update()` snapshots `pending_notifications` under `_lock`, then passes
  the *stored* `state` object to `_notify_observers` outside the lock (line 228 ✓).
  A concurrent `update()` can mutate that same object while an observer reads it.
- **Impact:** An observer can persist/display a field value inconsistent with the
  `(field, old, new)` event it was handed — transient wrong UI values, torn DB
  writes.
- **Fix:** Pass `dataclasses.replace(state)` (an immutable snapshot) to observers,
  matching what `create()` / `reset()` effectively already do.

#### DM-M2 — `update_if_status` CAS has a TOCTOU window
- **Where:** `state/state_store.py:254-268` ✓
- **Detail:** Verifies `expected_status` under `_lock`, releases the lock, then calls
  `update()` which re-acquires; `update()` does not re-verify the expected status.
  The in-code comment acknowledges this.
- **Impact:** Narrow — the V2 handoff is the only caller — but the "atomic CAS"
  contract is overstated.
- **Fix:** Do the check + apply inside one `_lock` acquisition (internal
  `_update_locked` helper).

#### DM-M3 — Polling-based priority-handoff retry ladders
- **Where:** `coordinator/series_intent_coordinator.py` (legacy ~32 s ladder; V2
  250 ms ticks over a 60 s budget).
- **Detail:** Both chains are pure QTimer polling loops; there is no callback from
  `WorkerPool` when a slot frees. `WorkerPool` already accepts an `on_worker_removed`
  callback (`worker_pool.py:30,43` ✓) — it just is not used to wake the coordinator.
- **Impact:** CRITICAL-handoff latency is bounded only by the tick interval; ticks
  burn cycles re-reading state while nothing changes.
- **Fix:** Wire `WorkerPool.on_worker_removed` → coordinator "try start now"; keep
  the timer only as a coarse safety backstop.

#### DM-M4 — `speed_mb_per_sec` / `eta_seconds` fabricated from a hardcoded 500 KB/file
- **Where:** `core/models.py:246-260` ✓
- **Detail:** Speed and ETA assume every instance is exactly 500 KB
  (`total_mb = downloaded_count * 500 / 1024`). Real DICOM instances vary 10×+.
  Actual bytes are already measured in the downloader
  (`socket_client.py:1278-1279` ✓ `batch_write_bytes` / `total_write_bytes`) but
  never threaded into the state model.
- **Impact:** UI speed and ETA — and any KPI derived from them — can be wildly wrong.
- **Fix:** Carry real downloaded-byte totals into `DownloadState`; compute speed/ETA
  from actual bytes + elapsed time.

#### DM-M5 — `get_next_download` mutates queue state during selection
- **Where:** `rules/rule_engine.py` (`_filter_database_completed_pending`).
- **Detail:** The next-study *selection* read path calls `state.remove(study_uid)`
  for DB-completed studies, which deletes state and fires `removed` observers
  (DB delete, UI row removal).
- **Impact:** If the DB row is stale, a legitimately pending study is silently
  dropped from the queue.
- **Fix:** Make selection non-destructive (skip, do not remove); perform cleanup in
  an explicit, separate step.

#### DM-M6 — Final progress update can be permanently dropped
- **Where:** `download/progress_tracker.py:119-132`; no `force_update()` caller in
  `SeriesDownloader`.
- **Detail:** `report_progress` flushes only when the 100 ms throttle window has
  elapsed; a final 100 % event arriving inside a window sits in `pending_updates`
  and is never flushed.
- **Impact:** Progress bar can stall just short of 100 % until the separate
  `completed` signal arrives.
- **Fix:** Call `progress_tracker.force_update()` at the end of
  `download_all_series` and on series completion.

#### DM-M7 — Subprocess progress dropped on full IPC queue; completion `put()` can block forever
- **Where:** `workers/download_process_entry.py` (`put_nowait` + swallowed
  exception for progress; `put()` with no timeout for completion).
- **Detail:** Progress heartbeats are silently lost when the bridge consumer is
  slow; the completion message uses an unbounded `put()` — if the queue is full and
  the bridge has died, the subprocess blocks forever and never exits.
- **Impact:** Bar jumps/stalls; in the worst case a subprocess that cannot exit.
- **Fix:** Completion `put(..., timeout=N)` with a fallback path; optional small
  coalescing on progress.

#### DM-M8 — No hang/watchdog timeout on a wedged subprocess
- **Where:** `workers/download_process_worker.py` bridge poll loop.
- **Detail:** If the child deadlocks but stays `is_alive()`, the bridge polls
  forever; nothing force-terminates it unless the user cancels.
- **Impact:** A wedged download permanently occupies the single pool slot.
- **Fix:** Max-idle watchdog — no queue message AND process alive for N seconds →
  force-terminate child, emit failure.

#### DM-M9 — `INSERT OR REPLACE` PK churn + non-atomic progress read-modify-write
- **Where:** `database/download_progress_db.py:46`; `storage/database_manager.py`
  (`update_download_progress`).
- **Detail:** `INSERT OR REPLACE` deletes+reinserts the progress row (PK changes
  every write); `update_download_progress` does `get` then `insert` with no
  enclosing transaction.
- **Impact:** Concurrent progress-throttle + completion writes can lose an update;
  PK churn breaks any future FK to that row.
- **Fix:** Use `UPDATE … WHERE` (or `INSERT … ON CONFLICT DO UPDATE`); wrap the
  read-modify-write in a single transaction.

#### DM-M10 — Outdated / misleading documentation
- **Where:** `modules/download_manager/ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md`.
- **Detail:** The guide describes a `PacsClient/zeta_download_manager/` path that is
  not the canonical module, an idealized JSON-RPC chunk protocol and
  `ChunkDownloader` / `FileAssembler` classes that do not exist, and a
  `socket_config.json` with a nested `server.host/port` shape and port `5555` —
  the real file is flat-keyed with `socket_port: 50052`. The guide's version is
  `2.2.7`; `__init__.py` says `1.08.9.8.3`.
- **Impact:** An engineer following the guide makes wrong assumptions about paths,
  protocol, and config.
- **Fix:** Rewrite the guide against the as-built `modules/download_manager/` code,
  or clearly mark it superseded by `docs/pipelines/download-pipeline.md`.

### LOW

| ID | Finding | Where |
|----|---------|-------|
| DM-L1 | **Dead code** — `network/connection_pool.py` (`ConnectionPool`) is exported but never instantiated (the live path uses one persistent `SocketDicomClient` per `SeriesDownloader`). It also contains a real dead-client-leak bug in `get_connection` (`:81-91` ✓) — latent because unused. | `network/connection_pool.py` |
| DM-L2 | **Dead code** — `download/batch_processor.py` (`BatchProcessor`) exported, referenced only in a `rule_engine.py` comment; adaptive batch sizing here is unreachable. | `download/batch_processor.py` |
| DM-L3 | **Dead/parallel infra** — `workers/database_worker.py` (`DatabaseWorker`) QThread DB offloader not used by the download path. | `workers/database_worker.py` |
| DM-L4 | Resume integrity is weak — `check_file_exists` accepts any file > 128 bytes as complete; `check_series_complete` uses `>=` so extra files mask a missing instance. (Related to DM-H2.) | `rules/resume_rules.py` |
| DM-L5 | Bare `except:` clauses swallow `KeyboardInterrupt`/`SystemExit` at several points. | `socket_client.py` (≈244,857,870,883,898,928,942,1555), `connection_pool.py:129` |
| DM-L6 | Stale `_pending_reception_requests` dict entry on error — the error handler clears legacy scalars but not the dict, permanently blocking re-fetch for that patient. | `ui/widget/_dm_reception.py` (≈155-158) |
| DM-L7 | `_tasks` dict grows unbounded — deliberately retained for retry; a slow leak over thousands of patient-switch cycles. | `ui/widget/_dm_workers.py` (`_cleanup_task_state`) |
| DM-L8 | Resume decisions key off study-level instance totals, not per-series content — net-zero count shifts mis-classify RESUME; any total delta forces a full RESTART that discards valid partial files. | `rules/resume_rules.py` |
| DM-L9 | Legacy vs V2 handoff chains differ in token-staleness / elapsed-ms baseline handling — minor diagnostics inaccuracy. | `coordinator/series_intent_coordinator.py` |

---

## 8. Performance KPIs & Bottlenecks

### What is measured today
- Real per-batch disk-write telemetry exists: `dicom_file_write_batch_count`,
  `dicom_file_write_bytes_total`, `dicom_file_write_ms_p95` (canonical
  `download_diagnostics.log`).
- Priority-handoff latency KPIs: `overlap_priority_handoff_latency_p50/p95_ms`,
  pool-busy ratio, primary/recovery/V2 exhaust counts.

### Gaps
- **No true end-to-end throughput KPI.** Speed/ETA are fabricated (DM-M4); a real
  MB/s from measured bytes is not surfaced.
- No KPI for resume effectiveness (files skipped vs re-fetched) or for
  partial-file re-fetch (which DM-H2 currently hides entirely).

### Bottlenecks (ranked)
1. **In-RAM batch buffering** — `response_data += chunk` builds the whole payload
   (up to 500 MB) in memory via repeated `bytes` concatenation (≈O(n²) realloc),
   then `json.loads` + base64-decode + gzip-decompress hold ~3–4× the payload at
   peak. Mitigated by `BATCH_SIZE=10` and adaptive halving, but a single large
   instance still spikes. → use `bytearray`/`b"".join`; consider per-instance
   streaming.
2. **`initialize_study` is `async def` doing blocking sync SQLite** — blocks the
   subprocess asyncio loop for the whole patient+study+series insert (unlike the
   instance inserts, which already use `run_in_executor`).
3. **DB write serialization** against the live `dicom.db` (DM-H5).
4. **Polling retry ladders** (DM-M3) burn QTimer cycles.
5. Sequential CRITICAL/HIGH series download is **by design** (clinical ordering) —
   not a bottleneck to "fix".

---

## 9. Full Fix Plan (Phased — Per-Step Approval)

Conservative ordering: zero-runtime-risk work first, behavioral changes last. Each
step lists the change, files, **risk**, **test gate**, and **rollback**. I will
execute one step at a time and pause for your approval between steps.

### Phase 0 — Baseline & safety gate (no code change)
- **S0.1** Capture baselines before any edit: run
  `tests/download_manager/run_dm_test.py`, `test_dm_stress.py`,
  `test_socket_client_cancellation.py`, `test_priority_handoff_v2.py`,
  `test_state_store_batch_update.py`; save output under `generated-files/benchmarks/`.
  Run the existing audit `tools/diagnostics/zeta_dm_evaluation_audit.py`.
  - **Risk:** none. **Gate:** baseline recorded (pass/fail noted as-is).

### Phase 1 — Zero-runtime-risk cleanup
| Step | Change | Files | Risk | Test gate |
|------|--------|-------|------|-----------|
| S1.1 | Rewrite or supersede the implementation guide; fix the gRPC-stream wording in `download-pipeline.md` (DM-M10) | docs only | none | n/a |
| S1.2 | Delete dead `subprocess_worker.py` + `download_subprocess.py` after a final grep confirms zero non-test references (DM-H6, part 1) | `workers/` | low | full DM suite green; app launches |
| S1.3 | Delete or quarantine dead `connection_pool.py`, `batch_processor.py`, `database_worker.py` after grep confirmation (DM-L1/L2/L3) | `network/`, `download/`, `workers/` + `__init__.py` exports | low | import smoke test; full DM suite |
| S1.4 | Fix `worker_pool.py` import + `active_workers` type hint to the real worker type / a shared `Protocol` (DM-H6, part 2) | `workers/worker_pool.py` | low | full DM suite |

Gate for Phase 1: full DM test suite green; source build launches and a
single-patient + multi-study download still works (manual GUI check).

### Phase 2 — Low-risk reliability fixes
| Step | Change | Files | Risk |
|------|--------|-------|------|
| S2.1 | **DM-H2** atomic writes: `*.part` + `os.replace()` for DICOM and thumbnail writes | `socket_client.py:~1265-1287`, `executor.py:~455` | low–med |
| S2.2 | **DM-H2** add size / `DICM`-magic integrity check to `_scan_existing_files` so truncated files re-fetch; align `check_file_exists`/`check_series_complete` (DM-L4) | `socket_client.py:1407-1421`, `resume_rules.py` | medium |
| S2.3 | **DM-H1** distinguish `socket.timeout` from EOF/reset in `_safe_recv`; callers retry recv on timeout | `socket_client.py:910-948` + recv-loop callers | medium |
| S2.4 | **DM-M6** call `progress_tracker.force_update()` at series/study completion | `series_downloader.py`, `progress_tracker.py` | low |
| S2.5 | **DM-M9** `UPDATE…WHERE` instead of `INSERT OR REPLACE`; wrap progress read-modify-write in one transaction | `download_progress_db.py`, `database_manager.py` | low–med |
| S2.6 | **DM-L5** replace bare `except:` with `except Exception:` in DM network code | `socket_client.py`, `connection_pool.py` (if kept) | low |

Gate: after each step, `test_download_manager.py` + `test_socket_client_cancellation.py`
green; for S2.1/S2.2 add a focused test that a truncated `.dcm` is detected and
re-fetched; manual resume-after-interrupt GUI check.

### Phase 3 — Medium-risk concurrency & DB correctness
| Step | Change | Files | Risk |
|------|--------|-------|------|
| S3.1 | **DM-H5** wrap `initialize_study` + `batch_insert_instances` in the locked-retry helper used by `insert_download_progress` | `database_manager.py` | medium |
| S3.2 | **DM-M1** pass `dataclasses.replace(state)` snapshots to observers | `state_store.py:216-228` | medium |
| S3.3 | **DM-M2** make `update_if_status` check+apply atomic under one lock | `state_store.py:254-268` | low–med |
| S3.4 | **DM-M5** make `get_next_download` selection non-destructive | `rule_engine.py` | medium |
| S3.5 | **DM-M7** completion `put(timeout=N)`; **DM-M8** subprocess hang watchdog | `download_process_entry.py`, `download_process_worker.py` | medium |

Gate: `test_state_store_batch_update.py`, `test_dm_stress.py` (esp. S6 thread-safety,
H3/H4 contention), `test_priority_handoff_v2.py` green; multi-patient GUI stress
check (rapid patient switching, no mixed data).

### Phase 4 — Behavioral / scheduling changes (highest care)
| Step | Change | Files | Risk |
|------|--------|-------|------|
| S4.1 | **DM-H3** include `VALIDATING`/slot-holding states in `evaluate_preemption`, or drive it from live `WorkerPool` truth | `priority_rules.py:88-97`, `series_intent_coordinator.py` | high |
| S4.2 | **DM-H4** terminate-safe subprocess teardown — cancel + join child before `QThread.terminate()`, or move teardown to a `finished` slot | `worker_pool.py`, `download_process_worker.py` | high |
| S4.3 | **DM-M3** wire `WorkerPool.on_worker_removed` → coordinator wakeup; keep timer as backstop | `worker_pool.py`, `series_intent_coordinator.py` | high |
| S4.4 | **DM-M4** thread real downloaded-byte totals into `DownloadState`; compute true speed/ETA | `models.py`, `series_downloader.py`, progress path | medium |
| S4.5 | *(optional, larger)* **DM-H5 deep fix** — stage download instance rows in a per-download sqlite, merge once in a single main-process transaction | new staging module, `executor.py`, `database_manager.py` | high — only if S3.1 proves insufficient |

Gate: each step individually behind the full DM suite + the priority-handoff KPI
parser tests + a scripted GUI test (open patient → drag a different series →
confirm CRITICAL series downloads first; cancel mid-download → confirm no orphan
`python.exe` child in Task Manager).

### Phase 5 — Documentation & KPI close-out
- **S5.1** Update `download-pipeline.md` and the rewritten guide to match the
  shipped behavior; add a real-throughput KPI and a resume-effectiveness KPI.
- **S5.2** Record an as-built note (like `COPILOT_REPORT_db_cleanup.md`) capturing
  what changed and the new regression guards.

---

## 10. Regression Guards — Do **Not** Break

Carried from project `CLAUDE.md` and confirmed relevant to this module:

1. **Single-study path unchanged.** Multi-study behavior is gated on
   `len(_studies_series) > 1`; download-manager edits must not perturb the
   single-study download path.
2. **Disk path invariants.** DICOM →
   `{SOURCE_PATH}/{study_uid}/{series_number}/Instance_NNNN.dcm`; thumbnails →
   `THUMBNAIL_PATH/{study_uid}/{series_number}.png`. Never build a path from
   `BASE_PATH`. (Currently correct — keep it so, especially in S2.1.)
3. **Socket port.** Thumbnail/patient/download sockets use `socket_port` from
   `config/socket_config.json` (`50052`), never the `port` from `servers.json`
   (`105`, DICOM). (Currently correct.)
4. **DB isolation.** Tests must patch `PacsClient.utils.data_paths.DATABASE_FILE`,
   not `database.core._DB_PATH`. Any new DB-touching test for S2.2/S3.1 must follow
   the loud-fail temp-DB pattern.
5. **FAST viewer mode** must never instantiate VTK render windows — the
   download→viewer handoff stays signal-only.
6. **Qt-thread rules.** `make_pixmap_from_bytes` is main-thread only; all
   worker→UI updates stay marshaled via `QTimer.singleShot(0, …)`.
7. Preserve all viewer features, overlays, metadata, sync, measurements, sidebars,
   and the resume/retry behavior (R17/R19/R19b/R20).

---

## 11. Test Coverage Assessment

Existing coverage is good for state/priority/rules: `test_download_manager.py`
(27 scenarios), `test_dm_stress.py` (10 heavy scenarios),
`test_socket_client_cancellation.py`, `test_priority_handoff_v2.py`,
`test_state_store_batch_update.py`.

**Gaps this plan should close with new focused tests:**
- No test that a **truncated `.dcm`** is detected and re-fetched on resume
  (DM-H2 / DM-L4) — add in S2.2.
- No test that preemption frees a **`VALIDATING`** slot-holder (DM-H3) — add in S4.1.
- No test that a force-terminated worker leaves **no orphan child process**
  (DM-H4) — add in S4.2.
- No test for `_safe_recv` timeout-vs-EOF behavior (DM-H1) — add in S2.3.

---

## 12. Recommended First Actions

1. Approve **Phase 0** so baselines are captured before anything changes.
2. Approve **Phase 1** (docs + dead-code removal) — zero runtime risk, and it
   removes the confusion that makes every later fix riskier.
3. Then proceed step-by-step through Phases 2→4, pausing for approval and a test
   gate at each step.

---

## 13. Implementation Progress (2026-05-24)

§1–§12 above are the original review, frozen as written. This section records what
was actually applied, deferred, or left outstanding during the 2026-05-24 session.

**Verification note:** the analysis sandbox could not run the project test suite
(Windows venv mismatch), and its shell showed a stale view of editor-modified
files — the file tools (Read/Write/Edit) are authoritative. Every applied change
was verified by reading the on-disk result and by the user launching the source
build and confirming downloads still work.

### Status by step

| Step | Status | Notes |
|------|--------|-------|
| Phase 0 / S0.1 | ◑ partial | Static audit captured (`generated-files/benchmarks/zeta_dm_audit_2026-05-24.json`). Dynamic DM test suite **not** formally baselined — user-verified by launch instead. |
| S1.1 docs | ✅ done | Implementation guide given a SUPERSEDED banner; `download-pipeline.md` gRPC-stream wording fixed. |
| S1.2 / S1.3 dead code | ✅ done | `subprocess_worker.py`, `download_subprocess.py`, `connection_pool.py`, `batch_processor.py`, `database_worker.py` quarantined to `_recovery/phase1_deadcode_20260524/`; `__init__.py` exports cleaned. |
| S1.4 worker_pool hint | ✅ done | `DownloadWorker` import/hints → `QThread`. |
| S2.1 atomic writes | ✅ done | `.part` temp + `os.replace()` for DICOM (`socket_client.py`) and thumbnails (`executor.py`). |
| S2.2 resume-scan integrity | ✅ done | `_scan_existing_files` excludes `.part` and sub-128-byte files. Size check only — the DICM-magic check was judged too risky without server-format confirmation. |
| S2.3 timeout/EOF | ⏸ DEFERRED | Touches the hot socket recv loop; needs a focused test before applying. |
| S2.4 progress flush | ✅ done | `progress_tracker.force_update()` at study completion in `download_all_series`. |
| S2.5 progress DB SQL | ⏸ DEFERRED | `INSERT OR REPLACE` / non-atomic RMW — needs the `download_progress` schema confirmed + a DB test. |
| S2.6 bare excepts | ✅ done | 8 bare `except:` → `except Exception:` in `socket_client.py`. |
| S3.1 DB retry-on-lock | ✅ done | `initialize_study` + `batch_insert_instances` retry on "database is locked" (the harmony fix). |
| S3.2 / S3.3 / S3.4 / S3.5 | ⛔ outstanding | Central concurrency/queue changes — test-gated. Awaiting a `tests/download_manager/` baseline run before applying. |
| Phase 4 (S4.1–S4.5) | ⛔ outstanding | Not started. |

### Extra work done this session (not in the original §9 plan)

- **Corrupt-file recovery.** `_hp_search.py` (305 trailing null bytes) and
  `_hp_modules.py` (truncated mid-statement at line 836) were found broken in the
  working tree and recovered; the corrupt originals are archived in
  `_recovery/corrupt_files_20260524/`.
- **Download-start delay diagnosed & largely fixed** — see §14.
- **Subprocess-spawn timing instrumentation** added to `download_process_entry.py`
  (`[SPAWN-TIMING]` WARNING markers in `download_diagnostics.log`).

### Files changed this session (for future review / `git diff`)

`modules/download_manager/`: `network/socket_client.py`, `download/executor.py`,
`download/series_downloader.py`, `storage/database_manager.py`,
`workers/worker_pool.py`, `workers/download_process_entry.py`,
`download/__init__.py`, `network/__init__.py`, `workers/__init__.py`,
`ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md`.
Integration surface: `PacsClient/.../home_panel/_hp_study_save.py` (GetStudyInfo
fix), `_hp_search.py` + `_hp_modules.py` (corrupt-file recovery).
Docs: `docs/pipelines/download-pipeline.md`, this file.
Quarantined: 5 dead files → `_recovery/phase1_deadcode_20260524/`.

### To resume

1. Run the `tests/download_manager/` suite for a baseline (the Phase 3 gate).
2. Apply S3.2 → S3.5 one at a time, re-running the suite after each.
3. Then S2.3 / S2.5 (also test-gated).
4. Phase 4 last.
5. Optional startup optimization: pre-warm the download subprocess (§14) and
   remove the dead gRPC imports (§15).

---

## 14. Download-Start Delay — Diagnosed & Largely Fixed (2026-05-24)

**Symptom:** the download began ~9 s after the user opened a patient.

**Root cause** (from `download_diagnostics.log`) — the delay was *not* in the
download manager. It split two ways:

1. **~6.8 s — patient open stalled on `GetStudyInfo`.** The server does not answer
   the `GetStudyInfo` endpoint. `get_series_info_from_server` (`_hp_study_save.py`)
   probed it via `get_study_info()`, whose internal 2-attempt retry turned the
   intended "3 s fast probe" into ~6.2 s; multiple open threads each probed
   concurrently, racing the `_GETSTUDYINFO_UNSUPPORTED` skip-cache.
2. **~2.5 s — download subprocess spawn** (Windows `multiprocessing` bootstrap).

**Fix applied** — `_hp_study_save.py`: the probe now sends a single `GetStudyInfo`
request (not the 2-attempt `get_study_info()`), serialized by a new
`_GETSTUDYINFO_PROBE_LOCK` with a re-check of `_GETSTUDYINFO_UNSUPPORTED` inside
it. Confirmed in the log: `download_manager_wired` dropped from **t_ms ≈ 6,852 →
≈ 600–1,000**; `GetStudyInfo` timeouts per open from **8 → 0–1**. Download-start
is now ~3 s steady-state.

**Remaining ~2.3 s — subprocess spawn (not yet optimized).** `[SPAWN-TIMING]`
markers proved the subprocess's own setup is ~90 ms (`Imports OK 0.001 s`,
`DatabaseManager ready 0.010 s` — imports are free because the spawn bootstrap
already loaded them). The full ~2.3 s is the Windows `spawn` bootstrap — process
creation + interpreter boot + re-importing the app tree in the child. **No
hotspot in download-manager code.** The realistic fix is to **pre-warm an idle
download subprocess** (precedent: `modules/zeta_boost/warmup_subprocess.py`) so the
bootstrap is off the user-visible path. Not done — paused at user request.

---

## 15. Communication Path Map — Socket vs gRPC (2026-05-24)

**gRPC has been retired from the active flow; socket is the entire transport.**
Class names mislead — verify before assuming a `*grpc*` name means gRPC.

**Active (socket) paths — truly used at runtime:**

| Path | Client | Notes |
|------|--------|-------|
| Patient list / metadata / thumbnails | `modules/network/socket_client.py` → `PatientListSocketClient` | socket port 50052; endpoints `GetStudyThumbnails`, `QuerySeriesThumbnails`, `GetStudyInfo`\*, `GetReportStatus`\* |
| DICOM image download | `modules/download_manager/network/socket_client.py` → `SocketDicomClient` | endpoint `GetSeriesImages` |
| Download-manager "metadata" | `modules/download_manager/network/grpc_client.py` → `GrpcMetadataClient` | **gRPC name, socket implementation** — wraps `PatientListSocketClient`; `_connect()` is a no-op, `channel`/`stub` always `None` |

\* `GetStudyInfo` / `GetReportStatus` are attempted but the server does not answer them.

**Retired gRPC — files still present, on no active path:**
`modules/network/grpc_client.py` (`DicomGrpcClient`), `dicom_downloader.py`,
`dicom_downloader_client_help.py`, `multi.py`, `dicom_service_pb2.py`,
`dicom_service_pb2_grpc.py` — all do a real `import grpc`.

**Legacy still accidentally wired (cleanup candidates):**
- `home_panel/widget.py:36-37` — dead imports of `DicomGrpcClient` + the pb2
  modules (unused, but the import drags the heavy `grpcio` library into every app
  launch).
- `PacsClient/components/__init__.py` — re-exports the dead gRPC classes.
- `_hp_series.py` `download_and_open_tab` — orphaned gRPC-download method, no caller.
- `core/constants.py DEFAULT_GRPC_PORT`, `core/enums.py NetworkProtocol.GRPC` — vestigial.

Removing the dead gRPC imports from `widget.py` is a safe startup-time win —
identified, not yet applied.

---

*Document updated 2026-05-24: §1–§12 = original review (frozen); §13–§15 record the
applied work, the delay diagnosis, and the path map. Optimization paused — resume
per §13.*
