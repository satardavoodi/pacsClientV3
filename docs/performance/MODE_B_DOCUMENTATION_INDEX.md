# Mode B Performance — Documentation Index

**Version:** v2.2.3.2.9  
**Updated:** 2026-02-27  
**Status:** ✅ Active — see PERFORMANCE_STATUS.md for current snapshot

---

## 📌 Start Here

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **[PERFORMANCE_STATUS.md](PERFORMANCE_STATUS.md)** | **One-page current state: what's fixed, what's open, key numbers** | **Start here every session** |
| [METRICS_TRACKING_v2.2.3.x.md](METRICS_TRACKING_v2.2.3.x.md) | Phase-by-phase measurements and version history (v2.2.3.0.x → v2.2.3.2.2) | Review baseline vs current; fill in new measurements |
| [PERFORMANCE_DECISION_LOG_2026-02-27.md](PERFORMANCE_DECISION_LOG_2026-02-27.md) | Decisions from 2026-02-26/27 session | Trace why recent changes were made |
| [PERFORMANCE_DECISION_LOG_2026-02-24.md](PERFORMANCE_DECISION_LOG_2026-02-24.md) | Decisions from 2026-02-24 session | Historical context; log rotation, first B-mode diagnostics |
| [CROSS_PC_IMPROVEMENT_WORKFLOW.md](CROSS_PC_IMPROVEMENT_WORKFLOW.md) | PC A → GitHub → PC B validation cycle | After every code change |

---

## 📚 Reference Documents (Background / Historical)

| Document | Purpose |
|----------|---------|
| [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md) | Root cause analysis at v2.2.2.8 (pre-optimization baseline) |
| [MODE_B_QUICK_START_GUIDE.md](MODE_B_QUICK_START_GUIDE.md) | Implementation quickstart from v2.2.2.8 era |
| [MODE_AB_ARCHITECTURE_REVIEW_v2.2.3.1.5.md](MODE_AB_ARCHITECTURE_REVIEW_v2.2.3.1.5.md) | Architecture review at v2.2.3.1.5 |
| [ZETABOOST_PIPELINE_ANALYSIS.md](ZETABOOST_PIPELINE_ANALYSIS.md) | ZetaBoost engine design reference |
| [IMAGE_PIPELINE_REFERENCE.md](IMAGE_PIPELINE_REFERENCE.md) | Image load pipeline: DICOM → ITK → VTK |

---

## 🎯 What's in Each Document

### MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md

**Answers:** Why does lag still occur despite subprocess separation?

**Key Sections:**
- ✅ Root cause verified from real logs (ZetaBoost executes 0.6-0.9s ITK without yielding CPU first)
- ✅ Identified two mechanisms (boolean flag + global counter)
- ✅ Explained why both are insufficient
- ✅ Three prioritized fixes with code snippets
- ✅ Success metrics to validate improvements
- ✅ Implementation checklist

**Architecture Map:**
```
Download Manager (subprocess)
         ↓
ZetaBoost Engine (main process)
    ↓
Warmup Lane (NOT BLOCKED) ← ROOT CAUSE
    ↓
ITK Job (0.6-0.9s CPU hog)
    ↓
Viewer Blocked (gets minimal CPU) ← RESULT: LAG
```

**Quick Facts:**
- **Problem:** Global counter defined but orphaned (never called)
- **Fix 1:** Wire counter from download manager → instant lane block
- **Fix 2:** Defer jobs during download (optional, additional benefit)
- **Fix 3:** Increase yield duration (optional, safety)
- **Expected Improvement:** 30-50% overall (Fix 1 alone gives 30%)

---

### MODE_B_QUICK_START_GUIDE.md

**Answers:** How do I apply the fixes right now?

**Key Content:**
- Copy/paste code snippets for 3 fixes
- Exact line numbers and file locations
- Verification checklist (post-implementation testing)
- Expected improvements table
- Success metrics

