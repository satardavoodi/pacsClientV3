# ZMPR (Zeta MPR) Module

**Version:** 1.09.8.2  
**Last Updated:** 2026‑02‑08  
**Location:** `PacsClient/pacs/patient_tab/zeta mpr/`

---

## Overview

Zeta MPR is the primary MPR implementation in v1.09.8.2. It provides orthogonal
multi‑planar views, crosshair synchronization, measurement tools, curved MPR,
and advanced rendering options.

**Key Features**
- Standard MPR (axial / sagittal / coronal)
- Curved MPR (parallel transport frames)
- Measurement tools (ruler, angle, caption)
- Window/level presets
- MIP / MinIP / Thick‑slab helpers

---

## Module Structure

```
zeta mpr/
├── __init__.py
├── standard_mpr_viewer.py
├── curved_mpr.py
├── mpr_measurement_tools.py
├── advanced_rendering.py
├── surface_reconstruction.py
├── segmentation_tools.py
├── preset_manager.py
└── ZETA_MPR_PIPELINE_REFERENCE.md
```

---

## Integration (v1.09.8.2)

Zeta MPR is launched from the main toolbar via:
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
- `ToolbarManager.toggle_zeta_mpr()`

**Implementation detail:** the toolbar loads the module dynamically from
`patient_tab/zeta mpr/` using `importlib` to avoid issues with the space in
the folder name.

---

## Curved MPR

Curved MPR uses `CurvedMPRGenerator` (see `curved_mpr.py`). The toolbar includes
UI to collect points and generate a curved volume + panoramic view.

---

## Measurement Tools

Measurement tools are coordinated by `MPRMeasurementTools` and are activated
from the toolbar. Tools are shared across all MPR views (axial/sagittal/coronal).

---

## Oblique Reslice Behavior

Oblique reslicing is controlled by `StandardMPRViewer.oblique_enabled`.
If disabled, crosshair rotation remains visual only.

---

## Known Operational Notes

- The folder name contains a space (`zeta mpr`), so dynamic import is used.
- `vtk_3d_presets.py` is expected by `preset_manager.py` (verify it exists if
  presets fail to load).

---

## 🧠 AI Notes (Explicit Guidance)

1. Zeta MPR and Orthogonal MPR are separate modules. Do not mix their APIs.
2. Any change to Zeta MPR behavior must be reflected in
   `ZETA_MPR_PIPELINE_REFERENCE.md`.
3. If you change crosshair or oblique logic, document the new default for
   `oblique_enabled` and how it is toggled.
