# AIPacs Documentation

> **Current Stable Version:** v2.2.3.4.0 (2026-02-27)

This is the canonical entrypoint for all project documentation. The docs are organized by concern area so you can find what you need quickly.

## Quick Navigation

### Architecture & Design
- [Architecture Overview](architecture/overview.md) — System layers, module boundaries, database and cache responsibilities
- [Repository Layout](architecture/repository-layout.md) — Standardized folder ownership and conventions
- [Workstation Lifecycle](architecture/workstation-lifecycle.md) — App startup, session loops, resource lifecycle, shutdown
- [Database Architecture](architecture/database-architecture.md) — Schema, connection pooling, WAL mode, migration strategy

### Pipelines
- [Image Pipeline Reference](pipelines/IMAGE_PIPELINE_REFERENCE.md) — DICOM→ITK→VTK coordinate transforms (essential)
- [Download Pipeline](pipelines/download-pipeline.md) — Socket→gRPC→Executor→DB→Disk flow
- [Viewer Pipeline](pipelines/viewer-pipeline.md) — DB→ImageIO→ITK filters→VTK→Display flow
- [ZetaBoost Pipeline Analysis](pipelines/ZETABOOST_PIPELINE_ANALYSIS.md) — Multi-lane preload engine design
- [Multi-Pipeline Concurrent Architecture](pipelines/MULTI_PIPELINE_CONCURRENT_ARCHITECTURE.md) — Concurrent pipeline design (proposed)
- [PyDicom 2D Backend](pipelines/PYDICOM_2D_BACKEND.md) — Lazy per-slice backend (Phase 1)
- [Phase 2: Tool Overlay Prep](pipelines/PHASE2_TOOL_OVERLAY_PREP.md) — Backend-independent tool overlay (planned)
- [Fast Mode Download-Viewing Plan](pipelines/FAST_MODE_DOWNLOAD_VIEWING_PLAN.md) — Progressive viewing during download
- [Pipeline Optimization Research](pipelines/PIPELINE_OPTIMIZATION_RESEARCH_REPORT.md) — Filter alternatives and optimization analysis

### Stability & Reliability
- [Stability Architecture](stability/STABILITY_ARCHITECTURE.md) — Resource lifecycle, cache management, loop stability patterns
- [Workstation Loops & Cycles](stability/WORKSTATION_LOOPS.md) — Repeating operation cycles and their stability guarantees

### Performance
- [Performance Status](performance/PERFORMANCE_STATUS.md) — **Start here** — current metrics, open issues, key files
- [Metrics Tracking](performance/METRICS_TRACKING_v2.2.3.x.md) — Phase-by-phase measurements
- [Performance Decision Log (Feb 27)](performance/PERFORMANCE_DECISION_LOG_2026-02-27.md) — Latest decision rationale
- [Performance Decision Log (Feb 24)](performance/PERFORMANCE_DECISION_LOG_2026-02-24.md) — Earlier session decisions
- [High-Frequency Loop Optimization](performance/HIGH_FREQUENCY_LOOP_OPTIMIZATION.md) — 1000+ cycle stability validation
- [Cross-PC Improvement Workflow](performance/CROSS_PC_IMPROVEMENT_WORKFLOW.md) — PC A→GitHub→PC B validation cycle
- [Mode B Documentation Index](performance/MODE_B_DOCUMENTATION_INDEX.md) — Performance doc navigation

### Modules
- [Module Catalog](modules/README.md) — Active workstation modules and integration notes

### Development
- [Setup & Tooling](development/setup-and-tooling.md) — Dependencies, commands, day-to-day workflow
- [GapGPT API Usage](development/GAPGPT_API_USAGE.md) — External AI API reference

### Releases
- [Release Notes](releases/RELEASE_NOTES.md) — Current consolidated release history

### Archive
- [Archive Index](archive/README.md) — Historical documents (not current truth)
- `archive/performance-history/` — Historical performance analysis and bottleneck reports
- `archive/design-proposals/` — Completed or superseded design proposals
- `archive/bug-analysis/` — Historical bug analysis and code review reports
- `archive/ui-backups/` — UI snapshot documentation
- `archive/module-framework/` — Original module system delivery docs
- `archive/root-guides/` — Legacy implementation guides

### Assets
- `assets/` — Images and diagrams used by documentation

## Directory Structure

```
docs/
├── README.md                  ← You are here
├── architecture/              ← System design, layers, lifecycle
├── pipelines/                 ← Data flow pipelines (image, download, viewer)
├── stability/                 ← Resource lifecycle, cache management, loop patterns
├── performance/               ← Benchmarks, metrics, optimization decisions
├── modules/                   ← Active module catalog
├── development/               ← Setup, tooling, external APIs
├── releases/                  ← Version history
├── archive/                   ← Historical documents (not current truth)
└── assets/                    ← Images and diagrams
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
| `archive/` | Historical — may reference old code/paths | Read-only unless consolidating |

## Known Documentation Debt

- `PacsClient/pacs/patient_tab/zeta mpr/` uses a space in the folder name (runtime depends on dynamic imports).
- Some package-local notes still contain encoding issues or time-bound details.
