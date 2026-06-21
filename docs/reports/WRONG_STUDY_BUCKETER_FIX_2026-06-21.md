# Wrong-study drag fix — primary-study bucket fallback (default-on)

**Date:** 2026-06-21  **Commit base:** `beta-version` @ `56ca5eec`
**Status:** implemented, default-ON; offscreen-tested AND **live-validated 2026-06-21** — across 24 traced drops every `study_path == resolved_study`, and after viewing a Previous Exam the **current** series resolved to the **primary** study (`ms_resolved=True`), not the previous one (`16:36`: prev `1000006/1000007`→`…010`, then current `203/185546005/185610435`→primary `…86523`; `16:58`: prev `1000005`→`…088`, then current `252/253`→primary `…86517`). 0 `CACHE-STUDY-MISMATCH`, 0 ERROR.
**Fixes:** the clinical wrong-study display analyzed in `docs/reports/PIPELINE_DRAG_EXACT_SERIES_ANALYSIS_2026-06-21.md`.

## The bug

On a multi-study tab (current patient + one or more merged Previous Exams), after viewing a Previous Exam, dragging a **current** series sometimes loaded it from the **previous exam's** study folder (verified in logs: current `key=1/2` → `study_path=…352100000089` = study 43373, a previous exam of 44030). Same real person, but the **wrong study/series** is displayed.

## Root cause

`set_server_series_info` (`_pw_thumbnails.py`) buckets each series into the multi-study studies-index keyed by the series' own `study_uid`, and **dropped any series with no `study_uid`** (`if not study_uid: continue`). `_rebuild_multistudy_series_index` then **replaces** `_server_series_info` with a map built only from those buckets. So when the **primary** study's series arrived without an explicit `study_uid`, the primary bucket was empty, the rebuild emitted only the previous-exam offset keys, and the primary's slot-0 bare entries (`1`, `2`, …) were **dropped from `_server_series_info`**. A later drag of a primary thumbnail then found **no entry** → `resolve_entry_study_location` returned `(None, None)` → `ms_resolved=False` → the loader fell back to the tab `study_path`, which a prior previous-exam load had **poisoned** to the previous study → wrong-study load. (This explained the intermittency: the same `key=1` resolved correctly when the primary series happened to carry `study_uid`, and wrongly when they didn't.)

## The change

`PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py` (NOT plugin-mirrored):

- New flag (default ON): `_PRIMARY_BUCKET_FALLBACK = os.getenv("AIPACS_PRIMARY_BUCKET_FALLBACK","1") != "0"`.
- In the studies-index bucketer, a series with no explicit `study_uid` is now attributed to **`self.study_uid` (the tab's primary study)** instead of being dropped; only if there is still no study (no primary either) does the legacy `continue` apply.

With the primary always bucketed, `_rebuild_multistudy_series_index` stamps the primary's slot-0 entries with their own `series_path` + `_orig_series_number` (it already does this for every slot), so a primary-key drag resolves via **entry authority** (`ms_resolved=True`) and loads from the primary study — never the poisoned tab path.

## Why it is safe

- **Foreign series always carry `study_uid`.** Previous-exam series are stamped by `build_download_payload`/the merge path, and the cross-patient guards depend on `study_uid`. So a series lacking `study_uid` on a patient tab is the **primary's own** — attributing it to the primary is the correct default, not a cross-study leak.
- **Cross-patient isolation unchanged.** The four automatic guards (open / reconcile / resync / back-fill) still re-validate the server owner; this fix only ensures the primary's *own* series are present in the index.
- **Single-study tabs are byte-identical.** If the primary series carry `study_uid` (normal), nothing changes. If they don't, the index gets a one-entry primary bucket (`len == 1`) → still the single-study path (`is_multi_study` is `len > 1`); the rebuild does not run. No grouping/behavior change.
- **Default-ON with kill switch** `AIPACS_PRIMARY_BUCKET_FALLBACK=0` for instant revert.
- Complements (does not replace) the 2026-06-21 entry-authority fix: that fix loads a dragged series from its **own** entry; this fix guarantees the entry **exists** so entry-authority can fire for primary keys.

## Verification done (offscreen)

- Syntax OK; plugin mirrors verified **390/390** (`_pw_thumbnails.py` is not mirrored).
- `tests/code/download_manager` + `tests/code/ui_services`: **398 passed, 1 skipped**.
- `tests/code/viewer` (targeted): **21 passed** — incl. the new `test_primary_bucket_fallback.py` and the existing `test_drag_loads_exact_series.py` / `test_progressive_uid_bind.py`.

## Live validation (please run once)

1. Relaunch the source build with `AIPACS_VIEWPORT_LOAD_TRACE=1` (the fix itself is already on).
2. Open patient **44030**, view a **Previous Exam** series, then drag a **current** series into a viewport.
3. In `viewer_diagnostics.log` confirm the current (bare) key now shows **`ms_resolved=True`** and a `study_path` equal to the **primary** study (`…20260530112945.0.173`), not a previous-exam study (`…089`/`…057`/`…552`). The displayed image must be the **current** series.
4. Kill switch (revert): `AIPACS_PRIMARY_BUCKET_FALLBACK=0`.

## Plan status

- ✅ **B2** (prime alignment) — live-validated, **default-ON**.
- ✅ **B6** (oversize fast-fail) — default-off, available (no oversized instance seen to exercise it).
- ✅ **Wrong-study fix** (this) — default-ON, **needs live GUI confirmation**.
- ⏸ **B4** (multi-study DB-first metadata), **B5** (DB-write contention), **B1** (batch growth, needs server pagination) — still staged.
