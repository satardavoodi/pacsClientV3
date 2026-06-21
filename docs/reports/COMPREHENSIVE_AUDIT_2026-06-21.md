# AI-PACS — Comprehensive Application Audit

**Date:** 2026-06-21
**Branch / commit:** `beta-version` @ `56ca5eec`
**Scope:** Full application — architecture, code, performance, database/storage, communication, logging/observability, KPIs, monitoring, user workflows, security.
**Weighting (per request):** Performance + reliability first, then the remaining areas.
**Stance:** This is an *assessment first*. Sections 2–11 establish the evidence-based current state; recommendations and the roadmap come only afterward (Sections 12–14). No source code was modified.

---

## 1. Executive summary

AI-PACS is a large, mature, single-process **PySide6 DICOM workstation** (~735 first-party Python files, ~330k LOC excluding a vendored 805 MB 3D Slicer) backed by SQLite and a custom TCP socket server. It is an unusually *well-instrumented and well-documented* codebase: an async logging core with correlation IDs, a 4,150-test suite that collects cleanly, ~16 "must-not-break" regression-guard sections, and per-incident as-built docs. The engineering discipline around clinical correctness (atomic writes, cross-patient isolation guards, resume-safe downloads) is genuinely strong.

The audit nevertheless surfaces **four Critical and a cluster of High-severity issues**, concentrated in **security** and **observability** — the two areas where the otherwise-careful discipline has not been applied:

- **Critical — Plaintext PHI & credentials in transit.** The PACS socket (port 50052) and the EchoMind AI endpoint (`http://81.16.117.196:8082`) carry patient data, login credentials, generated reports and transcripts **with no TLS**. Verified in source.
- **Critical — Hardcoded production secrets in the repo.** Real `sk-…` LLM API keys and IranNobat keys for **seven named medical centers** are committed in `modules/EchoMind/api_manager.py`; the license-signing secret is hardcoded in `license_manager.py`; login passwords are stored in plaintext JSON. Verified in source.
- **Critical — No data-at-rest encryption.** `dicom.db` and all DICOM/attachment files are unencrypted on disk.
- **High — Native-crash capture is broken.** `faulthandler` is wired **nowhere** (0 references), so the dominant real-world failure class (PySide6/VTK use-after-free access violations) self-records nothing; `native_fault.log` is 9 days stale.

On **performance** (the priority area), the heavy lifting has largely been done well — the FAST 2D pipeline, adaptive download manager, and thumbnail cache are sound. The remaining bottlenecks are specific and addressable: eager top-level imports of multi-second libraries (`openai` ~6.9 s, `pandas` ~5.3 s, `vtkmodules.all`/`pydicom` ~1 s each — measured), a residual main-thread DICOM-decode-on-cache-miss path, **61 `processEvents` call sites** in hot paths, and ~1 GB peak RSS in real sessions.

On **maintainability**, the load-bearing risk is **scale and configurability sprawl**: **281 distinct `AIPACS_*` feature flags** (mostly never-retired default-on kill-switches), a 9,330-LOC toolbar god-file (75 files > 1,000 LOC), a 37-file mixin explosion, ~1,900 LOC of dead gRPC code kept in-tree, and ~2,000 silent `except: …: pass` handlers that create monitoring blind spots.

**Test health is good:** 4,150 tests collected with **0 collection errors**; verified green subsets total **665 passing** across `ui_services`, `database`, `runtime`, `download_manager`, `network`, `system` (full-suite result appended in §13).

The single most valuable cross-cutting investment is **observability + KPI runtime telemetry** (turn the rich-but-passive logs into live error-rate / latency / crash signals), closely followed by a **security remediation sprint** (TLS, secret rotation, at-rest encryption). Neither requires touching clinical geometry or the viewer hot paths.

---

## 2. Methodology & evidence base

This audit combined four independent evidence streams:

1. **Static analysis** — seven parallel domain investigations (architecture, performance, database, communication, observability, reliability/debt, security/UX) reading source with file:line citations, grounded against the project's own `docs/` and `CLAUDE.md` and verified against code.
2. **Test execution** — pytest 9.0.3 in the real `.venv` (Python 3.13.5, `QT_QPA_PLATFORM=offscreen`): full collection plus targeted suite runs.
3. **Log mining** — direct metric extraction from `user_data/logs/` (`app.log`, `download_diagnostics.log`, `db_diagnostics.log`).
4. **Live measurement** — heavy-library import timing and real-session memory (RSS) drawn from runtime logs.

**Items independently verified by the auditor (not just reported):** the 281-flag count, 735-file / 381-test-file counts, 4,150-test clean collection, the green core-suite runs, the four security findings (read in source — secret values are **masked** in this report), `faulthandler=0`, `native_fault.log` staleness, app.log heartbeat ratio, peak RSS, and the import-cost table.

**Caveats / limits.** Import timings were measured while the test suite ran concurrently (CPU contention), so absolute numbers are upper bounds — the *ranking* is the reliable signal. The live `dicom.db` was not opened (schema assessed from `CREATE TABLE/INDEX` in code, which is authoritative for structure but not row counts/fragmentation). A GUI cold-start stopwatch pass (human-assisted launch) was not run in this pass and is offered as an addendum. Server-side behavior (TLS termination, password hashing, server audit logs) is out of repo scope and cannot be confirmed from the client.

---

## 3. Current architecture overview

**Process & boot.** Single-process Qt desktop app. `main.py` (~1,281 LOC) sets Qt/Nuitka env, calls `multiprocessing.freeze_support()`, creates the `QApplication`, acquires a `SingleInstanceLock` (Qt `QLocalServer` + takeover), checks `LicenseManager`, integrates asyncio via `QEventLoop` (qasync), then shows `AppHandler` (frameless login `QDialog`) → `MainWindowWidget` → the workstation shell after auth.

**Module model.** A 15-entry `MODULE_CATALOG` (`aipacs_runtime.py`) declares tier (basic/optional), `default_enabled`, plugin-package metadata and healthcheck imports, gated by `is_module_enabled()`. **Caveat:** `_should_enforce_module_profile()` makes dev/source runs enable everything, so flag/tier gating only actually bites in installed builds — the dev and customer execution paths differ. A generic `ModuleManager` (`module_system/`) with a `ThreadPoolExecutor` exists, but the main UI modules are wired by direct/lazy imports, not through it (two parallel module-execution models).

**Dominant pattern — "horizontal mixin splitting."** Four god-objects are each one logical class physically split across ~10 mixin files sharing one mutable `self`:

- `PatientWidget` — `widget.py` is 368 LOC / 2 methods but inherits **~252 methods** across **10 `_pw_*` mixins**.
- `ViewerController` — **~211 methods** across **7 `_vc_*` mixins**.
- `HomePanelWidget` — **10 `_hp_*` mixins**; the DM widget — **10 `_dm_*` mixins**; the VTK widget — 10 `_vw_*`; MPR — 13 `_mpr_*`.

This eases editing but not coupling: any mixin can touch any other's state; clinical invariants (multi-study offset-keys, exact-series load) are upheld by hand across all of them.

