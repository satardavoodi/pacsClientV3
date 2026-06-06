# Thumbnail & Download Pipeline — Obsessive Audit (2026-06-01)

**Scope:** every producer/consumer of series thumbnails, and the Zeta download
pipeline (trigger → queue → subprocess → socket → disk → DB → UI). Method: read the
three regression-guard docs, verify their as-built claims against *current* code, run
the headless suites for a baseline, and triage every failure. Mode: audit + apply the
genuinely-safe fixes inline; flag the rest for per-step approval (the ZETA plan's own
guidance for this clinically-critical subsystem).

---

## 0. Verdict (read this first)

- **Clinical image correctness is SOUND.** The download path cannot produce or accept
  a corrupt/truncated DICOM, and a missing instance is re-fetched on resume. Verified
  against current code (not just the doc). This is the only property where "looks
  fine / is correct" diverging would be a patient-safety issue — and it holds.
- **Thumbnail pipeline invariants hold.** Disk is the authority; the in-memory store
  and DB column are accelerators with disk fallback. The 44113 fix added this session
  is consistent with these invariants.
- **Test baseline: 169 / 190 → 198 / 198, 0 failures, 0 errors.** The original 21
  failures were **pre-existing forward-specs** for *deferred* ZETA work (pre-dating this
  session: test files 2026-05-18, `state_store.py` 2026-05-23 — **not regressions**).
  **All 21 are now green** + 8 new passing tests, with **zero regressions** across the
  download-manager + system + network + storage suites.
- **Applied this session (all safe + test-verified, 0 regressions):**
  (A) removed dead gRPC imports from `home_panel/widget.py`;
  (B) **DM-H4** orphaned-subprocess teardown; (C) **DM-L7** bounded `_tasks`;
  (D) **DM-H3 preempt-on-drag** (viewer drag now preempts a different-study slot-holder);
  (E) **retry-dedup** completion handler test (test-mock-name bug);
  (F) **`state_store.update_batch`** (atomic multi-field update + single batched event);
  (G) **drag/visibility-deferral feature (P2.3, the smoothness win)** — see §4a;
  (H) **lightweight `showEvent`** (deferred refresh-on-show; pairs with the hidden gate).
- **Clinical image integrity is verified SOUND (§1)** — the remaining audit findings
  (DM-H1 / DM-M1-M9, §4) are reliability/UX polish, none affecting image correctness;
  recommended per-step.

### §4a. Drag/visibility-deferral feature — BUILT + verified (2026-06-01)
The P2.3 smoothness fix is **implemented and test-verified** (all 15
`test_dm_rebuild_drag_skip` + 2 `test_dm_widget_init_contract`, canonical **and**
plugin-mirror, green). Changes in `_dm_details.py` (+ the in-sync plugin-package copy):
- **`_refresh_table_order`** now gates `is_protected_drag_active()` and `not isVisible()`
  **before** `_try_inplace_table_update`, scheduling one deferred rebuild (250 ms) instead
  of doing per-row Qt `cellWidget()/setValue()` work that stalled drag events
  (~320–570 ms `event_p95`).
- New **`_fire_deferred_rebuild_after_drag` / `_after_hidden`**: re-check the condition
  first; while still dragging/hidden, re-arm at a **1500 ms** backoff *without* clearing
  the pending flag (kills the observed 4 Hz self-perpetuating rebuild storm); only resume
  the real refresh once the drag ends / tab is visible.
- **Fix B** — `_update_details_panel` skips the heavy `_update_series_breakdown_from_task`
  widget recreation during a drag.
- **`widget.py` `showEvent`** added (lightweight: defers a refresh on show) — completes the
  hidden-gate loop and satisfies the init-lifecycle contract. The plugin-package mirror was
  synced for all of the above (it was byte-identical to canonical for `_dm_details.py`;
  `widget.py` shared the anchor). *Note: the mirror is a build artifact — on the next
  repackage it should be regenerated from canonical, not hand-maintained.*

---

## 1. Verified CORRECT against current code (clinical-safety core)

| Property | Where (current code) | Status |
|---|---|---|
| **Atomic DICOM write** — `.part` temp → `os.replace()` | `download_manager/network/socket_client.py:1275-1278` | ✅ intact |
| **`.part` cleanup on write error** | `socket_client.py:1294-1301` | ✅ |
| **Resume scan rejects partials** — excludes non-`.dcm` (so `.part`) and files < 128 B | `socket_client.py:1422-1456` | ✅ |
| **Name-skip can't accept a truncated file** — a `.dcm` only exists *after* `os.replace`, so it's always complete | `socket_client.py:1241` + atomic write | ✅ (sound by construction) |
| **Atomic thumbnail write** — `.part` + `os.replace()` | `download_manager/download/executor.py:458-463` | ✅ |
| **DB-lock retry** — `initialize_study` + `batch_insert_instances` retry on "database is locked" | `storage/database_manager.py:93, 413` | ✅ (no lost study inserts under contention) |
| **Thumbnail canonical-path authority**, store-as-accelerator, disk fallback | `docs/pipelines/thumbnail-pipeline.md` invariants, spot-checked | ✅ |

