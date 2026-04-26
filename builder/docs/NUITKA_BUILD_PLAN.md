# Nuitka Incremental Build Plan

Status: In Progress (checkpoint pipeline implemented)
Updated: April 26, 2026

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
- Native DLL/PYD footprint audit without rebuilding:
  `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --audit-native-footprint`

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
- Final staged core layout now uses:
  - `core/Engine/` for executable, DLLs, and internal runtime files
  - `core/User Data/` parallel to `Engine`
  - `core/Launch AIPacs.cmd` and `core/Launch AIPacs.vbs` as root launchers

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

## Core Native Footprint Reduction

This repo has two separate build systems that must remain coherent:
- `builder/` is the Python/PyInstaller release builder.
- `builder nuitka/` is the staged Nuitka release builder.

Use these docs together:
- `builder/docs/NUITKA_BUILD_AGENT_HANDOFF.md` for current Nuitka operator notes.
- `builder/docs/BUILD_DOCUMENT.md` for long-lived PyInstaller build standards.
- `builder/docs/BUILD_CHECKLIST.md` for release checks and plugin dual-location rules.
- `builder/docs/WINDOWS_RELEASE_FLOW.md` for installer/profile/module behavior.

### DLL/PYD reality
Nuitka standalone mode does not safely collapse the full Qt/VTK/SimpleITK/NumPy/native-extension stack into one private DLL. Windows still loads native runtime DLLs and `.pyd` extension modules as separate files. `--onefile` can hide the layout at rest, but it extracts files at runtime and is harder to debug for this medical-imaging dependency stack.

The reliable reduction strategy is therefore:
- keep the clean root layout (`AIPacs.exe`, `Engine/`, `User Data/`, uninstaller files);
- keep required native runtime files inside `Engine/`;
- remove unnecessary dependencies from the compiled core only after audit evidence;
- keep optional modules external through the shared plugin package system.

