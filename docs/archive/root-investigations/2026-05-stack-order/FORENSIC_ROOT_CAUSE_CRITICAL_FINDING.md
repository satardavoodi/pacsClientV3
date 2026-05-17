# 🔴 CRITICAL ROOT-CAUSE FINDING: Normal Vector Mismatch

## Executive Summary

**ROOT CAUSE**: Load 2 has a **completely different normal vector** than Load 1 for the same series, causing the geometry-based sort to reverse the instance order.

---

## Forensic Evidence

### Load 1 (12:07:22) - Initial Load
- **Normal Vector**: `[-0.9917, 0.068, 0.1091]` ← Sagittal-like normal
- **Instance Order**: Instance_0001...Instance_0021 (ascending by instance number)
- **Direction**: REVERSE (head slice > tail slice)
- **HEAD**: Instance_0001 at IPP `[-8.62, -104.52, 80.11]`
- **TAIL**: Instance_0019 at IPP `[85.09, -110.94, 69.80]`

### Load 2 (14:39:45) - FLIPPED Load [**ORIENTATION FLIP OCCURS HERE**]
- **Normal Vector**: `[-0.0738, -0.0937, 0.9929]` ← **COMPLETELY DIFFERENT!** Axial-like normal
- **Instance Order**: Instance_0021...Instance_0003 (descending/inverted!)
- **Direction**: FORWARD (head slice < tail slice)
- **HEAD**: Instance_0021 at IPP `[36.30, -93.80, -106.04]`
- **TAIL**: Instance_0003 at IPP `[28.58, -103.60, -2.21]`

---

## What This Means

| Metric | Load 1 | Load 2 | Status |
|--------|--------|--------|--------|
| Normal vector | [-0.99, 0.07, 0.11] | [-0.07, -0.09, 0.99] | ❌ **DIFFERENT** |
| Instance order | 0001→0021 (ascending) | 0021→0003 (descending) | ❌ **REVERSED** |
| Scan direction | REVERSE | FORWARD | ❌ **OPPOSITE** |
| Anatomical plane | Sagittal-like | Axial-like | ❌ **DIFFERENT PLANE** |

---

## Root Cause Classification

**This is a CLASS C failure**: "Cache/metadata holds wrong geometry for the instances"

**The series is not being loaded correctly on Load 2 because:**

1. ❌ **Corrupted Geometry Metadata**: The instance geometry (IPP/IOP) is wrong on Load 2
2. ❌ **Wrong Series Data**: Load 2 is reading a different series or corrupted copy
3. ❌ **Stale Cache**: Load 2 hits a corrupted cache entry with inverted geometry
4. ❌ **Metadata Mutation**: Between Load 1 and Load 2, the instance geometry was modified/corrupted

---

## Evidence Chain

1. **Same instances** (0001-0021) loaded in both cases
2. **Same sort algorithm** (IPP_IOP_GEOMETRY) used
3. **Completely different sort results** due to different normal vectors
4. **This caused the orientation flip** from REVERSE (correct) to FORWARD (flipped)

---

## Next Forensic Step

**Question**: Where does the normal vector come from?
- Is it computed from the geometry metadata?
- Is it stored in the instance metadata?
- Is it cached somewhere?

**Hypothesis**: The instance geometry metadata is being corrupted or swapped between Load 1 and Load 2, causing the sort algorithm to compute a different normal vector.

---

## Conclusion

**The orientation flip is NOT a display/camera issue.**  
**It IS a data integrity issue where instance geometry metadata changes between loads.**

The immediate fix would be to:
1. Verify geometry metadata consistency
2. Invalidate caches that might be corrupted
3. Ensure instance metadata is not being mutated
4. Validate normal vector computation
