# Build Document

Last updated (UTC): `2026-02-23T23:03:54.106807+00:00`

This is the long-lived build knowledge base for packaging this repository on Windows using PyInstaller `onedir`. Re-run the audit (`builder/audit/scripts/run_audit.py`) and regenerate this document (`builder/audit/scripts/generate_build_docs.py`) whenever imports/dependencies/resources/runtime paths change.

## A) Project Overview

- Repository packages two independent deliverables from one codebase.
- App A (DICOM workstation): `main.py` (AIPacs)
- App B (3D Slicer tool / launcher): `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/launch_slicer.py` (AIPacsAdvancedViewerLauncher)
- App A is a PySide6/Qt desktop app with VTK + SimpleITK + multiprocessing-sensitive startup (`freeze_support` detected in `main.py`).
- App B entrypoint is a launcher for a custom AI-PACS Advanced Viewer (3D Slicer-based runtime). Audit detected references to `AIPacsAdvancedViewer.exe`.
- Slicer runtime detection status: AIPacsAdvancedViewer.exe was NOT detected in the repository. App B should be treated as a packaged launcher/front-end that requires an external or locally built custom Slicer runtime.

## B) Build Strategy

- Target platform: Windows
- Packaging mode: PyInstaller `onedir` only (no one-file)
- Build outputs must stay under `builder/output/`
- Separate app builds:
  - App A dist root: `builder/output/dist/appA/`
  - App B dist root: `builder/output/dist/appB/`
- Build workspace:
  - Build specs: `builder/spec/`
  - Hooks: `builder/hooks/`
  - Scripts: `builder/scripts/`
  - Logs: `builder/logs/`
- Build venv strategy:
  - Use dedicated repo-root virtual environment `.venv_build`
  - Install pinned build tooling and project dependencies into `.venv_build`
  - Run audit and `pip freeze` from `.venv_build` before release builds
- Pinned build tools strategy:
  - Pin `PyInstaller` and `pyinstaller-hooks-contrib`
  - Pin runtime-critical packages together (`PySide6`, `vtk`, `SimpleITK`, `numpy`, `qasync`)
  - Record final pins in `builder/requirements/build_requirements.txt`

## C) Dependency Notes

### VTK Packaging Notes

- VTK detected via imports: `True`
- Imported `vtkmodules` submodules:
- `vtkmodules.all`
- `vtkmodules.qt.QVTKRenderWindowInteractor`
- `vtkmodules.util`
- `vtkmodules.util.data_model`
- `vtkmodules.util.execution_model`
- `vtkmodules.util.numpy_support`
- `vtkmodules.vtkCommonCore`
- Audit environment `vtkmodules` binary summary:
  - available: `True`
  - package dir: `C:\Users\vahid\AppData\Roaming\Python\Python312\site-packages\vtkmodules`
  - `.pyd` count: `141`
  - `.dll` count (under `vtkmodules` folder): `0`
- `vtk` wrapper module summary:
  - available: `True`
  - scan mode: `single_file_module_no_recursive_scan`
  - module file: `C:\Users\vahid\AppData\Roaming\Python\Python312\site-packages\vtk.py`
- Build guidance:
  - Collect `vtkmodules` submodules (`collect_submodules('vtkmodules')`)
  - Collect VTK dynamic libs from both `vtkmodules` and `vtk` package locations as needed
  - Include `vtkmodules.qt.QVTKRenderWindowInteractor`
  - Verify OpenGL/runtime rendering on target GPU; keep software-rendering fallback documented

### SimpleITK Packaging Notes

- SimpleITK detected: `True`
- Audit environment `SimpleITK` summary:
  - available: `True`
  - package dir: `C:\Users\vahid\AppData\Roaming\Python\Python312\site-packages\SimpleITK`
  - `.pyd` count: `1`
  - `.dll` count: `0`
- Hidden import to include: `SimpleITK._SimpleITK`
- Prefer hook-based collection of SimpleITK binaries rather than manual copy lists.

### PySide6 Packaging Notes

- PySide6 detected: `True`
- Detected PySide6 submodules:
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
- Qt WebEngine usage detected: `True` (QtWebEngineCore/QtWebEngineWidgets imports present)
- Audit Qt plugins path: `C:/Users/vahid/AppData/Roaming/Python/Python312/site-packages/PySide6/plugins`
- Audit Qt QML path: `C:/Users/vahid/AppData/Roaming/Python/Python312/site-packages/PySide6/qml`
- Important plugin directories present:
- platforms: True
- imageformats: True
- styles: True
- iconengines: True
- tls: True
- networkinformation: True
- multimedia: True
- printsupport: False
- sqldrivers: True
- webenginecore: False
- webview: True
- Minimum plugin folders to collect:
  - `platforms`
  - `imageformats`
  - `styles`
