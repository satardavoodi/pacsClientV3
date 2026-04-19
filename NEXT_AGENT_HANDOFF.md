# NEXT AGENT HANDOFF — H13 Investigation

**Date:** 2026-04-12  
**Investigation:** H13 — `Fatal Python error: PyThreadState_Get: GIL not held`  
**Scope:** FAST mode `pydicom_2d` viewer ONLY. Advanced viewer is out of scope.

---

## 1. Task / Problem Being Solved

### Bug
`Fatal Python error: PyThreadState_Get: the function must be called with the GIL held` — a hard process crash in the FAST-mode `pydicom_2d` viewer during **download + scroll overlap** (Pipeline A).

### Expected behavior
FAST viewer is stable and responsive during active download + rapid scrolling of a large CT series (200+ slices).

### Actual behavior
- Process crashes with the above fatal GIL error within seconds to minutes of starting Pipeline A
- Stack: main thread in VTK render chain (`set_slice` → `_flush_pending_wheel_slice_impl` or `_on_lazy_slice_ready_impl` → VTK `Render()`) while worker thread is in numpy C operations (`numpy._clip`)
- Even in non-crash runs, the system degrades severely: CPU > 140%, dropped frames up to 1538, `set_slice_p95 ≈ 84ms`, overlap_count up to 329

### Affected components
- `pydicom_2d` FAST backend only
- `PyDicomLazyVolume` worker decode/write path
- `VTKWidget._on_lazy_slice_ready_impl` hot callback
- VTK render chain under scroll pressure

### Severity
App-crashing. Loss of all viewer state. Reproducible within 1–5 minutes under Pipeline A.

---

## 2. Current Status

### Done
- Probes P1–P5 deployed (always-on, in production code)
- Toggle infrastructure coded: T3 (deep copy), T4 (render gate), T5 (keepalive), T6 (stale-render-abort)
- Live runs completed: Log 18 (baseline), Log 19 (T4), Log 20 (T5), Log 21-A (T6 ON), Log 21-B (T6 OFF)
- T4 result: crash persists even when write/render overlap is zeroed (does NOT fix it)
- T5 result: crash persists with no grow events (grow/UAF is NOT the dominant path)
- T6 instrumented: `[H13-T6-DIAG]` block added to `_on_lazy_slice_ready_impl`, `stale_cond_count` counter added (always-on, toggle-independent)
- Focused recovery plan written: `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md`

### Partially done
- T6 diagnostic run NOT yet performed with the new instrumentation
- `stale_cond_count` data for T6-OFF is **not yet collected** (counter was toggle-gated before this session; the split into `stale_cond_count` / `stale_abort_count` was just made)
- P1 (booster off) and P2 (throttle/window reduction) experiments not yet run

### Unresolved
- Whether stale-render TOCTOU is a **necessary** crash trigger
- Whether pressure (H13-E / booster) is dominant or subordinate
- Whether both must align to produce the crash

### Reproducibility
**Reliable** under Pipeline A (large CT download + rapid scrolling). Time-to-crash varies 1–4s after first scroll activity. T6-OFF produced no crash in one run but extreme pressure signals.

---

## 3. Where The Important Context Already Lives

| File | What it contains | Status |
|------|-----------------|--------|
| `docs/stability/H13_WORKING_DOCUMENT.md` | Full forensic evidence ledger: hypotheses table, probe/toggle inventory, all KPI tables (Logs 18–21), decision gate logic, phase procedures | **Current — primary reference** |
| `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md` | Distilled executable plan: what's proven, what's open, exact next-run order, guardrails, KPI set | **Current — day-to-day guide** |
| `modules/viewer/fast/_decode_guard.py` | All H13 probe functions (P1–P3), toggle flags (T3/T4/T5/T6), overlap stats | **Current — primary probe source** |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py` | Hot callback `_on_lazy_slice_ready_impl`, `_log_lazy_metrics_if_due` (P5), T6 diagnostic block, `_stale_condition_count` / `_stale_render_abort_count` counters | **Current — modified this session** |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py` | Scroll render path, T4 render gate call site, P1/P3 probe call sites | Current |
| `modules/viewer/fast/pydicom_lazy_volume.py` | `grow()` logic, T3/T5 implementation, P4 marker, worker loop, zero-copy VTK link | Current |
| `tests/viewer/test_fast_download_scroll_cpu_repro.py` | Test harness: timer-storm test, crash signature parser, `extract_h13_toggle_state()`, Phase 2A pre-screening (18 pass, 1 xfail) | Current |
| `docs/pipelines/PYDICOM_2D_BACKEND.md` | Architecture contract for pydicom_2d backend; critical wiring rules | Reference |
| `docs/viewer/FAST_PIPELINE_DETAILED.md` | Hot-path callback map; §7 identifies `_on_lazy_slice_ready_impl` as TOCTOU-sensitive point | Reference |
| `docs/performance/PERFORMANCE_STATUS.md` | Performance guardrails; scroll hot-path overhead budget; booster behavior at download completion | Reference |

