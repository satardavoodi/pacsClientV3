# H13 Focused Recovery Plan

**Investigation:** FAST `pydicom_2d` crash + scroll/download performance collapse  
**Scope:** FAST viewer only (`pydicom_2d` + VTK render path). Advanced viewer is out of scope unless explicitly needed later.  
**Status date:** 2026-04-14  
**P1 status:** COMPLETED (2 runs)  
**Investigation status:** **RESOLVED (mitigated)** — root cause identified, H13-FIX deployed, strategic replacement planned

**Active failure families now tracked:**
1. **H13-F1 — Fatal viewer crash:** `Fatal Python error: PyThreadState_Get: GIL not held` (baseline dominant)
2. **H13-F2 — Qt/UI event-handler exception:** Python exception propagating through Qt event boundary (surfaced under P1)
3. **H13-F3 — Download/network/coordinator instability:** socket loss, priority retry exhaustion, process-level failure

---

## 1. Why this document exists

`H13_WORKING_DOCUMENT.md` is the full forensic journal. It is valuable, but large.

This document is the **focused execution companion**:
- what we have learned,
- what is probably noise,
- what remains plausible,
- what to run next,
- what performance work is allowed inside H13,
- and what to avoid so we do not drift.

Use this as the day-to-day guide. Use `H13_WORKING_DOCUMENT.md` as the evidence ledger.

---

## 2. What the process has already accomplished

### Wins

1. **The problem is now well-scoped.**  
   We are no longer debugging the entire viewer stack. The active failure zone is the FAST lazy VTK path:
   - `PyDicomLazyVolume` worker decode/write path
   - `VTKWidget._on_lazy_slice_ready_impl`
   - VTK render chain under scroll pressure

2. **Several hypotheses have already been materially tested.**
   - **T4 render gate** proved `_load_lock`-scoped overlap is **not the whole story**.
   - **T5 keepalive** weakened grow/UAF as the primary explanation for the currently dominant crash path.
   - **T6 initial run** exposed that stale-render logic needs instrumentation before its result can be trusted.

3. **The investigation now has probes, toggles, and KPIs.**  
   This is the biggest process improvement. We are no longer working from intuition alone.

4. **The pressure story is now undeniable.**  
   Logs show:
   - high dropped frames,
   - high overlap counts,
   - high CPU under scroll pressure,
   - degraded `set_slice` timings,
   - and large callback/render churn.

5. **P1 (booster OFF) materially changed the failure character.**  
   - Overlap collapsed from 329 → 0.
   - Dropped frames reduced from 1538 → 171.
   - The dominant visible failure shifted from fatal GIL crash (F1) to a Qt event-handler exception (F2).
   - Booster is now evidenced as a dominant amplifier, not a sole cause.
   - Reducing booster pressure exposes a more tractable failure path.

### Process mistakes that we should not repeat

1. **Running a behavioral toggle before insertion-point telemetry existed.**  
   T6 ON crashed early, but without exact insertion-point diagnostics that run was not decision-grade.

2. **Letting one suspicious correlation dominate too early.**  
   Grow timing in T4 was useful, but T5 showed that grow is not the primary active branch of the failure.

3. **Allowing crash/no-crash to dominate over pressure KPIs.**  
   A no-crash run with `CPU ~140%`, `dropped_frames > 1500`, and `set_slice_p95 ~84ms` is still a failing system.

4. **Mixing trigger, amplifier, and mechanism into one bucket.**  
   H13 is easier to solve when separated into:
   - direct trigger,
   - enabling condition,
   - pressure amplifier,
   - lower-level C/runtime mechanism.

---

## 3. Current technical understanding

This is the current best model consistent with the evidence and the official pipeline docs.

### 3.1 Architecture facts from repo docs

From `docs/pipelines/PYDICOM_2D_BACKEND.md` and `docs/viewer/FAST_PIPELINE_DETAILED.md`:

