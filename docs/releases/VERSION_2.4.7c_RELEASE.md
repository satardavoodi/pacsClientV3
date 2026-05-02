# AIPacs v2.4.7c Release Notes

**Version:** v2.4.7c  
**Release Date:** 2026-05-02  
**Branch:** `matab-conservative`  
**Theme:** Conservative FAST cache growth and slice-state stability

## Summary

v2.4.7c is a conservative FAST-mode cache stabilization release.  It changes
progressive download growth from a rebuild-oriented path into an additive path
that preserves existing cached data where slice identity is still valid.

The release also documents the remaining stack-drag jitter mechanism: small
one-slice visual twitches during fast stacking are most likely caused by the
drag-time surrogate-frame policy at cache boundaries, not by `setSlice` or by
the additive cache update itself.

## Key Changes

- **Additive FAST cache growth** — `Lightweight2DPipeline.refresh_file_list()`
  now preserves compatible pixel, frame, and filter-state cache entries when
  progressive downloads add new files.
- **Slice-identity remapping** — because FAST caches are index-keyed for speed,
  growth now remaps preserved cache entries by DICOM file path after sorting.
  This prevents old cached pixels from being attached to the wrong slice if a
  newly downloaded file sorts before an existing slice.
- **Stable current slice during growth** — `QtViewerBridge.grow()` updates slice
  count and mock VTK dimensions without treating growth as a navigation event.
  The current slice remains stable unless user interaction or explicit sync
  navigation changes it.
- **Same-series Qt refresh guard** — same-slice refresh no longer forces an
  unnecessary `set_slice()` and default W/L application.
- **Geometry metadata cache** — FAST now caches per-slice basis vectors, stack
  normal, and slice positions for repeated sync/reference-line geometry work.
- **Bounded active-viewer cache capacity** — default adaptive cache max increased
  from `384` to `512`, while explicit environment/custom cache sizes still win.
- **Defensive diagnostics** — diagnostic timing logging now tolerates lightweight
  test/dry-run logger stubs, and prefetch guards tolerate partially constructed
  test pipeline instances.

## Stacking Jitter Analysis

Observed symptom:
- During stack-drag, the image can briefly appear to move one slice backward or
  forward, especially near a cache edge or during download/scroll overlap.

Likely source:
- The FAST drag path intentionally allows surrogate frames.  If the requested
  target slice is not fully cached yet, the pipeline may show the nearest cached
  frame or nearest cached pixel while the exact target is warmed or decoded.
- The slider and logical `slice_index` can already be at the requested slice,
  while the displayed pixels briefly come from a nearby cached slice.  That
  visual mismatch is perceived as a small jitter.

Less likely sources after v2.4.7c:
- `setSlice`: growth no longer calls `set_slice()` for same-slice additive
  updates.
- Additive cache update: preserved caches are remapped by file identity, so
  growth itself should not attach old pixels to the wrong slice.
- Cache limit transition: LRU pruning can expose cache-edge misses, but the
  visible twitch comes from surrogate substitution after the miss, not from
  pruning alone.

Handling policy:
- Keep wheel scrolling exact; wheel precision browsing never uses surrogate
  frames.
- Keep drag surrogate support for responsiveness, but treat surrogate distance
  and repeat count as the jitter control knobs.
- If live validation still shows objectionable jitter, the next conservative
  change should be to tighten drag surrogate admission near cache edges, for
  example by allowing only distance-1 surrogates by default and forcing exact
  decode after the first repeated surrogate.  This should be guarded by tests
  and KPIs rather than changed blindly.

## Verification

Validated with internal tests:

- `python -m py_compile modules/viewer/fast/lightweight_2d_pipeline.py modules/viewer/fast/qt_viewer_bridge.py PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py PacsClient/utils/diagnostic_logging.py tests/viewer/test_fast_viewer_pipeline.py`
- `.venv\Scripts\python.exe -m pytest tests\viewer\test_fast_viewer_pipeline.py tests\viewer\test_fast_viewer_reset_slider.py`
- `.venv\Scripts\python.exe -m pytest tests\viewer\test_dragdrop_progressive.py`
- `.venv\Scripts\python.exe -m pytest tests\fast\test_sync_reference_line_geometry.py tests\fast\test_sync_sparse_stack.py tests\fast_viewer\test_reference_lines.py tests\fast_viewer\test_geometry_coordinates.py`

Results:
- FAST pipeline/reset-slider: `166 passed`
- Drag/drop progressive: `20 passed`
- Geometry/reference-line subset: `119 passed`

## Backup

A local source backup for this branch should be created as:

- `backups/v2.4.7c_conservative_2026-05-02.zip`
