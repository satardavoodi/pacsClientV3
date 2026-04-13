# AIPacs Documentation

> **Current Stable Version:** v2.3.3 (2026-04-14)

This is the canonical entrypoint for all project documentation. The docs are organized by concern area so you can find what you need quickly.

## Quick Start for AI Agents

| I need to... | Go to |
|-------------|-------|
| Start viewer investigations (FAST + ADVANCED) | [Viewer Docs Hub](viewer/README.md) |
| Understand the overall architecture | [Architecture Overview](architecture/overview.md) |
| Find a specific file/class/function | `.github/copilot-instructions.md` أ¢â€ â€™ "Complete file map" and "Function lookup" |
| Understand how modules talk to each other | [Module Connections](architecture/module-connections.md) |
| Find test files and run commands | [Test Catalog](architecture/test-catalog.md) + [tests/README.md](../tests/README.md) |
| Check KPIs and performance targets | `.github/copilot-instructions.md` أ¢â€ â€™ "KPI thresholds" |
| Debug a download issue | `.github/copilot-instructions.md` أ¢â€ â€™ "Common debugging patterns" |
| Understand the download pipeline | [Download Pipeline](pipelines/download-pipeline.md) |
| Understand the viewer pipeline | [Viewer Pipeline](pipelines/viewer-pipeline.md) |
| Find config for a specific module | [Module Catalog](modules/README.md) أ¢â€ â€™ "Module Configuration Reference" |
| Find where a signal is emitted/handled | [Module Connections](architecture/module-connections.md) أ¢â€ â€™ "Inter-Module Signal Connections" |
| Check rules before changing timers | `.github/copilot-instructions.md` أ¢â€ â€™ "Critical rules" and "Pipeline latency budget" |

## Quick Navigation

### Architecture & Design
- [Architecture Overview](architecture/overview.md) أ¢â‚¬â€‌ System layers, module boundaries, database and cache responsibilities, KPI snapshot
- [Module Connections & Signal Map](architecture/module-connections.md) أ¢â‚¬â€‌ Inter-module signals, data flow, thread model, timer inventory
- [Repository Layout](architecture/repository-layout.md) أ¢â‚¬â€‌ Standardized folder ownership and conventions
- [Workstation Lifecycle](architecture/workstation-lifecycle.md) أ¢â‚¬â€‌ App startup, session loops, resource lifecycle, shutdown
- [Database Architecture](architecture/database-architecture.md) أ¢â‚¬â€‌ Schema, connection pooling, WAL mode, migration strategy
- [Network Architecture](architecture/network-architecture.md) أ¢â‚¬â€‌ Socket/gRPC protocol, framing, retry, connection health
- [Home UI Services](architecture/home-ui-services.md) أ¢â‚¬â€‌ Thin controller + service layer pattern
- [Test Catalog](architecture/test-catalog.md) أ¢â‚¬â€‌ All test suites, scenarios, KPI thresholds, run commands
- [tests/README.md](../tests/README.md) أ¢â‚¬â€‌ Suite map and practical run routing from the repo test folder