- `pydicom_2d` is **lazy per-slice decode** but still uses **VTK render** in Phase 1.
- The hot callback is `VTKWidget._on_lazy_slice_ready_impl(...)`.
- Both the scroll path and lazy callback path eventually go through:
  - `mark_vtk_modified()`
  - `_call_image_viewer_set_slice(...)`
  - `ImageViewer2D.set_slice(...)`
  - VTK `Render()`
- The backend uses shared numpy-backed / VTK-connected image data.

From `docs/performance/PERFORMANCE_STATUS.md`:
- scroll and render are highly sensitive to extra per-frame work,
- backpressure and queue buildup are known historical failure amplifiers,
- CPU pressure and callback storms are already recognized performance hazards.

### 3.2 Current evidence hierarchy

#### Most important direct trigger candidate
**State/coherence issue at render boundary (TOCTOU).**

When a ready frame reaches `_on_lazy_slice_ready_impl`, we already know there are scenarios where a frame can be treated as renderable while live viewer state has moved. Even when mismatch is not dominant in every run, it is the cleanest direct trigger candidate because it decides whether an unnecessary render happens at all.

#### Strong amplifier
**H13-E: pressure / backpressure mismatch.**

Evidence already collected:
- high dropped-frame counts,
- high callback churn,
- high overlap counts,
- high `set_slice` p95,
- CPU spikes under active scroll.

This means even if TOCTOU is real, pressure decides how often the system reaches the dangerous window.

#### Necessary enabling condition
**H13-A: shared zero-copy / shared backing model.**

Without shared writable/Renderable state, the dangerous overlap class does not exist in the same way. T4 already showed that a Python lock around one scope is not sufficient, but zero-copy/shared-memory remains an enabling condition.

#### Plausible lower-level mechanism
**H13-B: VTK / numpy / Python 3.13 GIL-sensitive C-level interaction.**

Still plausible, especially because the crash family is C-level and not a normal Python exception. But it is **not yet isolated** as an independent root cause. At present it is better treated as the likely lower-level failure mechanism that becomes fatal once trigger + pressure align.

#### Newly exposed post-P1 failure path
**H13-F2: Qt/UI event-handler exception.**

Under `AIPACS_DISABLE_BOOSTER=1`, overlap collapsed dramatically and dropped frames improved materially, but the system did not fully stabilize. Instead of the original `PyThreadState_Get` fatal, P1 run #2 surfaced a Qt-caught exception (`"Qt has caught an exception thrown from an event handler"`). The last two set_slice calls before crash showed WL spikes of 356ms (up from 0ms), but both **completed and logged their sub-timing** — the stall did not throw. The `frame_delivery action=render` log immediately preceding the crash also completed normally. The Qt exception was thrown in a **subsequent event handler for which no Python traceback was captured** (neither `sys.excepthook` nor PySide6's hook fired).

This indicates that booster pressure was hiding at least one more tractable failure path underneath the fatal GIL crash. Booster is therefore reclassified as a **dominant amplifier, not a sole cause**.

**Known unguarded paths that CAN let exceptions escape to Qt:**
- `_call_image_viewer_set_slice` (_vw_scroll.py) catches only `TypeError` — any other exception escapes
- `ImageViewer2D.set_slice` (viewer_2d.py) has no try/except at all
- `apply_default_window_level` (viewer_2d.py) has no try/except; `GetScalarRange()` fallback can stall
- `update_corners_actors` (viewer_2d.py) has no try/except; `metadata['series']['series_thk']` KeyError risk

**Critical silent suppression:** `_on_lazy_slice_ready_impl` (line 636) catches ALL render exceptions at `logger.debug` level — completely invisible at normal INFO log level. If the WL/set_slice path throws during any lazy render, the exception is caught but the evidence is silently discarded.

**What we do NOT know:** which specific event handler threw the exception that Qt caught. The guards above are defensive hardening for all known unguarded Qt boundary paths, not a confirmed fix for the specific P1 run #2 crash.

