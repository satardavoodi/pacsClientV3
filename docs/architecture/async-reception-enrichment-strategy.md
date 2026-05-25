# Async Reception / Workflow Enrichment Strategy

> **Type:** Design / planning deliverable (no implementation)
> **Status:** For review — implement only after approval, stage by stage
> **Date:** 2026-05-23
> **Companion docs:** `network-architecture.md`, `hybrid-communication-model-analysis.md`
> **Scope:** How reception/workflow metadata (reporting physician, report status
> detail, approvals, comments) should enrich the patient list — fast, reliable,
> non-blocking — without ever slowing imaging.

This document designs a deliberate orchestration model for REST/workflow
enrichment. It proposes **no code changes**; it defines the target architecture,
timing, caching, and a staged roadmap. It builds on the confirmed Stage 0 finding:
the socket `GetPatientList` carries `latest_study_report_status` only — no reporter
name/ID, no `report` object — so reporter data **must** be enriched over REST.

---

## 1. Current-State Analysis

### 1.1 The end-to-end flow today

| # | Step | Code | Transport | Thread |
|---|------|------|-----------|--------|
| 1 | Patient search | `HomeSearchService.search_server()` | Socket `GetPatientList` | bg executor → `asyncio` |
| 2 | List render | `_add_socket_patient_to_table()` → `add_data2patient_list_table()` → `add_patient_data()` | — | **UI thread** (bulk-insert, chunked every 25 rows) |
| 3 | Reporter enrichment | `_sync_completed_reporting_physicians_after_search()` → `_queue_reporting_physician_hydration()` | REST `/api/pacs/patients/{id}` (+ `/api/pacs/users/{id}`) | per-task daemon threads, max 4 |
| 4 | Patient open | `show_patient_studies()` / open flow | Socket thumbnails / `GetStudyInfo` | bg threads |
| 5 | Download | `start_priority_download_immediately()` → DM | Socket (download subprocess) | spawn subprocess + QThread bridge |
| 6 | Viewer interaction | FAST / Advanced viewer | local files | viewer threads |
| 7 | Report dialog | `_on_report_status_clicked()` → `_fetch_report_comment_async()` | REST `/api/pacs/patients/{id}` | one daemon thread |
| 8 | Background workers | per-task `threading.Thread` (hydration), QThread (DM), daemon threads (dialog) | — | **no shared pool** |
| 9 | Caching | `_reporting_physician_cache` (pid→name), comment cache, thumbnail file cache | — | in-memory / disk |

### 1.2 What works well

- **Socket list is already immediate** — rows render in chunks of 25 with
  `await asyncio.sleep(0)` yields; the UI stays responsive during insert.
- **Report status is already immediate** — `latest_study_report_status` ships
  inside `GetPatientList`, so the status icon needs zero enrichment.
- **Enrichment is already off the UI thread** — `_queue_reporting_physician_hydration()`
  does REST work in daemon threads and marshals UI updates back via
  `QTimer.singleShot(0, ...)`.
- **A per-patient cache exists** — `_reporting_physician_cache` prevents re-fetching
  the same patient within a session.

### 1.3 Current pain points (evidence-based)

**C1 — Per-task thread spawning, not a pool.** `_queue_reporting_physician_hydration()`
creates a fresh `threading.Thread` per patient, capped at 4 concurrent via an
`_reporting_physician_inflight` set; when full it re-queues itself with
`QTimer.singleShot(120, ...)`. This works but is a soft busy-wait pattern and has
no real backpressure, no prioritization, and no cancellation.

**C2 — No prioritization.** `collect_completed_rows_missing_reporting_physician()`
returns completed rows in table order. Rows the user is actually looking at (the
viewport) are not hydrated first. On a long list the visible rows may be last.

**C3 — No cache TTL or invalidation.** `_reporting_physician_cache` lives for the
whole process and is keyed by `patient_id`. There is no freshness bound and no
event-driven invalidation; a status change made elsewhere is not reflected until
restart (the in-app dialog path does update the row, but the cache can go stale).

