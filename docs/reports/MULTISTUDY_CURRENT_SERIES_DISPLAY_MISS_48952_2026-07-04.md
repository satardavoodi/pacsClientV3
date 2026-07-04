# Multi-study: current-study series won't display next to a same-numbered previous exam (48952) — 2026-07-04

**Severity:** HIGH — clinical (a current-exam series fails to display; the previous exam stays on
screen). **Status:** FIX IMPLEMENTED (viewport study-identity gate + intended-study stamp),
flag-gated default-on, guard test green offscreen — NEEDS live source-build verify on 48912/48952.

## FIX IMPLEMENTED 2026-07-04 (14:55 trace, sess-18dbcb9b2936) — viewport STUDY-identity gate

Pinned the exact behaviour from the fresh 48912 trace: `change_series_on_viewer(4)` enters with
series=**4**, study=**current** (…300000002), and within the SAME 94 ms call the viewport renders
**1000004** (previous exam) via `qt_fast_container._start_qt_viewer` — with **NO** `change_series(1000004)`
anywhere, and NOT via `_perform_series_switch_optimized` (its diag was silent). So a superseded/stale
re-render (an async apply or a grow/resume watchdog still pointing at the previously-displayed exam)
pushes the previous exam's metadata straight into the render choke point. `_resolve_canonical_series_identity("4")`
is CORRECT (→ current study); the identity is resolved right upstream but **never enforced at the viewport**.

**Architectural fix (identity travels AND is enforced at the viewport boundary):**
1. `_vc_switch.change_series_on_viewer` STAMPS `vtk_widget._intended_study_uid` (+ `_intended_series_key`)
   from `_resolve_canonical_series_identity(series_number)` BEFORE any cache lookup / async load / switch.
2. `qt_fast_container._start_qt_viewer` GATES right before the bridge teardown: if the incoming render's
   `study_uid` differs from the stamped intended study_uid, it SKIPS the render (logs `[IDENTITY-GATE]`)
   and keeps the current image — so a superseded cross-exam render can never stomp the correct series.

**Safe by construction:** gates ONLY on cross-STUDY mismatch → same-study ops (normal switch, paired-MG,
in-place grow, reset) are never blocked; fail-open when either study_uid is unknown (byte-identical
legacy). Kill switch `AIPACS_VIEWPORT_STUDY_IDENTITY_GATE=0`. Combined with the disk-resolution
poison-guard (`AIPACS_PRIMARY_SERIES_POISON_GUARD`, the LOAD half), current series 4 now both resolves
from its own study AND displays without the previous exam stomping it. Guard test:
`tests/code/viewer/test_viewport_study_identity_gate.py` (9 behavioral pass offscreen; 2 source-pins pass
on the real FS — the sandbox FUSE mount truncated the large source files during this session). NEEDS live
source-build verify on 48912/48952 (load previous exam series 4, then current series 4 on the same cell →
current 4 shows; expect an `[IDENTITY-GATE] SKIP` line for the superseded previous render).

## UPDATE 2026-07-04 (14:33, sess-d5da7d00846f) — UNIFIES 48912 + 48952; poison-guard did NOT fix the display half

Fresh 48912 log proves this is the SAME bug as 48952 and that the disk-resolution poison-guard
(`AIPACS_PRIMARY_SERIES_POISON_GUARD`) did NOT fix it — it only fixed the disk half. Evidence:
`change_series_on_viewer` requests were current series **3/4/5/6** (study …300000002); the renders
(`first_image_visible`) were **1000004 / 1000005 / 1000006** — the PREVIOUS exam's offset-key series.
There were NO change_series requests for 1000004/5/6, so the current requests rendered the previous
series. NO `[MULTI-STUDY LOAD]` and NO `primary poison-guard` line fired. So: **requesting current
series N renders the previous exam's series 100000N** — a consistent +1,000,000 remap in the DISPLAY
layer, between `change_series_on_viewer(N)` and `first_image_visible(100000N)`. 48912 and 48952 are ONE
bug (display binds the current plain key to the same-numbered previous offset key), not two. Next: a run
with `AIPACS_SERIES_SWITCH_DIAG=1` shows whether `_perform_series_switch_optimized` receives `N` or
already `100000N` → pins the remap site (click→series resolution vs the fast-cache lookup binding).

## Symptom

Patient 48952 (current MRI exam) + previous exam 48954 (X-ray), same series numbers. Loading the
**current** series 2 into a viewport does not show it — the previous exam remains. Reported persistent
across reloads.

## What the trace PROVES (session sess-712775fd7969, pid 348620)

Two facts, both from `user_data/logs/viewer_diagnostics.log`:

