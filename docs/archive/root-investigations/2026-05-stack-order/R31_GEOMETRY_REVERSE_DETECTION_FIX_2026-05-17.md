# R31: Geometry Index Reversal Detection and K_FLIP Correction
**Date**: 2026-05-17  
**Severity**: CRITICAL  
**Status**: IMPLEMENTED  
**Affected**: Advanced/VTK viewer with geometry-sorted DICOM loading  

---

## Executive Summary

Fixed the final **Advanced/VTK slice-numbering inversion** in AIPacs v3.0.3.

The original R31 design was correct but incomplete in production. Runtime validation showed two missed hops in the actual Advanced load path:

1. `viewer_2d.py` was reading `_geometry_index_applied_reverse` from `series_meta`, while the flag is stamped on the root metadata dict.
2. `process_series_groups()` in `image_io.py` was still building the ITK volume from the pre-geometry file list and yielding metadata that had not been updated with the geometry contract.

That meant the viewer kept receiving an old-looking stack even after the display-side logic was fixed, so the user-visible numbering did not change.

**Final fix set**:
- keep the R30 `display_k -> raw_k` offset in `DisplayGeometry`
- carry `applied_reverse` from `SeriesGeometryIndex` through metadata and into `DisplayGeometry.audit_stack_order_convention(...)`
- read `_geometry_index_applied_reverse` from the root metadata in `viewer_2d.py`
- reorder `process_series_groups()` input files to `geometry_index.dicom_files_for_itk` before the SimpleITK load
- stamp the exact same geometry contract onto the yielded metadata in all three Advanced load branches

**User expectation**: Counter shows `1/N` when viewing the most superior or clinically first display slice, and counts upward to `N/N` while reference-line sync stays unchanged.

---

## Technical Details

### The Problem: The Runtime Path Still Bypassed The Contract

#### Step 1: Geometry Index Creates Reversed Order (image_io.py)
```python
# advanced_geometry_contract.py lines 702-712
display_instances = tuple(reversed(geometry_instances))  # ← REVERSES anatomy order
applied_reverse = True
```

The geometry_index:
1. Reads DICOM files in instance-number order (Instance_001.dcm, Instance_002.dcm, ...)
2. Sorts by IPP (Image Position Patient) to get anatomy order (INFERIOR → SUPERIOR or vice versa)
3. **REVERSES** the anatomy order for display purposes
4. Creates VTK volume from the REVERSED order

#### Step 2: Metadata Stamped with Reversed Instances
```python
# advanced_geometry_contract.py line 483
metadata["instances"] = geometry_index.display_instances_metadata()  # ← Uses REVERSED order
metadata["_instances_geometry_sorted"] = True
```

The instances in metadata are now in REVERSED order, and the flag says so. But...

#### Step 3: DisplayGeometry Never Learns About Reversal
```python
# viewer_2d.py lines 2268-2270 (OLD CODE)
plane = str(series_meta.get("display_convention") or ...)
body_part = str(series_meta.get("body_part_examined") or "")
convention, matches, recommended, reason, direction = dg.audit_stack_order_convention(plane, body_part)
# ← NO INFORMATION ABOUT applied_reverse!
```

DisplayGeometry tries to determine K_FLIP based on plane/body_part/direction alone, **but doesn't know the instances were reversed!**

#### Step 4: R29 Prevents K_FLIP for UNKNOWN Planes
```python
# display_geometry.py line 521 (R29 fix)
recommended_transform = "NONE" if (convention_name == "UNKNOWN" or order_matches) else "K_FLIP"
```

For UNKNOWN planes (extremities, unusual anatomies), R29 prevents K_FLIP. But the instances ARE reversed, so no K_FLIP = **INVERTED COUNTER**.

---

### The Solution: R31 - Pass Reversal Flag and Force K_FLIP

#### Change 1: Store `applied_reverse` in SeriesGeometryIndex (advanced_geometry_contract.py)
```python
@dataclass(frozen=True)
class SeriesGeometryIndex:
    ...
    applied_reverse: bool = False  # ← NEW FIELD
```

#### Change 2: Stamp Metadata with Reversal Flag (advanced_geometry_contract.py)
```python
def stamp_metadata_with_geometry_index(...):
    ...
    metadata["_geometry_index_applied_reverse"] = geometry_index.applied_reverse  # ← NEW
    return metadata
```

