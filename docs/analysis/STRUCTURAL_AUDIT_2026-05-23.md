# AI-PACS Structural Audit — 2026-05-23

> **Scope:** Conservative, read-only structural review of the `beta-version` branch.
> **Goal:** Identify structural issues affecting stability and reliability. No bug
> fixes were applied — those are to be assigned individually after this review.
> **Method:** Five parallel read-only subsystem audits (download, viewer, modules,
> database, UI/UX), each cross-checked against `docs/architecture/*` and the
> diagnostic logs under `user_data/logs/`.

This is an analysis/time-bound note (per `docs/architecture/repository-layout.md`,
analysis notes belong under `docs/analysis/`).

---

## Executive Summary

The project is **structurally healthier than its own documentation suggests**. The
big consolidations the docs only partially describe — the `modules/` tree, the
9-module `database/` split, the `HomePanelWidget`/`PatientWidget` mixin splits, the
explicit FAST/ADVANCED viewer leak guard — are real and in good shape.

There are **no Critical findings**. The most important safety rule —
*the FAST viewer must never build a VTK render window* — **holds**: no FAST render
path constructs a `vtkRenderWindow`.

The genuine problems cluster in three buckets:

1. **A few real reliability bugs** that accumulate over the repeated download/view
   cycle (socket FD leak path, unbounded state dict, a connection-pool exception
   gap). These are small and isolated — good candidates for the one-by-one fix queue.
2. **Repo hygiene** — 8 full repo copies under `.claude/worktrees/`, stale temp
   files in the root, and no `.gitattributes`. This is what makes `git status` and
   project-wide searches noisy and misleading.
3. **Documentation drift** — `README.md` and `docs/architecture/overview.md` point
   to module/viewer paths that no longer exist.

The working tree looked alarming (2,071 modified files) but is almost entirely
benign — see Section 1.

---

## 1. Git Working-Tree State — investigated first, as requested

**Finding: the 2,071-file diff is ~98% line-ending noise, not real work.**

| Measurement | Result |
|---|---|
| `git diff --shortstat` (raw) | 2,045 files, 976,112 insertions, 972,368 deletions |
| `git diff --ignore-cr-at-eol --shortstat` | **36 files**, 5,064 insertions, 1,320 deletions |
| `core.autocrlf` | unset |
| `.gitattributes` | does not exist |

Insertions ≈ deletions across ~2,000 files is the signature of a CRLF↔LF flip: git
sees every line as removed and re-added. Ignoring carriage returns, only **36 files
have real content changes**.

**Root cause:** no `.gitattributes` + unset `core.autocrlf`. A tool or editor
re-wrote line endings across the tree. It will recur on every machine/tool with a
different EOL setting.

**The 36 files with genuine uncommitted changes** are concentrated in the actively
developed areas — substantial in-progress work, *not* noise:

- Home panel / search: `_hp_search.py` (+974 lines of churn), `patient_table_widget.py`
  (~1,263), `_hp_series.py` (+525), `_hp_patient_open.py` (~315), `_hp_study_save.py`,
  `_hp_download.py`, `_hp_modules.py`, `home_search_service.py`, `right_panel_widget.py`
- Network/download: `modules/network/socket_client.py`, two `grpc_client.py` copies
- Viewer: `ai_module_ui/overrides/vtk_widget.py` (~422), interactor styles
- Settings: `server_settings.py`
- Tests: `test_thumbnail_fetch_async.py`

**Recommendation (needs your decision — git history is yours to own):**

- Add a `.gitattributes` (e.g. `* text=auto` and `*.py text eol=lf` or `eol=crlf`
  to match your standard) so endings stop drifting. Adding the file alone changes
  nothing until you renormalize.
- The ~2,000 line-ending-only files should be reverted or renormalized in one
  dedicated commit, separate from the 36 real-change files, so the real work stays
  reviewable. This is a git operation you should drive; I can prepare the exact
  commands on request.
