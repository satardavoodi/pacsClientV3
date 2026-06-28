# AIPacs v3.4.0 Release Notes

**Release date:** 2026-06-28
**Branch:** beta-version
**Previous stable:** v3.3.9

---

## Summary

v3.4.0 advances the stable version line to the 3.4 series and publishes the full
current beta-version source state to all configured remotes. Highlights: imported
studies now open in the FAST (VTK-free) viewer, a per-series download progress bar
on each thumbnail, smoother and persistent MPR annotations with faster MPR open,
EchoMind command-routing v2 with popup theme/contrast fixes, and CD/portable-viewer
plus web-browser updates.

---

## Version Alignment

The following canonical version markers are set to `3.4.0`:

- `pyproject.toml` -> `version = "3.4.0"`
- `main.py` -> `app.setApplicationVersion("3.4.0")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.0`
- `docs/README.md` -> current stable `v3.4.0`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.0`
- `.github/copilot-instructions.md` -> current stable `v3.4.0`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.0`

LICENSE unchanged.

---

## Included In This Release

- Import opens the FAST (VTK-free) viewer instead of the legacy VTK backend
- Per-series download progress bar inside each thumbnail card
- MPR: smoother ruler/arrow annotations, annotation persistence, layout-switch annotation routing, deferred 3D view for faster MPR open
- EchoMind secretary: command-routing v2, popup theme/contrast fixes, viewer-chat UI refinements
- CD burner: portable-viewer cd_launcher and viewer-locator updates
- Web browser module fixes (autofill, styles, widget)
- Stable version bump to v3.4.0 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.0` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
