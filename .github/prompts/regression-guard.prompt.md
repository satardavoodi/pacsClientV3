---
mode: agent
description: Pre-edit safety check — confirm the subsystem invariants before changing viewer, thumbnail, DB, or download code.
---

# Regression-guard check (run before editing a guarded subsystem)

Identify which subsystem the change touches, read its as-built doc, and confirm you will
preserve every invariant. Summarize the invariants back before writing code.

- **Multi-study viewer** (sidebar, `_vc_load.py` / `_vc_switch.py`, `thumbnail_manager.py`,
  home right-panel): read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`. Single-study patients must
  run the original path unchanged; multi-study behaviour is gated on `len(_studies_series) > 1`.
- **Thumbnail pipeline** (any producer/consumer): read `docs/pipelines/thumbnail-pipeline.md`.
  Canonical disk path is `THUMBNAIL_PATH/<study_uid>/<series_number>.png`; never build from
  `BASE_PATH`; `make_pixmap_from_bytes` is Qt-main-thread only.
- **Database / tests** (`database/_pool.py`, `database/core.py`, DB tests): patch
  `PacsClient.utils.data_paths.DATABASE_FILE` + clear `database._pool._connection_pool`.
  Never write to the live `dicom.db`.
- **Zeta Download Manager** (`modules/download_manager/`, `_hp_study_save.py`,
  `_hp_patient_open.py`, socket clients): read
  `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`.
  Transport is **socket, not gRPC**; writes are atomic via `*.part` + `os.replace()`.
- **FAST stack-drag** (`modules/viewer/fast/qt_viewer_bridge.py`): read
  `docs/plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`. Keep the pressure
  sampler off by default; never call psutil synchronously on the main thread.
- **V2 design layer** (`PacsClient/utils/v2_style.py`, `ui_variant.py`, toolbar styling):
  read `docs/design/V2_DESIGN_SYSTEM_AS_BUILT.md`. Apply styles at the source function;
  tokens only.

Global hard rules (`CLAUDE.md`): FAST viewer mode must **never** instantiate VTK render
windows; never remove metadata, overlays, measurements, sync, reference lines, sidebars,
or clinical tools; prefer minimal, reversible edits.
