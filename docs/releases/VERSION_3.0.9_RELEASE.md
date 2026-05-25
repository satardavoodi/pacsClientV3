# AIPacs v3.0.9 Release Notes

**Release date:** 2026-05-25
**Branch:** beta-version
**Previous stable:** v3.0.8

---

## Summary

v3.0.9 is a workspace-sync rollup on top of v3.0.8. It consolidates the
accumulated subsystem fixes and architecture audits from the past week into a
new stable consolidation checkpoint, and publishes the result across all
mirrored remotes (`origin`, `p2`, `satar`).

This release is documentation- and stabilization-heavy: the major in-flight
fixes (multi-study viewer, thumbnail pipeline, DB test isolation, Zeta DM
review) have been merged into the canonical workspace with their as-built
records committed alongside.

---

## Version Alignment

The following canonical version markers are set to `3.0.9`:

- `pyproject.toml` -> `version = "3.0.9"`
- `main.py` -> `app.setApplicationVersion("3.0.9")`
- `docs/README.md` -> current stable `v3.0.9`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.0.9`
- `.github/copilot-instructions.md` -> current stable `v3.0.9`

LICENSE is unchanged (MIT).

---

## Included In This Release

### Multi-study viewer (single-tab grouped sidebar)
- All multi-study behavior gated on `len(self._studies_series) > 1`; single-study
  patients run the original path unchanged.
- `_server_series_info` keyed by offset keys
  (`study_slot * 1_000_000 + original_series_number`); primary study keeps
  original numbers.
- Disk reads resolve to `{SOURCE_PATH}/{study_uid}/{original_series_number}/`.
- Right-panel thumbnails cleared inside the deferred, repaint-suppressed
  rebuild (no pre-clear flicker).
- Main-page previews render with `progressive=False` to avoid two-study flicker.
- As-built record: `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`.

### Thumbnail pipeline canonicalization
- Canonical disk path: `THUMBNAIL_PATH/<study_uid>/<series_number>.png`.
- `THUMBNAIL_PATH` is an aliased re-export of `THUMBNAILS_DIR`
  (`USER_DATA_ROOT/patients/thumbnails`) — disk is the single source of truth.
- Consumers read via `ThumbnailImageSourceService` / `ThumbnailStore` with disk
  fallback; DB `series.thumbnail_path` column is a hint only.
- `make_pixmap_from_bytes` is Qt-main-thread only.
- As-built record: `docs/pipelines/thumbnail-pipeline.md`.

### Database test isolation + production cleanup
- Test redirection now patches `PacsClient.utils.data_paths.DATABASE_FILE`
  (the path the real pool actually reads) — not the inert
  `database.core._DB_PATH`.
- Pool clearing now targets `database._pool._connection_pool` under
  `database._pool._pool_lock`.
- Loud-fail guard in `_setup_temp_db()` validates `PRAGMA database_list` and
  raises if the path is not the temp DB.
- Production cleanup: removed 87 orphan `_commit_test_*` / `_nocommit_test_*` /
  `_test_rollback` tables and 946 synthetic `PID-` / `THREAD-` / `SRCH-`
  patients (with cascaded studies/series/instances) from the live `dicom.db`;
  ~363 real patients retained.
- Tooling: `tools/maintenance/cleanup_test_pollution.py` (dry-run by default,
  `--apply` to act, backs up to `backups/` first).
- Pre-cleanup backup: `backups/dicom_pre-cleanup_2026-05-24_192543.db`.
- As-built record: `COPILOT_REPORT_db_cleanup.md`.

### Zeta Download Manager review + fixes
- Confirmed transport is socket, not gRPC. `GrpcMetadataClient` is
  socket-backed; legacy `modules/network/` gRPC stack is dead and quarantined.
- Atomic DICOM/thumbnail writes: instances and thumbnails write to `*.part`
  then `os.replace()` to the final `.dcm` / `.png`; resume scan excludes
  `.part` and sub-128-byte files.
- `GetStudyInfo` probe reduced to a single fast attempt under
  `_GETSTUDYINFO_PROBE_LOCK` (eliminates ~6s patient-open stall).
- Download subprocess shares live `dicom.db` with retry on
  "database is locked" — keeps the downloader yielding to the main app.
- Dead code quarantined under `_recovery/phase1_deadcode_20260524/`;
  corrupt-file backups under `_recovery/corrupt_files_20260524/`.
- As-built record:
  `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`.

### Other bundled updates
- EchoMind viewer-chat updates (`llm_client.py`, `ai_chat_pages.py`,
  `ai_chat_widgets.py`), conservative image-flow coercion limits, viewer
  `ai_chat_interactorstyle.py` updates.
- AI imaging module: dataset/imaging/reception data service tab updates,
  report editor dialog, VTK/patient widget overrides.
- Home panel: download / layout / modules / patient_open / priority / search
  / series / study_save updates; home search service and patient table widget
  polish; right-panel widget; report status dialog.
- Workstation UI: AIPacs_ui, mainwindow_ui, server_settings, settings_ui.
- Plugin package mirrors resynced for canonical module changes
  (download_manager / EchoMind / viewer payloads).
- New configs and diagnostics tooling under `tools/diagnostics/` and
  `tools/maintenance/`.
- Runtime profile artifact refreshed.

### Documentation added in this release
- `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`
- `docs/pipelines/thumbnail-pipeline.md`
- `docs/analysis/CODE_QUALITY_AUDIT_2026-05-23.md`
- `docs/analysis/STRUCTURAL_AUDIT_2026-05-23.md`
- `docs/architecture/async-reception-enrichment-strategy.md`
- `docs/architecture/hybrid-communication-model-analysis.md`
- `docs/development/DOWNLOAD_TRIGGER_FLOW.md`
- `docs/pipelines/AI_CSV_TO_VTK_GEOMETRY_CONVERSION.md`
- `docs/plans/RESPONSIVE_UI_SCALING_PLAN.md`
- `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`
- `CLAUDE.md` (project-instructions companion to `.github/copilot-instructions.md`)
- `COPILOT_REPORT_db_cleanup.md` / `COPILOT_TASK_db_test_isolation_and_cleanup.md`

---

## Publication

- All pending workspace changes committed as the v3.0.9 consolidation checkpoint.
- Tag `v3.0.9` created for release traceability.
- Pushed to all three configured remotes:
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3
