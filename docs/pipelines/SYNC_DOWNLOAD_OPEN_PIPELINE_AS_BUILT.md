# AI-PACS — Sync / Download / Open Pipeline (Clean As-Built, 2026-06-15)

Authoritative, straightforward reference for the study **download → sync → open →
preview → display** lifecycle after the 2026-06-15 consolidation. Background and the
phased plan are in `docs/reports/SYNC_DOWNLOAD_LIFECYCLE_REVIEW_2026-06-15.md`; this
file is the as-built "how it works now + every knob + every issue handled".

Design principle: **disk is the source of truth; the server is consulted for
freshness; the DB and memory are caches.** One read-model (`sync_manifest`) answers
"what is local vs the server", and every recovery path is idempotent, off the UI
thread, de-duplicated, and flag-gated with a safe default.

---

## 1. The single state read-model — `modules/storage/sync_manifest.py`

`evaluate_sync(study_uid, server_series=...)` is the **one** place that compares
local (DB hint + disk truth) against the server and returns a pure decision — no
writes, no downloads:

- `state` ∈ `NotDownloaded | ThumbnailOnly | PartiallyDownloaded | Downloaded | Stale`
- `missing_series`, `partial_series`, `missing_thumbnails`, `up_to_date`

It is now the shared basis for the open download decision, the disk-aware resync,
and (by the same logic) R17. Legacy equivalents (`check_study_complete`,
`get_study_download_status`, `_detect_study_growth`, `validation_rules` disk check)
remain as tested as-built implementations of the same disk-first idea; new work uses
the manifest.

**Cheap pre-gate — server `contentVersion`** (`modules/storage/content_version_store.py`).
The server keeps a monotonic per-study `contentVersion` and `$inc`s it on *any*
content change, returning it on `GetStudyThumbnails` (see
`STUDY_STORAGE_AND_VERSIONING`). The client persists, per study, the version at
which the local copy was **last confirmed complete on disk**. The resync compares
the freshly-fetched server version against that record: **equal ⇒ nothing changed
⇒ skip the DB query and the disk scan entirely** — the cheapest possible gate. Only
a higher/unknown version (or a server that omits the field) falls through to the
manifest. The version is stamped *only* on the confirmed-complete branch (never on
mere enqueue), and is **forgotten when local data is cleared** (so a cleared study
re-syncs). Disk remains the source of truth; `contentVersion` only decides *whether
it is worth looking*.

---

## 2. Lifecycle — what happens, in order

**Single-click (main page)** — debounced ≥ doubleClickInterval; loads thumbnails
only (right-panel cache gate, keyed by server series count); **no full download**.
A throttled (5-min), off-thread, **disk-aware** resync runs in the background.

**Double-click open** — tab created immediately (UI never blocks); then, off the UI
thread:
1. Fresh server series-info is fetched (the lightweight metadata check — every open).
2. **Download decision** (`_hp_patient_open`): feed the fresh server list to
   `evaluate_sync`. Nothing missing → **skip** the re-download (`download_skipped_complete`);
   some missing → queue **only the missing/partial** series (`download_only_missing`),
   never the whole study; before queueing, a stale terminal DM state is reset
   (`download_reset_stale_complete`) so R17 can't block the new series.
3. First series loads from disk via the **adaptive header scan** (parallel on a
   slow/I-O-bound disk, sequential on a fast SSD).
4. The background resync confirms completeness and pulls anything still missing.

**Re-open of an already-open patient** — instead of only focusing the tab, fire a
**forced** server check + refresh the open viewer's series sidebar
(`existing_tab_series_refreshed`) so series added since the first open show and download.

**Resync (server-grew detection)** — off-thread, throttled, **contentVersion- then
disk-aware**: first the cheap `contentVersion` gate (unchanged ⇒ skip with no DB/disk
work, trace `result='current_cv'`); otherwise a study grew (new DB series) OR has
files missing on disk relative to the server → enqueue only the missing series; resets
a stale terminal DM state first; stamps the synced `contentVersion` once disk is
confirmed complete. A manual "Refresh / Sync from server" (force) bypasses both the
throttle and the contentVersion gate.

**Drag-drop** — always reloads the dropped series into the target viewport
(`force_reload`); a partial/downloading series of the opened study is fed by the
progressive-grow pipeline as files arrive; de-dup prevents duplicate tasks.

**Download de-dup (R17)** — one state per study; reopening a downloading study
resumes the in-flight task, never spawns a duplicate; a `COMPLETED` study whose files
are actually missing on disk is allowed to resume (disk-aware), a genuinely-complete
one is skipped.

---

## 3. Every knob (env flags — all default to the safe/correct behaviour)

| Flag | Default | Effect |
|---|---|---|
| `AIPACS_HEADER_SCAN_PARALLEL` | `auto` | Adaptive disk header scan: sequential on fast SSD, parallel on slow/I-O-bound disk. `0`=legacy sequential, `1`=force parallel. (FIX-009) |
| `AIPACS_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE` | `1` (on) | Skip the redundant re-download when the server confirms the study is complete; otherwise queue only the missing series. `0`=always download full. (S1) |
| `AIPACS_OPEN_RESET_STALE_COMPLETE` | `1` (on) | On open AND resync, clear a stale terminal (`COMPLETED`/`CANCELLED`) DM state when the server shows missing series, so the new series download. (FIX-010) |
| `AIPACS_OPEN_REFRESH_ALREADY_OPEN` | `1` (on) | Re-opening an open tab fires a forced server check + refreshes the open viewer's series sidebar. (FIX-011) |
| `AIPACS_RESYNC_ON_REOPEN` | `1` (on) | The background resync-on-reopen itself (pre-existing). |
| `AIPACS_RESYNC_DISK_AWARE` | `1` (on) | The resync treats disk-missing/partial series (not just new DB rows) as a reason to sync. (FIX-011 follow-up) |
| `AIPACS_R17_DISK_AWARE_COMPLETED` | `1` (on) | R17a checks disk before blocking a `COMPLETED` study, so a grown/cleared study can resume at the de-dup rule. (FIX-014) |
| `AIPACS_CONTENT_VERSION_SYNC` | `1` (on) | Resync **fast-gate**: when the server's monotonic per-study `contentVersion` equals the version we last confirmed complete, skip the DB query + disk manifest scan entirely. Only a changed/unknown version falls through to the disk-aware check. **Inert when the server omits the field.** Never short-circuits a forced (manual) refresh. (FIX-015) |

