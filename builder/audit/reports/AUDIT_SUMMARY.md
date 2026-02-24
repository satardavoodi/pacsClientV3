# Audit Summary

- Generated (UTC): `2026-02-23T23:03:53.478697+00:00`
- Repo root: `C:\AI-Pacs codes\PacsClient V2(5jan)\PacsClientV2`

## Entrypoints

- App A: `main.py` (AIPacs)
  - Detection: score=27; candidate filename main.py; __main__ guard; QApplication creation; Qt app exec() call; freeze_support; repo root main.py
- App B: `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/launch_slicer.py` (AIPacsAdvancedViewerLauncher)
  - Detection: score=22; slicer launch filename; __main__ guard; argparse CLI; slicer content/path; AIPacsAdvancedViewer.exe reference

## GUI / Heavy Libraries

- PySide6 detected: `True`
- VTK/vtkmodules detected: `True`
- SimpleITK detected: `True`
- multiprocessing detected: `True`
- PySide6 submodules (10)
  - `PySide6.QtCore`
  - `PySide6.QtGui`
  - `PySide6.QtMultimedia`
  - `PySide6.QtMultimediaWidgets`
  - `PySide6.QtNetwork`
  - `PySide6.QtPrintSupport`
  - `PySide6.QtSvg`
  - `PySide6.QtWebEngineCore`
  - `PySide6.QtWebEngineWidgets`
  - `PySide6.QtWidgets`
- vtkmodules submodules (7)
  - `vtkmodules.all`
  - `vtkmodules.qt.QVTKRenderWindowInteractor`
  - `vtkmodules.util`
  - `vtkmodules.util.data_model`
  - `vtkmodules.util.execution_model`
  - `vtkmodules.util.numpy_support`
  - `vtkmodules.vtkCommonCore`

## Dynamic Import Risks / Hiddenimports

- Dynamic import risk files: `5`
- Suggested hiddenimports (21 total, preview):
  - `PySide6.QtCore`
  - `PySide6.QtGui`
  - `PySide6.QtMultimedia`
  - `PySide6.QtMultimediaWidgets`
  - `PySide6.QtNetwork`
  - `PySide6.QtPrintSupport`
  - `PySide6.QtSvg`
  - `PySide6.QtWebEngineCore`
  - `PySide6.QtWebEngineWidgets`
  - `PySide6.QtWidgets`
  - `SimpleITK`
  - `SimpleITK._SimpleITK`
  - `logging`
  - `vtkmodules`
  - `vtkmodules.all`
  - `vtkmodules.qt.QVTKRenderWindowInteractor`
  - `vtkmodules.util`
  - `vtkmodules.util.data_model`
  - `vtkmodules.util.execution_model`
  - `vtkmodules.util.numpy_support`
  - `vtkmodules.vtkCommonCore`

## Runtime Data Paths (Privacy Critical)

- Must not package (detected paths/patterns preview):
  - `Education`
  - `Education/**`
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/logs/**`
  - `PacsClient/pacs/patient_tab/viewers/.env`
  - `Segments`
  - `app_output.log`
  - `attachment`
  - `attachment/**`
  - `build_final.log`
  - `database`
  - `database/**`
  - `debug.log`
  - `dicom.db`
  - `download_manager_test.log`
  - `generated-files`
  - `generated-files/**`
  - `generated-files/live_sync2_err.log`
  - `generated-files/live_sync2_out.log`
  - `generated-files/live_sync3_err.log`
  - `generated-files/live_sync3_out.log`
  - `generated-files/live_sync_err.log`
  - `generated-files/live_sync_out.log`
  - `generated-files/viewer_stress_live.log`
  - `generated-files/zeta_boost_cache/manifest.db`
  - `source`
  - `source/**`
  - `source/thumbnails/**`
  - `thumbnails`
  - `thumbnails/**`
- Recommended runtime root: `%LOCALAPPDATA%\\AIPacs`
- Use QStandardPaths.AppLocalDataLocation / GenericCacheLocation rather than writing into dist/ or project root.

## Slicer Runtime Requirement

- Custom Slicer runtime binary (AIPacsAdvancedViewer.exe) not present in repo; App B is a launcher and requires an external or locally built Slicer runtime.
- External binaries referenced in code:
  - `AIPacsAdvancedViewer.exe` (count=12)
  - `AIPacs.exe` (count=2)
  - `dist/AIPacs/AIPacs.exe` (count=1)
  - `--output-filename={app_name}.exe` (count=1)
  - `{app_name}.exe` (count=1)
  - `{entry_stem}.exe` (count=1)
  - `*.exe` (count=1)
  - `AIPacsAdvancedViewer*.exe` (count=1)

## Qt Plugins / DLL Inventory (Environment)

- Qt plugins inventory available: `True`
- Qt plugins path: `C:/Users/vahid/AppData/Roaming/Python/Python312/site-packages/PySide6/plugins`
- vtkmodules: available=`True`, pyd_count=`141`, dll_count=`0`
- SimpleITK: available=`True`, pyd_count=`1`, dll_count=`0`
- vtk: available=`True`, pyd_count=`0`, dll_count=`0`

## Resource Inventory

- `.ui`: `2`
- `.qss`: `3`
- `.qrc`: `2`
- `.png`: `3823`
- `.svg`: `9`
- `.ico`: `3`
- `.json`: `231`
- `.ttf`: `22`
- Likely package data roots:
  - `EchoMind/secretary` (dir, files=81) - Detected config-like directory
  - `EchoMind/secretary/catalog` (dir, files=9) - Detected config-like directory
  - `Fonts` (dir, files=46) - Fonts loaded at runtime
  - `PacsClient/components/cd_burner/assets` (dir, files=1) - CD burner assets
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer` (dir, files=43) - Detected config-like directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/.github` (dir, files=3) - Detected config-like directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/.github/workflows` (dir, files=2) - Detected config-like directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources` (dir, files=14) - Detected UI/QSS/QRC directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources/Settings` (dir, files=1) - Detected config-like directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources/Styles` (dir, files=1) - Detected UI/QSS/QRC directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Modules/Scripted/Home/Resources` (dir, files=4) - Detected UI/QSS/QRC directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Modules/Scripted/Home/Resources/UI` (dir, files=2) - Detected UI/QSS/QRC directory
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/branding` (dir, files=4) - Slicer launcher branding assets
  - `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/docs` (dir, files=1) - Slicer launcher docs/contract
  - `PacsClient/pacs/patient_tab/viewers` (dir, files=36) - Detected config-like directory
  - `Qss` (dir, files=2871) - Global UI styles, icons, and images
  - `Qss/scss` (dir, files=4) - Detected UI/QSS/QRC directory
  - `config` (dir, files=10) - Configuration templates/defaults (filter secrets/local overrides)
  - `education_assets` (dir, files=10) - Bundled educational thumbnails/assets (non-runtime static assets)
  - `json-styles` (dir, files=1) - JSON stylesheet resources

## High-Risk Packaging Items

- PySide6 Qt plugin collection (platforms/imageformats/styles minimum)
- Qt WebEngine plugin/resources/QML packaging if WebEngine path is used
- VTK hiddenimports and native DLL collection (vtkmodules.*)
- SimpleITK pyd/DLL collection
- multiprocessing spawn behavior in frozen builds (freeze_support, child module imports)
- OpenGL/software rendering compatibility on Windows (Qt + VTK)
- Project/dist-relative runtime writes may leak data into packaged folders

## Dependency Tree / Environment Notes

- pip freeze not captured: No active venv; skipped by policy (only run in .venv_build)
- Re-run audit inside `.venv_build` after installing build/runtime dependencies.

