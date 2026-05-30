# AI-PACS Workstation Design V1 — Claude Design Master Plan

**Status:** Planning / in-progress. No application code changed.
**Date:** 2026-05-29
**Companion:** `docs/design/UI_UX_DESIGN_REVIEW.md` (the audit this plan operationalizes).

## Guiding principle (non-negotiable)

Claude Design is a **design-system generator for the real Python/PySide6 workstation** — not a separate HTML prototype. Every output must be **directly translatable to PySide6 + QSS**. A "beautiful but unimplementable" mockup is a failure. The design language is introduced **gradually, phase by phase**, so the live clinical workstation stays stable the whole time.

Claude Design **redesigns** only: layout, visual hierarchy, color system, typography, iconography, component consistency, information density, usability.

Claude Design **must NOT redesign**: the DICOM workflow, download architecture, viewer architecture, or module architecture. These are mature and out of scope.

## Master project

**Name:** `AI-PACS Workstation Design V1` (the master design project).

It models the **actual radiology workflows**, not isolated screens.

### Project structure
- `01 - Design System` — colors, typography, icons, buttons, tabs, cards, status indicators, thumbnail design, viewer overlays.
- `02 - Home Page` — real patient workflow (Workflow 1).
- `03 - Viewer` — real viewer workflow (Workflow 1 cont.).
- `04 - EchoMind` — reporting workflow (Workflow 2).
- `05 - Eagle Eye` — AI analysis workflow (Workflow 3).
- `06 - Education` — Case of the Day workflow (Workflow 4).
- `07 - Printing` — print workflow (Workflow 5).
- `08 - Settings` — responsive settings redesign.

## Product context to give Claude Design

- **Product:** AI-PACS Workstation. **Type:** Radiology DICOM workstation. **Platform:** Windows desktop. **Tech:** Python + PySide6 (Qt). **Theme:** dark-first.
- **Users:** radiologists, residents, technologists, teaching hospitals.
- **Priorities (in order):** 1) reading speed, 2) information density, 3) low visual noise, 4) fast workflow, 5) multi-monitor, 6) high-DPI support, 7) AI-assisted workflow.
- **Non-priorities (explicitly ignore):** mobile, touch UI, consumer design patterns.

## The five workflows to model

**Workflow 1 — Patient search (PRIMARY, the center of the project):**
select server → search patient → patient list appears → click patient → thumbnails appear → double-click patient → viewer opens → download begins → drag & drop series → read study.

**Workflow 2 — Reporting:** open patient → open EchoMind → dictate report → AI transcription → report review → sign report → export.

**Workflow 3 — AI analysis:** open patient → open Eagle Eye → load mammography → display detections → display segmentation → classification panel → confidence filtering → final review.

**Workflow 4 — Education:** open patient → save as Case of the Day → add diagnosis → save educational package → browse Education module → search cases → open educational viewer.

**Workflow 5 — Printing:** open study → select images → print layout → DICOM printer → film preview → print.

## Implementation layer (the most important requirement)

Every Claude Design output must ship **two layers**:

1. **Design layer** — screens, components, layouts.
2. **Implementation layer** — for every component, define:
   - **Qt widget equivalent** (the widget tree).
   - **PySide6 implementation approach.**
   - **Theme variables** (the real token keys — see below).
   - **Style tokens** (radius, padding, spacing, state styles).
   - **Icon reference** (Feather glyph name).

**Translation example (the required style of output):**

> Instead of: *"Beautiful modern card."*
> Output:
> - Widget: `QFrame` + `QVBoxLayout`
> - `border-radius: 6px`, `padding: 8px`
> - Background: `card_bg`; border: `1px solid border`
> - Hover state: `panel_alt_bg` (token, not a hard-coded hex)
> - Title: `text_primary` 14px 600; meta: `text_muted` 12px
> - Icon: Feather `file-text`, tinted from `text_secondary`, 16px

### Canonical theme token keys (the contract)

These are the **actual keys** produced by `PacsClient/utils/theme_manager.py::_theme_blueprint()` and consumed by `build_application_stylesheet()`. The implementation layer must reference these names so generated QSS maps 1:1 onto the running app. Hard-coded hex is prohibited.

Accents: `accent`, `accent_secondary`, `accent_hover`, `accent_pressed`, `accent_soft`, `button_text`.
Surfaces: `window_bg`, `window_alt_bg`, `menu_bg`, `menu_hover_bg`, `menu_active_bg`, `panel_bg`, `panel_alt_bg`, `panel_deep_bg`, `card_bg`, `border`, `shadow`.
Text: `text_primary`, `text_secondary`, `text_muted`, `neutral`.
Tabs: `tab_bg`, `tab_hover_bg`, `tab_active_bg`.
Semantic: `info`/`info_subtle`/`info_hover`, `success`/`success_subtle`/`success_hover`, `warning`/`warning_subtle`/`warning_hover`, `danger`/`danger_subtle`/`danger_hover`.
Badges/status: `badge_blue`, `badge_cyan`, `status_online`, `status_offline`, `status_busy`.