#### Change 3: Pass Flag to DisplayGeometry (viewer_2d.py)
```python
applied_reverse = bool(series_meta.get("_geometry_index_applied_reverse", False))  # ← NEW
convention, matches, recommended, reason, direction = dg.audit_stack_order_convention(
    plane, body_part, applied_reverse=applied_reverse  # ← PASS IT
)
```

#### Change 4: Force K_FLIP When Reversal Detected (display_geometry.py)
```python
def audit_stack_order_convention(self, plane: str, body_part: str, applied_reverse: bool = False):
    ...
    # R31 fix: When geometry_index applied reversal, FORCE K_FLIP
    if applied_reverse:
        recommended_transform = "K_FLIP"  # ← OVERRIDE any other logic
        reason = "geometry_index_applied_reverse_requires_kflip"
    else:
        recommended_transform = "NONE" if (convention_name == "UNKNOWN" or order_matches) else "K_FLIP"
    ...
```

**Why This Works**:
- Geometry index reverses instances for anatomy (correct)
- `process_series_groups()` now feeds that same display order into SimpleITK, so the loaded volume matches the contract
- the yielded metadata now carries the same geometry contract as the loaded pixels
- `viewer_2d.py` reads the reversal flag from the root metadata object that actually owns it
- K_FLIP and the 1-based display transform now act on the correct runtime stack

### Load-Bearing Invariants

1. Every Advanced load branch must use `geometry_index.dicom_files_for_itk` as the file list passed into SimpleITK.
2. Every Advanced load branch must stamp the yielded metadata with the same `SeriesGeometryIndex` used to build the volume.
3. `viewer_2d.py` must read `_geometry_index_applied_reverse` from the root metadata dict, not only from `metadata['series']`.
4. Geometry metadata propagation must stay centralized so one branch cannot silently drift from the others.

---

## Files Modified

### Canonical Files
1. **PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py**
   - Added `applied_reverse: bool = False` field to `SeriesGeometryIndex`
   - Serialize/deserialize `applied_reverse`
   - Stamp `_geometry_index_applied_reverse` onto metadata

2. **PacsClient/pacs/patient_tab/utils/image_io.py**
   - Fixed `process_series_groups()` to build the ITK volume from `geometry_index.dicom_files_for_itk`
   - Stamped the geometry contract into yielded metadata for the process-groups path
   - Added `_apply_geometry_index_metadata(...)` so DB/filesystem/process-groups paths share one metadata-propagation helper

3. **modules/viewer/geometry/display_geometry.py**
   - Updated `audit_stack_order_convention()` to accept `applied_reverse`
   - Force `recommended_transform = "K_FLIP"` when geometry reversal was applied
   - Preserve the R30 1-based display transform initialization

4. **modules/viewer/advanced/viewer_2d.py**
   - Read `_geometry_index_applied_reverse` from the root metadata dict
   - Pass `applied_reverse` to `audit_stack_order_convention()`
   - Keep the bind path aligned with the geometry contract stamped by `image_io.py`

5. **tests/viewer/test_canonical_series_sort.py**
   - Added regression coverage for `_apply_geometry_index_metadata(...)`

### Plugin Package Mirrors
1. **builder/plugin package/packages/viewer/payload/python/modules/viewer/geometry/display_geometry.py** (parity maintained)
2. **builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py** (parity maintained)

---

## Diagnostic Logging (NEW)

### Log Tags Added

#### `[R31_METADATA_APPLIED_REVERSE]` (viewer_2d.py)
- **Level**: WARNING
- **Component**: viewer
- **Message**: Logs when metadata indicates geometry index applied reversal
- **Fields**: series_uid, series_number, applied_reverse, will_force_kflip

#### `[R31_GEOMETRY_REVERSE_DETECTION]` (display_geometry.py)
- **Level**: WARNING
- **Component**: viewer
- **Message**: Logs when K_FLIP is being forced due to applied_reverse flag
- **Fields**: applied_reverse, FORCING_KFLIP, plane, body_part, convention, direction, reason

---

## Expected Behavior After Fix

### Counter Numbering (User-Visible)
- **Most superior position**: Shows "1/N" (where N = total slices)
- **Scrolling downward**: Counter increments (1→2→3→...→N)
- **Most inferior position**: Shows "N/N"
- **All planes consistent**: AXIAL, SAGITTAL, CORONAL all show same numbering scheme

### Reference Lines (Unchanged)
- Reference lines continue to sync correctly across viewers
- Geometry extraction (IPP, IOP) remains unaffected
- Anatomy orientation remains correct

