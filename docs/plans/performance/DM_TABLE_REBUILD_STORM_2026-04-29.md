# DM Table Rebuild Storm — Silent Main-Thread Blocker

**Discovered:** 2026-04-29 (live log run completed 18:05)
**Phase:** G7 (observation) → G8 (fix)
**Predecessor:** [`SILENT_BLOCKER_TRIAGE_2026-04-29.md`](./SILENT_BLOCKER_TRIAGE_2026-04-29.md) (G6 instrumentation)
**Status:** observation-only instrumentation pending; fix gated on G7 KPI.

## TL;DR

Drag-dropping a series promotes its study to `CRITICAL` priority. The promotion path is supposed to do one DM-table rebuild. Instead it does **two recursively**, because `_clear_details_panel()` mutates `priority_combo` without `blockSignals(True)`, firing `_on_priority_changed` mid-rebuild, which calls `_refresh_table_order` again from inside `_refresh_table_order`. Each rebuild creates ~15 QWidgets per row including a stylesheet QProgressBar and an ActionButtons container.

In the latest live log this storm produced **1264 main-thread stalls ≥50 ms** — including **91 stalls ≥1 s, 34 ≥2 s, 14 ≥5 s** — across the session, with the trace sampler catching the recursive stack at 400 ms and 405 ms.

## Live-Log Evidence

Source: `user_data\logs\viewer_diagnostics.log` (2026-04-29 18:04–18:05).

Stall histogram (main-thread gap_ms, real-blocker band, total 1264):

| Bucket           | Count |
| ---------------- | ----- |
| 100–200 ms       | 675   |
| 200–500 ms       | 382   |
| 500–1000 ms      | 116   |
| 1000–2000 ms     | 57    |
| 2000–5000 ms     | 20    |
| 5000–10000 ms    | 14    |

Captured stack (gap_ms = 400.8, drag_active=False):

```
loop.run_forever
  app.exec
    notify
      _vc_load.py:1474 _deferred_dm_notify
        dm.set_viewed_series
          _dm_priority.py:378 set_viewed_series
            intent_coordinator.request_critical_series
              series_intent_coordinator.py:291 request_critical_series
                self._refresh_table_order()                      ← rebuild #1 starts
                  _dm_details.py:709 _refresh_table_order
                    _select_study_row
                      _dm_details.py:96 _select_study_row
                        _clear_details_panel
                          _dm_details.py:233 _clear_details_panel
                            self.priority_combo.setCurrentText("Normal")  ← unguarded mutation
                              _dm_controls.py:517 _on_priority_changed     ← signal fires
                                self._refresh_table_order()                ← rebuild #2 starts (RECURSION)
                                  _dm_details.py:701 _refresh_table_order
                                    _add_download_row_to_table
                                      _dm_details.py:912 setCellWidget(action_container)
```

A second sample (gap_ms = 405.0) shows the same root cause continuing into `_update_series_breakdown_from_task → frame_layout.addLayout(header_layout)`.

## Root Cause

**File:** `modules/download_manager/ui/widget/_dm_details.py`, line 233.

```python
def _clear_details_panel(self):
    ...
    if self.priority_combo:
        self.priority_combo.setCurrentText("Normal")   # <── BUG: no blockSignals
    ...
```

**Why it explodes:**

1. `_on_priority_changed` (in `_dm_controls.py:487`) is connected to `priority_combo.currentTextChanged`. The slot does NOT short-circuit on programmatic changes — it always calls `state_store.update`, `intent_coordinator.negotiate_priority_change`, AND `_refresh_table_order`.
2. `_refresh_table_order` (in `_dm_details.py:639`) clears the entire `download_table` (`setRowCount(0)`) and repopulates it, calling `_add_download_row_to_table` (line 820) once per study. Each row constructs:
   - 1 `StatusBadge` (`setCellWidget`)
   - 1 `QTableWidgetItem` for patient
   - 1 `QTableWidgetItem` for modality
   - 1 `QProgressBar` with a 17-line CSS stylesheet (`setCellWidget`)
   - 1 `QLabel` for speed (`setCellWidget`)
   - 1 `QLabel` for priority with stylesheet (`setCellWidget`)
   - 1 `ActionButtons` widget + `QHBoxLayout` + `QWidget` container (`setCellWidget`)
   - 4 signal connections on `ActionButtons`
