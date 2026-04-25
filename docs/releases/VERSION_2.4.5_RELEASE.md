# v2.4.5 - Advanced MPR Launch Readiness + FAST Corner-Zoom Regression Fix (2026-04-25)

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
