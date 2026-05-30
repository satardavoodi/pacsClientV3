# AI-PACS — UI/UX Design Review & Improvement Roadmap

**Status:** Review only — no code changed.
**Date:** 2026-05-29
**Reviewer basis:** Source styling layer (`Qss/scss`, `json-styles/style.json`, `PacsClient/utils/theme_manager.py`, `theme_ui.py`), brand assets (`Qss/images`), Feather icon set, and a live visual pass of the running source build (Home, Settings, Viewer) in the active **Blue** theme.

This document is a decision aid. Nothing here should be implemented until we agree which items to take. The clinical invariants in `CLAUDE.md` (never remove metadata/overlays/measurements/sync/sidebars; FAST viewer never instantiates VTK; minimal safe edits) take precedence over every suggestion below.

---

## 0. The single most important finding: two design systems coexist

The app currently carries **two parallel theming systems**, and only one of them actually drives the running UI.

**System A — legacy PyDracula SCSS** (`Qss/scss/_variables.scss`, `Qss/scss/_styles.scss`, `json-styles/style.json`)
- Palette: dark slate `#21272a` background with an **orange** accent `#fba43b`.
- Structured token set: 6 background levels, 4 text levels, 4 accent levels, border tokens, 4px radius.
- Drives the QtCustom framework chrome (frameless window, slide menus, stacked-widget navigation).
- Declares a second theme "LightBlue" (`#FFFFFF` / cyan `#26bae3`) that is effectively dead.

**System B — modern `theme_manager.py`** (the one that actually renders)
- 7 named themes: **Blue (default, `#3182ce`)**, Gray, Green, Turquoise, Dark Red, Yellow, Custom.
- Semantic tokens beyond accent: `info / success / warning / danger` (+ subtle variants), `status_online/offline/busy`, `badge_*`, `tab_*`, `card_bg`, `border`.
- Derives the full palette from 4 anchor colors via HSL mixing, and computes button text color from **WCAG relative luminance** — genuinely modern and well-architected.
- Rounded corners (8–12px), hover/pressed states, runtime `build_application_stylesheet()`.

**Why this matters:** the live app renders the Blue theme (slate + blue), so the orange PyDracula palette is legacy. But widgets still styled by the old QSS won't follow theme changes, and we observed **off-palette hard-coded colors** that bypass System B entirely (the purple "Series Thumbnails" header in the viewer; teal/green one-off buttons on Home). The result is a system that is 80% coherent but visibly leaks.

**Strategic recommendation that frames the whole roadmap:** declare `theme_manager.py` the single source of truth, then incrementally migrate remaining widgets off hard-coded colors and the legacy QSS onto its tokens. Almost every recommendation below depends on this.

---

## 1. UI/UX Audit

### 1.1 What works well
- **Strong architectural bones.** The three-pane Home (left search rail · central patient table · right Study Information) is the correct PACS layout and is immediately legible.
- **The modern theme engine is a real asset.** Semantic colors, status colors, WCAG-aware contrast, and 6 ready presets are more than most in-house PACS UIs ever build. This is the foundation to standardize on, not replace.
- **Feather icon set** is a coherent, modern, monoline family (341 glyphs) — a good baseline.
- **Status communication on Home** is good: green check / orange warning in the Report column, the "3 studies found" pill, and series cards that show modality label (R-CC, L-CC, R-MLO) plus image counts.
- **Viewer fundamentals are right:** near-black image canvas (correct for radiology reading), explicit empty-state drop guidance ("Drop a series here or select one from the thumbnail panel"), a layout-grid control, and customizable toolbar groups.
- **Settings is the most polished surface:** organized tabs, two-column forms, section headers with helper subtitles, and semantically colored buttons (blue Save, green Verify/Echo, red Delete).

### 1.2 What feels outdated
- The **header "logo" is a plain text pill** reading "AI - Pacs" — the actual brand mark (`aiLogo.png`) is never used in the chrome.
- The **logo SVG is fake vector**: `ai_pacs_logo.svg` is 320 KB because it wraps a base64 PNG. There is no clean scalable logo.
- **Icons are white-only raster PNGs.** The Feather set exists only in the `fefefe` (white) color variant and as PNGs, so they don't recolor per theme and don't stay crisp on HiDPI.
- **Legacy orange palette + dead LightBlue theme** linger in the SCSS/JSON layer.

