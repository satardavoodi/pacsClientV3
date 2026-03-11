# Mode B Performance - Implementation Quick Reference

**Version:** v2.2.2.8  
**Created:** February 24, 2026  
**Purpose:** Fast-track guide to apply fixes and verify improvements

**Status:** Root cause confirmed from logs. Ready for implementation.

---

## 🎯 Goal

Apply three fixes to wire global download counter and restore viewer responsiveness (30-50% lag reduction expected).

---

## ⚡ Quick Implementation (15 Minutes)

### Fix 1: Wire Download Counter (5 min)

**File 1:** [PacsClient/zeta_download_manager/ui/main_widget.py](main_widget.py#L2111)

**At line 2111 (after `worker.start()`):**
```python
worker.start()
logger.info(f"🚀 [WORKER-START] Worker thread started")

# ADD THESE LINES:
from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
ZetaBoostEngine.notify_global_download_start()
```

**File 2:** [main_widget.py](main_widget.py#L2296) - Line 2296 (first line of `_on_worker_completed`)

**At line 2296:**
```python
def _on_worker_completed(self, study_uid: str, success: bool) -> None:
    """Handle worker completion signal"""
    # ADD THESE LINES FIRST:
    try:
        from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
        ZetaBoostEngine.notify_global_download_stop()
    except Exception as e:
        logger.warning(f"Failed to notify ZetaBoost stop: {e}")
    
    # REST OF METHOD CONTINUES:
```

**Result:** Warmup lane blocked completely during download → No ITK jobs execute → Viewer CPU uncontested

---

### Fix 2: Defer Jobs (Optional, 5 min)

**File:** [PacsClient/pacs/patient_tab/zeta_boost/engine.py](engine.py#L1010)

**At line 1010 (before job execution):**
```python
# If download active, skip this job iteration
if (_GLOBAL_DOWNLOAD_ACTIVE or self._download_active) and lane in ("warmup", "background"):
    self._queue[lane].appendleft(series_number)
    with self._cv:
        self._cv.wait(timeout=2.0)
    continue
```

**Result:** Additional 20% improvement (jobs skip entirely during download)

---

### Fix 3: Increase Yield (Optional, 1 min)

**File:** [engine.py](engine.py#L1100) - Line 1100

**Change:**
```python
# FROM:
if _any_dl:
    time.sleep(2.0)

# TO:
if _any_dl:
    time.sleep(3.5)    # Exceeds max job duration (0.9s)
```

**Result:** Additional 5% improvement (safety margin)

---

## ✅ Verification Checklist

After applying fixes:

- [ ] **Fix 1 applied:** Lines 2111 and 2296 in main_widget.py have notify calls
- [ ] **Tests pass:** No import errors or syntax issues
- [ ] **Logs check:** Run app, start download, see `Notified ZetaBoost` messages
- [ ] **Performance test:** Open cached study, start download, scroll—measure fps improvement
- [ ] **Baseline comparison:** set_slice mean < 22ms during download (was 30-50ms)

---

## 📊 Expected Improvements

| Metric | Before | After Fix 1 | After Fixes 1+2 |
|--------|--------|------------|-----------------|
| set_slice mean | 30-50ms | 20-25ms | 17-22ms |
| Scroll fps | 14-20 | 30-40 | 35-50 |
| CPU (main) | 30-50% | 15-25% | 10-20% |

---

## 📁 Reference Documents

- [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md) ← Root cause + detailed fixes
- [MODE_B_MEASUREMENT_PLAN_v2.2.2.8.md](MODE_B_MEASUREMENT_PLAN_v2.2.2.8.md) ← Original test procedures

---

**Status:** Ready to implement  
**Next Action:** Apply Fix 1 above, test, then decide if Fix 2/3 needed
