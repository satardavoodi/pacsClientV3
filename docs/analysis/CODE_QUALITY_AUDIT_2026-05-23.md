# AI-PACS Code-Quality Audit — 2026-05-23

> **Type:** Read-only code-quality, duplication, optimization & reliability audit.
> **Scope:** Function-level quality, duplication/forked logic, hot-path performance,
> reliability/lifecycle, and architecture standardness across the live codebase.
> **No code was changed.** Every item is a candidate for a later, individually
> approved fix task. Companion to `docs/analysis/STRUCTURAL_AUDIT_2026-05-23.md`.
> **Method:** Four parallel deep code reads (home/patient workflow, download &
> network, viewer & decoding, database/tabs/lifecycle), synthesized here.

---

## 1. Overall Code-Health Judgment

The codebase is **semi-stable and visibly being hardened** — generation counters
guard stale renders, download-manager signal wiring is idempotent and torn down
correctly, the DB connection pool is thread-local with disciplined commits, and the
FAST viewer has correct multi-tier caching and cancellation. The structure is sound;
**no architectural rewrite is warranted.**

What it carries is the debt typical of a fast-moving clinical app: a few
**god-functions and god-classes** (4,000–4,800-line UI/viewer files; 300–490-line
hot-path functions), **genuine forked duplication** (DICOM decode logic implemented
three times and already diverged; a reception-payload fetcher duplicated and
diverged; a fully dead duplicate `viewer/backends/` package), **inconsistent
diagnostics** (`print()` with mojibake alongside structured logging; ~119
silent `except: pass` sites), and **a small set of concrete bugs** that bite the
repeated open/download/close cycle.

The good news: almost everything worth fixing is **small, local, and reversible**.
There is one Critical item, a short list of High items, and a clear top-5 of safe
high-impact fixes. The deep refactors (decode consolidation, god-class splitting)
are real but should wait and be done incrementally with tests.

---

## 2. Architecture Standardness Assessment

| Dimension | Verdict | Notes |
|---|---|---|
| PySide6 UI separation | **Mixed** | Thin-controller + mixin split adopted (`home_panel/`, `patient_widget_core/`), but god-classes remain (`patient_table_widget.py` 4,560 lines; `viewer_2d.py` 4,765). Some functions still mix UI + network + DB. |
| Async / background work | **Adequate** | Thread pools + daemon threads keep heavy work off the Qt thread; but some ad-hoc `threading.Thread` use, and lock discipline is not uniform (see DL-1). |
| Database access | **Good** | Clean 9-module split, context-manager + commit discipline, `?`-binding throughout. Weak spots: thread-ident pool keying, monolithic `init_database()`, CRUD split arbitrarily across `manager.py`/`dicom_db.py`. |
| Network client design | **Adequate** | Deliberate dual-client split (bulk-DICOM vs patient/metadata) is sound. But retry/backoff and socket-cleanup logic are copy-pasted; the coordinator carries two retry engines. |
| Config management | **Weak** | `servers.json` and config JSON are loaded ad hoc in 20+ files with duplicated dev-fallback logic; no single cached loader. |
| Logging / diagnostics | **Inconsistent** | Strong structured logging in newer code (`download_diagnostics`), but `print()` + mojibake in `viewer_2d.py`, ~119 `except: pass`, and permanent `[MG_DIAG]` cruft in a hot path. |
| Module boundaries | **Good** | Post-consolidation `modules/` tree is clean. Main smell: the `PacsClient/utils` broad re-export hub; one dead `viewer/backends/` package. |
| FAST vs ADVANCED viewer separation | **Holds, with leaks** | No FAST render path builds a VTK render window. But the VTK *library* is imported into the FAST path, and decode logic is triple-implemented across the boundary. |
| Socket vs REST ownership | **Good** | Imaging over socket, reception/workflow over REST — respected in code. |

---

## 3. Prioritized Findings Table

