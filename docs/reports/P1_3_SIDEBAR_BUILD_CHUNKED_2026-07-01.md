# P1.3 — Progressive (chunked) viewer thumbnail-sidebar build (2026-07-01)

Phase 1.3 of `docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md`.
**Flag-gated; shipped default-off, then flipped DEFAULT-ON after source-build visual
verification (2026-07-01)** — order + no flicker + download borders confirmed on single- and
multi-study patients; no errors/tracebacks in the run. Kill switch: `AIPACS_SIDEBAR_BUILD_CHUNKED=0`.

## Root cause

On patient open, `_pw_thumbnails._render_thumbnails_from_files` loops over every cached series
thumbnail and calls `_pw_panels.add_thumbnail_to_thumbnail_layout`, which loads a **QPixmap** and
builds a **thumbnail card widget** per series (both main-thread-only), then adds it to the grid.
For a many-series study that synchronous loop froze patient open (~723 ms; `_pw_thumbnails` →
`_pw_panels` in the stall traces).

## Change (conservative, isolated)

- Extracted the per-series body into a shared helper `_render_one_thumbnail_file(...)` used by both
  the synchronous and the new chunked path (no forked per-series logic).
- New `_render_files_chunked(...)`: appends the thumbnails a few per event-loop tick
  (`QTimer.singleShot(0, …)`), **in the same order** (a progressive *append* — no clear/rebuild, so
  existing cards never flash). A per-render `_sidebar_build_token` cancels a stale chain if the user
  switches patient mid-build. Chunk size `AIPACS_SIDEBAR_BUILD_CHUNK` (default 3); only engages for
  `> 4` series.
- Gate: `AIPACS_SIDEBAR_BUILD_CHUNKED` — **default OFF**. Off → the original synchronous loop
  (behaviour identical). Scoped to the **single-study cached-file render only**; the server-entries
  path and the **multi-study grouped render are intentionally untouched** (strict run-once /
  repaint-suppressed / ordering invariants — a separate, carefully-verified step).

## Why default-OFF (unlike P1.1 / P1.2)

P1.1 (pure I/O) and P1.2 (pure scheduling of an idempotent status badge) were log-verifiable.
P1.3 changes the *timing of clinical image rendering*, and the sidebar has a documented flicker
history (progressive rendering has caused flicker before). Whether it flickers / preserves order /
keeps the download borders correct can only be judged **visually**. So it ships OFF and is flipped
ON only after you confirm it looks right — the sanctioned pattern for a rendering change.

## Why it is safe once enabled

- **Order preserved** (same list, same sequence; `thumb_index` threaded across chunks — the mirror
  test pins 0..N-1 in order).
- **Main-thread rule intact** — QPixmap/widget creation still on the GUI thread; only *when* each
  card is built changes.
- **No clear/rebuild** in this path, so existing cards don't flash (append-only).
- **Token-cancel** prevents a stale build from a previous patient bleeding into a new one.
- **Multi-study path untouched**; kill switch restores the exact prior loop.

## Verification done (offscreen)

- `_pw_thumbnails.py` `py_compile` clean.
- Guard test `tests/code/viewer/test_sidebar_build_chunked.py`: **6 passed** (source-pins +
  mirror-behavioral proving order, `thumb_index` continuity, and token-supersede cancellation).

## Live-verify checklist (source build — VISUAL, human-required)

1. Set `AIPACS_SIDEBAR_BUILD_CHUNKED=1` and relaunch the source build.
2. Open a **single-study patient with many series**. Watch the sidebar:
   - thumbnails appear **in the correct series order** (progressively is fine/expected);
   - **no flicker** of already-shown cards;
   - the **download-status borders** (blue→green) still land on the right cards.
3. Open a **multi-study / previous-exam patient**. The sidebar must look **exactly as before**
   (that path is untouched) — confirm no regression.
4. Run `.venv\Scripts\python.exe tools\performance\kpi_session_report.py --print` — expect
   `_pw_thumbnails` / `_pw_panels` to **drop out of the stall traces** on patient open, decode/TTFI
   unchanged.
5. If all clean → tell me and I flip the default to ON and add the CLAUDE.md as-built note. If
   anything looks off, leave the flag unset (default) — behaviour is unchanged.

## Not included (staged, same visual-verify needed)

- Chunking `_render_thumbnails_from_entries` (server path; also patches `_server_series_info` +
  background DB update — needs end-of-run coordination).
- The multi-study grouped render (`_render_multistudy_grouped`) — strict invariants; separate pass.
- **P1.4** startup `add_AIPacs_tab` (~1.4 s) + theme (~2.5 s).