### 1.3 What creates visual noise
- **Competing accent colors with no hierarchy.** On Home alone: blue (Server tab), green (Search button), teal ("Adaptive to Screen Size"), plus three **red badges** top-right. There is no single, unambiguous "primary action" color.
- **Red badges as decoration.** The three top-right buttons each carry a red badge; red is the system's danger color and should be reserved for errors, not routine counts/notifications.
- **Off-palette one-offs:** the **purple** "Series Thumbnails" header and teal/green buttons are hard-coded outside the token system.
- **Settings button weight.** Nearly every control is a large, full-width, saturated fill — a heavy "control-panel" density with no secondary/ghost tier to calm the page.
- **Viewer toolbar overload:** ~16 identically-colored blue icon buttons separated by faint drag-handle "||" marks, no labels and no per-group color — the eye has nothing to anchor on.

### 1.4 What creates usability friction
- **Viewer tool discovery.** With 16 same-color, unlabeled icons, finding a specific tool depends entirely on hovering for tooltips. This is the highest-friction surface in the product.
- **Series numbering shown to users.** The viewer lists "Series 2 / 4 / 6 / 8" (the multi-study offset keys leaking to the UI) and Home shows "Series 0". Clinicians read this as missing/!mislabeled series.
- **Rotated vertical tab labels** (Series, Reception Data, ECHO MIND, EAGLE EYE, Advanced Analysis) are harder to scan than horizontal labels or labeled icons.
- **Low-affordance disabled states.** Disabled toolbar items (e.g. "Offline Sync") are only dimmed; mixing icon-only and icon+text buttons in the same table toolbar makes the row hard to parse.
- **Empty tables lack empty states.** External PACS / Offline Cloud tables in Settings show only headers with no "nothing configured yet" guidance.
- **Patient table whitespace.** With a few rows the central table leaves large empty vertical space; no density option or summary fills it.
- **Low-contrast EchoMind widget** on Home (dark circular badge) reads as an unclear decorative element rather than an actionable control.

---

## 2. Design System Recommendations

