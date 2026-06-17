# Drag-Drop Under Slow/Unstable Internet — Priority Thrash Root Cause + Strategy

Date: 2026-06-17
Status: **Phase 1 (first-image prime) + Phase 1b (live download notification) +
Phase 2 (drag coalescing) IMPLEMENTED, unit-tested, plugin-mirror-synced (389/389).
Awaiting live slow-link GUI validation. Phases 3–4 remain staged (see §6).**
Original investigation + strategy below (§1–§4).
Context: a clinical site with a very unstable, frequently-dropping internet link. A
competitor workstation shows one image of a dragged series almost immediately and a
"downloading" state; AI-PACS shows nothing until the first ~10-image batch arrives, the
user gets impatient and re-drags repeatedly, and the Download Manager priority system
thrashes until nothing downloads. Goal: a better strategy, framed within the
server-pipeline unification.

Related history (same failure family): `docs/reports/UI_ISSUE_INVESTIGATION_2026-06-04.md`,
`docs/reports/VIEWER_DRAG_PROGRESSIVE_SYNC_REVIEW_2026-06-02.md`,
`docs/reports/STABILITY_FIXES_TAKEOVER_AND_LARGE_BATCH_2026-06-05.md`,
`docs/reports/DM_*` and `docs/pipelines/unified-patient-study-pipeline.md`.

## 1. The two-part root cause

### A. There is no single-image fetch — the smallest unit is a whole batch
On drag-drop of a not-yet-downloaded series, the first pixel can only appear after the
**entire first download batch** clears: server `GetSeriesImages` → atomic disk write →
DB insert → throttled `seriesProgressUpdated` → viewer re-reads the folder from disk and
paints (`network/socket_client.py:1310` fetch, `:1446` atomic write,
`series_downloader.py` DB insert, `home_download_service._flush_progress`,
`_vc_progressive.py::_apply_progressive_to_target_viewer`).

- Default batch = **10** for CT/MR (`core/constants.py:16` `BATCH_SIZE`; init at
  `socket_client.py:1166`). The disk preview path (`load_series_preview`,
  `_vc_switch.py`) is **disk-only** — it shows nothing when the series isn't on disk yet.
- The FAST `ObjectCache.request_object` looks like a single-slice fetch but is **not**:
  it just escalates the whole series to CRITICAL (`_dm_priority.py:60-98`,
  "the current socket protocol downloads by series/batch, not arbitrary SOP object"), and
  it is **not even on the drop path** (only the stack-scroll scheduler).
- Under a dropping link, first-batch latency is dominated by the **30 s socket timeout**
  (`CONNECTION_TIMEOUT`, `constants.py:12`) + multi-layer backoff, **not** transfer — so
  the first 10 images can take tens of seconds to minutes. **The user stares at nothing.**

**This is the trigger:** the user sees no image, assumes it's stuck, and re-drags.

### B. Repeated drag-drop is not coalesced, and cross-study drops tear down the slot
There is a single download slot (`MAX_CONCURRENT_STUDIES = 1`, `constants.py:88`).

- **Same-series rapid re-drop IS guarded — but only per `(study, series)` key.** The drop
  notify `_notify_dm_viewed_series` has a **500 ms per-`(study_uid, series)` cooldown**
  (`_vc_load.py:1648,1723`); the download trigger `_trigger_download_if_needed` has a
  **2 s per-`(study_uid, series)` in-flight guard** (`:1834-1850`); and `set_viewed_series`
  no-ops when the same series is already viewed (`_dm_priority.py:391`). So hammering the
  SAME series is absorbed. **The gap: every guard is keyed by `(study, series)`** — a
  *different* series, or alternating *studies*, produces a new key and bypasses all of
  them. (The time-window debounce, 0.25/0.75 s, exists only on the FAST stack-scroll
  `request_object`, `_dm_priority.py:84-95` — not the drop.)
- **Same-study cross-series alternation is cheap.** The drop goes `_notify_dm_viewed_series
  → set_viewed_series → coordinator.request_critical_series` (`_dm_priority.py:396`). For a
  series of the SAME downloading study, that writes a `.critical_intent.json`
  (batch-boundary yield, last-write-wins, **no teardown** — `series_downloader.py` yield).
  The only pathology is "the target keeps moving, so the series the user stares at never
  finishes."
