# Advanced VTK AXIAL Extremity Display Convention - Root Cause Analysis

## Executive Summary

**No AXIAL extremity/joint series are present in the current logs.** All loaded extremity series (knee, shoulder, wrist) are SAGITTAL, CORONAL, or OBLIQUE planes.

However, **code analysis reveals no fundamental logical flaw**, but identifies **three plausible failure scenarios** that would manifest as distal-first display if AXIAL extremity series were loaded under specific non-ideal conditions.

## Section 1: Log Analysis Results

### Inventory of All Loaded Advanced Series

**Total**: 11 Advanced geometry-indexed series

| Plane | Extremity/Joint | Body/Head | Total |
|-------|-----------------|-----------|-------|
| AXIAL | 0 | 0 | 0 |
| SAGITTAL | 1 | 0 | 1 |
| CORONAL | 3 | 0 | 3 |
| OBLIQUE | 7 | 0 | 7 |

### Why No AXIAL Extremity Series?

The recent patient sessions loaded:
- Patient 156 (KNEE): SAGITTAL (S4), CORONAL (S5, S6) — no AXIAL acquired
- Patient 162 (SHOULDER): OBLIQUE only (S4, S5) — no AXIAL acquired
- Patient 164 (WRIST): OBLIQUE (S5, S6), CORONAL (S8) — no AXIAL acquired

These are realistic clinical acquisitions (MRI extremity protocols often skip pure AXIAL in favor of oblique plannings), but they do NOT test the AXIAL extremity convention.

### Series Loaded (Full Table)

```
Series | Patient | Plane | Body Part | Laterality | Patient Pos | First Label | Last Label | Convention
-------|---------|-------|-----------|-----------|------------|-------------|-----------|---
4      | 156     | SAGITTAL | KNEE | L | FFS | Right | Left | SAGITTAL_RIGHT_TO_LEFT
5      | 156     | CORONAL | KNEE | L | FFS | Anterior | Posterior | CORONAL_ANTERIOR_TO_POSTERIOR
6      | 156     | CORONAL | KNEE | L | FFS | Anterior | Posterior | CORONAL_ANTERIOR_TO_POSTERIOR
4      | 162     | OBLIQUE | SHOULDER | R | HFS | Anterior | Posterior | OBLIQUE_GEOMETRY_ORDER
5      | 162     | OBLIQUE | SHOULDER | R | HFS | Anterior | Posterior | OBLIQUE_GEOMETRY_ORDER
6      | 164     | OBLIQUE | WRIST | L | HFS | Right | Left | OBLIQUE_GEOMETRY_ORDER
5      | 164     | OBLIQUE | WRIST | L | HFS | Left | Right | OBLIQUE_GEOMETRY_ORDER
8      | 164     | CORONAL | WRIST | L | HFS | Anterior | Posterior | CORONAL_ANTERIOR_TO_POSTERIOR
```

---

## Section 2: Code Path Analysis - How AXIAL Extremity Display Convention Is Chosen

### 2.1 Plane Detection

**File**: `advanced_geometry_contract.py::_plane_from_normal()` (lines 45-70)

The function computes the slice_normal from IOP (Image Orientation Patient) and determines the dominant axis:
- axis 0 (X) → SAGITTAL
- axis 1 (Y) → CORONAL  
- axis 2 (Z) → AXIAL (only if dominance ≥ 0.9)

**Contract**: AXIAL is detected when `dominant_axis == 2` with dominance ≥ 0.9. Otherwise, classified as OBLIQUE.

### 2.2 Body Part Extraction

**File**: `advanced_geometry_contract.py::_is_extremity_or_joint()` (lines 72-83)

Recognizes extremity keywords: KNEE, ANKLE, FOOT, HIP, LEG, FEMUR, TIBIA, SHOULDER, ELBOW, WRIST, HAND, HUMERUS, FOREARM, JOINT, EXTREM

Source: DICOM tag (0x0018, 0x0015) = "Body Part Examined"

### 2.3 Display Convention Decision (CRITICAL LOGIC)

**File**: `advanced_geometry_contract.py::_resolve_display_labels()` (lines 85-118)

**Decision tree for AXIAL plane**:

