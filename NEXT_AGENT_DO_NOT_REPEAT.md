# NEXT AGENT DO NOT REPEAT — H13 Investigation

These are approaches that were already tried, theories that were already disproven, and traps to avoid.

---

## 1. DO NOT re-run T4 (render gate) expecting it to fix the crash

**What was tried:**  
Set `AIPACS_RENDER_GATE=1`. This wraps the full render chain (mark_vtk_modified + SetSlice + Render) in a `_load_lock` acquire/try-finally block in both `_vw_scroll.py:719` and `_vw_backend.py:526`.

**Why it seemed promising:**  
Phase 1 (Log 18) confirmed overlap_count=1. The decision table said: `overlap>0 + crash → T4`. Logic: if we lock around the render chain, workers can't write simultaneously.

**What actually happened (Log 19):**  
- overlap_count dropped to **0** (lock worked at Python level)
- **Crash still occurred** — same identical stack trace, same crash family
- `set_slice_p95` increased from 93ms to 113ms (lock contention overhead)

**How to think about it:**  
Python `threading.Lock` synchronizes Python-level threads, but VTK `Render()` and numpy `vol[i] = arr` both **release the GIL** to execute C code. A Python lock cannot protect GIL-released C code segments. The race is happening at the C++ level, not at Python level. T4 proved this definitively.

**Verdict:** T4 is an **exhausted avenue**. Do not retry it in any form unless the race moves to a different code boundary.

---

## 2. DO NOT re-run T5 (keepalive old volume) expecting it to fix the crash

**What was tried:**  
Set `AIPACS_KEEPALIVE_OLD_VOLUME=1`. This stashes the old `_volume` reference in `_old_volumes_keepalive` (capped at 5) after `grow()` replaces it.

**Why it seemed promising:**  
T4 (Log 19) showed grow(50→54) 4 seconds before crash. VTK might hold stale C++ pointers to old memmap arrays freed by GC. Keeping the old volume alive prevents UAF.

**What actually happened (Log 20):**  
- No `[H13-T5]` keepalive events logged → **no grow() occurred in this run at all**
- overlap_count=1 (T4 was off), crash still occurred
- New TOCTOU evidence: `render slice=107 current=109` immediately before crash
- Crashed at CPU 40.6% (much lower than prior runs)

**How to think about it:**  
H13-C (grow/UAF) was based on a correlation in T4 logs that turned out to be coincidental. T5 ran with no grow events and crashed anyway — the crash mechanism is grow-independent. The "T4 had grow, then crash" was noise.

**Verdict:** H13-C (grow/UAF) is a **weakened theory**. T5 is exhausted for the dominant current failure path. Only revisit if grow events reappear in a future log with a timing correlation.

---

## 3. DO NOT treat T6 ON crash (Log 21-A) as "T6 behavioral abort is harmful"

**What was tried:**  
Set `AIPACS_STALE_RENDER_ABORT=1`. T6 behavioral abort was intended to drop stale renders.

**Why it seemed promising:**  
Log 20 showed `render slice=107 current=109` before crash. Aborting stale renders seemed to be a direct trigger-suppression fix.

**What actually happened (Log 21-A):**  
- Crashed in ~1 second — faster than previous runs
- P5 data barely collected (too short a window)
- `stale_abort_count` was the only counter and it was toggle-gated → still showed 0 (pre-fix bug)

**How to think about it:**  
T6 ran **before** the `[H13-T6-DIAG]` instrumentation was added and before the counter bug was fixed. There was no data on what `abort_decision` was doing — it may have been aborting valid renders and causing viewer state divergence, which could independently trigger crashes. The result is **uninterpretable** without instrumentation.

**Verdict:** The T6 ON crash is **not a verdict on the hypothesis**. Do NOT conclude "aborting stale renders makes things worse." The diagnostic run (T6 OFF with new `stale_cond_count` instrumentation) must happen first. Only then activate T6 behavioral mode.

---

## 4. DO NOT use `AIPACS_MAX_DECODE_THREADS` for experiment P2

**What was originally planned:**  
Run P2 with `AIPACS_MAX_DECODE_THREADS=1` to throttle decode concurrency.

**Why it's a trap:**  
`AIPACS_MAX_DECODE_THREADS=1` is **already the default**. The H12 fix set the semaphore to 1 by default (doc: `_MAX_CONCURRENT_DECODE = int(os.environ.get("AIPACS_MAX_DECODE_THREADS", "1"))`). All runs including Log 21-B (CPU 140.9%, dropped 1538) were already at decode concurrency = 1. Setting it again adds zero information.

