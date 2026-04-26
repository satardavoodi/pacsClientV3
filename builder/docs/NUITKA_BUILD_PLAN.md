# Nuitka Incremental Build Plan

Status: In Progress (checkpoint pipeline implemented)
Updated: April 25, 2026

This document is for the **Nuitka build chain in `builder nuitka/`** only.

## Build-System Boundary

This repo has two separate builders:

- `builder/` = Python/PyInstaller-based release builder
- `builder nuitka/` = staged Nuitka builder

Use this document only when the task is about:

- `build_nuitka.bat`
- `build_nuitka_release.bat`
- `builder nuitka/build_nuitka_release.py`
- `builder nuitka/output/`
- stage checkpoints, resume flow, or Nuitka-specific compiler issues

If the task is about `build.bat`, `build.py`, `builder/build_release.py`, `builder/spec/appA_workstation.spec`, or `builder/output/`, use the PyInstaller docs in `builder/docs/BUILD_DOCUMENT.md`, `builder/docs/WINDOWS_RELEASE_FLOW.md`, and `builder/docs/BUILD_CHECKLIST.md` instead.

## PyInstaller Incremental Builds (separate pipeline)

The PyInstaller pipeline (`builder/`) now also supports incremental builds without
touching the Nuitka pipeline.

### How it works
PyInstaller caches its dependency-scanning results in `builder/output/build/`
as `Analysis-00.toc` and related `.toc` files.  When those files exist, PyInstaller
skips the expensive binary/DLL scanning phase (VTK, PySide6, SimpleITK) and only
recompiles the changed Python modules and re-links the exe.

Previously every build deleted `BUILD_DIR` **and** passed `--clean` to PyInstaller,
forcing a full re-scan every time (~5 min).  Now:
- `BUILD_DIR` is preserved between runs by default.
- `--clean` is **not** passed to PyInstaller by default.
- Result: **~1–2 min** for subsequent code-only changes.

### Workflows
| Command | What runs | Use when |
|---------|-----------|----------|
| `build.bat` | PyInstaller (incremental) + stage + installer | Normal code change |
| `build_incremental.bat` | Same as above, documented default | Shortcut / reminder |
| `build.bat --clean-build` | PyInstaller (full clean) + stage + installer | New packages, spec change |
| `build.bat --skip-pyinstaller` | Stage + installer only (reuse existing dist) | Config/asset change only |
| `build.bat --skip-installer-compile` | PyInstaller + stage, no ISCC | Quick test bundle |

### When to use `--clean-build`
- You added or removed a pip package.
- You changed `builder/spec/appA_workstation.spec` or `spec_utils.py`.
- You changed `builder/inventory/imports_summary.json`.
- You moved a module between packages (changes the import graph).
- The incremental build fails with "module not found" errors in the frozen app.

### File created
- `build_incremental.bat` — convenience wrapper at project root.
- `builder/build_release.py` — `--clean-build` flag, `preserve_build` param.

## Objective
Convert Nuitka release build from one-shot compilation to a staged, resumable pipeline where failed late stages do not destroy earlier successful work.

## Scope
- Keep PyInstaller pipeline untouched (`builder/` remains separate).
- Keep all Nuitka artifacts under `builder nuitka/output/`.
- Use standalone/one-folder first; no onefile in development pipeline.
- Preserve output/cache by default; clean only when explicitly requested.

## Stage Model
Stages are implemented in `builder nuitka/build_nuitka_release.py`.

0. Preflight
1. Minimal core smoke build
2. Qt shell build
3. Core package inclusion
4. DICOM basic viewer dependencies
5. Heavy native imaging stack (VTK/SimpleITK/Mesa)
6. Full core build (optional plugins excluded)
7. Runtime resources staging
8. External plugin package staging
9. Installer staging (manifest/profile)
10. Inno Setup installer

## Command Interface
Run from project root.

