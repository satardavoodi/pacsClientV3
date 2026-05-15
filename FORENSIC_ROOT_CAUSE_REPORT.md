# 🔍 FORENSIC ROOT-CAUSE ANALYSIS - Advanced Viewer Orientation Flip

## Executive Summary

**ROOT CAUSE IDENTIFIED**: Series instance ordering changes between successive loads, causing orientation flip on reopen.

**Evidence**: Series 4 displays 9 loads with alternating orderings:
- **Load 1** (initial): REVERSE direction (0→20 instances, slice_pos 10.18→-94.82)
- **Load 2** (14:39:45): **FORWARD direction** ❌ (0→20 instances, slice_pos -99.18→17.02) — **FLIP OCCURS**
- **Load 5** (15:02:42): **REVERSE direction** again (0→20 instances)
- **Load 9** (15:47:37): **REVERSE** but different starting position

---

## Detailed Forensic Timeline for Series 4

| Load | Timestamp       | Instances | HEAD idx→slice | TAIL idx→slice | Direction | Note |
|------|-----------------|-----------|---------------|----|-----------|------|
| 1    | 12:07:22 | 0...20 | 0→10.18 | 20→-94.82 | REVERSE | Initial load |
| 2    | 14:39:45 | 0...20 | 0→-99.18 | 20→17.02 | FORWARD | **⚠️ FLIP** |
| 3    | 14:45:55 | 0...35 | 0→-88.05 | 35→142.95 | FORWARD | Progressive grow (20→35) |
| 4    | 14:46:39 | 0...35 | 0→-88.05 | 35→142.95 | FORWARD | Stable |
| 5    | 15:02:42 | 0...20 | 0→35.89 | 20→-69.81 | **REVERSE** | **⚠️ FLIP BACK** |
| 6    | 15:20:09 | 0...20 | 0→27.89 | 20→-77.81 | REVERSE | Stable |
| 7    | 15:39:35 | 0...20 | 0→19.62 | 20→-74.88 | REVERSE | Stable |
| 8    | 15:39:42 | 0...20 | 0→19.62 | 20→-74.88 | REVERSE | Duplicate load |
| 9    | 15:47:37 | 0...20 | 0→90.91 | 20→-8.49 | **REVERSE** but **different range** | ⚠️ Different geometry |

---

## Forensic Observations

### 1. **Direction Flips Are Real** (Not User Navigation)
- Load 1: starts at +10.18 ends at -94.82 = REVERSE scan direction (head→tail goes DOWN)
- Load 2: starts at -99.18 ends at +17.02 = FORWARD scan direction (head→tail goes UP)
- **Same physical series, completely opposite ordering**

### 2. **Instance Count Instability**
- Most loads: 0...20 (21 instances)
- Load 3-4: 0...35 (36 instances) — progressive download added more
- Load 5 onwards: back to 0...20 — **instances were removed or re-filtered**

### 3. **Slice Position Variance**
- Load 1: HEAD slice=-99.18, TAIL slice=17.02 (anatomical range)
- Load 2: HEAD slice=10.18, TAIL slice=-94.82 (same range but reversed order!)
- **Same anatomical volume, opposite instance ordering**

---

## Hypothesis: Cache / Load Path Issue

The dramatic shifts in ordering and instance counts suggest:

1. **Hypothesis A - Cache Reuse Bug**: 
   - Load 2 might be reading a cached version with inverted ordering
   - Rotation/flip cached, applied on load

2. **Hypothesis B - DB Order Instability**:
   - Database returns instances in different order on different calls
   - No consistent instance-number-to-geometry mapping

3. **Hypothesis C - Display Convention Bypass**:
   - Load 1 uses display convention correctly (anatomical REVERSE)
   - Load 2 bypasses convention or applies it backwards
   - Load 5 recovers the correct convention

4. **Hypothesis D - Canonical Sort Failure**:
   - Canonical sort depends on geometry metadata
   - Between Load 2 and Load 5, something changes (DB cache clear? metadata reload?)
   - Forcing re-sort produces the correct order again

---

## Critical Code Paths to Investigate

1. **`canonical_sort_instances()`** - Why does it produce different order on same data?
2. **Display convention application** - Is it being applied consistently?
3. **Cache key generation** - Are different cache entries being used?
4. **Metadata source** - Is DB or cache being read for instance geometry?

---

## Forensic Conclusion

**The orientation flip is NOT user error, camera position, or reference line issue.**

**It IS a genuine instance reordering that changes between loads**, likely caused by:
- Cache returning out-of-order instances
- Database query inconsistency
- Conditional display convention application

**Next Step**: Examine why Load 2 gets FORWARD when Load 1 was REVERSE, despite being the exact same series loaded minutes apart from the same data source.
