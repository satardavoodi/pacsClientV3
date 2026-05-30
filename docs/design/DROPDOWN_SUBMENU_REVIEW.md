# Viewer Dropdowns & Submenus — Review & V2 Rollout Plan

**Status:** Review + in-progress. Gated behind `ui_variant('viewer')=='v2'`; V1 untouched.
**Date:** 2026-05-30
**Companion:** `VIEWER_TOOLBAR_INTERACTION_REVIEW.md`, `CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`.

The toolbar buttons are now modernized (flat/ghost, unified split controls). The dropdown **panels, their contents, the legacy voice controls, and submenus** still use the previous-generation visuals, so the UI feels mixed. This brings them onto the same V2 language.

## How the dropdowns are built (as-built)

Each dropdown is a **frameless `QWidget` popup** (`Qt.Popup | Qt.FramelessWindowHint`, `WA_DeleteOnClose`) built by its own `_show_*_dropdown(button)` method in `toolbar_manager.py`:

- `_show_measurements_dropdown` (Tools) · `_show_sync_dropdown` (ZSync) · `_show_audio_dropdown` (Voice) · `_show_capture_dropdown` · `_show_wl_presets_dropdown` (window/level) · `_show_mpr_dropdown` · `_show_rotation_dropdown` · `_show_capture_mode_dropdown` · `_show_status_upload_dropdown`

Each sets, inline: a **panel** stylesheet (gradient `#1f2937→#111827`, **2px** border `#374151`, radius 10), a **header** `QLabel` (a **filled blue-gradient bar**, white bold text), and **item** buttons via `create_dropdown_tool(label, icon, icon_color)` (each with a different per-item icon color). The **voice play/pause/delete** controls live in `voice_tool_ui.py` (`VoiceWidget`).

## V2 target (one design language)

1. **Panel** — flat token surface (`card_bg`/`panel_bg`), **1px** `border`, radius 12 (no gradient). *(`dropdown_panel_qss`)*
2. **Header** — a quiet muted caption (`text_muted`, 11px, letter-spaced), **not** a filled accent bar, so it doesn't compete with selection. *(`dropdown_header_qss`)*
3. **Items** — flat rows: consistent **icon column** (fixed width, 16–18px icons), left-aligned label, uniform **row height (~34–36px)** and padding; rest transparent; **hover = `accent_soft`**; **selected = `accent`**. (Items are `create_dropdown_tool` → `_theme_style_type='dropdown'` → already routed through the gated ghost; this step tightens alignment/row metrics and quiets the per-item icon colors to one consistent treatment.)
4. **Voice controls** (`voice_tool_ui.py`) — restyle play/pause/delete to the V2 button language (flat, accent for primary/active, `danger` only for delete), consistent sizing + hover.
5. **Submenus** — same panel/header/item language; anchor snugly to the parent item; consistent hover/focus.

PySide6 notes: QSS has **no `box-shadow`** → use `QGraphicsDropShadowEffect` if a shadow is wanted (deferred — Popups can clip effects). Rounded popup corners may need `WA_TranslucentBackground` to avoid square window corners (evaluate per dropdown). All colors via tokens; no hard-coded hex.

## Shared helpers (in `PacsClient/utils/v2_style.py`)
- `dropdown_panel_qss(theme)` / `apply_dropdown_panel_v2(dropdown)` — flat panel.
- `dropdown_header_qss(theme)` / `apply_dropdown_header_v2(label)` — quiet header.
- (Next) `dropdown_item_qss` for row metrics/alignment; voice-control helpers.

Each `_show_*_dropdown` gets two gated lines (panel + header) right after its existing inline `setStyleSheet` calls — a small, mechanical, reversible edit per dropdown.

## Rollout (incremental, each testable) — COMPLETE
> Authoritative as-built is now **`V2_DESIGN_SYSTEM_AS_BUILT.md`**. This file is the original review.

- **Done:** Panel + header gating on the dropdowns.
- **Done:** Item row metrics/alignment — `dropdown_item_qss` / `apply_dropdown_item_v2` applied at the
  source `_apply_dropdown_button_style`, so **all** `create_dropdown_tool` items get a two-column
  (fixed 18px icon column + left-aligned text) layout (Rotate/Flip, W/L presets, Measurement tools, MPR, …).
- **Done:** The two legacy menus — **Sync Options** (`_show_sync_dropdown`) and **Selected Status**
  (`_show_status_upload_dropdown`): flat panel + quiet header; status rows quieted to
  transparent / `accent_soft` hover / `accent`-current with neutral text (the status **dot** keeps its
  colour for meaning); amber/green lock + green sync icons quieted to accent/muted; status emoji column
  fixed-width (56px) so labels align with nothing truncated.
- **Done:** Inline **voice controls** (cancel/send/pause) → `mic_control_qss` / `apply_mic_control_v2`
  (flat ghost, semantic colours preserved). Voice play/pause toggle bug fixed.
- **Optional / deferred:** submenu anchor + positioning pass; swapping status emoji glyphs for
  monochrome line icons (would change semantics — out of scope).

Order kept risk low and let the look be confirmed on one dropdown before propagation.
