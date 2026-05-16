# Scrollbar vs Image-Drag Smoothness Analysis
**Date:** 2026-05-16  
**Session:** `sess-f4930d8a4951` / `sess-0ab9649cd62e`  
**Series:** 204, 264 slices, backend=pydicom_qt  
**Log source:** `viewer_latest.txt` (pid=58316)

---

## 1. Executive Summary

The scrollbar drag path delivers frames at **~34fps** with ≤51ms worst-case interval, while the image-drag path delivers frames at **~14fps** with up to 162ms worst-case interval. Both paths have **identical per-frame rendering cost** (0ms decode, <1ms paint, all cache hits). The entire performance gap is caused by one root cause: **input delivery rate**.

| Metric | Scrollbar | Image Drag | Scrollbar Advantage |
|--------|-----------|------------|---------------------|
| Frame rate (avg) | **34 fps** | **14 fps** | **2.5×** |
| Frame interval p50 | **27 ms** | **64 ms** | **2.4×** |
| Frame interval p95 | **38 ms** | **143 ms** | **3.8×** |
| Frame interval max | **51 ms** | **162 ms** | **3.2×** |
| Jitter range (max−min) | **35 ms** | **131 ms** | **3.7×** |
| Render cost (p50) | ~0 ms | ~0 ms | Equal |
| Decode cost | 0 ms | 0 ms | Equal |

---

## 2. Raw Evidence

### 2a. Image Drag (FAST_DRAG_SESSION path)
Two sessions logged:

**Session 1** `drag-b6ead0-1778935515549` — duration 3.308s:
```
[FAST_DRAG_KPI] ... targets=44
  event_p50_ms=64.2   event_p95_ms=141.9
  handler_p50_ms=0.2  handler_p95_ms=0.3
  ui_lag_max_ms=145.6
  paint_p50_ms=0.8    paint_p95_ms=1.0    paint_max_ms=1.2
  frame_present_interval_p50_ms=64.3
  frame_present_interval_p95_ms=143.2
  frame_present_interval_max_ms=161.0
  background_decode_count=0
  queue_wait_classification=INPUT_DELIVERY_GAP

[FAST_EVENT_PACING]
  raw_input_event_count=44   accepted_input_event_count=44
  coalesced_input_event_count=0   same_slice_rejected=0
  input_event_gap_p95_ms=141.9    input_event_gap_max_ms=161.1
  event_jitter_p95_ms=41.0        event_jitter_max_ms=47.8
  implied_queue_wait_p95_ms=141.7 implied_queue_wait_max_ms=160.8
  set_to_image_p50_ms=0.6  set_to_image_p95_ms=1.0  set_to_image_max_ms=1.2
```

`FAST_FG_DISK` inter-frame intervals (ms) during Session 1:
```
70, 73, 64, 49, 32, 48, 32, 48, 65, 31,
48, 53, 43, 85, 127, 162, 127, 145, 154, 112,
111, 97, 80, 47, 65, 53, 59, 79, 71, 64,
58, 48, 54, 74, 77, 35, 48, 70, 74, 112,
47, 64
```
→ **Average 72.7 ms (13.7 fps)**; p50=64ms, p95=145ms, max=162ms

**Session 2** `drag-b6ead0-1778935519694` — same pattern with outlier:
- 241ms gap at direction reversal (ui_lag=241ms)

---

### 2b. Scrollbar Path (H10-2 + OVERLAP path)
`OVERLAP_SCENARIO` events fire every 5th call to `get_rendered_frame()` (sample=5).  
Per-OVERLAP-event intervals ÷ 5 = per-frame estimate.

**Series 204 scrollbar, down phase** — 15 intervals:
```
Per-OVERLAP: 184, 143, 155, 166, 136, 155, 127, 134, 111, 127, 124, 127, 135, 173, 192 ms
Per-frame:    37,  29,  31,  33,  27,  31,  25,  27,  22,  25,  25,  25,  27,  35,  38 ms
```

