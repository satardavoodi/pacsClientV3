# Viewer Unification — staged plan (better · faster · simpler) — 2026-06-25

**Premise (user directive):** stop patching symptoms one at a time; look at the whole
process/structure from above. The recurring viewer bugs are one structural cause. Fix the
structure and the symptoms disappear *and* the codebase shrinks.

**Inputs this builds on (do not re-derive):**
- `docs/reports/VIEWER_PIPELINE_ARCHITECTURE_REVIEW_2026-06-25.md` §10 (the target model + P0 hazards A1/C1/D1/D2/F1).
- `docs/plans/architecture/UNIFIED_SERIES_DISPLAY_AUTHORITY_PLAN_2026-06-24.md` (prior authority plan).
- Already built: `PacsClient/utils/series_display_state.py` (`SeriesDisplayState`,
  `decide_display_action`, `target = max(disk, expected)`) and
  `PacsClient/utils/patient_study_set.py` (the pure-authority pattern to copy).

---

## 1. The one root cause

A series is keyed **three different ways** along its life:

| Layer | Key today | Set in |
|---|---|---|
| Download manager | bare/resolved `series_number`, scoped per `study_uid` | DM signals |
| Multi-study UI (thumbnails, viewport) | offset/display key (`slot*1_000_000+n`) | `set_server_series_info` |
| Viewer request token | **grid index** (`viewer_id = viewer_index`) | viewer apply |

Every recurring bug is a seam between two of these keyings:
- **47084** thumbnail status, **46970** progressive bind, **46713** disk-ready resume → DM-key vs UI-key seam (each got its own re-keying guard).
- **47855** partial volume / ownership leak → state held in N places, no atomic owner.
- **A1** cross-patient isolation → request token = grid index collides across patient/layout switch; isolation currently rests on 4 *content* guards, not the keys.

So: **one identity + one state owner + one entry chokepoint + one volume cache** dissolves the seams.

## 2. The spine (4 abstractions, all pure/thread-safe, both backends)

1. **`SeriesRequest` / `ViewerHandle`** — stable identity value objects: `(patient_id,
   study_uid, series_uid, display_key, viewer_handle: UUID)`. Replaces grid-index `viewer_id`
   + bare `series_number` as the request token. Pure stdlib.
2. **`SeriesStateStore`** — the single per-series state authority (`Requested → Queued →
   Downloading → PartialOnDisk → Decoding → Displayed | Failed`), atomic, thread-safe, keyed
   by identity. The 6 existing holders become thin projections that *read* it.
3. **`ensure_series_displayed(handle, request, intent)`** — the single chokepoint every entry
   point funnels through. Owns `decide_display_action` (already built), canonical
   `set_server_series_info` sync, settled-state, and cancellation.
4. **`VolumeCache`** — one decoded-volume cache keyed by identity, with pin/unpin + a shared
   invalidation bus. Replaces the ~10 ad-hoc cache layers (5 bare-keyed, lock-free).

## 3. Stages (each: flag default-OFF → live-validate on Windows source build → flip default-ON → soak → delete the listed guards)

### S0 — Lay the spine, change no behavior (shadow-only) — ✅ LANDED 2026-06-25
> **Done:** `PacsClient/utils/viewer_identity.py` (`ViewerHandle`, `SeriesRequest`) +
> `PacsClient/utils/series_state_store.py` (`SeriesState`, `SeriesStateStore`,
> `can_transition`) — pure stdlib, **unwired** (zero runtime risk). Flag
> `AIPACS_VIEWER_SPINE_SHADOW` (default off). Tests:
> `tests/code/ui_services/test_viewer_unification_spine.py` — 19 green. The store already
> encodes the structural fixes (atomic ownership release, monotonic displayed-count, owner
> gate, server-grew refetch reset) the later guards will retire. The first read-only shadow
> wiring is the opening move of S1.

- Add `SeriesRequest`/`ViewerHandle` + `SeriesStateStore` as **pure, unused** modules with a
  default-OFF shadow that logs what they *would* decide next to the live path, for diff.
- **Unifies:** nothing yet. **Retires:** nothing. **FAST/VTK:** N/A (no wiring).
- **Flag:** `AIPACS_VIEWER_SPINE_SHADOW` (off). **Test:** pure unit tests for the value
  objects + state transitions; shadow-diff harness.
- **Payoff:** zero risk; proves the model matches reality before any call site moves.

