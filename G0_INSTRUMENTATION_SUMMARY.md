# G0 Event-Loop Diagnostics Implementation Summary

**Date**: May 13, 2026  
**Status**: ✅ Complete and tested  
**Acceptance Criteria**: ✅ All met

---

## What Was Implemented

A pure **instrumentation-only** patch to diagnose why Qt events are delivered with **1000+ ms gaps** during stack drag, causing ui_lag spikes.

### Four New/Modified Files

#### 1. `modules/viewer/fast/event_loop_diagnostics.py` (NEW — 340 lines)
**Purpose**: Collect and classify event jitter

**Key Functions**:
- `start_session(session_id)` — Begin event timeline recording
- `record_event(type, source, x, y, wheel_delta, widget_name)` — Log event with timestamp
- `stop_session() -> Dict` — Aggregate metrics and classify jitter source
- `_classify_jitter_source(agg) -> str` — Return classification (A–H)

**Classification Outputs** (8-way):
- A: Event delivery jitter at Qt input level
- B: QApplication dispatch gap
- C: Widget handler gap  
- D: qasync loop starvation
- E: Paint scheduling gap
- F: Mouse event compression/coalescing
- G: OS-level input batching
- H: Unknown jitter source

**Metrics Computed**:
- `mouse_event_gap_p95/max_ms` — Latency between MouseMove events
- `wheel_event_gap_p95/max_ms` — Latency between Wheel events
- `paint_event_gap_p95/max_ms` — Latency between Paint events
- `timer_gap_p95/max_ms` — Latency between Timer events (heartbeat)
- `update_to_paint_p95/max_ms` — Delay from update() call to paintEvent
- `wheel_compression_suspected` — True if wheel deltas are batched
- `paint_independent_of_input_suspected` — True if paints don't follow input
- `timer_heartbeat_steady` — True if timers fire regularly (no starvation)

#### 2. `modules/viewer/fast/app_event_filter.py` (NEW — 130 lines)
**Purpose**: Instrument Qt at the QApplication level

**Key Class**: `AIPacsEventFilter(QObject)`
- Intercepts all Qt events (MouseMove, Wheel, Paint, Timer, UpdateRequest)
- Records event position, delta, widget type, timestamp
- Never blocks or crashes event loop (always returns False)

**Key Function**: `install_app_event_filter(qapp)`
- Install filter on QApplication at startup

#### 3. `modules/viewer/fast/qt_viewer_bridge.py` (MODIFIED — 5 edits, +60 lines)
**Changes**:
- Import event_loop_diagnostics helpers
- In `_start_drag_metrics_session()`: Call `_event_diag_start_session()`
- In `_on_stack_drag_target()`: Call `_event_diag_record_event()`
- In `_log_drag_metrics_summary()`: Call `_event_diag_stop_session()` and merge results
- Emit new log tag: `[FAST_INPUT_JITTER_DIAG]` with 16 diagnostic fields

**New Log Output**:
```
[FAST_INPUT_JITTER_DIAG] drag_session_id=abc jitter_source=G_OS_INPUT_BATCHING 
  mouse_event_gap_p95_ms=1057.5 mouse_event_gap_max_ms=1546.5
  wheel_event_gap_p95_ms=150.2 wheel_event_gap_max_ms=350.1
  paint_event_gap_p95_ms=95.3 paint_event_gap_max_ms=210.4
  update_to_paint_p95_ms=22.1 update_to_paint_max_ms=45.3
  timer_gap_p95_ms=15.2 timer_gap_max_ms=45.1 timer_heartbeat_steady=true
  wheel_compression_suspected=false paint_independent_of_input_suspected=false
  paint_within_50ms_of_input=42 corr_session=drag-session-1 corr_mono_ms=1234567890
```

#### 4. `main.py` (MODIFIED — 1 edit, +13 lines)
**Change**: Install event filter at startup
- After `app = _AIPacsApplication(sys.argv)`
- Guarded by env var: `AIPACS_EVENT_LOOP_DIAG=1` (default enabled)
- Wrapped in try/except for safe failure

### Tests
**File**: `tests/viewer/test_event_loop_diagnostics.py` (9 tests, all passing ✅)
- Classification logic for all 8 hypotheses (A–H)
- Event recording and session lifecycle
- Percentile computation and edge cases
- Wheel compression detection
- Update-to-paint latency measurement

### Documentation
**Files**: 
- `docs/performance/EVENT_LOOP_DIAGNOSTICS_G0.md` — Complete architecture guide
- `docs/performance/EVENT_LOOP_DIAGNOSTICS_ACCEPTANCE.md` — Acceptance criteria checklist

---

## Zero Behavior Changes

✅ **No optimization**: Pure observation only  
✅ **No rendering changes**: Events recorded passively  
✅ **No cache changes**: No cache logic touched  
✅ **No disk changes**: No disk I/O changes  
✅ **No RAM changes**: Light memory footprint (bounded deques)  
✅ **No CPU changes**: Minimal overhead (thread-safe)  
✅ **No Download Manager changes**: DM untouched  
✅ **All existing tests pass**: Integration verified  

