# AI-PACS Viewer Pipeline — Comprehensive Architecture Review (2026-06-25)

**Scope:** the complete end-to-end flow — double-click patient → open tab → metadata →
download → DICOM files → thumbnails → drag series → import → decode → first image →
progressive view → cache → complete → mark fully loaded — with emphasis on **concurrent**
usage (Patient A loading while Patient B is opened/dragged), **duplicate pipelines**, **data
ownership**, and **thread safety**.

**Method:** three independent code audits (execution paths; data/cache ownership;
concurrency/threads/state) cross-checked against the project's own records
(`docs/pipelines/MULTI_PIPELINE_CONCURRENT_ARCHITECTURE.md`, `viewer-pipeline.md`,
`unified-patient-study-pipeline.md`, `thumbnail-pipeline.md`) and the as-built history in
`CLAUDE.md`. Evidence is cited as `file:line`. **No code was changed by this review** (per the
request).

---

## 0. Executive verdict

**Is the pipeline built around a single, unified, well-defined execution flow? Partially.**

| Layer | Unified? | One-line finding |
|---|---|---|
| **Download** | ✅ **Yes** | One Zeta DM, two public APIs, six triggers funnel in; gRPC dead. |
| **Thumbnails** | ✅ **Yes** | One `ThumbnailStore` singleton over a canonical disk PNG; one dead duplicate (`thumbnail_panel.py`). |
| **DICOM files on disk** | ✅ **Yes** | Single owner: `SOURCE_PATH/<study_uid>/<series>/`, atomic `.part`→`replace`. |
| **Viewport apply (sink)** | ✅ **Mostly** | One sink `VTKWidget.switch_series` + one deliberate in-place `grow()`. |
| **Import / load orchestration** | ⚠️ **Converged, not unified** | One hub (`change_series_on_viewer`) but several entry paths + 2 duplicate `_display_loaded_series`. |
| **Decode** | ⚠️ **One function, double-decode windows** | `load_single_series_by_number` (4 modes) + `load_series_preview` + ZetaBoost booster; same series can decode twice. |
| **Caches** | ❌ **No** | ~10 cache layers; 5 keyed by **bare `series_number`**; the hot lookup caches are **lock-free** yet written from worker threads. |
| **Per-series STATE** | ❌ **No** | **6+ parallel state holders** with no single authority; reconciled by a growing pile of one-shot guards. |
| **Request identity / isolation** | ❌ **Structurally no** | Cancellation tokens + caches keyed by **grid-index `viewer_id`** and **bare series number**, neither unique across patients/layouts. Cross-patient isolation rests on **content guards**, not on the keys. |

**Bottom line:** the *data-path* (download → disk → thumbnail → metadata sink
`set_server_series_info`) is genuinely unified and clean. The *viewer-side execution* (load →
decode → cache → per-series state → viewport) is a **defensive, fix-on-detect** architecture:
correctness is currently held together by ~20 one-shot guards and four cross-patient content
checks rather than by a single owned execution model. **Every recurring bug this session
(47793/47842/47855 partial-volume, the 145× resume livelock, the 99→8 downgrade) is a direct
symptom of that fragmentation.** The unified model is **not yet verified**; §10–§11 define what
must be built/confirmed before further changes.

---

## 1. Current pipeline architecture

### 1.1 End-to-end stages and the modules that own each

