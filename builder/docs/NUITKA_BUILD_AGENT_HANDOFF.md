# Nuitka Build Plan (Agent Handoff)

Status: Active and validated
Updated: April 25, 2026

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
- State shows completed stages 0..10 with no failed stage.
- Smoke test passes with MSVC-built artifacts.
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
  - `modules.web_browser`
  - `modules.EchoMind`
  - `modules.mpr.advanced_3d_slicer`
- Always inspect stage log + report before modifying include flags.
- If compiler is `auto` on Windows/Python 3.13+, expect MSVC path.

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
