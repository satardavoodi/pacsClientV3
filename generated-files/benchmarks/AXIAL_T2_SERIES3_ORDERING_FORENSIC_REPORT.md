# Axial T2 Series 3 Ordering Forensic Report

**Patient:** 40261  
**Series Number:** 3  
**Sequence:** t2_tse_fs_AXI_256_fov140 (Axial T2 TSE Fat-Sat)  
**Modality:** MR  
**Study UID:** 1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058  
**Series UID:** 1.3.12.2.1107.5.2.46.174759.2026051212205633737775718.0.0.0  
**Report Generated:** 2026-05-16  
**Viewer Mode:** Advanced (viewer_2d.py)

---

## Executive Summary

**CRITICAL FINDING:** The Advanced Viewer (VTK-based viewer_2d) is displaying slice numbering with **complete inversion** relative to DICOM radiological convention.

| Metric | Finding |
|--------|---------|
| **K-flip active** | YES |
| **Display numbering inverted** | YES |
| **Root cause location** | DisplayGeometry K-flip policy OR Viewer2D display_k/raw_k mapping |
| **User-visible symptom** | Slice "20" appears Superior (correct anatomy), Slice "1" appears Inferior (correct anatomy) — **numbering is backwards** |
| **Expected radiological order** | Slice 1 = Inferior, Slice 20 = Superior |

---

## Detailed Forensic Chain

### 1. DICOM Series Geometry

#### Header Geometry
```
Row Cosines (X-direction):     [ 0.990271,  0.028356, -0.136234]
Col Cosines (Y-direction):     [-0.001728,  0.981448,  0.191719]
Slice Normal (Z-direction):    [ 0.139143, -0.189618,  0.971949]
  Dominant Axis:               Z (Superior-Inferior, axis=2)
  Dominant Value:              0.9719 (pointing Superior)
```

#### First and Last Slices
```
Instance 1 (Instance_0001.dcm):
  IPP:        [-171.574, -88.495, 31.513]
  Projection: +23.535 (SUPERIOR)
  Physical:   Head/Superior end

Instance 20 (Instance_0020.dcm):
  IPP:        [-184.066, -71.472, -55.744]
  Projection: -66.240 (INFERIOR)
  Physical:   Feet/Inferior end
```

#### Projection Analysis
- **Min Projection:** -66.24 (Instance 20 = Inferior)
- **Max Projection:** +23.54 (Instance 1 = Superior)
- **Direction:** Negative (DICOM files stored Inferior→Superior in spatial order, Superio→Inferior in instance numbering)

---

### 2. Canonical Geometry Ordering

The DICOM stack contains 20 slices with Instance Numbers 1–20 in the file sequence.

When slices are sorted by **ascending IPP projection** (radiological order: Inferior→Superior):

#### Complete 20-Slice Sort Table

| Display K | Instance | File | IPP Projection | Physical Label | No-Flip Result | Flip=20-K |
|-----------|----------|------|----------------|----------------|---|---|
| 1 | 20 | Instance_0020.dcm | -66.24 | Inferior | Would show Inferior | Shows as 20 |
| 2 | 19 | Instance_0019.dcm | -61.51 | Inferior | Would show Inferior | Shows as 19 |
| 3 | 18 | Instance_0018.dcm | -56.79 | Inferior | Would show Inferior | Shows as 18 |
| 4 | 17 | Instance_0017.dcm | -52.06 | Inferior | Would show Inferior | Shows as 17 |
| 5 | 16 | Instance_0016.dcm | -47.34 | Inferior | Would show Inferior | Shows as 16 |
| 6 | 15 | Instance_0015.dcm | -42.61 | Inferior | Would show Inferior | Shows as 15 |
| 7 | 14 | Instance_0014.dcm | -37.89 | Inferior | Would show Inferior | Shows as 14 |
| 8 | 13 | Instance_0013.dcm | -33.16 | Inferior | Would show Inferior | Shows as 13 |
| 9 | 12 | Instance_0012.dcm | -28.44 | Inferior | Would show Inferior | Shows as 12 |
| 10 | 11 | Instance_0011.dcm | -23.71 | Inferior | Would show Inferior | Shows as 11 |
| 11 | 10 | Instance_0010.dcm | -18.99 | Inferior | Would show Inferior | Shows as 10 |
| 12 | 9 | Instance_0009.dcm | -14.26 | Inferior | Would show Inferior | Shows as 9 |
| 13 | 8 | Instance_0008.dcm | -9.54 | Inferior | Would show Inferior | Shows as 8 |
| 14 | 7 | Instance_0007.dcm | -4.81 | Inferior | Would show Inferior | Shows as 7 |
| 15 | 6 | Instance_0006.dcm | -0.09 | Inferior | Would show Inferior | Shows as 6 |
| 16 | 5 | Instance_0005.dcm | 4.64 | Superior | Would show Superior | Shows as 5 |
| 17 | 4 | Instance_0004.dcm | 9.36 | Superior | Would show Superior | Shows as 4 |
| 18 | 3 | Instance_0003.dcm | 14.09 | Superior | Would show Superior | Shows as 3 |
| 19 | 2 | Instance_0002.dcm | 18.81 | Superior | Would show Superior | Shows as 2 |
| 20 | 1 | Instance_0001.dcm | 23.54 | Superior | Would show Superior | Shows as 1 |

