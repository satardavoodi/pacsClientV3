# AIPacs v3.2.3 Release Notes

**Release date:** 2026-06-07
**Branch:** beta-version
**Previous stable:** v3.2.2

---

## Summary

v3.2.3 is a minor release consolidating the v3.2.2 codebase with critical input-synchronous
COM crash fix and production stability improvements, delivered with final v3.2.3 production
installer (698 MB, Inno Setup 6). All v3.2.2 and prior production improvements and test
infrastructure, command bus, and KPI system features are carried forward and included in
the bundled executable.

---

## Version Alignment

The following canonical version markers are set to `3.2.3`:

- `pyproject.toml` -> `version = "3.2.3"`
- `main.py` -> `app.setApplicationVersion("3.2.3")`
- `docs/README.md` -> current stable `v3.2.3`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.2.3`
- `.github/copilot-instructions.md` -> current stable `v3.2.3`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Final v3.2.3 Installer

- Production-ready executable (698 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### Critical Crash Fix

- **0x8001010d fatal error:** Input-synchronous COM crash on patient double-click
- **Root cause:** Deferred right-panel thumbnail rebuild executed while double-click
  SendMessage dispatch still on native stack (ThumbnailWidget creation fired outgoing
  UIA/COM call → fatal RPC_E_WRONGTHREAD)
- **Fix:** `_inside_input_synchronous_dispatch()` (user32 InSendMessageEx, fail-open)
  + deferral gates in both renderers (bounded 16ms re-post, generation-safe) + tick-skip
  in display_next_thumbnail

### All v3.2.2 Features (carried forward)

- Production stability improvements from v3.2.2
- Comprehensive production enhancements from v3.2.0
- Production stability improvements from v3.1.9+
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

- All v3.2.2 codebase + version bump to 3.2.3 + crash fix committed
- Tag `v3.2.3` created for release traceability
- Pushed to all configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `main`   → https://github.com/satardavoodi/PacsClientV2/tree/main
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
