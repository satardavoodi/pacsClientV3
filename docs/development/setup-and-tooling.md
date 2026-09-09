# Development Setup and Tooling

For any Git publication or installer task, start at the
[release and build documentation hub](../release-and-build/README.md). This page
owns development-environment setup only; it is not an alternate release runbook.

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

Prepare the Windows build environment:

```powershell
.\setup_build_env.ps1
```

Do not run `build.py`, `build.bat`, `builder/build_release.py`, or the Nuitka
release stages directly from the developer checkout. For source tests, internal
packaging, or a full six-installer candidate, select the correct lane in
[`../../BUILD.md`](../../BUILD.md). A full candidate first requires the Git
publication receipt defined by [`../../RELEASE.md`](../../RELEASE.md).

Manual environment bootstrap, when the setup script itself is being diagnosed:

```powershell
python -m venv .venv_build
.venv_build\Scripts\python -m pip install -r builder\requirements\build_requirements.txt
.venv_build\Scripts\python -m pip install -r requirements-core.txt
```

The authoritative filenames, both output folders, metadata files, expected size
bands, and verification gates are listed in `BUILD.md`.

## GitHub Push Workflow

Versioned publication must follow [`../../RELEASE.md`](../../RELEASE.md). It
commits one reviewed revision, verifies every configured destination, pushes the
same SHA/tag to all required branches, reads them back, and creates the receipt
required by the build coordinator.

VS Code tasks that call `tools/git/Push-GitHub.ps1` are connectivity or
non-release feature-branch helpers only. The helper refuses live pushes to
`main` and `beta-version`; it cannot publish a versioned release.

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
