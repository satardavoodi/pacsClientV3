# 🚨 CRITICAL INSIGHT: Why The Normal Vectors Are Different

## The Discovery

From the existing logs, we extracted these CANONICAL_SORT entries for Series 4:

**Load 1** (2026-05-14 12:07:22):
```
Mean Normal computed: [-0.9917, 0.0680, 0.1091]
This is sagittal-like (X-axis dominant)
Instances sorted REVERSE (head > tail in slice order)
```

**Load 2** (2026-05-14 14:39:45):
```
Mean Normal computed: [-0.0738, -0.0937, 0.9929]
This is axial-like (Z-axis dominant) 
Instances sorted FORWARD (tail > head in slice order)
```

---

## Why This Matters

These are NOT 180° opposite vectors.  
They are **different planes entirely**:

```
Load 1 normal: [-0.99, +0.07, +0.11] ≈ sagittal plane (perpendicular to L/R axis)
Load 2 normal: [-0.07, -0.09, +0.99] ≈ axial plane (perpendicular to S/I axis)

These are orthogonal anatomical planes! 
The difference is ~90° change in slice orientation.
```

---

## The Three Hypotheses

### Hypothesis A: WRONG SERIES METADATA
```
What if Load 2 is actually loading a DIFFERENT SERIES?

Example:
  Series 4 has sagittal slices (all with sagittal IOP)
  But Load 2 loads some instances from Series 5 (axial slices with axial IOP)
  
Result:
  mean_normal = average of (sagittal IOPs + axial IOPs) = twisted/wrong result
  OR if all instances are from different series:
  mean_normal = average of ONLY axial IOPs = axial normal

Evidence to look for:
  - [CANONICAL_SORT_MIXED_SERIES_ERROR] in logs
  - unique_series_uid_count > 1 in [CANONICAL_SORT_INPUT_SAMPLE]
  - series_uid mismatch in first5/last5 samples
```

### Hypothesis B: MIXED INSTANCES
```
What if Load 2's instance list contains instances from DIFFERENT ANATOMICAL PLANES?

Example:
  Load 1: all 21 instances are sagittal slices from Series 4
  Load 2: 10 sagittal instances + 11 axial instances = mixed list
  
Result:
  mean_normal = average of (10 sagittal + 11 axial) normals = twisted/axial result
  Depends on which plane dominates in the average

Evidence to look for:
  - [CANONICAL_SORT_PLANE_MIX_ERROR] in logs
  - plane_histogram={SAGITTAL: 10, AXIAL: 11} in [CANONICAL_SORT_INPUT_SAMPLE]
  - File paths or series_uids differ in first5 vs last5 samples
```

### Hypothesis C: IOP CORRUPTION
```
What if the SAME instances have DIFFERENT IOP values between loads?

Example:
  Load 1: Instance 0001 has IOP = [1, 0, 0; 0, 1, 0] (sagittal)
  Load 2: Instance 0001 has IOP = [0, 0, 1; 0, 1, 0] (axial)
  
Result:
  mean_normal computed from corrupted IOP values
  Produces completely different normal

Evidence to look for:
  - NO [CANONICAL_SORT_MIXED_SERIES_ERROR]
  - NO [CANONICAL_SORT_PLANE_MIX_ERROR]
  - But first5/last5 show SAME sop_uid yet DIFFERENT iop and plane
  - Or first5/last5 show completely different instances (different file paths)
```

---

## How To Distinguish The Three Cases

### The Forensic Checklist

From `[CANONICAL_SORT_INPUT_SAMPLE]` logs, check in order:

**1. Mixed Series Check**
```
Read: unique_series_uid_count from Load 2's CANONICAL_SORT_INPUT_SAMPLE

if unique_series_uid_count > 1:
  ❌ CASE A CONFIRMED: WRONG SERIES LOADED
  Evidence: [CANONICAL_SORT_MIXED_SERIES_ERROR] present in logs
  Fix location: _vc_backend.py cache key collision
  
else:
  Continue to next check...
```

**2. Mixed Plane Check**
```
Read: plane_histogram from Load 2's CANONICAL_SORT_INPUT_SAMPLE

Count how many plane types have >10% of instances:
  if len(dominant_planes) > 1:
    ❌ CASE B CONFIRMED: MIXED INSTANCES
    Evidence: plane_histogram={AXIAL: 11, SAGITTAL: 10} or similar
    Fix location: _vc_load.py or _vc_cache.py instance assembly
    
  else:
    Continue to next check...
```

