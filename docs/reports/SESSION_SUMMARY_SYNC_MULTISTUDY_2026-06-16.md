# AI-PACS — Session Summary: Synchronization, Multi-Study, and Fixes (2026-06-15 → 16)

Authoritative record of this engagement. Emphasis, in order: **(1) live-server
synchronization**, **(2) the multi-study patient problems**, **(3) every other fix**.
Cross-references: `docs/architecture/SYNC_MODE_SEPARATION.md`,
`docs/pipelines/SYNC_DOWNLOAD_OPEN_PIPELINE_AS_BUILT.md`,
`docs/technical-debt/suspected-issues.json` (FIX-009 … FIX-021, OBS-009…012).

Guiding principle throughout: **no regression to clinically-verified output** (image
geometry, slice order, orientation, rendering) and **no regression to the multi-study
or synchronization behaviour the team worked hard to stabilise**. Every change is
flag-gated where it touches behaviour, default-safe, test-guarded, and plugin-mirror
verified.

---

## 1. Synchronization (the core of this session)

### 1.1 What the server actually provides — `contentVersion`

Per the server spec `STUDY_STORAGE_AND_VERSIONING`: each Study carries a **monotonic
`contentVersion`** counter that the server `$inc`s on **any** content change — not just
new instances, but also **attachment upload, voice upload/delete, capture add/delete,
and document (DOC) add/delete**. It is returned on `GetStudyThumbnails`
(gRPC `content_version:int64` / socket `content_version`). The client rule (§7) is:

> re-download **only** when `server.content_version > local.content_version`; after the
> files are saved, set `local.content_version = server.content_version`.

> Note: a **reportStatus** change alone does NOT bump `contentVersion` — it is delivered
> by a separate `report_status_changed` socket event, so report-status stays on its own
> path (we did not fold it into contentVersion).

### 1.2 What we implemented — version-first, disk-aware, non-blocking (FIX-015)

| Piece | File | Role |
|---|---|---|
| **Capture** | `modules/network/socket_client.py` (`get_study_thumbnails`), `series_utils.py`, `_hp_study_save.py` (`get_series_info_from_server`) | Surface `content_version` from the thumbnails response into `study_info`. Casing-robust (`content_version`/`contentVersion`); inert if the server omits it. |
| **Local version store** | `modules/storage/content_version_store.py` (new) | Per-study **last-confirmed-complete** version; JSON under `USER_DATA_ROOT`, atomic, fail-open. Forgotten on patient clear. |
| **The gate** | `_hp_series.py::_resync_patient_studies_from_server` | `server_cv <= local_cv` → **cheap-skip** (no DB query, no disk scan). `server_cv > local_cv` (or unknown) → fall to the disk-aware check. Stamp `synced = server_cv` **only** once disk is confirmed complete (never on mere enqueue). |
| **Disk read-model** | `modules/storage/sync_manifest.py` (new) | `evaluate_sync(study_uid, server_series=…)` — disk is the read authority; returns missing/partial series. Download only the delta, never a full re-download; de-dup via the DM resume scan. |

This matches the spec exactly: lightweight version check first, download only what
changed, no duplicate downloads, no full rescan, off the UI thread. Because the gate
keys on the bare `contentVersion`, it catches **every** §4.3 bump (images **and**
attachments / voice / captures / documents). Because the stamp happens **only** when
disk is complete, a study with files missing on disk is never wrongly cheap-skipped — it
re-syncs (46533 case).

### 1.3 Mode separation — Live-Server vs Local/Offline/Import/CD (FIX-021)

The directive: clearly separate workflows where the **server is the source of truth**
(strict version-aware sync) from those that rely only on **local/offline** data (the
live server must never be *required*). Before this, "is this local?" was re-derived
ad-hoc with **different** source-sets at each site — a cross-mode-bug risk.

New single source of truth: **`modules/storage/sync_mode_policy.py`** — `WorkflowMode`
(`LiveServer / LocalDatabase / Import / OfflineServer / CDBurn / Unknown`),
`resolve_workflow_mode(source)`, named predicates, and `log_mode_decision(...)`. The
per-mode contract (full matrix in `docs/architecture/SYNC_MODE_SEPARATION.md`):

| Mode (`SourceOfPatientLoad`) | Source of truth | Auto remote resync? | Server version check? |
|---|---|---|---|
| **LiveServer** (`SERVER`) | Server | Yes — contentVersion delta sync | Yes |
| **LocalDatabase** (`DB`) | Local for **display**; server `contentVersion` governs growth | **Yes** (a DB study is a cached *server* study) — non-blocking, default on | Yes |
| **OfflineServer** (`OFFLINE_CLOUD`) | Offline-cloud package | Yes — **cloud** sync (offline rules) | No (not the live server) |
| **Import** (`IMPORT`) | Provided local files | **No** | No |
| **CDBurn** (action) | Local selected data | **No** | No |
| **Unknown** | — | Yes (permissive — degrades gracefully) | No |