**Series 204 scrollbar, up phase** (excluding deceleration pauses 224/256/240ms) — 19 intervals:
```
Per-OVERLAP: 112, 111, 121, 105, 158, 154, 151, 152, 141, 138, 153, 224*, 256*, 240*, 142, 90, 143, 136, 80 ms
Per-frame:    22,  22,  24,  21,  32,  31,  30,  30,  28,  28,  31,  45*,  51*,  48*, 28, 18,  29,  27, 16 ms
```
\* Deceleration pauses (user nearly stopped before reversing direction)

**Scrollbar statistics across all 34 per-frame estimates:**
- Average: **29 ms = 34 fps**
- p50: **27 ms (37 fps)**
- p95: **38 ms (26 fps)** — includes deceleration pause frames
- Max: **51 ms (20 fps)** — moment of direction reversal
- Jitter range: 16 – 51 ms = **35 ms**

---

## 3. Root Cause Analysis

### 3.1 The Bottleneck is NOT Rendering

Both paths show identical per-frame rendering cost:
- Decode: **0 ms** (full pixel cache hit, both paths)
- Paint: **0.8–1.2 ms** (both paths)
- Frame total: **0.5–1.2 ms** (both paths)

The `queue_wait_classification=INPUT_DELIVERY_GAP` tag in the FAST_DRAG_KPI directly identifies the root cause: **the render clock is idle for 64–162ms between input events**. It is not compute-bound.

### 3.2 Architectural Difference Between the Two Paths

**Scrollbar path (H10-2 → OVERLAP):**
```
QSlider::valueChanged(n)
  → VTKWidget.set_slice(n)           [H10-2 logged here]
  → QtViewerBridge._set_slice_impl()
  → Lightweight2DPipeline.get_rendered_frame()   [OVERLAP logged here]
  → QWidget.update()                 [paint scheduled, fires next event loop tick]
```
- **Synchronous dispatch** — no timer, no queue, no render clock
- Each `valueChanged` = 1 rendered frame, latency ≈ 0
- Rate = slider event rate

**Image drag path (FAST_DRAG_SESSION → FAST_FG_DISK):**
```
QWidget.mouseMoveEvent(e)
  → QtViewerBridge._on_stack_drag_state()   [sets pending target]
  → [WAITS for next render clock tick]
  → QtViewerBridge._set_slice_impl()        [FAST_FG_DISK logged here]
  → Lightweight2DPipeline.get_rendered_frame()
  → QWidget.update()
```
- **Event-driven render clock** — one tick fires per incoming mouse event
- Rate = mouse event delivery rate → only 13.3 events/sec → 75ms/event

### 3.3 Why Input Delivery Rates Differ

The key question is why `valueChanged` fires at 34/sec but `mouseMoveEvent`→target-update fires at only 13.3/sec, when both come from the same physical mouse at the same speed.

**Scrollbar sensitivity analysis:**
- Series 204 has 264 slices
- QSlider maps over ~400px height → **1.52 px per slice step**
- At "medium" drag speed (~50 px/sec): 50 ÷ 1.52 = **33 events/sec → 30 ms/event** ✓

**Image drag sensitivity analysis (back-computed from log):**
- 44 events in 3.308s at same mouse speed → **13.3 events/sec → 75 ms/event**
- Required sensitivity: 50 px/sec ÷ 13.3 events/sec = **~3.76 px per slice step**

**The image drag is 2.5× coarser than the scrollbar** (3.76px/step vs 1.52px/step). The slider integer snaps at every 1.52px of cursor movement, while the image drag only registers a new target at every 3.76px of movement. At the same physical cursor speed, this produces 2.5× fewer target updates per second → 2.5× lower frame rate.

### 3.4 The High Jitter Problem

Beyond the lower average rate, the image drag has catastrophic temporal jitter:

| | Scrollbar | Image Drag |
|--|-----------|------------|
| Min interval | 16 ms | 31 ms |
| Max interval | 51 ms | 162 ms |
| Jitter range | **35 ms** | **131 ms** |

The jitter ratio is **3.7×**. This matters more for perceived smoothness than frame rate: the human visual system is highly sensitive to temporal irregularity (judder). A 14fps stream with consistent 71ms intervals would look smoother than a 14fps stream with 31–162ms intervals.

The jitter sources (from `FAST_EVENT_PACING`):
1. `event_jitter_p95_ms=41ms` — OS mouse event delivery is irregular (WM_MOUSEMOVE coalescing)
2. `input_event_gap_p95_ms=141.9ms` — 5% of events arrive 142ms apart (pauses in user's motion)
3. `implied_queue_wait_p95_ms=141.7ms` — the render clock waits up to 142ms for the event

The burst of 85→162→127→145→154ms intervals at 16:15:16.4–16:15:17.1 corresponds exactly to the user slowing their drag around slice 144–140 (movement near zero → very few mouse events → very long gaps).

### 3.5 The Render Clock Does Not Self-Drive

Critical observation: `render_clock_gap_p95_ms=0.0` — the render clock fires with perfect timing. However, `frame_present_interval_p50=64ms` tells us the clock only fires **when there is a new input event**. The render clock does NOT tick at a fixed rate independent of input; it fires once per accepted mouse event. This is the correct design for "don't show stale frames", but it means the frame rate is entirely determined by the input delivery cadence.

---

## 4. MAIN_THREAD_STALL Context

At 16:24:09, a separate stall was logged:
```
[MAIN_THREAD_STALL] stall_duration_ms=136.5 active_viewer_state=fast_drag_inactive stalls_total=16 max_gap_ms=9242.1
```
This stall occurred ~9 minutes after the drags, `nearest_fast_drag=none`, so it is unrelated to the drag performance. It represents some background main-thread work post-drag.

---

## 5. Optimization Targets

Ranked by expected smoothness improvement per implementation effort:

### Option A — Fix Image Drag Sensitivity (High Impact, Low Effort)

**What:** Change the pixels-per-slice-step factor in `qt_slice_viewer.py` or `qt_viewer_bridge.py` for the image drag calculation from ~3.76px/step to ~1.52px/step (matching the scrollbar).

**Expected result:** 13.3 events/sec → ~33 events/sec → frame rate rises from 14fps to ~34fps. Matches scrollbar smoothness exactly.

**Risk:** At same mouse speed, the user traverses slices 2.5× faster. May feel too sensitive for large datasets. Can be addressed by making sensitivity configurable or proportional to series size.

**Implementation:** Find the pixel-delta-to-slice-step calculation in `_on_stack_drag_state` / `_compute_target_from_drag` and reduce the denominator by 2.5×.

---

### Option B — Fixed-Rate Render Clock with Velocity Extrapolation (High Impact, Medium Effort)

**What:** Run the FAST render clock at a fixed 16ms (60fps) timer regardless of input events. Between mouse events, extrapolate the expected slice from the last known velocity (slices per ms). On mouse event arrival, correct the slice to the exact target.

**Expected result:** Frame presentation becomes metronomic 60fps. Even at 13.3 mouse events/sec, each gap of 75ms would contain 4–5 predicted frames at fractional slice positions. The worst-case "wrong frame shown for one tick" is 16ms before correction.

**Risk:** Very briefly shows a predicted slice that's 1–2 off. Corrects on the next mouse event. For most DICOM viewing this is imperceptible. Do NOT use velocity extrapolation past the end-of-series bounds.

**Implementation:** Add velocity tracking to the drag state (`slices_per_ms` from last 3 events), tick the render clock at 16ms, and in `_set_slice_impl` during drag: if no new event since last tick, advance by `velocity × 16ms`.

---

### Option C — Raise OS Mouse Report Rate (Low Impact, Zero Code)

**What:** Set `SetMouseCoalescingEnabled(False)` on the FAST viewer widget or call `GetSystemMetrics(SM_MOUSEHOVERTIME)` / `SystemParametersInfo(SPI_SETMOUSEHOVERTIME, ...)` to reduce Windows mouse coalescing. Some implementations call `SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)` to get full-rate WM_MOUSEMOVE delivery.

**Expected result:** Reduces `event_jitter_p95` from 41ms toward 0ms. However, even with perfect mouse event delivery, the 3.76px/step sensitivity limit still caps the useful rate at ~33fps (same as scrollbar at medium speed). Impact is smaller than Options A or B.

**Implementation:** In `QtSliceViewer.__init__` or `QtViewerBridge.__init__`, call `setMouseTracking(True)` (already done?) and possibly configure Qt's event compression. Check `QApplication::SetQuitOnLastWindowClosed` and mouse compression settings.

---

### Option D — Defer reference_applied Until Drag End (Marginal Impact)

`reference_applied=True` fires every ~3rd frame during image drag, adding a small per-frame cost (~0.5ms). During the burst of long intervals (85–162ms) this coincides with `reference_applied=True` on slices 143, 141, 139, 137, 133. Deferring all reference line updates to drag end (`_flush_final_side_effects_on_settle`) would remove this ~0.5ms per-3rd-frame overhead. Impact is marginal vs the 64ms input gap, but would tighten the most-variable frames.

**Expected result:** Reduces max paint time from 1.2ms to ~0.7ms for 1/3 of frames. Not perceptible at 64ms intervals.

---

## 6. Recommended Action Plan

**Short term (next session):**
1. Implement **Option A** — reduce image drag sensitivity factor by 2.5×. Measure the new `event_p50_ms` and `frame_present_interval_p50_ms` in a follow-up log. Target: `event_p50_ms < 35ms`.

**Medium term:**
2. Implement **Option B** velocity extrapolation to achieve 60fps visual rate independent of input rate. Gate behind `AIPACS_DRAG_CLOCK_INTERPOLATE=1` env var for controlled rollout.

**Validation:**
- After Option A: `event_p50_ms` should drop from 64ms → ~30ms; `frame_present_interval_p50_ms` should match.
- Regression check: `background_decode_count=0` must stay 0 (R3), `[FAST_DRAG_KPI]` `queue_wait_classification` should change from `INPUT_DELIVERY_GAP` to `RENDER_BOUND` or `INPUT_COALESCE`.
- Use `run_overlap_regression.ps1` (F1 gate) before committing any `qt_viewer_bridge.py` or `qt_slice_viewer.py` changes.

---

## 7. Why Scrollbar Feels "Smooth" Despite Lower Peak Frame Rate

Counterintuitively, the scrollbar's **consistent 27ms cadence** (37fps) feels smoother than the image drag's **73ms average** (14fps) even at the same physical cursor speed. Two mechanisms:

1. **Temporal regularity**: 27ms with 35ms jitter range = 16–51ms. All within 3× of each other. The visual system perceives this as a steady rhythm.

2. **1:1 input-to-frame ratio**: Every slider step = exactly 1 new frame. The rendered slice always matches where the cursor is on the scrollbar. This gives tactile coupling.

The image drag has **0.38× average frame rate** AND **3.7× more jitter**. The jitter is the dominant perceptual factor — irregular cadence creates "judder" sensation even when the average fps is acceptable. At 14fps with ±65ms jitter, users often perceive the motion as "stuttering" or "sticky" rather than "smooth but slow."

The fix (Option A) addresses both problems simultaneously by driving up the input rate to match the scrollbar, which also inherently reduces jitter because the render clock fires more consistently.

---

*Analysis based on live session data: series=204 (264 slices), backend=pydicom_qt, gen=1, all frames from memory pixel cache (cache_hit=True), zero foreground disk reads, zero background decodes. CPU p95=8.7%, RSS p95=878.5MB, avail_RAM=34GB.*