Theme presets (all dark, derived from 4 anchors): `Blue` (default, accent `#3182ce`), `Gray`, `Green`, `Turquoise`, `Dark Red`, `Yellow`, plus `Custom`.

Viewport canvas: always near-black (e.g. `#05080c`), independent of theme — clinical requirement.

Fonts: Roboto (Latin) + IranYekan (Persian, RTL). Claude Design substitutes Vazirmatn for IranYekan in the web preview — flagged; real font files to be supplied. Icons: Feather (monoline), recolorable from tokens.

### Component → Qt mapping reference (to be expanded in `01 - Design System`)
- Button tiers → `QPushButton` with object-name variants (`primary`/`secondary`/`destructive`); QSS per state (`:hover`→`accent_hover`, `:pressed`→`accent_pressed`, `:disabled`→`text_muted`).
- Pills/badges → `QLabel` with rounded QSS; semantic background from `*_subtle`, text from semantic color.
- Data table (worklist) → `QTableView`/`QTableWidget`; header `menu_bg`, row hover `panel_alt_bg`, selection `accent_soft`; status cells = pill delegates.
- Tabs / segmented → `QTabBar` or button-group; active `tab_active_bg`, hover `tab_hover_bg`.
- Cards / empty states → `QFrame` + layout; `card_bg`, `border`, radius 8–12px.
- Icon rail → `QToolButton` list, labeled; active `menu_active_bg`; Feather icons tinted at runtime.
- Viewer overlays → `QLabel`/painter overlays on near-black canvas; never hidden.

## Phased migration strategy (keep the workstation stable)

- **Phase 1 — Design System only** (current). Produce `01 - Design System` *with the implementation layer*. ← do this first, review, then proceed.
- **Phase 2 — Home Page only.**
- **Phase 3 — Viewer and tabs.**
- **Phase 4 — EchoMind + Eagle Eye.**
- **Phase 5 — Education + Printing.**
- **Phase 6 — Settings.**

Each phase is reviewed and (optionally) implemented behind the existing architecture before the next begins. No big-bang redesign.

## Parallel & regression-safe integration strategy (V1 runs ALONGSIDE the current UI)

**Hard rule: the new design language must NOT interfere with the current live UI/UX.** It ships as a dormant, opt-in parallel layer. With the flag off (the default), the running workstation is byte-for-byte unchanged. This is how we keep the clinical app stable while introducing the new look gradually.

### What the code reality tells us (grounding)
- **One global switch point.** The whole-app stylesheet is applied in exactly one place: `main.py::_apply_application_theme()` (~lines 1208–1213), which does `app.setStyleSheet(theme_manager.build_application_stylesheet(theme) + get_scroll_area_style())` and reapplies on `theme_manager.themeChanged`. This single hook is where a V2 stylesheet would be branched in — a minimal, reversible edit.
- **But styling is NOT centralized.** There are **391+ per-widget `setStyleSheet(...)` calls across the app and modules** (home panels, viewer, download manager, AI imaging, education, printing, settings, dialogs, overlays), many with hard-coded hex. A global stylesheet swap does **not** override widget-level QSS — widget-level wins. So those calls are the real migration surface and the real regression risk.

**Consequence:** we never try to flip the whole app at once. We swap the global layer behind a flag, and migrate per-widget styling **module by module**, each behind the same gate. Until a module is migrated it simply keeps its current appearance — which is fine, because both layers are token-driven and visually compatible.

### Isolation mechanism (so V1 is never touched)
1. **Feature flag, default OFF.** Add a `ui_variant` setting (`"v1"` default | `"v2"`) — natural home is `user_data/config/theme_settings.json` (already owned by `theme_manager`) or `config/`. V1 is the default everywhere; V2 is dormant until explicitly enabled.
2. **New files only — never overwrite.** V2 lives in new modules: e.g. `PacsClient/utils/theme_v2.py` (a `build_application_stylesheet_v2(theme)` sibling) and `Qss/v2/`. Do **not** edit `theme_manager.py`, `Qss/scss/`, or `json-styles/style.json`. The existing `build_application_stylesheet` stays the source of truth for V1.
3. **Same token keys = drop-in.** Because V2 consumes the exact `theme_manager` token dict (the keys enforced in the Implementation Layer contract above), the V2 stylesheet is a drop-in alternative — no widget code changes needed for globally-styled widgets, and theme switching keeps working across all 6 presets.
4. **One guarded branch at the boundary.** The only edit to live code is in `_apply_application_theme`: `if ui_variant == "v2": use theme_v2 builder else current`. Removing the flag (or the branch) = full rollback to today's UI.
5. **Per-widget migration is scoped & token-routed.** When a module is migrated, its local `setStyleSheet` strings are routed through a shared token-based style helper (reading the same theme dict) instead of hard-coded hex — done inside that module only, behind the gate.

