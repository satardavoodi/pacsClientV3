# Build Systems Index

> Documentation map: [`../../docs/release-and-build/README.md`](../../docs/release-and-build/README.md).
>
> **Canonical current route:** start at [`../../BUILD.md`](../../BUILD.md). It is
> the only authoritative procedure for the combined PyInstaller + Nuitka,
> Eagle Eye + Standard + ARM64-emulated release matrix. Commands below describe
> backend internals and historical recovery only; do not use them as an alternate
> final-release workflow.
> A full build also requires the Git synchronization receipt created through
> [`../../RELEASE.md`](../../RELEASE.md); backend scripts are not a substitute.

This repository has **two separate build backends** coordinated by one release
workflow. They are not interchangeable and they do not share output folders or
command-line flags.

**2026-08-31 PyInstaller output policy:** the default now prepares Eagle Eye,
Standard and ARM compatibility outputs with isolated payloads. See
[distribution editions and offline assets](DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md)
for cached inputs, commands, size gates, no-publish behavior, and release blockers.

## 1. PyInstaller Build Chain

Use this when you want the current Windows release pipeline based on the Python/PyInstaller builder.

- Builder root: `builder/`
- Backend implementation entry points (diagnostics only; the official entry is
  `tools/build/build_local_candidate.py` from root `BUILD.md`):
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

Historical/direct backend commands are intentionally omitted from this index.
Release-capable direct invocation is authority-gated and will fail in the mutable
developer checkout. Use the internal snapshot commands in root `BUILD.md` for a
diagnostic backend run.

Backend flags are documented for implementation diagnosis below. Copy the full
internal-snapshot command from root `BUILD.md`; it supplies the external build
interpreter, verified asset path, and mandatory `--internal-build` marker.

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

The commands that originally accompanied this historical v2.4.7 section are no
longer valid release entry points. Use the lane and snapshot commands in root
`BUILD.md`. Inside an approved snapshot, the backend must still produce `stage`,
`packages`, and `updates`; file-lock and resume notes below remain useful for
diagnosis.

Operational guardrails:

- Ensure `builder/output/.build_release.lock` is removed at the end of a successful run.
- If `dist` exists but `updates` is missing, treat the backend as incomplete and
  follow the recovery route in root `BUILD.md`; do not promote the partial output.
- Always derive version from `pyproject.toml`; do not hardcode release version in builder scripts.
