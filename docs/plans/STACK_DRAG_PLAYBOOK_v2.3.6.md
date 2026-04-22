# FAST viewer stack-drag — how we made it smooth (v2.3.6 playbook)

**Status: STABILIZED** — Log 96 (2026-04-22) confirmed fluid, user-reported-smooth stack drag on low-config test PC with a simultaneous 150-series download running in the background.

This document exists so a future agent (or the same author six months from now) does NOT accidentally regress the fix. Every rule below has a causal story behind it — read the story, not just the rule.

---

## 1. The original problem, in user words

> "When you stack and reach around the fourth image... the mouse is moving, even the right-side scrollbar pointer is moving, but the image itself does not change. You have to do this several times, or use the wheel to go up and down. Only after the images are prefetched and cached does stacking start to work correctly."

Symptom set:
- **Frozen image during drag.** Mouse moves, slider label advances, rendered pixels don't change.
- **ui_lag spikes ≥ 3–6 seconds** in log 92 (`SystemLoadController._last_ui_tick_ms`).
- **event_p50 = 100–150 ms** where nominal mouse delivery should be ~16 ms.
- **background_decode_count = 5–15** on every drag — background workers stealing CPU under Python's GIL.
- **CPU ≥ 149 %** system-wide (one core saturated) during mixed download + drag.

The root cause was **not one bug** — it was a chain of six interacting problems, each of which had to be fixed in order for the next one to become visible.

---

## 2. The six-layer defense (solve order = discovery order)

| Layer | Fix | File(s) | Why it was needed |
|---|---|---|---|
| **L1** | Incremental bounded-step adaptive drag | `modules/viewer/fast/qt_slice_viewer.py` | Old path read absolute Y-delta → dead zone + multi-slice jump on delayed mouse. |
| **L2** | Protected-drag admission gate for PREFETCH + CACHE_WARM | `modules/viewer/fast/ui_throttle.py` | `should_admit()` checked CACHE_WARM only; PREFETCH workers still ran during drag. |
| **L3** | `record_protected_drag()` proper latch + keepalive | `modules/viewer/fast/ui_throttle.py`, `qt_slice_viewer.py` | Original ternary was buggy (`x if active else x`); 500 ms grace expired mid-drag → protection was off for 2.5–9.5 s of every drag. |
| **L4** | Async logging via QueueHandler | `PacsClient/utils/diagnostic_logging.py` | 50+ synchronous `logger.info()` per drag = 50–150 ms ui_lag/cycle. |
| **L5** | DM progress-throttle skip during drag + GC suppression | `modules/download_manager/ui/widget/_dm_workers.py`, `qt_slice_viewer.py` | DM emitted every 100 ms, cascading 4–5 main-thread slots at ~10 Hz; Python gen-2 GC paused main thread 100–500 ms. |
| **L6** | **Surrogate-staleness break** (the last mile) | `modules/viewer/fast/lightweight_2d_pipeline.py` | B3.7 nearest-cached surrogate served `slice_index=<target>` labeled frames containing `<nearest_idx>` pixels — the "frozen image" the user saw. |

Each layer is **additive**. Removing any one of them resurrects the corresponding symptom.

---

## 3. The anti-regression rule set

Copy-pasted into `.github/copilot-instructions.md` for automatic surfacing. Reproduced here with rationale.

### R1 — Never remove or unconditionally bypass the B3.7 surrogate
File: `modules/viewer/fast/lightweight_2d_pipeline.py` → `_try_surrogate_frame()`.

The surrogate is how we get 0 ms decode during fast scroll. But it is _label-lying_: `RenderedFrame.slice_index` is the requested target, and the QImage pixels are from `nearest_idx`. The trap is returning the SAME `nearest_idx` for many consecutive requests → frozen image.

