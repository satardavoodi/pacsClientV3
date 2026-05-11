# AIPacs FAST Viewer — Performance Engineering Master Plan

**Document status:** Active  
**Author:** Engineering  
**Date:** 2026-05-05  
**Baseline commit:** `04e184a64e89627d5136256ebeeef5217ef2f9e2` (`origin/beta-version`)  
**Prior work stashed:** `stash@{0}: pre-clean-baseline-reset-2026-05-05`

---

## 1. Executive Summary

The AIPacs FAST viewer exhibits significant UI-thread stalls during the **overlap scenario**: a user scrolls or stacks through a series while another series is simultaneously downloading. User-visible symptoms are image freezes and frame drops during scroll.

This plan defines a disciplined, gate-driven path to a **100% performance improvement**, defined as ≥ 50% reduction on all primary user-visible KPIs relative to the clean baseline. Work is sequenced so that control-plane stability is proven before any FAST pipeline surgery is attempted.

The baseline commit already contains R22 (G8.1 blockSignals fix + G8.2 reentrancy guard). The pre-G8 measurements (1863 ms p95 for DM_REBUILD) are therefore upper-bound historical data, not the current starting point. **Phase 0 of this plan establishes the actual post-G8 baseline before any further code changes are made.**

### 1.1 Audit Addendum (2026-05-07)

This document was reviewed against current code and generated KPI artifacts on 2026-05-07.

Evidence-backed corrections:

1. Phase 1 architecture changes (in-place DM table update, `update_batch`, hidden/drag deferral) are implemented in code.
2. Latest captured DM plan-step payload is **not fully green**: `generated-files/benchmarks/dm_plan_step_eval_2026-05-07_latest2.json` shows `overall_pass=false`, `phase1b_hidden_defer=false`, `phase1c_priority_handoff=false` (`v2_exhaust_count=1` in latest handoff session).
3. Overlap KPI capture remains red: `generated-files/benchmarks/overlap_kpi_2026-05-07_latest2.json` reports `overlap_drag_event_p95_p95_ms=490.16`, `overlap_drag_ui_lag_max_p95_ms=727.34`, `overlap_drag_ui_lag_max_max_ms=1398.4`, `overlap_drag_background_decode_count_total=646`.
4. Therefore prior statements in this file claiming full phase closure are historical snapshots only; they are not the current go/no-go state.

Latest-session correction from the newest captured live run (`pid=24448`, session `sess-868bc62cc9c2`):

1. The latest viewer tail is not a crash, but it is also not green: `[FAST_DRAG_KPI]` reports `event_p95_ms=226.8`, `ui_lag_max_ms=1031.3`, `background_decode_count=13`.
2. The same live run shows a real V2 handoff failure: `[INTENT] Priority retry V2 wall-clock budget exhausted` and `[INTENT_PRIORITY] tag=exhaust ... branch=v2 reason=pool_busy`.
3. The same tail also shows shutdown-time blocking in `closeEvent -> lifecycle_manager.shutdown_all() -> worker_pool.stop_all()` and later DB cleanup lock acquisition. This is a separate late-session blocker and must not be mistaken for the primary overlap root cause.
4. Repeated `[DM_REBUILD] event=defer_hidden` lines prove the hidden-tab deferral path is active, but they do not by themselves prove control-plane stability. A deferred storm can still coexist with handoff exhaustion and elevated drag KPI tails.

Operational rule from this audit:

1. Treat this plan as **re-opened** until one fresh, isolated run family (rotated/clean logs) shows green Stage 1 and Stage 2 gates together.
2. Treat the latest `pid=24448` run as the controlling live reference until a newer clean-session capture disproves it.

---

## 2. Problem Statement

### 2.1 User-Visible Symptoms

| Symptom | Observed context |
|---|---|
| Image freezes for 200 – 2000 ms during scroll | Active download in background |
| Scroll input drops (scroll wheel ignored) | Overlap scenario |
| UI unresponsive for seconds after drag-drop | Series priority change + active download |
| "Scrollbar moves but image frozen" | Worst-case surrogate stale (R1 violation) |

### 2.2 Engineering Root Causes (identified and ordered by impact)

**Root cause A — DM rebuild storm (control-plane, highest impact)**

Each drag-drop by the user triggers `request_critical_series` in `SeriesIntentCoordinator`. This calls `state_store.update()` with a priority change. `state_store.update()` iterates over each changed field and fires `_notify_observers` once per field. `UIObserver.on_state_change()` for `field_name == 'priority'` defers `QTimer.singleShot(0, self.ui.refresh_table_order)`. `refresh_table_order` rebuilds the full QTableWidget — a blocking main-thread operation measured at 50 – 2130 ms.

Before G8.1/G8.2 (pre-baseline): `_clear_details_panel` wrote `priority_combo.setCurrentText("Normal")` without `blockSignals`, which fired `_on_priority_changed` synchronously, calling `state_store.update(priority=NORMAL)` on the just-promoted CRITICAL study, triggering a recursive `refresh_table_order`. This was the dominant storm cause (1863 ms p95).

After G8.1 (blockSignals) + G8.2 (reentrancy guard): the recursive rebuild is blocked. The current baseline therefore has substantially better DM_REBUILD behaviour — but the exact post-G8 numbers have **not yet been measured**.

**Root cause B — UIObserver fan-out per field (control-plane, secondary)**

`state_store.update(study_uid, status=PENDING, is_auto_paused=False, error_message=None)` fires three separate `_notify_observers` calls (one per field). Each triggers all registered observers. For a typical drag-drop sequence, 4–8 observer fan-outs occur in a single event-loop cycle. While each individual call is cheap, the aggregate at 10 Hz download progress rate creates a continuous background load.

**Root cause C — FAST drag-interaction lag (pipeline layer, tertiary)**