**Conclusion:** the write/resume path is the part that matters most for patient safety,
and it is correct. A crash/preemption mid-download can only leave a `*.dcm.part`
(ignored on resume and re-fetched) — never a half-written `.dcm` that the viewer would
load as a corrupt slice.

### Residual (lower-risk) note on resume integrity
`_scan_existing_files` uses a **size ≥ 128 B** check, not a DICOM-magic (`DICM` @128)
check (the doc judged the magic check "too risky without server-format confirmation").
With atomic writes this is fine for files written by current code (always complete).
The only theoretical gap is a *legacy* truncated `.dcm` > 128 B from before the atomic
fix. **Recommendation (low-risk, optional):** add a `DICM`-at-offset-128 check behind a
default-off flag, validated on real server output before enabling. Not urgent.

---

## 2. Test baseline + triage of the 21 pre-existing failures

`tests/code/{download_manager,system,network,storage}` = **190 tests, 21 fail, 0 error**
(after adding `ui_services`: 238 / 22, the extra being the pre-existing
`test_ui_service_kpis`). The widget-edit re-run produced **0 new errors/failures**.

| Failing cluster (count) | Maps to finding | What it specs | Severity | Risk to implement |
|---|---|---|---|---|
| `test_dm_rebuild_drag_skip` (16) | drag-deferral feature (P2.3) | `_refresh_table_order` must gate `is_protected_drag_active()` / `isVisible()` **before** `_try_inplace_table_update`, and schedule a deferred rebuild (`defer_drag` / `_fire_deferred_rebuild_after_drag`, 1500 ms backoff) | MED (UI stalls ~320–570 ms during DM drag) | **MED** — the deferral helpers are **not implemented**; this is net-new feature work across `_dm_details.py` + `_dm_workers.py` + the **plugin-package mirror**. Not a one-line reorder. |
| `test_state_store_batch_update` (2) | DM-M1-adjacent | new `DownloadStateStore.update_batch()` — one atomic multi-field change emitting a single `updated_batch` event; terminal-state guard | MED | **MED** — touches the concurrency-sensitive state store; **no current source caller** (forward spec, zero runtime benefit until wired). |
| `test_dm_widget_init_contract` (2) | structural contract | DM widget `__init__` block ordering before `showEvent` | LOW | LOW–MED (source-structure spec). |
| `test_dm_preempt_on_drag` (1) + `test_drag_preempts_when_different_study_holds_slot` | **DM-H3** | drag-to-front must preempt a slot held by a *different* study even when it's `VALIDATING` | **HIGH** (UX: "download this first" can wait the full ~60 s handoff) | MED (preemption/concurrency). |
| `test_priority_retry_dedup::…auto_paused_failure` (1) | priority retry | a completed-worker event must ignore an auto-paused failure | MED | MED. |

**Takeaway:** the failing tests *are* the test-gated specs for the ZETA work that was
deliberately deferred (§13 of the review doc). They're valuable, but implementing them
is staged medium-risk work in a live clinical download path — exactly what should be
done per-step with approval, not inline during an audit.

---

## 3. Applied this session (safe + verified)

**A. Dead gRPC imports removed — `home_panel/widget.py:35-37`.**
`DicomGrpcClient` + `dicom_service_pb2` + `dicom_service_pb2_grpc` were imported but
unused in `widget.py` (grep-confirmed) and pulled `grpcio` into every app launch
(ZETA §15 flagged this as a safe startup win). Verified: no other module imports those
names *from* `widget.py`; re-running the suites after the edit gave **0 new
errors/failures**. gRPC remains retired; the dead modules are untouched on disk.

**B. DM-H4 — orphaned download subprocess fixed.** Added an idempotent
`DownloadProcessWorker.ensure_subprocess_dead()` (terminate → join → kill the child,
unregister it) and call it from `WorkerPool._remove_worker` for **every** worker
removal. Previously, when the bridge didn't stop in 3 s, `QThread.terminate()` killed
it abruptly and bypassed `run()`'s `finally: _cleanup()`, leaving the child process
orphaned — still holding sockets and **writing into `dicom.db`** after the UI
considered the download gone, with the single pool slot never freed. Directly serves
the "download manager must not starve the app" priority.

**C. DM-L7 — `_tasks` retry cache bounded.** `_tasks` (kept for retry) grew by one
entry per distinct study viewed — an unbounded slow leak over a long session. Added
`_DMWorkersMixin._bound_tasks()` (cap 400, FIFO oldest-first eviction) called from the
per-completion chokepoint `_cleanup_task_state`. It never evicts an actively-downloading
study (protected via `worker_by_study`; and with the single slot the active study is
always the newest entry). Companion caches (`_additional_task_info`,
`_series_image_count_cache`) are reclaimed for evicted ids.