**Most likely scenario (interpretation):**
1. Lazy callback fires → render completes OK (WL=356ms logged, frame_delivery success).
2. Event loop advances to the next queued handler.
3. State is already inconsistent from the previous heavy operation (e.g., metadata stale, viewer state moved).
4. Exception occurs in a **consumer downstream** of the render — UI sync, secondary render, metadata access, or corner text update.
5. Exception is either swallowed silently (`logger.debug`) or propagates unguarded to Qt.

**Implication:** The real bug may not be in WL or `set_slice` at all. WL=356ms was the last **observable** heavy step, not necessarily the **cause**. The exception may originate in a subsequent handler that consumes state left inconsistent by the render.

#### Deprioritized branch
**H13-C: grow/UAF.**

Still possible for some variants, but no longer the lead branch for the active path.

---

## 4. Focused problem statement

We are now solving **three linked problems**, not one:

### A. Fatal stability failure (H13-F1)
Under FAST-mode active scroll + active decode/download pressure, the process can terminate with:

- `Fatal Python error: PyThreadState_Get: GIL not held`

This is the baseline-dominant crash. It is C-level fatal — no Python traceback, no recovery.

### B. Recoverable/UI stability failure (H13-F2)
Under reduced pressure (P1 booster OFF), the dominant visible failure shifts to:

- Python exception propagating through a Qt event handler
- `"Qt has caught an exception thrown from an event handler. Throwing exceptions from an event handler is not supported in Qt."`

This failure is catchable, inspectable, and diagnosable — unlike F1. It was hidden behind booster pressure in baseline runs.

### C. Performance failure
Even in runs that do not hit a fatal or Qt crash, the system can degrade to:
- CPU > 100%
- dropped frames in the hundreds or thousands
- `set_slice_p95` well above acceptable limits
- excessive overlap and render churn

That means the final solution must do **all three**:
1. reduce or eliminate the fatal GIL window (F1),
2. guard against exception propagation through Qt event boundaries (F2),
3. reduce pressure enough that the system remains responsive (C).

---

## 5. What we have proven vs not proven

### Proven enough to act on

- The issue is inside the FAST lazy VTK path.
- Pressure is a major amplifier.
- `_load_lock`-scoped render gating is not sufficient as a complete fix.
- Grow/UAF is not the dominant explanation for the currently active branch.
- A no-crash run does not imply healthy behavior if pressure metrics are terrible.
- Booster load is now evidenced as a dominant amplifier.
- P1 (booster OFF) can materially reduce overlap (329 → 0) and dropped frames (1538 → 171).
- P1 can change the dominant visible failure from fatal GIL crash (F1) to Qt event-handler exception (F2).
- Stale conditions remain present even when overlap collapses (18 T6-DIAG entries, all stale).

### Not yet proven

- Whether stale-render TOCTOU is a **necessary** trigger.
- Whether pressure alone can explain the crash frequency without TOCTOU.
- Whether deep copy is the cleanest final fix or only a discriminating experiment.
- Whether booster load or lazy-worker concurrency is the dominant pressure source.
- Whether the Qt/WL/event-handler exception is a direct trigger or only the first newly visible symptom after pressure reduction.
- Whether booster window reduction can preserve most of the P1 benefit without reintroducing the fatal family.
- Whether the WL spike (0ms → 356ms) is the root cause of the Qt exception or only the last visible signal before failure.

---

## 6. The focused plan from this point

This plan is intentionally short. It exists to keep the investigation on rails.

**Key update (2026-04-13):** P1 is COMPLETED. Steps 3a/3b are DONE (observability recovered). Step 3c verification run crashed with F1 (GIL fatal) — no `[H13-S5]` guards fired, confirming the active failure is C-level, not Python-catchable. `[H13-OVERLAP]` confirmed real render/write overlap 0.51ms before fatal. T3 deep-copy experiment is now the primary discriminating step.

### Step 1 — Preserve T6 as diagnostic-only (DONE)

T6 diagnostic instrumentation runs passively in all subsequent runs. It provides `stale_cond_count` and per-callback telemetry without behavioral changes.