During overlap, the FAST pipeline's surrogate search radius, prefetch admission, and progressive grow cadence compete for main-thread cycles. The R12 (P1 admitted during drag), R3 (CACHE_WARM denied), R5 (DM progress skipped during drag), and R22 fixes address these, but post-G8 measurement is required to confirm adequacy.

---

## 3. Current Baseline State

### 3.1 What Is Already in the Baseline Commit (04e184a)

| Fix | Location | Status |
|---|---|---|
| G8.1 — `blockSignals` on `priority_combo.setCurrentText` in `_clear_details_panel` | `_dm_details.py` L246 | ✅ In baseline |
| G8.2 — `_refresh_table_order_in_progress` reentrancy guard | `_dm_details.py` L667 | ✅ In baseline |
| R22 — `[DM_REBUILD]` WARNING-level instrumentation | `_dm_details.py` | ✅ In baseline |
| R22 — `[DM_PRIORITY_TRANSITION]` during_rebuild field | `_dm_controls.py` | ✅ In baseline |
| R12 — P1-neighbor prefetch admitted during protected drag | `ui_throttle.py` | ✅ In baseline |
| R15 — Advanced viewer joins unified protected-interaction latch | `ui_throttle.py`, `_vw_scroll.py` | ✅ In baseline |
| R5 — DM progress skip during protected drag | `_apply_throttled_progress` | ✅ In baseline |
| R3 — CACHE_WARM denied during protected drag | `ui_throttle.py` | ✅ In baseline |
| R18 — Prefetch pre-queue cancellation gates + direction-flip | `lightweight_2d_pipeline.py` | ✅ In baseline |
| Observer notifications fired outside `_lock` | `state_store.py` L220-228 | ✅ In baseline |
| `update_if_status` CAS helper (F3.5.2) | `state_store.py` | ✅ In baseline |
| `QTimer.singleShot(0, refresh_table_order)` for priority changes | `observers.py` L180 | ✅ In baseline |

### 3.2 Pre-G8 KPI Measurements (Historical Upper Bound)

These numbers were captured from a session with additional experimental patches applied on top of beta-version. They represent the worst-case prior to G8 and are reference points, **not the current starting point**.

| KPI | Pre-G8 measured | Instrument |
|---|---|---|
| DM_REBUILD exits | 31 | `[DM_REBUILD] event=exit` |
| DM_REBUILD avg | 621.1 ms | KPI harness p50 |
| DM_REBUILD p95 | 1863.1 ms | KPI harness p95 |
| DM_REBUILD max | 2129.8 ms | KPI harness max |
| INTENT_PRIORITY exhaust | 1 | `[INTENT_PRIORITY] tag=exhaust` |
| FAST drag `event_p95_ms` | 393.5 ms | `[B3.8_SCROLL]` |
| FAST drag `ui_lag_max_ms` | 460.5 ms | `[OVERLAP_SCENARIO]` |
| `handler_p95_ms` | 34.9 ms | `[B3.8_SCROLL]` |
| `background_decode_count` | 0 | KPI harness |

### 3.3 Post-G8 KPI Baseline

**NOT YET MEASURED.** Phase 0 of this plan captures these numbers. All subsequent phases gate against this measured baseline.

---

## 4. Objectives and Success Criteria

### 4.1 Primary Objective

Achieve a true **100% performance improvement** in the overlap scenario, defined as ≥ 50% reduction on every Tier-1 KPI relative to the Phase 0 measured baseline.

### 4.2 KPI Tiers and Targets

**Tier 1 — User-visible, primary gate for plan completion**

| KPI | Source | Phase 0 target (measure) | Plan-complete target |
|---|---|---|---|
| `DM_REBUILD p95_ms` | `parse_dm_rebuild_log_text` | Measured | < 80 ms |
| `DM_REBUILD max_ms` | `parse_dm_rebuild_log_text` | Measured | < 200 ms |
| `FAST drag event_p95_ms` | `[FAST_DRAG_KPI]` | Measured | ≤ 50% of baseline |
| `FAST drag ui_lag_max_ms` | `[FAST_DRAG_KPI]` | Measured | ≤ 50% of baseline |
| `INTENT_PRIORITY exhaust_count` | `parse_priority_handoff_log_text` | Measured | 0 |

**Tier 2 — Invariants that must not regress**

| KPI | Hard limit |
|---|---|
| `overlap_drag_background_decode_count_total` | Must remain 0 (R3 invariant) |
| `DM_PRIORITY_TRANSITION during_rebuild=True count` | Must remain 0 |
| Image correctness (F1 settled hash) | No regression |
| Surrogate correctness (F1 drag hash) | No regression |
| Crash signatures (`PermissionError`, `DuplicateHandle`, Qt exception) | Must remain 0 |

**Tier 3 — Internal quality, non-blocking**

| KPI | Target |
|---|---|
| `handler_p95_ms` | ≤ 16 ms |
| `DM_REBUILD recursive_count` | 0 (already expected post-G8) |
| `DM_REBUILD reenter_skip_count` | 0 (expected post-G8) |

---

## 5. Constraints and Non-Negotiables

The following rules are absolute. Any plan step that violates them is invalid regardless of KPI results.

| Rule | Constraint | Why |
|---|---|---|
| Qt observer deferral contract | `QTimer.singleShot(0, self.ui.refresh_table_order)` in `UIObserver.on_state_change` for priority events **must never be removed** | Removing it puts Qt widget mutations on a worker thread path → Windows `DuplicateHandle` / `PermissionError` crash on subprocess spawn (confirmed crash in prior session) |
| One change per commit | No multi-patch surgery. Each change must have unit tests passing + live KPI run before next change | Prior session proved combined patches cannot be debugged in isolation |
| Plugin mirror parity | Every change to a canonical file must be mirrored to its `builder/plugin package/...` copy before the step is declared complete | Production builds use the plugin copies, not the canonical files |
| No FAST surgery before control-plane gate | Phase 2 (FAST pipeline) does not start until Phase 1 gate is green | FAST improvements are masked if control-plane storms are still occurring |
| R1 surrogate invariant held | `_try_surrogate_frame` threshold `>= 2` must not change | "Scrollbar moves but image frozen" regression |
| Functional parity first | No performance step may change user-visible workflow semantics for series open, drag-drop priority, progressive completion, or background-complete FAST placement rules | This plan is optimization-only; correctness and workflow behavior must remain stable |
| Shutdown work isolated | Shutdown blocking fixes must not be mixed into overlap/drag optimization commits | The latest session shows shutdown stalls are real but diagnostically separate from active-drag behavior |

