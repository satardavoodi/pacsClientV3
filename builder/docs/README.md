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
  - `WINDOWS_RELEASE_FLOW.md`
  - `BUILD_CHECKLIST.md`
  - `INSTALLER_QA_CHECKLIST.md`

Typical commands:

```powershell
.\.venv_build\Scripts\python.exe build.py
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller
.\.venv_build\Scripts\python.exe build.py --skip-installer-compile
.\.venv_build\Scripts\python.exe build.py --clean-build
```

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
- Canonical doc:
  - `NUITKA_BUILD_PLAN.md`

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