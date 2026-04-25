# Advanced MPR Build/Runtime Integration (Anti-Regression Guide)

## Purpose

Defines the canonical structure and guardrails for shipping and launching
`AI Advanced Analysis` / `Advanced MPR` so the module cannot silently disappear,
ship partially, or regress in installed builds.

## Canonical Flow

1. Runtime source assembled on build machine:
- Source root: `advanced_mpr_runtime_root()` (resolved in `aipacs_runtime.py`)

2. Build validation gate:
- `builder/build_release.py` -> `stage_advanced_mpr_payload()` checks required files.
- Build must fail if required runtime files are missing (unless explicit override env is used).

3. Staging:
- Staged under `builder/output/stage/plugin_packages/advanced_mpr/payload/`

4. Installer deployment:
- Installed payload root:
  `C:\ProgramData\AIPacs\module_packages\advanced_mpr\payload\`

5. Runtime deployment per user:
- User runtime root:
  `C:\Users\<user>\AppData\Local\AIPacs\modules_runtime\advanced_mpr\`

6. Launch:
- UI -> `slicer_launcher.py` worker -> `launch_slicer.py` -> `AIPacsAdvancedViewer.exe`

## Required Runtime Files (Build Gate)

`builder/build_release.py` enforces these files:
- `AIPacsAdvancedViewer.exe`
- `AIPacsAdvancedViewerLauncherSettings.ini`
- `bin/Python/startup_script.py`
- `python-install/Lib/site-packages/numpy/testing/__init__.py`
- `python-install/Lib/site-packages/pydicom/examples/__init__.py`

If any are missing, treat as release blocker.

## Launch Readiness Contract (UI Behavior)

Loading overlay must remain visible until startup readiness is confirmed.

Readiness criterion in `slicer_launcher.py`:
1. Preferred: startup log contains marker
   `STARTUP SEQUENCE COMPLETED SUCCESSFULLY`
2. Fallback: process remains stable for bounded interval with startup log output.

Do not close loading overlay at process spawn time.

## Runtime Readiness Check Before Launch

`SlicerLauncherWorker._check_runtime_installed()` must verify:
- runtime folder exists
- `AIPacsAdvancedViewer.exe` exists

If check fails, show actionable message and do not launch.

## Installed-Build Verification Checklist

1. Build artifacts
- `builder/output/installer/ai-pacs installer.exe` exists and timestamp matches build.

2. ProgramData payload
- `C:\ProgramData\AIPacs\module_packages\advanced_mpr\payload\...`
- required files present.

3. Local runtime payload
- `C:\Users\<user>\AppData\Local\AIPacs\modules_runtime\advanced_mpr\...`
- required files present.

4. Logs
- `C:\Program Files\AIPacs\User Data\logs\viewer_diagnostics.log`
- `C:\Program Files\AIPacs\User Data\logs\advanced_mpr\newmpr2_geometry_*.txt`

5. Launch markers
- Look for `[AIPACS_LAUNCH]` in viewer diagnostics.
- Look for startup completion marker in advanced_mpr log.

## Do-Not-Regress Rules

- Do not remove required runtime file checks from `build_release.py`.
- Do not revert launch readiness gating to immediate `started` on spawn.
- Do not write launcher diagnostics to Program Files writable paths.
  Use user-writable log location from `_resolve_user_writable_launch_dir()`.
- Keep startup script path fallback logic intact in installed mode.

## Ownership Map

- Build staging and validation: `builder/build_release.py`
- Installer deployment: `builder/installer/AIPacs_Setup.iss`
- Runtime path resolution: `aipacs_runtime.py`
- Launcher orchestration: `modules/mpr/advanced_3d_slicer/slicer_launcher.py`
- Process execution and startup log generation:
  `modules/mpr/advanced_3d_slicer/slicer_custom_app/launch_slicer.py`
