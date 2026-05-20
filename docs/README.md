# AIPacs Documentation

> **Current Stable Version:** v3.0.8 (2026-05-20)

This is the canonical entrypoint for all project documentation. The docs are organized by concern area so you can find what you need quickly.

## Quick Start for AI Agents

| I need to... | Go to |
|-------------|-------|
| Start viewer investigations (FAST + ADVANCED) | [Viewer Docs Hub](viewer/README.md) |
| Understand the overall architecture | [Architecture Overview](architecture/overview.md) |
| Find a specific file/class/function | `.github/copilot-instructions.md` â†’ "Complete file map" and "Function lookup" |
| Understand how modules talk to each other | [Module Connections](architecture/module-connections.md) |
| Find test files and run commands | [Test Catalog](architecture/test-catalog.md) + [tests/README.md](../tests/README.md) |
| Check KPIs and performance targets | `.github/copilot-instructions.md` â†’ "KPI thresholds" |
| Debug a download issue | `.github/copilot-instructions.md` â†’ "Common debugging patterns" |
| Understand the download pipeline | [Download Pipeline](pipelines/download-pipeline.md) |
| Understand the viewer pipeline | [Viewer Pipeline](pipelines/viewer-pipeline.md) |
| Find config for a specific module | [Module Catalog](modules/README.md) â†’ "Module Configuration Reference" |
| Find where a signal is emitted/handled | [Module Connections](architecture/module-connections.md) â†’ "Inter-Module Signal Connections" |
| Check rules before changing timers | `.github/copilot-instructions.md` â†’ "Critical rules" and "Pipeline latency budget" |

## Quick Navigation

### Architecture & Design
- [Architecture Overview](architecture/overview.md) â€” System layers, module boundaries, database and cache responsibilities, KPI snapshot
- [Module Connections & Signal Map](architecture/module-connections.md) â€” Inter-module signals, data flow, thread model, timer inventory
- [Repository Layout](architecture/repository-layout.md) â€” Standardized folder ownership and conventions
- [Workstation Lifecycle](architecture/workstation-lifecycle.md) â€” App startup, session loops, resource lifecycle, shutdown
- [Database Architecture](architecture/database-architecture.md) â€” Schema, connection pooling, WAL mode, migration strategy
- [Network Architecture](architecture/network-architecture.md) â€” Socket/gRPC protocol, framing, retry, connection health
- [Home UI Services](architecture/home-ui-services.md) â€” Thin controller + service layer pattern- [Doc Summary](architecture/DOC_SUMMARY.md) â€" One-page structural survey of the entire docs/ tree- [Test Catalog](architecture/test-catalog.md) â€” All test suites, scenarios, KPI thresholds, run commands
- [tests/README.md](../tests/README.md) â€” Suite map and practical run routing from the repo test folder

### Pipelines
- [Image Pipeline Reference](pipelines/IMAGE_PIPELINE_REFERENCE.md) â€” DICOMâ†’ITKâ†’VTK coordinate transforms (essential)
- [Download Pipeline](pipelines/download-pipeline.md) â€” Socketâ†’gRPCâ†’Executorâ†’DBâ†’Disk flow
- [Viewer Pipeline](pipelines/viewer-pipeline.md) â€” DBâ†’ImageIOâ†’ITK filtersâ†’VTKâ†’Display flow
- [Viewer Docs Hub](viewer/README.md) â€” Canonical FAST vs ADVANCED architecture/debug map
- [FAST Mammography Regression Playbook](viewer/FAST_MAMMOGRAPHY_REGRESSION_PLAYBOOK_2026-05-19.md) â€” Recovery checklist and non-regression rules for FAST MG display issues
- [FAST vs ADVANCED Architecture](viewer/FAST_vs_ADVANCED_ARCHITECTURE.md) â€” Render-owner truth and code-backed split
- [ZetaBoost Pipeline Analysis](pipelines/ZETABOOST_PIPELINE_ANALYSIS.md) â€” Multi-lane preload engine design
- [Multi-Pipeline Concurrent Architecture](pipelines/MULTI_PIPELINE_CONCURRENT_ARCHITECTURE.md) â€” Concurrent pipeline design (proposed)
- [PyDicom 2D Backend](pipelines/PYDICOM_2D_BACKEND.md) â€” Lazy per-slice backend (Phase 1)
- [Phase 2: Tool Overlay Prep](pipelines/PHASE2_TOOL_OVERLAY_PREP.md) â€” Backend-independent tool overlay (planned)
- [Fast Mode Download-Viewing Plan](plans/pipelines/FAST_MODE_DOWNLOAD_VIEWING_PLAN.md) â€” Progressive viewing during download
- [Pipeline Optimization Research](pipelines/PIPELINE_OPTIMIZATION_RESEARCH_REPORT.md) â€” Filter alternatives and optimization analysis

