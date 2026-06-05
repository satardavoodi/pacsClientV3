# AIPacs v3.2.0 Release Notes

**Release date:** 2026-06-02
**Branch:** beta-version
**Previous stable:** v3.1.9

---

## Summary

v3.2.0 is a major release consolidating the v3.1.9 codebase with comprehensive production
enhancements and final v3.2.0 production installer (698 MB, Inno Setup 6). All v3.1.9
production improvements and prior test infrastructure, command bus, and KPI system
features are carried forward and included in the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.2.0`:

- `pyproject.toml` -> `version = "3.2.0"`
- `main.py` -> `app.setApplicationVersion("3.2.0")`
- `docs/README.md` -> current stable `v3.2.0`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.2.0`
- `.github/copilot-instructions.md` -> current stable `v3.2.0`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Final v3.2.0 Installer

- Production-ready executable (698 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.1.9 Features (carried forward)

- Production stability improvements from v3.1.9
- Production stability improvements from v3.1.8
- Production stability improvements from v3.1.7
- Production stability improvements from v3.1.6
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

- All v3.1.9 codebase + version bump to 3.2.0 committed
- Tag `v3.2.0` created for release traceability
- Pushed to all configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `main`   → https://github.com/satardavoodi/PacsClientV2/tree/main
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