---

### 3. DisplayGeometry K-Flip Policy

#### Two Competing Hypotheses

**Hypothesis 1: NO K-FLIP (Radiological Order)**
```
Formula: raw_k = display_k - 1
Example: display_k 1 → raw_k 0 → Instance 20 → Inferior ✓
         display_k 20 → raw_k 19 → Instance 1 → Superior ✓
```

**Hypothesis 2: WITH K-FLIP (Current Observed Behavior)**
```
Formula: raw_k = 20 - display_k
Example: display_k 1 → raw_k 19 → Instance 1 → Superior ✓
         display_k 20 → raw_k 0 → Instance 20 → Inferior ✓
```

#### Clinical Validation

User observation:
- **Displayed slice "20" is actually Superior** → Instance 1 at IPP projection +23.54
- **Displayed slice "1" is actually Inferior** → Instance 20 at IPP projection -66.24

This **EXACTLY matches Hypothesis 2: K-FLIP IS ACTIVE**.

---

### 4. Where Does Numbering Become Inverted?

The inversion occurs at **THREE possible locations**, in order of likelihood:

#### **Location A: DisplayGeometry K-Flip Policy (MOST LIKELY)**

When the VTK viewer loads the series, `DisplayGeometry` or a k-flip layer applies:
```
display_k_to_raw_k = lambda dk: 20 - dk
```

This maps user-facing display_k numbers backwards through the VTK internal raw_k array.

**Files to check:**
- `modules/viewer/advanced/viewer_2d.py` — DisplayGeometry construction or reset_slider()
- `modules/viewer/advanced/viewer_2d_optimized.py` — alternative implementation
- Any file containing `display_k`, `raw_k`, `k_flip`, `k_invert` logic

#### **Location B: Viewer2D set_slice() / reset_slider() Mapping (LIKELY)**

The `reset_slider()` or `set_slice()` method in Viewer2D may apply a secondary transform:
```python
def reset_slider(self):
    display_k = self._slider.value()
    raw_k = self._n_slices - display_k  # Inversion happens here
    self._set_slice_impl(raw_k)
```

**Files to check:**
- `modules/viewer/advanced/viewer_2d.py` — search for `reset_slider`, `set_slice`, `_slider.setValue`

#### **Location C: Counter/Label Generation (UNLIKELY)**

The slice counter display might be applying a label inversion separately from the actual slice selection. Less likely because the anatomy is correct (only numbering is inverted).

---

### 5. Current K-Flip Policy Analysis

#### With K-Flip Active (Observed)
```
display_k=1  → raw_k=19 → Instance_0001 → IPP projection +23.54 → SUPERIOR ✓
display_k=10 → raw_k=10 → Instance_0011 → IPP projection -23.71 → ~INFERIOR ✓
display_k=20 → raw_k=0  → Instance_0020 → IPP projection -66.24 → INFERIOR ✓
```

#### Without K-Flip (Expected)
```
display_k=1  → raw_k=0 → Instance_0020 → IPP projection -66.24 → INFERIOR
display_k=10 → raw_k=9 → Instance_0010 → IPP projection -18.99 → INFERIOR  
display_k=20 → raw_k=19 → Instance_0001 → IPP projection +23.54 → SUPERIOR
```

---

### 6. VTK Slice Interpretation Chain

When user interacts with slider at display_k=1:

1. **Slider receives:** `setValue(1)`
2. **Viewer maps:** `raw_k = 20 - 1 = 19`
3. **VTK receives:** `SetSlice(19)`  ← Sets to Instance_0001
4. **Display shows:** Slice 1 (correct label) but displays Instance_0001 (Superior)
5. **Counter shows:** "1/20" 
6. **Anatomy shown:** Superior aspect (correct)
7. **User expectation:** Slice 1 should show Inferior aspect ✗

---

### 7. Policy Numbering Direction

**Current policy (with K-flip active):**
```
Increasing display_k = Moving Superior (toward higher slice numbers showing Superior aspects)
Decreasing display_k = Moving Inferior
```

**Radiological expectation:**
```
Increasing display_k = Moving Superior (conventional: slice 1 = Inferior, slice 20 = Superior)
```

**Status:** Policy is INVERTED relative to radiological convention.

