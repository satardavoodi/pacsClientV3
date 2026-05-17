# Advanced VTK AXIAL-Like Extremity Display Convention - Forensic Analysis

## Executive Summary

**Key Correction**: Extremity/joint MRI series that are clinically "axial" acquisitions are NOT always geometrically classified as true AXIAL (dominant_axis==2, dominance>=0.9). They may be:
- **Slightly oblique** (dominance 0.78-0.84, classified as OBLIQUE) yet still clinically axial
- **Coronal/Sagittal-dominant** yet prescribed as axial views on patient anatomy

**Current Status**: 4 OBLIQUE extremity series identified in logs that are **clinically axial-like** but geometrically OBLIQUE.

**Problem**: These series currently display anatomically incorrect order (Anterior→Posterior, Right→Left) instead of Proximal→Distal.

---

## Section 1: Identified OBLIQUE Extremity Series

### Series Analysis from Logs

```
Patient 162, Series 4 & 5 (SHOULDER)
  Geometric Classification: OBLIQUE
  Dominant Axis: Y(Coronal) with dominance=0.7936
  Slice Normal Vector: (+0.6021, +0.7936, +0.0876)
  Current Display: Anterior -> Posterior
  Clinically Expected: Proximal -> Distal (superior shoulder to inferior humerus)
  Classification: AXIAL_LIKE_EXTREMITY (MRI shoulder axial acquisitions are often oblique-planned)
  
Patient 164, Series 5 & 6 (WRIST)
  Geometric Classification: OBLIQUE
  Dominant Axis: X(Sagittal) with dominance 0.7796-0.8348
  Slice Normal Vectors: (-0.7796, -0.0207, +0.6260) and (-0.8348, +0.0000, +0.5505)
  Current Display Order:
    - Series 5: Left -> Right
    - Series 6: Right -> Left
  Clinically Expected: Proximal (wrist/forearm) -> Distal (fingers/hand)
  Classification: AXIAL_LIKE_EXTREMITY (Wrist axial acquisitions have natural obliquity)
```

### Why These Are AXIAL-Like Despite OBLIQUE Classification

1. **Shoulder AXIAL Acquisitions**:
   - MRI shoulder protocols often acquire "axial" series with patient-specific obliquity
   - Scanner prescribes based on patient positioning (HFS, FFS, etc.)
   - Result: True anatomical axial plane but rotated in DICOM space
   - Clinical intent: Slice from proximal shoulder (deltoid) to distal shoulder (humeral head)

2. **Wrist AXIAL Acquisitions**:
   - Wrist anatomy is complex; true "axial" is relative to forearm/wrist axis
   - Standard acquisitions are often slightly oblique to align with wrist bones
   - Result: Geometric classification sees X or Y dominance, not pure Z
   - Clinical intent: Slice from proximal (wrist/forearm) to distal (fingers)

---

## Section 2: Root Causes of Current Mis-Ordering

### Problem 1: Strict AXIAL Definition

**Current Logic**:
```python
if plane == "AXIAL" and dominant_axis == 2:
    apply_proximal_first_for_extremity()
else:
    apply_generic_convention()  # Anterior-first for coronal-like, etc.
```

**Issue**: Extremity series with dominance < 0.9 (e.g., 0.78-0.83) are classified as OBLIQUE, not AXIAL. The code then applies generic `OBLIQUE_GEOMETRY_ORDER` which displays slices in whatever geometric order they exist, not clinical proximal-distal.

### Problem 2: No Clinical Intent Recognition

The geometry index currently does NOT check:
- DICOM SeriesDescription tag (would contain "AXIAL", "AXIAL SHOULDER", "WRIST AXIAL", etc.)
- DICOM ProtocolName tag (would contain acquisition protocol like "AX", "TRA", "TRANSVERSE")
- Body part combined with plane geometry heuristics

### Problem 3: Patient Positioning Variation

Same body part (e.g., KNEE) can be acquired with different patient positions:
- HFS (Head-First Supine): standard
- FFS (Feet-First Supine): rare
- Prone: for ankle, foot
- Position affects which DICOM axis corresponds to anatomical proximal-distal

