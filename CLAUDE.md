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
(as-built record: `COPILOT_REPORT_db_cleanup.md`).

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
(`_show_grouped_patient_studies`), **read `CROSS_PATIENT_STUDY_MIXING_44504_2026-06-02.md`**
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
**read `MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`** and the
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
`main.py`, or the shutdown `finally`, **read `SINGLE_INSTANCE_GUARD_2026-06-02.md`** and the
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
See `AUDIT_THUMBNAIL_DOWNLOAD_PIPELINE_2026-06-01.md`. Clinical image integrity verified sound
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
- **Large-batch stability (2026-06-05,** see `STABILITY_FIXES_TAKEOVER_AND_LARGE_BATCH_2026-06-05.md`**):**
  the response-body recv loop accumulates into a **`bytearray`** (`extend`) — never revert to
  `bytes +=` (O(n²): minutes of CPU on a 300 MB radiology batch = the "stuck download"). A
  per-series **byte-budget soft cap** (`_BATCH_BYTES_SOFT_CAP`, 64 MB) halves subsequent
  batches AFTER the `batch_start` advance (alignment-safe) and must never write the global
  adaptive batch size. `XA`/`RF`/`DR` belong in `_SERIES_FORCE_BATCH_ONE_MODALITIES`. On
  "Response too large" (usually stream desync) `send_request` returns a structured error for
  `GetSeriesImages` only; `download_series` halves, then does 2 bounded same-size retries at
  min batch on a fresh socket. Guards: `tests/code/download_manager/test_large_batch_stability.py`
  + `test_response_too_large_u1.py`.


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
