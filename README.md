# AIPacs

Current project version: `v3.6.5`. Production acceptance is tracked separately
in the current release and deployment records.

Modular DICOM workstation for viewing, download orchestration, printing, education, and AI-assisted workflows.

## Quick Start

**To build a Windows installer:**

Start with the [Release and Build Documentation Map](docs/release-and-build/README.md),
then prepare the supported toolchain if needed:

```powershell
.\setup_build_env.ps1     # One-time setup on any Windows PC
```

Then follow [BUILD.md](BUILD.md). It is the authoritative human/AI procedure and the
only supported route for the current PyInstaller + Nuitka six-installer matrix.
Before a full release build, follow [RELEASE.md](RELEASE.md) to commit, tag, push,
and verify the exact same source revision across all required Git repositories.

**To run for development:**
```powershell
.\setup_env.ps1           # One-time setup
.\run_app.ps1             # Runs the app with terminal logging
```

See [Development Setup](docs/development/setup-and-tooling.md) for more details.

## Canonical Documentation

- [Release and Build Documentation Map](docs/release-and-build/README.md)
- [Repository Guide](docs/README.md)
- [Git Release Workflow](RELEASE.md)
- [Build and Installer Workflow](BUILD.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Repository Layout](docs/architecture/repository-layout.md)
- [Module Catalog](docs/modules/README.md)
- [Development Setup](docs/development/setup-and-tooling.md)
- [Current Release Notes](docs/releases/RELEASE_NOTES.md)
- [Version 3.0.6 Release Notes](docs/releases/VERSION_3.0.6_RELEASE.md)
- [Version 3.0.3 Release Notes](docs/releases/VERSION_3.0.3_RELEASE.md)
- [Version 2.5.4 Release Notes](docs/releases/VERSION_2.5.4_RELEASE.md)
- [Version 2.4.7c Release Notes](docs/releases/VERSION_2.4.7c_RELEASE.md)
- [Version 2.3.7 Release Notes](docs/releases/VERSION_2.3.7_RELEASE.md)
- [Version 2.3.6 Release Notes](docs/releases/VERSION_2.3.6_RELEASE.md)
- [Version 2.3.5 Release Notes](docs/releases/VERSION_2.3.5_RELEASE.md)
- [Version 2.3.4 Release Notes](docs/releases/VERSION_2.3.4_RELEASE.md)
- [Version 2.2.7 Release Notes](docs/releases/VERSION_2.2.7_RELEASE.md)
- [Windows Release Flow](builder/docs/WINDOWS_RELEASE_FLOW.md)
- [Plugin Package Workspace](builder/plugin%20package/README.md)

## Runtime Areas

- `main.py`: desktop application entrypoint
- `PacsClient/`: workstation shell, viewer stack, download manager integration, shared utilities
- `EchoMind/`: AI assistant and secretary orchestration
- `printing/`: filming and print workflow
- `database/`: schema migration helpers and stored report data
- `config/`: runtime configuration files
- `tests/`: focused automated tests

## Module Map

- Viewer, fast path: `modules/viewer/fast/lightweight_2d_pipeline.py`
- Viewer, advanced path: `modules/viewer/advanced/viewer_2d.py`
- Zeta Download Manager: `PacsClient/zeta_download_manager/`
- Zeta MPR and orthogonal MPR: `PacsClient/pacs/patient_tab/zeta mpr/`, `PacsClient/pacs/patient_tab/orthogonal_mpr/`
- Advanced imaging and AI tools: `PacsClient/pacs/patient_tab/ui/ai_module_ui/`
- Education: `PacsClient/pacs/education/`, `Education/`
- Web viewing: `modules/web_browser/`
- Printing: `printing/`
- EchoMind assistant: `EchoMind/`

## Project Conventions

- Authoritative project documentation lives under `docs/`.
- Historical and version-specific notes live under `docs/archive/`.
- Primary dependency files are `requirements-core.txt` and `requirements-dev.txt`.
- `pyproject.toml` is the metadata and tooling entrypoint.
- Generated runtime output belongs in `generated-files/`, `logs/`, or ignored local storage paths, not the source tree.

## Install

Recommended PowerShell setup:

```powershell
.\setup_env.ps1
.\run_app.ps1
```

`run_app.ps1` now also mirrors terminal stdout/stderr to a timestamped **UTF-8** session file under `log/` and updates `log/latest_terminal_log.txt` so the newest console log is easy to find.

Quick lookup for the latest captured terminal session:

```powershell
.\tools\diagnostics\Get-LatestTerminalLog.ps1
.\tools\diagnostics\Get-LatestTerminalLog.ps1 -Tail
```

Manual runtime setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-core.txt
.\.venv\Scripts\python main.py
```

For development and tests:

```powershell
.\setup_env.ps1 -IncludeDev
.\.venv\Scripts\python -m pytest
```

## Build

Use [BUILD.md](BUILD.md). It defines machine bootstrap, source validation,
disposable fast lanes, the isolated full-matrix command, the two output folders,
all six filenames, expected sizes, content/hash/version checks, interruption
rules, and the production release gate. Backend-specific wrappers remain useful
for diagnosis but are not alternate release entry points.


---

## Recovery documentation

If projects, skills, MCP servers or agent configuration ever need to be reconstructed
(for example after switching Claude accounts), start here:

```text
Document Recovery Account Vahid
D:\_RECOVERY\Document Recovery Account Vahid.md
```

This project also has its own `RECOVERY.md` in its root.
<!-- added 2026-08-27 by environment recovery; nothing above this line was modified -->
