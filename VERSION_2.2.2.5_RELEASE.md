# AIPacs Release Notes — v2.2.2.5

## Version metadata
- **Version:** `2.2.2.5`
- **Tag:** `v2.2.2.5`
- **Branch:** `DR.vahid`

## Scope included in this release

### EchoMind Secretary updates (UI + backend)
- Secretary backend flow updates (agent/orchestrator/resolver and related logic)
- Secretary UI integration updates in home/patient workflow
- Secretary memory package added under `EchoMind/secretary/memory/`

### Home page UI updates
- Updates across home page widgets and related tab/panel wiring
- Includes changes under:
  - `PacsClient/pacs/workstation_ui/home_ui/home_ui.py`
  - `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py`
  - `PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py`
  - `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`

### Curve MPR module creation
- New module added under:
  - `PacsClient/pacs/patient_tab/zeta mpr/CurveMPR/`
- Includes:
  - `__init__.py`
  - `curve_mpr_core.py`
  - `curve_mpr_interactor.py`
  - `curve_mpr_ui.py`

## Notes
- This release packages the current local branch state for publication to both configured GitHub remotes.
- Cache artifacts (e.g., `__pycache__`) are ignored by repository policy and are not included as tracked release files.
