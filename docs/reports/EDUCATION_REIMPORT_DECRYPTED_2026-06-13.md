# E-Learning Re-Import — Fully Decrypted Courses (2026-06-13)

## Summary

The PooyanPacs "Learn" source was re-exported with **all** attachment types
decrypted (previously only DICOM had been decrypted). This pass re-scanned the
decrypted source and refreshed the current AI-PACS runtime education structure
**in place** — copying the newly decrypted JPEG/PNG/WEBP/PDF/PowerPoint/Word/video
files into each course/item, retiring the stale encrypted leftovers, repairing the
education database so the attachments render in the workstation, and writing
`course.json` / `item.json` manifests describing every item's resources.

Approach chosen by the user: **surgical in-place refresh** + **update the live DB
(after backup)**. No full re-import; existing migrated content (DICOM, enrichment,
course/slide structure) was preserved untouched.

## Source inspected

`E:\ai-pacs\ai-pacs codes\PooyanPacs_V1.0.0-master\dicom-workstation\PooyanClient\Storage\Learn`

Re-decrypted by the upstream tool (per-course `course.json` / per-item `item.json`,
schemaVersion **1.2**, generated 2026-06-13, `plainFilesCompleted: true`,
`isEncrypted: false` on every attachment).

File types found in source (29,170 files): `.dcm` 27,297 · `.jpg` 1,416 ·
`.png` 19 · `.webp` 1 · `.pdf` 4 · `.pptx` 2 · `.docx` 2 · `.mp4` 11 · `.txt` 11 ·
`.zip` 4 · `.json` 197 · `.ipdcom` 193 (still-encrypted DICOM) · `.ipe` 12
(course config). **0 `.ipcrypt`** remained in source.

## Runtime ↔ source mapping (from each `migration_manifest.json`)

| runtime | source | items |
|---|---|---|
| course_9 | Course-10 | 9 |
| course_10 | Course-1010 | 13 |
| course_11 | Course-1011 | 11 |
| course_12 | Course-2011 | 10 |
| course_13 | Course-2012 | 37 |
| course_14 | Course-2013 | 40 |
| course_15 | Course-3 | 6 |
| course_16 | Course-4 | 1 |
| course_17 | Course-7 | 29 |
| course_18 | Course-8 | 10 |
| course_19 | Course-9 | 10 |

`course_<pk>` does **not** equal `Course-<pk>`; the mapping is read from each
runtime course's `migration_manifest.json` `source_folder`.

## What changed

**Decrypted files imported into the runtime structure — 121 total**
(`user_data/education/courses/course_<pk>/assets/Item-*/_originals/`):
102 images · 4 PDFs · 11 videos · 2 PowerPoint · 2 Word. Originals preserved with
their real extensions; safe-overwrite by size + SHA1 (never clobbers a newer file).

**Encrypted leftovers retired — 314 total**, moved (never deleted) to
`_originals/_legacy_encrypted/` preserving sub-paths: 121 `.IPcryp` (the previously
encrypted non-DICOM attachments) + 193 `.IPdcom` (redundant encrypted DICOM; the
plain `.dcm` are already materialised).

**Database repaired (live `dicom.db`, backed up first):** the previous import had
left 166 `slide_content` rows as "Encrypted originals (archived)" placeholders.
These were removed and replaced with proper `image` / `pdf` / `video` / `attachment`
content rows pointing at the decrypted files (tagged `origin=elearning_refresh` for
idempotent re-runs). Post-state: image 102, pdf 4, video 11, attachment 4, dicom 202,
text 11; **121 media rows, 0 missing on disk, 0 leftover encrypted placeholders,
0 encrypted primary references**.

**Manifests written:** `course.json` at each course root (courseId, title,
description, category, modality, numberOfItems, ordered items with relative paths,
resource summary, timestamp, warnings) and `item.json` in each item folder
(resources with **relative** paths, a `protectedFiles` legacy section for the retired
encrypted files, and per-item warnings). 363 JSON manifests validated as UTF-8/parseable.

## Validation (`--validate`)

