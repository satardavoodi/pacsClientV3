# Reliable Block Structure Roadmap

**Date:** 2026-04-19
**Status:** Initial structure plan with first safe slice implemented

## Objective

Make Block A / B / C reliable and aligned with upper layers:
- app entry / main bootstrap
- Home service layer
- database access layer
- download manager
- viewer modules

## Required runtime order

1. **Block A** — thumbnail projection
2. **Block B** — first image visible
3. **Block C** — scrolling, cache, prefetch, growth, optimization

## Structural rule

Lower blocks must not pull upper responsibilities downward.

That means:
- thumbnail UI must not own DB query logic
- series-switch UI must not own nonessential warmup policy
- cache/prefetch logic must not compete with first image visibility

---

## Target ownership

## App / upper layer

### `main.py`
Owns:
- process bootstrap
- graphics/runtime profile
- Qt app lifecycle
- exception hooks
- global services startup/shutdown

### `HomePanelWidget` + home services
Owns:
- patient-open intent
- study tab creation
- DM wiring
- server/search orchestration
- DB save/load via service layer

This is the correct "upper hand" layer for patient-open orchestration.

---

## Block A target

### Purpose
Project study/series availability into the sidebar quickly.

### Allowed responsibilities
- create thumbnail widgets
- show basic series identity
- show progress / ready state
- use already-resolved thumbnail metadata provider

### Not allowed
- direct DB query logic inside `ThumbnailPanel`
- duplicated study-UID resolution logic in multiple methods
- direct orchestration of unrelated download/viewer concerns

### First implemented slice
Implemented on 2026-04-19:
- added `ThumbnailMetadataService`
- rewired `ThumbnailPanel` to consume that service
- removed duplicated `get_cached_series_metadata()` ownership problem

Extended on 2026-04-19:
- promoted the core logic into project-wide `PacsClient.utils.series_metadata_service.SeriesMetadataService`
- kept `ThumbnailMetadataService` as a backward-compatible alias instead of creating a second implementation
- rewired Home priority DB fallback to reuse the same normalized series metadata service

Extended further on 2026-04-19:
- added `ThumbnailProjectionService` so `ThumbnailPanel` no longer owns thumbnail payload shaping
- centralized cached/server thumbnail projection building behind one sidebar helper
- clarified the Block A pipeline into: metadata service → projection service → panel timers/layout → thumbnail widgets

Extended further on 2026-04-19 (source cleanup):
- added `ThumbnailImageSourceService` so `ThumbnailPanel` no longer decides memory-store vs disk thumbnail loading inline
- isolated the thumbnail source stage before projection/layout work

Extended further on 2026-04-19 (performance cleanup):
- replaced repeated thumbnail duplicate scans in `ThumbnailPanel` with O(1) panel-side series/file indexes
- kept Block A batch insertion cheaper as series counts grow, instead of re-scanning button lists on every timer tick

Extended further on 2026-04-19 (batch scheduling cleanup):
- added `ThumbnailBatchRunner` so timer cadence and batch iteration are no longer hand-written twice inside `ThumbnailPanel`
- moved progressive/cached batch scheduling into a reusable Qt-side helper
- kept `ThumbnailPanel` focused on per-item processing and layout hosting

Files changed:
- `PacsClient/utils/series_metadata_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_projection_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_metadata_service.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_priority.py`
- `PacsClient/pacs/patient_tab/utils/__init__.py`

### Next Block A slices
1. Move thumbnail cache/disk fallback decisions behind a thumbnail data provider
2. Remove direct DB helper imports from `thumbnail_panel.py`
3. Split display batching/timer logic from metadata resolution
4. Define one series projection state source for sidebar UI

## Clearer Block A pipeline

Current intended flow:

1. `SeriesMetadataService`
   - resolves study identity
   - loads normalized series summary rows
2. `ThumbnailImageSourceService`
   - resolves thumbnail pixels from memory/disk-backed store first, then explicit file fallback
3. `ThumbnailProjectionService`
   - converts normalized rows / server thumbnail records into sidebar projection payloads
   - creates standardized metadata for immediate/cached thumbnail display
4. `ThumbnailPanel`
   - owns per-item processing and layout insertion only
5. `ThumbnailManager`
   - owns widget creation, selection state, progress state, and border rendering
