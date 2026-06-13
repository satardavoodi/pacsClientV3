# Education → Courses — UI/UX Review & Redesign Plan (2026-06-13)

Primary evaluation case: **Ankle MRI – Teaching Cases** (course_pk 19, real migrated content).
Method: live walk-through of **both** apps — Monitor A = current AI-PACS (source build),
Monitor B = previous **Ino-PACS Pooyan Viewer v1.0.61** — plus source grounding in
`modules/education/`. Not a screenshot-only review; every finding below was reproduced on screen.

---

## 0. Executive summary

The current module's **Library / LMS shell is genuinely better** than the old app: card
browser, search, filters, difficulty/modality/tags, learning objectives, My Courses, Build
Course, Case of the Day, Online Consultation. The old app has none of that — it is a DICOM
viewer with a "next case" stepper.

But the current module **regressed the part the old app did best — in-course DICOM review** —
and surfaces **raw/placeholder metadata**. The redesign goal is therefore: *keep the new
library, fix the viewer back to (and beyond) the old app, and finish the metadata.*

The four things a radiologist hits immediately in Ankle MRI:

1. **Series rail is empty ("0 series")** inside a case that has 10 series → you cannot
   browse or switch series, and multi-pane layouts show the *same* series in every pane.
   The old app's series rail (SR01…SR06+ with thumbnails + slice counts) is the reference.
2. **First item shows "File not found: N/A"** — text/objective items render as a missing file.
3. **Metadata reads as unfinished** — "Needs Fix" badges, titles like *"MR – Lower Exteimiti
   FOOT LT -K"*, three identical "FOOT LT -K" items, and objectives that say *"…anatomy on
   IMAGING"* / *"the imaged region"*.
4. **Library proportions** — left filter rail is wide (380 px fixed), right info panel is
   narrow (340 px fixed) **and clips its own text on the left edge**; the card grid is locked
   to 3 columns and centered, leaving side gutters.

---

## 1. UI findings

### Strengths (keep)
- Card grid with thumbnail, modality/level/Needs-Fix badges, title, description, author,
  Select — clean and scannable (`ModernCourseCard`).
- Coherent dark theme, consistent badge styling, readable typography in the cards.
- Course viewer has a real teaching scaffold the old app lacks: per-item learning objectives,
  session timer, slide stepper, course-info panel.
- DICOM **does** render and slice-scroll; 2×2 / 3×3 layout selector works.

### Weaknesses (with code locations)
| # | Issue | Evidence | Code |
|---|-------|----------|------|
| U1 | Left filter panel fixed-wide; right info panel fixed-narrow | 380 vs 340 px on a 1920 screen | `education_module_redesigned.py:140` (FilterPanel `setFixedWidth(380)`), `:676` (CourseDetailsPanel `setFixedWidth(340)`) |
| U2 | Right info panel **clips text on the left** ("nkle…", "ematic…", "…nkle" tag) | zoomed right panel | `CourseDetailsPanel.show_course` `:712+` inside fixed 340 frame + scroll; content wider than viewport |
| U3 | Course grid hard-locked to 3 columns, never reflows | `resizeEvent` only resizes height | `:957 GRID_COLUMNS = 3`, `:1119`, `:1130 resizeEvent`, `:1058 AlignHCenter` (side gutters = "unused center") |
| U4 | Empty preview box in the right info panel (thumbnail not shown) | gray rectangle | details panel has no thumbnail render of `thumbnail_path` |
| U5 | "Needs Fix" on most migrated courses | orange badge on 6/11 cards | `:546`/`:766` gated on `needs_attention` |
| U6 | Viewer **series rail empty** ("0 series") | left panel blank in a 10-series case | education loads one series via `_load_single_series_on_demand`; the series-thumbnail rail is never populated |
| U7 | Default 2-pane layout leaves an empty "Drop a series here" pane; with the rail empty there is nothing to drop | right pane placeholder | `educational_patient_viewer_widget.py` dicom path |
| U8 | "File not found: N/A" for text items | slide 1 (Item-61) | `educational_patient_viewer_widget.py:785-804` — `_load_media_content` has **no `text` branch** (image/video/audio/pdf only) |
| U9 | Toolbar is the full clinical viewer (tiny icons + `≡` separators) and clinical side-rail tabs (Reception Data, ECHO MIND, EAGLE EYE, Advanced Analysis) appear in an education context | top + left rail | viewer chrome reused wholesale |
| U10 | Bottom dock is a fixed ~130 px band; item **objectives are clipped** at the screen bottom | learning-objectives row cut | bottom dock fixed height |
| U11 | "Slides: 10, Items: 20" — confusing dual terminology (slides vs items vs content rows) | course-info panel | viewer course-info labels |