3. After repopulation, `_refresh_table_order` calls `_select_study_row` (line 709), which calls `_clear_details_panel` (line 96), which fires the `setCurrentText("Normal")` again → **rebuild #2**.
4. Each rebuild also tears down and rebuilds the entire series breakdown (`_update_series_breakdown_from_task` at line 542 — `while self.series_layout.count(): item.widget().deleteLater()` followed by per-series QFrame + QHBoxLayout + QProgressBar + 3 QLabel construction).
5. There is NO `_refresh_table_order` re-entrancy guard. There is NO coalescing.

## Dependency Map (callers of `_refresh_table_order`)

Direct callers found via grep on the canonical tree:

| Caller                                                          | Trigger                          |
| --------------------------------------------------------------- | -------------------------------- |
| `_dm_controls.py:_on_priority_changed`                          | combo change (incl. programmatic) |
| `series_intent_coordinator.py:request_critical_series` (line 291) | drag-drop → CRITICAL              |
| `series_intent_coordinator.py:clear_series_intent`              | viewer close                      |
| `series_intent_coordinator.py:negotiate_priority_change` (called by `_on_priority_changed`) | priority demote/promote |
| `_dm_workers.py` / `_dm_queue.py` / `_dm_retry.py`              | various status flips             |
| `state/observers.py:UIObserver`                                 | priority field change → `QTimer.singleShot(0, refresh_table_order)` |

The recursion path is: **any caller → `_refresh_table_order` → `_select_study_row` → `_clear_details_panel` → `priority_combo.setCurrentText` → `_on_priority_changed` → `_refresh_table_order`**.

## Why G6 Drag Telemetry Missed This

G6 (`[SLOT_TIMING]`) only emits at INFO when `drag_active=True OR force=True` AND duration crosses an 8 ms drag threshold (30 ms idle threshold).
The DM rebuild storm fires from `_deferred_dm_notify`, which runs on a 1500 ms delay AFTER drag release. By the time it hits, `is_protected_drag_active()` has long returned False. So:
- Drag-only sample count: 1 in the entire session.
- The storm ran 1264 times producing user-visible jank, but G6's gate filtered all of them out.

The F11 stall sampler caught them because it's drag-agnostic.

## G7 Plan — Observation-Only Instrumentation

**Goal:** quantify the recursion before fixing it, so we can prove the fix works.

### G7.1 — `[DM_REBUILD]` log tag

Wrap `_refresh_table_order` with timing + recursion-depth tracking:

```
[DM_REBUILD] event=enter depth=<N> caller=<frame> rows=<R> selected_uid=<U>
[DM_REBUILD] event=exit  depth=<N> duration_ms=<D.3> rows=<R>
[DM_REBUILD] event=signal_recursion src=<priority_combo|...> depth_at_emit=<N>
```

- Stable format under R21-style contract.
- `extra={"component": "download"}` so async logger admits at INFO.
- One thread-local recursion counter on the mixin instance.
- `caller=` field is `inspect.stack()[2].function` (cheap; called once per rebuild, not per row).
- Rate-limit: emit every call (rebuilds are infrequent in steady-state; storms are exactly what we want to count).

### G7.2 — `[DM_PRIORITY_COMBO_SIGNAL]` log tag

Inside `_on_priority_changed`, log entry with: caller frame, current programmatic-change suspicion (using a new `_priority_combo_programmatic` flag), and whether `_refresh_table_order` is already on the stack.

### G7.3 — KPI parser extension

Add `parse_dm_rebuild_log_text` to `tools/performance/clearcanvas_aipacs_kpi_harness.py`:
- `dm_rebuild_count`
- `dm_rebuild_recursive_count` (depth ≥ 2 at exit)
- `dm_rebuild_duration_p50_ms` / `_p95_ms` / `_max_ms`
- `dm_rebuild_per_session_total_ms`
- `dm_rebuild_signal_recursion_count` (per source)
- `top_callers` (top 5 by total_ms)

### G7.4 — Plugin-mirror parity

Both `modules/download_manager/ui/widget/_dm_details.py` and `_dm_controls.py` have plugin-package copies at `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/ui/widget/`. Every observation edit must land in both with identical bytes.

## G8 Plan — Fix (gated on G7 KPI confirmation)

Three layers, in order of safety / payoff:

### G8.1 — Block signals in all programmatic combo writes

In `_clear_details_panel` and any other programmatic `priority_combo` writer, wrap with `blockSignals(True/False)`. There is already precedent in `_on_priority_changed` itself (line 510-512 wraps the rejection-revert).

```python
if self.priority_combo:
    self.priority_combo.blockSignals(True)
    try:
        self.priority_combo.setCurrentText("Normal")
    finally:
        self.priority_combo.blockSignals(False)
```

