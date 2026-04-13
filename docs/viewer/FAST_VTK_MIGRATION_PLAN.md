# FAST Mode VTK Removal — Migration Plan

**Date:** 2026-04-13  
**Version:** v2.3.3  
**Rollback:** v2.3.2 tag + backup dir  
**Prerequisites:** [FAST_RENDERER_EVALUATION.md](FAST_RENDERER_EVALUATION.md), [FAST_VTK_COUPLING_ANALYSIS.md](FAST_VTK_COUPLING_ANALYSIS.md)

---

## Strategy

**Complete the existing `pydicom_qt` path. Do NOT add new dependencies.**

The migration has 4 stages, each independently testable and committable:

```
Stage 1: Make pydicom_qt the exclusive FAST backend (config only)
Stage 2: Remove dead FAST code paths (pydicom_2d elimination)
Stage 3: Lazy-import VTK in shared modules (startup optimization)
Stage 4: Extract FastViewerWidget from VTKWidget (architecture cleanup)
```

Stage 1 alone eliminates the H13 crash class. Stages 2-4 are cleanup/optimization.

---

## Stage 1: Make `pydicom_qt` the Exclusive FAST Backend

**Goal:** Ensure FAST mode never enters VTK rendering code.  
**Risk:** Low — `pydicom_qt` is already the active FAST renderer.  
**Effort:** ~1 hour

### Tasks

1. **Update `viewer_backend_config.py`**
   - In `resolve_viewer_backend()`, remove the `BACKEND_PYDICOM` (lazy VTK) as a valid FAST result
   - FAST mode → always returns `BACKEND_PYDICOM_QT`
   - Advanced mode → always returns `BACKEND_VTK` (unchanged)

2. **Update `config/viewer_backend_settings.json`**
   - Set `"fast_backend": "pydicom_qt"` as default
   - Remove or deprecate `"pydicom_2d"` option

3. **Update `image_io.py` fast path**
   - Ensure `BACKEND_PYDICOM_QT` early exit is the only FAST code path
   - Add warning log if `BACKEND_PYDICOM` is somehow selected

4. **Test**
   - Run existing viewer tests: `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v`
   - Run smoke tests: `python -m pytest tests/smoke/test_import_smoke.py -v`
   - Manual: open patient in FAST mode, verify scroll/W/L/tools work

### Verification

```
✓ Only BACKEND_PYDICOM_QT used in FAST mode
✓ No VTK Render() calls during FAST scroll (check logs)
✓ Progressive display still works
✓ Measurement tools functional
✓ Advanced mode completely unaffected
```

---

## Stage 2: Remove Dead `pydicom_2d` Code Paths

**Goal:** Clean up the lazy VTK hybrid path that caused H13 crashes.  
**Risk:** Low — path is no longer reachable after Stage 1.  
**Effort:** ~2 hours

### Tasks

1. **Mark `pydicom_lazy_volume.py` as Advanced-only**
   - Remove from FAST import paths
   - Keep for any Advanced mode lazy-loading needs (if any)
   - Or: deprecate entirely if Advanced mode uses its own pipeline

2. **Remove `_decode_guard.py` H13 probes**
   - These were diagnostic tools for the VTK GIL crash investigation
   - No longer needed in production
   - Archive to `docs/stability/archived/` if desired

3. **Clean up `_vw_backend.py` BACKEND_PYDICOM branches**
   - Remove or no-op the `BACKEND_PYDICOM` conditional branches
   - These handled lazy VTK image data binding, now dead code

4. **Remove H13-FIX worker auto-shutdown code** (optional)
   - The worker shutdown/revive in `pydicom_lazy_volume.py` (lines 1045-1065, 518-540) was the H13 mitigation
   - If `pydicom_lazy_volume.py` is removed from FAST path, this code is no longer exercised

5. **Test**
   - Run all test suites
   - Verify no import errors

---

## Stage 3: Lazy-Import VTK in Shared Modules