- The 36 real-change files are an in-progress body of work — decide whether to
  commit or stash them before any further cleanup so changes remain isolated.

---

## 2. Download System

**Summary:** Structurally sound. Exactly one live download-manager tree at
`modules/download_manager/`, organized into the documented subpackages. Port
resolution is **correct** — every socket call resolves the socket-protocol port
(50052) via `get_socket_server_settings()`; the DICOM port (105) does not leak into
the download path anywhere. Worker/subprocess cleanup is the strongest part of the
system. The issues are repeated-cycle resource hygiene and a server-side timeout.

| # | Severity | Finding | Evidence | Conservative recommendation |
|---|---|---|---|---|
| D-1 | High | Thumbnail/right-panel socket fails ~38% of the time (30 errors vs 48 successes), clustered at ~25 s and ~120 s — server-side timeouts on `GetStudyThumbnails`/`GetStudyInfo`. Client behaves correctly. | `download_diagnostics.log` ~line 26385+; `host=192.168.2.222` | Not a client code fix — server latency or probe-timeout policy. Hand to the networking owner; do not change retry constants blindly. |
| D-2 | Medium | Thumbnail fetch fans out many concurrent socket threads for one patient open; each timed-out attempt holds a socket for its full timeout, amplifying D-1. | same log, multiple `tid=` per endpoint | Investigate capping/serializing concurrent `GetStudyThumbnails` probes per patient. Measure before changing. |
| D-3 | Medium | `download_all_series` socket is not wrapped in `try/finally`; an unexpected exception in the series loop exits without `disconnect()`, leaking the FD until GC. Degrades over many cycles. | `modules/download_manager/download/series_downloader.py:195` | Wrap the loop body in `try/ finally: socket_client.disconnect()`. Small, isolated, reversible. |
| D-4 | Medium | `DownloadStateStore._states` dict grows unbounded — entries removed only by explicit `remove()`/`clear_completed()`. Memory creep over a long session of many downloads. | `modules/download_manager/state/state_store.py:50` | Confirm the DM widget calls `clear_completed()` periodically; if not, add one call. Do not auto-evict inside the store. |
| D-5 | Low | `GrpcMetadataClient.self.port` defaults to gRPC 50051. Not a bug today (socket traffic overrides it), but a latent footgun if a future edit wires `self.port` into a socket client. | `modules/download_manager/network/grpc_client.py:46` | Add a one-line comment marking `self.port` as legacy/unused for socket traffic. |

---

## 3. Viewer & Decoding System

**Summary:** The FAST (pydicom + OpenCV) and ADVANCED (VTK + SimpleITK) pipelines
are functionally separated, with an explicit runtime guard
(`_emit_fast_advanced_geometry_leak_guard`) and a `QtFastContainer` that null-stubs
VTK objects. **The FAST-path-no-VTK-render-window rule holds.** The remaining issue
is import-graph entanglement: the VTK *library* still gets imported into the FAST
process even though no render window is created.

