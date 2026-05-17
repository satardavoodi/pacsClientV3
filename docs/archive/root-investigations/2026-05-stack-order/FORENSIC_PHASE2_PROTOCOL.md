# 🔍 FORENSIC ANALYSIS - PHASE 2: DETAILED INSTANCE METADATA COMPARISON

## Status

**Previous Findings**: 
- Load 1 normal: [-0.9917, 0.068, 0.1091] = sagittal-like ✓ Correct
- Load 2 normal: [-0.0738, -0.094, 0.993] = axial-like ❌ COMPLETELY DIFFERENT PLANE
- Same series UID (UI says series 4), same instances (0001-0021), completely different geometric planes

**Hypothesis Before**: IOP corruption in instance metadata

**New Hypothesis**: 
One of these is more likely:
1. **WRONG SERIES LOADED** — Load 2 metadata from a different series
2. **MIXED SERIES LIST** — Load 2 contains instances from multiple series  
3. **PLANE MIX** — Load 2 contains instances from different anatomical planes
4. **CACHE KEY COLLISION** — Cache returning instances from wrong series_uid
5. **INSTANCE PATH/FILE MISMATCH** — File paths differ between loads
6. **METADATA OBJECT REUSE** — Same instance dict reused, mutated in-place

---

## Phase 2 Instrumentation Deployed

### New Forensic Probes in `image_io.py::canonical_sort_instances()`

```python
@entry
[CANONICAL_SORT_INPUT_SAMPLE]
  load_id=<N>
  n=<instance_count>
  unique_series_uid_count=<M>
  unique_sop_count=<K>
  plane_histogram={AXIAL:5, SAGITTAL:15, CORONAL:0}
  first5=[
    {path, sop_uid, series_uid, instance_number, ipp, iop, normal, plane},
    ...
  ]
  last5=[...]

[CANONICAL_SORT_MIXED_SERIES_ERROR] if unique_series_uid_count > 1
  load_id=<N>
  n=<instance_count>
  unique_series_uid_count=<M>
  series_uid_set={uid1, uid2, ...}

[CANONICAL_SORT_PLANE_MIX_ERROR] if plane_histogram has >1 dominant plane
  load_id=<N>
  n=<instance_count>
  plane_histogram={...}
```

---

## Fresh Reproduction Protocol (Required)

### Step 1: Close App & Rotate Log (5 min)

```powershell
# 1. Close the running AIPacs application (unlock log file)
# 2. Delete or rotate the baseline log
cd "e:\ai-pacs\ai-pacs codes\ai-pacs beta version"
rm user_data/logs/viewer_diagnostics.log
# Or rename it:
# mv user_data/logs/viewer_diagnostics.log user_data/logs/viewer_diagnostics.log.baseline
```

### Step 2: Open App Fresh (2 min)

```powershell
# Activate venv and run app
.\run_app.ps1
```

### Step 3: Navigate to Patient 41236 (1 min)

- Click Home or Patient List
- Search for or open patient 41236
- Wait for patient to fully load

### Step 4: Navigate to Series 4 (1 min)

- Find Series 4 in the sidebar
- Click on it to load and display
- Wait for image to appear
- Note the orientation (e.g., sagittal, coronal, axial)
- Document via screenshot or log

### Step 5: Close and Reopen Series (2 min)

- Switch to a different series (any other)
- Switch back to Series 4
- Compare orientation with Step 4
- If orientation changed → **BUG REPRODUCED**

### Step 6: Close App & Extract Logs (5 min)

```powershell
# Close the app
# Then extract the fresh logs

Get-Content user_data/logs/viewer_diagnostics.log | 
  Select-String -Pattern '\[CANONICAL_SORT' | 
  Out-File fresh_canonical_sort_logs.txt

Get-Content user_data/logs/viewer_diagnostics.log | 
  Select-String -Pattern '\[ADVANCED_' | 
  Out-File fresh_advanced_probes_logs.txt
```

---

## Analysis Protocol (After Fresh Logs)

### Step 1: Run Forensic Comparison Script

```powershell
python forensic_detailed_series_comparison.py > forensic_report_phase2.txt
```

This will automatically:
- Parse all [CANONICAL_SORT_INPUT_SAMPLE] entries
- Detect [CANONICAL_SORT_MIXED_SERIES_ERROR] if unique_series_uid_count > 1
- Detect [CANONICAL_SORT_PLANE_MIX_ERROR] if multiple plane types present
- Compare Load 1 vs Load 2 instance counts, series UIDs, SOPInstanceUIDs, planes
- Auto-classify the root cause:
  - **MIXED_SERIES** → Wrong series loaded
  - **PLANE_MIX** → Mixed instances from different planes
  - **Neither** → IOP values are different for same instances (need DICOM header verification)

### Step 2: Classification Outcomes

#### Outcome A: MIXED_SERIES_ERROR detected
```
Finding: Multiple unique SeriesInstanceUIDs in single canonical_sort call
Proof: unique_series_uid_count > 1 in [CANONICAL_SORT_INPUT_SAMPLE]
Conclusion: **CACHE KEY COLLISION or WRONG SERIES LOOKUP**
Next: Check _vc_backend.py::_get_series_from_cache() series_uid matching
```

