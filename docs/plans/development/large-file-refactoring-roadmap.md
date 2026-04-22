# Plan: Large File Refactoring Roadmap

## TL;DR
Split the 6 largest Python files (7,460 / 5,540 / 5,410 / 1,200 / 1,100 / 1,074 lines) into focused, well-organized submodules with backward-compatible shims, meaningful folder structure, and AI-agent-friendly documentation. Follow the proven database-split pattern (v2.2.9.0). No runtime performance impact — strictly maintainability and AI-agent discoverability.

---

## File Inventory (by priority)

| Priority | File | Lines | Reason |
|----------|------|-------|--------|
| P1 | `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py` | 7,460 | Largest file; mixes UI, sync, reference lines, pipelines, legacy code, advanced tools |
| P2 | `modules/download_manager/ui/main_widget.py` | 5,540 | Single 5500-line QWidget; mixes UI setup, progress, workers, details, theming |
| P3 | `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` | 5,410 | "Thin controller" that grew back; mixes search, import, modules, priority, legacy |
| P4 | `modules/zeta_boost/engine.py` | 1,200 | Monolithic cache engine; mixes cache, lanes, failsafe, health |
| P5 | `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` | 1,100 | 4-layer completion protocol; complex but already a mixin |
| P6 | `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | 1,074 | Hub combining 7 mixins; could slim further |

### Already well-split (no action needed)
- `database/core.py` → split into 6 domain files (v2.2.9.0) ✅
- Viewer controller mixins (`_vc_*.py`) → good granularity ✅
- Home UI services (`home_*_service.py`) → good delegation ✅
- Download manager core/state/rules/workers → already modular ✅

---

## Guiding Principles

1. **Backward compatibility first**: Every split file gets a shim in the original location that re-exports all public names. Zero import breakage for callers.
2. **Follow the database-split pattern**: The `database/core.py` → 6-file split (v2.2.9.0) is the proven reference.
3. **Meaningful folder structure**: Split files go into purpose-named subfolders, not flat alongside the original.
4. **Module-level `__init__.py` re-exports**: Each new subfolder has an `__init__.py` that exports the public API.
5. **Documentation per subfolder**: Each new subfolder gets a brief `README.md` explaining files, classes, and integration points.
6. **One PR per priority file**: Each P-level is an independent, testable unit of work.
7. **Test before and after**: Run the relevant test suite before splitting (baseline) and after (regression).

---

## Phase 1: patient_widget.py (P1) — 7,454 → 11 files ✅ COMPLETED

**Completed:** 2026-04-05

### Result
`PatientWidget` (7,454 lines) split into 9 mixin files + 1 core widget + 1 `__init__.py` inside `patient_widget_core/`. The original `patient_widget.py` is now a 32-line backward-compatible shim.

### Actual folder structure
```
PacsClient/pacs/patient_tab/ui/patient_ui/
├── patient_widget.py                    ← SHIM (32 lines): re-exports PatientWidget + helpers
├── patient_widget_core/                 ← NEW PACKAGE
│   ├── __init__.py                      ← re-exports PatientWidget
│   ├── README.md                        ← documentation (file map, MRO, rules, tests)
│   ├── widget.py                        ← PatientWidget core: __init__, signals, properties (368 lines)
│   ├── _pw_sync.py                      ← _PWSyncMixin: sync point, lock sync, ref lines, DICOM mapping (1,050 lines)
│   ├── _pw_advanced.py                  ← _PWAdvancedMixin: Advanced Analysis, MPR, stitching, Eagle Eye (1,068 lines)
│   ├── _pw_panels.py                    ← _PWPanelsMixin: header, sidebar, thumbnails, reception, AI chat (775 lines)
│   ├── _pw_viewers.py                   ← _PWViewersMixin: viewer creation, VTK widgets, slider, grid (638 lines)
│   ├── _pw_series.py                    ← _PWSeriesMixin: series loading, display, search, progress (898 lines)
│   ├── _pw_pipeline.py                  ← _PWPipelineMixin: pipelines, startup, progressive display (1,298 lines)
│   ├── _pw_thumbnails.py               ← _PWThumbnailsMixin: server thumbnails, series info (386 lines)
│   ├── _pw_metadata.py                  ← _PWMetadataMixin: metadata, caching, grid config (407 lines)
│   └── _pw_lifecycle.py                 ← _PWLifecycleMixin: priority queue, cleanup, theme, tools (726 lines)
```

### Pattern used
- **Mixin classes** assembled via multiple inheritance (matches existing `_vc_*.py` pattern)
- `PatientWidget(_PWSyncMixin, _PWAdvancedMixin, ..., QWidget)` in `widget.py`
- Each mixin has its own imports at file top
- Original `patient_widget.py` is a thin shim re-exporting `PatientWidget` + all module-level names

### Test results (all passing)
- Smoke tests: 24/24 ✅
- Viewer pipeline tests: 19/19 ✅
- Connection tests: 1/1 ✅
- DM tests: 129/129 (27 scenarios) ✅

---

## Phase 2: main_widget.py — DM UI (P2) — 5,534 → 11 files ✅ COMPLETED

**Completed:** 2026-04-05

### Result
`DownloadManagerWidget` (5,534 lines) split into 9 mixin files + 1 core widget + 1 `__init__.py` inside `widget/`. The original `main_widget.py` is now a ~25-line backward-compatible shim.

### Actual folder structure
```
modules/download_manager/ui/
├── main_widget.py                       ← SHIM (~25 lines): re-exports DownloadManagerWidget + helpers
├── widget/                              ← NEW PACKAGE
│   ├── __init__.py                      ← re-exports DownloadManagerWidget
│   ├── README.md                        ← documentation (file map, MRO, signals, rules, tests)
│   ├── widget.py                        ← DownloadManagerWidget core: __init__, signals, property (320 lines)
│   ├── _dm_ui_setup.py                  ← _DMUISetupMixin: header, toolbar, queue, details panel (812 lines)
│   ├── _dm_queue.py                     ← _DMQueueMixin: add/update/remove rows, progress, badges (630 lines)
│   ├── _dm_controls.py                  ← _DMControlsMixin: play, pause, clear, start, cancel, retry (571 lines)
│   ├── _dm_workers.py                   ← _DMWorkersMixin: worker start, progress, complete, error, health (855 lines)
│   ├── _dm_retry.py                     ← _DMRetryMixin: per-patient/series non-blocking retry (587 lines)
│   ├── _dm_details.py                   ← _DMDetailsMixin: selection, details, table ordering (887 lines)
│   ├── _dm_priority.py                  ← _DMPriorityMixin: critical series, viewed series, preemption (427 lines)
│   ├── _dm_reception.py                 ← _DMReceptionMixin: reception data load/apply (299 lines)
│   └── _dm_theming.py                   ← _DMThemingMixin: theme changes, v106 styling, speed display (206 lines)
```

### Pattern used
- Same mixin pattern as Phase 1
- `DownloadManagerWidget(_DMUISetupMixin, _DMQueueMixin, ..., QWidget)` in `widget.py`
- Relative imports adjusted: `..core.models` → `...core.models` (one extra level)
- Module-level theme helpers stay in `widget.py`

### Test results (all passing)
- Smoke tests: 24/24 ✅
- DM tests: 129/129 (27 scenarios) ✅
- Viewer pipeline tests: 19/19 ✅
- Connection tests: 1/1 ✅

---

## Phase 3: home_ui.py (P3) — 5,410 → 12 files ✅ COMPLETED

**Completed:** 2026-04-05

### Result
`HomePanelWidget` (5,410 lines) split into 10 mixin files + 1 core widget + 1 `__init__.py` inside `home_panel/`. The original `home_ui.py` is now a ~30-line backward-compatible shim.

### Actual folder structure
```
PacsClient/pacs/workstation_ui/home_ui/
├── home_ui.py                           ← SHIM (~30 lines): re-exports HomePanelWidget + helpers
├── home_panel/                          ← NEW PACKAGE
│   ├── __init__.py                      ← re-exports HomePanelWidget, SourceOfPatientLoad, get_home_widget
│   ├── README.md                        ← documentation (file map, MRO, rules, tests)
│   ├── widget.py                        ← HomePanelWidget core: __init__, signals, module-level helpers (209 lines)
│   ├── _hp_layout.py                    ← _HPLayoutMixin: left/center/right panels, theme, loading (803 lines)
│   ├── _hp_patient_open.py              ← _HPPatientOpenMixin: double-click, tab open, close/cleanup (495 lines)
│   ├── _hp_search.py                    ← _HPSearchMixin: local/server search, patient table delegates (497 lines)
│   ├── _hp_import.py                    ← _HPImportMixin: folder import, auto-import from startup (390 lines)
│   ├── _hp_download.py                  ← _HPDownloadMixin: download start, complete, fail, resume (614 lines)
│   ├── _hp_series.py                    ← _HPSeriesMixin: series info, thumbnails, right panel (424 lines)
│   ├── _hp_priority.py                  ← _HPPriorityMixin: thumbnail-click priority, single series (668 lines)
│   ├── _hp_modules.py                   ← _HPModulesMixin: DM, web browser, education, printing, etc. (575 lines)
│   ├── _hp_offline.py                   ← _HPOfflineMixin: offline cloud sync, export, import (451 lines)
│   └── _hp_study_save.py               ← _HPStudySaveMixin: save complete study info, series DB (321 lines)
├── home_db_service.py                   ← unchanged
├── home_tab_service.py                  ← unchanged
├── home_download_service.py             ← unchanged
├── home_search_service.py               ← unchanged
├── home_module_tabs.py                  ← unchanged
├── home_widget_utils.py                 ← unchanged
└── ... (other unchanged files)
```

### Pattern used
- Same mixin pattern as Phases 1-2
- `HomePanelWidget(_HPLayoutMixin, ..., _HPStudySaveMixin, QWidget)` in `widget.py`
- Relative imports adjusted: `from .xxx` → `from ..xxx` (sibling-level)
- Module-level names (`SourceOfPatientLoad`, lazy loaders) stay in `widget.py`
- Mixin files import shared names via `from .widget import SourceOfPatientLoad`

### Test results (all passing)
- Smoke tests: 24/24 ✅
- DM tests: 129/129 (27 scenarios) ✅
- Viewer pipeline tests: 19/19 ✅
- Connection tests: 1/1 ✅

---

## Phase 4: engine.py — ZetaBoost (P4) — 1,200 → ~5 files

### Proposed folder structure
```
modules/zeta_boost/
├── engine.py                            ← SHIM: imports + re-exports ZetaBoostEngine
├── cache_engine/                        ← NEW SUBFOLDER
│   ├── __init__.py                      ← re-exports ZetaBoostEngine
│   ├── README.md                        ← documentation
│   ├── boost_engine.py                  ← ZetaBoostEngine class (init, activate/deactivate, public API, ~300 lines)
│   ├── cache_store.py                   ← query, get, put, trim_keep, eviction, clear (~350 lines)
│   ├── lane_worker.py                   ← _worker_loop, _try_promote_disk_to_memory, _check_system_memory_ok (~300 lines)
│   ├── health_monitor.py               ← _maybe_log_health_locked, _failsafe_reset, _ensure_workers_locked (~200 lines)
│   └── global_state.py                  ← Module-level _GLOBAL_DOWNLOAD_ACTIVE, set_global_download_active (~50 lines)
```

### Critical rules to preserve
- DL_WARMUP subprocess runs at IDLE priority
- GC is suppressed during scroll bursts
- Global download state coordination across engines

### Verification
- Run: `python -m pytest tests/smoke/test_import_smoke.py -v`
- Manual: open patient, verify cache warmup, scroll performance

---

## Phase 5: _vc_progressive.py (P5) — 1,100 lines — DEFERRED

### Assessment
This file implements the critical 4-layer completion protocol. It's already a mixin extracted from the viewer controller. While large, it has very high internal cohesion — the layers are interdependent. **Recommend defer** unless a natural sub-boundary emerges during Phases 1-4.

If split is desired later:
```
_vc_progressive/
├── __init__.py
├── progressive_mixin.py       ← Main _VCProgressiveMixin (signal handlers, orchestration)
├── grow_engine.py             ← _grow_progressive_fast, _flush_progressive_grow, stale retry
├── completion_protocol.py     ← Layer 2-4: verify, sweep, one-shot recovery
```

---

## Phase 6: patient_widget_viewer_controller.py (P6) — 1,074 lines — DEFERRED

### Assessment
This is the hub file combining 7 mixins. At 1,074 lines it's borderline. Much of it is initialization and timer setup. **Recommend defer** — it's already well-structured with the mixin pattern.

---

## Documentation Strategy

### Per-subfolder README.md template
```markdown
# {Subfolder Name}

