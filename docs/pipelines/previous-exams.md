# Previous Exams — As-Built Record (2026-06-20)

**Status:** Implemented (flag-gated default-ON). Pure logic unit-tested
(`tests/code/ui_services/test_previous_exams.py`, 28 checks) + source-wiring
guard (`tests/code/ui_services/test_previous_exams_wiring.py`). **Needs live GUI
verification** on the source build (human-assisted bootstrap).

## Goal

A patient opened in the workstation may be the **same real person** imaged before
at this center under **different Patient IDs**. The server links them by
**National ID / RIS reception**. The viewer surfaces those prior exams, lets the
user load any of them for comparison, and downloads on demand — without mixing
each exam's identity.

Server contract: `docs`-attached `patient-past-studies-api.md`
(§1.2 `GetPatientStatus`, §1.3 `GetPatientReceptionHistory`, socket port 50052).

## UX

* A **"Previous Exam"** button sits in the **Series Thumbnails** panel header.
  * Gray/disabled when the server reports no prior exams.
  * **Red/active** (with a count) when prior exams exist.
* Clicking it switches the thumbnail area **in place** (a `QStackedWidget`)
  between the current series grid (page 0) and a **previous-exams list** (page 1:
  rows of `Patient ID · date · modality`).
* Selecting a row **merges** that exam's series into the open viewer as an
  additional grouped study ("Study N"), loading its thumbnails. **No DICOM
  images download on select.** Dragging/opening one of its series downloads that
  series via the existing pipeline.

## Data flow (chained, metadata-first)

```
patient open ─► widget.init_previous_exams(pid, name)         [_hp_patient_open.py]
            └─► daemon thread:
                   GetPatientReceptionHistory(pid)  (cross-PatientID / National ID)
                   GetPatientStatus(pid)            (same-id full history, supplement)
                   build_previous_exam_set(...)     [PacsClient/utils/previous_exams.py]
                └─► _on_previous_exams_ready (main thread): button red/active

select row ─► daemon thread: GetStudyThumbnails(prev_study_uid)
           │     save thumbnails to THUMBNAIL_PATH/<prev_study_uid>/, strip blobs
           └─► _apply_previous_exam_merge (main thread):
                  sanction prev_study_uid + record its OWN patient_id
                  build_download_payload(prev_uid, prev_pid, ...)   [shared authority]
                  set_server_series_info(series)  ─► multi-study offset-key regroup
                  dm.add_downloads([payload], start_immediately=False)  (PENDING, no DL)
                  reset _multistudy_thumbs_rendered ─► grouped sidebar repaints

drag/open a prev-exam series ─► _trigger_download_if_needed (_vc_load.py)
           └─► _resolve_canonical_series_identity ─► (prev_uid, orig_no, series_uid)
           └─► _on_retry_series_download ─► (registers prev exam w/ DM if needed)
                  ─► request_critical_series_download(prev_uid, series, series_uid)
```

The merge **reuses the multi-study single-tab mechanism**
(`docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`): each prior study becomes an additional
study slot with offset keys (`study_slot * 1_000_000 + series_number`); disk is
keyed by `study_uid` (patient-blind) so a different-Patient-ID exam loads
correctly while preserving its own identity.

## Files

| File | Change |
|------|--------|
| `modules/network/socket_client.py` | `get_patient_status`, `get_patient_reception_history` |
| `modules/network/socket_patient_service.py` | `get_patient_status_sync`, `get_reception_history_sync` |
| `PacsClient/utils/previous_exams.py` | **NEW** pure model + parsers (`PreviousExamStudy`/`PreviousExamSet`, `build_previous_exam_set`, `sanctioned_study_uids`) |
| `PacsClient/utils/patient_study_set.py` | `merge_study_uids`/`resolve_study_uids` gain `sanctioned_uids` |
| `.../patient_widget_core/_pw_previous_exams.py` | **NEW** `_PWPreviousExamsMixin` (fetch, list UI, merge, DM register) |
| `.../patient_widget_core/widget.py` | mixin added to `PatientWidget` bases |
| `.../patient_widget_core/_pw_panels.py` | header button + content `QStackedWidget` |
| `.../patient_widget_core/_pw_series.py` | `_on_retry_series_download` registers a sanctioned prev exam if needed |
| `.../home_ui/home_panel/_hp_patient_open.py` | calls `widget.init_previous_exams` on open |