### K_FLIP Application
- **Before R31**: K_FLIP applied only for known SAGITTAL/CORONAL/AXIAL with mismatched direction
- **After R31**: K_FLIP ALSO forced when `applied_reverse=True` (geometry_index reversal)

---

## Validation Steps

### For Development Testing
1. Load a series with extremity anatomy (e.g., knee, ankle)
   - These commonly trigger UNKNOWN plane classification
   - Geometry index will reverse instances for proximal-to-distal display
   
2. Check diagnostic logs:
   ```
   [R31_METADATA_APPLIED_REVERSE] applied_reverse=True
   [R31_GEOMETRY_REVERSE_DETECTION] FORCING_KFLIP
   [AUDIT_RECOMMENDATION] recommended=K_FLIP
   ```

3. Verify corner counter:
   - Most superior slice: "1/20"
   - Scroll down: "2/20", "3/20", ..., "20/20"
   - Never inverted

4. Verify reference line sync:
   - Open same series in two viewers (AXIAL + SAGITTAL)
   - Reference line positions should match anatomy
   - Test on all three planes

### For User Acceptance
1. Close all series from OLD code
2. Load fresh series with FIXED code
3. Observe counter: should show "1/N" for most superior position
4. Scroll: counter should count UP to N (not down)
5. All three planes should show consistent numbering

---

## Rollback Plan (If Needed)

If unexpected issues arise, revert changes to:
1. Remove `applied_reverse` field from SeriesGeometryIndex
2. Remove pass-through of `applied_reverse` in stamp_metadata_with_geometry_index
3. Remove `applied_reverse` parameter from audit_stack_order_convention
4. Remove diagnostic logs

**Note**: This is a low-risk surgical fix. The `applied_reverse` flag defaults to `False`, so OLD code will continue to work unchanged.

---

## Technical Notes

### Why Geometry Index Reverses Instances
- Medical convention: display proximal-to-distal for extremities (reversed from anatomy order)
- SimpleITK reads files in the order given
- Reversing the file list changes the Z-axis direction of the resulting volume
- This is architecturally correct for visual display

### Why DisplayGeometry Must Know About It
- The counter formula uses raw_k (VTK Z-index) to look up display position
- If instances are reversed but DisplayGeometry doesn't know, counter is inverted
- K_FLIP corrects this by swapping the relationship between raw_k and display

### Thread Safety
- `applied_reverse` is set at volume creation time, never changes
- Passed through immutable metadata structures
- No race conditions

---

## Related Rules

- **R29** (2026-05-17): Prevent K_FLIP for UNKNOWN planes to preserve user intent
- **R30** (2026-05-17): Initialize DisplayGeometry matrix with -1.0 offset for 1-based display
- **R31** (2026-05-17): **Pass geometry_index.applied_reverse flag to force K_FLIP when needed** (THIS RULE)

All three rules work together:
1. R30: Correct math for 1-based counter formula
2. R29: Don't K_FLIP for known-good planes
3. R31: DO K_FLIP when geometry_index reversed the instances

---

## Copilot Instructions Update Required

Add to copilot-instructions.md:

> **R31 — Geometry index reversal detection and K_FLIP correction (2026-05-17 / critical global fix).**
> When SeriesGeometryIndex detects that DICOM instances need anatomical reversal (e.g., extremity proximal-to-distal display), it sets `applied_reverse=True`. This flag MUST be passed through metadata via `_geometry_index_applied_reverse` to DisplayGeometry's `audit_stack_order_convention()`. DisplayGeometry must force `recommended_transform="K_FLIP"` when `applied_reverse=True`, regardless of plane/convention detection. This corrects the relationship between raw_k (VTK index) and display slice counter, ensuring counters show "1/N" for superior-most position. Diagnostic logs: `[R31_METADATA_APPLIED_REVERSE]` in viewer_2d.py and `[R31_GEOMETRY_REVERSE_DETECTION]` in display_geometry.py. Do NOT remove the applied_reverse flag or the K_FLIP forcing logic — they are load-bearing for anatomically correct numbering on extremity and other UNKNOWN-plane anatomy.

---

## Success Criteria

✅ **All Three Planes**: AXIAL, SAGITTAL, CORONAL show consistent 1-based numbering  
✅ **Anatomy Correct**: Counter "1" = most superior, counter "N" = most inferior  
✅ **Reference Lines**: Continue to sync correctly (IPP/IOP extraction unchanged)  
✅ **Diagnostic Logs**: New [R31_*] tags appear in logs confirming fix triggered  
✅ **Plugin Parity**: No SHA mismatches between canonical and plugin mirrors  

