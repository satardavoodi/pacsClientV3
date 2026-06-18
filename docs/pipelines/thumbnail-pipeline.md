# Thumbnail Pipeline — As-Built Reference

**Status:** ✅ Audited and corrected (2026-05-24).
**Scope:** Every place a series thumbnail is produced, cached, or rendered.

> This is a permanent reference + regression-guard. If you touch any thumbnail
> producer or consumer, read the **Regression guardrails** section first.
> Related: `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` (multi-study viewer sidebar).

---

## 1. Storage layers

A series thumbnail is a small PNG (a few KB). Three layers hold it:

| Layer | Where | Notes |
|-------|-------|-------|
| **Disk cache (canonical)** | `THUMBNAIL_PATH/<study_uid>/<series_number>.png` | The single source of truth on disk. |
| **In-memory cache** | `ThumbnailStore` singleton (`modules/storage/thumbnail_store.py`) | Thread-safe LRU, 300 entries / 50 MB, keyed `(study_uid, series_number)`. On a miss it reads the canonical disk path and warms itself. |
| **DB hint column** | `series.thumbnail_path` (TEXT, nullable) | A convenience pointer; populated only by `save_image_as_png`. Treated as a *hint*, never the authority. |

### Canonical path — one definition, no aliases that diverge

* `data_paths.THUMBNAILS_DIR` = `USER_DATA_ROOT/patients/thumbnails`.
* `PacsClient.utils.config.THUMBNAIL_PATH` is an **aliased re-export** of
  `THUMBNAILS_DIR` — same `Path` object, not a copy. Both names are safe.
* `ThumbnailStore` resolves disk fallback against `config.THUMBNAIL_PATH`, so
  the in-memory store and every disk reader agree.
* **Do not** build a thumbnail path from `BASE_PATH` (`= PROJECT_ROOT`, the
  code root). `BASE_PATH/thumbnails` is the *legacy pre-migration* location and
  is empty after migration. This was the print-module bug fixed on 2026-05-24.

---

## 2. Producers (who writes thumbnails)

| Producer | Writes PNG to disk | Writes `ThumbnailStore` | Updates DB column |
|----------|:---:|:---:|:---:|
| Download manager — `executor._save_thumbnails` | ✅ | ✅ (write-through) | ❌ |
| Socket fetch — `save_thumbnail_with_bytes` (`patient_tab/utils/utils.py`) | ✅ | ❌ | ❌ |
| Viewer VTK→PNG — `save_image_as_png` (`utils.py`) | ✅ | ❌ | ✅ |

All three write the **canonical disk path**, so every disk reader and the
`ThumbnailStore` disk-fallback see them. The DB column and the in-memory store
are populated inconsistently — this is acceptable because **every consumer
treats disk as the authority** and the store/column as accelerators only.

---

## 3. Consumers (who renders thumbnails)

| Consumer | Code | Image source |
|----------|------|--------------|
| Main patient-list right panel | `right_panel_widget.py` `_build_pixmap_from_thumb` | Canonical PNG file → base64 fallback. |
| Opened patient viewer-tab sidebar | `_pw_panels.py` `add_thumbnail_to_thumbnail_layout` | **`ThumbnailImageSourceService`** → `ThumbnailStore` → canonical PNG fallback. |
| Tab-title icon (small image by the tab title) | patient tab widget | Canonical PNG file (first series). |
| Print module series list | `printing/ui/printing_widget.py` `_build_series_thumbnail_pixmap` | DB hint → **`ThumbnailStore`** (memory + canonical disk) → DICOM-decode fallback → placeholder. |

