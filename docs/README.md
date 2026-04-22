# AIPacs Documentation

> **Current Stable Version:** v2.3.7 (2026-04-22)

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
- [Home UI Services](architecture/home-ui-services.md) â€” Thin controller + service layer pattern
- [Test Catalog](architecture/test-catalog.md) â€” All test suites, scenarios, KPI thresholds, run commands
- [tests/README.md](../tests/README.md) â€” Suite map and practical run routing from the repo test folder

### Pipelines
- [Image Pipeline Reference](pipelines/IMAGE_PIPELINE_REFERENCE.md) â€” DICOMâ†’ITKâ†’VTK coordinate transforms (essential)
- [Download Pipeline](pipelines/download-pipeline.md) â€” Socketâ†’gRPCâ†’Executorâ†’DBâ†’Disk flow
- [Viewer Pipeline](pipelines/viewer-pipeline.md) â€” DBâ†’ImageIOâ†’ITK filtersâ†’VTKâ†’Display flow
- [Viewer Docs Hub](viewer/README.md) â€” Canonical FAST vs ADVANCED architecture/debug map
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

### Plans
- [Plans Index](plans/README.md) â€” canonical home for active planning documents and roadmaps
- [Master Plan](plans/plan.md) â€” current top-level FAST/workstation planning ledger

### Releases
- [Release Notes](releases/RELEASE_NOTES.md) â€” Current consolidated release history
- [Version 2.3.7 Release](releases/VERSION_2.3.7_RELEASE.md) â€” Stable release notes for the current published version
- [Version 2.3.6 Release](releases/VERSION_2.3.6_RELEASE.md) â€” Previous stable release snapshot
- [Version 2.3.5 Release](releases/VERSION_2.3.5_RELEASE.md) â€” Earlier stable release snapshot
- [Version 2.3.4 Release](releases/VERSION_2.3.4_RELEASE.md) â€” Earlier stable release snapshot
- [Version 2.2.7 Release](releases/VERSION_2.2.7_RELEASE.md) â€” Earlier stable release snapshot

### Deployment
- [Windows Release Flow](../builder/docs/WINDOWS_RELEASE_FLOW.md) â€” Build, stage, and install workflow for shipping to another PC
- [Installer QA Checklist](../builder/docs/INSTALLER_QA_CHECKLIST.md) â€” Cross-PC validation for module selection, first launch, and graphics fallback

### Archive
- [Archive Index](archive/README.md) â€” Historical documents (not current truth)
- `archive/performance-history/` â€” Historical performance analysis and bottleneck reports
- `archive/design-proposals/` â€” Completed or superseded design proposals
- `archive/bug-analysis/` â€” Historical bug analysis and code review reports
- `archive/ui-backups/` â€” UI snapshot documentation
- `archive/module-framework/` â€” Original module system delivery docs
- `archive/root-guides/` â€” Legacy implementation guides

### Assets
- `assets/` â€” Images and diagrams used by documentation

## Directory Structure

```
docs/
â”œâ”€â”€ README.md                  â†گ You are here
â”œâ”€â”€ plans/                     â†گ Canonical home for planning docs and roadmaps
â”œâ”€â”€ architecture/              â†گ System design, layers, lifecycle
â”œâ”€â”€ pipelines/                 â†گ Data flow pipelines (image, download, viewer)
â”œâ”€â”€ stability/                 â†گ Resource lifecycle, cache management, loop patterns
â”œâ”€â”€ performance/               â†گ Benchmarks, metrics, optimization decisions
â”œâ”€â”€ modules/                   â†گ Active module catalog
â”œâ”€â”€ development/               â†گ Setup, tooling, external APIs
â”œâ”€â”€ releases/                  â†گ Version history
â”œâ”€â”€ archive/                   â†گ Historical documents (not current truth)
â””â”€â”€ assets/                    â†گ Images and diagrams
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

