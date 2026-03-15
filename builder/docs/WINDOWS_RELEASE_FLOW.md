# Windows Release Flow

## Commands

```powershell
python build.py
python build.py --skip-pyinstaller
python build.py --skip-installer-compile
python build.py --clean-only
```

## Output Layout

- `builder/output/dist/AIPacs/`
  - Raw PyInstaller `onedir` output for the workstation core.
- `builder/output/stage/core/`
  - Core bundle consumed by the Windows installer.
- `builder/output/stage/modules/advanced_mpr/`
  - Optional Advanced MPR / 3D Slicer runtime payload when available.
- `builder/output/stage/manifest/release_manifest.json`
  - Release manifest describing staged payloads and module catalog.
- `builder/output/installer/`
  - Final `.exe` installer output when `ISCC.exe` is available.

## Installation Model

- `Core` is always installed.
- `Basic` modules are selected by default:
  - Viewer
  - Download Manager
  - ZetaBoost
- `Optional` modules are opt-in:
  - Advanced MPR
  - Printing
  - Run CD
  - Web Browser
  - EchoMind

The installer writes the selected module state to:

- `{app}\_internal\config\installation_profile.json`
  - Fallback: `{app}\config\installation_profile.json`

The running application reads that profile and:

- enables or disables optional feature entry points,
- stores writable user config in `%APPDATA%\AIPacs\config`,
- stores user data in `%LOCALAPPDATA%\AIPacs\user_data`,
- probes GPU availability when the installer marked the workstation as GPU-capable.

## Advanced MPR Payload

The Advanced MPR module is treated as an external runtime, not ordinary Python files.

- Source runtime expected by the release builder:
  - `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/`
- If the runtime is missing, the release builder still stages the core installer but records the payload as missing in `release_manifest.json`.
- To assemble the runtime before release:

```powershell
python tools/assemble_slicer_runtime.py
```
