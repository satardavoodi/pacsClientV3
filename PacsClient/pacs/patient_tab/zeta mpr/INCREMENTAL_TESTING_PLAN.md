# Incremental Testing Plan - Simple VTK Oblique MPR
**Date:** 2026-01-31  
**Current State:** v1.03-dev (experimental method added, NOT enabled)  
**Stable Fallback:** v1.02 at `zeta mpr_BACKUP_v1.02\`  
**Strategy:** Test each small change, rollback immediately if issues

---

## Status: Step 1 Complete ✅ | Step 2 Working at 15° ✅ | UI Updated ✅ | Naming Unified ✅

### What Was Done:
✅ v1.02 confirmed stable and backed up  
✅ Simple oblique method `_simple_oblique_slice()` added to code  
✅ Method enabled for testing at 15° rotation - WORKING!  
✅ Version marked as 1.03-dev (experimental)  
✅ **UI Updated:** Main MPR button now launches Zeta MPR directly  
✅ **UI Updated:** Zeta MPR removed from dropdown menu (now redundant)  
✅ **Naming Unified:** All references now consistently say "Zeta MPR" (not "Standard MPR")

### What This Method Does:
```python
def _simple_oblique_slice(self, view_name, angle_degrees):
    """
    Simple VTK approach - NOT based on 3D Slicer
    Uses basic vtkImageReslice with rotation transform
    """
    1. Create rotation transform around crosshair center
    2. Apply to volume: reslice.SetResliceTransform(transform)
    3. Output 3D volume (works with existing mapper)
    4. Update display
```

**Key Differences from Failed v1.03:**
| Aspect | Failed v1.03 | New Approach |
|--------|--------------|--------------|
| Method | SetResliceAxes + direction cosines | SetResliceTransform + simple rotation |
| Output | 2D slice | 3D volume (like v1.02) |
| Mapper | vtkImageSliceMapper (new) | vtkImageResliceMapper (existing) |
| Complexity | HIGH | LOW |
| Inspiration | 3D Slicer (complex) | Direct VTK (simple) |

---

## Step-by-Step Testing Plan

### Step 2: Enable for ONE View, SMALL Angle (Next)

**Objective:** Test if basic mechanism works without breaking anything

**Change Required:**
Modify `_update_oblique_reslicing()` around line 2196:

```python
def _update_oblique_reslicing(self):
    """Update oblique reslicing when crosshairs rotate."""
    import math
    
    # STEP 2 TEST: Enable for axial view only, small angle
    # Check if axial has rotation
    axial_angle_rad = self.crosshair_angles.get('axial', 0.0)
    
    if abs(axial_angle_rad) > 0.01:  # If axial is rotated
        axial_angle_deg = math.degrees(axial_angle_rad)
        
        # TEST ONLY: Apply to sagittal view (perpendicular to axial)
        success = self._simple_oblique_slice('sagittal', axial_angle_deg)
        
        if not success:
            logger.error("Simple oblique failed - resetting to orthogonal")
            self._reset_all_to_orthogonal()
        return
    
    # No rotation - stay orthogonal
    self._reset_all_to_orthogonal()
```

**Test Procedure:**
```
1. Open Zeta MPR with brain CT (101777)
2. Enable crosshairs
3. Drag axial crosshair handle SLIGHTLY (try to get ~15° rotation)
4. OBSERVE sagittal view:
   - Does image appear? (Not black)
   - Is it different from before? (oblique view)
   - Does it look correct? (anatomy visible)
5. Click on a landmark (e.g., eye orbit) in axial
6. Does crosshair land correctly in sagittal?
7. Click Reset
8. Does sagittal return to normal?
```

**Success Criteria:**
- ✅ Sagittal view shows oblique image (not black)
- ✅ Image looks anatomically correct
- ✅ Crosshair clicking still accurate
- ✅ Reset works

**Failure Response:**
- ❌ If ANY test fails: Immediate rollback to v1.02
- Document what failed
- Debug that specific issue
- Don't proceed to Step 3

---

### Step 3: Test Different Angles (After Step 2 Success)

**Objective:** Verify oblique works at various angles

**Test Angles:**
- 15° (small)
- 30° (medium)
- 45° (standard)
- 60° (large)
- 90° (perpendicular)
- -45° (negative)

**For Each Angle:**
1. Rotate to target angle
2. Verify image visible
3. Check anatomical alignment
4. Test crosshair clicking
5. Reset and verify

**Success Criteria:**
- ✅ All angles show images
- ✅ No progressive degradation
- ✅ Crosshair accuracy maintained

---

### Step 4: Enable for All Views (After Step 3 Success)

**Objective:** Full oblique MPR across all views

**Change Required:**
Update `_update_oblique_reslicing()` to handle all view combinations:

```python
def _update_oblique_reslicing(self):
    """Update oblique reslicing for all views."""
    import math
    
    has_rotation = any(abs(angle) > 0.01 for angle in self.crosshair_angles.values())
    
    if not has_rotation:
        self._reset_all_to_orthogonal()
        return
    
    # Apply oblique slicing to perpendicular views
    for source_view, angle_rad in self.crosshair_angles.items():
        if abs(angle_rad) < 0.01:
            continue
        
        angle_deg = math.degrees(angle_rad)
        
        # Determine which views to affect
        if source_view == 'axial':
            # Axial rotation affects sagittal and coronal
            self._simple_oblique_slice('sagittal', angle_deg)
            self._simple_oblique_slice('coronal', angle_deg)
        elif source_view == 'sagittal':
            # Sagittal rotation affects axial and coronal
            self._simple_oblique_slice('axial', angle_deg)
            self._simple_oblique_slice('coronal', angle_deg)
        elif source_view == 'coronal':
            # Coronal rotation affects axial and sagittal
            self._simple_oblique_slice('axial', angle_deg)
            self._simple_oblique_slice('sagittal', angle_deg)