### Pipelines
- [Image Pipeline Reference](pipelines/IMAGE_PIPELINE_REFERENCE.md) أ¢â‚¬â€‌ DICOMأ¢â€ â€™ITKأ¢â€ â€™VTK coordinate transforms (essential)
- [Download Pipeline](pipelines/download-pipeline.md) أ¢â‚¬â€‌ Socketأ¢â€ â€™gRPCأ¢â€ â€™Executorأ¢â€ â€™DBأ¢â€ â€™Disk flow
- [Viewer Pipeline](pipelines/viewer-pipeline.md) أ¢â‚¬â€‌ DBأ¢â€ â€™ImageIOأ¢â€ â€™ITK filtersأ¢â€ â€™VTKأ¢â€ â€™Display flow
- [Viewer Docs Hub](viewer/README.md) أ¢â‚¬â€‌ Canonical FAST vs ADVANCED architecture/debug map
- [FAST vs ADVANCED Architecture](viewer/FAST_vs_ADVANCED_ARCHITECTURE.md) أ¢â‚¬â€‌ Render-owner truth and code-backed split
- [ZetaBoost Pipeline Analysis](pipelines/ZETABOOST_PIPELINE_ANALYSIS.md) أ¢â‚¬â€‌ Multi-lane preload engine design
- [Multi-Pipeline Concurrent Architecture](pipelines/MULTI_PIPELINE_CONCURRENT_ARCHITECTURE.md) أ¢â‚¬â€‌ Concurrent pipeline design (proposed)
- [PyDicom 2D Backend](pipelines/PYDICOM_2D_BACKEND.md) أ¢â‚¬â€‌ Lazy per-slice backend (Phase 1)
- [Phase 2: Tool Overlay Prep](pipelines/PHASE2_TOOL_OVERLAY_PREP.md) أ¢â‚¬â€‌ Backend-independent tool overlay (planned)
- [Fast Mode Download-Viewing Plan](pipelines/FAST_MODE_DOWNLOAD_VIEWING_PLAN.md) أ¢â‚¬â€‌ Progressive viewing during download
- [Pipeline Optimization Research](pipelines/PIPELINE_OPTIMIZATION_RESEARCH_REPORT.md) أ¢â‚¬â€‌ Filter alternatives and optimization analysis

### Stability & Reliability
- [Stability Architecture](stability/STABILITY_ARCHITECTURE.md) أ¢â‚¬â€‌ Resource lifecycle, cache management, loop stability patterns
- [Workstation Loops & Cycles](stability/WORKSTATION_LOOPS.md) أ¢â‚¬â€‌ Repeating operation cycles and their stability guarantees

### Performance
- [Performance Status](performance/PERFORMANCE_STATUS.md) أ¢â‚¬â€‌ **Start here** أ¢â‚¬â€‌ current metrics, open issues, key files
- [FAST Viewer Performance Roadmap](performance/FAST_VIEWER_PERFORMANCE_ROADMAP.md) أ¢â‚¬â€‌ ordered KPI-driven phases, dependencies, stop/go checkpoints
- [FAST Viewer KPI Catalog](performance/FAST_VIEWER_KPI_CATALOG.md) أ¢â‚¬â€‌ component vs system KPI definitions and capture rules
- [FAST Viewer Test Scenarios](performance/FAST_VIEWER_TEST_SCENARIOS.md) أ¢â‚¬â€‌ scenario matrix, setup, pass/fail signals
- [Concurrent Execution Analysis](performance/CONCURRENCY_ANALYSIS_v2.3.3.md) أ¢â‚¬â€‌ workload classes, contention map, queue and cancellation boundaries
- [Metrics Tracking](performance/METRICS_TRACKING_v2.2.3.x.md) أ¢â‚¬â€‌ Phase-by-phase measurements
- [Performance Decision Log (Feb 27)](performance/PERFORMANCE_DECISION_LOG_2026-02-27.md) أ¢â‚¬â€‌ Latest decision rationale
- [Performance Decision Log (Feb 24)](performance/PERFORMANCE_DECISION_LOG_2026-02-24.md) أ¢â‚¬â€‌ Earlier session decisions
- [High-Frequency Loop Optimization](performance/HIGH_FREQUENCY_LOOP_OPTIMIZATION.md) أ¢â‚¬â€‌ 1000+ cycle stability validation
- [Cross-PC Improvement Workflow](performance/CROSS_PC_IMPROVEMENT_WORKFLOW.md) أ¢â‚¬â€‌ PC Aأ¢â€ â€™GitHubأ¢â€ â€™PC B validation cycle
- [Mode B Documentation Index](performance/MODE_B_DOCUMENTATION_INDEX.md) أ¢â‚¬â€‌ Performance doc navigation

