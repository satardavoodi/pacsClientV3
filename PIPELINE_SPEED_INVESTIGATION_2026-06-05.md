# Patient-Open & Series-Load Pipeline Speed Investigation (2026-06-05)

Question: why does loading feel slower than the local network should allow, and is the
delay server-side or client-side?

Method: clean-slate instrumented runs (`tools/testing/aipacs_control_mcp/
kpi_pipeline_run.py`) on FRESH (never-downloaded) CT studies, joining the always-on
`FAST-OPEN-TRACE` phases with download/socket/DB log marks into ms-resolution
timelines (runs `20260605_121814_kpi` = before, `20260605_123459_kpi` = after).
Freshness is established against the local DB (study has no instances), so these are
true cold-path numbers.

## 1. Verdict: the delay was CLIENT-side; the server is fast

On the local network the server answers `GetStudyThumbnails` in ~280–340 ms and
delivers the first DICOM files ~300–400 ms after `GetSeriesImages` — i.e. the server
preparation step is NOT the bottleneck. Two client-side costs dominated the
double-click → first-byte path (8.3 s measured before):

| # | Cost | Where | Measured |
|---|---|---|---|
| D1 | **Dead `GetStudyInfo` probe** — the server never answers this endpoint; the open path paid the full 3 s probe timeout before the download queue could be created. The in-process skip-cache only helped from the *second* open of each session. | `_hp_study_save.get_series_info_from_server` (GUI process, inside STEP 3.5's series-info fetch) | first open: queue at **3.9 s** (~3.0 s = probe) — second open: queue at 0.53 s |
| D2 | **Cold download-subprocess spawn** — Windows `spawn` + interpreter boot + imports before the first `GetSeriesImages` could go out. | `WorkerPool` → `DownloadProcessWorker` | spawn → first request ≈ **3.8 s** every fresh study |

Together: ~6.9 s of the 8.3 s to first byte was avoidable client overhead.
Remaining structural costs are modest: tab construction ~0.35–0.43 s, series-info
fallback fetch ~0.3 s (a genuine server round-trip), spawn-handoff ~0.1–0.3 s.

Drag-and-drop was already healthy at the escalation layer: drop → `INTENT_PRIORITY`
Critical in **~6 ms** (instant), with the wait dominated by the same-study in-flight
series finishing its batch before yielding (bounded, by design).

## 2. Fixes applied (both conservative, fail-safe, default-preserving)

**F1 — probe timeout 3 s → 1.2 s + persisted capability cache.**
`_GETSTUDYINFO_PROBE_TIMEOUT_S = 1.2` (the probe is best-effort; the reliable
`GetStudyThumbnails` fallback follows immediately), and a timed-out endpoint is now
persisted to `<USER_DATA_ROOT>/config/server_capabilities.json` with a **7-day TTL**
— so even the FIRST open of a new session skips the dead probe. TTL keeps it honest
if the server gains the endpoint later. The ZETA §14 regression guard is fully
preserved: still a raw single-attempt `send_request("GetStudyInfo")` under
`_GETSTUDYINFO_PROBE_LOCK` (never the 2-attempt helper).

**F2 — enabled the §14 subprocess pre-warm pool on this workstation.**
The pool (`modules/download_manager/workers/prewarm.py`) was fully implemented and
test-guarded but env-gated OFF. `prewarm_enabled()` gained a config fallback
(`<USER_DATA_ROOT>/config/download_manager.json` `{"prewarm": true}`; explicit env
always wins; build default stays OFF), and the config was written for this
workstation. Confirmed live: `[PREWARM] spawned idle download subprocess` at first
search, `Reused pre-warmed download subprocess` on both opens, next spare warmed in
the background. Safety properties unchanged: no DB/socket open while idle, daemon
spare, falls back to normal spawn on any failure.

Guard tests updated: `test_dm_prewarm.py` isolated from live user config (the same
live-config-bleed pattern as the mpr/identity flags) + a new config-fallback test.
DM suite **108/108**; plugin payload mirrored (287/287 parity).

## 3. KPI results (double-click clock; fresh CT studies, local network)

| KPI | BEFORE | AFTER — 1st open of session | AFTER — steady state |
|---|---|---|---|
| Double-click → patient tab visible | 0.53 s | 0.43 s | **0.35 s** |
| Double-click → download request sent | ~4.6 s | 1.9 s | **0.59 s** |
| Double-click → first thumbnails (server fetch done) | 4.2 s | 2.2 s | **0.77 s** |
| Double-click → first byte/file received | **8.3 s** | 3.6 s | **1.07 s** |
| Double-click → first image viewable | n/a (by design: viewports await selection; thumbnails are the actionable surface) | — | thumbnails at 0.77 s |
| Drag-drop → priority = Critical | ~6 ms | — | ~6 ms (unchanged) |
| Drag-drop → download request for dragged series | same-study yield, bounded | — | first file at drop+5.8 s (mid-download study) |
| Drag-drop → first image rendered | — | — | **7.5 s** (fresh series, study still downloading) |

Note: "AFTER — 1st open" still paid the one-time 1.2 s probe because the capability
cache was created during that very run; **every future session starts at
steady-state numbers** (the cache file now exists). The user's expectation —
"studies should begin loading in under one second on the local network" — is met:
**first byte at ~1.07 s, request out at ~0.59 s.**

## 4. What was checked and found healthy (no change needed)

- **Queue creation**: 3–5 ms once series info is in hand.
- **Critical escalation**: `INTENT_PRIORITY tag=begin` ~6 ms after the drop.
- **Disk writes / DB updates**: first `batch_insert` 1.5 ms for 5 rows; atomic
  `.part`→replace unchanged; 0 DB-lock retries.
- **Thumbnail refresh**: right-panel cache gate + render coalescing behave per
  contract (gate → socket 280–340 ms → display ~1 ms).
- **UI thread**: no stalls in the workflow window beyond the two known one-shot
  warm-ups (the 05-31/06-04 fixes hold).
- **Duplicate work**: the open path's series-info fetch and the right-panel
  thumbnail fetch are two server calls with overlapping metadata but different
  payloads (no-base64 vs base64 thumbs) and run off-thread in parallel — left
  as-is deliberately (merging them would couple two guarded subsystems for ~0.3 s).
- **Attachments fetch** (1.8–3.5 s) runs on a worker and does not block the queue.

## 5. Stability posture of the changes

No new parallelism was introduced: F1 only shortens a timeout and remembers a fact
across sessions (TTL'd, atomic write, never raises into the open path); F2 flips an
existing, reviewed, test-guarded feature whose OFF-path is byte-identical and whose
failure mode is "fall back to the old spawn". Race-sensitive subsystems
(progressive growth, preemption, cross-patient guards, right-panel gate) were not
touched. Verified by: DM suite 108/108, mirror parity 287/287, and the live
before/after KPI runs above (downloads completed, thumbnails correct, dropped
series rendered, no errors/faults in the run windows).

## 6. Possible next steps (NOT applied — would need their own review)

- Same-study drop latency (5.8 s to first file) is now the largest remaining wait:
  a finer-grained same-study yield (pause current series mid-batch for a Critical
  sibling) would cut it, but touches the preemption invariants (DM-H3) — needs its
  own soak.
- Tab construction (~0.35 s) could shrink via widget pooling — low value vs risk.
- If the server team can ship `GetStudyInfo`, the probe turns into a real
  lightweight metadata path and the fallback's base64 round-trip disappears.

*Evidence: `ui_probe_runs/20260605_121814_kpi/` (before) and
`ui_probe_runs/20260605_123459_kpi/` (after) — summary.json + timeline_A/B.json.*
