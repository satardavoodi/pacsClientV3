# AIPacs v3.1.5 Release Notes

**Release date:** 2026-05-28
**Branch:** beta-version
**Previous stable:** v3.1.4

---

## Summary

v3.1.5 is the final release consolidating the v3.1.4 codebase with final v3.1.5
production installer (687 MB, Inno Setup). All v3.1.4 test infrastructure,
command bus, and KPI system features are carried forward and included in the
bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.1.5`:

- `pyproject.toml` -> `version = "3.1.5"`
- `main.py` -> `app.setApplicationVersion("3.1.5")`
- `docs/README.md` -> current stable `v3.1.5`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.5`
- `.github/copilot-instructions.md` -> current stable `v3.1.5`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Final v3.1.5 Installer

- Production-ready executable (687 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.1.4 Features (carried forward)

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

- All v3.1.4 codebase + version bump to 3.1.5 committed
- Tag `v3.1.5` created for release traceability
- Pushed to all three configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