Images 1,447 OK (0 bad) · PDFs 4 OK · PowerPoint 2 OK · videos 11 seen · JSON 363 OK ·
**encrypted primary references 0** · **issues: none**. Headers were checked for image
(JPEG/PNG/RIFF), PDF (`%PDF`), and PowerPoint (OOXML zip **or** legacy OLE2).

## Unresolved / noted warnings (6)

- **5 × Quiz attachments** (course_15 ← Course-3): the source marks them `attachType:
  Quiz` with no renderable media file — listed as warnings, nothing to import.
- **1 × `.webp` image** (course_18 ← Course-8): imported and header-valid, but WEBP may
  not render on every PySide6/Qt build; flagged for awareness.
- **1 × legacy PowerPoint** (course_9 ← Course-10, Item-72): a real binary `.ppt`
  (OLE2) saved with a `.pptx` extension. It opens correctly in PowerPoint; the
  extension was left unchanged to avoid breaking the DB path reference.

## Safety & reproducibility

- DB backups: `backups/dicom_pre-elearning-refresh_<ts>.db` (≈175.6 MB) written before
  any DB write.
- Encrypted files are **moved to `_legacy_encrypted/`, never deleted** (reversible).
- Full machine-readable action report:
  `user_data/education/migration_reports/refresh_<ts>.json`.
- Tool: `tools/migration/refresh_decrypted_courses.py` — `--dry-run` (default),
  `--apply`, `--validate`; idempotent (re-runs replace its own tagged rows, skip
  identical files). Tests: `tests/code/education/test_refresh_decrypted_courses.py`
  (11, green; education suite 21 green). `modules/education` unchanged → plugin
  mirrors still 333/333.

## How to re-run

```
python tools/migration/refresh_decrypted_courses.py --dry-run    # preview
python tools/migration/refresh_decrypted_courses.py --apply      # apply (app closed)
python tools/migration/refresh_decrypted_courses.py --validate   # re-validate
```

Run with the AI-PACS app **closed** (it holds `dicom.db`); restart it afterward to
see the decrypted attachments in Education → Courses.


## Follow-up — Inline Word (.docx) rendering in the layout (2026-06-13)

Word documents previously routed to the "attachment" path (opened in an external
application). They now render **inside** the Education viewport.

- New module `modules/education/docx_render.py`: a dependency-free `.docx` → HTML
  converter (stdlib `zipfile` + `xml.etree` only — safe for frozen/installed builds,
  nothing to bundle). Handles headings, paragraphs, bold/italic/underline, bullet/
  numbered lists, tables, and inline images (data URIs).
- Viewer (`educational_patient_viewer_widget.py`): added a `QTextBrowser` "Word"
  page to the media stack; `_load_media_content` detects a `.docx` path (regardless
  of the stored content_type) and calls `_show_word`, which converts and displays the
  document, with an "Open in external editor" fallback button. If parsing fails
  (e.g. a legacy binary `.doc` mislabeled `.docx`) it falls back to opening externally.
- No DB change required — the 2 imported Word items keep their `attachment` rows and
  now render inline. Both real course docs convert cleanly (course_18 ≈ 826 words,
  course_19 ≈ 410 words).

Tests: `tests/code/education/test_docx_render.py` (4). Education suite 25 green;
plugin mirrors 334/334 (new file added via `sync_plugin_mirrors.py --add`). Restart
the app to pick up the viewer change.


## Follow-up — Media viewer controls (2026-06-13)

Added interactive controls to the Education media viewport, with an adaptive
control bar that shows only the controls relevant to the current content type:

- **Images:** zoom in/out, fit, reset, **mouse-wheel zoom**, and **drag-to-pan**.
  The image page now uses a `QGraphicsView` (`_ZoomPanGraphicsView`) instead of a
  static QLabel, so it supports true zoom/pan while still fitting the viewport on
  load and resize.
- **PDF:** zoom in/out, fit-to-view, and previous/next **page** navigation; panning
  via the view's scrollbars when zoomed in.
- **Text & Word:** `A-` / `A+` font-size controls (QTextEdit/QTextBrowser zoom).
- **Video:** play / pause / stop **plus a seek slider and elapsed/total time**
  (`m:ss / m:ss`), wired to the player's position/duration.
