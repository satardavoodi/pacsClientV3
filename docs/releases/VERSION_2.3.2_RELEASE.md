# v2.3.2 — H13 Investigation Resolution + FAST Stability

**Release date:** 2026-04-14  
**Version tag:** v2.3.2  
**Type:** Stability Release (H13 mitigation + pre-VTK-replacement snapshot)

---

## Summary

This release resolves the H13 FAST viewer crash investigation and prepares the codebase for VTK replacement in FAST mode. All H13 diagnostic infrastructure, mitigation fixes, and documentation are frozen at this point.

## Key changes

### H13 Investigation — Root Cause Identified and Mitigated

**Root cause:** VTK 9.6 PyPI wheel is NOT built with `VTK_PYTHON_FULL_THREADSAFE=ON`. Idle worker threads in `PyDicomLazyVolume._worker_loop` corrupt GIL state during VTK C++ `Render()`/`SetSlice()` calls, producing `Fatal Python error: PyThreadState_Get: GIL not held`.

**Evidence (Logs 18-25):**
- T4 (render gate): eliminated write/render overlap → crash persisted
- T5 (keep-alive): no grow events → crash persisted → H13-C weakened
- T3 (deep copy): broke shared-memory coupling → crash persisted
- Final finding: ALL crashes occurred with 4 workers idle, zero writes in flight, overlap_count=0

**H13-FIX (worker auto-shutdown):**
- `_worker_loop` exits when `np.all(self._loaded[:self.slice_count])` is True
- Log marker: `[H13-AUTOEXIT]`
- `_revive_workers_if_needed()` spawns fresh workers when `grow()` adds new slices
- Log marker: `[H13-REVIVE]`
- Eliminates idle Python threads during VTK render operations

### Observability Improvements

- **Silent suppression eliminated:** 4 render-path exception sites elevated from `logger.debug` to `logger.warning` with `[H13-S5]` tags
- **Qt boundary guards:** wrapper+impl pattern on `set_slice`, `apply_default_window_level`, `update_corners_actors`, `_call_image_viewer_set_slice`
- **Per-render markers:** `[H13-T3-RENDER]` for deep-copy diagnostic
- All H13 probes (P1-P5) and toggles (T3-T6) retained for diagnostic capability

### Documentation

- `H13_WORKING_DOCUMENT.md` updated with §17 (Phase 3 results, root cause, fix, final hypothesis ranking)
- `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md` updated with resolution status and strategic direction

## Files modified

| File | Change |
|------|--------|
| `modules/viewer/fast/pydicom_lazy_volume.py` | H13-FIX: worker auto-shutdown + auto-revive on grow() |
| `modules/viewer/fast/_decode_guard.py` | T3 deep-copy toggle, build-info log |
| `modules/viewer/advanced/viewer_2d.py` | Qt boundary guards (wrapper+impl pattern) |
| `PacsClient/.../vtk_widget/_vw_backend.py` | Silent suppression elimination, P5 enhancements |
| `PacsClient/.../vtk_widget/_vw_scroll.py` | Silent suppression elimination, Qt boundary widening |
| `docs/stability/H13_WORKING_DOCUMENT.md` | Full experiment history through resolution |
| `docs/plans/stability/H13_FOCUSED_RECOVERY_PLAN.md` | Resolution status and strategic direction |

## Test status

- 69 tests passing (45 pipeline + 24 combined)
- All pre-existing DM, network, database, smoke tests unaffected

## Strategic note

This version serves as the **rollback point** before the FAST-mode VTK replacement initiative. The codebase already contains a VTK-free Qt rendering path (`pydicom_qt` backend: `QtSliceViewer`, `Lightweight2DPipeline`, `QtViewerBridge`) that will become the exclusive FAST renderer in subsequent versions.
