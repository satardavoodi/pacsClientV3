# AI-PACS — Project Instructions

This file is picked up automatically by AI agents working in this repository
(`E:\ai-pacs\ai-pacs codes\ai-pacs beta version\`). Keep it accurate and integrate
new guidance cleanly rather than overwriting existing sections.

## AI-PACS runtime / testing workflow

When running or testing the AI-PACS DICOM workstation, **always use the SOURCE BUILD
launched from VS Code. Never use the installed frozen executable or a desktop shortcut.**

### Which build to run
- Source repository: `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\`
- Launch **only** via VS Code's Play / "Run Python File" button on `main.py`.
- Do **not** use `open_application`, the desktop AI-PACS icon, the black AI-PACS
  taskbar icon, or `d:\ai-pacs\aipacs\aipacs.exe`. The installed frozen build does
  **not** contain uncommitted source changes, so testing it does not test your fix.
- The **source build's taskbar icon is the Python icon**, not the black AI-PACS icon.
  Use the Python icon to identify the correct window.
- Run **only one** source instance. Press Play **once**, then wait — startup is slow.
  Do not press Run/Play repeatedly (it spawns extra instances and "AIPacs Already
  Running" dialogs). Watch the VS Code terminal as it loads.

### Startup sequence
1. Press Play on `main.py`; the integrated terminal starts loading.
2. Wait patiently — startup takes time.
3. The app window appears.
4. If a "disk full" popup appears, click **OK**.
5. At the login screen the credentials are pre-filled — just click **Sign In**
   (no typing required).
6. Wait again — post-login startup also takes time.

### Monitors
- The app usually opens on monitor 2, over VS Code. Move it to monitor 1 and keep
  VS Code on monitor 2 so both stay usable.

### Testing the patient / thumbnail workflow
1. Select the **MRI** modality.
2. Select **yesterday** or **two days ago** as the date.
3. Wait for the patient list to populate.
4. Single-click several different patients.
5. Observe whether thumbnails load automatically in the sidebar.

### Log verification
Check `user_data\logs\download_diagnostics.log` for the run:
- **Success:** `right_panel_socket_start` followed within ~1–3 s by
  `right_panel_socket_done thumbnail_count=N`.
- **Failure:** `right_panel_socket_error`, a ~45123 ms timeout, port `105` usage,
  or a missing thumbnail UI update.
- On failure: make **one** targeted follow-up fix from the log evidence, then retest once.

### Networking note (thumbnail socket port)
The thumbnail / patient sockets must use the socket-protocol port from
`config/socket_config.json` (e.g. `50052`), resolved via `get_socket_server_settings()`.
Do **not** use the `port` field from `config/servers.json` (e.g. `105`) — that is the
DICOM port. Feeding the DICOM port into the socket client makes thumbnail fetches
connect to the wrong port and hang until a ~45 s timeout.

## Human-assisted bootstrap mode (DEFAULT)

Human-assisted bootstrap mode is the **default** workflow for all AI-PACS sessions.

- **The human handles:** cleaning old processes, launching the source build,
  startup / login / popups, moving the app to monitor 1, and bringing the UI into
  the requested state.
- **The agent then:** continues testing from the already-open app — clicks
  studies / patients, observes UI behaviour, inspects logs, patches code, retests
  once, reports evidence.
- The agent must **not** spend cycles automating window management, startup
  bootstrap, monitor movement, login, or process recovery.
- If interaction with the running app becomes unreliable, the agent **stops and
  asks for a short, specific human action** — it does NOT do random relaunches and
  does NOT open the installed exe.

### Hard rules
- **Never** reopen the frozen installed executable (`d:\ai-pacs\aipacs\aipacs.exe`)
  under any circumstance.
- **Never** create multiple instances.
- **Never** click the black AI-PACS icon.
- The only correct running app is the **source-build `python.exe` instance**.

## Subsystem regression guards

### Multi-study viewer (patients with >1 study under one Patient ID)
Before editing the viewer thumbnail sidebar, the series-load path
(`_vc_load.py` / `_vc_switch.py`), `thumbnail_manager.py`, or the home-page
right-panel thumbnails, **read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` first** —
it is the as-built record and regression-guard for the multi-study fix
(implemented & verified 2026-05-24).

Key invariants that must not be broken:
- All multi-study behaviour is gated on `len(self._studies_series) > 1` (or
  `_is_multistudy_hint`). **Single-study patients must run the original path
  unchanged.**
- For a multi-study patient, `_server_series_info` is keyed by **offset keys**
  (`study_slot * 1_000_000 + original_series_number`); the primary study keeps
  its original numbers. Treat these keys as opaque — use each entry's
  `study_uid` / `_orig_series_number` / `series_path` for any server or disk
  access.
- Disk reads resolve to `{SOURCE_PATH}/{study_uid}/{original_series_number}/`,
  never the widget's single `study_uid`/`import_folder_path` for a non-primary
  series.
- Only `_render_multistudy_grouped` may populate the sidebar for a multi-study
  patient; the single-study early render stays gated off.
- Right-panel thumbnails must clear inside the deferred, repaint-suppressed
  rebuild — never clear before the deferred rebuild (that flickers).
- Multi-study main-page previews render with `progressive=False`
  (`_show_grouped_patient_studies`); progressive mode reintroduces the
  two-study flicker. The grouped viewer sidebar renders each study's series in
  numeric series-number order (`_rebuild_multistudy_series_index` sorts before
  building the offset-key groups).

### Thumbnail pipeline (cache / disk / store consistency)
Before editing any thumbnail producer or consumer, **read
`docs/pipelines/thumbnail-pipeline.md`** — the as-built audit record
(2026-05-24).

Key invariants that must not be broken:
- Canonical disk path is `THUMBNAIL_PATH/<study_uid>/<series_number>.png`.
  `THUMBNAIL_PATH` (config) is an aliased re-export of `THUMBNAILS_DIR`
  (`USER_DATA_ROOT/patients/thumbnails`) — disk is the single source of truth.
- **Never build a thumbnail path from `BASE_PATH`** (the code root);
  `BASE_PATH/thumbnails` is the empty legacy pre-migration location.
- Consumers read via `ThumbnailImageSourceService` / `ThumbnailStore`
  (memory-first) but must fall back to the canonical PNG file; the DB
  `series.thumbnail_path` column is a hint only — never the sole source.
- `make_pixmap_from_bytes` is Qt-main-thread only.

### Right-panel refresh / server-grew gate (44113 → 44323/44534, 2026-06-01→02)
The main-page right-panel thumbnails render via the **fast-cache-first gate in
`show_patient_studies` (`_hp_search.py` ~:1230)** — it shows the local PNG cache without
a server call unless the study is judged stale. Before editing that gate, the
`_server_series_count_by_study` stash (`_hp_search.py::_add_socket_patient_to_table`,
`_hp_series.py::_reconcile_patient_studies_on_click`), or the series-list gate in
`_load_and_display_series_info`, **read `docs/pipelines/thumbnail-pipeline.md` §8** and
the [[stale-series-44113-fix]] history.
- **`count_of_series` is the PATIENT series total, not a study's.** Only stash it
  against a study when `total_studies <= 1`. A multi-study patient still returns one
  (latest) UID, so `len(study_uids)==1` is NOT sufficient — without the `total_studies`
  guard the aggregate (44534: DX 3 + MRI 7 = 10) mis-attributes to one study and feeds a
  false "grew" signal (B1).
- **Keep the refresh marker keyed by the server count** — `_thumbs_server_refreshed_uids`
  holds `f"{uid}@{server_series}"`, not the bare UID. Same key (unchanged count) → fast
  cache + no loop on a benign count/thumbnail off-by-one; new count (genuine server
  growth) → exactly one re-fetch. Reverting to a UID-only marker pins stale thumbnails
  forever after the first refresh (B2).
- **Fast cache stays the default.** Fall through to `get_study_thumbnails(...)` only when
  the gate says the study grew; never make every click hit the network (the 44113
  responsiveness contract). Disk stays the read authority — the gate decides *whether to
  fetch*, not *where to read*.
- The *missing MRI study* on a multi-modality patient is study **discovery**, not this
  gate — see the multi-study completeness guard above ([[multistudy-multimodality-enumeration]]).
- Verify via `download_diagnostics.log`: `right_panel_cache_gate` should log `grew=1`
  once per server-count value, then `grew=0` + `right_panel_cache_hit`.
- **Render coalescing (anti-flicker, 2026-06-02):** a click triggers the right panel
  twice (fast open path + post series-info). `RightPanelWidget.display_thumbnails` now
  short-circuits when the requested set's visual signature (`_thumbnail_render_signature`
  = `(study_uid, series_number, file_path)` per thumb) equals what's already shown, so it
  does NOT `clear_content()`+rebuild the identical set (that was the flicker). Reset in
  `clear_content()`. Keep it idempotent; don't add volatile fields to the signature. See
  `docs/pipelines/thumbnail-pipeline.md` §8 "Render coalescing".