### Per-module gates (bounded blast radius)
Each phase gets its own sub-flag so V2 can be enabled for one area while the rest stays V1: `ui_variant.home`, `ui_variant.viewer`, `ui_variant.echomind`, `ui_variant.eagle_eye`, `ui_variant.education`, `ui_variant.printing`, `ui_variant.settings`. Enable Home in V2, keep Viewer on V1, etc. This matches the phased migration and means a problem in one module can be reverted independently without affecting others.

### Regression guards (the "don't break other parts" mechanism)
For every phase, before it can be considered done:
1. **Functional tests stay green.** Run the existing suites (`tests/code/` headless + `tests/gui/`) before and after. Styling-only changes must not change behavior; any failure blocks the phase.
2. **Honor the existing regression-guard docs.** V2 work must not touch the logic paths protected by `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`, `docs/pipelines/thumbnail-pipeline.md`, the DB-isolation rules, and the Zeta Download Manager plan. Design changes are presentation-only; offset-key/series logic, download/socket transport, and DB paths are off-limits.
3. **Visual baselines + diff.** Capture baseline screenshots of every screen in V1 **now**; after enabling V2 per module, diff V2 against (a) the V1 baseline to see exactly what changed, and (b) the Claude Design reference to confirm fidelity. The `tests/gui` live-driver scaffold can host this harness.
4. **Clinical invariants preserved.** Never hide metadata, overlays, measurements, sync, reference lines, or sidebars; viewport canvas stays near-black; **FAST viewer mode never instantiates VTK** — the styling layer must not create render windows.
5. **No new hard-coded color.** A grep/lint check asserts V2 files contain no raw hex (all colors via tokens). Prevents re-introducing the un-themeable styling the audit flagged.
6. **Token-contract test.** A unit test asserts `build_application_stylesheet_v2` consumes exactly the `theme_manager` token keys, so theme switching can't silently break.
7. **Git isolation.** Do V2 work on a branch/worktree; the live build keeps running V1. Claude Design artifacts stay as reference in the cloud project and are ported deliberately — never auto-applied to the repo.

### Rollback
At any point: flip `ui_variant` (global or per-module) back to `v1`, or drop the branch. Because V1 code and assets are never modified, rollback is instant and total.

## Phase 2 mechanism — how V2 actually hooks into the live UI (discovered 2026-05-29)

The global `theme_manager.build_application_stylesheet` only styles **standard dialogs** (QMessageBox/QFileDialog/etc.). The main workstation UI (home, viewer, panels) gets its colours from the QtCustom SCSS framework plus the ~391 per-widget `setStyleSheet` calls. **Therefore V2 for the main UI cannot be a global stylesheet swap** — it must be per-widget token-routing behind the gate.

Pattern used (see `PacsClient/utils/v2_style.py`):
- The widget keeps setting its existing V1 style unconditionally.
- Immediately after, a guarded call (`apply_*_v2(widget)`) overrides it **only when** `get_ui_variant('home')=='v2'`, using theme tokens. It is a no-op on v1 and never raises, so V1 is byte-identical and any error leaves V1 intact.
- The same guarded call is repeated at any theme-reapply site so V2 survives theme changes.

**First slice landed (Phase 2.0):** Home "Search Patients" button → accent *primary* style (audit fix: it was off-palette green). Files: `PacsClient/utils/v2_style.py` (helper + pure `search_button_qss`), gated calls in `patient_search_widget.py` at creation and theme-reapply. Tests: `tests/code/test_v2_style_scaffold.py`. Default off — visible only when `home` (or global) variant is `v2`.

## What's already done in Claude Design (to be folded into this plan)
- A published `AI-PACS Design System` foundation exists (tokens match the real app; surface ramp, type scale, semantic colors, components, an interactive worklist + 3-pane viewer UI kit, reusable `.jsx` components, `colors_and_type.css`, `README.md`, `SKILL.md`). It will be renamed/aligned to `AI-PACS Workstation Design V1` and extended with the implementation layer above.
- It still needs (Claude Design's own asks): real IranYekan + Roboto font files, the official AI-PACS logo (SVG/PNG), and screenshots/source of the real worklist & viewer to reconcile exact spacing and toolbar order.
