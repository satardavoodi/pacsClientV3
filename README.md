# AIPacs

Modular DICOM workstation for viewing, download orchestration, printing, education, and AI-assisted workflows.

## Canonical Documentation

- [Repository Guide](docs/README.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Repository Layout](docs/architecture/repository-layout.md)
- [Module Catalog](docs/modules/README.md)
- [Development Setup](docs/development/setup-and-tooling.md)
- [Current Release Notes](docs/releases/RELEASE_NOTES.md)
- [Windows Release Flow](builder/docs/WINDOWS_RELEASE_FLOW.md)

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
- Dependencies remain split across `requirements-core.txt` and `requirements-dev.txt`, with `pyproject.toml` acting as the tool and metadata entrypoint.
- Generated runtime output belongs in `generated-files/`, `logs/`, or ignored local storage paths, not the source tree.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-core.txt
.venv\Scripts\python main.py
```

For tests and tooling:

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```
