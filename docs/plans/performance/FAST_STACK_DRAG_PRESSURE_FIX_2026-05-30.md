# FAST Stack-Drag Pressure Sampler — Main-Thread Stall Fix (As-Built)

**Status:** Fixed & verified by log evidence. 2026-05-30.
**Area:** `modules/viewer/fast/qt_viewer_bridge.py` (FAST `pydicom_qt` backend stack-drag path).
**Related:** `FAST_STACK_INTERACTION_PROTECTED_LANE_PLAN_2026-04-21.md`, `FAST_2D_CELL_SEPARATION_PLAN.md`,
viewer scroll hot-path `PacsClient/.../vtk_widget/_vw_scroll.py`.

## Symptom

Stack-scrubbing (drag on the image to move through slices) felt choppy/laggy, **worse on series
with many slices** (>50). The render itself was not the problem.

## Root cause (observer effect — telemetry was causing the stall)

Log evidence from a live run (patient 43744, session `sess-bb6d936d83aa`, backend `pydicom_qt`):

- `[FAST_DRAG_KPI]`: render **handler was fast** (`handler_p95` ≈ 27–65 ms) but `event_p95`
  ≈ 118–292 ms and **`ui_lag_max` ≈ 200–485 ms**, CPU saturated (`cpu_p95` 94–119%, max 128%),
  effective ~10–12 fps.
- `[MAIN_THREAD_STALL_TRACE] drag_active=True gap_ms≈492` captured the blocking stack pointing at:
  `qt_slice_viewer.mouseMoveEvent → qt_viewer_bridge._on_stack_drag_target → _sample_drag_pressure
  → _FastDragPressureSampler.sample() → _read_available_ram_mb → psutil.virtual_memory()`.

`_FastDragPressureSampler.sample()` runs a battery of **synchronous psutil / system-stat calls on
the main thread** — `psutil.virtual_memory()`, process + system `io_counters()`,
`Process.cpu_times()`, `memory_info()` — plus several telemetry snapshots, **every ~125 ms
(`_FAST_STACK_PRESSURE_SAMPLE_MIN_INTERVAL_MS`) during a drag**, with no enable flag. On Windows
those calls intermittently take hundreds of ms, injecting 300–500 ms UI-thread stalls mid-drag.
More slices ⇒ longer/faster drags ⇒ more 125 ms samples ⇒ more stalls.

The sampler was added by commit `3a25b5a "instrument: add runtime correlation for FAST stall
attribution"` — i.e. the telemetry meant to *attribute* FAST stalls was itself *causing* them.

## Fix

Gate the pressure sampler **OFF by default**, opt-in via env:

- New module constant in `qt_viewer_bridge.py`:
  `_FAST_STACK_PRESSURE_ENABLED = os.getenv('AIPACS_FAST_STACK_PRESSURE','').strip() == '1'`.
- `_sample_drag_pressure()` returns the cached/baseline phase immediately and **never calls
  `sampler.sample()`** when disabled — removing all per-drag psutil/system work from the main thread.

Enable the telemetry on demand for diagnosis: launch with `AIPACS_FAST_STACK_PRESSURE=1`.

## Why this does NOT regress stacking behaviour (verified)

- The sampler is **pure telemetry**. Its only output is a `phase` string consumed solely by
  `_record_drag_phase_metrics()` (KPI logging). It does **not** feed rendering, slice selection,
  **reference lines, geometry overlays, or WL/filters** — those run earlier in
  `_on_stack_drag_target` and are untouched.
- The `[FAST_STACK_PRESSURE]` summary block is guarded by `if pressure_samples:`, so zero samples
  is a no-op (no divide-by-zero). `[FAST_DRAG_KPI]` and `[FAST_EVENT_PACING]` summaries still log
  (they use handler/event/ui_lag metrics measured cheaply elsewhere).

## Invariants — do not regress

- **Never call psutil / `virtual_memory` / `io_counters` / `cpu_times` / `disk_io_counters`
  synchronously on the main thread inside the stack-drag (or wheel-scroll) hot path.** If pressure
  telemetry is needed in production, sample it on a background thread and cache, or keep it behind
  `AIPACS_FAST_STACK_PRESSURE`.
- Keep `_sample_drag_pressure`'s early-return guard. Removing it re-introduces the mid-drag stalls.
- `phase` must remain telemetry-only. If a future change makes rendering depend on `phase`, it must
  not depend on the psutil-derived fields.

## Secondary factor (not changed here)

Residual choppiness on very heavy series is governed by the FAST render throttle in
`vtk_widget/widget.py`: `_fast_render_min_interval_ms = 58` (~17 fps cap),
`_fast_render_skip_velocity_sps = 20`, `_fast_render_max_skip_chain = 2`; heavy-series stride
quantization only triggers at **≥ 300 slices**. A smoother render clock (33 ms/16 ms ≈ 30–60 fps)
exists in `qt_viewer_bridge.py` but is **off by default** (`AIPACS_FAST_RENDER_CLOCK_EXPERIMENT=1`).
These are env-tunable and were left as-is — change deliberately, they are clinical-path tuning.
