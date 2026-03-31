# Advanced 3D Slicer Module — Deployment & Setup Guide

> **Purpose:** This document ensures any developer can deploy, rebuild, or troubleshoot
> the AI-PACS Advanced Viewer (custom 3D Slicer) module without day-long discovery sessions.
>
> **Last updated:** 2026-03-11 — v0.1.0

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Directory Layout](#2-directory-layout)
3. [Runtime Requirements](#3-runtime-requirements)
4. [Quick Start: Fresh Machine Setup](#4-quick-start-fresh-machine-setup)
5. [Assembly Script: Building the Runtime](#5-assembly-script-building-the-runtime)
6. [Deploying to Another PC](#6-deploying-to-another-pc)
7. [Integration with Main PACS App](#7-integration-with-main-pacs-app)
8. [Known Issues & Fixes](#8-known-issues--fixes)
9. [Troubleshooting](#9-troubleshooting)
10. [Version Matrix](#10-version-matrix)
11. [File Manifest](#11-file-manifest)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│  AI-PACS Main App (PySide6)                              │
│                                                          │
│  patient_widget.py  ──→  slicer_launcher.py              │
│                          (QThread worker)                │
│                              │                           │
│                    ┌─────────┴─────────┐                 │
│                    │ Try TCP:47891     │ Launch subprocess│
│                    │ (remote command)  │ (new process)   │
│                    └─────────┬─────────┘                 │
└──────────────────────────────┼───────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │  Subprocess: AIPacsAdvancedViewer.exe      │
         │                                            │
         │  CTK Launcher (.exe + .ini)                │
         │      │                                     │
         │      ▼ sets PATH, PYTHONPATH, etc.         │
         │  bin/Release/AIPacsAdvancedViewer.exe      │
         │      │                                     │
         │      ▼ loads C++ modules                   │
         │  qt-loadable-modules/*.dll (49 modules)    │
         │      │                                     │
         │      ▼ runs --python-script                │
         │  startup_script.py                         │
         │      │                                     │
         │      ▼ loads DICOM, configures views       │
         │  4-up MPR layout with series data          │
         └────────────────────────────────────────────┘
```

**Key entities:**

| Component | Role |
|---|---|
| `slicer_launcher.py` | Main-app side: finds exe, manages prewarm, spawns worker thread |
| `launch_slicer.py` | Builds command, sets env vars, calls subprocess |
| `startup_script.py` | Runs inside Slicer: loads DICOM, sets layout, brands UI |
| CTK Launcher (.exe) | Sets DLL/Python paths from .ini, spawns real Slicer exe |
| `tools/slicer/assemble_slicer_runtime.py` | Build tool: creates portable runtime from SuperBuild |

**Communication:**
- PACS → Slicer: environment variables (`NEWMPR2_DICOM_DIR`, `NEWMPR2_SERIES_UID`, etc.)
- PACS → running Slicer: TCP JSON on `127.0.0.1:47891` (series switching)

---

## 2. Directory Layout

```
modules/mpr/advanced_3d_slicer/
├── __init__.py                     # Public API
├── slicer_launcher.py              # Main-app integration (QThread, prewarm)
├── README.md                       # Module overview
│
└── slicer_custom_app/
    ├── launch_slicer.py            # Exe finder, cmd builder, subprocess launcher
    ├── startup_script.py           # Runs inside Slicer (DICOM, views, branding)
    ├── unified_logging.py          # Geometry logging helpers
    ├── customize_slicer_app.py     # Build-time customization (pre-compile)
    ├── NewMPR2SlicerArgs.h         # C++ argument struct header
    ├── .gitignore                  # Excludes build/, logs/, __pycache__
    │
    ├── branding/                   # QSS, icons, colours
    │   ├── colors.json
    │   ├── NewMPR2Slicer.qss
    │   └── icons/
    │       ├── AIPacsAdvancedViewer.ico
    │       └── AIPacsAdvancedViewer.png
    │
    ├── docs/                       # ← YOU ARE HERE
    │   ├── DEPLOYMENT_GUIDE.md     # This file
    │   ├── DEPENDENCY_MANIFEST.md  # Full DLL/component inventory
    │   ├── BUILD_FROM_SOURCE.md    # SuperBuild instructions
    │   ├── launch_contract.md      # Interface contract (env vars, args)
    │   └── TROUBLESHOOTING.md      # Common problems & solutions
    │
    ├── logs/                       # Runtime logs (git-ignored)
    │
    └── NewMPR2Slicer/              # CMake SuperBuild project
        ├── CMakeLists.txt          # Fetches Slicer from GitHub
        ├── Applications/           # C++ app source (Main.cxx, MainWindow)
        ├── Modules/                # Scripted modules (Home, NewMPR2MPR)
        └── build/                  # ← ASSEMBLED RUNTIME (git-ignored, 842 MB)
            ├── AIPacsAdvancedViewer.exe
            ├── AIPacsAdvancedViewerLauncherSettings.ini
            ├── bin/                # Core DLLs + real exe
            ├── lib/                # Module DLLs
            ├── deps/               # External dependency DLLs
            ├── python-install/     # Embedded Python 3.12
            └── share/              # Certs, color tables
```

---

## 3. Runtime Requirements

### 3.1 The Assembled Build (842 MB)

The `NewMPR2Slicer/build/` directory is the **complete, self-contained runtime**.
It does NOT require any system-installed software to run. It bundles:

| Component | Version | Size | Source |
|---|---|---|---|
| 3D Slicer core | 5.11.0 (commit ae061ac) | 62 MB | `C:\S\NB\Slicer-build` |
| Qt5 | 5.15.2 (MSVC 2019 x64) | 181 MB | `C:\Qt\5.15.2\msvc2019_64` |
| Python | 3.12.10 | 314 MB | `C:\S\NB\python-install` |
| VTK | 9.x | 149 MB | `C:\S\NB\VTK-build` |
| ITK | — | 22 MB | `C:\S\NB\ITK-build` |
| DCMTK | 3.6.8 | 29 MB | `C:\S\NB\DCMTK-build` |
| CTK | — | 6 MB | `C:\S\NB\CTK-build` |
| PythonQt | — | 11 MB | `C:\S\NB\CTK-build\PythonQt-build` |
| TBB | — | 2 MB | `C:\S\NB\tbb-install` |
| OpenSSL | — | 4 MB | `C:\S\NB\OpenSSL-install` |
| Others (Teem, JsonCpp, SEM, LibArchive) | — | 4 MB | Various |
| **Total** | | **~842 MB** | |

### 3.2 Python Packages in Embedded Python

The embedded `python-install/` contains these site-packages:

| Package | Version | Purpose |
|---|---|---|
| numpy | 2.3.4 | Numerical arrays |
| scipy | 1.16.3 | Scientific computing |
| pydicom | 3.0.1 | DICOM file parsing |
| Pillow | 12.0.0 | Image processing |
| requests | 2.32.5 | HTTP client |
| dicomweb-client | 0.60.1 | DICOMweb protocol |
| VTK | 9.5.2 | VTK Python bindings |
| certifi, urllib3, idna, charset-normalizer | — | HTTP deps |
| setuptools, pip, wheel | — | Package management |

### 3.3 No System Requirements

The runtime is fully portable. It does NOT need:
- ❌ System Python installation
- ❌ System Qt installation
- ❌ Visual C++ redistributables (bundled)
- ❌ DICOM toolkit installation
- ❌ 3D Slicer installation

---

## 4. Quick Start: Fresh Machine Setup

### 4.1 If You Already Have the Assembled Build

1. **Clone the repo** from GitHub
2. **Download the runtime** from the team's shared storage (see Section 6)
3. **Extract** `slicer_runtime_v0.1.0.zip` into:
   ```
   modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/
   ```
4. **Verify** the structure:
   ```
   NewMPR2Slicer/build/AIPacsAdvancedViewer.exe    ← must exist
   NewMPR2Slicer/build/bin/Release/                 ← must have DLLs
   NewMPR2Slicer/build/deps/qt/                     ← must have Qt5*.dll
   ```
5. **Test** from command line:
   ```powershell
   $exe = "modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"
   & $exe --version
   ```
   Expected: version string with "5.11.0"

6. **Run the PACS app** — Advanced MPR button should now work.

### 4.2 If You Need to Build from Source

See [BUILD_FROM_SOURCE.md](BUILD_FROM_SOURCE.md) for the full SuperBuild instructions.

---

## 5. Assembly Script: Building the Runtime

The assembly script copies only runtime files from the SuperBuild tree into a portable directory.

### Prerequisites (on the BUILD machine only)

| Requirement | Path | Notes |
|---|---|---|
| Slicer SuperBuild | `C:\S\NB` | Complete build with `Slicer-build/`, `python-install/`, `VTK-build/`, etc. |
| Qt 5.15.2 | `C:\Qt\5.15.2\msvc2019_64` | MSVC 2019 x64 build |
| Python 3.12+ | system or venv | To run the assembly script itself |

### Running the Assembly

```powershell
cd "c:\AI-Pacs codes\aipacs-pydicom2d"
python tools/slicer/assemble_slicer_runtime.py
```

This will:
1. Clean previous `NewMPR2Slicer/build/`
2. Copy 11 categories of files from the SuperBuild
3. Flatten `Release/` subdirectories (fixes intDir issue)
4. Generate `AIPacsAdvancedViewerLauncherSettings.ini` with relative paths
5. Report total size (~842 MB)

### Packaging the Runtime for Distribution

After assembly, create a distributable archive:

```powershell
$build = "modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build"
Compress-Archive -Path "$build\*" -DestinationPath "slicer_runtime_v0.1.0.zip" -CompressionLevel Optimal
```

---

## 6. Deploying to Another PC

### Option A: Team Shared Storage (Recommended)

1. After assembly, upload `slicer_runtime_v0.1.0.zip` to your team's shared storage
2. On the target PC, clone the repo and extract the zip into `NewMPR2Slicer/build/`

### Option B: Direct Copy

1. Copy the entire `NewMPR2Slicer/build/` directory (842 MB) to the target machine
2. Place it at the same relative path under the project

### Option C: GitHub Releases

1. Create a GitHub Release tagged `slicer-runtime-v0.1.0`
2. Attach `slicer_runtime_v0.1.0.zip` as a release asset
3. On fresh machines, run the provided `tools/slicer/download_slicer_runtime.py` script

### Verification After Deploy

```powershell
# Quick smoke test
$exe = "modules\mpr\advanced_3d_slicer\slicer_custom_app\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"
& $exe --version

# Full module loading test
& $exe --no-splash --no-main-window --python-code "import slicer; fm=slicer.app.moduleManager().factoryManager(); print(f'MODULES: {len(fm.loadedModuleNames())}'); slicer.app.quit()"
# Expected output: MODULES: 49
```

---

## 7. Integration with Main PACS App

### 7.1 Executable Discovery

`launch_slicer.py` finds `AIPacsAdvancedViewer.exe` in this priority order:

1. `AIPACS_ADVANCED_VIEWER_EXE` environment variable
2. `AIPACS_SLICER_BUILD_DIR` environment variable
3. `config/slicer_config.json` → `slicer_exe_path`
4. `config/slicer_config.json` → `slicer_build_dir`
5. Relative path: `slicer_custom_app/NewMPR2Slicer/build/AIPacsAdvancedViewer.exe`

For most setups, **option 5 (relative path) works automatically** — no config needed.

### 7.2 Environment Variables Passed to Slicer

| Variable | Required | Description |
|---|---|---|
| `NEWMPR2_DICOM_DIR` | **Yes** | Absolute path to series DICOM folder |
| `NEWMPR2_SERIES_UID` | No | Series Instance UID for verification |
| `NEWMPR2_STUDY_UID` | No | Study Instance UID |
| `NEWMPR2_LAYOUT` | No | Layout name (default: `mpr`) |
| `NEWMPR2_WINDOW_WIDTH` | No | Window/level width |
| `NEWMPR2_WINDOW_LEVEL` | No | Window/level center |
| `NEWMPR2_PATIENT_ID` | No | Patient ID |
| `NEWMPR2_STUDY_ID` | No | Study ID |
| `NEWMPR2_AUTO_CENTER` | No | Auto-center slices (default: `true`) |
| `SLICER_HOME` | Auto | Points to build/ root |

### 7.3 Remote Command Protocol (TCP 47891)

After Slicer starts, `startup_script.py` listens on `127.0.0.1:47891` for JSON commands:

```json
{
    "command": "load_series",
    "dicom_dir": "C:/path/to/series/folder",
    "series_uid": "1.2.3..."
}
```

The main app tries this FIRST before spawning a new process.

---

## 8. Known Issues & Fixes

### 8.1 intDir Empty — C++ Modules Not Found (Fixed 2026-03-11)

**Problem:** Slicer's module factory uses `searchPath + intDir` to locate C++ DLLs.
In the SuperBuild, `intDir="Release"` → finds DLLs in `qt-loadable-modules/Release/`.
In the assembled build, `intDir=""` → looks in `qt-loadable-modules/` → finds nothing.

**Fix:** `tools/slicer/assemble_slicer_runtime.py` now runs `_flatten_release_subdirs()` which copies
all files from `{subdir}/Release/` up to `{subdir}/`. Both paths now work.

**Affected dirs:** `qt-loadable-modules/`, `cli-modules/`, `ITKFactories/`

### 8.2 CTK Launcher Cannot Handle Spaces in --python-script Path (Fixed 2026-03-11)

**Problem:** If the workspace path contains a space (e.g., `C:\AI-Pacs codes\...`),
the CTK launcher binary splits the `--python-script` argument on the space.

**Fix:** `launch_slicer.py` copies `startup_script.py` to a space-free temp path
(`%TEMP%\aipacs_slicer\startup_script.py`) before launching.

### 8.3 stdout Suppressed — No Diagnostic Output (Fixed 2026-03-11)

**Problem:** `launch_slicer.py` used `stdout=subprocess.PIPE` which swallowed all
output from `startup_script.py`.

**Fix:** stdout now redirects to the same log file as stderr.

### 8.4 BOM in Python Scripts (Historical)

**Problem:** PowerShell `Set-Content -Encoding utf8` adds a BOM (`\xef\xbb\xbf`)
which causes `SyntaxError: invalid non-printable character U+FEFF` in Slicer's Python.

**Prevention:** Always write Python scripts with Python's `open(path, 'w', encoding='utf-8')`.

---

## 9. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| "Slicer opens but shows no image" | C++ modules not loaded (intDir issue) | Run `tools/slicer/assemble_slicer_runtime.py` or manually copy DLLs from Release/ to parent |
| "Specified python script doesn't exist" | Space in path | Check that `launch_slicer.py` copies to temp path; or move project to space-free path |
| Only 20 modules load (should be 49) | DLLs only in Release/ subdirs | Run `_flatten_release_subdirs()` on the lib directory |
| `slicer.util.loadVolume()` fails | Volumes module not loaded | Same as intDir issue above |
| "SubjectHierarchy not available" | Cascade failure from missing C++ modules | Same fix — all C++ modules must load |
| Slicer crashes immediately | Missing Qt DLLs or platform plugin | Verify `deps/qt/` has Qt5*.dll and `deps/qt-plugins/platforms/qwindows.dll` |
| Black window, no rendering | OpenGL issue | Set `MESA_GL_VERSION_OVERRIDE=3.3` or use software rendering |
| Module loads but DICOM import fails | DICOMDatabase path issue | Check `startup_script.py` Strategy 1 logs in `slicer_custom_app/logs/` |
| Process starts but no window appears | Wrong exe (running real exe directly) | Must use root launcher exe, NOT `bin/Release/AIPacsAdvancedViewer.exe` |

### Diagnostic Commands

```powershell
# Test module loading count
$exe = "...\NewMPR2Slicer\build\AIPacsAdvancedViewer.exe"
& $exe --no-splash --no-main-window --python-code "import slicer; print(len(slicer.app.moduleManager().factoryManager().loadedModuleNames())); slicer.app.quit()"

# Test volume loading
$env:NEWMPR2_DICOM_DIR = "C:\path\to\dicom\series"
& $exe --no-splash --no-main-window --python-code "import slicer,os,glob; dcms=glob.glob(os.path.join(os.environ['NEWMPR2_DICOM_DIR'],'*.dcm')); vol=slicer.util.loadVolume(dcms[0]); print(vol.GetImageData().GetDimensions()); slicer.app.quit()"

# Check intDir
& $exe --no-splash --no-main-window --python-code "import slicer; print(f'intDir=[{slicer.app.intDir}]'); slicer.app.quit()"
```

---

## 10. Version Matrix

| Component | Version | Commit/Tag | Source |
|---|---|---|---|
| 3D Slicer | 5.11.0-2026-01-03 | `ae061acd0f40` | github.com/Slicer/Slicer |
| App Name | AIPacsAdvancedViewer | v0.1.0 | Custom SuperBuild |
| Qt | 5.15.2 | msvc2019_64 | qt.io |
| Python (embedded) | 3.12.10 | — | SuperBuild |
| VTK | 9.5.2 | — | SuperBuild |
| DCMTK | 3.6.8 | — | SuperBuild |
| CMake (build only) | ≥ 3.16.3 | — | cmake.org |
| Visual Studio (build only) | 2019+ | — | Microsoft |

---

## 11. File Manifest

See [DEPENDENCY_MANIFEST.md](DEPENDENCY_MANIFEST.md) for the complete file inventory
of the assembled runtime directory.