| ID | Sev | Area | Location | Summary |
|----|-----|------|----------|---------|
| DL-1 | **Critical** | Download | `download_manager/state/state_store.py:519` | `clear_completed()` fires observers while holding the state lock → Qt-thread UI work runs under the download lock |
| VW-1 | High | Viewer | `decode_service.py:144`, `lightweight_2d_pipeline.py:2218`, `pydicom_2d_backend.py` | DICOM decode (rescale / MONOCHROME1 / W-L) implemented 3× and **already diverged** — slices can render differently by cache path |
| DL-2 | High | Download | `download_manager/download/series_downloader.py:116` | `download_all_series` socket has no `try/finally` → FD leak on any unexpected exception |
| DB-1 | High | UI/Tabs | `custom_tab_manager.py:612,790,858` | Two divergent tab-index code paths; can close the wrong patient tab / stale `study_uid_to_tab` |
| DB-2 | High | UI/Tabs | `custom_tab_manager.py:790` | `close_patient_tab` never destroys the patient widget → timers/tasks/VTK leak if closed via any non-X path |
| DB-3 | High | Database | `database/_pool.py:160-234` | Pool keyed by reusable `thread().ident`; reuse-validation only catches `OperationalError` (closed conns raise `ProgrammingError`) |
| HP-1 | High | Home/Patient | `patient_table_widget.py:2816`, `_hp_search.py:196` | `_fetch_reception_patient_payload` duplicated and **behavior-diverged** (timeout, logging, extractor keys) |
| DL-3 | Medium | Download | `network/socket_client.py:993` | `SocketDicomClient.download_series` — 389-line function, 5 responsibilities, 5-level nesting |
| DL-4 | Medium | Download | `network/socket_client.py:758+` | Socket-cleanup block copy-pasted ~6× — divergence risk |
| DL-5 | Medium | Download | `coordinator/series_intent_coordinator.py:406` | Two complete retry engines (legacy + V2) live behind an env flag |
| DL-6 | Medium | Download | `network/connection_pool.py:57` | `ConnectionPool` eagerly allocates 4 clients on construction; no live caller |
| DL-7 | Medium | Download | `network/grpc_client.py:154` | `fetch_study_metadata_sync` has a fall-through branch returning `None` implicitly |
| DL-8 | Medium | Download | `network/socket_patient_service.py:105` | `is_connected()` returns `True` unconditionally in pooled mode |
| DL-9 | Medium | Download | `network/socket_client.py:1219` | Per-instance `file_path.exists()` syscall in the download loop despite a prebuilt skip-set |
| HP-2 | Medium | Home/Patient | `_hp_patient_open.py:363` | `_on_patient_double_clicked_async` — ~489-line hot-path function, mixes everything |
| HP-3 | Medium | Home/Patient | `home_ui/**` | ~119 `except: pass` silent-failure sites; worst in the patient-open path |
| HP-4 | Medium | Home/Patient | `patient_table_widget.py:3617` | `update_reporting_physician_for_patient` linear-scans the table per hydration callback (O(rows²)) |
| HP-5 | Medium | Home/Patient | `patient_table_widget.py:2552`, `_hp_search.py:278` | `_report_status_cache` / `_reporting_physician_cache` never pruned → unbounded growth per session |
| VW-2 | Medium | Viewer | `modules/viewer/backends/` | Dead duplicate package — stale, divergent copies of `pydicom_2d_backend.py` / `pydicom_lazy_volume.py`, zero live importers |
| VW-3 | Medium | Viewer | `lightweight_2d_pipeline.py:3139` | `_decode_into_cache` (~156 lines) wraps everything in `try/except: pass`; failures look like successful prefetch |
| VW-4 | Medium | Viewer | `advanced/viewer_2d.py` | 43 `print()` calls (mojibake-corrupted) instead of `logger`; `reset_image_viewer` ~310 lines |
| VW-5 | Medium | Viewer | `advanced/viewer_2d.py:4250` | `cleanup()` has all VTK `Delete()` calls commented out → possible VTK leak across patient switches |
| DB-4 | Medium | Database | `database/manager.py`, `dicom_db.py` | CRUD split arbitrarily between the two; near-identical read helpers in both |
| DB-5 | Medium | Database | `database/manager.py:151,208,300` | Query helpers do a second PK lookup (extra pool acquire + query) when the first SELECT already had the row |
| DB-6 | Medium | Database | `database/dicom_db.py:47-351` | `init_database()` — ~300 lines, runs 17 ALTER-migrations every startup, swallows all migration errors |
| DB-7 | Medium | Database | `database/_pool.py:342` | `cleanup_connection_pools()` closes every thread's connections, not just the caller's |
| DL-10 | Medium | Download | `network/socket_client.py:631` | `_send_request_once` — 264-line method, manual lock acquire/release, 3-deep nesting |
| VW-6 | Low | Viewer | `qt_viewer_bridge.py:2026` | `_log_drag_metrics_summary` ~334 lines of pure telemetry formatting |
| VW-7 | Low | Viewer | `lightweight_2d_pipeline.py:1988` | Permanent `[MG_DIAG]` scan block in a hot render path |
| DB-8 | Low | Database | `database/dicom_db.py:1099` | Stray `conn.close()` after the `with` block closes a pooled connection |
| DB-9 | Low | Database | `database/manager.py:227,242,801,848` | DB read helpers `except Exception: return None/[]/{}` with no logging |
| DB-10 | Low | Lifecycle | `components/lifecycle_manager.py:106` | `shutdown_all()` ignores its own `timeout`; a hung callback blocks app close |
| DB-11 | Low | Config | `PacsClient/utils/utils.py` + 20 files | `servers.json` / config loaded ad hoc, dev-fallback duplicated everywhere |
| HP-6 | Low | Home/Patient | `_hp_patient_open.py:582` | Series info fetched twice (fallback) on patient open |
| HP-7 | Low | Home/Patient | `right_panel_widget.py:439` | `ThumbnailManager` reconstructed per immediate render |