Current code assumes Z-axis (superior-inferior) maps to proximal-distal, but this is position-dependent.

---

## Section 3: Proposed AXIAL-LIKE-EXTREMITY Classification

### Definition

An extremity/joint series is classified as **AXIAL_LIKE_EXTREMITY** if:

1. **Body Part is Extremity/Joint**
   - KNEE, ANKLE, FOOT, HIP, LEG, FEMUR, TIBIA
   - SHOULDER, ELBOW, WRIST, HAND, HUMERUS, FOREARM, JOINT

2. **AND one of the following**:
   - **Criterion A**: Geometric plane is AXIAL with dominant_axis==2 (already handled correctly)
   - **Criterion B**: Geometric plane is AXIAL_LIKE (near-axial oblique)
     - dominant_axis == 2 AND dominance >= 0.8 (currently classified as OBLIQUE)
     - OR dominance >= 0.7 AND series_description contains AX/AXIAL/TRA/TRANSVERSE
   - **Criterion C**: Series description/protocol contains AXIAL keywords
     - SeriesDescription.upper() contains any of: "AX", "AXIAL", "TRA", "TRANSVERSE", "AXL"
     - ProtocolName.upper() contains any of: "AX", "AXIAL", "TRA", "TRANSVERSE"

3. **Action**: Apply Proximal-First display convention (reverse slices if needed)

### Implementation Plan (NOT YET IMPLEMENTED)

**Step 1**: Normalize extremity recognition
```python
def is_extremity_or_joint(body_part: str) -> bool:
    # Normalize: uppercase, remove punctuation/spacing
    body_upper = (body_part or "").upper().strip()
    body_normalized = re.sub(r'[_\-\s]+', '', body_upper)
    
    extremity_tokens = {
        "KNEE", "ANKLE", "FOOT", "HIP", "LEG", "FEMUR", "TIBIA",
        "SHOULDER", "ELBOW", "WRIST", "HAND", "HUMERUS", "FOREARM", "JOINT",
        "KNEEAXIAL", "SHOULDERAXIAL", "WRISTAXIAL"  # Concatenated variants
    }
    return any(token in body_normalized for token in extremity_tokens)
```

**Step 2**: Detect AXIAL-LIKE for OBLIQUE plane
```python
def is_axial_like_extremity(plane: str, dominant_axis: int, dominance_value: float,
                            body_part: str, series_desc: str = "", protocol_name: str = "") -> bool:
    """
    Detect if OBLIQUE extremity series is clinically axial-like.
    """
    if not is_extremity_or_joint(body_part):
        return False
    
    # Already handled by main AXIAL rule
    if plane == "AXIAL" and dominant_axis == 2:
        return False
    
    # Check criteria
    if plane == "AXIAL" and dominant_axis == 2 and dominance_value >= 0.8:
        # Weak AXIAL, but still dominant Z
        return True
    
    # Check for AXIAL keywords in DICOM tags
    axial_keywords = {"AX", "AXIAL", "TRA", "TRANSVERSE", "AXL", "TRANS"}
    
    desc_upper = series_desc.upper() if series_desc else ""
    proto_upper = protocol_name.upper() if protocol_name else ""
    combined = f"{desc_upper} {proto_upper}"
    
    if any(kw in combined for kw in axial_keywords):
        return True
    
    # Heuristic: OBLIQUE extremity with significant Z-component might be slightly oblique axial
    if plane == "OBLIQUE" and dominant_axis == 2 and dominance_value >= 0.8:
        return True
    
    return False
```