| # | Severity | Finding | Evidence | Conservative recommendation |
|---|---|---|---|---|
| V-1 | High | FAST container transitively imports the VTK library and the advanced `ImageViewer2D` via the `_vw_globals` chain — module-scope `import vtkmodules.all`, `QVTKRenderWindowInteractor`. No render window is built, so it is not a render leak, but it breaks strict import isolation. | `PacsClient/.../vtk_widget/_vw_globals.py:8,12,18`; `qt_fast_container.py:28`; `_pw_viewers.py:14` | Narrow `qt_fast_container.py`'s import so it pulls the few constants it needs from a small VTK-free module instead of `_vw_globals`. Low risk. |
| V-2 | Medium | `modules/viewer/fast/pydicom_lazy_volume.py` imports `vtkmodules.all` at module scope. It is used only as a data container and is *not* imported by the core FAST render path — effectively a misfiled module sitting in the `fast/` package. | `modules/viewer/fast/pydicom_lazy_volume.py:15-16` | Relocate to `advanced/` or a `shared/` package in a later cleanup so `fast/` stays VTK-free by inspection. No behavior change. |
| V-3 | Low/Info | The geometry-contract leak guard is firing (`warn_only`): something upstream keeps offering the advanced `instances_order_contract` to the FAST `open_series`. The guard correctly blocks it — separation is working. | `viewer_diagnostics.log` `[FAST_ADVANCED_GEOMETRY_LEAK_BLOCKED]` | Trace the caller passing `instances_order_contract` into FAST `open_series`; stop passing it. Keep the guard. |
| V-4 | Medium | Oversized viewer files concentrate complexity and regression risk: `advanced/viewer_2d.py` 4,765 lines; `fast/lightweight_2d_pipeline.py` 3,784; `qt_viewer_bridge.py` 3,536. | file line counts | No refactor now. Flag for incremental extraction only when a file is next touched for another reason. |
| V-5 | Low | `qt_viewer_bridge.py` has 6 `.connect()` vs 1 `.disconnect()`; a new bridge is built per series open. Safe *if* the previous bridge is fully dereferenced on series switch. | `qt_viewer_bridge.py` | Confirm the old `QtViewerBridge` is dropped / `deleteLater()`'d on series switch. |

Decode logic is otherwise cleanly partitioned — FAST decode contains no VTK/SimpleITK;
advanced code imports `pydicom` only lazily inside functions.

Note: recurring `MAIN_THREAD_STALL_TRACE` events (worst 8–9 s) originate in
`secretary_button_widget.paintEvent` (home UI) — not a viewer defect, but see UI section.

---

## 4. Project Modules

**Summary:** The actual layout is healthier than the docs describe — MPR, printing,
EchoMind, viewer, and supporting subsystems are consolidated under one `modules/`
tree, and the legacy `zeta mpr/` space-in-name problem is already fixed
(`modules/mpr/zeta_mpr/`). The notable issue is a dead module-loader and heavy
documentation drift.

| # | Severity | Finding | Evidence | Conservative recommendation |
|---|---|---|---|---|
| M-1 | High | The documented "module system" loader is **dead code** — referenced only inside `.claude/worktrees/*` copies, never in live `PacsClient/` or `main.py`. Modules are actually loaded by direct import + `bootstrap_installer_selected_module_packages()`. The loader also opens a *second* SQLite `ConnectionPool`, conflicting with the single-pool rule. | `modules/module_system/module_manager.py` (`ModuleManager` 262-578, `ConnectionPool` 118-184); live loader at `main.py:85,187` | Do not delete. Add a header comment marking it not-currently-wired, and correct the docs to describe the real direct-import loading. |
| M-2 | Medium | Documentation paths are systematically stale — docs place modules at top-level (`EchoMind/`, `printing/`, `zeta mpr/`, `orthogonal_mpr/`); none exist. Live paths: `modules/EchoMind/`, `modules/printing/`, `modules/mpr/zeta_mpr/`, `modules/mpr/orthogonal/`. | `docs/architecture/overview.md`, `repository-layout.md`, `docs/modules/README.md` | One verified doc-refresh pass to the real `modules/` paths. No code change. |
| M-3 | Medium | Stale forked file `standard_mpr_viewer_original.py` (3,600+ lines) sits next to the live `standard_mpr_viewer.py` inside a stability-critical module. | `modules/mpr/zeta_mpr/standard_mpr_viewer_original.py` | Confirm it is unused, then move it to `backups/` or `docs/archive/` — out of the package tree. |
| M-4 | Medium | `PacsClient/utils/__init__.py` re-exports 60+ symbols from utils/database/db_manager/config — a broad coupling hub creating import-order fragility (a documented risk). | `PacsClient/utils/__init__.py` | Do not refactor now. For new code, import the specific submodule directly rather than widening the hub. |
| M-5 | Low | Modules present in code but absent from the catalog: `cd_burner/`, `offline_cloud_server/`, `data_analysis/`, `storage/`, `zeta_sync/`, `zeta_boost/`, `mpr/curved_mpr/`. | `modules/` listing vs `docs/modules/README.md` | Add catalog rows. Doc-only. |

