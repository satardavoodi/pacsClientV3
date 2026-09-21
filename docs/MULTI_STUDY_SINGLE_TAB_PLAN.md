# Multi-Study Single-Tab Viewer — Implementation Record

**2026-09-17 shared enumeration correction:** grouped Local uses the same exact
catalog/offset/header contract while its inventory avoids one redundant type-stat
per candidate. Fresh version validation is preserved. No first-paint latency
acceptance yet: 334 code passes / 1 synthetic-symlink privilege skip; the 09:13 run
predates this change. See the enumeration receipt in the UI-stall report. The
Advanced first-render freeze in that run is a separately assigned owner fix.

**2026-09-17 ownership correction:** duplicate Home setup inventory is removed
only for single-study Local opens. Grouped Local continues complete aggregation
and retains headers, study slots and exact-series storage mapping. New worker
guards cover 2/4-study repeated-number, unnamed and cine records; expanded suite
321 passes. This is code evidence, not a new multistudy live acceptance or a
grouped-latency fix. Fresh-source GUI is pending. See the single-study ownership
receipt in `reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.

**2026-09-17 Local admission follow-up:** the 23:40 source run has 39/34-card,
two-study metadata waits of 6.570/27.004 seconds. The new optimization reuses
version-checked positive pixel facts in the existing shared worker service across
restart. It does not publish a partial grouped catalog or change study slots,
duplicate-number allocation, exact paths, history order, cine counts or geometry.
No facts are stored in thumbnail folders; first uncached classification remains.
Fresh-source cold/reopen/restart GUI is pending. See the dated OPT-58/60 receipt
in `reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md` and its 32-case guard.

**2026-09-16 grouped-header follow-up:** show a header only after grid parenting while
grouped paint is suppressed, constrain it to the existing card-column width and reserve
its wrapped height before painting. No changes to study slots, previous-exam labeling,
UID/path mapping or card counts. Four new 2/4-study Qt cases pass; 432 expanded passes /
467 mirrors. Fresh source GUI is pending. Actual late discovery of a second study still
causes the existing topology promotion and is not claimed solved by a geometry fix.
See the 20:51-source/header receipt in the UI-stall report.

**2026-09-16 sidebar ownership correction:** late queued primary files/entries and
chunks are rejected during grouped ownership; an explicit grouped-render failure
retains primary-study fallback, and a new grouped attempt cancels older chunks.
Retiring/disposed owners cannot render. Grouped clear retires effects/callbacks and
keeps cards parented until deletion; shared insertion establishes geometry before
paint and counts cards rather than header rows. No study-slot, UID/path, history or
frame/object identity changes. 428 focused passes; initial 466-pair mirror pass was
followed by one unrelated Advanced Viewer drift on final recheck. Fresh-source visual
acceptance pending. Synchronous grouped construction and GUI reads remain separate
work. See the sidebar presentation receipt in the UI-stall report.

**2026-09-16 partial metadata safety:** the patient metadata sink now reserves
previously admitted study-local display handles before the unchanged study-offset
projection. A late same-number series cannot steal a sibling's alias; a partial
refresh resolves prior folder/path hints by Study/Series UID, not raw number.
Foreign-study records cannot fill primary metadata before projection. Full initial
allocation, study slots, count precedence and viewer execution remain unchanged.
This is a prerequisite for catalog-first delivery, not its activation. Fifteen new
behavioral guards, 181 + 107 adjacent passes and one existing stateful property
pass; fresh-source GUI is pending. See the dated catalog-first review in
`docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.

**Fresh-source follow-up, 11:52:59:** sampled MCP Local switches displayed exact
Study/Series identities for a two-study / five-series case. Same-number still/cine
also retained 25 images versus two objects / 424 frames. This supersedes the
bootstrap-pending status above, not the remaining native-drag, Server, late-arrival,
close/reopen or performance gates. See the report's scoped receipt and cine GUI stall.

**2026-09-14 Home explicit-series entry:** double-clicking a Home thumbnail now requests the
normal patient open/reuse flow, then resolves the selected Study/Series UID pair against the
destination's current map. Home ordinals/offset keys are not portable. Repeated names/numbers,
primary-bucket fallback and existing study offsets retain their contracts. Single click remains
preview-only; name-based open does not automatically place a series. This supersedes the
earlier existing-tab-only Home click note below. Code acceptance passes; the user's two-study
server-open sample is log-corroborated. This is not verification of all series across both studies
or the repeated/unnamed/cine matrix. Final header and semantic-refresh changes still need
fresh-source live acceptance. See the thumbnail/priority provenance receipt and regression catalog.

**Status:** ✅ Implemented and user-verified (2026-05-24).
**Verified with:** patients **42471** (KNEE + ANKLE) and **43068** — both
studies' thumbnails appear grouped in the viewer tab, drag-and-drop of a
second-study series loads its images, no thumbnail flicker.