- Additional plugin/resource folders likely required for this repo:
  - `iconengines`, `tls`, `networkinformation`, `multimedia`, `sqldrivers`
  - WebEngine-related resources and QML imports because WebEngine imports were detected
- Note: `main.py` sets `QT_OPENGL=software` and Chromium flags; frozen runtime should preserve these environment behaviors.

### Slicer Packaging Notes (App B)

- App B entrypoint: `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/launch_slicer.py`
- App B is currently a launcher script that locates and runs `AIPacsAdvancedViewer.exe` (custom Slicer build), not a full 3D Slicer build pipeline inside PyInstaller.
- Audit conclusion:
  - AIPacsAdvancedViewer.exe was NOT detected in the repository. App B should be treated as a packaged launcher/front-end that requires an external or locally built custom Slicer runtime.
- Packaging implication:
  - Package the launcher and its supporting Python/resources in App B
  - Document external runtime requirement and expected discovery locations/env vars
  - Do NOT assume stock `Slicer.exe` fallback (audit shows code explicitly rejects stock Slicer fallback)

## D) Privacy / No-Patient-Data Policy

- Non-negotiable: No real patient/runtime data may be embedded in builds.
- Must exclude runtime/generated data roots and files from packaging.
- Detected must-not-package paths (audit):
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
- Explicit exclusion patterns (use in specs/scripts):
- `Education/**`
- `database/**`
- `generated-files/**`
- `thumbnails/**`
- `attachment/**`
- `downloads/**`
- `cache/**`
- `logs/**`
- `**/*.db`
- `**/*.sqlite`
- `**/*.sqlite3`
- `**/*.log`
- `**/*.dcm`
- `**/*.dicom`
- `**/.env`
- `**/.env.*`
- Runtime storage policy:
  - Store writable data under `%LOCALAPPDATA%\AIPacs` (and subdirectories such as `cache`, `downloads`, `dicom`, `thumbnails`, `attachments`, `logs`, `db`)
  - Do not write user/runtime data inside `dist/` or next to the executable
- Code hotspots requiring migration to AppData-safe paths (examples):
- EchoMind/secretary/memory/memory_store.py:60 `DB_PATH` = "dicom.db"
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:23 `ATTACHMENT_PATH` = Path.cwd() / "attachment"
- PacsClient/utils/config.py:35 `THUMBNAIL_PATH` = BASE_PATH / 'thumbnails'
- PacsClient/utils/config.py:36 `ATTACHMENT_PATH` = BASE_PATH / 'attachment'
- PacsClient/utils/config.py:37 `EDUCATION_ASSETS_PATH` = BASE_PATH / 'education_assets'
- PacsClient/utils/config.py:38 `EDUCATION_STORAGE_PATH` = BASE_PATH / 'Education'
- PacsClient/utils/config.py:42 `SOURCE_PATH` = BASE_PATH / 'source'
- PacsClient/utils/patient_cleanup_manager.py:27 `ATTACHMENT_PATH` = SOURCE_PATH.parent / 'attachment'
- Critical note: `PacsClient/utils/config.py` currently creates/writes project-root folders such as `thumbnails`, `attachment`, `Education`, `source`, and `Segments`. Frozen builds must redirect these to AppData to avoid contaminating the installation directory.

## Config & Secrets

- Detected secret/config risk signals:
  - `.env` files found: `PacsClient/pacs/patient_tab/viewers/.env`
  - Environment variables referenced in code include `OPENAI_API_KEY`, Slicer launcher env vars (`AIPACS_ADVANCED_VIEWER_EXE`, `AIPACS_SLICER_BUILD_DIR`, `NEWMPR2_*`), and Qt runtime flags.
- Policy:
  - Never include real `.env` files in PyInstaller datas
  - Never hardcode or ship real API keys/tokens
  - Load secrets from environment variables or external config stored under LocalAppData
  - Bundle only non-sensitive default config templates
- Packaging rule:
  - Add `.env` and secret-like files to exclusion filters in spec data collection helpers and scripts

## E) Dynamic Import / Hook Requirements

- Dynamic import risk files detected: `5`
- Dynamic import risk files (audit):
- EchoMind/build_nuitka.py -> importlib.util.spec_from_file_location, spec_from_file_location
- PacsClient/pacs/patient_tab/ui/ai_module_ui/overrides/vtk_widget.py -> eval
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py -> __import__, importlib.util.spec_from_file_location, spec_from_file_location
- PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py -> exec
- build_nuitka.py -> importlib.util.spec_from_file_location, spec_from_file_location
- Suggested hiddenimports (audit-driven seed list):
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
- Hook strategy:
  - `hook-pyside6.py` / `hook-PySide6.py`: collect Qt plugins/resources (including WebEngine/QML if imported)
  - `hook-vtk.py` and `hook-vtkmodules.py`: collect `vtkmodules` submodules + native binaries
  - `hook-simpleitk.py` / `hook-SimpleITK.py`: collect `_SimpleITK` and package binaries
