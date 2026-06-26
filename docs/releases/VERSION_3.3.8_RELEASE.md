# AIPacs v3.3.8 Release Notes

**Release date:** 2026-06-27
**Branch:** beta-version
**Previous stable:** v3.3.7

---

## Summary

v3.3.8 advances the stable version line and publishes the full current
beta-version source state to all configured remotes. It is a viewer performance
and reliability release: a large-series scroll-stall fix, sibling-study
progressive grow, a unified viewer request/cancellation pipeline, and VTK
volume-cache architecture groundwork, all under the unified-pipeline boundary that
keeps the Fast / Advanced / VTK domains cleanly separated.

---

## Version Alignment

The following canonical version markers are set to `3.3.8`:

- `pyproject.toml` -> `version = "3.3.8"`
- `main.py` -> `app.setApplicationVersion("3.3.8")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.3.8`
- `docs/README.md` -> current stable `v3.3.8`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.3.8`
- `.github/copilot-instructions.md` -> current stable `v3.3.8`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.3.8`

LICENSE unchanged.

---

## Included In This Release

- Large-series scroll/stack stall fix (progressive hot-force starvation guard)
- Sibling-study progressive grow by series identity (multi-study studies grow live)
- Unified viewer request pipeline and cancellation registry (stable viewer identity)
- VTK volume-cache and service groundwork (decode-coalescing, pin/unpin) — staged default-off
- Architecture direction: unified pipeline boundary (Fast/Advanced/VTK separation) and S4B VTK cache design
- Batched thumbnail render; resume and identity-shadow guard refinements
- Stable version bump to v3.3.8 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.3.8` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