6. `ThumbnailBatchRunner`
   - owns timer cadence, batch iteration, and progress/finished callbacks for sidebar thumbnail scheduling

This keeps the pipeline readable and prevents the sidebar widget from becoming a mixed UI+DB+payload orchestration layer.

---

## Block B target

### Purpose
Show the first diagnostic image with stable layout and minimal delay.

### Allowed responsibilities
- cache-hit switch
- async load scheduling
- backend binding
- first-frame display
- essential slider/layout stabilization

### Not allowed
- eager warmup/prefetch admission
- mixed ownership of progress/caching/completion policy
- excessive post-switch side effects in the hot path

### Next Block B slices
1. Split `_vc_switch.py` into:
   - switch request validation
   - first-frame loader/apply path
   - post-display follow-up hooks
2. Move nonessential warmup triggers out of the first-frame authority path
3. Make first-frame completion an explicit milestone (`B1 first image visible`)

---

## Block C target

### Purpose
Optimize continuous interaction only after Block B succeeds.

### Allowed responsibilities
- scroll handling
- cache selection
- surrogate/exact frame logic
- prefetch
- progressive grow
- post-completion warmup

### Not allowed
- any work that delays Block A first-visible or Block B first-image milestones

### Next Block C slices
1. Add explicit admission gates for prefetch/warmup after first image visible
2. Isolate drag/settle debugging from thumbnail/progressive concerns
3. Add KPI markers for:
   - `C1 first smooth scroll frame`
   - `C2 warmup admitted`

---

## Recommended implementation order

### Phase 1 — finish Block A cleanup
- complete thumbnail metadata/data-provider extraction
- reduce sidebar DB/disk ownership
- keep thumbnail projection cheap and deterministic

### Phase 2 — narrow Block B hot path
- define first-frame-only authority
- move nonessential side effects out of switch hot path

### Phase 3 — harden Block C admission
- allow optimization only after visual readiness milestones
- debug drag/cache issues without polluting A/B paths

---

## Practical rule for future edits

Before adding logic to a block, ask:

- Does this help the user see **thumbnails first**? → Block A
- Does this help the user see **the first image**? → Block B
- Does this help only **after an image is already visible**? → Block C

If it belongs to Block C, it should not run in Block B’s critical path.

## Reuse / no-duplication rule

Any code that needs normalized series summary data from the DB must go through:

- `PacsClient.utils.series_metadata_service.SeriesMetadataService`

Do **not** add new local helpers in widgets/mixins that:
- resolve `study_uid` again,
- call `get_series_by_study_uid()` directly from UI code,
- reshape series dicts into local one-off formats.

If patient-tab code still imports `ThumbnailMetadataService`, that is acceptable as a backward-compatible alias, but the implementation authority remains `SeriesMetadataService`.

## Current status

- Review complete
- First structural slice implemented
- Safe next target: continue Block A cleanup before touching the Block B/C hot path

---

## 2026-04-20 continuation update

Use `docs/plans/analysis/BLOCK_A_B_KPI_CLEARCANVAS_HANDOFF_2026-04-20.md` as the current continuation document.

### What changed after this roadmap was written

- Block B hot-path follow-up work was narrowed further in `_vc_switch.py` so first-visible image work stays immediate and lower-priority UI refresh work runs on the next Qt tick.
- FAST shutdown cleanup in `lightweight_2d_pipeline.py` was corrected and mirrored into the builder payload copy to keep packaged/runtime behavior aligned.
- A runtime-log-driven Qt startup refit fix landed in `_vw_series.py` to correct the wrong-zoom / under-fit presentation of the last series inserted into the layout.
- Small-stack FAST interaction policy was tightened in `modules/viewer/fast/stack_cache_profile.py` so stacks `<= 24` now use `fast_prefetch_radius = 4` during active fast interaction.

### Updated practical interpretation

- Block A remains the correct next structural cleanup area when doing architecture work.
- Block B is in better shape than when this roadmap was first written; it now has a clearer first-frame boundary.
- The latest KPI direction says remaining work is more about background/control-plane CPU pressure than foreground visible decode.

### Updated next-step rule

Before changing architecture again:

1. capture a fresh runtime log after the small-stack radius change,
2. verify visible drag remains low-latency and mostly decode-free,
3. only then choose whether the next move is Block A cleanup or Block B/Block C boundary tightening.