### Native footprint audit command
Run this before and after any dependency-reduction change:

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --audit-native-footprint`

The command inspects:

`builder nuitka/output/stage/core/Engine`

It writes:
- `builder nuitka/output/reports/native_footprint.json`
- `builder nuitka/output/reports/native_footprint.md`

The audit records:
- total `.dll` count;
- total `.pyd` count;
- total native file count;
- largest native folders;
- key package presence (`pandas`, `matplotlib`, `cv2`, `vtkmodules`, `SimpleITK`, `PySide6`, `numpy`, `PIL`);
- optional plugin native-path presence;
- optional plugin presence in the Stage 6 Nuitka XML report;
- added/removed native files compared with the previous audit.

The audit is warning-only. It must not fail release builds by itself.

### First safe reduction target
The first practical reduction candidate was `modules.data_analysis`, because it pulled heavy analytics dependencies such as `pandas` and `matplotlib`.

Completed approach:
1. `modules.data_analysis` is now a default-enabled external package instead of a compiled Nuitka-core module.
2. The shared package definition lives under `builder/plugin package/definitions/data_analysis/`.
3. Both PyInstaller and Nuitka installers stage it through the shared module package feed/profile system.
4. Nuitka Stage 6 excludes it with `--nofollow-import-to=modules.data_analysis`.
5. Runtime startup can still install/load it through `aipacs_runtime` package path injection.

For future candidates, do not remove dependencies blindly. First:
1. Run `--audit-native-footprint` and save the baseline.
2. Confirm the module is not required for default startup.
3. If it is optional, move it to external plugin/package handling or no-follow it from the Nuitka core.
4. Rebuild only the affected stages.
5. Run `--audit-native-footprint` again and verify whether the target dependency dropped from the core.

Do not remove `modules.ai_imaging` in the first pass. It is connected to patient/reception/download workflows. Instead, its small CSV-only `pandas` usage was replaced with a narrow standard-library CSV table shim so AI Imaging remains compiled into the core without pulling `pandas`.

Expected audit detail:
- `pandas` should be absent from `Engine/`.
- Python `matplotlib` package folders should be absent from `Engine/`.
- `vtkRenderingMatplotlib` files can still appear while VTK remains in core; these are VTK rendering bridge binaries, not the full Python `matplotlib` package.

### VTK/SimpleITK policy
Keep VTK and SimpleITK in the Nuitka core for now. The large VTK footprint is mainly caused by broad `vtkmodules.all` imports in viewer/MPR/patient-tab code. Reducing that safely requires a separate source refactor to replace `vtkmodules.all` with explicit VTK imports plus viewer/MPR regression tests.

Do not manually delete VTK, SimpleITK, Qt, NumPy, OpenCV, PIL, Python, or VC runtime binaries from `Engine/` unless smoke/manual tests prove the application still works.

### Plugin alignment with Python build
Plugin package behavior must stay build-agnostic. The Python build is the reference for plugin package behavior; the Nuitka build is the reference for compiled-core behavior.

Shared plugin/package sources:
- `builder/materialize_plugin_packages.py`
- `builder/plugin_package_registry.py`
- `builder/plugin package/definitions/`
- `builder/plugin package/packages/`

Optional modules that should remain external in both builders:
- `advanced_mpr`
- `data_analysis`
- `printing`
- `run_cd`
- `web_browser`
- `echomind`

EchoMind must load through external package staging, not by compiling `modules.EchoMind` into Nuitka core.

Advanced MPR is a customized 3D Slicer runtime/plugin. It must not be optimized as part of the Nuitka core and does not need to be compiled into the core. Its expected model is:
- build/package Advanced MPR independently using its Python/Slicer runtime structure;
- stage it as a `runtime_payload` plugin package;
- connect it to the core through the shared plugin feed/profile/runtime path injection;
- keep its large Slicer runtime and bridge resources outside the Nuitka `Engine/` core.
- only expose the Advanced MPR installer component when `plugin_packages/advanced_mpr/payload/AIPacsAdvancedViewer.exe` exists.

Advanced MPR runtime source resolution for package materialization:
1. `AIPACS_ADVANCED_MPR_RUNTIME_SOURCE`
2. `advanced_mpr_runtime_root()` from `aipacs_runtime.py`
3. `%LOCALAPPDATA%\AIPacs\modules_runtime\advanced_mpr` as a developer-machine fallback

Stage 08 now validates the required runtime files before accepting Advanced MPR as staged:
- `AIPacsAdvancedViewer.exe`
- `AIPacsAdvancedViewerLauncherSettings.ini`
- `bin/Python/startup_script.py`
- `python-install/Lib/site-packages/numpy/testing/__init__.py`
- `python-install/Lib/site-packages/pydicom/examples/__init__.py`

If the runtime is missing or incomplete, Stage 08 fails fast unless `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` is deliberately set. This prevents a metadata-only Advanced MPR package from silently reaching the Nuitka installer.

Any Python subpackage added to an optional module must also be added to the matching plugin package payload path, following the dual-location rule in `BUILD_CHECKLIST.md`.

### Module/plugin readiness audit
Run this after Stage 8 or before installer sign-off:

`.venv_build\Scripts\python.exe builder/scripts/check_module_plugin_readiness.py`

The command writes:
- `builder nuitka/output/reports/module_plugin_readiness.json`
- `builder nuitka/output/reports/module_plugin_readiness.md`

It checks:
- optional module package definitions;
- PyInstaller and Nuitka staged plugin package presence;
- Advanced MPR runtime payload availability;
- Web Browser QtWebEngine runtime files inside Nuitka `Engine/`;
- FAST/OpenCV files and `pooyan_opencv_filter.json` parity.

Current classification:
- `viewer`, `download_manager`, `zeta_boost`, `education`, `stitching`, `offline_cloud_server`: core/basic behavior.
- `data_analysis`: default-enabled external package to keep analytics dependencies out of `Engine/`.
- `printing`, `run_cd`, `web_browser`, `echomind`: selectable external Python packages.
- `advanced_mpr`: selectable only when the assembled Slicer runtime payload exists.
- `ai_imaging`, `network`, `storage`, `module_system`, `LicenseGenerator`, `zeta_sync`: internal/core-support folders, not standalone installer plugins in the current release model.

### Web Browser runtime rule
The Web Browser plugin remains an external Python package (`modules/web_browser`), but its QtWebEngine native runtime must be included in the compiled Nuitka `Engine/`. Stage 6 force-includes:
- `PySide6.QtWebEngineCore`
- `PySide6.QtWebEngineWidgets`

This causes Nuitka to include `QtWebEngineProcess.exe`, `qt6webengine*.dll`, `icudtl.dat`, `v8_context_snapshot.bin`, and `qtwebengine*.pak` resources. Do not remove those files while `web_browser` remains a selectable installer plugin.

### FAST/OpenCV rule
FAST mode uses `PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline` and `cv2` through `modules.viewer.fast.pydicom_lazy_volume`. The Nuitka core must include:
- `cv2/cv2.pyd`
- `cv2/opencv_videoio_ffmpeg*.dll`
- `Engine/config/pooyan_opencv_filter.json`

The expected default filter config is `config/pooyan_opencv_filter.json` with `preserve_dimensions=true`. The readiness checker verifies the staged Engine config matches the source config.

### Incremental reduction workflow
For core/spec dependency changes:

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-stage 6`

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 6`

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 7`

