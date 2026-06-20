# AIPacs v3.3.5 Release Notes

**Release date:** 2026-06-21
**Branch:** beta-version
**Previous stable:** v3.3.4

---

## Summary

v3.3.5 is a minor release that advances the stable version line and generates
an updated fresh build from the current beta-version source state.

---

## Version Alignment

The following canonical version markers are set to `3.3.5`:

- `pyproject.toml` -> `version = "3.3.5"`
- `main.py` -> `app.setApplicationVersion("3.3.5")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.3.5`
- `docs/README.md` -> current stable `v3.3.5`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.3.5`
- `.github/copilot-instructions.md` -> current stable `v3.3.5`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.3.5`

LICENSE unchanged.

---

## Included In This Release

- Stable version bump to v3.3.5 across canonical metadata files
- Release notes updated to the v3.3.5 line
- Fresh release build generated from latest local source state

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.3.5` across canonical metadata files
