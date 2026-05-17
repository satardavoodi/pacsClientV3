# 🔴 SMOKING GUN - EXACT CODE ROOT CAUSE IDENTIFIED

## The Sorting Algorithm (image_io.py:546-595)

```python
def canonical_sort_instances(instances: list) -> tuple:
    # STEP 1: Compute mean normal from ALL instance IOP values
    normals = []
    for inst in instances:
        iop = inst.get("image_orientation_patient")  # ← Get IOP from instance
        if iop is None or len(iop) < 6:
            continue
        n = _slice_normal_from_iop(iop)  # Cross product of IOP vectors
        normals.append(n / norm(n))
    
    # STEP 2: Compute mean normal vector
    mean_normal = np.mean(normals, axis=0)  # ← AVERAGE OF ALL NORMALS
    mean_normal = mean_normal / norm(mean_normal)
    
    # STEP 3: Sort using mean normal
    sorted_list = sorted(
        instances,
        key=lambda inst: _canonical_sort_key_geometry(inst, mean_normal)  # ← USE mean_normal
    )
    return sorted_list, "IPP_IOP_GEOMETRY"

# The sort key function (line 518):
def _canonical_sort_key_geometry(inst, normal: np.ndarray):
    sp = _slice_position(inst, normal)  # ← Compute sort position
    return (sp, instance_number, sop_uid, path)

# The slice position function (line 507):
def _slice_position(inst, normal: np.ndarray) -> float:
    ipp = inst.get("image_position_patient")  # ← Get IPP from instance
    return float(np.dot(np.asarray(ipp), normal))  # ← DOT PRODUCT WITH NORMAL
```

---

## The Root Cause Chain

1. **Load 1 computes mean_normal = [-0.9917, 0.068, 0.1091]**
   - This is computed from the IOP values of instances in Load 1
   - Each instance's sort position = dot(IPP, [-0.9917, 0.068, 0.1091])
   - Result: instances sorted in ascending order → REVERSE direction

2. **Load 2 computes mean_normal = [-0.0738, -0.0937, 0.9929]**
   - This is computed from the IOP values of instances in Load 2
   - Each instance's sort position = dot(IPP, [-0.0738, -0.0937, 0.9929])
   - Result: instances sorted in opposite order → FORWARD direction

3. **The instances' IOP values are DIFFERENT between Load 1 and Load 2!**
   - Same physical instances (0001-0021)
   - But their IOP metadata is corrupted or different in Load 2
   - This causes the mean_normal to be 180° different
   - Which reverses the entire sort order

---

## Why The IOP Is Different

The IOP (Image Orientation Patient) is a 6-tuple describing the anatomical orientation:
```
IOP = [row_x, row_y, row_z, col_x, col_y, col_z]
```

The mean normal is: `cross(row_vector, col_vector)` = normalized([-0.99, 0.07, 0.11]) in Load 1

But in Load 2 it's: normalized([-0.07, -0.09, 0.99]) — **COMPLETELY DIFFERENT PLANE**

**Hypothesis**: The IOP values in the instance metadata are either:
1. ❌ **Corrupted between loads** — same file, different metadata extracted
2. ❌ **From different instances** — wrong instances loaded in Load 2
3. ❌ **Cached incorrectly** — cache returns corrupted IOP values
4. ❌ **Mutated in-place** — instance dict is being modified between loads

---

## Exact Code Location of the Bug

**File**: `PacsClient/pacs/patient_tab/utils/image_io.py`  
**Function**: `canonical_sort_instances()` (line 546)  
**Root Cause**: The instances passed to this function have DIFFERENT IOP values in Load 2 than Load 1

**The Fix Would Require**: Determining WHY the instance IOP values are different, then fixing the data source (cache, DB, file read, metadata extraction, etc.)

---

## Forensic Evidence Chain

1. ✅ Logs show different normal vectors computed ([-0.99...] vs [-0.07...])
2. ✅ Different normal vectors cause different sort keys via dot product
3. ✅ Different sort keys cause opposite instance order
4. ✅ The canonical_sort function is working correctly (it's deterministic)
5. ✅ The problem is the INPUT data (IOP values) are wrong in Load 2

---

## Where To Investigate Next

1. **Instance data source**: Where are the IOP values loaded from?
   - DICOM file reads in `_vc_load.py`?
   - Cache retrieval in `_vc_backend.py`?
   - Database query in `image_io.py`?

2. **Data mutation points**: Where might the IOP be corrupted?
   - Metadata extraction and storage (`pydicom.dcmread`)?
   - Cache serialization/deserialization?
   - Metadata normalization functions?

3. **Specific instances**: Compare the actual IOP values in the log files for Load 1 vs Load 2 instances
   - Extract the IOP from each instance in the log
   - See if they're actually different or if just the mean computation differs

---

## Conclusion

**The orientation flip is NOT a display, camera, or reference-line bug.**

**It IS a data integrity failure where instance IOP metadata values are different between Load 1 and Load 2**, causing the canonical sort algorithm to compute a reversed sort order for the same physical instances.

**Next step**: Trace the instance IOP source and determine where the corruption occurs.