Instrumentation at the exact insertion point:
- fresh `GetSlice()` re-read,
- toggle state,
- ready/requested/live/guard slices,
- shadow abort decision,
- reason,
- `stale_cond_count` (always-on — how often `reason=stale/mismatch` fires, toggle-independent),
- `stale_abort_count` (only non-zero when toggle ON).

### Step 2 — Record and separate the newly exposed failure families (DONE)

**Goal:** prevent future runs from conflating:
- fatal GIL crash family (F1),
- Qt/UI event-handler exception family (F2),
- download/network failure family (F3).

**What success looks like:**
- every new run is classified into one of these families,
- and KPI interpretation is not mixed across unrelated failure modes.

**Status:** Failure families are now separated in §4 and the KPI table (§8).

### Step 3 — Recover observability and classify the Qt/event failure

**This step must be completed before any further pressure experiments (P2A/P2B).**

**Governing principle:** Before any further stability or performance experiments, the system must be made observable. Silent exception suppression in the lazy/render path is currently preventing correct failure classification and must be eliminated first.

**Critical gap discovered during review:** We do NOT have a Python traceback from the P1 run #2 Qt crash. The `sys.excepthook` (H5a) did not fire. The last render completed cleanly. The absence of a Python traceback in a Qt exception scenario is itself diagnostic evidence — either the exception was swallowed, occurred outside Python context, or was lost at an event boundary.

#### Step 3a — Eliminate silent exception suppression (DONE)

**Goal:** Ensure no exception in the lazy/render path is silently swallowed.

**Completed (2026-04-13):**
- `_on_lazy_slice_ready_impl` (`_vw_backend.py:635`) — `logger.debug` → `logger.warning` with `exc_info=True` and rich context (`[H13-S5]` tagged: viewer_id, backend, generation, progressive state).
- `set_slice` camera scale save (`_vw_scroll.py`) — bare `except: pass` → `except Exception: logger.warning("[H13-S5]", exc_info=True)`.
- `set_slice` camera zoom restore (`_vw_scroll.py`) — bare `except: pass` → `except Exception: logger.warning("[H13-S5]", exc_info=True)`.
- `set_slice` `mark_vtk_modified` (`_vw_scroll.py`) — bare `except Exception: pass` → `except Exception: logger.warning("[H13-S5]", exc_info=True)`.
- Audit found 30+ suppression sites total; the 4 above are on the critical render/Qt path.

**Rule established:** `logger.debug` is treated as non-existent for H13. No guard added before this step.

#### Step 3b — Add Qt boundary guards (DONE)

**Goal:** Prevent exceptions from propagating through Qt event handlers.

**Completed (2026-04-13):**
1. `_call_image_viewer_set_slice` (`_vw_scroll.py`) — widened `except TypeError` to also catch `Exception` with `[H13-S5]` context logging.
2. `ImageViewer2D.set_slice` (`viewer_2d.py`) — wrapper+impl split: `set_slice()` → `_set_slice_impl()` with outer `[H13-S5]` exception guard.
3. `apply_default_window_level` (`viewer_2d.py`) — wrapper+impl split: `apply_default_window_level()` → `_apply_default_window_level_impl()` with outer `[H13-S5]` exception guard.
4. `update_corners_actors` (`viewer_2d.py`) — wrapper+impl split: `update_corners_actors()` → `_update_corners_actors_impl()` with outer `[H13-S5]` exception guard.

All guards log with `exc_info=True` for full traceback. No core behavior changed.

#### Step 3c — Verify traceback capture works (DONE — answered a different question)

**Goal:** Confirm that exceptions are now observable and classifiable.

**Result (2026-04-13, log 22):**
- Crash reproduced under `AIPACS_DISABLE_BOOSTER=1`.
- **No `[H13-S5]` guards fired.** No Python traceback captured.
- Crash was `Fatal Python error: PyThreadState_Get: GIL not held` — pure F1 family.
- `[H13-OVERLAP]` fired twice: overlap_count=2, overlap_max_ms=0.51.
- `[H12-3] BACKING_STORE_OVERLAP current=vtk_render:26948 holder=lazy_volume_write:16012` confirmed real render/write overlap.
- Last log line before fatal: `frame_delivery action=render viewer=0 slice=20`.