### Modules
- [Module Catalog](modules/README.md) أ¢â‚¬â€‌ Active workstation modules, DM internal structure, signal flows

### Development
- [Setup & Tooling](development/setup-and-tooling.md) أ¢â‚¬â€‌ Dependencies, commands, day-to-day workflow
- [Tools Governance & Roadmap](development/tools-governance-and-roadmap.md) أ¢â‚¬â€‌ Rules, lifecycle, and 90-day plan for `tools/`
- [GapGPT API Usage](development/GAPGPT_API_USAGE.md) أ¢â‚¬â€‌ External AI API reference

### Releases
- [Release Notes](releases/RELEASE_NOTES.md) أ¢â‚¬â€‌ Current consolidated release history
- [Version 2.3.3 Release](releases/VERSION_2.3.3_RELEASE.md) أ¢â‚¬â€‌ Stable release notes for the current published version
- [Version 2.2.7 Release](releases/VERSION_2.2.7_RELEASE.md) أ¢â‚¬â€‌ Previous stable release snapshot

### Deployment
- [Windows Release Flow](../builder/docs/WINDOWS_RELEASE_FLOW.md) أ¢â‚¬â€‌ Build, stage, and install workflow for shipping to another PC
- [Installer QA Checklist](../builder/docs/INSTALLER_QA_CHECKLIST.md) أ¢â‚¬â€‌ Cross-PC validation for module selection, first launch, and graphics fallback

### Archive
- [Archive Index](archive/README.md) أ¢â‚¬â€‌ Historical documents (not current truth)
- `archive/performance-history/` أ¢â‚¬â€‌ Historical performance analysis and bottleneck reports
- `archive/design-proposals/` أ¢â‚¬â€‌ Completed or superseded design proposals
- `archive/bug-analysis/` أ¢â‚¬â€‌ Historical bug analysis and code review reports
- `archive/ui-backups/` أ¢â‚¬â€‌ UI snapshot documentation
- `archive/module-framework/` أ¢â‚¬â€‌ Original module system delivery docs
- `archive/root-guides/` أ¢â‚¬â€‌ Legacy implementation guides

### Assets
- `assets/` أ¢â‚¬â€‌ Images and diagrams used by documentation

## Directory Structure

```
docs/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ README.md                  أ¢â€ ع¯ You are here
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ architecture/              أ¢â€ ع¯ System design, layers, lifecycle
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ pipelines/                 أ¢â€ ع¯ Data flow pipelines (image, download, viewer)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stability/                 أ¢â€ ع¯ Resource lifecycle, cache management, loop patterns
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ performance/               أ¢â€ ع¯ Benchmarks, metrics, optimization decisions
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ modules/                   أ¢â€ ع¯ Active module catalog
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ development/               أ¢â€ ع¯ Setup, tooling, external APIs
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ releases/                  أ¢â€ ع¯ Version history
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ archive/                   أ¢â€ ع¯ Historical documents (not current truth)
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ assets/                    أ¢â€ ع¯ Images and diagrams
```

## Documentation Rules

| Directory | Contents | Freshness |
|-----------|----------|-----------|
| `architecture/` | Source-of-truth architecture and structure | Keep current with code |
| `pipelines/` | Data flow references and pipeline design | Update when pipeline changes |
| `stability/` | Reliability patterns and lifecycle management | Update when patterns change |
| `performance/` | Benchmarks and optimization decisions | Update every optimization session |
| `modules/` | Module catalog and integration notes | Update when modules change |
| `development/` | Setup, tooling, workflow | Update when tooling changes |
| `releases/` | Version history | Update per release |
| `archive/` | Historical أ¢â‚¬â€‌ may reference old code/paths | Read-only unless consolidating |

## Known Documentation Debt

- `PacsClient/pacs/patient_tab/zeta mpr/` uses a space in the folder name (runtime depends on dynamic imports).
- Some package-local notes still contain encoding issues or time-bound details.

