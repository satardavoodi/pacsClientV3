# B2 — first-image prime / pagination alignment fix (staged, default-off)

**Date:** 2026-06-21  **Commit base:** `beta-version` @ `56ca5eec`
**Status:** **promoted to default-ON (live-validated 2026-06-21 on an expected=41 series — clean tiling, 0 `INCOMPLETE_SERIES`).** Kill switch `AIPACS_PRIME_ALIGN=0` restores the legacy off-by-one + gap-fill.
**Scope:** download batch loop only (`download_series`). No change to write atomicity, resume, force-single modalities, or the completeness backstop. Pure performance.

## What this fixes

For a freshly-viewed (not-yet-downloaded) series, the first-image **prime** fetches slice 1 as a size-1 batch so the viewport paints in one round-trip, then restores the full batch size. The legacy advance left `batch_start = 1` (not a tile boundary), so the server's `batch_index = batch_start // batch_size` re-requested tile 0 and then `batch_start` stepped `1, size+1, 2*size+1, …`. For any series whose instance count **≡ 1 (mod batch_size)** (e.g. 11, 21, 31 with size 10) the **final tile's last instance was never requested in the main loop** — it fell to the `INCOMPLETE_SERIES … filling pagination gap` path, which does a **full series-folder disk re-scan + a separate gap-fill fetch** on a fresh socket. Observed **16×/day** in `download_diagnostics.log` (12× `expected=11`, 4× `expected=21`), always recovered (no data loss) but pure overhead.

## The change

`modules/download_manager/network/socket_client.py` (+ plugin mirror):

1. New flag (default OFF): `_PRIME_ALIGN = os.getenv("AIPACS_PRIME_ALIGN","0") == "1"`.
2. In the prime-restore block (`if _prime_restore_size is not None and batch_idx == 1:`), when enabled, reset `batch_start = 0` so the loop re-tiles cleanly (`0, size, 2*size, …`) and fetches every tile.

Legacy lines preserved (`_prime_restore_size is not None and batch_idx == 1`, `batch_size = _prime_restore_size`) so existing wiring guards still pass.

## Why it is safe (no data-loss risk)

- **Same tiles, no new fetches.** The prime always consumes exactly instance index 0. After it, the next needed index is 1, which is in tile 0, so the correct realignment is `batch_start = 0`. Tile 0 is re-requested (instance 0 is re-sent and **file-skipped**, already primed) and the loop then continues to the final tile — the *same* tiles the legacy path fetched (just the last one via the loop instead of gap-fill).
- **Gap-fill backstop unchanged.** The `INCOMPLETE_SERIES` gap-fill is untouched, so if the realignment ever mis-tiled, completeness is still guaranteed. Worst case of a wrong realign = the gap-fill fires as before (no regression); it cannot drop an instance.
- **Atomic writes unchanged.** Re-sent instance 0 is `.part`→`os.replace` and resume-safe; no torn/duplicate file.
- **Untouched paths:** resume (`skipped_count > 0` → prime never engages), force-single modalities (XA/RF/DR/MG/CR/DX), and single-study/normal series whose count is **not** ≡ 1 (mod size) — for those the fetched-tile set is identical with the flag on or off (proved in `test_prime_align_tile_coverage_math`).
- **Default OFF** ⇒ production is byte-identical until you validate live.

## Verification done (offscreen)

- Syntax OK; plugin mirror synced + **verified 390/390 pairs match**.
- `tests/code/download_manager`: **252 passed** with `AIPACS_PRIME_ALIGN` **unset (off)** and **=1 (on)**.
- New tests in `tests/code/download_manager/test_first_image_prime.py`: flag default-off pin, realign-wired-in-restore pin, gap-fill-backstop-preserved pin, and a tile-coverage arithmetic lock (legacy drops the last tile for 11/21/31; aligned covers all; other residues unchanged).

## Live validation — CONFIRMED 2026-06-21 16:35 (pid 745532, `AIPACS_PRIME_ALIGN=1`)

Series 201, **expected=41** (≡ 1 mod 10 — the exact bug pattern), `download_diagnostics.log`:
`batch_index 0(size1 prime) → 0(size10,skipped=1) → 1 → 2 → 3 → 4(received=1, has_more=False, downloaded=41)` → `SERIES_COMPLETE`, **no `INCOMPLETE_SERIES`**. Session-wide: **0 `INCOMPLETE_SERIES` across 14 completed series** (the pre-fix run had 12 gap-fills, all N≡1). No data loss, no new errors. **→ Safe to promote to default-on.**

## Live validation (do this before promoting to default-on)

1. With the source build running, set `AIPACS_PRIME_ALIGN=1` (env) and restart it.
2. Open a **not-yet-downloaded** study and drag a series whose image count is **11 or 21** (or any `N ≡ 1 mod 10`). Good candidates from today's logs: studies `…300000044`, `…300000047`, `…300000052` had series with `expected=11`.
3. In `user_data/logs/download_diagnostics.log` for that series confirm:
   - `[BATCH_TRACE]` shows `batch_index=0` then `batch_index=1` (clean tiling) — **not** `0` then `0`.
   - **No** `INCOMPLETE_SERIES … filling pagination gap` line for that series.
   - final on-disk count == expected; the viewer shows **all** slices (scroll to the last image).
4. Compare to a flag-off run (you'll see the `INCOMPLETE_SERIES` gap-fill fire). When satisfied, flip the default: change `"0"` → `"1"` in the `_PRIME_ALIGN` definition (and re-sync the mirror).

**Rollback:** unset `AIPACS_PRIME_ALIGN` (or set `=0`) — instant revert to legacy.

## Remaining staged optimizations (not yet implemented)

Per the performance evaluation (`docs/reports/PIPELINE_PERFORMANCE_EVALUATION_2026-06-21.md`), still staged for one-at-a-time live validation:
- **B1** — re-enable safe batch growth (needs server-side stable pagination; biggest not-downloaded latency win; data-loss-risk without the server change).
- **B4** — multi-study DB-first metadata (skip the off-disk header re-scan; needs golden-compare geometry validation).
- **B5** — download↔viewer DB-write contention (write-batching / read-snapshot tuning).
- **B6** — fast-fail the oversized-single-instance `Response too large` case instead of multi-minute retries.
- Safe-tier items B3 (off-thread thumbnail decode) and B7 (prefetch warm) were assessed already-optimal / not worth the guarded-widget risk (see prior turn).
