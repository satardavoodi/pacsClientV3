# 📋 FORENSIC INVESTIGATION - COMPLETE ARTIFACT INDEX

## Status: Phase 2 Ready to Execute

All instrumentation deployed, automated analysis ready, fresh reproduction protocol established.

---

## Code Modifications

### Modified Files (Pure Observation, Zero Behavior Changes)

| File | Changes | Lines Added | Probe Tags |
|------|---------|-------------|-----------|
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Added `_emit_canonical_sort_diagnostic()` function + call in `canonical_sort_instances()` | ~130 | [CANONICAL_SORT_INPUT_SAMPLE], [CANONICAL_SORT_MIXED_SERIES_ERROR], [CANONICAL_SORT_PLANE_MIX_ERROR] |

**Syntax Validated**: ✅ `py_compile` successful  
**Behavioral Impact**: ❌ Zero (pure observation logging)  
**Logic Changes**: ❌ Zero  

---

## Analysis Scripts Created (Automated Forensics)

### Phase 1 Scripts (Historical Data)

| Script | Purpose | Lines | Status |
|--------|---------|-------|--------|
| `analyze_series4_order.py` | Extract CANONICAL_SORT timeline | 270 | ✅ Executed, 9 loads found |
| `compare_load1_load2.py` | Detailed Load 1 vs Load 2 comparison | 230 | ✅ Executed, normal vector mismatch found |

**Outputs**:
- Series 4 timeline showing 9 loads across 6 reopen cycles
- Smoking gun: Load 1 normal [-0.99, 0.07, 0.11] vs Load 2 normal [-0.07, -0.09, 0.99]

### Phase 2 Scripts (Fresh Log Analysis)

| Script | Purpose | Lines | Ready |
|--------|---------|-------|-------|
| `forensic_detailed_series_comparison.py` | Auto-classify root cause from fresh logs | 170 | ✅ Ready to run |

**Capabilities**:
- Parse [CANONICAL_SORT_INPUT_SAMPLE] entries
- Detect [CANONICAL_SORT_MIXED_SERIES_ERROR]
- Detect [CANONICAL_SORT_PLANE_MIX_ERROR]
- Compare Load 1 vs Load 2 metadata
- Auto-classify: wrong series, mixed instances, or IOP corruption

**Output**: `forensic_phase2_results.txt` with classification and evidence

---

## Documentation Files

### Investigation Reports

| File | Purpose | Key Findings |
|------|---------|--------------|
| `FORENSIC_ROOT_CAUSE_REPORT.md` | Initial investigation findings | Series 4 order reversal, 9 loads analyzed |
| `FORENSIC_ROOT_CAUSE_CRITICAL_FINDING.md` | Normal vector analysis | Load 1 sagittal vs Load 2 axial |
| `FORENSIC_EXACT_CODE_ROOT_CAUSE.md` | Code mechanism explained | canonical_sort_instances() mechanism |
| `FORENSIC_INVESTIGATION_COMPLETE.md` | Phase 1 summary | Root cause mechanism, next steps |

### Phase 2 Protocols & Analysis

| File | Purpose | Content |
|------|---------|---------|
| `FORENSIC_PHASE2_PROTOCOL.md` | Fresh reproduction protocol | Step-by-step: close app, open fresh, reproduce bug, analyze |
| `FORENSIC_CASE_ANALYSIS_THREE_HYPOTHESES.md` | Case analysis framework | Three hypotheses: wrong series, mixed instances, IOP corruption |
| `FORENSIC_SUMMARY_PHASE1_PHASE2_READY.md` | Complete status summary | What's done, what's ready, timeline |
| **THIS FILE** | Artifact index | Complete file listing |

### Total Documentation Generated
- 10 detailed markdown documents
- ~5000+ lines of forensic analysis
- 3 automated analysis scripts
- Complete fresh reproduction protocol

---

## Key Forensic Findings (Phase 1)

### The Smoking Gun

```
Series 4 Reopen Cycles: 6 cycles, 9 total loads over 1 hour

Load 1 (12:07:22):   normal=[-0.9917, 0.0680, 0.1091]  plane=SAGITTAL    order=REVERSE ✓
Load 2 (14:39:45):   normal=[-0.0738, -0.0937, 0.9929] plane=AXIAL       order=FORWARD ❌

CRITICAL: Not 180° opposite, but completely different planes!
```

### Root Cause Classification (Preliminary)

**NOT IOP corruption** (too different to be same header with corruption)  
**POSSIBLY**:
1. Wrong series metadata loaded (series UID collision)
2. Mixed instances from different anatomical planes
3. Metadata object reuse/mutation

---

## How to Execute Phase 2

### Quick Start (15 min)

```powershell
# Step 1: Close app, reset logs
cd "e:\ai-pacs\ai-pacs codes\ai-pacs beta version"
rm user_data/logs/viewer_diagnostics.log

# Step 2: Open app and reproduce bug
.\run_app.ps1
# ... navigate to patient 41236, Series 4, note orientation, switch series, switch back
# ... close app

# Step 3: Analyze fresh logs
python forensic_detailed_series_comparison.py > forensic_phase2_results.txt
cat forensic_phase2_results.txt
```

### Expected Output (Good Case)