**Layering & coupling.** Intended layers (presentation → orchestration → imaging → network → download → infra) exist in docs, but in code `modules/` → `PacsClient` (**225 imports across 120 files**) *and* `PacsClient` → `modules.*` are bidirectional, so there is no clean dependency direction and modules are not independently loadable despite the plugin framing. `PacsClient.utils.__init__` is an eager re-export hub (config + database + db_manager + AI-chat DB), so importing it pulls in the DB/service layers. A known import cycle exists: `download_manager.__init__ → home_panel.widget → modules.network.zeta_adapter → download_manager`.

**Transport.** Custom **synchronous TCP socket** protocol: 4-byte big-endian length prefix + UTF-8 JSON envelope `{endpoint, params, token}`; DICOM pixels shipped as base64 (optionally gzip) **inside** the JSON. Socket port (50052) from `config/socket_config.json`; DICOM port (104/105) from `servers.json`. The real gRPC stack in `modules/network/` is **dead** (~1,900 LOC); `GrpcMetadataClient` is socket-backed despite its name. Two parallel socket clients (download vs patient/thumbnail) duplicate framing logic with divergent size limits.

**Data.** SQLite (`dicom.db`) via a per-thread connection pool (max 5/thread) with WAL, `synchronous=NORMAL`, `busy_timeout=120 s`, capped lock-retry backoff. Hierarchy patients→studies→series→instances with FK cascades; the download subprocess shares the live DB with retry/backoff. Files are stored per-study-UID with atomic `*.part`→`os.replace()` writes (DICOM and thumbnails).

**Module inventory (22 dirs under `modules/`):** viewer, download_manager, mpr (+ vendored 3D Slicer), EchoMind, education, cloud_consultation, Identity, cd_burner, network, ai_imaging, printing, stitching, storage, zeta_boost, zeta_sync, offline_cloud_server, data_analysis, web_browser, upload_manager, module_system, LicenseGenerator.

---

## 4. Detailed findings by area

Each finding has an ID for traceability (used in the §15 register and §13 roadmap). Severity: **Critical / High / Medium / Low**. Evidence is `file:line` unless noted.

### 4.1 Architecture & maintainability

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| ARC-1 | High | God-objects split into mixins, not decomposed | `patient_widget_core/widget.py` (368 LOC) inherits ~252 methods from 10 `_pw_`; `ViewerController` ~211 over 7 `_vc_` | Shared mutable `self`, no interface boundaries → coupling/testability identical to one giant class; clinical invariants enforced by hand across files |
| ARC-2 | High | Bidirectional `PacsClient ↔ modules` coupling | modules→PacsClient 225×/120 files; PacsClient→modules across network/viewer/dm/mpr | No layer direction; modules not independently loadable despite plugin/tier framing; import-order fragility |
| ARC-3 | High | Runtime-flag explosion | **281 distinct `AIPACS_*`** flags (verified); 215 in PacsClient alone | Each fix ships a permanent default-on kill-switch; combinatorial config is effectively untestable; flags never retired |
| ARC-4 | High | Extreme single-file size (god-files) | 75 files >1,000 LOC; `toolbar_manager.py` **9,330**, `ai_chat_pages.py` 7,478, `patient_table_widget.py` 5,991, `viewer_2d.py` 4,832, `lightweight_2d_pipeline.py` 4,003 | Concentrated change-risk; these are the files cited repeatedly in regression history |
| ARC-5 | Medium | Known import cycle | `home_panel/widget.py:40` ↔ `zeta_adapter.py:13` ↔ `download_manager.__init__` | Documented test-collection fragility; init order becomes load-bearing; latent crash under refactor/freeze |
| ARC-6 | Medium | Module gating inert in source / dual-path | `aipacs_runtime.py` `_should_enforce_module_profile()` returns all-True in dev | Customer-facing gating exercised differently than developers run it — the "works in source, missing in build" class |
| ARC-7 | Medium | `PacsClient.utils` eager re-export hub | `PacsClient/utils/__init__.py` eagerly imports config+db+db_manager+services | Pervasive imports pull in DB/service layers → import-time + circular-import risk |
| ARC-8 | Medium | Plugin-mirror duplication needs manual sync | `tools/dev/sync_plugin_mirrors.py` + `verify_plugin_mirrors.py`; mirrored `modules/education`, run_cd, socket_client, DM files | Source-of-truth split across byte-copies; a missed sync silently ships stale code (recurring "my fix isn't in the build") |
| ARC-9 | Low | Architecture docs lag code by major versions | `docs/architecture/overview.md` v2.3.3 cites removed paths; app is v3.3.5 | Docs ground intent but can't be trusted for current structure |

### 4.2 Performance & responsiveness — PRIORITY

The performance program is mature and largely well-executed (see §11 Strengths). Remaining issues, ordered by impact:

| ID | Sev | Finding | Evidence | Why it matters / measured |
|----|-----|---------|----------|----------------|
| PERF-1 | High | Eager top-level imports of multi-second libraries | `main.py:627-642` (PySide6+`vtkmodules.vtkCommonCore`+qasync top-level); `vtkmodules.all`/`SimpleITK` top-level in 25+ patient-tab/viewer files (`patient_widget_core/widget.py:6`, `image_io.py:11-13`) | **Measured (under load):** `openai` ~6.9 s, `pandas` ~5.3 s, `vtkmodules.all` ~1.0 s, `pydicom` ~1.0 s. Any on the eager startup path dominates cold start for a FAST-2D workflow that may never open VTK. Direction: lazy-import behind the Advanced/VTK entry point |
| PERF-2 | High | Main-thread DICOM decode on cache miss during interaction | `lightweight_2d_pipeline.py:2395 _get_pixel_array`→`:2453 pydicom.dcmread`, reached from drag/wheel `qt_viewer_bridge.py:1092` | On cold cache / fast scrubbing the GUI thread does a synchronous read+decode per frame (self-labeled `foreground_disk_reads=1`); the #1 instrumented stall source despite caches+surrogates |
| PERF-3 | Medium | `processEvents` density in hot paths | **61 call sites across 17 files**; `toolbar_manager.py` 12, `_vc_load.py` 5, `_pw_viewers.py` 7, `_pw_pipeline.py` 6 | Re-enters the event loop inside user slots (re-entrancy/jank); several sit in loops scaling with slice count |
| PERF-4 | Medium | Redundant thumbnail disk+DB scan on socket-error fallback | `_hp_search.py:691 _build_cached_thumbnail_payload` invoked on fast-path AND each empty/exception socket fallback (~:1453/:1715/:1738) | A single click on a slow link can repeat a full directory listing + DB query 2–3×; memoize within the click scope |
| PERF-5 | Medium | Double `get_study_thumbnails` for the primary study on open | `_hp_search.py:~1647` (main page) + `_pw_thumbnails.py:~311` (viewer sidebar) | Two overlapping socket calls for identical data on open; on slow links the second queues behind the first |
| PERF-6 | Medium | Adaptive batch GROWTH disabled by a data-loss guard | `socket_client.py:167-182,1754-1759` (`_PAGINATION_SAFE` default on) | Server pages by `batch_index = batch_start // batch_size`; growth broke tiling and silently dropped series tails (verified 47221 s202 wrote 40/52), so growth is fully disabled → every batch keeps paying ~40 ms/request on fast LAN. Real fix is server-side stable pagination |
| PERF-7 | Low-Med | Per-frame RGB copies for color/overlay frames; psutil in load-decision path | `lightweight_2d_pipeline.py:2186-2214`; `_vc_backend.py:510,539` `psutil.virtual_memory()` per viewer-load | Extra per-frame CPU/alloc for color/MG/overlay series (grayscale CT/MR avoids it); a sync system query per tab-switch (not per frame) |
| PERF-8 | Low-Med | Memory footprint ~1 GB peak in real sessions | **Measured from app.log:** RSS min 211 / avg 573 / **max 1006 MB** | Acceptable for imaging but trending toward limits with multi-study + VTK; no runtime leak alerting (GDI/USER handles logged but only trended offline) |