EchoMind is **not** duplicated — only `modules/EchoMind/` exists. Minor: `ai_chat_config.py`
and `api_manager.py` appear both at the package root and under `viewer_chat/` — worth a
later check that the root copies are not stale.

---

## 5. Database Layer

**Summary:** Good structural health, better than the (stale) spec. The `database/`
package is a real, clean 9-module split, with `core.py` reduced to a 134-line
re-export shim. Connection/commit discipline is strong: no production code uses bare
`get_connection_database()`, no `PRAGMA read_uncommitted`, every inspected
INSERT/UPDATE/DELETE commits inside its `with` block, and all user values use `?`
binding (no SQL injection). One real recurring pool bug stands out.

| # | Severity | Finding | Evidence | Conservative recommendation |
|---|---|---|---|---|
| DB-1 | High | Pool reuse-validation only catches `sqlite3.OperationalError`. A pooled connection closed during shutdown raises `sqlite3.ProgrammingError` ("Cannot operate on a closed database"), which escapes and fails the whole operation. ~89 recurring warnings in the log. | `database/_pool.py:181-194`; `db_diagnostics.log` lines 12048, 25522+ | Widen the `except` to `(sqlite3.OperationalError, sqlite3.ProgrammingError)` so a stale/closed pooled connection is transparently discarded and recreated. Two-line fix. |
| DB-2 | High | `cleanup_connection_pools()` closes **every thread's** connections, not just the calling thread's. A worker thread still running after `closeEvent` then finds its connection closed — the upstream cause of DB-1. | `database/_pool.py:342-353`, called from `mainwindow_ui.py:1126` | Keep the global close at shutdown, but pair it with the DB-1 fix so surviving threads recover gracefully. Avoid thread-targeted cleanup logic (higher risk). |
| DB-3 | Medium | `init_database()` is called from `DatabaseManager.__init__`, violating the "only once, from `MainWindowWidget`" rule. Idempotent, so an annoyance not a crash — extra DDL/migration churn. | `modules/download_manager/storage/database_manager.py:67` | Drop the call, or guard it with a module-level "already initialized" flag. |
| DB-4 | Medium | A stray `conn.close()` runs *after* the `with get_db_connection()` block exits, closing a connection already returned to the pool — can close a connection another thread later receives. | `database/dicom_db.py:1099` (`bulk_update_instances`) | Delete the `conn.close()` line; the context manager already returns the connection. |
| DB-5 | Low | `docs/architecture/database-architecture.md` describes a 6-module split with `core.py` ~3,300 lines; reality is 9 modules with `core.py` a 134-line shim. | the doc vs `database/` | Refresh the "Database Files" table when convenient. Doc-only. |

DB-1 and DB-2 share one root cause; the DB-1 two-line `except` widening plus
deleting the DB-4 line resolves the only observed runtime DB instability.

---

## 6. UI / UX Structure

**Summary:** Better than the docs imply. The `HomePanelWidget`/`PatientWidget` "god
files" are already split into mixin packages (`home_panel/`, `patient_widget_core/`).
The most safety-critical repeated-use path — Download-Manager signal wiring — is
well-engineered: `HomeDownloadService` uses idempotent connections with per-widget
`_ConnectionRecord` bookkeeping and deterministic `disconnect_widget`/`cleanup`. The
patient-open flow has duplicate-open guards, tab reuse, and thorough teardown. **No
stale/mixed-patient-data leak was found** in the traced flows.