A modern/healthy server + fast SSD experiences **no behaviour change** from any of
these — they are inert (or identical to legacy) on the happy path and only act on the
specific failure/degraded condition. Each is independently revertible.

---

## 4. Issues handled (this engagement)

| Issue (patient / report) | Root cause | Fix | Status |
|---|---|---|---|
| Slow open ~44–100s (46370) | server-opened study re-reads all headers sequentially on the UI thread (slow disk) | adaptive parallel header scan | **FIX-009 — live-confirmed 1.9s** |
| Redundant re-download of a complete study (46370) | open always started a CRITICAL download | skip when server-confirmed complete | **S1 — live-confirmed** |
| Grown study "all of them start downloading" (46640) | open queued the whole study | download only the missing series | **download_only_missing** |
| New server series never download (46640) | stale `COMPLETED` DM state blocked R17 | reset stale terminal state (open + resync) | **FIX-010** |
| Reopen doesn't show/download new series (46533) | already-open tab just focused, no refresh | forced resync + viewer sidebar refresh on reopen | **FIX-011** |
| Resync misses files-missing studies (46533) | resync compared DB rows, not files | disk-aware resync (manifest) | **FIX-011 follow-up** |
| Stale `COMPLETED` blocks at the de-dup rule | R17a had no disk check (R17b did) | R17a disk-aware (resume if files missing) | **FIX-014** |
| Crash after all-modality search (46692) | thumbnail priority-flash `QPropertyAnimation` GC'd mid-flash | parent + keep reference | **FIX-012** |
| Tab-hover / overlay crashes (pc2) | bare-local `QPropertyAnimation` GC'd mid-animation | parent + keep reference / liveness guard | **FIX-007 / FIX-008** |
| Main-page thumbnail stale vs count (46692) | right-panel gate used stale stashed count within resync throttle | self-resolves on reopen (FIX-011); deliberate throttle | **explained** |
| `GetPatientList` fails on MongoDB < 5.2 (client PC) | server aggregation uses `$sortArray` | client graceful degradation (compatibility/simple/client-sort) | **FIX-013** (server fix is the root) |
| Storage clear left DB/thumbnails/badge stale | clear didn't span all layers | transactional clear + validator/repair + badge refresh | **FIX-003/004/005/006** |
| Resync re-scanned disk every reselect even when nothing changed | no cheap server-side staleness signal was used | server `contentVersion` fast-gate: skip DB+disk scan when version unchanged, forget on clear | **FIX-015** |

All recorded in `docs/technical-debt/suspected-issues.json` (FIX-003 … FIX-014, S1,
REVIEW-SYNC-001).

---

## 5. Validation checklist (review §7) — current status

| # | Check | Status |
|---|---|---|
| 1 | Not-downloaded single-click loads thumbnails fast | ✔ |
| 2 | Not-downloaded double-click opens + downloads | ✔ |
| 3 | Downloading study → no duplicate download | ✔ (R17 + FIX-014) |
| 4 | Downloaded study opens fast + still checks server | ✔ (FIX-009 + S1) |
| 5 | New server series detected + downloaded | ✔ (resync + download_only_missing + FIX-010/014) |
| 6 | Cleared study no longer shows downloaded | ✔ (disk-first + FIX-004/005) |
| 7 | Drag-drop local / partial / remote | ✔ local/partial; remote-never-downloaded = S4 (staged) |
| 8 | UI responsive during sync/download | ✔ orchestration; series load fast (FIX-009), full off-thread = S3 (staged) |
| 9 | DB / files / cache / UI consistent | ✔ |
| 10 | No duplicate series / files | ✔ |

---

## 6. Remaining enhancements (NOT unresolved issues — need live verification)

The functional pipeline is complete; these two are performance/UX enhancements that
touch the clinical render path / clinical-adjacent UI and must be golden/live-verified
on the running app before shipping, so they are staged rather than changed blind:

- **S3 — full off-thread / preview-first first-series load.** GOAL (fast open) is
  **largely met** by FIX-009 (44s→1.9s). The remaining win is keeping the UI thread
  fully free during the ~1–2s scan: move `_build_metadata_headers_only` to a worker and
  paint the first slice after a few headers, render staying on the main thread. Golden-
  image gated (slice order/geometry must stay byte-identical). Repair preview-first
  (currently silently no-ops).
- **S5 — progressive status surface.** Expose the manifest `state`
  (Checking/Downloading/Syncing/Ready/Stale/Failed) in the home table status cell.
  Low clinical risk (status indicator, not the viewer) but a UI-render change; wire the
  DM/resync signals → the existing status cell additively, flag-gated, and live-verify.

Optional, only if a real PACS needs it: **S6 — SOP-level sync** (opt-in, heavier query).
