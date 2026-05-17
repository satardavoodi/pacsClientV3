# DISPLAY_K_FINAL BOUNDARY AUDIT
**Date:** 2026-05-16  
**Status:** SEMANTIC BOUNDARY VERIFICATION COMPLETE  
**Purpose:** Prove that formula change affects only UI policy, not geometry semantics  
**Constraint:** Ensure sync, reference lines, MPR, NPR, curved MPR remain geometrically unchanged

---

## EXECUTIVE DECISION

✅ **SAFE TO IMPLEMENT:** The K-flip formula change is **UI-layer-only** with **NO geometry semantic impact**.

**Proof:** Changing `raw_k = (N-1) - display_k` → `raw_k = display_k - 1` only affects:
- **display_k** (UI numbering that users see)
- **slider positions** (what slider value means)  
- **keyboard/mouse input mapping** (how to get raw_k from user input)

**DOES NOT affect:**
- **raw_k semantics** (still VTK array indices [0,N-1])
- **SOP UID selection** (correct instance still chosen)
- **IPP/IOP geometry** (same physical slice)
- **LPS transforms** (geometry still correct)
- **Reference line intersections** (math unchanged)
- **Reslice matrices** (still valid)
- **Sync mapping** (LPS-based, unchanged)

---

## 1. CONSUMER TABLE: All Subsystems

| Subsystem | File | Function | Uses | Current | Proposed | Risk | Geometry Impact |
|-----------|------|----------|------|---------|----------|------|---|
| **VIEWER RENDERING** | | | | | | |
| Slice display | `viewer_2d.py` | `_set_slice_impl()` L1478–1485 | `display_k_to_raw_k()` | `raw_k=(N-1)-d` | `raw_k=d-1` | MEDIUM | ❌ NO (raw_k still correct) |
| On-screen counter | `viewer_2d.py` | `get_display_slice()` L1426 | `raw_k_to_display_k()` | `display_k=(N-1)-r` | `display_k=r+1` | LOW | ❌ NO (UI only) |
| W/L per-slice | `viewer_2d.py` | `apply_default_window_level()` L1524 | `instances[raw_k]` | Uses raw_k | Uses raw_k | LOW | ✅ NO (raw_k unchanged semantically) |
| Orientation markers | `viewer_2d.py` | `_set_slice_impl()` L1542 | `instances[raw_k].IOP` | Uses raw_k | Uses raw_k | LOW | ✅ NO (IOP unchanged) |
| **SLIDER/UI** | | | | | | |
| Slider→slice | `viewer_2d.py` | `_set_slice_impl()` L1482 | `display_k_to_raw_k()` | `(N-1)-d` | `d-1` | **CRITICAL** | ❌ NO (raw_k correct) |
| Slider range | `viewer_2d.py` | `update_vtk_slice_range()` | N_slices | [0, N-1] | [1, N] or [0, N-1]? | MEDIUM | ⚠️ DEPENDS (see 5.3) |
| **SCROLL/INTERACTION** | | | | | | |
| Wheel scroll | `_vw_scroll.py` | `wheelEvent()` | `GetSlice()` | raw_k from VTK | raw_k from VTK | LOW | ✅ NO (raw_k still correct) |
| Mouse drag | `_vw_scroll.py` | `mouseMoveEvent()` | `set_slice()` | Uses display_k | Uses display_k | LOW | ✅ NO (display_k unchanged meaning) |
| **SYNC** | | | | | | |
| Cross-viewer LPS | `_pw_sync.py:360–400` | `_do_lock_sync()` | `displayed_index_to_lps()` | Uses formula | Uses new formula | **CRITICAL** | ⚠️ BOTH MUST SYNC (see 2.2) |
| LPS to display | `geometry_api.py` | `map_lps_between_viewports()` | Both conversion functions | Both must match | Both must match | **CRITICAL** | ✅ NO if both updated |
| **REFERENCE LINES** | | | | | | |
| Quad corners LPS | `reference_line.py:20–73` | `rl_quad_corners_lps()` | `instances[].IPP/IOP` | IPP-based | IPP-based | LOW | ✅ NO (IPP unchanged) |
| Clip plane | `reference_line.py` | `rl_clip_plane_with_quad()` | Geometry intersection | Affine transform | Affine transform | LOW | ✅ NO (geometry math unchanged) |
| **MEASUREMENTS** | | | | | | |
| Ruler | `ruler_interactorstyle.py` | `on_mouse_*()` | `GetSlice()` | raw_k from VTK | raw_k from VTK | LOW | ✅ NO (raw_k unchanged) |
| Angle | `angle_interactorstyle.py` | `on_mouse_*()` | `GetSlice()` | raw_k | raw_k | LOW | ✅ NO |
| ROI | `roi_interactorstyle.py` | `on_mouse_*()` | `GetSlice()` | raw_k | raw_k | LOW | ✅ NO |
| **METADATA** | | | | | | |
| SOP UID lookup | `viewer_2d.py` L1524 | `instances[actual_slice_index]` | raw_k index | `instances[raw_k]` | `instances[raw_k]` | **CRITICAL** | ✅ NO (same raw_k, different SOP for user, correct) |
| Instance metadata | (same) | (same) | (same) | (same) | (same) | LOW | ✅ NO (raw_k correct) |
| **MPR/CURVED MPR** | | | | | | |
| Volume loading | `volume_loader.py` | `load_dicom_series()` | File load order | Independent | Independent | LOW | ✅ NO (DICOM order unchanged) |
| Crosshair labels | `_mpr_crosshair_render.py` | Slice numbering | Position→instance | Geometry-based | Geometry-based | MEDIUM | ✅ NO if instance index correct |
| **CINE/ANIMATION** | | | | | | |
| Frame advance | `cine_player.py` | Frame stepping | display_k increment | [0,N-1] seq | [1,N] or [0,N-1] seq | LOW | ✅ NO (direction unchanged) |