**3. IOP Corruption Check**
```
Extract first5/last5 instances from Load 1 and Load 2:

if all(Load1[i].sop_uid == Load2[i].sop_uid for i in range(5)):
  if any(Load1[i].iop != Load2[i].iop for i in range(5)):
    ❌ CASE C CONFIRMED: IOP CORRUPTION
    Evidence: Same SOP, different IOP between loads
    Fix location: DICOM header read or metadata mutation point
    
  else:
    ❌ SHOULD NOT HAPPEN: Impossible state
    
else:
  ⚠️  DIFFERENT INSTANCES LOADED: New case discovered
  Evidence: first5 SOPUIDs don't match between Load 1 and Load 2
  Fix location: Series selection or instance retrieval logic
```

---

## What The Fresh Logs Will Show

When you reproduce the bug with the new instrumentation:

**Best Case**: Clear diagnostic errors
```
[CANONICAL_SORT_MIXED_SERIES_ERROR] load_id=2 n=21 unique_series_uid_count=2 
  series_uid_set={'1.2.3.4.5.6', '2.3.4.5.6.7'}
  
→ IMMEDIATELY PROVES: Cache collision, wrong series UID lookup
```

**Good Case**: No errors, but plane mix
```
[CANONICAL_SORT_INPUT_SAMPLE] load_id=2 ... plane_histogram={'AXIAL': 11, 'SAGITTAL': 10} 
  first5=[{..., plane: 'SAGITTAL'}, ..., {..., plane: 'AXIAL'}]
  
→ PROVES: Mixed instances in Load 2
```

**Requires Verification**: Clean logs, but different planes
```
[CANONICAL_SORT_INPUT_SAMPLE] load_id=1 ... plane_histogram={'SAGITTAL': 21}
[CANONICAL_SORT_INPUT_SAMPLE] load_id=2 ... plane_histogram={'AXIAL': 21}

Both have unique_series_uid_count=1 (same series)
Both have unique_sop_count=21 (same instances)
But planes are different!

→ REQUIRES: Read DICOM headers directly to confirm if IOP actually differs
```

---

## Verification Procedure (If Needed)

**If fresh logs show Case C** (same instances, same series, different planes):

```python
import pydicom
from pathlib import Path

# From first5/last5 log sample, extract a file path, e.g.:
file_path = "user_data/[study_path]/Series_4/Instance_0001.dcm"

# Read Load 1 DICOM file (extract IOP from DICOM header)
dcm1 = pydicom.dcmread(file_path)
iop1 = dcm1.ImageOrientationPatient
print(f"Load 1 IOP from disk: {iop1}")

# Read Load 2 DICOM file (same path, same file)
dcm2 = pydicom.dcmread(file_path)
iop2 = dcm2.ImageOrientationPatient
print(f"Load 2 IOP from disk: {iop2}")

# Compare
if iop1 == iop2:
  print("❌ IOP is IDENTICAL in DICOM header")
  print("→ IOP corruption is in Python metadata extraction/mutation")
  
else:
  print("❌ IOP is DIFFERENT in DICOM header")
  print("→ DICOM file header is corrupted or was re-written")
```

---

## Bottom Line

**The fresh logs will immediately tell you which of these is true:**

| Case | Detection | Root Cause | Proof |
|------|-----------|-----------|-------|
| **A** | [CANONICAL_SORT_MIXED_SERIES_ERROR] | Cache key collision | Unique series UIDs > 1 |
| **B** | [CANONICAL_SORT_PLANE_MIX_ERROR] | Mixed instances | Multiple planes in histogram |
| **C.1** | Different plane, same instances, same series_uid | Python metadata mutation | DICOM header matches one plane, Python shows another |
| **C.2** | Different plane, same instances, same series_uid | DICOM corruption | DICOM header differs from expected |

Each case has a different fix:
- **A**: Fix _vc_backend.py cache key generation
- **B**: Fix _vc_load.py or _vc_cache.py instance filtering
- **C.1**: Fix metadata extraction or mutation in image_io.py / _vc_backend.py
- **C.2**: Investigate DICOM storage/retrieval pipeline

**We don't propose ANY fix until the fresh logs prove which case it is.**

---

## Ready To Go

All instrumentation deployed ✅  
Fresh reproduction protocol ready ✅  
Forensic classification script ready ✅  
Documentation complete ✅  

**Next action**: Close app, rotate logs, open fresh, reproduce bug, analyze.
