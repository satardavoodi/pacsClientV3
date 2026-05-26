# Responsive UI — Monitor A vs Monitor B Test Criteria
**Created:** 2026-05-26
**Purpose:** Define the rubric and procedure BEFORE the live monitor test so Monitor A and Monitor B results are directly comparable.
**Scope target:** the 90 % share of responsiveness problems that should be solvable with Qt-native primitives (per `RESPONSIVE_UI_ROOT_CAUSE_2026-05-26.md`).
**Status:** rubric only — no testing performed yet. Awaiting user signal that the source build is running on Monitor A.

---

## 1. Severity scale (use the same labels on both monitors)

| Severity | Meaning | Example |
|---|---|---|
| **C — Critical** | Blocks workflow OR clinical content is hidden / unreadable | Patient list clipped; viewer toolbar buttons disappear off-screen; settings page content unreachable |
| **M — Major** | UI is broken visually but workflow is still possible with effort | Buttons overlap but still clickable; text truncated mid-word; sidebar resize fights back |
| **m — Minor** | Cosmetic / spacing imperfection that an experienced user could ignore | Slight icon-to-text gap inconsistency; one row of a form 2 px taller than its neighbours |
| **OK** | Behaves correctly at this monitor size | Layout reflows cleanly, no clipping, no overlap |
| **N/A** | Screen not reachable / module disabled in this run | EchoMind tab when module is off |

Every issue captured during the tour gets one of these letters.

---

## 2. KPI / visual criteria — what we are looking for on every screen

A screen passes a KPI when all sub-criteria are met. If any sub-criterion fails, mark the KPI as C/M/m per §1.

### 2.1 Geometry KPIs

| KPI | Pass criterion | Typical failure to look for |
|---|---|---|
| **G1 — No element overlap** | Every interactive element occupies a non-overlapping rectangle | Buttons sit on top of each other; close-button overlaps title text |
| **G2 — No clipped content** | All visible text fits the widget's bounds; no `...` truncation on labels meant to be fully visible | Title bar text cut by user info container; settings field labels lose right-hand letters |
| **G3 — No hidden elements** | Every element that should be visible at this monitor size is rendered on-screen | Save / Cancel buttons fall below the bottom edge with no scrollbar; toolbar items pushed off-right |
| **G4 — Window-edge respect** | Nothing is drawn outside the application window's content area | A popup or dropdown extends past the screen edge |
| **G5 — Scrollbars appear when needed, hidden when not** | `ScrollBarAsNeeded` behaviour holds | Content overflows but no scrollbar; or scrollbar present on a panel that fits |

### 2.2 Typography KPIs

| KPI | Pass criterion | Typical failure |
|---|---|---|
| **T1 — Readability floor** | All body text ≥ 10 device-independent px effective height | Body text rendered at 7–8 px — squint test |
| **T2 — Readability ceiling** | No body text exceeds 24 device-independent px (cosmetic, not workflow-blocking) | Heading rendered at 32 px on a small monitor, dominating the column |
| **T3 — No mid-word truncation** | If text must shorten, it ends with `…` after a whole word boundary where possible | "Patien…" mid-word |
| **T4 — Consistent typeface** | Same widget category (e.g. all form labels) uses one face + weight | Some labels Segoe UI, others fallback sans-serif |

### 2.3 Icon & control KPIs

| KPI | Pass criterion | Typical failure |
|---|---|---|
| **I1 — Icon legibility** | Toolbar / sidebar icons are visually identifiable at this scale | Icons render at 14 px and look like dots |
| **I2 — Hit-target size** | Clickable area ≥ 28 × 28 device-independent px (Qt + Windows desktop convention) | Close button is 16 × 16 — too small for older users |
| **I3 — No icon clipping** | The full glyph fits its container with at least 2 px margin | Icon edges chopped because container shrank but `setIconSize` did not |
| **I4 — Crisp rendering** | No fuzzy / smeared icons; raster icons match `devicePixelRatio` | Logo is blurred because no `@2x` variant was loaded |

### 2.4 Layout-behaviour KPIs (the ones that reveal the `setFixed*` problem)