**Goal:** A patient with multiple studies under one Patient ID shows as one
list row, opens as one viewer tab, and that tab presents every study's series
grouped (`Study 1` / `Study 2` / …) in the left sidebar. Any series from any
study can be dragged into any viewport. All studies download.

> This file is a permanent regression-guard record. If you touch the viewer
> thumbnail sidebar, the series-load path, or the right-panel thumbnails, read
> the **Regression guardrails** section below first.

> **Current integration note — 2026-09-13:** The offset-key viewer contract remains valid. Do not
> extend it by passing a main-page card ordinal as series identity, and do not change generic
> `ThumbnailManager` precedence to repair the right panel. The historical reason for the parallel
> render/action paths and the identity-aware migration sequence are in
> `docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

---

## 2026-09-14 shared projection extraction

**2026-09-16 presentation cadence:** projection/offset allocation remains unchanged.
Normal qasync grouped rendering now reserves all known headers and fixed-size card
slots, then prepares images/readiness off GUI and applies one card per yield through
the same manager. Duplicate raw numbers use each study's persisted folder/PNG key;
offsets remain UI-only. See the [bounded-build receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60).
Fresh source GUI is pending; late study topology and full inventory admission are
not certified by the synthetic layout/cancellation guards.

**Later Home click cutover:** main-page clicks now carry immutable study/series
UIDs into the tab service, which resolves that tab's OWN key from its existing
projection. Home display hints never become destination keys or storage paths.
Missing/ambiguous targets fail closed and no tab is auto-created. This does not
change the multi-study projection below, single-study viewer behavior, or numeric
drag MIME. Source-live and installed acceptance are pending for this cutover;
see the latest provenance record and `test_home_series_action.py`.

The historical key, storage and ordering contracts below remain in force. The implementation
of study-slot assignment and series-entry projection now lives in
`PacsClient/utils/series_identity.py::build_multistudy_series_projection`; the controller
`_rebuild_multistudy_series_index` calls that implementation instead of maintaining its own
loop. The controller still owns its lifetime slot history, single-study bypass and the exact
clinical-history/numeric sorting policy. The helper returns new owner-local maps and does
not modify the input records or prior slot list. Cross-domain identity still uses `SeriesRef`.

The guard `tests/code/viewer/test_unify_multistudy_projection.py` exercised 14 scenarios on
the original implementation before extraction, then the same scenarios on the shared path.
It now has 15 cases, including input ownership. Missing/identical descriptions do not affect
identity; missing numbers continue through the existing socket normalizer; same-study
collisions retain their numeric alias and exact folder. `02` remains the raw label/storage
key, while multi-study UI keys retain their historical numeric conversion. Adding a later
study does not reorder the keys of already-admitted studies. Slot-removal/reassignment
semantics were not changed by this extraction.

The focused adjacent suite is 171 passed, exit 0. The stateful test now consumes the same
production projection and passes with 150 configured examples and up to 40 steps. Source
live and packaged-runtime verification remain pending for this September change; the May
verification above is historical evidence, not validation of the new extraction.

**Source-run update, 2026-09-14:** the inspected run contains secondary-study
renders and no logged projection rebuild failure. Two UID mismatch attempts were
blocked before subsequent matching images, so the zero-SKIP oracle is still unmet.
This is partial live evidence only; the full compatibility matrix and installed
runtime remain pending. See the provenance document's source-run evidence section.
Current dispatcher code also clears before the deferred rebuild; the May atomic-swap
description below is a historical contract, not a verified statement of today's code.

## Background — how the system is laid out (confirmed by probe + trace)

* A multi-study patient genuinely has >1 study under one Patient ID. Probe
  (`tools/analysis/oneoff/probe_patient_structure.py`, run 2026-05-24): 42471 = 2 studies / 16
  series; 43346 = 1 study (NOT multi-study — correct as-is).
* **Series identity:** `series_uid` is globally unique; `series_number` is
  **study-local** — it restarts at 1 in every study. This is the root of the
  collision.
* **Disk layout is already study-aware:** downloads are written to
  `{SOURCE_PATH}/{study_uid}/{series_number}/Instance_NNNN.dcm`. Series folders
  use the *original* study-local number; the parent `study_uid` folder keeps
  the two studies separate. **Do not change this.**
* **Download was never broken.** `_hp_patient_open.py` STEP 3.5 already loops
  every study in `all_study_uids`, builds a per-study `dm_study_data` tagged
  with that study's own `study_uid`, and queues each one. No download-side
  change was needed or made.
* **The right panel (main-page preview) was already study-grouped** via
  `_show_grouped_patient_studies()`.

## Root cause (the one real bug)

The viewer's **left thumbnail sidebar** keyed every series by bare
`series_number` in shared maps (`_server_series_info`, `thumbnail_manager`'s
`series_widgets` / `ready_series`). Because series numbers restart per study,
Study 2's "series 1" silently overwrote Study 1's "series 1" — the second
study collapsed out of the viewer. The image-load path
(`_vc_load.py`) also resolved DICOM folders against the widget's single
`import_folder_path`, so even if a second-study series was addressable it could
not be loaded.

Symptoms "Study 2 doesn't appear" and "only Study 1 loads" were the **same**
root cause. The data always arrived correctly; only the viewer collapsed it.

---

## As-built implementation

The fix is **gated entirely on multi-study** — a patient is "multi-study" only
when `len(self._studies_series) > 1` (or the early `_is_multistudy_hint`).
**Single-study patients run the original code path byte-for-byte unchanged.**

### Core idea — collision-free offset keys

For a multi-study patient, `_server_series_info` is rebuilt with
**patient-unique keys**:

* the **primary** study (the double-clicked `self.study_uid`) keeps its
  **original** series numbers — `study_slot 0`, offset `0`;
* every **additional** study's series get an **offset key**
  `study_slot * 1_000_000 + original_series_number`.

So keys never collide, and the primary study's keys are unchanged (its load /
green-border behaviour is identical to a single-study patient). Each rebuilt
entry carries: `study_uid`, `_orig_series_number`, `_study_slot`, and an
absolute `series_path` (`{SOURCE_PATH}/{study_uid}/{orig_no}`).

### Files changed

**`PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`**
* `set_server_series_info()` — builds the `_studies_series`
  `{study_uid: [series…]}` index; when multi-study, calls
  `_rebuild_multistudy_series_index()` + `_schedule_multistudy_thumbnail_prefetch()`
  and **gates the single-study loader off** (`should_load` is forced false).
* `_rebuild_multistudy_series_index()` — rebuilds `_server_series_info` with the
  offset keys above and builds `_multistudy_viewer_groups` (the ordered
  per-study render plan). Idempotent — safe to call on every
  `set_server_series_info` call.
* `_schedule_multistudy_thumbnail_prefetch()` — daemon thread; fetches **every**
  study's series thumbnails into its own `THUMBNAIL_PATH/<study_uid>` cache,
  then schedules `_render_multistudy_grouped_slot` on the main thread.
* `_render_multistudy_grouped()` / `_render_multistudy_grouped_slot()` — renders
  every study's thumbnails into the one sidebar grid, under a `Study N` header,
  keyed by the offset key. Runs once (guarded by `_multistudy_thumbs_rendered`).
  On total failure it falls back to the single-study loader so the sidebar is
  never worse than before.
* `_make_study_header_widget()` — the non-selectable `Study N — <body part>`
  divider row.
* `show_exist_thumbnails()` — **gated**: returns early for multi-study so the
  single-study early render does not paint study 1 and then get cleared by the
  grouped render (that clear+rebuild was a flicker).

**`PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`**
* `create_thumbnail_widget()` — the thumbnail header shows
  `series_info['_orig_series_number']` when present, so the user sees the real
  study-local number (`Series 3`), not the internal offset key.

**`PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`**
* After tab creation, sets `widget._is_multistudy_hint = len(all_study_uids) > 1`
  so the viewer knows it is multi-study *before* `set_server_series_info`
  arrives (prevents an early single-study render).

**`PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_series.py`**
* `change_series_on_viewer()` — the temporary Phase-1b fail-fast guard was
  removed; non-primary-study series now load for real (see `_vc_load.py`).

**`PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`**
* `_load_single_series_on_demand()` — multi-study load resolution. For an
  offset-keyed series it resolves `ms_disk_series_number` (the original number)
  and `study_path` (the series' own study folder, from `series_path`'s parent),
  and uses **those** for the on-disk read (`tentative_folder`,
  `load_single_series_by_number(...)`, the empty-instances repair). The offset
  key stays the cache / dedup / tracking key throughout.
* After load, the returned metadata's `series['series_number']` is **normalized
  to the offset key** (with the original kept as `_orig_series_number`) so the
  viewer's no-op detection / focus tracking cannot confuse Study 1's "series 3"
  with Study 2's "series 3".

**`PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py`** (flicker fix)
* `display_thumbnails()` no longer calls `clear_content()` immediately —
  clearing then, before the timer-deferred rebuild, painted an empty panel.
* `display_thumbnails_immediately()` clears inside the repaint-suppressed
  (`setUpdatesEnabled(False)`) block right before rebuilding; the old → new
  swap is now a single repaint with no empty frame.
* `display_thumbnails_progressively()` clears at its own start.

---

## Regression guardrails — read before touching this area

1. **Single-study is sacred.** Every multi-study branch is gated on
   `len(self._studies_series) > 1` (or `_is_multistudy_hint`). A single-study
   patient must never enter `_rebuild_multistudy_series_index`,
   `_render_multistudy_grouped`, the prefetch, or the offset-key load branch.
   When editing, keep the gate.
2. **Offset keys are opaque.** For a multi-study patient,
   `_server_series_info` keys are offset keys, not server series numbers. Any
   code that reads `_server_series_info` must treat the key as opaque and use
   the entry's `_orig_series_number` / `study_uid` / `series_path` for anything
   touching the server or disk.
3. **Disk reads use the entry's own study.** Never build a series folder path
   from the widget's single `study_uid` / `import_folder_path` for a
   multi-study series. Use `series_path` (absolute) or
   `{SOURCE_PATH}/{entry.study_uid}/{entry._orig_series_number}/`.
4. **Don't reintroduce the early render.** `show_exist_thumbnails()` and the
   single-study `_load_server_thumbnails` path must stay gated off for
   multi-study — only `_render_multistudy_grouped` may populate the sidebar.
5. **Don't clear before a deferred rebuild.** In `right_panel_widget.py` the
   clear must stay inside the deferred render (repaint-suppressed). Clearing in
   `display_thumbnails()` before the `QTimer` rebuild reintroduces the flicker.
6. **Download is already correct — do not "fix" it.** `_hp_patient_open.py`
   STEP 3.5 queues every study under its own `study_uid`. Leave it.
7. **FAST viewer mode must still never instantiate VTK render windows.**
8. **Multi-study previews render immediately, not progressively.**
   `_show_grouped_patient_studies()` must call `display_thumbnails(...,
   progressive=False)`. Progressive mode (120 ms/thumb) reintroduces the
   two-study flicker. Single-study clicks already use `progressive=False`.
9. **Grouped sidebar order is numeric.** `_rebuild_multistudy_series_index()`
   sorts each study's series by numeric series number before building the
   offset-key groups, so the sidebar renders `0,1,2,…,10,11`. Don't drop that
   sort — server `series_list` order can be lexical.
10. **Card construction must not trigger a late recursive Qt repolish.** Keep
    the root-only `QWidget#seriesThumbnailCard` stylesheet at the beginning of
    `ThumbnailManager.create_thumbnail_widget`, before layouts, child widgets,
    graphics effects, and event filters. The 2026-09-01 native fault captured a
    Windows `0xc0000374` termination at the former late unscoped stylesheet
    while `_render_multistudy_grouped` was creating a card. This stability rule
    does not alter offset keys, per-study identity, ordering, or drag payloads.