### Main-page patient click handling — single vs double (2026-06-02)
Before editing `patient_table_widget.py` click handlers (`_on_patient_clicked`,
`_on_patient_double_clicked`, `_emit_patient_selection*`, `_on_single_click_timeout`,
`_on_current_row_changed`) read the [[single-double-click-disambiguation]] memory.
- Single-click = load thumbnails; double-click = open the patient. The single-click
  selection emit (`patientClicked` + `thumbnailRequested`) is **debounced behind
  `QApplication.doubleClickInterval()`** via `click_timer` — it must NOT fire
  immediately. Qt delivers the first click of a double-click as a normal click, so an
  immediate emit starts thumbnail loading on every double-click and races/blocks the
  open (and can push the 2nd press past the interval → Qt sees two singles → "double-
  click won't open / must single-click first"). Do not restore an immediate emit.
- A double-click MUST cancel the pending single-click (`click_timer.stop()` +
  `_pending_selection_row=-1`) and open independently — the open resolves study UIDs from
  the table row, never from the single-click reconcile, so it must not depend on the
  single-click having run.
- The debounce interval must be **≥ `doubleClickInterval`** (floor 250 ms); a smaller
  value re-breaks slow double-clicks. Row highlight is Qt-native on press (stays instant);
  only the thumbnail load waits the window.

### Database test isolation (tests must never write to the live `dicom.db`)
Before editing `tests/database/test_database.py`, any other DB-touching test, or
the connection layer (`database/_pool.py`, `database/core.py`), know that the live
clinical database `user_data/database/dicom.db` had been polluted by ~43 runs of a
test whose isolation silently failed — **fixed & cleaned 2026-05-24**
(as-built record: `docs/reports/COPILOT_REPORT_db_cleanup.md`).

Root cause: the old `_setup_temp_db()` patched `database.core._DB_PATH`, an
attribute nothing reads. The connection factory
`database/_pool.py::_create_sqlite_connection()` resolves the path from
`PacsClient.utils.data_paths.DATABASE_FILE` via an **in-function import**, so every
run wrote into production. The leak: 87 orphan `_commit_test_*` / `_nocommit_test_*`
/ `_test_rollback` tables and 946 synthetic `PID-` / `THREAD-` / `SRCH-` patients
(plus cascaded studies/series/instances) — all removed; ~363 real patients remain.

Key invariants that must not be broken:
- To redirect the database in a test, patch **`PacsClient.utils.data_paths.DATABASE_FILE`**
  (save and restore the original). Patching `database.core._DB_PATH` does nothing.
- After patching the path, clear the real pool — `database._pool._connection_pool`
  (dict) under `database._pool._pool_lock` — so no pooled connection still points at
  production. `database.core._pool` is **not** the real pool.
- Keep the loud-fail guard in `_setup_temp_db()`: it opens a connection, checks
  `PRAGMA database_list`, and raises `RuntimeError` if the path is not the temp DB.
  A DB-touching test must never fall back to production silently.
- Cleanup tool: `tools/maintenance/cleanup_test_pollution.py` (dry-run by default,
  `--apply` to act, backs up to `backups/` first) removes the leaked test tables and
  synthetic patients. Pre-cleanup backup: `backups/dicom_pre-cleanup_2026-05-24_192543.db`.
- Known residual: `tests/offline_cloud_server` patches only its own module-level
  `DATABASE_FILE` copy — safe today (it uses raw `sqlite3.connect`), but would break
  isolation the same way if it ever calls the central pool.

### Zeta Download Manager (review + fixes, 2026-05-24)
Before editing `modules/download_manager/`, the download trigger
(`_hp_study_save.py` / `_hp_patient_open.py`), or the socket clients, **read
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`** —
it is the as-built review, fix plan, and progress record (§13 = applied vs
outstanding; §14 = download-start delay; §15 = the socket/gRPC path map).

Key invariants that must not be broken:
- **Transport is socket, not gRPC.** gRPC is retired. `GrpcMetadataClient`
  (`modules/download_manager/network/grpc_client.py`) is socket-backed despite the
  name. The real gRPC stack in `modules/network/` (`grpc_client.py`,
  `dicom_downloader*.py`, `multi.py`, `dicom_service_pb2*.py`) is dead — do not
  reconnect it.
- **Atomic DICOM/thumbnail writes.** Instances and thumbnails write to a `*.part`
  temp then `os.replace()` — never write straight to the final `.dcm` / `.png`.
  The resume scan (`_scan_existing_files`) excludes `.part` and sub-128-byte files.
- **GetStudyInfo probe.** The server does not answer `GetStudyInfo`. The probe in
  `get_series_info_from_server` must stay a single fast attempt under
  `_GETSTUDYINFO_PROBE_LOCK`; do not revert it to the 2-attempt `get_study_info()`
  (that re-introduces a ~6 s patient-open stall).
- **DB harmony.** The download subprocess shares the live `dicom.db`;
  `initialize_study` / `batch_insert_instances` retry on "database is locked" —
  keep that backoff so the downloader yields to the main app rather than starving
  it or hard-failing.
- Quarantined dead code is in `_recovery/phase1_deadcode_20260524/`; corrupt-file
  backups in `_recovery/corrupt_files_20260524/`. Do not re-import them.
- Deferred / outstanding: review-doc steps S2.3, S2.5, S3.2–S3.5, Phase 4, and the
  subprocess-spawn pre-warm — all test-gated. Run `tests/download_manager/` before
  resuming.

### CD burner + portable Lite Viewer (implemented 2026-06-06)
Before editing `modules/cd_burner/` (burn pipeline, viewer staging, `viewer_locator.py`,
`portable_viewer/`) or `settings_ui/lightviewer_settings.py`, **read
`docs/pipelines/cd-burner-portable-viewer.md`** — the as-built record.

Key invariants that must not be broken:
- **`portable_viewer/` is self-contained**: never import `PacsClient` or other
  `modules.*` from it (it compiles standalone via Nuitka and runs from read-only CD).
  PySide6/pydicom/numpy only; no VTK/MPR/AI. Keep the relative-or-plain import pattern.
- **Default-viewer resolution** (`viewer_locator`): env override → built
  `lightViewer_dist/AIPacsLiteViewer/AIPacsLiteViewer.exe` → legacy `lightViewer/*.exe`
  fallback. `viewer_mode` in `lightviewer_settings.json` is back-compat normalized
  (missing mode + configured path = custom). Don't reorder the chain.
- **Viewer staging**: `single_exe` mode copies ONLY the exe; bundle mode copies the tree
  excluding junk archives (`*.rar/*.7z` — the legacy folder holds a 75 MB rar). `*.zip`
  must NEVER be excluded: PyInstaller's runtime is `_internal\base_library.zip` and
  excluding it bricks the viewer on every PC (caught by the staging guard 2026-06-07).
  `.py` changes mirror to the `run_cd` payload
  (`tools/dev/sync_plugin_mirrors.py`, then `verify_plugin_mirrors.py`).
- **Lite viewer build** (`tools/build/build_lite_viewer.py`): PyInstaller onedir is the
  DEFAULT builder (~30 s; Nuitka kept via `--builder nuitka`). Each pylibjpeg plugin
  (`rle`/`openjpeg`/`libjpeg` import names) needs BOTH its import AND its dist metadata
  (`--hidden-import`+`--copy-metadata` / `--include-package`+`--include-distribution-metadata`)
  or compressed DICOM silently stops decoding. `aipacs_lite_viewer.py` must NEVER import
  `modules.cd_burner...` (freeze tools follow it statically → workstation chain in the bundle).
- **Professional burn options (2026-06-06 evening, §9 of the pipeline doc):**
  `BurnOptions` + `dicom_prepare.py` (anonymize/transcode) + `content_collectors.py`
  (reports/JPEG/attachments). Invariants: anonymize failure EXCLUDES the file (never
  leak), transcode failure FALLS BACK to previous form (never drop images), extras are
  auto-skipped when anonymize is ON, default `BurnOptions()` must stay byte-identical to
  the legacy pipeline, and verify burns with `eject_after=False` then compares + ejects.
- **Burn-image filesystem:** `cd_writer.filesystems_for_media()` must return 3
  (ISO9660+Joliet) for ALL media — ISO9660-only mangles names to 8.3 (`_INTER~1`) and
  bricks the bundled viewer on other PCs ("Failed to start embedded python interpreter",
  reproduced + fix-verified via mounted ISO 2026-06-06; pipeline doc §10).
- **Bundle completeness (2026-06-07, pipeline doc §11):** PyInstaller does NOT honor the
  entry script's runtime `sys.path.insert` — the build MUST keep `--paths` +
  `--hidden-import viewer_app/media_scan/render/viewer_meta`, the `CRITICAL_BUNDLE_FILES`
  assertion, and the frozen `--selftest` release gate (exit 0 required). The staging
  verification's `VIEWER/_internal` completeness check must stay. NEVER judge viewer
  health by "process stayed alive" — windowed PyInstaller errors keep the process up.
- Run `tests/code/cd_burner/` (offscreen) after any change — 51 green as of 2026-06-07.

### Online Consultation — Identity + Drive + Education submodule (implemented 2026-06-06)
Before editing `modules/Identity/`, `modules/cloud_consultation/`, or
`modules/education/online_consultation/`, **read
`docs/pipelines/online-consultation-education.md`** (as-built; design background in
`docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md`).

Key invariants that must not be broken:
- **The AI-PACS server login is untouched.** Identity links external accounts to the
  current `auth_user`; it never writes to it. Tokens live in the OS keychain/DPAPI
  (`secure_store`), never in the DB; consultation code never sees raw credentials —
  it gets a Drive client via `get_capability_client(CLOUD_STORAGE)`.
- **Triple gate (ADR-0003, 2026-06-10):** Education's "Online Consultation" tab + the
  poller are inert unless BOTH `config/identity/identity.json` AND
  `config/cloud_consultation/cloud_consultation.json` (or env equivalents) enable
  them AND `aipacs_runtime.is_module_enabled("consultation")` allows it — gate via
  `online_consultation_available()` (still the single gate; the registry check FAILS
  OPEN, and dev/source runs are unaffected because dev defaults enable all modules).
  Flag-off Education renders byte-identically (both flags are ON in this source
  build). Consultation is a purchasable module: `MODULE_CATALOG` ids `consultation`
  (optional, ships `modules/cloud_consultation`) and `identity` (basic/core, ships
  `modules/Identity`), with plugin package definitions + installer component — the
  registry parity test enforces all three stay aligned.
- **De-identification is default-ON in the compose path** (B3, 2026-06-10):
  `build_export_callable(..., deidentify=True)` runs
  `modules/cloud_consultation/consultation/deidentify.py` IN PLACE after staging and
  before envelope sealing. A file that cannot be de-identified is DELETED (an
  identified file never uploads); losing every image raises. Never disable it
  silently — consumer Gmail/Drive is not HIPAA-eligible. `deidentify.py` must NOT
  import `modules/cd_burner` (ships in the separate run_cd package). One-click
  ingest (B4) reuses `sync_offline_cloud_study_to_local` via `package_import.py` —
  no fork of the offline engine.
- **Internal statuses are frozen** (`pending|uploaded|downloaded|reviewed|answered|
  closed|conflict`, guarded by `sync/state_machine.py`); the clinical labels
  Pending/Sent/Received/Answered/Closed are display-only (`status_labels.py`) and
  must never be persisted. `close_consultation` keeps `assert_transition`.
- **Reuse, don't fork, the offline package engine** — staging goes through
  `export_studies_to_offline_cloud` (`build_export_callable` raises on `ok=False`);
  the envelope stays a sibling `consultation.json`; integrity is verified before any
  ingest. Drive I/O is HTTP for packages only — DICOM stays on the socket stack.
- **No UI-thread blocking** (connect/upload/download/respond in QThread workers;
  poller scans off-thread). The poller is an idempotent QApplication-level singleton
  (`notifications/autostart.py`) and must never raise into the title bar.
- **Per-physician Drive structure + quota gate (ADR-0005, 2026-06-10):** hub layout is
  `AI-PACS Consultations/<consultation_address>/<cid>/` + `physician.json` per
  physician (see pipeline doc §8). The client quota gate (`physician_store.check_quota`)
  **FAILS OPEN without physician.json** and blocks only on explicit excess; the
  workstation never writes quota values (approximate usage bump only — the Laravel
  backend is authoritative: `physician_storage`, `physician:quota`, `drive:sync-usage`).
  `find_assigned_consultations` must keep scanning BOTH layouts (legacy depth-1 and
  per-physician depth-2).
- **Hub-account mode (ADR-0004, 2026-06-10) is the v1 cross-machine transport:**
  all participating workstations connect the SAME hub Google account; routing is
  by `consultation_address` (env/flag-file, fallback = Google handle) — see
  `docs/pipelines/online-consultation-education.md` §7. Share + revocation are
  best-effort and must never block/fail the local clinical action (send in hub
  mode / close); `stage_response_attachments` must run BEFORE `record_response`
  (the re-seal must cover attachment files); keep `num_retries` on every Drive
  `execute()`/`next_chunk()` call.
- `modules/education/` is plugin-mirrored: after edits run
  `tools/dev/sync_plugin_mirrors.py` then `verify_plugin_mirrors.py`.
- Run `python -m pytest tests/code/cloud_consultation tests/code/identity
  tests/code/education_online_consultation
  tests/code/builder/test_plugin_package_registry.py -q -p no:debugging` after any
  change (128 green as of 2026-06-10).

### New module / new feature-flag checklist (release-parity guards — 2026-06-11)
The "works in source, missing in installed build" class is guarded by
`tests/code/builder/test_release_parity_guards.py` (repo level), `builder/release_gate.py`
(build time, wired into `build_release.py`; `--skip-release-gate` is emergencies-only), and
`tools/maintenance/install_doctor.py` (read-only field diagnosis). See
`docs/pipelines/online-consultation-education.md` §12–§13. When adding a module or a
feature-flag config file, complete ALL of:
1. `MODULE_CATALOG` entry in `aipacs_runtime.py`.
2. Plugin package definition under `builder/plugin package/definitions/<id>/`.
3. `AIPacs_Setup.iss`: component + `[Files]` line (optional tier) AND the id in BOTH
   JSON writers of `WriteInstallationProfile()` (`modules` + `module_packages`).
4. New config file: ship the template under `config/` (subdirs seed; `secrets/` and
   `.gitignore` never do) and add the family to `CONFIG_FAMILY_VERSIONS` — bump that
   version whenever the template later gains new keys.
5. Mirrored trees (`modules/education`, run_cd): `tools/dev/sync_plugin_mirrors.py`,
   then rebuild — a stale stage fails the gate's frozen-PYZ probe.
6. Run `python -m pytest tests/code/builder tests/code/runtime -q -p no:debugging` —
   the parity tests enforce steps 1–5 automatically.

### Viewer/Home "V2" design layer (DEFAULT — flipped 2026-05-31)
Before editing `PacsClient/utils/v2_style.py`, `PacsClient/utils/ui_variant.py`, the viewer
toolbar styling (`patient_tab/.../patient_toolbar/toolbar_manager.py`), or home-page widget
styling, **read `docs/design/V2_DESIGN_SYSTEM_AS_BUILT.md`** (authoritative as-built; the
`*_REVIEW.md` / `*_PLAN.md` files are background). The full theme + per-widget audit landed
in `docs/design/THEME_SYSTEM_REVIEW_2026-05-30.md`.

Key invariants that must not be broken:
- V2 is now the **default** workstation design. `get_ui_variant(module)` returns `"v2"` when
  no env var or config override is present. V1 is preserved as a **backup/legacy variant**
  reachable via env `AIPACS_UI_VARIANT=v1` or `<USER_DATA_ROOT>/config/ui_variant.json`
  containing `{"variant": "v1"}` (or any per-module override). Every `apply_*_v2()` wrapper
  still checks `home_is_v2()` / `viewer_is_v2()` and **no-ops back to V1** when the user
  pins V1, so the legacy path remains byte-identical to its pre-migration self.
- The build-default constant is `_BUILD_DEFAULT_VARIANT` in `PacsClient/utils/ui_variant.py`.
  To re-flip the default for a build (or for a single user via env var), change that one
  string — every call site reads from it.
- **Apply at the source, not after the fact.** Each `apply_*_v2()` is called from *inside* the
  widget's V1 source style function (e.g. `_apply_qtoolbutton_style`, `_apply_split_*_style`,
  `_apply_dropdown_button_style`, `PatientTableWidget._apply_theme`) so it survives the app's
  frequent re-styling. Calling it from an outer creation site regresses under re-style.
- Split-pair toolbar buttons draw their **own** box (split geometry) and share one hover via the
  `_SplitGroup` event filter setting `groupHover` on both halves. Status menus keep the semantic
  status **dot** colour; only chrome/text are quieted. Tokens only — no hard-coded hex except
  builder fallbacks.
- Run `tests/code/test_v2_style_scaffold.py` + `test_ui_variant_scaffold.py` after any change.

### FAST stack-drag pressure sampler (main-thread stall fix — 2026-05-30)
Before editing the FAST stack-drag path in `modules/viewer/fast/qt_viewer_bridge.py`, **read
`docs/plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`**.
- The drag-pressure sampler (`_FastDragPressureSampler.sample()`) runs synchronous
  psutil/system-stat calls and is **off by default**, gated by `_FAST_STACK_PRESSURE_ENABLED`
  (env `AIPACS_FAST_STACK_PRESSURE=1`). `_sample_drag_pressure()` early-returns the cached phase
  when disabled. **Keep that guard** — it removed 300–500 ms mid-drag UI stalls that made stacking
  choppy on high-slice-count series.
- **Never** call psutil (`virtual_memory`, `io_counters`, `cpu_times`, `disk_io_counters`)
  synchronously on the main thread in the stack-drag or wheel-scroll hot path.
- The sampler's `phase` is telemetry-only — it must never drive rendering, reference lines,
  geometry overlays, or WL/filters.

### Cross-patient study isolation (persist-layer guards — 2026-06-02)
Clinical data isolation is the **highest-severity** invariant: a patient must only ever
show / download studies that belong to that exact `patient_id`. Before editing
`_hp_patient_open.py` (`_resolve_patient_study_uids`, open STEP 3.5), `_hp_series.py`
(`_reconcile_patient_studies_on_click`), or `_hp_modules.py`
(`_show_grouped_patient_studies`), **read `docs/reports/CROSS_PATIENT_STUDY_MIXING_44504_2026-06-02.md`**
and the [[cross-patient-study-mixing]] history.
- The 2026-05-31 `_resolve_patient_study_uids` pid-scope guard is a SAFETY NET only and has
  a hole: it KEEPS studies whose owner is unknown in the local DB, so a *fresh* leaked study
  (another patient's, not yet downloaded) could be persisted under the wrong patient (e.g.
  44533's shoulder study `…152` under 44504, self-confirming once downloaded).
- **The authority for study ownership is the SERVER's study-info `patient_id`** (from
  `_get_or_fetch_series_info` / `GetStudyThumbnails`). The persist/display guards now skip a
  non-clicked study whose server `patient_id` ≠ the target patient: STEP 3.5 (download queue +
  viewer series map), the single-click reconcile (before `save_complete_study_info` +
  `add_downloads`), and the grouped thumbnails (DB-owner check). **Keep all three** — they log
  `*_cross_patient_skip`. Never attribute a study to a patient from the *caller/current*
  context; always verify against the study's own server/DICOM `patient_id`.
- Disk/thumbnail folders are keyed by `study_uid` (patient-blind), so a leaked UID can surface
  another patient's images — the guards, not the folder layout, enforce isolation.

### Multi-study completeness across modalities (per-modality enumeration — 2026-06-02)
The *complement* of the isolation guard above: a patient with several studies of their **own**
must show ALL of them. Before editing `_hp_patient_open.py`
(`_resolve_patient_study_uids_async`, `_enumerate_studies_for_row`, `_row_modalities`,
`_row_total_studies`, the double-click open), `_hp_series.py`
(`_reconcile_patient_studies_on_click` server-side enumeration), or
`_hp_search.py::_add_socket_patient_to_table` (the `_server_patient_meta_by_pid` stash),
**read `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`** and the
[[multistudy-multimodality-enumeration]] memory.
- **Server limitation:** `GetPatientList` returns only ONE study UID per patient (the latest)
  even when it reports `total_studies>1` + multiple `modalities`. It splits a patient's studies
  **by modality**, so a same-patient study of a non-latest modality (44534's MRI behind its
  latest DX) is otherwise invisible. The fix queries the patient list **once per modality** and
  unions the UIDs (`study_enumerated_by_modality` trace).
- **Keep it zero-cost for the common case.** Single-modality / single-study patients must do
  **zero** extra server queries and add **no** open latency — the decision reads the modality
  set from the list row / the `_server_patient_meta_by_pid` stash, NOT a fresh query. Don't
  reintroduce an unconditional per-open patient-list query.
- **Isolation is preserved, not weakened.** Every enumerated UID is fetched with the server's
  `patient_id` filter AND re-checked locally (`_row_for` matches `patient_id`); the cross-patient
  persist/display guards still run on top. Enumeration ADDS the patient's own studies; the guards
  REMOVE any foreign one. Never union a UID without confirming it is this `patient_id`'s.
- Same-modality multiple studies are NOT discoverable this way (the server returns only the
  latest even under a modality filter) — a separate, rarer server limitation; do not assume the
  enumeration closes it.

### Single-instance application guard + clean termination (2026-06-02, takeover 2026-06-05)
Before editing `PacsClient/utils/single_instance_lock.py`, the lock acquire/release in
`main.py`, or the shutdown `finally`, **read `docs/reports/SINGLE_INSTANCE_GUARD_2026-06-02.md`** and the
[[single-instance-guard]] memory.
- Primary mechanism is a Qt **`QLocalServer`/`QLocalSocket`** (atomic, OS-released on crash,
  cross-process ACTIVATE→raise-window IPC); the PID lock file is a diagnostic/fallback layer.
  Per-user, build-independent server name. Keep `try_acquire(show_dialog)` / `release()` /
  `set_activate_callback(cb)`.
- **TAKEOVER is the default (2026-06-05): new launch wins.** A new launch sends
  `AIPACS_SHUTDOWN` over the local socket (clean close), waits ~6 s, then force-kills
  remaining AIPacs process TREES via psutil (`_force_close_other_instances` — top-level
  candidates only; never self/ancestors/descendants; covers frozen exes, source runs, and
  orphaned workers/spares that re-exec a relative `main.py`). No dialog, no question. A
  failed `listen()` after takeover re-pings and DEFERS to a racing newer launch (no kill
  loops). Legacy raise-window behavior: `AIPACS_NO_TAKEOVER=1`; under pytest
  (`PYTEST_CURRENT_TEST`) takeover is ALWAYS off so tests can't kill the runner or a live
  session. Guard tests: `tests/code/test_single_instance_takeover.py`.
- In the ping path use a **graceful** `disconnectFromServer()` + `waitForDisconnected()` —
  **never `abort()`** (it discards the in-flight ACTIVATE/SHUTDOWN so the message is lost).
- Shutdown guarantees no lingering process: the run-loop `finally` calls
  `terminate_all_download_subprocesses()` (`_vw_globals.py`, also `atexit`) then a guarded
  `os._exit(0)` (escape hatch `AIPACS_NO_HARD_EXIT=1`). Keep cleanup (lock release, DB WAL
  checkpoint, log flush, subprocess kill) BEFORE the `os._exit`. The SHUTDOWN handler quits
  via the event loop (so that `finally` runs) with an 8 s hard-exit failsafe.

### Download-manager reliability + smoothness (2026-06-02)
See `docs/reports/AUDIT_THUMBNAIL_DOWNLOAD_PIPELINE_2026-06-01.md`. Clinical image integrity verified sound
(atomic `.part`→`os.replace`, resume rejects partials, DB-lock retry). Applied + test-verified:
- **DM-H4** `DownloadProcessWorker.ensure_subprocess_dead()` called from
  `WorkerPool._remove_worker` — `QThread.terminate()` bypasses `run()`'s `finally:_cleanup()`,
  which would orphan the child (sockets + `dicom.db` writes). Keep it.
- **DM-L7** `_DMWorkersMixin._bound_tasks()` caps `_tasks` (FIFO 400, never evicts the active
  study). **DM-H3** viewer-drag preempts a *different* study holding the single slot.
- **P2.3 drag/visibility-deferral** in `_dm_details.py` (`_refresh_table_order` gates
  `is_protected_drag_active()` / `not isVisible()` before `_try_inplace_table_update`; deferred
  callbacks re-arm at a 1500 ms backoff). Mirror any change to the plugin-package copy.
- KNOWN pre-existing latent circular import: `modules.download_manager.__init__` (coordinator /
  executor) reaches `home_panel.widget → zeta_adapter` mid-init, so some test files fail to
  *collect* when a home-panel suite is collected before `download_manager`. Order-only, **no
  production impact**; to verify home-panel changes, collect `tests/code/download_manager` first.
- **Large-batch stability (2026-06-05,** see `docs/reports/STABILITY_FIXES_TAKEOVER_AND_LARGE_BATCH_2026-06-05.md`**):**
  the response-body recv loop accumulates into a **`bytearray`** (`extend`) — never revert to
  `bytes +=` (O(n²): minutes of CPU on a 300 MB radiology batch = the "stuck download"). A
  per-series **byte-budget soft cap** (`_BATCH_BYTES_SOFT_CAP`, 64 MB) halves subsequent
  batches AFTER the `batch_start` advance (alignment-safe) and must never write the global
  adaptive batch size. `XA`/`RF`/`DR` belong in `_SERIES_FORCE_BATCH_ONE_MODALITIES`. On
  "Response too large" (usually stream desync) `send_request` returns a structured error for
  `GetSeriesImages` only; `download_series` halves, then does 2 bounded same-size retries at
  min batch on a fresh socket. Guards: `tests/code/download_manager/test_large_batch_stability.py`
  + `test_response_too_large_u1.py`.

### Patient attachment local-first persistence (2026-06-16)
Every generated patient attachment (voice `REC_*.wav`, viewport/MPR screenshots, AI
output, notes/reports) is saved to `ATTACHMENT_PATH/<study_uid>/`
(`ATTACHMENTS_DIR = user_data/patients/attachments`) **before** any server contact, and the
attachment UI panels (`attachments_dropdown.py`) read straight from that folder — so display
never depends on the server. **Local save must stay authoritative; server sync is a later,
retryable, NON-destructive step.** Before editing `PacsClient/pacs/patient_tab/utils/patient_sync_service.py`,
`modules/network/upload_download_attchments.py`, or `modules/network/attachment_pending_sync.py`,
know the invariants (regression test: `tests/code/network/test_attachment_local_first_persistence.py`):
- **Sync must NEVER delete the local attachment folder.** The old `_sync_worker` did
  `shutil.rmtree(ATTACHMENT_PATH/study_uid)` then re-downloaded — a partial-batch upload or a
  failed re-download then lost the not-yet-synced files permanently (the "attachment gone after
  sync" bug). It is replaced by `reconcile_attachments_from_server()` =
  `download_attachments_for_study(..., overwrite=False)` (pulls only server files missing
  locally; never overwrites or deletes). Do not reintroduce `rmtree` here — the guard test fails
  if `rmtree` reappears in that module.
- **`upload_attachments_for_study` only READS local files**; it must never delete on failure. A
  `client.connect()` failure (offline/server-down) marks every discovered file PendingSync and
  returns a structured `failed` summary instead of raising — the files stay on disk for the next
  sync. Failed/partial uploads keep their files in the pending manifest (`.pending_sync.json`).
- Statuses are derived from the manifest via `attachment_pending_sync.get_status()`
  (Synced / LocalOnly / PendingSync); disk is the source of truth for existence.
- `download_attachments_for_study` (default `overwrite=False`) is the bidirectional pull on both
  patient-open (`_hp_patient_open._start_attachment_download_in_background`) and post-sync; keep
  it non-destructive. These three files are NOT plugin-mirrored.

### Approved voice must survive patient/tab close — close never deletes it (2026-06-20)
Closing a patient (tab "X", patient close, or full app close) must **NEVER delete an approved /
saved voice** — once the green check is pressed it is a permanent local attachment. Only an
**explicit user delete** may remove it: the red-X on the active recording
(`cancel_recording_inline`), the voice dropdown/menu delete, or the voice popup delete button.
"Server sync state is irrelevant" — an unsynced/LocalOnly/PendingSync voice must persist across
close and app restart. Before editing
`PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py` (the soundbox
`VoiceWidget`), know the invariants (guard test:
`tests/code/system/test_voice_not_deleted_on_close.py` — source-pin, no PySide6/audio dependency):
- **Root cause it guards (46838 / 47183):** `__init__` captures
  `self._main_window = self.patient_widget.window()`, and the widget is built in
  `ToolbarManager.__init__` (`toolbar_manager.py`) DURING patient-tab construction — *before* the
  patient widget is reparented into the main window's tab area — so `.window()` returns the
  **patient widget itself**. The `eventFilter` then receives `QEvent.Close` when the patient TAB
  closes and used to call `self._on_delete_clicked()` UNCONDITIONALLY →
  `os.remove(self._file_path)`. Approve (`_on_save_clicked` → `_on_stop_internal`) writes the WAV
  but never clears `_file_path`, so the approved file was still pointed at and deleted on close.
- **The `eventFilter` Close branch must pass `user_initiated=False`** (`reason="window_close"`):
  it may stop the stream/timer/playback but must not delete. Do **not** restore a bare
  `self._on_delete_clicked()` in the Close branch.
- **`_on_delete_clicked(..., *, user_initiated=True, reason=...)` is the single delete choke
  point + protective guard.** When `not user_initiated` it KEEPS the saved file and its
  `_file_path` reference (logs `[VOICE-DELETE-GUARD]`); an explicit user delete logs
  `[VOICE-DELETE]` before `os.remove`. Every real user-delete caller (red-X / dropdown / delete
  button) keeps the default `user_initiated=True` — never pass `user_initiated=False` from a user
  action, and never add a new non-user caller that deletes a saved voice.
- Kill switch `AIPACS_VOICE_KEEP_ON_CLOSE=0` restores the legacy delete-on-close (emergencies
  only). `voice_tool_ui.py` is NOT plugin-mirrored. Complements the attachment local-first
  persistence guard above (local save authoritative; sync non-destructive).

### Unified patient-study-set pipeline + 46630 late-study back-fill (2026-06-17)
The recurring multi-study bug (a second/DOC study shows on single-click but is lost on
double-click open, returning only on reopen — patient 46630) is fixed by a shared
study-set authority plus an in-session open-tab back-fill. Before editing
`PacsClient/utils/patient_study_set.py`, the home-panel study-resolution/open/back-fill
paths (`_hp_patient_open.py`, `_hp_series.py`), or the viewer canonical series resolver
(`_vc_load.py::_resolve_canonical_series_identity`), **read
`docs/pipelines/unified-patient-study-pipeline.md`** (as-built; implemented + live-verified
on 46630 2026-06-17).

Key invariants that must not be broken:
- **`patient_study_set.py` is PURE** (stdlib only — no Qt/VTK/pydicom/numpy). It is the
  single shared authority (`merge_study_uids` / `diff_study_uids` / `resolve_study_uids` /
  `build_download_payload` / `PatientStudySetService`) and must stay unit-testable in
  isolation. The wiring guard `tests/code/ui_services/test_unified_pipeline_wiring.py`
  fails if the flags/functions/caller-routing are removed.
- **The pipeline TERMINATES at the metadata sink `set_server_series_info`**
  (`_pw_thumbnails.py:86`, merge-aware). It must NEVER reach pixel loading, IPP/IOP
  geometry, slice ordering, orientation, VTK/MPR — those are DOWNSTREAM and clinically
  protected. The back-fill's only viewer call is `set_server_series_info`.
- **Legacy = kill switch, not deletion.** Every behavior change is gated default-on with
  the legacy path preserved: `AIPACS_PSS_MERGE_RESOLVE` (resolver tail→`merge_study_uids`;
  `=0` restores the byte-identical legacy owner-guard tail — pinned by
  `tests/code/ui_services/test_resolve_patient_study_uids_scope.py`),
  `AIPACS_OPEN_TAB_STUDYSET_BACKFILL` (open-tab back-fill), `AIPACS_OPEN_TAB_LATE_DOWNLOAD`
  (open-intent missing-only late download), `AIPACS_PATIENT_STUDY_SET_SHADOW` (default OFF
  diagnostic). Flip a flag to revert; do not delete the legacy path.
- **The resolver study-source GATHER is unchanged** — only the owner-filter TAIL routes
  through the authority. Converting the gather is deferred (Qt-table path not unit-coverable;
  needs a live multi-study GUI pass).
- **Cross-patient isolation is centralized AND kept at the sinks.** `merge_study_uids`
  drops positively-foreign studies (keeps selected + unknown-owner); the back-fill, resync,
  and reconcile ALSO re-validate the server owner (`*_cross_patient_skip`). Keep both.
- **Open intent vs preview:** the back-fill/late-download run ONLY when a viewer tab is
  open for the patient; a single-click preview with no open tab must never download. The
  back-fill is fire-and-forget (`_schedule_ui_coro`) and must not block the grouped render.
- **No unnecessary duplicate path:** callers were consolidated onto the shared authority +
  the existing `set_server_series_info` sink; the only net-new path is the open-tab
  back-fill (gap-filling). Extend the shared authority — never fork a parallel
  resolver/payload/enqueue variant.
- Tests: `tests/code/ui_services/test_patient_study_set.py`,
  `test_open_tab_studyset_backfill.py`, `test_resolve_patient_study_uids_scope.py`,
  `test_unified_pipeline_wiring.py`. None of these source files are plugin-mirrored. The
  larger consolidation (full `PatientStudySetService.resolve()`, typed `DownloadPlan`,
  catalog, mode policy) is staged — do it before the prior-study / National-ID feature.

### Drag-drop first-image prime + view-intent coalescing (slow-link thrash — 2026-06-17)
On a very slow / frequently-dropping link, an impatient user re-drags series repeatedly and
the single download slot thrashes until nothing completes. Two reinforcing causes were
fixed (as-built + validation steps: `docs/reports/DRAGDROP_SLOW_INTERNET_PRIORITY_THRASH_2026-06-17.md`
§6; history [[dragdrop-slow-internet-thrash-2026-06-17]]). Before editing the
`download_series` batch loop in `modules/download_manager/network/socket_client.py` or the
viewer drop-intent path (`_vc_load.py` / `_vc_switch.py`), read that report.

- **First-image prime** (`socket_client.py`, **plugin-mirrored**): `_first_image_prime_size(...)`
  fetches the FIRST batch of a **fresh** series (`skipped_count == 0`, batch > 1, not a
  force-single modality) as **one image**, then restores the full adaptive size **after
  batch 0** (the advance uses the old size, so `batch_start` is exactly 1 — alignment with
  the server's batch_index mapping preserved). It must stay **skipped on resume**
  (`skipped_count > 0`) so the R19b leading-batch skip is untouched, and must restore the
  size after the first batch (don't ramp from 1 — that re-adds round-trips on fast LAN).
  Flag `AIPACS_FIRST_IMAGE_PRIME` (default on, `=0` = byte-identical legacy). Mirror any
  edit; guard `tests/code/download_manager/test_first_image_prime.py`.
- **Global view-intent coalescing** (`_vc_load.py` + `_vc_switch.py`, **NOT mirrored**): the
  drop's `_notify_dm_viewed_series` + the two `_trigger_download_if_needed` sites route
  through `_coalesce_dm_view_intent(...)` → a single **last-write-wins** target
  (`_merge_drag_view_intent`) dispatched by a (re)started single-shot QTimer
  (`AIPACS_DRAGDROP_DEBOUNCE`, default on; `_MS` default 350). Only the FINAL drop's intent
  fires, so alternating drops can't preempt/tear-down the one slot per drop. **The view
  switch is NOT debounced** — it runs immediately in `change_series_on_viewer`; only the DM
  priority/download intent waits. Keep the downstream per-`(study,series)` cooldowns (500 ms
  notify / 2 s retry) and the `:691` token guard (`_is_request_current`). Guard
  `tests/code/viewer/test_dragdrop_coalesce.py`.
- **Rich download notification** (`_vc_progressive.py` + `loading_spinner.py` (mirrored) +
  `loading_overlay.py`, NOT all mirrored): the waiting spinner shows series identity,
  "Downloading N of M · P%", a progress bar, speed/ETA/elapsed, and an inferred connection
  state ("Connecting…" → "Waiting for server…" → "Slow connection — still trying…") via
  `_update_download_spinner_text` (fed by `on_series_images_progress`) + `_begin_download_wait`
  + the self-stopping `_dl_watchdog_tick` staleness watchdog → `ViewportSpinner.set_loading_details`
  → the minimal `AiPacsLoadingOverlay` (identity line + `QProgressBar` + detail line). **The
  progress-impl call is wrapped in try/except** — a status update must NEVER abort the
  progressive-display/grow pipeline (tests drive that impl on partial stubs; production
  hardening). Connection state is INFERRED from progress staleness (no cross-layer signal) and
  must **NEVER assert the connection is slow** — the viewer cannot tell a slow link from a series
  queued behind another download or downloading under a different key (false "slow connection" on
  a 100 Mb/s LAN, patient 46970). `_connection_state_text` is neutral only ("Preparing images…" /
  "Still loading… (the series may be queued)"); a regression test forbids the phrase "slow
  connection". Real DM retry counts are a deferred future enhancement. `AIPACS_DOWNLOAD_PROGRESS_TEXT`
  (+ `AIPACS_DL_SLOW_AFTER_S` / `AIPACS_DL_STALLED_AFTER_S` / `AIPACS_DL_WATCHDOG_INTERVAL_MS`).
  Guard `tests/code/viewer/test_download_progress_text.py`.
- **Multi-study progressive binding by series_uid** (`home_download_service.py` +
  `_vc_progressive.py`, NOT mirrored — patient 46970, 2026-06-17): a secondary-study series is
  awaited under a DISPLAY KEY (offset key 1000302) but the DM reports progress under the bare
  resolved number (302), so it never bound → empty viewport until a manual re-drag. Series numbers
  COLLIDE across a patient's studies, so number-only matching is unsafe. The bridge
  `on_series_progress` re-keys progress to the awaiting display key, matched on the globally-unique
  `series_uid` via `display_key_awaiting_series_uid(series_uid)`, so the existing progressive
  machinery binds + grows + loads from the correct per-study folder. Single-study unaffected
  (display key == number). No Qt signal-signature change (the 3-arg `series_images_progress` + the
  3-arg `diagnostic_hooks/hooks.py` wrapper stay intact). Flag `AIPACS_PROGRESSIVE_UID_BIND`
  (default on). Guard `tests/code/viewer/test_progressive_uid_bind.py`.
- **Viewport loading-state lifecycle** (`_vc_switch.py` + `_vc_progressive.py`, NOT mirrored —
  patient 46970, 2026-06-17): `_arm_spinner_timeout` used to hide the spinner UNCONDITIONALLY after
  20 s → blanked the viewport while a slow/queued/second-study series was still downloading (re-drag
  recovered it). Now it is **persistent**: the pure `_spinner_timeout_action(awaiting, waited_ms,
  hard_fail_ms)` returns `wait`/`error`/`hide`; while the viewport is still `_awaiting_series_number`
  the loading state STAYS (re-checks, never blanks) and hides only when no longer awaiting
  (loaded/cleared/replaced). A per-viewer `_loading_timeout_gen` generation counter prevents timer
  pile-up and gives clean replacement; the opt-in hard cap (`AIPACS_VIEWPORT_LOADING_HARD_FAIL_MS`,
  default 0=keep-visible) shows `_enter_viewport_load_error` ("Still loading — check the Download
  Manager") instead of a blank viewport. Auto-load when ready needs no re-drag (relies on the
  series_uid re-key above). Structured logging via `_log_viewport_lifecycle` (ViewportLoadRequested /
  RemoteSeriesDownloadAttached / ViewportLoadWaitingForDownload / ViewportLoadingStateCleared /
  ViewportLoadSucceeded / ViewportLoadFailed / ViewportLoadCancelledByReplacement + viewer id +
  canonical study/series uid). Flags `AIPACS_VIEWPORT_LOADING_PERSIST` (default on) /
  `AIPACS_VIEWPORT_LIFECYCLE_LOG`. A true download-FAILURE error (vs the timeout hint) still needs a
  real DM failure signal (future). Guard `tests/code/viewer/test_viewport_loading_lifecycle.py`.
- **Disk-readiness resume for unbridged (secondary-study) downloads** (`_vc_progressive.py`,
  NOT mirrored — patient 46713, Study 2, DOC series 100000, 2026-06-18): the home-download
  progress bridge (`home_download_service.on_series_progress`) filters by `study_uid`, so a
  NON-opened study's download progress/completion never reaches `on_series_images_progress` —
  a dropped secondary-study series would download fully yet spin forever (no progress → no
  uid-bind → no load). The watchdog now also runs `_maybe_resume_awaiting_from_disk`: while a
  viewport is awaiting, it resolves the series' OWN per-study folder
  (`_resolve_canonical_series_identity` → `SOURCE_PATH/<study_uid>/<orig_series>`), and once the
  files are complete (`_disk_ready_complete`: server expected-count met, else on-disk count
  stable across two ticks) resumes the load ONCE via the proven `change_series_on_viewer(display_key)`
  path (= an automated re-drag). Guard `_disk_ready_resume_done` (reset per awaiting episode at
  the `:716` awaiting-set site). Watchdog gate is now `(_DOWNLOAD_PROGRESS_TEXT or
  _LOADING_DISK_READY_RESUME)` so the resume works even if progress-text is off. Flag
  `AIPACS_VIEWPORT_DISK_READY_RESUME` (default on). Deeper follow-up (not done): bridge the
  secondary study's progress so it binds progressively DURING download, not only on completion.
  Guard `tests/code/viewer/test_viewport_loading_lifecycle.py`.
- **Clinical guardrail:** download/priority/perception only. No VTK/MPR geometry, slice
  order, orientation, or render change. No data-loss risk (atomic `.part` + resume). All
  three pieces are flag-gated default-on with the legacy path preserved as a kill switch.
  Drag-drop is now folded into the unified pipeline plan as a view-intent (see
  `docs/pipelines/unified-patient-study-pipeline.md` §8). Staged next (need live validation):
  settle-then-switch cross-study preemption (batch-boundary yield not kill), and converging
  the drop onto the shared `PatientStudySetService` / typed `DownloadPlan`.

### Previous Exams — cross-PatientID prior studies (National ID, 2026-06-20)
A patient may be the SAME real person as other patients imaged before under
DIFFERENT Patient IDs; the server links them by National ID / RIS reception. A
"Previous Exam" button in the Series Thumbnails header (gray→red when prior exams
exist) lists them; selecting one merges it into the open viewer for comparison.
Before editing `PacsClient/utils/previous_exams.py`, the `_PWPreviousExamsMixin`
(`patient_widget_core/_pw_previous_exams.py`), or the `sanctioned_uids` path in
`patient_study_set.py`, **read `docs/pipelines/previous-exams.md`** (as-built).
- **Clinical isolation is preserved.** A previous exam enters the current
  patient's grouped viewer ONLY via the `sanctioned_uids` allow-list passed to
  `merge_study_uids` — populated solely from server-verified previous-exam
  identity AND the explicit user click. NEVER auto-populate it from caller/current
  context. The four automatic cross-patient guards (open / reconcile / resync /
  back-fill) are UNCHANGED and still drop foreign studies.
- **Each exam keeps its OWN `study_uid` + `patient_id`.** DM payload carries the
  exam's own patient_id; disk stays `SOURCE_PATH/<study_uid>/...` (patient-blind).
  Never re-attribute a previous exam to the current Patient ID / DB owner.
- **Metadata-first; no auto-download on open.** Open fetches only the list
  (`GetPatientReceptionHistory` + `GetPatientStatus`). Select loads series
  metadata + thumbnails. Images download only on drag/open of a series
  (`add_downloads(start_immediately=False)` → PENDING; `request_critical_series_download`
  promotes the dragged series). Reuses the multi-study offset-key sink
  `set_server_series_info` + `build_download_payload` — no parallel workflow.
- Reset `_multistudy_thumbs_rendered` before each merge (run-once render guard).
- `previous_exams.py` stays pure stdlib. Flag `AIPACS_PREVIOUS_EXAMS` (default on,
  `=0` = byte-identical legacy). Tests: `tests/code/ui_services/test_previous_exams*.py`.
  None of these files are plugin-mirrored. NEEDS live GUI verification.

### Drag loads EXACTLY that series — multi-study disk resolution (2026-06-21)
A dragged series must load from ITS OWN study, never from a sibling/previous-exam study.
On a multi-study tab (current patient + merged Previous Exams under different Patient IDs /
Study UIDs) the viewer resolved the right series identity but loaded pixels from the
tab-level `study_path` (`import_folder_path`), which a prior previous-exam load had
"poisoned" to that previous study; since the previous study often has a same-numbered
series, the old `study_path/<key>` folder-exists check kept it → current drag showed the
previous series (44030 + 43373/47214, live-verified + fixed). Before editing the series
resolution in `_vc_load.py::_load_single_series_on_demand`,
`resolve_entry_study_location`, `_resolve_plain_series_study_path`, or
`_vc_cache._cache_entry_study_matches`, **read
`docs/reports/DRAG_LOADS_EXACT_SERIES_2026-06-21.md`**.
- **Resolve disk location from the series' OWN `_server_series_info` entry**
  (`series_path = SOURCE_PATH/<study_uid>/<orig_no>` + `_orig_series_number`), set for
  EVERY slot incl. primary by `_rebuild_multistudy_series_index`. The pure
  `resolve_entry_study_location(entry, tab_study_path)` is the authority and the gate
  calls it for **every** key. Do **NOT** re-gate it on `_study_slot > 0` (that regresses
  current/primary keys — the original bug). Keep it pure stdlib (unit-testable).
- The gate requires BOTH `series_path` AND `_orig_series_number`; only the multi-study
  rebuild sets the latter, so **single-study tabs stay byte-identical**.
- Keep all three layers: entry authority → stable-slot/plain-key fallback → cache
  study-match guard (`[CACHE-STUDY-MISMATCH]`). Each defends a different failure mode.
- Production diagnostic (INFO, app.log): `[MULTI-STUDY LOAD] key=… -> study_path=…
  (entry-authority slot=N)` — `study_path` must match the key's study. Deep cross-check
  `[VIEWPORT-LOAD-TRACE]` is opt-in (`AIPACS_VIEWPORT_LOAD_TRACE=1`); for every drop its
  `study_path` must equal `resolved_study`. Lesson: when a fix "isn't working", verify the
  log CHANNEL first — viewer logs route to `viewer_diagnostics.log` (which had stalled),
  not `app.log`. Guard: `tests/code/viewer/test_drag_loads_exact_series.py`. Not mirrored.


## VS Code Agent Mode environment (configured 2026-06-02)

The VS Code workspace is tuned so both **Copilot Agent Mode** (in VS Code) and
**Claude Desktop** work from the same project knowledge. `CLAUDE.md` (this file) is the
shared brief; `.github/copilot-instructions.md` is the in-editor instruction file Copilot
auto-loads (`github.copilot.chat.codeGeneration.useInstructionFiles` is on).

**Reusable agent prompts** (`.github/prompts/`, invoke with `/<name>` in Copilot Chat):
- `/root-cause-fix` — the understand → inspect logs → root cause → minimal fix → retest loop.
- `/debug-thumbnails` — patient/thumbnail sidebar socket-download debugging.
- `/inspect-logs` — where the `user_data/logs/` files are and what to scan for.
- `/run-tests` — the blessed `run_test.ps1` path + direct pytest, and the `-p no:debugging` rule.
- `/regression-guard` — pre-edit invariant check for the guarded subsystems above.

**VS Code tasks** (Terminal → Run Task): `AIPacs: Run App (logged)`, `AIPacs: Run Tests
(run_test.ps1)`, `Pytest: Collect only`, `Pytest: Run tests/code`, `Lint: Ruff check`,
`Logs: Tail download_diagnostics.log`, `Logs: Tail app.log`.

**Debug configs** (`launch.json`): Run AIPacs (.venv / no-terminal / legacy V1 UI),
Debug Current File, Debug Tests (pytest).

**Performance:** `settings.json` excludes the heavy trees (`user_data`, `backups`, `.venv*`,
`.claude/worktrees`, `generated-files`, `builder*`) from search, file-watcher, and Pylance
indexing — so logs/clinical data are reached by opening files or the `Logs:` tasks, not by
workspace search.

**MCP servers** (`.vscode/mcp.json`, Copilot Agent Mode): `filesystem` and
`sequential-thinking` (npx — one-time online warm-up). An optional read-only SQLite server
over a **copy** of `dicom.db` is documented but disabled (never point MCP at the live DB).

**Recommended extension to add:** `charliermarsh.ruff` (ruff is configured in
`pyproject.toml` but the extension isn't installed yet).

Original `.vscode/*.json` files are backed up at `.vscode/_backup_2026-06-02/`.

## Agent control & testing abilities (2026-06-21)

The single capability overview for an agent that needs to **control and test** the app is
`docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md` — it maps every ability (desktop
control + tiers, the offscreen sandbox test lane, logs, file tools) to how it's used here, and
cross-links the runbook and `.github/prompts/`. There are **two testing lanes**:

- **Verify lane (fast, agent-autonomous) — offscreen pytest in the Linux sandbox.** Recreate the
  env with `bash tools/dev/sandbox_setup.sh`, then `source tools/dev/sandbox_env.sh` (sets the
  vendored `libEGL`/PortAudio `LD_LIBRARY_PATH` + `QT_QPA_PLATFORM=offscreen`), then
  `python3 -m pytest tests/code/<target> -p no:debugging -q`. Installs every `requirements.txt`
  package (all import except Windows-only `comtypes`); ~1955 tests collect; pure-Python **and**
  Qt-offscreen suites run. Sandbox installs **do not persist** — re-run the setup each session.
  As-built: `tools/dev/SANDBOX_TESTING.md`.
- **Clinical lane (real) — the Windows source build.** The only lane that proves GUI / rendering
  / clinical behaviour. **Human-assisted bootstrap stays the default** (human launches the source
  build + logs in + positions on Monitor 1; the agent tests from the open app). Procedure:
  `docs/AIPACS_LAUNCH_CONTROL_RUNBOOK.md`. Source build only — never the frozen exe, never the
  black taskbar icon, never multiple instances.

The Verify lane is a pre-filter for the Clinical lane, not a substitute. It does NOT run the real
GUI, VTK render windows, or anything Windows-only.
