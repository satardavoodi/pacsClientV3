# Viewer Investigation Playbook

Use this playbook when debugging viewer issues across FAST and ADVANCED paths.

## 1) Triage: identify backend + render owner

Check these runtime signals first:

- metadata backend: `metadata['series']['viewer_backend']`
- widget backend: `vtk_widget._active_backend`
- Qt bridge state: `vtk_widget._qt_bridge_active`

Render owner matrix:

| Backend state | Render owner |
|---|---|
| `vtk_simpleitk` | VTK (`ImageViewer2D.Render`) |
| `pydicom_2d` | VTK (`ImageViewer2D.Render`) with lazy pydicom source |
| `pydicom_qt` + `_qt_bridge_active=True` | Qt (`QtSliceViewer.paintEvent`) |

---

## 2) Trace load/switch lifecycle

Primary chain:

1. `change_series_on_viewer` (`_vc_switch.py`)
2. cache check + async scheduling (`_vc_load.py`)
3. `VTKWidget.switch_series` (`_vw_series.py`)
4. backend bind (`_bind_backend_from_metadata`)

If failure occurs before image display, inspect this chain first.

---

## 3) FAST lazy callback investigations

Critical callback boundary:

- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py`
- `VTKWidget._on_lazy_slice_ready_impl(...)`

Checklist:

- generation values consistent (`_lazy_requested_generation`, `_series_generation_id`)
- requested/current slice consistency (`_lazy_requested_slice`, current slice)
- stale-frame guard decision before render call
- no reslice dirtying in lazy path (`image_reslice.Modified/Update` should not be introduced)

---

## 4) Progressive display investigations

Primary file:

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`

Core guards:

- `_progressive_display_inflight` (dedup first load)
- `_progressive_display_done` (lifecycle guard, not permanent cache)

Completion layers to verify:

1. direct completion path (`on_series_download_fully_complete`)
2. deferred verify (`_completion_verify_series`)
3. sweep safety-net (`_completion_sweep_tick`)

---

## 5) Scroll/render performance investigations

- Scroll path: `_vw_scroll.py` (`set_slice`, `wheelEvent`)
- Do not add per-frame expensive operations without wheel guards.
- Do not dirty `vtkImageReslice` during scroll (known catastrophic regression class).

---

## 6) Quick test routing

Use focused tests by symptom:

| Symptom | First tests |
|---|---|
| Progressive grow / done-guard | `tests/viewer/test_fast_viewer_pipeline.py` |
| FAST live update / stale grow | `tests/viewer/test_fast_viewer_live_sync.py` |
| FAST geometry/sync | `tests/fast/` |
| Backend resolver mismatch | `tests/viewer/test_viewer_backend_config.py` |
| pydicom geometry contracts | `tests/viewer/test_pydicom_backend_geometry.py` |

---

## 7) Documentation authority map

When docs disagree, trust in this order:

1. `docs/viewer/FAST_vs_ADVANCED_ARCHITECTURE.md`
2. `docs/viewer/FAST_PIPELINE_DETAILED.md`
3. `docs/viewer/ADVANCED_PIPELINE_DETAILED.md`
4. `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md`
5. historical/proposal docs (informational only)