---

## 6. Architecture Analysis

### 6.1 Observer Notification Fan-Out (the remaining storm path)

```
drag-drop
  → request_critical_series(study_uid, series_number)
      → state_store.update(viewed_series_number=..., priority=CRITICAL)   [2 fields]
          → _notify_observers x2
              → UIObserver: priority field → QTimer.singleShot(0, refresh_table_order)
      → state_store.update(status=PENDING, is_auto_paused=False, error_message=None)   [3 fields]
          → _notify_observers x3
              → UIObserver: status → update_status_badge (fast, ok)
      → negotiate_priority_change(...)
          → pause_downloads_for_preemption([peers])
              → per peer: state_store.update(status=PAUSED, is_auto_paused=True, ...)   [2+ fields]
          → state_store.update(status=PENDING, is_auto_paused=False, ...)   [3 fields]
              → _notify_observers x3
                  → UIObserver: priority? → possibly QTimer(0, refresh_table_order)
  → _refresh_table_order()   [direct call — synchronous at end of request_critical_series]
```

**Result:** 1–3 deferred `refresh_table_order` calls via QTimer, plus 1 direct synchronous call, per drag-drop. Each rebuild is a full QTableWidget construction (50–200ms in normal conditions, 1800ms+ pre-G8 due to recursive cascade).

With G8.2 reentrancy guard: the deferred QTimer calls that arrive while a rebuild is in progress are skipped. The question Phase 0 answers is: **after G8.1+G8.2, do the remaining non-recursive rebuilds each complete within the 80ms p95 gate?**

### 6.2 `state_store.update()` Per-Field Observer Iteration

```python
# Current implementation (state_store.py)
for field_name, old_value, new_value in pending_notifications:   # N iterations
    self._notify_observers('updated', study_uid, state, field_name, old_value, new_value)
```

Each call invokes all registered observers (Database, UI, Priority, Logging, Validation). For `update(status, is_auto_paused, error_message)` with 3 fields: **5 observers × 3 fields = 15 observer calls per `update()` invocation**.

A single drag-drop triggers ~3–5 `update()` calls = **45–75 observer calls total**, all synchronously before the lock is released (lock released before observer fire, but all in the same main-thread event-loop cycle).

### 6.3 `_refresh_table_order` Cost Profile (post-G8 expected)

Estimated rebuild cost components (without recursion):
- `self.download_table.setRowCount(0)`: clears all widgets, triggers Qt layout — **20–80 ms**
- Per-row widget creation (QProgressBar, QLabel, StatusBadge): **5–20 ms per row** × N rows
- `addStretch()` + `updateGeometry()`: **5–10 ms**

For 5 active studies: estimated **50–180 ms per rebuild**. This exceeds the 80 ms p95 gate even post-G8 if triggered multiple times per drag-drop. **The topology-aware skip (Phase 1B) addresses this.**

---

## 7. Implementation Phases

### Phase 0 — Establish Post-G8 KPI Baseline (mandatory first)

**Objective:** Measure the actual KPIs of the current `beta-version` baseline commit. No code changes.

**Steps:**
1. Confirm `git status --short` is clean (only `docs/plans/README.md` untracked OK)
2. Run a representative live session: open 2–3 patients, start downloads, drag-drop series to trigger priority changes, stack-scroll during download
3. Collect `user_data/logs/download_diagnostics.log` and `viewer_diagnostics.log`
4. Run KPI harness:
   ```
   python tools/performance/clearcanvas_aipacs_kpi_harness.py parse-dm-rebuild-log ...
   python tools/performance/clearcanvas_aipacs_kpi_harness.py parse-priority-handoff-log ...
   python tools/performance/clearcanvas_aipacs_kpi_harness.py parse-overlap-log ...
   ```
5. Record all Tier-1 KPIs in the Phase 0 Measurement Table below

**Decision gate after Phase 0:**

| Condition | Decision |
|---|---|
| `DM_REBUILD p95 < 80 ms` AND `DM_REBUILD max < 200 ms` | G8 was sufficient → skip Phase 1A/1B, go directly to Phase 2 |
| `DM_REBUILD p95 ≥ 80 ms` OR `DM_REBUILD max ≥ 200 ms` | Proceed to Phase 1A |
| `INTENT_PRIORITY exhaust > 0` | Proceed to Phase 1C regardless of DM_REBUILD result |
| `event_p95_ms > 300 ms` OR `ui_lag_max_ms > 180 ms` | Note as Phase 2 target; do not start until Phase 1 complete |

**Phase 0 Measurement Table (captured 2026-05-06 from `download_diagnostics.log`):**

| KPI | Measured value | Target | Gate |
|---|---|---|---|
| DM_REBUILD exits (global) | 141 | — | Recorded |
| DM_REBUILD p95_ms (global) | 1019.625 | < 80 ms | FAIL (historical aggregate) |
| DM_REBUILD max_ms (global) | 2129.780 | < 200 ms | FAIL (historical aggregate) |
| DM_REBUILD recursive_count (global) | 0 | 0 | PASS |
| DM_REBUILD reenter_skip_count (global) | 0 | 0 | PASS |
| DM_PRIORITY_TRANSITION during_rebuild (global) | 0 | 0 | PASS |
| INTENT_PRIORITY exhaust (global) | primary=10, recovery=7 | 0 | FAIL |
| FAST drag event_p95_ms | pending phase-2 capture | TBD baseline | Pending |
| FAST drag ui_lag_max_ms | pending phase-2 capture | TBD baseline | Pending |
| background_decode_count | pending phase-2 capture | 0 | Pending |