**C4 — Duplicate REST calls across paths.** Three independent code paths hit
`GET /api/pacs/patients/{id}`: list hydration (`_hp_search.py`), the report dialog
(`patient_table_widget.py::_fetch_report_comment_async`), and the reception data
tab. They do **not** share a cache layer, so the same patient can be fetched 2–3×.

**C5 — No coalescing against re-search.** Each new search re-runs hydration. There
is no search-generation token, so in-flight hydration for rows that no longer
exist still completes and still calls `update_reporting_physician_for_patient()`
(which simply finds no matching row — wasted REST + work, not a crash).

**C6 — Enrichment timeout is sized for a blocking call.** `_fetch_reception_patient_payload()`
uses `requests.get(timeout=8)`. For *enrichment* (non-critical, best-effort) 8 s is
long; a slow/unreachable endpoint ties up a worker slot for 8 s.

**C7 — Disconnected until just now.** `_sync_completed_reporting_physicians_after_search()`
was orphaned; Stage 1 (N1) wired it. So enrichment now runs — but with all the
limitations C1–C6.

### 1.4 Risk notes

- **UI-thread risk:** low today — REST is off-thread. The remaining UI-thread cost
  is `collect_completed_rows_missing_reporting_physician()` (walks every table row)
  and `update_reporting_physician_for_patient()` (walks rows to find one). Both are
  O(rows) table scans on the UI thread; cheap at 100 rows, worth watching at 1000+.
- **Race condition risk:** low — UI updates are marshalled through `QTimer.singleShot`.
  The only real race is C5 (stale-row updates), which is harmless today.
- **Retry storms:** none currently (no retry logic in hydration) — but also no
  negative caching, so an endpoint that returns "no physician" is re-fetched on
  every re-search.

---

## 2. Pain Points (summary, ranked)

| ID | Pain point | Impact | Fix difficulty |
|----|-----------|--------|----------------|
| C2 | No visible-row prioritization | UX — wrong rows fill first | medium |
| C4 | Duplicate REST calls across 3 paths | server load, latency | low–medium |
| C3 | No cache TTL / invalidation | staleness or wasted refetch | low |
| C1 | Per-task threads, no real pool | scalability, no cancellation | medium |
| C5 | No search-generation coalescing | wasted REST after re-search | low |
| C6 | 8 s enrichment timeout | a worker slot stalls 8 s on a bad endpoint | low |
| — | Per-row REST (N calls for N rows) | server load on big lists | server-side |

---

## 3. Recommended Orchestration Model

A single, deliberate **Enrichment Coordinator** owns all reception/workflow
enrichment. It is the only thing that issues enrichment REST calls; ad-hoc
spawning is removed.

```
            ┌──────────────────── search_server() ───────────────────┐
            │ socket GetPatientList → rows rendered (UI, chunked)     │
            │ report-STATUS icon already correct (socket payload)     │
            └───────────────────────────┬─────────────────────────────┘
                                         │ hand off (fire-and-forget)
                                         ▼
            ┌──────────────  EnrichmentCoordinator  ──────────────────┐
            │  • single owner, one bounded ThreadPoolExecutor (3–4)   │
            │  • input: completed rows missing a physician name       │
            │  • dedup: skip pid in cache(fresh) / in-flight / queued  │
            │  • priority queue:                                      │
            │       tier 0  visible completed rows                    │
            │       tier 1  near-viewport completed rows              │
            │       tier 2  off-screen completed rows (idle backfill) │
            │  • generation token: dropped on next search             │
            │  • each task → REST GET /api/pacs/patients/{id}         │
            │       → extract physician → (resolve id→name if needed) │
            │       → write shared cache → marshal UI update          │
            └───────────────────────────┬─────────────────────────────┘
                                         ▼
            ┌──────────── shared ReceptionCache (TTL) ────────────────┐
            │  key: patient_id → {physician, status, comment, ts}     │
            │  also written by: report dialog fetch, patient-open,    │
            │  reception tab → one cache, no duplicate REST           │
            └──────────────────────────────────────────────────────────┘
```

Principles:

1. **Socket list first, always.** Rows render from the socket payload with no
   wait. Enrichment is strictly post-render and fire-and-forget.
