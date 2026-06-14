# Resync-on-reopen — server-vs-local study completeness (45611)

**Example:** patient/study `45611` (a **multi-study** patient: an MR study
`…30000026060804254275800000078` + a DOC study). The MR study was opened/received
earlier with **6 series**; over the next days the device pushed more, growing it to
**10 → 18 series** on the server. On reopen the workstation kept showing the stale
local set; the newly-added sequences were never received or shown without a manual
cache wipe.

**Status:** root cause confirmed from the live logs + code (2026-06-14); fix
applied + headless-verified. Live 45611 validation pending (recipe below).

This is the **multi-study sibling** of `BUG_STALE_SERIES_ON_SERVER_UPDATE_44113.md`.
44113 fixed the **single-study** double-click / Download paths; 45611 exposes the
gap that remained for **multi-study** patients and the **single-click home** paths.

---

## Root cause (log + code confirmed)

`download_diagnostics.log` for `…078`:

```
2026-06-09 14:29  right_panel_cache_gate  local_thumbs=6 server_series=6 grew=0 → cache_hit (6)
2026-06-14 11:35  thumbnail_stubs_scheduled series_count=10  (first open)
2026-06-14 11:37  thumbnail_stubs_scheduled series_count=18  (reopen)
```

The study genuinely grew on the server. Why the home page didn't reflect it:

1. **The single-click "server grew" gate never runs for a multi-study patient.**
   `_hp_series.py::_load_and_display_series_info` (~:434) routes a patient with
   `len(study_uids) > 1` into `_show_grouped_patient_studies` and **returns before**
   the `_server_grew` gate (~:447).
2. **The gate's input is suppressed for multi-study patients anyway.** Both the
   right-panel thumbnail gate (`_hp_search.py::show_patient_studies` ~:1392) and the
   series-list gate read `_server_series_count_by_study`, which is stashed only when
   `total_studies <= 1` (`_hp_series.py` ~:334 / `_hp_search.py` ~:749). That guard is
   deliberate — the patient-aggregate `count_of_series` must NOT be attributed to one
   study (the 44534 false-grew bug). So a multi-study patient has **no** stashed count
   and the gate is permanently blind.
3. **The grouped display only asks the server when nothing is local.**
   `_show_grouped_patient_studies` (~:633) reads thumbnails from the local disk cache
   and falls back to the server `if not study_thumbs:` — once any local thumbnail
   exists, new server series are never fetched.

Net: for a multi-study patient, when one study gains series on the server, the
home-page single-click paths render the stale local cache and never reconcile. Only
double-click open re-enumerates (44113), and even that falls back to the stale DB if
the first fetch is slow (the 10-then-18 in the log).

---

## The fix (smart check + reveal + background download)

A throttled, background, per-study server completeness check, plus a manual
"Refresh / Sync from server" right-click action. Implemented additively; the
existing gates, the 44534 guard, cross-patient isolation, and the cache-first
responsiveness contract are all preserved.

**Policy (user-chosen 2026-06-14):** Smart check (re-check only when freshness
can't be proven — throttled per study, TTL 5 min) · Reveal + background download ·
Manual refresh in the patient right-click menu.

### Changes
- **`_hp_series.py`** — new `_resync_patient_studies_from_server(patient_id,
  patient_name, study_uids, *, force)`:
  - throttle: `_study_due_for_resync` / `_mark_study_resync_checked`
    (`_study_resync_check_ts`, `_RESYNC_TTL_S=300`); `force=True` ignores throttle
    **and** the env gate.
  - per study: `_get_or_fetch_series_info(..., force_refresh=True)` →
    **cross-patient guard** (`study_info['patient_id'] == pid`, logs
    `resync_cross_patient_skip`) → `_detect_study_growth(server_by_num,
    local_by_num)` using the study's **own** per-series numbers/counts (never the
    aggregate → 44534-safe).
  - on growth: `save_complete_study_info` + `clear_study_cache` + `dm.add_downloads`
    (the resume scan dedups → only missing series/instances download) → re-render.
  - logs `study_resync_check` (study, local vs server series, new/grown series,
    result, forced) — no credentials.
  - wired fire-and-forget into `_load_and_display_series_info` after reconcile (so it
    never blocks first paint), env-gated `AIPACS_RESYNC_ON_REOPEN` (default on).
  - `_on_resync_from_server_requested` handles the manual menu signal (force=True).
- **`_hp_modules.py`** — `_show_grouped_patient_studies(..., force_server_merge=False)`:
  when True, each study also fetches server thumbnails and **merges series not
  already present locally** (dedup by series_number — never duplicate/overwrite), so
  new series are revealed immediately while their images download in the background.
- **`patient_table_widget.py`** — `resyncFromServerRequested` signal +
  `CustomContextMenu` + `_on_table_context_menu` ("Refresh / Sync from server").
- **`_hp_layout.py`** — connects the signal to `_on_resync_from_server_requested`.

### Invariants preserved
- **Fast cache stays the default** — the resync is background + throttled; first
  paint is unchanged (44113 responsiveness contract).
- **44534-safe** — growth uses each study's own server series list, never the
  patient-aggregate `count_of_series`.
- **Cross-patient isolation** — a study whose server owner ≠ target patient is never
  saved/downloaded (same guard as the reconcile loop / open STEP 3.5).
- **No duplicate files** — re-enqueue relies on the DM atomic `.part`→`os.replace`
  resume scan, which pulls only missing instances.
- **No destructive deletes** — sync only adds; never removes local data.

---

## Validation plan (live 45611)
1. `py_compile` + `pytest tests/code/ui_services/test_resync_on_reopen.py` (14 green).
2. Source build; search 45611; single-click it.
3. Expect: local cache paints immediately; within ~1–3 s `study_resync_check
   … result=grew` in `download_diagnostics.log`; the grouped view re-renders with the
   new series; their images download in the background (DM queue), thumbnails fill in.
4. Right-click 45611 → **Refresh / Sync from server** → forces an immediate re-check
   (ignores the throttle); safe to repeat.
5. Confirm: full current series count (18); no duplicate series/files; an up-to-date
   patient reopens with no extra latency (throttle + "current" result, no re-fetch).
6. Regression: a single-study patient and a genuinely-current multi-study patient
   show no spurious "grew"; cross-patient isolation holds.

Disable hatch: `AIPACS_RESYNC_ON_REOPEN=0` (auto path off; manual refresh still works).

**Note:** the other clinic PC runs the frozen installed build — it needs a rebuilt
installer to receive this.