The auto resync now gates on `requires_remote_resync` and logs the mode on skip and run.
A **manual** "Refresh / Sync from server" always runs for any source.

### 1.4 The no-regression corrections (caught this session)

Two synchronization regressions were introduced mid-session and **caught + reverted**:

1. **DB auto-sync was briefly defaulted OFF.** A DB/Local patient is a locally-cached
   *server* study, so its `contentVersion` must be checked to detect server growth.
   Reverted to **ON** (default), `AIPACS_LOCALDB_AUTO_SERVER_SYNC=0` for strict local.
   Verified against the server spec.
2. **`UNKNOWN`-source was briefly skipped.** The resync historically ran for every
   source; an unclassified source must keep resyncing (degrades gracefully). Now only
   the *explicitly-local* `IMPORT` / `CDBurn` are skipped; everything else runs.

Net behaviour change vs. before the session: the auto resync no longer fires for
**Import / CD** sources — those studies are not on the server (no `contentVersion`), so
the call was always a wasteful no-op. **Everything that synced before still syncs.**

---

## 2. Multi-study patients (the hard problem — verified no regression)

The team's long-standing multi-study pain (a patient with >1 study under one Patient ID):
**series/thumbnails not showing**, **freezing**, and **not syncing** when a study grows
server-side. This session's synchronization work was audited specifically to ensure none
of it regressed.

**Showing series & thumbnails — untouched.** The grouped-render path
(`_hp_modules.py::_render_multistudy_grouped` / `_show_grouped_patient_studies`, the
`_vc_load`/`_vc_switch` series-load, the offset-key series index) was **not modified**
this session (verified by `git diff`). The only nearby files of ours are
`thumbnail_manager.py` (a Qt-lifetime animation fix only) and `_hp_patient_open.py`
(download decision + tab refresh, with zero multi-study branches). No regression is
possible in the grouped display.

**Freezing — reduced, not added.** The `contentVersion` gate makes the reselect resync
*cheaper* (it cheap-skips the DB query + disk scan when the version is unchanged) and it
runs fire-and-forget off the UI thread. It removes work from the hot path.

**Not-synced (server growth, "45611") — preserved.** The resync still: iterates **per
study**, version-checks each study's **own** `contentVersion` (never the
patient-aggregate count — the 44534 guard stays intact), runs for DB + SERVER multi-study
patients, enqueues only the missing series, and **re-renders the grouped view with a
server merge** (`_show_grouped_patient_studies(force_server_merge=True)`) so new series
appear without a manual cache wipe. The stamp-only-on-complete rule means a multi-study
study with files missing on disk is never cheap-skipped — it re-downloads (46533).

**Regression caught + fixed during verification:** the new disk-aware check had silently
broken the committed 45611 resync tests (`tests/code/ui_services/test_resync_on_reopen.py`)
— a *test-isolation* problem (the stub models DB counts, not disk files, so the correct
disk-aware check flagged them "missing"), not a production fault. Isolated the disk-aware
check in those growth-detection tests; production is unaffected (real current patients
have their files on disk, and the contentVersion gate cheap-skips before the disk check).

---

## 3. Other fixes this session (by area)

### 3.1 Viewer / open performance & rendering
- **FIX-009 — slow open (46370): 44s → 1.9s.** Adaptive parallel DICOM header scan
  (`image_io.py`): parallel on a slow/I-O-bound disk, sequential on a fast SSD.
  Live-confirmed.
- **FIX-017 — multi-modality window (46370 series 61, CSI spectroscopy).** A
  heterogeneous series (SPECTRUM frames at WC2048/WW4096 + REFERENCEIMAGE frames at
  WC301/WW637) rendered near-black because slice 0's window was kept for the whole
  series. On scroll, when no manual window is set and the slice's own DICOM window
  differs *substantially*, re-apply it (`qt_viewer_bridge.py`). Normal series keep a
  stable window — byte-identical. (The spectra **plot** + CSI grid can't be drawn: the
  server delivered no MR-Spectroscopy objects — only secondary-capture thumbnails — see
  OBS-011.)

### 3.2 Import (Local/CD viewer)
- **FIX-016 — 2nd imported study opened empty (0 series).** A multi-study folder import
  prepared thumbnails only for the *primary* study, so the others opened with an empty
  thumbnail-driven sidebar. Now **every** imported study is prepared (primary first),
  in both the manual and startup import paths.

### 3.3 Download reliability (client-PC logs)
- **FIX-018 — UnicodeDecodeError + broadcast flood.** A strict `json.loads(data.decode(
  'utf-8'))` crashed the whole download on a non-UTF-8 byte (Persian / Latin-1 names) —
  now decodes tolerantly (strict first, then `errors='replace'`), in both the download
  and the patient-list/thumbnail clients. The broadcast-skip cap (`GetSeriesImages`
  "Too many broadcast messages") was raised 10 → 50, env-configurable.
- **FIX-010 / FIX-014 — stale-COMPLETED unblock.** A grown study whose DM state was a
  stale `COMPLETED`/`CANCELLED` was reset (open + resync) and R17a made disk-aware, so
  new server series download.

