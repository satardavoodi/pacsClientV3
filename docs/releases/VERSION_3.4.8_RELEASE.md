# AIPacs v3.4.8 Release Notes

**Release date:** 2026-07-11
**Branch:** beta-version
**Previous stable:** v3.4.7

---

## Summary

v3.4.8 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It consolidates the EagleEye
Mammography 3D-cursor work merged from the `sadra` branch, EagleEye
model-training/feedback, INO reception assignment and report approval-flags sync,
the new Admission Reports dashboard, viewport overlay-metadata unification, and
download/network reliability work.

---

## Version Alignment

The following canonical version markers are set to `3.4.8`:

- `pyproject.toml` -> `version = "3.4.8"`
- `main.py` -> `app.setApplicationVersion("3.4.8")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.8`
- `docs/README.md` -> current stable `v3.4.8`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.8`
- `.github/copilot-instructions.md` -> current stable `v3.4.8`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.8` (English + Farsi)

LICENSE unchanged.

---

## Included In This Release

### EagleEye (merged selectively from the `sadra` branch)
- New `modules/ai_imaging/ai_module_ui/cursor_3d/` Mammography module: dual-view widget, breast contour, nipple detection/picking, pectoral detection, correlator, correspondence arc, geometry/visualization/validation, MLO depth projection
- Rewritten mammography `imaging_tab.py`; toolbar and viewer overrides
- Polygon + rectangle interactor styles (findings / box annotation workflow)
- Findings feedback collector, local training runner, training-data settings tab
- Segmentation host resolved from the active server profile (no hardcoded IP)
- Bone Age and other EagleEye behaviour preserved (verified unchanged)

### Reception / INO
- Internal-assignment foundation and report workflow
- Report approval-flags sync so patient/report status renders correctly in INO

### Data Analysis
- New Admission Reports dashboard over the reception Reports API

### Viewer / Platform
- Viewport overlay metadata unification (canonical provider)
- Download manager network monitor plus resume/retry reliability
- Patient-search client optimization (redundant per-search probe and pool churn removed)
- Windows-on-ARM: Nuitka ARM64/WoA installer variants

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.8` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
