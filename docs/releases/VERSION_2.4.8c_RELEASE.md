# AIPacs v2.4.8c Release Notes

Date: 2026-05-03
Branch: matab-conservative

## Scope

This release packages the latest launcher and build updates as a clean upgrade
version so installed workstations receive the Advanced MPR startup compatibility
fixes reliably.

## Included Fixes

1. Advanced MPR launcher startup-script compatibility checks are multi-path.
The launcher now evaluates all expected runtime script locations and accepts the
runtime when any candidate contains the required compatibility markers.

2. Failure diagnostics for stale runtime script signatures are more explicit.
When compatibility checks fail, the user-facing error includes searched paths
and the exact missing markers.

3. Installer upgrade reliability.
Version bump to 2.4.8c ensures installation flow upgrades from older deployed
launcher code instead of staying on a previously installed build.

4. FAST stacking appearance consistency.
Filtering remains enabled during wheel and drag fast interaction so stacked
frames and stationary frames match for the same slice/window-level context.

5. Sync/reference mapping geometry-cache reuse.
Qt bridge closest-slice selection now reuses pipeline-cached slice normal and
slice positions when available, improving consistency and reducing repeated
geometry computation during synchronized navigation.

6. Advanced backend settings persistence and override precedence hardening.
The installed application now preserves user backend selection across launches,
and explicit global Advanced mode selection is no longer masked by per-widget
FAST import overrides.

## Post-release patch (2026-05-03)

### Problem

On installed builds, selecting Advanced mode in Settings could appear to apply
but still resolve to FAST backend behavior after reopen/restart.

### Root causes

1. Frozen config seeding path could overwrite user backend settings with the
bundled default at startup.
2. Viewer controller override precedence could force a parent-widget FAST
override even when the persisted global backend was Advanced.

### Code changes

1. `aipacs_runtime.py` — `seed_user_config_defaults()` now preserves existing
user config files and only seeds files that are missing.
2. `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_backend.py` —
`_get_requested_viewer_backend()` now applies `viewer_backend_override` only
when configured global backend is FAST (`pydicom_qt`/`pydicom_2d`); when global
backend is Advanced (`vtk_simpleitk`), persisted choice is authoritative.
3. `tests/viewer/test_fast_viewer_pipeline.py` — integration tests updated to
lock this precedence contract:
   - configured Advanced wins over parent override
   - parent override is honored only in configured FAST mode

### Regression-prevention contract

1. Do not reintroduce unconditional overwrite of `%APPDATA%` backend settings
from bundled config in frozen startup paths.
2. Do not allow parent-widget backend override to supersede persisted Advanced
selection.
3. Any future change touching `seed_user_config_defaults()` or
`_get_requested_viewer_backend()` must update release notes and run backend
precedence tests.

## Verification Checklist

1. `pyproject.toml` version is `2.4.8c`.
2. `modules/mpr/advanced_3d_slicer/slicer_launcher.py` contains
   `source_module_script` and `candidate_scripts` in
   `_validate_runtime_startup_script`.
3. `build.py` completes and writes:
   - `builder/output/installer/ai-pacs installer.exe`
   - `builder/output/installer/ai-pacs installer v2.4.8c.exe`
4. `modules/viewer/fast/lightweight_2d_pipeline.py` uses
   `filter_enabled = bool(self._config.opencv_filter_enabled)` in
   `get_rendered_frame`.
5. `modules/viewer/fast/qt_viewer_bridge.py` `_find_closest_slice` attempts
   `pipeline.get_cached_slice_normal()` and
   `pipeline.get_cached_slice_positions()` before fallback computation.
6. `aipacs_runtime.py` `seed_user_config_defaults()` copies only missing user
   config files and preserves existing files.
7. `_vc_backend.py` `_get_requested_viewer_backend()` only applies
   `viewer_backend_override` when configured backend is FAST.
8. Backend precedence tests pass in
   `tests/viewer/test_fast_viewer_pipeline.py`.

## Notes

- This release is intended to eliminate repeated installed-build mismatch cases
  where old launcher code remained active after prior same-version installs.
