# AIPacs v3.1.3 Release Notes

**Release date:** 2026-05-27
**Branch:** beta-version
**Previous stable:** v3.1.2

---

## Summary

v3.1.3 is a patch release bundling the v3.1.2 responsive UI codebase with final
v3.1.3 production installer (687 MB, Inno Setup). All v3.1.2 and v3.0.9 features
are carried forward and included in the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.1.3`:

- `pyproject.toml` -> `version = "3.1.3"`
- `main.py` -> `app.setApplicationVersion("3.1.3")`
- `docs/README.md` -> current stable `v3.1.3`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.3`
- `.github/copilot-instructions.md` -> current stable `v3.1.3`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### All v3.1.2 Features (carried forward)

- Responsive UI scaling implementation and updates (home panel, search, table, series display)
- Production-ready executable installer (687 MB, Inno Setup 6)
- Installer metadata and checksums
- Staged artifacts: core bundle, plugin packages, update feeds, release manifest

### All v3.0.9+ Codebase Features (carried forward)

- Multi-study viewer (single-tab grouped sidebar, offset-keyed series)
- Thumbnail pipeline (canonical disk paths, DB hint-only columns)
- Database test isolation + production cleanup tooling
- Zeta Download Manager (atomic writes, single GetStudyInfo probe)
- Crash hardening (faulthandler native-fault logging, viewer/UI patches)
- AI-PACS proprietary EULA (v3.0.9)

---

## Publication

- All v3.1.2 codebase + version bump to 3.1.3 committed
- Tag `v3.1.3` created for release traceability
- Pushed to all three configured remotes:
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
