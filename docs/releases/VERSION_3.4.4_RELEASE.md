# AIPacs v3.4.4 Release Notes

**Release date:** 2026-07-03
**Branch:** beta-version
**Previous stable:** v3.4.3

---

## Summary

v3.4.4 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It adds a Nuitka-based
optimized build pipeline and continues the patient-loading reliability work
(lifecycle seam-B cutover wiring), plus download-service refinements.

---

## Version Alignment

The following canonical version markers are set to `3.4.4`:

- `pyproject.toml` -> `version = "3.4.4"`
- `main.py` -> `app.setApplicationVersion("3.4.4")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.4`
- `docs/README.md` -> current stable `v3.4.4`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.4`
- `.github/copilot-instructions.md` -> current stable `v3.4.4`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.4`

LICENSE unchanged.

---

## Included In This Release

- Nuitka build pipeline: build_nuitka.py, AIPacs_nuitka.spec.py, build_nuitka_release.py, build_nuitka_simple.cmd, with a completion report and build README
- Patient load lifecycle: seam-B cutover wiring (test-guarded)
- Download manager: home_download_service refinements
- Stable version bump to v3.4.4 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.4` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
