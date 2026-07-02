# AIPacs v3.4.3 Release Notes

**Release date:** 2026-07-02
**Branch:** beta-version
**Previous stable:** v3.4.2

---

## Summary

v3.4.3 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It focuses on patient-loading
reliability: a deterministic patient/study load lifecycle foundation (done = disk
convergence, identity over liveness) with an additive shadow-diagnostic mode, plus
download series-intent coordination and thumbnail/search refinements.

---

## Version Alignment

The following canonical version markers are set to `3.4.3`:

- `pyproject.toml` -> `version = "3.4.3"`
- `main.py` -> `app.setApplicationVersion("3.4.3")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.3`
- `docs/README.md` -> current stable `v3.4.3`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.3`
- `.github/copilot-instructions.md` -> current stable `v3.4.3`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.3`

LICENSE unchanged.

---

## Included In This Release

- Patient load lifecycle: deterministic study-load model foundation (identity-keyed, disk-convergence completion) with an additive shadow-diagnostic mode (default off)
- Download manager: series-intent coordinator refinements for correct viewing-series prioritization
- Home: thumbnail/status and search refinements (home_download_service, _hp_search)
- Case of the Day: database and widget refinements
- Stable version bump to v3.4.3 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.3` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
