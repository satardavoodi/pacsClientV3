# AIPacs Copilot Instructions

**Current Stable Version:** v2.2.2 (2026-02-19)

## Architecture map (start here)
- App entry is `main.py` → `AppHandler` (login) → `MainWindowWidget` → `ControlPanelInterface` → `HomePanelWidget` for patient list and downloads.
- UI is PySide6 with qasync (`main.py` sets `QEventLoop`) and VTK; keep async UI work on the Qt event loop and offload heavy work to executor threads.
- Patient workflow lives in `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` and opens `PacsClient/pacs/patient_tab` widgets for viewing.
- Download stack is Zeta-based: `PacsClient/zeta_download_manager/**` with adapter helpers in `PacsClient/components/zeta_adapter.py`. Legacy download helpers in `home_ui.py` are marked deprecated.
- Socket comms go through `PacsClient/components/socket_service.py` and config via `PacsClient/utils/socket_config.py` + `config/socket_config.json`.

## Critical rules (learned the hard way)
- **Do NOT re-sort metadata['instances'] by IPP.** VTK slices are in instance_number order (files are `Instance_NNNN.dcm` loaded via `natsort`). Metadata from DB is already in the correct order. Re-sorting by IPP broke reference lines in v1.09.5-v1.09.7.
- **The stored DirectionMatrix in field data has row 1 negated** (Y-flip compensation from `convert_itk2vtk`). Do not use it directly for DICOM normal comparisons without un-negating row 1 first.
- **Local backup of this stable version:** `backups/v2.2.2_2026-02-19/`

## Key flows to preserve
- Opening a study: `HomePanelWidget._on_patient_double_clicked_async` opens tab immediately, then starts Zeta download with priority and wires progress signals.
- Download UI: always use `DownloadManagerWidget` from `PacsClient/zeta_download_manager/ui/main_widget.py` (created via `_get_or_create_download_manager_tab`).
- Shutdown behavior: `main.py` clears only the Download Manager UI state file but keeps DB download history; do not delete DB progress in shutdown.

## Project-specific conventions
- Resource paths must go through `PacsClient/utils/config.py` (`BASE_PATH`, `ICON_PATH`, `IMAGES_LOGIN_PATH`) to work for both dev and PyInstaller.
- For sockets, update settings via `update_socket_server_settings()` before querying server-side lists.
- Prefer signals/slots for UI updates; download progress is emitted from background threads via Qt signals.

## Build/run/test workflows
- Run app: `python main.py` (Windows uses software OpenGL flags set in `main.py`).
- Build executable: `build.bat` → `build.py` (PyInstaller spec `AIPacs.spec`).
- Tests are ad-hoc scripts like `test_*.py`; there is no single test runner configured.

## Where to look for feature work
- Patient UI and tabs: `PacsClient/pacs/patient_tab/**`.
- MPR modules: `PacsClient/pacs/patient_tab/zeta mpr/**` and `advance_mpr_3d_slicer/**`.
- Download engine + state: `PacsClient/zeta_download_manager/{core,download,network,storage,state,ui}`.

## Documentation rules for AI
- When changing image pipeline or sync mapping, update `docs/IMAGE_PIPELINE_REFERENCE.md`.
- When changing Zeta MPR internals, update `PacsClient/pacs/patient_tab/zeta mpr/ZETA_MPR_PIPELINE_REFERENCE.md`.
- When bumping versions, update `VERSION_*.md` with date, tag, and commit.
