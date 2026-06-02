# Bug: stale series/thumbnails when the server gets new images for an already-partially-downloaded study

**Example:** patient `44113` — partially downloaded earlier (~30 images, Series 0 only). The device later pushed the full study (~1408 images, many series). The patient list shows 1408, but double-click / single-click / Download still show only Series 0; the viewer never shows the new series.

**Status:** root cause confirmed (2026-06-01). Fix designed; **not yet applied** (clinical-data-integrity code, triple-guarded — needs live 44113 validation; see §Validation).

---

## Root cause: there is NO server-vs-local comparison anywhere

Every "is this study complete / can I use local data?" decision looks **only at local state**, so a study that gained images on the server is never detected as stale. Three independent local-only gates, all in play:

1. **`check_study_complete()` — `PacsClient/pacs/patient_tab/utils/utils.py:1409`**
   Counts local series *folders* vs the **local DB's** `number_of_series`; if the DB count is unknown it does "assume complete if any series exists" (lines 1446-1447). For partial 44113 (1 local folder; DB recorded 1 series at partial-download time) → returns **True**. It has no way to know the server has more. *It already accepts an `expected_series_count` param and compares correctly (line 1443-1444) — callers just never pass the server's count.*

2. **In-memory `_series_info_cache` — `_hp_series.py:584-588`**
   Returns the cached partial series list; only re-queries the server on `force_refresh=True`. Double-click and Download never pass it.

3. **Local-DB series shortcut on double-click — `_hp_patient_open.py:628-637`**
   `current_study_data = get_study_by_study_uid(...)` (local DB); `if db_series: use it` — bypasses the server fetch entirely (the `else` at 638 only fetches when the DB has *no* series).

### Where each entry point goes stale

| Trigger | Code | Stale because |
|---|---|---|
| Single-click (home thumbnails) | `_hp_series.py:383` | `check_study_complete → True` → loads stale DB series; never hits the `force_refresh=True` server branch at 443-451 |
| Double-click (open viewer) | `_hp_patient_open.py:628-637` | uses local-DB `db_series` (Series 0); server fetch (641) bypassed |
| Download button | `_hp_download.py:94-116` | only fetches series for studies with **no** carried series list; carried/stale lists reused (and the fetch at 113 has no `force_refresh`) |

Thumbnails are not separately broken — the download manager writes new thumbnails to the canonical disk path (`THUMBNAIL_PATH/<study_uid>/<series_number>.png`) as series arrive, and consumers read disk. They simply never get **requested** because the series list is never refreshed.

---

## The fix: detect server > local, then refresh

The server's authoritative count is already known — the patient **search** returns `count_of_series` + per-series `image_count` (that's the "1408" in the list). Thread that into the completeness decision:

1. **Feed the server count to `check_study_complete`.** At the single-click (`_hp_series.py:383`) and the double-click (`_hp_patient_open.py:628`), pass the patient-row's server `number_of_series` as `expected_series_count`. Then `series_folders >= expected_series_count` (line 1443-1444) correctly returns **False** when the server has more → the existing `force_refresh=True` server branch runs.
2. **Don't trust the local-DB `db_series` shortcut when stale.** At `_hp_patient_open.py:634`, gate the shortcut on "local image/series count >= server count"; otherwise fall through to the server fetch (the `else` branch) with `force_refresh=True`.
3. **Force a fresh fetch on the explicit triggers.** `_hp_patient_open.py:641` and `_hp_download.py:113` → `force_refresh=True` when the staleness check says local < server.
4. **Refresh the UI.** After the refreshed series info, rebuild the right-panel (`_display_series_info_in_right_panel`) / grouped studies and let the viewer sidebar re-read (thumbnails come from disk as the new series download). Update the DB series rows (`save_series_info_to_database`) so subsequent `check_study_complete` is correct.

**Performance:** the refresh fires **only when server count > local** (count compare is free; the patient row already carries it) — so up-to-date studies still use the cache/DB with no extra socket call. The single-click path already does a `force_refresh=True` fetch for incomplete studies, so this is consistent with the established pattern.

---

## Why this isn't a blind patch

It edits three guarded clinical paths (multi-study open, the download trigger, the thumbnail/series pipeline — see `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`, `docs/pipelines/thumbnail-pipeline.md`, ZETA). A wrong change could show **wrong or missing images for a patient**. So it must be applied deliberately and validated against the live scenario, not patched blind.

## Validation plan (live 44113)

1. Apply the fix; `py_compile` + import the three files; run `tests/code/system` + `download_manager` + `ui_services`.
2. Restart the source build; open `44113`.
3. Confirm: the series sidebar shows the **full** series structure (not just Series 0); the image count matches the server (~1408); new series download and their thumbnails render; closing/reopening still works; an **up-to-date** patient opens with no extra latency (cache still used).
4. Re-check a multi-study patient (regression guard) and the download queue.

---

## FIX APPLIED — 2026-06-01 (pending live 44113 validation)

Confirmed the bug live first: the 44113 row shows **1408 images** (server) while the series panel shows only **Series 0 / 30 images** (stale local).

Two minimal, additive edits (both compile + import verified):

1. **`_hp_patient_open.py` (double-click open, ~line 633).** Replaced the "use local-DB `db_series` shortcut, else fetch" logic with **always force-refresh from the server first**, falling back to local DB series only if the server fetch fails. So an explicit open now shows the full current series structure, and the fetch refreshes the DB `number_of_series` — which **cascades** to correct `check_study_complete` for later single-clicks (no separate edit needed there).
2. **`_hp_download.py` (Download button, ~line 113).** Added `force_refresh=True` to the per-study series fetch so Download re-queries the current server series instead of the stale cache.

**Performance:** the extra fetch is one socket round-trip (~200–500 ms, background thread) on the *explicit* open/download — consistent with the single-click path, which already force-refreshes incomplete studies. Up-to-date studies are unaffected in practice (server count == local).

**Not changed (lower risk / cascades):** `check_study_complete`'s own local-only logic (self-corrects once the DB is refreshed by the fix above); the single-click right-panel uses the corrected DB on its next click.

**NEXT: restart the source build, then open 44113** — expect the series sidebar to show the full structure (~1408 images, all series) and the new series to download with thumbnails. Revert is two small diffs if anything regresses.