1. **Disk resolution is CORRECT** (the earlier `AIPACS_PRIMARY_SERIES_POISON_GUARD` fix works here).
   - Current series 2 (13:44:05): `change_series_on_viewer series=2 study=…1.3.12.2.1107…300000008`,
     `ViewportLoadRequested series=2 series_uid=…20260702083844…` (current exam), and
     `load_single_series_by_number … load_single_series_total series=2` — **it loaded the current
     study's series 2 off disk.**
   - Previous series 2 (13:43:57, key 1000002): `open_series path=…\1.2.826.0.1.3680043…\2` (previous
     exam). Correct.

2. **The DISPLAY of current series 2 fails.** Immediately after the load:
   - `_get_series_by_number_fast` logs `cache_result=miss` (hot + main + index + full all miss),
   - then `[VIEWPORT_LIFECYCLE] ViewportLoadingStateCleared viewer=0 series=None` — **no
     `first_image_visible series=2`, no `open_series` for series 2.** The render aborted.
   - By contrast the previous exam's series (1000004) logs `_get_series_by_number_fast
     cache_result=main_hit` → `open_series` → `first_image_visible series=1000004` — it renders,
     because it was cached from an earlier display.

So: **it is not disk resolution, not the metadata series_number (line 957 already sets the display
key), and not the same-series no-op.** It is the **display-side FAST cache/index lookup missing a NEW
current-study series on a multi-study tab**, which aborts the render and leaves the prior content.

## Where it lives

`ViewerController._get_series_by_number_fast` (`_vc_backend.py:758`) checks, in order:
hot cache → main cache → `_series_number_to_index` → `_full_cache_get` (line 886). For the freshly
loaded current series 2 (key "2") all four miss. Meanwhile `_load_single_series_on_demand` ran the load
on a **worker thread**, which by explicit contract (lines 900-903) **must not mutate
`lst_thumbnails_data`/`_series_number_to_index`** — it stores into the thread-safe `_full_cache`. The
render then depends on the main-thread lookup finding that worker-loaded payload.

**CONFIRMED locus (2026-07-04):** `_full_cache_get` (`_vc_cache.py:266`) retrieves via
`self.zeta_boost.query(series_number)` — **the ZetaBoost cache is keyed by the BARE display series
number, NOT study-scoped** (its own comment, lines 283-291, documents this exact hazard). But the
sibling key builder `_full_cache_key` (line 215) **is** study-scoped: `return (study_uid,
str(series_number))`. So there are two cache identity schemes in the same layer — a study-scoped
`_full_series_cache` key and a bare-number ZetaBoost key — and the display lookup uses the bare-number
one. On a multi-study tab the current series "2" cannot be cleanly distinguished from a previous-exam
series in the ZetaBoost layer; `query("2")` misses (`[META_CACHE_MISS] series=2` in the log) or the
compensating `_cache_entry_study_matches` guard (line 219, which leans on
`_resolve_canonical_series_identity`) drops it — either way the render aborts.

**Correct structural fix = make the ZetaBoost cache identity study-scoped** (consistent with
`_full_cache_key`'s `(study_uid, series_number)`), so current "2" and previous "1000002"/same-number
are distinct at the cache layer and the compensating study-match guard becomes unnecessary. This is a
change to the ZetaBoost put/get identity used across the viewer — broad blast radius; must be done as a
dedicated pass with a full `tests/code/viewer` run, NOT bolted on here.

## Correct fix direction (structural, no exceptions)

Make the **display cache/index identity is the patient-unique display key end-to-end**: the worker
load must store, and the main-thread lookup must retrieve, the current series under its display key
("2"), so a same-numbered previous-exam series (key "1000002") can never shadow it in `_full_cache` /
`_series_number_to_index`. Fix the *keying*, not add a guard. Then a new current series renders on the
first attempt regardless of an open previous exam.

## Why not patched yet (the SAFE-way constraint)

- The exact cache-storage key mismatch is not yet confirmed (one more read of the `_full_cache`
  put/get path is required — do not guess on clinical display code).
- This is the highest-risk display path (`_vc_backend` FAST cache / `_vc_switch` / `qt_fast_container`).
- A correct fix needs a green verify-lane run (`tests/code/viewer`), which requires a stable sandbox
  (the FUSE mount intermittently truncated large files during this session; it has since recovered).

## Next step (focused pass)

1. Read the `_full_cache` PUT in the load path + `_full_cache_get` keying; confirm the display-key vs
   stored-key mismatch on a multi-study tab.
2. Implement the identity-keyed fix (flag-gated default-on, kill switch), keeping single-study
   byte-identical.
3. Add a guard test that reproduces: current series N must resolve/display distinctly from a
   same-numbered previous-exam series (pure/fs-backed, like `test_primary_series_poison_guard.py`).
4. Verify offscreen (`tests/code/viewer`), then live on 48952.

## Related

`WRONG_STUDY_PRIMARY_SERIES_AFTER_PREVIOUS_EXAM_2026-07-04.md` (the disk-resolution half, live-verified
on 48912); `docs/reports/DRAG_LOADS_EXACT_SERIES_2026-06-21.md`; the multi-study offset-key identity
work in `CLAUDE.md`.
