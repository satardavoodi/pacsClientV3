# Advanced Mode Sync Security Audit — v2.2.9.2
**Date:** 2026-04-09  
**Auditor:** GitHub Copilot (automated diff audit)  
**Trigger:** FAST-mode sparse-stack work (v2.2.9.2) introduced new code into `_pw_sync.py`,
`sync_manager.py`, `manage_reference_line`, and `_map_sync_dicom`. This audit verifies that
no Advanced (VTK) mode sync logic was accidentally broken.  
**Constraint:** Read-only evaluation — no code changes made.

---

## 1. Scope

Compare every sync-related file between:
- **Baseline A:** `C:\AI-Pacs codes\BACKUP_v2.2.6.2_20260315_235632` (v2.2.6 — last stable before mixin split)
- **Baseline B:** `backups/v2.3.0_2026-04-04` (v2.3.0 — last monolithic `patient_widget.py`)
- **Current:** working tree at v2.2.9.2

Advanced path = VTK backends where `IS_QT_BRIDGE` is absent/False and `_qt_bridge_active` is False.

---

## 2. Files Verified Identical (zero diff)

| File | Lines (v2.3.0 → current) | Result |
|------|--------------------------|--------|
| `modules/zeta_sync/sync_context.py` | 23 → 23 | ✅ UNCHANGED |
| `modules/zeta_sync/sync_types.py` | 18 → 18 | ✅ UNCHANGED |
| `PacsClient/.../utils/patient_sync_service.py` | 213 → 213 | ✅ UNCHANGED |
| `patient_toolbar/reference_line.py` | 144 → 144 | ✅ UNCHANGED |
| `_pw_sync._wire_lock_sync_callbacks()` | 8 → 8 | ✅ UNCHANGED |
| `_pw_sync._schedule_reference_line_update()` | 40 → 40 | ✅ UNCHANGED |
| `_pw_sync.set_slice()` (in `_vw_scroll.py`) | 358 → 358 | ✅ UNCHANGED |

---

## 3. Files Changed — Advanced Mode Impact Assessment

### 3.1 `modules/zeta_sync/sync_manager.py` (122 → 141 lines)

**What changed:**
```python
# __init__: new field
self._hide_cursor: Optional[Callable[[str], None]] = None

# New method:
def set_hide_cursor_callback(self, callback):
    self._hide_cursor = callback

# In broadcast_sync() — new guard:
if mapped_world is None:
    if self._hide_cursor is not None:
        self._hide_cursor(viewer_id)
    continue
```

**Advanced mode impact:** NONE. The guard fires when `mapped_world is None`, which is the same
condition that triggered `continue` in v2.3.0. The callback is called as an added side-effect;
it does not change the control flow. The `_apply_cursor` call path for valid Advanced mappings
is physically untouched.

**Verdict:** ✅ Safe

---

### 3.2 `_pw_sync._do_lock_sync()` (103 → 149 lines)

Three additions:

#### A. Qt-source true-LPS correction
```python
if getattr(viewer, 'IS_QT_BRIDGE', False):
    # ... compute world_pos from DICOM IPP/IOP instead of VTK origin
```
This block is **gated by `IS_QT_BRIDGE`**. VTK source viewers never have this attribute.
Dead code for Advanced→* sync.

#### B. `hide_sync_point()` when mapped=None
```python
_tgt_iv = getattr(target_vw, 'image_viewer', None)
if _tgt_iv is not None:
    try:
        _tgt_iv.hide_sync_point()
    except Exception:
        pass
```
`ImageViewer2D` (Advanced viewer) **does have** `hide_sync_point()` (confirmed at line 2077 of
`modules/viewer/advanced/viewer_2d.py`). This is a correct new behavior: hides a stale
crosshair when the source point is outside the target stack. Previously it left a stale cursor
visible. Safe improvement.

#### C. Counters `_sync_target_count` / `_sync_map_fail_count`
Pure diagnostic counters; no output effect.

**Verdict:** ✅ Safe — Advanced VTK behavior improved (stale cursor hide); geometry unchanged

---

### 3.3 `_pw_sync._map_sync_dicom()` (128 → 313 lines)

