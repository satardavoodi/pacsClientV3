# AIPacs

Stable release: `v2.3.0` (`2026-04-04`)

Modular DICOM workstation for viewing, download orchestration, printing, education, and AI-assisted workflows.

## Canonical Documentation

- [Repository Guide](docs/README.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Repository Layout](docs/architecture/repository-layout.md)
- [Module Catalog](docs/modules/README.md)
- [Development Setup](docs/development/setup-and-tooling.md)
- [Current Release Notes](docs/releases/RELEASE_NOTES.md)
- [Version 2.3.0 Release Notes](docs/releases/VERSION_2.3.0_RELEASE.md)
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

- Viewer, fast path: `PacsClient/pacs/patient_tab/viewers/lightweight_2d_pipeline.py`
- Viewer, advanced path: `PacsClient/pacs/patient_tab/viewers/viewer_2d.py`
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

Primary build outputs land under `builder/output/`, including staged bundles and the installer when Inno Setup is available. Successful installer builds also emit `INSTALL_NOTES*.txt` and `SHA256*.txt` under `builder/output/installer/`.

The Windows installer is prepared for deployment on other PCs. In `Custom` mode it asks which optional modules should be installed on that workstation, stores the selection in `installation_profile.json`, and uses a GPU probe plus runtime fallback logic so unsupported systems can still run with CPU-safe software OpenGL.
