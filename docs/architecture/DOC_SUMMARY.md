# Architecture Reverse-Engineering Summary (Read-Only)

## What was done

Completed read-only reverse engineering of viewer architecture with direct code tracing (no fixes, no edits to runtime code).

Produced documents:
- `docs/viewer/FAST_vs_ADVANCED_ARCHITECTURE.md`
- `docs/viewer/FAST_PIPELINE_DETAILED.md`
- `docs/viewer/ADVANCED_PIPELINE_DETAILED.md`
- `docs/viewer/SHARED_COMPONENTS.md`
- `T6_PREPARATION.md`

## Key findings

1. FAST is dual-mode in rendering reality:
   - `pydicom_qt` => Qt renderer (`QtSliceViewer`/QPainter).
   - `pydicom_2d` => VTK renderer (`ImageViewer2D.Render`) with lazy pydicom-backed data.

2. ADVANCED uses VTK/SimpleITK full pipeline and VTK render ownership.

3. Backend routing is centrally controlled by `resolve_viewer_backend(...)` + metadata completeness/fallback flags.

4. The critical lazy callback TOCTOU-sensitive zone is `VTKWidget._on_lazy_slice_ready_impl(...)` in `_vw_backend.py`.

## Contradictions matrix (docs vs code)

- Claim: FAST is globally VTK-free.
  - Code: true only for `pydicom_qt`; false for `pydicom_2d`.

- Claim: backend name alone predicts render engine.
  - Code: runtime flags (`_active_backend`, `_qt_bridge_active`, lazy loader presence) determine real render path.

## Evidence anchors

- Backend resolver: `modules/viewer/viewer_backend_config.py`
- Loader behavior: `PacsClient/pacs/patient_tab/utils/image_io.py`
- Switch/load controller: `_vc_load.py`, `_vc_switch.py`
- FAST lazy callback + guard: `_vw_backend.py`
- Scroll/set_slice routing: `_vw_scroll.py`
- Series startup and Qt bridge branching: `_vw_series.py`
- Advanced render implementation: `modules/viewer/advanced/viewer_2d.py`
- Qt bridge/render implementation: `modules/viewer/fast/qt_viewer_bridge.py`, `qt_slice_viewer.py`
- Lazy volume + mark/modify behavior: `modules/viewer/fast/pydicom_lazy_volume.py`

## Constraints respected

- No runtime code changed.
- No bugfixes implemented.
- Output is analysis/documentation only.
