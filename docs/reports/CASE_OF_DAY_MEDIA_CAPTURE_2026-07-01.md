# Case of the Day — Non-Modal Dialog + Media Capture (2026-07-01)

## Summary

Implemented the requested Case-of-Day UI/media spec:

1. **Non-modal dialog** — the toolbar-invoked `CaseOfDayEntryDialog` no longer blocks
   the rest of the app; the user can keep navigating/scrolling/zooming/panning/
   dragging-and-dropping studies while it stays open.
2. **Compacted layout** — smaller minimum size, tighter margins/spacing, Diagnosis+
   Protocol and Description+DDx merged into 2-column grids (were stacked full-width
   rows), shorter note boxes. Same fields, no functional field removed.
3. **New "Media Capture" section** — Screenshot (JPEG) and Record Viewport (MP4)
   buttons, wired to a new `modules/education/case_media_capture.py` module.
4. **Privacy** — the FAST corner patient-identity overlay (name/ID/age/sex) is
   temporarily hidden on the captured viewport only, for the duration of a
   screenshot or recording, and restored immediately after. DICOM data is never
   touched; the overlay is never permanently disabled. Tool annotations/
   measurements are a separate paint layer and are unaffected.
5. **Case folder structure** — added `screenshots/`, `videos/`, `card/`, `notes/`
   subfolders alongside the existing `dicom/`/`attachments/` package layout
   (purely additive; `card/`/`notes/` are reserved for the future teaching-card /
   notes-export pipeline, not populated by this change).

## Files changed

- `modules/education/case_of_day_database.py` — added `PACKAGE_SCREENSHOTS_SUBDIR` /
  `PACKAGE_VIDEOS_SUBDIR` / `PACKAGE_CARD_SUBDIR` / `PACKAGE_NOTES_SUBDIR` +
  `case_media_dir(dicom_folder_path, kind)` helper. No changes to existing constants,
  schema, or functions.
- `modules/education/case_of_day_widget.py` — `CaseOfDayEntryDialog`: non-modal flag,
  compacted `_build_ui`, new Media Capture section + handlers
  (`_on_screenshot_clicked` / `_on_toggle_recording_clicked` / `_start_recording` /
  `_stop_recording` / `_tick_recording_status`), `closeEvent` + `reject()` now stop an
  in-progress recording so the MP4 is always finalized and the overlay always
  restored, even if the (now-closable-anytime) window is closed mid-recording.
  `CaseOfDayPage._create_case` (the manual Education-tab entry point, no live
  viewer) is untouched — it still uses `exec()`, and the Media Capture section
  is simply unavailable there (no `selected_widget` to capture).
