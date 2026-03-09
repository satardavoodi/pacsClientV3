# AIPacs Release Notes — v2.2.2.3

## Version metadata
- **Version:** `2.2.2.3`
- **Tag:** `v2.2.2.3`
- **Branch:** `DR.vahid`

## Scope included in this release

### 2.1 Stitch module addition
- Added full Stitch module under:
  - `PacsClient/pacs/patient_tab/stitching/`
- Included module files and integration-related code in this release payload.

### 2.2 EchoMind updates
- **EchoMind core updates** (module structure and behavior improvements)
- **EchoMind Secretary updates** (core secretary flow, orchestration, parser updates, supporting components)
- **EchoMind-related UI updates** including secretary integration touchpoints and related UI wiring.

## Key areas touched
- `EchoMind/secretary/**`
- `EchoMind/llm_client.py`
- `PacsClient/pacs/patient_tab/viewers/secretary_bridge.py`
- `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
- `PacsClient/pacs/patient_tab/viewers/ai_chat_pages.py`
- `PacsClient/pacs/patient_tab/viewers/api_manager.py`
- `PacsClient/pacs/patient_tab/stitching/**`

## Notes
- This release is a branch snapshot intended for both configured GitHub remotes.
- DICOM/cache and ignored artifacts are not part of tracked source release contents by repository ignore policy.