#### Outcome B: PLANE_MIX_ERROR detected
```
Finding: AXIAL instances mixed with SAGITTAL instances (or similar)
Proof: plane_histogram={AXIAL:10, SAGITTAL:11} in [CANONICAL_SORT_INPUT_SAMPLE]
Conclusion: **WRONG INSTANCES or MIXED METADATA**
Next: Compare file_path values from first5/last5 across loads
      Verify file_path prefixes all point to Series 4 directory
```

#### Outcome C: Neither error detected (clean unique_series_uid, uniform planes)
```
Finding: Same series UID, same planes, but different geometric normal
Proof: first5/last5 show same SOPInstanceUIDs but different IOP values
Conclusion: **IOP CORRUPTION in instance metadata**
Next: Extract actual IOP from first5/last5, compare Load 1 vs Load 2
      If same SOP has different IOP, read DICOM header directly
```

### Step 3: Extract Detailed Comparison Data

```python
# From forensic_report_phase2.txt, look for:

# Load 1 metadata
load1_first5 = [
  {path: "...", sop_uid: "xyz123", series_uid: "1.2.3.4", iop: "[...], normal: "[...]", plane: "SAGITTAL"},
  ...
]

# Load 2 metadata  
load2_first5 = [
  {path: "...", sop_uid: "abc789", series_uid: "5.6.7.8", iop: "[...], normal: "[...]", plane: "AXIAL"},
  ...
]

# Compare:
# 1. Are the file_path values identical?
# 2. Are the sop_uid values identical?
# 3. Are the series_uid values identical?
# 4. Are the iop values identical for same sop_uid?
# 5. Are the plane values identical?
```

---

## Success Criteria for Forensic Proof

### Success: FORENSIC CHAIN COMPLETE
- ✅ Fresh logs captured showing [CANONICAL_SORT_INPUT_SAMPLE] with detailed instance data
- ✅ Load 1 vs Load 2 comparison shows concrete differences (sop_uid, path, series_uid, or iop)
- ✅ Root cause classified: wrong series, mixed instances, or IOP corruption
- ✅ Exact divergence point identified from instance metadata
- ✅ File-level evidence (if needed): DICOM header read with pydicom confirming IOP mismatch

### Success: Ready for Fix
Once forensic proof is complete, we can propose a fix targeted at the exact mutation/cache/lookup point.

---

## Timeline

| Phase | Duration | Blocker | Status |
|-------|----------|---------|--------|
| Code instrumentation | ~15 min | None | ✅ COMPLETE |
| Fresh reproduction | ~15 min | Need running app + patient 41236 | ⏳ READY TO RUN |
| Log analysis | ~10 min | Fresh logs | ⏳ READY TO RUN |
| Classification | ~5 min | Forensic comparison script | ✅ SCRIPT READY |
| DICOM verification (if needed) | ~10 min | IOP mismatch detected | ⏳ CONDITIONAL |
| Fix proposal | ~30 min | Forensic proof complete | ⏳ BLOCKED UNTIL FORENSICS DONE |

---

## Important Notes

### DO NOT
- Change any sorter logic
- Modify display convention
- Alter sync geometry
- Edit reference-line math
- Propose fixes until forensic proof is complete

### DO
- Capture fresh logs with new instrumentation
- Extract [CANONICAL_SORT_INPUT_SAMPLE] entries
- Compare instance metadata across loads
- Verify file paths and UIDs match expectations
- Read DICOM headers directly if IOP mismatch suspected

---

## Expected Output from Fresh Logs

**If instrumentation working**:
```
[CANONICAL_SORT_INPUT_SAMPLE] load_id=1 n=21 unique_series_uid_count=1 unique_sop_count=21 plane_histogram={'SAGITTAL': 21} first5=[...] last5=[...]
[CANONICAL_SORT_INPUT_SAMPLE] load_id=2 n=21 unique_series_uid_count=1 unique_sop_count=21 plane_histogram={'AXIAL': 21} first5=[...] last5=[...]
```

**If mixed series detected**:
```
[CANONICAL_SORT_MIXED_SERIES_ERROR] load_id=2 n=21 unique_series_uid_count=2 series_uid_set={'1.2.3.4', '5.6.7.8'}
```

**If plane mix detected**:
```
[CANONICAL_SORT_PLANE_MIX_ERROR] load_id=2 n=21 plane_histogram={'AXIAL': 11, 'SAGITTAL': 10}
```

---

## Next Command

When ready to start fresh reproduction:

```powershell
# 1. Close app if running
# 2. Run this to prepare:
cd "e:\ai-pacs\ai-pacs codes\ai-pacs beta version"
rm user_data/logs/viewer_diagnostics.log  # Reset baseline

# 3. Open app
.\run_app.ps1

# 4. After reproducing bug and closing app:
python forensic_detailed_series_comparison.py > forensic_report_phase2.txt
cat forensic_report_phase2.txt
```
