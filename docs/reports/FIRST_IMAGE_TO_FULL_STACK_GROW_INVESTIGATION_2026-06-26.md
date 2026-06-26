# Investigation: unreliable first-image → full-stack grow (drag-drop) — 2026-06-26

Three parallel code-mapping passes (grow mechanism / completion-event + isolation / viewport-binding
identity) converge on one primary root cause and a clear, already-proven fix shape.

## Symptom
After the first image of a dropped series displays, the rest of the stack sometimes groups normally,
sometimes after a long delay, sometimes never, and sometimes only after dragging the same series again.

## How the grow is *supposed* to work (FAST viewer)
The transition runs on **two parallel drivers that don't share one source of truth**:

1. **Event-driven (primary):** DM `seriesProgressUpdated(study_uid, series_uid, …)` →
   `home_download_service.on_series_progress` → `widget.series_images_progress.emit(sn, cur, total)` →
   `_vc_progressive.on_series_images_progress` → `_grow_progressive_fast` → `loader.grow()` /
   `bridge.grow()` (raises `_slice_count` + `_available_slice_count` → scroll becomes available).
   Driven by a single-shot 150 ms `_progressive_grow_timer`, armed per progress batch.
2. **Polling watchdog (safety net):** `_dl_watchdog_tick` every **2 s** →
   `_maybe_resume_awaiting_from_disk` → disk scan → resume when files are complete. Only runs while the
   viewport still has `_awaiting_series_number` set.

## PRIMARY ROOT CAUSE
**`home_download_service.py::on_series_progress` hard-returns on `uid != study_uid`** (the bridge is
bound to ONE primary `study_uid`). For a **secondary-study** series — a multi-study patient's
non-opened study, or a Previous Exam under a different Study UID — the progress signal is **dropped
entirely**, so the **event-driven grow never runs**. The viewport then depends *solely* on the 2 s
disk-ready watchdog, which:
- **delays** (2 s poll + 2-tick disk-stability ≈ up to ~4 s before anything grows),
- **never completes** if the expected count is wrong AND the slow download never lets the on-disk
  count stabilize, or if `_awaiting_series_number` never clears,
- and is **recovered by a re-drag**, which re-arms `_awaiting_series_number` and re-resolves the disk
  folder.

This is the **same `study_uid`-filter root cause** as the 47084 real-time-thumbnail bug fixed earlier
this session — but on the **viewer grow lane**, which was the explicitly-deferred follow-up. The
existing `_PROGRESSIVE_UID_BIND` re-key sits *after* the `uid != study_uid` return, so it only fixes
the offset/display-key mismatch for the **primary** study; it does **not** deliver a sibling study's
progress.

Matches the symptoms exactly: primary-study series work (event path fires) = "sometimes normal";
secondary-study series wait on the 2 s watchdog = "long delay"; watchdog conditions unmet = "never
completes"; re-drag re-arms the awaiting state = "must drag again".

## Cross-patient isolation — VERDICT: safe today (the critical safety requirement is met)
Cross-**patient** viewport mis-routing is **not structurally possible** in normal operation:
- every DM signal carries its own `study_uid` (`download_worker.py:42`); the shared worker slot reads
  it from the payload, never a "current study" field;
- all DM per-study state is dict-keyed by `study_uid` (`_pending_progress`, `_completed_series_emitted`,
  `_last_series_number_by_study`, `_tasks`);
- the bridge record is keyed `f"{study_uid}_{id(widget)}"` and every handler re-checks `uid != study_uid`;
- viewer grow state is per-`ViewerController` instance + per-`vtk_widget` attributes; grows only scan
  *this* widget's `lst_nodes_viewer`;
- **no global "selected patient / current series / active viewer"** is read by the grow/progress/
  completion routing (`selected_widget` is used only on the click path, not drag-drop).

The residual structural weakness is **intra-patient, multi-study**: routing keys are the **grid-index
token** + **bare `series_number`**, neither patient/study-scoped. Isolation is held by the bridge
boundary + per-controller node lists (defense-in-depth), not by the keys — which is exactly what the
S0 `SeriesRequest`/`ViewerHandle` spine is meant to make structural. The A1 grid-index reuse is a
**same-tab rebind** hazard (shadow-instrumented), not a two-tabs-open hazard.

## Secondary defects (cause delay/partial even for the primary study)
- **8-slice admit cap per non-terminal grow** + a **900–2500 ms minimum interval** between grows →
  visible stack lags the on-disk count; full count usually only lands on the terminal grow.
- **Terminal pulse skipped** when `_resolve_series_total(sn)` returns 0 (DM-task lookup miss) → stack
  sticks at the last per-slice count.
