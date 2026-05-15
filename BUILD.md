# Building AIPacs (Windows Release Guide)

This guide walks you through building AIPacs from a fresh clone on any Windows PC.

## Quick Start

```powershell
# 1. Automated build environment setup (one-time, works on any PC)
.\setup_build_env.ps1

# 2. Build the Windows installer
.venv_build\Scripts\python build.py

# Installer output: builder/output/installer/ai-pacs installer v<version>.exe
```

That's it! The build is self-contained and reproducible on any Windows PC with Python 3.13.5+.

---

## System Requirements

- **Windows 10/11** (64-bit)
- **Python 3.13.5+** (auto-detected by `setup_build_env.ps1`)
- **~15 GB free disk space** (for build artifacts and dependencies)
- **~1-2 hours build time** (PyInstaller compilation can be slow)

Python does NOT need to be installed in `PATH` — the setup script will find it.

---

## Step-by-Step Build Process

### 1. Clone the Repository

```powershell
git clone -b matab-conservative https://github.com/Vahid-INO/ai-pacs.git
cd ai-pacs
```

**Branch note:** `matab-conservative` is the stable release branch. Do NOT switch to `main` unless explicitly instructed.

### 2. Set Up Build Environment

#### Automated (Recommended)

```powershell
.\setup_build_env.ps1
```

This script:
- Locates Python 3.13.5+ on your system
- Creates isolated build venv at `.venv_build`
- Installs pinned build toolchain from `builder/requirements/build_requirements.txt`
- Installs runtime dependencies from `requirements-core.txt`
- Verifies PyInstaller, PySide6, VTK, and other critical packages

**To rebuild from scratch:**
```powershell
.\setup_build_env.ps1 -Force
```

#### Manual Alternative

```powershell
python -m venv .venv_build
.venv_build\Scripts\python -m pip install --upgrade pip
.venv_build\Scripts\python -m pip install -r builder\requirements\build_requirements.txt
.venv_build\Scripts\python -m pip install -r requirements-core.txt
```

### 3. Execute the Build

#### Default Build (Fast, Recommended)

```powershell
$env:PYTHONUTF8='1'
.venv_build\Scripts\python build.py
```

This creates an installer **without** the optional Advanced MPR module (the custom 3D Slicer viewer). Advanced MPR files are excluded from git because they're ~500 MB and built separately.

**Output:**
- `builder/output/installer/ai-pacs installer v3.0.2.exe` (684 MB)
- `builder/output/installer/INSTALL_NOTES.txt` (installation instructions)
- `builder/output/installer/SHA256.txt` (installer hash)

#### Build WITH Advanced MPR (Advanced Users Only)

Advanced MPR is optional. If you have a pre-built Slicer runtime, you can include it:

```powershell
$env:AIPACS_ADVANCED_MPR_RUNTIME_SOURCE='C:\path\to\built\advanced_mpr'
$env:PYTHONUTF8='1'
.venv_build\Scripts\python build.py
```

For details on assembling the Advanced MPR runtime, see [Advanced MPR Build/Runtime Integration](builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md).

### 4. Resume a Broken Build

If the build is interrupted (terminal crash, VS Code restart, OOM):

```powershell
# Show current progress
python builder/run_resumable_build.py --status

# Resume from last incomplete stage
python builder/run_resumable_build.py

# Reuse existing PyInstaller output (skip recompilation)
python builder/run_resumable_build.py --reuse-dist
```

For more options, see [WINDOWS_RELEASE_FLOW.md](builder/docs/WINDOWS_RELEASE_FLOW.md).

---

## Build Outputs

After a successful build, you'll find:

```
builder/output/installer/
├── ai-pacs installer v3.0.2.exe     ← Main installer
├── ai-pacs installer.exe             ← Alias (same as above)
├── INSTALL_NOTES.txt                 ← Installation guide
├── INSTALL_NOTES_FA.txt              ← Farsi installation guide
├── SHA256.txt                         ← Hash for integrity verification
└── SHA256_FA.txt                      ← Farsi hash notes
```

**Verify installer integrity:**
```powershell
$hash = (Get-FileHash 'builder/output/installer/ai-pacs installer v3.0.2.exe' -Algorithm SHA256).Hash
Write-Output $hash
# Compare with SHA256.txt
```

---

## Build System Architecture

This repository uses **two independent build systems**:

### PyInstaller Builder (Default, Recommended)
- **Location:** `builder/`
- **Entry point:** `build.py`
- **Use case:** Production release builds
- **Spec file:** `builder/spec/appA_workstation.spec`
- **Installer:** Inno Setup (`builder/installer/AIPacs_Setup.iss`)