### S1 — Stable identity becomes the request token (keystone, closes A1)
> **S1a LANDED 2026-06-25 (read-only shadow):** `_vc_switch.py` (not mirrored) now attaches a
> stable `ViewerHandle` per viewer cell (`_viewer_handle_for`) and runs a default-off shadow
> (`AIPACS_VIEWER_SPINE_SHADOW`) that logs `[VIEWER-IDENTITY-SHADOW] event=grid_slot_reused`
> when a grid index is reused by a new cell identity, and `event=token_match_handle_mismatch`
> when the grid-index token says "current" but the cell identity changed (the A1 false-positive).
> Live request-token behavior is byte-identical; no handle is attached when the flag is off
> (zero cost). Guard: `tests/code/viewer/test_viewer_identity_shadow.py` (6 green; 42 green with
> the switch suites). **S1b (flip `_is_request_current` to handle-based under
> `AIPACS_VIEWER_STABLE_IDENTITY`) is GATED on live shadow evidence** — run the app with
> `AIPACS_VIEWER_SPINE_SHADOW=1`, switch patients/layouts, and confirm whether `grid_slot_reused`
> actually fires before flipping.

- Thread `ViewerHandle` (UUID) + `SeriesRequest` through the request path; `_is_request_current`
  compares handles, not grid indices. FAST and VTK both carry it.
- **Unifies:** request identity across patient/study/layout. **Retires (after soak):** the
  A1 collision risk structurally; the 4 `*_cross_patient_skip` content guards become
  belt-and-suspenders (keep as defense, no longer load-bearing).
- **Flag:** `AIPACS_VIEWER_STABLE_IDENTITY`. **Test:** a Patient-A worker cannot pass
  `_is_request_current` for a Patient-B viewer after a layout swap.
- **Payoff (safer + simpler):** isolation stops depending on content heuristics.

### S2 — One per-series state authority (kills the ownership-leak class, closes F1)
> **S2a LANDED 2026-06-25 (read-only shadow):** `_vc_progressive.py` (not mirrored)
> `_shadow_observe_state_authority` feeds the S0 `SeriesStateStore` at the resume settled-stop —
> the exact 47084 livelock site — and logs `[STATE-AUTHORITY-SHADOW]` when its structural
> `is_settled` (displayed ≥ max(disk,expected)) diverges from the live race-prone
> `get_count_of_slices() >= disk`. Gated `AIPACS_VIEWER_SPINE_SHADOW` (default off → no store
> created, zero work). The feed is now `_feed_state_authority` (see S2b).
>
> **S2b LANDED 2026-06-25 (first authority READ — additive + safe):** `_feed_state_authority`
> runs when shadow OR `AIPACS_VIEWER_STATE_AUTHORITY` is on (populating the store), and the resume
> settled-stop reads the authority's structural `is_settled` as an **ADDITIONAL** stop signal:
> `if _settled_visible or _exhausted or _authority_settled`. The store's **monotonic high-water
> mark** of displayed slices means once a viewport has shown the full set it stays settled even
> when `get_count_of_slices()` momentarily reads low mid-rebuild — the exact race that let the
> 47084 loop spin (a real reliability gain). It NEVER removes the live checks (strictly
> more-likely-to-stop, never less), and cannot keep a genuinely-incomplete series from resuming
> (then displayed < target → `is_settled` False). Default **off** (`=1` to enable) until
> live-validated; guard `test_resume_livelock_complete_series.py::test_s2b_state_authority_is_additional_stop_signal`
> (30 green). NEXT (S2c): feed the store from download-complete + `ViewportLoadSucceeded` too,
> then make it primary (live check = fallback) and retire `AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE`
> + `AIPACS_CRITICAL_INTENT_FRESH_STATE`.

- Route the 6 holders (PipelineOrchestrator, DM `state_store`, `_progressive_*` sets,
  `_loading_series_numbers`, `vtk._awaiting_series_number`, the caches) to read/write through
  `SeriesStateStore`. Transitions atomic → no leaked ownership by construction.
- **Retires:** `AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE` (47855 leak guard),
  `AIPACS_CRITICAL_INTENT_FRESH_STATE` (F1 — the store is the single fresh source),
  `AIPACS_RESUME_STOP_WHEN_SETTLED` simplifies (authority knows `Displayed`).
- **Flag:** `AIPACS_VIEWER_STATE_AUTHORITY`. **Test:** stale-load + preempt sequences can't
  strand a series in "loading"; no holder disagrees with the store.
- **Payoff (faster + simpler):** removes a whole guard family; deterministic state.

### S3 — One `ensure_series_displayed` chokepoint (dissolves the DM-key/UI-key seam)
- All entry points (drag-drop, thumbnail click, switch, progressive resume, study back-fill,
  previous-exams) call the one chokepoint. It resolves the display/offset key **once** from
  the stable identity, so DM-number↔UI-offset-key re-keying is no longer per-site.
- **Retires:** `AIPACS_THUMB_SIBLING_STUDY_STATUS` (47084),
  `AIPACS_PROGRESSIVE_UID_BIND` (46970), `AIPACS_VIEWPORT_DISK_READY_RESUME` (46713) — three
  re-keying patches collapse into one resolution; plus `AIPACS_SWITCH_REBUILD_WHEN_BEHIND`,
  `AIPACS_POSTCOMPLETE_EXPECTED_GATE`, `AIPACS_GROW_FALLBACK_FORCE_RELOAD` (count-truth now
  lives in the authority).
