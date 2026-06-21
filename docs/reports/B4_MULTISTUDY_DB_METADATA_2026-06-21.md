# B4 — per-series DB-first metadata for multi-study (staged, default-off)

**Date:** 2026-06-21  **Commit base:** `beta-version` @ `56ca5eec`
**Status:** implemented, **default-OFF**; offscreen-tested. **Needs live validation** (geometry golden-compare) before promotion.
**Scope:** which `study_pk` is passed to the series loader. No change to slice ordering, IPP/IOP, orientation, or the disk-resolution / exact-series logic. Fail-safe by design.

## What this optimizes

On a multi-study tab, every series load **re-scanned all DICOM headers off disk** (`_build_metadata_headers_only`) even though the downloader already indexed that geometry into `dicom.db`. Measured: `load_single_series_total` avg 248 ms (worst 2.46 s). Single-study already uses the DB-metadata fast path (default `AIPACS_VIEWER_DB_METADATA=auto`); multi-study was excluded.

## Root cause of the exclusion

`_ensure_study_pk_for_db_metadata` (`_vc_load.py:294`) stamps the **primary** study's `study_pk` into `metadata_fixed`, then skips multi-study entirely (`:343-346`) — because an offset-key (non-primary) series belongs to a **different** study, so the primary `study_pk` would read the wrong study's metadata. So multi-study fell through to the disk-header path on every load.

## The change (`_vc_load.py`, not plugin-mirrored)

During the multi-study resolution that already computes each series' own study folder, also capture the series' own `study_uid` (`_ms_study_uid`, from the entry-authority entry or the offset-key fallback). Then, just before the load call, when `AIPACS_VIEWER_DB_METADATA_MULTISTUDY=1` (and the base `AIPACS_VIEWER_DB_METADATA` mode is active), resolve **that study's** `study_pk` (`find_study_pk_with_study_uid`, cached per-widget) and pass it as `study_pk=_effective_study_pk` to `load_single_series_by_number`. When the flag is off, `_effective_study_pk` equals the previous value (the primary's / `None`), so the path is **byte-identical**.

## Why it is safe (geometry cannot regress)

- **Per-`study_pk` self-verify (the existing fail-safe).** `load_single_series_by_number` keeps a `_db_geom_trust_cache` keyed by `study_pk` (`image_io.py:809-812, 2865-2886`): the **first series of each study** is compared DB-vs-disk; on a geometry **match** it trusts the DB for that study, on any **mismatch or error** it falls back to the disk header path (`geometry_match=False -> disk`). Because B4 passes each series' **own** `study_pk`, every study self-verifies independently. Worst case = disk fallback = today's behavior.
- **Default-OFF** (`AIPACS_VIEWER_DB_METADATA_MULTISTUDY=0`) and gated by the base mode (`AIPACS_VIEWER_DB_METADATA=0` disables everything). Flag-off is byte-identical.
- **Exact-series / disk resolution unchanged** — the entry-authority resolution (`series_path`/`_orig_series_number`) and the 2026-06-21 wrong-study fix are untouched; B4 only changes which `study_pk` accompanies the load.
- `study_pk` is consumed **only** as the DB-loader's `study_pk` argument.

## Verification done (offscreen)

- Syntax OK; plugin mirrors verified **390/390** (`_vc_load.py` not mirrored).
- `tests/code/viewer` (targeted): **18 passed** — new `test_db_metadata_multistudy.py` (flag default-off, per-series study_pk wired + used, gated by base mode, per-study_pk auto-verify fail-safe present, per-widget cache) + `test_drag_loads_exact_series.py` + `test_primary_bucket_fallback.py`.
- Flag-off is byte-identical, so the broader green suites (398 download+ui, 256 download) are unaffected.

## Live validation (please run before promoting to default-on)

1. **Shadow first (observe-only):** relaunch with `AIPACS_VIEWER_DB_METADATA_MULTISTUDY=1` **and** `AIPACS_VIEWER_DB_METADATA=verify`. In verify mode the loader builds BOTH maps, **logs a golden compare, and DISPLAYS THE DISK MAP** (no behavior change). Open a multi-study patient and drag several series across studies. In `app.log`/viewer logs confirm `[H1_DB_METADATA_MS]` lines and `[DB_METADATA_AUTOVERIFY] … geometry_match=True` for each study (no `geometry_match=False`).
2. **Then enable the speedup:** relaunch with `AIPACS_VIEWER_DB_METADATA_MULTISTUDY=1` and the default `AIPACS_VIEWER_DB_METADATA=auto`. Confirm correct images and faster multi-study loads (no per-series header re-scan; `itk_pipeline_total` duration drops).
3. **Rollback:** `AIPACS_VIEWER_DB_METADATA_MULTISTUDY=0` (or `AIPACS_VIEWER_DB_METADATA=0`).

## Plan status

- ✅ **B2** prime alignment — default-ON (live-validated).
- ✅ **Wrong-study** drag fix — default-ON (live-validated).
- ✅ **B6** oversize fast-fail — default-off, available.
- ✅ **B4** (this) — implemented default-OFF, fail-safe; **needs the verify-mode live check** above.
- ⏸ **B5** (download↔viewer DB-write contention), **B1** (batch growth — needs server-side stable pagination) — still staged.