**Goal:** Avoid loading VTK DLLs when only FAST mode is used.  
**Risk:** Medium — import timing changes can have subtle effects.  
**Effort:** ~2 hours

### Tasks

1. **`image_io.py` — lazy VTK import**
   ```python
   # Before (module level):
   import vtkmodules.all as vtk
   
   # After:
   vtk = None  # lazy
   def _ensure_vtk():
       global vtk
       if vtk is None:
           import vtkmodules.all as vtk_mod
           vtk = vtk_mod
   ```
   Call `_ensure_vtk()` only inside non-FAST code paths.

2. **`patient_widget_viewer_controller.py` — remove unused import**
   - Delete `import vtk` (unused in FAST path, confirmed by analysis)

3. **`pydicom_lazy_volume.py` — replace numpy_support**
   ```python
   # Before:
   from vtkmodules.util import numpy_support
   vtk_type = numpy_support.get_vtk_array_type(arr.dtype)
   
   # After:
   _DTYPE_TO_VTK = {np.uint8: 3, np.int16: 4, np.uint16: 5, ...}
   vtk_type = _DTYPE_TO_VTK.get(arr.dtype.type, 3)
   ```

4. **Test**
   - Measure startup time with FAST config (should save ~200ms)
   - Verify Advanced mode still works (VTK loaded on demand)

---

## Stage 4: Extract FastViewerWidget (Architecture)

**Goal:** FAST viewers use a pure QWidget, not QVTKRenderWindowInteractor.  
**Risk:** Medium-High — significant refactoring of widget hierarchy.  
**Effort:** ~4-6 hours

### Tasks

1. **Create `FastViewerWidget(QWidget)`**
   - New file: `PacsClient/pacs/patient_tab/ui/patient_ui/fast_viewer_widget.py`
   - Inherits QWidget (not QVTKRenderWindowInteractor)
   - Contains QtSliceViewer as child widget
   - Implements the subset of VTKWidget API needed by mixins

2. **Extract shared mixin interface**
   - The `_vw_*.py` mixins reference `self.image_viewer`, `self._qt_bridge_active`, `self._active_backend`
   - Define a protocol/ABC that both FastViewerWidget and VTKWidget satisfy

3. **Update `MultiViewerLayoutManager`**
   - Create FastViewerWidget when backend is FAST
   - Create VTKWidget when backend is Advanced

4. **Update cache key system**
   - Replace `vtk_data is not None` checks with `cache_entry is not None`
   - Use metadata-only cache entries for FAST mode

5. **Test**
   - Full regression test on both FAST and Advanced modes
   - Memory profiling (confirm VTK memory not allocated in FAST mode)

### This stage is OPTIONAL for H13 fix — Stage 1 alone eliminates the crash.

---

## Timeline

| Stage | Prerequisite | Can Ship Independently | H13 Impact |
|-------|-------------|----------------------|------------|
| Stage 1 | None | Yes | **Eliminates crash class** |
| Stage 2 | Stage 1 | Yes | Cleanup only |
| Stage 3 | Stage 1 | Yes | ~200ms startup improvement |
| Stage 4 | Stages 1-3 | Yes | Memory reduction, architectural purity |

---

## Rollback Plan

Each stage is a separate commit. Rollback is:
```
git revert <stage-N-commit>
```

Full rollback to pre-migration:
```
git checkout v2.3.2
```

Physical backup available at `backups/v2.3.2_2026-04-13/`.

---

## Success Criteria

After Stage 1:
- [ ] Zero VTK Render() calls during FAST mode scroll (verified by log)
- [ ] H13 crash scenario no longer reproducible
- [ ] All 69 existing tests pass
- [ ] Progressive display works end-to-end
- [ ] Measurement tools functional
- [ ] Advanced mode unchanged

After Stage 4 (full migration):
- [ ] VTK DLLs not loaded in FAST-only sessions
- [ ] Startup time reduced by ~200ms
- [ ] Memory baseline reduced (no unused VTK render window)
- [ ] Module import of `modules/viewer/fast/*` works without VTK installed