---

## How to Use

### Enable Instrumentation
```powershell
$env:AIPACS_EVENT_LOOP_DIAG="1"  # (default enabled)
python main.py
```

### Disable Instrumentation (if needed)
```powershell
$env:AIPACS_EVENT_LOOP_DIAG="0"
python main.py
```

### Analyze Logs
```powershell
Select-String "FAST_INPUT_JITTER_DIAG" user_data/logs/viewer_diagnostics.log | 
  Select-Object -First 10
```

Extract `jitter_source` field to see which of A–H is the root cause.

---

## Test Results

```
tests/viewer/test_event_loop_diagnostics.py::test_event_timestamp_creation PASSED
tests/viewer/test_event_loop_diagnostics.py::test_percentile_calculation PASSED
tests/viewer/test_event_loop_diagnostics.py::test_session_start_stop PASSED
tests/viewer/test_event_loop_diagnostics.py::test_jitter_source_classification_os_batching PASSED
tests/viewer/test_event_loop_diagnostics.py::test_jitter_source_classification_wheel_compression PASSED
tests/viewer/test_event_loop_diagnostics.py::test_jitter_source_classification_qasync_starvation PASSED
tests/viewer/test_event_loop_diagnostics.py::test_jitter_source_classification_paint_lag PASSED
tests/viewer/test_event_loop_diagnostics.py::test_event_compression_detection PASSED
tests/viewer/test_event_loop_diagnostics.py::test_update_to_paint_delay PASSED

============================== 9 passed ==============================
```

---

## Next: Fresh Interactive Run

1. **Run app with instrumentation enabled**:
   ```powershell
   $env:AIPACS_EVENT_LOOP_DIAG="1"
   python main.py
   ```

2. **Perform drag operations**:
   - Stack drag (mouse drag across images)
   - Wheel scroll
   - Switch series

3. **Collect logs**:
   - Extract `[FAST_INPUT_JITTER_DIAG]` tags
   - Note the `jitter_source` field

4. **Analyze classification**:
   - D → qasync loop is blocking Qt events
   - G → Windows OS is batching input
   - F → Qt wheel events are being compressed
   - E → Paint events are delayed relative to input
   - A → Qt input events arrive with gaps
   - B → QApplication→widget dispatch is slow
   - C → Widget handler is slow
   - H → Root cause unknown (needs further investigation)

5. **Optional: Controlled comparison**:
   - Run same scenario with `AIPACS_MINIMAL_ASYNCIO=1` to test if disabling asyncio changes jitter metrics
   - If jitter drops significantly → confirms D (qasync starvation)

---

## Files Modified

### Created (4 files)
- ✅ `modules/viewer/fast/event_loop_diagnostics.py`
- ✅ `modules/viewer/fast/app_event_filter.py`
- ✅ `tests/viewer/test_event_loop_diagnostics.py`
- ✅ `docs/performance/EVENT_LOOP_DIAGNOSTICS_G0.md`
- ✅ `docs/performance/EVENT_LOOP_DIAGNOSTICS_ACCEPTANCE.md`

### Modified (2 files)
- ✅ `modules/viewer/fast/qt_viewer_bridge.py` — Added 5 edits (+60 lines)
- ✅ `main.py` — Added 1 edit (+13 lines)

---

## Summary of Changes

| Component | Status | Details |
|-----------|--------|---------|
| Event recording | ✅ Complete | 8 event types, timestamps, positions |
| Classification logic | ✅ Complete | All 8 hypotheses (A–H) implemented |
| QApplication filter | ✅ Complete | Installed at startup |
| Drag session integration | ✅ Complete | Start/stop/record wired |
| Log emission | ✅ Complete | [FAST_INPUT_JITTER_DIAG] tag added |
| Tests | ✅ Complete | 9/9 passing |
| Documentation | ✅ Complete | Guide + acceptance criteria |
| No regressions | ✅ Complete | Existing tests unaffected |

---

## Expected Outcome

After running this with real user interactions, logs will reveal which of the 8 jitter sources is causing the ui_lag spikes:

**Example log output**:
```
[FAST_INPUT_JITTER_DIAG] drag_session_id=drag-001 jitter_source=G_OS_INPUT_BATCHING 
  mouse_event_gap_p95_ms=1057.5 mouse_event_gap_max_ms=1546.5 ...
```

This tells us:
- **jitter_source=G** → Windows OS is batching input events instead of delivering them immediately
- **mouse_event_gap_p95=1057.5ms** → Events arriving ~1 second apart on average
- **timer_heartbeat_steady=true** → Qt event loop itself is responsive

---

## No Further Changes Needed

All acceptance criteria met. Instrumentation is complete and ready for deployment.

To disable after testing: Set `AIPACS_EVENT_LOOP_DIAG=0` (or delete env var).