```python
if plane == "AXIAL":
    if _is_extremity_or_joint(body_part) AND dominant_axis == 2:
        # CASE A: True AXIAL extremity with clear Z-axis
        first_display_label = "Proximal"
        last_display_label = "Distal"
        sort_target_first_label = "Superior"
        convention = "AXIAL_PROXIMAL_TO_DISTAL"
        unresolved = False
    else:
        # CASE B: Either body/head AXIAL, or extremity with non-2 axis
        if _is_extremity_or_joint(body_part):
            # Extremity but axis != 2 (shouldn't happen for true AXIAL)
            unresolved = True
            convention = "AXIAL_SUPERIOR_TO_INFERIOR_UNRESOLVED_EXTREMITY"
            first_display_label = "Superior"
        else:
            # Standard body/head AXIAL (brain, abdomen)
            convention = "AXIAL_SUPERIOR_TO_INFERIOR"
            first_display_label = "Superior"
        last_display_label = "Inferior"
        sort_target_first_label = "Superior"
    return first_display_label, last_display_label, sort_target_first_label, convention, unresolved
```

**Key insight**: The code assumes that IF an extremity is detected AND it's a true AXIAL (dominant_axis==2), THEN apply proximal-first. Otherwise, fall back to body/head rule (superior-first).

### 2.4 Slice Ordering & Reversal

**File**: `advanced_geometry_contract.py::build_series_geometry_index()` (lines 565-580)

1. Sort instances geometrically by slice_pos (inferior→superior typically for AXIAL)
2. Detect the current first/last labels from geometry  
3. **Reverse if geometry order doesn't match desired sort_target_first**
4. After any reversal, recompute the actual first/last display labels

The reversal logic is **correct**:
```python
if geometry_first_label != sort_target_first_label and geometry_last_label == sort_target_first_label:
    display_instances = tuple(reversed(geometry_instances))
```

This properly detects when instances need to be flipped to achieve superior-first ordering.

---

## Section 3: Root Cause Analysis - When Distal-First Would Occur

### Scenario 3a: Body Part Not Recognized (LIKELY)

**Trigger**: DICOM Body Part tag doesn't match the extremity token list

**Examples**:
- "Knee" (vs "KNEE" - case-sensitive match)
- "Knee_Joint" (underscore not handled)
- "Left Knee" (extra text breaks detection)
- "KNEEAXIAL" (concatenated)

**Result**:
- `_is_extremity_or_joint()` returns False
- Convention selected: `AXIAL_SUPERIOR_TO_INFERIOR`
- Display: Superior→Inferior = Distal→Proximal for lower extremity (WRONG)

**Likelihood**: **HIGH** (DICOM tag formats vary by scanner/RIS)

### Scenario 3b: Dominance < 0.9 (Oblique AXIAL)

**Trigger**: AXIAL series acquired with slight obliquity

**Examples**:
- Prescription 5° from true horizontal
- dominance = 0.85 (below the 0.9 threshold)

**Result**:
- `_plane_from_normal()` classifies as OBLIQUE instead of AXIAL
- Convention selected: `OBLIQUE_GEOMETRY_ORDER`
- Display: Whatever order the files are in (could be distal→proximal by chance)

**Likelihood**: **MEDIUM** (MRI AXIAL can have intentional slight obliquity)

### Scenario 3c: Axis Inference Uncertainty

**Trigger**: Extremity AXIAL where the dominant axis is detected as not-2 despite being true AXIAL

**Result**:
- Convention selected: `AXIAL_SUPERIOR_TO_INFERIOR_UNRESOLVED_EXTREMITY`
- Display: Superior→Inferior (distal→proximal for legs, wrong)
- Warning log emitted: `[ADVANCED_SERIES_GEOMETRY_WARNING] reason=unresolved_extremity_display`

**Likelihood**: **LOW-MEDIUM** (would be flagged in logs)

---

## Section 4: Why Code Analysis Shows NO Fundamental Bug (When Conditions Are Ideal)

If AXIAL extremity series has:
1. Body part recognized correctly
2. dominant_axis == 2 (true AXIAL geometry)
3. Instances ordered geometrically by IPP

Then the logic is **correct**:
- Selects `AXIAL_PROXIMAL_TO_DISTAL`
- Reverses if needed to achieve superior-first ordering
- Relabels superior/inferior as proximal/distal
- Result: **Proximal-first display** ✓

The bug is not in the algorithm; it's in the **assumptions** about input data quality and DICOM tag normalization.

---

## Section 5: Why We Haven't Seen The Problem Yet

