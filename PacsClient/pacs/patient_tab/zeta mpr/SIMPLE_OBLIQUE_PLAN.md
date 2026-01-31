# Simple VTK-Based Oblique MPR Plan
**Date:** 2026-01-31  
**Current State:** v1.02 Stable Restored  
**Status:** Planning Phase - Starting Fresh

---

## What Went Wrong with v1.03

**Problem:**
- Tried to replicate 3D Slicer's complex approach
- Used `SetResliceAxes()` with direction cosines
- Images disappeared (especially coronal) when rotating
- Over-engineered solution broke what was working

**Lesson Learned:**
- 3D Slicer integration approaches often fail
- Need simpler, more direct VTK methods
- Must test incrementally, not big-bang changes

---

## New Approach: Minimal VTK Oblique Slicing

### Goal:
Get oblique slices working with the SIMPLEST possible VTK approach.

### Core Principle:
**Use what already works in v1.02 + minimal additions**

---

## Option 1: Rotate the Camera, Not the Data (SIMPLEST)

### Concept:
Instead of reslicing the volume, just rotate the camera viewing angle.

**Advantages:**
- ✓ No data manipulation
- ✓ No coordinate system confusion
- ✓ Fast and simple
- ✓ Can't break the display pipeline

**Disadvantages:**
- ✗ Not true MPR oblique slicing
- ✗ Viewing angle changes, but slice orientation doesn't

**Verdict:** Too simple - doesn't achieve true oblique reconstruction.

---

## Option 2: Simple vtkImageReslice with Transform (RECOMMENDED)

### Concept:
Use basic `vtkImageReslice` with a simple rotation transform.

**Method:**
```python
def _simple_oblique_slice(self, view_name, angle_degrees):
    """
    SIMPLE oblique slicing - just rotate and extract a slice.
    No complex matrices, no direction cosines.
    """
    import math
    
    # Get current slice center
    center = self.current_position  # From crosshair
    
    # Create a simple rotation transform
    transform = vtk.vtkTransform()
    transform.PostMultiply()
    
    # Move to origin, rotate, move back
    transform.Translate(-center[0], -center[1], -center[2])
    
    # Rotate around appropriate axis for this view
    if view_name == 'axial':
        transform.RotateZ(angle_degrees)  # Rotate in plane
    elif view_name == 'sagittal':
        transform.RotateX(angle_degrees)
    elif view_name == 'coronal':
        transform.RotateY(angle_degrees)
    
    transform.Translate(center[0], center[1], center[2])
    
    # Create reslice filter
    reslice = vtk.vtkImageReslice()
    reslice.SetInputData(self.image_data)  # Our X-flipped volume from v1.01
    reslice.SetResliceTransform(transform)
    reslice.SetInterpolationModeToLinear()
    reslice.SetOutputDimensionality(3)  # Keep as 3D volume
    reslice.Update()
    
    # Output is a rotated volume - use existing mapper to display it
    oblique_volume = reslice.GetOutput()
    
    # Update the mapper with rotated volume
    # This is what we were already doing in v1.02 disabled code!
    mapper = self.viewers[view_name]['mapper']
    mapper.SetInputData(oblique_volume)
    mapper.Update()
    
    # Render
    self.viewers[view_name]['renderer'].GetRenderWindow().Render()
```

**Why This Should Work:**
1. Uses `SetResliceTransform()` - the straightforward VTK way
2. Still outputs 3D volume - works with existing `vtkImageResliceMapper`
3. Simple rotation around center point
4. No complex matrix math
5. Similar to what was working before in earlier versions

**Testing Strategy:**
1. Add this method to v1.02
2. Test with SMALL angle (15°) first
3. Only enable for ONE view initially (axial)
4. Verify image appears and is correct
5. Then expand to other views

---

## Option 3: Per-View Slice Extraction (MIDDLE GROUND)

### Concept:
Extract a 2D slice at the current crosshair position, then rotate that 2D image.

**Method:**
```python
def _extract_and_rotate_slice(self, view_name, angle_degrees):
    """
    Extract orthogonal slice first, then rotate the 2D image.
    """
    # Step 1: Extract current orthogonal slice at crosshair position
    # (We already do this for normal viewing)
    
    # Step 2: Rotate the extracted 2D slice image
    rotate_filter = vtk.vtkImageReslice()
    rotate_filter.SetInputData(current_slice)  # 2D slice
    rotate_filter.SetOutputDimensionality(2)   # Keep as 2D
    
    # Rotate in-plane
    transform = vtk.vtkTransform()
    transform.RotateZ(angle_degrees)  # Always Z for in-plane rotation
    rotate_filter.SetResliceTransform(transform)
    rotate_filter.Update()
    
    rotated_slice = rotate_filter.GetOutput()
    
    # Display rotated slice
    # ... update mapper ...
```