---

## 4. Code Areas Touched or Most Relevant

### `modules/viewer/fast/_decode_guard.py` — lines 170–250
- All H13 probe functions: `h13_write_begin/end`, `h13_check_overlap_before_render`, `h13_get_decode_age_ms`, `h13_get_overlap_stats`
- Toggle flags: `_H13_DEEP_COPY`, `_H13_RENDER_GATE`, `_H13_KEEPALIVE`, `_H13_STALE_RENDER_ABORT`
- Global counters: `_WRITE_ACTIVE`, `_H13_OVERLAP_COUNT`, `_H13_OVERLAP_MAX_DURATION_NS`, `_WRITE_TIMESTAMPS`
- **Changed this session:** `_H13_STALE_RENDER_ABORT` added, `[H13-INIT]` log extended
- **Sensitive:** changing these affects measurement reliability for all future runs

### `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py` — lines 140–560
- `_reset_lazy_metrics()` — initializes `_stale_condition_count` and `_stale_render_abort_count`
- `_log_lazy_metrics_if_due()` lines 206–228 — emits `[H13-P5]` with `stale_cond_count` and `stale_abort_count`
- `_on_lazy_slice_ready_impl()` lines ~470–560 — hot callback; contains new T6 diagnostic block (lines ~495–528)
- **Changed this session:** `_stale_condition_count` counter added (always-on), `_stale_render_abort_count` behavior clarified (toggle-gated), `[H13-T6-DIAG]` block inserted
- **CRITICAL:** This is the TOCTOU-sensitive insertion point. The T6 diag block has NO early return — behavior unchanged.

### `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py` — lines 700–740
- Scroll path render chain, P1/P3 call sites, T4 gate
- **Not changed this session** but critical context

### `modules/viewer/fast/pydicom_lazy_volume.py` — lines 310–490, 585–615, 790–800
- `grow()` with P4 marker and T5 keepalive (lines 380–485)
- Zero-copy VTK link with T3 deep-copy option (lines 314–325)
- `get_metrics_snapshot()` for H13 fields (lines 585–615)
- Worker loop with P1 write probes (lines 795–800)
- **Not changed this session**

### `tests/viewer/test_fast_download_scroll_cpu_repro.py`
- Pre-flight requirement: must pass 18/1xfail before every manual run
- Contains `_extract_crash_signature()` and `extract_h13_toggle_state()` parsers
- **Not changed this session**

---

## 5. Changes Already Made (This Session)

### 5.1 `modules/viewer/fast/_decode_guard.py`
- **What:** Added `_H13_STALE_RENDER_ABORT = bool(os.environ.get("AIPACS_STALE_RENDER_ABORT"))`
- **Where:** After the existing T3/T4/T5 flag declarations (line ~191)
- **Why:** T6 behavioral toggle for stale-render abort (not yet active as behavioral change)
- **Status:** Wired but the abort path (`return` early) has NOT been added to `_on_lazy_slice_ready_impl` yet
- **Extended `[H13-INIT]` log:** Now includes `stale_render_abort=%s` field

### 5.2 `PacsClient/.../vtk_widget/_vw_backend.py`
- **What:** Counter split — `_stale_condition_count` (always-on) vs `_stale_render_abort_count` (toggle-gated)
  - `_stale_condition_count` increments whenever `reason=stale/mismatch` at the T6 insertion point, regardless of toggle state
  - `_stale_render_abort_count` only increments when `AIPACS_STALE_RENDER_ABORT=1`
  - Both initialized in `_reset_lazy_metrics()`, both emitted in `[H13-P5]` log as `stale_cond_count=N stale_abort_count=N`
