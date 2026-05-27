# AIPacs v3.1.2 Release Notes

**Release date:** 2026-05-26
**Branch:** beta-version
**Previous stable:** v3.1.1

---

## Summary

v3.1.2 is a patch release consolidating responsive UI scaling updates with the
final v3.1.2 production installer (687 MB, Inno Setup). All v3.1.1 and v3.0.9
features are carried forward and included in the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.1.2`:

- `pyproject.toml` -> `version = "3.1.2"`
- `main.py` -> `app.setApplicationVersion("3.1.2")`
- `docs/README.md` -> current stable `v3.1.2`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.2`
- `.github/copilot-instructions.md` -> current stable `v3.1.2`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Responsive UI Scaling (new in v3.1.2)

- Home panel, search widget, and patient table widget responsive layout updates
  — see `docs/plans/RESPONSIVE_UI_SCALING_PLAN.md`
- Series display grid, selection UI, and patient table scaling improvements
- Dynamic layout adaptation for different screen resolutions and workstation
  configurations

### All v3.1.1 Features (carried forward)

- Production-ready executable installer (687 MB, Inno Setup 6)
- Installer metadata and checksums (`SHA256.txt`, `INSTALL_NOTES.txt`)
- Staged artifacts: core bundle, plugin packages, update feeds, release manifest
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.0.9+ Codebase Features (carried forward)

- Multi-study viewer (single-tab grouped sidebar, offset-keyed series)
- Thumbnail pipeline (canonical disk paths, DB hint-only columns)
- Database test isolation + production cleanup tooling
- Zeta Download Manager (atomic writes, single GetStudyInfo probe)
- Crash hardening (faulthandler native-fault logging, viewer/UI patches)
- AI-PACS proprietary EULA (v3.0.9)

---

## Publication

- All responsive UI scaling updates + version bump to 3.1.2 committed
- Tag `v3.1.2` created for release traceability
- Pushed to all three configured remotes:
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