None are plugin-mirrored. Feature flag: **`AIPACS_PREVIOUS_EXAMS`** (default ON;
`=0` = button never built, no server calls — byte-identical legacy).

## Invariants (do not break)

1. **Clinical isolation stays intact.** A previous exam is admitted into the
   current patient's grouped viewer ONLY because (a) the server linked it to the
   same real person and (b) the user explicitly selected it. That admission is
   the `sanctioned_uids` allow-list passed to `merge_study_uids` — never
   auto-populate it from caller/current context. The four automatic cross-patient
   guards (open / single-click reconcile / resync / back-fill) are **unchanged**
   and still drop foreign studies.
2. **Each exam preserves its own `study_uid` and `patient_id`.** The DM payload
   carries the exam's OWN patient_id; disk stays `SOURCE_PATH/<study_uid>/...`.
   Never re-attribute a previous exam to the current Patient ID (no DB write under
   the current patient).
3. **Metadata-first.** Open fetches only the list. Select loads series metadata +
   thumbnails. Images download only on drag/open of a specific series
   (`add_downloads(start_immediately=False)` registers PENDING; the existing
   `request_critical_series_download` promotes the dragged series).
4. **Reuse, don't fork.** Merge goes through `set_server_series_info` (the one
   viewer sink) and `build_download_payload` + `dm.add_downloads` (the one
   enqueue). No parallel download/viewer workflow.
5. **Reset `_multistudy_thumbs_rendered` before each merge** so the grouped
   sidebar repaints to include the newly-added study (the render is run-once).
6. `previous_exams.py` is **pure stdlib** (unit-testable, no Qt/network) — keep
   it that way.

## UI refinements (2026-06-20)

* **Exam date in the grouped "Study N" header.** `_make_study_header_widget`
  (`_pw_thumbnails.py`) now renders `Study N — YYYY-MM-DD — <body parts>
  (N series)` with the series-count in a smaller/dimmer rich-text span and word
  wrap on, so the date always fits the narrow sidebar without overflow. The date
  comes from `_study_date_display` (previous-exam set first, then any series
  `study_date`). `study_date` is stamped onto series at the central fetch
  (`_hp_series._get_or_fetch_series_info`, current studies) and onto merged
  previous-exam series (`_pw_previous_exams._load_previous_exam_worker`).
* **Single origin-aware border (red spectrum for previous status).** There is ONE
  border per card — the existing `CircularProgressborder` (the content card carries
  no border of its own; a second ring there was the "double line"). At card
  creation `progress_border._is_previous` is set from
  `_origin_border_color`/`_is_sanctioned_previous_exam`. In `paintEvent`:
  * **Current/main** series keep the normal status palette (accent=open,
    success=viewed, info=downloaded, grey-dashed=pending).
  * **Previous-exam** series are painted in a **spectrum of red** keyed by the same
    states, so a prior study reads as red throughout while still showing status:
    open `#fca5a5` (light) · viewed `#f87171` · downloaded `#ef4444` (solid) ·
    pending `#7f1d1d` (dark, dashed). `apply_border_states_new` never touches
    `_is_previous`, so origin persists across state changes.
* **Red-tinted "Study N" header for a previous exam.** `_make_study_header_widget`
  red-tints the group header (red text + translucent red background + a 4px red
  left accent), appends a `· PREVIOUS` tag, and surfaces the exam's OWN (prior)
  Patient ID — `Study 3 — ID 43373 — 2026-05-24 — BRAIN · PREVIOUS (16 series)`.
  The current/main exam keeps the neutral header. So the whole group reads as
  current vs prior at a glance, reinforcing the per-card blue/red borders.