```
USER double-clicks patient
  │
  ▼  PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py
[1] OPEN PATIENT TAB  (FAST-OPEN-TRACE hot path; builds PatientWidget; study_path resolved)
  │   metadata source: server GetPatientList/GetStudyThumbnails → set_server_series_info sink
  ▼
[2] METADATA  → _server_series_info (map) + lst_thumbnails_data[idx]['metadata'] (per-series)
  │            terminus of the UNIFIED data-path pipeline (_pw_thumbnails.py set_server_series_info)
  ▼
[3] DOWNLOAD (if needed)  → Zeta Download Manager
  │   add_downloads() / request_critical_series_download()
  │   → WorkerPool QThread → subprocess → DownloadExecutor → SeriesDownloader
  │   → SocketDicomClient.download_series (socket, NOT gRPC)
  ▼
[4] DICOM FILES  → disk: SOURCE_PATH/<study_uid>/<series_number>/Instance_NNNN.dcm
  │               atomic .part → os.replace
  ▼
[5] THUMBNAILS  → executor _save_thumbnails → THUMBNAIL_PATH/<study_uid>/<series>.png
  │              + ThumbnailStore (singleton memory LRU)
  ▼
USER drags a series into a viewport
  │   PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py::change_series_on_viewer  ← THE HUB
  ▼
[6] IMPORT / DECODE  → image_io.load_single_series_by_number (FAST=pydicom_qt lazy | VTK=ITK)
  │   (preview-first: load_series_preview decodes slice 0 for instant first image)
  ▼
[7] FIRST IMAGE  → qt_fast_container.switch_series → qt_viewer_bridge (Qt/QPainter render)
  ▼
[8] PROGRESSIVE VIEW  → _vc_progressive: on_series_images_progress → _grow_progressive_fast
  │                     (admission-gated grow; disk-ready resume watchdog as fallback)
  ▼
[9] CACHE  → _hot_series_cache/_series_cache/_full_series_cache + ZetaBoost L1(mem)/L2(disk)
  ▼
[10] COMPLETE / MARK READY  → PipelineOrchestrator (study-level state) + _progressive_display_done
                              + ViewportLoadSucceeded lifecycle event
```

### 1.2 Threading model (who runs where)

| Thread / process | On GUI thread? | Role |
|---|---|---|
| Qt main + **qasync event loop** (`main.py:1256` `QEventLoop(app)`) | **Yes** (one loop drives the whole app) | all viewport apply/switch/grow, progressive timers, watchdog, warmup-result poll, asyncio coroutines |
| `AsyncSwitchLoad-N` threads (`_vc_switch.py:1022`) | No (1/uncached switch) | DICOM+ITK decode for an uncached drag, then marshal apply back to UI |
| DM `WorkerPool` QThreads + **download subprocess** (1/study) | No | download + atomic disk write + writes to live `dicom.db` |
| ZetaBoost **warmup subprocess** + disk-write daemons + `ImageSliceBooster` worker | No | prefetch/decode completed series into L1/L2 |
| Background **header-fill** threads (`_vc_cache.py:651`) | No | pydicom header reads; **mutate `metadata['instances']`** off-thread |
| DB connection pool (per-thread, `_pool.py`) | any thread | WAL SQLite |

The intended design (`MULTI_PIPELINE_CONCURRENT_ARCHITECTURE.md`) is a **main download pipeline +
N independent sub-render pipelines over a protected shared-resource layer with a pin/unpin memory
manager and an atomic state machine**. In reality the "sub-pipelines" are **not** separate
per-viewer threads — they are coroutines + ad-hoc worker threads on the single qasync loop, and the
pin/unpin manager and atomic `PipelineStateManager` from that doc are marked "🔨 Implement" and were
**not built** (the doc is aspirational for those pieces).

---

## 2. Pipeline ownership diagram

```
                          ┌─────────────────────────────────────────────┐
                          │  UNIFIED DATA-PATH (clean, single-owner)     │
                          ├─────────────────────────────────────────────┤
 Server ──GetPatientList─▶│ set_server_series_info  (the sink/terminus)  │
                          │   ↳ _server_series_info  (identity authority) │
 Zeta DM ──add_downloads─▶│ SOURCE_PATH/<study>/<series>/*.dcm (disk own) │
   (one slot/study)       │ THUMBNAIL_PATH/<study>/<series>.png (disk own)│
                          │   ↳ ThumbnailStore singleton (mem LRU)        │
                          └───────────────────────┬─────────────────────┘
                                                  │  set_server_series_info
              ════════════════ CLINICAL BOUNDARY ═╪═══════════════════════════
                                                  ▼
                          ┌─────────────────────────────────────────────┐
                          │  VIEWER-SIDE EXECUTION  (fragmented)         │
                          ├─────────────────────────────────────────────┤
 drag/click/resume ──────▶│ change_series_on_viewer  (the HUB)           │
 reopen/back-fill ───────▶│   ├─ sync apply: _perform_series_switch_opt  │
 progressive grow ───────▶│   ├─ async:     _schedule_async_load_and_switch│
 disk-ready watchdog ────▶│   └─ → switch_series  (THE APPLY SINK)        │
                          │                                              │
   STATE (NO OWNER):      │  PipelineOrchestrator (study) ┐              │
   6 parallel holders ───▶│  DM state_store (study)       ├ disagree →   │
                          │  _progressive_* (12 sets)     │ patched by   │
                          │  _loading_series_numbers      │ one-shot     │
                          │  vtk._awaiting_series_number  │ guards       │
                          │  caches (the payload)         ┘              │
                          │                                              │
   CACHES (NO SHARED      │  _hot/_series/_metadata_flat (bare key,      │
   INVALIDATION BUS):     │     LOCK-FREE) · _full(study key) ·          │
                          │  ZetaBoost L1/L2 (bare key) · lazy_registry  │
                          └─────────────────────────────────────────────┘
   Isolation today = the four cross-patient CONTENT guards
   (open / reconcile / resync / back-fill *_cross_patient_skip) — NOT the keys.
```