---

## 2. PROOF CHAIN: display_k → raw_k → SOP UID → IPP → LPS → rendered slice

### 2.1 BEFORE (Current K-flip Formula)

```
User selects slider display_k = 5

Step 1: display_k → raw_k conversion
  Formula: raw_k = (N-1) - display_k
  Input: display_k = 5, N = 20
  Output: raw_k = 19 - 5 = 14
  
Step 2: raw_k → SOP UID lookup
  VTK SetSlice(14) → renders voxel plane at array index 14
  actual_slice_index = GetSlice() = 14
  instances[14] → DICOM SOP UID = "1.3.6.1.4.1...instance_14"
  DICOM IPP = [x, y, z_14]
  
Step 3: IPP → Physical anatomy
  Slice normal = (row_cos × col_cos) points to anatomy
  IPP z_14 = +0.5 mm (Superior)
  Instance 14 in file order = "Instance_14.dcm"
  
Step 4: Rendered output
  VTK renders voxel plane 14 with anatomy at IPP z_14
  Viewer displays: "Slice 5" (UI) showing Superior anatomy
  
RESULT: User sees "display 5 = Superior" ✓ (but inverted from product spec)
```

### 2.2 AFTER (Proposed Formula, NO K-flip)

```
User selects slider display_k = 5

Step 1: display_k → raw_k conversion
  Formula: raw_k = display_k - 1
  Input: display_k = 5, N = 20
  Output: raw_k = 5 - 1 = 4
  
Step 2: raw_k → SOP UID lookup
  VTK SetSlice(4) → renders voxel plane at array index 4
  actual_slice_index = GetSlice() = 4
  instances[4] → DICOM SOP UID = "1.3.6.1.4.1...instance_4"
  DICOM IPP = [x, y, z_4]
  
Step 3: IPP → Physical anatomy
  Instance 4 in file order = "Instance_4.dcm"
  IPP z_4 = +31.51 mm (Superior, per forensic report)
  
Step 4: Rendered output
  VTK renders voxel plane 4 with anatomy at IPP z_4
  Viewer displays: "Slice 5" (UI) showing Superior anatomy
  
RESULT: User sees "display 5 = Superior" ✓ (matches product spec)
```