### 2.1 Color palette
1. **Adopt `theme_manager.py` as the canonical system.** Freeze the legacy orange PyDracula palette and the dead LightBlue theme as "legacy/compat only," and stop adding new styling to the SCSS layer.
2. **Eliminate hard-coded colors.** Grep for literal hex values in widget code and route them through theme tokens. Known offenders: the purple Series-Thumbnails header, the teal "Adaptive to Screen Size" button, the green Search button (should be `accent`, not a separate green unless it's intentionally a "success/go" semantic).
3. **Define one primary action color = `accent`.** Search, Save, primary CTAs all use `accent`. Reserve `success` (green) for verbs that mean "verify/confirm/connected," `danger` (red) for destructive/error only, `warning` (amber) for caution.
4. **Demote red badges.** Use `accent` or a neutral badge for counts; switch to `danger` only when the badge represents an actual error/failure. Show a number, not an "✕"-looking glyph.
5. **Keep the radiology-correct near-black canvas** in the viewer regardless of theme — this is a clinical requirement, not a theming choice.

### 2.2 Typography
- Current fonts: **IranYekan** (Persian, light/regular/bold) + **Roboto** (full family). The app is **bilingual (Persian RTL + English LTR)** — preserve both.
- The modern theme defines text *colors* (`text_primary/secondary/muted`) but **no size/weight scale**. Define a small type-scale token set, e.g. Display / Title / Section / Body / Label / Caption with explicit px sizes and weights, and apply consistently (headings like "Server Management" vs. helper subtitles already hint at a 2-level hierarchy — formalize it).
- Set Roboto/IranYekan pairing rules so Latin and Persian text share consistent optical sizing in mixed strings.

### 2.3 Spacing & alignment
- Codify a **4/8px spacing grid** as tokens (xs 4 · sm 8 · md 12 · lg 16 · xl 24). The theme dialog already uses 12–16px margins — make that the rule, not an instance.
- Standardize control heights (e.g. inputs/buttons 32–36px) and corner radius (the modern system uses 8–12px; pick 8px for controls, 12px for cards and stick to it).
- Give the patient table a **density setting** (comfortable/compact) and a fill strategy so short result sets don't leave dead space.

### 2.4 Icon system
- **Move to recolorable icons.** Either (a) generate per-theme color variants of the Feather PNGs, or preferably (b) switch to **SVG icons tinted at runtime** from the theme's `text_primary`/`accent`. This is mandatory for a working light theme and for HiDPI crispness.
- Keep Feather as the single icon language; remove the stray `.jpeg`/`.jpg` icons in the set for consistency.
- Establish **icon sizing tokens** (16 / 20 / 24px) and use them deliberately (table toolbar vs. main toolbar should not be the same tiny size).

### 2.5 Component consistency
- **Button tiers:** define Primary (filled `accent`), Secondary (outline/ghost), and Destructive (filled/outline `danger`). Settings should mostly use Secondary, with one Primary per section — this alone removes most of the "control panel" heaviness.
- **Tabs:** unify the horizontal tab style (Settings) and the rotated vertical tabs (Viewer) into one tab component; prefer horizontal or labeled-icon tabs over rotated text.
- **Empty states:** one reusable empty-state component (icon + short message + optional action) for all tables/viewports.
- **Badges/pills:** one pill component driven by semantic tokens (the "3 studies found", "4 series", and status pills should all be the same component).

### 2.6 Dark-theme improvements
- The dark themes are the strength — keep dark as default. Tighten the **elevation model**: window < panel < card should be visually distinct via the existing `window_bg / panel_bg / card_bg / panel_alt_bg` tokens, applied consistently (today some panels read flat).
- Verify **contrast across all 6 presets**, not just Blue — the luminance helper exists; extend it to validate text/control pairs (esp. Gray and Yellow, which tend to fail AA).

---

## 3. Branding Recommendations

### 3.1 AI-PACS visual identity
- The `aiLogo.png` concept is good: the "A + i" forms a walking-person figure over "PACS · Based On Artificial Intelligence." Build the identity around this mark rather than a text label.
- Produce a **true vector logo** (clean SVG, not a base64-wrapped PNG) in three lockups: full (mark + wordmark + tagline), horizontal (mark + "AI-PACS"), and mark-only (for the collapsed rail / favicon).
- Provide **themed color variants** (white for dark themes, dark for the eventual light theme, single-accent version) generated from theme tokens.

### 3.2 Logo placement
- Replace the header **text pill "AI - Pacs"** with the horizontal logo lockup, recolored to the active theme.
- Use the **mark-only** version in the collapsed left rail and as the window/taskbar icon (replace the bloated SVG and regenerate the `.ico`).
- Keep the "Intelligent Medical Imaging" tagline as a defined brand element, not an ad-hoc viewer string.

### 3.3 Product identity consistency across modules
- The **AI-module hero images (Echo Mind, Eagle Eye)** are attractive but use a deep-navy + cyan particle aesthetic that diverges from the app's slate + blue. Re-render or re-grade them toward the unified palette, and remove baked-in text (so labels can be localized and themed).
- Create a lightweight **module-identity framework**: each module (EchoMind, Eagle Eye, MPR, Printing, Education, Case of the Day) gets one consistent icon + one accent role drawn from the theme — distinguishable but unmistakably part of AI-PACS.

---

## 4. Module-Specific Recommendations

### 4.1 Main / Home page
- Establish a single primary action color (Search = `accent`); demote "Adaptive to Screen Size" and segmented Local/Server/Import to secondary styling.
- Rework the **patient-table toolbar**: consistent icon size, tooltips on all, group with spacing not faint drag-handles, and a uniform disabled treatment (icon + reduced opacity + cursor).
- Add a **density toggle** and a short result summary; handle the zero/short-result whitespace.
- Show **user-facing series numbers as 1…N** (keep offset keys internal — see `MULTI_STUDY_SINGLE_TAB_PLAN.md`). This is presentation-only and must not touch the offset-key logic.
- Clarify the **EchoMind widget**: raise contrast, give it a label/affordance so it reads as a control.
- Tone down the three top-right **red notification badges**.

### 4.2 Viewer (highest-priority surface)
- **Redesign the toolbar**: group by function (layout · measurement · windowing · transform · capture · AI · MPR), separate groups with whitespace or subtle dividers rather than drag handles, add hover tooltips uniformly, and consider optional text labels / an overflow menu for less-used tools. Optionally tint icon groups subtly so the eye can navigate.
- Replace the **purple** Series-Thumbnails header with a theme token.
- Convert **rotated vertical module tabs** to horizontal or labeled-icon tabs.
- Keep all existing tools, overlays, measurements, sync, and the near-black canvas exactly as-is (clinical invariant) — this is purely a layout/labeling/coloring pass.

### 4.3 Education & Case of the Day
- Not reviewed live in this pass (lower confidence). Recommend a dedicated visual review. From the code structure (`modules/education`) and the header education entry point, apply the same component system: card-based content, the unified empty-state, and module identity.

### 4.4 Printing
- Not reviewed live (lower confidence). Recommend a follow-up pass; ensure print dialogs use the standard dialog/button tiers and that layout/preview controls follow the icon + spacing tokens.

### 4.5 AI modules (EchoMind, Eagle Eye, MPR)
- Unify entry points: today they appear as a microphone icon, a feather/eagle icon, an "MPR" text button, and rotated side tabs — three different patterns. Give each a consistent labeled-icon treatment from the module-identity framework.
- Align their hero/splash art and accent to the unified palette (see 3.3).

### 4.6 Settings
- Introduce the **button tier system** (mostly Secondary, one Primary per section) to reduce visual weight.
- Add **empty-state messaging** to the External PACS and Offline Cloud tables.
- Keep the existing tab structure and semantic colors — these are good.

---

## 5. Claude Design — Project Context Brief

When briefing Claude Design (or any external design tool), provide this context so its output fits the product rather than a generic web aesthetic:

**Product:** AI-PACS — a clinical DICOM **PACS workstation** (Picture Archiving and Communication System) with integrated AI. Desktop application, **PySide6/Qt** on **Windows**, frameless custom-chrome window, typically run on **dual monitors**. Performance- and stability-sensitive (used in live clinical workflows).

**Users:**
- **Radiologists** reading studies (primary): need glanceable status, fast tool access, minimal chrome, dark UI for reading rooms.
- **Technologists / reception** managing patient lists, imports, and assignments.
- Bilingual: **Persian (RTL) + English (LTR)** — layouts and type must handle both.

**Radiology workflow to respect:** search/filter patients by modality + date → review the patient/study list → open a study in the viewer → window/level, zoom, pan, measure, annotate, compare series/prior studies → run AI assistance → report / print / burn to CD → (optionally) teach from Education / Case of the Day.

**DICOM workstation environment:** near-black image canvas is required; clinical metadata, overlays, measurements, reference lines, and sync **must never be hidden or removed**; multi-study/multi-series handling uses internal offset keys (presentation may renumber, logic may not).

**AI-assisted workflow:** Eagle Eye (image AI), EchoMind (voice assistant), plus breast/bone-age/segmentation service endpoints. These are first-class modules that need a consistent, trustworthy identity (AI output in a clinical tool must look reliable, not flashy).

**Educational workflow:** Education module + Case of the Day for teaching — content-card oriented, can be lighter/more inviting than the reading UI but still on-brand.

**Design constraints to hand Claude Design:**
- Dark-first, 6 existing theme presets + custom; the token vocabulary already exists (`accent`, `window_bg/menu_bg/panel_bg/card_bg`, `text_primary/secondary/muted`, `info/success/warning/danger`, `status_*`, `badge_*`, `tab_*`, `border`).
- Type: Roboto (Latin) + IranYekan (Persian).
- Icons: Feather (monoline).
- Deliverables most useful from Claude Design: a true vector logo + favicon set; recolorable SVG icon approach; a viewer-toolbar layout concept; a button-tier + empty-state + pill component spec; and a one-page token/spacing/type cheat-sheet.

---

## 6. Prioritization

### High impact / low effort
- Declare `theme_manager.py` the single source of truth; stop styling via legacy SCSS.
- Replace remaining **hard-coded colors** with tokens (purple Series-Thumbnails header; teal/green one-off buttons).
- Establish **one primary action color**; apply across Home + Settings.
- **Tame the three red top-right badges** (neutral/accent; counts not glyphs).
- **Renumber series for display (1…N)** while keeping offset keys internal.
- Swap the **text "AI - Pacs" header pill** for the existing logo mark, recolored to theme.
- Uniform **disabled-state** treatment and consistent tooltips on table/toolbar icons.

### High impact / medium effort
- **Redesign the viewer toolbar** (grouping, labels-on-hover/overflow, consistent sizing, remove drag-handle clutter).
- Define and roll out **button tiers** (Primary/Secondary/Destructive) — biggest win for Settings density.
- Define and apply a **typographic scale** and a **4/8px spacing token set**.
- Add **reusable empty-state** and **pill/badge** components.
- Produce a **true vector logo + favicon** and themed variants; replace the 320 KB fake SVG and regenerate the `.ico`.
- **Recolorable SVG icons** (or per-theme variants) so icons work on all themes + HiDPI.

### Long-term design improvements
- A formal **AI-PACS Design System** doc/component library (tokens, spacing, components, do/don'ts) as the single reference — and the artifact to feed Claude Design.
- **Module-identity framework** so EchoMind / Eagle Eye / MPR / Printing / Education share a coherent but distinguishable language; re-grade AI hero art to palette.
- **Complete & validate the light theme** (icons, contrast) — the legacy LightBlue is currently dead.
- **Accessibility pass:** extend the existing WCAG luminance check to all text/control pairs across all 6 presets; add visible focus states and keyboard navigation review.
- **Unified dialog/notification system** (toasts + modals) with standard layout.
- **RTL polish** for Persian across all modules.

---

## 7. Suggested next steps (decision points for you)
1. Confirm we standardize on `theme_manager.py` (System B) as canonical.
2. Pick the first implementation slice — recommended: the **High impact / low effort** group, since it's mostly token routing and presentation with no behavioral risk.
3. Decide whether to commission Claude Design for the **logo + icon + viewer-toolbar concept** using the §5 brief.
4. Schedule a second live pass to cover **Education, Case of the Day, and Printing** (not reviewed in depth here).

*No code or assets were modified in producing this review.*