**Ownership summary:** clean single-owner above the `set_server_series_info` line; **no single
owner** for per-series state or the decoded-volume caches below it.

---

## 3. Shared vs duplicated execution paths

| Responsibility | Status | Convergence point | Duplicate / dead paths (evidence) |
|---|---|---|---|
| **Download** | **UNIFIED** | `add_downloads` + `request_critical_series_download` → `SocketDicomClient.download_series` | gRPC retired and dead (`network/grpc_client.py:1-58` is socket-backed). Legacy `_on_patient_double_clicked__bb` (`_hp_patient_open.py:1589`) is a parallel open-enqueue — verify/remove. |
| **Import / load** | **CONVERGED (1 dup)** | `change_series_on_viewer` → `switch_series` | **Two `_display_loaded_series`**: live `_vc_warmup.py:753` vs legacy-ish `_pw_series.py:657` — should be merged. |
| **Decode** | **1 fn, 4 modes + 2 satellites** | `image_io.py:2634 load_single_series_by_number` | `load_series_preview` (2nd decode of slice 0) + ZetaBoost `ImageSliceBooster`; **same series can decode twice** (preview→full; warmup vs interactive), deduped only by caches. |
| **Thumbnails** | **UNIFIED store** | `ThumbnailStore` singleton | **DEAD:** `thumbnail_panel.py::ThumbnailPanel.change_series_on_viewer` + `ThumbnailBatchRunner` — never instantiated. |
| **Viewport update** | **1 sink + 1 grow** | `VTKWidget.switch_series` | `_grow_progressive_fast`→`bridge.grow()` is an intentional append-only path (not a dup). |

**Unification candidates (concrete, low-risk):** (1) delete dead `thumbnail_panel.py`; (2) merge
the two `_display_loaded_series`; (3) remove the legacy `__bb` open; (4) add a decode-coalescing
authority to close the preview→full / warmup→interactive double-decode windows.

---

## 4. Data ownership model

| Data type | Source of truth | Writers | Readers | Conflicts |
|---|---|---|---|---|
| **Series identity / enumeration** | **Server** (`_server_series_info`) — `image_count` never overwritten once set (`_pw_thumbnails.py:206`) | `set_server_series_info`, `_rebuild_multistudy_series_index` (replaces map) | `resolve_series_expected_count`, thumbnail render | C2: two SeriesInstanceUIDs sharing a number → disambiguated offset key |
| **Series slice COUNT (live)** | **Disk** (`os.scandir`) — `_refresh_stored_metadata_instances` rewrites `metadata['instances']` (`_vc_cache.py:629`) | refresh + `replace_series_data` + DB writer | slider, decision logic | **C1 (central): server count vs disk file count vs `len(instances)` vs `get_count_of_slices()` — four numbers, no single authority.** This is the root of the 47793/47842/47855 bugs. |
| **Thumbnail** | **Disk PNG** (canonical) | DM executor atomic write; `ThumbnailStore.put` warms mem | `ThumbnailStore.get_bytes` (mem→disk), `ThumbnailImageSourceService` | Clean. DB `thumbnail_path` is a non-authoritative hint. |
| **DICOM files** | **Disk** `SOURCE_PATH/<study>/<series>/` (patient-blind) | download subprocess (atomic) | volume backend, header fillers, counters | Write integrity sound; **path key = series_number** → cross-study collision risk, mitigated by disambiguated folder key + cross-patient guards. |
| **Decoded volume** | **`PyDicomLazyVolume`** (np.memmap) registered in `lazy_volume_registry` (uuid key, refcounted) | loader build | viewer + all caches | **memmap must outlive cached `vtk_image_data`** or VTK reads dangling C++ ptr (segfault risk, `pydicom_lazy_volume.py:547`). |
| **Cache entries** | — | workers + UI | workers + UI | **4 layers hold the decoded volume with NO shared invalidation bus**; only manual `_invalidate_series_caches` clears all together (`_vc_cache.py:365`). |
| **Viewport metadata** | deep-copy of `lst_thumbnails_data[idx]['metadata']` at viewer creation | `_sync_viewer_metadata_instances` | render | Goes stale if sync not called; **sync matches on bare `series_number`** so a multi-study offset-key viewer can miss the sync. |