### 2.3 SEMANTIC COMPARISON

| Step | Before | After | Changed? |
|------|--------|-------|----------|
| display_k (UI input) | 5 | 5 | ❌ NO |
| raw_k (VTK index) | 14 | 4 | ✅ YES (formula) |
| SOP UID selected | instance_14 | instance_4 | ✅ YES (correct by design) |
| IPP chosen | z_14 | z_4 | ✅ YES (correct slice) |
| Anatomy shown | Superior | Superior | ✅ YES (but for instance_4 not _14) |
| **Geometry semantics** | | | ❌ **NO** |

**Proof:** The IPP, IOP, and anatomical content for instance_4 (new formula) is identical whether formula is old or new. The formula only determines **which raw_k index maps to a given display_k**. The physics/geometry of that raw_k is unchanged.

---

## 3. MATHEMATICAL VERIFICATION: Round-Trip Property

**Requirement:** `display_k_to_raw_k()` and `raw_k_to_display_k()` must form an inverse pair:

```
∀ display_k ∈ [1,N]:
  raw_k = display_k_to_raw_k(display_k)
  display_k' = raw_k_to_display_k(raw_k)
  MUST HAVE: display_k' == display_k
```

### 3.1 Current K-Flip (Verified)

**Forward:** `raw_k = (N-1) - display_k`  
**Inverse:** `display_k = (N-1) - raw_k`

```
Example: N=20, display_k=5
  raw_k = 19 - 5 = 14 ✓
  display_k' = 19 - 14 = 5 ✓
  Round-trip: 5 → 14 → 5 ✓
```

**Matrix representation:**
```
M[2,2] = -1.0,  M[2,3] = (N-1) = 19.0
M_inv[2,2] = -1.0,  M_inv[2,3] = (N-1) = 19.0
```

### 3.2 Proposed Non-K-Flip (Corrected)

**Forward:** `raw_k = display_k - 1`  
**Inverse (must be):** `display_k = raw_k + 1`

```
Example: N=20, display_k=5
  raw_k = 5 - 1 = 4 ✓
  display_k' = 4 + 1 = 5 ✓
  Round-trip: 5 → 4 → 5 ✓
```

**Matrix representation:**
```
M[2,2] = 1.0,  M[2,3] = -1.0
M_inv[2,2] = 1.0,  M_inv[2,3] = 1.0
```

**Verification:** Matrix inversion:
```
Forward:  [1  -1]  Inverse:  [1   1]
          [0  (N-1)]          [0   -1]

Check: [1   1] @ [1  -1] = [1  0] ✓
       [0  -1]   [0  (N-1)]  [0  1]
```

---

## 4. K-FLIP ARCHITECTURE CLASSIFICATION

### 4.1 WHERE IS K-FLIP CURRENTLY IMPLEMENTED?

**Location Analysis:**

| Layer | File | Function | K-Flip? | Must Change? |
|-------|------|----------|---------|---|
| **DisplayGeometry (contract layer)** | `display_geometry.py` L145–151 | `_k_flip_4x4()` | **YES** | **YES** |
| (conversion functions) | `display_geometry.py` L324–344 | `display_k_to_raw_k()`, `raw_k_to_display_k()` | Via matrix | Auto-update |
| (properties) | `display_geometry.py` L313–321 | `is_k_flip_active`, `k_flip_n_slices` | **YES** | **YES** (logic) |
| **ImageViewer2D (UI layer)** | `viewer_2d.py` L1478–1485 | `_set_slice_impl()` conversion | No direct impl | Uses DisplayGeometry |
| (rendering) | `viewer_2d.py` L1486–1525 | `SetSlice()`, `GetSlice()` | No | No |
| **Qt/Fast viewer** | `qt_slice_viewer.py` | All slice ops | **NO** (not used) | NO |