**Interpretation:**
- Python-level guards (3a/3b) are in place but irrelevant for F1 — the crash occurs at the C/VTK level, below Python's exception system.
- The active failure is confirmed as **shared-memory overlap between lazy worker writes and VTK render reads**.
- Step 3c answered a DIFFERENT question than intended: not "is observability working?" but "is the active crash path even reachable by Python guards?" Answer: NO.
- The correct next step is **T3 deep-copy isolation**, not P2A/P2B.

### Step 4 — Run T3 deep-copy experiment (IMPLEMENTED, READY TO RUN)

**Goal:** Break the shared-memory coupling between lazy decode/write and VTK render to determine if it is a necessary condition of the H13 GIL crash.

**Implementation (2026-04-13):**
- Env var: `AIPACS_VTK_DEEP_COPY=1` (already wired in `_decode_guard.py`).
- When ON: `mark_vtk_modified()` in `PyDicomLazyVolume` snapshots the entire numpy backing store (`_volume.ravel().copy()`) into an independent array, creates a new VTK scalar array from the snapshot, and sets it as the VTK image's scalars before calling `Modified()`.
- Workers continue writing to `self._volume` (memmap). VTK `Render()` reads from the snapshot. No shared-memory overlap is possible.
- Snapshot kept alive by `self._t3_snapshot` attribute until the next frame replaces it.
- `[H13-T3]` startup marker emitted to confirm mode is active.
- All existing probes preserved: `[H13-OVERLAP]`, `[H12-3]`, `[H13-T6-DIAG]`, `[H13-P5]`.

**Run command:**
```
set AIPACS_VTK_DEEP_COPY=1 && .venv\Scripts\python.exe main.py
```

**Expected performance cost:**
- One numpy `ravel().copy()` per render frame.
- For 33-slice 512×512 int16 CT: ~17MB copy ≈ 3–5ms per frame.
- For 500-slice studies: ~250MB ≈ 50ms — too expensive for production, acceptable for experiment.
- Adds ~3–5ms to the existing ~30–50ms Render() time.

**Success criteria:**
- If T3 eliminates the `PyThreadState_Get` fatal: shared mutable backing is a **necessary condition** of the active H13 crash → propose the cleanest production isolation path.
- If T3 does NOT eliminate the fatal: the crash is deeper than shallow shared-buffer overlap → next isolation step (but do not guess).

**Isolation scope:**
- T3 isolates the render-time overlap between `vol[i] = arr` (worker write) and VTK scalar reads (during Render).
- T3 does NOT isolate: `Modified()` calls on VTK pipeline objects, VTK internal thread scheduling, or numpy dtype/GIL interactions outside the scalar data path.
- If T3 passes, the overlap path is confirmed as the coupling that matters. If it fails, the coupling is deeper.

### Step 5 — Classify T3 result and decide next path

**If T3 eliminates the fatal:**
- Shared-memory coupling is a necessary condition.
- Propose: (a) production-grade per-slice copy, (b) double-buffer architecture, or (c) render gating with write exclusion.

**If T3 does NOT eliminate the fatal:**
- The crash is below the scalar data overlap level.
- Next candidates: VTK `Modified()` thread safety, VTK internal pipeline state, or Python/C boundary in numpy ↔ VTK.

### Step 6 — P2A/P2B (deferred)

Pressure reduction experiments are deferred until after T3 classification. They remain valid for reducing pressure KPIs but are not the primary discriminating step for stability.

---

## 7. Exact H13 priorities now

### Priority 1 — Keep failure families separated
Do not mix fatal GIL crashes (F1), Qt event-handler exceptions (F2), and download/network failures (F3). Every new run must be classified.

### Priority 2 — Recover observability before anything else
The system currently swallows exceptions silently (`logger.debug` = invisible). Until observability is restored, failure classification is impossible and further experiments produce uninterpretable results.