- **Cross-STUDY alternation is the destructive case.** The drop also runs
  `_trigger_download_if_needed → _on_retry_series_download → _on_series_retry`. For a
  DIFFERENT study, two things preempt the in-flight worker: the coordinator's
  `negotiate_priority_change` (PAUSE_ALL / PREEMPT_LOWER on the other study, via
  `request_critical_series`) and `_on_series_retry`'s `_pause_all_active_downloads()`
  (`_dm_retry.py`, when something is downloading). With `MAX_CONCURRENT_STUDIES=1` that
  **kills the running subprocess and spawns a new one** (Windows `spawn` ≈ 2.3 s +
  re-import + reconnect + **re-auth** + resume-scan). Under slow internet the next
  impatient cross-study drop arrives **before the new worker emits a byte**, so the slot is
  perpetually reclaimed — **nothing finishes.** Retry chains are **per-study, not global**
  (`series_intent_coordinator.py`), so alternating studies create competing chains for the
  one slot. (Correction to an earlier draft: the drop path is `set_viewed_series` +
  `_on_series_retry`, NOT `request_critical_series_download` — that is a separate viewer
  API; and same-series repeats ARE debounced per-key, as above.)
- **Retries compound.** Four nested layers (socket 30 s × batch 3× × reconnect 5× ×
  series 3×) under a study-level budget that treats unknown/network errors as *temporary*
  (10 retries, `constants.py:42`) → a flaky link churns for a very long time. No data is
  lost (atomic `.part` + resume), but a mid-series partial batch is re-requested over the
  wire.

**Net:** the perceptual gap (A) makes the user re-drag; the missing coalescing + the
cross-study teardown (B) turn that re-dragging into slot thrash. The competitor avoids
both by showing one image immediately (so the user waits) — exactly the fix direction.

## 2. Strategy — two pillars, both inside the unified pipeline

### Pillar 1 — First-slice-fast (kills the trigger)
Make a dragged series paint **one image as fast as possible**, then show clear progress.
The machinery already exists: `socket_client.py:1167` already forces `batch_size = 1` for
large-frame modalities. Generalize it to a **first-image prime**:

- For a freshly-viewed / drag-dropped series, make the **first batch size 1** (fetch one
  representative slice — first or middle), write it, emit progress → the existing
  progressive feed paints it within one round-trip instead of ten. Then let the adaptive
  batch grow as today for the remainder.
- Pair it with an explicit **loading/progress overlay** on the viewport: "Loading series
  N — image 1 of M" (and a spinner that reflects real progress), so the user sees motion
  and does not assume it is stuck.
- This is the smallest, highest-payoff change and uses existing code paths (batch=1 +
  progressive feed). It directly reproduces the competitor's "one image immediately"
  behavior under a slow link.

### Pillar 2 — Intent-stable, cheap repeated drag (kills the thrash even if the user re-drags)
- **Globalize the coalescing** (a per-`(study,series)` debounce already exists — the
  500 ms notify cooldown + 2 s retry in-flight guard — but it does NOT coalesce across
  keys). Add a single, study-agnostic **last-write-wins "current view target"** so rapid
  drops of *different* series/studies collapse to one target instead of each firing a fresh
  `request_critical_series` + preempt. The existing per-key guards stay; the new layer
  coalesces across them.
- **Settle-then-switch for cross-study drops:** replace the unconditional per-drop
  `_pause_all_active_downloads()` with a debounced preemption — do not kill the in-flight
  worker until the new target has been stable for a short window, and prefer a
  **batch-boundary yield** (the same `.critical_intent.json` mechanism that already makes
  same-study switches cheap) over a process teardown. The in-flight batch finishes; the
  slot then moves to the settled target. No kill/respawn per drop.
- **Single-flight slot:** since there is one slot, coalesce all pending critical requests
  into one "current target" (last-write-wins) drained at the next safe boundary, instead
  of N per-study retry chains racing. This is the "reduce parallel workflows" goal applied
  to the priority plane.

### How this fits the unification
A drag-drop should be **one "view series X" intent** through the unified pipeline, not its
own mini-workflow:
1. **prime** the first image (fast paint) — a `first_image=True` flag on the request;
2. register a **coalesced, stable download intent** — a `DownloadPlan` carrying
   open-intent + first-image priority (the same `DownloadPlan` the open/back-fill paths
   will use, per `docs/pipelines/unified-patient-study-pipeline.md`);
3. feed the viewer **progressively** from disk as batches land.
One coalesced intent for the single slot replaces the current racing chains — the
drag-drop path stops being a separate thrash-prone pipeline.

## 3. Phased, flag-gated implementation (lowest risk first)

Each phase default-on-after-validation, reversible by env flag, validated under a
simulated slow/dropping link AND live on the client PC. **No geometry/render change.**

- **Phase 1 — First-image prime + progress overlay** (perceptual; lowest risk, highest
  behavioral payoff). `AIPACS_FIRST_IMAGE_PRIME` (first batch of a freshly-viewed series =
  1 image, then grow) + a real "image X of M" loading state. This alone likely removes the
  re-dragging trigger. Risk: one extra round-trip before the batch grows (negligible;
  resume is batch-granular and tolerates a size-1 first batch). Validate first paint < a
  few seconds even on a slow link.
