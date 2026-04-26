# Nuitka Build Plan (Agent Handoff)

Status: Active and validated
Updated: April 26, 2026

This file is the operator/agent-facing handoff for the Nuitka pipeline.
Canonical implementation details are in:
- `builder/docs/NUITKA_BUILD_PLAN.md`
- `builder nuitka/build_nuitka_release.py`

## What Was Implemented

- Replaced one-shot Nuitka flow with staged resumable pipeline (Stages 0..10).
- Added persistent state and checkpoints:
  - `builder nuitka/output/build_state.json`
  - `builder nuitka/output/checkpoints/stage_XX/checkpoint.json`
- Added per-stage logs/reports:
  - `builder nuitka/output/logs/stage_XX_*.log`
  - `builder nuitka/output/reports/nuitka_stage_XX_*.xml`
- Added stage control commands:
  - `--resume`
  - `--from-stage N`
  - `--stage N`
  - `--clean-stage N`
  - `--clean-all`
  - `--smoke-test`
  - `--audit-native-footprint`
- Preserved artifacts by default (no destructive clean unless requested).
- Kept optional plugin boundary (core compiled, optional plugins staged externally).
- Added robust Windows handling:
  - MSVC environment auto-bootstrap via `vswhere + vcvars64.bat`
  - Auto compiler preference: on Windows/Python 3.13+, use MSVC when available
  - Path/copy robustness in Stage 7 (`robocopy` fallback + correct file/dir mapping)

## Current Stable Process

Run from repo root:

1) Normal continue:
`python "builder nuitka/build_nuitka_release.py" --resume`

2) Restart from a stage:
`python "builder nuitka/build_nuitka_release.py" --from-stage 6`

3) Run one stage for debugging:
`python "builder nuitka/build_nuitka_release.py" --stage 4`

4) Clean one stage only:
`python "builder nuitka/build_nuitka_release.py" --clean-stage 6`

5) Validate build structure/runtime smoke:
`python "builder nuitka/build_nuitka_release.py" --smoke-test`

6) Audit current DLL/PYD footprint without rebuilding:
`python "builder nuitka/build_nuitka_release.py" --audit-native-footprint`

## Stage Map

0. Preflight  
1. Minimal core smoke build  
2. Qt shell build  
3. Core package inclusion  
4. DICOM basic dependencies  
5. Heavy native stack (VTK/SimpleITK/Mesa)  
6. Full core build (optional plugins excluded)  
7. Runtime resources staging  
8. External plugin package staging  
9. Installer staging  
10. Inno Setup installer

## Verified Outcome (Latest)

- End-to-end run completes through Stage 10.
- Installer generated:
  - `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`
- Latest validated installer (April 26, 2026):
  - Version `2.4.6`
  - SHA256 `25D6FD5286E5E9761190AB1604F61426B23FC89073EEA46543170DC2EE7F0067`
  - Size `416,704,335` bytes
  - Built after the medium-term native-footprint reduction pass plus Web Browser QtWebEngine runtime inclusion.
- State shows completed stages 0..10 with no failed stage.
- Smoke test passes.
- Native-footprint audit passes:
  - Previous baseline: `538` native files (`268` DLL, `270` PYD)
  - Post analytics-reduction result: `483` native files (`267` DLL, `216` PYD)
  - Current Web-ready result: `496` native files (`277` DLL, `219` PYD)
  - `pandas`, Python `matplotlib`, and compiled `modules/data_analysis` are absent from `Engine/`.
  - QtWebEngine files are present because Web Browser remains a selectable external plugin.
  - `vtkRenderingMatplotlib` files can still appear because VTK remains in core.
  - Final staged layout has root `AIPacs.exe`, `Engine/`, and root `User Data/`; nested `Engine/User Data` is removed during Stage 7.
- April 25, 2026 re-validation on current branch:
  - `--stage 0` passes.
  - `--smoke-test` passes.
  - Stage 7 rerun conflict (`WinError 183` under `slicer_custom_app`) fixed by safe destination handling and clean rebuild of `output/stage/core` on each Stage 7 run.