**How to think about it:**  
Decode serialization was done by H12 and is baked into the default. The pressure we're seeing is coming from the **booster** (ImageSliceBooster) firing decode bursts in parallel to the lazy worker, not from multiple lazy workers racing without a gate. The correct P2 experiment is booster window reduction, not decode thread reduction.

**Correct P2 approach:**  
- Use `AIPACS_DISABLE_BOOSTER=1` (P1) to remove booster entirely, OR  
- Reduce booster window (e.g., `AIPACS_BOOSTER_WINDOW=5` if wired) to narrow the burst

---

## 5. DO NOT trust Log 21-B `stale_abort_count=0` as evidence of "no stale events"

**What was observed:**  
T6 OFF run (Log 21-B) `[H13-P5]` showed `stale_abort_count=0` throughout.

**Why it seemed significant:**  
stale_abort_count=0 appeared to say "no stale renders occurred."

**What actually happened:**  
The counter was inside the `if _t6_toggle_on:` branch. With toggle=OFF, the counter NEVER ran regardless of how many stale renders occurred. The value 0 means "toggle was off" not "no stale events."

**Verdict:** Discard this data point completely. The first valid `stale_cond_count` measurement will come from the next diagnostic run (after the counter split fix in this session).

---

## 6. DO NOT expand scope to the Advanced viewer (VTK/SimpleITK backend)

**What this means:**  
The crash and all investigation are in the `pydicom_2d` FAST backend. Advanced viewer (`vtk_simpleitk` backend) has completely different code paths and does not show this crash.

**Why it's tempting:**  
Shared infrastructure (VTK container, scroll handler, patient_widget) touches both backends.

**How to think about it:**  
The crash has never been reported in Advanced mode. Any code change must NOT affect the Advanced backend. If investigating shared infrastructure, add backend guards (`if self._active_backend == BACKEND_PYDICOM`). The copilot-instructions.md explicitly says: "FAST and Advanced viewer caching/boosting protocols strictly separate."

---

## 7. DO NOT add synchronous I/O or blocking locks to the scroll hot path as mitigation

**What is tempting:**  
"If we add a lock around the slice write or slow down the workers, maybe the race window narrows."

**Why it's a trap:**  
The scroll path has a hard budget: `set_slice_p50 ~ 17–42ms`, `p95 ~ 45–83ms`. Adding synchronous blocking (Python lock with GIL-aware code) adds measurable latency. T4 already showed +20ms p95 from a Python-level render gate, and it didn't fix the crash. A lock inside the worker write path would stall decodes during scroll, potentially adding 50–150ms per slice.

**Correct approach:**  
Reduce the frequency of entering the dangerous window (stale-render abort, pressure reduction) rather than trying to hold a lock across GIL-released C boundaries.

---

## 8. DO NOT run toggle experiments without first collecting pre-flight test results

**What was skipped once:**  
T6 was run before `[H13-T6-DIAG]` instrumentation existed, making the result uninterpretable.

**Required pre-flight for every manual run:**
```
python -m pytest tests/viewer/test_fast_download_scroll_cpu_repro.py tests/viewer/test_fast_viewer_pipeline.py -v
```
Must show: 18 pass + 1 xfail + 45 pass.

If any test fails: investigate the failure before running live tests.

---

## 9. DO NOT interpret single-run crash/no-crash without pressure KPIs

**What happened:**  
T4 crashed → T4 failed. T6-OFF didn't crash → T6-OFF succeeded. Both are wrong conclusions.

**T4 analysis:**  
Crash under T4 was compared to "baseline crashed" → T4 failed. But T4 actually revealed critically important information: the race is GIL-released. Even a "failed" toggle test changes the hypothesis space.

**T6-OFF analysis:**  
No crash with CPU=140%, dropped=1538 is NOT a healthy run. The system was degraded to unusable levels. "No crash" in a single run with these metrics means nothing — pressure may be preventing the specific TOCTOU window by accident, or the run may just have been lucky.

**Rule:** A run is only evaluated using the full KPI set from the comparison table in `H13_WORKING_DOCUMENT.md §12.3`.

---

## 10. DO NOT skip the `[H13-INIT]` log line verification after setting a toggle

Every toggle run must begin by verifying in the **console output** before running the scenario:
```
[H13-INIT] toggles: deep_copy=False render_gate=False keepalive=False stale_render_abort=False
```
The relevant field must show `True` for the active toggle. If it doesn't, the toggle is NOT active — do not run the scenario, investigate why the env var isn't being read.