| # | Severity | Finding | Evidence | Conservative recommendation |
|---|---|---|---|---|
| UI-1 | High | Stale tab-index binding: `close_requested.connect(partial(self.close_patient_tab, tab_index))` binds a fixed index at tab creation. `update_tab_indices()` re-wires only the title-bar branch, not the `setTabButton` fallback — so after a tab closes, the fallback close button can target the wrong tab. Latent today (app uses the title-bar path) but a real correctness bug. | `custom_tab_manager.py:526`; re-wire loop 858-914 | Extend the re-wire loop to the non-titlebar case, or have `close_patient_tab` resolve the index from the widget at call time. |
| UI-2 | Medium | `patient_table_widget.py` is 4,560 lines in a single class concentrating table rendering, search delegates, dialogs, CD-burn, print, delete, export, status threading. No leak (`setRowCount(0)` disposes cell widgets), but a maintenance/review hotspot on a hot path. | `patient_table_widget.py` (class at line 560) | No refactor under the freeze. Flag for the existing mixin-split pattern as future work. |
| UI-3 | Medium | `QApplication.processEvents()` is called inside `search_local` right after `clear_table()`. It re-enters the event loop and can dispatch a queued click while the table is mid-clear — re-entrant search risk. | `home_search_service.py:170` | Remove the lone `processEvents()`; the surrounding code already does `await asyncio.sleep(0)`, which yields safely. |
| UI-4 | Low | Per-row `lambda`/`partial` signal connections are created on every search, but `setRowCount(0)` destroys the widgets (and connections) before each repopulate — no accumulation. | `patient_table_widget.py:2458-2459` | None — keep the `setRowCount(0)`-before-populate discipline intact. |
| UI-5 | Low | Patient-open spawns short-lived daemon threads with their own asyncio loops; closed in `finally`, duplicate-guarded — no cross-cycle leak. | `_hp_patient_open.py:237-241, 802` | None required; optionally route through the shared `thread_pool` if rapid-repeat issues appear. |

---

## 7. Cross-Cutting Structural Issues

| # | Severity | Issue | Detail |
|---|---|---|---|
| X-1 | High (hygiene) | **8 full repo copies** under `.claude/worktrees/` (`angry-matsumoto-78c431`, `cool-easley-66342b`, …). `.claude/` is **not** git-ignored. These dominate project-wide `grep`/`find`, inflate diffs, and were the source of the "duplicated download_manager / module_loader" confusion. | Add `.claude/` to `.gitignore`; prune stale worktrees with `git worktree prune` / `git worktree remove`. |
| X-2 | Medium | **Root-level temp clutter**: `.tmp_diff_open.patch`, `.tmp_diff_series.patch`, `.tmp_diff_socket.patch`, `.tmp_diff_studysave.patch` (all 0 bytes), `.tmp_diff__hp_patient_open.py.patch`, `.tmp_diff__hp_series.py.patch`, `.tmp_diff__hp_study_save.py.patch`, `.tmp_diff_socket_client.py.patch`, plus `_recovery/` and `.tmp_backup_extract/` directories — all untracked, none git-ignored. | Review and delete the temp `.patch` files and `.tmp_backup_extract/`; keep `_recovery/`/`backups/` only if intentionally retained, and git-ignore them. (Deletion is yours to perform — see Section 8.) |
| X-3 | Medium | **No `.gitattributes` + unset `core.autocrlf`** → the 2,071-file line-ending churn (Section 1). Recurs on every tool/machine with a different EOL setting. | Add a `.gitattributes`; renormalize in one dedicated commit. |
| X-4 | Medium | **Documentation drift.** `docs/architecture/overview.md` (v2.3.3) and the README "Module Map" point to module/viewer paths that no longer exist; network/database docs are more current but still slightly behind. Multiple docs disagree with each other. | One verified doc-refresh pass across `overview.md`, `repository-layout.md`, `docs/modules/README.md`, and the README "Module Map". |
| X-5 | Low | The `builder/plugin package/.../payload/python/modules/download_manager/` bundles a **copy** of `download_manager` that is tracked by git and drifts independently of the live tree. | Confirm this is generated/packaged output and git-ignore it, so it stops appearing in diffs alongside the live tree. |

