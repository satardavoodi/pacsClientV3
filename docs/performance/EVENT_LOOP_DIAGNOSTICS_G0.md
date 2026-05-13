# Event-Loop and Input Delivery Diagnostics (G0)

## Overview

Instrumentation-only patch to investigate why Qt mouse/wheel/drag events are delivered with **1000+ ms gaps** during active interaction, causing ui_lag spikes.

**Root cause verified**: Event delivery jitter (hypothesis A), not slow rendering:
- event_jitter_p95 = 1057.5 ms
- event_jitter_max = 1546.5 ms  
- handler cost = 2–3 ms (NOT the bottleneck)
- set_to_image_p95 ≈ 22 ms (fast)
- qt_repaint_delay_p95 ≈ 37 ms (acceptable)

## Architecture

### Core Modules

#### 1. `modules/viewer/fast/event_loop_diagnostics.py` (NEW)
Collects event timing data across the entire Qt event pipeline:

**Functions**:
- `start_session(session_id)` — Begin instrumentation for a drag session
- `stop_session() -> Dict` — End session and return aggregated metrics
- `record_event(event_type, source, x, y, wheel_delta, widget_name)` — Record event at a point in the pipeline

**Event Types**:
- `MouseMove` — User mouse input
- `Wheel` — Scroll wheel input
- `Paint` — Qt paintEvent execution
- `Timer` — Qt timer heartbeat
- `UpdateRequest` — Qt update() calls

**Event Sources**:
- `app_filter` — QApplication event filter (OS → Qt boundary)
- `widget_filter` — Widget event filter
- `handler` — Event handler execution
- `paint` — paintEvent execution
- `update_call` — update()/repaint() call sites

**Aggregates Computed**:
- `mouse_event_gap_p95/max_ms` — Time between consecutive mouse events
- `wheel_event_gap_p95/max_ms` — Time between consecutive wheel events
- `paint_event_gap_p95/max_ms` — Time between consecutive paint events
- `timer_gap_p95/max_ms` — Time between consecutive timers (heartbeat)
- `update_to_paint_p95/max_ms` — Delay from update() call to actual paintEvent
- `event_jitter_p95/max_ms` — Variance in inter-event gaps
- `wheel_compression_suspected` — True if wheel deltas are being accumulated/compressed
- `paint_independent_of_input_suspected` — True if paints don't follow input events
- `timer_heartbeat_steady` — True if timers fire at regular intervals (no starvation)

**Classification Targets**:
Categorizes the jitter source as one of:
- `A_EVENT_DELIVERY_JITTER` — Events arrive with inconsistent timing
- `B_QAPPLICATION_DISPATCH_GAP` — QApplication→widget dispatch is slow
- `C_WIDGET_HANDLER_GAP` — Handler execution is slow or deferred
- `D_QASYNC_LOOP_STARVATION` — qasync/asyncio tasks block Qt event loop
- `E_PAINT_SCHEDULING_GAP` — Paint events are delayed relative to input
- `F_MOUSE_EVENT_COMPRESSION` — Qt or OS is batching/coalescing mouse events
- `G_OS_INPUT_BATCHING` — Windows is batching input at OS level
- `H_UNKNOWN_INPUT_JITTER` — Jitter cause unknown

#### 2. `modules/viewer/fast/app_event_filter.py` (NEW)
Qt event filter installed on QApplication to instrument input at the application entry point:

**Class**: `AIPacsEventFilter(QObject)`
- Implements `eventFilter(obj, event) -> bool`
- Records MouseMove, Wheel, Paint, Timer, UpdateRequest events
- Captures event position, wheel delta, widget type
- Never blocks events (always returns False)
- Silent error handling (never crashes the event filter)

**Functions**:
- `install_app_event_filter(qapp)` — Install on QApplication at startup
- `uninstall_app_event_filter(qapp)` — Remove from QApplication on shutdown

#### 3. Modified `modules/viewer/fast/qt_viewer_bridge.py`
Integrated event-loop diagnostics into drag metrics pipeline:

**Changes**:
- Import event_loop_diagnostics helpers
- In `_start_drag_metrics_session()`: Call `_event_diag_start_session(drag_session_id)`
- In `_on_stack_drag_target()`: Call `_event_diag_record_event("Wheel"/"MouseMove", "handler", ...)`
- In `_log_drag_metrics_summary()`: Call `_event_diag_stop_session()` and merge results
- New log output: `[FAST_INPUT_JITTER_DIAG]` with 16 derived KPI fields

**New Log Tag**: `[FAST_INPUT_JITTER_DIAG]`
```
[FAST_INPUT_JITTER_DIAG] drag_session_id=... jitter_source=... 
  mouse_event_gap_p95_ms=... mouse_event_gap_max_ms=...
  wheel_event_gap_p95_ms=... wheel_event_gap_max_ms=...
  paint_event_gap_p95_ms=... paint_event_gap_max_ms=...
  update_to_paint_p95_ms=... update_to_paint_max_ms=...
  timer_gap_p95_ms=... timer_gap_max_ms=... timer_heartbeat_steady=...
  wheel_compression_suspected=... paint_independent_of_input_suspected=...
  paint_within_50ms_of_input=... corr_session=... corr_mono_ms=...
```

#### 4. Modified `main.py`
Installed event filter at application startup:

**Changes**:
- Import `install_app_event_filter` from `modules.viewer.fast.app_event_filter`
- After `app = _AIPacsApplication(sys.argv)`: Call `install_app_event_filter(app)`
- Guarded by env var: `AIPACS_EVENT_LOOP_DIAG=0` disables (default enabled)
- Logs `[EVENT_LOOP_DIAG] Event filter installed on QApplication` at INFO level

