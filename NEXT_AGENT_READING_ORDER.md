# NEXT AGENT READING ORDER — H13 Investigation

Read in this exact order. Do not skip Priority 1 before running any code.

---

## Priority 1 — Read First (before touching any code or running any tests)

### 1. `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md`
**Why first:** This is the distilled execution guide. It tells you what is proven, what is open, what to avoid, and the exact next-run order. Written specifically to prevent drift and repeated wasted work.  
**Key sections:**
- §2 "What the process has already accomplished" — wins and mistakes
- §5 "Proven vs not proven" — exact boundary of the evidence
- §6 "The focused plan" — Step 1 through Step 4 in order
- §11 "Immediate next run order" — the literal ordered list

### 2. `docs/stability/H13_WORKING_DOCUMENT.md` — §11 Status Log ONLY (last 20 rows)
**Why:** The full ground-truth log of every run, result, and code change. You only need the last 20 rows to understand current state.  
**Key markers:** Look for `T6 ON`, `T6 OFF`, `T6 instrumentation`, `stale_cond_count`, `counter split`, `focused plan created`

### 3. `docs/stability/H13_WORKING_DOCUMENT.md` — §16 Full Read
**Why:** The most recent section. Contains T6 classification, mandatory instrumentation spec, P1/P2 experiment design, and the KPI comparison matrix that must be filled in.  
**Key sub-sections:** §16.1 (T6 classification), §16.2 (instrumentation spec), §16.3 (P1/P2 experiment design), §16.4 (KPI matrix)

---

## Priority 2 — Read After Priority 1 (before manual live runs)

### 4. `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py` — lines 140–560
**Why:** All recent code changes are here. Verify:
- `_reset_lazy_metrics()` (line ~152): `_stale_condition_count = 0` and `_stale_render_abort_count = 0` both present
- `_log_lazy_metrics_if_due()` (lines ~206–228): `stale_cond_count=%d stale_abort_count=%d` in `[H13-P5]`
- `_on_lazy_slice_ready_impl()` (post-guard, lines ~495–528): `[H13-T6-DIAG]` block present, NO early return added

### 5. `modules/viewer/fast/_decode_guard.py` — lines 170–250 specifically
**Why:** Toggle flags and probe functions all live here. Verify `AIPACS_STALE_RENDER_ABORT` is wired, understand the `_WRITE_ACTIVE` / `_H13_OVERLAP_COUNT` overlap probe.

### 6. `tests/viewer/test_fast_download_scroll_cpu_repro.py`
**Why:** Run this before EVERY live test. Also contains `_extract_crash_signature()` and `extract_h13_toggle_state()` parsers you will use after every run.  
**Expected result:** 18 pass + 1 xfail. Any other result = problem, do not proceed to live run.

---

## Priority 3 — Only If Needed (background / deep dives)

### 7. `docs/stability/H13_WORKING_DOCUMENT.md` — §12 (Phase 2 procedure) and §13 (Hypothesis Ranking after T4+T5)
**Why:** Contains detailed decision gate tables for toggle interpretation. Reference this when a live run produces surprising results.  
**When to use:** After a live run produces unexpected outcomes, or when choosing between T3/P1/P2.

### 8. `docs/stability/H13_WORKING_DOCUMENT.md` — §14 (T4 run) and §15 (T5 run)
**Why:** Detailed KPI tables and interpretation for the two already-exhausted toggles. Use only if you need to understand WHY T4 and T5 were not sufficient.  
**When NOT to use:** Do not re-run T4 or T5 — these are done.

### 9. `modules/viewer/fast/pydicom_lazy_volume.py` — lines 310–490, 585–615, 795–800
**Why:** T3 deep-copy and T5 keepalive implementation details; `grow()` code; worker loop write probes. Read if you need to understand how the L1/L2 backing store is structured or if T3 becomes relevant.  
**When to use:** Only if P1/P2 pressure experiments are inconclusive and T3 is the next step.

### 10. `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py` — lines 700–740
**Why:** Scroll path, P1/P3 call sites, T4 gate. Needed only if investigating the scroll path as opposed to the lazy callback path.

### 11. `docs/pipelines/PYDICOM_2D_BACKEND.md`
**Why:** Architecture rules for the fast backend. Critical wiring constraints. Read this if proposing any structural change to the pipeline.  
**Key rule:** VTK viewer MUST be wired directly to raw `vtkImageData`, NOT through `image_reslice`. Any proposed fix must comply.

### 12. `docs/viewer/FAST_PIPELINE_DETAILED.md` — §7 specifically
**Why:** The TOCTOU-sensitive point (`_on_lazy_slice_ready_impl`) is documented with the full stale-frame guard logic. Reference when understanding why the T6 diag block is placed where it is.

### 13. `docs/performance/PERFORMANCE_STATUS.md`
**Why:** Performance targets, scroll hot-path overhead budget, booster behavior. Reference when evaluating whether a proposed fix costs too much latency.  
**Key targets:** Mode B p95 < 50ms for `set_slice`, no per-frame overhead >1ms in `set_slice`.

---

## File Map Quick Reference

```
docs/plans/stability/
  H13_FOCUSED_RECOVERY_PLAN.md    ← START HERE (operational guide)
  H13_WORKING_DOCUMENT.md         ← full evidence ledger (read §11 + §16)

modules/viewer/fast/
  _decode_guard.py                 ← all probes + toggle flags
  pydicom_lazy_volume.py           ← vol write path, T3/T5 code

PacsClient/.../vtk_widget/
  _vw_backend.py                   ← hot callback, T6 diag, P5 log (MODIFIED THIS SESSION)
  _vw_scroll.py                    ← scroll path, T4 gate

tests/viewer/
  test_fast_download_scroll_cpu_repro.py  ← pre-flight test + log parsers

docs/pipelines/
  PYDICOM_2D_BACKEND.md           ← architecture contract
docs/viewer/
  FAST_PIPELINE_DETAILED.md       ← callback map + §7 TOCTOU point
docs/performance/
  PERFORMANCE_STATUS.md           ← latency budget
```