- Re-audit after any module/plugin loader changes; hiddenimports must evolve with the codebase.

## F) Plugin Package Architecture

The AIPacs installer deploys optional modules as self-contained **plugin packages**
under `%PROGRAMDATA%\AIPacs\module_packages\<name>\`. Each plugin package contains
a `module_package.json` that declares Python path additions:

```json
{
  "python_paths": ["python"]
}
```

When a module is enabled, `payload/python/` is prepended to `sys.path` at app
startup **before** the PyInstaller `engine/` bundle. This means the plugin
package's `modules.<name>` package **overrides** the bundled copy from `engine/`.

### Dual-Location Rule (critical)

> Any Python subpackage added to `modules/<name>/` MUST also be added (with
> identical content) to `builder/plugin package/packages/<name>/payload/python/modules/<name>/`.

**Why**: If `data/` (or any subpackage) exists only in the PyInstaller bundle
but not in the plugin package, `from modules.printing.data import ...` raises
`ModuleNotFoundError` at runtime on any machine where the module is enabled —
even though the build log shows no errors and the bundle is correct.

### Runtime resolution order (Printing module example)

```
Machine with Printing enabled:
  sys.path = [
    ...  ← other plugins
    C:\ProgramData\AIPacs\module_packages\printing\payload\python\  ← WINS
    ...
    C:\Program Files\AIPacs\engine\  ← bundled fallback (never reached for modules.printing)
  ]

Machine without Printing enabled (or dev mode):
  sys.path = [..., engine/]  ← bundled modules.printing used