**Same-data-from-different-sources (no clear policy):** the **series count** (5 readers via an
ordered fallback chain vs 3 independent writers that each treat a different source as truth) and the
**decoded `vtk_image_data`** (simultaneously in `lst_thumbnails_data`, `_series_cache`/`_hot`,
ZetaBoost L1, and reconstructed-distinct L2). These two families are where ownership is weakest.

---

## 5. Concurrency review (the critical scenario)

**Scenario:** open A → drag A-series → before it finishes open B → drag B-series → keep switching.

**What holds up well:**
- **Download contention** is correctly arbitrated: A and B are different studies → they contend for
  the WorkerPool; dragging sets CRITICAL → `evaluate_preemption` pauses the other study's worker
  (`series_intent_coordinator.py:476`); same-study yield is a batch-boundary `.critical_intent.json`
  (no teardown). The viewer-side `_coalesce_dm_view_intent` debounce (last-write-wins) prevents the
  single slot from thrashing on rapid alternating drops.
- **No classic lock-ordering deadlock** found: `_series_load_lock` is released before the load and
  the **main thread refuses to block** on the dedup event (`_vc_load.py:656`); WorkerPool/orchestrator
  callbacks fire *outside* their locks; DB connections are created *outside* `_pool_lock`.
- **Within one viewport**, request invalidation works: `_next_request_token` + `_is_request_current`
  drops a stale load when the user switches series on the same cell.

**Where it breaks (ranked, with evidence):**

| # | Hazard | Type | Severity | Evidence |
|---|---|---|---|---|
| **A1** | **`viewer_id` is the GRID INDEX**, so the request-token namespace (0,1,2,3) collides across patient/layout switch. A stale Patient-A worker holding `expected_token=5` for viewer 0 can pass `_is_request_current` against Patient B's new viewer 0. | cross-contamination | **HIGH** | `id_vtk_widget=viewer_index`; `_vc_switch.py:1668-1682`, `_vc_load.py:204` |
| **C1** | `_series_cache`/`_hot_series_cache`/`_full_series_cache` are **lock-free dicts keyed by bare `series_number`**, written from the off-thread decode workers (`_vc_switch.py:654`, `_vc_cache.py:640`). | race / cross-contamination | **HIGH** | `viewer_controller.py:155/172/257` |
| **D1** | The `AsyncSwitchLoad` apply path touches `vtk_w.image_viewer` **without** the `RuntimeError` guard that `_finish_on_ui` has, and is **not cancelled on tab close** (only asyncio tasks are). A decode finishing as the tab closes can write a half-deleted Qt/VTK object. | disposal / use-after-free | **HIGH** | `_vc_load.py:1074-1152`; `_pw_lifecycle.py:213` |
| **F1** | `request_critical_series` reasons from a **pre-update state snapshot** (`series_intent_coordinator.py:300` vs `:358`); under rapid cross-patient drops it can write the critical-intent for the wrong series or queue the dragged series behind the retry ladder ("nothing finishes"). | race / starvation | **HIGH** | `series_intent_coordinator.py:374` |
| **A2/B1** | `_viewer_request_token` and `_async_switch_inflight` are **lock-free** and mutated from GUI **and** worker; a lost `discard` permanently blocks a `(viewer_id,series)` switch (code even has a "last-resort cleanup" comment). | race / livelock | MEDIUM | `_vc_switch.py:801/891/1011` |
| **D2** | `_dl_watchdog_timer` is **not stopped in `closeEvent`** (only `_progressive_grow_timer` is); a queued tick can call `change_series_on_viewer` post-teardown. | disposal | MEDIUM | `_pw_lifecycle.py:329`; `_vc_progressive.py:1135` |
| **E1** | Disk-ready resume **livelock** (the observed "145× attempts") because nothing clears `_awaiting_series_number` on the change_series path. Now patched by the settled-stop guard. | livelock | MEDIUM | `_vc_progressive.py:1272` |

