# AIPacs v3.4.1 Release Notes

**Release date:** 2026-06-29
**Branch:** beta-version
**Previous stable:** v3.4.0

---

## Summary

v3.4.1 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. Highlights: EchoMind
structured CT/MRI report generation, MPR annotation precision (per-slice binding,
render throttle, click-to-activate cell), correct multi-study per-series study
resolution, and viewer resume/disk-completeness fixes for previous exams.

---

## Version Alignment

The following canonical version markers are set to `3.4.1`:

- `pyproject.toml` -> `version = "3.4.1"`
- `main.py` -> `app.setApplicationVersion("3.4.1")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.1`
- `docs/README.md` -> current stable `v3.4.1`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.1`
- `.github/copilot-instructions.md` -> current stable `v3.4.1`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.1`

LICENSE unchanged.

---

## Included In This Release

- EchoMind viewer-chat: dedicated CT and MRI report generation (openai_reporter) and prompt refinements
- MPR annotations: per-slice binding, render throttle for smoother drawing, click-to-activate the MPR cell, persistence across layout switch
- Multi-study: correct per-series study_pk so colliding series load from the right study
- Viewer resume: canonical on-disk completeness and settle-requires-awaited-series guards (previous exams)
- Stable version bump to v3.4.1 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.1` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