| KPI | Pass criterion | Typical failure |
|---|---|---|
| **L1 — Reflow on horizontal resize** | When the window narrows, content rearranges (wraps / scrolls / shrinks gracefully) instead of overlapping | Settings form columns collide because field widths are pinned |
| **L2 — Reflow on vertical resize** | When the window shortens, vertical scrollbar appears or content compresses | Settings page is taller than viewport; bottom row of buttons inaccessible |
| **L3 — Sidebar resize honoured** | If the panel is meant to be user-resizable, drag works and persists; if fixed, it stays fixed cleanly | Sidebar snaps back to default width on click; or resizes but content inside doesn't reflow |
| **L4 — Tab strip overflow** | When tabs exceed strip width, either scroll buttons appear (QTabBar style) or strip scrolls horizontally | Patient chips overlap each other instead of becoming reachable via scroll |
| **L5 — Spacing & alignment consistency** | Equivalent widgets across screens use comparable gaps; labels align on a column | Form field gaps vary 4–14 px between rows; one row is left-shifted |
| **L6 — Same widget kind looks the same** | All `QPushButton`s in one dialog share padding, font-size, height tier | One button 28 px tall, sibling 36 px tall |

### 2.5 Cross-monitor specific KPIs (only relevant when comparing A vs B)

| KPI | Pass criterion | What it tells us |
|---|---|---|
| **X1 — Proportional growth** | Going from small monitor to larger monitor, panels grow / fit more content rather than letterbox or stay tiny | If the app stays the same 1024-px wide on a 4K monitor, the main window has a `setFixedSize` it shouldn't |
| **X2 — Same DPI behaviour** | If both monitors are at the same Windows scaling %, geometry should look identical at the same window size | Drift indicates `screen().logicalDotsPerInch()` mid-flight differences |
| **X3 — Cross-monitor drag stability** | Dragging the app window from A → B while open does not break layout (clipping / overlap) | If it does, per-monitor V2 awareness is not behaving |
| **X4 — Per-monitor font size stability** | Same `font-size: 14px` reads at proportionally similar physical size on both monitors | If letters are physically tiny on the larger monitor, Qt DPI auto-scale is partial |

---

## 3. Screen tour — exact order, what to capture, what to test

This is the canonical sequence. Both monitors must follow it in the same order so the comparison is direct. Captures go to `docs/plans/responsive_ui_baselines/monitor_<A|B>/<NN>_<screen>.png`.

### Pre-tour setup (you, the user)
- Make sure the app is running from the VS Code source build (per `CLAUDE.md`).
- Move the app window to the monitor under test.
- Maximize the app window so we measure the worst-case real-estate the layout actually has.

### 3.1 Login screen / app shell — `00_shell_default`
**Capture:** full window.
**Check:** title bar height & content (G1, G2), user info container fit (G1, G2), tab area not yet populated (G3, L4).
**Resize test:** drag the bottom-right corner inward 200 px width × 150 px height and re-capture as `00b_shell_resized`. Watch for: title bar overflow, user info pushed off-right, minimize/maximize/close buttons clipped.

### 3.2 Home page (default after login) — `01_home`
**Capture:** full window + a zoom-in of the patient table header.
**Check:** patient table column widths (G2, L1), left navigation pane icons & labels (I1, I2, L5), right panel thumbnails grid (G1, L1).
**Resize test:** narrow the window so the navigation pane is forced to a tighter width. Capture as `01b_home_narrow`. Watch for: icons + labels in nav pane overlapping or label disappearing.

### 3.3 Patient open (any patient) — `02_patient_first_open`
**Capture:** full window, focus on the new patient tab chip and the viewer toolbar.
**Check:** patient tab chip (`patient_tab_widget.py:113-115` is `Fixed/Fixed`) fits the title bar without overlapping the user info container (L4, G1).
**Workflow:** open 4 more patients (5 total). Capture `02b_five_tabs` after each open. Watch for: 5th chip overlapping prior chips, chips going past the right edge, tabs becoming partially hidden.