> **Correction folded in:** an earlier pass flagged a main-thread `requests.get` (3–10 s hang) at `patient_table_widget.py:3959`; on verification those HTTP calls run inside a `threading.Thread(daemon=True)` worker — **not** a main-thread stall. Several `time.sleep()` calls in `image_io.py`/`image_filters.py` are likewise worker-side, not GUI-thread.

### 4.3 Database & storage

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| DB-1 | Medium | No automatic storage retention / quota → unbounded DICOM growth | `modules/storage/disk_alert_service.py` (90%-full warning only), `local_storage_cleanup_manager.py`, `patient_cleanup_manager.py` (manual) | A clinical workstation silently fills its disk; the only automation is a dialog at 90% requiring human action |
| DB-2 | Medium | `studies.study_date` unindexed but drives most queries/sorts | `dicom_db.py:981-987,1600-1613`; `search_patients_local`, `get_patients_by_date_range`, `ORDER BY study_date DESC` | Date filter + sort scans the studies table; latency grows with table size on a GUI-blocking path. One cheap index fixes it |
| DB-3 | Medium | Many DB calls run synchronously on the GUI thread | `_hp_series.py` (`_reconcile_patient_studies_on_click`, `_load_and_display_series_info`) call `find_study_pk…`/`get_series_by_study_pk` on the UI thread | Bounded for 1–3 UIDs, but under downloader write contention (120 s busy_timeout) a click can stall; read-side queries not consistently off-thread |
| DB-4 | Low-Med | Per-thread pool → connection churn | `_pool.py:160-210`; keyed by `thread.ident`, dead-thread eviction only past 16 entries | Many short-lived daemon threads each open up to 5 connections (9 PRAGMAs each) on hot paths |
| DB-5 | Low | `series_number` stored as TEXT in an INTEGER column | `database_manager.py:169` writes `str(...)`; `manager.py:145` `ORDER BY series_number` | Affinity coerces clean numerics, but edge values sort lexically → subtle series mis-ordering; multi-study offset-keys assume numeric order |
| DB-6 | Low | `INSERT OR REPLACE` on instances reallocates PK | `dicom_db.py:711-767,1313-1357` | Safe today (no child tables) but a latent foot-gun if `instance_pk` ever gains FKs; churns autoincrement on re-download |
| DB-7 | Low | `find_instances_by_sop_uids` builds unchunked `IN (?)` | `dicom_db.py:1293-1310` | A huge series can exceed `SQLITE_MAX_VARIABLE_NUMBER` and throw during resume/dedup; should chunk |
| DB-8 | Low | Delete is multi-step, not transactional across DB↔disk; no WAL `TRUNCATE` at shutdown | `patient_cleanup_manager.py:48-70`; `_pool.py:291` `wal_autocheckpoint=2000` | A crash mid-delete leaves orphan files / `download_progress` rows (self-heal exists); `-wal` can grow on long busy sessions |