**Cross-patient isolation today is held by CONTENT guards (study_uid/patient_id checks), not by the
keys.** The token/cache/inflight machinery is a *performance* layer that is not itself patient-safe;
A1/C1 are the realistic bleed paths and are caught downstream only because the four
`*_cross_patient_skip` guards re-validate ownership. This is robust-in-practice but **fragile by
design** — remove or mis-order one guard and isolation is gone.

---

## 6. Synchronization issues

1. **Lock-free shared mutable state across threads** (the central issue): `_viewer_request_token`
   (dict), `_series_cache`/`_hot_series_cache`/`_full_series_cache` (dicts), `_async_switch_inflight`
   (set) are read/written from both the GUI thread and the AsyncSwitchLoad/warmup workers with **no
   lock and no memory barrier**. CPython's GIL prevents corruption of the container, but there is **no
   happens-before guarantee** — a worker can act on a stale token/cache value.
2. **No shared cache-invalidation bus**: four layers hold a decoded volume; consistency depends on a
   *manual* `_invalidate_series_caches` call on every disk-growth tick.
3. **The interactive-load semaphore is held across the full VTK decode** (`_vc_load.py:758-781`) —
   intentional (serialize heavy ITK) but can serialize two patients' loads into multi-second waits on
   weak hardware.
4. **Off-thread metadata mutation**: background header-fill mutates `metadata['instances']` (shared by
   reference across `_server_series_info`, `lst_thumbnails_data`, caches, and each viewer copy) — the
   `object_id_metadata`/`object_id_instances` probes exist *only* to detect this divergence.
5. **`os.replace` last-write-wins on `.critical_intent.json`** with no sequence number — two rapid
   drops can drop the first intent.

---

## 7. Cache ownership review

| Cache | Key | Scope / TTL | Collision risk | Owner of invalidation |
|---|---|---|---|---|
| `_hot_series_cache` | **bare series_number** | per-tab, ≤3 FIFO | **HIGH** (mitigated by per-tab + `entry[0] is cur_vtk` identity) | `_invalidate_series_caches` |
| `_series_cache` | **bare series_number** | per-tab, unbounded | **HIGH** (per-tab only) | same |
| `_metadata_flat_cache` / `_series_number_to_index` | bare series_number | per-tab, rebuild | per-tab | rebuild |
| `_full_series_cache` (viewer) | **(study_uid, series_number)** ✓ | delegates to ZetaBoost | LOW on viewer side, **lost at the ZetaBoost boundary** (bare key) | `zeta_boost.invalidate_series` |
| **ZetaBoost L1 mem** | **bare series_number** | LRU + byte budget | **HIGHEST** (documented `_vc_cache.py:284`) — guarded by read-time `_cache_entry_study_matches` drop+invalidate | `invalidate_series` |
| ZetaBoost L2 disk | (tab_key, series_number) | LRU 20 GB | per-tab + bare | same |
| `_disk_count_cache` | bare series_number | **1.0 s TTL** | low (count only) | `_invalidate_disk_count_cache` |
| **ThumbnailStore** | **(study_uid, series_number)** ✓ | singleton LRU 300/50 MB | **LOW** | `clear()` |
| `lazy_volume_registry` | opaque uuid | refcount | **NONE** | refcount→0 |

**Finding:** **five caches key on the bare `series_number`**, which restarts at 1 per study. Within a
multi-study patient they *would* collide; collision is prevented not by the keys but by **(a)**
offset keys (`study_slot*1_000_000+orig`) for non-primary studies and **(b)** read-time study-match
validation that drops mismatched entries. The properly-scoped caches (`ThumbnailStore`,
`_full_series_cache`, `lazy_volume_registry`) are the clean exceptions. **There is no pin/unpin and no
single eviction authority** — the `MemoryCacheManager` from the design doc was never built; each
cache evicts independently, so a series can be evicted from L1 while still displayed (re-decode) or
held in three layers at once (memory waste).

---

## 8. Thread-safety review

- **Race conditions:** A1 (token namespace), A2 (lock-free token), C1 (lock-free caches), B1
  (lock-free inflight set). **HIGH/MEDIUM.**
