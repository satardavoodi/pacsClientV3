# AIPacs v2.5.0 Release Notes

Date: 2026-05-04
Branch: matab-conservative

## Scope

This release finalizes the Window Level toolbar enhancement by adding a split-button CT preset menu and bundles the runtime repair work needed to keep patient opening and viewer startup stable after the toolbar change.

## Included Changes

### 1. Window Level split-button with CT presets

The Window Level tool now follows the same split-button pattern used by the other toolbar tools.

- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
  - Added a left-side hamburger button next to the existing Window Level action button.
  - Added `_show_wl_presets_dropdown(...)` for CT presets.
  - Presets included: `Lung`, `Abdomen`, `Brain`, `Bone`.
  - Preset selection applies the configured WW/WL values to the active FAST or Advanced viewer target.
  - Styling follows the existing toolbar theme and split-button treatment.

### 2. Toolbar regression repairs from the WL feature work

The WL toolbar work had introduced accidental regressions in the large toolbar manager file. This release keeps only the intended WL feature and the required runtime fixes.

- Restored the microphone timer/state initialization needed during `ToolbarManager` construction so patient tabs can open without the toolbar throwing during setup.
- Restored the `AI Analyze` button click wiring.
- Removed an accidental stray callback inserted into an unrelated import-error path.
- Reverted unrelated Curved MPR drift so the release diff stays focused on the intended toolbar change.

### 3. Release metadata update

- `pyproject.toml` bumped to `2.5.0`.
- `.github/copilot-instructions.md` current stable version banner updated to `v2.5.0`.
- `docs/releases/RELEASE_NOTES.md` updated to point to this release.

## Validation

Validated after the toolbar cleanup:

- `pytest tests/gui/qt/test_main_window_basic.py -q` → passed
- Offscreen `PatientWidget()` construction smoke → passed (`PATIENT_WIDGET_OK`)
- `toolbar_manager.py` static error check → no errors
- Latest May 4 log tail review showed no fresh `ERROR`/`CRITICAL` entries for the current run; only normal viewer/download activity plus a shutdown-time main-thread stall probe entry.

## Notes For Next Changes

- `toolbar_manager.py` is a high-risk file because it combines many unrelated responsibilities. Future edits should use exact local anchors and keep diffs tightly scoped.
- If another toolbar feature is added, prefer extending the split-button helpers already introduced here instead of open-coding one-off button styles.
- For runtime verification, clear or rotate `user_data/logs/*.log` before reproducing a flow so new errors are not mixed with older sessions.

---

# AIPacs v2.5.0 Beta — FAST 2D Cell Separation

Date: 2026-05-05
Branch: beta-version

## Scope

VTK-free viewer cell separation for FAST mode (`BACKEND_PYDICOM_QT`).  In the
previous architecture every viewer cell — even in FAST/Qt mode — allocated a
`QVTKRenderWindowInteractor`, consuming 40–80 MB of GPU memory and 100–400 ms
of initialisation time per cell.  This release replaces the VTK cell with a
lightweight `QWidget` subclass (`QtFastContainer`) in FAST mode while leaving
the Advanced/VTK path completely unchanged.

## Included Changes

### 1. `QtFastContainer` — VTK-free cell widget (`vtk_widget/qt_fast_container.py`)

New file.  Drop-in structural replacement for `VTKWidget` when the active
backend is `BACKEND_PYDICOM_QT`.

- `_NullVtkObject` — null-object stub for `render_window`, `renderer`,
  `interactor`.  All method calls are absorbed (no-op).  Boolean value is
  `False` so `if vtk_widget.render_window:` guards skip their bodies.
- `_NullImageViewer` — minimal stub for `vtk_widget.image_viewer`, covering
  the subset of `ImageViewer2D` attributes reachable in FAST mode.
- `QtFastContainer(QWidget)` — the actual cell widget.  Holds the same
  attribute surface as `VTKWidget` for duck-typed call sites.  `_qt_bridge`
  is wired at series-load time by the existing `_bind_backend_from_metadata`
  path (no changes to the bridge wiring itself).
- Crash-site register C1–C9 covered (all VTK surface attributes present as
  null stubs).
- Eagle Eye guard respected (`current_style = None`, not a stub, so
  `if not vtk_widget.current_style:` evaluates `True` → skipped correctly).
- `ViewportSpinner` constructed from the same class used by `VTKWidget`; falls
  back silently if Qt application is not running.

### 2. Package export (`vtk_widget/__init__.py`)

`QtFastContainer` and `_NullVtkObject` added to the public API of the
`vtk_widget` package alongside the existing exports.

### 3. `is_vtk_widget()` update (`patient_toolbar/toolbar_manager.py`)

The single production `isinstance` guard that routes toolbar actions to viewer
cells now accepts `(VTKWidget, QtFastContainer, CurvedMPRViewport)`.

### 4. Factory switch — primary path (`patient_widget_core/_pw_viewers.py`)

`_create_lightweight_vtk_placeholder()` and `creator_vtk_widget()` check
`_get_requested_viewer_backend()` first.  When the result is
`BACKEND_PYDICOM_QT` a `QtFastContainer` is returned; otherwise the original
`VTKWidget` path runs unchanged.

### 5. Factory switch — fallback path (`_vc_layout.py`)

The fallback factory copies in `ViewerController._create_lightweight_vtk_placeholder()`
and `ViewerController.creator_vtk_widget()` apply the same backend guard so
that any code path that bypasses `parent_widget` factories also gets the
correct cell type.

### 6. Plan documents

- `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md` — full design and
  crash-site register.
- `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md` — safety constraints and
  rollback procedure.

## Validation

- `pytest tests/viewer/test_fast_viewer_pipeline.py` → **167 passed, 1
  pre-existing failure** (`test_b41_drag_fast_interaction_still_skips_filter`
  — timing threshold, not related to cell separation).
- Import/stub smoke: `_NullVtkObject` is falsy, `render_window/renderer/
  interactor` stubs absorb all calls, `QtFastContainer` package export OK.
- Advanced mode (`BACKEND_VTK`) factory path verified to return `VTKWidget`
  unchanged.

## Files Changed

| File | Change |
|------|--------|
| `PacsClient/.../vtk_widget/qt_fast_container.py` | NEW |
| `PacsClient/.../vtk_widget/__init__.py` | Added `QtFastContainer`, `_NullVtkObject` exports |
| `PacsClient/.../patient_toolbar/toolbar_manager.py` | `is_vtk_widget()` accepts `QtFastContainer` |
| `PacsClient/.../patient_widget_core/_pw_viewers.py` | Factory switch in both factory methods |
| `PacsClient/.../patient_ui/_vc_layout.py` | Import + factory switch in fallback paths |
| `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md` | NEW — design plan |
| `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md` | NEW — safety plan |