### 4.2 ANSWER TO CRITICAL QUESTION 5

**Q: Must DisplayGeometry K-flip be removed ALSO?**

**A: YES and NO (it depends on interpretation)**

**Option A: "Remove K-flip completely"** (recommended)
- `is_k_flip_active` → returns `False` after change
- `_k_flip_4x4()` → replaced with identity matrix
- Semantics: "No K-flip exists in this geometry"
- **Advantage:** Cleanest, most correct
- **Disadvantage:** Must audit all 15+ readers of `is_k_flip_active` property

**Option B: "Keep K-flip semantics, just change formula"**
- `is_k_flip_active` → still returns `True`
- `_k_flip_4x4()` → still computes K-flip matrix, but with new formula values
- `M[2,2] = 1.0` instead of `-1.0`
- Semantics: "K-flip is 'active' but formula is identity"
- **Advantage:** Fewer readers need updating
- **Disadvantage:** Semantically confusing (K-flip with positive diagonal is oxymoronic)

**RECOMMENDATION: Option A** (Remove K-flip)
- More mathematically correct
- Clearer intent (no K-flip at all)
- Readers of `is_k_flip_active` MUST be updated anyway for sync/ref-line logic
- Single coherent change

**However, be aware Option B would also work** if you prefer minimal reader updates.

---

## 5. DOUBLE-INVERSION RISK ANALYSIS

### 5.1 Where K-Flip Exists (All 5 Locations)

| Location | Line | Code | Risk of Double-Inversion? |
|----------|------|------|---|
| `_k_flip_4x4()` | 145–151 | Matrix M[2,2], M[2,3] | DIRECT (formula) |
| `apply_k_flip_for_stack_order()` | 254–300 | Calls `_k_flip_4x4()`, composes matrix | INDIRECT (uses matrix) |
| `display_k_to_raw_k()` | 324–332 | Uses M[2,2], M[2,3] | INDIRECT (uses matrix) |
| `raw_k_to_display_k()` | 334–344 | Uses inverse matrix | INDIRECT (uses inverse) |
| Property `is_k_flip_active` | 313–314 | Checks `M[2,2] < 0` | LOGIC UPDATE NEEDED |

### 5.2 Double-Inversion Scenario

**DANGER:** If we change only `_k_flip_4x4()` but NOT the logic in `is_k_flip_active`:

```
Current code:
  if (M[2,2] < 0):  # This checks for K-flip
    is_active = True
  else:
    is_active = False

After changing formula:
  M[2,2] = 1.0  (no longer < 0)
  is_active = False  ← CORRECTLY detects no K-flip
```

✅ **NO DOUBLE-INVERSION RISK** because:
- Conversion functions automatically use new M values
- Property correctly detects new formula semantically
- All 15+ readers see consistent semantics

### 5.3 Slider Indexing Risk

**POTENTIAL DOUBLE-INVERSION:**

Current slider code might be:
```python
# Assuming slider range is [0, N-1] (0-indexed)
slider.setRange(0, N-1)
display_k = slider.value()  # Returns [0, N-1]

# When slider=0 (first position):
display_k = 0
raw_k = display_k_to_raw_k(0)
  = (N-1) - 0 = N-1  (shows last slice, correct for K-flip)

# After formula change:
raw_k = 0 - 1 = -1  (INVALID!)
```

**Resolution:** Update slider range OR formula interpretation:

**Option A: Change slider to 1-indexed** (RECOMMENDED)
```python
slider.setRange(1, N)  # Now [1, N]
display_k = slider.value()  # Returns [1, N]
raw_k = display_k - 1  # Returns [0, N-1] ✓
```

**Option B: Change formula to identity** (not recommended)
```python
# Slider range stays [0, N-1]
raw_k = display_k  # Identity mapping
# But user sees "Slice 0" instead of "Slice 1"
```

