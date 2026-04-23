# Development Setup and Tooling

## Python Environment

Recommended PowerShell setup:

```powershell
.\setup_env.ps1
```

To include test and developer extras:

```powershell
.\setup_env.ps1 -IncludeDev
```

Manual setup:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-core.txt
```

For development and tests:

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Dependency Files

- `requirements-core.txt`: runtime dependencies
- `requirements-dev.txt`: developer extras layered on top of core
- `requirements.txt`: legacy combined list kept only for compatibility with older tooling
- `pyproject.toml`: project metadata plus tool configuration

## Common Commands

Run the desktop app:

```powershell
.\run_app.ps1
```

Or run the entrypoint directly:

```powershell
.venv\Scripts\python main.py
```

Run tests:

```powershell
.venv\Scripts\python -m pytest
```

Run the built-in test shortcut:

```powershell
.venv\Scripts\python main.py --run-tests
```

Run a Windows release build:

```powershell
# Preferred: use the build venv setup script (creates .venv_build with pinned toolchain)
.\setup_build_env.ps1
.venv_build\Scripts\python build.py
```

Or manually:

```powershell
python -m venv .venv_build
.venv_build\Scripts\python -m pip install -r builder\requirements\build_requirements.txt
.venv_build\Scripts\python -m pip install -r requirements-core.txt
.venv_build\Scripts\python build.py
```

You can also use `build.bat` from the repo root — it selects `.venv_build\Scripts\python.exe`
automatically when the build venv exists, and falls back to ambient Python with a warning.

Successful installer builds produce:

- `builder/output/installer/ai-pacs installer.exe`
- `builder/output/installer/ai-pacs installer v<version>.exe`
- `builder/output/installer/INSTALL_NOTES.txt`
- `builder/output/installer/SHA256.txt`

## GitHub Push Workflow

This repository is configured to push to GitHub over HTTPS. That avoids the SSH path that is currently unreliable on this machine.

For a stable push path inside VS Code, use `Terminal -> Run Task` and run one of these tasks:

- `GitHub: Check connection (auto)`
- `GitHub: Push current branch (dry-run)`
- `GitHub: Push current branch`

All three tasks call `tools/git/Push-GitHub.ps1`. In `Auto` mode the script tries a direct HTTPS connection first and falls back to a proxy only if you have configured one.

If GitHub only works through a proxy on your network, create `tools/git/github-network.local.json` from `tools/git/github-network.example.json` and set your proxy URL there. The local file is ignored by git so you only need to configure it once on this machine.

## Tooling Conventions

- `pyproject.toml` is the entrypoint for pytest and Ruff settings.
- `.editorconfig` defines basic formatting defaults across the repo.
- Keep new test files under `tests/` unless they are package-specific and benefit from local proximity.
- For `tools/` organization rules, lifecycle policy, and improvement plan, see `docs/development/tools-governance-and-roadmap.md`.

## Current Practical Rules

- Avoid adding new broad re-export patterns like `PacsClient.utils.__init__`.
- Prefer direct module imports over package-wide import hubs.
- Keep UI widgets thin when adding new features; put database access into repositories or services.
- Keep generated artifacts and temporary logs out of source directories.