## Critical Rules For Future AI Agents

- Do not touch or break PyInstaller pipeline under `builder/`.
- Do not use one huge one-shot compile for development.
- Do not use `--remove-output` by default.
- Do not delete `builder nuitka/output/` unless explicit `--clean-all`.
- Always read and respect existing `build_state.json` before running.
- Prefer `--resume` and stage-local fixes over global rebuilds.
- Keep optional plugins external:
  - `modules.printing`
  - `modules.cd_burner`
  - `modules.data_analysis`
  - `modules.web_browser`
  - `modules.EchoMind`
  - `modules.mpr.advanced_3d_slicer`
- Always inspect stage log + report before modifying include flags.
- If compiler is `auto` on Windows/Python 3.13+, expect MSVC path.
- Do not promise a single hidden DLL for the Qt/VTK/SimpleITK stack. Use the native-footprint audit to reduce unnecessary dependencies instead.
- Keep plugin packaging behavior aligned with the PyInstaller builder through `builder/materialize_plugin_packages.py` and `builder/plugin_package_registry.py`.
- Advanced MPR is a customized 3D Slicer runtime plugin. Do not compile or optimize it as part of the Nuitka core; stage it as an external `runtime_payload` package.
- To stage Advanced MPR reliably, set `AIPACS_ADVANCED_MPR_RUNTIME_SOURCE` to the assembled custom Slicer runtime root before Stage 08. Materialization falls back to `advanced_mpr_runtime_root()` and then `%LOCALAPPDATA%\AIPacs\modules_runtime\advanced_mpr`.
- Nuitka Stage 08 now fails if Advanced MPR is selected but the payload is metadata-only or missing required runtime files. Use `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` only for deliberate builds that must exclude Advanced MPR.
- Current workspace note: a complete Advanced MPR runtime was found at `C:\Users\Dr.Alizadeh\Documents\ScreenConnect\Files\advanced_3d_slicer\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build`, then copied into the source project at `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build` for dev-mode resolution. The project-local runtime is intentionally Git-ignored because it is generated binary payload (~0.81 GB), not source code.
- Advanced MPR packages must include both pieces: Slicer runtime files at `payload/` root and Python bridge files under `payload/python/modules/mpr/advanced_3d_slicer`. The manifest must keep `python_paths: ["python"]`; otherwise installed launch fails with `No module named 'modules.mpr.advanced_3d_slicer'`.
- Data Analysis is a default-enabled external package. Do not recompile `modules.data_analysis` into the Nuitka core unless product requirements change; it exists to keep analytics dependencies out of `Engine/`.
- AI Imaging remains compiled into the core, but its CSV handling should stay standard-library based to avoid pulling `pandas` back into Stage 6.
- Web Browser remains an external Python package, but Stage 6 must include `PySide6.QtWebEngineCore` and `PySide6.QtWebEngineWidgets` so the external plugin can run inside the installed Nuitka Engine.
- Advanced MPR must only be selectable in installers when `plugin_packages/advanced_mpr/payload/AIPacsAdvancedViewer.exe` exists. If the Slicer runtime payload is absent, the installer component is preprocessor-guarded out.

## Module/Plugin Readiness

Run before release sign-off:

`python builder/scripts/check_module_plugin_readiness.py`

Current expected result:
- passes with Advanced MPR payload staged in the current workspace;
- Web Browser QtWebEngine runtime check is true;
- FAST/OpenCV runtime check is true;
- `pooyan_opencv_filter.json` staged config matches source.

## Known Risk Profile

- Zig on Python 3.13 may show runtime bootstrap instability in some stages.
- Pipeline now contains guarded known-issue handling, but MSVC is preferred.
- Manual GUI validation is still required for release confidence:
  1) launch app
  2) open DICOM study
  3) verify plugin loading from staged external packages

## Operator Notes

- This file is for quick operations/handoff.
- Deep implementation and detailed change history remain in:
  - `builder/docs/NUITKA_BUILD_PLAN.md`