- Full staged run:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py"`
- Resume from first failed/incomplete stage:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume`
- Run from selected stage onward:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 5`
- Run only one stage (debugging):  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 2`
- Run with explicit compiler override (when Zig/MSVC behavior differs):  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 1 --compiler msvc`
- Clean one stage artifacts only:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-stage 5`
- Clean all Nuitka outputs only:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-all`
- Post-build smoke checks:  
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --smoke-test`

Batch wrappers:
- `build_nuitka_release.bat` now auto-bootstraps `.venv_build` if missing and auto-installs `requirements-nuitka.txt` if Nuitka toolchain is missing.
- `build_nuitka.bat` now routes to staged pipeline (`--resume` by default) instead of one-shot clean compile.

## Build State / Checkpoints / Logs

### State file
`builder nuitka/output/build_state.json`

Tracks:
- current stage
- completed stages
- failed stage
- timestamp(s)
- mode (fresh/resume/single/from-stage)
- per-stage command, outputs, artifacts, issues
- per-stage report path and log path

### Per-stage logs
`builder nuitka/output/logs/stage_XX_<name>.log`

Behavior:
- existing stage log is archived with timestamp
- latest log keeps stable filename

### Checkpoints
`builder nuitka/output/checkpoints/stage_XX/checkpoint.json`

Checkpoint currently uses marker-based strategy:
- references preserved output/report/log/artifact paths
- does not clone full dist folders (avoids massive duplication)

## Reports
Every Nuitka compile stage writes an explicit report:

`builder nuitka/output/reports/nuitka_stage_XX_<name>.xml`

Reports are used for:
- missing import/DLL diagnostics
- optional-plugin boundary verification at stage 6

## Cache Strategy
Project-local cache roots:
- `builder nuitka/output/cache/`
- `builder nuitka/output/nuitka-cache/`
- `builder nuitka/output/ccache/`

Configured behavior:
- Nuitka 4.0.8 does not support `--cache-dir`, so output/cache control is done by
  preserving stage build/dist/report folders and Nuitka's own managed cache.
- `CCACHE_DIR` / `CLCACHE_DIR` env overrides are intentionally disabled in the
  orchestrator because they produced unstable artifacts in this toolchain.
- no `--remove-output` in stage commands.

## Requirements Strategy
- Added `requirements-nuitka.txt` as the dedicated Nuitka build layer:
  - `-r requirements-core.txt`
  - `nuitka`
  - `ordered-set`
  - `zstandard`
- Updated `requirements-dev.txt` to include `requirements-nuitka.txt`.
- Updated `setup_build_env.ps1` to install `requirements-nuitka.txt` and verify `nuitka` import.
- Result: new release versions can reuse `.venv_build` without repeating manual tool installs.

Notes:
- Some compiler/system caches can still exist outside project depending on toolchain behavior.

## Core vs Optional Plugin Boundary
At full-core stage:
- Optional modules are excluded through `--nofollow-import-to`, including:
  - `modules.printing`
  - `modules.cd_burner`
  - `modules.web_browser`
  - `modules.EchoMind`
  - `modules.mpr.advanced_3d_slicer`
- Plugin packages are staged externally in stage 8 (not compiled into core).

## Runtime Resource Strategy
Stage 7 copies runtime resources into staged core bundle and syncs theme qss:
- Qss
- Fonts
- config
- json-styles
- additional data dirs from spec

It also records basic comparison notes against existing PyInstaller dist when present.

## Smoke Test
`--smoke-test` validates:
- stage 6 exe exists
- Qt platform plugin folder exists
- key graphics DLL candidates exist
- staged resources exist
- plugin package staging exists
- optional plugin compile boundary check from report
- fast launch check using `AIPACS_NUITKA_SMOKE_TEST=1`

Manual checks are still required for full clinical workflows.

## Cross-Build Coherence Check
After PyInstaller and Nuitka staging complete, run:

`python builder/scripts/check_build_coherence.py`

This verifies:
- both stage outputs contain required installer/profile/feed artifacts
- `installation_profile.json` module map and version fields match
- optional plugin package feed/module directories match in both build systems
- Nuitka stage 6 report does not compile optional plugin module families into core

## Failure Recovery
On stage failure, output includes:
- failed stage name/number
- log path
- report path (if created)
- reminder that previous checkpoints are preserved
- next commands:
  - `--resume`
  - `--stage N`

## Current Progress
- Implemented staged orchestrator with 0..10 stages
- Implemented resumable state (`build_state.json`)
- Implemented per-stage logs/reports/checkpoints
- Implemented stage-specific Nuitka command generation
- Implemented smoke-test command
- Added early startup smoke-exit hook (`AIPACS_NUITKA_SMOKE_TEST`)
- Installer stage support wired for Nuitka installer script
- Added automated Nuitka environment bootstrap flow (`requirements-nuitka.txt` + setup/build wrappers)
- Confirmed stage 0 preflight passes on `.venv_build` with Zig 0.15.1 and Mesa DLL set.
- First stage 1 resume attempt failed on April 24, 2026 due to unsupported Nuitka CLI flag `--cache-dir` in Nuitka 4.0.8; command builder updated to remove this flag for compatibility.
- Stage 1 compile then failed with Zig linker undefined-symbol errors (`lld-link` + zig backend). Added `--compiler` override support to run compile stages with MSVC when needed.
- Added Zig backend stabilization in orchestrator: when `--zig` is active, it now exports `CC/CXX/LINK` to the user-installed `zig.exe` from PATH to avoid private-pip Zig mismatch.
- Stage 1 now passes with local Zig 0.15.1.
- Stage 2 now passes (Qt shell compile + runtime smoke + platform plugin path validation updated for Nuitka layout `PySide6/qt-plugins/platforms`).
- Stage 3 remains in-progress tuning: long-running compilation exceeds automation timeout window in this session; stage reset with `--clean-stage 3` so next run starts cleanly from stage 3.
- April 25, 2026 validation: `--stage 0` passes preflight and `--smoke-test` passes on current workspace state.
- Fixed Stage 7 rerun reliability: `copy_if_exists()` now treats folder-like destinations correctly for file copies, and Stage 7 now recreates `builder nuitka/output/stage/core` each run to avoid stale artifact conflicts.
- Smoke-test updated for Qt plugin layout compatibility by checking both:
  - `PySide6/plugins/platforms`
  - `PySide6/qt-plugins/platforms`
- Installer parity update: `builder nuitka/installer/AIPacs_Nuitka_Setup.iss` now uses the same installation-profile and setup-state logic as the PyInstaller installer (existing-install detection, GPU page, and `installation_profile.json` writing).
- Stage 8/9 hardening:
  - Stage 8 now fails early if `module_package_feed.json` is missing after plugin staging.
  - Stage 9 now explicitly sets `installer.current_version` in `installation_profile.json`.
- State coherence hardening:
  - `--resume` now always starts from the first incomplete stage number, even if old `failed_stage` metadata exists.
  - Re-running any stage now marks all downstream completed stages as `stale` in `build_state.json`, so resume naturally rebuilds affected downstream stages instead of trusting stale completion flags.
- April 25, 2026 runtime startup diagnosis:
  - Observed installer/runtime launch failure reproduced from `builder nuitka/output/stage/core/AIPacs.exe`.
  - Root cause captured: recursion loop in lazy database shims under frozen PySide/Shiboken introspection (`RecursionError` through `database.__getattr__` / `PacsClient.utils.database.__getattr__`).
  - Mitigation applied in source shims: dunder-attribute fast-fail + import-in-progress guards for:
    - `database/__init__.py`
    - `PacsClient/utils/database.py`
    - `PacsClient/utils/db_manager.py`
  - Stage 7 now creates `User Data/` explicitly in staged core so installer output layout includes it predictably.
- Stage 10 artifact handling corrected to keep Nuitka installer outputs/metadata under `builder nuitka/output/installer/` without PyInstaller path/name normalization.
- April 25, 2026 stability tuning:
  - Removed forced `CC/CXX/LINK` Zig override; pipeline now lets Nuitka choose its managed Zig toolchain (0.16.x).
  - Removed forced compiler-cache env overrides (`CCACHE_DIR`/`CLCACHE_DIR`) due unstable artifacts.
  - Narrowed `--nofollow-import-to` to optional plugin module families only (`modules.*`), avoiding stdlib-side effects.
  - Removed deprecated `--enable-plugin=numpy` usage.
  - Full-core command switched to entrypoint-driven inclusion (no giant forced include lists).
  - Stage 6 smoke launch is now warning-only (recorded in stage notes) so compile checkpoint is preserved even when runtime triage is still needed.
  - Added startup guard in `main.py` for missing pydicom encoder plugin modules to prevent hard crash during plugin registration.
  - Stage 6 now compiles reliably and preserves checkpoint; remaining runtime issues should be triaged incrementally from stage 6 without rebuilding from stage 0.
- April 25, 2026 (v2.4.5 sync + focused Stage 6 fix):
  - Synced local branch with latest `origin/main` changes that include Python-build updates for Advanced MPR/plugin packaging consistency.
  - Resolved plugin package descriptor merge conflicts by keeping 2.4.5 metadata (`module_package.json` versions aligned with Python build).
  - Stage 6 `full_core` command now force-includes available pydicom encoder modules (including `pydicom.encoders.gdcm` and related handlers) to fix frozen runtime import failures.
  - Fixed optional-plugin boundary startup crash by making `PacsClient.pacs.workstation_ui.home_ui` import-safe when EchoMind is excluded from compiled core.
  - Verified requested focused execution path:
    - `--clean-stage 6`
    - `--stage 6`
    - `--from-stage 7`
    - followed by validation rebuild (`--stage 6`, `--from-stage 7`) and `--smoke-test` pass.
  - Observed incremental build behavior in practice:
    - clean Stage 6 compile: ~30.7 min
    - incremental Stage 6 recompile after small patch: ~9.8 min
    - confirms cache/checkpoint pipeline avoids full restart cost for small changes.

## Next Execution (Current)
Use the build venv and continue from stage 3:

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 3`

If interrupted, continue with:

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume`

If stage 3 command profile is changed again, reset only stage 3 artifacts:

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-stage 3`

## Known Risks
- Stage 3-6 compile times remain high on first pass.
- Dependency-specific tuning may still be needed in stage command profiles.
- Optional module data files can appear in dist if requested explicitly as data; this is separate from Python module compilation.
- Toolchain-specific cache locations may not be fully relocatable in every environment.

## Next Iterations
1. Tune stage profile include lists based on real failures from reports.
2. Add richer report summarization (human-readable stage diagnostics).
3. Add targeted runtime checks for DICOM test dataset and native DLL probe logs.
4. Tighten installer profile payload contents to match release operations checklist.
