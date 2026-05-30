# AIPacs v3.1.4 Release Notes

**Release date:** 2026-05-28
**Branch:** beta-version
**Previous stable:** v3.1.3

---

## Summary

v3.1.4 is the final release consolidating the v3.1.3 codebase with comprehensive
test infrastructure reorganization, command bus system for AI-assisted workflows,
KPI collection and reporting framework, and final v3.1.4 production installer
(687 MB, Inno Setup).

This release represents a major architectural checkpoint: test organization,
automated KPI tracking, and command bus infrastructure are now in place for
scalable AI-driven testing and diagnostics.

---

## Version Alignment

The following canonical version markers are set to `3.1.4`:

- `pyproject.toml` -> `version = "3.1.4"`
- `main.py` -> `app.setApplicationVersion("3.1.4")`
- `docs/README.md` -> current stable `v3.1.4`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.4`
- `.github/copilot-instructions.md` -> current stable `v3.1.4`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Test Infrastructure (new in v3.1.4)

- **Test reorganization:** `tests/` → `tests/code/` with clear separation
- **GUI test suites:**
  - `tests/gui/pywinauto/` — Windows automation tests (close cycles, drag/drop, pixel isolation)
  - `tests/gui/echomind_driven/` — AI command bus integration tests (patient open, bulk download, long sessions)
  - `tests/gui/live_walkthroughs/` — Manual/automated verification scripts
- **Architecture audit docs:**
  - Multi-stage audit snapshots (stages 0–10, 4b)
  - Unified command layer design
  - Regression catalog and scenario KPIs
  - Live validation and testing architecture
- **KPI collection framework:**
  - `tests/_kpi/` schema, collector, reporter
  - Baseline and comparison tooling
  - Automated KPI extraction and dashboarding

### Command Bus System (new in v3.1.4)

- **EchoMind command adapters:**
  - `modules/EchoMind/secretary/adapters/` — system, viewer, download, home, module commands
  - `command_bus.py` — unified command routing
  - `registry.py` — adapter registration and lifecycle
  - `command_envelope.py` — command payload marshaling
- **Bus factory** — orchestration and initialization
- **Integration tests** — command routing, module coverage, KPI auto-recording

### Final v3.1.4 Installer

- Production-ready executable (687 MB, Inno Setup 6)
- Installer metadata, checksums, installation notes
- Staged artifacts: core bundle, plugin packages, update feeds
- Full crash-diagnostics and faulthandler native-fault logging

### All v3.1.3+ Features (carried forward)

- Responsive UI scaling (home panel, search, table, series display)
- Production installers and bundled executables
- Crash hardening (faulthandler native-fault logging, viewer/UI patches)
- Multi-study viewer (single-tab grouped sidebar, offset-keyed series)
- Thumbnail pipeline (canonical disk paths, DB hint-only columns)
- Database test isolation + production cleanup tooling
- Zeta Download Manager (atomic writes, single GetStudyInfo probe)
- AI-PACS proprietary EULA (v3.0.9)

---

## Publication

- All v3.1.3 codebase + test infrastructure + version bump to 3.1.4 committed
- Tag `v3.1.4` created for release traceability
- Pushed to all three configured remotes (beta-version branch):
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3

---

## Key Architectural Improvements

- **Testability:** Unified command bus allows AI agents to drive workflows programmatically
- **Observability:** KPI collection framework provides automated performance tracking
- **Maintainability:** Test organization and audit docs enable faster regression detection
- **Diagnostics:** GUI test runners (pywinauto, echomind-driven) catch UI regressions early
