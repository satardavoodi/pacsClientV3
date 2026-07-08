# AIPacs v3.4.7 Release Notes

**Release date:** 2026-07-08
**Branch:** beta-version
**Previous stable:** v3.4.6

---

## Summary

v3.4.7 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It adds Windows-on-ARM
(ARM64) platform support, hardens MPR/3D against GPU/driver failures, fixes two
UI-thread freeze regressions, and improves multi-study display correctness.

---

## Version Alignment

The following canonical version markers are set to `3.4.7`:

- `pyproject.toml` -> `version = "3.4.7"`
- `main.py` -> `app.setApplicationVersion("3.4.7")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.7`
- `docs/README.md` -> current stable `v3.4.7`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.7`
- `.github/copilot-instructions.md` -> current stable `v3.4.7`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.7` (English + Farsi)

LICENSE unchanged.

---

## Included In This Release

- Windows-on-ARM (ARM64): platform plan, ARM64/WoA installers (`AIPacs_Setup_arm64.iss` / `AIPacs_Setup_woa.iss`), `requirements-arm64.txt`, runtime-arch log, WoA runtime profile, ARM64 packaging tests
- MPR/3D robustness: OpenGL pre-flight with a Settings hardware-requirements check, native fault-handler log, crash-evidence collector (WoA ARM64 MPR crash investigation)
- Regression fixes (OPT-22/OPT-23): startup web-browser prewarm idle-gate and EchoMind deferred series-switch (two UI-thread freezes)
- Multi-study: distinct series-append (a series sharing name + count under a different study now displays)
- Release parity: `module_package.json` refresh across plugin packages; release-gate and build refinements
- Stable version bump to v3.4.7 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.7` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