- **`_resolve_sn` mis-resolution** (uid→number) → grow matches no viewport.
- **Untargeted-deferred / throttle starvation** for a viewport transiently not recognized as interested.
- The watchdog only covers **`_awaiting`** viewports, not "loaded-partial-then-starved" ones.

## FIX DIRECTION
**Primary, targeted, low-risk (direct analog of the shipped 47084 thumbnail sibling fix):** extend the
DM→viewer bridge so a **sibling-study** `on_series_progress` (`uid != study_uid`) is admitted into the
**viewer grow lane** when its globally-unique `series_uid` resolves to a series this patient's tab is
showing/awaiting — re-keyed to the display/offset key (reuse `display_key_awaiting_series_uid` /
`_belongs_to_open_thumbnails`). This makes the event-driven grow fire for secondary studies, so the
stack grows live instead of waiting on (or never reaching) the 2 s watchdog. Flag-gated default-off →
validate → on. Cross-patient isolation preserved (admit only a `series_uid` already mapped to THIS
patient's open series — never from caller/global context). Also emit a real **series-level completion
grow** for siblings (terminal `(sn,total,total)` pulse) so completion finalizes the stack even if
progress was sparse.

**Structural, staged (S3 of the unification plan):** make the grow **request-scoped** by the
`SeriesRequest` identity `(study_uid, series_uid, viewer_handle)` instead of bare `series_number` +
grid-index token — retiring `_PROGRESSIVE_UID_BIND` and the bare-number `_progressive_series` keying,
and funnelling drop / progress / completion / disk-resume through one `ensure_series_displayed`
chokepoint.

## Logging to add (request-scoped, per the spec)
A single structured line per transition carrying: `LoadRequestId` (handle UUID), `patient_id`,
`study_uid`, `series_uid`, `viewport_id`, `files_available`, `files_expected`, and the event
(`first_image`, `regroup_start`, `regroup_end`, `stack_update`, `scroll_enabled`, `skipped_regroup`
+ reason, `stale_mismatch`). Most fields already exist in `_log_viewport_lifecycle`; add `series_uid`
+ the regroup/scroll/skip events.

## FIX LANDED 2026-06-26 — `series_uid` identity routing (fundamental, not an exception)
The bridge no longer routes the grow by the single primary `study_uid`; it routes by the
globally-unique `series_uid` the metadata already carries, so **primary and secondary studies
travel the identical path**.

- NEW `ViewerController.display_key_for_active_series_uid(series_uid)` (`_vc_progressive.py`,
  not mirrored) — generalises `display_key_awaiting_series_uid` to the WHOLE grow lifecycle:
  returns the display/offset key of a viewport AWAITING **or** PROGRESSIVELY DISPLAYING that
  `series_uid` (so the grow keeps flowing after the first image clears the awaiting flag). Matched
  on `series_uid` (numbers collide across studies); built solely from this patient's
  `_server_series_info` → cross-patient safe.
- `home_download_service.py` (not mirrored) `on_series_progress` / `on_series_completed`: when
  `uid != study_uid`, a sibling event is admitted into the **grow lane** ONLY when
  `display_key_for_active_series_uid` confirms a viewport here is actively showing/awaiting that
  `series_uid`, re-keyed to its display key (progress → live grow; completion →
  `_on_series_completed_impl` finalize). The **primary path is byte-identical**. Flag
  `AIPACS_GROW_SIBLING_STUDY` (default on; `=0` = legacy primary-only filter). New `[GROW-SIBLING]`
  logs carry `study_uid`, `series_uid`, `display_key`, `images=N/M`.
- **Isolation preserved/strengthened:** a sibling is admitted only when its `series_uid` already
  maps to a viewport THIS patient's tab is displaying — never from caller/global context. Cross-
  patient mixing remains structurally impossible.
- **Backend-agnostic:** the bridge + identity resolution are FAST/VTK-neutral.
- Tests `tests/code/viewer/test_grow_sibling_study.py` (6 green; 39 green with thumbnail-sibling +
  progressive-uid-bind + viewport-lifecycle + resume-livelock). NEEDS live source-build verify on a
  multi-study / Previous-Exam drop: stack grows live + scroll enabled with no re-drag.
- **Residual (not the never-completes cause):** the 8-slice admit cap + 900–2500 ms grow throttle
  still pace the *visible* growth (a few seconds' lag, never a stall); the full request-scoped
  `ensure_series_displayed` chokepoint (S3) that retires the bare-number keying + `_PROGRESSIVE_UID_BIND`
  is the remaining structural consolidation.

## Acceptance check
Open patient A, drop a (secondary-study) series → first image → stack grows live as slices arrive,
scroll works without re-drag; open patient B, drop another → both grow independently; each viewport
gets only its own series. The primary fix targets exactly the "grows live without re-drag" + "secondary
study works" criteria; isolation is already satisfied.
