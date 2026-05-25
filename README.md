# AIPacs

Stable release: `v3.0.6` (`2026-05-18`)

Modular DICOM workstation for viewing, download orchestration, printing, education, and AI-assisted workflows.

## Quick Start

**To build a Windows installer:**
```powershell
.\setup_build_env.ps1     # One-time setup on any Windows PC
python build.py           # Builds installer automatically
```

See [BUILD.md](BUILD.md) for detailed instructions, troubleshooting, and build customization options.

**To run for development:**
```powershell
.\setup_env.ps1           # One-time setup
.\run_app.ps1             # Runs the app with terminal logging
```

See [Development Setup](docs/development/setup-and-tooling.md) for more details.

## Canonical Documentation

- [Repository Guide](docs/README.md)
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

Windows release build:

```powershell
python -m venv .venv_build
.\.venv_build\Scripts\python -m pip install -r builder\requirements\build_requirements.txt
.\.venv_build\Scripts\python -m pip install -r requirements-core.txt
.\.venv_build\Scripts\python build.py
```

Build prerequisite for CPU-safe fallback (required for clean full builds):

```powershell
Get-ChildItem graphics_runtime\opengl32sw.dll, graphics_runtime\osmesa.dll, graphics_runtime\pipe_swrast.dll
```

If any of these files are missing, `build.py` can fail before packaging because software OpenGL fallback would be incomplete.

Primary build outputs land under `builder/output/`, including staged bundles and the installer when Inno Setup is available. Successful installer builds also emit `INSTALL_NOTES*.txt` and `SHA256*.txt` under `builder/output/installer/`.

Build stability guardrail (regression check): after any release build, verify the output structure includes `dist`, `stage`, `packages`, and `updates` under `builder/output/`. If `updates` is missing, run:

```powershell
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller --skip-installer-compile
```

This revalidates publish/staging from the existing `dist` bundle and is the canonical non-installer completeness check.

If Inno Setup fails with `Error 32` on `builder/output/installer/ai-pacs installer.exe`, stop any stale `ISCC.exe` process and rerun:

```powershell
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller
```

The Windows installer is prepared for deployment on other PCs. In `Custom` mode it asks which optional modules should be installed on that workstation, stores the selection in `installation_profile.json`, and uses a GPU probe plus runtime fallback logic so unsupported systems can still run with CPU-safe software OpenGL.
