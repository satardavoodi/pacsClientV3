# NEXT AGENT OPEN QUESTIONS — H13 Investigation

These are the questions that must be answered to solve the crash. They are ordered by what experiment answers them.

---

## Q1 — How frequently does stale-render occur at the insertion point?

**Why it matters:** If stale/mismatch events are frequent (>10 per P5 window), then TOCTOU suppression (T6 behavioral) is a justified first fix. If they are near zero, stale-render is not a primary trigger and we should focus entirely on pressure (H13-E).

**Current best guess:** Unknown. The `stale_cond_count` counter was just added this session and has never produced data. An earlier T6-OFF run showed `stale_abort_count=0` but that counter was toggle-gated — the value was meaninglessly zero, not a true 0-event measurement.

**What evidence would answer it:**
- Run Pipeline A with no env vars (all toggles OFF)
- After the run, check:
  ```powershell
  Select-String "\[H13-P5\]" $log | Select-String "stale_cond_count"
  Select-String "\[H13-T6-DIAG\].*reason=stale" $log | Measure-Object Count
  ```
- If `stale_cond_count > 0` consistently in P5 snapshots: stale-render events are real
- If `stale_cond_count ≈ 0` across all snapshots: stale render is not a frequent path

**Where to look next:** `_vw_backend.py` `_on_lazy_slice_ready_impl` T6 diag block (lines ~495–528); `[H13-P5]` in post-run log

---

## Q2 — Is booster-side decode pressure the dominant amplifier?

**Why it matters:** The `ImageSliceBooster` fires a large decode burst after download completion. Under Pipeline A, this burst overlaps with active scroll. If disabling the booster materially reduces CPU, dropped frames, and overlap_count, then booster management is the primary H13-E fix target.

**Current best guess:** Strong. Log 21-B (T6 OFF) showed CPU 140.9%, dropped 1538, overlap_count 329. The booster is the most likely source of the sustained decode burst that creates this pressure.

**What evidence would answer it:**
- Run P1: set `AIPACS_DISABLE_BOOSTER=1` (verify this env var is wired in `ImageSliceBooster.set_active()`, then run Pipeline A
- Compare: CPU peak, dropped_frames, overlap_count, overlap_max_ms, `set_slice_p95`
- If all metrics drop materially → booster is the dominant amplifier
- If metrics are unchanged → booster is NOT the primary source (re-examine primary amplifier)

**Where to look next:** `modules/viewer/fast/` — `ImageSliceBooster` code; search for `AIPACS_DISABLE_BOOSTER` to confirm env var support before running P1

---

## Q3 — Are both TOCTOU trigger AND pressure amplifier required to produce the crash?

**Why it matters:** If both are required simultaneously, the fix needs to address both. If either alone is sufficient, fixes can be simpler.

**Current best guess:** Both likely required. T6-OFF produced extreme pressure but NO crash in one run. T5 and T4 had lower pressure but crashed. This suggests pressure widens the dangerous window but something (TOCTOU?) is the actual trigger that makes it fatal.

**What evidence would answer it:**
- Compare T6 diagnostic run (stale_cond_count) with P1 (booster off) results
- If T6-OFF crashes frequently AND `stale_cond_count` is high → TOCTOU is primary trigger
- If P1 (booster off) eliminates crashes with high `stale_cond_count` remaining → pressure is primary gate
- If neither alone fixes it → both required; dual fix needed

**Where to look next:** `docs/stability/H13_FOCUSED_RECOVERY_PLAN.md §6.5 (decision goal mapping)` in `H13_WORKING_DOCUMENT.md §16.5`

---

## Q4 — Can T6 behavioral abort be activated safely?

**Why it matters:** T6 behavioral abort (early return when `reason=stale/mismatch`) is the proposed direct TOCTOU fix. But T6 ON crashed within 1 second in Log 21-A, suggesting the abort logic may have been incorrectly rejecting valid frames or causing state divergence.

**Current best guess:** The T6 ON crash was pre-instrumentation. We had no `stale_cond_count` data and the abort condition was not validated. The diagnostic run (Q1) will show whether the abort condition is stable.

**Before activating T6 behavioral abort (early return):**
1. Q1 must be answered — need `stale_cond_count` data
2. A run with T6 ON (abort active) + `[H13-T6-DIAG]` instrumentation must show abort decisions that are consistent with the viewer state (not false-positive aborts on valid frames)
3. The early return must be added to `_on_lazy_slice_ready_impl` at the exact insertion point (after `should_render_ready_slice` guard, before render chain)

**Where to look next:** `_vw_backend.py` lines ~495–528 — `[H13-T6-DIAG]` block; add early `return` statement ONLY after diagnostic data confirms the abort condition is stable

---

## Q5 — Is H13-A (zero-copy shared backing) a necessary enabling condition?

**Why it matters:** T3 (deep copy) would break the shared-memory link between worker writes and VTK render. If the crash disappears with T3, zero-copy is a necessary condition and the fix space narrows to synchronization or copy strategies.

**Current best guess:** Likely yes — both workers and VTK render access the same numpy-backed `vtkImageData`. But this has not been tested.

**Status:** T3 is deprioritized until P1/P2 pressure experiments are complete. Only run T3 if pressure experiments are insufficient.

**What evidence would answer it:**
- Set `AIPACS_VTK_DEEP_COPY=1`
- Run Pipeline A for 5+ minutes
- If no crash + no visual corruption → zero-copy is necessary condition → T3 confirms H13-A
- If crash persists → zero-copy is not sufficient root cause; H13-B (VTK/Py3.13 path) is primary

**Where to look next:** `modules/viewer/fast/pydicom_lazy_volume.py` lines 314–325 (T3 deep copy code); `modules/viewer/fast/_decode_guard.py` `_H13_DEEP_COPY` flag

---

## Q6 — Does the crash frequency change between Python 3.13 and an earlier Python version?

**Why it matters:** H13-B hypothesizes that Python 3.13's stricter GIL validation makes existing race conditions fatal that were previously silent. If confirmed, this would mean the race existed before but was tolerated.

**Current best guess:** Plausible but not investigated. Downgrading Python is a significant test environment change.

**Status:** Low priority. Only pursue if all other experiments are inconclusive.

**What evidence would answer it:**
- Run Pipeline A under Python 3.11 (if feasible) and compare crash rate
- If no crash at 3.11 + same crash at 3.13 → confirms H13-B is Py3.13-specific
- Practical blocker: test environment change requirement

**Where to look next:** `pyproject.toml` and `requirements.txt` for Python version constraints before attempting

---

## Answer Sequencing

| Question | Answered by | Dependency |
|----------|-------------|------------|
| Q1 (stale frequency) | T6 diagnostic run | None — do this first |
| Q2 (booster pressure) | P1 (booster off run) | After T6 diagnostic |
| Q3 (trigger vs amplifier) | Comparison of Q1+Q2 results | After Q1+Q2 |
| Q4 (T6 activation safety) | Diagnostic run data + Q1 | After Q1 |
| Q5 (zero-copy necessary) | T3 run | Only after P1+P2 inconclusive |
| Q6 (Py3.13 specific) | Environment test | Last resort |