**Latest-session KPI snapshot (pid=33000, same capture):**

| KPI | Measured value | Target | Gate |
|---|---|---|---|
| DM_REBUILD exits (latest pid) | 1 | — | Recorded |
| DM_REBUILD p95_ms (latest pid) | 47.329 | < 80 ms | PASS |
| DM_REBUILD max_ms (latest pid) | 47.329 | < 200 ms | PASS |
| DM_REBUILD recursive_count (latest pid) | 0 | 0 | PASS |
| DM_REBUILD reenter_skip_count (latest pid) | 0 | 0 | PASS |
| DM_REBUILD defer_hidden_count (latest pid) | 77 | > 0 expected | PASS (feature active) |

Interpretation: this snapshot is no longer authoritative. Newer evidence (`pid=24448`) shows the hidden-defer path is active but Stage 1 is still red because V2 handoff exhausted in a live session.

### Execution Snapshot (2026-05-06)

Completed work since baseline reset:

1. DM rebuild protections and de-duplication improvements landed and mirrored to plugin payload copies.
2. Observer fan-out reduction via `update_batch(...)` landed and mirrored.
3. Hidden-tab rebuild deferral landed and mirrored.
4. `INTENT_HANDOFF_V2_DEFAULT = True` is implemented — V2 wall-clock retry enabled by default (60 s budget). Pre/post synthetic baselines confirm `primary_exhaust 20→0`. L11 load test fixed to use legacy-mode guard. 54 priority handoff tests passing.
5. Test-first KPI infrastructure added:
    - `tests/performance/test_dm_rebuild_kpi_parser.py`
    - `tests/performance/test_dm_rebuild_latest_session_kpi.py`
    - `tests/performance/test_dm_plan_step_gates.py` (12 tests, Phase 1A/1B/1C gates)
    - `tests/performance/test_dm_plan_step_cli_payload.py`
6. New harness commands added:
    - `evaluate-dm-plan-steps --log ... --output ...`
    - Session-scoped handoff parser: `parse_priority_handoff_sessions_log_text()`

Current gate status (historical snapshot):

1. `phase0_integrity`: PASS
2. `phase1a_global_budget`: FAIL (historical aggregate — expected; latest-session is PASS)
3. `phase1a_latest_budget`: PASS
4. `phase1b_hidden_defer`: PASS
5. `phase1b_observer_fanout`: PASS
6. `phase1c_priority_handoff`: PASS in earlier run family only

**Audit correction (2026-05-07):** do not treat Phase 1 as complete globally or on the newest live run. Newest gate payload (`dm_plan_step_eval_2026-05-07_latest2.json`) reports:

1. `phase1a_latest_budget`: PASS
2. `phase1b_hidden_defer`: FAIL
3. `phase1c_priority_handoff`: FAIL (`latest session v2_exhaust_count=1`)

Additional newest-session correction (`pid=24448`):

1. Hidden deferral is visibly active in the log, but `[INTENT_PRIORITY] tag=exhaust ... branch=v2 reason=pool_busy` still occurs in the same run.
2. Therefore the correct interpretation is not "Phase 1 mostly done" but "Phase 1 controls are partially active yet still insufficient under live overlap conditions."

Remaining plan work:

1. Re-run a clean, isolated Stage 1 capture and resolve the live V2 exhaust / rebuild interaction first.
2. Only after a Stage 1 green run family exists, execute Phase 2 overlap KPI captures (`event_p95_ms`, `ui_lag_max_ms`) with pre/post evidence.
3. Run Phase 3 acceptance bundle and document closure evidence.

### Phase 2 Validation Snapshot (2026-05-07 latest run)

Artifacts from latest run:

1. `generated-files/benchmarks/aipacs_log_metrics_2026-05-07_latest2.json`
2. `generated-files/benchmarks/dm_plan_step_eval_2026-05-07_latest2.json`
3. `generated-files/benchmarks/slot_timing_latest_session_2026-05-07.json`

Session-scoped evidence (latest SLOT_TIMING session only, `sess-3f233c8238a8`):

| KPI | Value | Notes |
|---|---:|---|
| `overlap_slot_timing_drag_blocked_ms_total_latest_session` | 49.434 ms | Previously dominated by historical aggregate (~1643 ms across mixed sessions) |
| `progressive.finalize_terminal drag_max_ms` | 14.988 ms | Drag-active, background path |
| `thumbnail.complete_series_download drag_max_ms` | 16.375 ms | Drag-active |
| `thumbnail.start_series_download drag_max_ms` | 8.377 ms | Drag-active |

Latest run aggregate (all sessions in the same log file) still includes historical heavy events and must not be used alone for phase closure:

| KPI | Value |
|---|---:|
| `fast_drag_event_p95_ms` | 490.16 ms |
| `fast_drag_ui_lag_p95_ms` | 727.34 ms |
| `fast_drag_ui_lag_max_ms` | 1398.4 ms |
| `fast_foreground_decode_during_drag_count` | 0 |

Interpretation:

1. The new drag-defer behavior is visible in session-scoped traces, but that alone does not close Phase 2.
2. Newer live evidence (`pid=24448`) still shows elevated drag tails and non-zero drag background decode.
3. Global aggregate remains noisy because it still contains older sessions in `viewer_diagnostics.log`.
4. Phase 2 closure must use session-scoped captures from clean run windows (or rotated logs), and those captures must also be contemporaneous with a Stage 1 green result.

Audit correction (2026-05-07): this same artifact family still shows severe overlap lag and drag background decode activity. Do not mark Phase 2 closed until a clean session family demonstrates:

1. `overlap_drag_event_p95_p95_ms` reduced by >= 50% vs baseline
2. `overlap_drag_ui_lag_max_p95_ms` reduced by >= 50% vs baseline
3. `overlap_drag_background_decode_count_total = 0`