- **Deadlocks:** none found (good lock hygiene). **One livelock** (E1, resume watchdog — patched).
- **Duplicate jobs:** interactive load + switch are deduped; **gap** is the bare/grid keys (same
  series in two patients shares an inflight key) and the double-decode windows (preview→full,
  warmup↔interactive).
- **Double decode:** real but bounded by caches (§3).
- **Duplicate cache writes:** possible — two workers can write the same bare key in different patient
  contexts (C1).
- **Duplicate viewport updates:** the render-coalescing signature (`display_thumbnails`) and the
  switch dedup mitigate; the in-place grow vs full apply are distinct by design.
- **Task cancellation:** per-viewport token works **within** a cell; **does not** cleanly cancel a
  stale load across patient/layout switch (A1) nor on tab close for worker threads (D1).
- **Viewport disposal:** **use-after-free surface** (D1/D2) — same class as the curved-MPR crash
  already in `CLAUDE.md`. Asyncio tasks are cancelled on close; **worker threads and the DM watchdog
  timer are not.**
- **Patient tab switching:** safe for content (guards) but **not** for the token/cache identity (A1).

---

## 9. Identified bottlenecks

1. **Full-volume load bails for some secondary-study series** (47855/47842 series 203): the volume
   stays a 1-slice preview because `_load_single_series_on_demand(force_reload=True)` never reaches
   the disk scan (`UX_SERIES_LOAD_START` never logs) — likely the `_loading_series_numbers` not-owner
   dedup or a 0-file path resolution. **Clinical-visible** (user sees 1 image). *Open.*
2. **Metadata-count fragmentation** (§4 C1) → the 47793/47842 "stuck at N", 99→8 downgrade, and the
   metadata-clobber oscillation. Patched per-sink this session; not unified.
3. **Resume-watchdog churn** (E1): up to 145 re-fires/series until the settled-stop guard — CPU + main
   thread stalls.
4. **Synchronous full-series build on the GUI thread** for the cached recovery/force-reload path
   (~1.9 s stall on multi-frame US) — the off-thread route exists but isn't taken for that case.
5. **App startup** ~2.9 s (`add_AIpacs_tab`), separate from viewer.
6. **Interactive-load semaphore** serializes two patients' VTK decodes on weak HW.
7. **Triple+ memory residency** of a decoded volume (no pin/unpin, no single eviction owner).

---

## 10. Recommended unified architecture

The data-path is already unified; the work is on the **viewer-side execution**. Target model
(extends the staged `ensure_series_displayed` chokepoint + the `SeriesDisplayState` authority already
built this session, and the `DownloadPlan`/catalog in `unified-patient-study-pipeline.md` §7):

1. **One stable request identity, not grid index.** Replace `viewer_id = grid position` and bare
   `series_number` keys with a composite **`(patient_id, study_uid, series_uid, viewer_handle)`** where
   `viewer_handle` is a per-widget UUID (not the layout slot). This single change closes A1, B1, and
   the bare-key collision class (C1, §7) at the root, and makes cross-patient isolation **structural**
   instead of guard-dependent.
2. **One per-series state authority** (`SeriesLifecycle`): owns `Requested → Downloading → Downloaded
   → Importing → Decoding → Rendering → Cached → Ready` for each `(study,series)`, with atomic
   transitions (the `PipelineStateManager` the design doc specified but never built). The six current
   holders (orchestrator, DM state_store, `_progressive_*`, `_loading_series_numbers`,
   `_awaiting_series_number`, the caches) become *projections* of it, not independent truth.
3. **One `ensure_series_displayed(viewer_handle, series_id, intent)` chokepoint** that every entry
   point (drag, click, reopen, restore-cache, reload, prefetch, resume) funnels through — it owns the
   decide-once decision (already prototyped as `decide_display_action`), the canonical-metadata sync,
   the settled-state emission (`ViewportLoadSucceeded` + clear awaiting), and cancellation. This
   removes the duplicate `_display_loaded_series`, the resume livelock, and the "no one clears
   awaiting" gap.
4. **One decoded-volume cache with a shared invalidation bus + pin/unpin.** Collapse
   `_hot`/`_series`/`_full`/ZetaBoost-L1 into one study-keyed memory cache with the `MemoryCacheManager`
   pin/unpin from the design doc (pin while displayed, single LRU eviction owner), and a single
   `invalidate(study,series)` that all layers subscribe to. Keep ZetaBoost L2 (disk) and the lazy
   registry as the cold tiers.