## Follow-up fixes — flicker + ordering (2026-05-24, second pass)

Two smaller multi-study issues were found after the initial fix and corrected
with minimal, gated edits:

1. **Main-page preview flicker for two-study patients.** Single-clicking a
   multi-study patient routed through `_show_grouped_patient_studies()` which
   called `display_thumbnails(combined_thumbnails)` with the default
   `progressive=True`. Progressive mode clears the grid and then refills it one
   widget at a time on a 120 ms timer — visible as a flicker/hesitation. The
   single-study click path (`show_patient_studies`) already uses
   `progressive=False`. Fix: `_hp_modules.py::_show_grouped_patient_studies()`
   now calls `display_thumbnails(combined_thumbnails, progressive=False)`. The
   old→new swap is now a single repaint-suppressed pass (see
   `right_panel_widget.display_thumbnails_immediately()`), with no empty frame.

2. **Viewer-tab grouped sidebar not numerically ordered.** For a multi-study
   patient the grouped sidebar rendered each study's series in server
   `series_list` order, which could be lexical (`1, 10, 11, 2, 21`). Fix:
   `_pw_thumbnails.py::_rebuild_multistudy_series_index()` now sorts each
   study's series by **numeric** series number (`_series_order_key`) before
   building the offset-key `group`, so the sidebar renders `0, 1, 2, …, 10,
   11, 12`. Non-numeric series sort last. Single-study paths were already
   numerically ordered (`get_image_files()` uses `natsorted`,
   `_render_thumbnails_from_entries()` sorts by `int`), so they are untouched.

Both changes stay inside the existing multi-study gates; single-study
behaviour is unchanged.

## Known cosmetic follow-up (not a regression, not blocking)

* A non-primary study's series, once loaded into a viewport, may show its
  internal offset key in the viewport's series-number label. Images are
  correct; only the label number is internal. Fix later by teaching the
  viewport overlay to prefer `metadata['series']['_orig_series_number']`.

## Out of scope (unchanged)

* No change to the socket protocol, DB schema, or single-study behaviour.
* No change to the download manager or the disk layout.