Validation tests added for this phase:

1. `tests/ui_services/test_lifecycle_hygiene.py::test_series_started_is_deferred_during_drag_for_background_series`
2. `tests/ui_services/test_lifecycle_hygiene.py::test_series_completed_is_deferred_during_drag_for_background_series`

Validation results:

1. `python -m pytest tests/ui_services/test_lifecycle_hygiene.py -q` → `25 passed`
2. `python -m pytest tests/performance/test_dm_plan_step_gates.py -q` → `12 passed`

---

### Phase 1A — `_refresh_table_order` Topology-Aware Skip

**Applies only if:** a clean latest-session capture shows Stage 1 remains red and targeted instrumentation confirms ordering/topology churn is still causing unnecessary rebuild work.

**Current status:** Not yet approved to implement. The newest live evidence proves Stage 1 is red, but it does not yet isolate topology-stable rebuilds as the remaining dominant cost. The next action is evidence capture, not code change.

**What changes:** Add a topology comparison at the top of `_refresh_table_order` in `_dm_details.py`. Before doing any widget churn, compute the sorted list of `(priority_rank, status_value, study_uid)` tuples for all current states. Compare with the cached topology from the previous rebuild. If identical, log a skip and return.

**File:** `modules/download_manager/ui/widget/_dm_details.py`  
**Plugin mirror:** `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/ui/widget/_dm_details.py`

**Expected mechanism:**
- Most `QTimer.singleShot(0, refresh_table_order)` calls deferred from UIObserver arrive while the table already reflects the correct priority ordering. The topology check (~1 ms) exits immediately instead of doing 50–180 ms of widget work.
- Skip rate expected: 70–90% of deferred rebuild calls trigger when ordering hasn't changed (e.g., progress updates between drag-drops).

**Consequences:**
- Positive: DM_REBUILD p95 drops proportional to skip rate. Estimated post-Phase-1A: 15–40 ms p95 (from cache-hit path only).
- Negative: If topology comparison logic is wrong, stale table UI (wrong row order). Requires robust comparison including priority, status, and study_uid position.
- Risk level: Low — topology is read-only; worst case is a stale ordering, not a crash.

**Implementation notes:**
```python
# At top of _refresh_table_order, after reentrancy guard:
current_topology = self._compute_table_topology()
if current_topology == getattr(self, '_last_table_topology', None):
    logger.debug("[DM_REBUILD] topology-skip — ordering unchanged")
    return
self._last_table_topology = current_topology
# ... proceed with rebuild ...
```
`_compute_table_topology()` returns a sorted tuple of `(priority_sort_key, study_uid)` for all non-terminal studies. Must match the exact ordering that `_refresh_table_order` produces.

**Gate criteria (must ALL be true before Phase 1A is declared complete):**
1. `DM_REBUILD p95 < 80 ms` in post-Phase-1A live run
2. `DM_REBUILD max < 200 ms` in post-Phase-1A live run
3. DM table visually shows correct ordering after priority change (manual QA)
4. All DM unit tests pass: `python tests/download_manager/run_dm_test.py`
5. Plugin mirror SHA matches canonical: `(Get-FileHash ...).Hash` on both files

**Rollback trigger:** Any crash, `DM_PRIORITY_TRANSITION during_rebuild=True` appearing, or test failure. Rollback: `git checkout modules/download_manager/ui/widget/_dm_details.py` + mirror.

---

### Phase 1B — `state_store.update()` Batch Observer Notification

**Applies only if:** Phase 1A evidence shows remaining observer churn is material, or a focused latest-session trace proves `update_batch(...)` adoption is still incomplete on the controlling handoff path.

**Current status:** Partially implemented in codebase, not yet sufficient in live runs. Do not expand this API further unless the next isolated trace shows a specific remaining per-field fan-out path.

**What changes:** Add `update_batch(study_uid, **changes)` method to `DownloadStateStore` that fires a single `_notify_observers('updated_batch', ...)` call after applying all field changes, instead of one call per field.

**File:** `modules/download_manager/state/state_store.py` + `observers.py`  
**Plugin mirror:** Both state files in plugin package

**Expected mechanism:**
- `update(status, is_auto_paused, error_message)` currently fires 3 observer cycles. With `update_batch`, it fires 1. For `request_critical_series` + `negotiate_priority_change`, the total observer fan-out drops from ~30–50 calls per drag-drop to ~5–10.
- UIObserver must be extended to handle the `updated_batch` event and process all field updates in one pass (but still only queue ONE `QTimer(0, refresh_table_order)` if priority is among the changed fields).

**Consequences:**
- Positive: Reduces observer churn by 3–5×. Lower CPU usage during active download.
- Negative: API change to DownloadStateStore — any external caller using the observer protocol for individual field granularity must be updated.
- Risk level: Medium — observer API change; requires updating all 5 observer classes and all tests.

**Implementation notes:**
- `update_batch` is additive (does not replace `update`). Coordinator callers that pass multiple fields can opt in. Keep existing `update` for single-field callers.
- `UIObserver.on_state_change` for `updated_batch`: iterate changed fields, call appropriate `update_xxx` methods, and queue at most ONE `QTimer(0, refresh_table_order)` if `priority` is in `changed_fields`.

**Gate criteria:**
1. All 5 observer classes handle `updated_batch` event without error
2. `python tests/download_manager/run_dm_test.py` passes (27 scenarios, 129 assertions)
3. DM_REBUILD count per drag-drop decreases (measured via `[DM_REBUILD] event=enter` log lines)
4. No crash signatures in live run
5. Plugin mirror parity

**Rollback trigger:** Any test failure, crash, or DM state corruption (wrong status after priority change).

---

### Phase 1C — Priority Retry Chain Exhaustion Fix (implemented; live stability not yet closed)

**Applies only if:** Phase 0 shows `INTENT_PRIORITY exhaust_count > 0`. ✅ Triggered.