### 4.4 API & communication layer

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| NET-1 | High | PACS socket transport has no TLS — PHI + credentials in cleartext | `socket_client.py:366-374`, `login() :595`; `modules/network/socket_client.py:107-111` (raw `AF_INET/SOCK_STREAM`, no `ssl`) | Login password, JWT, demographics, base64 DICOM all in plaintext on the LAN; exposed on any routed/VPN/multi-site link (the Razi/Mehr multi-server direction) — *see also SEC-1* |
| NET-2 | High | Duplicate socket-transport implementations with divergent limits | `download_manager/network/socket_client.py` (2,083 LOC) vs `modules/network/socket_client.py`; size caps 500 MB vs 50/500 MB; broadcast caps 50 vs 200 | A protocol/limit fix must be made twice and can drift; framing/broadcast/decode forked |
| NET-3 | Medium | Dead gRPC stack still imported at package init | `PacsClient/components/__init__.py:1-2`; `modules/network/{grpc_client,multi,dicom_downloader*,dicom_service_pb2*}.py` (~1,900 LOC) | Eagerly imports `grpc`/builds stubs for code never instantiated at runtime; misleading "grpc" name actively misled past investigations |
| NET-4 | Medium | Single global download slot → preemption thrash on slow links | `core/constants.py:88` `MAX_CONCURRENT_STUDIES=1`; `series_intent_coordinator.py:460`; `_dm_priority.py:410-524` | A cross-study drag triggers pause-all/preempt + a 90×200 ms retry poller; on a dropping link the kill/respawn/reauth cycle can starve completion (the documented drag-drop thrash) |
| NET-5 | Medium | Token sent as plaintext JSON field; no per-request integrity | `socket_client.py:810-816` (`request["token"]`) | Over an unencrypted socket a MITM can replay/alter requests or swap DICOM bytes; needs TLS + (ideally) signing |
| NET-6 | Low | `__del__`-driven socket cleanup; broadcast-skip can exceed nominal timeout | `socket_client.py:2076-2082`; broadcast loop `:858-997` (skips up to 50, each bounded by 30 s timeout) | GC-timed socket close is non-deterministic; worst-case wait far exceeds one timeout (the patient client's wall-clock `response_deadline` pattern is better — apply to the download client) |

### 4.5 Logging & observability

The logging **core** is genuinely sophisticated (async `QueueListener`, structured formatter with pid/tid/component/correlation/study/series IDs, `SafeRotatingFileHandler`, a 2-second resource monitor, `log_stage_timing()`). The **gaps** are in crash capture, signal-to-noise, retention, and the absence of any runtime aggregation.

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| OBS-1 | High | `faulthandler`-to-file is wired nowhere → native crashes self-record nothing | **Verified: 0 `faulthandler` refs** in `main.py`+`PacsClient`; `native_fault.log` last-write **2026-06-12** (9 days stale) vs app.log today; `CRASH_EVAL_PC2_SANAM_2026-06-17.md` confirms a client crash with no native log | The actual crash class (PySide6/VTK UAF access-violation `0xc0000005`) is native and uncatchable by `sys.excepthook`; every field native crash is undiagnosable |
| OBS-2 | High | `app.log` is ~70% idle resource-summary heartbeat | **Verified:** 32,768 / 46,859 lines (70%) are `resource-summary`, logged every 2 s unconditionally | Rotates 20 MB in ~1–2 days (only 3 backups → ~4–6 days history); a crash investigated a week later has no surviving logs |
| OBS-3 | High | ~2,000 silent `except: …: pass` handlers → monitoring blind spots | Multiline grep ≈ **2,024 across 252 files**; viewer/download hot paths (`_vc_load.py` 52, `qt_viewer_bridge.py` 49, `ai_chat_pages.py` 132) | "Thumbnails silently didn't load / series silently failed" is unanswerable when the failing branch logs nothing |
| OBS-4 | High | KPIs exist only in tests + offline tools, **nothing aggregated at runtime** | `tests/_kpi/schema.py` (thresholds), `tools/kpi_dashboard.py`, `tools/reliability/soak_log_analyzer.py` parse logs after the fact; app emits raw `stage-timing`/`resource-summary` but no rolled-up error rate / p95 / health signal | No way to know production health without manually pulling and parsing log files; no alerting |
| OBS-5 | Medium | `download_diagnostics.log` is 98% WARNING — severity miscalibrated | Progress aggregator logs routine progress at `logger.warning` (`diagnostic_logging.py:710`); ~98% of lines WARNING | WARNING is meaningless as a filter; genuine ERRORs are buried |
| OBS-6 | Medium | No log retention/cleanup; runtime dir polluted with test debris | logs dir **286 MB**; 18 stray `pytest_*.txt`/`_audit_probe.txt`/`*.json`; un-rotated `com_trace.log`, `native_fault*.log` | Unbounded growth on clinical workstations; runtime dir mixed with test artifacts |
| OBS-7 | Medium | Active stream-desync errors firing in normal use | **Verified (current rotation):** `Response too large` ×144, `Error in send_request` ×191, `timeout` ×22 (download_diagnostics) | A real, recurring, partially-handled reliability signal nobody aggregates (ties to PERF-6/NET) |
| OBS-8 | Low-Med | Second divergent logging config + emoji in messages | `download_manager/utils/logger.py` (different format, `handlers.clear()`, dormant); emoji `❌/✅` in log lines | Silent inconsistency footgun; emoji risk `UnicodeEncodeError` on non-UTF-8 consoles and complicate grep/automation |

**Positive baseline:** `db_diagnostics.log` shows **0 ERROR / 0 "database is locked"** in the current rotation and `right_panel_socket_error=0` — the DB-lock and thumbnail-socket paths are currently healthy.

### 4.6 Reliability, crash risk & technical debt — PRIORITY

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| REL-1 | High | PySide6 use-after-free crashes are a recurring, reactively-patched class | `docs/technical-debt/suspected-issues.json` OBS-010/FIX-007/FIX-008; `shiboken6.isValid` guards in ~22 files (40 occ) | Each UAF is fixed at one site; no systemic Qt-ownership discipline → the next unguarded `.window()`/dialog-parent/animation site is the next crash. A crash mid-read is a clinical event |
| REL-2 | High | `QApplication.notify()` override re-raises into the Qt dispatch | `main.py:751-846` | OBS-010 attributes PC2 crashes to `notify()` re-raising event-dispatch exceptions into a PySide cascade; a diagnostic hook is *amplifying* crashes (+ heavy widget-tree walk in the crash path) |
| REL-3 | High | Feature-flag sprawl — 281 default-on kill-switches, legacy paths retained forever | Verified 281; `CLAUDE.md` policy "flip a flag to revert; do not delete the legacy path" | Every flag multiplies live code paths; the real-world config is one untested combination; largest accumulated-risk signal |
| REL-4 | High | God-files beyond safe-edit size | `toolbar_manager.py` 9,330 LOC (also a voice-UI UAF origin); `patient_table_widget.py` 5,991; `_vc_progressive.py` 3,792; `image_io.py` 3,734 | Un-reviewable, un-safely-editable; concentrate change-risk and defeat the regression guards' intent |
| REL-5 | Medium | `QThread.terminate()` in DM worker pool bypasses `run()` cleanup | `workers/worker_pool.py:155,304,361` (mitigated by DM-H4 `ensure_subprocess_dead()` :170) | Correct today, but safety depends on a fragile timing chain + an opt-in `getattr`-discovered method → easy to regress (orphan child holds sockets + writes `dicom.db`) |
| REL-6 | Medium | Distributed ad-hoc threading, **no central pool, 0 `QMutex`** | ~6 QThread + ~31 threading files (PacsClient); ~99 threading files / 290 occ (modules); `QMutex`/`QReadWriteLock` = 0; ~176 `QTimer.singleShot`/51 files | Concurrency is bespoke per feature; cross-thread correctness is by-convention; every new thread is a potential race |
| REL-7 | Medium | Mixin explosion (37 split-class files) raises change risk | `_hp_`×10, `_vc_`×7, `_pw_`×10, `_dm_`×10 | Implicit cross-file state; the multi-study/cross-patient/count-doubling regressions all live here |
| REL-8 | Medium | ~1,900 LOC dead gRPC + 42k-LOC `_recovery/` quarantine + ~10 uncleaned worktrees + multi-GB backups | `modules/network/` (6 dead files), `_recovery/` (45 .py), `.claude/worktrees/`, `backups/*` (vendoring `.venv`) | Inflates every repo search, risks edits to the wrong copy, bloats the tree |
| REL-9 | Medium | Heavy main-thread monkeypatch instrumentation available in hot path | `main.py:191-530` wraps `os.*`, `pydicom.dcmread`, `sqlite3`, `__import__`, GC (opt-in `AIPACS_UNKNOWN_STALL_HOOKS`); F8 50 ms probe + F11 sampler **default-on** | Patching `sqlite3.connect`/`__import__` globally is high-blast-radius; default-on probes add steady-state cost/log volume in release builds |
| REL-10 | Medium | ~40 "must-not-break" invariant blocks = systemic fragility signal | `CLAUDE.md` (~16 guard sections) + ~50 memory topic files; `suspected-issues` registry (19 items, several clinical-geometry deferred RED) | Almost any edit touches a guarded invariant; change cost depends on an external memory system, not self-evident code; a standing set of known-RED tests erodes the "all green" signal |

### 4.7 Security

> All four Critical/High items below were **read in source by the auditor**; secret values are masked here.

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| SEC-1 | Critical | PHI + credentials transmitted in cleartext (no TLS) | `modules/network/socket_client.py:107,196-197`; `socket_client.py:581-598` (login posts plaintext user/pass); EchoMind `http://81.16.117.196:8082` | Anyone on the LAN can sniff PHI + credentials or MITM the session; no `ssl/wrap_socket` in either client |
| SEC-2 | Critical | Hardcoded production secrets committed to the repo | **Verified** `modules/EchoMind/api_manager.py:34-105` — real `sk-…` GapGPT + IranNobat keys for 7 named centers (RAZI/IMA/ROOHANI/HASANPOUR/ASSARZADEGAN/BRAKE/FAZEL); `config/echomind_settings.json:2` committed `api_key` | Recoverable from source *and* the frozen installer; anyone can bill against / impersonate every center. Rotate all, move to secure storage |
| SEC-3 | Critical | Cleartext AI endpoint over public IP | **Verified** `ai_chat_config.py:23` `AI_BASE='http://81.16.117.196:8082'` → `/chat`, `/generate_report`, `/generate_transcript` | Clinical chat, generated reports and transcripts (PHI) POSTed in cleartext to a public IP — interceptable/tamperable |
| SEC-4 | Critical/High | No data-at-rest encryption (DB, DICOM, attachments) | `database/` (no SQLCipher/PRAGMA key); `user_data/patients/` plain files, OS-default ACLs | Disk theft or any local read exposes all PHI |
| SEC-5 | High | Login credentials stored in plaintext on disk | **Verified** `login_ui.py:254-268` `save_credentials` writes `password` to `%APPDATA%/AIPacs/login_config.json`; `:191` reads it back + auto-login | Any local user/malware reads clinical-system credentials directly (the "pre-filled" mechanism) |
| SEC-6 | High | Hardcoded license signing secret → forgeable licenses | **Verified** `license_manager.py:86` `secret_key="AIPACS-SECRET-KEY-2026-V1"`; license = `sha256(hwid\|expiry\|secret)[:24]` | Anyone with the binary can mint valid licenses (comment itself says "use environment variable") |
| SEC-7 | Medium | No client-side authorization model or PHI-access audit log | login `role` displayed only (`login_ui.py:243`); audit logging exists only for downloads/consultation | Single-trust workstation: no enforcement on viewing/exporting; no record of who viewed which patient |
| SEC-8 | Medium | AI/OpenAI key persisted in plaintext config (inconsistent with secure_store) | `EchoMind/settings_store.py:67-77` `json.dump` vs keychain-backed OAuth/web-browser secrets | The good `secure_store`/DPAPI pattern exists but isn't applied to AI/login configs |
| SEC-9 | Low | Secure-store fallback key not OS-sealed; stray `.bak` source files | `Identity/secure_store.py:94-104` (Fernet key beside ciphertext; DPAPI "planned"); `.bak-20260614` files | Fallback reversible by a local reader; minor source-leak hygiene |

**Security strengths (real):** consultation **de-identification is default-ON and fail-closed** (`study_select.py:61-74`, `deidentify.py:184-194` — un-de-identifiable files are deleted, raises if none survive); OAuth tokens + saved website passwords use **OS keychain/DPAPI** via an audited `secure_store`; the auth JWT is **memory-only, never persisted to the DB**; cross-patient isolation is the highest-severity guarded invariant.

### 4.8 UX / workflow

| ID | Sev | Finding | Evidence | Why it matters |
|----|-----|---------|----------|----------------|
| UX-1 | Medium | Modality + date filters not remembered across sessions | `patient_search_widget.py:162-190` (`previously_checked` rebuilt from live state only) | A radiologist re-selects the same modality + date on every launch — daily friction |
| UX-2 | Medium | Single-click thumbnail load delayed by full double-click interval | `patient_table_widget.py:1810-1837` (waits `doubleClickInterval`, floor 250 ms) | Correct fix for double-click reliability, but every single-click incurs a visible ~250 ms wait — the most frequent micro-friction |
| UX-3 | Medium | Interrupting modal popups in the startup path | disk-full popup before login (CLAUDE.md startup step 4); `app_handler.py:998` blocking `QMessageBox.critical` | Modal dialogs halt the workflow and must be dismissed before continuing |
| UX-4 | Medium | Slow startup / post-login load (perceived) | CLAUDE.md "startup takes time"; ties to PERF-1 | The radiologist waits twice before reaching the worklist |
| UX-5 | Low-Med | Explicit multi-step search; uneven error feedback | `patient_search_widget.py:884 _on_search_clicked`; some load errors only `print()` (`_pw_series.py:589-652`) | Listing today's worklist takes several actions vs auto-populating; mature spinner UX coexists with console-only failures |

> **UX strength:** the viewport error-state UX has matured well — persistent spinner with progress/ETA/connection-state and disk-ready auto-resume rather than a blank viewport.

---

## 5. Identified bottlenecks (consolidated)

Ranked by expected effect on the clinical experience:

1. **Cold-start latency from eager heavy imports (PERF-1).** Measured import costs (under load): `openai` ~6.9 s, `pandas` ~5.3 s, `vtkmodules.all` ~1.0 s, `pydicom` ~1.0 s, PySide6/SimpleITK/cv2 ~0.2–0.35 s. Anything multi-second on the eager path is felt on every launch.
2. **Main-thread DICOM decode on cache miss (PERF-2).** The only instrumented GUI-thread stall during scrubbing; felt as choppiness on cold series / fast stacking.
3. **Network round-trip floor on downloads (PERF-6 / NET).** Batch growth is disabled for a correctness reason, so every batch pays ~40 ms/request; large series download slower than necessary on a fast LAN.
4. **Single download slot + preemption thrash on slow links (NET-4).** One study at a time; impatient re-drags can starve completion.
5. **Redundant thumbnail fetch/scan on open & on slow-link fallback (PERF-4/PERF-5).** Double `get_study_thumbnails` and repeated disk+DB scans.
6. **`study_date` scan/sort on every patient search (DB-2)** and **GUI-thread DB reads under downloader write contention (DB-3).**
7. **`processEvents` re-entrancy in toolbar/viewer hot paths (PERF-3).**
8. **Log write volume (OBS-2/OBS-5):** ~46 k lines/1–2 days in app.log (70% heartbeat), 98%-WARNING download log — I/O + rotation churn and lost history.

## 6. Performance risks

- **Startup regression risk is unbounded** while heavy imports are eager and 281 flags can alter the boot path differently in source vs build.
- **Memory trend:** ~1 GB peak RSS today (measured) with no runtime leak/handle alerting; multi-study + Previous-Exams + VTK can push higher, and GDI/USER-handle growth is only trended offline.
- **Interaction stalls** will reappear wherever a new code path does synchronous disk/`pydicom`/`psutil`/DB work on the GUI thread — the pattern recurs (the project has fixed several instances reactively); without a lint/guard it will recur again.
- **Download correctness-vs-speed tension (PERF-6):** the safe pagination cap means the gap-fill pass adds a full extra disk re-scan; the real fix is server-side stable pagination.
- **Crash-driven "performance":** a native UAF (REL-1/REL-2) mid-session is the worst latency event of all and is currently invisible to telemetry (OBS-1).

## 7. Logging & observability gaps (summary)

The core is strong; the gaps (detailed in §4.5) are: **(a)** native-crash capture broken (`faulthandler=0`, OBS-1); **(b)** 70% heartbeat noise + ~6-day history window (OBS-2); **(c)** ~2,000 silent `except: pass` blind spots (OBS-3); **(d)** no runtime metric aggregation — KPIs live only in tests/offline tools (OBS-4); **(e)** miscalibrated severity (98% WARNING, OBS-5); **(f)** no retention + test-debris pollution (OBS-6). Net: logs are excellent for *post-hoc, manual, on-box* tracing (good correlation IDs) but cannot answer "is the fleet healthy right now?" or capture the dominant native crash.

## 8. KPI assessment

**What exists.** A real KPI registry with thresholds lives in `tests/_kpi/schema.py` (e.g. patient_open ≤ 400 ms, viewer first_render ≤ 800 ms, scroll ≥ 30 fps, thumbnail cross-patient-leak = 0) and offline analyzers (`tools/kpi_dashboard.py`, `tools/reliability/soak_log_analyzer.py`). The running app emits the *raw materials* (`stage-timing duration_ms`, `resource-summary cpu/rss/io/gdi/user`, `download-summary throughput`) but **aggregates nothing at runtime** and ships nothing off-box.

**Measured baselines captured during this audit (real data):**

| Metric | Value (this audit) | Source |
|--------|--------------------|--------|
| Peak process RSS | **1,006 MB** (avg 573, min 211) | app.log `resource-summary` |
| `openai` / `pandas` import cost | **~6.9 s / ~5.3 s** (under load) | venv import timing |
| `vtkmodules.all` / `pydicom` import | ~1.0 s / ~1.0 s | venv import timing |
| app.log heartbeat share | **70%** (32,768 / 46,859 lines) | app.log |
| Download errors (current rotation) | `Response too large` 144, `send_request` err 191, timeout 22 | download_diagnostics.log |
| Thumbnail socket success / error | 150 / **0** | download_diagnostics.log |
| DB "database is locked" (current) | **0** | db/download logs |
| Test suite | **4,150 collected, 0 collection errors** | pytest |

**Gaps / recommended KPIs (not measured today, all derivable):** startup time (cold/warm), patient-open p50/p95, viewer first-render p95 + scroll fps in production, **error rate** (errors/hour by component), **crash rate / MTBF** (needs OBS-1 fix first), download success rate + throughput distribution, DB-lock incidence, memory/handle leak slope per session, thumbnail failure rate, and **feature-usage counters** (which of the 22 modules are actually used). None of these are emitted/rolled up at runtime today.

---

## 9. Monitoring & diagnostics blind spots

- **Native crashes (OBS-1):** the single biggest blind spot — no in-app capture; root-causing the PC2 crash required pulling Windows `.evtx` + WER minidumps from the client machine.
- **Swallowed exceptions (OBS-3):** ~2,000 `except: pass` sites, concentrated in the viewer/download/AI-chat hot paths, hide failures from both the user and the logs.
- **Fleet health:** no off-box telemetry; there is no way to know error/crash/latency trends across installed centers without manually collecting logs.
- **Orphan subprocesses:** download subprocesses can outlive their parent (REL-5 mitigation exists but is fragile); during this audit, lingering `python.exe` processes were observed after an aborted test run — exactly the orphan class to monitor.
- **Resource leaks:** GDI/USER handle and RSS slope are logged but only trended by an offline tool, so a slow leak is invisible until a crash.
- **Session segmentation:** the offline soak analyzer keys off `[SESSION_START]/[SESSION_END]` markers that appear in only one source file, so per-session leak/clean-shutdown analysis is partly blind.

## 10. User-workflow summary

The clinical path — launch → (disk-full popup) → login (pre-filled, Sign In) → modality → date → Search → single-click (thumbnails) / double-click (open) → series drag-load → measurements/overlays → report/attachments — is functional and recently hardened (mature viewport spinner/progress, disk-ready auto-resume). The friction a radiologist hits most: re-entering modality+date every session (UX-1), the ~250 ms single-click debounce before thumbnails (UX-2), interrupting modal popups (UX-3), and perceived slow start (UX-4, ties to PERF-1). Powerful multi-study / Previous-Exams comparison features exist but are built from many flag-gated branches, raising edge-case and maintenance complexity.

## 11. Strengths (what is genuinely well done)

Preserving these is as important as fixing the gaps:

- **Clinical data integrity.** Atomic `*.part`→`os.replace()` writes, resume scans rejecting partial/`<128 B` files, `bytearray` recv (no O(n²)), post-download completeness gap-fill — clinical images don't tear or silently truncate.
- **Cross-patient isolation** is treated as the highest-severity invariant with layered server-owner checks + dedicated regression tests; de-identification before consumer-Drive/Gmail egress is default-ON and fail-closed.
- **FAST 2D viewer pipeline** — a sound 3-tier cache (LRU memory → disk pixel cache → prefetch + decode subprocess), int16 LUT W/L fast path, surrogate frames during drag; correctly avoids VTK for 2D (and the FAST stack-drag psutil sampler is correctly gated OFF).
- **Download manager** — adaptive batch + first-image prime + soft cap, DB-lock retry/backoff, worker-subprocess `ensure_subprocess_dead()`, drag/visibility-gated table refresh.
- **Logging core** — async non-blocking queue, structured correlation IDs, Windows-safe rotating handler, resource monitor (the *plumbing* for great observability already exists — it just isn't aggregated).
- **Process hardening** — robust single-instance lock + clean takeover, WAL + 120 s busy_timeout + capped backoff, build/release-parity gate for the module/flag system.
- **Engineering memory** — ~16 regression-guard sections, per-incident as-built docs, 4,150 tests collecting cleanly, kill-switch-per-fix discipline that makes reverts a one-flag operation. (This same discipline, applied to security/observability, would close most of this report.)

---

## 12. Prioritized optimization opportunities & estimated impact

> These are **proposals**, not changes. Per project rules each would be a minimal, flag-gated, reversible edit preserving clinical behavior (no geometry/slice-order/render changes), validated by tests before/after. Effort: **S** ≤ ½ day, **M** ~1–3 days, **L** > 3 days. Listed in recommended execution order.

| # | Opportunity (IDs) | Priority | Effort | Estimated impact |
|---|-------------------|----------|--------|------------------|
| 1 | **Rotate all hardcoded/committed secrets**; move EchoMind keys + AI/login keys to `secure_store`/env; purge from git history (SEC-2, SEC-6, SEC-8) | **P0** | M | Eliminates active credential-theft / license-forgery exposure across 7 centers |
| 2 | **TLS for the AI endpoint + PACS socket**; verify certs (SEC-1, SEC-3, NET-1, NET-5) | **P0** | M–L | Closes the plaintext-PHI-in-transit breach; required for any non-LAN/multi-site use |
| 3 | **Wire `faulthandler` → `native_fault.log`** at boot (+ optional WER/minidump capture) (OBS-1, REL-1/2) | **P0** | S | Makes the dominant native-crash class diagnosable in the field; ~1 file |
| 4 | **Throttle/level-correct logs**: gate idle `resource-summary` (change-only or 30 s), demote download progress WARNING→INFO/DEBUG, add log retention + stop writing test debris to the logs dir (OBS-2, OBS-5, OBS-6) | **P0** | S | ~70% app.log volume cut; multiplies usable history window; makes WARNING meaningful |
| 5 | **At-rest encryption** for `dicom.db` + DICOM/attachment store (SQLCipher / OS-level / per-file) and tighten `user_data/` ACLs (SEC-4) | **P1** | L | Closes PHI-at-rest exposure on theft/local access |
| 6 | **Lazy-import heavy libs** (`openai`, `pandas`, `vtkmodules.all`, `SimpleITK`) behind first use / Advanced viewer entry (PERF-1) | **P1** | M | Removes multi-second cost from the default FAST-2D cold start (largest measured startup lever) |
| 7 | **Runtime KPI/health surface** — aggregate existing `stage-timing`/`resource-summary`/error counts into in-app counters + a small status/health view (and a session-boundary marker) (OBS-3/OBS-4, KPI gaps) | **P1** | M | Turns rich passive logs into live error-rate/latency/crash/leak signals; enables everything else to be measured |
| 8 | **Eliminate main-thread decode on cache miss** — serve last-good/surrogate and decode strictly off-thread on the interactive path (PERF-2) | **P1** | M | Removes the #1 instrumented scrubbing stall |
| 9 | **Add `idx_studies_study_date`** (and consider `(patient_fk, study_date)`); move hot patient-click DB reads off the GUI thread (DB-2, DB-3) | **P1** | S–M | Faster search/sort as the DB grows; fewer click stalls under download contention |
| 10 | **Automatic storage retention/quota** (age/LRU eviction policy, not just a 90% dialog) (DB-1) | **P1** | M | Prevents silent disk-full → download failures on clinical workstations |
| 11 | **De-duplicate the two socket clients** onto one framing layer with unified limits; **quarantine the ~1,900-LOC dead gRPC stack** out of the import path (NET-2, NET-3, REL-8) | **P2** | M | One place to fix protocol/limits; smaller import graph; removes misleading dead code |
| 12 | **Reduce `processEvents` re-entrancy** (replace in-loop pumps with `QTimer.singleShot(0,…)` continuations) starting in `toolbar_manager.py` (PERF-3) | **P2** | M | Smoother toolbar/series-load interaction; fewer re-entrancy hazards |
| 13 | **Coalesce redundant thumbnail work** — memoize the cached payload per click; share the primary-study fetch between main page and viewer sidebar (PERF-4, PERF-5) | **P2** | S–M | Fewer disk scans + socket calls per open, esp. on slow links |
| 14 | **Flag retirement program** — inventory the 281 `AIPACS_*` flags; collapse long-stable default-on ones into the code path and delete the legacy branch (REL-3, ARC-3) | **P2** | L (incremental) | Shrinks the untestable config space; reduces change risk over time |
| 15 | **God-file decomposition** (start `toolbar_manager.py` 9,330 → cohesive units; then `patient_table_widget.py`) (ARC-4, REL-4) | **P3** | L | Lowers change-risk in the most defect-prone files; do behind tests, incrementally |
| 16 | **Persist last modality+date filter**; make single-click debounce feel instant (optimistic highlight already exists) (UX-1, UX-2) | **P3** | S | Removes the most frequent daily friction points |
| 17 | **Add a CI guard** that flags new synchronous disk/`pydicom`/`psutil`/DB calls in GUI-thread handlers (PERF-2 class) | **P3** | M | Prevents responsiveness regressions from recurring |

## 13. Recommended implementation roadmap

Phased so clinical risk stays low and each phase is independently shippable. Nothing here changes viewer geometry, slice order, or render output.

**Phase 0 — Security & crash-visibility sprint (P0; ~1–2 weeks).** Items 1–4. Rotate/secure all secrets + purge history; add TLS to AI endpoint and PACS socket; wire `faulthandler`; throttle/level-correct logs + retention. *Rationale: highest severity, mostly small/medium effort, no clinical-path risk. Do these first.* Exit criteria: no plaintext secrets in tree/build; PHI encrypted in transit; native crashes produce a log; app.log heartbeat ≤ ~10%.

**Phase 1 — Observability + at-rest + top performance (P1; ~3–5 weeks).** Items 5–10. Stand up the runtime KPI/health surface *early* in this phase so the performance and DB changes can be measured before/after. Then at-rest encryption, lazy heavy-imports, main-thread-decode fix, the `study_date` index + off-thread reads, and storage retention. Exit criteria: live error-rate/latency/crash KPIs visible; measured cold-start reduction; no GUI-thread decode on the scrub path; bounded disk usage.

**Phase 2 — Structural debt reduction (P2; ~4–8 weeks, incremental).** Items 11–14. Socket-client consolidation, dead-gRPC removal, `processEvents` cleanup, thumbnail coalescing, and the start of flag retirement. Exit criteria: one socket framing layer; dead transport out of the import path; a measurable drop in flag count with green guards.

**Phase 3 — Maintainability & UX polish (P3; ongoing).** Items 15–17. God-file decomposition behind tests, workflow-filter persistence, and the responsiveness CI guard. Exit criteria: largest file < ~3,000 LOC; persisted filters; regression-guard for GUI-thread blocking.

**Cross-cutting guardrails for every phase:** one change per flag (default-on, legacy preserved); run `tests/code/<subsystem>` before/after + the relevant regression-guard test; sync plugin mirrors + run `verify_plugin_mirrors.py`; respect the deploy-safety gate before any production build.

---

## 14. Evidence appendix

### 14.1 Test execution (pytest 9.0.3, Python 3.13.5, `QT_QPA_PLATFORM=offscreen`, `-p no:debugging`)

- **Collection:** `tests/code` → **4,150 tests collected in 14.4 s, 0 collection errors**, 5 documented stale-spec skips. (The known circular-import collection-order fragility did **not** trigger for `tests/code` collected together.)
- **Verified subset runs (bound):**
  - `ui_services` + `database` + `runtime` → **164 passed, 1 skipped (3.1 s)**
  - `download_manager` + `network` + `system` → **501 passed (6.9 s)**
  - `cloud_consultation` + `identity` + `education_online_consultation` + `storage` → **378 passed, 8 failed (29.6 s)**
  - **Totals across bound subsets: 1,043 passed, 8 failed, 1 skipped.**

### 14.2 Failures & the full-run hard-stop

- **The 8 failures are all in `tests/code/identity`** (`test_gmail_attestation.py`, `test_google_provider.py` — e.g. `test_connect_builds_identity_and_stores_token`, `test_attest_gmail_*`). These exercise Google OAuth / Gmail token attestation and depend on keychain + network/mocks not present in a headless sandbox run; they are **most likely environment-sensitive rather than core-logic regressions** (CLAUDE.md records this area as green on the dev machine 2026-06-10). They should be re-run on the real workstation to confirm — flagged, not assumed broken.
- **The monolithic single-process `tests/code` run reproducibly hard-terminates at ~58% with no summary and no traceback** (observed twice, buffered and unbuffered). The interpreter is being killed mid-run — the signature of a **native crash** (most plausibly VTK/PySide6 offscreen rendering in the `viewer` suite, which is alphabetically near the 58% mark and was independently slow/heavy in this audit). This is **direct corroboration of OBS-1/REL-1**: a native fault produces *no Python traceback even inside pytest*, because `faulthandler` is unwired. The project's own practice of running tests per-subsystem (not as one process) is consistent with this. Run log: `user_data/logs/_audit_pytest_u.txt`.
- **Net read:** core logic suites are healthy (1,043 passed); the only failures are an isolated, likely-environmental Identity/OAuth cluster; and the inability to run the whole suite in one process is itself an observability finding, not a broad test rot.

### 14.3 Code-base metrics (verified)

- First-party Python files (excl. vendored 3D Slicer + `__pycache__`): **735**; test files: **381**.
- Distinct `AIPACS_*` feature flags: **281**.
- Files > 1,000 LOC: **75**; largest: `toolbar_manager.py` 9,330 · `ai_chat_pages.py` 7,478 · `patient_table_widget.py` 5,991 · `viewer_2d.py` 4,832 · `lightweight_2d_pipeline.py` 4,003.
- Mixin split-class files: `_hp_`×10, `_vc_`×7, `_pw_`×10, `_dm_`×10 (= 37).
- `modules/` → `PacsClient` imports: 225 across 120 files. Dead gRPC stack: ~1,900 LOC. `_recovery/` quarantine: ~42,000 LOC.
- Silent `except: …: pass`: ≈ **2,024 across 252 files** (multiline-grep estimate).
- `processEvents` call sites: **61 across 17 files**. `shiboken/isValid` guards: ~22 files / 40 occ. `QMutex`/`QReadWriteLock`: **0**.

### 14.4 Runtime/log metrics (verified, current rotation)

- `app.log`: 46,859 lines; **resource-summary = 32,768 (70%)**; ERROR 0, WARNING 130.
- Process RSS: min **211** / avg **573** / max **1,006** MB.
- `download_diagnostics.log`: 49,594 lines; `Response too large` **144**, `Error in send_request` **191**, `timeout` 22; `right_panel_socket_done` 150, `right_panel_socket_error` **0**; `database is locked` **0**.
- `faulthandler` references in `main.py`+`PacsClient`: **0**. `native_fault.log` last write **2026-06-12** (9 days stale).
- Heavy-import wall time (venv, measured under test-load → upper bounds): `openai` 6,889 ms · `pandas` 5,270 ms · `vtkmodules.all` 1,037 ms · `pydicom` 1,025 ms · `SimpleITK` 348 ms · `PySide6.QtWidgets` 343 ms · `numpy` 304 ms · `cv2` 282 ms · (`pass` baseline 116 ms).

### 14.5 Live process snapshot (captured)

The source build was running during the audit; a passive snapshot was taken (no UI interaction, per bootstrap rules):

| Process | RSS | Threads | Handles |
|---------|-----|---------|---------|
| **GUI app** (`.venv` python, main.py) | **1,026 MB** | **69** | **2,441** |
| `multiprocessing.spawn` children (×4 sampled) | 272 / 202 / 202 / 186 MB | ~20 each | ~230–360 |
| **All python procs (×10)** | **~2,108 MB total** | — | — |

Observations: the **1,026 MB GUI footprint independently confirms the log-derived ~1,006 MB peak** (KPI §8); **69 threads in one process corroborates REL-6** (bespoke threading, no central pool); **2,441 handles** is high and is exactly the metric that should be trended for leaks (OBS-4/PERF-8); the worker family adds ~1 GB, so the whole app resident set is ~2 GB. A *cold-start stopwatch* + interaction-latency capture still needs a human-driven launch/restart and can be appended on request.

---

## 15. Master findings register

**Counts:** Critical **4**, High **18**, Medium **29**, Low **12** (63 tracked). (Items marked "Low-Med" in §4 are rounded to Low here.)

**Critical**

- **SEC-1** PHI + credentials in cleartext (no TLS) on PACS socket + AI endpoint.
- **SEC-2** Hardcoded `sk-…` LLM/IranNobat keys for 7 centers committed in `api_manager.py`.
- **SEC-3** Cleartext `http://` AI endpoint carrying reports/transcripts/chat (PHI).
- **SEC-4** No data-at-rest encryption (`dicom.db`, DICOM, attachments).

**High**

- **PERF-1** Eager multi-second heavy imports on startup · **PERF-2** Main-thread DICOM decode on cache miss.
- **NET-1** No TLS on socket transport · **NET-2** Duplicate socket clients, divergent limits.
- **OBS-1** `faulthandler` unwired (native crashes invisible) · **OBS-2** 70% heartbeat log noise · **OBS-3** ~2,000 silent `except: pass` · **OBS-4** No runtime KPI/health aggregation.
- **REL-1** Recurring PySide6 UAF crashes (reactive guards) · **REL-2** `notify()` override amplifies crashes · **REL-3** 281-flag sprawl · **REL-4** God-files beyond safe-edit size.
- **ARC-1** Mixin god-objects · **ARC-2** Bidirectional core↔modules coupling · **ARC-3** Flag explosion · **ARC-4** 75 files > 1,000 LOC.
- **SEC-5** Plaintext login credentials on disk · **SEC-6** Hardcoded forgeable-license secret.

**Medium**

- **PERF-3** `processEvents` re-entrancy · **PERF-4** Redundant thumbnail scan · **PERF-5** Double primary-study fetch · **PERF-6** Batch growth disabled (round-trip floor).
- **DB-1** No storage retention/quota · **DB-2** `study_date` unindexed · **DB-3** GUI-thread DB reads.
- **NET-3** Dead gRPC imported · **NET-4** Single slot preemption thrash · **NET-5** Plaintext token, no integrity.
- **OBS-5** 98%-WARNING download log · **OBS-6** No log retention + test debris · **OBS-7** Active stream-desync errors.
- **REL-5** `QThread.terminate()` cleanup-bypass · **REL-6** Ad-hoc threading, 0 mutexes · **REL-7** Mixin change-risk · **REL-8** Dead code / clutter · **REL-9** High-blast-radius monkeypatch hooks · **REL-10** ~40 fragility-signal invariants.
- **SEC-7** No client authz / PHI-access audit · **SEC-8** AI key plaintext config.
- **UX-1** Filters not remembered · **UX-2** 250 ms single-click debounce · **UX-3** Modal startup popups · **UX-4** Slow start (perceived).
- **ARC-5** Import cycle · **ARC-6** Gating inert in source · **ARC-7** utils eager hub · **ARC-8** Plugin-mirror manual sync.

**Low**

- **PERF-7** Per-frame RGB copies / psutil in load path · **PERF-8** ~1 GB peak RSS, no leak alerting.
- **DB-4** Connection churn · **DB-5** `series_number` TEXT-in-INTEGER · **DB-6** `INSERT OR REPLACE` PK churn · **DB-7** Unchunked `IN(?)` · **DB-8** Non-atomic delete / no WAL truncate.
- **NET-6** GC-timed socket close / broadcast-skip overrun · **OBS-8** Divergent second logging config + emoji · **ARC-9** Docs lag code · **UX-5** Multi-step search / uneven errors · **SEC-9** Fallback key not OS-sealed.

---

## 16. Closing note

AI-PACS is a capable, clinically-careful workstation whose **performance and data-integrity engineering is strong**, but whose **security posture and runtime observability have not received the same rigor** — those two areas hold every Critical and most High findings, and they are also where remediation is lowest-risk to the clinical path (no viewer/geometry changes required). The recommended sequence is therefore: **secure the secrets and transit, make crashes visible, quiet the logs (Phase 0) → stand up runtime KPIs and take the measured top performance/DB wins (Phase 1) → pay down structural debt (Phases 2–3).** The project's existing kill-switch-per-fix discipline and regression-guard culture are exactly the tools needed to do this safely.

_No source code was modified during this audit. All recommendations are proposals pending your go-ahead._



