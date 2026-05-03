# Build Systems Index

This repository has **two separate build systems**. They are not interchangeable and they do not share the same entry scripts, output folders, or command-line flags.

## 1. PyInstaller Build Chain

Use this when you want the current Windows release pipeline based on the Python/PyInstaller builder.

- Builder root: `builder/`
- Canonical entry points:
  - `build.bat`
  - `build.py`
  - `builder/build_release.py`
- Main spec / installer files:
  - `builder/spec/appA_workstation.spec`
  - `builder/installer/AIPacs_Setup.iss`
- Main output root: `builder/output/`
- Canonical docs:
  - `BUILD_DOCUMENT.md`
  - `ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md`
  - `WINDOWS_RELEASE_FLOW.md`
  - `BUILD_CHECKLIST.md`
  - `INSTALLER_QA_CHECKLIST.md`

Typical commands:

```powershell
.\.venv_build\Scripts\python.exe build.py
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller
.\.venv_build\Scripts\python.exe build.py --skip-installer-compile
.\.venv_build\Scripts\python.exe build.py --clean-build
.\.venv_build\Scripts\python.exe builder\run_resumable_build.py
```

For long-running or unstable sessions, prefer `builder\run_resumable_build.py` so stage 1 (dist/stage/packages/updates) and stage 2 (installer compile) can resume independently.

## 2. Nuitka Build Chain

Use this only when you want the staged resumable Nuitka builder.

- Builder root: `builder nuitka/`
- Canonical entry points:
  - `build_nuitka.bat`
  - `build_nuitka_release.bat`
  - `builder nuitka/build_nuitka_release.py`
- Main config / installer files:
  - `builder nuitka/nuitka_build_config.py`
  - `builder nuitka/installer/AIPacs_Nuitka_Setup.iss`
- Main output root: `builder nuitka/output/`
- Canonical docs:
  - `NUITKA_BUILD_PLAN.md`
  - `NUITKA_BUILD_AGENT_HANDOFF.md`

Typical commands:

```powershell
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 3
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 2
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --smoke-test
```

## Rule For Humans And AI Agents

- If the task mentions `build.py`, `build.bat`, `builder/spec/appA_workstation.spec`, `builder/output/`, or PyInstaller, work in `builder/` and use PyInstaller commands only.
- If the task mentions `build_nuitka`, `builder nuitka/`, stages, checkpoints, `build_state.json`, or `builder nuitka/output/`, work in `builder nuitka/` and use Nuitka commands only.
- Do not mix `builder/` flags with `builder nuitka/` commands.
- Do not write PyInstaller troubleshooting into the Nuitka plan, and do not write Nuitka recovery steps into the PyInstaller build document unless explicitly cross-referencing the other build system.

## Current Python Build Structure (v2.4.8c)

The production release contract for the Python/PyInstaller chain is:

1. Source of truth
- Version from `pyproject.toml` only.
- Build orchestration from `builder/build_release.py`.

2. Bundle layout
- `builder/output/dist/AIPacs/AIPacs.exe`
- `builder/output/dist/AIPacs/engine/` (PyInstaller runtime payload)

3. Staging/layout outputs
- `builder/output/stage/`
- `builder/output/packages/`
- `builder/output/updates/`

4. Installer outputs
- `builder/output/installer/ai-pacs installer.exe`
- `builder/output/installer/ai-pacs installer v<version>.exe`

5. Optional module payloads
- Built from `builder/plugin package/definitions/*/plugin_package.json`
- Materialized to `builder/plugin package/packages/*`
- Installed runtime roots under ProgramData and LocalAppData must satisfy runtime marker checks.

## No-Regression Release Gates (Mandatory)

Before marking any release complete, pass all gates below.

1. Builder chain gate
- Run PyInstaller chain only for Python release builds.
- Do not substitute Nuitka commands or flags.

2. Runtime marker gate (Advanced MPR)
- Required markers in at least one startup script candidate per runtime root:
  - `_REMOTE_SERVER_STARTED`
  - `NEWMPR2_REMOTE_PORT`
  - `start_remote_command_server`

3. Source/mirror/dist parity gate
- For every changed runtime-sensitive module, verify parity across:
  - source (`modules/...`)
  - plugin payload mirror (`builder/plugin package/packages/.../payload/python/modules/...`)
  - built dist (`builder/output/dist/AIPacs/engine/modules/...`)

4. Post-install runtime gate
- Validate installed launch-critical files under:
  - `C:/Program Files/AIPacs/engine/...`
  - `C:/ProgramData/AIPacs/module_packages/...`
  - `%LOCALAPPDATA%/AIPacs/modules_runtime/...`

5. Clinical-view consistency gate (FAST viewer)
- During wheel and drag stack interaction, filtered appearance must match settled appearance.
- Sync/reference-line slice selection must reuse cached geometry when available.

If any gate fails, treat the release as blocked.

## Regression Guardrails (v2.4.7)

The stable reference for build structure is the v2.4.6 backup snapshot under `backups/v2.4.6_2026-04-27_081245_full/`.

When validating a new release build, treat this as the minimum expected output structure:

- `builder/output/dist/`
- `builder/output/stage/`
- `builder/output/packages/`
- `builder/output/updates/`
- `builder/output/installer/` (when installer compilation is enabled)

Recommended deterministic validation flow for CI/manual/AI agents:

1. Build core bundle (or reuse existing dist):

```powershell
.\.venv_build\Scripts\python.exe build.py
```

2. Verify post-build structure without installer variability:

```powershell
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller --skip-installer-compile
```

This command must produce `stage`, `packages`, and `updates` from the current `dist` bundle.

3. Compile installer after the above succeeds:

```powershell
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller
```

If installer compilation fails with file-in-use (`Error 32`) on `builder/output/installer/ai-pacs installer.exe`, clear the stale lock holder (typically a stuck `ISCC.exe`) and rerun step 3.

Operational guardrails:

- Ensure `builder/output/.build_release.lock` is removed at the end of a successful run.
- If `dist` exists but `updates` is missing, rerun `--skip-pyinstaller --skip-installer-compile` before treating the build as complete.
- Always derive version from `pyproject.toml`; do not hardcode release version in builder scripts.