**What was changed:**
- `INTENT_HANDOFF_V2_DEFAULT = True` in `modules/download_manager/core/constants.py` (+ plugin mirror)
- V2 wall-clock retry path (`_schedule_priority_start_retry_v2`): 250 ms cadence, 60 s budget vs legacy 18 s primary cap
- Added `parse_priority_handoff_sessions_log_text()` to KPI harness for session-scoped gate isolation
- Updated `evaluate_dm_plan_step_results()` to prefer latest-session handoff metrics over global aggregate
- Added `test_v2_env_default_on` replacing `test_v2_env_default_off` in `test_priority_handoff_v2.py`
- Fixed L11 load test: wrapped in legacy-mode guard (`AIPACS_INTENT_HANDOFF_V2=0`) since L11 specifically tests the 90×200ms legacy retry budget and the synchronous `defer_call` mock in that test caused infinite recursion with V2's ticker loop

**Pre/post synthetic baselines:** `generated-files/benchmarks/priority_handoff_v2_pre.json` → `_post.json`  
- Pre: `primary_exhaust_count=20, started_count=20 (from primary chain)`, V2 disabled  
- Post: `primary_exhaust_count=0, v2_started_count=20, v2_defer_reclaimed_count=12, total_exhaust=0`

**Gate results (synthetic and regression suites):**

| Gate | Result |
|---|---|
| `INTENT_PRIORITY exhaust_count = 0` in synthetic sessions | ✅ V2 produces 0 exhaust per synthetic run |
| DM test suite: 127 passed, 0 failed | ✅ |
| Priority handoff tests: 54 passed | ✅ |
| DM stress H1–H10: 31 PASS, 0 FAIL | ✅ |
| Load tests L1–L11: 37 PASS, 0 FAIL (after L11 legacy-mode fix) | ✅ |
| Plugin mirror parity (constants.py, coordinator.py) | ✅ |

**Live exhaust data (audit correction):** in the latest evaluated run family (`dm_plan_step_eval_2026-05-07_latest2.json`), `parse_priority_handoff_sessions_log_text` reports latest session `v2_exhaust_count=1` (`phase1c_priority_handoff = FAIL`).

**Newest live evidence (controlling run):** `pid=24448` also hits `[INTENT] Priority retry V2 wall-clock budget exhausted` followed by `[INTENT_PRIORITY] tag=exhaust ... branch=v2 reason=pool_busy`. This confirms the remaining defect is not just a stale aggregate artifact.

**Required next step before any new Phase 1C code change:** capture one focused timeline around the controlling session's `begin -> exhaust` chain and identify whether the failure is caused by pool-slot reclamation lag, repeated hidden-tab rebuild wakeups, or another scheduler interaction. Do not widen the V2 timeout again until that distinction is proven.

---

### Phase 2 — FAST Pipeline Overlap Optimisation

**Prerequisite:** Phase 0 `event_p95_ms` and `ui_lag_max_ms` measurements exceed targets AND all Phase 1 gates are green.

**Current status:** Blocked by Stage 1 red state. The newest session (`pid=24448`) still shows `event_p95_ms=226.8`, `ui_lag_max_ms=1031.3`, and `background_decode_count=13`, but Phase 2 work must remain frozen until the live handoff/control-plane failure is resolved or proven independent with clean-session evidence.

**Note:** Given that R12, R15, R18, B3.x, R5, and R3 are all already in the baseline, Phase 2 work is expected to be incremental. The exact changes will be defined after Phase 0 measurements confirm whether a gap exists.

**Candidate improvements (to be prioritised after Phase 0 evidence):**

| Candidate | Mechanism | Expected gain |
|---|---|---|
| P2.1 — Adaptive surrogate search window tuning | Widen `±N` window during overlap for smoother scroll | Reduces foreground decode during sparse-cache drag |
| P2.2 — `[SLOT_TIMING]` hot-path analysis | Use G6 slot timing data to find hidden main-thread blockers | Identifies any remaining slow slots to target |
| P2.3 — DM progress throttle during protected drag | Skip `_apply_throttled_progress` more aggressively | Reduces UIObserver calls during scroll |

**For each Phase 2 sub-step:** follow the same one-change-per-commit + live KPI gate discipline as Phase 1.

**Gate criteria (Phase 2 complete):**
1. `event_p95_ms ≤ 50% of Phase 0 measured baseline`
2. `ui_lag_max_ms ≤ 50% of Phase 0 measured baseline`
3. `background_decode_count = 0`
4. All F1 pixel-hash regression gates green: `.\tools\dev\run_overlap_regression.ps1`
5. No crash signatures

---

### Phase 3 — Acceptance and Documentation

**Applies when:** All Phase 1 and Phase 2 gates are green in the same live run.

**Steps:**
1. Run full test suite: DM (129 assertions) + viewer tests + smoke tests
2. Run F1 overlap regression bundle: `.\tools\dev\run_overlap_regression.ps1`
3. Capture final KPI table (Tier 1 and Tier 2)
4. Verify plugin mirror parity for all changed files (SHA hash comparison)
5. Update `copilot-instructions.md` with any new rules introduced
6. Tag commit with performance milestone note

**Phase 3 closure snapshot (2026-05-07, provisional):**