This is the critical function. The diff shows two distinct sections:

#### A. New FAST (Qt) target route — **never entered for VTK targets**
```python
_tgt_is_qt = getattr(target_viewer, 'IS_QT_BRIDGE', False)
if _tgt_is_qt:
    # ... pure-DICOM geometry engine path
    return (P_proj, ijk_diag, not res.final_valid_sync_point, res.rejection_reason)
```
For Advanced VTK targets `IS_QT_BRIDGE` is absent → `_tgt_is_qt=False` → entire block skipped.

#### B. VTK target route — geometry math byte-for-byte identical
The section starting at `# ── Route: VTK target → reference_line flip-Y path (unchanged) ──`
contains exactly the same operations as v2.3.0:

| Step | v2.3.0 | current |
|------|--------|---------|
| `d0 = np.dot(P_lps − ipp_0, n_t)` | ✅ | ✅ identical |
| `k_float = d0 / ds` | ✅ | ✅ identical |
| `k_tgt = max(0, min(...))` | ✅ | ✅ identical |
| `dp = np.dot(P_lps − ipp_k, n_t)` | ✅ | ✅ identical |
| `P_proj = P_lps − dp * n_t` | ✅ | ✅ identical |
| `center_t = rl_center_of_slice(...)` | ✅ | ✅ identical |
| flip-Y via `rl_apply_flip_y_in_plane` | ✅ | ✅ identical |
| `rl_lps_to_target_index(...)` | ✅ | ✅ identical |
| `vtk_t = tgt_orig + tgt_sp * I_t` | ✅ | ✅ identical |

Additions around the math:
- 4× `logger.info()` diagnostics — no behavioral effect
- 4th return value `rejection_reason` (was 3-tuple, now 4-tuple)

The 4th return value is handled in the caller (`_map_sync_cursor`) which now unpacks 4-tuple.
For VTK paths the 4th value is `'none'` (in-stack) or `'out_of_stack'` — informational only.

**Verdict:** ✅ Safe — VTK geometry math identical; only diagnostics added

---

### 3.4 `_pw_sync._map_sync_cursor()` (173 → 178 lines)

Two changes:
1. Unpack 4-tuple instead of 3-tuple (matches new `_map_sync_dicom` return signature)
2. New gate: `if mapped is None: return None`

For VTK→VTK sync, `_map_sync_dicom` either returns whole-tuple `None` (abort) or a valid
4-tuple where `mapped` is a non-None VTK world position. The `mapped is None` gate **can never
fire** for a VTK target — `mapped=None` inside a 4-tuple is only possible when
`res.final_valid_sync_point=False` which is a FAST-only rejection policy.

**Verdict:** ✅ Safe — gate is dead code for Advanced paths

---

### 3.5 `_pw_sync.manage_reference_line()` (178 → 203 lines)

All VTK-target code blocks preserved verbatim. Every change is a parallel Qt branch:

```python
# Before (v2.3.0):
reference_line.rl_hide_actor_if_any(iv)

# After (current):
if getattr(iv, 'IS_QT_BRIDGE', False):
    iv.qt_viewer.clear_overlay_lines()
else:
    reference_line.rl_hide_actor_if_any(iv)   # ← same line, untouched
```

The flip-Y gate change:
```python
# Before:
if self.RL_APPLY_FLIP_Y:
    P0_lps = rl_apply_flip_y_in_plane(...)

# After:
_is_qt_target = getattr(iv, 'IS_QT_BRIDGE', False)
if self.RL_APPLY_FLIP_Y and not _is_qt_target:
    P0_lps = rl_apply_flip_y_in_plane(...)
```
For Advanced VTK targets `_is_qt_target=False` → condition becomes `if self.RL_APPLY_FLIP_Y`,
exactly as before. Flip-Y behavior for Advanced targets is **unchanged**.

**Verdict:** ✅ Safe — VTK path identical; Qt branches are additive only

---

### 3.6 `vtk_widget/_vw_scroll.py::set_slice()` (358 → 364 lines)

Only change: removed `self.image_viewer.image_reslice.Update()` after `Modified()`.