**The correct policy (GC#5):**
- Track `_last_surrogate_pixel_idx` and `_surrogate_repeat_count`.
- If the same `nearest_idx` is served for the previous 2 consecutive (different) targets, **return `None`** on the third → caller falls through to synchronous decode once (15–45 ms spike) and the CORRECT pixels appear.
- Reset counters on `begin_protected_drag_session()` so every new gesture starts clean.
- In the frame-cache path, skip the staleness check when `nearest_idx == idx` (exact hit is real data, not a surrogate).

**Forbidden rewrites:**
- ❌ Removing the `_find_nearest_cached_pixel` / `_find_nearest_cached_frame` call during fast interaction (causes 20–45 ms per-frame decode, 220 % CPU).
- ❌ Making the escape unconditional (defeats the purpose of the surrogate).
- ❌ Using a different reset anchor than `begin_protected_drag_session()` (stale counter leaks across gestures).

### R2 — `record_protected_drag()` must be a real latch with keepalive
File: `modules/viewer/fast/ui_throttle.py`.

Required shape:
```python
_PROTECTED_DRAG_ACTIVE: bool = False
_PROTECTED_DRAG_UNTIL_MS: float = 0.0

def record_protected_drag(active: bool, grace_ms: float = 1500.0) -> None:
    # True → latch active AND set deadline to now + grace_ms
    # False → keep active=False until deadline; deadline drops to now + tail grace (250 ms)
```

`keepalive_protected_drag(1500)` MUST be called from `qt_slice_viewer.mouseMoveEvent` while stack drag is active, or the latch expires mid-drag on slow hardware.

**Forbidden rewrites:**
- ❌ Ternary branches that set the same value (`x if active else x`).
- ❌ Grace window < 1000 ms at begin (drags commonly last 3–10 s on low-spec PCs).
- ❌ Dropping keepalive (grace will expire on the first long pause between mouse events).

### R3 — PREFETCH and CACHE_WARM must BOTH be gated by protected-drag
File: `modules/viewer/fast/ui_throttle.py` → `should_admit()`.

During `is_protected_drag_active()`:
- `WorkClass.PREFETCH` → ❌ deny (ui_throttle level). Inside pipeline, `_prefetch_around()` still enters its tiny-directional-P1 lane with its own P1 admission check — DO NOT clamp to 0 at ui_throttle (that killed the P1 lane in log 94 and caused stuck-on-surrogate).
- `WorkClass.CACHE_WARM` → ❌ deny. This was the existing fix.

`cap_prefetch_radius()` was reverted in GC#4 — it no longer returns 0 during protected drag. The pipeline-local `_PROTECTED_DRAG_AHEAD_RADIUS=2` / `_PROTECTED_DRAG_BEHIND_RADIUS=1` governs the tiny directional lane.

### R4 — Non-terminal progressive grow must defer during drag, terminal must not
File: `modules/viewer/fast/ui_throttle.py`.

- `should_defer_progressive_grow(terminal=False)` → `True` during protected drag.
- `should_defer_progressive_grow(terminal=True)` → `False` always (user must see completion).
- `progressive_grow_interval_ms()` → `1500.0` during drag (matches keepalive), `150.0` default.

### R5 — DM worker `_apply_throttled_progress` SKIPS during drag, doesn't just slow down
File: `modules/download_manager/ui/widget/_dm_workers.py`.

When `is_protected_drag_active()`:
- Leave the throttle timer armed at `1500 ms`.
- Do **not** drain `_pending_progress`. Accumulate and flush after drag.

Slowing from 100 → 750 ms is not enough — each tick still cascades 4–5 main-thread slots (`studyProgressUpdated` → `on_series_progress` → `_flush_progress` → `series_images_progress.emit` → `on_series_images_progress`). Skip the whole chain during drag.

### R6 — GC suppression during stack drag
File: `modules/viewer/fast/qt_slice_viewer.py`.

- `_begin_stack_drag_session()` → `gc.disable()` + set `_gc_suppressed_drag=True`.
- `_end_stack_drag_session()` → start/restart `_gc_reenable_timer` (`QTimer.singleShot(1500, _reenable_gc_after_drag)`).
- `_reenable_gc_after_drag()` → `gc.enable()` inside try/except if `_gc_suppressed_drag`.

Eliminates 100–500 ms gen-2 GC pauses during multi-second drags. Mirrors the existing wheel-scroll pattern.

### R7 — Async logging must stay
File: `PacsClient/utils/diagnostic_logging.py`.

File handlers behind `queue.Queue(-1)` + `QueueListener` daemon thread. Console handler stays sync (stderr is cheap).
Escape hatch: `AIPACS_LOG_SYNC=1`. Shutdown: `shutdown_diagnostic_logging()` from `main.py` finally block + atexit hook.

### R8 — CPU priority boost (Windows, opt-in default)
File: `main.py`.

`SetPriorityClass(ABOVE_NORMAL_PRIORITY_CLASS)` after `QApplication()` construction. Env override `AIPACS_PRIORITY=normal|above_normal|high`. Logs `[CPU_BUDGET]` banner.

### R9 — Decode service worker count capped at 1 on low-config
File: `modules/viewer/fast/decode_service.py`.

`_MAX_WORKERS = _resolve_decode_workers()` reads `AIPACS_DECODE_WORKERS` (default 1, cap 4). More workers = more IPC contention on low-core PCs, not faster decode. Single worker + disk pixel cache is the happy path.

---

## 4. What NOT to do (top 10 tripwires)

1. **DO NOT** reduce drag-begin grace below 1500 ms. Log 92 showed 500 ms expiring mid-drag.
2. **DO NOT** remove keepalive from `mouseMoveEvent`. Drags on low-config PCs can pause 800–1200 ms between events.
3. **DO NOT** route foreground (main-thread) cache misses through the decode service. IPC adds 2.4 ms that the user perceives.
4. **DO NOT** call `gc.collect()` during scroll or drag. Copilot-instructions rule from v2.2.3.3.2.
5. **DO NOT** make the surrogate unconditional (regression = 220 % CPU, 20–45 ms/frame).
6. **DO NOT** make the surrogate-escape threshold `>= 1` (regression = decode on every drag target, defeats surrogate).
7. **DO NOT** clamp `cap_prefetch_radius()=0` during protected drag. Log 94 regression: cache stopped growing → stuck on surrogate.
8. **DO NOT** emit Qt signals from non-Qt threads via `QTimer.singleShot`. Use `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` (v2.2.9.2 thumbnail rule).
9. **DO NOT** add new per-frame overhead to `qt_viewer_bridge.set_slice()` without guarding with `if not fast_interaction:` or equivalent.
10. **DO NOT** remove the `_emit_final_progress()` Layer 2a completion pulse. Without it, the viewer never learns a series is complete when the DM's throttle timer hasn't flushed the last batch.

---

## 5. The discovery story (so future agents don't repeat mistakes)

| Log | Symptom | What we thought | What was actually wrong |
|---|---|---|---|
| 91 | Drag laggy | Background decode during drag | Correct — but gated only CACHE_WARM, not PREFETCH. |
| 92 | Drag still laggy | Handler too slow | WRONG — handler was 0.9 ms. The `record_protected_drag()` ternary bug meant protection was OFF for most of every drag. |
| 93 | Improved, one 627 ms tail | Need finer throttling | WRONG — it was fine for cached regions. Problem was decode workers still running. |
| 94 | Frozen image after fix | `cap_prefetch_radius=0` was "clean" | WRONG — it killed the P1 lane that grows the cache during drag. |
| 95 | Still frozen sometimes | Cache grow fixed it | PARTIALLY — cache growing, but surrogate was returning same pixels. |
| 96 | **Smooth** | — | GC#5 staleness-break on surrogate unblocked the last case. |

**Meta-lesson:** when a fix "mostly works", the remaining 5 % is often a completely different bug. Don't stack epicycles on the original hypothesis — look at what the user literally sees.

---

## 6. Regression test map

Run these before any change to the drag stack:

```powershell
.venv\Scripts\python.exe -m pytest tests/viewer/test_qt_slice_viewer_stack_drag.py -v
.venv\Scripts\python.exe -m pytest tests/viewer/test_qt_stack_drag_bridge.py -v
.venv\Scripts\python.exe -m pytest tests/viewer/test_b34_interaction_aware_policy.py -v
.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py::test_b41_protected_drag_admits_tiny_directional_p1_prefetch -v
.venv\Scripts\python.exe -m pytest tests/viewer/test_cp1_control_plane_governance.py -v
```

Known pre-existing batch-mode flakiness (test isolation, shared module state) — tests pass individually. If a NEW test fails only in batch mode, it's likely the same class of flake. Verify by running the single test in isolation before assuming a regression.

---

## 7. Production validation path

A fix is considered _field-stable_ only after:
1. All regression tests above pass individually.
2. Log on dev PC shows `[FAST_DRAG_KPI] background_decode_count=0` for every drag.
3. Log on target low-config PC (the user's test machine) shows same.
4. User-reported smoothness confirmed subjectively across 3+ consecutive sessions.

Log 96 met all four conditions for v2.3.6.