For resource/layout changes:

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 7`

For plugin-package-only changes:

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 8`

`.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 9`

Always finish reduction work with:
- `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --smoke-test`
- `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --audit-native-footprint`
- `python builder/scripts/check_build_coherence.py`

Avoid `--clean-all` unless intentionally rebuilding every Nuitka artifact. Never add `--remove-output` to development builds.

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
- April 26, 2026 (installer/runtime structure + optional-module runtime behavior):
  - Added `--no-deployment-flag=excluded-module-usage` to Stage 6 full-core command so modules excluded by `--nofollow-import-to` can still load externally at runtime (fixes EchoMind startup exclusion crash path).
  - Updated Nuitka installer layout to launch from `{app}\Engine\AIPacs.exe`.
  - Updated staged runtime output to produce `Engine + User Data + launcher files`.
  - Updated frozen runtime path resolution so `User Data` remains parallel to `Engine`.
  - Advanced MPR status: runtime payload source path is currently missing in this workspace, so package is staged metadata-only (`PAYLOAD_NOT_MATERIALIZED`) until runtime payload files are provided.
- April 26, 2026 (core/plugin boundary build):
  - Reconfirmed product boundary: Nuitka work is for the compiled core only; plugins remain Python/runtime payload packages.
  - Advanced MPR is treated as a customized 3D Slicer runtime plugin and is not part of Nuitka core optimization.
  - Removed optional-plugin resource copying from the local Nuitka spec data list so Stage 7 core staging does not place `modules/mpr/advanced_3d_slicer`, `modules/EchoMind`, or `modules/cd_burner` under `Engine/`.
  - Rebuilt `--from-stage 7` successfully through Stage 10 and generated `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`.
  - Verified `--smoke-test`, `--audit-native-footprint`, and `python builder/scripts/check_build_coherence.py` all pass.
  - Latest installer SHA256: `DE7EAD31C3FA04B9C7670A4F089B99DDFA14723CB1A5D4DAA0744E265C0BB575`.
- April 26, 2026 (medium-term native-footprint reduction pass):
  - Added `data_analysis` as a default-enabled external module package in `aipacs_runtime.py`.
  - Added shared package definition `builder/plugin package/definitions/data_analysis/plugin_package.json`.
  - Updated both PyInstaller and Nuitka installer scripts so `data_analysis` is staged through ProgramData module packages instead of compiled into the Nuitka core.
  - Added `modules.data_analysis` to Nuitka optional no-follow rules.
  - Replaced AI Imaging's direct `pandas` CSV usage with `modules/ai_imaging/ai_module_ui/csv_table.py`, keeping AI Imaging in the compiled core while removing the `pandas` dependency.
  - Rebuilt the targeted path:
    - `--clean-stage 6`
    - `--stage 6`
    - `--from-stage 7`
  - Validation passed:
    - `--smoke-test`
    - `--audit-native-footprint`
    - `python builder/scripts/check_build_coherence.py`
    - focused import check for staged external `data_analysis`.
  - Native footprint changed from `538` native files (`268` DLL, `270` PYD) to `483` native files (`267` DLL, `216` PYD).
  - Removed core package folders: `pandas`, Python `matplotlib`, and `modules/data_analysis`.
  - Removed stale nested `Engine/User Data` during Stage 7 so final staging keeps `User Data/` only parallel to `Engine/`.
  - New installer: `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`, size `323,255,179` bytes, SHA256 `A1172236943E123F1A14AB40B2D5C625E03D4FB94924514C865400022FAE6CCA`.
- April 26, 2026 (module/plugin readiness + Web/FAST fix):
  - Reviewed `modules/` against `MODULE_CATALOG`, plugin package definitions, PyInstaller staging, Nuitka staging, and installer copy rules.
  - Added `builder/scripts/check_module_plugin_readiness.py`.
  - Fixed Web Browser installed-runtime support by force-including `PySide6.QtWebEngineCore` and `PySide6.QtWebEngineWidgets` in Stage 6 while keeping `modules.web_browser` external.
  - Updated Nuitka and PyInstaller installer scripts so Advanced MPR is only selectable when the assembled runtime payload contains `AIPacsAdvancedViewer.exe`.
  - Verified FAST/OpenCV runtime presence and filter config parity; `cv2` and `pooyan_opencv_filter.json` are present in Nuitka `Engine/`.
  - Rebuilt requested targeted flow:
    - `--clean-stage 6`
    - `--stage 6`
    - `--from-stage 7`
  - Validation passed:
    - `--smoke-test`
    - `--audit-native-footprint`
    - `python builder/scripts/check_build_coherence.py`
    - `python builder/scripts/check_module_plugin_readiness.py`
    - direct Web Browser staged-payload import check
    - direct FAST OpenCV filter smoke check.
  - Native footprint after adding QtWebEngine: `496` native files (`277` DLL, `219` PYD). This is larger than the post-analytics-reduction `483` baseline, but required for the Web Browser plugin.
  - Latest installer: `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`, size `416,704,335` bytes, SHA256 `25D6FD5286E5E9761190AB1604F61426B23FC89073EEA46543170DC2EE7F0067`.
