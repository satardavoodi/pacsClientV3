# AIPacs Release Notes (Consolidated)

**Current Stable Version:** v2.2.6.3  
**Release Date:** 2026-03-17  
**Branch:** main  

---

## v2.2.6.3 — GitHub Push / Package Metadata Alignment (2026-03-17)

### Summary

This release packages the current working changes for GitHub publication under **v2.2.6.3** and aligns the visible application/build/package metadata to the same version.

### Version Alignment
- Updated application version in `main.py`
- Updated package version in `pyproject.toml`
- Updated Nuitka product version in `build_nuitka.py`
- Updated plugin package manifest versions under `builder/plugin package/packages/**`
- Updated consolidated release notes to reflect `v2.2.6.3`

### Release Intent
- Publish current `main` branch state to GitHub as **`v2.2.6.3`**
- Keep package feed and module manifests synchronized with the tagged application version

---

## v2.2.6 — Stable Release (2026-03-15)

### Critical Bug Fix: Wheel Scroll Freeze

**Symptom:** After using stack drag (left mouse), switching to wheel scroll caused the image to freeze — scrollbar moved but image stayed fixed. Neither scroll method worked after that.

**Root Cause:** The `wheelEvent` performance optimization (v2.2.3.4.0) called `reslice.SetInterpolationModeToNearestNeighbor()` + `reslice.Modified()` to degrade quality during fast scroll. However, the `vtkImageReslice` carries a non-identity direction-matrix transform (Y-flip from `convert_itk2vtk`). Dirtying the reslice caused VTK's `UpdateDisplayExtent()` to compute a wrong output extent, collapsing the slice range (e.g. `(0,24)` → `(14,14)`, `data_z` → 1). All subsequent `SetSlice()` calls were clamped to that single slice.

**Fix:** Disabled NN interpolation degradation for ALL backends (`_skip_nn_degrade = True`). Made `_restore_reslice_quality()` a no-op. The performance gain from NN was negligible (<1ms) compared to the catastrophic freeze it caused.

**Files Changed:**
- `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` — `wheelEvent`, `_restore_reslice_quality`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` — study path exists() guard

### Other Fixes
- **Study path corruption:** Added `exists()` check before overwriting `import_folder_path` with stale legacy `source\` path from metadata
- **Post-scroll sync render:** Added `_post_scroll_sync_render()` one-shot callback to force VTK + annotation sync after scroll settles

### New Documentation
- `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md` — Complete Advanced vs Fast backend pipeline reference
- Updated `docs/pipelines/viewer-pipeline.md` with reslice corruption warning

### GPU / Software OpenGL
- Verified: GPU detection (`resolve_graphics_profile`) and Software OpenGL fallback (`build_windows_graphics_environment`) remain fully functional
- Both modes produce correct viewer rendering and scroll behavior

### Rule Added
> **CRITICAL:** Never call `reslice.SetInterpolationMode*()` or `reslice.Modified()` during interactive scroll. See `VIEWER_BACKENDS_REFERENCE.md §4.6`.

---

## v2.2.3.4.0 — Performance Sprint (2026-02-27)

**Commit:** `5215a89`

## Summary
This consolidated release note covers the performance optimization sprint from v2.2.3.0 through v2.2.3.4.0. The primary focus was eliminating scroll lag during Mode B (active download) and Mode A (post-download) on software OpenGL renderers.

## Highlights (v2.2.3.4.0)

### Scroll Performance (Mode B — during download)
- **GIL contention eliminated:** DL_WARMUP moved to separate process with own GIL (v2.2.3.2.3). `queue_p95_ms` dropped from 200–510ms → **0.00ms**.
- **Per-frame overhead reduced:** Camera zoom save/restore, interactor style update, and Lock Sync skipped during wheel scroll (v2.2.3.4.0). Saves 4–6ms per frame.
- **Subprocess priority:** IDLE_PRIORITY_CLASS for warmup subprocess (v2.2.3.4.0). Eliminates memory-bus contention during scroll.
- **Reference line optimization:** Round-robin single-target repaint (v2.2.3.3.7). Caps ref-line blocking to ~20ms per tick.
- **GC suppression hardened:** 2000ms re-enable timer + elevated thresholds kept (v2.2.3.3.2). Eliminates 660ms periodic lag.

### Scroll Performance (Mode A — no download)
- **Adaptive throttle:** Replaced debounce with adaptive frame-gap throttle (v2.2.3.2.8). ~2x frame rate improvement.
- **VTK render pipeline:** FXAA off, MSAA disabled, redundant color_mapper.Update() skipped (v2.2.3.2.5).
- **Stale-event drain:** Skip render for events queued >500ms, render final position once (v2.2.3.2.1).

### Series Load Performance
- **Parallel pydicom:** Instance create from 4.3s → 0.8s for 330-file CT (v2.2.3.1.9).
- **Cast-once filter:** ITK filter 423ms → 151ms for MR 20sl (v2.2.3.1.6).
- **Download DB insert:** batch_insert from 2217ms → 326ms (v2.2.3.2.0).

## Version History (v2.2.3.x)

| Version | Commit | Key Change |
|---|---|---|
| v2.2.3.4.0 | `5215a89` | Scroll fast-path: skip camera/style/locksync during wheel scroll; subprocess IDLE priority |
| v2.2.3.3.9 | `af11baf` | Reduce Mode B subprocess contention: ITK 2→1 thread, defer poll, tighten notify |
| v2.2.3.3.8 | `125c00a` | Fix size-mismatch detection for incomplete downloads |
| v2.2.3.3.7 | `f6c4dda` | Round-robin reference line repaint |
| v2.2.3.3.6 | `f90b608` | Eliminate ref-line paint blocking from scroll loop |
| v2.2.3.3.5 | `6b18b94` | Real-time reference line sync (dual-timer) |
| v2.2.3.3.4 | `5b3b77c` | Reference lines sync with stack drag + lock sync |
| v2.2.3.3.3 | `1f2cd36` | Debounce reference line updates during scroll |
| v2.2.3.3.2 | `edfff7f` | Eliminate 660ms periodic GC lag (PC B) |
| v2.2.3.3.1 | `0382270` | Cache os.getenv; event-loop bypass for timer congestion |
| v2.2.3.3.0 | `66914e0` | Strengthen GC suppression for heavy volumes |
| v2.2.3.2.9 | `495a61a` | GC suppression during scroll + throttle booster |
| v2.2.3.2.8 | `e34c6b1` | Adaptive throttle replaces debounce (~2x fps) |
| v2.2.3.2.7 | `8fb6629` | Fix infinite stale-drain loop |
| v2.2.3.2.5/6 | `34b559b` | Render pipeline + signal coalescing |
| v2.2.3.2.2 | `ff0d4b1` | DL_WARMUP speed improvements |
| v2.2.3.2.1 | `9724dea` | Stale-event fast-drain guard |
| v2.2.3.2.0 | `3cd1a09` | Parallel pydicom + adaptive ITK + BELOW_NORMAL priority |

## Known Issues
- First-series load still runs in-process (~2.4s via asyncio.to_thread)
- `update_corners_actors()` updates 6 VTK text actors per scroll (only 2 change)
- `viewer_db_read` 38–88ms on series load (could be cached)

## Documentation
- Performance status: `docs/PERFORMANCE_STATUS.md`
- Detailed metrics: `docs/METRICS_TRACKING_v2.2.3.x.md`
- Decision log: `docs/PERFORMANCE_DECISION_LOG_2026-02-27.md`
- Cross-PC workflow: `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`
