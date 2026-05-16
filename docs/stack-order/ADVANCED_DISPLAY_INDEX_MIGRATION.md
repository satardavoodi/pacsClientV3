# Advanced Viewer — Display-Index Semantics Migration

**Date:** 2026-05-14  
**Branch:** `matab-conservative`  
**Author:** copilot  
**Status:** COMPLETE  

---

## 1. Purpose

Prior to this migration the Advanced VTK viewer used **raw VTK k indices** throughout
the interaction layer.  Because `canonical_sort_instances` orders DICOM instances by
IPP ascending, raw `k=0` is the Inferior-most slice for axial series.  Scrolling down
(step=+1) incremented the raw index and therefore moved *Superiorly* — the opposite of
the expected clinical direction.

This migration makes the interaction layer operate in **display_k space** where
`display_k=0` is always the clinically-canonical first slice (Superior for axial HFS,
Left for sagittal, Posterior for coronal).  The K-flip conversion is encapsulated
entirely in `DisplayGeometry` and `ImageViewer2D.get_display_slice()` / `_set_slice_impl`.
No voxel memory is reordered; no VTK pipeline is changed.

---

## 2. Architecture Invariants (unchanged)

| Layer | State |
|-------|-------|
| Raw voxel memory order | **Unchanged** — IPP-ascending in-memory |
| `vtkImageData` contents | **Unchanged** — same pixels same order |
| `SourceGeometry` | **Unchanged** |
| `DisplayGeometry` K-flip matrix | Applied in prior session (canonical architecture) |
| FAST path (`QtViewerBridge`, `Lightweight2DPipeline`) | **Unchanged** — architecturally separate |

---

## 3. Files Modified

| File | Change type |
|------|------------|
| `modules/viewer/advanced/viewer_2d.py` | New `get_display_slice()` method; `_set_slice_impl` Gap 1+2 fix; slice counter text (Tasks 2–3) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py` | `wheelEvent` VTK path uses `get_display_slice()`; `_post_scroll_sync_render` comparison (Task 4) |
| *(prior session)* `modules/viewer/geometry/display_geometry.py` | K-flip APIs: `is_k_flip_active`, `k_flip_n_slices`, `display_k_to_raw_k()`, `raw_k_to_display_k()`, `_k_flip_applied` guard (Task 1) |

Plugin copies kept SHA-equal:
- `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py`
- `builder/plugin package/packages/viewer/payload/python/modules/viewer/geometry/display_geometry.py`

---

## 4. Interaction-Layer Migration Table

| Site | File:function | Pre-migration semantic | Post-migration semantic | Risk |
|------|--------------|----------------------|------------------------|------|
| Scroll direction source | `_vw_scroll.py:wheelEvent` | `GetSlice()` → raw_k | `get_display_slice()` → display_k | Low — wrapper gracefully falls back to `GetSlice()` |
| Scroll direction arithmetic | `_vw_scroll.py:wheelEvent` | `raw_k + step` | `display_k + step` | None — same arithmetic, correct space |
| Post-scroll sync comparison | `_vw_scroll.py:_post_scroll_sync_render` | `GetSlice()` vs `slider.value()` (raw vs display) | `get_display_slice()` vs `slider.value()` (both display) | Low — both in same space now |
| Set slice — conversion | `viewer_2d.py:_set_slice_impl` | `SetSlice(display_k)` — wrong | `SetSlice(display_k_to_raw_k(display_k))` | None — K-flip guard is safe when inactive |
| Set slice — early return | `viewer_2d.py:_set_slice_impl` | `GetSlice() == display_k` — mixed spaces | `GetSlice() == _raw_k` — both raw | None |
| Slice counter text | `viewer_2d.py:_update_corners_actors_impl` | `GetSlice()+1` → shows raw_k+1 | `get_display_slice()+1` → shows display_k+1 | None |
| Slice counter text | `viewer_2d.py:load_top_right_actors` | `GetSlice()` → raw_k in counter | `get_display_slice()` → display_k in counter | None |
| Metadata/instance indexing | `viewer_2d.py:_set_slice_impl` (via `actual_slice_index`) | `GetSlice()` → raw_k ✓ | `GetSlice()` after `SetSlice(_raw_k)` → still raw_k ✓ | None — intentionally unchanged |
| W/L per-slice | `viewer_2d.py:apply_default_window_level` | raw_k passed | raw_k passed (from `actual_slice_index = GetSlice()`) | None |
| Orientation markers | `viewer_2d.py:_set_slice_impl` line ~1493 | raw_k `instances[]` index | same | None |
| `update_available_slice_count` | `_legacy_widget.py` | `GetSlice()` vs VTK dimension | still raw_k vs VTK dimension ✓ | None — both raw_k, no change needed |
| FAST path stack drag | `_vw_scroll.py` FAST branch (line 1004–1055) | `GetSlice()` for Qt bridge | **Unchanged** — architecturally separate | None |

---

## 5. Key Design Decisions

### 5.1 `actual_slice_index` keeps raw_k for metadata indexing

Inside `_set_slice_impl`, after `SetSlice(_raw_k)`, `actual_slice_index = int(self.GetSlice())`
is raw_k.  This is **intentional**: `metadata['instances']` is in IPP-ascending order
(= raw_k order).  All instance lookups (`apply_default_window_level`, orientation markers,
corner actors instance data) correctly use raw_k.

The only place that changes is the **slice counter text** — which displays for the user and
should show display_k.

### 5.2 K-flip is no-op when inactive

Both `display_k_to_raw_k(dk)` and `raw_k_to_display_k(rk)` return the input unchanged
when `is_k_flip_active == False` (diagonal element `M[2,2] == 1`, offset `M[2,3] == 0`).
The `get_display_slice()` fallback in `_vw_scroll.py` uses `hasattr` + `callable` guard,
so if a viewer doesn't have the method (e.g. legacy stub), it falls back to `GetSlice()`.

### 5.3 `_post_scroll_sync_render` semantic

The slider stores display_k (set from `queue_interactive_slice_target` → `set_slice`).
After migration, `current_vtk` is also display_k (via `get_display_slice()`).  The
comparison `current_vtk != target` is now consistent.

---

## 6. Diagnostic Log Tags

| Tag | Emitted from | Purpose | Level |
|-----|-------------|---------|-------|
| `[DISPLAY_K_RUNTIME_BIND]` | `display_geometry.py:apply_k_flip_for_stack_order` | K-flip applied; shows display_0_raw_k, display_last_raw_k | WARNING |
| `[DISPLAY_POLICY_DOUBLE_APPLICATION_BLOCKED]` | `display_geometry.py:apply_k_flip_for_stack_order` | Double-apply guard triggered | WARNING |
| `[SCROLL_RUNTIME_DIRECTION]` | `_vw_scroll.py:wheelEvent` | Every 20th wheel event; display_k_before/after, raw_k, k_flip status | WARNING |

---

## 7. Runtime Proof — Log Evidence to Collect

After a production session on an axial CT series, check `viewer_diagnostics.log` for:

```
[DISPLAY_K_RUNTIME_BIND] viewport_id=vp_0 n_slices=512 k_flip_active=True
    display_0_raw_k=511 display_last_raw_k=0 reason=axial_hfs