### Priority 3 — Continue pressure narrowing only after the Qt path is classified
Use P2A/P2B after the Qt failure becomes inspectable.

### Priority 4 — Preserve system responsiveness while investigating
No broad locks or expensive per-frame work.

### Priority 5 — Keep solution hypotheses narrow
Do not jump to architecture rewrites or T3 prematurely.

---

## 8. KPI set that matters most

These are the KPIs that should decide the next move.

| KPI | Why it matters |
|---|---|
| Crash yes/no | Primary stability outcome |
| Failure family (F1/F2/F3) | Distinguishes fatal GIL crash vs Qt/UI exception vs download/network |
| Exception type / site | Critical when the crash is no longer a fatal GIL abort |
| Time to crash | Distinguishes immediate logic failure from slow pressure accumulation |
| CPU peak | Direct pressure indicator |
| Dropped frames | Render consumer overload indicator |
| `set_slice_p95` | User-facing responsiveness |
| `H13-OVERLAP count` | Shared-state contention signal |
| `overlap_max_ms` | Severity of overlap window |
| `stale_abort_count` | Whether T6 would have meaningfully acted |
| qsize / pending | Producer backlog |
| visual corruption / zoom-layout status | Important even when crash is absent |

### KPI interpretation rule

A run is **not healthy** unless all three are true:
1. no fatal H13 crash (F1),
2. no Qt event-handler exception escape (F2),
3. pressure metrics move in the right direction.

---

## 9. Guardrails — what not to do

1. **Do not conflate failure families.** F1 (fatal GIL), F2 (Qt exception), and F3 (download/network) require separate classification and separate KPI interpretation.
2. **Do not broaden scope to Advanced viewer or unrelated modules.**
3. **Do not trust single-run crash/no-crash outcomes without KPI context.**
4. **Do not add expensive per-frame work in the render/scroll hot path.**
5. **Do not treat one suspicious log line as proof without counters and repeated evidence.**
6. **Do not jump to T3 (deep copy) before the Qt/WL/event path is classified and guarded.**
7. **Do not claim the Qt exception guard is a final fix.** It is diagnostic hardening — it makes the failure inspectable, not necessarily resolved.
8. **Do not add any guard (3b) before removing silent suppression (3a).** Adding guards first risks catching exceptions at the guard site instead of at the original throw site, losing the diagnostic stack trace that is the entire point of this step.
9. **Treat `logger.debug` as non-existent for H13.** In production-like runtime, debug logging is OFF. Any `except ... logger.debug(...)` is functionally equivalent to swallowing the exception with zero evidence.
10. **Treat absence of Python traceback as a signal, not a dead end.** It means one of: (a) exception was swallowed, (b) exception originated outside Python context, or (c) exception was lost at an event boundary. Each requires a different response.

---

## 10. Near-term candidate solution space

These are not all approved yet; they are the bounded solution space implied by the current evidence.

### A. Trigger suppression / coherence hardening
- stale-render suppression at callback boundary
- stricter render admission rule based on live slice consistency
- drop unnecessary callback-driven renders

### B. Pressure reduction
- booster off / delayed under active scroll (`AIPACS_DISABLE_BOOSTER=1`)
- booster window reduction (`AIPACS_BOOSTER_WINDOW=5`)
- single lazy-decode worker (`AIPACS_PYDICOM_SINGLE_WORKER=1`)
- stronger callback coalescing / frame dropping under scroll pressure
- Note: `AIPACS_MAX_DECODE_THREADS=1` is already the default (H12) — not a discriminating knob

### C. Shared-state discrimination
- **T3 deep-copy experiment (IMPLEMENTED):** `AIPACS_VTK_DEEP_COPY=1` — `mark_vtk_modified()` snapshots the numpy backing store before every Render. Implemented in `modules/viewer/fast/pydicom_lazy_volume.py`. Startup marker: `[H13-T3]`.