1. FAST viewer regression suite: `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -q` → `168 passed`.
2. DM suite: `python tests/download_manager/run_dm_test.py` → `127 passed, 0 failed`.
3. Smoke imports: `python -m pytest tests/smoke/test_import_smoke.py -q` → `24 passed`.
4. Connection-between-modules: `python -m pytest tests/connection_between_modules/ -q` → `1 passed`.
5. F1 overlap bundle: `.\tools\dev\run_overlap_regression.ps1` → `43 passed, 0 failed` (GREEN).
6. DM stress H1–H10: scenarios all completed (`Scenarios failed = 0`); one legacy KPI threshold line (`P99 < 50ms`) remains red in stress summary totals but did not produce scenario failure.
7. Load L1–L11: all scenarios executed with `0` exceptions, summary `37 passed / 0 failed`.
8. Plugin parity maintained for viewer FAST pipeline edits (canonical + plugin payload copies updated together).
9. `copilot-instructions.md` updated with R26 stack-filter rule to lock current policy.
10. Post-fix rerun verification (latest app session `pid=32956`):
    - `download_diagnostics.log`: `Error in progress handler = 0`, `_last_series_number_by_study` missing = `0`, `_pending_progress` missing = `0`, `AttributeError = 0`.
    - True log-level `ERROR/CRITICAL` lines for `pid=32956`: `0` in both `download_diagnostics.log` and `viewer_diagnostics.log`.

**Status (audit correction):** Not complete. Test-suite health is green, but KPI gates are not yet all green in the latest run family, and the newest live run still shows both V2 exhaust and elevated FAST drag tails.

---

## 8. Test Strategy

### 8.1 Unit Tests (run after every commit)

```powershell
# DM state machine, coordinator, priority, observer tests
python tests/download_manager/run_dm_test.py              # 27 scenarios, 129 assertions

# Viewer pipeline tests
python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v   # 61 tests

# Structured logging lint gate
python -m pytest tests/utils/test_structured_logging_lint.py -v  # 6 tests

# Smoke tests
python -m pytest tests/smoke/test_import_smoke.py -v
```

### 8.2 Integration Tests (run after each phase gate)

```powershell
# DM stress (heavy load scenarios H1-H10)
python tests/download_manager/test_dm_stress.py

# Load scenarios (L1-L11)
python tests/load/run_load_test.py

# F1 pixel regression (overlap scenario)
.\tools\dev\run_overlap_regression.ps1
```

### 8.3 Live Run Protocol (required for each KPI measurement)

1. Launch app: `python main.py`
2. Open patient with 3+ series, start download
3. While download is active: drag-drop different series to each viewer (repeat 5×), stack-scroll each viewer for 10+ seconds
4. Close patient, collect logs from `user_data/logs/`
5. Run KPI harness against collected logs

### 8.4 Regression Alarm Conditions (stop immediately if observed)

| Signal | Action |
|---|---|
| `PermissionError` or `DuplicateHandle` in any log | Stop, revert last commit, investigate observer thread safety |
| `[DM_PRIORITY_TRANSITION] during_rebuild=True` | Stop, G8.1 blockSignals regressed |
| `DM_REBUILD reenter_skip_count > 0` in same run as increased p95 | Stop, G8.2 guard may be masking a new signal source |
| `background_decode_count > 0` | Stop, R3 invariant broken |
| F1 pixel hash mismatch | Stop, image correctness regression |
| New stall traces only during shutdown/closeEvent | Separate into shutdown track; do not use as proof that active-drag optimization regressed or improved |

---

## 9. KPI Measurement Protocol

### 9.1 Instruments and Log Tags

| Instrument | Log tag | Harness function | Log file |
|---|---|---|---|
| DM rebuild | `[DM_REBUILD]` | `parse_dm_rebuild_log_text` | `download_diagnostics.log` |
| Priority transition | `[DM_PRIORITY_TRANSITION]` | `parse_dm_priority_transition_log_text` | `download_diagnostics.log` |
| Priority handoff | `[INTENT_PRIORITY]` | `parse_priority_handoff_log_text` | `download_diagnostics.log` |
| FAST drag summary | `[FAST_DRAG_KPI]` | `parse_overlap_log_text` (overlap drag fields) / `parse_aipacs_log_text` | `viewer_diagnostics.log` |
| Overlap | `[OVERLAP_SCENARIO]` | `parse_overlap_log_text` | `viewer_diagnostics.log` |
| Slot timing | `[SLOT_TIMING]` | `parse_slot_timing_log_text` | `viewer_diagnostics.log` |

### 9.2 Comparing Runs

For a valid comparison between two runs, the following must be equivalent:
- Same patient data (same series, same image count)
- Same workflow: same number of drag-drops, same scroll duration
- Same machine (PC A or PC B — do not compare across machines)
- Download server available and responding within normal latency

Record comparison in the Phase 0 measurement table. Do not declare a gate green based on a run with fewer drag-drops or lighter download load than the baseline run.

---

## 10. Sequencing Summary

```
Phase 0  →  Measure post-G8 KPIs  (no code changes)
              ↓
    DM_REBUILD p95 ≥ 80ms?  ──Yes──→  Phase 1A (topology skip)
              ↓ No                          ↓
    INTENT exhaust > 0?     ──Yes──→  Phase 1C (retry fix)
              ↓ No
    event_p95 > target?     ──Yes──→  Phase 2 (FAST overlap)
              ↓ No
    Phase 3  (acceptance, docs, tag)
```

Each phase runs its full test suite and KPI gate before the next begins. No phases run in parallel. If a phase gate fails, the change is reverted before the next attempt.

### 10.1 Immediate Conservative Sequence (supersedes optimistic earlier wording)

1. Rotate or isolate logs and recapture one clean Stage 1 live session on the current codebase.
2. Build a short `begin -> defer/rebuild -> exhaust|started` timeline for the controlling handoff session.
3. Only if that trace isolates a single remaining control-plane cause, make one minimal fix for that cause.
4. Re-run Stage 1 gates on a fresh session family.
5. Unlock Phase 2 only after Stage 1 is green in that same evidence family.

This is the only safe path that preserves function and quality while avoiding another mixed-cause regression cycle.

---

## 11. Non-Negotiable Forbidden Patterns

1. **Never remove `QTimer.singleShot(0, self.ui.refresh_table_order)` from `UIObserver.on_state_change`** — doing so routes widget mutations onto a worker thread path and causes Windows subprocess `DuplicateHandle` crash.
2. **Never combine multiple root-cause changes in one commit** — the prior session confirmed this makes regressions impossible to isolate.
3. **Never start Phase 2 before Phase 1 gates are green** — FAST optimisations are invisible if control-plane storms are masking the results.
4. **Never skip the plugin mirror parity step** — production installed builds use the plugin package copies; a desync causes production-only regressions.
5. **Never accept a KPI improvement measured on a lighter workload than the baseline run** — it is not a real improvement.