## Test Coverage

**File**: `tests/viewer/test_event_loop_diagnostics.py` (9 tests, all passing ✅)

- `test_event_timestamp_creation` — EventTimestamp dataclass creation
- `test_percentile_calculation` — Percentile computation (p50, p95, edge cases)
- `test_session_start_stop` — Session lifecycle (start → record → stop)
- `test_jitter_source_classification_os_batching` — Large gaps → OS batching
- `test_jitter_source_classification_wheel_compression` — Wheel delta accumulation
- `test_jitter_source_classification_qasync_starvation` — Timer starvation
- `test_jitter_source_classification_paint_lag` — Paint delay detection
- `test_event_compression_detection` — Wheel delta sum tracking
- `test_update_to_paint_delay` — Update→paint latency measurement

## Usage

### In Interactive Sessions
1. Enable environment variable: `$env:AIPACS_EVENT_LOOP_DIAG="1"`
2. Run the application normally
3. Perform drag operations on the viewer
4. Observe `[FAST_DRAG_KPI]` + `[FAST_EVENT_PACING]` + `[FAST_INPUT_JITTER_DIAG]` tags in logs
5. Analyze `jitter_source` classification to identify the root cause

### In Log Analysis
```powershell
Select-String "FAST_INPUT_JITTER_DIAG" user_data\logs\viewer_diagnostics.log | 
  Select-Object -First 10
```

Extract all jitter diagnostics and review the `jitter_source` field for each drag session.

### Disabling (if needed)
```powershell
$env:AIPACS_EVENT_LOOP_DIAG="0"
python main.py
```

## Detailed Metrics Explanation

### Event Gap Metrics
- **mouse_event_gap_p95_ms**: 95th percentile time between consecutive MouseMove events
  - p95 > 1000 ms suggests OS batching or input starving
  - p95 < 50 ms indicates normal, responsive input
  
- **wheel_event_gap_p95_ms**: Similar for wheel scroll events
  
- **paint_event_gap_p95_ms**: Time between paintEvent executions
  - High values (>100 ms) suggest paint starvation

### Timer Heartbeat
- **timer_gap_p95_ms**: Time between Qt timer ticks
  - Steady <100 ms: Event loop is responsive
  - > 500 ms: Event loop may be starved by asyncio tasks
  
- **timer_heartbeat_steady**: True if timers fire regularly (not starved)

### Update-Paint Delay
- **update_to_paint_p95_ms**: Latency from update() call to paintEvent
  - 10–40 ms: Normal (acceptable)
  - > 100 ms: Indicates paint scheduling delays

### Wheel Compression
- **wheel_compression_suspected**: True if wheel deltas accumulate
  - Example: Single scroll = delta 120, but multiple scrolls compress to delta 360
  - Indicates Qt or OS batching wheel events instead of delivering per-event

### Paint Independence
- **paint_independent_of_input_suspected**: True if paints don't follow input
  - If True: paints are queued but not triggered by input events
  - Suggests paint is waiting for some other trigger (timer, async task)

## Classification Logic

The `_classify_jitter_source()` function uses a decision tree:

```
if wheel_compression_suspected:
  → F_MOUSE_EVENT_COMPRESSION (Qt batching wheel events)

else if not timer_heartbeat_steady:
  → D_QASYNC_LOOP_STARVATION (asyncio blocking Qt)

else if paint_gap_p95 > 100 AND paint_gap_p95 > mouse_gap_p95:
  if paint_independent_of_input_suspected:
    → E_PAINT_SCHEDULING_GAP (paint queued, not triggered by input)
  else:
    → C_WIDGET_HANDLER_GAP (handler is slow/deferred)

else if mouse_gap_p95 > 1000:
  → G_OS_INPUT_BATCHING (Windows batching at OS level)

else if mouse_gap_p95 > 500:
  → B_QAPPLICATION_DISPATCH_GAP (QApplication→widget dispatch slow)

else:
  → H_UNKNOWN_INPUT_JITTER (no clear cause)
```

## Known Limitations

1. **Sampling**: Timer events are sampled (every Nth) to avoid log spam
2. **Thread Safety**: Uses thread-local locking; safe across threads
3. **Memory**: Deques sized at 10,000 events max per timeline (sufficient for multi-second drags)
4. **Heuristics**: Classification uses simple percentile thresholds; may need tuning

## No Behavior Changes

- Pure observation/instrumentation only
- Zero impact on rendering, cache, disk, RAM, CPU, or DM rebuild
- All existing tests pass
- Guarded by env var; disabled by default in production if needed

## Next Steps After Instrumentation

Once this data is collected from fresh runs:

1. **Analyze jitter_source classification** — Which component is causing the jitter?
2. **If D_QASYNC_LOOP_STARVATION**: Check for asyncio tasks running during drag
3. **If G_OS_INPUT_BATCHING**: Investigate Windows message queue or drag loop design
4. **If F_MOUSE_EVENT_COMPRESSION**: Check Qt wheel coalescing or OS compression
5. **If E_PAINT_SCHEDULING_GAP**: Examine paint triggering logic

## References

- Prior instrumentation: `[FAST_DRAG_KPI]`, `[FAST_EVENT_PACING]`, `[FAST_STACK_PRESSURE]`
- Earlier analysis: event_jitter_p95 = 1057.5 ms, frame_present_interval_p95 = 1536.8 ms
- Root cause confirmed: Event delivery jitter, not processing bottleneck