### D. Diagnostic: VTK build-flag audit
- One-time `[H13-BUILD]` log at startup: Python version, VTK version, NumPy version, VTK wheel provenance.
- PyPI VTK wheels are NOT built with `VTK_PYTHON_FULL_THREADSAFE=ON`. This means VTK wrapper methods that release/reattach the GIL (`VTK_UNBLOCKTHREADS` hint) may not behave correctly, elevating H13-B as an enabling condition alongside H13-A.
- Zero runtime cost. Informs whether H13-B is partly a build-environment issue.
- **Implemented:** `[H13-BUILD]` emitted from `modules/viewer/fast/_decode_guard.py` at import time.

### E. Observability recovery and UI/event-path hardening
- **Systematic audit and elimination of silent exception suppression** — not just `_on_lazy_slice_ready_impl`, but all lazy callbacks, render dispatch paths, and Qt-bound slots where `except ... logger.debug(...)` or bare `except: pass` patterns exist. `logger.debug` is treated as non-existent for H13.
- **Elevate all suppressed exceptions** to `logger.exception(...)` or structured error logging at INFO/ERROR level before adding any behavioral guards.
- wrapper+impl exception guards for Qt event/callback boundaries (`_call_image_viewer_set_slice`, `set_slice`, `apply_default_window_level`, `update_corners_actors`)
- rich `[H13-S5]` logging for event-handler exceptions (viewer_id, slice, backend, series, lazy/progressive state, WL source)
- prevent Python exceptions from escaping through Qt event handlers
- preserve enough context to distinguish bad-data, WL-path, stale-frame, and downstream-consumer triggers
- verify traceback capture works end-to-end (sys.excepthook + PySide6 hooks + confirmation that a reproduced failure yields a classifiable traceback)

### F. Final stabilization target
A healthy final state should look like:
- no H13 fatal crash (F1) under Pipeline A,
- no Qt event-handler exception escape (F2),
- materially reduced overlap counts,
- materially reduced dropped frames,
- `set_slice_p95` back near acceptable FAST thresholds,
- no visible corruption / zoom-layout regressions.

---

## 11. Immediate next execution order

1. ~~Record P1 results formally in the working ledger and focused plan~~ **(DONE — §2, §3.2, §4, §5, §11.1)**
2. ~~Separate failure families in analysis and future KPI tables~~ **(DONE — §4, §8)**
3. ~~Recover observability~~ **(DONE — Step 3a: elevated 4 silent suppression sites to `logger.warning` with `[H13-S5]` tags)**
4. ~~Add Qt boundary guards~~ **(DONE — Step 3b: wrapper+impl on 4 functions with `[H13-S5]` logging)**
5. ~~Verify traceback capture~~ **(DONE — Step 3c: crash reproduced, no Python traceback, confirmed F1/C-level, not Python-catchable)**
6. ~~Run T3 deep-copy experiment~~ **(DONE — Logs 23-25: crashes with ALL workers idle, overlap=0. T3 does NOT prevent crash. Shared-memory buffer is NOT the sole cause)**
7. ~~Classify T3 result and decide next path~~ **(DONE — H13-B CONFIRMED: VTK PyPI wheel lacks VTK_PYTHON_FULL_THREADSAFE. Idle threads corrupt GIL state during VTK render)**
8. ~~Implement mitigation~~ **(DONE — H13-FIX: worker auto-shutdown when all slices decoded, auto-revive on grow(). All 69 tests passing)**

### 11.2 Resolution and strategic direction

**Root cause (confirmed):** VTK 9.6 PyPI wheel is NOT built with `VTK_PYTHON_FULL_THREADSAFE=ON`. When worker threads exist (even idle in `queue.get()`), VTK's C++ `Render()`/`SetSlice()` corrupt GIL state via improper `vtkPythonUtil::SaveThread()`/`RestoreThread()` calls. This produces `Fatal Python error: PyThreadState_Get: GIL not held`.

**Immediate mitigation (H13-FIX):** Workers auto-exit when all slices are decoded (`[H13-AUTOEXIT]`). When `grow()` adds new slices during progressive download, workers are revived on demand (`[H13-REVIVE]`). This eliminates idle threads during VTK render operations.