2. **Status is free.** Report-status icons come straight from
   `latest_study_report_status`; the Coordinator never fetches status.
3. **One owner.** All enrichment REST goes through the Coordinator → one pool, one
   cache, one queue. No path spawns its own enrichment thread.
4. **Visible-first.** The viewport defines priority. The user sees the rows they
   are looking at fill within ~1 s; off-screen rows fill as the pool drains.
5. **Cache is the contract.** The report dialog, patient-open, and reception tab
   read/write the *same* cache. A fetch by any path benefits all paths.
6. **Event-driven, never polling.** Refresh is triggered by re-search, by a
   report-status change, or by TTL expiry on access — never by a timer loop.
7. **Total isolation from imaging.** The Coordinator's pool is separate from the
   socket pool, the gRPC client, and the download subprocess (see §F / below).

---

## 4. Timing Model

"Immediate" = same frame as the socket response. "Async" = off the UI thread,
UI interactive throughout. "Lazy" = only when needed.

| Signal | Target | Class | Mechanism |
|--------|--------|-------|-----------|
| Patient list visible | immediate | immediate | socket `GetPatientList`, chunked insert (exists) |
| Report **status** icon | immediate | immediate | `latest_study_report_status` from socket payload (exists) |
| Reporting physician — **visible** completed rows | **< 1 s** after rows | async, prioritized | Coordinator tier 0, bounded pool |
| Reporting physician — off-screen completed rows | best-effort (seconds) | async, lazy | Coordinator tier 2, idle backfill |
| Reception detail (approvals, comment, findings) | on demand | lazy | report dialog fetch (exists) — now cache-backed |
| Completed-report change | on next search / on event | async | re-search re-hydrates; later: broadcast-driven |
| Viewer responsiveness | never blocked | immediate | enrichment fully isolated |
| Download responsiveness | never blocked | immediate | enrichment fully isolated |

**Honest note on the < 1 s target.** With per-patient REST, < 1 s is realistic for
the *visible* completed rows (typically 15–25 rows; 4 workers × ~5 waves ×
~100–250 ms ≈ 0.5–1.3 s). It is **not** guaranteed for *all* rows on a large,
completed-heavy list. A true < 1 s for the whole list requires a server-side
**batch endpoint** or `radiologist_name` inlined into `GetPatientList` (§8, Stage F).
The design hits the UX goal (what the user is looking at is fast) without the
server change, and degrades gracefully.

---

## 5. Cache Strategy

A single **ReceptionCache**, shared by every path that touches
`/api/pacs/patients/{id}`.

| Aspect | Recommendation |
|--------|----------------|
| Key | `patient_id` (the REST endpoint is per-patient) |
| Value | `{ reporting_physician, report_status, comment, fetched_at, source }` |
| TTL — completed reports | long (e.g. 10–15 min, or session-long): a completed report's radiologist is effectively immutable |
| TTL — pending/in-progress | short (e.g. 60–120 s) or no positive cache: these can change |
| Negative cache | "no physician found" cached briefly (e.g. 60 s) to stop re-hammering an endpoint that genuinely has nothing |
| Invalidation | on report-status change via the in-app dialog (already updates the row → also update cache); later, on a realtime broadcast for that study/patient |
| Staleness tolerance | **optimistic display** — show cached value immediately even if slightly stale; refresh in the background if past TTL ("stale-while-revalidate") |
| Scope | process-lifetime, in-memory; no disk persistence needed (cheap to refetch) |
| Shared writers | list hydration, report dialog, patient-open, reception tab all write here |

The cache is what kills duplicate REST (C4): the report dialog opening for a
patient already hydrated in the list does **zero** new network I/O.

---

## 6. Retry / Failure Strategy

Enrichment is **non-critical**: a missing physician name must degrade to the
existing NA/icon fallback, never to an error or a stall.