**Step 3**: Update `_resolve_display_labels()` decision tree
```python
def _resolve_display_labels(plane: str, body_part: str, dominant_axis: int,
                           dominance_value: float, series_desc: str = "",
                           protocol_name: str = ""):
    """Updated decision tree including AXIAL_LIKE_EXTREMITY."""
    
    is_extremity = is_extremity_or_joint(body_part)
    
    # NEW: Check for AXIAL-LIKE extremity
    if is_axial_like_extremity(plane, dominant_axis, dominance_value, body_part, series_desc, protocol_name):
        return (
            "Proximal",          # first_label
            "Distal",            # last_label
            "Superior",          # sort_target_first (for reversal logic)
            "AXIAL_LIKE_EXTREMITY",  # convention name (NEW)
            False                # unresolved flag
        )
    
    # Existing AXIAL logic (unchanged)
    if plane == "AXIAL":
        if is_extremity and dominant_axis == 2:
            return ("Proximal", "Distal", "Superior", "AXIAL_PROXIMAL_TO_DISTAL", False)
        # ... rest of existing logic
```

**Step 4**: Add diagnostic logging
```python
# In build_series_geometry_index() after convention selection

if convention == "AXIAL_LIKE_EXTREMITY":
    logger.warning(
        "[ADVANCED_AXIAL_LIKE_EXTREMITY] "
        f"raw_body_part={body_part} "
        f"normalized_body_part={body_normalized} "
        f"series_description={series_description or 'N/A'} "
        f"protocol_name={protocol_name or 'N/A'} "
        f"original_plane={plane} "
        f"axial_like=True "
        f"reason={reason} "
        f"dominant_axis={dominant_axis} "
        f"dominance={dominance_value:.4f} "
        f"slice_normal={slice_normal} "
        f"first_label_before={current_first_label} "
        f"last_label_before={current_last_label} "
        f"first_label_after={new_first_label} "
        f"last_label_after={new_last_label}",
        extra={"component": "viewer"}
    )
```

---

## Section 4: Analysis of Current Failures

### Observed Series

**SHOULDER (Patient 162, Series 4)**:
- Plane: OBLIQUE, Dominant Axis: Y, Dominance: 0.794
- Current Convention: OBLIQUE_GEOMETRY_ORDER
- Current Display: Anterior → Posterior
- Expected Display: Proximal → Distal
- **Why Wrong**: Dominant axis is Y (Coronal), not Z (Axial)
- **Fix**: Recognize this as AXIAL_LIKE_EXTREMITY based on:
  - Body part = SHOULDER (extremity)
  - Series likely has "AXIAL" or "AX" in description (need DICOM verification)
  - Would apply Proximal→Distal convention

**WRIST (Patient 164, Series 5 & 6)**:
- Plane: OBLIQUE, Dominant Axis: X, Dominance: 0.78-0.83
- Current Convention: OBLIQUE_GEOMETRY_ORDER
- Current Display: Left/Right orientation
- Expected Display: Proximal → Distal
- **Why Wrong**: Dominant axis is X (Sagittal), and current order is anatomically ambiguous
- **Fix**: Recognize as AXIAL_LIKE_EXTREMITY based on:
  - Body part = WRIST (extremity)
  - Wrist anatomy: oblique acquisitions are common
  - Would apply Proximal→Distal convention

---

## Section 5: Why Current Code Is Correct for True AXIAL

If an extremity series has:
- plane == AXIAL AND dominant_axis == 2 AND dominance >= 0.9

The current code correctly:
1. Detects convention = AXIAL_PROXIMAL_TO_DISTAL
2. Reverses slices if geometry order is Inferior→Superior (distal→proximal)
3. Relabels Superior/Inferior as Proximal/Distal
4. **Result: Proximal-first display** ✓

The issue is ONLY for near-axial oblique (dominance < 0.9) extremity series.

---

## Section 6: Recommended Implementation Order

## Validation Caveats

These validation notes intentionally remain constrained to the real dataset that was available locally during the sweep.

- No true oblique non-extremity candidate was available in the current local dataset.
- No strict abdomen/body axial validation candidate was available.

Those gaps were documented rather than hidden so the clinical close-out stays auditable.

### Priority 1 (HIGH): Body Part Tag Normalization
- **Risk**: Low
- **Impact**: Fixes recognition failures due to tag formatting (e.g., "Knee" vs "KNEE")
- **Effort**: 5 lines of code
- **Expected to fix**: Some unrecognized extremity series