- **What:** `[H13-T6-DIAG]` instrumentation block inserted in `_on_lazy_slice_ready_impl` AFTER the `should_render_ready_slice()` guard passes and BEFORE the render chain executes
  - Logs: `toggle_state`, `ready_slice`, `requested_slice`, `live_current_slice` (fresh `GetSlice()` re-read), `guard_current_slice`, `abort_decision` (shadow only), `reason`, `viewer_id`, `thread_id`
  - Log level: `INFO` when `reason=stale/mismatch`, `DEBUG` otherwise
  - **NO early return added — behavior is unchanged**
- **Why:** T6 OFF ran with no useful `stale_cond_count` data (counter was toggle-gated). This fix makes the next T6-OFF diagnostic run the **first valid measurement** of stale-render frequency.
- **Whether it helped:** Not yet measured (needs a new run)
- **Should stay:** Yes — this is diagnostic infrastructure, not a behavioral change

### 5.3 `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md`
- **What:** Created new document — focused execution companion to the working document
- **Why:** The working document is ~1000 lines; this distills what's proven, what's open, the next-run order, and guardrails
- **Status:** Current — primary day-to-day guide for the next agent

### 5.4 `docs/stability/H13_WORKING_DOCUMENT.md`
- **What:** §16 added (T6 classification, instrumentation spec, P1/P2 pressure experiment design, KPI comparison matrix); §11 status log updated with T6 ON/OFF results and instrumentation notes; file map updated with focused plan link
- **Status:** Current

---

## 6. What We Believe So Far

### Confirmed facts (direct code/log/test evidence)
- The crash is `PyThreadState_Get: GIL not held` — a C-level fatal error from Python 3.13
- The active backend at crash time is always `pydicom_2d` (FAST mode)
- The crash stack always shows main-thread VTK render chain + worker thread in numpy C operations
- T4 set overlap count to 0 but crash persisted: write/render overlap at `_load_lock` scope is NOT the crash mechanism
- T5 saw zero `grow()` events yet crash occurred: grow/UAF is NOT the dominant path for the current failure mode
- Typical time-to-crash under Pipeline A: ~1–4 seconds from first scroll event
- In high-pressure runs without crash: CPU peaks 140%, dropped frames up to 1538, overlap_count up to 329, overlap_max_ms = 39,257ms
- Previous T6-OFF `stale_abort_count=0` was NOT a real 0 — counter was toggle-gated and never incremented in OFF mode
- `stale_cond_count` is a new always-on counter; T6-OFF was run **before** this counter existed; **no valid `stale_cond_count` data exists yet**

### Strongly supported conclusions
- H13-B (VTK/numpy/Py3.13 C-level GIL interaction) is the likely lower-level crash mechanism: both crash threads are in GIL-released C code (VTK `Render()` + numpy `_clip`)
- H13-E (backpressure/pressure amplifier) is a major amplifier: overlap counts and dropped frames are extreme in high-pressure runs
- The crash is at a GIL-released C-code boundary — Python-level `threading.Lock` cannot synchronize it
- TOCTOU coherence gap is real: Log 20 showed `render slice=107 current=109` immediately before crash

### Open hypotheses
- Whether stale-render abort (T6 as a behavioral fix) would materially reduce crash frequency
- Whether booster-side decode pressure is a dominant amplifier (P1 experiment pending)
- Whether H13-A (zero-copy shared backing) is a **necessary** enabling condition (T3 not yet run)
- Whether both TOCTOU trigger AND pressure amplifier must align simultaneously

### Rejected / weak theories
- H13-C (grow UAF): weakened — T5 showed crash without any grow event
- H13-D (CPU as primary cause): weakened — Log 20 crashed at CPU 40.6%, much lower than Log 16's 110%
- T4 `_load_lock` as sufficient fix: confirmed inadequate — crash persisted with 0 overlaps

---

## 7. Evidence Pointers