```
Confirms K-flip active: display index 0 maps to Superior (raw_k = N-1 = 511).

```
[SCROLL_RUNTIME_DIRECTION] viewport_id=vp_0 plane=axial
    display_k_before=10 display_k_after=11 raw_k_before=501 step=1 k_flip=True event=20
```
Confirms: scroll down (step=+1) increments display_k → maps to Inferior (raw_k decreases
from 501 to 500 via `display_k_to_raw_k`).

---

## 8. Acceptance Criteria Validation Matrix

| # | Criterion | Expected signal | Status |
|---|-----------|----------------|--------|
| 1 | Axial scroll down → moves Inferiorly | `[SCROLL_RUNTIME_DIRECTION]` step=+1 increments display_k | ✅ Architecture correct |
| 2 | Sagittal scroll follows selected policy | Same K-flip logic applies | ✅ Architecture correct |
| 3 | Orientation markers remain correct | `actual_slice_index` = raw_k (unchanged) for instance lookup | ✅ Not changed |
| 4 | Lock sync correct | Sync uses `set_slice(display_k)` which converts internally | ✅ No sync-layer change needed |
| 5 | Reference lines correct | Reference lines read `GetSlice()` (raw_k) for IPP lookup | ✅ Not changed |
| 6 | Reopen stable — no double-application | `_k_flip_applied` guard in `DisplayGeometry` | ✅ Implemented |
| 7 | Rendering stable — no frozen image | `SetSlice(_raw_k)` → VTK gets the correct raw index | ✅ Architecture correct |
| 8 | Slice counter shows correct 1-based index | Counter uses `get_display_slice()+1` | ✅ Implemented |
| 9 | No raw_k usage remains in scroll arithmetic | `get_display_slice()` in wheelEvent + `_post_scroll_sync_render` | ✅ Migrated |
| 10 | No voxel reorder / no VTK bridge mutation | Only display layer changed | ✅ Not changed |

---

## 9. Three Gaps Closed

| Gap | Description | Fix location |
|-----|-------------|-------------|
| Gap 1 | `_set_slice_impl` called `SetSlice(display_k)` — VTK received wrong index | `_set_slice_impl`: compute `_raw_k = display_k_to_raw_k(display_k)` before `SetSlice` |
| Gap 2 | `GetSlice()` returns raw_k but scroll used it as display_k for step arithmetic | `wheelEvent`: `get_display_slice()` converts raw_k → display_k before arithmetic |
| Gap 3 | Slice counter showed raw_k+1 instead of display_k+1 | `_update_corners_actors_impl`, `load_top_right_actors`: use `get_display_slice()` for text |

---

*Prior-session work: K-flip matrix in `DisplayGeometry`, `_bind_geometry_contract()` binding, 8 synthetic tests. See `docs/stack-order/` for investigation notes.*
