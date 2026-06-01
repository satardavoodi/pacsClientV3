# AIPacs v3.1.6 Release Notes

**Release date:** 2026-06-01
**Branch:** beta-version
**Previous stable:** v3.1.5

---

## Summary

v3.1.6 is a minor release consolidating the v3.1.5 codebase with production stability
improvements and final v3.1.6 production installer (698 MB, Inno Setup 6). All v3.1.5
test infrastructure, command bus, and KPI system features are carried forward and
included in the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.1.6`:

- `pyproject.toml` -> `version = "3.1.6"`
- `main.py` -> `app.setApplicationVersion("3.1.6")`
- `docs/README.md` -> current stable `v3.1.6`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.6`
- `.github/copilot-instructions.md` -> current stable `v3.1.6`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Final v3.1.6 Installer

- Production-ready executable (698 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.1.5 Features (carried forward)

- Test infrastructure reorganization (`tests/code/`)
- GUI test suites (pywinauto, echomind-driven, live walkthroughs)
- EchoMind command bus system (adapters, registry, envelope)
- KPI collection and reporting framework
- Architecture audit docs and regression catalog

### All v3.0.9+ Codebase Features (carried forward)

- Responsive UI scaling (home panel, search, table, series display)
- Crash hardening (faulthandler native-fault logging, viewer/UI patches)
- Multi-study viewer (single-tab grouped sidebar, offset-keyed series)
- Thumbnail pipeline (canonical disk paths, DB hint-only columns)
- Database test isolation + production cleanup tooling
- Zeta Download Manager (atomic writes, single GetStudyInfo probe)
- AI-PACS proprietary EULA (v3.0.9)

---

## Publication

- All v3.1.5 codebase + version bump to 3.1.6 committed
- Tag `v3.1.6` created for release traceability
- Pushed to all configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `main`   → https://github.com/satardavoodi/PacsClientV2/tree/main
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