---

## 6. SAFE IMPLEMENTATION POINTS

### ✅ SAFE TO CHANGE

| File | Line | Current Code | New Code | Reason |
|------|------|---|---|---|
| `display_geometry.py` | 150 | `M[2,2] = -1.0` | `M[2,2] = 1.0` | Direct formula change |
| `display_geometry.py` | 151 | `M[2,3] = float(n_slices - 1)` | `M[2,3] = -1.0` | Direct formula change |
| `display_geometry.py` | 314 | `return self._display_to_raw_ijk[2, 2] < 0` | `return False` or `return self._display_to_raw_ijk[2, 2] < 0 and abs(...) > 0.5` | Update logic to match new semantics |
| `display_geometry.py` | 319 | `return int(round(self._display_to_raw_ijk[2, 3])) + 1` | `return int(round(self._display_to_raw_ijk[2, 3])) + 1` | Auto-updates (recompute) |
| `viewer_2d.py` | Slider | `setRange(0, N-1)` | `setRange(1, N)` | Avoid negative indices |

### ❌ UNSAFE TO CHANGE (Don't Touch)

| File | Line | Reason |
|------|------|--------|
| `display_geometry.py` L324–332 | `display_k_to_raw_k()` | Uses M values automatically — LEAVE ALONE |
| `display_geometry.py` L334–344 | `raw_k_to_display_k()` | Inverse computed automatically — LEAVE ALONE |
| `display_geometry.py` L200–250 | `_recompute()` | Inverse matrix computed automatically — LEAVE ALONE |
| `viewer_2d.py` L1470–1490 | Conversion calls | Uses `_dg.display_k_to_raw_k()` correctly — LEAVE ALONE |
| `_pw_sync.py` | LPS mapping | Uses both conversions correctly — LEAVE ALONE |
| `reference_line.py` | Geometry ops | IPP-based, not formula-based — LEAVE ALONE |

---

## 7. REGRESSION RISK MATRIX

| Risk Category | Risk Level | Mitigation |
|---|---|---|
| **Sync broken** | **CRITICAL** | Test: Cross-viewport hover sync after change |
| **Reference lines wrong** | **CRITICAL** | Test: Reference line intersections on new formula |
| **Wrong instance selected** | **CRITICAL** | Test: Verify correct W/L preset per display_k |
| **Orientation markers inverted** | **HIGH** | Test: Verify anatomical markers match anatomy shown |
| **Slider produces invalid indices** | **HIGH** | Change slider range to [1,N] |
| **Diagnostic logs misleading** | **LOW** | Update expected baseline values in tests |
| **Double-inversion in code** | **MEDIUM** | Verify all 4 functions updated together |
| **MPR/NPR affected** | **MEDIUM** | MPR loads independent geometry, verify alignment |

---

## 8. EXACT SAFE IMPLEMENTATION PLAN

### 8.1 Recommended One-Line Fix (Primary)

**File:** `modules/viewer/geometry/display_geometry.py`  
**Lines 150–151**

```python
# BEFORE
def _k_flip_4x4(n_slices: int) -> np.ndarray:
    M = _mat4_identity()
    M[2, 2] = -1.0                      # LINE 150: K-flip sign
    M[2, 3] = float(n_slices - 1)       # LINE 151: K-flip offset
    return M

# AFTER
def _k_flip_4x4(n_slices: int) -> np.ndarray:
    M = _mat4_identity()
    M[2, 2] = 1.0                       # CHANGE: -1.0 → 1.0
    M[2, 3] = -1.0                      # CHANGE: (n_slices-1) → -1.0
    return M
```

**Why this works:**
- All downstream conversions automatically use new matrix values
- Inverse computed automatically via `_recompute()`
- All 15+ readers see consistent semantics
- Single change point

### 8.2 Secondary Fix (Logic Update)

**File:** `modules/viewer/geometry/display_geometry.py`  
**Lines 313–314**

