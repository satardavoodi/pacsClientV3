# PyInstaller Version Management for AIPacs Builds

**Document Version**: v2.5.4  
**Last Updated**: 2026-05-12  
**Applies To**: PyInstaller 6.x builds (AIPacs v2.5.4+)

## Problem Statement

The AIPacs build pipeline uses **two separate Python virtual environments** with potentially different PyInstaller versions:

- **`.venv_build`** — used by `builder/build_release.py` (PyInstaller orchestration, spec loading)
- **`.venv`** — development environment (testing, debugging)

When these environments have **different PyInstaller versions**, the bundled application crashes at runtime with:

```
AttributeError: module 'pyimod02_importers' has no attribute 'PyiFrozenImporter'
```

### Why This Happens

Different PyInstaller versions use different loader/runtime hook implementations:

- **PyInstaller 6.11.1** defines `PyiFrozenImporter` (older style)
- **PyInstaller 6.20.0** defines `PyiFrozenFinder` (newer style)

The build process bundles **runtime hooks** (e.g., `pyi_rth_pkgutil.py`) from one PyInstaller version, but when the `.venv` has a different version, the bundled code calls APIs that don't exist in the actual runtime.

### Symptom Recognition

Users see this error during app startup (or first import of affected modules):

```
Traceback (most recent call last):
  File "main.py", line XX, in <module>
    ...
AttributeError: module 'pyimod02_importers' has no attribute 'PyiFrozenImporter'
```

The error appears as a **silent crash** with no clear indication of what went wrong.

## Solution: Version Parity

### 1. Check Current Versions

To diagnose a version mismatch, run:

```powershell
# Check .venv_build version
.venv_build\Scripts\python.exe -c "import PyInstaller; print(f'PyInstaller version: {PyInstaller.__version__}')"

# Check .venv version (for reference)
.venv\Scripts\python.exe -c "import PyInstaller; print(f'PyInstaller version: {PyInstaller.__version__}')" 2>$null || Write-Host ".venv does not have PyInstaller"
```

Both should report the **same version number**.

### 2. Fix Version Mismatch

If versions differ, update the **build venv** to match:

```powershell
# Install the same PyInstaller version that's pinned in requirements-dev.txt
$version = & .venv\Scripts\python.exe -c "import PyInstaller; print(PyInstaller.__version__)"
Write-Host "Installing PyInstaller $version in .venv_build..."
.venv_build\Scripts\pip.exe install --force-reinstall "PyInstaller==$version"
```

Alternatively, if `.venv` doesn't have PyInstaller (dev-only setup):

```powershell
# Use the version pinned in builder/requirements/build_requirements.txt
.venv_build\Scripts\pip.exe install -r builder\requirements\build_requirements.txt --force-reinstall
```

## Prevention: Build-Time Enforcement

**As of v2.5.4**, the build system includes **automatic detection and correction**:

1. **Version Detection** (`builder/build_release.py`, lines ~95-102)
   - On every build, the script reads the current `.venv_build` PyInstaller version
   - Compares against a cached marker file (`.build/.pyinstaller_version`)

2. **Auto-Clean on Mismatch** (`builder/build_release.py`, lines ~1170-1182)
   - If cached version ≠ current version, forces `--clean-build`
   - Ensures all bootstrap and runtime hooks are regenerated with the correct PyInstaller version

3. **Marker Persistence** (`builder/build_release.py`, lines ~118-121)
   - After successful PyInstaller build, the current version is written to `.build/.pyinstaller_version`
   - Next build compares against this marker

### Build Messages

During a build with version mismatch, you'll see:

```
[WARN] PyInstaller cache version mismatch detected: cached=6.11.1, current=6.20.0.
[WARN] Forcing --clean-build to avoid mixed bootstrap/runtime artifacts.
```

This is **intentional and safe** — the clean build ensures consistency.

## Long-Term Prevention: Environment Setup

To avoid this on multi-PC deployments, follow these setup rules:

### Rule 1: Sync Pinned Versions

Both `builder/requirements/build_requirements.txt` and `requirements-dev.txt` should specify the **same PyInstaller version**:

```txt
# builder/requirements/build_requirements.txt
PyInstaller==6.11.1

# requirements-dev.txt
PyInstaller==6.11.1  # Must match build_requirements.txt
```

### Rule 2: Setup Scripts Must Enforce Parity

The setup scripts `setup_build_env.ps1` and `setup_env.ps1` install from pinned requirements:

```powershell
# setup_build_env.ps1 (creates .venv_build)
.venv_build\Scripts\pip.exe install -r builder\requirements\build_requirements.txt

# setup_env.ps1 (creates/updates .venv)
.venv\Scripts\pip.exe install -r requirements-dev.txt
```

**Important**: Both must install from **their respective** pinned requirements files (which have matching PyInstaller versions).

### Rule 3: Force Reinstall on Version Update

When updating PyInstaller version globally, regenerate the venvs from scratch:

```powershell
# Remove old environments
Remove-Item .venv_build -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .venv -Recurse -Force -ErrorAction SilentlyContinue

# Recreate from pinned requirements
& setup_build_env.ps1
& setup_env.ps1
```

**Note**: `pip install --upgrade` may update to a different minor version than pinned. Use `--force-reinstall` to lock to exact version.

### Rule 4: CI/CD Pre-Build Validation

On continuous integration or multi-PC deployment, validate version parity before building:

```powershell
$build_version = & .venv_build\Scripts\python.exe -c "import PyInstaller; print(PyInstaller.__version__)"
$dev_version = & .venv\Scripts\python.exe -c "import PyInstaller; print(PyInstaller.__version__)"

if ($build_version -ne $dev_version) {
    Write-Error "PyInstaller version mismatch: .venv_build=$build_version, .venv=$dev_version"
    exit 1
}

Write-Host "✓ PyInstaller versions match: $build_version"
```

## Installer Artifact Cleanup

**As of v2.5.4**, the build system also cleans up old build artifacts:

- **Keeps**: `ai-pacs installer.exe` (primary) and `ai-pacs installer v<version>.exe` (versioned)
- **Removes**: `ai-pacs installer build YYYYMMDD-HHMMSS.exe` (intermediate timestamps)

This reduces installer folder size and removes ambiguity about which file is the deliverable.

## Appendix: Version History

| PyInstaller Version | AIPacs Version | Notes |
|-------------------|-----------------|-------|
| 6.11.1 | v2.5.3 and earlier | Uses `PyiFrozenImporter` |
| 6.20.0 | v2.5.4+ optional | Uses `PyiFrozenFinder` (newer) |
| (locked at build time) | v2.5.4+ | Auto-detection enforced; mismatch triggers clean build |

## See Also

- [Build System Architecture](./BUILD_SYSTEM.md)
- [VERSION_2.5.4_RELEASE.md](../releases/VERSION_2.5.4_RELEASE.md) — v2.5.4 release notes
- `.github/copilot-instructions.md` — project runtime instructions