`ThumbnailImageSourceService` (`patient_tab/utils/thumbnail_image_source_service.py`)
is the shared read helper: `ThumbnailStore.get_bytes()` first, then
`QPixmap(file_path)`. The file-path fallback is always the correct per-series
path, so a store miss (e.g. a multi-study non-primary series whose store key
cannot match the widget's primary `study_uid`) degrades cleanly to a direct
disk read — never to a blank thumbnail.

---

## 4. Changes applied 2026-05-24 (thumbnail audit)

1. **Print module — unified source + correct directory.**
   `_build_series_thumbnail_pixmap` Tier 1.5 used
   `Path(BASE_PATH)/"thumbnails"/...`, the legacy code-root location, which
   almost always missed and forced the slow Tier-2 full-DICOM decode on the UI
   thread. It now resolves through `ThumbnailStore` (memory + canonical disk)
   and keys on the series' own `study_uid` for multi-study correctness.

2. **Viewer-tab sidebar — routed through the unified source.**
   `_pw_panels.add_thumbnail_to_thumbnail_layout` did `QPixmap(file_path)`
   directly. It now calls `ThumbnailImageSourceService.load_pixmap()`, so the
   sidebar shares the in-memory `ThumbnailStore` populated by the download
   write-through. The service's file fallback guarantees no regression.

3. **Multi-study flicker + ordering** (same day, first pass) — see
   `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` §"Follow-up fixes".

4. **Viewer-tab sidebar latency — faster deferred-retry poll.**
   On a cache miss while a heavy download is active,
   `_load_server_thumbnails_async` defers the sidebar thumbnail load
   (`should_defer_noncritical_open_network`) and polls the local cache via
   `_schedule_deferred_server_thumbnail_retry`. The poll interval was a flat
   **700 ms**, so the sidebar lagged the main page by up to 700 ms even
   though the download warms the (tiny) thumbnail cache within a few hundred
   ms. The retry is now **150 ms for the first 8 ticks** (≈1.2 s of dense
   polling) then 700 ms for the slow-download tail — same ~8 s total budget,
   but the common case renders ~150–300 ms after the cache is ready. Each
   tick is only a cheap on-disk check; the heavy-download throttle policy
   itself is unchanged.

---

## 5. KPI summary

* **Loading speed** — Cached PNGs are a few KB; disk reads are sub-millisecond.
  Viewer sidebar and print also hit the in-memory store. Print's slow
  DICOM-decode path is now a rare last resort.
* **Stability** — `ThumbnailStore` is fully thread-safe; multi-study rendering
  is gated; renders are repaint-suppressed.
* **UI smoothness** — Multi-study previews render immediately (no progressive
  flicker); grouped sidebar is numerically ordered.
* **Cache behavior** — One canonical disk dir; in-memory LRU bounded by entries
  and bytes; disk-fallback warms the store automatically.
* **Database usage** — `series.thumbnail_path` is a hint only; consumers never
  depend on it being populated.
* **Disk usage** — Single dir, small files; cleanup managers exist
  (`modules/storage/*cleanup*`).
* **Repeated access** — Sidebar/print served from memory after first read.
* **Multi-study** — Offset-key sidebar (see multi-study doc); print and tab
  icon resolve per-study paths.

---

## 6. Regression guardrails — read before touching this area

1. **Disk is the authority.** Every consumer must resolve to
   `THUMBNAIL_PATH/<study_uid>/<series_number>.png`. The DB column and
   `ThumbnailStore` are accelerators — never the sole source.
2. **Never use `BASE_PATH` for thumbnails.** `BASE_PATH` is the code root.
   Thumbnails live under `USER_DATA_ROOT` (`THUMBNAIL_PATH` / `THUMBNAILS_DIR`).
3. **Read through `ThumbnailImageSourceService`** where practical — it keeps the
   memory-first / disk-fallback policy in one place.
4. **`make_pixmap_from_bytes` is main-thread only.** Call it on the Qt main
   thread (QPixmap construction is not thread-safe).
5. **A store miss must fall back to the file path**, which is the correct
   per-series path — especially for multi-study non-primary series whose store
   key cannot match the widget's primary `study_uid`.
6. **Do not make a consumer depend on the DB `thumbnail_path` column** being
   populated — only `save_image_as_png` writes it.

## 7. Known non-blocking follow-ups

* The main-page right panel (`right_panel_widget._build_pixmap_from_thumb`)
  still reads the canonical PNG directly rather than via `ThumbnailStore`.
  Correct and fast (tiny files); could be unified later for symmetry.
* `ThumbnailPanel` (`patient_tab/ui/patient_ui/thumbnail_panel.py`) is a legacy
  class that is never instantiated — the live sidebar is built inline in
  `_pw_panels.py`. Left in place (removing it has no functional benefit and
  carries risk); do not wire new code to it.
* The print module's Tier-2 DICOM-decode fallback still runs on the UI thread.
  It is now rarely reached; moving it to a worker is optional polish.

---

## 8. Right-panel refresh / server-grew gate (2026-06-01 → 2026-06-02)

The main-page right-panel thumbnails for a clicked patient are rendered by
**`show_patient_studies` in `_hp_search.py`** (~:1230). It is a *fast-cache-first*
path: it builds a payload from the local disk cache
(`_build_cached_thumbnail_payload` → canonical PNGs) and displays it **without a
server call** whenever possible. A server thumbnail fetch
(`get_study_thumbnails(include_base64=True)`, which pulls every series and warms the
disk cache) only runs when the cache is judged stale/incomplete.

The staleness decision is the **server-grew gate** (~:1240–1266). Because the local
completeness checks are all local-only (`check_study_complete` makes no server call),
a study that gained series on the server would otherwise pin its stale partial cache
forever. The gate compares a **server series count** against the **local thumbnail
count** and, when the server has more, skips the cache once and falls through to the
server fetch.

Inputs to the gate:

* **`self._server_series_count_by_study[study_uid] = count_of_series`** — the server's
  series count, stashed as the patient list loads (`_add_socket_patient_to_table`,
  `_hp_search.py`) and on single-click reconcile (`_reconcile_patient_studies_on_click`,
  `_hp_series.py`), so it is ready before the gate runs.
* **`_local_thumbs`** — `len(_build_cached_thumbnail_payload(...).thumbnails)`.
* **`self._thumbs_server_refreshed_uids`** — a per-session set that records studies
  already refreshed, so the gate refreshes **once** rather than looping on a benign
  `count_of_series`-vs-fetchable-thumbnails off-by-one.

Diagnostic traces (in `download_diagnostics.log`): `right_panel_cache_gate`
(`local_thumbs` / `server_series` / `grew`), `right_panel_cache_hit`
(`thumbnail_count`), `right_panel_socket_start` / `right_panel_socket_done`.

### History — read before changing the gate
1. **44113 (2026-06-01):** introduced the stash + gate so a study that grew on the
   server (1→9 series) re-fetches on single-click. See
   `docs/reports/ROOTCAUSE_44113_SINGLE_CLICK_PIPELINE_2026-06-01.md`.
2. **44323 / 44534 (2026-06-02):** two gate defects found via live DB/disk/log ground
   truth (44323 MRI 20 series/20 PNGs = complete; 44534 DX 3/3 = complete):
   - **B1 — patient-aggregate count mis-attributed to one study.** `count_of_series`
     is the *patient* series total. The stash fired on `len(study_uids)==1`, but a
     **multi-study** patient still returns only the latest UID (so that is true), and
     then `count_of_series` aggregates all the patient's studies (44534 DX got
     `server_series=10` = DX 3 + MRI 7; DX really has 3) → a false "grew". **Fixed:**
     stash only when `total_studies <= 1`.
   - **B2 — "refresh once" never recovered on a later server growth.**
     `_thumbs_server_refreshed_uids` was keyed by **UID only**, so after the first
     refresh a genuine later growth was never re-fetched on re-click — the stale
     partial cache was pinned. **Fixed:** key the marker by the server series **count**
     (`f"{uid}@{server_series}"`). An unchanged count still hits the fast cache (same
     key → skip, so the benign off-by-one does not loop); a changed count gets a fresh
     key → exactly one re-fetch. See `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`.

