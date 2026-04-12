# T6 Preparation (No-Fix, Read-Only)

## Objective

Prepare precise insertion guidance for a future T6 guard change around lazy-slice callback race handling, without implementing code changes now.

## Exact target function

- File: `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py`
- Function: `VTKWidget._on_lazy_slice_ready_impl(self, slice_index, decode_ms, cache_hit)`

## Why this is the T6 insertion zone

This function is the convergence point where:
1. decoded slice-ready signals arrive asynchronously,
2. stale-frame/generation guards are evaluated,
3. render is triggered (`mark_vtk_modified` + `set_slice` call chain).

Any TOCTOU protection for late/stale decode completion must be placed at this boundary (just before entering render chain).

## Current guard logic present

Before render path, it checks:
- backend still lazy backend (`_active_backend`)
- loader still present (`_lazy_loader`)
- stale-frame gate via `should_render_ready_slice(...)` with:
  - `ready_slice`
  - `requested_slice = self._lazy_requested_slice`
  - `current_slice`/`guard_current_slice`
  - `ready_generation = self._lazy_requested_generation`
  - `current_generation = self._series_generation_id`

## Candidate re-check signals for T6

Per request, likely future checks to evaluate:
- `_current_slice_index` equivalent (effective current requested/visible target)
- `_lazy_requested_slice`

Suggested placement for future patch (not applied now):
- immediately before `h13_check_overlap_before_render(...)` and render-chain entry
- after stale-frame gate but before `mark_vtk_modified()` + `_call_image_viewer_set_slice(...)`

## Related paths to keep consistent

- Scroll request path:
  - `_vw_scroll.py` -> `set_slice(...)`
  - sets/updates `_lazy_requested_slice` and generation-related state.
- Loader growth/progressive path:
  - `_vc_progressive.py` (`_grow_progressive_fast`, completion verify/sweep)

## Non-goals in this prep

- No behavior changes.
- No lock strategy changes.
- No timing constant changes.
- No render-path rewiring.

## Quick validation checklist for future T6 implementation

1. callback still respects generation boundary.
2. no regressions in fast scroll responsiveness.
3. no frozen-image regressions for `pydicom_2d` and `pydicom_qt`.
4. progressive completion still reaches final slice count.
5. verify against existing viewer/download stress tests.