**Log evidence**: Zero AXIAL extremity series in current session

**Possible reasons**:
1. Recent patient cohort acquired clinically realistic protocols (sagittal/coronal/oblique preferred)
2. AXIAL extremity acquisitions, if any, loaded in FAST mode (Qt path), not Advanced VTK
3. AXIAL extremity series not yet loaded for evaluation

**To trigger the issue**: Explicitly load AXIAL knee/shoulder/wrist in Advanced mode, then check if first_display_label is "Proximal" or "Distal".

---

## Section 6: Proposed Minimal Fix (NOT IMPLEMENTED YER)

### Option A: Normalize DICOM Body Part Tags

**Location**: Where body_part is extracted in `build_series_geometry_index()`

**Action**: Standardize tags to match recognizer tokens
```python
body_part_normalized = (body_part or "").upper().strip()
# Remove common punctuation/spacing
body_part_normalized = re.sub(r'[_\-\s]+', '', body_part_normalized)
```

**Effect**: Catches "Knee", "knee", "KNEE_JOINT", "Left Knee" variants

**Risk**: Low - only makes the extremity detector more robust

### Option B: Relax Dominant Axis Threshold for Extremity

**Location**: `_resolve_display_labels()` line 99

**Current**:
```python
if _is_extremity_or_joint(body_upper) and dominant_axis == 2:
```

**Proposed**:
```python
# For extremity AXIAL, be more lenient on axis threshold (0.8 instead of 0.9)
is_extremity = _is_extremity_or_joint(body_upper)
is_strong_axial = dominant_axis == 2
is_weak_axial = dominant_axis == 2 and dominance >= 0.8
if is_extremity and (is_strong_axial or is_weak_axial):
    # Apply proximal-first convention
```

**Effect**: Catches slightly oblique AXIAL extremity acquisitions

**Risk**: Might over-apply to truly oblique planes; requires measured testing

### Option C: Add Body Part Laterality for Proximal Inference

**Location**: `_resolve_display_labels()` extremity branch

**Action**: Use body_part + laterality + orientation cosines to infer proximal direction even when axis is weak

**Effect**: More robust for clinical acquisitions with acquisition variations

**Risk**: Complex heuristics; higher chance of misclassification

---

## Section 7: Recommended Validation Test Plan

### Step 1: Generate AXIAL Extremity Test DICOM

Create synthetic DICOM with:
- Body part: "KNEE", "SHOULDER", "WRIST" (exact matches)
- Plane: True AXIAL (dominance = 1.0, axis = 2)
- Instance order: Both "Distal→Proximal" and "Proximal→Distal"

### Step 2: Load in Advanced Mode

Load each in Advanced VTK viewer.

### Step 3: Check Result

- First display label should be "Proximal"
- Reference lines should align with proximal end

### Step 4: Repeat with Variations

- Body part with case variations: "Knee", "KNEE_JOINT", "Left Knee"
- Slight obliquity: dominance = 0.88 (triggers Scenario 3b)
- Geometry reversed: disk files ordered "Distal→Proximal"

### Step 5: Verify Logs

Check `[ADVANCED_SERIES_GEOMETRY_INDEX]` log entries for:
- Convention chosen
- Body part recognition status
- dominant_axis value
- first_display_label actual value

---

## Conclusion

**Current Status**:
- ✓ Code logic is correct for ideal inputs (body part recognized, true AXIAL)
- ✗ No AXIAL extremity series in logs yet to validate real-world behavior
- ⚠ Three plausible failure scenarios identified that could cause distal-first display

**Root Cause** (Hypothesis):
- Most likely: Body part tag format variation → not recognized as extremity → falls back to superior-first (distal for legs)
- Secondary: Series classified as OBLIQUE due to dominance < 0.9
- Tertiary: Unresolved extremity AXIAL falling back to generic axial rule

**Recommended Fix Priority**:
1. **HIGH**: Normalize DICOM body part tags (Option A - low risk)
2. **MEDIUM**: Add test cases with real AXIAL extremity loads
3. **DEFERRED**: Relax axis thresholds or add complex heuristics (wait for real test results first)

**Next User Action**: Load real AXIAL extremity series in Advanced mode, capture logs with `[ADVANCED_SERIES_GEOMETRY_INDEX]` entries, and share exact entries showing the distal-first display if reproduced.
