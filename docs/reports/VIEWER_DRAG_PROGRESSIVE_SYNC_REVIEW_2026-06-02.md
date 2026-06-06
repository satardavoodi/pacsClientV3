# Viewer drag-and-drop / progressive-download sync — review + fix (2026-06-02)

Review of the two requested pipelines, grounded in the live `viewer_diagnostics.log`
(series 202) and the FAST loader/bridge code.

---

## Pipeline 1 — progressive sync during download (review: sound)

**Path:** download subprocess writes `.dcm` (atomic `.part`→`os.replace`) →
`series_images_progress` signal → `_on_series_images_progress_impl`
(`_vc_progressive.py`) → `_grow_progressive_fast` → `bridge.grow()` →
`pipeline.refresh_file_list()` (`lightweight_2d_pipeline.py`).

Findings — the mechanism is **optimized and stable**:
- **Incremental append is reliable.** Each `refresh_file_list` collects a background
  header scan (≤16 headers/dispatch, ~2 ms `os.scandir` on the main thread; `dcmread`
  off-thread) and flushes new slices into the existing volume **without reloading** —
  cached pixels/frames are preserved and remapped (`_remap_indexed_caches_after_resort`),
  so no full reload or flicker.
- **Smoothness is protected.** The grow is **8 ms-budgeted** per tick and the
  actively-viewed series **bypasses the UI-admission throttle** (`_has_viewer_interest_for_series`
  in the admit gate) so it grows on every chunk while background series stay throttled.
- **No unnecessary reloads.** Grows are additive; `grow()` snapshots old paths before
  refresh to remap interleaved instance numbers correctly (no wrong-slice placement).

The one weak point was **completion catch-up** — see Pipeline 2.

## Pipeline 2 — drag an undownloaded series → auto-load (BUG → fixed)

**Symptom:** drag a not-yet-downloaded series into a viewport; it goes Critical and
downloads, but after the download finishes the viewport stays **partial** (or the loader
spins then stops); the user must re-drag.

**Root cause (live-confirmed, series 202):**
```
final grow (qt_bridge) on download-complete series=202 count=26
download-complete but grow incomplete series=202 count=26 expected=241
completion-verify: EXHAUSTED
progressive-fast: STALE grow series=202 got=38 … (retry 1/5)  … 44 … 50 … 56 … 62 … 68
progressive-fast: STALE-EXHAUSTED series=202 stuck at 68/241 after 5 retries
```
The per-tick grow is bounded by the **≤16-header background scan** (~6 slices/tick live),
but `_STALE_RETRY_MAX = 5` counted **TOTAL** ticks — so a large series can only climb ~5
ticks (~30 slices) before it is abandoned, even though the download already finished and
all 241 files are on disk. The "done-guard completion one-shot" could not recover it: it
just re-enters the **same** capped `_grow_progressive_fast` loop. Layer-3
`completion-verify` (cap 3) exhausts the same way. So nothing drives a large
fully-downloaded series to its full count.

**Fix applied (`_vc_progressive.py::_grow_progressive_fast`):** make the cap count
**CONSECUTIVE NO-PROGRESS** ticks, not total ticks. The retry counter is reset to 0
whenever a tick advances the slice count (`_stale_last_count`). So:
- A series still flushing in from disk makes progress every tick → counter resets → it
  **keeps climbing all the way to the full count** (self-terminating once
  `new_count >= target_visible_count`).
- A genuinely stuck series (no new slices for 5 consecutive ticks — download stalled /
  disk not flushing) still exhausts and hands off to the Layer-4 backstop.
- Each tick remains bounded/non-freezing (8 ms grow budget); the loop cannot freeze or
  spin forever.

This supersedes the earlier `_COMPLETION_VERIFY_MAX_RETRIES 3→15` attempt (reverted) —
it is principled (tied to actual progress) rather than a larger fixed cap, and it does
**not** touch the grow/bridge mechanism or the drag path.

## Related — Issue A: download not *starting* (recommendation, NOT applied)

Separately, the **viewer-drag preempt** is currently **absent** from
`request_critical_series_download` (`_pause_all_active_downloads` not called). It was
implemented 2026-05-31 then **reverted** to shrink the footprint on an open+drag crash
(`right_panel_widget.display_thumbnails_immediately → thumbnail_manager.create_thumbnail_widget`;
see [[download-start-and-sync]] / [[fast-progressive-completion]]). Without it, a dragged
series whose study does **not** hold the single download slot (`MAX_CONCURRENT_STUDIES=1`)
can stall until the current study yields — the "loader spins then stops / never appears"
case. **Recommendation:** re-apply the preempt (pause-for-resume, honoring
[[dm_resource_harmony]]; preempt only when a *different* study holds the slot), but only
with a **live multi-patient restart test**, since this is a download-scheduler change on
the historically crash-prone path. Not applied here because it cannot be live-verified in
this session and must not be shipped blind.

## Verification
- Static: `_grow_progressive_fast` extract-compiles clean; edit present + consistent
  (`_stale_last_count` set/read, cap semantics changed to no-progress). Whole-file
  `py_compile` blocked only by the sandbox mount-truncation artifact.
- **Live (pending restart):** drag a large (200+ image) not-yet-downloaded series into a
  FAST viewport; after the download completes, expect `progressive-fast: STALE grow`
  lines to keep climbing (counter resetting on progress) until `got == expected`, then
  the viewport at the full count — **no** `STALE-EXHAUSTED` while the series is still
  advancing. Confirm a genuinely stuck series still exhausts after 5 no-progress ticks.

## Invariants (do not break)
- The progressive grow must stay **additive + bounded** (8 ms budget, ≤16-header scan);
  never switch completion to a single full reload (freezes the main thread 0.7–1.75 s on
  large series) and never instantiate VTK in FAST mode.
- The STALE retry cap is **consecutive-no-progress**, not total — do not revert it to a
  fixed total-tick cap (re-introduces "stuck at N/total" on large series).
- Self-termination is `new_count >= target_visible_count`; keep it so the loop ends at
  full count.
