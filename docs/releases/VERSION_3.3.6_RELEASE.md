# AIPacs v3.3.6 Release Notes

**Release date:** 2026-06-21
**Branch:** beta-version
**Previous stable:** v3.3.5

---

## Summary

v3.3.6 advances the stable version line and publishes the full current
beta-version source state to all configured remotes. It focuses on viewer/MPR
stability, voice-attachment de-duplication, correct multi-study series grouping,
and download reliability, plus offscreen sandbox testing tooling.

---

## Version Alignment

The following canonical version markers are set to `3.3.6`:

- `pyproject.toml` -> `version = "3.3.6"`
- `main.py` -> `app.setApplicationVersion("3.3.6")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.3.6`
- `docs/README.md` -> current stable `v3.3.6`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.3.6`
- `.github/copilot-instructions.md` -> current stable `v3.3.6`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.3.6`

LICENSE unchanged.

---

## Included In This Release

- MPR preserved on series switch and on load into another viewport
- Voice-attachment de-duplication (no duplicate voice on reopen)
- Correct multi-study series-to-study bucketing (wrong-study fix + primary fallback)
- Download reliability: oversize fast-fail + first-image pagination alignment
- DB-first metadata for multi-study patients
- Offscreen sandbox test lane tooling and comprehensive audit reports
- Stable version bump to v3.3.6 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.3.6` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