Eliminates the recursion trigger.

### G8.2 — Re-entrancy guard on `_refresh_table_order`

Add `_refresh_table_order_in_progress` flag. If already running, log `[DM_REBUILD] event=reenter_skip` and return immediately. Defense-in-depth: even if a future caller forgets `blockSignals`, the recursion stops.

### G8.3 — Coalesce burst rebuilds

Many of the 116 stalls in 500–1000 ms band likely come from rapid sequences (drag-drop a study, observer fires for state→DOWNLOADING, observer fires for first progress, etc.). Add a 50 ms coalesce timer:

```python
def schedule_table_refresh(self):
    if self._refresh_pending:
        return
    self._refresh_pending = True
    QTimer.singleShot(50, self._do_refresh_table_order)
```

Mirrors the existing observer-throttle pattern (R observer-refresh = 0 ms intentionally; coalescing is at the rebuild side, not signal side, so 0 ms observer remains correct for first-tick latency).

## Tests (G7 ships with these; G8 extends)

### `tests/download_manager/test_dm_rebuild_recursion.py` (G7 — to be created)

Required scenarios:

1. `test_clear_details_panel_does_not_fire_priority_changed` — current state: FAILS (documents bug). Future: passes after G8.1.
2. `test_refresh_table_order_recursion_depth_observed` — drives `_refresh_table_order` entry, verifies `[DM_REBUILD]` log shows `depth=2` exit (today's behavior; documented).
3. `test_refresh_table_order_records_caller` — verifies `caller=` matches the actual Python frame.
4. `test_refresh_table_order_emits_dm_rebuild_log` — round-trip with the KPI parser.
5. `test_priority_combo_programmatic_writer_blocks_signals` — once G8.1 ships, this guards regression.
6. `test_refresh_table_order_reentrancy_guard_blocks_recursion` — once G8.2 ships, verifies a forced recursive call returns without rebuilding.
7. `test_table_refresh_coalesce_within_50ms` — once G8.3 ships, three burst calls produce one rebuild.

### `tests/performance/test_dm_rebuild_kpi_parser.py` (G7 — to be created)

Round-trip tests for `parse_dm_rebuild_log_text`:
- Single rebuild round-trip (depth=1).
- Recursive rebuild round-trip (depth=2).
- Burst of 5 rebuilds aggregates to correct percentiles.
- `signal_recursion` counter increments correctly.
- Malformed lines silently dropped (defense-in-depth contract).

## KPI Targets

| Metric                                | Today  | G8 target |
| ------------------------------------- | ------ | --------- |
| `dm_rebuild_recursive_count` / session | ≥ 1264 | 0         |
| `dm_rebuild_duration_p95_ms`          | ~400   | < 80      |
| `dm_rebuild_duration_max_ms`          | ~5000  | < 200     |
| `dm_rebuild_per_session_total_ms`     | thousands | < 500   |
| `MAIN_THREAD_STALL` count ≥ 200 ms (real-blocker band) | 213 in this session | < 30 |

These thresholds are pre-G7-data estimates. Final G8 acceptance gates are written once the G7 baseline is collected.

## Cross-PC Validation

Per repo rule: PC A measures, push, pull on PC B, re-measure. G7 instrumentation lands on PC A first; user collects a baseline log on PC A AND PC B before G8 ships.

## What this DOES NOT touch

- F4 / F5 / F7 (deferred per consolidation).
- F3.5.4 default-on flip (BLOCKED on installed-build refresh).
- Existing G6 instrumentation, KPI parsers, tests, and rules — they remain valid; G7 layers on top.
- ZetaBoost, prefetch, viewport, scroll, drag latch — none of these are involved in the storm.
- `_deferred_dm_notify` itself — it is doing exactly what it should (1500 ms cooldown, single call). The damage is downstream in the DM UI.

## Open questions to resolve in G7 baseline

1. Which call sites (besides drag-drop) cause the most rebuilds? `caller=` field will tell us.
2. Is the recursion always depth=2, or can rapid signal storms push it deeper?
3. Are there silent paths where `_refresh_table_order` is called from a worker thread? (must run on UI thread; G7 will catch wrong-thread calls if they exist.)
4. How much of the 5–10 s stall band is GC pauses triggered by widget churn vs. raw rebuild time?

## Standing constraints honored

- G6 deliverables remain in place (`slot_timing.py`, KPI parser, `R21`, both test files).
- Previous tests, KPIs, and docs remain untouched.
- Plugin-mirror parity required for every G7/G8 code change.
- G7 is observation-only — no behavior changes ship in this phase.
