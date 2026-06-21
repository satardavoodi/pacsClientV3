# Pipeline analysis — not-downloaded study → thumbnail → drag → import → decode → display → cache

**Date:** 2026-06-21
**Branch/commit:** `beta-version` @ `56ca5eec`
**Scope:** the single end-to-end pipeline requested. READ-ONLY analysis — **no code was changed.**
**Hard requirement under test:** the series the user drags must be the exact series imported, decoded, displayed and cached — never a fallback to another tab/study/series/stale path.

## TL;DR

The pipeline is well-architected and, for **offset keys (previous-exam / secondary-study series), it is correct** — today's logs show those always resolving to their own study via the 2026-06-21 "entry-authority" fix. **But a real wrong-study load is reproducing in the latest logs for PRIMARY (current-study) series**: on patient **44030**, after viewing a Previous Exam, dragging a *current* series (`key=1`, `key=2`) loaded it from the **previous exam's** study folder (`...089` = study 43373), not from 44030's folder (`...0173`).

- **Confirmed (not hypothetical):** `[VIEWPORT-LOAD-TRACE] dropped_key=1 -> study_path=...352100000089 disk_series=1 ms_resolved=False primary=...20260530112945.0.173` — dropped a primary key, loaded from the previous study. Reproduced in two sessions (pids 704752 @ 21:41, 723748 @ 22:56).
- **Trigger:** it only happens when `ms_resolved=False` for a primary/bare key **and** the tab `study_path` has been poisoned by a prior previous-exam drop.
- **Root cause (high-confidence, from code + log signature):** the primary study's slot-0 entries can be **missing from `_server_series_info` after the multi-study rebuild**, so the entry-authority resolver has nothing to honor and the loader falls back to the poisoned tab path. The 2026-06-21 fix is intact and works *when the entry exists*; the gap is **upstream** — the entry can be absent.
- This is a **same-person, wrong-study/wrong-series mis-display** (Previous Exams are the same real patient under a different Patient ID), not a cross-patient leak. It is still a clinical-correctness defect: the radiologist drags the current series and sees the prior exam.

---

## 1. The pipeline as-built (responsible code areas)

| # | Stage | Owner (file:line) | Identity carried |
|---|-------|-------------------|------------------|
| 1 | Double-click open of a **not-downloaded** study | `home_ui/patient_table_widget.py:2022` `_on_patient_double_clicked` (cancels single-click timer); `_hp_patient_open.py:819` `_on_patient_double_clicked_async` → STEP 3.5 `:1093` `start_priority_download_immediately` | Tab opens immediately; per-study download queued under each study's **own** `study_uid` + server-verified `patient_id` (`:1165-1208`). Cross-patient skip `:1165-1176`. |
| 2 | Thumbnail load | Home panel: `_hp_search.py:1366` `show_patient_studies` (fast-cache-first gate `:1461`, server `get_study_thumbnails` `:1647`). Viewer sidebar: `_pw_thumbnails.py:86` `set_server_series_info` → `:245` `_load_server_thumbnails_async` | Home panel keyed by `study_uid`; sidebar/store keyed by `(study_uid, series_number)`. Not-downloaded → server socket `GetStudyThumbnails`. |
| 3 | Per-thumbnail metadata identity | `_pw_thumbnails.py:86` `set_server_series_info` (single-study: bare key, **no** `_orig_series_number`/`series_path`); `:462` `_rebuild_multistudy_series_index` (multi-study: offset keys, stamps `study_uid`/`_orig_series_number`/`series_path`/`_study_slot`) | Multi-study entries are self-contained; single-study entries depend on the (unambiguous) tab path. |
| 4 | Drag payload | `thumbnail_manager.py:616-632` `DraggableButton.mouseMoveEvent` | **Bare integer only** — `mime "application/x-aipacs-series-number" = str(self.series_number)`. No `series_uid`/`study_uid`. For multi-study this integer is the **offset key**. |
| 5 | Drop in viewport | FAST: `qt_fast_container.py:850` `dropEvent` → `_extract_series_number` `:816`. VTK: `_vw_dragdrop.py:198` `dropEvent` → `:46`. Both → `change_series_on_viewer(series_index, force_reload=True)` | The bare key, unchanged. `force_reload=True` bypasses same-series no-op + cache read. View switch is immediate; only the DM/download intent is debounced (`_coalesce_dm_view_intent`, `_vc_load.py:1812`). |
| 6 | Import / resolution | `_vc_load.py:723` `_load_single_series_on_demand`; **entry authority** `:81` `resolve_entry_study_location` (gate `:443-452`, every key); fallbacks `:461-499` (stable slot) + `:241` `_resolve_plain_series_study_path`; canonical identity `:1780` | Resolves disk from the series' OWN entry **iff** the entry has both `series_path` AND `_orig_series_number`. Otherwise → tab-level `study_path`. |
| 7 | Decode | `lightweight_2d_pipeline.py:2420` `_decode_slice` (`pydicom.dcmread` `:2453`); not-downloaded resume `_vc_progressive.py:1192` `_maybe_resume_awaiting_from_disk`; progressive uid-bind `:962` `display_key_awaiting_series_uid` | Decodes by file **path** (study+series scoped). Progressive binds DM progress to the awaiting display key via globally-unique `series_uid`. |
| 8 | Display | `lightweight_2d_pipeline.py:1452` `get_rendered_frame` → `:2152` `_render_frame_uncached`; lifecycle `_vc_switch.py:1509` `_arm_spinner_timeout` | Renders the currently-bound series' slices. |
| 9 | Cache | Frame LRU `lightweight_2d_pipeline.py:1777` key=`(idx, ww, wc, filter)`; pixel LRU key=`idx`; L2 disk `:467` key=**file path**; thumbnail store `thumbnail_store.py:88` key=`(study_uid, series_number)`; ZetaBoost RAM `cache_engine/widget.py:64` key=**bare `series_number`** (guarded by `_vc_cache.py:219` `[CACHE-STUDY-MISMATCH]`) | See §5 — cache is **not** the failure point here, but the ZetaBoost RAM key is the one non-study-scoped key (guarded + fail-open). |

