# Phase 1 stability optimizations — consolidated as-built (2026-07-01)

Consolidation record for the Phase-1 main-thread-blocking fixes from
`docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md`. All three are flag-gated,
default-on, with the legacy path preserved as a kill switch and a guard test. Per-item detail is in
the individual reports; this file is the single guard entry + the collapse ledger.

## Summary of shipped changes

| Fix | Flag (default) | Files | Guard test | Verification |
|---|---|---|---|---|
| **P1.1** thumbnail disk write off the GUI thread (fire-and-forget worker, reuses `save_thumbnail_with_bytes`; caller keeps the canonical path) | `AIPACS_THUMB_SAVE_ASYNC` (on) | `patient_tab/utils/utils.py`, `.../utils/__init__.py`, `home_ui/home_panel/_hp_series.py` | `tests/code/ui_services/test_thumbnail_async_save.py` | **LIVE-verified** pid 193028 — `save_thumbnail` gone from stall traces, no errors |
| **P1.2** cooperative chunking of `refresh_download_statuses` (yields to the event loop between studies; no threads) | `AIPACS_STATUS_REFRESH_CHUNKED` (on) | `home_ui/patient_table_widget.py` | `tests/code/ui_services/test_status_refresh_chunked.py` | offscreen (5/5); **live path not yet exercised** (fires only on Refresh click) |
| **P1.3** progressive/chunked single-study thumbnail-sidebar build (append-in-order; multi-study path untouched) | `AIPACS_SIDEBAR_BUILD_CHUNKED` (on, flipped after visual verify) | `patient_tab/.../_pw_thumbnails.py` | `tests/code/viewer/test_sidebar_build_chunked.py` | **visual-verified** on source build (order/no-flicker/borders) |

**Latest run (pid 62868):** zero errors/tracebacks from all three; `save_thumbnail`,
`refresh_download_statuses`, `build_local_manifest`, `_pw_thumbnails`, `_pw_panels` all absent from
the stall traces.

## Ready-to-paste CLAUDE.md guard entry

> ### Phase-1 main-thread-blocking fixes (P1.1–P1.3, 2026-07-01)
> Main-thread stalls on patient interaction were traced to synchronous GUI-thread work. Three
> flag-gated, default-on fixes (kill switch + guard test each): **P1.1** thumbnail disk write moved
> to a background worker (`AIPACS_THUMB_SAVE_ASYNC`; `save_thumbnail_with_bytes_async` in
> `patient_tab/utils/utils.py`, reuses `save_thumbnail_with_bytes`, caller keeps the canonical path —
> live-verified pid 193028). **P1.2** `refresh_download_statuses` processes studies in event-loop-
> yielding chunks (`AIPACS_STATUS_REFRESH_CHUNKED`, `_refresh_statuses_chunked`; no threads, token
> cancels a stale chain). **P1.3** the single-study thumbnail sidebar (`_render_thumbnails_from_files`)
> appends progressively in order (`AIPACS_SIDEBAR_BUILD_CHUNKED`, `_render_files_chunked`; multi-study
> grouped render UNTOUCHED). Do NOT re-add the synchronous multi-series loops on these paths. Guards:
> `test_thumbnail_async_save.py`, `test_status_refresh_chunked.py`, `test_sidebar_build_chunked.py`.

*(The maintainer should fold this block into `CLAUDE.md` — a direct append was deferred this session
because the mount reported an inconsistent file length, making a safe in-place append unreliable.)*

## Flag-collapse ledger (policy: collapse a flag only after solid, repeated live-verify)

The project's practice is to keep kill switches until a change has baked across multiple clean
sessions; only then delete the env read + legacy branch + re-pin the test. Status:

- **P1.1 `AIPACS_THUMB_SAVE_ASYNC`** — live-verified once (pid 193028). **Collapse candidate; kill
  switch retained** pending one more clean session. Collapse = delete `_THUMB_SAVE_ASYNC` +
  the `if not _THUMB_SAVE_ASYNC: return save_thumbnail_with_bytes(...)` branch (the internal
  dispatch-failure sync fallback already guarantees no dropped thumbnail); update the guard test's
  flag assertions.
- **P1.2 `AIPACS_STATUS_REFRESH_CHUNKED`** — offscreen-verified only; the live path fires **only on a
  Refresh click**, not yet exercised. **Keep kill switch**; exercise Refresh on the next run first.
- **P1.3 `AIPACS_SIDEBAR_BUILD_CHUNKED`** — visual-verified once; it is a *clinical rendering* change.
  **Keep kill switch** through a few more reading sessions before collapsing.

Recommendation: collapse P1.1 first (after the next clean session), then P1.2 once its Refresh path is
live-exercised, then P1.3 after it has run clean across several sessions.