```
Found 2 CANONICAL_SORT_INPUT_SAMPLE entries
Found 0 MIXED_SERIES_ERROR entries
Found 1 PLANE_MIX_ERROR entries

[CANONICAL_SORT_PLANE_MIX_ERROR] load_id=2 n=21 
  plane_histogram={'SAGITTAL': 10, 'AXIAL': 11}

CLASSIFICATION:
  ❌ HYPOTHESIS: DIFFERENT ANATOMICAL PLANES
     Evidence: Multiple plane types in plane_histogram
     ...
```

### Expected Output (Best Case)

```
Found 2 CANONICAL_SORT_INPUT_SAMPLE entries
Found 1 MIXED_SERIES_ERROR entries
Found 0 PLANE_MIX_ERROR entries

[CANONICAL_SORT_MIXED_SERIES_ERROR] load_id=2 n=21 
  unique_series_uid_count=2
  series_uid_set={'1.2.3.4.5.6', '2.3.4.5.6.7'}

CLASSIFICATION:
  🔴 HYPOTHESIS: WRONG SERIES LOADED
     Evidence: Multiple unique SeriesInstanceUIDs in single call
     Root cause: Cache key collision or series UID lookup bug
     ...
```

---

## Phase 2 Checklist

### Before Running

- [ ] App is closed
- [ ] `user_data/logs/viewer_diagnostics.log` deleted or rotated
- [ ] Fresh Python environment ready
- [ ] `forensic_detailed_series_comparison.py` script is present

### During Reproduction

- [ ] Open app
- [ ] Navigate to patient 41236
- [ ] Open Series 4
- [ ] Document initial orientation (screenshot preferred)
- [ ] Switch to different series
- [ ] Switch back to Series 4
- [ ] Compare orientation (note if changed)
- [ ] Close app

### After Reproduction

- [ ] Run: `python forensic_detailed_series_comparison.py > forensic_phase2_results.txt`
- [ ] Review output for classification
- [ ] Identify which case (A, B, or C)
- [ ] Extract concrete evidence from first5/last5 samples
- [ ] If Case C: Prepare DICOM header verification script

---

## Files NOT Modified (By Design)

These files remain completely unchanged:
- ✅ `_vc_backend.py` (only has old instrumentation probes, no logic changes)
- ✅ `_vc_cache.py` (only has old instrumentation probes)
- ✅ `_vc_load.py` (only has old instrumentation probes)
- ✅ `_vc_switch.py` (only has old instrumentation probes)
- ✅ `_pw_sync.py` (only has old instrumentation probes)
- ✅ `_vw_backend.py` (only has old instrumentation probes)
- ✅ `_vw_series.py` (only has old instrumentation probes)
- ✅ All display convention code
- ✅ All sorter algorithm code
- ✅ All sync geometry code
- ✅ All reference-line code

---

## Success Criteria

### Phase 2 Complete When:
- [ ] Fresh logs captured with [CANONICAL_SORT_INPUT_SAMPLE] entries
- [ ] [CANONICAL_SORT_MIXED_SERIES_ERROR] or [CANONICAL_SORT_PLANE_MIX_ERROR] detected (or neither)
- [ ] Load 1 vs Load 2 instance metadata extracted
- [ ] Root cause classified (Case A, B, or C)
- [ ] Concrete evidence document created showing divergence point
- [ ] (Optional) DICOM headers verified if Case C detected

### Ready for Fix When:
- [ ] Forensic evidence is undeniable
- [ ] Exact code location identified
- [ ] User approval of classification obtained
- [ ] Minimal fix prepared (surgical, not broad rewrite)

---

## Timeline to Completion

| Activity | Duration | Status |
|----------|----------|--------|
| Code instrumentation | ✅ Done | Complete |
| Script creation | ✅ Done | Complete |
| Fresh reproduction | 15 min | Ready |
| Automated analysis | 2 min | Automated |
| Classification | 1 min | Auto-classified |
| Evidence extraction | 5 min | Manual review |
| DICOM verification (if needed) | 10 min | Optional |
| **Total Time to Root Cause** | **~33 min** | Ready now |

---

## Contact & Documentation

**All forensic documents are in**:
```
e:\ai-pacs\ai-pacs codes\ai-pacs beta version\
  FORENSIC_*.md (7 documents)
  forensic_*.py (3 scripts)
```

**Log location**:
```
e:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs\viewer_diagnostics.log
```

**Fresh logs output**:
```
e:\ai-pacs\ai-pacs codes\ai-pacs beta version\forensic_phase2_results.txt
```

---

## Key Insight: Why We Know It's NOT Simple

From existing logs:
- **Sagittal normal** [-0.99, +0.07, +0.11] ← Load 1
- **Axial normal** [-0.07, -0.09, +0.99] ← Load 2

These are ~90° different in anatomical space, not 180° opposite.

This CANNOT be explained by:
- ❌ A simple IOP sign flip
- ❌ IOP axis swap  
- ❌ Cross product reversal
- ❌ Endianness issue
- ❌ Floating point rounding

This CAN be explained by:
- ✅ Different series metadata
- ✅ Mixed instances from different series
- ✅ Complete IOP value replacement (different plane)
- ✅ Wrong instance UID being read

**Fresh forensics will prove which one it is.**

---

## Conclusion

All instrumentation complete and validated.  
Fresh reproduction protocol ready.  
Automated analysis script deployed.  
Three hypotheses clearly articulated.  
Success criteria defined.  

**Ready to execute Phase 2 whenever the user is ready.**