**Defensive layers for "exact series" (all present and, in isolation, correct):** (1) entry authority `resolve_entry_study_location`; (2) stable-slot / plain-key fallback; (3) cache study-match guard. Verified against `docs/reports/DRAG_LOADS_EXACT_SERIES_2026-06-21.md`.

---

## 2. Evidence from the latest logs (the smoking gun)

`AIPACS_VIEWPORT_LOAD_TRACE=1` was on, so every drop logged its final resolution. Latest trace window: **2026-06-20 21:41–22:56** (today's `app.log` shows 16 `[MULTI-STUDY LOAD]` lines resolving correctly; the wrong-study drops are in `viewer_diagnostics.log`). Patient **44030**, primary study `...20260530112945.0.173`. Trace fields: `dropped_key → study_path | disk_series | ms_resolved | primary`.

**Session pid 704752 — the failure sequence:**

```
21:41:31  key=1        -> ...0173            disk=1   ms_resolved=False  primary=...0173   ✅ (tab path still clean)
21:41:37  key=1000002  -> ...352100000089    disk=2   ms_resolved=True   primary=...0173   ✅ previous-exam (entry-authority) — POISONS tab path to ...089
21:41:41  key=1000003  -> ...352100000089    disk=3   ms_resolved=True   primary=...0173   ✅ previous-exam
21:41:47  key=1        -> ...352100000089    disk=1   ms_resolved=False  primary=...0173   ❌ CURRENT series 1 loaded from PREVIOUS study 43373
21:41:51  key=2        -> ...352100000089    disk=2   ms_resolved=False  primary=...0173   ❌ CURRENT series 2 loaded from PREVIOUS study 43373
```

**Session pid 723748 — identical pattern** (22:56:26 key=1 ✅ → 22:56:30/34 previous `1000002/1000004` ✅ poison → 22:56:38 key=1 ❌ `...089` → 22:56:43 key=2 ❌ `...089`).

**Session pid 719172 — the SAME patient, healthy:** after a previous-exam drop poisoned the path, primary `key=3` (21:51:35) and `key=2` (21:52:06) came back **`ms_resolved=True` → `...0173`** ✅. So the entry-authority fix *does* protect primary keys — **when the primary entry exists and is stamped.**

**Interpretation:** the difference between broken and healthy sessions is purely `ms_resolved` for the primary/bare key. `ms_resolved=False` means `resolve_entry_study_location` returned `(None,None)` → the dragged primary key had **no stamped entry** in `_server_series_info`, so the loader fell to the tab `study_path`, which the previous-exam drop had poisoned to `...089`. `...089` = study **43373** (confirmed by `DRAG_LOADS_EXACT_SERIES_2026-06-21.md` line 36, which records `...30000026052404...089(43373)` as the same wrong-study path), a Previous Exam of 44030.

Supporting counts (latest rotations): `[MULTI-STUDY LOAD]` 16 (app.log, all correct entry-authority), `VIEWPORT-LOAD-TRACE` 21 (viewer log, includes the 4 wrong loads above), `CACHE-STUDY-MISMATCH` **0**, `cross_patient_skip` **0**.

> Why `CACHE-STUDY-MISMATCH=0` does **not** clear this: the cache guard compares the cached entry's study against *the study the key currently resolves to*. Here the **resolution itself** is wrong (key 1 resolves to `...089`), so the cache agrees with the wrong resolution — no mismatch is logged. Also, drag uses `force_reload=True`, which skips the cache read entirely (`_vc_load.py:582-590`). The cache is not the culprit and its guard cannot catch this class.

---

## 3. Root cause (high-confidence hypothesis)

The 2026-06-21 entry-authority fix requires the dragged key to have an entry in `_server_series_info` carrying **both** `series_path` and `_orig_series_number`. The failure is that, for the primary study, **that entry can be missing entirely after the multi-study rebuild**:

1. `set_server_series_info` buckets series into `_studies_series` keyed by each series' own `study_uid`, and **skips any series with no `study_uid`** — `_pw_thumbnails.py:181-183`:
   ```python
   study_uid = str((series or {}).get('study_uid') or '').strip()
   if not study_uid:
       continue            # <-- series with no study_uid never enters the studies index
   ```
2. When a Previous Exam is merged, the tab becomes multi-study and `_rebuild_multistudy_series_index` runs and **replaces** the map — `_pw_thumbnails.py:559-560` `if new_info: self._server_series_info = new_info`. `new_info` is built **only** from `_studies_series` buckets (`:533-557`). For the primary slot it iterates `studies_index.get(su, [])` (`:537`).
3. Therefore, **if the primary study's series reached `set_server_series_info` without a `study_uid` field**, the primary bucket is empty, slot 0 produces **no** entries, and `new_info` contains only the previous-exam offset keys. The primary's bare keys (`1`, `2`, `3`) are **dropped** from `_server_series_info` (the old single-study entries are overwritten by `new_info`).
4. A later drag of a primary thumbnail (`key=1`) then finds **no entry** → `resolve_entry_study_location(None)` → `(None,None)` → `ms_resolved=False` → fallback to the tab `study_path` (poisoned to the previous study) → **wrong-study load**. This matches the trace exactly (no entry ⇒ `ms_resolved=False` ⇒ `study_path=...089`).

This explains the intermittency precisely: it depends on whether the primary series carried `study_uid` at `set_server_series_info` time (healthy session 719172: they did → stamped → `ms_resolved=True`; broken sessions: they did not → dropped → `ms_resolved=False`). The primary's `study_uid` is normally stamped in the open path (`_hp_patient_open.py:1188-1190`), so the suspect is any path that feeds the viewer primary series **without** that stamp (a thumbnail/series-info refresh, a progressive update, or a previous-exam merge call that re-enters the sink with unstamped primary data).

**This is not a regression of the 2026-06-21 fix** — that fix is intact and works when the entry exists. The defect is the *upstream* possibility of the primary entry being absent, which routes straight into the legacy poisoned-tab-path fallback the fix was meant to retire.

---

## 4. The exact failure point & the invariant at risk

- **Failure point:** `_load_single_series_on_demand` (`_vc_load.py:443-452`) falls back to the tab-level `study_path` whenever `_server_series_info[key]` is missing/unstamped — and on a multi-study tab that path may belong to a previously-viewed study.
- **Upstream cause:** `_rebuild_multistudy_series_index` can emit a `new_info` that omits the primary study's entries because the studies-index bucketer dropped primary series lacking `study_uid` (`_pw_thumbnails.py:181-183`, `:533-560`).
- **Invariant violated:** "a dragged series always loads from its own study folder; resolve from the series' own entry, never from the tab `import_folder_path`/`study_path`" (`DRAG_LOADS_EXACT_SERIES_2026-06-21.md` §Invariants). When the entry is absent, there is nothing to resolve from and the invariant cannot be honored.

---

## 5. Secondary findings (in scope, lower severity)

- **Drag payload is a bare integer (`thumbnail_manager.py:629-631`).** Exactness depends *entirely* on (offset-key uniqueness + stable slot order + the entry existing in `_server_series_info`). The payload carries **no `series_uid`/`study_uid`**, so when the entry is missing there is no self-describing identity to fall back to — the single weakest link in the chain and a direct contributor to §3.
- **Readiness check uses tab path first.** `_is_series_downloaded` (`_pw_thumbnails.py:955-965`) tests `base_path/series_key` (tab-level) before the entry's `series_path`; for multi-study this is a badge/readiness signal only (the pixel load uses entry authority), but it can mis-report readiness for a same-numbered series.
- **ZetaBoost RAM cache keyed by bare `series_number`** (`cache_engine/widget.py:64`) is the only non-study-scoped cache; guarded by `[CACHE-STUDY-MISMATCH]` (`_vc_cache.py:219`, runs before serving, `:292`) but **fail-open** (serves when study can't be determined). Not implicated in today's logs (FAST path doesn't fill it; drag uses `force_reload`), but it is a latent same-numbered-series hazard.
- **Three parallel drop decoders** (`qt_fast_container.py:816`, `_vw_dragdrop.py:46`, `_legacy_widget.py:3502`) duplicate extract/dispatch — currently consistent, but a maintenance hazard.
- **Download completeness:** `INCOMPLETE_SERIES` ×35 today, all `on_disk=N expected=N+1 missing=1 pagination_safe=True — filling pagination gap`, recovered (`SERIES_COMPLETE` ×349). This is the known pagination off-by-one (safe-pagination gap-fill), not the exact-series bug, but it means a series can briefly display one image short before the gap-fill lands. `Response too large` ×144 is the known large-batch desync (download reliability, not exact-series).

---

## 6. Race conditions across the pipeline (catalogued)

1. **Stamp-vs-drop race (the live defect, §3):** the multi-study rebuild and the primary-series `study_uid` stamping must both be complete before a primary thumbnail is dragged; if the primary bucket was empty at rebuild time, the primary entry is gone and the drag falls back. Time-ordered evidence shows correct→poison→wrong within ~10 s.
2. **Tab-path poisoning ordering:** a previous-exam load sets the tab `study_path`; any later resolution that falls back to the tab path inherits the wrong study. Order-dependent (only after a previous-exam drop).
3. **Secondary-study progress not bridged:** `home_download_service.on_series_progress` filters by opened `study_uid`, so a non-primary study's download progress/completion may not reach the viewer; mitigated by `_maybe_resume_awaiting_from_disk` (`_vc_progressive.py:1192`) + uid-bind (`:962`) — relevant to not-downloaded drops of secondary series.
4. **Drop vs download for a not-downloaded series:** resolution computes the correct folder first; disk empty → `ok=False` → spinner + `_coalesce_dm_view_intent(want_trigger=True)` → progressive populate. Correct by design *provided* the entry exists (same dependency as §3).

---

## 7. Recommended next step — confirm before any change (no fix applied)

Per your instruction, nothing was modified. To convert the §3 hypothesis from high-confidence to proven at the exact line, add **one diagnostic log** (temporary, no behavior change) at the failing fallback and at the rebuild:

1. In `_load_single_series_on_demand` when `ms_resolved=False`, log whether `series_key in self._server_series_info`, and if present, whether the entry has `series_path`/`_orig_series_number`. This distinguishes "entry missing" (the §3 hypothesis) from "entry present but unstamped".
2. In `_rebuild_multistudy_series_index`, log `len(studies_index.get(primary, []))` and the resulting `new_info` slot-0 key count. If slot-0 count is 0 while a previous exam is present, §3 is confirmed.
3. Re-run the exact repro: open 44030, drag a current series (✅), open a Previous Exam and drag one of its series (poison), then drag the current series again — watch for `ms_resolved=False` + `study_path` = previous study.

**Candidate fix directions (NOT implemented — for discussion):** (a) make the studies-index bucketer fall back to `self.study_uid` for series lacking `study_uid` instead of skipping them (`_pw_thumbnails.py:181-183`), so the primary bucket is never empty; (b) have `_rebuild_multistudy_series_index` preserve/re-stamp existing primary entries rather than dropping them when the primary bucket is empty; (c) enrich the drag payload with `series_uid`+`study_uid` so resolution never depends solely on the offset key existing in the map; (d) when `ms_resolved=False` on a multi-study tab, refuse the poisoned tab-path fallback and resolve via `self.study_uid` for a bare key. Each is small and flag-gateable; all preserve single-study behavior. Decision and implementation pending your go-ahead.

---

## 8. Responsible-area index (for the fix phase)

- Open (not-downloaded): `PacsClient/pacs/.../_hp_patient_open.py:819, 1093, 1165-1208`
- Thumbnail metadata sink + multi-study rebuild (**root-cause locus**): `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py:86-218, 181-183, 462-562`
- Drag payload: `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py:616-632`
- Drop handlers: `.../vtk_widget/qt_fast_container.py:816-901`, `.../vtk_widget/_vw_dragdrop.py:46-308`, `.../_legacy_widget.py:3502-3525`
- Resolution (**failure point**): `.../_vc_load.py:81-108 (resolve_entry_study_location), 443-499, 241-292, 1780-1810`
- Cache guard: `.../_vc_cache.py:219-297`
- Decode/progressive/resume: `modules/viewer/fast/lightweight_2d_pipeline.py:2420-2472`, `.../_vc_progressive.py:962-1000, 1192-1281`
- As-built references: `docs/reports/DRAG_LOADS_EXACT_SERIES_2026-06-21.md`, `docs/pipelines/previous-exams.md`, `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`

_No source code was modified during this analysis. Findings 2–4 are confirmed from logs; the §3 root cause is a high-confidence hypothesis pending the one-line diagnostic in §7._