**Non-findings (do not chase):** the "duplicated socket/gRPC clients" are a
*deliberate* split — `SocketDicomClient`/`PatientListSocketClient` (bulk DICOM) and
`GrpcMetadataClient`/`DicomGrpcClient` (patient/metadata) serve distinct roles, both
live; **do not consolidate them.** The FAST viewer's `close_series`/`shutdown`/
signal-disconnect lifecycle was checked and is **sound** — no leak there.

---

## 4. Detailed Findings

Each: *why it matters · evidence · repeated-use risk · minimal safe recommendation · timing.*

### CRITICAL

**DL-1 — `clear_completed()` runs observers under the state lock**
*Why:* `state_store.py` deliberately fires observers *outside* `self._lock` (see the
comment near line 223) to avoid Qt-thread callbacks running under the
download-thread lock. `clear_completed()` (519-534) holds the lock and calls
`remove()`, which calls `_notify_observers()` while still locked — defeating that
design. *Evidence:* `state/state_store.py:519-534`. *Repeated-use risk:* High — UI
observers stalling the download thread on every cleanup; also blocks the safe fix
for unbounded `_states` growth (HP/DL state). *Recommendation:* snapshot the
completed UIDs inside the `with` block, then loop `remove()` after it exits. ~4
lines. *Timing:* **fix now.**

### HIGH

**VW-1 — DICOM decode logic implemented three times and diverged**
*Why:* the rescale-slope/intercept + MONOCHROME1-inversion + RGB-fallback ladder is
re-implemented in `_decode_worker` (subprocess), `_decode_slice` (in-process), and
`pydicom_2d_backend._window_level_to_uint8`. `_decode_slice` has gained VOILUT
handling and storage-bounds MONOCHROME1 inversion that `_decode_worker` lacks — so
the *same slice* can render with different window/level or inversion depending on
whether it came from the subprocess or in-process path. *Evidence:*
`decode_service.py:144`, `lightweight_2d_pipeline.py:2218-2391`,
`pydicom_2d_backend.py`. *Repeated-use risk:* Medium-High — display inconsistency is
a clinical concern. *Recommendation:* extract one shared pure
`apply_rescale(arr, slope, intercept, photometric, …)` used by all paths. *Timing:*
**fix later** — requires a cross-modality (CT/MR/MG/RGB) equivalence test first.

**DL-2 — `download_all_series` socket FD leak**
*Why:* the socket created at `series_downloader.py:195` is disconnected on every
explicit `return`, but the 475-line body has no `try/finally`; any unexpected
exception leaks the FD until GC. *Evidence:* `series_downloader.py:116-591`.
*Repeated-use risk:* High — runs on every study download. *Recommendation:* wrap the
body in `try:` / `finally: socket_client.disconnect()` (already idempotent).
*Timing:* **fix now.**

**DB-1 — Tab-index map corruption**
*Why:* `close_patient_tab` and the still-exported, unused `remove_patient_tab` use
*different* index logic; `update_tab_indices` also contains a dead `pass` loop. With
service tabs (Download Manager / Education / Web) interleaved, the paths can produce
divergent maps. *Evidence:* `custom_tab_manager.py:612-660, 790-815, 858-914`.
*Repeated-use risk:* High — wrong patient tab closed, or `study_uid_to_tab` pointing
at a stale index. *Recommendation:* delete the unused `remove_patient_tab` and the
dead loop so only the correct widget-matching rebuild remains. *Timing:* **fix now.**