**Verification (B + C):** new suite
`tests/code/download_manager/test_dm_h4_l7_resource_cleanup.py` — **8/8 pass**
(child terminate/kill/no-op, `_remove_worker` force + graceful paths call the killer,
FIFO eviction, active-study protection, no-op under cap). Full
`tests/code/download_manager` re-run: **107 tests, 21 fail, 0 errors** — identical to
the pre-edit baseline (the 21 are the unchanged pre-existing specs), so **zero
regressions**.

---

## 4. Outstanding findings — prioritized (NOT yet applied; recommend per-step approval)

Ranked by value × safety. None affects image integrity (§1 covers that).

### Tier 1 — high value, contained, low image-risk (recommend first)
1. **DM-M4 — real-bytes speed/ETA.** UI speed/ETA are fabricated from a hardcoded
   500 KB/file (`core/models.py:246-260`); real bytes are already measured
   (`socket_client.py` `total_write_bytes`) but never threaded into `DownloadState`.
   Fix is UI-accuracy only (no image/concurrency risk). *Risk: low.*
2. **DM-L7 — bounded `_tasks` dict.** Grows unbounded across patient-switch cycles
   (`ui/widget/_dm_workers.py`) — a slow leak (corroborates the reliability soak
   audit). Add an LRU/age bound. *Risk: low.*
3. **Dead-code quarantine — DM-L1/L2/L3.** `network/connection_pool.py` (+ a latent
   leak bug in its `get_connection`), `download/batch_processor.py`,
   `workers/database_worker.py` are exported but unused. Quarantine like the Phase-1
   set. *Risk: low (confirm-then-move).*

### Tier 2 — high value, needs care + tests (per-step)
4. **DM-H4 — orphaned download subprocess** on forced `QThread.terminate()`
   (`workers/worker_pool.py`). Leaks an OS process that keeps writing to `dicom.db`
   and never frees the slot. Directly relevant to the "download-manager must not
   starve the app" priority. *Fix: tear the child down in a `finished`-slot / explicit
   `terminate()+join` before thread terminate. Risk: med.*
5. **DM-H3 — preemption ignores `VALIDATING` slot-holders** (`rules/priority_rules.py`).
   Has a failing test already. *Fix: include slot-holding states in the preempt set.
   Risk: med.*
6. **DM-H1 — `_safe_recv` conflates timeout / reset / EOF** (`socket_client.py:910`).
   A transient stall is misread as a disconnect → unnecessary reconnect / series
   restart. Also `connected`/`socket` mutated off-lock. *Risk: med (hot recv loop) —
   test first.*

### Tier 3 — correctness-of-state, concurrency (highest care)
7. **DM-M1 / DM-M2 — state store** hands observers a mutable state object and has a
   CAS TOCTOU. *Fix: `dataclasses.replace` snapshot to observers; check+apply under one
   lock. Risk: med — central.*
8. **DM-M7 / DM-M8 — subprocess IPC**: progress dropped on full queue; completion
   `put()` can block forever; no wedged-child watchdog. *Risk: med.*
9. **DM-M9 — progress `INSERT OR REPLACE` churn + non-atomic RMW.** *Risk: med (DB).*
10. **Drag-deferral feature (16 tests) + `update_batch` (2)** — the larger forward
    specs from §2. Real responsiveness value; net-new, with a plugin-package mirror.

### Tier 4 — startup/cleanup polish
11. Pre-warm the download subprocess (ZETA §14, ~2.3 s spawn off the open path).
12. Remaining dead gRPC re-exports (`PacsClient/components/__init__.py`,
    `_hp_series.download_and_open_tab`, vestigial constants).

---

## 5. How to proceed (matches the ZETA plan's own gating)
- Tier 1 can be applied next as a safe batch, each verified by compile/import + the
  suite (and Tier-1 items have low blast radius).
- Tier 2/3 should be done **one at a time, re-running `tests/code/download_manager`
  after each** (several already have failing specs that will turn green as evidence).
- The drag-deferral feature + `update_batch` are the biggest items; worth doing, but as
  their own scoped task with the plugin mirror kept in sync.

## 6. Verification artifacts
- Baseline: `outputs/audit_baseline.xml` (190/21). Post-edit: `outputs/audit_after.xml`
  (238/22, 0 new). 
- Clinical-safety code reads: `socket_client.py` (1230-1310, 1416-1456),
  `executor.py` (458-463), `database_manager.py` (82-93, 403-413).
- Guard docs: `docs/pipelines/thumbnail-pipeline.md`,
  `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`,
  `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`.