### 3.4 Stability / crashes
- **FIX-012 — crash after all-modality search (46692).** A bare-local thumbnail
  priority-flash `QPropertyAnimation` was GC'd mid-flash → access violation. Parented +
  referenced.
- **FIX-020 — `QApplication.notify` malformed-dispatch crash.** A rare non-QObject
  receiver made `super().notify` raise `TypeError`, and the override re-raised it →
  crash. Now that specific malformed case returns "unhandled" instead of crashing;
  genuine handler exceptions still propagate (crash capture preserved).

### 3.5 Voice notes
- **FIX-019 — short voice recordings silently saved nothing ("record 2-3 times").** The
  60 ms QTimer was the only thing draining the audio queue into the buffer; on stop the
  timer was stopped *before* draining, so short takes lost all audio and the save was a
  silent no-op. Now the queue is drained before saving, and the path has its first real
  logging.

### 3.6 Server compatibility
- **FIX-013 — `GetPatientList` failed on MongoDB < 5.2 (`$sortArray`).** Client graceful
  degradation (compatibility / simple / client-sort modes), config-toggleable. The root
  cause is server-side; this keeps the client working against older Mongo.

---

## 4. New modules & key files

| New | Purpose |
|---|---|
| `modules/storage/sync_mode_policy.py` | Mode-aware sync policy (single source of truth) |
| `modules/storage/content_version_store.py` | Per-study last-synced contentVersion |
| `modules/storage/sync_manifest.py` | Disk-vs-server read model (`evaluate_sync`) |
| `docs/architecture/SYNC_MODE_SEPARATION.md` | Per-mode contract + validation checklist |
| `docs/pipelines/SYNC_DOWNLOAD_OPEN_PIPELINE_AS_BUILT.md` | The download→sync→open as-built |

Most-touched existing files: `_hp_series.py` (resync + contentVersion + mode gate),
`_hp_study_save.py`, `_hp_patient_open.py`, `_hp_import.py`,
`modules/network/socket_client.py` + `series_utils.py`,
`modules/download_manager/network/socket_client.py`,
`modules/viewer/fast/qt_viewer_bridge.py`, `voice_tool_ui.py`, `image_io.py`, `main.py`.

---

## 5. Behaviour flags (all default to the safe/correct behaviour)

| Flag | Default | Effect |
|---|---|---|
| `AIPACS_CONTENT_VERSION_SYNC` | on | contentVersion fast-gate in the resync |
| `AIPACS_LOCALDB_AUTO_SERVER_SYNC` | **on** | DB/Local patients auto-check server contentVersion (set `0` for strict local-only) |
| `AIPACS_RESYNC_DISK_AWARE` | on | resync also treats disk-missing/partial as a reason to sync |
| `AIPACS_FAST_PER_INSTANCE_WINDOW` | on | per-instance DICOM window on scroll for heterogeneous series |
| `AIPACS_MAX_BROADCAST_RETRIES` | 50 | broadcast-skip cap for `GetSeriesImages` |
| `AIPACS_HEADER_SCAN_PARALLEL` | auto | adaptive parallel header scan |
| `AIPACS_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE` / `AIPACS_OPEN_RESET_STALE_COMPLETE` / `AIPACS_OPEN_REFRESH_ALREADY_OPEN` / `AIPACS_R17_DISK_AWARE_COMPLETED` | on | open/resync sync hardening (FIX-010/011/014, S1) |

---

## 6. Verification status

- **Code-level:** the full touched surface is green — download_manager + ui_services +
  storage + network + system + fast + cd_burner (**795 passed, 1 skipped**), plus the
  viewer drag/stack + per-instance window suites. New guard tests for every fix
  (contentVersion, mode policy, manifest, import-prepare-all, tolerant decode, voice
  drain, notify guard, per-instance window). Plugin mirrors 389/389. JSON registry valid.
- **Live (monitor A, source build, FAST viewer — no VTK):** single-click thumbnails,
  double-click open (S1 `download_skipped_complete`), stacking, drag-drop + reference
  lines, reopen (`existing_tab_series_refreshed`) all verified; logs showed real server
  `content_version` values (50/1/135/274) and the store persisted the synced versions —
  the contentVersion mechanism works end-to-end against the production server.
- **Multi-study:** grouped rendering untouched; resync preserved + re-verified; the one
  test break (disk-aware isolation) fixed; 45611 resync tests green.

### Open / for the team (not regressions)
- **OBS-011** — MR-spectroscopy plot + CSI grid for 46370 series 61 need the actual
  spectroscopy objects, which the server does not deliver (only secondary-capture
  thumbnails). Server-side data question first, then a dedicated spectroscopy module.
- **OBS-012** — a few low-frequency client-log items (a download-subprocess spawn AV; a
  series-path-not-found) flagged for a live repro before any change.
- **Report-status sync** stays on its own `report_status_changed` / GetReportStatus path
  (correctly *not* folded into contentVersion). The frequent `GetReportStatus` timeouts
  are a server-side report-endpoint matter.