### Key log markers to search for (post-run PowerShell)
```powershell
$log = "user_data\logs\viewer_diagnostics.log"

# H13 specific
Select-String "\[H13-INIT\]" $log | Select-Object -First 1           # confirm toggle state
Select-String "\[H13-OVERLAP\]" $log | Measure-Object Count          # P1/P2 overlap events
Select-String "\[H13-P5\]" $log | Select-Object -Last 5              # P5 pressure with stale_cond_count
Select-String "\[H13-T6-DIAG\]" $log | Measure-Object Count          # NEW: T6 insertion-point diag
Select-String "\[H13-T6-DIAG\].*reason=stale" $log | Measure-Object Count   # stale events only
Select-String "H13-GROW" $log | Measure-Object Count                 # P4 grow events
Select-String "Fatal Python error" $log | Select-Object -First 3     # crash
Select-String "dropped_frames_count" $log | Select-Object -Last 3    # pressure
Select-String "resource-summary" $log | Select-Object -Last 3        # CPU/RSS
```

### Crash signature (confirmed across all logs 18–21)
- File: `set_slice` → `_flush_pending_wheel_slice_impl` → `wheelEvent` OR `_on_lazy_slice_ready_impl`
- Worker thread: `pydicom_lazy_volume.py` `_worker_loop` / `_load_slice_blocking` / `numpy._clip`

### Key section to read in the working document
- `§11 Status Log` — full ordered history of all runs and findings
- `§13 Hypothesis Ranking` — updated after T4+T5
- `§16 T6 Classification` — current state of T6 analysis

### Automated analysis tool
```python
from tests.viewer.test_fast_download_scroll_cpu_repro import (
    _extract_crash_signature, extract_h13_toggle_state
)
log_text = open("user_data/logs/viewer_diagnostics.log").read()
print(_extract_crash_signature(log_text))
print(extract_h13_toggle_state(log_text))
```

---

## 8. Reproduction Guide

### Environment
- Windows, Python 3.13, VTK 9.x, PySide6
- No special env vars (baseline run) or specific toggle for toggle tests
- App: `python main.py`

### Pipeline A scenario (reliable crash trigger)
1. Launch app
2. Open a patient with a large CT series (200+ slices, prefer series being actively downloaded)
3. While download is in progress, **scroll rapidly** through slices
4. If a second series exists, drag-drop it to a different viewer
5. Continue for 2–5 minutes or until crash

### Success/failure criteria for a run
- **Crash** = `Fatal Python error: PyThreadState_Get: GIL not held` in log — same H13 family
- **Pressure failure** = CPU > 100%, dropped_frames > 200, `set_slice_p95 > 60ms` — even without crash
- **Healthy** = no crash AND `dropped_frames < 100`, CPU < 80%, `set_slice_p95 < 50ms`

### Reproduction reliability
**Reliable** within ~1–4 minutes under Pipeline A. However, CPU variance can shift time-to-crash. Single no-crash run is NOT conclusive — always compare pressure KPIs.

---

## 9. What The Next Agent Should Do First

### Step 1: Read
1. `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md` — sections 2, 5, 6, 11 (this is the operational guide)
2. `docs/stability/H13_WORKING_DOCUMENT.md` §11 status log (last 20 rows) and §16

### Step 2: Verify code changes are intact
Check that these counters exist and are initialized in `_vw_backend.py`:
```python
self._stale_condition_count = 0   # H13-T6: always-on
self._stale_render_abort_count = 0  # H13-T6: toggle-gated
```
And that `[H13-T6-DIAG]` block is present in `_on_lazy_slice_ready_impl` after the `should_render_ready_slice` guard.

### Step 3: Pre-flight test
```
python -m pytest tests/viewer/test_fast_download_scroll_cpu_repro.py tests/viewer/test_fast_viewer_pipeline.py -v
```
Must show: 18 pass + 1 xfail (for CPU repro) + 45 pass (for pipeline). DO NOT proceed to manual runs until this passes.

### Step 4: T6 diagnostic run (NO env vars)
```powershell
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
Remove-Item "user_data\logs\viewer_diagnostics.log*" -ErrorAction SilentlyContinue
# No env vars — all toggles OFF
python main.py
```
Run Pipeline A for 5 minutes. Then extract:
```powershell
$log = "user_data\logs\viewer_diagnostics.log"
Select-String "\[H13-T6-DIAG\]" $log | Measure-Object Count
Select-String "\[H13-T6-DIAG\].*reason=stale" $log | Measure-Object Count
Select-String "\[H13-P5\]" $log | Select-Object -Last 5
```
Goal: first valid measurement of `stale_cond_count`. This answers whether stale renders are frequent.