---

## 12. Open Questions (updated after 2026-05-07 audit)

1. Why does latest-session handoff still produce V2 exhaustion (`v2_exhaust_count=1`) despite synthetic and stress suites being green?
2. Why does overlap still report high drag tails (`overlap_drag_event_p95_p95_ms=490.16`, `overlap_drag_ui_lag_max_p95_ms=727.34`) after control-plane improvements?
3. Why is `overlap_drag_background_decode_count_total` non-zero in latest overlap captures, and which path is bypassing the intended protected-drag behavior?
4. Should DM plan-step gate defaults be normalized to strict targets (`--dm-p95-target-ms 80 --dm-max-target-ms 200`) in all scripts to avoid accidental 120 ms pass criteria?
5. In the controlling `pid=24448` run, how much of the remaining handoff failure is attributable to repeated hidden-tab deferred rebuild wakeups versus true worker-pool reclamation delay?
6. Should shutdown stalls (`worker_pool.stop_all`, DB cleanup lock, `zetaboost.notify_global_download_stop`) be moved into a separate hardening mini-plan after overlap closure so they do not contaminate active-drag analysis?

## What Is Not Allowed (Hard Bans)

1. Do not remove Qt deferral contract in DM/UI observer paths (no removal of `QTimer.singleShot(0, ...)` where it protects observer sequencing).
2. Do not continue from partially broken local states.
3. Do not combine control-plane changes into one commit without intermediate live validation.
4. Do not run FAST algorithm surgery while Stage 1 control-plane gates are red.

## Success Definition (100% Better)

The plan is complete only when all conditions below are met in comparable runs.

1. `overlap_drag_event_p95_max_ms` improves by >= 50% versus clean baseline.
2. `overlap_drag_ui_lag_max_max_ms` improves by >= 50% versus clean baseline.
3. `overlap_decode_only_p95_ms` improves by >= 50% on harsh synthetic anchor.
4. `overlap_slow_frame_count_16ms` improves by >= 50% on harsh synthetic anchor.
5. No regression on image correctness gates (F1 settled and surrogate hash contracts).
6. No regression on DM priority correctness (`during_rebuild=True` signal remains zero in normal runs).

## Single Direction Roadmap

### Stage 0 - Clean Foundation Lock

Objective: guarantee all work starts from the reference baseline, not an inherited broken tree.

Checklist:

1. `git fetch origin beta-version`
2. Verify `HEAD == origin/beta-version`
3. If dirty workspace exists: stash before any plan execution
4. Record baseline in run note (`commit`, `date`, machine)

Exit criteria:

1. Clean `git status --short`
2. Commit parity with `origin/beta-version`

### Stage 1 - Control-Plane Stabilization Gate (Mandatory Before FAST Surgery)

Objective: remove dominant UI-thread pressure from DM/control-plane first.

Primary gate metrics:

1. `DM_REBUILD p95 < 80 ms`
2. `DM_REBUILD max < 200 ms`
3. `INTENT_PRIORITY exhaust count = 0`
4. `DM_PRIORITY_TRANSITION during_rebuild=True count = 0`

Execution policy:

1. One change per commit.
2. For each change: unit tests + live run + KPI diff before next change.
3. Keep observer deferral contract intact.

Allowed change classes:

1. Rebuild coalescing, topology skip, signal discipline.
2. Batched state updates that reduce observer fan-out.
3. Instrumentation-only improvements.

Exit criteria:

1. All four gate metrics green in same run family.
2. No crash signatures (`PermissionError`, `DuplicateHandle`, Qt exception banner).

### Stage 2 - FAST Path Optimization (Only After Stage 1 Green)

Objective: improve overlap interaction latency from already-stable control-plane base.

Prioritized sequence:

1. Cancellation/admission improvements that reduce decode fallthrough.
2. Frame/prefetch path improvements that preserve protected-drag invariants.
3. Settled-frame polish and end-of-burst smoothness.

Guardrails:

1. Preserve R1-R25 invariants from copilot instructions.
2. Keep FAST/Advanced separation.
3. Mirror required files to plugin payload copies in same commit.

Exit criteria:

1. Per-step KPI delta positive or neutral on all no-regression metrics.
2. No image correctness regressions.

### Stage 3 - 100% Improvement Closure

Objective: prove 2x improvement with reproducible evidence.

Required evidence set:

1. Harsh synthetic pre/post JSON
2. Live overlap pre/post JSON from same scenario class
3. KPI parser outputs archived in `generated-files/benchmarks/`
4. Test suite pass reports for viewer + DM critical suites

Closure rule:

1. All success-definition items pass.
2. Cross-run consistency on at least two comparable captures.

## Per-Step Go/No-Go Contract

For every change:

1. Pre-capture KPIs.
2. Apply one isolated change.
3. Run focused tests.
4. Run live scenario.
5. Compare KPI deltas.
6. If any critical gate regresses, revert that one change immediately.

## Minimal Test Bundle Per Step

1. `tests/viewer/test_fast_viewer_pipeline.py`
2. `tests/viewer/test_overlap_pixel_quality.py`
3. `tests/viewer/test_b34_interaction_aware_policy.py`
4. `tests/download_manager/run_dm_test.py`
5. `tests/performance/test_overlap_kpi_parser.py`

Full regression bundle runs at stage boundaries.

## Why This Path Is Correct

1. It starts from clean `beta-version` baseline instead of patching a broken chain.
2. It fixes control-plane dominance before FAST micro-optimization.
3. It enforces one-direction execution with strict gates and rollback.
4. It defines 100% improvement as measurable 2x KPI gains, not subjective feel.
