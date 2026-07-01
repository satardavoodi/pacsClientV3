# AIPacs v3.4.2 Release Notes

**Release date:** 2026-07-01
**Branch:** beta-version
**Previous stable:** v3.4.1

---

## Summary

v3.4.2 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It is a large batch spanning
dental imaging, the FAST viewer, startup/responsiveness, and the AI assistant:
dual-arch/oblique dental panoramic reconstruction and nerve-canal tracing,
multi-frame/cine playback, chunked startup and patient-switch loading, additional
EchoMind report types, and multi-study/previous-exam grow correctness.

---

## Version Alignment

The following canonical version markers are set to `3.4.2`:

- `pyproject.toml` -> `version = "3.4.2"`
- `main.py` -> `app.setApplicationVersion("3.4.2")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.2`
- `docs/README.md` -> current stable `v3.4.2`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.2`
- `.github/copilot-instructions.md` -> current stable `v3.4.2`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.2`

LICENSE unchanged.

---

## Included In This Release

- Dental Imaging: dual-arch/oblique panoramic reconstruction, mandibular nerve-canal tracing, planning/measurement tools, geometry sync
- FAST viewer: multi-frame / cine playback (ultrasound, XA, enhanced CT/MR) with cine metadata and player
- Responsiveness: async thumbnail save, chunked status refresh and sidebar build, warmup dispatch, startup stage sub-timing, KPI session-report tooling
- EchoMind: mammography and ultrasound reporters, GapGPT connection test, reporter refinements
- Multi-study/previous-exam: canonical on-disk count for offset keys and grow-displayed-to-disk (secondary series grow correctly)
- Stable version bump to v3.4.2 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.2` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