### 3.4 Viewer — `03_viewer_default_layout`
**Capture:** full window with the viewer toolbar in default state, thumbnail sidebar at default width.
**Check:** toolbar (`toolbar_manager.py`) buttons fit (G3, L1), thumbnail sidebar (`thumbnail_panel.py:setFixedWidth(216)`) does not crowd the main image area (L3), reference lines / overlays render (out of scope for layout test but note any regression).
**Resize test:** drag the viewer-toolbar window narrow; capture as `03b_viewer_narrow`. Watch for: toolbar buttons pushed off-screen or overlapping each other.

### 3.5 Multi-study patient (if available) — `04_multistudy`
**Capture:** full window, focus on grouped sidebar layout.
**Check:** grouped study headers do not overlap series rows (G1), sidebar scrolling works (G5, L2).
**Important regression guard:** per project rules, multi-study path must remain functional — note any failure to render a second study, not just layout issues.

### 3.6 Settings → Server Settings tab — `05_settings_server`
**Capture:** full window, then scroll down inside the tab and re-capture as `05b_settings_server_scrolled` (if scrolling exists).
**Check:** form fields fit (G2), Save/Verify/Delete/Clear buttons all visible without overflow (G3, L2), labels align (L5).
**Resize test:** shorten the window vertically until buttons risk falling off; capture as `05c_settings_server_short`. Watch for: bottom buttons disappear with no scrollbar (this is THE bug from §4.2 of the root-cause doc).

### 3.7 Settings → Tools Settings — `06_settings_tools`
Same protocol as 3.6.

### 3.8 Settings → Viewer Configuration — `07_settings_viewer`
Same protocol. Special attention to the modality grid layout (custom `setFixedSize(29, 29)` grid buttons — L6).

### 3.9 Settings → Image Filter — `08_settings_filter`
Same protocol.

### 3.10 Settings → Installation & Updates — `09_settings_install`
Same protocol.