**DB-2 — Tab close path never destroys the patient widget**
*Why:* `close_patient_tab` calls `removeTab` and drops the dict reference but never
calls `widget.deleteLater()`. All real teardown lives in `PatientWidget.closeEvent`,
which only fires when the widget's own X is used. Any other close path detaches the
widget without destroying it. *Evidence:* `custom_tab_manager.py:790-815` vs
`_pw_lifecycle.py:346-415`. *Repeated-use risk:* High — leaked timers, background
tasks, and VTK render windows accumulate across an open/close shift. *Recommendation:*
after `removeTab`, call `widget.deleteLater()` on the stored widget (idempotent with
`closeEvent`). *Timing:* **fix now.**

**DB-3 — Connection-pool thread-ident reuse + narrow exception catch**
*Why:* `_get_pooled_connection` keys the pool by `threading.get_ident()`, which the
OS recycles after a thread dies; a new thread can inherit a dead thread's
connection. Reuse-validation only catches `sqlite3.OperationalError`, but a closed
connection raises `sqlite3.ProgrammingError`, which escapes. *Evidence:*
`database/_pool.py:160-234` (catch at ~193). *Repeated-use risk:* High — recurring
"Cannot operate on a closed database" failures (~89 in the log). *Recommendation:*
broaden the `except` to `(sqlite3.OperationalError, sqlite3.ProgrammingError)` — the
stale connection then fails `SELECT 1` and is transparently recreated. ~1 line.
*Timing:* **fix now.**

**HP-1 — `_fetch_reception_patient_payload` duplicated and diverged**
*Why:* the function exists in both `patient_table_widget.py:2816` and
`_hp_search.py:196`; both are live. They have diverged — PTW uses a hard-coded
`timeout=10` and `logger.debug`; `_hp_search` uses `get_reception_api_timeout()` and
structured `download_diagnostics` events. The reporting-physician extractors also
diverged (different JSON keys). *Repeated-use risk:* Medium — reception hydration can
behave differently between the search path and the report dialog; a server schema
change must be fixed twice. *Recommendation:* consolidate onto the `_hp_search`
version (configurable timeout + structured logging) in a shared service; repoint
PTW's two callers. *Timing:* **fix later** — after one reception-hydration test.

### MEDIUM (condensed — full template fields)