```

### Plugin package locations

| Module | Plugin package path |
|--------|-------------------|
| Printing | `builder/plugin package/packages/printing/payload/python/modules/printing/` |
| EchoMind | `builder/plugin package/packages/echomind/payload/python/modules/EchoMind/` |
| Download Manager | `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/` |

### `build_release.py` copies plugin packages to stage

`builder/build_release.py` → `materialize_plugin_packages.py` copies each
`builder/plugin package/packages/<name>/` to
`builder/output/stage/plugin_packages/<name>/` before Inno Setup runs.
The installer then deploys them to `%PROGRAMDATA%\AIPacs\module_packages\`.

---

## G) Known Issues + Fixes

### v2.4.5 — `cv2` missing from build venv (2026-04-23)

- **App**: appA (FAST viewer)
- **Symptom**: `opencv_filter_pipeline.py` raised `ImportError: No module named 'cv2'`
  at viewer startup. The FAST viewer fell back to the VTK backend and displayed an
  incorrect "Advanced" badge. Drag-drop was broken.
- **Root cause**: `opencv-python-headless` was not installed in `.venv_build` and
  not listed in `suggested_hiddenimports`.
- **Fix**:
  1. Added `opencv-python-headless` to `builder/requirements/build_requirements.txt`
  2. Added `cv2` to `suggested_hiddenimports` in `builder/inventory/imports_summary.json`
  3. Added guarded import in `modules/viewer/fast/opencv_filter_pipeline.py`:
     ```python
     try:
         import cv2
     except ImportError:
         cv2 = None
     ```
- **Validation**: FAST viewer starts with pydicom_qt backend; "Advanced" badge only
  shows when Advanced mode is explicitly selected.

### v2.4.6 — `modules.printing.data` missing (2026-04-23)

- **App**: appA (Printing module)
- **Symptom**: `ModuleNotFoundError: No module named 'modules.printing.data'` when the
  Printing module was enabled on an installed machine.
- **Root cause (two-layer)**:
  1. `modules/printing/data/` did not exist at all in the main codebase.
  2. Even after fixing the main codebase, the **plugin package** at
     `builder/plugin package/packages/printing/payload/python/modules/printing/`
     had no `data/` directory. Because the plugin is loaded first (see §F), the
     bundled fix is never reached when the plugin is active.
- **Fix**:
  1. Created `modules/printing/data/` with 4 files:
     `__init__.py`, `series_repository.py`, `filming_manager.py`, `dicom_enrichment.py`
  2. Created identical `data/` in the plugin package:
     `builder/plugin package/packages/printing/payload/python/modules/printing/data/`
  3. Added `!modules/*/data/` exception to `.gitignore` (was blocking the new package).
- **Validation**: Both pre-build checks in `BUILD_CHECKLIST.md` pass. Build log
  contains no `ModuleNotFoundError`. Installer v2.4.6 = 458.8 MB.

### v2.4.7 — Inno Setup Architecture deprecation + test.py spurious warnings (2026-04-24)

- **App**: appA (installer + build log)
- **Symptom 1**: Inno Setup emitted `Warning: Architecture identifier "x64" is deprecated.
  Substituting "x64os", but note that "x64compatible" is preferred` and returned exit code 1.
- **Symptom 2**: PyInstaller `warn-appA_workstation.txt` contained top-level (non-optional)
  `missing module named image_filters` and `missing module named utils` entries, which could mask
  real missing-module problems in future audits.
- **Root cause 1**: `ArchitecturesInstallIn64BitMode=x64` in `AIPacs_Setup.iss` used the old
  Inno Setup 6 architecture identifier. Inno Setup substituted `x64os` automatically but warned.
- **Root cause 2**: `PacsClient/pacs/patient_tab/utils/test.py` is a legacy dev helper with bare
  (non-relative) top-level imports of `image_filters` and `utils` that do not exist as standalone
  packages. PyInstaller traced them as missing top-level imports even though the file is never
  used in production.
- **Fix**:
  1. Changed `ArchitecturesInstallIn64BitMode=x64` → `x64compatible` in `builder/installer/AIPacs_Setup.iss`.
  2. Added `PacsClient.pacs.patient_tab.utils.test` to the `excludes` list in
     `builder/spec/appA_workstation.spec`.
- **Validation**: Build log contains no `Architecture identifier` deprecation warning.
  `warn-appA_workstation.txt` contains no top-level `image_filters` or `utils` entries.
  All remaining warnings are third-party optional deps (confirmed harmless).

- Add entries here for each build/runtime failure using this template:
  - Date (UTC):
  - App: appA/appB
  - Error snippet:
  - Root cause hypothesis:
  - Fix applied (hook/spec/script change):
  - Validation result:

## G) Reproducibility Checklist + Version Pinning

- Current declared runtime dependencies (`requirements.txt`):
- `PySide6==6.10.2`
- `pynetdicom==2.1.1`
- `pydicom>=2.4.0`
- `grpcio`
- `google==3.0.0`
- `google-api-python-client==2.168.0`
- `vtk`
- `SimpleITK==2.5.3`
- `natsort==8.4.0`
- `sounddevice==0.5.2`
- `soundfile==0.13.1`
- `qasync`
- `numpy`
- `QtAwesome`
- `pandas`
- `openai==1.97.0`
- `python-dotenv`
- `comtypes>=1.3.0`
- `SpeechRecognition>=3.10.0`
- `pyaudio`
- `webrtcvad`
- Recommended build/runtime pin placeholders:
- PyInstaller: PyInstaller==<pin-me>
- pyinstaller-hooks-contrib: pyinstaller-hooks-contrib==<pin-me>
- PySide6: PySide6==6.10.2
- vtk: vtk==<pin-me>
- SimpleITK: SimpleITK==2.5.3
- qasync: qasync==<pin-me>
- numpy: numpy==<pin-me>
- QtAwesome: QtAwesome==<pin-me>
- pydicom: pydicom==<pin-me>
- soundfile: soundfile==0.13.1
- sounddevice: sounddevice==0.5.2
- grpcio: grpcio==<pin-me>
- pynetdicom: pynetdicom==2.1.1
- pandas: pandas==<pin-me>
- comtypes: comtypes==<pin-me>
- Controlled venv `pip freeze` status:
  - ran: `False`
  - reason/status: `No active venv; skipped by policy (only run in .venv_build)`
- Reproducibility process:
  - Create fresh `.venv_build`
  - Install pinned `builder/requirements/build_requirements.txt`
  - Install pinned project deps
  - Run audit + docs generation
  - Build appA + appB using specs only
  - Archive logs + hashes for output folders

## H) Release Checklist

- Pre-build
  - Clean `builder/output/build/*` and `builder/output/dist/*`
  - Verify `.venv_build` active
  - Verify no `.env` / tokens are staged for inclusion
  - Re-run audit (`AUDIT_SUMMARY.md`) and review privacy exclusions
- Build
  - Build App A (`builder/spec/appA_workstation.spec`)
  - Build App B (`builder/spec/appB_slicer.spec`)
  - Capture logs under `builder/logs/`
- Smoke test (local)
  - Launch App A exe
  - Open main window/login flow
  - Exercise VTK + SimpleITK viewer path
  - Exercise WebEngine features if used
  - Verify subprocess/multiprocessing features do not recurse-launch
  - Launch App B exe and confirm external Slicer runtime discovery/error messaging behavior
- Clean VM test (Windows)
  - Install VC++ prerequisites if needed
  - Run both apps from fresh user profile
  - Confirm Qt plugins load (no platform plugin errors)
  - Confirm no writes into install directory (only LocalAppData)
- Release hardening (optional but recommended)
  - Code signing
  - Hash manifest / SBOM
  - Version stamping and changelog update

## References

- Audit summary: `builder/audit/reports/AUDIT_SUMMARY.md`
- Inventory files: `builder/inventory/*.json`