---

## 8. Conservative Cleanup — Status

Per the agreed scope (audit + *conservative* code cleanup; bug fixes assigned
individually afterward):

**Applied this pass (zero runtime risk, fully verified, isolated):**

- `README.md` "Module Map" — corrected the two viewer paths to the real
  `modules/viewer/fast/lightweight_2d_pipeline.py` and
  `modules/viewer/advanced/viewer_2d.py` (the old `PacsClient/pacs/patient_tab/viewers/`
  directory does not exist).

**Recommended but NOT applied — needs your decision (git history / file deletion):**

- Add `.gitattributes` + renormalize the line endings in one dedicated commit (X-3, Section 1).
- Add `.claude/` (and `builder/.../payload/`) to `.gitignore` (X-1, X-5).
- Delete the root temp `.patch` files and `.tmp_backup_extract/` (X-2). *Deletion is
  intentionally left to you* — file deletion on a clinical project should be a human
  action; I will not delete files unilaterally.
- A full verified documentation-refresh pass (X-4, M-2, M-5, DB-5, V-7) — best done
  as its own task so paths are individually confirmed, not guessed.

**Queued as candidate one-by-one fix tasks (real behavior changes — your call on order):**

- DB-1 + DB-2: connection-pool closed-connection handling (one root cause).
- DB-3: stray `init_database()` call. DB-4: stray `conn.close()`.
- D-3: `series_downloader.py` socket `try/finally`. D-4: `DownloadStateStore` growth.
- UI-1: stale tab-index binding. UI-3: `processEvents()` re-entrancy.
- V-1: VTK import isolation for the FAST container.

---

## 9. Prioritized Findings

| Rank | ID | Severity | Area | One-line |
|---|---|---|---|---|
| 1 | DB-1/DB-2 | High | Database | Pooled connection closed under running threads → recurring failures |
| 2 | D-1/D-2 | High | Download | ~38% thumbnail-socket failure (server-side timeout + fan-out) |
| 3 | UI-1 | High | UI | Stale tab-index binding can close the wrong tab (latent) |
| 4 | M-1 | High | Modules | Documented module loader is dead code; opens a second DB pool |
| 5 | V-1 | High | Viewer | VTK library imported into the FAST path (no render window — isolation only) |
| 6 | D-3 | Medium | Download | Socket FD leak path on unexpected exception |
| 7 | D-4 | Medium | Download | `DownloadStateStore` grows unbounded over a session |
| 8 | DB-3/DB-4 | Medium | Database | Stray `init_database()` / stray `conn.close()` |
| 9 | UI-3 | Medium | UI | `processEvents()` re-entrancy during table clear |
| 10 | V-2/V-4 | Medium | Viewer | Misfiled VTK module; oversized viewer files |
| 11 | M-3/M-4 | Medium | Modules | Stale forked MPR file; broad `utils` re-export hub |
| 12 | X-1…X-5 | High–Low | Repo | Worktree copies, temp clutter, no `.gitattributes`, doc drift |

---

## 10. Remaining Risks & Notes

- **No Critical findings.** The FAST-viewer-no-VTK-render-window rule holds.
- The audit was **static** (code + logs). Behavior under live repeated cycles was
  not exercised; D-1/D-2 (server timeouts) and DB-1/DB-2 are confirmed by logs.
- The biggest practical drag on engineering is **repo hygiene** (Section 7), not the
  code itself. Cleaning `.claude/worktrees/`, the temp files, and line endings will
  make every future diff, search, and audit dramatically clearer — recommended first.
- No source behavior was changed by this audit beyond the single README doc line fix.
- Nothing here removes or disables clinical functionality, metadata, overlays,
  measurements, sync, or viewer behavior.
