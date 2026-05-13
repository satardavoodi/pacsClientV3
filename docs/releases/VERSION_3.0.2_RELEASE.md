# AIPacs v3.0.2 Release Notes
**Date**: May 13, 2026  
**Branch**: beta-version  
**Release Type**: Validation build (multi-PC)

---

## Summary

v3.0.2 packages the validated FAST smoothness architecture work for cross-machine validation.

Primary intent is controlled rollout for multi-PC testing before any default-on promotion decisions for FAST Render Clock behavior.

---

## Included in v3.0.2

1. Progressive grow defer/budget behavior during active interaction
2. Retroactive metadata sync cap/throttle fix
3. FAST Render Clock experiment path
4. FAST clock side-effect deferral
5. Runtime diagnostics/logging for smoothness KPIs
6. Plugin mirror parity updates for modified FAST files

---

## Safety and Defaults

- FAST Render Clock experiment remains **configuration-driven** and **safe by default**.
- Enable experiment mode explicitly with:

```powershell
$env:AIPACS_FAST_RENDER_CLOCK_EXPERIMENT="1"
```

- Disable explicitly with:

```powershell
$env:AIPACS_FAST_RENDER_CLOCK_EXPERIMENT="0"
```

If unset, runtime behavior follows existing conservative defaults.

---

## Diagnostics Preserved

This release preserves and validates diagnostic observability for:

- `FAST_RENDER_CLOCK_CONFIG`
- `FAST_RENDER_CLOCK`
- `FAST_CLOCK_SIDE_EFFECT_DEFERRED`
- `FAST_CLOCK_SIDE_EFFECT_APPLIED`
- `FAST_CLOCK_FINAL_SIDE_EFFECT_FLUSH`
- `FAST_DRAG_KPI`
- `FAST_EVENT_PACING`
- `FAST_FG_DISK`
- `PROGRESSIVE_GROW_*`
- `RETRO_META_SYNC_*`

---

## Versioning Updates

- `pyproject.toml` -> `version = "3.0.2"`
- `main.py` -> `app.setApplicationVersion("3.0.2")`
- `docs/releases/RELEASE_NOTES.md` -> current stable set to `v3.0.2`
- `docs/README.md` -> current stable set to `v3.0.2`
- `.github/copilot-instructions.md` -> current stable set to `v3.0.2`

---

## Validation Suite (release gate)

Required tests for this release:

- `tests/viewer/test_fast_render_clock_experiment.py`
- `tests/viewer/test_qt_stack_drag_bridge.py`
- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_retroactive_metadata_sync_fix.py`

---

## Build and Distribution

The Windows release build for v3.0.2 is produced via the PyInstaller pipeline under `builder/`.

Artifact naming follows the project version and includes `3.0.2` in the versioned installer copy.

---

## Notes

- Previous stable: `v2.5.4`
- This release tag: `v3.0.2`
- Purpose: multi-PC validation candidate, not a default-on behavior promotion
