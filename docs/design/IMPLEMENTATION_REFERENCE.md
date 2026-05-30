# AI-PACS V2 Implementation Reference (Phase 1)

**Status:** Reference for the parallel V2 design layer. No live UI changed.
**Date:** 2026-05-29
**Companion:** `CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md` (strategy), `UI_UX_DESIGN_REVIEW.md` (audit).

This captures the Phase-1 output of the Claude Design "AI-PACS Design System" and resolves its one open reconciliation flag against the real codebase. It is the spec the parallel `theme_v2` layer implements from.

## Runtime QSS pipeline (how styling actually flows today)

`theme_manager._theme_blueprint(name, palette)` → produces the full token dict →
`ThemeManager.build_application_stylesheet(theme)` → formats a QSS string from those tokens →
`main.py::_apply_application_theme()` → `app.setStyleSheet(...)`, reapplied on `themeChanged`.

The V2 layer plugs in at the same boundary: a parallel `build_application_stylesheet_v2(theme)` consuming the **same token dict**, selected by the `ui_variant` flag. No new color math — V2 reuses the computed `theme`.

## Reconciliation flag — RESOLVED

Claude Design asked us to confirm the derived token hexes. They do **not** need confirming as fixed hexes, because the real app **computes them at runtime** from 5 anchors (`accent`, `accent_secondary`, `window_bg`, `menu_bg`, `panel_bg`). The exact derivations in `theme_manager._theme_blueprint` are:

- `accent_hover` = shift_lightness(accent, +14); `accent_pressed` = shift_lightness(accent, −18)
- `accent_soft` = mix(panel_bg, accent, 0.28)
- `window_alt_bg` = mix(window_bg, menu_bg, 0.40)
- `menu_hover_bg` = mix(menu_bg, accent, 0.18); `menu_active_bg` = mix(menu_bg, accent, 0.33)
- `panel_alt_bg` = shift_lightness(panel_bg, +9); `panel_deep_bg` = shift_lightness(panel_bg, −6)
- `card_bg` = mix(panel_bg, window_bg, 0.35)
- `border` = mix(panel_bg, #d7e3f4, 0.22)
- `tab_bg` = mix(menu_bg, panel_bg, 0.26); `tab_hover_bg` = mix(menu_bg, accent, 0.12); `tab_active_bg` = accent
- `button_text` = #0f172a if luminance(accent) > 0.32 else #ffffff
- `text_primary` #f8fafc, `text_secondary` #dbe7f3, `text_muted` #93a4b7
- `*_hover` (info/success/warning/danger) = shift_lightness(base, +12)
- `neutral` = mix(text_muted, panel_bg, 0.5); `shadow` = rgba(0,0,0,0.35)

**Implication for V2:** the V2 stylesheet must reference tokens by key only (e.g. `{accent_hover}`), never hard-code these hexes. Whatever theme is active (Blue default, or any of the 6 presets / Custom), the correct derived values arrive in the dict automatically. This is exactly the no-hard-coded-hex invariant from the strategy.

## Component → Qt widget → token map (Phase 1, 10 cards)

- **Buttons** (Primary/Secondary/Destructive) → `QPushButton` + objectName variants. Primary bg `accent`, text `button_text`, `:hover accent_hover`, `:pressed accent_pressed`, `:disabled` text `text_muted`. Secondary = transparent bg + `1px solid border`, text `text_secondary`. Destructive = `danger`.
- **Pills / badges** → `QLabel`, rounded; semantic bg `*_subtle`, text semantic color; count badges use `badge_blue`/`badge_cyan` — never red.
- **Data table (worklist)** → `QTableView`/`QTableWidget`; header `menu_bg`/`text_secondary`, row `:hover panel_alt_bg`, selection `accent_soft`; status cell = pill delegate.
- **Tabs & segmented** → `QTabBar` or button group; `tab_bg` / `:hover tab_hover_bg` / active `tab_active_bg` (=accent).
- **Form inputs** → `QLineEdit`/`QComboBox`/`QSpinBox`; bg `panel_alt_bg`, `1px solid border`, `:focus border accent`, placeholder `text_muted`.
- **Card & empty-state** → `QFrame` + layout; `card_bg`, `1px solid border`, radius 12px. (QSS has no `box-shadow` → use `QGraphicsDropShadowEffect`.)
- **Icon rail** → `QToolButton` list, labeled; active `menu_active_bg`, `:hover menu_hover_bg`; Feather icon tinted via `currentColor`.
- **Series thumbnail** (new) → `QFrame`/`QLabel`; near-black image area, label `text_secondary`, count `text_muted`, selection ring `accent`.
- **Status indicators** (new) → dot = sized `QLabel` + `border-radius`; `status_online`/`status_offline`/`status_busy` (busy ≠ danger).
- **Viewer overlays** (new, clinical-critical) → `QLabel`/painter overlays on the near-black `#05080c` canvas; metadata / measurement / AI labels **always visible, never themed away**. The viewport hex is the only allowed hard-coded color.

## Qt realities a PySide6 dev must honor (baked into the spec)
- QSS has **no `box-shadow`** → `QGraphicsDropShadowEffect`.
- Status dots = a fixed-size `QLabel` with `border-radius` = half its size.
- The **viewport canvas (`#05080c`) is the only permitted hard-coded hex**; everything else is a token.
- `status_busy` is its own color, **not** `danger`.
- Counts/notification badges use `badge_blue`/`badge_cyan`, **never** `danger` (red) — fixes the audit's "red badges" finding.

## Artifacts in the Claude Design project (reference only — not auto-applied)
`IMPLEMENTATION.md` (master map), `colors_and_type.css`, 10 `comp-*.html` component cards with the impl layer, `brand/` (Stride/Block/Split marks + module-identity SVGs), `ui_kits/workstation/` (worklist + viewer + `.jsx` components), `SKILL.md`, `README.md`. These are ported deliberately into the parallel `theme_v2` layer, never copied wholesale into the live app.
