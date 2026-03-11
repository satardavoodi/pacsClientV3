# Launch Contract – AI-PACS Advanced Viewer

> **Version:** 1.0 (2026-02-19)
> **Status:** Stable — aligned with AI-PACS v2.2.2

This document defines the interface between the **PacsClient launcher code** (`slicer_launcher.py` + `launch_slicer.py`) and the **AI-PACS Advanced Viewer application** (the custom 3D Slicer SuperBuild). Any change to one side must preserve this contract.

---

## 1. Executable Requirement

| Item | Value |
|------|-------|
| Executable name | `AIPacsAdvancedViewer.exe` |
| Type | SuperBuild launcher (sets up DLL paths via `LauncherSettings.ini`) |
| Fallback | **None.** Stock `Slicer.exe` is never used. |

Discovery is handled by `find_slicer_executable()` — see [README.md](../../README.md#executable-discovery-dynamic-paths) for the priority chain.

---

## 2. Command-Line Arguments

The launcher builds a command of the form:

```
AIPacsAdvancedViewer.exe --no-splash --launcher-no-splash \
    --python-code "<branding one-liner>" \
    --python-script "<path-to-startup_script.py>"
```

| Argument | Description |
|----------|-------------|
| `--no-splash` | Suppress the application splash screen. |
| `--launcher-no-splash` | Suppress the launcher splash screen. |
| `--python-code "<code>"` | Inline Python executed *before* `--python-script`. Used for immediate window-title branding. |
| `--python-script "<path>"` | Path to `startup_script.py`. This is the primary integration point. |
| `--testing` | *(optional)* Added when `software_rendering=True` to reduce GPU requirements. |

---

## 3. Environment Variables (Parameter Passing)

Standard 3D Slicer does not forward custom CLI arguments to `--python-script`. All parameters are therefore passed as **environment variables**:

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `NEWMPR2_DICOM_DIR` | `str` (path) | Absolute path to the DICOM directory for the selected series. |
| `NEWMPR2_LAYOUT` | `str` | Layout name (see §3.1). |

### Optional

| Variable | Type | Description |
|----------|------|-------------|
| `NEWMPR2_SERIES_UID` | `str` | Series Instance UID to identify the primary volume when multiple series exist in `NEWMPR2_DICOM_DIR`. |
| `NEWMPR2_PATIENT_ID` | `str` | Patient ID for window title display. |
| `NEWMPR2_STUDY_ID` | `str` | Study Instance UID. |
| `NEWMPR2_WINDOW_WIDTH` | `float` as `str` | Window width (contrast). Applied to Volume Display nodes after loading. |
| `NEWMPR2_WINDOW_LEVEL` | `float` as `str` | Window center (brightness). Applied to Volume Display nodes after loading. |
| `NEWMPR2_AUTO_CENTER` | `"1"` or `"0"` | If `"1"` (default), auto-center slice views after loading. |
| `NEWMPR2_VOR_X` | `int` as `str` | Main PACS viewer X position on screen (for initial window placement). |
| `NEWMPR2_VOR_Y` | `int` as `str` | Main PACS viewer Y position. |
| `NEWMPR2_VOR_WIDTH` | `int` as `str` | Main PACS viewer width (for sizing). |
| `NEWMPR2_VOR_HEIGHT` | `int` as `str` | Main PACS viewer height. |

### 3.1 Valid Layout Names

| Name | Description |
|------|-------------|
| `mpr` | Four-up view: Axial + Sagittal + Coronal + 3D (default) |
| `fourup` | Alias for `mpr` |
| `axial` | Single axial (Red) slice view |
| `sagittal` | Single sagittal (Yellow) slice view |
| `coronal` | Single coronal (Green) slice view |
| `threeD` | Single 3D view |
| `conventional` | Conventional Slicer layout |
| `dualthreeD` | Two 3D views side by side |

---

## 4. `startup_script.py` Responsibilities

When `AIPacsAdvancedViewer.exe` starts, it runs `startup_script.py` inside the Slicer Python environment. The script **must**:

1. **Read environment variables** listed in §3.
2. **Load the DICOM data** from `NEWMPR2_DICOM_DIR`.
3. **Set the layout** according to `NEWMPR2_LAYOUT`.
4. **Apply window/level** from `NEWMPR2_WINDOW_WIDTH` / `NEWMPR2_WINDOW_LEVEL` if provided.
5. **Auto-center slices** if `NEWMPR2_AUTO_CENTER == "1"`.
6. **Apply branding** — set window title to `"AI-PACS Advanced Viewer v0.1"`, hide the Slicer logo placeholder.
7. **NOT show** the DICOM browser, Welcome screen, or any stock Slicer landing page.

---

## 5. Process Model

| Aspect | Specification |
|--------|--------------|
| **Isolation** | The viewer runs in a **separate process** with `CREATE_NEW_CONSOLE` (Windows) to isolate its OpenGL/VTK context from the parent PacsClient. |
| **Single instance** | Only one Advanced Viewer may run per PacsClient session. `SlicerLauncher` tracks `_is_running` and shows a message if the user clicks the button again. |
| **Remote command** | Before spawning a new process, `SlicerLauncher` attempts to send a `load_dicom` command over TCP (port 47891). If an existing viewer responds, no new process is created. |
| **Exit code** | Exit code `0` = normal close. Non-zero = error (logged, user warned). Exit code `127` = executable not found (fatal). |
| **Cleanup** | On PacsClient shutdown, `terminate_all_slicer_processes()` kills all `AIPacsAdvancedViewer.exe` instances via `taskkill`. |

---

## 6. GPU / Rendering

| Mode | When | Effect |
|------|------|--------|
| **Hardware (default)** | `software_rendering=False` | Forces discrete GPU: `SHIM_MCCOMPAT`, `OPTIMUS_PERFORMANCE_MODE`, `QT_OPENGL=desktop`. |
| **Software** | `software_rendering=True` | Mesa/llvmpipe: `LIBGL_ALWAYS_SOFTWARE=1`, `QT_OPENGL=software`, adds `--testing` flag. |

---

## 7. Versioning and Compatibility

- The branding string (`"AI-PACS Advanced Viewer v0.1"`) is defined in both `launch_slicer.py` (inline branding code) and `startup_script.py` (`BRAND_TITLE`). Both must match.
- The SuperBuild CMakeLists.txt in `NewMPR2Slicer/` pins the Slicer version used for the build.
- Any change to this contract requires updating **both** this document and the [module README](../../README.md).