- **DL-3** `download_series` 389-line/5-responsibility hot function (`socket_client.py:993`). *Risk:* hardest code in the app to change safely. *Rec:* extract `_process_batch_instances()` / `_compute_resume_batch_start()` as pure helpers. *Later — only when the file is next touched.*
- **DL-4** Socket-cleanup block copy-pasted ~6× (`socket_client.py:758-929`). *Risk:* a cleanup fix won't reach all copies. *Rec:* extract one `_drop_socket()`. *Later (hot path — schedule).* 
- **DL-5** Two retry engines in `SeriesIntentCoordinator` (`series_intent_coordinator.py:406-850`). *Risk:* every priority bug must be reasoned about twice. *Rec:* delete the legacy path once `INTENT_HANDOFF_V2` is default-on and baked. *Later.*
- **DL-6** `ConnectionPool` eagerly allocates 4 clients, no live caller (`connection_pool.py:57`). *Rec:* make lazy (match `SocketConnectionPool`) or drop the export. *Later.*
- **DL-7** `fetch_study_metadata_sync` falls through to implicit `None` (`grpc_client.py:154`). *Risk:* silent-failure trap on the metadata path. *Rec:* add the unconditional `return self._fetch_metadata_with_retries(...)`; the `if not self.stub` guard is vestigial. ~1 line. **Fix now.**
- **DL-8** `is_connected()` always `True` in pooled mode (`socket_patient_service.py:105`). *Rec:* report real pool availability. *Later.*
- **DL-9** Per-instance `exists()` stat in the download loop (`socket_client.py:1219`) despite a prebuilt skip-set. *Risk:* ~480 redundant syscalls per CT series. *Rec:* check the set first, stat only on miss. *Later.*
- **DL-10** `_send_request_once` 264-line method, manual lock (`socket_client.py:631`). *Rec:* convert to `with self.lock:`, extract `_recv_response()`. *Later.*
- **HP-2** `_on_patient_double_clicked_async` ~489 lines (`_hp_patient_open.py:363`). *Risk:* core flow, near-untestable as one unit. *Rec:* extract the download-queue block (lines 560-667) — pure mechanical move. *Later.*
- **HP-3** ~119 `except: pass` sites in `home_ui/`. *Risk:* a broken viewer wire-up looks like "slow load." *Rec:* add `logger.debug` in the patient-open ones first. *Later, incremental.*
- **HP-4** `update_reporting_physician_for_patient` O(rows²) (`patient_table_widget.py:3617`). *Rec:* maintain a `patient_id → row` index. *Later.*
- **HP-5** `_report_status_cache` / `_reporting_physician_cache` never pruned (`patient_table_widget.py:2552`, `_hp_search.py:278`). *Risk:* unbounded process memory over a long session of searches. *Rec:* clear (or cap) both in `clear_table()`. ~2 lines. **Fix now.**
- **VW-2** Dead duplicate `modules/viewer/backends/` package — stale divergent decode copies, zero importers. *Risk:* editing it is a silent no-op. *Rec:* delete the package (verify the self-import resolves first). **Fix now** (deletion — must be done by you).
- **VW-3** `_decode_into_cache` ~156 lines, `try/except: pass` (`lightweight_2d_pipeline.py:3139`); `record_prefetch_completed()` still fires, so failures look like success. *Rec:* narrow the except to `logger.debug` with `idx` + exception type. **Fix now.**
- **VW-4** 43 `print()` calls (mojibake) in `viewer_2d.py`; `reset_image_viewer` ~310 lines. *Rec:* swap `print()` → `logger.debug` now; defer the function split. **print→logger: fix now.**
- **VW-5** `viewer_2d.py:4250` `cleanup()` — all VTK `Delete()` commented out. *Risk:* VTK render-buffer/scalar leak across patient switches. *Rec:* confirm with a memory probe over ~10 series switches before deciding whether to restore `Delete()`. *Later.*
- **DB-4** CRUD split arbitrarily across `manager.py` / `dicom_db.py`; no behavior divergence yet. *Rec:* over time migrate `manager.py` read helpers into `dicom_db.py`. *Later.*
- **DB-5** Redundant PK sub-lookups in `manager.py` query helpers (`:151,208,300`). *Rec:* return `study_pk` from the first SELECT, drop the second call. *Later — additive.*
- **DB-6** `init_database()` ~300 lines, re-runs 17 migrations every startup, swallows migration errors (`dicom_db.py:47-351`). *Rec:* gate migrations behind a `schema_version` check; narrow the excepts. *Later.*
- **DB-7** `cleanup_connection_pools()` closes every thread's connections (`_pool.py:342`). *Risk:* acceptable at shutdown only. *Rec:* close only the caller's list, or document as shutdown-only. *Later.*

### LOW

- **DB-8** Stray `conn.close()` after the `with` block (`dicom_db.py:1099`, `bulk_update_instances`) closes a pooled connection. *Rec:* delete the line. ~1 line. **Fix now.**
- **DB-9** DB read helpers swallow exceptions with no logging (`manager.py:227,242,801,848`). *Rec:* add `logger.warning` in the except. *Later.*
- **DB-10** `lifecycle_manager.shutdown_all()` ignores its `timeout` (`:106`). *Rec:* run callbacks under a watchdog, or document timeout as advisory. *Later.*
- **DB-11** `servers.json`/config loaded ad hoc in 20+ files. *Rec:* one cached `get_all_servers()` loader. *Later.*
- **VW-6** `_log_drag_metrics_summary` ~334 lines (`qt_viewer_bridge.py:2026`). *Rec:* extract to a helper module. *Later — cosmetic.*
- **VW-7** Permanent `[MG_DIAG]` scan in a hot render path (`lightweight_2d_pipeline.py:1988`). *Rec:* gate behind an env flag or remove. *Later.*
- **HP-6** Series info fetched twice on patient open (`_hp_patient_open.py:582`). *Rec:* cache-check between calls. *Later.*
- **HP-7** `ThumbnailManager` rebuilt per immediate render (`right_panel_widget.py:439`). *Rec:* reuse like the progressive path. *Later.*

---

## 5. Findings Grouped by Fix Risk