**Advantages:**
- ✓ 2D operation - simpler
- ✓ Less likely to break 3D volume handling
- ✓ Clearer what's happening

**Disadvantages:**
- ✗ Only rotates in-plane, not true oblique through volume
- ✗ Doesn't give different slice angles

**Verdict:** Not true oblique MPR, but safer than Option 2.

---

## Implementation Roadmap

### Phase 1: Test Option 2 (Simple Transform) ✅ RECOMMENDED

**Step 1.1: Add the simple method**
- Copy the `_simple_oblique_slice` code above
- Add to `standard_mpr_viewer.py` after existing methods

**Step 1.2: Enable for testing**
- Modify `_update_oblique_reslicing()` to call this simple method
- Test with ONE view only (axial)
- Use SMALL angle (15°)

**Step 1.3: Verify basic functionality**
- Does image appear? (Not black)
- Is it rotated? (Visual check)
- Does crosshair still work? (Click test)

**Step 1.4: If working, expand**
- Test other views (sagittal, coronal)
- Test larger angles (30°, 45°, 90°)
- Verify anatomical accuracy

### Phase 2: Handle Interaction Improvements (Later)

**Only after oblique slicing works:**
- Better handle visuals
- Clearer interaction feedback
- Separate rotation/translation handles

---

## Critical Success Factors

### Must Have:
1. **Image appears** when crosshair rotates (not black!)
2. **Anatomical alignment** maintained (crosshair clicks land correctly)
3. **Reset works** (can get back to orthogonal)
4. **Doesn't break v1.02** functionality

### Nice to Have:
- Smooth interpolation
- Fast performance
- Professional handle design

### Can Skip:
- Fancy 3D Slicer-style handles
- Complex matrix validation
- Perfect slice extraction

---

## Testing Protocol (Minimal)

### Test 1: Basic Visibility
```
1. Enable crosshairs
2. Rotate 15° in axial view
3. CHECK: Do sagittal/coronal still show images?
4. CHECK: Are they different from before? (oblique view)
```

### Test 2: Anatomical Accuracy
```
1. Rotate crosshair 30°
2. Click on eye orbit
3. CHECK: Does crosshair land on orbit in all views?
```

### Test 3: Reset
```
1. Rotate to 45°
2. Click Reset
3. CHECK: Returns to orthogonal?
4. CHECK: Images still visible?
```

**If all 3 pass:** Success! Can refine.  
**If any fail:** Debug that specific issue before continuing.

---

## Code Change Strategy

### Minimal Change Approach:

**Change 1: Add simple oblique method**
```python
# After line ~2500 in standard_mpr_viewer.py
def _simple_oblique_slice(self, view_name, angle_degrees):
    # ... implementation from Option 2 ...
```

**Change 2: Enable in oblique update**
```python
# Around line ~2185
def _update_oblique_reslicing(self):
    # REMOVE the early return
    # ADD: Call _simple_oblique_slice for affected views
```

**Change 3: Test incrementally**
- Test after each change
- Rollback if breaks
- Build on what works

---

## Rollback Plan

### If this fails too:

**Option A: Disable oblique completely**
- Keep v1.02 visual-only rotation
- Focus on other features
- Oblique MPR is nice-to-have, not critical

**Option B: Use different library**
- SimpleITK for oblique reslicing
- Display result in VTK
- Separate the reslicing from display

**Option C: Accept limitations**
- Document that oblique MPR is not supported
- Visual rotation only
- Focus on what works well

---

## Key Differences from v1.03

| Aspect | v1.03 (Failed) | New Approach |
|--------|----------------|--------------|
| Method | SetResliceAxes + direction cosines | SetResliceTransform + simple rotation |
| Output | 2D slice | 3D volume (like before) |
| Complexity | High (matrix math, validation) | Low (basic transform) |
| Inspiration | 3D Slicer (complex) | Direct VTK (simple) |
| Testing | Big-bang (all at once) | Incremental (one view at a time) |

---

## Next Steps

1. **USER DECISION:** Should we try the simple approach (Option 2)?
2. If yes: Implement `_simple_oblique_slice()` method
3. Test with minimal changes
4. Report results
5. Iterate or rollback as needed

**Estimated time:** 30 minutes to implement + test  
**Risk level:** LOW (can easily revert)  
**Success probability:** MEDIUM-HIGH (simpler = less to break)

---

## Alternative: Accept Current State

**Reality Check:**
- v1.02 works well for most use cases
- Visual rotation is better than no rotation
- Oblique MPR is advanced feature, not critical
- May not be worth the risk

**Option:** 
- Keep v1.02 as-is
- Document that crosshair rotation is visual only
- Focus development on other features
- Revisit oblique MPR later when have more time

**USER CHOICE:** What would you prefer?
- A) Try simple VTK approach (Option 2)
- B) Keep v1.02 stable, skip oblique for now
- C) Different approach entirely