## Purpose
{One-paragraph description}

## Files
| File | Class/Functions | Responsibility |
|------|----------------|----------------|
| ... | ... | ... |

## Integration Points
- {How this connects to other parts of the system}
- {Key signals/slots/callbacks}

## Critical Rules
- {Rules from copilot-instructions.md that apply to this code}

## Related Tests
- {Test commands that exercise this code}
```

### Update copilot-instructions.md after each phase
- Update "Complete file map" section with new subfolder paths
- Update "Where does X happen?" function lookup table
- Add any new critical rules discovered during splitting

### Update docs/architecture/overview.md
- Update "Recommended next refactors" section
- Document completed splits

---

## Execution Order & Dependencies

```
Phase 1 (patient_widget.py) ──┐
Phase 2 (main_widget.py) ─────┤── Independent, can run in parallel
Phase 3 (home_ui.py) ─────────┘
     │
Phase 4 (engine.py) ── Independent
     │
Phase 5 (_vc_progressive.py) ── Depends on Phase 1 being stable
Phase 6 (viewer_controller.py) ── Depends on Phase 1 being stable
```

Phases 1-3 are independent and can proceed in parallel.
Phase 4 is independent.
Phases 5-6 are deferred and depend on Phase 1 stabilization.

---

## Risk Mitigation

1. **Import breakage**: Shim files re-export everything. Run smoke tests after each phase.
2. **Signal/slot breakage**: Qt signals must stay on the same class. Mixins share `self`.
3. **Circular imports**: Use lazy imports where needed (already a project pattern).
4. **IDE navigation**: `__init__.py` re-exports preserve autocomplete.
5. **Git blame history**: Use `git mv` where possible. Large splits will lose blame — document original source in README.md.
6. **Test coverage**: Run ALL relevant test suites before AND after each phase.

---

## Decisions

- Using mixin pattern (not delegation) for UI files — matches existing `_vc_*.py` precedent
- Subfolders (not flat files) — per user requirement for meaningful organization
- Shims at original location — zero import breakage
- Phases 5-6 deferred — high cohesion, already-reasonable size
- One PR per phase — independently reviewable and revertable

---

## Pre-Phase Cleanup (recommended)

Before starting any phase, consider:
1. **Delete deprecated methods** in `home_ui.py` (~400 lines of `NotImplementedError` stubs) — reduces file size before splitting
2. **Rename `zeta mpr/` → `zeta_mpr/`** — eliminates dynamic import workarounds (independent task)