- **PowerPoint / other attachments:** open in the external application (unchanged).

Implementation: `educational_patient_viewer_widget.py` - new `_ZoomPanGraphicsView`,
an adaptive `media_controls` bar, `_set_media_controls(kind)` to toggle visibility,
and dispatch handlers (`_media_zoom`, `_media_fit`, `_pdf_zoom`, `_pdf_jump`,
`_font_zoom`, seek/position/duration). A module `logger` was also added (previously
missing). Verified headless: fit 1.94x, zoom x2 -> 3.88x, refit -> 1.94x; time format
`1:05`. Compile clean; education suite 25 green; plugin mirrors 334/334. Restart the
app to pick up the controls.


## Fix — Crash/freeze when switching between video and images (2026-06-13)

**Symptom:** the app froze and/or crashed when switching the viewport between a
video and an image. No Python traceback in `app.log` (native crash/freeze).

**Root cause:** the new image page (`_ZoomPanGraphicsView`) called `fitInView()` from
inside `resizeEvent()`. `fitInView` can toggle a scrollbar, which resizes the viewport
and **synchronously re-enters** `resizeEvent → fit → fitInView → …`. That C++↔Python
recursion both spins (freeze) and can overflow the stack (crash). Showing the image
page (e.g. when switching off the video) made the view visible → resize → triggered it.

**Fix:**
- Re-entrancy guard in `_ZoomPanGraphicsView.fit()` (`_in_fit`): any nested `fit()`
  during an in-progress fit is a no-op, so the resize→fit loop can't recurse. Verified
  headless: rapid resizes across scrollbar-toggling sizes (1×1 … 800×600) complete
  instantly with no hang.
- Hardened the media switch: `_show_video`/`_show_audio` now switch to the media page
  **before** (re)setting the source, call `stop()` first, and wrap play in try/except
  (falls back to external open); `_stop_media_playback` is exception-safe. This avoids
  starting the native media sink while the `QVideoWidget` is mid stack-switch.

Compile clean; education suite 25 green; plugin mirrors 334/334. Restart to apply.


## Fix #2 — Crash/freeze when changing item while a video is playing (2026-06-13)

**Symptom:** with a video playing, clicking another item (or prev/next) froze and
crashed the app. `native_fault.log` was not updated -> a hard native access violation
(uncatchable by try/except).

**Root cause:** `_on_item_clicked` branches to `_load_dicom_content` for DICOM items
**without stopping the media player at all**, and the media show-methods only `stop()`
(which is asynchronous) — they never released the source/sink. So the QVideoWidget got
hidden by the `QStackedWidget` switch while the Windows media sink was still rendering
into it → access violation.

**Fix:** new `_teardown_media()` (`stop()` + `setSource(QUrl())` to fully detach the
sink, plus seek-UI reset) is called at the **top of `_on_item_clicked`**, before any
branch and while the video page is still visible. Every content-switch path routes
through `_on_item_clicked` (item click, prev/next item buttons, slide select, and the
drag-drop handler), so the player is always released before the stack hides the video
widget or a DICOM study loads.

Compile clean; education suite 25 green; plugin mirrors in sync. Restart to apply.


## Fix #3 — Video-switch crash persisted: detach sink + defer the switch (2026-06-13)