### Stability & Reliability
- [Stability Architecture](stability/STABILITY_ARCHITECTURE.md) â€” Resource lifecycle, cache management, loop stability patterns
- [Workstation Loops & Cycles](stability/WORKSTATION_LOOPS.md) â€” Repeating operation cycles and their stability guarantees

### Performance
- [Performance Status](performance/PERFORMANCE_STATUS.md) â€” **Start here** â€” current metrics, open issues, key files
- [FAST Viewer Performance Roadmap](plans/performance/FAST_VIEWER_PERFORMANCE_ROADMAP.md) â€” ordered KPI-driven phases, dependencies, stop/go checkpoints
- [FAST Viewer KPI Catalog](performance/FAST_VIEWER_KPI_CATALOG.md) â€” component vs system KPI definitions and capture rules
- [FAST Viewer Test Scenarios](performance/FAST_VIEWER_TEST_SCENARIOS.md) â€” scenario matrix, setup, pass/fail signals
- [Concurrent Execution Analysis](performance/CONCURRENCY_ANALYSIS_v2.3.3.md) â€” workload classes, contention map, queue and cancellation boundaries
- [Metrics Tracking](performance/METRICS_TRACKING_v2.2.3.x.md) â€” Phase-by-phase measurements
- [Performance Decision Log (Feb 27)](performance/PERFORMANCE_DECISION_LOG_2026-02-27.md) â€” Latest decision rationale
- [Performance Decision Log (Feb 24)](performance/PERFORMANCE_DECISION_LOG_2026-02-24.md) â€” Earlier session decisions
- [High-Frequency Loop Optimization](performance/HIGH_FREQUENCY_LOOP_OPTIMIZATION.md) â€” 1000+ cycle stability validation
- [Cross-PC Improvement Workflow](performance/CROSS_PC_IMPROVEMENT_WORKFLOW.md) â€” PC Aâ†’GitHubâ†’PC B validation cycle
- [Mode B Documentation Index](performance/MODE_B_DOCUMENTATION_INDEX.md) â€” Performance doc navigation

### Modules
- [Module Catalog](modules/README.md) â€” Active workstation modules, DM internal structure, signal flows

### Development
- [Setup & Tooling](development/setup-and-tooling.md) â€” Dependencies, commands, day-to-day workflow
- [Tools Governance & Roadmap](development/tools-governance-and-roadmap.md) â€” Rules, lifecycle, and 90-day plan for `tools/`
- [GapGPT API Usage](development/GAPGPT_API_USAGE.md) â€” External AI API reference
- [T6 Preparation Notes](development/T6_PREPARATION.md) — Lazy-slice callback TOCTOU guard analysis (read-only; no fix needed)
- [H13 Do-Not-Repeat](development/NEXT_AGENT_DO_NOT_REPEAT.md) — Exhausted approaches from H13 VTK crash investigation

### Plans
- [Plans Index](plans/README.md) — canonical home for active planning documents and roadmaps
- [Master Plan](plans/plan.md) — current top-level FAST/workstation planning ledger
- [Next Agent Handoff](plans/NEXT_AGENT_HANDOFF.md) — Current session handoff summary and short-term goals
- [Next Agent Reading Order](plans/NEXT_AGENT_READING_ORDER.md) — Ordered reading list before making changes
- [Next Agent Open Questions](plans/NEXT_AGENT_OPEN_QUESTIONS.md) — Outstanding questions for the next work session
- [Large File Refactoring Roadmap](plans/development/large-file-refactoring-roadmap.md) — P1–P6 large-file split plan

