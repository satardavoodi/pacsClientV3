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