* **Origin-colored viewport border (stamped at load).** The active-viewport
  highlight encodes the SOURCE of the loaded series: **blue** = current/main exam,
  **red** = previous exam. Origin is STAMPED on the viewport state at load time —
  `change_series_on_viewer` sets `vtk_widget._origin_is_previous =
  _series_is_previous_exam(series_number)` (resolved from the offset-keyed
  `_server_series_info` / canonical identity, independent of paint-time metadata).
  `_viewport_container_styles(active, previous)` then paints red (solid active / dim
  inactive) vs the default blue accent; `_node_is_previous_exam` reads the stamp
  first (falling back to metadata resolution for legacy/VTK paths). Because the
  stamp is re-set on every load, **replacing** a previous-exam series with a current
  one flips the border back to blue (and vice-versa). A selection-preserving
  `refresh_viewport_borders()` (wired into the FAST container's `switch_series` +
  drop) re-colors immediately without changing which viewport is active. NOT applied
  to thumbnails/study-cards/labels — only the active viewport highlight.

## UI refinement — two-row thumbnail header (2026-06-21)

The panel header is now **two rows** instead of one (`_pw_panels.py`,
`header_v = QVBoxLayout`), because the single line overlapped / truncated when the
counts grew, the width was limited, or DPI / localized labels were larger:

* **Row 1** — `Series Thumbnails` title + an `N series` count pill beside it.
* **Row 2** — the `Previous Exam` button + an `N exams` count pill beside it.

Each row groups its count **right next to** the label (`label → addSpacing(8) →
count → addStretch()`), so the count stays close to its title rather than being
pushed to the far right edge; the trailing stretch fills the remaining width. Labels
size to content (no fixed widths) so longer localized text stays readable and
responsive. The panel column itself was narrowed (`default_panel_width` 260 → 234 in
`widget.py`, thumbnail left margin 20 → 10) so it sits snugly around the fixed 190px
cards (234 − margins − scrollbar ≈ 202 ≥ 190); the Reception view keeps its previous
width. The previous-exam
count moved **out of the button label** (it used to be `Previous Exam (N)`) into its
own pill `self.prev_exam_count_label`, styled by `_previous_exam_count_style(active)`
(neutral gray when 0 exams; red-tinted when prior exams exist, matching the active
button). Count text pluralizes: `0 exams` / `1 exam` / `N exams`. Count pills use a
slightly smaller font (9px) than the section titles (10px). Row 2 is only built when
the previous-exams feature is enabled; when disabled, only Row 1 shows (unchanged).

## Tests

* `tests/code/ui_services/test_previous_exams.py` — parsers, merge/dedup/sort,
  current-exclusion, sanctioned override (drops foreign without sanction, keeps
  with sanction, default-empty byte-identical).
* `tests/code/ui_services/test_previous_exams_wiring.py` — source-wiring guard.
* `tests/code/viewer/test_thumbnail_header_two_rows.py` — source-pin guard for the
  two-row header (fails if it regresses to a single row or the count pill is removed).

Run on Windows: `python -m pytest tests/code/ui_services/test_previous_exams.py
tests/code/ui_services/test_previous_exams_wiring.py
tests/code/viewer/test_thumbnail_header_two_rows.py -q -p no:debugging`.

## Live validation checklist (human-assisted)

1. Open a patient with **no** prior exams → button gray/disabled.
2. Open a patient with prior exams → button **red** with count.
3. Click it → previous Patient IDs + dates appear in the thumbnail area.
4. Click a previous exam → its series/thumbnails load as a new grouped study; no
   bulk download starts (`download_diagnostics.log`: no `DownloadEnqueued` for it).
5. Drag one of its series into a viewport → that series downloads + displays.
6. Confirm the current patient's studies and the previous exam stay separate
   (each keeps its own Patient ID; no cross mixing).
7. Multi-study / multi-modality previous exams group correctly.
8. Each "Study N" header shows the exam date (`YYYY-MM-DD`); the series count is
   still visible (smaller) and the header does not overflow the sidebar.
9. Each thumbnail has a SINGLE border (no double line). Current/main series use the
   normal status palette; previous-exam series use a **red spectrum** keyed by
   status (open / viewed / downloaded / pending shades). Drag-and-drop still works
   for both.
10. A previous exam's "Study N" header is **red-tinted** with a `· PREVIOUS` tag
    and its own (prior) Patient ID; the current/main header stays neutral.
11. A viewport displaying a previous-exam series has a **red** border; a current
    series has the default **blue** border. Red appears immediately on drop and on
    thumbnail-click, without changing which viewport is active.