### Nuitka Builder (Alternative)
- **Location:** `builder nuitka/`
- **Entry point:** `builder nuitka/build_nuitka_release.py`
- **Use case:** Staged/resumable experimental builds
- **Status:** Optional, not used for default releases

**For this guide, always use the PyInstaller builder.** Do NOT use `build_nuitka.bat` unless explicitly instructed.

---

## Environment Variables (All Optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AIPACS_ALLOW_MISSING_ADVANCED_MPR` | unset | Set to `1` to allow builds without Advanced MPR runtime |
| `AIPACS_ADVANCED_MPR_RUNTIME_SOURCE` | unset | Path to pre-built Advanced MPR runtime |
| `PYTHONUTF8` | unset | Set to `1` for UTF-8 console (recommended on Windows) |
| `AIPACS_FAST_RENDER_CLOCK_EXPERIMENT` | unset | Set to `1` to enable FAST render clock diagnostics (dev only) |

---

## Understanding Advanced MPR (Optional Module)

Advanced MPR is a custom 3D viewer based on Slicer. It is:

- **Optional** — the base AIPacs install works perfectly without it
- **Large** — runtime is ~500 MB, so it's excluded from git
- **Separately Assembled** — built from the Slicer custom app source

**Availability:**
- In a fresh clone, Advanced MPR **source files are present** (`modules/mpr/advanced_3d_slicer/**`)
- In a fresh clone, Advanced MPR **runtime build is missing** (listed in `.gitignore` line 77)

**Default behavior:**
- The build system auto-detects the missing runtime
- Build succeeds without Advanced MPR (creates a fully functional base install)
- If you need Advanced MPR, you must provide the pre-built runtime via `AIPACS_ADVANCED_MPR_RUNTIME_SOURCE`

For full details, see [Advanced MPR Build/Runtime Integration](builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md).

---

## Troubleshooting

### "Python 3.13.5+ not found"
The setup script looks for Python in several places:
1. `py -3.13` (Windows Python launcher)
2. `py -3` (any Python 3.x)
3. `python3.13`, `python3`, `python` in PATH

If none found, install Python from [python.org](https://www.python.org/downloads/) and ensure it's in your PATH, or use the Windows Python launcher.

### "PyInstaller failed with permission denied"
The `.venv_build` directory may be locked by an antivirus or running process. Try:
```powershell
.\setup_build_env.ps1 -Force
```

### "Installer executable is 0 bytes"
The Inno Setup compiler may have failed silently. Check `builder/logs/` for error messages.

### Build output disappears after Ctrl+C
PyInstaller can leave partial files. Use `--clean-only` to reset:
```powershell
python build.py --clean-only
```

### "ModuleNotFoundError" during build
Ensure `requirements-core.txt` and `builder/requirements/build_requirements.txt` are fully installed in `.venv_build`:
```powershell
.venv_build\Scripts\python -m pip install --upgrade -r builder/requirements/build_requirements.txt
```

---

## Development vs Release

**To run for development (no build):**
```powershell
.\setup_env.ps1              # Creates .venv for runtime
.\run_app.ps1                # Runs main.py with diagnostics
```

**To build a release installer:**
```powershell
.\setup_build_env.ps1        # Creates .venv_build for build tools
python build.py              # Invokes PyInstaller + Inno Setup
```

These use **separate virtual environments** so building doesn't affect development.

---

## What's Next After Building?

1. **Verify the installer:**
   - Check file size (~684 MB)
   - Verify SHA256 hash matches `builder/output/installer/SHA256.txt`

2. **Test on another machine:**
   - Copy the `.exe` to a test PC
   - Run the installer
   - Verify the app starts and all features work

3. **Deploy:**
   - Distribute the installer to end users
   - Installer places files in `C:\Program Files\AIPacs` and config in `C:\ProgramData\AIPacs`

---

## Related Documentation

- [WINDOWS_RELEASE_FLOW.md](builder/docs/WINDOWS_RELEASE_FLOW.md) — Detailed build flow and resumable stages
- [BUILD_DOCUMENT.md](builder/docs/BUILD_DOCUMENT.md) — Dependency audit and packaging details
- [ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md](builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md) — Advanced MPR assembly and validation
- [docs/development/setup-and-tooling.md](docs/development/setup-and-tooling.md) — Development environment setup
- [RELEASE_NOTES.md](docs/releases/RELEASE_NOTES.md) — Current release notes

---

## Summary

✅ **This repository is fully self-contained and reproducible on any Windows PC.**

A fresh clone requires only:
1. Python 3.13.5+ installed
2. Running `setup_build_env.ps1` (one command)
3. Running `build.py` (one command)

No manual file copying, no external dependencies, no special setup. The build process is deterministic and works the same way on any Windows machine.

**Last updated:** 2026-05-13 | **Version:** 3.0.2
