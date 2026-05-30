# Viewer Toolbar — Interaction & Polish Review (V2)

**Status:** Review only. No code changed by this document.
**Date:** 2026-05-30
**Scope:** The V2 viewer toolbar (now flat/ghost) — hover feedback, dropdown attachment, dropdown menu layout.
**Companion:** `CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`, `IMPLEMENTATION_REFERENCE.md`.

All recommendations below are **incremental, PySide6/QSS-realistic, and gated behind `ui_variant('viewer')=='v2'`** (V1 untouched). They build on the existing `v2_style.py` helpers — no architectural change, no new dependencies.

## What we observed (current V2 state)

- The toolbar is now correctly **flat/ghost**: icons on transparent backgrounds, active tool = accent fill. Good — the heavy "blue blocks" are gone.
- **Hover feedback is too weak.** The current `:hover` is `panel_alt_bg` background + a `border` (low-contrast) outline. On the near-dark toolbar this is barely perceptible — discoverability suffered when we removed the heavy fill.
- **Dropdowns feel detached** from their trigger icon: the popup opens with a visible vertical/horizontal gap and isn't clearly anchored to the ≡ (split-left) button that opened it.
- **Dropdown menu items are inconsistent with the toolbar**: they're still the old blue-gradient blocks (e.g., the Tools menu: Angle / Two-Line Angle / Arrow / Text / ROI / Circle ROI), with icons of varying size/baseline and uneven alignment vs. text. They don't speak the new flat/accent language.

The reference the user likes — the Home **"Adaptive to Screen Size"** hover (clear outline + tinted fill) — is the target interaction feel.

---

## 1. Toolbar hover feedback

**Goal:** clear, consistent, discoverable hover — matching the Adaptive-button feel — without returning to heavy fills.

**Recommendation (small QSS change to the existing ghost helpers):**
- `:hover` → background `accent_soft` (the muted accent tint, already a token) **+ `1px solid accent` border** (not the low-contrast `border` token). This gives the "blue outline + subtle tinted background" the user prefers.
- Keep `:checked`/active = solid `accent` fill (clear active state).
- Keep `:pressed` = `accent` (or `accent_pressed`) for tactile feedback.
- Optionally add a 120 ms feel via no animation (QSS can't animate easily) — rely on the stronger color contrast instead.

**Where (PySide6):** edit only the `:hover` rules in the V2 ghost builders in `PacsClient/utils/v2_style.py`:
- `qtoolbutton_qss` (QToolButton items)
- `tool_button_qss` (QPushButton 'tool' items)
- `pushbutton_ghost_qss` (dropdown + split-pair halves)

Example (token-based, no hard-coded hex):
```
QToolButton:hover { background: {accent_soft}; border: 1px solid {accent}; }
```
This is one-line-per-helper, fully gated, reversible. Applies uniformly to Tools / Voice / Screenshot / ZSync / Rotation / all toolbar icons because they all route through these helpers.

---

## 2. Dropdown attachment (anchor to the trigger icon)

**Goal:** the menu should read as belonging to the icon that opened it.

**Recommendation (popup positioning, not styling):**
- Anchor the popup's **top-left to the trigger button's bottom-left** with a **small fixed gap (4 px)**: `popup.move(btn.mapToGlobal(QPoint(0, btn.height() + 4)))`. Remove any larger hard-coded offset currently used.
- If the popup is a custom frameless `QWidget`/`QFrame` (it appears custom, not a native `QMenu`), give it a subtle **connector cue**: a 2 px accent top-border on the popup, or a small caret/arrow aligned to the trigger's center. Even without an arrow, snug alignment (≤4 px gap, left edges flush) removes the "floating" feel.
- Clamp to screen bounds so it never opens off-monitor (multi-monitor): if `popup.right() > screen.right()`, shift left.

**Where (PySide6):** the dropdown trigger handlers in `modules`/`patient_toolbar/toolbar_manager.py` that build and `.show()`/`.move()`/`.exec()` the popups (the split-left "≡" buttons). This is positioning logic — keep it gated so V1 popup positions are unchanged.

---

## 3. Dropdown menu layout & item styling

**Goal:** clean, scannable menu rows that match the flat/accent language.

**Recommendation (consistent row template + flat items):**
- **Item style:** flat rows (transparent), `:hover` = `accent_soft` background, selected/active = `accent` left-accent or fill. Drop the per-item blue gradient so the menu matches the toolbar.
- **Alignment grid:** fixed **icon column width (~24 px)**, then text left-aligned with consistent left padding. All icons rendered at the **same size (16–18 px)** and vertically centered.
- **Row height:** uniform (~34–36 px), consistent vertical padding (8 px), so rows don't look ragged.
- **Header row** ("Measurement Tools"): visually distinct but quieter — `text_muted`, smaller caps, not a filled accent bar competing with selection.
- **Separators/grouping:** if grouping is needed, a 1 px `border` divider with 4 px spacing rather than color blocks.

**Where (PySide6):**
- If items are `QPushButton`/`QToolButton` rows in a custom popup: reuse a gated `menu_item_qss(theme)` helper (new, in `v2_style.py`) with `text-align:left; padding:8px 12px; icon column via setIconSize(QSize(16,16))` and `:hover {background: accent_soft}`.
- If it's a native `QMenu`: style `QMenu::item { padding: 8px 12px 8px 32px; } QMenu::item:selected { background: accent_soft; } QMenu::icon { left: 8px; }` — gated.

---

## Consistency principle

All three fixes share one language, so the toolbar and its menus feel like one system:
- **Rest:** transparent / flat.
- **Hover:** `accent_soft` background + `1px accent` border (the Adaptive-button feel).
- **Active/selected:** solid `accent`.
- **Tokens only** (no hard-coded hex); all gated behind `viewer`=`v2`; V1 untouched and instantly reversible.

## Suggested order (incremental, each independently testable)
1. **Hover strengthen** (1-line `:hover` change ×3 helpers) — biggest perceived win, lowest risk. *(Do first.)*
2. **Dropdown menu item styling** (flat rows + alignment grid).
3. **Dropdown attachment/positioning** (anchor + 4 px gap + screen clamp).

Each step: gate it, you relaunch V2 + open a study + open a dropdown, confirm V1 (Play button) unchanged.

## Not recommended (out of scope / risk)
- No layout/architecture restructure of the toolbar or popups.
- No change to which tools exist, their order, or their behavior.
- No animation framework — rely on color contrast for feedback.
