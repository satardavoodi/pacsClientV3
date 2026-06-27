# AIPacs v3.3.9 Release Notes

**Release date:** 2026-06-27
**Branch:** beta-version
**Previous stable:** v3.3.8

---

## Summary

v3.3.9 advances the stable version line and publishes the full current
beta-version source state to all configured remotes. It is a viewer interaction
and responsiveness release: a patient/tab/app-close freeze fix, slow-link
progressive grow, annotation creation-mode lockout across both viewer backends,
and Sync Image viewport-click preservation, plus web-browser module fixes.

---

## Version Alignment

The following canonical version markers are set to `3.3.9`:

- `pyproject.toml` -> `version = "3.3.9"`
- `main.py` -> `app.setApplicationVersion("3.3.9")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.3.9`
- `docs/README.md` -> current stable `v3.3.9`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.3.9`
- `.github/copilot-instructions.md` -> current stable `v3.3.9`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.3.9`

LICENSE unchanged.

---

## Included In This Release

- Patient/tab/app-close freeze fix (GC deferred and coalesced off the close path)
- Slow-connection progressive grow (series grow step-by-step on weak links)
- Annotation creation-mode lockout across FAST and Advanced backends
- Sync Image: viewport-click switches active viewer, preserves sync, places the point
- Inactive-tab resume skip (no background churn stealing GUI cycles)
- Web browser module: autofill, page tools, prewarm, and styling/stability fixes
- MPR-open freeze optimization plan and groundwork
- Stable version bump to v3.3.9 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.3.9` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