`stop()` + `setSource(QUrl())` alone was still crashing/freezing when changing item
mid-playback. The codebase's other video widget (`video_slide_widget.py`) uses the same
player pattern but is **created fresh and destroyed** per video — it never hides a live
video sink inside a `QStackedWidget`, which is exactly the education viewer's case. Two
things were still wrong: the Windows media sink stayed **bound to the QVideoWidget** when
it got hidden, and the teardown + hide + heavy DICOM load all ran in **one synchronous
call stack** (backend can't settle → hang/access violation).

**Fix (two parts):**
1. `_teardown_media()` now also calls `setVideoOutput(None)` to **detach the sink from
   the QVideoWidget while it is still visible**; `_show_video()` re-attaches it.
2. `_on_item_clicked` now **defers** the page-switch/new-content load to the next
   event-loop turn (`QTimer.singleShot(0, …)`) **when a video/audio was active**, so the
   native backend finishes releasing before the widget is hidden / a study loads.
   (`_dispatch_item_payload` holds the branch logic, wrapped in try/except.)

Compile clean; media teardown/re-attach API smoke OK; education suite 25 green; mirrors
in sync. Restart to apply.


## Fix #4 (architectural) — Education media pipeline hardening (2026-06-13)

After three symptom patches the video crash kept recurring, so the **architecture**
was changed rather than patched again.

**Root-cause class:** a single persistent `QVideoWidget` lived inside the media
`QStackedWidget` and was *hidden* (not destroyed) on every content switch. The
Windows media backend crashes/freezes when its sink is left bound to a hidden window
— no amount of `stop()`/`setSource()`/`setVideoOutput(None)` fully avoided it. The
codebase's own `video_slide_widget.VideoSlideWidget` never hit this because it is
**created fresh and destroyed** per use.

**New design (mirrors the working pattern):**
- Video/audio pages are now bare hosts. `_show_video`/`_show_audio` mount a FRESH
  `VideoSlideWidget` (its own player + QVideoWidget + play/pause/seek/volume) via
  `_mount_player()`.
- `_destroy_active_player()` tears the whole widget down on every switch:
  `cleanup()` (stop + clear source → releases sink + file lock) → `setParent(None)`
  → `deleteLater()`. **The widget is destroyed, never hidden**, so no live sink is
  ever bound to a hidden window. Removed the persistent `QMediaPlayer`/`QVideoWidget`
  and the old seek/position/duration handlers.
- `_on_item_clicked` still tears media down first and defers the next load one
  event-loop turn when media was active.

**Hardening (all content types):**
- `_load_media_content` is now an **error boundary** — any renderer exception →
  `_show_media_message("could not be displayed…")` + `logger.exception`, never a crash.
- `[EDU_MEDIA]` logging on every load / mount / destroy for diagnosis.
- Image fit keeps the re-entrancy guard (no fitInView recursion); PDF FitInView,
  Word/text reflow, DICOM shared-viewer fit — all resize-safe.

**Verification:** headless cycle with a real H.264 course video — mount → play →
`cleanup()` → `deleteLater()` repeated **5×** in 1.74 s with **no crash/hang**.
Compile clean; education suite 25 green; plugin mirrors in sync. Manual QA checklist
added at `docs/qa/EDUCATION_MEDIA_QA_CHECKLIST.md`.

**Live testing:** requires an app restart to load the new code (Python has no hot
reload). After restart, run the checklist's video-switch cases.


## Fix #5 — Root cause pinned via hung-stack dumps: QMediaPlayer.stop() deadlock (2026-06-13)

Live testing on Monitor A + py-spy stack dumps of the **frozen process** pinned the
exact cause (no more guessing):

- Dump #1 (switch item while playing): MainThread blocked in
  `cleanup()` → `self.player.stop()` (`video_slide_widget.py`).
- Dump #2 (after the cleanup fix, user pressed the **Stop button**): MainThread
  blocked in `stop_video()` → `self.player.stop()`.

**Root cause:** `QMediaPlayer.stop()` deadlocks the UI thread whenever a video sink
(`QVideoWidget`) is attached and rendering — `stop()` waits for the sink to flush its
final frame, but frame presentation runs on the UI thread, which is stuck inside
`stop()`. (PySide6 6.10, default ffmpeg backend.) That the hang *moved* from
`cleanup` to `stop_video` after the first fix confirmed the mechanism.

**Fix (all `stop()` call sites in `video_slide_widget.py`):**
- `cleanup()` (both `VideoSlideWidget` and `SimpleVideoWidget`): detach sinks
  (`setVideoOutput(None)` + `setAudioOutput(None)`) **before** `stop()` — so there's
  nothing to wait on. This is the teardown path used on every item switch.
- `stop_video()` (Stop button) and `SimpleVideoWidget.stop()`: replaced `stop()`
  with `pause()` + `setPosition(0)` — same user-visible result, no pipeline teardown,
  no deadlock. `toggle_play_pause` already uses pause()/play() (safe).

Net: no `QMediaPlayer.stop()` is ever called with a live sink attached. Compile
clean; education suite 25 green; mirrors 335. Pending live re-confirmation after
restart (play → Stop button → switch item; and switch item while playing).


## Fix #6 (definitive) — Persistent player, PAUSE-only switching; never tear down (2026-06-13)

**Complete evaluation.** py-spy hung-stack dumps of the live frozen app showed the UI
thread blocked successively in `cleanup()->setVideoOutput(None)`, `cleanup()->stop()`,
and `stop_video()->stop()`. Every `QMediaPlayer` teardown call (stop / setVideoOutput /
setSource(empty) / destroy) deadlocks the UI thread. Crucially, I could **not reproduce
the deadlock in isolation** — standalone `QApplication.exec()` AND a `qasync` harness
both tore the player down cleanly (stop+setVideoOutput+setSource in <0.01 s). The
deadlock only manifests in the full app context (nested `QApplication.notify`, qasync
loop, FAST-viewer GL context), so no teardown-based fix can be validated outside the app.
QtWebEngine was ruled out as an alternative renderer: this build has **no H.264**
(`DEMUXER_ERROR_NO_SUPPORTED_STREAMS`).

**The only operation proven safe in-app is `pause()`** (the Stop button used
pause+rewind and the app got past it — the hang was always in the *subsequent* teardown).

**Correct fix — never tear the player down during a session:**
- ONE **persistent** `VideoSlideWidget` (its player/sink/controls) is created on first
  video and **reused** for every later clip via new `set_video(path)` (setSource+play
  while the widget is visible — the load path, which does not deadlock).
- Switching away from a video calls only `pause_only()` → `player.pause()`. No stop, no
  setVideoOutput, no setSource(empty), no deleteLater — ever, mid-session. A paused,
  hidden player is safe and is reused next time.
- All `_show_*` / item-switch hooks (`_stop_media_playback`, `_teardown_media`, the
  error boundary) now route to `_pause_active_media()` (pause-only). The ephemeral
  create/destroy approach (Fix #4) and all stop()/detach teardown (Fix #2/#3/#5) are
  removed from the hot path.
- Insurance: `main.py` also forces `QT_MEDIA_BACKEND=windows` (MF) on Windows.

Verified headless: persistent widget reuses one player across clips; `pause_only()` →
PausedState; `set_video()` swaps source in place. Compile clean; education suite 25
green; mirrors 335. Residual: the player is intentionally never destroyed mid-session
(reused); process exit handles final teardown via the app's `os._exit` path.


## Course polish — DICOM integrity audit (2026-06-13): no broken DICOM found

Goal: ensure each item has correct content and remove any broken/incomplete DICOM,
cross-checked against the reference `Storage\Learn`. Four independent read-only audits
were run; **all clean — nothing to remove.**

1. **File-level (pydicom headers):** 153 items with DICOM, **1,345 series, 27,297 .dcm —
   0 header-bad, 0 dead series.**
2. **Render probe (decode one image per series):** **0 undecodable series** — every
   series produces a pixel image.
3. **Viewer references (DB → disk):** 176 items, 334 content rows, 202 DICOM rows —
   **0 missing paths, 0 incomplete (vs claimed counts), 0 undecodable, 0 missing media
   files; every item has ≥1 renderable resource (0 empty items).**
4. **Source cross-check (both directions):** **0 items** where runtime is missing
   decrypted DICOM the source has, and **0 source-all-encrypted** items. The 193
   source `.IPdcom` are encrypted per-series *config sidecars* (e.g.
   `Dicom*/<n>/Config*.IPdcom`), not image instances, so no image data is missing.

Conclusion: the migrated/refreshed DICOM (and image/PDF/video/Word) content is complete
and valid on disk and in the DB; there are **no broken DICOM files or incomplete series
to delete**. Any "broken" appearance in the app is therefore a viewer-load/runtime issue
for a specific item (e.g. the wrong-study-path class), not corrupt data — point me at the
specific course+item and I'll trace its load path. Audit JSON reports:
`user_data/education/migration_reports/dicom_audit.json`, `dicom_audit2.json`,
`dicom_audit_db.json`. No files or DB rows were changed by this audit (read-only).