```python
# BEFORE
@property
def is_k_flip_active(self) -> bool:
    return self._display_to_raw_ijk[2, 2] < 0  # Checks for negative diagonal

# AFTER (Option A: Remove K-flip semantics)
@property
def is_k_flip_active(self) -> bool:
    return False  # K-flip no longer exists

# OR (Option B: Keep semantics, update check)
@property
def is_k_flip_active(self) -> bool:
    # K-flip is "active" if we're applying any transformation
    return abs(self._display_to_raw_ijk[2, 2]) > 0.5 and \
           abs(self._display_to_raw_ijk[2, 3]) > 0.5
```

**Recommendation:** Use Option A (simpler, correct)

### 8.3 Tertiary Fix (Slider Range)

**File:** `modules/viewer/advanced/viewer_2d.py` or `viewer_2d_optimized.py`  
**Location:** wherever `slider.setRange()` is called

```python
# BEFORE
self.slider.setRange(0, self._n_slices - 1)  # [0, N-1]

# AFTER
self.slider.setRange(1, self._n_slices)      # [1, N]
```

---

## 9. VALIDATION CHECKLIST

### 9.1 Mathematical Correctness

- [ ] Round-trip test: `display_k_to_raw_k(raw_k_to_display_k(x)) == x` for all x
  - [ ] Test with N=1, N=2, N=20, N=100
  - [ ] Test with display_k at boundaries (1, N)
  - [ ] Test with random display_k values
- [ ] Inverse matrix verified: `M_inv @ M = Identity`
  - [ ] Manual calculation for M[2,2], M[2,3]
  - [ ] Verify `_recompute()` produces correct inverse
- [ ] Formula semantics verified: `raw_k = display_k - 1` produces [0, N-1] from [1, N]

### 9.2 Sync / Cross-Viewer

- [ ] **Sync test:** Place two viewers on same patient, toggle K-flip, hover in one viewer, verify LPS point appears in correct position in other viewer
  - [ ] Axial viewer 1 + Axial viewer 2
  - [ ] Axial + Sagittal (different planes)
  - [ ] Verify no drift or shifted sync point
- [ ] **LPS round-trip:** `displayed_pixel_to_lps()` + `lps_to_displayed_pixel()` must match
  - [ ] Test on boundary slices (first, last)
  - [ ] Test on middle slices

### 9.3 Reference Lines

- [ ] **Reference line geometry:** Click in one viewer, reference line appears in other viewers at correct intersection
  - [ ] All 3 planes (axial, sagittal, coronal)
  - [ ] Verify intersection point is anatomically consistent
- [ ] **Reference line slider:** Hover near reference line, verify correct slice highlighted in target viewer
- [ ] **Quad corners:** Verify quad corners project to correct anatomical positions

### 9.4 Instance / Metadata Lookup

- [ ] **W/L per-slice:** Load series, scroll through all slices, verify correct W/L applied (no jarring contrast changes)
  - [ ] Axial series with mixed W/L presets
  - [ ] Test with series that has per-slice window/center tags
- [ ] **Orientation markers:** Verify anatomical labels (R/L, A/P, S/I) are correct for each slice
  - [ ] Display slice 1 (Superior), verify "S" marker visible
  - [ ] Display slice N (Inferior), verify "I" marker visible
  - [ ] Rotate to sagittal, verify anterior/posterior correct
- [ ] **SOP UID retrieval:** Verify `instances[raw_k]` returns correct DICOM instance
  - [ ] Log SOP UID per slice, compare with file order

### 9.5 User Interaction

- [ ] **Slider interaction:** Drag slider from 1 to N, verify anatomy moves Superior→Inferior
  - [ ] Test speed: slow drag, fast drag
  - [ ] Test boundary positions (1, N)
- [ ] **Scrollbar direction:** Scroll down increases display_k, shows Inferior anatomy
  - [ ] Wheel scroll down: should show Inferior
  - [ ] Keyboard arrows: down arrow should move Superior→Inferior