### A. Safe small fixes — local, ~1–10 lines, reversible, no behavior change
DL-1 (lock scope), DL-2 (try/finally), DL-7 (missing return), DB-1 (delete dead
method + loop), DB-2 (`deleteLater()`), DB-3 (broaden except), DB-8 (delete stray
close), HP-5 (clear caches), VW-2 (delete dead package — *deletion is yours to run*),
VW-3 (narrow except → log), VW-4 (`print` → `logger`).

### B. Medium-risk refactors — schedule individually, with a test/verification step
DL-3 / DL-10 (extract helpers from the big network functions), DL-4 (`_drop_socket()`),
DL-9 (skip-set before stat), HP-1 (consolidate the reception fetcher), HP-2 (extract
the download-queue block), HP-3 (add logging to silent excepts), HP-4 (row index),
DB-4 (CRUD consolidation), DB-5 (drop redundant PK lookups), DB-6 (`schema_version`
gating), DB-11 (cached config loader).

### C. High-risk architecture changes — only with explicit go-ahead + a written test plan
VW-1 (decode-pipeline consolidation — clinical display equivalence testing required),
VW-5 (VTK `cleanup()` — memory profiling required), DL-5 (remove the legacy retry
engine — only after V2 bakes), splitting the god-classes (`patient_table_widget.py`,
`viewer_2d.py`), reworking the `PacsClient/utils` re-export hub.

---

## 6. Top 5 Safest High-Impact Fixes

1. **DL-1** — `clear_completed()`: snapshot UIDs under the lock, `remove()` after.
   Removes a real UI-stall path and unblocks the unbounded-state cleanup. ~4 lines.
2. **DB-3** — broaden `_pool.py` reuse-validation `except` to include
   `ProgrammingError`. Neutralizes the recurring closed-connection failures *and*
   the thread-ident-reuse hazard. ~1 line.
3. **DB-2** — add `widget.deleteLater()` in `close_patient_tab`. Stops timer/task/VTK
   leaks accumulating across the core open/close cycle. ~1–2 lines.
4. **DL-2** — wrap `download_all_series` in `try/finally: disconnect()`. Closes the
   confirmed socket-FD leak on every download; `disconnect()` is already idempotent.
5. **DB-1** — delete the unused `remove_patient_tab` and the dead `pass` loop in
   `custom_tab_manager.py`. Pure deletion that removes the divergent, buggy
   index-math path so only the correct rebuild remains.

All five are local, individually testable, reversible, and change no clinical or
viewer behavior. Recommended order: DL-1 → DB-3 → DB-2 → DL-2 → DB-1.

---

## 7. What Should NOT Be Touched Yet

- **Decode-pipeline consolidation (VW-1)** — correct in principle, but the three
  paths have diverged; consolidating without a cross-modality (CT/MR/MG/RGB) display
  equivalence test risks a clinical rendering regression.
- **ADVANCED `cleanup()` VTK `Delete()` (VW-5)** — do not blindly restore the
  commented-out calls; measure VTK memory across repeated series switches first.
- **The god-classes/functions** — `patient_table_widget.py` (4,560 lines),
  `viewer_2d.py` (4,765), `download_series` (389), `_on_patient_double_clicked_async`
  (489): do not restructure wholesale. Only extract clearly-pure helper blocks, one
  at a time, when the file is already being touched for an approved fix.
- **The legacy retry engine (DL-5)** — leave until `INTENT_HANDOFF_V2` is default-on
  and has baked in production.
- **The `PacsClient/utils` re-export hub** — do not refactor; just avoid widening it.
- **The dual socket/gRPC client split** — intentional; do not merge.
- **DB schema and `init_database()` table DDL** — no schema changes in this phase.
- **Network wire protocol / socket framing** — out of scope; do not modify.

---

## 8. Notes & Remaining Risk

- This audit was **static** (code reading + the prior log evidence). Behavioral
  confirmation of each fix should come from the existing `tests/` suites and a GUI
  pass over the repeated workflow (multiple patients/studies, thumbnails, scroll,
  no stale/mixed data).
- No fix here removes or disables clinical functionality, metadata, overlays,
  measurements, sync, reference lines, or viewer behavior — that constraint is built
  into every recommendation.
- Recommend doing the **Section 6 top-5** first as individual approved tasks, each
  with a before/after check, before moving to the Section B refactors.
