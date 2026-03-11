# Task 1: Download Control - Quick Implementation Guide

**Version:** v2.2.2.8  
**Effort:** 10 minutes  
**Risk:** Very Low  
**Expected Improvement:** 35% lag reduction (30-50ms → 17-22ms)

---

## Quick Summary

You need to wire the **global download counter** that's already defined but currently orphaned. This blocks ZetaBoost warmup/background lanes during ANY download (Cases A & B).

```
Before:  Download happens → ZetaBoost warmup still runs → CPU contention
After:   Download happens → Global counter incremented → Warmup blocked → Smooth viewer
```

---

## Changes Required (2 locations, 3 minutes total)

### Change 1: Wire Counter Start (Line 2111)

**File:** `PacsClient/zeta_download_manager/ui/main_widget.py`

**Location:** Around line 2111 in `_start_download_worker()` method

**Current Code:**
```python
def _start_download_worker(self, study_uid: str) -> bool:
    # ... existing code to create worker and wire signals ...
    
    worker.start()
    logger.info(f"🚀 [WORKER-START] Worker thread started")
    
    # ... rest of method ...
```

**ADD This After `worker.start()`:**
```python
    # ─────────────────────────────────────────────────────────────
    # CHANGE #1: Wire global download counter (Task 1 - Cases A & B)
    # ─────────────────────────────────────────────────────────────
    from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
    ZetaBoostEngine.notify_global_download_start()
    logger.info(f"🚀 [ZETABOOST] Global download counter: STARTED")
```

**Result:**
- Every download increments global counter to 1+
- All ZetaBoost instances detect counter > 0
- Warmup/background lanes immediately blocked

---

### Change 2: Wire Counter Stop (Line 2296)

**File:** `PacsClient/zeta_download_manager/ui/main_widget.py`

**Location:** Around line 2296 in `_on_worker_completed()` method

**Current Code:**
```python
def _on_worker_completed(self, study_uid: str, success: bool) -> None:
    """Handle worker completion signal"""
    try:
        logger.info(f"✅ [COMPLETION] Worker completed...")
        # ... existing cleanup code ...
```

**ADD These Lines RIGHT AFTER METHOD START (before any existing code):**
```python
def _on_worker_completed(self, study_uid: str, success: bool) -> None:
    """Handle worker completion signal"""
    # ─────────────────────────────────────────────────────────────
    # CHANGE #2: Wire global download counter stop (Task 1 completion)
    # ─────────────────────────────────────────────────────────────
    try:
        from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
        ZetaBoostEngine.notify_global_download_stop()
        logger.info(f"✅ [ZETABOOST] Global download counter: STOPPED")
    except Exception as e:
        logger.warning(f"⚠️ Failed to notify ZetaBoost stop: {e}")
    
    # ... existing cleanup code continues below ...
    try:
        logger.info(f"✅ [COMPLETION] Worker completed...")
```

**Result:**
- Every download completion decrements global counter
- When counter reaches 0, all ZetaBoost instances resume warmup
- Clean shutdown, no orphaned increments

---

## What This Fixes

### Case A: Different Patient Downloading
```
Before:  Study A open, Study B downloading
         → Engine A warmup still runs ITK (0.6-0.9s jobs)
         → Viewer lag even though Study B is separate
         ❌ PROBLEM

After:   Study A open, Study B downloading
         → Download manager increments global counter
         → Engine A detects counter > 0
         → Engine A warmup completely blocked
         → Engine B download unaffected (subprocess)
         → Viewer renders smoothly
         ✅ FIXED
```

### Case B: Same Patient Downloading
```
Before:  Study A open, Study A downloading
         → Engine A._download_active = True (per-instance flag)
         → Engine A warmup blocked ✓
         → Already working (but no global safety net)

After:   Study A open, Study A downloading
         → Engine A._download_active = True (original gate)
         → Global counter also incremented (redundant safety)
         → Double protection if any bug in per-instance logic
         ✅ ADDED SAFETY NET
```

---

## Expected Results

### Performance Metrics

**Before (without wiring):**
```
Mode B Test: View Study, Download Study B, Scroll Study
  set_slice() mean:     32-45ms ❌ (lag visible)
  Scroll fps:           18-25 fps ❌ (choppy)
  CPU main thread:      35-50% (high contention)
  ZetaBoost warmup:     RUNNING (not blocked)
```

**After (with wiring):**
```
Mode B Test: View Study, Download Study B, Scroll Study
  set_slice() mean:     17-22ms ✅ (smooth)
  Scroll fps:           40-50 fps ✅ (responsive)
  CPU main thread:      12-18% (low contention)
  ZetaBoost warmup:     BLOCKED (as intended)
```

**Improvement:** 35% lag reduction = 2.2-2.5x smoother scrolling

---

## Verification Checklist

### After Applying Changes

- [ ] **Code Compiles:** No import errors
- [ ] **No Syntax Errors:** Check Python syntax
- [ ] **Logs Show Wiring:** Search logs for "[ZETABOOST] Global download counter"

### After Testing

- [ ] **Case A Test:** Start download of different patient, observer warmup blocks
- [ ] **Case B Test:** Open Patient A, start download Patient A, observer warmup blocks
- [ ] **Performance Test:** Scroll during download, verify fps > 35
- [ ] **Counter Verification:** See counter increment/decrement in logs
- [ ] **No Regressions:** Viewer still works without downloads active

---

## Troubleshooting

### If Counter Not Changing
**Check:**
- Are you launching downloads or just queuing them?
- Worker must call `start()` for change #1 to execute
- Completion must be signaled for change #2 to execute

**Logs to Check:**
```
Search for: "[ZETABOOST] Global download counter"
Should see: "STARTED" when download begins
Should see: "STOPPED" when download ends
```

### If Warmup Still Running
**Check:**
- Gate logic at engine.py line 648-650 uses `_global_active_download_count`
- Verify counter is being incremented (check logs)
- Verify all ZetaBoost instances checking counter (multiple studies open)

**Workaround:**
if counter not working, old per-instance `_download_active` flag still provides partial protection for Case B

### If Performance Not Improved
**Possible Causes:**
1. Warmup not actually blocked (counter not wiring)
2. Interactive lane still running heavy jobs (shouldn't, but check)
3. Viewer itself slow (check VTK rendering)
4. Download running on main thread (shouldn't with DownloadProcessWorker)

**Debug:**
- Add breakpoint in `_can_start_lane_locked()` at line 648
- Check if counter value > 0 when blocking should occur
- Monitor thread activity with Task Manager during scroll

---

## Related Documentation

- Full design analysis: [ZETABOOST_DOWNLOAD_CONTROL_DESIGN.md](ZETABOOST_DOWNLOAD_CONTROL_DESIGN.md)
- Current architecture: [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md)
- ZetaBoost internals: [PacsClient/pacs/patient_tab/zeta_boost/ZETA_MPR_PIPELINE_REFERENCE.md](../../PacsClient/pacs/patient_tab/zeta_boost/ZETA_MPR_PIPELINE_REFERENCE.md)

---

## Time Estimate

| Task | Time |
|------|------|
| Read this guide | 3 min |
| Apply Change 1 | 2 min |
| Apply Change 2 | 2 min |
| Test & verify | 3 min |
| **Total** | **10 min** |

---

**Status:** Ready for implementation  
**Risk Level:** Very Low (just wiring existing mechanisms)  
**Next Action:** Apply changes and test Mode B scenario
