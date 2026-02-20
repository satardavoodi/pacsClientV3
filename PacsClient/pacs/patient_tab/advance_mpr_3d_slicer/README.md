# Advanced Analysis Module – AI-PACS Advanced Viewer

> **Stable version:** v2.2.2 (2026-02-19)
> **Module path:** `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/`

## What This Module Is

This module provides the **Advanced Analysis** feature in AI-PACS via a **customised 3D Slicer SuperBuild application** branded as *AI-PACS Advanced Viewer*.
It is **not** stock 3D Slicer; it is a purpose-built application that:

- Launches directly into an MPR (multi-planar reconstruction) layout.
- Bypasses the Slicer Welcome/DICOM-browser screens.
- Inherits the DICOM directory, series UID, window/level, and layout from the main PACS viewer.
- Displays the *AI-PACS Advanced Viewer* title and branding (no "3D Slicer" references).

**Stock 3D Slicer is NEVER used as a fallback.** If the custom executable is not found, the launch fails loudly with instructions to build it.

---

## Directory Layout

```
advance_mpr_3d_slicer/              ← Python package root
├── __init__.py                     ← Public API: SlicerLauncher, get_slicer_launcher, …
├── slicer_launcher.py              ← High-level launcher + prewarm manager (runs inside PacsClient)
├── README.md                       ← THIS FILE
│
└── slicer_custom_app/              ← Everything that ships or runs inside the custom Slicer
    ├── launch_slicer.py            ← CLI + library: locates exe, builds command, sets env vars, launches
    ├── startup_script.py           ← --python-script passed to Slicer: loads DICOM, sets layout, brands UI
    ├── unified_logging.py          ← Shared logging helpers for startup_script
    ├── customize_slicer_app.py     ← Build-time customisation (icons, splash, etc.)
    ├── branding/                   ← QSS, icons, colour palette for in-app branding
    │   ├── colors.json
    │   ├── icons/
    │   └── NewMPR2Slicer.qss
    ├── NewMPR2SlicerArgs.h         ← C++ header for custom CLI parameters
    ├── logs/                       ← Runtime geometry/diagnostic logs (auto-created)
    │
    └── NewMPR2Slicer/              ← CMake SuperBuild project (builds AIPacsAdvancedViewer.exe)
        ├── CMakeLists.txt
        ├── Applications/
        │   └── NewMPR2SlicerApp/
        └── Modules/
            └── Scripted/
                ├── Home/
                └── NewMPR2MPR/     ← Primary MPR Slicer module
```

---

## How It Works (End-to-End Flow)

```
User clicks "Advanced Analysis"
         │
         ▼
PatientWidget._launch_advanced_analysis_with_params()
         │  lazy-imports get_slicer_launcher()
         ▼
SlicerLauncher.launch_with_dicom()
         │  sends remote command (if viewer already running)
         │  otherwise creates SlicerLauncherWorker (QThread)
         ▼
SlicerLauncherWorker.run()
         │  imports launch_slicer.launch_slicer()
         │  calls find_slicer_executable() → resolves AIPacsAdvancedViewer.exe
         │  builds cmd: [exe, --no-splash, --python-code <branding>, --python-script startup_script.py]
         │  builds env vars: NEWMPR2_DICOM_DIR, NEWMPR2_SERIES_UID, …
         ▼
subprocess.run(cmd, env=env, cwd=exe.parent)
         │  AIPacsAdvancedViewer.exe starts → runs startup_script.py inside Slicer
         ▼
startup_script.py
         │  reads env vars → loads DICOM → sets MPR layout → applies branding
         ▼
User sees branded MPR viewer with their data
```

---

## Executable Discovery (Dynamic Paths)

The `find_slicer_executable()` function resolves the custom viewer executable using this priority chain — **no hardcoded absolute paths**:

| Priority | Source | How to set |
|----------|--------|-----------|
| 1 | `AIPACS_ADVANCED_VIEWER_EXE` env var | Full path to `.exe` |
| 2 | `AIPACS_SLICER_BUILD_DIR` env var | Directory containing `.exe` |
| 3 | `config/slicer_config.json` → `slicer_exe_path` | Per-developer JSON config |
| 4 | `config/slicer_config.json` → `slicer_build_dir` | Per-developer JSON config |
| 5 | Relative paths: `slicer_custom_app/NewMPR2Slicer/build/`, `<project_root>/Slicer-build/`, `cwd/Slicer-build/` | Portable, works if build is adjacent to project |

### Developer Setup

Each developer sets their own build path by editing `config/slicer_config.json`:

```json
{
  "slicer_build_dir": "C:/S/NB/Slicer-build",
  "slicer_exe_path": ""
}
```

This file is **git-ignored**, so each machine has its own without conflicts.

Alternatively, set the environment variable:
```
set AIPACS_SLICER_BUILD_DIR=C:\S\NB\Slicer-build
```

---

## Parameter Passing (Launch Contract)

