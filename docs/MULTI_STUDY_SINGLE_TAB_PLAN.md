# Multi-Study Single-Tab Viewer — Implementation Record

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

---

## Background — how the system is laid out (confirmed by probe + trace)

* A multi-study patient genuinely has >1 study under one Patient ID. Probe
  (`probe_patient_structure.py`, run 2026-05-24): 42471 = 2 studies / 16
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