- **Phase 2 — Global (cross-key) coalescing of the view target** (`AIPACS_DRAGDROP_DEBOUNCE`).
  The per-`(study,series)` cooldowns already exist (500 ms notify, 2 s retry); add a
  single last-write-wins "current target" across studies/series so alternating drops
  collapse to one intent. Risk: must guarantee the *final* drop wins (coalesce, not drop).
- **Phase 3 — Settle-then-switch cross-study preemption** (don't kill the worker on every
  cross-study drop; debounce the preempt; prefer batch-boundary yield). Medium risk —
  must preserve same-study yield, cross-patient isolation, and not starve a genuinely
  higher-priority study. Flag-gated.
- **Phase 4 — Unify drag-drop onto the view-intent / DownloadPlan + single-flight slot.**
  The architectural consolidation; do after Phases 1–3 prove the behavior, with the
  DownloadPlan work from the unified-pipeline plan.

## 4. Risks and validation

- **Resume/atomicity unaffected:** a size-1 first batch still writes atomically and
  resumes batch-granularly; verify the leading-batch resume still skips correctly.
- **Fast-LAN regression check:** the prime adds at most one extra round-trip; confirm
  no measurable open/drag slowdown on a healthy link.
- **Coalescing correctness:** test that the last of N rapid drops is the one that
  downloads/displays (no lost intent), and that same-study yield + cross-patient isolation
  are preserved.
- **Slow-link test:** exercise with an artificially throttled/dropping connection (or the
  client PC) — assert first image appears quickly, repeated drops do not tear down the
  worker, and a study eventually completes. Keep `tests/code/download_manager/test_dm_preempt_on_drag.py`
  + the large-batch stability tests green; add tests for first-image-prime and
  drag-debounce coalescing.
- **Clinical guardrail:** this is a download/priority/perception change only. VTK/MPR
  geometry, slice order, orientation, and rendering stay untouched.

## 5. Bottom line
The site's failure is two reinforcing problems: (A) no single-image fast paint, so a slow
link shows nothing and the user re-drags; (B) repeated drags are neither coalesced nor
cheap cross-study, so impatience thrashes the one download slot until nothing completes.
The competitor simply shows one image immediately. The fix is to **prime the first image
(Pillar 1)** — which removes the behavioral trigger using machinery that already exists —
and to **coalesce/soften repeated drag intent (Pillar 2)** so that even an impatient user
can't thrash the slot. Both belong in the unified "view series" pipeline. Recommend
implementing Phase 1 first (flag-gated) and validating it live on the unstable client
link before the deeper priority/unification phases.

## 6. Implementation status (2026-06-17)

### Phase 1 — First-image prime ✅ IMPLEMENTED (flag-gated, default on)
`modules/download_manager/network/socket_client.py` (plugin-mirrored). Pure decision
`_first_image_prime_size(enabled, skipped_count, batch_size, force_single)` →
`(first_batch_size, restore_size)`; for a **fresh** series (`skipped_count == 0`, batch
> 1, not a force-single modality) the first batch is fetched as **one image** so the
existing progressive feed paints a slice in a single round-trip, then the full adaptive
size is **restored after batch 0** (advance uses the old size, so `batch_start` is
exactly 1 — alignment preserved; bulk speed unchanged). Skipped on resume so the R19b
leading-batch skip is untouched. Flag `AIPACS_FIRST_IMAGE_PRIME` (kill switch `=0`).
No data-loss risk: atomic `.part` + resume mean a size-1 first batch is at worst one
extra round-trip. Tests: `tests/code/download_manager/test_first_image_prime.py`
(9 — pure decision + wiring). DM suite **208 passed**; mirrors **389/389**.

### Phase 2 — Global cross-key drag coalescing ✅ IMPLEMENTED (flag-gated, default on)
`PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py` + `_vc_switch.py` (NOT
plugin-mirrored). A single study-agnostic **last-write-wins "current view target"**:
the drop's `_notify_dm_viewed_series` (`_vc_switch.py:377`) and the two
`_trigger_download_if_needed` sites (`:300`, `:691`) now route through
`_coalesce_dm_view_intent(series, want_notify/want_trigger)`, which records the latest
target via the pure `_merge_drag_view_intent(prev, series, notify, trigger)` and
(re)starts a short single-shot timer (`AIPACS_DRAGDROP_DEBOUNCE_MS`, default 350 ms);
`_dispatch_coalesced_dm_view_intent` fires the DM intent for the **final** target only.
Rapid drops of *different* series/studies therefore collapse to one intent — the single
slot is no longer preempted/torn-down per drop. **The view switch is NOT debounced** (it
already ran synchronously in `change_series_on_viewer`); only the DM priority/download
intent waits. Existing per-`(study,series)` cooldowns stay as a second layer. The
async `:691` site is also token-guarded (`_is_request_current`), so only the current
series reaches it. Flag `AIPACS_DRAGDROP_DEBOUNCE` (kill switch `=0` → immediate legacy
path). Tests: `tests/code/viewer/test_dragdrop_coalesce.py` (9 — pure merge + wiring);
viewer drop subset **210 passed** (1 unrelated pre-existing failure,
`test_completion_signal_triggers_one_shot_grow_on_non_progressive_viewer`, confirmed via
baseline stash — about `on_series_images_progress`, not this change).

