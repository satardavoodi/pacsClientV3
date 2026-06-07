# Heavy-image impatient-user stress (CT>1000 / MG / DX) — 2026-06-07 21:26–21:50

Bus-driven run (aipacs-control test server → CommandBus → production functions),
source build with all of today's fixes. Cases: CT 44915 (2453 inst), 43977
(2418), 45112 (2345); MG 44966, 45073; DX 42275, 41893.
Artifacts: `_recovery/stress_heavy_results*.jsonl`, `_recovery/pyspy_freeze*.txt`.

## Verdicts

| Target | Verdict | Basis |
|---|---|---|
| **CT > 1000 slices** | **FAIL** | 57 s whole-GUI freeze mid-phase, then a terminal **>283 s GUI freeze** under continued load (below). Drops/scroll bursts acked at the bus but no first-image events landed in the freeze window. |
| **Mammography** | **NOT RUN** | Blocked behind the CT freeze — rerun after the fix. |
| **Radiography (DX)** | **NOT RUN** | Blocked behind the CT freeze — rerun after the fix. |
| Crash | none | The process never crashed — it froze. No new native-fault dumps beyond the startup/takeover teardown one (21:22:58). |

## The headline defect (py-spy-proven)

During the CT phase (2 opens + 2 heavy drops + 160 scroll commands + tab churn,
then a second 2400-slice patient), the **main Qt thread wedged inside
`threading.Thread.start()`**:

```
MainThread:
  wait (threading.py:359 ← 659)        # waiting for the new thread to bootstrap
  start (threading.py:981)
  _on_series_retry (modules\download_manager\ui\widget\_dm_retry.py:294)
  request_critical…                     # DM critical-priority escalation path
```

`_dm_retry.py:294` spawns a `series-retry-cleanup` thread **on the GUI
thread** when a retried study has no DB state. Under heavy-CT load,
`Thread.start()` itself blocked — new threads could not bootstrap (thread
population/bootstrap starvation) — freezing the entire UI. The F11 sampler
recorded the gap growing past **283,000 ms** before I killed and relaunched
the app. An earlier 57 s freeze (gap_ms=57021) occurred in the same phase.

Secondary finding: the retry fired its "study not found in database" branch
at all — DB state was missing for a study being stressed (same family as the
44982 dead-tab, task #148).

Harness finding: the test adapter's `snapshot_resources` blocks the
test-server dispatch queue indefinitely (head-of-line) — v2's run wedged on
it. Make it async/cached before the next stress session.

## KPI summary (CT window 21:26–21:31, before the terminal freeze)

- Bus ack latencies: opens ~0.1–1 s, drops (change_series) acked promptly;
  80-command scroll bursts fully acked on patient 1.
- Main-thread stalls during the phase: 1.5 s, 2.5 s, 3.5 s, 4.6 s, 5.0 s,
  then 57 s, then the terminal >283 s wedge. Far beyond the 100–300 ms
  baseline of normal sessions — **viewport responsiveness under impatient
  heavy-CT load is not acceptable in this state**.
- Memory/leak assessment: not measurable this run (snapshot_resources is the
  thing that wedged the harness); use the resource-summary log series next run.

## Recommended fixes (priority order)

1. **`_dm_retry.py` — never `Thread.start()` on the GUI thread.** Queue the
   cleanup onto the existing DM executor/worker pool (bounded), or
   `QTimer.singleShot` → pool submit. Audit the whole `_on_series_retry` /
   `request_critical` path for other GUI-thread spawns.
2. **Thread-population audit under heavy-CT stress**: capture a full py-spy
   dump at freeze (this one truncated) and count threads; suspect per-request
   spawns in the scroll/decode path. Cap with a shared executor.
3. **Close the missing-DB-state path** (ties to #148): a study open enough to
   be dropped/retried must have DB state; auto-create is fine but should not
   be reachable for a freshly opened patient.
4. Harness: make `snapshot_resources` non-blocking; add a watchdog that fails
   a bus command after N s instead of wedging the queue.

## Status

App killed and relaunched in normal (non-test) mode at the end of the run.
MG/DX phases + the memory-growth KPI need a rerun after fix (1). Tracked:
task #155.
