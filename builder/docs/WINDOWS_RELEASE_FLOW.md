# Windows Release Flow

## Commands

```powershell
python build.py
python build.py --skip-pyinstaller
python build.py --skip-installer-compile
python build.py --clean-only
```

## Prerequisites

- Python environment with release dependencies.
- PyInstaller available in the active environment.
- Inno Setup 6 installed to compile the final installer executable:
  - `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` (or)
  - `C:\Program Files\Inno Setup 6\ISCC.exe`
  - `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`

If Inno Setup is not installed, release staging still succeeds but installer compilation is skipped.

## Output Layout

- `builder/output/dist/AIPacs/`
  - Raw PyInstaller `onedir` output for the workstation core.
- `builder/output/stage/core/`
  - Core bundle consumed by the Windows installer.
- `builder/output/stage/plugin_packages/`
  - Installer-ready plugin package directories with `module_package.json` and payload content.
- `builder/output/stage/manifest/release_manifest.json`
  - Release manifest describing staged payloads and module catalog.
- `builder/output/packages/`
  - Store/Settings-ready distributable plugin package archives plus the package feed.
- `builder/output/installer/`
  - Final installer artifacts:
    - `ai-pacs installer.exe` (primary artifact)
    - `ai-pacs installer v<version>.exe` (version-stamped copy)

## Builder Plugin Workspace

- `builder/plugin package/definitions/`
  - Source-of-truth package definitions for the current modules.
- `builder/plugin package/sdk-template/`
  - Starter metadata for future SDK-style plugin packaging.

## Installation Model

- `Core` is always installed.
- `Custom` setup can additionally copy selected optional plugin packages into `{app}\module_packages\`.
- `Basic` modules are selected by default:
  - Viewer
  - Download Manager
  - ZetaBoost
  - Education Module
  - Stitching Module
- `Optional` modules are opt-in:
  - Advanced MPR
  - Printing
  - Run CD
  - Web Browser
  - EchoMind

The installer UX flow covers:

1. Welcome and license acceptance.
2. Setup type (Core vs Custom).
3. Optional plugin selection for Custom installs.
4. Graphics preference page with automatic GPU detection hint and manual override.
5. Ready summary with selected modules and graphics mode.
6. Install progress and post-install launch option.

The installer writes the selected module state to:

- `{app}\_internal\config\installation_profile.json`
  - Fallback: `{app}\config\installation_profile.json`

The running application reads that profile and:

- enables or disables optional feature entry points,
- bootstraps setup-selected bundled plugin packages on first launch,
- stores writable user config in `%APPDATA%\AIPacs\config`,
- stores user data in `%LOCALAPPDATA%\AIPacs\user_data`,
- probes GPU availability when the installer marked the workstation as GPU-capable.

## Advanced MPR Payload

The Advanced MPR module is treated as an external runtime, not ordinary Python files.

- Source runtime expected by the release builder:
  - `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/`
- If the runtime is missing, the release builder still stages the core installer but records the payload as missing in `release_manifest.json`.
- During release staging, obvious non-runtime content is pruned from packaged module payloads to keep installer size and compile time under control:
  - `tests/`, `testing/`, `docs/`, `examples/`
  - `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`
  - `*.pyc`, `*.pyo`, `*.pdb`, `*.lib`, `*.pyi`
- To assemble the runtime before release:

```powershell
python tools/assemble_slicer_runtime.py
```

## Verification Checklist

After a release run:

1. Confirm staging completed without errors.
2. Confirm `builder/output/stage/core/AIPacs.exe` exists.
3. Confirm `builder/output/stage/plugin_packages/module_package_feed.json` exists.
4. Confirm `builder/output/stage/manifest/release_manifest.json` exists.
5. If Inno Setup is installed, confirm both:
   - `builder/output/installer/ai-pacs installer.exe`
   - `builder/output/installer/ai-pacs installer v<version>.exe`
6. Install on a clean Windows VM or target PC and verify:
   - Core app launches.
   - Selected optional modules appear.
   - Graphics mode falls back safely when GPU is unavailable.

For a full pass/fail workflow (including PC A/PC B evidence capture), use:

- `builder/docs/INSTALLER_QA_CHECKLIST.md`