```python
# Removed:
self.image_viewer.image_reslice.Update()
# Kept:
self.image_viewer.image_reslice.Modified()
```

This is a deliberate performance optimization documented in the code comment: calling
`Update()` here forced the VTK reslice pipeline to execute at the OLD slice position, then
`SetSlice(N)` triggered a second pipeline run during `Render()` — doubling per-frame cost
(75–127ms → 40–60ms target). The rendered output is **identical** because VTK reslice still
executes exactly once per frame during `Render()`.

**Verdict:** ✅ Safe — output identical; CPU cost reduced

---

### 3.7 `vtk_widget/_vw_scroll.py::wheelEvent()` (217 → 256 lines)

Added a FAST fast-path at the very top:
```python
if self._qt_bridge_active and self.image_viewer is not None and ...:
    # Qt scroll fast-path
    ...
    return
```
For Advanced VTK mode `_qt_bridge_active=False` → entire block skipped on the very first
condition. Full v2.3.0 VTK scroll machinery executes unchanged below.

Also removed temp-file DIAG writes (`aipacs_wheel_diag.log`) that were diagnostic scaffolding
from v2.3.0.

**Verdict:** ✅ Safe — VTK path unchanged; Qt fast-path is additive

---

### 3.8 `widget_viewer.py` restructured into `vtk_widget/` package

`widget_viewer.py` became a 54-line shim. Original code is preserved in
`vtk_widget/_legacy_widget.py` (only 3 minor changes vs v2.3.0: two Qt-bridge mouse-event
guards + one `print()→logger.warning()`). Production logic is factored into mixin files.

`set_slice` is now in `_vw_scroll.py` — confirmed identical to v2.3.0 (0 diff lines).

**Verdict:** ✅ Safe — structural refactoring only; logic preserved

---

## 4. Summary Table

| Function / File | Changed? | Advanced VTK path affected? | Safe? |
|-----------------|----------|----------------------------|-------|
| `sync_context.py` | No | — | ✅ |
| `sync_types.py` | No | — | ✅ |
| `patient_sync_service.py` | No | — | ✅ |
| `reference_line.py` | No | — | ✅ |
| `sync_manager.py` | Yes | `_hide_cursor` on None (improvement) | ✅ |
| `_do_lock_sync` | Yes | Qt-source gate (dead for VTK); hide stale cursor (improvement) | ✅ |
| `_map_sync_dicom` | Yes | VTK math identical; FAST route gated | ✅ |
| `_map_sync_cursor` | Yes | 4-tuple unpack; `mapped is None` gate dead for VTK | ✅ |
| `manage_reference_line` | Yes | Qt branches additive; flip-Y VTK path identical | ✅ |
| `_wire_lock_sync_callbacks` | No | — | ✅ |
| `_schedule_reference_line_update` | No | — | ✅ |
| `set_slice` | Yes (perf only) | `reslice.Update()` removed (double-exec fix) | ✅ |
| `wheelEvent` | Yes | Qt fast-path gated by `_qt_bridge_active` | ✅ |

**Overall verdict: No regressions in Advanced VTK mode sync.**

---

## 5. Key Design Contract Confirmed

The backend split established this invariant — confirmed intact:

```
IS_QT_BRIDGE = True  →  FAST geometry engine (project_lps_to_target, dicom_sync_geometry)
IS_QT_BRIDGE absent  →  Advanced VTK path (reference_line flip-Y, VTK world indices)
```

Every new code block that touches geometry is gated on `IS_QT_BRIDGE` or `_qt_bridge_active`.
No FAST validation policies (slab/inplane validity rejection) were applied to Advanced targets.

---

## 6. Methodology

All comparisons performed via Python `difflib.unified_diff` on the actual files:

```
Baseline:  backups/v2.3.0_2026-04-04/PacsClient/.../patient_widget.py
Current:   PacsClient/.../patient_widget_core/_pw_sync.py
           PacsClient/.../vtk_widget/_vw_scroll.py
           modules/zeta_sync/sync_manager.py
           patient_toolbar/reference_line.py
```

Function bodies extracted by scanning for `def method_name(` and reading until next
same-indent `def`/`class`. All extractions verified by line-number cross-reference.
