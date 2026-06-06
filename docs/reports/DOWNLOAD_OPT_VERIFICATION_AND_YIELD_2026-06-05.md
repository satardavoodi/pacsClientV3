# Download Optimizations — Stability Verification + Batch-Boundary Yield (2026-06-05)

Two work items: (1) verify yesterday's pipeline-speed changes (probe cache + pre-warm)
are stable, repeatable and regression-free; (2) improve same-study drag-drop priority
so the running download yields at a BATCH boundary instead of being torn down.

## 1. Stability verification of the optimization changes

Evidence: soak run `ui_probe_runs/20260605_135452_soak/` (2 restart cycles, fresh
CT patients), KPI runs `20260605_121814_kpi` / `20260605_123459_kpi`, headless suites.

| Check | Result |
|---|---|
| Multiple fresh patient opens | PASS — P1 44558 queue at **670 ms**, first file **1.87 s**; P2 44592 opened during P1's download, isolated correctly |
| Repeated double-click workflow | PASS — every open in 3 sessions produced tab + thumbnails + queue + download with steady-state timings |
| Restart behavior | PASS — cycle 2 restarted cleanly; pending downloads auto-resumed; no probe re-paid |
| Capability cache | PASS — `server_capabilities.json` persisted; **probe lines = 0 in every session after the first** (incl. first open right after restart) |
| Pre-warm subprocess | PASS — `[PREWARM] spawned idle download subprocess` at first search; `Reused pre-warmed download subprocess` on each open; next spare re-warmed in background |
| Download queue correctness | PASS — `FAST-SERIES-DOWNLOAD-QUEUE` per study, single-slot honored, completed statuses correct |
| Thumbnail correctness | PASS — sidebar thumbnails (scout/Tissue with counts) verified on-screen; right-panel gate hits |
| Viewer load correctness | PASS — drop on fresh series rendered (7.5 s incl. mid-download fetch); progressive admission grew to disk count |
| No duplicate requests | PASS — one GetStudyThumbnails per surface (series-info + right-panel, different payloads); GetSeriesImages batches sequential, no repeats |
| No stale state | PASS — per-tab UIDs exact (`no_mixing=True`); freshness re-checks against the local DB |
| Normal download flow regression | NONE — DM suite **115/115**, architecture 19/19, echomind 81/81 (215 total green); mirrors 287/287 |

**Caveat found and fixed in the HARNESS (not the app):** with pre-warm enabled, the
idle spare appears as a second `python.exe main.py` process (this build's worker
children re-exec the main script). `lifecycle.find_app_processes()` now counts only
TOP-LEVEL main.py processes (parent not itself main.py) — previously the spare
triggered false ALREADY_RUNNING / launch-not-ready results and tempted kills of a
healthy worker. Operational note: a `taskkill` of the app should also expect the
worker child; `stop_app` handles both.

## 2. Batch-boundary yield (same-study drag-drop priority)

### What changed
The OLD same-study path (`series_intent_coordinator.request_critical_series`)
**cancelled the study's own worker mid-batch** and restarted it with the dragged
series first — measured cost 5–27 s (teardown + respawn + re-auth + R20 resume scans
of every earlier series) and the in-flight batch's transfer was wasted.

NEW (three pieces, all DM-mirrored, plus the rule the user specified):

1. **Intent file channel** — the GUI writes
   `{SOURCE_PATH}/{study_uid}/.critical_intent.json`
   (`{"series_number","ts"}`, atomic tmp+replace) because the subprocess's state
   store is isolated from the GUI mid-flight. Written by the coordinator (primary)
   and by `_dm_retry`'s same-study branch (defense-in-depth). Falls back to the
   legacy cancel-and-restart if the file cannot be written.
2. **`SocketDicomClient.yield_check`** — consulted ONLY BETWEEN instance batches
   (right after the R25 cancel check): the in-flight batch always completes; if a
   different series of this study is requested, the current series stops with the
   distinct `YIELDED_TO_CRITICAL` marker (kept files, NOT a failure).
3. **`SeriesDownloader`** — polls the intent file (mtime-cached stat) at series
   boundaries AND feeds the hook; on yield it re-queues
   `[critical series, interrupted series, rest]` so the critical series is serviced
   before any new lower-priority batch, and the interrupted series resumes right
   after (R19/R20 skip what it already has). The intent is consumed (file deleted)
   when the critical series completes or is found already complete; stale intents
   (>15 min) are ignored.

Rule compliance: current batch finishes ✓ · no new normal batch before the critical
series ✓ · already-started transfers elsewhere untouched ✓ · single sequential loop,
no new threads/locks in the subprocess, file signaling is crash-safe ✓.

### Verification status
- **Headless: VERIFIED.** New guard suite `test_dm_critical_yield.py` (7/7): intent
  round-trip/TTL/consume semantics, GUI-writer ↔ downloader-reader compatibility,
  and source contracts (hook sits between batches; yielded ≠ failed and precedes the
  failed branch; retry path prefers the intent file over teardown). Full DM suite
  115/115; coordinator/socket/downloader/_dm_retry/_dm_contracts mirrored (287/287).
- **Live: PENDING a quiet window.** Four live attempts today were invalidated by
  environment interference, not by the change: shell-timeout retries piled up
  duplicate harness/app instances, a parallel session was building the v3.2.0
  release on this machine, and earlier attempts ran the cross-study path (another
  study held the slot) — which correctly used the existing DM-H3 preempt. Harness
  hardening landed for the next attempt: singleton lock in the yield test,
  top-level-only process discovery, `YIELD_TEST_SKIP_RESTART` mode, MRI fallback for
  fresh-patient selection. To validate live: run
  `tools/testing/aipacs_control_mcp/same_study_yield_test.py` when nothing else is
  launching app instances; expected signature — `[INTENT] Series yield: …` (WARNING,
  download_diagnostics), NO `download_batch cancelled`, intent file appears then is
  consumed, dropped series' `series_images_progress` within ~1–2 batch periods
  (≈1–2 s) of the drop, interrupted series resumes after.

### Expected effect (from measured components)
Batch period ≈ 350 ms and the dragged series' fetch starts on the SAME socket
session: drop → first byte of the dragged series should fall from 5–27 s to roughly
**0.5–2.5 s** (one batch remainder + one GetSeriesImages round-trip), with zero
wasted transfer and zero process churn.

## 3. Files changed
- `modules/network/socket_client.py` → attachments client (prior session, unchanged)
- `modules/download_manager/network/socket_client.py` — `YIELDED_TO_CRITICAL`,
  `yield_check` hook between batches
- `modules/download_manager/download/series_downloader.py` — intent polling, yield
  handling/re-queue, intent consumption
- `modules/download_manager/coordinator/series_intent_coordinator.py` — intent file
  INSTEAD of same-study worker cancel (legacy path kept as fallback)
- `modules/download_manager/ui/widget/_dm_retry.py` — same-study branch writes
  intent + helpers; `_dm_contracts.py` baseline updated
- `tools/testing/aipacs_control_mcp/` — `kpi_soak_run.py`, `same_study_yield_test.py`,
  `lifecycle.py` top-level process discovery
- `tests/code/download_manager/test_dm_critical_yield.py` (new, 7 tests) +
  `test_dm_prewarm.py` (live-config isolation + config-fallback test)