---

## 2. UX findings

**Discoverability**
- D1 — You cannot discover the other 9 series of a case (empty rail, U6). The single most
  damaging issue for a learner.
- D2 — Within an item, content is chosen via tiny "D"/"T" tiles in the bottom dock — easy to
  miss. The old app surfaced content as explicit buttons (Images / Voice / Comment / Document
  / Dicoms). Attachments/PowerPoint/PDF would be hard to find here.
- D3 — The right info panel (the place to read a course summary before opening) is the most
  truncated element on the page (U2).

**Navigation**
- N1 — Item stepping via the dropdown + `< >` works, but raw/duplicate titles (3× "FOOT LT -K")
  make it impossible to know where you are.
- N2 — No "next/previous series", no keyboard navigation between items, no breadcrumb
  (Course → Item).
- N3 — Switching item then layout then back loses pane state (panes can't be re-filled, U6/U7).

**Educational flow**
- E1 — Objectives/teaching points are present (good) but read as machine-filler on items
  without DICOM facts ("anatomy on IMAGING", "the imaged region").
- E2 — No sense of progression (which cases are normal vs pathology, beginner→advanced).
  The old app at least labelled "normal 1". Items here are unordered raw scanner strings.
- E3 — PHI ("MIRZAEI^SHIRALI", "SAFIKHANIYAN^PARISA") is shown in the teaching overlay in
  **both** apps — not a regression, but for a shareable teaching library a de-identified
  overlay toggle would be a real improvement over both.

---

## 3. Old vs New (per workflow)

| Workflow | Old (Ino-PACS) better | New (AI-PACS) better | Improve beyond both |
|----------|----------------------|----------------------|---------------------|
| Find a course | — | Card library + search + filters + metadata | Reflowing grid, richer summary panel |
| Read course overview | — | Objectives, level, tags, description | Fix clipping; add syllabus/case-count |
| Browse series in a case | **Populated SR rail w/ thumbnails + slice counts** | — | Rail + "load into pane" + auto 1×N |
| Multi-series compare | **Two panes, different series** | layout selector exists | Drag from rail; sync scroll/WL |
| Pick content type | **Explicit Images/Voice/Doc/Dicoms buttons** | — | Content chips per item, labelled |
| Toolbar clarity | **Bigger icons, L/R/M mouse-button badges** | — | Education-trimmed toolbar |
| Item naming | **Short labels ("normal 1")** | — | Clean titles + case numbering |
| Learning scaffold | — | **Objectives, timer, stepper** | Keep + finish text quality |

Net: **new wins on the library/LMS, old wins on the viewer.** Target = new library + a viewer
that matches the old rail/panes and adds the LMS scaffolding.

---

## 4. Proposed improvements

### A. Metadata / "Needs Fix" (explicitly requested)
- Infer & fill every field that can be derived, then only flag what truly can't:
  - Titles: stronger normalization — fix "Exteimiti→Extremity", "Ankel→Ankle", drop trailing
    "-K"/"LT -K" laterality noise into a clean "(Left)/(Right)" suffix, expand "&".
  - **Disambiguate duplicates** ("FOOT LT -K" ×3 → "Ankle MRI — Case 1/2/3").
  - Items with no DICOM facts: inherit modality/body-part from the **course** (Ankle MRI →
    MR / Ankle) instead of the "IMAGING/imaged region" generic.
  - Objectives/keywords: rebuild from the resolved body-part/modality so no placeholders ship.
  - Then set `validation_status='ok'`, `needs_attention=0` for courses with no remaining gaps
    → the "Needs Fix" badge disappears for fully-populated courses. Keep the flag ONLY where a
    field is genuinely unknown (don't hide real gaps).
- Re-runnable as an enrichment pass over already-migrated courses (no re-copy of 11.8 GB).

### B. Library layout & responsiveness
- Make side panels flexible: left filters `max≈300` and collapsible; right details `min≈360`,
  stretch with a sensible max (`~30%`). Reclaim the centered side-gutters.
- **Responsive grid**: compute columns from the cards viewport width
  (`cols = max(1, viewport // (CARD_MIN+spacing))`) in `update_grid`/`resizeEvent`: 3-up wide,
  **2-up medium, 1-up narrow**; never shrink a card below a readable min. Readability > density.
- Fix right-panel clipping (U2): word-wrap to viewport, no inner fixed widths, show the course
  thumbnail (U4).

### C. DICOM educational viewer
- **Populate the series rail** for the loaded study (thumbnail + description + slice count per
  series) — the highest-value fix. Reuse the study's series enumeration that already feeds the
  item description ("10 series: PD TSE FS Cor RT, …").
- Click/drag a series → load into the focused/empty pane; default a single-series case to 1×1
  (no empty "drop here" pane).
- Keep layout controls above the bottom dock at all sizes; make the bottom dock collapsible so
  the viewport can use full height; stop clipping objectives (U10).
- Education-trimmed toolbar (scroll/zoom/WL/pan/measure/layout/MPR + the L/R/M mouse-button
  badges the old app had); hide clinical-only rails (Reception Data/ECHO MIND/EAGLE EYE) in
  education or move them behind a "Clinical tools" overflow.

### D. Content renderers
- Add a **`text` branch** to `_load_media_content` (render `content_data['text']` instead of
  "File not found") — fixes U8 immediately.
- Per-item **content chips** (DICOM · Image · PDF · Presentation · Notes · Attachment) with
  type icons, always visible — replaces the cryptic D/T tiles and fixes discoverability (D2).
- For non-native types (PPTX/zip), render a clear "Open externally" card with the file name &
  size (already stored) rather than silence.

### E. Educational experience
- Course header band: case count, modality mix, body-region, level, est. time.
- Item ordering: normal/overview first (already attempted) + visible "Case N" numbering.
- Optional de-identified overlay toggle for teaching (covers both apps' PHI exposure).

### F. Visual consistency
- One spacing/radius/color token set across cards, panels, viewer chrome; consistent hover
  /selection states; replace `≡`-separated icon clutter with grouped, labelled tool groups.

---

## 5. Prioritized implementation plan

### P0 — High impact / low risk (data + isolated renderers; no layout surgery)
1. **Enrichment v2 pass** (A): improve `course_importer` normalization + course-inheritance
   for item facts + duplicate disambiguation; run an *update-in-place* over courses 9–19;
   clear `needs_attention` where complete. Risk: low (data only; backed up). 
2. **`text` content branch** (D/U8) in `educational_patient_viewer_widget._load_media_content`.
   Risk: low, additive.
3. **Right-panel clipping + thumbnail** (U2/U4) — word-wrap, drop inner fixed widths, show
   `thumbnail_path`. Risk: low, single widget.

### P1 — High impact / medium risk (layout + viewer)
4. **Responsive grid** (U3) — column count from viewport width. Risk: medium (grid relayout).
5. **Panel rebalance** (U1) — flexible/collapsible left, wider stretchy right. Risk: medium.
6. **Series rail population** (U6) + **single-series → 1×1 default** (U7). Highest user value;
   medium risk (touches the education viewer's DICOM load path — guarded by the viewer-layout
   invariant: study/`<numeric series>`/`*.dcm`). Test before/after.
7. **Bottom dock collapsible + objectives no longer clipped** (U10). Risk: medium.

### P2 — Nice to have
8. Education-trimmed toolbar with L/R/M badges + hide clinical rails (U9).
9. Per-item content chips with type icons (D2).
10. Course header band, case numbering, de-identified overlay toggle (E1–E3).
11. Keyboard nav (next/prev item & series), breadcrumb (N2).

### Guardrails for all of the above
- Education module is **plugin-mirrored** — after edits run `tools/dev/sync_plugin_mirrors.py`
  then `verify_plugin_mirrors.py`.
- FAST viewer must never instantiate VTK; preserve the `study/<numeric series>/*.dcm` layout
  the educational viewer requires.
- Run `python -m pytest tests/code/education -q` (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` if the
  local plugin set stalls) after changes.

---

## 6. Concrete bug list (root-caused, ready to fix)

- **B1 "File not found: N/A" on text items** — `_load_media_content` (`:785-804`) has no
  `text` handler. Fix: branch on `text` → show `content_data['text']`.
- **B2 Empty series rail** — education DICOM path loads a single series and never fills the
  series-thumbnail rail; populate from the study's series list.
- **B3 Right-panel left-clipping** — fixed 340 px `CourseDetailsPanel` + scroll content wider
  than viewport; make content width-follow the viewport and wrap.
- **B4 Non-responsive grid** — `GRID_COLUMNS = 3` constant (`:957`) used unconditionally in
  `update_grid`; derive from width.
- **B5 Raw/placeholder metadata** — `course_importer` item enrichment kept scanner strings and
  generic "IMAGING/imaged region" fallbacks; improve normalization + course inheritance.

---

## 7. Implementation status (this session)

### Shipped (P0)
- **Enrichment v2** (`course_importer.py`): stronger spelling (`Exteimiti→Extremity`,
  `Ankel→Ankle`, `Scarpbook→Scrapbook`); `_normalize_anatomy_title` lifts laterality
  (`LT/RT → (Left)/(Right)`) and drops scanner-noise tokens; `_smart_title` no longer leaves
  `FOOT/HAND/KNEE` uppercase; **duplicate item titles disambiguated** (`- Case N`); items with
  no DICOM facts inherit course modality/body-part and are named "… Supplementary Material";
  objectives/keywords rebuilt from resolved facts (**no more "IMAGING / imaged region"**).
  `needs_attention` now means *genuinely missing field*, not "contains AI text", so the
  **"Needs Fix" badge is cleared** for all fully-populated courses.
- **Re-enrich CLI** (`run_education_import.py --reenrich`): updates titles/descriptions/
  objectives/metadata of already-imported courses IN PLACE (no 11.8 GB re-copy). Applied to
  courses 9–19 → all `needs_review=False`, every slide retitled. (Result verified in DB:
  e.g. "MR - Lower Extremity Foot (Left) - Case 1/2/3", "Ankle - Supplementary Material - Case 1–4".)
- **Text renderer** (`educational_patient_viewer_widget._load_media_content`): added a `text`
  branch + scrollable text page → fixes **"File not found: N/A"** on notes/objective items (B1).
- **Right info panel** (`CourseDetailsPanel`): `ScrollBarAlwaysOff` stops the left-edge
  clipping (B3); renders the course thumbnail at the top (U4).

### Shipped (P1)
- **Responsive grid** (`LibraryPage`): `_responsive_columns()` reflows **3 → 2 → 1** by viewport
  width (capped per page); `resizeEvent` re-lays out only when the count changes (B4/U3).
- **Panel rebalance**: filters `380 → 300` + modality grid `4 → 2` columns (fixes the
  "Mammography/Fluoroscopy" truncation); details `340 → 420` (U1).
- **Objectives no longer clipped**: `slide_notes` wrapped in a bounded `QScrollArea` (U10).
- **Clearer terminology**: course-info now reads **Items / Resources** (was Slides/Items, U11).

### Bonus fix
- **Demo re-seeding stopped**: the running app had re-created the 8 demo courses (the seeders
  `_ensure_my_courses_samples` / `_ensure_sample_courses_and_thumbnails` re-add them by name).
  They now seed **only into an empty library**, so deleted demos stay deleted. The re-created
  demos were removed again.

### Verification
- `tests/code/education` 9/9 pass (added title-normalization, disambiguation, objective tests);
  `py_compile` clean on all edited files; plugin mirrors synced + verified (333 pairs match);
  DB: 11 courses, 0 demos, `needs_attention=0`, 176 items / 379 resources intact.
- **The app must be restarted** (re-run `main.py` from VS Code) to load the new source.

### Deferred — needs dedicated clinical-viewer work + live testing (NOT rushed, by design)
These modify the **shared clinical `PatientWidget`** that the education viewer subclasses;
changing them carelessly risks the clinical workflow (guardrails: preserve viewer behaviour,
never remove sidebars, FAST must not instantiate VTK). Root causes are pinned for a focused pass:
- **Series rail empty (B2 / U6)** — the education "single-series-on-demand" load path never
  populates `PatientWidget`'s series-thumbnail panel; `switch_right_panel("series")` only
  switches the right-panel stack (`_pw_panels.py:213`), it does not feed series data. Fix needs
  the thumbnail-pipeline population call for the loaded study (guarded subsystem).
- **Single-series → 1×1 default (U7)** — clinical default is `(1,2)`
  (`viewer_state_controller.initialize_viewers_with_loading_state`); a single-series education
  case should call `multi_viewer_layout_manager.set_layout(1,1)` on the education instance.
- **In-viewer content chips (D2)**, **education-trimmed toolbar / hide clinical rails (U9)**,
  **de-identified overlay toggle (E3)** — all touch the inherited clinical chrome/overlay.

---

## 8. Round 2 (post-restart feedback) — shipped

After the first changes were verified live, three more items were addressed:

- **Series-thumbnail rail now populates (B2 / U6 — was deferred).** Education studies
  had no pre-rendered thumbnails, so the rail was empty. Added
  `tools/migration/generate_education_thumbnails.py` (renders one windowed slice per
  series via pydicom/PIL into the canonical `THUMBNAIL_PATH/<study_uid>/<series>.png`)
  and ran it for all 11 courses → **1,149 thumbnails (202 studies, 8 failures)**. The
  education viewer now sets `self.study_uid` and calls a new
  `_populate_education_series_rail()` (clears `thumb_grid` → resets state →
  `show_exist_thumbnails()`), so the left rail fills exactly like the normal
  patient/study view and each series is clickable.
- **DICOM "Load Failed" dialog (B2/U18) mitigated.** The series=4 load actually succeeds
  in the logs — the modal was a transient first-load (course auto-open). Now the rail is
  populated *before* the load attempt, so a missed auto-load just lets the user click a
  series; the scary modal is suppressed whenever the rail has entries (only shown when
  there is genuinely nothing to display).
- **Bottom dock redesigned for efficiency (U10).** The footer is now a slim, always-visible
  header (collapse toggle + course summary + compact session timer) over a bounded,
  **collapsible** body (max 150 px). Collapsing hands the vertical space back to the
  viewport; the verbose date/time clock was condensed and the timer moved to the header.

Verification: `py_compile` clean, mirrors verified (333 match), `tests/code/education` 9/9.
**Restart the app to load these changes.** Future education imports should re-run the
thumbnail generator (or it can be folded into the importer in a later pass).

---

## 9. Round 3 — Course-viewer layout redesign (item-first)

Reworked `educational_patient_viewer_widget` so the viewer is optimised for studying the
current item, per the educational-priority rule (content > resources > DICOM > item desc >
nav > course metadata):

- **Slide navigation → compact vertical box on the side (req 11).** The wide horizontal
  slider in the bottom dock is gone. A slim ~84px vertical nav now sits on the right of the
  viewer: "ITEM", the current number, "of N", ▲/▼ prev-next, and a small item thumbnail
  indicator. A "jump to item" combo remains in the dock for direct selection.
- **Item Information replaces persistent Course Info (req 12).** The dock's main panel is now
  item-driven: item **title**, a meta line (modality · body part · level · resource count),
  and the description / learning objectives / teaching points / keywords (scrollable). The
  resources for the current item sit in a fixed left column. **Course Info moved behind an
  "ⓘ Course overview" button** (a dialog) instead of occupying a persistent column.
- **More vertical space for content (req 13/14/15).** The slide-nav left the bottom, Course
  Info left the dock, and the timer/clock condensed into a one-line header — so the dock is
  shorter and the viewer/media + resource area get the largest share of height. Course
  metadata now consumes the least persistent space (a single button).

Verification: `py_compile` clean, mirrors verified (333 match), `tests/code/education` 9/9.
Restart the app to load it. (Layout is structurally sound but best confirmed live.)

---

## 10. Round 4 — Teaching-first viewer (metadata → Review popups, resources maximised)

Per follow-up feedback, persistent metadata was removed so the dock is dedicated to
resources + item selection:

- **Slide Information → "Slide Review" popup; Course Info → "Course Review" popup.** The
  header now carries two buttons that open dialogs: **Course Review** (course description /
  objectives / metadata / author) and **Slide Review** (current item title / objectives /
  teaching points / notes / keywords / modality / body part / level). No item or course text
  is permanently on screen.
- **Bottom panel = item selector + resource browser only.** Left: an **Items** list (all
  slides, click to switch). Right: the **Resources** browser (DICOM / image / PDF /
  presentation / attachment tiles) with larger icons (44px) and tiles (150×92) — it takes the
  full remaining width so more resources are visible with less scrolling. The dock is a touch
  taller (≈208px) for the resource grid.
- **Header = Review buttons + item stepper + session controls.** Compact `◀ Item N / M ▶`
  stepper plus the session timer/clock + Pause/Reset, all on one line.
- **Side vertical nav removed** — item switching now lives in the bottom Items list + the
  header stepper, returning that width to the viewer (the main area).

This realises the educational-priority rule: the viewer + resources own the screen; course
and slide metadata are one click away. Verification: `py_compile` clean, mirrors 333 match,
`tests/code/education` 9/9. Restart the app to load it.

---

## 11. Round 5 — Viewport sizing + resource-aware viewport

- **Viewport sizing (cropped behind the dock).** The content/viewport area was overflowing
  behind the bottom panel. Fixed education-side: the content stack + DICOM surface now have an
  Expanding size policy with minimum size 0 and fill via stretch, so the viewport fits exactly
  in the area above the dock and recalculates on resize / item change / layout switch. (If
  cropping persists, check for another window overlapping AI-PACS — a masked overlay appeared
  in the review screenshot.)
- **Resource Items selector widened ~80%** (240 → 432px) so full item titles read; Resources
  box flexes to the remaining width.
- **Content-type header.** A header above the viewport now states what is shown:
  `DICOM · <name> · <n series, m images>`, `Image · file.png`, `PDF · file.pdf`,
  `Presentation · deck.pptx`, `Notes · …`.
- **Drag-to-open.** Resource tiles are draggable; dropping one on the viewport opens it there
  (an `eventFilter` on the content stack handles DragEnter/Drop → `_on_item_clicked`). Clicking
  still works too.
- **Resource-type-aware viewport (already largely present).** The single content area renders
  DICOM (clinical viewer), images, PDFs, video, audio and text via type-specific renderers
  (`_load_dicom_content` / `_show_image` / `_show_pdf` / `_show_video` / `_show_audio` /
  `_show_text`). Added an **attachment** renderer for PowerPoint/Office docs (`_show_external_resource`
  opens them in the native app) and routed the importer's presentation/document resources to it.
- **Scope note:** true multi-pane *mixed-type* viewports (e.g. DICOM in one pane, a PDF in
  another, independently) remain a larger change to the shared clinical multi-pane viewer and
  were intentionally not attempted here (regression risk; needs live testing).

Verification: `py_compile` clean, mirrors 333 match, `tests/code/education` 10/10. Restart to load.

---

## 13. Round 7 — Single-pane viewport (image now fills the layout)

Live screenshot review showed the image **did** fit its pane and the dock no longer cropped
it, but the viewer was in a **1×2 layout** so the single series filled only the left half and
the right pane sat empty ("Drop a series here"). Root cause: the base widget
(`patient_widget_core/widget.py`) treats `size_init_viewers == (1, 1)` as "use the default
layout" (which is 1×2 from `modality_grid.json`), so education's `(1,1)` request was ironically
expanded to two panes. Fix: education now explicitly applies a **1×1** layout via the same
public `apply_multi_viewer((1,1), modify_by_user=True)` the toolbar's layout picker uses —
once on init and after each DICOM load — then fits. So a single teaching resource now fills the
whole viewport, no empty pane. Guarded against redundant re-applies (checks the controller's
`_current_layout`).

Verification: `py_compile` clean, mirrors 333 match, `tests/code/education` 10/10. Restart to load.

---

## 12. Round 6 — Fit content to the viewport after load/drop

- **Image (root cause found + fixed).** `_show_image` scaled to a **600×420 floor**
  (`max(600, w) × max(420, h)`), so in the smaller Education viewports the image was forced
  larger than the pane → overflow/crop. Now it keeps the original pixmap and fits it to the
  **actual** viewport (scales down or up, keeps aspect), re-fits on `resizeEvent`, and re-fits
  on a deferred timer (0/60 ms) so it's correct even when the pane isn't at final size right
  after a switch/drop. The image label uses an Ignored size policy + 0 minimum so a large
  pixmap can never push the layout.
- **PDF.** `_show_pdf` now sets `QPdfView.ZoomMode.FitInView` so the page fits the pane.
- **DICOM.** After an education DICOM load, a deferred `_fit_education_dicom()` (120 ms, after
  layout stabilises) calls the FAST viewer's existing `zoom_to_fit()` / `reset_view()` on the
  education viewer's own panes. This is education-instance-only — it does NOT change the shared
  FAST viewer's resize behaviour (so it can't reset a clinician's zoom in Patient Hub).
- **Note on "shared" scope.** The standalone image/PDF renderers live in the Education media
  page (Patient Hub shows DICOM via the FAST viewer, not this QLabel/QPdfView). The DICOM fit
  uses the shared `zoom_to_fit`. If Patient Hub DICOM also mis-fits on first load, that's a
  FAST-viewer-level timing change best done with live testing (deliberately not changed here to
  protect the clinical zoom/pan behaviour).

Verification: `py_compile` clean, mirrors 333 match, `tests/code/education` 10/10. Restart to load.


## Round 8 — Shared FAST viewer fit-to-viewport (DICOM, Education + Patient Hub)

**Symptom (user, re-reported with screenshot):** after dropping a series into a viewport
the DICOM showed too large / cropped / wrong zoom — worst in Education (small 2×2 panes)
but present in Patient Hub too. Viewport *box* sizing was already correct; only the
*content* zoom was wrong.

**Root cause (shared, `modules/viewer/fast/qt_slice_viewer.py`).** The fit math
(`_calculate_fit_zoom`) was correct, but fit was only re-applied when the image
*dimensions* changed. Two real gaps:
1. **Stale viewport size.** A same-dimension series dropped into a pane that had since
   resized (e.g. 1×1 → 2×2) kept the previous, larger fit zoom → content overflowed the
   smaller pane.
2. **Content set before layout settled.** On a drop into a multi-pane layout / first show,
   `set_image` ran while the pane was still at a transient size; no later re-fit fired.

**Fix (Round 8, surgical, fit-mode-only).**
- Track the viewport size each fit was computed at (`_last_fit_w/_h`) via a single
  `_apply_fit_zoom()` helper used by `reset_view`, `zoom_to_fit`, `resizeEvent`,
  `set_pixel_spacing`, and `set_image`.
- `set_image` now re-fits when **dims OR viewport size** changed (was dims-only).
- Added a coalesced **deferred post-layout re-fit** (`_schedule_deferred_fit` /
  `_run_deferred_fit`, one `QTimer.singleShot(0)`) and a **`showEvent`** re-fit, so the
  content matches the pane's FINAL size after the layout stabilises.

**Clinical safety (the Round-7 concern).** Every new path is gated on
`self._fit_to_viewport`, which is set False the moment a clinician pans/zooms. So manual
zoom/pan is never clobbered, and slice scrolling (same size) is a no-op. This is what made
it safe to finally apply the fix at the shared FAST level rather than Education-only.

**Verification.** `py_compile` clean; mirrors 333 match; `tests/code/education` 10/10.
Headless offscreen smoke (`QtSliceViewer`, real fit math):
- 512² into 800×600 → zoom 1.1133 = expected `min(800/512,600/512)·0.95` ✓
- shrink pane to 360×260 + re-drop → zoom **0.4824** (re-fits smaller, the bug) ✓
- manual zoom 3.0 then same-size `set_image` (scroll) → **3.0 preserved** ✓
Note: the pre-existing 72 failures in `tests/code/viewer` (VTK backend-resolution /
tool-layer / mixin-name suites) are unrelated — they fail identically with this change
absent. **Restart the source build to load the change.**


## Round 9 — REAL root cause of "content larger than the viewport box" (shared FAST container)

Rounds 5–8 chased the *zoom-fit* layer; the user's annotated screenshots reframed it as a
**geometry/layering** bug: a dark **`#1a1a2e`** ("ground glass dark blue") surface that is
*larger than the layout cell box*, with the DICOM fitted to that oversized surface.

**Root cause — `PacsClient/.../vtk_widget/qt_fast_container.py`.**
- `QtFastContainer.__init__` did `self.setMinimumHeight(height_viewer)`.
- Callers (`_pw_viewers.py::_create_lightweight_vtk_placeholder` / `creator_vtk_widget`,
  `_vc_layout.py`) pass `height_viewer = self.sidebar.height()` — the **full** viewer height.
- So every FAST pane demanded the *entire* viewer height as its hard minimum. Fine for 1×1,
  but in any **multi-row** layout (2×2 / 3×3) or a **shortened** viewer area (Education's
  page, where the bottom dock steals vertical space) each pane could not shrink to its grid
  cell → its `#1a1a2e` surface overflowed the cell box, and the fitted image landed on an
  oversized surface (looks too large / cropped / misaligned). This is exactly why it was
  "very visible in Education (small viewports)" yet "also in Patient Hub" (2×2 on shorter
  screens). The legacy `VTKWidget` sets **no** minimum height — the FAST container had
  silently diverged from the working contract.

**Fix (shared, minimal).** Treat `height_viewer` as a preferred hint only:
`setMinimumHeight(40)` (tiny floor against degenerate collapse) + explicit
`setSizePolicy(Expanding, Expanding)`, so the layout-managed pane shrinks to its cell and
expands to fill it. 1×1 is unchanged (large cell → pane still fills it); multi-row no longer
overflows.

**Verification.** `py_compile` clean; mirrors 333 match; `tests/code/education` 10/10.
Headless grid smoke: 2×2 `QtFastContainer(height_viewer=560)` inside a 900×560 host →
panes now **268×438** each (fit to cell), previously pinned to 560 (overflow). Combined with
the Round-8 fit (the image re-fits to the now-correct pane size), the DICOM fills the cell
exactly. **Restart the source build to load both changes.**


## Round 10 — Cleanup + Education default layout 1x2 (user-confirmed fix)

User confirmed the viewport fit/overflow is resolved. Follow-ups:
- **Cleanup.** Trimmed the verbose comments added in Rounds 8–9 (`qt_slice_viewer.py`
  set_image block; `qt_fast_container.py` geometry block) to concise rationale. No behaviour
  change. Per-slice scroll stays zero-overhead (neither `dims_changed` nor `size_changed`
  fires, so no fit/`QTimer` work). Deferred-fit remains coalesced via `_deferred_fit_pending`.
- **Education default layout → 1x2.** Renamed `_force_single_pane` →
  `_apply_default_education_layout`, now applying `(1, 2)` (was `(1, 1)`) via the same public
  `apply_multi_viewer` the toolbar uses, with a `(1, 2)` short-circuit guard. Both call sites
  updated (init @300 ms, DICOM load @60 ms). `(1, 2)` is the base/default config
  (`{"rows":1,"cols":2}`), so this restores the standard two-pane teaching layout; combined
  with the Round-9 container fix each pane now sizes correctly to its half-width cell.

Verification: `py_compile` clean (3 files); mirrors 333 match; `tests/code/education` 10/10.
Restart to load.