5. **Thread-safe by construction.** All shared cross-thread state behind locks **or** passed as
   immutable per-request snapshots; cancellation via a unique request-id token (not grid index); a
   single teardown that (a) cancels worker threads + the DM watchdog timer and (b) routes every apply
   site through one `RuntimeError`-guarded helper (closes D1/D2).
6. **One decode-coalescing authority** keyed by `(study,series)` so preview→full and
   warmup↔interactive never double-decode the same series.

This stays **above `set_server_series_info`** and changes no VTK/MPR geometry, slice order, or
rendering — it is a control-plane unification, exactly the discipline in
`unified-patient-study-pipeline.md` §7.

---

## 11. Prioritized list of required fixes

**P0 — clinical correctness / safety (do first, each flag-gated + guard-tested + live-validated):**
- **P0.1 Request identity:** introduce a per-widget `viewer_handle` UUID and make the request token +
  inflight sets patient/handle-scoped (fixes **A1, B1**). Until then, the cross-patient content guards
  are the only isolation — keep all four.
- **P0.2 Lock the hot caches** (or snapshot-pass them) and key them by `(study_uid, series)` (fixes
  **C1**). Add the single shared `invalidate(study,series)` bus.
- **P0.3 Disposal safety:** stop `_dl_watchdog_timer` in `closeEvent`; cancel/abandon AsyncSwitchLoad
  apply on tab close; wrap every `image_viewer`/`vtk_widget` apply site in the existing
  `RuntimeError`-swallow guard (fixes **D1, D2** — same class as the curved-MPR crash).
- **P0.4 Full-volume load bail (47855/203):** root-cause why `_load_single_series_on_demand` never
  reaches the disk scan for these series (instrument the `_loading_series_numbers` dedup + the
  0-file path resolution) and ensure the volume reaches disk count.

**P1 — robustness / the unified core:**
- **P1.1** Build the single **per-series state authority** + `ensure_series_displayed` chokepoint
  (§10.2–10.3); migrate the six state holders to projections. This retires the resume livelock (E1),
  the settled-state gap, and the metadata-count fragmentation (C1) structurally.
- **P1.2** Fix the **preempt stale-snapshot race** (F1) — re-read state after `state_store.update`;
  add a sequence number to `.critical_intent.json` (F2).
- **P1.3** Consolidate the **series-count truth** into the `SeriesDisplayState` builder (one accessor
  over server/disk/canonical/viewer) so no path re-derives it.

**P2 — efficiency / hygiene (low risk):**
- **P2.1** One **decoded-volume cache + pin/unpin** eviction owner (§10.4); end triple residency and
  evict-while-displayed.
- **P2.2** **Decode coalescing** authority (preview→full, warmup↔interactive).
- **P2.3** Delete dead code: `thumbnail_panel.py` (`ThumbnailPanel`/`ThumbnailBatchRunner`), merge the
  two `_display_loaded_series`, remove the legacy `__bb` open.
- **P2.4** Move the synchronous full-series build off the GUI thread for the force-reload/recovery case
  (bottleneck §9.4).

**Sequencing & guardrail:** P0.3/P0.4 are isolated and shippable now. P0.1/P0.2 and all of P1 are the
unified-model core — build the authority + handle identity behind flags, migrate one entry point at a
time with a live multi-patient concurrent GUI pass each, legacy preserved as kill switch, **no
VTK/MPR/geometry/render change**. Do **not** begin P1/P2 structural work until P0.1/P0.2's identity
model is validated, since everything else keys off it.

---

## Verification statement

The unified execution model is **verified as present for the data-path (download → disk → thumbnail
→ metadata sink) and the viewport-apply sink**, and **verified as ABSENT for per-series state,
request identity, and the decoded-volume caches** — which is the measured source of the recurring
viewer bugs. Per the request, **no architectural changes were made**; §10 defines the model to build
and §11 the order, with P0.1 (request identity) as the keystone that must be confirmed before the
rest.

*Audit basis: three independent code audits (execution paths, data/cache ownership,
concurrency/threads/state) with file:line evidence, cross-checked against the project pipeline docs
and CLAUDE.md as-built history, 2026-06-25.*