### Releases
- [Release Notes](releases/RELEASE_NOTES.md) — Current consolidated release history
- [Version 3.0.3 Release](releases/VERSION_3.0.3_RELEASE.md) — FAST-to-MPR route hardening and geometry boundary stabilization
- [Version 2.4.7c Release](releases/VERSION_2.4.7c_RELEASE.md) — Current conservative FAST cache release notes
- [Version 2.4.6 Release](releases/VERSION_2.4.6_RELEASE.md) — Previous stable release notes
- [Version 2.4.5 Release](releases/VERSION_2.4.5_RELEASE.md) — Previous stable release notes
- [Version 2.4.4 Release](releases/VERSION_2.4.4_RELEASE.md) — Previous stable release notes
- [Version 2.4.3 Release](releases/VERSION_2.4.3_RELEASE.md) — Previous stable release snapshot
- [Version 2.3.6 Release](releases/VERSION_2.3.6_RELEASE.md) — Earlier stable release snapshot
- [Version 2.3.5 Release](releases/VERSION_2.3.5_RELEASE.md) â€” Earlier stable release snapshot
- [Version 2.3.4 Release](releases/VERSION_2.3.4_RELEASE.md) â€” Earlier stable release snapshot
- [Version 2.2.7 Release](releases/VERSION_2.2.7_RELEASE.md) â€” Earlier stable release snapshot

### Build & Deployment
- [Build Systems Index](../builder/docs/README.md) â€" Canonical split between the PyInstaller builder and the staged Nuitka builder
- [Advanced MPR Build/Runtime Integration](../builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md) â€" Canonical anti-regression guide for packaging and launching Advanced MPR
- [Windows Release Flow](../builder/docs/WINDOWS_RELEASE_FLOW.md) â€" Build, stage, and install workflow for shipping to another PC
- [Build Document](../builder/docs/BUILD_DOCUMENT.md) â€" Long-lived PyInstaller packaging knowledge base (VTK, PySide6, SimpleITK notes)
- [Nuitka Build Plan](../builder/docs/NUITKA_BUILD_PLAN.md) â€" Staged incremental Nuitka pipeline status, checkpoints, and next execution steps
- [Build Checklist](../builder/docs/BUILD_CHECKLIST.md) â€" Step-by-step pre-release validation checklist
- [Installer QA Checklist](../builder/docs/INSTALLER_QA_CHECKLIST.md) â€" Cross-PC validation for module selection, first launch, and graphics fallback
- [Privacy & Data Policy](../builder/docs/PRIVACY_AND_DATA_POLICY.md) â€" What is and is not packaged into the release bundle
- **Setup scripts** (run on any PC after git clone, before building):
  - [`setup_env.ps1`](../setup_env.ps1) â€" Creates `.venv` development environment for day-to-day work
  - [`setup_build_env.ps1`](../setup_build_env.ps1) â€" Creates `.venv_build` release-build environment required by `build.bat`
- **PyInstaller builder (`builder/`) commands:**
  - `\.\build.bat` â€" Full pipeline: PyInstaller â†' stage â†' plugin packages â†' Inno Setup installer
  - `\.\build.bat --skip-pyinstaller` â€" Reuse existing `dist/`, only restage and compile installer
  - `\.\build.bat --skip-installer-compile` â€" Stage but skip Inno Setup (ISCC not required)
- **Nuitka builder (`builder nuitka/`) commands:**
  - `\.\build_nuitka.bat` â€" Route into the staged Nuitka pipeline (resume by default)
  - `\.\build_nuitka_release.bat` â€" Full Nuitka release wrapper with build-venv bootstrap
  - `\.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume` â€" Resume the staged Nuitka pipeline directly