Known trade-off (documented, acceptable): with one global target for the one download
slot, two viewports each dropped a *different* series within the same 350 ms window keep
only the last as CRITICAL (the others still download at normal priority — no lost data,
just lost force-promotion). This matches the `MAX_CONCURRENT_STUDIES = 1` reality.

### Phase 1b — Rich download notification on the waiting spinner ✅ IMPLEMENTED (flag-gated, default on)
The waiting spinner now shows a **rich, reassuring loading state** so a slow/dropping link
never reads as a blank "is it stuck?" wait — removing the re-drag trigger even before the
first image lands. Four fields, all of which the user requested:
- **Series identity** — "MR · Series 4 · T2 FLAIR" (`_resolve_series_identity` from viewer
  metadata, falling back to the home panel's `_server_series_info`). Clarifies *which* series
  is loading, especially with multiple viewports/drops.
- **Status + percent** — "Downloading 12 of 25 · 48%" → "Finalizing…" (`_format_download_progress`).
- **Progress bar** — a thin determinate bar in the minimal overlay (`set_loading_details(fraction=…)`);
  hidden for indeterminate states.
- **Speed · ETA · elapsed** — "1.2 img/s · ~8s left · 5s elapsed" (`_compute_download_rate_eta`
  smoothed from the first observation + `_format_download_detail`).
- **Connection state** — "Connecting…" → "Waiting for server…" → "Slow connection — still
  trying…" / "Receiving slowly…" (`_connection_state_text`), **inferred** from progress
  staleness by a self-stopping watchdog QTimer (`_dl_watchdog_tick`, 2 s) armed when the wait
  begins (`_begin_download_wait`). No new cross-layer signal — robust on the flaky link.

Plumbing: `loading_overlay.py` minimal `AiPacsLoadingOverlay` grew an identity line, a
`QProgressBar`, and a detail line + a structured `set_loading_details(title/status/detail/
fraction)`; `ViewportSpinner.set_loading_details` (`loading_spinner.py`, **plugin-mirrored**)
delegates to it (or the legacy fallback spinner). `_vc_progressive.py` computes the fields and
pushes them from `on_series_images_progress`, **isolated in try/except** so a status update can
never disturb the progressive-display/grow pipeline (the partial-stub guard tests rely on this).
Flag `AIPACS_DOWNLOAD_PROGRESS_TEXT` (kill switch `=0`); thresholds env-tunable
(`AIPACS_DL_SLOW_AFTER_S`, `AIPACS_DL_STALLED_AFTER_S`, `AIPACS_DL_WATCHDOG_INTERVAL_MS`). Pure
UI — no render/geometry. Tests: `tests/code/viewer/test_download_progress_text.py` (20 —
formatters + rate/ETA + identity + connection state + viewport matching + wiring). Viewer drop
subset **239 passed** (1 unrelated pre-existing failure).

**Future (real retry counts):** the connection state is inferred from progress staleness, which
covers the "is it stuck?" case. Exact retry/reconnect attempt numbers ("retry 2 of 10") would
need the download subprocess/coordinator to emit a state signal up to the viewport — a separate,
larger cross-layer change; deferred.

### Staged — not yet implemented (need live validation / deeper DM work)
- **Phase 3 — settle-then-switch cross-study preemption.** Phase 2 reduces the
  *frequency* of preempts (N drops → 1); softening the remaining cross-study teardown
  (prefer a batch-boundary `.critical_intent.json` yield over a subprocess kill) is a
  deeper DM-coordinator change to do after Phase 2 proves out live.
- **Phase 4 — unify drag-drop onto the view-intent / DownloadPlan + single-flight slot**
  (with the unified-pipeline work).

### How to validate / revert
Live on the unstable client link (human relaunches the source build): drag a fresh CT/MR
series → first image should appear in ~one round-trip (watch `download_diagnostics.log`
for `⚡ First-image prime`); then drag several different series rapidly → only the final
series should be promoted/started, and a study should complete instead of perpetually
re-starting. Watch the viewport spinner show a live "Downloading N of M images…" count.
Revert any phase instantly with `AIPACS_FIRST_IMAGE_PRIME=0` / `AIPACS_DRAGDROP_DEBOUNCE=0`
/ `AIPACS_DOWNLOAD_PROGRESS_TEXT=0` (each restores byte-identical legacy behavior).
