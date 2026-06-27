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
- **FULL SPINE DEFAULT-ON 2026-06-27 (user directive — "make the unified path the default, stop
  the flag-gating, we'll run it and fix what breaks").** Flipped to default-ON in main:
  **S1** `AIPACS_VIEWER_STABLE_IDENTITY` (handle-based request currency — only rejects on a
  DEFINITE handle mismatch, never a false reject) and **S3** `AIPACS_ENSURE_SERIES_DISPLAYED`
  (chokepoint observation/divergence feed). S2 + S5 were already default-ON. Each keeps a `=0`
  kill switch as the **per-part rollback** the user asked for (not a validation gate). The
  validation-before-flip discipline above is SUPERSEDED by the user's "default-first, fix-on-break"
  directive. Guard tests updated to the new defaults (`test_stable_identity_request_check.py`,
  `test_ensure_displayed_shadow.py`, `test_viewer_identity_shadow.py`). **NEXT = the real path
  reduction:** the S3b CUTOVER — route the entry points through `plan_series_display` to ACT and
  DELETE the re-keying branches (`AIPACS_PROGRESSIVE_UID_BIND`, `AIPACS_THUMB_SIBLING_STUDY_STATUS`,
  the sibling/slow-link/resume-skip patches) so the path count actually drops. Landed in main
  default-on (no shadow gate); run → find the broken part → fix that part.
- **S3b CUTOVER — FIRST CUT LANDED 2026-06-27 (`home_download_service.py`, the DM→viewer bridge).**
  The three flag-gated re-keying patches `AIPACS_PROGRESSIVE_UID_BIND` (46970),
  `AIPACS_THUMB_SIBLING_STUDY_STATUS` (47084) and `AIPACS_GROW_SIBLING_STUDY` (sibling grow) — all
  default-ON — were **deleted** and replaced by ONE unconditional rule: every DM grow-lane event
  (`on_series_progress` / `on_series_completed`) resolves its display key via the single
  `_grow_lane_display_key(uid, series_uid)` (awaiting/shown key from this patient's
  `_server_series_info` → cross-patient safe; else PRIMARY `_resolve_sn`; else None = background
  sibling, skip), and the thumbnail lane (`on_series_started`/completed) admits via the
  unconditional `_belongs_to_open_thumbnails`. **3 flags + 3 branches → 1 resolver.** Behavior is
  byte-identical in production (the flags were default-ON; only the dead `=0` legacy branches were
  removed). Guard tests updated (`test_grow_sibling_study` / `test_progressive_uid_bind` /
  `test_thumb_sibling_study_status` — kill-switch tests removed, source-pins now pin the unified
  resolver; 58 green with the lifecycle/connection/slow-link/resume neighbours). NEXT cuts: route
  the viewer-side grow/resume count-truth gates (`AIPACS_SWITCH_REBUILD_WHEN_BEHIND`,
  `AIPACS_POSTCOMPLETE_EXPECTED_GATE`, `AIPACS_GROW_FALLBACK_*`) through `plan_series_display`, then
  the disk-ready-resume + slow-link-grow + resume-skip into the same chokepoint.
- **First count-gate ROUTED THROUGH THE AUTHORITY — `AIPACS_POSTCOMPLETE_EXPECTED_GATE` (LANDED
  2026-06-27, `_vc_load.py::load_series_on_demand` post-complete skip).** The flag + its legacy
  raw-disk `=0` branch (the buggy 47804 path) were deleted; the completeness TARGET now comes from
  the shared authority `build_series_display_state(series, disk_count, expected_count).target`
  (== `max(disk, expected)`) instead of an inline `max()`. This is the FIRST gate whose count-truth
  is sourced from the one authority rather than re-derived locally — the structural pattern the rest
  of the count-gates follow. Behaviour-identical to the default-ON path (a `max()` fallback guards an
  import failure); the 47804 fix is preserved + proven equivalent by
  `test_postcomplete_expected_gate.py::test_authority_target_equals_max_disk_expected` (12 green).
  Remaining count-gates (`SWITCH_REBUILD_WHEN_BEHIND` qt_fast_container, `GROW_FALLBACK_*` _vc_switch —
  the latter embeds the 47084 livelock fix) are next, one at a time with a live check between.
- **DEFAULT-ON activation 2026-06-26 (user "safe robustness"):** the two *monotonic-safe* spine
  layers were flipped default-ON — **S2** `AIPACS_VIEWER_STATE_AUTHORITY` (additional settled-stop;
  can only stop *earlier*, never load a wrong/late series) and **S5** `AIPACS_VIEWER_UNIFIED_TEARDOWN`
  (cancellation token only ever *bails* a stale/superseded apply). Both keep `=0` kill switches and
  byte-identical legacy. **HELD default-OFF:** **S1** `AIPACS_VIEWER_STABLE_IDENTITY` (load-bearing
  request-currency flip — needs the live shadow pass first) and the read-only shadows
  (`AIPACS_VIEWER_SPINE_SHADOW`, `AIPACS_ENSURE_SERIES_DISPLAYED`). So the S3b cutover gate is now
  "S2 default-ON ✓ (pending soak) + S1 default-ON (still pending) + shadow 0-divergence".
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

## 5c. Stage status 2026-06-26
- **S0** ✅ spine (identity + state authority), pure, tested.
- **S1a** ✅ identity shadow. **S1b** ✅ LANDED — `_is_request_current` also requires the cell's
  stable `ViewerHandle` to match the handle that issued the token (closes A1), flag
  `AIPACS_VIEWER_STABLE_IDENTITY` default-off; guard `test_stable_identity_request_check.py` (4 green).
- **S2a/S2b** ✅ state-authority shadow + additive settled-stop. **S2c** ✅ LANDED (feed half) —
  the authority is now fed at the real display terminal (`ViewportLoadSucceeded`) via the
  `_log_viewport_lifecycle` chokepoint (`_feed_state_authority_from_lifecycle`), so the store records
  genuine display completions; gated by shadow / `AIPACS_VIEWER_STATE_AUTHORITY`; guard
  `test_resume_livelock_complete_series.py::test_s2c_authority_fed_at_display_lifecycle`. **S2c tail**
  (make the authority PRIMARY for the settled/ownership decision + retire
  `AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE` / `AIPACS_CRITICAL_INTENT_FRESH_STATE`) stays gated on a
  live soak.
- **S3a** ✅ LANDED (chokepoint decision core, pure + UNWIRED) —
  `PacsClient/utils/viewer_request_pipeline.py`: `plan_series_display(request, …) -> DisplayPlan`
  composes the `SeriesRequest` identity with the single `decide_display_action` authority (no second
  copy of the rules) and a request-scoped `DisplayPlan.supersedes()` (same ViewerHandle + different
  series = the cancellation signal that replaces the grid-index token race) + `LoadIntent`. Guard
  `tests/code/ui_services/test_viewer_request_pipeline.py` (8 green). **S3b-shadow** ✅ LANDED
  2026-06-26 (additive, default-OFF, retires NOTHING) — `_vc_progressive.py::_feed_state_authority`
  now ALSO asks the chokepoint at the resume settled-stop (reusing the `SeriesRequest` + counts
  already gathered for S2) and logs `[ENSURE-DISPLAYED-SHADOW]` when `plan_series_display`'s
  `DisplayPlan` disagrees with the live settled decision. Pure helper
  `_ensure_displayed_shadow_divergence`; flag `AIPACS_ENSURE_SERIES_DISPLAYED` (default off; also runs
  under `AIPACS_VIEWER_SPINE_SHADOW`). Guard `tests/code/viewer/test_ensure_displayed_shadow.py`
  (functional truth-table on the REAL `plan_series_display` + source-pins; verified to sandbox limit —
  runs on the Windows `.venv`). `check_validation.ps1` now reports the "S3 chokepoint shadow" line.
  **S3b-cutover** (route drop / progress / completion / disk-resume to ACT on the plan, then retire
  `_PROGRESSIVE_UID_BIND` + the sibling patches) stays gated per §4's strict order: **not until
  S1/S2 are default-ON and soaked**, and the shadow shows 0 divergences on a live multi-study run.
- **S4a** ✅ LANDED (volume-cache core, pure + UNWIRED) — `PacsClient/utils/volume_cache.py`:
  thread-safe `VolumeCache` keyed by the stable `(study_uid, series_uid)`; `get_or_create`
  **coalesces concurrent decodes** (factory runs at most once per key — closes the duplicate-decode
  the audit found); `pin`/`unpin` keep the active volume resident; LRU eviction skips pinned; one
  `invalidate` / `invalidate_study` / `invalidate_all` bus. Guard
  `tests/code/ui_services/test_volume_cache.py` (8 green, incl. an 8-thread coalescing proof + error
  propagation). **S4b** (wire into the FAST decode path, pin the active series, retire the ~5
  bare-keyed lock-free caches → closes C1 + the speed win) is the dedicated, clinical-lane-validated
  commit.
- **S5a** ✅ LANDED (cancellation primitive, pure + UNWIRED) —
  `PacsClient/utils/viewer_cancellation.py`: `CancellationRegistry` buckets `CancellationToken`s by
  `ViewerHandle` UUID; `new_token(handle, supersede=True)` cancels the prior in-flight op for the
  same viewport (request supersession), `cancel_handle` / `cancel_all` cancel on tab/patient close
  (the D1/D2 use-after-free fix — a late apply finds its token cancelled and bails before touching a
  deleted object), `retire` drops a cleanly-finished op. Cross-viewport isolated. Guard
  `tests/code/ui_services/test_viewer_cancellation.py` (7 green, incl. concurrency). **S5b** wires it
  into `closeEvent` + the AsyncSwitchLoad apply + the watchdog stop — dedicated, clinical-lane-validated.

**Net so far — the ENTIRE pure foundation set is built and green** (≈60 tests): stable identity
(S0/S1), per-series state authority (S0/S2), chokepoint decision core (S3a), decoded-volume cache +
decode-coalescing (S4a), cancellation-by-handle (S5a). **All pure/additive/default-off → zero
clinical behavior changed.** What remains is exclusively the **side-effecting WIRING** —
- **S3b** route the 4 entry points through `plan_series_display`, then retire `_PROGRESSIVE_UID_BIND`;
- **S4b** wrap the FAST volume build with `VolumeCache.get_or_create` (pin active series) — note the
  build site (`pydicom_lazy_volume.py`) has a delicate mmap/VTK-backing/GC lifetime, so this needs
  careful design + a clinical-lane pass;
- **S5b** ✅ LANDED (first wiring stage, flag-gated default-off) — `_vc_switch.py`: the async
  `_schedule_async_load_and_switch` registers a `CancellationToken` on the viewer's stable handle
  (`_register_load_cancellation`, `supersede=True`), `_finish_on_ui` **bails before touching the
  widget** when the token is cancelled, and retires it on completion; `_pw_lifecycle.exit_patient_widget`
  calls `cancel_inflight_loads()` first on close. Flag `AIPACS_VIEWER_UNIFIED_TEARDOWN` (default off →
  no token registered → byte-identical; D2 timer-stop was already fixed, and `_finish_on_ui` already
  caught the deleted-widget RuntimeError — this makes the apply BAIL cleanly instead, and also gives
  request-supersession). Guard `tests/code/viewer/test_unified_teardown_cancellation.py` (6 green;
  38 green across the touched viewer suites — no async-path regression). Remaining S5 wiring (the
  off-thread non-`_finish_on_ui` apply sites + the watchdog) can extend the same registry.

Each is flag-gated default-off + guard-tested, and its activation/guard-retirement **must** clear the
clinical-lane validation gate (`run_with_validation.cmd` + `check_validation.ps1` + a Mehr slow-link
multi-study drop). Do NOT land the wiring blind — the volume-lifetime delicacy + this session's
grow-fallback-livelock regression both prove why.

## 6. Suggested first move
S0 is pure and zero-risk (shadow only). Recommend starting there to lock the contracts and
prove the model against the live app, then S1 (the identity keystone) gated default-off for
live validation.

## 7. Observed-in-default-run issues (2026-06-26) → stage coverage
After the S2+S5 default-ON activation, a default-mode run (PID 194692) + a log/KPI check surfaced two
**pre-existing** items (NOT activation regressions — S5 cancellation never fired, zero new-code-path
errors, resume bounded at `attempt=3`, TTFI avg 33 ms / max 68 ms). Both fold into the existing
stages — **no new viewer-unification stage is needed.**

**Issue A — false `[ASYNC SWITCH] preview remained active (full load failed)` ERROR**
(`_vc_switch.py::_finish_on_ui`).
- Root cause: the `ok==False` branch is the NORMAL "switched to a series still downloading" path
  (the code itself says *"Not a hard failure"*). Line 959 was downgraded to INFO, but the
  `if preview_applied:` sub-line kept a stray `logger.error` (with, ironically, an info ℹ️ emoji).
  The affected series confirmedly reach `complete` via progressive grow — purely a log-level oversight.
- ✅ **FIXED 2026-06-26** (log-level only, zero behavior change): downgraded to `logger.debug` with a
  clarifying comment. Removes the recurring FALSE ERROR from clinical logs.
- **Structural coverage:** the "real load failure vs. not-downloaded-yet" decision is the S3
  chokepoint's `AWAIT_DOWNLOAD` `DisplayPlan` action. After **S3b cutover** this path routes through
  `plan_series_display`; the already-shipped progressive grow + disk-ready resume
  (`AIPACS_VIEWPORT_DISK_READY_RESUME`) finish it. **S3 already owns it** — no new work.

**Issue B — main-thread stalls** (this run: max ~3.0 s; 3 of 58 over 1 s). Two distinct sources:
- **B1 — full-series finalize/build on the GUI thread.** The ~2.8 s stall window (20:34:41) was
  dominated by `load_series_on_demand` + `_finalize_progressive_series` on the main thread (total=30
  slices; scales with slice count → the up-to-4.4 s seen on big CBCT). **Coverage: S4b + task #39** —
  `VolumeCache.get_or_create` (S4a, built; decode-coalescing) wired into the FAST build AND the
  finalize/build moved OFF the GUI thread. This is exactly the S4 "speed win"; B1 is its headline
  symptom. (Caution unchanged: `pydicom_lazy_volume.py` mmap/VTK-backing/GC lifetime — design + a
  clinical-lane pass before flipping on.)
- **B2 — one-time STARTUP stalls** (20:32:12 + 20:32:21, right after lock-acquire): app/VTK/Qt init +
  first render, NOT series work. **OUT OF SCOPE for viewer-unification** (this plan is the series
  pipeline). Tracked as a separate, lower-priority *startup responsiveness* item (lazy/defer heavy
  subsystem init); may be an acceptable one-time cost. New backlog task.

**Net:** A = fixed (log) + owned by S3; B1 = the core of S4b/#39 (already planned — the speed win);
B2 = a new small out-of-scope startup item. The default-mode activation itself is clean.
