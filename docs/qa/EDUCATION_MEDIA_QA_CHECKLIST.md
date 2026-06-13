# Education module — media QA checklist (2026-06-13)

Manual QA for the Education/E-Learning viewer content pipeline. Run after any change
to `modules/education/educational_patient_viewer_widget.py`,
`modules/education/video_slide_widget.py`, or `modules/education/docx_render.py`.
Watch the VS Code terminal and `user_data/logs/app.log` for `[EDU_MEDIA]` lines.

## Architecture invariants (do not regress)
- **Video/audio uses an ephemeral player.** Each video/audio mounts a FRESH
  `VideoSlideWidget` in `video_host_layout`/`audio_host_layout`; switching content
  calls `_destroy_active_player()` → `cleanup()` (stop + clear source, releases the
  native sink + file lock) → `setParent(None)` → `deleteLater()`. A live media sink
  is **never** just hidden inside the `QStackedWidget` (that was the repeated crash).
- `_on_item_clicked` ALWAYS calls `_teardown_media()` first; if a video/audio was
  active the new load is **deferred** one event-loop turn so the backend settles.
- `_load_media_content` is an **error boundary** — a bad/unsupported file shows a
  friendly message and logs, never crashes the app.
- Images use a re-entrancy-guarded `QGraphicsView.fit()` (no fitInView recursion).

## Launch / open
- [ ] App launches from VS Code (source build).
- [ ] Education module opens; courses list populates.
- [ ] Open 3+ different courses; open several items each.

## Video (the focus)
- [ ] Video plays on open (autoplay).
- [ ] Pause, then play again.
- [ ] Seek with the slider; time updates.
- [ ] Stop, then play again.
- [ ] **Switch item WHILE video is playing** → image: no freeze/crash.
- [ ] Switch while playing → PDF: no freeze/crash.
- [ ] Switch while playing → DICOM study: no freeze/crash.
- [ ] Switch while playing → another video: previous releases, new plays.
- [ ] Switch while **paused** → any type: no freeze/crash.
- [ ] Play video, then change SLIDE (◀/▶ item buttons): no crash.
- [ ] Open a course with a video, then close/switch the patient tab while loaded.
- [ ] Repeat fast switching video↔image↔DICOM ~10× rapidly: no crash, no slowdown.
- [ ] After leaving a video, the `.mp4` is not file-locked (can be moved/deleted).

## PDF
- [ ] Opens and renders; fit-to-view correct.
- [ ] Zoom +/- and prev/next page work; pan via scrollbars when zoomed.
- [ ] Switch away and reopen: stable.

## Images (JPEG/PNG/WEBP)
- [ ] Open; fits the viewport (no crop, correct aspect).
- [ ] Zoom +/-, wheel-zoom, drag-pan, Fit, Reset.
- [ ] Resize the window / maximize / restore → image re-fits, no freeze.
- [ ] Switch away and reopen.

## DICOM
- [ ] Open a study/series; scroll slices.
- [ ] Default 1×2 layout; content fits each pane.
- [ ] Switch away (to video/image) and back: stable.

## Word / PowerPoint / documents
- [ ] `.docx` renders inline (headings/lists/text); `A−`/`A+` resize text.
- [ ] `.pptx`/`.ppt`/`.doc` open externally via the message page (no crash).
- [ ] Unsupported/garbage file → friendly "could not be displayed" message + log.

## Layout / DPI / monitors
- [ ] Maximized, restored, and manually resized windows — no overflow/distortion.
- [ ] Move the window between the Dell monitor and the secondary monitor — layout
      stays correct.
- [ ] High-DPI scaling (125%/150%) — viewers sized correctly, controls not oversized.

## Stability
- [ ] No app close/crash across all of the above.
- [ ] `app.log` shows `[EDU_MEDIA] load …` / `player mounted` / `player destroyed`
      pairs with no `load failed` for valid files.
- [ ] No `native_fault.log` written during the session.