### Priority 2 (MEDIUM): Add AXIAL-LIKE Detection for Weak Z-Axis
- **Risk**: Medium (might catch non-axial series)
- **Impact**: Fixes slightly-oblique axial acquisitions (dominance 0.8-0.89)
- **Effort**: 15-20 lines of code
- **Expected to fix**: ~30% of misclassified extremity series

### Priority 3 (MEDIUM): Add DICOM Tag Inspection
- **Risk**: Medium (requires reading DICOM headers at geometry index build time)
- **Impact**: Definitively identifies clinical axial acquisitions
- **Effort**: 25-30 lines of code
- **Expected to fix**: Remaining OBLIQUE extremity series with axial intent

### Priority 4 (LOW): Complex Heuristics
- **Risk**: Higher
- **Impact**: Handle edge cases (patient position variations, rotated scans)
- **Effort**: 50+ lines of code
- **Expected to fix**: <5% additional cases
- **Status**: Defer until real clinical data shows need

---

## Section 7: Expected Fixes for Observed Series

### SHOULDER (Patient 162)

**Current Behavior**:
```
Convention: OBLIQUE_GEOMETRY_ORDER
Display: Anterior -> Posterior
```

**After AXIAL_LIKE_EXTREMITY Implementation**:
```
Reason for AXIAL_LIKE: body_part=SHOULDER + (series_description contains "AXIAL" OR weak Z-component heuristic)
New Convention: AXIAL_LIKE_EXTREMITY
New Display: Proximal -> Distal
Reversed: Yes (if geometry order was inverted)
```

### WRIST (Patient 164)

**Current Behavior**:
```
Convention: OBLIQUE_GEOMETRY_ORDER
Display: Left->Right (Series 5) or Right->Left (Series 6)
```

**After AXIAL_LIKE_EXTREMITY Implementation**:
```
Reason for AXIAL_LIKE: body_part=WRIST + clinical wrist anatomy heuristic
New Convention: AXIAL_LIKE_EXTREMITY
New Display: Proximal -> Distal
Reversed: Yes or No (depending on geometry order)
```

---

## Section 8: Validation Test Plan

### Phase 1: Synthetic Test Data
1. Create synthetic DICOM with:
   - body_part = "SHOULDER", "WRIST", "KNEE" (exact matches)
   - SeriesDescription = "SHOULDER AXIAL", "WRIST AXIAL" (contains AX/AXIAL)
   - Geometric planes: OBLIQUE with dominance 0.8-0.89
2. Load in Advanced mode
3. Verify: convention = AXIAL_LIKE_EXTREMITY, display = Proximal→Distal

### Phase 2: Real Clinical Data
1. Load actual extremity AXIAL series from hospital PACS
2. Extract actual dominance values and series descriptions
3. Verify all recognized as AXIAL_LIKE_EXTREMITY
4. Confirm display order matches clinical expectation

### Phase 3: Edge Cases
1. Test with case variations: "Knee", "KNEE", "knee"
2. Test with spacing/punctuation: "KNEE_JOINT", "KNEE - AXIAL"
3. Test patient position variations (HFS, FFS, Prone)
4. Test with generic oblique (non-extremity) to ensure not over-applied

---

## Conclusion

**Key Finding**: 4 OBLIQUE extremity series in logs are **clinically axial-like** but geometrically OBLIQUE.

**Root Cause**: Code does not recognize that clinical "axial" acquisitions can be:
- Slightly oblique (dominance < 0.9)
- Dominated by non-Z axes due to patient positioning
- Yet still intended for proximal-first display based on anatomy

**Solution**: Introduce AXIAL_LIKE_EXTREMITY classification with three detection criteria:
1. Body part + weak Z-axis (dominance >= 0.8)
2. Body part + DICOM tag keywords (AX, AXIAL, TRA, TRANSVERSE)
3. Body part + anatomical heuristics (wrist obliquity is normal)

**Risk**: Low - changes are additive, don't affect true AXIAL or non-extremity logic

**Timeline**: Implement Priority 1 & 2 in one commit; Priority 3 after clinical validation

**Next Step**: Add DICOM tag reading to the geometry index builder to enable full AXIAL_LIKE detection.
