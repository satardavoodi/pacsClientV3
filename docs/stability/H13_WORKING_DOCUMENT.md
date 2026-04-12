# H13 — Working Document

**Investigation:** Backing-Store / Publish / Render Consistency  
**Crash:** `Fatal Python error: PyThreadState_Get: GIL not held`  
**Platform:** Python 3.13.5, VTK 9.x, PySide6/Shiboken, numpy  
**First observed:** Log 12 (persisted through Log 14, 16, 17)  
**Phase:** 1 (baseline diagnostic — probes deployed, live run pending)  
**Last updated:** 2026-04-12

---

## 1. Goal

Identify the root cause of the fatal `PyThreadState_Get: GIL not held` crash that occurs during FAST-mode download+scroll overlap (Pipeline A). The crash persists after decode serialization (H12), eliminating the C-extension codec hypothesis. This investigation systematically discriminates among 5 remaining hypotheses using probes, toggles, and KPI measurement.

---

## 2. Hypotheses

| ID | Name | Claim | Status | Current evidence strength |
|----|------|-------|--------|--------------------------|
| **H13-A** | Zero-copy write/read race | Worker `vol[i]=arr` (GIL released) overlaps with main-thread VTK render chain (GIL released). Both access same memmap via `numpy_to_vtk(deep=False)` | **ACTIVE — strongest** | Code arch confirms lock gap; no experimental overlap data yet |
| **H13-B** | VTK/Shiboken GIL bug (Py 3.13) | VTK wrapper incorrectly manages GIL during callbacks from C++ on Python 3.13 | **ACTIVE — secondary** | Crash is C-level PyThreadState_Get, not Python exception; but only under load |
| **H13-C** | grow() pointer swap UAF | `grow()` replaces VTK scalar array; VTK internal caches hold stale pointer to old memmap freed by GC | **ACTIVE — secondary** | Architecturally plausible; no grow-timing correlation data yet |
| **H13-D** | CPU pressure amplifier | CPU >100% widens GIL-released windows, making latent races fatal | **ACTIVE — amplifier** | User reports clear correlation; CPU 110.4% in Log 16, decode 50→280ms |
| **H13-E** | Throughput/backpressure mismatch | No bounded backpressure between decode producers and render consumer; pacing gap narrows under load | **ACTIVE — mechanism** | 218 dropped frames, no throttle, queue maxsize ~4× slices |

---

## 3. Probe Inventory

All probes are always-on (no env var required). They add minimal overhead (atomic reads, `perf_counter_ns` calls, periodic 1s log lines).

| ID | Probe | Location | What it measures | Log marker |
|----|-------|----------|-----------------|------------|
| **P1** | Write/Render overlap detector | `_decode_guard.py` → `h13_write_begin/end`; `_vw_scroll.py:712`, `_vw_backend.py:519` → `h13_check_overlap_before_render` | Whether a worker is mid-`vol[i]=arr` when main thread enters render chain | `[H13-OVERLAP]` |
| **P2** | Overlap frequency counter | `_decode_guard.py` → `_H13_OVERLAP_COUNT` | Running count of P1 events | Included in P5 snapshot |
| **P3** | Decode-to-render age | `_decode_guard.py` → `_WRITE_TIMESTAMPS` + `h13_get_decode_age_ms`; `_vw_scroll.py:714`, `_vw_backend.py:521` | Time gap between slice write completion and its next render | `[H13-AGE]` (logged when age <5ms) |
| **P4** | grow() event marker | `pydicom_lazy_volume.py:397` | grow() occurrence, old→new slice count | `H13-GROW entry` |
| **P5** | Worker/queue pressure snapshot | `_vw_backend.py:206-224` via `_log_lazy_metrics_if_due` (every 1s) | Worker count, queue depth, pending count, overlap count/max, decode count/total ms | `[H13-P5]` |

### Toggle Inventory (Phase 2 — NOT active for Phase 1)

| ID | Toggle | Env var | What it tests | Status |
|----|--------|---------|--------------|--------|
| **T3** | Deep copy | `AIPACS_VTK_DEEP_COPY=1` | Breaks zero-copy link; tests H13-A necessary condition | Coded in `pydicom_lazy_volume.py:325,469` — **NOT active** |
| **T4** | Render gate | `AIPACS_RENDER_GATE=1` | Main thread acquires `_load_lock` around full render chain; tests H13-A fix direction | Coded in `_vw_scroll.py:719`, `_vw_backend.py:526` — **NOT active** |
| **T5** | Old-volume keep-alive | `AIPACS_KEEPALIVE_OLD_VOLUME=1` | Stashes old memmap after grow(); tests H13-C | Coded in `pydicom_lazy_volume.py:477` — **NOT active** |

---

## 4. Crash Signature Definition

A crash belongs to the **H13 family** if ALL of the following are present in the log:

1. `Fatal Python error: PyThreadState_Get: the function must be called with the GIL held`
2. Main-thread stack includes `set_slice` → VTK render chain (`SetSlice`, `Render`, `_flush_pending_wheel_slice_impl`, or `_on_lazy_slice_ready_impl`)
3. At least one worker thread in `pydicom_lazy_volume.py` (`_worker_loop`, `_load_slice_blocking`, or `_prepare_slice_for_volume`)
4. Active backend is `pydicom_2d` (FAST mode)
5. Series has multiple slices (not single-frame)

**Optional amplifiers** (strengthen H13 family membership):
- `dropped_frames_count` > 50
- `cpu` > 80%
- `H13-OVERLAP` events in preceding log
- `H13-AGE` events with age < 5ms
- Visual corruption reported before crash

The `_extract_crash_signature()` function in `test_fast_download_scroll_cpu_repro.py` is the automated parser for this signature.

---

## 5. Test File: `test_fast_download_scroll_cpu_repro.py`

### Role in H13

This is an **official H13 artifact** — the automated validation harness for the investigation.

### What it simulates

| Test | Simulates | Exercises real code? | Status |
|------|-----------|---------------------|--------|
| `test_fast_download_scroll_overlap_can_trigger_timer_storm` | Timer re-arm storm from repeated `_flush_progressive_grow_impl` failures during download+scroll overlap | **YES** — binds real `_VCProgressiveMixin` methods, injects failure via `_always_fail_grow` | **PASSES** (timer-storm fix: `_GROW_ERROR_MAX=5` bounded retry) |
| `test_log_signature_parser_matches_log17_pattern` | Crash signature extraction from production logs | **YES** — `_extract_crash_signature()` parses real log patterns | **PASSES** |
| `test_fast_download_scroll_callback_storm_signature` | Callback churn / drop-rate model under scroll+decode overlap | **NO** — pure mathematical model (75% drop rate hardcoded, no production code) | **XFAIL** (represents unfixed H13-E backpressure concern) |

### What it does NOT simulate

- VTK render calls (`SetSlice`, `Render`, `mark_vtk_modified`)
- Actual numpy memmap write/read race (no `vol[i]=arr` vs `Render()`)
- `grow()` pointer swap under concurrent render
- Real `_load_lock` contention
- GIL release/acquire during C-extension calls
- Actual CPU pressure from DM subprocess or decode workers

### Phase 1 usage

- Run the test suite as a **pre-flight check** before every Phase 1 live run to confirm probes don't regress existing behavior
- `_extract_crash_signature()` is used **post-run** to classify any crash log against the H13 family
- Timer-storm test confirms the `_GROW_ERROR_MAX` fix remains intact

### Phase 2 usage

- After each toggle test (T3/T4/T5), run the full test suite to confirm no regression
- If a toggle eliminates the live crash, extend the test file with a new test that exercises the toggle's mechanism:
  - T3 confirmed → add test for deep-copy fallback behavior
  - T4 confirmed → add test for render-gate lock contention bounds
  - T5 confirmed → add test for grow() keep-alive lifecycle
- `_extract_crash_signature()` classifies post-toggle crash logs to confirm same family or new family

### Future extensions (not yet implemented)

- `test_vtk_numpy_concurrent_access` — Phase 3 minimal VTK reproducer (only if Phase 2 is inconclusive)
- `test_render_gate_scroll_latency` — measures P95 set_slice with T4 active (Phase 2, Step 6)
- `test_backpressure_bounded_queue` — validates H13-E fix if chosen (post-Phase 2)

---

## 6. Phase 1 Procedure

### Environment

- **App command:** `python main.py`
- **Env vars:** NONE set (all toggles off, default decode serialization)
- **All H13 probes:** active (always-on by design)

### Scenario: Pipeline A (download + scroll overlap)

1. Launch the app
2. Open a patient with a large CT series (200+ slices)
3. While download is active, **scroll rapidly** through slices for 2+ minutes
4. If a second series exists, **drag-drop** it to a different viewer while scrolling
5. Observe for **at least 5 minutes** or until crash
6. Record: crash/no-crash, time-to-crash, visual artifacts, DnD behavior

### Log collection

After the run, extract all lines matching these patterns:

```
H13-OVERLAP          → P1/P2 overlap events
H13-AGE              → P3 tight decode-to-render age
H13-GROW             → P4 grow() events
[H13-P5]             → P5 pressure snapshots
viewer-lazy metrics  → dropped frames, decode timing
resource-summary     → CPU, RSS
stage-timing set_slice → set_slice latency
viewer-scroll sub-timing → render latency
Fatal Python error   → crash confirmation
```

### Pre-flight check

Before the live run:
```
python -m pytest tests/viewer/test_fast_download_scroll_cpu_repro.py -v
python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v
```
Both must pass (2 pass + 1 xfail for CPU repro; 45 pass for pipeline).

---

## 7. KPI Table Template

| KPI | Value | Notes |
|-----|-------|-------|
| **Crash** | **YES** | `Fatal Python error: PyThreadState_Get: GIL not held` — same family |
| **Time to crash** | ~4 s | Log spans 15:04:12.938–15:04:16.605 (viewer activity window) |
| **Visual corruption** | unknown | Log truncated before viewer open; user reported in prior runs |
| **Zoom/layout inconsistency** | unknown | Not captured in this log window |
| **Dropped frames** | 33–60 | viewport 0: 33, viewport 1: 47→55→60 (rising) |
| **Render P95** | 90.0 ms | `viewer-scroll sub-timing total=90.0ms` (2 samples: 31.9, 90.0) |
| **set_slice P95** | 93.1 ms | `stage-timing set_slice_total duration_ms=93.13` (max of 2 samples) |
| **CPU peak** | 75.1% | `resource-summary cpu=75.1%` (moderate — lower than Log 16's 110%) |
| **RSS peak** | 1284.6 MB | `resource-summary rss=1284.6MB` |
| **H13-OVERLAP event count** | **1** | P5 reports `overlap_count=1`; no explicit `[H13-OVERLAP]` log line (may be in truncated portion) |
| **H13-OVERLAP max duration** | **2.49 ms** | P5 reports `overlap_max_ms=2.49` |
| **Queue depth P95** | 0 | `[H13-P5] qsize=0` — all snapshots show 0 (workers idle by snapshot time) |
| **Decode-to-render age P5** | N/A | No `[H13-AGE]` events — no tight ages detected (all >5ms) |
| **grow() events** | 0 | No `H13-GROW` lines — no progressive grow during this run |
| **Active workers at crash** | 4 | `[H13-P5] workers=4` consistently; thread dump confirms worker threads |
| **Drag-and-drop performed** | no | Viewer series 201 vs DM series 202 divergence (series pre-assigned) |
| **DnD visual effect** | N/A | No drag-drop during this run |
| **Env vars active** | none | Baseline — no toggles |
| **Crash signature match** | **YES** | `viewer_2d.py:1345 set_slice` → `_vw_scroll.py:284` → `_flush_pending_wheel_slice_impl` → `wheelEvent` — identical to Log 16 |

---

## 8. Phase 1 Completion Criteria

Phase 1 is **complete** when ALL of the following are satisfied:

### Required evidence (mandatory)

- [x] **KPI table fully filled** — every row has a value (even if "N/A" or "unknown")
- [x] **Crash signature check** — identical to Log 16: `viewer_2d.py:1345 set_slice` → `_vw_scroll.py:284` → `_flush_pending_wheel_slice_impl` → `wheelEvent`
- [x] **H13-OVERLAP count recorded** — 1 event, max duration 2.49ms
- [x] **H13-AGE distribution recorded** — no tight ages observed (all decode-to-render ages >5ms)
- [x] **H13-P5 snapshots collected** — 8 snapshots across 2 viewports (workers=4, qsize=0, pending=0-1)
- [x] **grow() events listed** — 0 events (no progressive grow during run)
- [x] **CPU peak recorded** — 75.1% (moderate)
- [x] **Dropped frames recorded** — 33-60 per viewport (high, rising)
- [x] **Visual corruption observation** — unknown (log truncated, but reported in prior runs)
- [x] **Drag-and-drop tested** — no (viewer vs DM series divergence observed)
- [x] **Pre-flight tests pass** — `test_fast_download_scroll_cpu_repro.py` (18 pass, 1 xfail) and `test_fast_viewer_pipeline.py` (45 pass)

### Required analysis (mandatory)

- [x] **Hypothesis ranking update** — see §13 below
- [x] **Explicit Phase 2 recommendation** — **T4** (render gate) — overlap detected + crash → per §9 decision table row 1
- [x] **Crash family membership** — confirmed H13 family (identical crash signature, same thread, same call chain)

### Optional (informative but not blocking)

- [ ] Decode time distribution (min, P50, P95, max)
- [ ] Cache hit rate
- [ ] Time-to-first-frame

---

## 9. Decision Gate: Phase 1 → Phase 2

Phase 2 is entered ONLY after Phase 1 is complete per Section 8.

### Toggle selection rule

| Phase 1 outcome | Next toggle | Reason |
|------------------|-------------|--------|
| `H13-OVERLAP > 0` + crash | **T4** (render gate) | Overlap detected → test the fix directly |
| `H13-OVERLAP > 0` + no crash | **T3** (deep copy) | Overlap exists but not fatal → test if zero-copy is necessary condition |
| `H13-OVERLAP = 0` + crash | **T3** (deep copy) | No visible overlap → test necessary condition to discriminate A vs B |
| `H13-OVERLAP = 0` + crash correlates with grow() | **T5** (keep-alive) | No data-race overlap, but grow timing matches → test UAF |
| `H13-OVERLAP = 0` + no crash after 5 min | Increase CPU pressure or test on slower machine | Baseline is stable — need to widen the failure window |
| Any crash + `H13-AGE P5 < 5ms` + dropped > 100 | Add **H13-E throttle test** in parallel | Tight pacing confirmed — backpressure may be a cofactor |

### Precondition for every Phase 2 toggle run

1. Phase 1 KPI table is complete
2. Pre-flight tests pass
3. Toggle env var is set BEFORE app launch
4. Same Pipeline A scenario is followed
5. Post-run KPI table is filled and compared against Phase 1 baseline

---

## 10. File Map

| File | H13 role |
|------|----------|
| `modules/viewer/fast/_decode_guard.py:170-250` | P1/P2/P3 probe functions, T3/T4/T5 toggle flags, overlap stats |
| `modules/viewer/fast/pydicom_lazy_volume.py:23-28` | Probe/toggle imports |
| `modules/viewer/fast/pydicom_lazy_volume.py:314-325` | Zero-copy VTK link (`numpy_to_vtk deep=T3`) |
| `modules/viewer/fast/pydicom_lazy_volume.py:380-485` | `grow()` with P4 marker, T3 deep-copy, T5 keep-alive |
| `modules/viewer/fast/pydicom_lazy_volume.py:585-615` | `get_metrics_snapshot()` with H13 fields |
| `modules/viewer/fast/pydicom_lazy_volume.py:795-800` | `_load_slice_blocking` P1 write probes |
| `PacsClient/.../vtk_widget/_vw_backend.py:24-30` | Probe/toggle imports |
| `PacsClient/.../vtk_widget/_vw_backend.py:206-224` | P5 pressure snapshot in metrics logger |
| `PacsClient/.../vtk_widget/_vw_backend.py:515-545` | `_on_lazy_slice_ready_impl` P1/P3/T4 |
| `PacsClient/.../vtk_widget/_vw_scroll.py:18-20` | Probe/toggle imports |
| `PacsClient/.../vtk_widget/_vw_scroll.py:710-740` | `set_slice` scroll path P1/P3/T4 |
| `tests/viewer/test_fast_download_scroll_cpu_repro.py` | Test harness: timer-storm, signature parser, callback-storm model, Phase 2A pre-screening (19 tests) |
| `docs/stability/H13_WORKING_DOCUMENT.md` | This document |
| `docs/stability/H13_FOCUSED_RECOVERY_PLAN.md` | Focused companion: distilled findings, current priorities, pressure/stability run order |

---

## 11. Status Log

| Date | Phase | Activity | Result |
|------|-------|----------|--------|
| 2026-04-12 | 0 | Architecture/ownership map | Complete (in h13-plan.md Section 6 Phase 0) |
| 2026-04-12 | 1 | Probes P1-P4 deployed | Verified: h13_write_begin/end, h13_check_overlap, h13_get_decode_age, H13-GROW |
| 2026-04-12 | 1 | Probe P5 deployed | `[H13-P5]` log line added to `_log_lazy_metrics_if_due` |
| 2026-04-12 | 1 | Toggles T3/T4/T5 coded | All coded with env var guards — NOT active for Phase 1 |
| 2026-04-12 | 1 | Timer-storm fix | `_GROW_ERROR_MAX=5` in `_flush_progressive_grow_impl` — bounded retry |
| 2026-04-12 | 1 | Pre-flight tests | 3 CPU-repro tests (2 pass, 1 xfail); 45 viewer pipeline tests pass |
| 2026-04-12 | 1 | **PENDING: Live diagnostic run** | KPI table not yet filled |
| 2026-04-12 | 2 | Phase 2 revised: test-first | Phase 2A tests added (16 new), T5 keepalive cap (5 entries), `extract_h13_toggle_state()` parser added |
| 2026-04-12 | 2A | Phase 2A pre-screening tests | **18 pass, 1 xfail** — all probe/toggle/cap/signature validations green |
| 2026-04-12 | 1 | **Phase 1 live run (Log 18)** | **CRASH** — `PyThreadState_Get` at ~4s. overlap_count=1, max=2.49ms, dropped 33-60, set_slice max=93ms, CPU=75%. H13-A STRENGTHENED → **T4 selected** |
| 2026-04-12 | 2 | Phase 2 toggle selected | **T4 (render gate)** — per §9 decision: `overlap>0 + crash → T4` |
| 2026-04-12 | 2B | **T4 run (Log 19)** | **CRASH** — overlap=0 but crash persists. grow 50→54 at 15:44:45, crash at set_slice(51) 15:44:49 (~4s after grow). T4 eliminates write/render overlap but not the crash. H13-A weakened as sole cause, H13-C STRENGTHENED. |
| 2026-04-12 | 2B | T5 selected | **T5 (keep-alive)** — per §14 decision: crash+overlap=0+grow correlated → H13-C, test with T5 |
| 2026-04-12 | 2B | **T5 run (Log 20)** | **CRASH** — overlap=1, keepalive=0 events (no grow occurred), dropped 88-191 (worst yet). TOCTOU coherence gap: `render slice=107 current=109` immediately before crash. Crash stack: worker in numpy._clip. User reports scroll feel improved. H13-C **WEAKENED** (no grow → crash is grow-independent). H13-B **ELEVATED** (VTK/numpy concurrent C-level access). **State/coherence investigation** next. |
| 2026-04-12 | 2C | **T6 ON run (Log 21-A)** | **CRASH (early)** — same family (`PyThreadState_Get`). Crash occurred ~1.0s from first scroll activity. P5: workers=4, qsize=10→3, pending=14→6, overlap_count=0 in this short window. Classify T6 as **B: valid hypothesis, invalid/untested implementation** (no behavior-safe instrumentation existed yet). |
| 2026-04-12 | 2C | **T6 OFF run (Log 21-B)** | **NO crash in this run**, but severe pressure: CPU peak 140.9%, dropped up to 1538, probe p95=83.78ms, P5 overlap_count up to 329 and overlap_max_ms up to 39256.77. Confirms strong H13-E amplifier behavior. |
| 2026-04-12 | 2C | **T6 instrumentation-only deployed** | Added `[H13-T6-DIAG]` at `_on_lazy_slice_ready_impl` insertion point + `stale_abort_count` counter in P5 snapshots. **No behavior change / no early return**. |
| 2026-04-12 | 2C | **Focused recovery plan created** | Added `docs/stability/H13_FOCUSED_RECOVERY_PLAN.md` to keep the team aligned on what is proven, what remains plausible, which KPIs matter, and the exact next-run order (T6 diag → P1 booster off → P2 throttle → T3 only if still needed). |
| 2026-04-12 | 2C | **Counter split: stale_condition_count vs stale_abort_count** | `_stale_render_abort_count` was only incremented when toggle=ON, making T6-OFF `stale_abort_count=0` uninformative. **Fix:** added `_stale_condition_count` (always-on, toggle-independent — increments on `reason=stale` or `mismatch` regardless of toggle) and kept `_stale_render_abort_count` for actual aborts only. P5 log now shows both `stale_cond_count=N stale_abort_count=N`. T6-DIAG now emits at `logger.debug` for non-stale calls (not `logger.info`) to reduce log noise. These changes make the next T6 diagnostic run able to answer "how frequently does stale render fire?" in OFF mode for the first time. |

---

## 12. Phase 2 — Revised (Test-First, Semi-Automated)

### Design principle

Phase 2 is split into two sub-phases:

- **Phase 2A (test-harness narrowing)** — automated, no app launch required. Uses `test_fast_download_scroll_cpu_repro.py` to validate probe infrastructure, toggle wiring, and crash-signature parsing BEFORE any expensive manual run.
- **Phase 2B (manual runtime validation)** — one targeted toggle run chosen by Phase 2A results + Phase 1 KPI data. Clean-log required. Full KPI table recorded.

Manual runs are the **second** step, not the first. The test harness narrows which toggle to run.

### 12.1 Phase 2A — Test-Harness Pre-Screening

**Purpose:** Confirm that H13 infrastructure is correctly wired, so manual toggle runs produce trustworthy data.

**Command:**
```
python -m pytest tests/viewer/test_fast_download_scroll_cpu_repro.py -v
```

**Expected: 18 pass, 1 xfail.** Any failure is a blocking finding — do NOT proceed to manual runs.

#### Phase 2A test inventory

| Test class | Test name | What it validates | Blocks |
|------------|-----------|-------------------|--------|
| `TestPhase2A_ToggleWiring` | `test_toggle_flags_inactive_in_test_env` | T3/T4/T5 flags are OFF in test env | All manual toggle runs |
| `TestPhase2A_ToggleWiring` | `test_toggle_env_var_names_match_code` | Env var names in source match documented names | All manual toggle runs |
| `TestPhase2A_OverlapProbe` | `test_no_overlap_when_no_write_active` | P1 does NOT false-positive | Phase 1 KPI trust |
| `TestPhase2A_OverlapProbe` | `test_overlap_detected_during_active_write` | P1 correctly detects overlap | Phase 1 KPI trust |
| `TestPhase2A_OverlapProbe` | `test_overlap_counter_accumulates` | P2 counter increments correctly | Phase 1 overlap count |
| `TestPhase2A_OverlapProbe` | `test_max_duration_tracks_worst_case` | P2 tracks worst-case duration | Phase 1 max-duration KPI |
| `TestPhase2A_DecodeAge` | `test_unknown_slice_returns_negative` | P3 returns -1 for unknown slice | Phase 1 age KPI |
| `TestPhase2A_DecodeAge` | `test_recently_written_slice_has_small_age` | P3 age is small immediately after write | Phase 1 age KPI |
| `TestPhase2A_DecodeAge` | `test_age_increases_over_time` | P3 age grows with elapsed time | Phase 1 age KPI |
| `TestPhase2A_TimerStormUnderToggles` | `test_timer_storm_bounded_baseline` | Timer-storm fix works without toggles | Regression gate |
| `TestPhase2A_TimerStormUnderToggles` | `test_timer_storm_bounded_with_deep_copy_flag` | Timer-storm fix holds under T3 flag | T3 safety |
| `TestPhase2A_CrashSignatureExtended` | `test_signature_detects_no_crash_clean_run` | Signature parser handles clean runs | Post-run analysis |
| `TestPhase2A_CrashSignatureExtended` | `test_signature_detects_crash_under_toggle` | Signature parser handles crash+toggle logs | Post-run analysis |
| `TestPhase2A_CrashSignatureExtended` | `test_signature_no_crash_with_render_gate` | Signature parser handles T4 success logs | Post-run analysis |
| (module) | `test_h13_toggle_state_parser` | `extract_h13_toggle_state()` parses H13-INIT, GROW, OVERLAP, AGE, P5 markers | Post-run automation |
| `TestPhase2A_GrowKeepAliveCap` | `test_keepalive_list_capped_at_5` | T5 keepalive stash capped at 5 entries (memory safety) | T5 safety |

#### Phase 2A results interpretation

| Phase 2A result | Meaning | Action |
|-----------------|---------|--------|
| All 18 pass, 1 xfail | Infrastructure is sound | Proceed to Phase 2A analysis → toggle selection |
| Any `ToggleWiring` test fails | Toggle env var wiring is broken | Fix before any manual run |
| Any `OverlapProbe` test fails | P1/P2 data is unreliable | Fix P1/P2, re-run Phase 1 live |
| Any `DecodeAge` test fails | P3 age data is unreliable | Fix P3, re-run Phase 1 live |
| `TimerStormUnderToggles` fails | Timer-storm fix regressed under toggle | Investigate before activating toggle |
| `GrowKeepAliveCap` fails | T5 memory leak risk | Fix cap before T5 manual run |
| `callback_storm_signature` PASSES (was xfail) | Drop-rate model no longer exceeds threshold | The xfail condition resolved — review whether H13-E backpressure concern changed |

### 12.2 Phase 2A Analysis — Toggle Selection

After Phase 2A tests pass AND Phase 1 KPI data is available, apply this decision table to choose the first manual toggle run.

#### Primary decision table (Phase 1 KPIs → toggle)

| Phase 1 KPI pattern | Primary hypothesis | First toggle | Reason |
|---------------------|--------------------|-------------|--------|
| `H13-OVERLAP > 0` **AND** crash | H13-A (zero-copy race) confirmed active | **T4** (render gate) | Overlap is detected AND fatal → test the fix direction directly |
| `H13-OVERLAP > 0` **AND** no crash | H13-A present but non-fatal | **T3** (deep copy) | Overlap exists but isn't crashing → test if removing zero-copy changes behavior |
| `H13-OVERLAP = 0` **AND** crash | H13-A not visible at probe granularity | **T3** (deep copy) | Overlap may be too brief for P1 to catch → T3 tests the broader necessary condition |
| `H13-OVERLAP = 0` **AND** crash correlates with `H13-GROW` timing | H13-C (grow UAF) | **T5** (keep-alive) | No data-race overlap but grow timing matches → test UAF directly |
| `H13-OVERLAP = 0` **AND** no crash after 5 min | Baseline is stable | Increase CPU pressure, reduce worker count, or test slower machine | Need to widen failure window |
| Any pattern **AND** `H13-AGE P5 < 5ms` **AND** dropped > 100 | H13-E (pacing) is active | Run **T3 or T4** but also log queue depth closely | Backpressure is a cofactor — record queue depth changes |

#### Secondary consideration: grow() correlation

If Phase 1 shows `H13-GROW` events clustered within 2 seconds before crash:
- Add **T5** (keep-alive) as a parallel or follow-up run alongside the primary toggle
- If primary toggle is T3 and T3 eliminates crash, T5 is deprioritized
- If primary toggle is T3 and T3 does NOT eliminate crash, T5 rises to next

#### What the test harness tells us about toggle priority

| Test harness observation | Toggle priority implication |
|--------------------------|---------------------------|
| `test_overlap_detected_during_active_write` passes (P1 works) | P1 data from Phase 1 is trustworthy → use overlap count for decision |
| `test_timer_storm_bounded_with_deep_copy_flag` passes | T3 flag doesn't break progressive grow path → safe to activate T3 |
| `test_keepalive_list_capped_at_5` passes | T5 memory is bounded → safe to activate T5 |
| `callback_storm_signature` still xfail (drop_rate>0.35) | H13-E backpressure concern is still live → record queue depth in manual run |
| `callback_storm_signature` unexpectedly PASSES | H13-E backpressure concern resolved → lower priority for pacing investigation |

### 12.3 Phase 2B — Manual Runtime Validation

Phase 2B runs ONLY after Phase 2A tests pass and the toggle is selected per §12.2.

#### Pre-run requirements (mandatory)

1. **Clean log files.** Before launching the app:
   ```powershell
   # Clear old H13 data from logs
   Remove-Item "user_data\logs\viewer_diagnostics.log*" -ErrorAction SilentlyContinue
   ```
2. **Set the chosen toggle env var** (exactly one):
   ```powershell
   # T3: $env:AIPACS_VTK_DEEP_COPY = "1"
   # T4: $env:AIPACS_RENDER_GATE = "1"
   # T5: $env:AIPACS_KEEPALIVE_OLD_VOLUME = "1"
   ```
3. **Phase 2A tests pass** (18 pass, 1 xfail)
4. **Phase 1 KPI table is complete** (all rows filled)

#### Run procedure

1. Launch: `python main.py`
2. Verify `[H13-INIT] toggles:` in console shows the correct toggle active
3. Open a patient with a large CT series (200+ slices)
4. While download is active, **scroll rapidly** for 2+ minutes
5. Perform at least one **drag-drop** series switch
6. Observe for **at least 5 minutes** or until crash
7. Record visual corruption and zoom/layout behavior **separately** from crash (they are independent observations)

#### Observation recording (mandatory — separate fields)

| Observation | Record |
|-------------|--------|
| **Crash occurrence** | yes / no (fatal `PyThreadState_Get`) |
| **Time to crash** | seconds from first scroll, or N/A |
| **Visual corruption** | yes / no / unknown — describe: offset? bad pixels? wrong image? |
| **Zoom/layout inconsistency** | yes / no / unknown — describe: wrong zoom? extent? viewport mismatch? |
| **Image update behavior** | normal / stale / frozen — does scrolling show new slices correctly? |
| **DnD behavior** | normal / wrong zoom / stale image / crash — describe |

**Important:** "No crash" does NOT mean "no problem." Visual corruption and zoom/layout issues must be recorded independently. A toggle that eliminates the crash but introduces image staleness or zoom errors is a **partial** result, not a success.

#### Post-run KPI extraction

```powershell
# Set working dir
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
$log = "user_data\logs\viewer_diagnostics.log"

# Overlap count
Select-String "\[H13-OVERLAP\]" $log | Measure-Object | Select-Object -ExpandProperty Count

# Overlap max duration
Select-String "\[H13-OVERLAP\]" $log | ForEach-Object { if ($_ -match 'age_ns=(\d+)') { [int64]$Matches[1] } } | Measure-Object -Maximum | Select-Object -ExpandProperty Maximum

# Decode-to-render age (tight ages)
Select-String "\[H13-AGE\]" $log | ForEach-Object { if ($_ -match 'age_ms=([\d.]+)') { [double]$Matches[1] } } | Measure-Object -Minimum -Maximum -Average

# grow() events
Select-String "H13-GROW entry" $log | Measure-Object | Select-Object -ExpandProperty Count

# P5 pressure snapshots
Select-String "\[H13-P5\]" $log | Select-Object -Last 5

# Crash?
Select-String "PyThreadState_Get|Fatal Python error" $log | Select-Object -First 3

# Dropped frames
Select-String "dropped_frames_count" $log | Select-Object -Last 3

# CPU / RSS peak
Select-String "resource-summary" $log | Select-Object -Last 3
```

#### Automated analysis (Python)

After extracting the log, run toggle-state parser for structured comparison:

```python
# In Python console or script
from tests.viewer.test_fast_download_scroll_cpu_repro import extract_h13_toggle_state
log_text = open(r"user_data\logs\viewer_diagnostics.log").read()
state = extract_h13_toggle_state(log_text)
print(state)
# Returns: {"init_line": ..., "grow_count": ..., "overlap_count": ..., "age_min_ms": ..., "p5_snapshots": ..., "t5_keepalive_events": ...}
```

#### Phase 2B KPI comparison table (fill after EACH run)

| KPI | Phase 1 (baseline) | Phase 2B (toggle: ___) | Delta | Interpretation |
|-----|--------------------|-----------------------|-------|----------------|
| Crash | | | | |
| Time to crash | | | | |
| Visual corruption | | | | |
| Zoom/layout | | | | |
| Image update | | | | |
| DnD behavior | | | | |
| H13-OVERLAP count | | | | |
| H13-OVERLAP max duration | | | | |
| H13-AGE P5 (min) | | | | |
| Queue depth P95 | | | | |
| Dropped frames | | | | |
| Render P95 | | | | |
| set_slice P95 | | | | |
| CPU peak | | | | |
| RSS peak | | | | |
| grow() events | | | | |
| Active workers at crash | | | | |

### 12.4 Post-Toggle Decision Gate

After each Phase 2B manual run, apply this decision table to determine the next step.

| Toggle tested | Crash? | Visual corruption? | Zoom/layout? | Next action |
|---------------|--------|-------------------|-------------|-------------|
| **T3** (deep copy) | **No** | No | No | Zero-copy confirmed as root cause. Proceed to **T4** (render gate) to validate fix direction. |
| **T3** | **No** | Yes (stale image) | Yes | Zero-copy is root cause but deep copy breaks live updates. Proceed to **T4** — render gate preserves zero-copy. |
| **T3** | **Yes** | — | — | Zero-copy is NOT the sole cause. Pivot: if grow() correlated → **T5**; otherwise → **H13-B** (VTK standalone reproducer, Phase 3). |
| **T4** (render gate) | **No** | No | No | **Fix A (render-chain gate) is viable.** Measure P95 latency increase. If ≤5ms → ship as fix. If >5ms → consider Fix B (snapshot). |
| **T4** | **No** | No | Yes (zoom) | Gate scope needs narrowing — lock is held too long or covering wrong operations. Debug lock scope. |
| **T4** | **Yes** | — | — | Lock scope insufficient OR race is outside render chain. Investigate: (a) widen gate to cover more operations, or (b) pivot to Fix B/F. |
| **T5** (keep-alive) | **No** | No | No | **H13-C (grow UAF) confirmed.** Implement proper keep-alive or VTK pipeline reset (Fix E). |
| **T5** | **Yes** | — | — | H13-C is NOT the cause. Return to T3/T4 results for next hypothesis. |
| **Any** | — | — | — (but render P95 increased >10ms) | Toggle adds unacceptable latency. Note as constraint for fix design — may need Fix B (snapshot) or Fix F (backpressure) instead. |

### 12.5 Completion Criteria

Phase 2 is COMPLETE when ALL of the following are met:

- [ ] Phase 2A tests pass (18 pass, 1 xfail)
- [ ] Phase 1 KPI table is filled (all rows)
- [ ] At least ONE Phase 2B toggle run completed
- [ ] Phase 2B KPI comparison table filled for the tested toggle  
- [ ] Visual corruption recorded separately from crash occurrence
- [ ] Zoom/layout behavior recorded separately from crash occurrence
- [ ] Image update behavior (stale/frozen/normal) recorded
- [ ] DnD behavior recorded
- [ ] Decision gate (§12.4) applied — next action determined
- [ ] H13 working document status log updated with Phase 2B results
- [ ] Hypothesis ranking updated based on experimental evidence

### 12.6 Execution Order

| Step | Action | Prerequisite | Output |
|------|--------|-------------|--------|
| 1 | Run Phase 2A tests | — | 18 pass, 1 xfail confirmation |
| 2 | **Run Phase 1 live** (if not already done) | Phase 2A pass | Phase 1 KPI table |
| 3 | Apply §12.2 decision table to Phase 1 KPIs | Phase 1 KPIs | Selected toggle (T3, T4, or T5) |
| 4 | Clear logs, set toggle env var | Toggle selected | Clean log file |
| 5 | Run Phase 2B manual procedure (§12.3) | Step 4 | Observations + log file |
| 6 | Extract KPIs + run toggle state parser | Step 5 | Phase 2B KPI table + automated analysis |
| 7 | Fill Phase 2B comparison table (§12.3) | Step 6 | Side-by-side Phase 1 vs Phase 2B |
| 8 | Apply decision gate (§12.4) | Step 7 | Next action (another toggle, fix, or Phase 3) |
| 9 | Update H13 working document | Step 8 | Status log + hypothesis ranking update |

---

## 13. Phase 1 Results — Hypothesis Ranking (Log 18)

### Evidence summary

- **overlap_count = 1** with **max duration = 2.49ms** — P1 detected a confirmed write/render temporal overlap
- **Crash = YES** — identical `PyThreadState_Get` crash signature (same thread, same call chain as Log 16)
- **grow() = 0** — no progressive grow events, ruling out grow-triggered UAF for this specific crash instance
- **CPU = 75.1%** — moderate; crash occurred at lower CPU than Log 16's 110% → race is not purely CPU-gated
- **Dropped frames = 33–60** — render consumer still saturated
- **Decode overlap up to 5** — H12-1 markers show up to 5 concurrent decodes (lazy + booster combined)
- **set_slice max = 93ms** — very high, indicates render chain under pressure
- **Viewer series 201 vs DM active 202** — series divergence present throughout

### Hypothesis ranking after Phase 1

| Hypothesis | Pre-Phase 1 | After T4+T5 | Reason |
|------------|-------------|-------------|--------|
| **H13-A** (zero-copy race) | Strongest | **REFRAMED — NECESSARY COFACTOR** | T4 eliminated `_load_lock`-scoped overlaps (P5 overlap=0) but crash persisted. T5 run (T4 OFF) shows overlap_count=1 again. The race is NOT at `_load_lock` scope — it's between VTK C++ `Render()` (GIL released) and worker threads writing `vol[i]=arr`. Python `threading.Lock` cannot synchronize GIL-released C code. |
| **H13-B** (VTK/C-level race) | Secondary | **ELEVATED — CO-PRIMARY** | Crash stack: worker in `numpy._clip` (C, GIL released) while main thread in VTK Render() (C, GIL released). Both access numpy-backed memory. Python 3.13 strict GIL validation detects the inconsistency. Fundamental mechanism. |
| **H13-C** (grow UAF) | Secondary | **WEAKENED — MINOR** | No grow events in Log 20, crash occurred anyway. Grow correlation in T4/Log 19 was coincidental. |
| **H13-D** (CPU amplifier) | Amplifier | **WEAKENED** | CPU only 40.6% in Log 20, crash still happened. Not required. |
| **H13-E** (backpressure) | Mechanism | **STRENGTHENED — KEY AMPLIFIER** | Dropped 88–191 (3× Phase 1), decode overlap_after avg=2.77. Creates stale callbacks → TOCTOU coherence gaps → unnecessary Render() calls that widen the C-level race window. |
| **NEW: coherence/TOCTOU** | N/A | **ELEVATED — DIRECT TRIGGER** | `render slice=107 current=109` at 16:26:29.647, crash ~100ms later. Guard allows stale renders → each enters VTK Render() (GIL released) while workers write to same backing array. |

### Phase 2 recommendation

Per §9 decision table: **`H13-OVERLAP > 0` + crash → T4 (render gate)**.

T4 acquires `_load_lock` around the full render critical section (mark_vtk_modified + SetSlice + Render). If the crash disappears under T4 → the lock gap between worker writes and main-thread render is **confirmed as the root cause** → Fix A (render-chain gate) is validated.

---

## 14. T4 Run Procedure (Phase 2B — Run 3)

### Pre-run checklist

- [x] Phase 2A tests pass (18 pass, 1 xfail)
- [x] Phase 1 KPI table complete (§7)
- [x] T4 implementation verified (both scroll + lazy callback paths use try/finally)
- [ ] Clean logs (step 1 below)
- [ ] Toggle env var set (step 2 below)

### Exact run instructions

```powershell
# Step 1: Clean logs
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
Remove-Item "user_data\logs\viewer_diagnostics.log*" -ErrorAction SilentlyContinue

# Step 2: Set T4 toggle
$env:AIPACS_RENDER_GATE = "1"

# Step 3: Verify no other toggles
$env:AIPACS_VTK_DEEP_COPY = $null
$env:AIPACS_KEEPALIVE_OLD_VOLUME = $null

# Step 4: Launch
python main.py
```

After launch, verify the **first** `[H13-INIT]` line in the console shows:
```
[H13-INIT] toggles: deep_copy=False render_gate=True keepalive=False
```

### Test scenario (same as Phase 1)

1. Open a patient with a large CT series (200+ slices)
2. While download is active, **scroll rapidly** through slices for 2+ minutes
3. If a second series exists, **drag-drop** it to a different viewer
4. Observe for **at least 5 minutes** or until crash
5. Record observations **during** the run (not just after)

### What to observe and record

| Observation | Record |
|-------------|--------|
| **Crash** | yes / no (`Fatal Python error: PyThreadState_Get`) |
| **Time to crash** | seconds from first scroll, or "survived 5 min" |
| **Visual corruption** | yes / no / unknown — describe: offset? bad pixels? wrong image? |
| **Zoom/layout** | yes / no / unknown — describe: wrong zoom? extent? viewport mismatch? |
| **Image update** | normal / stale / frozen — does scrolling show new slices correctly? |
| **Scroll feel** | smooth / choppy / significantly degraded — subjective responsiveness |
| **DnD behavior** | normal / wrong zoom / stale image / crash |

### Post-run KPI extraction

```powershell
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
$log = "user_data\logs\viewer_diagnostics.log"

# Crash?
Select-String "PyThreadState_Get|Fatal Python error" $log | Select-Object -First 3

# Init line (confirm T4 active)
Select-String "\[H13-INIT\]" $log | Select-Object -First 1

# Overlap count (should drop to 0 under T4)
Select-String "\[H13-P5\]" $log | Select-Object -Last 4

# Overlap explicit events
Select-String "\[H13-OVERLAP\]" $log | Measure-Object | Select-Object -ExpandProperty Count

# set_slice timing
Select-String "set_slice_total" $log | ForEach-Object { if($_.Line -match 'duration_ms=([\d.]+)') { [double]$Matches[1] } } | Measure-Object -Maximum -Average | Format-List

# Render sub-timing
Select-String "viewer-scroll sub-timing" $log | Select-Object -Last 5

# Dropped frames
Select-String "dropped_frames_count" $log | Select-Object -Last 5 | ForEach-Object { if($_.Line -match 'dropped_frames_count=(\d+)') { $Matches[1] } }

# CPU / RSS
Select-String "resource-summary" $log | Select-Object -Last 3
```

### T4 KPI comparison table

| KPI | Phase 1 (baseline, Log 18) | T4 run (Log 19) | Delta | Interpretation |
|-----|---------------------------|-------------------|-------|----------------|
| Crash | YES | **YES** | same | T4 did NOT eliminate crash |
| Time to crash | ~4s | ~4s (after grow) | same | Crash ~4s after grow event |
| Visual corruption | unknown | unknown | — | Log truncated, not observed |
| Zoom/layout | unknown | unknown | — | Not captured |
| Image update | N/A | N/A | — | — |
| Scroll feel | N/A | N/A | — | — |
| DnD behavior | N/A | N/A | — | — |
| H13-OVERLAP count | 1 | **0** | **-1** | **Gate eliminated overlaps but crash persists** |
| H13-OVERLAP max ms | 2.49 | **0.00** | **-2.49** | No write/render overlap under T4 |
| Dropped frames | 33–60 | 39–87 | ~same/higher | Render pipeline still saturated |
| Render P95 | 90.0 ms | 111.5 ms | +21.5 | Higher — lock contention adds latency |
| set_slice P95 | 93.1 ms | 113.2 ms | +20.1 | Higher — consistent with gate overhead |
| CPU peak | 75.1% | 80.3% | +5 | Similar |
| RSS peak | 1284.6 MB | 1016.7 MB | -268 | Lower (shorter run) |
| grow() events | 0 | **1** (50→54) | **+1** | **grow() occurred 4s before crash** |
| Workers at snapshot | 4 | 4 | same | — |

### T4 Decision Criteria

| T4 result | Meaning | Next action |
|-----------|---------|-------------|
| **No crash + overlap=0** | **T4 render gate eliminates both the overlap and the crash.** Lock gap is confirmed as root cause. | Measure latency impact. If set_slice P95 increase ≤10ms → **Fix A (render-chain gate) is viable — proceed to fix design.** If >10ms → consider narrower gate (Fix B: snapshot). |
| **No crash + overlap>0** | Gate scope is too narrow — lock isn't covering the full critical section. | Widen gate scope (currently covers mark_vtk_modified → SetSlice → Render). Check if apply_default_window_level or overlay updates are outside the gate. |
| **Crash + overlap=0** | Gate prevents the overlap but crash persists → race is NOT between `_load_lock`-protected writes and the render chain. | Pivot: H13-B (VTK standalone reproducer, Phase 3) or investigate other shared state (`_pixel_cache`, VTK internal pipeline caches). |
| **Crash + overlap>0** | Gate scope is insufficient — lock isn't covering the actual racing paths. | Review lock coverage: is `_load_lock` the right lock? Are there VTK internal paths that bypass Python-level synchronization? |
| **No crash + visual corruption (stale/frozen images)** | Gate prevents crash but breaks image pipeline — lock introduces deadlock or stale-data issue. | This is a **partial success** for causal proof. Investigate whether lock ordering or conditional rendering can preserve correctness. |
| **No crash + set_slice P95 increased >30ms** | Gate works but adds unacceptable scroll latency. | Fix A scope is too broad. Proceed to Fix B (render-side snapshot: copy only the active slice before render) or Fix F (decode throttle during scroll). |

# H13-OVERLAP events
Select-String "H13-OVERLAP" user_data\logs\viewer_diagnostics.log | Measure-Object | Select-Object Count

# H13-AGE tight ages
Select-String "H13-AGE" user_data\logs\viewer_diagnostics.log | Select-Object -Last 10

# H13-GROW events
Select-String "H13-GROW" user_data\logs\viewer_diagnostics.log | Measure-Object | Select-Object Count

# H13-T5 keepalive events (if T5 active)
Select-String "H13-T5" user_data\logs\viewer_diagnostics.log | Measure-Object | Select-Object Count

# H13-P5 pressure snapshots
Select-String "H13-P5" user_data\logs\viewer_diagnostics.log | Select-Object -Last 5

# Dropped frames
Select-String "dropped_frames" user_data\logs\viewer_diagnostics.log | Select-Object -Last 3

# Resource summary
Select-String "resource-summary" user_data\logs\viewer_diagnostics.log | Select-Object -Last 3

# Crash check
Select-String "Fatal Python error" user_data\logs\viewer_diagnostics.log
```

#### Post-run automated analysis

After collecting the log, run the toggle-state parser:

```python
from tests.viewer.test_fast_download_scroll_cpu_repro import (
    _extract_crash_signature,
    extract_h13_toggle_state,
)
log_text = open("user_data/logs/viewer_diagnostics.log").read()
print("=== Crash signature ===")
print(_extract_crash_signature(log_text))
print("=== Toggle state ===")
print(extract_h13_toggle_state(log_text))
```

#### Phase 2B KPI table (one per toggle run)

| KPI | Phase 1 baseline | Toggle run value | Delta | Notes |
|-----|------------------|------------------|-------|-------|
| **Toggle active** | none | T3/T4/T5 | — | Env var name |
| **Crash** | ___ | ___ | — | yes/no |
| **Time to crash** | ___ s | ___ s | ___ s | Δ time |
| **Visual corruption** | ___ | ___ | — | **record separately from crash** |
| **Zoom/layout inconsistency** | ___ | ___ | — | **record separately from crash** |
| **Image update** | ___ | ___ | — | normal/stale/frozen |
| **Dropped frames** | ___ | ___ | ___ | |
| **Render P95** | ___ ms | ___ ms | ___ ms | |
| **set_slice P95** | ___ ms | ___ ms | ___ ms | Critical for T4 (lock contention) |
| **CPU peak** | ___ % | ___ % | ___ % | |
| **RSS peak** | ___ MB | ___ MB | ___ MB | Critical for T5 (keepalive memory) |
| **H13-OVERLAP count** | ___ | ___ | ___ | Did overlaps change? |
| **H13-OVERLAP max ms** | ___ | ___ | ___ | |
| **Queue depth P95** | ___ | ___ | ___ | |
| **Decode-to-render age P5** | ___ ms | ___ ms | ___ ms | |
| **grow() events** | ___ | ___ | ___ | |
| **Crash signature match** | ___ | ___ | — | Same H13 family? |

#### Post-run regression check

After the manual run, unset the toggle env var and run:
```
Remove-Item Env:AIPACS_VTK_DEEP_COPY   # or whichever was set
python -m pytest tests/viewer/test_fast_download_scroll_cpu_repro.py tests/viewer/test_fast_viewer_pipeline.py -v
```
Must still show 18 pass + 1 xfail + 45 pass.

### 12.4 Phase 2B Decision Gate — After First Toggle Run

| Toggle run result | Hypothesis update | Next action |
|-------------------|-------------------|-------------|
| **T3 (deep copy) — no crash, no visual issues after 5+ min** | H13-A **CONFIRMED** as necessary condition | Run **T4** (render gate) to validate fix direction |
| **T3 — no crash BUT visual corruption/staleness** | H13-A confirmed BUT deep copy causes rendering artifacts | Run **T4** (render gate) — it preserves zero-copy while adding sync |
| **T3 — crash at same time, same KPIs** | H13-A **WEAKENED** — zero-copy is NOT the necessary condition | Run **T5** (keep-alive) to test H13-C, then consider H13-B (minimal VTK reproducer) |
| **T3 — crash but takes significantly longer** | H13-A is a **factor** but not sole cause | Run **T5** (keep-alive) in parallel — multiple causes may overlap |
| **T4 (render gate) — no crash, set_slice P95 increase ≤ 5ms** | **Fix A is viable** — render-chain gate eliminates the race with acceptable overhead | Proceed to Fix A implementation |
| **T4 — no crash, set_slice P95 increase > 10ms** | Gate works but scope is too broad | Narrow gate scope (Fix B: render-side snapshot) or add backpressure (Fix F) |
| **T4 — crash persists** | Race is NOT between `_load_lock`-protected writes and the render chain | Pivot to H13-B (standalone VTK reproducer) or H13-E (pacing toggle) |
| **T5 (keep-alive) — no crash** | H13-C **CONFIRMED** — use-after-free from grow() | Implement Fix E (viewport-state reset on grow) |
| **T5 — crash persists** | H13-C **REJECTED** | Return to T3/T4 or escalate to Phase 3 (minimal simulation) |

**Important nuance:** "Crash at same time with same KPIs" does NOT necessarily mean the toggle has no effect. CPU pressure (H13-D) introduces variance in time-to-crash. A toggle result is only considered "same" if at least 2 manual runs produce consistent crash timing (within ±30%). A single run that crashes at a similar time could be coincidence under CPU variance. When in doubt, repeat.

### 12.5 Phase 2 Completion Criteria

Phase 2 is **NOT complete** unless ALL of the following are recorded:

- [ ] **Phase 2A test results recorded** — 18 pass, 1 xfail (screenshot or log)
- [ ] **Toggle selection reasoning recorded** — which toggle was chosen and why, referencing Phase 1 KPI data
- [ ] **Clean log confirmed** — old logs deleted before manual run
- [ ] **Phase 2B KPI table filled** — all rows have values, compared against Phase 1 baseline
- [ ] **Visual corruption recorded separately from crash** — not conflated
- [ ] **Zoom/layout behavior recorded separately from crash** — not conflated
- [ ] **Crash signature check run** — `_extract_crash_signature()` + `extract_h13_toggle_state()` results recorded
- [ ] **Post-run regression tests pass** — 18+1 + 45
- [ ] **Hypothesis ranking updated** — each of H13-A/B/C/D/E updated based on toggle result
- [ ] **Next action chosen** — per §12.4 decision gate, with specific toggle or fix direction
- [ ] **Results written back into this document** — KPI tables added to Status Log (§11)

### 12.6 Phase 2 Execution Order

| Step | Type | Activity | Prerequisite |
|------|------|----------|-------------|
| 2A-1 | Auto | Run `pytest tests/viewer/test_fast_download_scroll_cpu_repro.py -v` | None |
| 2A-2 | Auto | Verify: 18 pass, 1 xfail | 2A-1 |
| 2A-3 | Analysis | Apply §12.2 decision table + Phase 1 KPIs → choose toggle | 2A-2 + Phase 1 complete |
| 2A-4 | Record | Document toggle choice + reasoning in §11 Status Log | 2A-3 |
| 2B-1 | Manual | Clean logs | 2A-4 |
| 2B-2 | Manual | Set toggle env var | 2B-1 |
| 2B-3 | Manual | Run Pipeline A scenario (5+ min) | 2B-2 |
| 2B-4 | Analysis | Extract KPIs (PowerShell commands in §12.3) | 2B-3 |
| 2B-5 | Auto | Run `_extract_crash_signature()` + `extract_h13_toggle_state()` | 2B-4 |
| 2B-6 | Analysis | Fill Phase 2B KPI table, compare against Phase 1 baseline | 2B-5 |
| 2B-7 | Analysis | Apply §12.4 decision gate → update hypotheses, choose next action | 2B-6 |
| 2B-8 | Auto | Post-run regression tests | 2B-7 |
| 2B-9 | Record | Write all results into §11 Status Log | 2B-8 |

---

## §15 T5 Run — Keep-Alive Old Volume (Run 4)

### 15.1 Rationale

T4 (render gate) proved that write/render overlap (`_load_lock`-scoped) is NOT the sole crash cause:
- overlap_count dropped 1→0 under T4
- **Crash persisted** with identical stack trace
- **Key new evidence:** grow(50→54) at 15:44:45.396, crash at set_slice(51) 15:44:49.478 (4.08s after grow)

This strongly implicates **H13-C (grow UAF)**:
1. `grow()` creates a new memmap, copies data, replaces `self._volume`
2. VTK's internal pipeline caches may still hold a stale pointer to the OLD memmap's numpy array
3. The old memmap is freed by Python GC
4. On the next `Render()`, VTK reads from freed memory → `PyThreadState_Get: GIL not held`

T5 keeps the OLD volume alive by stashing its reference in `_old_volumes_keepalive` (capped at 5). If the crash disappears, the UAF from dangling grow pointers is confirmed.

### 15.2 What T5 does (code reference)

File: `modules/viewer/fast/pydicom_lazy_volume.py` lines 477-486

```python
if _H13_KEEPALIVE and old_volume_ref is not None:
    if not hasattr(self, "_old_volumes_keepalive"):
        self._old_volumes_keepalive = []
    self._old_volumes_keepalive.append(old_volume_ref)
    if len(self._old_volumes_keepalive) > 5:
        self._old_volumes_keepalive = self._old_volumes_keepalive[-5:]
    logger.info("[H13-T5] keepalive stashed old volume ref (total=%d)", len(self._old_volumes_keepalive))
```

Activated by: `AIPACS_KEEPALIVE_OLD_VOLUME=1`

### 15.3 T5 run command (one-liner)

```powershell
cd "c:\AI-Pacs codes\aipacs-pydicom2d"; Remove-Item "user_data\logs\viewer_diagnostics.log*" -ErrorAction SilentlyContinue; $env:AIPACS_KEEPALIVE_OLD_VOLUME = "1"; $env:AIPACS_RENDER_GATE = $null; $env:AIPACS_VTK_DEEP_COPY = $null; & ".venv\Scripts\python.exe" main.py
```

**Environment state:** T5 ON, T4 OFF, T3 OFF. All probes (P1–P5) always-on.

### 15.4 Test scenario

Same as Phase 1 & T4:
1. Open a patient with a multi-series study (CT preferred)
2. Drag-drop a series into a viewer (triggers progressive download)
3. Scroll through slices continuously during download
4. Wait for download to complete (grow() events will fire)
5. Continue scrolling for 2+ minutes after completion
6. Target: 5+ minutes total, reproduce crash or confirm stability

### 15.5 KPI extraction (post-run)

```powershell
$log = "user_data\logs\viewer_diagnostics.log"

# T5 keepalive events (MUST be present)
Select-String "H13-T5" $log | Measure-Object | Select-Object Count

# H13-INIT line (verify T5 is active)
Select-String "H13-INIT" $log

# Crash check
Select-String "Fatal Python error" $log

# grow events
Select-String "H13-GROW" $log

# Overlap events (should still occur — T4 is OFF)
Select-String "H13-OVERLAP" $log | Measure-Object | Select-Object Count

# set_slice timing
Select-String "set_slice_total" $log | ForEach-Object { if($_.Line -match 'duration_ms=([\d.]+)') { [double]$Matches[1] } } | Measure-Object -Maximum -Average | Format-List

# Resource
Select-String "resource-summary" $log | Select-Object -Last 3

# Dropped frames
Select-String "dropped_frames_count" $log | Select-Object -Last 5 | ForEach-Object { if($_.Line -match 'dropped_frames_count=(\d+)') { $Matches[1] } }
```

### 15.6 T5 KPI comparison table

| KPI | Phase 1 (baseline) | T4 run | T5 run (Log 20) | Delta vs Phase 1 | Interpretation |
|-----|--------------------|---------|--------------------|-------------------|----------------|
| Crash | YES | YES | **YES** | same | T5 did NOT eliminate crash |
| H13-T5 keepalive events | 0 | 0 | **0** | 0 | No grow occurred → no keepalive to stash |
| H13-OVERLAP count | 1 | 0 | **1** | same | Overlap present again (T4 OFF) |
| H13-OVERLAP max ms | 2.49 | 0.00 | **1.52** | -0.97 | Slightly shorter overlap |
| grow() events | 0 | 1 | **0** | same | **No grow → crash is grow-independent** |
| Dropped frames | 33–60 | 39–87 | **88–191** | **3×+ worse** | Extreme backpressure |
| Render P95 | 90.0 ms | 111.5 ms | 83.5 ms | -6.5 | Similar to baseline |
| set_slice P95 | 93.1 ms | 113.2 ms | 83.5 ms | -9.6 | Similar (no gate overhead) |
| CPU peak | 75.1% | 80.3% | **40.6%** | -34.5 | Much lower CPU |
| RSS peak | 1284.6 MB | 1016.7 MB | **1128.6 MB** | -156 | Similar |
| **TOCTOU coherence gap** | not measured | not measured | **1 instance** (slice=107, current=109, gap=2) | N/A | **NEW: stale render immediately before crash** |
| decode overlap_after max | not measured | not measured | **3** (avg 2.77) | N/A | High concurrent decode load |
| Crash thread stack | numpy._clip (worker) | not captured | **numpy._clip** (worker tid=0x721c) | same | Worker in numpy C during crash |

### 15.7 T5 Decision criteria

| T5 result | Meaning | Hypothesis update | Next action |
|-----------|---------|-------------------|-------------|
| **No crash + keepalive >0 + grow >0** | Old volume freed by GC was the cause. Keeping it alive prevents UAF. | **H13-C CONFIRMED** | Implement **Fix E**: viewport-state reset on grow — force VTK to release internal cache refs to old volume before swap. |
| **No crash + keepalive=0** | T5 was NOT active — invalid run. | N/A | Re-run with correct env var. Check H13-INIT log line for `keepalive=1`. |
| **Crash + keepalive >0 + same timing** | Old volume lifetime is NOT the issue — VTK cache holds something else, or the race is on a different object. | **H13-C WEAKENED** | Pivot to **H13-B** (standalone VTK reproducer in Phase 3) or try **T3+T4+T5 combined** to eliminate all three simultaneously. |
| **Crash + keepalive >0 but takes much longer** | Keepalive mitigates but doesn't eliminate — multiple UAF sources or stale VTK cache entries beyond the memmap. | **H13-C PARTIAL** | Consider extended keepalive (cap >5) or Force VTK `Modified()` on all pipeline objects post-grow. |
| **No crash + RSS increases significantly (>500MB)** | Fix works but leaks memory — each grow stashes ~50-200MB of old volume. | **H13-C CONFIRMED but fix needs refinement** | Fix E must actively invalidate VTK cache refs rather than keeping old data alive permanently. |

### 15.8 KPI changes that specifically confirm or weaken H13-C

**Confirms H13-C:**
- Crash disappears (primary signal)
- `[H13-T5]` keepalive events present in log (T5 was active)
- grow() events still occurred (the trigger was present but didn't cause crash)
- RSS may increase slightly (expected — old volumes retained)
- Overlap count may still be >0 (T4 is OFF) — unrelated to H13-C

**Weakens H13-C:**
- Crash persists with identical stack trace despite keepalive active
- `[H13-T5]` keepalive events present (confirms old volumes ARE alive)
- grow() events still occurred → old volume survived but crash happened anyway
- This would mean the freed memory is NOT from the grow() volume swap

**Ambiguous (need more data):**
- Crash persists but keepalive=0 → invalid run, T5 wasn't active
- No crash but no grow events → grow didn't fire, can't prove H13-C
- Crash at very different timing → possibly different crash, check stack

---

## §16 T6 Classification + Pressure-Control Experiments (H13-E)

### 16.1 T6 classification (required)

**Classification: (B) Valid hypothesis, invalid implementation (current state).**

Justification:
1. **T6 ON crashed immediately** (same crash family), suggesting ordering/logic risk rather than a clean causal win.
2. **T6 OFF did not crash in this single run** but showed extreme pressure (CPU 140.9%, dropped frames up to 1538, set_slice probe p95=83.78ms).
3. **Overlap + pressure signals remain dominant** in OFF (`overlap_count` 329, `overlap_max_ms` 39256.77ms), indicating H13-E amplification is very strong.
4. Before this update, T6 had no dedicated diagnostics at the insertion point, so ON failure could not be interpreted safely.

Conclusion: stale-render TOCTOU remains a plausible trigger, but the previous ON result is not decision-grade without instrumentation proof.

### 16.2 Mandatory T6 instrumentation (implemented, behavior unchanged)

Location: `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py` in `_on_lazy_slice_ready_impl`, **exactly after** `should_render_ready_slice(...)` passes and before render-chain execution.

Logged on every pass via `[H13-T6-DIAG]`:
- `toggle_state` (on/off)
- `ready_slice`
- `requested_slice`
- `live_current_slice` (fresh `GetSlice()` re-read)
- `guard_current_slice`
- `abort_decision` (diagnostic shadow decision only)
- `reason` (`stale` / `mismatch` / `other`)
- `viewer_id`
- `thread_id`

Log level: `INFO` when `reason=stale/mismatch`; `DEBUG` otherwise (avoids flood on non-stale hot path).

Counters in `[H13-P5]` (updated 2026-04-12):
- `stale_cond_count` — **always-on, toggle-independent**: increments on `reason=stale/mismatch` regardless of env toggle. Answers "how often does stale render occur?" in T6-OFF runs. First valid measurement will be the next diagnostic run.
- `stale_abort_count` — only increments when `AIPACS_STALE_RENDER_ABORT=1` (toggle ON) AND reason is stale/mismatch. Tracks actual aborts.

**Patch note:** the previous `stale_abort_count` was toggle-gated, making T6-OFF value of `0` uninformative (not a real 0-event result — just the counter never incremented with toggle=OFF). The `stale_cond_count` counter fixes this.

Important: **No behavior change was introduced** (no abort return path added).

### 16.3 Pressure-control experiment design (high-priority H13-E)

#### Run P1 — Booster OFF

Goal: remove booster-side decode pressure.

Execution: set `AIPACS_DISABLE_BOOSTER=1` before launching the app.  
Already wired: `ImageSliceBooster.set_active()` returns immediately when this env var is set.  
Keep all other H13 probes/diagnostics active.

Expected discriminator:
- If crash frequency drops materially with lower pressure, H13-E is a dominant amplifier/trigger gate.

#### Run P2 — Prefetch window reduction

Goal: reduce the booster's decode backlog without eliminating it entirely.

**Important:** `AIPACS_MAX_DECODE_THREADS=1` is already the **current default** (serialized). The T6-OFF baseline was already running at N=1. Setting it again does not add new information.

Primary P2 knob: reduce the `ImageSliceBooster` window from ±20 → ±5 via `AIPACS_BOOSTER_WINDOW=5` (add support if not yet present), or set `AIPACS_DISABLE_BOOSTER=1` and compare with P1 to isolate whether it's the total load or the window size that matters.

Expected discriminator:
- Lower overlaps, lower dropped frames, and delayed/absent crash would favor H13-E dominance.

### 16.4 KPI comparison matrix (required)

| KPI | T6 OFF (Log 21-B) | T6 ON (Log 21-A) | P1 (booster off) | P2 (window/worker) |
|---|---:|---:|---:|---:|
| Crash (yes/no) | **No** | **Yes** |  |  |
| Time to crash | N/A | **~1.0s** |  |  |
| CPU peak | **140.9%** | 5.2% observed post-crash only |  |  |
| Dropped frames | **up to 1538** | N/A (short run; no stable metrics window) |  |  |
| set_slice_p95 | **83.78ms** (scroll probe) | N/A (insufficient samples) |  |  |
| H13-OVERLAP count | **329** (P5 counter) | 0 (short window) |  |  |
| overlap_max_ms | **39256.77** | 0.00 (short window) |  |  |
| stale_cond_count ¹ | **not measured** (pre-fix) | N/A | | |
| stale_abort_count ¹ | 0 (toggle OFF → always 0) | N/A (pre-instrument run) |  |  |

¹ `stale_cond_count` = stale/mismatch events regardless of toggle (always-on, added 2026-04-12).  
  `stale_abort_count` = actual aborts (only non-zero when `AIPACS_STALE_RENDER_ABORT=1`).  
  **The next T6 diagnostic run will be the first to populate `stale_cond_count`.**

**Automated KPI extraction (added 2026-04-12):**  
`extract_h13_run_kpis(log_text)` in `tests/viewer/test_fast_download_scroll_cpu_repro.py` parses all H13 log markers into a flat 25-key dict (crash, build, toggles, pressure, P5 max-across-snapshots, T6 diagnostic events, event counts).  
`format_h13_kpi_comparison({"label": kpis, ...})` renders a markdown comparison table.  
Usage after a run:
```powershell
.venv\Scripts\python.exe -c "
from tests.viewer.test_fast_download_scroll_cpu_repro import extract_h13_run_kpis, format_h13_kpi_comparison
import json, sys
log = open(sys.argv[1]).read()
print(json.dumps(extract_h13_run_kpis(log), indent=2))
" path\to\run.log
```

### 16.5 P1 Experiment Results (2026-04-13)

**Setup:** `AIPACS_DISABLE_BOOSTER=1`, all H13 toggles OFF (T3/T4/T5/T6 = OFF).  
**Protocol:** Pipeline A (download patient → scroll during download → trigger progressive display + series switches).

| KPI | Baseline (T6-OFF) | P1 #1 (booster OFF) | P1 #2 (booster OFF) |
|---|---:|---:|---:|
| Crash | **Yes** | **Yes** | **Yes** |
| Crash (GIL) | **Yes** | — (stderr lost) | **No** (Qt exception) |
| CPU peak (%) | 100.00 | 12.20 | 128.70 |
| Dropped frames | 1538 | 171 | 171 |
| set_slice p95 (ms) | 83.78 | 91.20 | 92.00 |
| Overlap count | 329 | 3 | 0 |
| Overlap max (ms) | 39256.77 | 1.40 | 0.00 |
| Stale cond count | — | 8 | 8 |
| Stale abort count | — | 0 | 0 |
| T6 stale events | 0 | 14 | 18 |
| T6 mismatch events | 0 | 0 | 0 |
| Queue max | 20.00 | 17.00 | 20.00 |
| Pending max | 21.00 | 21.00 | 20.00 |
| P5 snapshots | 97 | 97 | 86 |
| Overlap events | 329 | 3 | 0 |
| Grow events | 0 | 8 | 6 |
| Booster disabled | No | **Yes** | **Yes** |

**UI observations:**
- Run #1: Survived 2 full series downloads + scroll before crashing at 3rd series.
- Run #2: Smoother scrolling than Run #1, black images appeared near end (WL decode failure), crashed during 1st series scroll while 3rd downloading.
- Both runs: Scrolling felt responsive, significantly fewer frame drops than baseline.

**Key findings:**
1. **Overlap eliminated:** Booster OFF → overlap_count dropped from 329 → 3 → 0 across runs. Overlap_max dropped from 39.2 **seconds** to 0.
2. **Dropped frames 91% lower:** 1538 → 171 in both P1 runs — consistent and reproducible.
3. **P1 Run #2 crash is NOT a GIL crash:** stderr captured `"Qt has caught an exception thrown from an event handler"` — no `Fatal Python error`, no `PyThreadState_Get`. The Python traceback was swallowed by Qt. `_aipacs_excepthook` did NOT fire.
4. **WL spike at crash point:** Last 2 set_slice calls showed WL=356.2ms and 356.4ms (normal: 0.0ms). This correlates with user-reported black images immediately before crash.
5. **Stale condition is constant:** `stale_cond_count_max=8` in both runs, all 14-18 T6 diagnostic events are `reason=stale` (zero mismatch). This is independent of booster state.
6. **CPU in Run #2 was very high:** 128.7% peak, 44 samples >90%. The app startup phase had sustained 86-94% CPU for ~20 seconds.

**Crash type divergence:**
- Baseline crash: `Fatal Python error: PyThreadState_Get: GIL not held` — C-level fatal, process killed.
- P1 Run #2 crash: `Qt has caught an exception` — Python exception in event handler, Qt caught it. This is a DIFFERENT failure mode. The booster OFF condition changed the crash CHARACTER, not just its frequency.
- P1 Run #1 crash type: Unknown (stderr not captured). Could be either type.

### 16.6 Decision goal mapping

1. **Is stale-render TOCTOU necessary?**
    - Use `stale_abort_count` + crash/time-to-crash deltas between ON/OFF after instrumentation.
2. **Is pressure (H13-E) dominant?**
    - Use P1/P2 impact on CPU, dropped frames, overlap_count/max, and crash behavior.
3. **Are both required?**
    - If T6 diagnostics show frequent stale decisions AND P1/P2 materially reduce crashes, both are likely required contributors.