**Fastest Path:**
1. Open [main_widget.py](main_widget.py#L2111) line 2111 → add 1 notify call
2. Open [main_widget.py](main_widget.py#L2296) line 2296 → add 1 notify call
3. Test with viewer + download scenario
4. Measure fps improvement

**Time Estimates:**
- Fix 1: 5 minutes (copies exactly from guide)
- Fix 2: 5 minutes (optional, increases margin)
- Fix 3: 1 minute (optional, safety)

---

## 🗑️ Deleted Documents (Why They Were Removed)

| Document | Reason | Alternatives |
|----------|--------|--------------|
| MODE_B_MEASUREMENT_PLAN_v2.2.2.8.md | Testing plan already executed; logs collected and analyzed |Refer to bottleneck analysis for evidence |
| MODE_B_SUBPROCESS_INVESTIGATION_v2.2.2.8.md | Findings already consolidated into bottleneck analysis | Read bottleneck analysis Part II |
| MODE_B_PERFORMANCE_COMPLETE_ANALYSIS_v2.2.2.5.md | Outdated (v2.2.2.5), superseded by v2.2.2.8 findings | Use bottleneck analysis v2.2.2.8 instead |

---

## 🚀 How to Use This Documentation

### Scenario 1: "I Need to Understand the Problem"
→ Read [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md) sections:
- The Problem (first 30 lines)
- Root Cause (verified from logs)
- Why Cached Content Lags (architecture explanation)

**Time:** 10 minutes

---

### Scenario 2: "I Need to Fix the Lag"
→ Follow [MODE_B_QUICK_START_GUIDE.md](MODE_B_QUICK_START_GUIDE.md):
1. Copy Fix 1 code snippets
2. Apply to main_widget.py (2 locations)
3. Test and verify improvements

**Time:** 15 minutes

---

### Scenario 3: "I Need to Verify the Root Cause"
→ Read [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md) sections:
- Log Evidence (real test output)
- Architecture: Why TWO Mechanisms Exist
- Three Fixes section (before/after code)

**Time:** 20 minutes

---

### Scenario 4: "I Need to Debug Why Fixes Didn't Work"
→ Check [MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md](MODE_B_BOTTLENECK_ANALYSIS_v2.2.2.8.md):
- Success Metrics section (expected values)
- Implementation Checklist (verification steps)
- Log Evidence (what to look for in logs)

**Time:** 15 minutes

---

## 📊 Key Facts at a Glance

| Aspect | Current State | After Fixes |
|--------|---------------|-------------|
| Root Cause | ZetaBoost warmup executes ITK 0.6-0.9s without CPU yield | Warmup lane blocked during download |
| Synchronization | Global counter orphaned (not called) | Counter wired to download manager |
| Viewer Lag | 30-50ms per frame during download | 17-22ms per frame (50% improvement) |
| FPS During Download | 14-20 fps (choppy) | 35-50 fps (smooth) |
| Implementation Effort | N/A | Fix 1: 5 min, Fix 2: 5 min (optional) |
| Risk Level | N/A | Very low (simple function calls) |

---

## ✅ Implementation Status Tracker

- [ ] **Fix 1 Wired:** Global counter calls added to main_widget.py
- [ ] **Fix 1 Tested:** Logs show download counter incrementing/decrementing
- [ ] **Viewer Performance Verified:** set_slice mean < 22ms during download
- [ ] **FPS Verified:** Scroll fps > 35 during download
- [ ] **Optional Fixes Applied:** Defer jobs and yield increase (if needed)

---

## 🔗 Related Documentation

For reference only (not directly used for Mode B fixes):
- [ZETA_MPR_PIPELINE_REFERENCE.md](../zeta_mpr_pipeline/ZETA_MPR_PIPELINE_REFERENCE.md) - MPR module architecture
- [IMAGE_PIPELINE_REFERENCE.md](../IMAGE_PIPELINE_REFERENCE.md) - Image pipeline details
- Version notes in [VERSION_2.2.2.6_CHANGELOG.md](../VERSION_2.2.2.6_CHANGELOG.md)

---

## 📞 Quick Reference

**File Locations for Fixes:**
- Fix 1a: [PacsClient/zeta_download_manager/ui/main_widget.py](../../PacsClient/zeta_download_manager/ui/main_widget.py) line 2111
- Fix 1b: [PacsClient/zeta_download_manager/ui/main_widget.py](../../PacsClient/zeta_download_manager/ui/main_widget.py) line 2296
- Fix 2: [PacsClient/pacs/patient_tab/zeta_boost/engine.py](../../PacsClient/pacs/patient_tab/zeta_boost/engine.py) line 1010
- Fix 3: [PacsClient/pacs/patient_tab/zeta_boost/engine.py](../../PacsClient/pacs/patient_tab/zeta_boost/engine.py) line 1100

**Methods to Wire:**
- [ZetaBoostEngine.notify_global_download_start()](../../PacsClient/pacs/patient_tab/zeta_boost/engine.py#L75)
- [ZetaBoostEngine.notify_global_download_stop()](../../PacsClient/pacs/patient_tab/zeta_boost/engine.py#L99)

---

**Status:** Documentation organized and consolidated  
**Next Action:** Apply fixes from quick start guide  
**Last Updated:** February 24, 2026