### 3.11 Toolbar dropdowns — `10_toolbar_dropdown`
**Capture:** open a viewer-toolbar dropdown (Layout / Window-Level / Filter, whichever is convenient) and capture as `10_toolbar_dropdown`.
**Check:** dropdown popup width (G4, doesn't extend past window edge), entries readable (T1), check-state indicators visible (I1).

### 3.12 Reception panel (if reachable) — `11_reception`
**Capture:** patient open with reception panel toggled on (right panel switches from 260 → 442 px per `_pw_panels.py`).
**Check:** wider panel doesn't crowd main viewer (L3); labels fit (G2).

### 3.13 CD Burn dialog — `12_cd_burn`
**Capture:** open the CD burn dialog from wherever it's reachable.
**Check:** dialog minimum size (650×550) fits monitor (G4), buttons aren't clipped (G3).

### 3.14 Print preview — `13_print_preview`
**Capture:** open the print preview module.
**Check:** thumbnail grid (72×54 or 96×72), splitter sizes, font sizes — this is the one place `_scaled()` already runs, so we want a baseline of what "scaled-correctly" looks like for comparison with the rest of the app.

### 3.15 Web browser module (if module enabled) — `14_web_browser`
**Capture:** open the embedded web browser sidebar.
**Check:** sidebar expanded (310 px) and collapsed (86 px) states (L3).

### 3.16 Final cross-monitor drag test (last step) — `15_cross_monitor_drag`
**Only after all above captures.** Drag the app window from the current monitor to the *other* monitor without resizing. Capture immediately after move as `15_cross_monitor_drag`.
**Check (X3):** layout integrity preserved; no per-monitor DPI fallback regression; toolbar / sidebar widths still consistent.

---

## 4. Per-screen capture protocol

For each screen capture I will:

1. Take a full-window screenshot via the computer-use MCP.
2. Save it to `docs/plans/responsive_ui_baselines/monitor_<A|B>/NN_screen.png` (mirroring filenames so A and B can be diffed pair-wise).
3. Append one row to `docs/plans/responsive_ui_baselines/findings_monitor_<A|B>.md` with:
   - Screen ID (`05_settings_server`)
   - KPI grid: G1 / G2 / G3 / G4 / G5 / T1 / T2 / T3 / T4 / I1 / I2 / I3 / I4 / L1 / L2 / L3 / L4 / L5 / L6 → severity letter or OK
   - Free-form notes pointing at suspected source file + line if I can identify it
   - Suspected Qt-native fix (e.g., "wrap in QScrollArea", "`setFixedHeight` → `setMinimumHeight`", "add `QSizePolicy.Expanding`")

---

## 5. What I will NOT do during the test

- Will not edit code during the tour — observation only.
- Will not click links from emails, messages, or PDFs (per link-safety rules).
- Will not interact with the running app outside this checklist (no random clicking, no menu spelunking).
- Will not open the frozen executable — only the source build per `CLAUDE.md`.
- Will not take screenshots of any other app on the user's desktop.

---

## 6. Cross-monitor comparison framework

After both passes are done, I will produce `docs/plans/responsive_ui_baselines/comparison_AB.md` containing:

1. **Side-by-side KPI table.** Each screen × KPI cell shows `A=OK B=M` etc.
2. **Issues unique to Monitor A** (i.e. things that work on B but break on A).
3. **Issues unique to Monitor B** (same the other way).
4. **Issues common to both** (these are layout-defect, not monitor-size, problems — the highest-priority targets for Track 1 hardening).
5. **Qt-native fix recommendation** for each issue, citing the Qt primitive that resolves it.
6. **Items that need `sf()`** — narrowed to the set of issues that Qt's primitives cannot fully address.

This becomes the source-of-truth backlog for the implementation phase.

---

## 7. Acceptance gate for "test phase complete"

- All 16 screens captured on both monitors (32 captures total minimum).
- Each capture has its KPI row filled in.
- `comparison_AB.md` produced and reviewed with user.
- Track 1 backlog (Qt-native fixes) prioritized C → M → m by aggregate severity across monitors.

Only then does implementation begin.

---

## 8. Information needed from the user before testing starts

### 8.1 Answered 2026-05-26

- **Monitor A:** main / primary display = Monitor 1. **1920 × 1080 @ 100 % Windows scaling.**
- **Monitor B:** secondary = Monitor 2. **1280 × 1024 @ 100 % Windows scaling.**
- **Enabled modules** (affect which Settings tabs and screens are reachable): EchoMind, Eagle Eye, Web, Print, Education.
- **Reception / multi-study:** not yet confirmed — I'll observe during the tour and mark N/A if unreachable.

### 8.2 What this monitor configuration tells us

Both displays are at **100 % Windows scaling**, so Qt 6's HiDPI auto-scaling math is identical on both — `devicePixelRatio == 1.0` on each, no fractional DPI to deal with. This means **any layout breakage we observe on Monitor B that we don't see on Monitor A is purely caused by the smaller physical pixel budget** (1280 × 1024 vs 1920 × 1080), not by DPI math.

In other words: this test isolates the **`setFixedX` / missing `QScrollArea`** defects identified in `RESPONSIVE_UI_ROOT_CAUSE_2026-05-26.md`. If buttons overlap on Monitor B but not Monitor A, the root cause is *the layout cannot shrink*, not *the DPI scaling is wrong*. That confirms Track 1 (Qt-native layout hardening) is the correct intervention, and `sf()` would not have helped here — there is no DPI difference for it to compensate for.

Pixel-budget delta:
- Monitor A horizontal real estate: **1920 px**
- Monitor B horizontal real estate: **1280 px** (33 % less)
- Monitor A vertical real estate: **1080 px**
- Monitor B vertical real estate: **1024 px** (5 % less)

The horizontal squeeze is the dominant dimension. Most reflow / overlap issues will surface horizontally, especially in:
- title bar (fixed 84 px tall, but full window width including patient tab chips at 252 px each)
- viewer toolbar (20 fixed-size buttons fighting for width)
- settings forms (label + field columns with fixed widths)
- patient sidebar (fixed 216 px wide thumbnail strip)

### 8.3 Start signal

Once the source build is running and you confirm the app is on Monitor A (maximized), I begin at screen 3.1. I will NOT touch the keyboard / mouse / app until you give that signal.