**Long-term resolution:** Replace VTK rendering in FAST mode with the existing Qt-native pipeline (`pydicom_qt` backend). The codebase already contains `QtSliceViewer`, `Lightweight2DPipeline`, and `QtViewerBridge` — these were built alongside `pydicom_2d` but never became the exclusive FAST path. Completing this transition eliminates the VTK thread-safety dependency entirely for FAST mode.

**Advanced mode:** Unaffected. Continues using VTK with single-threaded decode (SimpleITK loads full volume). No worker threads exist during Advanced mode VTK render.

### 11.1 P1 Results Summary — Booster OFF

**Experiment:** `AIPACS_DISABLE_BOOSTER=1`, all H13 toggles OFF, T6 diagnostic passive.  
**Pipeline:** Pipeline A (download CT study + active scroll under load).  
**Runs:** 2 (both crashed — different failure families).

**Observed outcome:**
- Overlap collapsed dramatically (329 → 0 in run #2).
- Dropped frames reduced materially (1538 → 171 in run #2).
- Stale conditions remained present (18 T6-DIAG entries, all reason=stale, 0 mismatch).
- The dominant visible failure changed from fatal GIL crash (F1 in run #1) to a Qt event-handler exception (F2 in run #2).
- WL spike: 0.0ms → 356ms in the last 2 frames before crash.
- CPU peak: 128.7% (still elevated but not as sustained as baseline).

**KPI comparison (Baseline T6-OFF / P1 #1 / P1 #2):**

| KPI | Baseline T6-OFF | P1 Run #1 | P1 Run #2 |
|---|---|---|---|
| crash | True (GIL) | True (GIL) | True (Qt exception) |
| overlap_count | 329 | 218 | 0 |
| overlap_max_ms | 3.2 | 1.8 | 0.0 |
| dropped_frames_max | 1538 | 1025 | 171 |
| cpu_peak_pct | 140.1 | 132.5 | 128.7 |
| set_slice_p95 | ~84ms | ~78ms | ~92ms |

**Interpretation:**
- Booster is a **dominant amplifier** — reducing it collapsed overlap and materially improved drops.
- Booster is **not a sole cause** — both runs still crashed, but the crash CHARACTER changed.
- Reducing booster pressure **exposes a more tractable failure path** (F2 vs F1).
- Booster OFF is an **isolation tool**, not yet a product decision.

**P1 success criteria evaluation:**
- `crash=False` — FAILED (both runs crashed)
- `cpu_peak_pct < 100%` — FAILED (128.7%)
- `overlap_count < 50` — PASSED (0 in run #2)
- Overall: partial success — pressure improved but stability failure persists in a different family.

**Decision tree outcome:**
P1 landed on a mix of branches: no-crash criteria not met, but pressure clearly improved AND failure family changed. This was not anticipated by the original 5-branch tree. The correct next step is: **classify and guard the newly exposed Qt/WL/event path (Step 3), THEN P2A.**

---

## 12. Relationship to other docs

- `docs/stability/H13_WORKING_DOCUMENT.md`  
  Full evidence ledger and experiment history.

- `docs/pipelines/PYDICOM_2D_BACKEND.md`  
  Backend contract and critical architecture rules.

- `docs/viewer/FAST_PIPELINE_DETAILED.md`  
  Hot-path callback and render chain map.

- `docs/performance/PERFORMANCE_STATUS.md`  
  Performance guardrails and historical lessons for hot loops.

---

## 13. One-sentence summary

**Root cause confirmed:** VTK 9.6 PyPI wheel lacks `VTK_PYTHON_FULL_THREADSAFE=ON` — idle worker threads corrupt GIL state during VTK C++ `Render()`/`SetSlice()`, producing `Fatal Python error: PyThreadState_Get: GIL not held`. **H13-FIX (worker auto-shutdown) deployed as immediate mitigation.** Long-term resolution: replace VTK rendering in FAST mode with the existing Qt-native pipeline (`pydicom_qt` backend: `QtSliceViewer` + `Lightweight2DPipeline` + `QtViewerBridge`).