### Step 5: Based on T6 diagnostic results
- If `stale_cond_count > 10` per P5 snapshot → stale-render is real → proceed to P1 booster-off run
- If `stale_cond_count ≈ 0` → stale render is not frequent → go directly to P1/P2 pressure experiments
- Full decision guide: `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md §6, §11`

---

## 10. What The Next Agent Must Avoid Repeating

See `NEXT_AGENT_DO_NOT_REPEAT.md` for the full list.

### Critical short-list:
1. Do NOT activate T6 behavioral abort (early return in `_on_lazy_slice_ready_impl`) before verifying `stale_cond_count` data from a diagnostic run
2. Do NOT interpret T6 ON crash (Log 21-A) as "T6 abort makes things worse" — the crash was pre-instrumentation and the abort logic had no data to act on correctly
3. Do NOT rerun T4 (render gate) expecting different results — it already confirmed that Python-level `_load_lock` cannot synchronize GIL-released C code
4. Do NOT treat a no-crash run as conclusive without checking pressure KPIs (CPU, dropped frames, overlap_count)
5. Do NOT set `AIPACS_MAX_DECODE_THREADS=N` for experiment P2 — the default is already N=1 (serialized). Use booster window reduction or booster disable instead

---

## 11. Unwritten Context Captured From This Session

### Counter bug (now fixed)
Previous `stale_abort_count` in `[H13-P5]` was always 0 in T6-OFF runs because the counter was inside the `if _t6_toggle_on` block. It was NOT measuring "no stale events occurred" — it was measuring "toggle is off so counter never ran." The `stale_cond_count` split (this session) fixes this. **The previous Log 21-B `stale_abort_count=0` is invalid data and should be ignored.**

### T6 ON crash interpretation
T6 ON crashed in ~1 second (Log 21-A). The working interpretation is: the early abort was running but may have been aborting valid frames (because the logic was written without firm data on what constitutes "stale"), causing the viewer state to diverge faster and trigger the crash sooner. Do NOT interpret this as "aborting stale renders is dangerous in principle" — it means **the abort needs validated TOCTOU conditions, which we now have instrumentation for**.

### P2 experiment design correction (important)
The original session plan said "Run P2 with `AIPACS_MAX_DECODE_THREADS=1`." This is ALREADY the default. The actual P2 experiment should target **booster window reduction** (`AIPACS_BOOSTER_WINDOW=5` if wired, or `AIPACS_DISABLE_BOOSTER=1`). See `docs/stability/H13_WORKING_DOCUMENT.md §16.3`.

### Pressure is causal, not just correlated
T6-OFF showed CPU 140.9% and dropped 1538 frames in a no-crash run. T5 showed dropped 88–191 in a crash run (P5 overlap_avg=2.77). High pressure is consistently present in all crash runs and in the worst non-crash run. Pressure reduction is not optional optimization — it is probably a necessary condition for the final fix.

### `_load_lock` scope reality
The existing `_load_lock` in the FAST viewer path is a Python-level threading.Lock. VTK `Render()` releases the GIL to call C++ code. Worker `vol[i] = arr` releases the GIL for the numpy C operation. Python locks do NOT protect GIL-released code segments. T4 proved this directly: no Python-level overlaps, crash still occurred.

### TOCTOU gap evidence
Log 20 (T5 run) captured: `render slice=107 current=109` **immediately before** crash. This is a stale render entering VTK `Render()` for a frame that the viewer has already moved past. This is the clearest direct-trigger evidence we have, but it was only one observation.

---

## 12. Uncertainty / Risk Notes

- **`stale_cond_count` is new and untested.** First run to produce real data is still pending.
- **T6 abort logic is NOT implemented.** The enum variable `_H13_STALE_RENDER_ABORT` is wired but no early-return path exists yet in `_on_lazy_slice_ready_impl`. The current code is instrumentation-only.
- **P1/P2 pressure experiments are not yet designed in code** — `AIPACS_DISABLE_BOOSTER` and `AIPACS_BOOSTER_WINDOW` env var support may not exist; check `ImageSliceBooster` before running P1.
- **Single no-crash run (T6-OFF, Log 21-B) is not enough evidence that the pressure path is stable** — it showed extreme metrics.
- **H13 working document §11 status log is the ground truth** — if anything in this handoff conflicts with §11, trust §11.
