# Drag-drop "tail lag" investigation — measurement artifact, no fix needed (2026-07-01)

Investigated the FAST stack-drag tail lag (`FAST_DRAG_KPI ui_lag_max_ms` up to 728 ms, `event_p95_ms`
up to 376 ms). **Finding: this is a KPI measurement artifact of slow/deliberate dragging, not an
app-responsiveness problem. No change to the drag path is warranted** (and would risk regressing a
delicate, heavily-tuned subsystem).

## Evidence

Worst drag observed (pid 22796): `duration_s=4.483 targets=34 event_p50_ms=96.3 event_p95_ms=376.0
handler_p50_ms=2.3 handler_p95_ms=3.0 ui_lag_max_ms=728.1 paint_p95_ms=1.2 background_decode_count=0
prefetch_per_s=0.0 dm_rebuild_during_drag=False main_thread_stall_during_drag=False`. Matching
`FAST_EVENT_PACING`: `total_events=34 accepted_events=34 coalesce_ratio_pct=0.0 scheduler_rejected=0`.

1. **Per-event processing is fast and constant** across all drags: `handler_p95 ≈ 3–10 ms`,
   `paint_p95 ≈ 1.2 ms`. The app handles each drag event in ~3 ms.
2. **The independent stall probe recorded ZERO `fast_drag_active` stalls** in *both* runs (pid 22796
   and 185640). That probe runs on a 50 ms QTimer with a 100 ms threshold, independent of drag events.
   A real 728 ms event-loop block during the drag would have been caught — it wasn't. This is decisive:
   the event loop was **never actually blocked** during dragging.
3. **No coalescing / no dropped events**: `coalesce_ratio_pct=0`, `scheduler_rejected=0` — the pacing
   layer accepted and processed every event.
4. **Not decode / rebuild / prefetch**: the worst drag had `background_decode_count=0`,
   `dm_rebuild_during_drag=False`, `prefetch_per_s=0`.
5. The worst drag was **34 slices over 4.5 s** — deliberate slow stacking, so input events are
   naturally sparse (one every ~130 ms, with pauses).

## Why the KPI looks alarming (metric definitions)

In `modules/viewer/fast/qt_viewer_bridge.py` / `perf_metrics.py` / `ui_throttle.py`:
- `event_p95_ms` = p95 of `event_interval_ms` — the **interval between consecutive input events**
  (`qt_viewer_bridge.py:2120`). Slow dragging → large intervals. This is input cadence, not lag.
- `ui_lag_max_ms` = max of `ui_lag_ms`, where `ui_lag_ms = record_ui_heartbeat()` is recorded **per
  drag event** (`qt_viewer_bridge.py:1068`) and returns the gap vs a 16 ms nominal. Between sparse
  events (user pausing) the gap is large — so it reports the *pause*, not processing lag.

Both metrics conflate "user dragged slowly / paused" with "app was laggy."

## Recommendation

- **Do not change the FAST drag path.** There is no real lag; the subsystem is well-tuned
  (see `docs/plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`,
  `STACK_DRAG_PLAYBOOK_v2.3.6.md`). A speculative change would risk the smoothness with no upside.
- **Read drag health from the right signals**, not `ui_lag_max`/`event_p95`:
  `handler_p95_ms`, `paint_p95_ms`, `background_decode_count` (decode hitches),
  `main_thread_stall_during_drag`, and the count of `active_viewer_state=fast_drag_active`
  `MAIN_THREAD_STALL` events. All were healthy here.
- **Do not touch `record_ui_heartbeat` / the system load controller** to "fix" the metric — it feeds
  adaptive throttling, so changing what it measures is riskier than the misleading number. If a
  cleaner drag-lag KPI is wanted later, add a *separate* input-pending-gated metric rather than
  redefining this one.

## KPI-catalog note (for `docs/performance/FAST_VIEWER_KPI_CATALOG.md`)

> `fast_drag_ui_lag` / `fast_drag_event_p95` are inflated by slow/deliberate dragging (sparse input),
> and do NOT by themselves indicate app lag. Confirm real drag lag with `handler_p95`, `paint_p95`,
> and `fast_drag_active` main-thread-stall count before acting.
