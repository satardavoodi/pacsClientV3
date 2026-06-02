# AIPacs v3.1.7 Release Notes

**Release date:** 2026-06-02
**Branch:** beta-version
**Previous stable:** v3.1.6

---

## Summary

v3.1.7 is a minor release consolidating the v3.1.6 codebase with production stability
improvements and final v3.1.7 production installer (698 MB, Inno Setup 6). All v3.1.6
production improvements and prior test infrastructure, command bus, and KPI system
features are carried forward and included in the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.1.7`:

- `pyproject.toml` -> `version = "3.1.7"`
- `main.py` -> `app.setApplicationVersion("3.1.7")`
- `docs/README.md` -> current stable `v3.1.7`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.7`
- `.github/copilot-instructions.md` -> current stable `v3.1.7`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Final v3.1.7 Installer

- Production-ready executable (698 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.1.6 Features (carried forward)

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

- All v3.1.6 codebase + version bump to 3.1.7 committed
- Tag `v3.1.7` created for release traceability
- Pushed to all configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `main`   → https://github.com/satardavoodi/PacsClientV2/tree/main
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
