# Viewer Documentation Hub

> **Purpose:** Canonical entry point for all viewer architecture/debug docs (FAST + ADVANCED).

If you only read one file first, read:
- [FAST vs ADVANCED Architecture](FAST_vs_ADVANCED_ARCHITECTURE.md)

---

## Start here by goal

| Goal | Read this first | Then read |
|---|---|---|
| Understand backend split and render ownership | [FAST vs ADVANCED](FAST_vs_ADVANCED_ARCHITECTURE.md) | [FAST Detailed](FAST_PIPELINE_DETAILED.md), [ADVANCED Detailed](ADVANCED_PIPELINE_DETAILED.md) |
| Recover FAST mammography regressions quickly | [FAST Mammography Regression Playbook](FAST_MAMMOGRAPHY_REGRESSION_PLAYBOOK_2026-05-19.md) | [FAST Detailed](FAST_PIPELINE_DETAILED.md), [Investigation Playbook](INVESTIGATION_PLAYBOOK.md) |
| Debug FAST lazy slice race / callback flow | [FAST Detailed](FAST_PIPELINE_DETAILED.md) | `T6_PREPARATION.md`, `docs/pipelines/PYDICOM_2D_BACKEND.md` |
| Debug ADVANCED VTK path | [ADVANCED Detailed](ADVANCED_PIPELINE_DETAILED.md) | `docs/pipelines/viewer-pipeline.md` |
| Find shared orchestration and where paths diverge | [Shared Components](SHARED_COMPONENTS.md) | `docs/modules/README.md` (Viewer module section) |
| Validate historical decisions and guards | `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md` | `docs/pipelines/IMAGE_PIPELINE_REFERENCE.md` |
| Run step-by-step investigations quickly | [Investigation Playbook](INVESTIGATION_PLAYBOOK.md) | FAST/ADV detailed docs + targeted tests |

---

## Canonical vs supporting docs

### Canonical (current architecture truth)
- `docs/viewer/FAST_vs_ADVANCED_ARCHITECTURE.md`
- `docs/viewer/FAST_PIPELINE_DETAILED.md`
- `docs/viewer/ADVANCED_PIPELINE_DETAILED.md`
- `docs/viewer/SHARED_COMPONENTS.md`
- `docs/viewer/INVESTIGATION_PLAYBOOK.md`

### Canonical recovery playbooks
- `docs/viewer/FAST_MAMMOGRAPHY_REGRESSION_PLAYBOOK_2026-05-19.md`

### Supporting operational references
- `docs/pipelines/viewer-pipeline.md`
- `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md`
- `docs/pipelines/PYDICOM_2D_BACKEND.md`
- `docs/pipelines/IMAGE_PIPELINE_REFERENCE.md`

### Historical/proposal material (not canonical truth)
- `docs/plans/pipelines/FAST_MODE_DOWNLOAD_VIEWING_PLAN.md` (proposal-era planning context)

---

## AI-friendly investigation playbook

1. Identify the runtime backend at failure point:
   - `viewer_backend` metadata
   - `_active_backend`
   - `_qt_bridge_active`
2. Confirm render owner:
   - `pydicom_qt` -> Qt (`QtSliceViewer.paintEvent`)
   - `pydicom_2d` and `vtk_simpleitk` -> VTK (`ImageViewer2D.Render`)
3. Trace entry path:
   - `change_series_on_viewer` -> load/switch -> `VTKWidget.switch_series`
4. For FAST lazy issues, inspect callback boundary:
   - `_vw_backend.py` -> `_on_lazy_slice_ready_impl`
5. For progressive issues, inspect lifecycle guards:
   - `_vc_progressive.py` (`_progressive_display_inflight`, `_progressive_display_done`)

---

## Terminology normalization

- **ADVANCED** = `vtk_simpleitk`
- **FAST-Qt** = `pydicom_qt` (Qt-rendered)
- **FAST-lazy VTK** = `pydicom_2d` (lazy decode, VTK-rendered)

Use these terms in new docs/issues/PRs to avoid ambiguity.
