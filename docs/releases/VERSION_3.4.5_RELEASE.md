# AIPacs v3.4.5 Release Notes

**Release date:** 2026-07-04
**Branch:** beta-version
**Previous stable:** v3.4.4

---

## Summary

v3.4.5 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It consolidates the
Optimization/Stability/Reliability master-plan work: OPT-01 startup-freeze
removals, multi-study wrong-study correctness guards, a patient-data
storage-cleanup fix, and lifecycle-shadow refinements.

---

## Version Alignment

The following canonical version markers are set to `3.4.5`:

- `pyproject.toml` -> `version = "3.4.5"`
- `main.py` -> `app.setApplicationVersion("3.4.5")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.5`
- `docs/README.md` -> current stable `v3.4.5`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.5`
- `.github/copilot-instructions.md` -> current stable `v3.4.5`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.5`

LICENSE unchanged.

---

## Included In This Release

- Startup performance (OPT-01): deferred startup work, DICOM-only status refresh, theme-apply de-duplication
- Multi-study correctness: primary-series poison guard and viewport study-identity gate (no wrong study/series after viewing a previous exam), plus a current-series display-miss fix
- Storage: filtered Patient Data Cleanup fix (Viewer Config)
- Reliability: patient-load lifecycle shadow refinements and the consolidated optimization/stability/reliability master plan
- Stable version bump to v3.4.5 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.5` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