Parameters are passed from PacsClient to the Slicer startup script via **environment variables** (standard Slicer does not forward custom CLI args to `--python-script`):

| Env Variable | Description | Required |
|-------------|-------------|----------|
| `NEWMPR2_DICOM_DIR` | Path to the DICOM file directory | Yes |
| `NEWMPR2_LAYOUT` | Layout name (`mpr`, `axial`, `sagittal`, `coronal`, `threeD`, `fourup`, `conventional`, `dualthreeD`) | Yes (default: `mpr`) |
| `NEWMPR2_SERIES_UID` | Series Instance UID for primary volume | No |
| `NEWMPR2_PATIENT_ID` | Patient ID for display | No |
| `NEWMPR2_STUDY_ID` | Study ID for display | No |
| `NEWMPR2_WINDOW_WIDTH` | Window width (contrast) | No |
| `NEWMPR2_WINDOW_LEVEL` | Window center/level (brightness) | No |
| `NEWMPR2_AUTO_CENTER` | `"1"` or `"0"` — auto-center slices | No (default: `"1"`) |
| `NEWMPR2_VOR_X/Y/WIDTH/HEIGHT` | Main PACS viewer geometry for window positioning | No |

---

## Stability Rules

### DO NOT

- **Do NOT replace this module with stock 3D Slicer.** The custom SuperBuild has custom modules (NewMPR2MPR), branding, and startup integration that stock Slicer lacks.
- **Do NOT add hardcoded absolute paths** (e.g., `C:/Users/...`, `C:/S/NB/...`). Use `config/slicer_config.json` or environment variables.
- **Do NOT import `advance_mpr_3d_slicer` at module top level.** Always use lazy imports inside functions to avoid import-time side effects.
- **Do NOT remove or rename the `startup_script.py` file.** It is the sole bridge between the launcher and the running Slicer process.
- **Do NOT call `slicer_launcher.py` functions from the slicer_custom_app code.** The dependency flows one direction: PacsClient → slicer_launcher → slicer_custom_app.

### DO

- Keep all paths resolved via `Path(__file__).parent.resolve()` and the config chain.
- Keep launch parameters in environment variables (not CLI args).
- Keep branding applied in `startup_script.py` (not `.slicerrc.py`).
- Run Slicer in a separate process with `CREATE_NEW_CONSOLE` on Windows for GPU context isolation.
- Use `SlicerPrewarmManager` for module preloading (the full prewarm is disabled to avoid visible windows).

---

## Building the Custom Slicer (SuperBuild)

```bash
# 1. Open Developer Command Prompt for VS 2022
# 2. Navigate to the NewMPR2Slicer directory
cd PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer

# 3. Create build directory
mkdir build && cd build

# 4. Configure with CMake
cmake -G "Visual Studio 17 2022" -A x64 \
  -DQt5_DIR="<path-to-Qt5-cmake-dir>" ..

# 5. Build
cmake --build . --config Release

# 6. Verify the executable exists
dir AIPacsAdvancedViewer.exe
```

After building, set your path in `config/slicer_config.json`:
```json
{
  "slicer_build_dir": "<your-build-dir>/Slicer-build",
  "slicer_exe_path": ""
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "AIPacsAdvancedViewer.exe not found" dialog | Exe not built or path not configured | Build the SuperBuild or set path in `config/slicer_config.json` |
| Stock Slicer Welcome screen appears | `startup_script.py` not found or not running | Ensure `--python-script` is pointing to the correct file (check logs) |
| "Already running" dialog | Previous instance not closed | Close the existing Slicer window or use `terminate_all_slicer_processes()` |
| GPU crash / GLEW error | Slicer inheriting parent's OpenGL context | Should not happen (uses `CREATE_NEW_CONSOLE`); check log files in `slicer_custom_app/logs/` |
| Wrong window/level | Env vars not passed correctly | Check `[AIPACS_LINK_DST]` log output for env var values |

---

## API Reference

### `slicer_launcher.py` (public API)

| Symbol | Description |
|--------|-------------|
| `SlicerLauncher` | QObject that manages launch lifecycle, signals: `slicer_started`, `slicer_finished(int)`, `slicer_error(str)` |
| `get_slicer_launcher(parent)` | Singleton factory for `SlicerLauncher` |
| `SlicerPrewarmManager` | Singleton that preloads launcher modules for faster first launch |
| `get_prewarm_manager()` | Convenience to get `SlicerPrewarmManager.instance()` |
| `terminate_all_slicer_processes()` | Kill all AIPacsAdvancedViewer.exe instances (for app shutdown) |

### `launch_slicer.py` (inner implementation)

| Symbol | Description |
|--------|-------------|
| `find_slicer_executable()` | Locate `AIPacsAdvancedViewer.exe` using the discovery chain |
| `launch_slicer(dicom_dir, …)` | Build command + env, launch subprocess, wait for exit |
| `build_slicer_command(…)` | Build the command-line argument list |
| `get_slicer_env(…)` | Build the environment variable dictionary |