```

**Test Procedure:**
```
1. Rotate in axial view → verify sagittal/coronal oblique
2. Reset
3. Rotate in sagittal view → verify axial/coronal oblique
4. Reset
5. Rotate in coronal view → verify axial/sagittal oblique
6. Reset
```

**Success Criteria:**
- ✅ All view combinations work
- ✅ No cross-contamination issues
- ✅ Reset always works

---

## Rollback Procedures

### Immediate Rollback (If ANY Step Fails)

**Quick Method** - Disable the function:
```python
# In _update_oblique_reslicing() around line 2196:
def _update_oblique_reslicing(self):
    # ADD THIS AT TOP:
    logger.debug("Oblique disabled - returning to v1.02 behavior")
    self._reset_all_to_orthogonal()
    return
    
    # ... rest of method ...
```

**Full Rollback** - Restore v1.02:
```powershell
cd "c:\AI-Pacs codes\PacsClientV2\PacsClient\pacs\patient_tab"
Remove-Item "zeta mpr" -Recurse -Force
Copy-Item "zeta mpr_BACKUP_v1.02" "zeta mpr" -Recurse
```

---

## Testing Checklist

### Step 2: Single View, Small Angle
- [ ] Method added to code (DONE ✅)
- [ ] Enable in `_update_oblique_reslicing()`
- [ ] Test with 15° rotation
- [ ] Verify image appears
- [ ] Check anatomical accuracy
- [ ] Test crosshair clicking
- [ ] Verify reset works
- [ ] **DECISION:** Pass/Fail? Proceed or rollback?

### Step 3: Multiple Angles (Only if Step 2 passes)
- [ ] Test 30°
- [ ] Test 45°
- [ ] Test 60°
- [ ] Test 90°
- [ ] Test -45°
- [ ] All angles work correctly
- [ ] **DECISION:** Pass/Fail? Proceed or rollback?

### Step 4: All Views (Only if Step 3 passes)
- [ ] Update for all view combinations
- [ ] Test axial rotation
- [ ] Test sagittal rotation
- [ ] Test coronal rotation
- [ ] All combinations work
- [ ] **DECISION:** Pass/Fail? Proceed or rollback?

---

## Success Metrics

### Critical (Must Pass):
1. **Image Visibility:** No black screens
2. **Anatomical Alignment:** Crosshair accuracy maintained
3. **Reset Functionality:** Always returns to orthogonal
4. **No Regressions:** v1.02 features still work

### Important (Should Pass):
5. **Interpolation Quality:** Smooth, no artifacts
6. **Performance:** <500ms for rotation
7. **Stability:** No crashes or freezes

### Nice-to-Have (Can Improve Later):
8. **Visual Polish:** Handle design
9. **User Feedback:** Cursor changes
10. **Advanced Features:** Thick slab with oblique

---

## Risk Assessment

### Why This Approach Is Safer:

**Lower Risk Than v1.03:**
- ✓ Uses familiar VTK methods (SetResliceTransform)
- ✓ Outputs 3D volume (works with existing mapper)
- ✓ Incremental testing (one step at a time)
- ✓ Easy rollback (just disable or restore v1.02)
- ✓ Minimal code changes

**Risks Still Present:**
- ⚠️ Transform could still confuse coordinate system
- ⚠️ Oblique slicing could produce unexpected results
- ⚠️ Performance could be slow

**Mitigation:**
- Test with small changes
- Verify each step before continuing
- Keep v1.02 backup ready
- Document what works/doesn't work

---

## Current Code Location

**File:** `standard_mpr_viewer.py`  
**Method Added:** `_simple_oblique_slice()` at line ~2263  
**Enable Point:** `_update_oblique_reslicing()` at line ~2196 (currently disabled)  
**Version:** 1.03-dev (experimental)  
**Stable Backup:** `zeta mpr_BACKUP_v1.02\`

---

## Next Action Required

**USER DECISION:** Should we proceed to Step 2?

**Step 2 involves:**
- Small code change to enable the method
- Testing with ONE view only
- SMALL rotation angle (15°)
- Immediate feedback on success/failure

**Estimated time:** 10 minutes to implement + 5 minutes to test  
**Risk level:** LOW (easily reversible)  
**Rollback time:** < 1 minute if needed

---

## Alternative Decision Points

### Option A: Proceed to Step 2
Continue with incremental testing as planned.

### Option B: Hold at Step 1
Keep the method in code but don't enable it yet.  
Focus on other features first.

### Option C: Remove experimental code
Stay at v1.02 completely.  
Accept visual-only rotation for now.

**Recommendation:** Try Step 2 - it's a small, safe change with immediate feedback.

---

**STATUS: Ready for Step 2 - Awaiting user approval to proceed**
