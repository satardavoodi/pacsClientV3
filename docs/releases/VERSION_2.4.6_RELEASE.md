# v2.4.6 - Advanced MPR Runtime Compatibility Guard (2026-04-26)

## Summary

Adds a fail-fast runtime compatibility check that prevents the Advanced MPR module
from launching when the installed runtime payload is outdated.  Before this fix,
a stale `startup_script.py` in the installed runtime caused Slicer to open in a
generic four-up / fourth-box layout instead of the intended Advanced MPR mode.

This release also records the synchronized Nuitka packaging work completed after
the latest pull: the staged Nuitka builder now carries the compiled core plus
external Python/plugin packages consistently, including the Advanced MPR runtime
payload and its Python bridge.

This version also inherits all patches from v2.4.5 (2026-04-25 / patch 2026-04-26).

---

## Fix — Advanced MPR stale runtime payload guard

### Symptom

In installed (non-dev) builds, clicking the Advanced MPR button with a DICOM study
selected caused the Advanced Viewer to open in a generic four-up / fourth-box layout
instead of the correct Advanced MPR mode.  The launcher reported no errors and the
process started normally.

The behavior was only reproducible from the **installed** app — not from dev
(`python main.py`).

### Root Cause

The installed runtime at `%LOCALAPPDATA%\AIPacs\modules_runtime\advanced_mpr\`
contained an **outdated `startup_script.py`** that predated the remote-command server
architecture introduced in a previous workstation update.  The stale script lacked
the markers that `SlicerLauncherWorker` expects to confirm Advanced MPR mode startup:

| Marker | Purpose |
|--------|---------|
| `_REMOTE_SERVER_STARTED` | Remote command server state variable |
| `NEWMPR2_REMOTE_PORT` | Port constant for remote socket server |
| `start_remote_command_server` | Function that starts the server |

Because Slicer's own Python startup script was stale, the remote command server was
never started; instead Slicer defaulted to its built-in four-up comparison layout.

### Fix

Added `_validate_runtime_startup_script(runtime_root)` static method to
`SlicerLauncherWorker` in `modules/mpr/advanced_3d_slicer/slicer_launcher.py`.

This method is called from `_check_runtime_installed()` **before** any process is
spawned.  It:

1. Checks that `startup_script.py` exists in the runtime directory.
2. Reads the file content.
3. Verifies all three required compatibility markers are present.
4. If any check fails, returns an actionable human-readable error string that is
   displayed in a dialog box, guiding the user to re-install the module.

```
Settings -> Installation -> Advanced MPR -> Re-install
```

No process is started if the script is stale — the user sees a clear error
immediately instead of a confusing wrong-layout behavior.

### File Changed

- `modules/mpr/advanced_3d_slicer/slicer_launcher.py`
  - New static method `SlicerLauncherWorker._validate_runtime_startup_script(runtime_root)`
  - Called from `SlicerLauncherWorker._check_runtime_installed()` as a third validation step
    (after runtime directory exists and exe exists checks)

### Verification

Confirmed on installed build (2026-04-26):
- Before fix: Advanced MPR opened in four-up mode silently.
- After fix: With stale runtime — dialog shows "outdated and incompatible" message
  with re-install instructions; no process launched.
- After runtime reinstall: Advanced MPR launches correctly in Advanced MPR mode.

### Rule for Future

When the installed `startup_script.py` is updated (new markers added, function
renamed, etc.), update `required_markers` in `_validate_runtime_startup_script` to
include the new mandatory identifiers.  This prevents future silent compatibility
failures from landing in installed builds undetected.

---

## Inherited — v2.4.5 and v2.4.5-patch content

See [`VERSION_2.4.5_RELEASE.md`](VERSION_2.4.5_RELEASE.md) for full details of:

- Advanced MPR loading overlay UX (stays visible until runtime ready)
- FAST viewer structural startup refit guard (epoch-guarded callbacks)
- MPR frozen-build crash fix (`sys.stdout is None` guard)
- `user_data_root()` writable fallback to `%LOCALAPPDATA%`
- Build script ASCII-safe print statements

---

## Nuitka Release Packaging Sync

### Scope

The Nuitka build remains separate from the PyInstaller/Python build:

- `builder/` is the Python/PyInstaller release builder.
- `builder nuitka/` is the staged/checkpointed Nuitka builder.
- Optional plugins remain external Python/runtime packages in both build systems.

### Advanced MPR

Advanced MPR is a customized 3D Slicer runtime package and is not compiled into
the Nuitka core.  For v2.4.6 the Nuitka package was fixed so installed builds
receive both required pieces:

- Slicer runtime files at `advanced_mpr/payload/`
- Python bridge files at `advanced_mpr/payload/python/modules/mpr/advanced_3d_slicer`

The `advanced_mpr` package manifest now declares `python_paths: ["python"]`.
Without this bridge path, installed Nuitka builds failed with:

```text
No module named 'modules.mpr.advanced_3d_slicer'
```

The source project now also has the assembled runtime available locally at:

```text
modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build
```

That directory is intentionally Git-ignored because it is a generated binary
runtime payload (~0.81 GB), not source code.

### Data Analysis / Native Footprint

`modules.data_analysis` was moved out of the compiled Nuitka core and into the
shared external module-package flow.  This keeps analytics dependencies such as
`pandas` and Python `matplotlib` out of the core `Engine/` folder while preserving
default module availability through package staging.

### FAST / OpenCV

Nuitka staging now verifies the OpenCV runtime required by FAST mode:

- `Engine/cv2/cv2.pyd`
- `Engine/cv2/opencv_videoio_ffmpeg4130_64.dll`
- `Engine/config/pooyan_opencv_filter.json`

The staged `pooyan_opencv_filter.json` is checked against the source config.
The build-time smoke verified the filter function with OpenCV `4.13.0`, preserving
input shape/dtype and changing pixel values as expected.

### Installer Layout

The Nuitka installer uses the cleaner installed layout:

- root `AIPacs.exe` launcher
- `Engine/` containing compiled core/runtime DLL/PYD files
- `User Data/` parallel to `Engine/`
- optional plugin packages installed externally through ProgramData/module package flow

### Validation

Validated after the Stage 08/09/10 Nuitka rebuild:

- `python "builder nuitka/build_nuitka_release.py" --smoke-test`
- `python builder/scripts/check_module_plugin_readiness.py`
- `python builder/scripts/check_build_coherence.py`

Latest local Nuitka installer produced during validation:

- `builder nuitka/output/installer/ai-pacs-nuitka-installer.exe`
- Size: `592,817,513` bytes
- SHA256: `3E7062AED3A1DFE6DD21734422838554BCD9D622B226FA2CFA87BD3B69788010`

---

## Build Info

| Key | Value |
|-----|-------|
| Version | 2.4.6 |
| Date | 2026-04-26 |
| Branch | main |
| Commit | b57fb327 |
| Base | v2.4.5 + 2026-04-26 patch |

### Packaging Confirmation (PyInstaller + Inno Setup)

Release packaging for v2.4.6 completed successfully on 2026-04-26.

- Build command exited with code 0.
- Inno Setup reported `Successful compile (5194.984 sec)`.
- Generated installers:
  - `builder/output/installer/ai-pacs installer.exe`
  - `builder/output/installer/ai-pacs installer v2.4.6.exe`

This confirms the Advanced MPR runtime guard changes are included in the
produced installer artifacts used for installation validation.