- `modules/education/case_media_capture.py` (new) — capture/recording engine,
  documented in its module docstring. Independent of DICOM loading, rendering, the
  annotation system, and viewer interaction — it only observes a widget and encodes
  what it paints.
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` —
  `_save_case_of_day_from_patient`: `dlg.show()` instead of `dlg.exec()`, a strong
  reference (`self._case_of_day_dialog`) so the dialog isn't GC'd, re-activates an
  already-open dialog instead of duplicating the DICOM copy, badge refresh moved
  from "after `exec()` returns" to `dlg.finished`.

Plugin mirror (`builder/plugin package/packages/education/payload/python/modules/
education/`) synced via `tools/dev/sync_plugin_mirrors.py` (2 drifted files) +
`--add modules/education/case_media_capture.py` (1 new file). Verified with
`tools/dev/verify_plugin_mirrors.py` → 395/395 pairs match, 0 drift.

## Design decisions

- **Video library: OpenCV `cv2.VideoWriter`** (already a dependency —
  `opencv-python-headless` is in `requirements.txt`; no new dependency added).
  Tries fourcc `avc1` (H.264, small+high quality) first, falls back to `H264`,
  then to `mp4v` (always available, larger files) if the installed OpenCV build
  has no H.264 encoder — `FOURCC_CANDIDATES` in `case_media_capture.py`. This
  needs a **live-build check**: confirm which fourcc actually opens on the
  Windows source build's OpenCV wheel, and note the resulting file size/quality
  in a follow-up.
- **Capture target = `patient_widget.selected_widget`**, i.e. the exact one
  viewport cell — this excludes window borders, menus, toolbars, and the patient
  list by construction (they're sibling widgets elsewhere in the layout, never
  children of the cell), satisfying the "only the medical viewport" requirement
  without needing a custom clip region.
- **Overlay suppression is FAST-viewer-only** in this pass: it uses
  `QtSliceViewer.set_show_annotations()`, a toggle that already existed
  (`modules/viewer/fast/qt_slice_viewer.py`) but had zero external callers before
  this change — it was gated into `paintEvent` but never wired to anything.
  Advanced/VTK and MPR viewports are not covered yet (capture still works there,
  the corner overlay just isn't suppressed) — deferred, flagged in code comments,
  and does not violate the Fast/Advanced/VTK domain-separation rule (no VTK code
  was touched).
- **Recording performance**: frames are grabbed on the GUI thread via a QTimer
  (default 10 fps, `AIPACS_CASE_OF_DAY_RECORD_FPS`) — cheap because the FAST
  viewer paints via `QPainter`, not OpenGL — but the MP4 encode runs on a
  background thread via a bounded `queue.Queue` (default 60 frames,
  `AIPACS_CASE_OF_DAY_RECORD_QUEUE`). When the encoder falls behind, new frames
  are **dropped** rather than blocking the GUI thread, so a slow disk can make the
  recording choppier but never freezes the viewer.
- **Media Capture is only enabled when there's already an on-disk case package**
  (i.e. opened from the patient-toolbar graduation-cap icon, which copies the
  DICOM folder before the dialog opens). The manual "Import DICOM Folder" /
  notes-only entry flow (Education tab → "+ Add Case") shows the buttons
  disabled with an explanatory tooltip rather than attempting to capture into a
  not-yet-existing folder.

## Flags (all default ON — kill switches only, no behavior removed)

| Flag | Default | Effect when set to `0` |
|---|---|---|
| `AIPACS_CASE_OF_DAY_NONMODAL` | on | Dialog stays modal-flagged (legacy) |
| `AIPACS_CASE_OF_DAY_MEDIA_CAPTURE` | on | Media Capture section is not built at all |
| `AIPACS_CASE_OF_DAY_PRIVACY_OVERLAY` | on | Overlay is left visible during capture |
| `AIPACS_CASE_OF_DAY_RECORD_FPS` | `10` | Capture frame rate |
| `AIPACS_CASE_OF_DAY_RECORD_QUEUE` | `60` | Encoder queue depth (frames) before drop |

## NOT done / follow-ups

- **Live source-build verification** — this change was implemented and unit/
  compile-checked, but has **not** been exercised against a real running FAST
  viewport on the Windows source build (per the "human-assisted bootstrap" /
  clinical-lane note in `CLAUDE.md`, this needs a human to launch the app).
  Specifically verify: (a) the dialog is genuinely non-modal (drag a series
  while it's open), (b) Screenshot produces a correct JPEG with the overlay
  hidden and restored, (c) Record Viewport produces a playable MP4 with correct
  duration/frame count and the overlay hidden throughout, (d) closing the dialog
  mid-recording finalizes the file instead of corrupting it, (e) no regression
  to the existing modal manual "+ Add Case" flow in the Education tab.
- **Advanced/VTK and MPR overlay suppression** is deferred — capture still works
  for those surfaces, just without hiding their patient overlay.
- **`card/` and `notes/` subfolders** are reserved directory names only; nothing
  populates them yet (staged for the future teaching-card / AI-summary / social
  export pipeline mentioned in the spec).
- **Multiple simultaneous Case-of-Day dialogs** across different patient tabs are
  fine (each toolbar/patient widget has its own `_case_of_day_dialog` reference);
  only *duplicate* dialogs for the *same* patient widget are prevented.