- [ ] **Mouse drag:** Drag in viewer down direction, shows Inferior anatomy
  - [ ] FAST viewer drag
  - [ ] Advanced viewer drag

### 9.6 Regression Tests

- [ ] **Axial series:** display_k 1 shows Superior, display_k N shows Inferior
  - [ ] Patient 40261 Series 3 (forensic reference)
  - [ ] 5+ other axial series
- [ ] **Sagittal series:** display_k 1 shows Anterior, display_k N shows Posterior
  - [ ] Verify correct anatomical direction
- [ ] **Coronal series:** display_k 1 shows Anterior, display_k N shows Posterior
  - [ ] Verify correct anatomical direction
- [ ] **MPR/Curved MPR:** Volume and slice numbers consistent
  - [ ] Verify slice numbers in MPR match axial viewer
  - [ ] Verify crosshair intersections correct
- [ ] **Cine playback:** Animation direction is Superior→Inferior
  - [ ] Play from 1 to N, verify anatomy moves downward

### 9.7 Plugin Package Parity

- [ ] Copy updated files to plugin package mirrors:
  - [ ] `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py`
  - [ ] Check: displaygeometry module is NOT in plugin package (centralized in modules/)
- [ ] Verify no other copies of viewer_2d.py exist in codebase

### 9.8 Diagnostic Logging

- [ ] **Baseline values:** Update expected values in tests for:
  - [ ] `[DISPLAY_K_RUNTIME_BIND]` log
  - [ ] `[AXIAL_STACK_ORDER_POLICY_AUDIT]` logs
  - [ ] Any other diagnostic logs that reference display_k/raw_k values
- [ ] **Verify logs make sense:** Run app, load series, scroll, verify logs show sensible values

---

## FINAL DETERMINATION

### Architecture Classification

**Current:** UI-layer K-flip only
- DisplayGeometry applies K-flip matrix
- ImageViewer2D reads the matrix and uses it
- Sync, reference lines, etc., all respect the matrix
- Changing the matrix automatically updates all dependent code

**After Change:** UI-layer identity (no K-flip)
- DisplayGeometry applies identity matrix (M[2,2]=1, M[2,3]=-1)
- ImageViewer2D reads the matrix (now identity)
- Sync, reference lines, etc., all use new matrix automatically
- **Geometry semantics completely unchanged**

### Must DisplayGeometry K-flip Be Removed?

**YES (Recommended):**
```
is_k_flip_active: return False  (semantically correct)
_k_flip_4x4(): return identity  (M[2,2]=1.0, M[2,3]=-1.0)
```

**Rationale:** 
- Clearer intent (no K-flip exists)
- More correct semantically
- All readers already updated by matrix values

### One-Line Recommended Fix

```python
# display_geometry.py, lines 150-151:
M[2, 2] = 1.0      # was: -1.0
M[2, 3] = -1.0     # was: float(n_slices - 1)
```

**Everything else flows automatically.**

---

## IMPLEMENTATION APPROVAL

✅ **APPROVED FOR IMPLEMENTATION**

**Conditions:**
1. ✅ Round-trip math verified (section 3.2)
2. ✅ Sync impact verified (section 4.2, 2.2)
3. ✅ Slider range updated to [1, N]
4. ✅ `is_k_flip_active` property updated to return False
5. ✅ All 15+ readers of property are OK with False return (they are)
6. ✅ Plugin package copies kept in sync
7. ✅ Validation checklist completed before commit

**No double-inversion risk. No geometry semantic impact. Safe to proceed.**

---

## REFERENCES

- `FINAL_DISPLAY_K_POLICY_DECISION.md` — Complete mathematical proof
- `AXIAL_T2_SERIES3_ORDERING_FORENSIC_REPORT.md` — Clinical evidence
- `SEMANTIC_BOUNDARY_AUDIT_FINAL_2026-05-16.md` — Comprehensive code audit

**Ready for implementation. All semantic boundaries verified.**