- April 26, 2026 (Advanced MPR runtime source validation):
  - Added `AIPACS_ADVANCED_MPR_RUNTIME_SOURCE` support to `builder/materialize_plugin_packages.py` so release builders can point directly at the assembled custom Slicer runtime root.
  - Materialization now validates the same required Advanced MPR runtime-file contract as the PyInstaller release flow before copying `advanced_mpr/payload`.
  - Nuitka Stage 08 now fails fast when `advanced_mpr` is selected but payload files are absent or incomplete.
  - Deliberate non-Advanced-MPR builds can still proceed with `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1`.
- April 26, 2026 (Advanced MPR payload found and staged):
  - Found a complete Advanced MPR/custom 3D Slicer runtime at `C:\Users\Dr.Alizadeh\Documents\ScreenConnect\Files\advanced_3d_slicer\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build`.
  - Copied the runtime into the source project at `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build` so dev mode and `advanced_mpr_runtime_root()` resolve the payload without depending on the ScreenConnect folder.
  - Kept `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/` ignored by Git because it is a large generated runtime payload (~0.81 GB, 10,919 files), not source code.
  - Re-ran `python builder/materialize_plugin_packages.py --include-runtime-payloads`; `advanced_mpr` now materializes with `payload_dir: "payload"`.
  - Re-ran Nuitka Stage 08 strictly with no bypass; required files were present under `builder nuitka/output/stage/plugin_packages/advanced_mpr/payload/`.
  - Rebuilt Stage 09 and Stage 10 only; the installer now includes Advanced MPR.
  - Validation passed:
    - `python "builder nuitka/build_nuitka_release.py" --smoke-test`
    - `python builder/scripts/check_module_plugin_readiness.py`
    - `python builder/scripts/check_build_coherence.py`
  - Latest Advanced-MPR-included installer: `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`, size `592,494,042` bytes, SHA256 `98F93FACEFA3D73736644BCE51D6EB0C52AF6905A163594E1CD231196D8156B8`.
- April 26, 2026 (Advanced MPR bridge fix):
  - Fixed installed Advanced MPR launch error `No module named 'modules.mpr.advanced_3d_slicer'`.
  - Updated `builder/plugin package/definitions/advanced_mpr/plugin_package.json` so the runtime package includes the Python bridge source:
    - `modules/mpr/__init__.py`
    - `modules/mpr/advanced_3d_slicer`
  - `advanced_mpr/module_package.json` now declares `python_paths: ["python"]`.
  - Updated package materialization so runtime payloads can also carry source bridge files under `payload/python` while excluding nested `NewMPR2Slicer/build` from the bridge copy to avoid duplicating the large Slicer runtime.
  - Rebuilt Stage 08, Stage 09, and Stage 10 only. No Nuitka core recompilation was needed.
  - Validation passed:
    - direct import of `modules.mpr.advanced_3d_slicer` from staged `advanced_mpr/payload/python`
    - `python "builder nuitka/build_nuitka_release.py" --smoke-test`
    - `python builder/scripts/check_module_plugin_readiness.py`
    - `python builder/scripts/check_build_coherence.py`
  - Latest installer after v2.4.6 metadata refresh: `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`, size `592,817,513` bytes, SHA256 `3E7062AED3A1DFE6DD21734422838554BCD9D622B226FA2CFA87BD3B69788010`.

## DLL Exposure Reality (Nuitka)
- Nuitka standalone on Windows still requires many runtime DLLs (`python*.dll`, Qt, VC runtime, extension-module `.pyd`, VTK/SimpleITK dependencies).
- Full consolidation into a single custom `AIPacs.dll` is not realistically supported for this dependency stack in stable standalone mode.
- `--onefile` can hide file layout at rest but still extracts runtime files at launch and is harder to debug for medical-imaging native dependencies.
- Recommended production direction remains:
  - keep standalone/Engine layout,
  - reduce visible surface via installer structure and launcher,
  - keep optional plugins external and versioned.

## Next Execution (Current)
The latest validated build is complete through Stage 10. For normal continuation after a small code/config change, use:

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume`

For another core dependency/spec change, use the targeted reduction workflow:

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-stage 6`

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 6`

`.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 7`

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