Note the *missing MRI study* on 44534 is **not** a thumbnail bug — it is study
discovery: the server's `GetPatientList` returns only the latest study UID per patient,
so the MRI study is enumerated per-modality elsewhere (see the multi-study completeness
guard in `CLAUDE.md` and `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`). The gate only
governs thumbnails *within* a study that is already known.

### Refresh-gate guardrails (read before touching the gate)
1. **`count_of_series` is patient-level, not study-level.** Only attribute it to a
   single study when `total_studies <= 1`. For multi-study patients use the per-study
   series count, never the patient aggregate.
2. **Keep the refresh marker keyed by the server count** (`uid@count`), not the bare
   UID — that is what lets a genuine server growth re-fetch while an unchanged study
   stays on the fast cache and a benign count/thumbnail off-by-one does not loop.
3. **The fast cache must stay the default.** Only fall through to the server fetch when
   the gate says the study grew; do not make every click hit the network (that is the
   responsiveness regression 44113's design avoided).
4. **Disk remains the authority** (§6). The gate decides *whether to fetch*; it never
   changes where thumbnails are read from.
5. **Re-validate with the traces.** A correct gate logs `grew=1` exactly once per
   server-count value, then `grew=0` + `right_panel_cache_hit` on subsequent clicks.
   Persistent `grew=0` while `server_series > local_thumbs` across *different* counts
   is the bug class B1/B2 fixed.

## 9. Right-panel render smoothness (2026-06-02)

Two render-layer fixes make the main-page right panel load calmly and consistently.

**(a) Skip-identical coalescing (anti-flicker).** A single click triggers the right
panel twice (fast open path ~450 ms + post series-info ~1.2 s). `display_thumbnails`
(`right_panel_widget.py`) always `clear_content()`s then rebuilds, so two identical calls
clear+rebuilt the same set ~0.8 s apart = a flicker/reload. Fix: `display_thumbnails`
computes a visual signature (`_thumbnail_render_signature` = ordered
`(study_uid, series_number, file_path)` per thumb) and returns early when it equals
`self._last_render_signature` (already shown/rendering). Reset in `clear_content()`;
`None` at init. A genuine change (grown study, different patient, multi-study regroup)
yields a different signature and still renders.

**(b) `progressive=False` on every main-page path (calm, not jumpy).**
`progressive=True` → `display_thumbnails_progressively` pops series in one-by-one on a
120 ms timer (jumpy/rushed). `progressive=False` → `display_thumbnails_immediately`
builds all widgets in one pass under `content_widget.setUpdatesEnabled(False)`→`(True)`,
so the set paints **once, together** (no per-widget flicker). Because the skip-identical
guard lets whichever path renders **first** win, a single mixed `progressive=True` path
made single-click thumbnails feel smooth sometimes and jumpy other times (timing race).
All main-page callers are now `progressive=False`: `_hp_search.py` cache/socket/offline
(already), `_hp_modules._show_grouped_patient_studies` (had regressed to default `True`;
restored), `_hp_series.py` series-info cached display (was `True`; changed).

Guardrails:
- Keep `display_thumbnails` **idempotent for identical content** (don't remove the
  signature short-circuit; don't make it unconditionally clear+rebuild every call); don't
  add volatile fields (timestamps/counters) to the signature.
- **Never** pass `progressive=True` — or omit the arg (defaults to `True`) — for a
  main-page right-panel render. Progressive mode is only for very large viewer-tab
  sidebars, not the home page.
- No extra render delay is needed: the repaint-suppressed immediate path already yields a
  clean "appear together" final state.

### Render coalescing — anti-flicker (2026-06-02)

A single patient click legitimately triggers the right panel **twice**: once on the
fast open path (`plus_entry → right_panel_begin`, ~450 ms) and again after series-info
loads (`series_info_entry → right_panel_begin`, ~1.2 s). Each call to
`RightPanelWidget.display_thumbnails` does `clear_content()` then rebuilds, so two
identical calls cleared and re-rendered the same set ~0.8 s apart — a visible
**flicker / jumpy reload**.

**Fix:** `display_thumbnails` now computes a **visual signature** of the requested set
(`_thumbnail_render_signature` = ordered `(study_uid, series_number, file_path)` per
thumbnail) and **returns early — no clear, no rebuild — when it equals the set already
shown/rendering** (`self._last_render_signature`). The signature is reset in
`clear_content()` (and `None` at init), so an explicit clear always allows the next
render. This is the single choke point for *all* render paths — single-study, the
socket-fetch render, the cache render, and the multi-study grouped main-page render
(`_hp_modules._show_grouped_patient_studies → display_thumbnails(combined_thumbnails)`)
all pass through it.

Guardrails:
- **Keep `display_thumbnails` idempotent for identical content.** Don't remove the
  signature short-circuit; don't make the panel unconditionally `clear_content()` +
  rebuild on every call.
- **The signature is the visual identity** (`study_uid` + `series_number` + thumbnail
  path). It must change whenever the drawn set changes — a grown study (new series), a
  different patient, or multi-study regrouping all change it and still render. Do not
  add volatile fields (timestamps, counters) that would make every call mismatch and
  re-introduce the flicker.
- **The two triggers are intentionally left in place** (each covers a different
  open-completion path); the coalescing is at the render layer, so neither correctness
  path is removed. Reducing to one trigger is a deeper change and not required.

## 10. Main Page ↔ Patient Viewer unification — verified (2026-06-17)

A bug/architecture check asked whether the patient-viewer sidebar reuses the home
page's thumbnails or runs a separate/old path (it "seemed" to load slowly, one by one).

**Finding — the pipeline IS unified; there is no separate active legacy path.**
- Both consumers resolve through the SAME `ThumbnailStore` singleton (memory, keyed
  `(study_uid, series_number)`) + canonical disk cache + `ThumbnailImageSourceService`.
  The viewer sidebar's live builder is `_pw_panels.add_thumbnail_to_thumbnail_layout`
  → `ThumbnailImageSourceService.load_pixmap` (store → disk). The legacy
  `thumbnail_panel.py` (`ThumbnailPanel`, with its `ThumbnailBatchRunner` drip) is
  **never instantiated** — do not attribute viewer behavior to it.
- On open, `_pw_thumbnails._load_server_thumbnails_async` calls
  `check_and_get_thumbnails` (disk) FIRST; on a **cache hit it renders directly with
  no server call and no regeneration** (the cache reuse return precedes the
  `get_study_thumbnails` fetch — pinned by
  `tests/code/ui_services/test_thumbnail_unified_pipeline.py`). It only fetches on a
  genuine miss, and never DICOM-re-decodes in the live path.

**Real causes of the *perceived* slowness (not a separate path):**
1. **Multi-study / non-primary study cache warmth.** The single-click home page warms
   the cache for the study/studies it displays; the viewer's primary loader fetches
   only `self.study_uid`, and other studies go through
   `_schedule_multistudy_thumbnail_prefetch` (per-study fetch on a daemon thread). A
   secondary study the home page did not pre-warm is a cache MISS on open → fetched
   fresh → slower/progressive. (Matches "especially second/non-primary study".)
2. **Cache miss during an active download** defers the (uncached) sidebar load behind
   the download and polls (150 ms ×8 then 700 ms, §4.4) → thumbnails trickle in.
3. Render cadence: the home page renders all-at-once (`progressive=False`,
   repaint-suppressed, §9); the cache-hit sidebar render is a synchronous loop and
   should also appear together (it is not the legacy drip).

**Structured logging added (2026-06-17)** for empirical validation on the next run —
`MainPageThumbnailRequested` (`_hp_search.py`), `PatientViewerThumbnailRequested` /
`ThumbnailCacheHit` / `ThumbnailReusedFromUnifiedPipeline` / `ThumbnailCacheMiss` /
`ThumbnailFetchedFromServer` (`_pw_thumbnails.py`), and `ThumbnailLoadedFromMemory` /
`ThumbnailLoadedFromDisk` (DEBUG, `thumbnail_image_source_service.py`). A
`ThumbnailCacheHit`+`ThumbnailReusedFromUnifiedPipeline` on open (no
`ThumbnailFetchedFromServer`) confirms reuse.

**Proposed follow-up (NOT yet implemented — needs live validation):** pre-warm ALL of a
multi-study patient's per-study thumbnail caches on the home page (so the viewer hits
cache for every study), and/or have the viewer reuse cached studies and fetch only the
genuinely-missing ones. This closes cause #1 — the dominant multi-study case. The
unification itself (shared store/service/keys) is already in place.