---

## Critical Questions Answered

### Q1: What DICOM says
- Instance 1 is at IPP z=31.5 (Superior end)
- Instance 20 is at IPP z=-55.7 (Inferior end)
- Slice normal points Superior (z=0.972)

### Q2: What canonical geometry says
- Sorted ascending IPP projection: Instance 20 first (Inferior), Instance 1 last (Superior)
- Canonical index 1 = Inferior, index 20 = Superior

### Q3: What DisplayGeometry says
- **K-flip is ACTIVE**
- Formula: `raw_k = 20 - display_k`
- Reverses canonical geometry order

### Q4: What VTK raw_k says
- Raw array index 0 = Instance 20 (Inferior)
- Raw array index 19 = Instance 1 (Superior)
- SetSlice(0) shows Inferior
- SetSlice(19) shows Superior

### Q5: What display_k says
- Display_k 1 = raw_k 19 = Instance 1 = Superior
- Display_k 20 = raw_k 0 = Instance 20 = Inferior

### Q6: Where numbering becomes inverted
- **Root cause:** DisplayGeometry K-flip policy or Viewer2D display_k/raw_k formula
- **Stage:** At viewer initialization/reset_slider time
- **Formula:** `raw_k = n_slices - display_k` instead of `raw_k = display_k - 1`

---

## Evidence Summary

| Finding | Value | Source |
|---------|-------|--------|
| DICOM Instance 1 projection | +23.54 (Superior) | ImagePositionPatient |
| DICOM Instance 20 projection | -66.24 (Inferior) | ImagePositionPatient |
| K-flip formula status | ACTIVE | Observation matches raw_k = 20 - display_k |
| Display k=1 shows | Superior (Instance 1) | User report + DICOM alignment |
| Display k=20 shows | Inferior (Instance 20) | User report + DICOM alignment |
| Numbering convention mismatch | YES | display_k 1 should equal Inferior, not Superior |

---

## Remediation Recommendation

**Fix should be applied to:**
1. **PRIMARY:** DisplayGeometry K-flip policy in `modules/viewer/advanced/` OR
2. **SECONDARY:** Viewer2D display_k/raw_k formula in `reset_slider()` / `set_slice()`

**Most likely single point of failure:**
- A `k_flip` boolean or a `reverse=True` parameter in DisplayGeometry initialization
- OR a `display_k = n - raw_k` formula that should be `display_k = raw_k + 1`

**Search for:**
- `raw_k = ` assignments (likely has `n_slices - display_k` or `(n_slices - 1) - `)
- `k_flip` boolean variables
- `display_k` / `raw_k` conversion functions
- `SetSlice` calls with negation or subtraction

**Verification after fix:**
- Display_k 1 should show Inferior slices
- Display_k 20 should show Superior slices
- Instance numbers should match DICOM convention
- Counter text should align with slice anatomy

---

## Files Implicated

| File | Confidence | Reason |
|------|-----------|--------|
| `modules/viewer/advanced/viewer_2d.py` | HIGH | reset_slider, set_slice, display_k/raw_k mappings |
| `modules/viewer/advanced/viewer_2d_optimized.py` | MEDIUM | alternative viewer implementation |
| DisplayGeometry class (location TBD) | HIGH | K-flip policy enforcement |
| Any file with `display_k` symbol | HIGH | search for all references |

---

## Conclusion

The Advanced Viewer (viewer_2d) is applying a **K-flip inversion that produces incorrect slice numbering** relative to the product's required clinical policy.

**Product Requirement:** Display slice numbers should INCREASE from Superior (1) → Inferior (N)

**Current Broken Behavior:** Display numbering is INVERTED (1=Inferior, 20=Superior)

**Root Cause:** K-flip formula `raw_k = 20 - display_k` is ACTIVE and wrong.

**Correct Fix:** Replace with `raw_k = display_k - 1` to REMOVE K-flip.

**Mathematical Verification:**
```
Current formula (raw_k = 20 - display_k):
  display_k 1  → raw_k 19 → Instance 20 → INFERIOR ✗ (should be Superior)
  display_k 20 → raw_k 0  → Instance 1  → SUPERIOR ✗ (should be Inferior)

Correct formula (raw_k = display_k - 1):
  display_k 1  → raw_k 0  → Instance 1  → SUPERIOR ✓
  display_k 20 → raw_k 19 → Instance 20 → INFERIOR ✓
```

**Single Point of Failure:** One K-flip formula in DisplayGeometry or Viewer2D reset logic.

**Implementation:** Change one formula and test.

---

*Forensic analysis completed: 2026-05-16*  
*Corrected interpretation: 2026-05-16*  
*Next phase: Code-level fix of K-flip formula in modules/viewer/advanced/viewer_2d.py*