| Concern | Recommendation |
|---------|----------------|
| Timeout | enrichment-specific, short — ~3–4 s (not the 8 s in `_fetch_reception_patient_payload`); a non-critical call must not hold a worker slot for 8 s |
| Retry | at most **1** retry, only on timeout/connection error, with a small fixed delay; then give up |
| Failure result | leave the row as status-icon/NA; write a short-TTL negative cache entry so the next search doesn't immediately re-hammer |
| Graceful degradation | if the REST endpoint is consistently failing (e.g. N consecutive failures), the Coordinator backs off the whole queue for a cooldown window — no retry storm |
| Cancellation | a new search bumps the generation token; queued (not-yet-started) tasks for the old generation are dropped; in-flight tasks finish but their UI write is a no-op if the row is gone |
| UI-thread safety | all failure handling stays in worker threads; only the final `update_reporting_physician_for_patient()` is marshalled to the UI thread |

---

## 7. Queue / Prioritization Strategy

| Element | Recommendation |
|---------|----------------|
| Queue | one priority queue inside the Coordinator |
| Tier 0 | **visible** completed rows missing a physician — hydrate first |
| Tier 1 | rows just above/below the viewport (pre-fetch for imminent scroll) |
| Tier 2 | all other completed rows — idle backfill as the pool drains |
| Skip entirely | non-completed rows — they have no final radiologist, and the column only renders a name for `completed` status anyway |
| Dedup / coalesce | before enqueue, skip a `patient_id` that is cached-fresh, in-flight, or already queued |
| Re-prioritization | on scroll, move newly-visible rows to tier 0 (debounced ~150–200 ms so a fast scroll doesn't thrash the queue) |
| Generation token | each search increments it; the queue is associated with the current token; a new search clears stale entries |
| Worker pool | one fixed `ThreadPoolExecutor`, size **3–4** — enough for < 1 s on visible rows, small enough to not stress the server or the GIL |
| Backpressure | the pool's bounded size *is* the backpressure; no busy-wait re-queue timer needed |

Visible-row detection: the patient table is a `QTableWidget`; the viewport row
range is derivable from `rowAt(viewport top/bottom)` plus the vertical scrollbar.
A debounced `valueChanged` handler feeds re-prioritization.

---

## 8. Suggested Staged Implementation Roadmap

Each stage is independently shippable, independently revertable, and gated on
verification. **Nothing here is implemented yet.**

| Stage | Change | Risk | Depends on |
|-------|--------|------|------------|
| **A** ✅ | N1 — wire `_sync_completed_reporting_physicians_after_search()` after search (done in Stage 1) | very low | — |
| **B** | Introduce `ReceptionCache` (TTL + negative cache) and route the existing hydration + report dialog + reception tab through it | low | A |
| **C** | Introduce `EnrichmentCoordinator` with one fixed `ThreadPoolExecutor`; replace per-task thread spawn + 120 ms re-queue timer; add dedup and the generation token | medium | B |
| **D** | Enrichment-specific timeout (~3–4 s) + ≤1 retry + failure backoff | low | C |
| **E** | Visible-row prioritization — viewport detection + debounced scroll re-prioritization | medium | C |
| **F** | **Server-side (cross-team):** batch endpoint `POST /api/pacs/patients/batch` *and/or* inline `radiologist_name` in `GetPatientList`. Collapses N calls → 1, or removes enrichment entirely | medium (cross-team) | independent |
| **G** | Event-driven refresh — invalidate/refresh a row on a realtime report-status broadcast (depends on the dedicated realtime channel from the hybrid doc, Stage 4) | medium–high | hybrid Stage 4 |

Recommended order: **B → C → D** first (these make enrichment correct, deduped,
and bounded with no UX coupling), then **E** (the visible-first UX win), then **F**
and **G** as larger/cross-team efforts. B+C+D together already deliver reliable,
low-traffic enrichment; E delivers the "feels near-live" UX.

---

## 9. High-Risk Anti-Patterns to Avoid

- **Blind polling loop.** No periodic timer that re-fetches the whole list.
  Refresh is event-driven (re-search, status change, TTL-on-access) only.
- **REST-on-search-row / synchronous per-row fetch.** Never fetch inside the
  row-build loop; never `await`/`join` a REST call before showing a row.
- **UI-thread REST.** No `requests.*` call on the Qt event loop, ever.
- **Unbounded thread spawning.** No "one thread per patient". A fixed, small pool
  only. (The current per-task spawn + 120 ms re-queue is the pattern Stage C
  replaces.)
- **Shared executors with imaging.** The enrichment pool must never be the socket
  pool, the gRPC client, or the download subprocess — that risks starving DICOM
  transfer or thumbnail loads.
- **Hydrating invisible rows before visible ones.** Wrong rows fill first; the UX
  goal fails even though work is being done.
- **No cache / re-hydrate every search.** Causes REST spam; a re-search of the
  same list should be almost free.
- **Retry storms.** No aggressive retry; ≤1 retry, negative cache, global backoff
  on sustained failure.
- **Blocking imaging on metadata.** Enrichment must never gate viewer open,
  thumbnail load, or DM enqueue (the Stage 3 decoupling in the hybrid doc).
- **Treating status like physician.** Status is in the socket payload — never
  issue a REST call just to get report status.

---

## 10. Risk Classification of Proposed Changes

| Change | Risk | Why |
|--------|------|-----|
| `ReceptionCache` with TTL + negative cache (Stage B) | **low** | additive; pure win; isolated module; easy to revert |
| Route existing 3 REST paths through the cache (Stage B) | **low–medium** | touches 3 call sites but only swaps a direct fetch for cache-or-fetch; behavior-preserving |
| `EnrichmentCoordinator` + fixed pool (Stage C) | **medium** | replaces the threading model; needs careful lifecycle (shutdown, generation token); confined to enrichment, no imaging impact |
| Enrichment timeout/retry tuning (Stage D) | **low** | parameter change in the enrichment path only |
| Visible-row prioritization (Stage E) | **medium** | couples to the table viewport/scroll; debounce needed; UI-thread cost must stay O(visible), not O(all rows) |
| Server-side batch / inline field (Stage F) | **medium** | cross-team; needs server work + a client capability check + fallback to per-patient |
| Event-driven refresh (Stage G) | **medium–high** | depends on a realtime channel that does not yet exist (hybrid doc Stage 4) |

**Untouchable / out of scope for this work** (high regression cost, no benefit
here): the socket connection pool and socket-port resolution
(`get_socket_server_settings()` → `50052`), the Download Manager subprocess and
its state store, the FAST vs Advanced viewer split, and the gRPC stack. Enrichment
is a separate domain and must stay that way.

---

## F. Isolation From the Download / Imaging Workflow

This is a hard requirement, so it is called out explicitly.

- **Separate pool.** The `EnrichmentCoordinator`'s `ThreadPoolExecutor` (3–4) is
  its own; it is never the socket pool, the gRPC client, or the DM subprocess.
- **Separate network path.** REST enrichment goes to `:8080` (HTTP); DICOM/socket
  traffic goes to `:50052`. They do not contend on the same connection.
- **Fire-and-forget hand-off.** `search_server()` hands rows to the Coordinator
  and returns; it never awaits enrichment. Imaging actions (thumbnail load, study
  open, DM enqueue, DICOM transfer, viewer startup) never await enrichment.
- **Shared resources are only CPU/GIL and the event loop.** Mitigation: keep the
  pool small (3–4), keep all REST off the UI thread, marshal only tiny UI updates
  back via `QTimer.singleShot(0, ...)`, and never `.join()` on the UI thread.
- **Priority yields to imaging.** If an imaging-critical operation is in progress
  (active download, viewer open), the Coordinator may pause tier-2 backfill until
  idle — visible-row enrichment (tier 0) still runs, since it is tiny and the
  user is looking at it.

---

## Honest Limitations

- The `< 1 s` UX target is met for **visible** rows with per-patient REST; a hard
  guarantee for *all* rows on large lists needs the Stage F server-side change.
- This document is design only. No threading model, cache, queue, timeout, or
  endpoint was changed. Stage A (N1) is the only enrichment change applied so far.
- Event-driven refresh (Stage G) is contingent on the realtime channel proposed
  in `hybrid-communication-model-analysis.md` (its Stage 4), which does not exist
  yet.