- **Flag:** `AIPACS_ENSURE_SERIES_DISPLAYED`. **Both backends** funnel through it (above the
  backend-specific apply). **Test:** multi-study secondary series start/complete/progress/
  resume all route correctly via one path; FAST + VTK parity.
- **Payoff (simpler, big):** retires ~6 flags; multi-study keying bugs cannot recur.

### S4 — One decoded-volume cache + pin/unpin + invalidation bus (closes C1, the speed win)
- Replace the ~10 cache layers (5 bare-keyed, lock-free, no shared invalidation) with one
  identity-keyed `VolumeCache`: pin the active series (no eviction mid-view), shared
  invalidation on server-grew, and **decode coalescing** (no series decodes twice — review
  found `load_single_series_by_number` + `load_series_preview` + ZetaBoost can double-decode).
- **Retires:** the bare-keyed caches + their ad-hoc invalidations.
- **Flag:** `AIPACS_VIEWER_VOLUME_CACHE`. **Test:** thread-safety under worker writes;
  single-decode assertion; pin survives switch-away/back.
- **Payoff (faster, the real one):** no double decode, no redundant rebuilds, hot series resident.

### S5 — Unified teardown by handle (closes D1/D2)
- Cancel/dispose by `ViewerHandle`: AsyncSwitchLoad apply guarded + cancelled on tab close;
  all timers (incl. `_dl_watchdog_timer`) stopped in one place.
- **Retires:** scattered disposal guards; `AIPACS_SWALLOW_DELETED_OBJECT_EVENTS` becomes a
  pure backstop, not load-bearing.
- **Flag:** `AIPACS_VIEWER_UNIFIED_TEARDOWN`. **Test:** close-during-load / close-during-MPR
  no use-after-free.

## 4. Order, dependencies, discipline
- Strict order S0→S5 (each depends on the prior spine piece). S1+S2 are the keystones; do not
  start S3 retirements until S1/S2 are default-ON and soaked.
- **Every stage:** flag default-OFF; legacy preserved as the kill switch; one guard test
  (source-pin + functional offscreen); live source-build validation on a **multi-study** and a
  **single-study** patient and on **both** FAST and Advanced before flip; only **delete** a
  retired flag after its replacement has soaked default-ON.
- **Clinical guardrails (unchanged):** stays ABOVE `set_server_series_info`; **no** VTK/MPR
  geometry, slice order, orientation, or render change; atomic `.part`+resume preserved;
  cross-patient isolation only ever *strengthened* (structural), never relaxed.
- **Mirroring:** `modules/download_manager` is plugin-mirrored (sync + verify after edits);
  `_vc_*`, `home_download_service.py`, `_pw_*` are not.

## 5. Net effect when done
- **Better:** isolation + multi-study correctness become structural (whole bug families gone).
- **Faster:** one decode + one cache + pin/unpin + no redundant rebuilds.
- **Simpler:** retire ~10+ `AIPACS_*` flags and the guard cluster they represent; 3-way keying → 1.

## 5b. Live status 2026-06-25 (post-restart verification)
- **Resume-watchdog livelock FIXED + live-verified.** New run (>21:49:42) on the multi-study
  patient: 0 `ViewportLoadResumedFromDisk`, 0 grow-fallback churn (was `attempt=3028` on the old
  code). Series that had been stuck at an 8-slice preview now grows to completion:
  `progressive-fast: series=202 COMPLETE (384 slices)`. KPIs excellent — viewer TTFI
  `total_ms=6.6 / 10.9 / 24.4`. (Fixes: `AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND` +
  settled-stop exhaustion; guard `tests/code/viewer/test_resume_livelock_complete_series.py`.)
- **NEXT FELT BOTTLENECK = main-thread stalls.** Same run: 60 `[MAIN_THREAD_STALL]`, avg 288 ms,
  **max 4418 ms**, 5 over 500 ms, all `interaction_active=False` → the synchronous full-series
  volume build on the GUI thread (the 2.4 s build called out in the poor-network review, now
  4.4 s on a 384-slice series). This is the highest-value remaining "faster" win and belongs to
  **S4** (off-thread decode + one volume cache). Promote it: the off-thread build can land as a
  focused, flag-gated pass (default-off → validate → on) ahead of the full S4, since it is the
  dominant user-felt freeze. Treat it as a dedicated change (clinical rendering on a worker
  thread) — design + live-validate carefully, do not rush.
- A1 identity shadow: still **no evidence** — the restart did not set `AIPACS_VIEWER_SPINE_SHADOW=1`,
  so S1b stays gated on a future shadow run.

## 6. Suggested first move
S0 is pure and zero-risk (shadow only). Recommend starting there to lock the contracts and
prove the model against the live app, then S1 (the identity keystone) gated default-off for
live validation.