### Archive
- [Archive Index](archive/README.md) â€” Historical documents (not current truth)
- `archive/performance-history/` â€” Historical performance analysis and bottleneck reports
- `archive/design-proposals/` â€” Completed or superseded design proposals
- `archive/bug-analysis/` â€” Historical bug analysis and code review reports
- `archive/ui-backups/` â€” UI snapshot documentation
- `archive/module-framework/` â€” Original module system delivery docs
- `archive/root-guides/` â€” Legacy implementation guides
- `archive/root-investigations/` â€” Root-level forensic/investigation bundles moved out of repository root

### Assets
- `assets/` â€” Images and diagrams used by documentation

## Directory Structure

```
docs/
|-- README.md                    <- You are here
|-- analysis/                    <- ClearCanvas / Cornerstone comparisons and KPI mapping
|-- architecture/                <- System design, layers, lifecycle
|   |-- DOC_SUMMARY.md           <- One-page structural survey of all docs/
|   `-- ...
|-- plans/                       <- Canonical home for planning docs and roadmaps
|   |-- development/             <- File-refactoring roadmaps and migration plans
|   |-- performance/             <- Ordered KPI-driven phases and stop/go checkpoints
|   |-- pipelines/               <- Progressive viewer and fast-mode plans
|   |-- NEXT_AGENT_HANDOFF.md    <- Handoff summary for the next session
|   |-- NEXT_AGENT_READING_ORDER.md
|   |-- NEXT_AGENT_OPEN_QUESTIONS.md
|   `-- ...
|-- pipelines/                   <- Data flow pipelines (image, download, viewer)
|-- stability/                   <- Resource lifecycle, cache management, loop patterns
|-- performance/                 <- Benchmarks, metrics, optimization decisions
|-- viewer/                      <- FAST vs ADVANCED viewer architecture and debug maps
|-- modules/                     <- Active module catalog
|-- development/                 <- Setup, tooling, investigation notes
|   |-- NEXT_AGENT_DO_NOT_REPEAT.md  <- H13 VTK crash exhausted approaches
|   |-- T6_PREPARATION.md            <- T6 lazy-slice TOCTOU guard analysis
|   `-- ...
|-- releases/                    <- Version history
|-- archive/                     <- Historical documents (not current truth)
|   |-- root-investigations/     <- Former root forensic bundles (organized by date/topic)
`-- assets/                      <- Images and diagrams

Build & release infrastructure (separate from docs/):
  builder/docs/                  <- Shared build-doc index plus per-builder documentation
  builder/                       <- PyInstaller-based builder root
  builder/spec/                  <- PyInstaller spec
  builder/installer/             <- PyInstaller Inno Setup script
  builder/plugin package/        <- Plugin package definitions
  builder/requirements/          <- Pinned build toolchain
  builder nuitka/                <- Separate staged Nuitka builder root
  setup_build_env.ps1            <- Shared .venv_build setup for both builders
  build.bat / build.py           <- PyInstaller builder entry points
  build_nuitka.bat / build_nuitka_release.bat <- Nuitka builder entry points
```

## Documentation Rules

| Directory | Contents | Freshness |
|-----------|----------|-----------|
| `architecture/` | Source-of-truth architecture and structure | Keep current with code |
| `plans/` | Active planning docs, recovery plans, and roadmaps | Put new plans here |
| `pipelines/` | Data flow references and pipeline design | Update when pipeline changes |
| `stability/` | Reliability patterns and lifecycle management | Update when patterns change |
| `performance/` | Benchmarks and optimization decisions | Update every optimization session |
| `modules/` | Module catalog and integration notes | Update when modules change |
| `development/` | Setup, tooling, workflow | Update when tooling changes |
| `releases/` | Version history | Update per release |
| `archive/` | Historical â€” may reference old code/paths | Read-only unless consolidating |

## Known Documentation Debt

- `PacsClient/pacs/patient_tab/zeta mpr/` uses a space in the folder name (runtime depends on dynamic imports).
- Some package-local notes still contain encoding issues or time-bound details.
- `docs/archive/reference-bundles/clear-canvas/` is an archived duplicate bundle kept only for historical reading order; canonical ClearCanvas docs now live in `docs/analysis/`, `docs/architecture/`, and `docs/plans/`.

