# v2.4.5 - Advanced MPR Launch Readiness + FAST Corner-Zoom Regression Fix (2026-04-25)
# Post-release patch: 2026-04-26 (MPR frozen crash + user_data_root fallback)

## Post-release Patches (2026-04-26)

Applied as uncommitted changes on top of the 2026-04-25 tag; embedded in the
installer rebuilt on 2026-04-26 (`ai-pacs installer v2.4.5.exe`).

### Fix 1 — MPR viewer crash in frozen (no-console) builds

**Symptom:** Zeta MPR viewer crash on launch in the installed build with:
```
AttributeError: 'NoneType' object has no attribute 'flush'
```

**Root cause:** `StandardMPRViewer.__init__` (in `widget.py` line 141) calls
`self._log_orientation_info()`.  That method calls `print()` + `sys.stdout.flush()`
approximately 16 times across two files.  In a PyInstaller windowed/no-console build
`sys.stdout is None`, so `.flush()` raises `AttributeError`.

**Fix:** Added an early-return guard at the top of `_log_orientation_info()` in both
affected files:

```python
import sys as _sys
if _sys.stdout is None:
    # No console in frozen/windowed mode — skip all print/flush debug output
    return
```

**Files changed:**
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_orientation.py`
- `modules/mpr/zeta_mpr/standard_mpr_viewer_original.py`

**Rule for future callers:** Any `print()` or `sys.stdout.flush()` inside a method
that runs during `__init__` of a widget that is constructed in the installed build
MUST be guarded by `if sys.stdout is None: return` (or use `logger.debug()` instead
of `print()`).  This applies to ALL debug-logging helpers called unconditionally from
`__init__` paths — not only in the MPR viewer.

**Verified:** Dev-mode regression test simulated `sys.stdout = None` and confirmed
the guard path exits cleanly (`mpr_stdout_none_guard=ok`).

---

### Fix 2 — `user_data_root()` writable fallback

**Symptom:** On machines where `C:\Program Files\AIPacs\User Data\` is not writable
(non-admin user, strict group policy, or UAC restrictions), any first write to user
data (DB, pixel cache, DICOM downloads) raised `PermissionError` and the app crashed
or produced a blank/frozen viewer.

**Root cause:** `aipacs_runtime.user_data_root()` (frozen branch) unconditionally
returned `install_root() / "User Data"` without checking writeability.

**Fix:** Added `_is_path_writable(path)` helper in `aipacs_runtime.py` that performs
a `mkdir` + write-probe + unlink cycle.  `user_data_root()` now:
1. Tries `Program Files\AIPacs\User Data` (preferred — visible, alongside `engine\`).
2. If not writable, falls back to `%LOCALAPPDATA%\AIPacs\user_data\`.

```python
preferred = install_root() / "User Data"
if _is_path_writable(preferred):
    return preferred
return local_state_root() / USER_DATA_DIRNAME
```

**Files changed:**
- `aipacs_runtime.py` — `_is_path_writable()` added; `user_data_root()` updated.
- `PacsClient/utils/data_paths.py` — module docstring updated to document fallback.

**Rule:** Any code that resolves a user-data path MUST call `user_data_root()` (or a
function derived from it) — never hardcode `install_root() / "User Data"` directly.
The writable fallback is transparent to all callers because they only see the
resolved `Path` object.

---

### Fix 3 — Build script ASCII-safe print statements

**Symptom:** On Windows consoles without UTF-8 mode (`PYTHONUTF8=1` not set),
`builder/build_release.py` raised `UnicodeEncodeError` when printing status lines
containing the Unicode right-arrow character `→`.

**Fix:** Replaced `→` with ASCII `->` in two `print()` calls in
`builder/build_release.py` (`stage_core_bundle` function).

**Rule:** `build_release.py` output goes to arbitrary consoles and CI logs that may
not be UTF-8.  Use only printable ASCII in its `print()` / log statements, or use
`PYTHONUTF8=1` in the canonical build command (both are now in place).

---

## Summary


This release resolves two user-visible regressions reported from installed builds:

1. Advanced MPR launch notification ended too early (looked like the app froze).
2. FAST viewer drag-drop/layout flow occasionally reintroduced the corner-zoom issue
   (image appears small in a corner until a click).

It also documents the Advanced MPR build/runtime integration contract so packaging
regressions do not silently return.

## Included Changes

### 1) Advanced MPR launch notification and readiness criterion

Files:
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_advanced.py`
- `modules/mpr/advanced_3d_slicer/slicer_launcher.py`
- `modules/mpr/advanced_3d_slicer/slicer_custom_app/launch_slicer.py`

Changes:
- Overlay text now uses product wording:
  - status while launching: `AI Advanced Analysis is launching`
  - status on ready: `AI Advanced Analysis launched`
- The launch worker no longer emits "started" immediately after process spawn.
- Launch readiness is now gated by a concrete criterion:
  - preferred: runtime startup log contains
    `STARTUP SEQUENCE COMPLETED SUCCESSFULLY`
  - fallback: process remains stable with startup log output for a bounded interval.
- Worker keeps tracking process lifecycle and still emits `finished` when the launched
  process exits.

Why this is structural:
- The UI now binds loading visibility to startup readiness, not to a timing guess.
- Startup marker is produced by the runtime itself, making the criterion robust to
  slower machines and larger studies.

### 2) FAST viewer corner-zoom regression hardening

File:
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py`

Changes:
- Added startup refit epoch guard in `_queue_qt_startup_refit`.
- Each refit burst increments an epoch.
- Delayed callbacks from older bursts are dropped automatically.

Why this is structural:
- The root cause was stale delayed refit callbacks applying an outdated fit after
  layout churn.
- Epoch invalidation prevents stale callbacks from mutating presentation state.
- This avoids reintroducing patch-on-patch zoom repair logic.

## Build / Packaging Documentation Added

- Added: `builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md`
- Updated: `builder/docs/README.md` to index the new document.

The new integration doc defines:
- Canonical source -> stage -> ProgramData -> LocalAppData runtime flow
- Required runtime files and build-time gate behavior
- Runtime readiness checks before launch
- Installed-build verification checklist and log signals
- "do not regress" rules for builder/package copy paths

## Version Metadata

Updated to `2.4.5` in:
- `pyproject.toml`
- `main.py`
- `docs/README.md`
- `docs/releases/RELEASE_NOTES.md`

## Validation Notes

- No static errors reported for modified files.
- Installed runtime logs contain startup markers suitable for readiness gating.
- FAST log traces showed conflicting host-size refits; epoch guard addresses this at source.
