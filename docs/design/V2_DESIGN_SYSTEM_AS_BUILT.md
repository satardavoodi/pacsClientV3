# V2 Design System — As-Built & Regression Guard

**Status:** Implemented & in use behind a flag (default OFF). V1 untouched and byte-identical when the flag is off.
**Date:** 2026-05-30
**Companions:** `UI_UX_DESIGN_REVIEW.md`, `CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`, `IMPLEMENTATION_REFERENCE.md`, `VIEWER_TOOLBAR_INTERACTION_REVIEW.md`, `DROPDOWN_SUBMENU_REVIEW.md`.

This is the as-built record for the parallel "V2" visual refresh of the AI-PACS workstation.
Read this before touching `PacsClient/utils/v2_style.py`, the viewer toolbar styling
(`patient_toolbar/toolbar_manager.py`), or any home-page widget styling — it documents what
is gated, where each style is applied, and the invariants that keep V1 safe.

## 1. Core principle — parallel, opt-in, reversible

V2 is a **parallel** design layer. Nothing about V1 changes unless a feature flag is set.

- **Flag:** `PacsClient/utils/ui_variant.py` → `get_ui_variant(module=None)` returns `"v1"` (default) or `"v2"`.
  Source: env `AIPACS_UI_VARIANT` or `config/ui_variant.json`. Never raises. Per-module:
  `home`, `viewer`, `echomind`, `eagle_eye`, `education`, `printing`, `settings`.
- **Gate helpers:** `v2_style.home_is_v2()` / `v2_style.viewer_is_v2()`. Every `apply_*` wrapper
  checks the relevant gate first and **no-ops** (returns `False`) when off.
- **Single switch point:** `main.py::_apply_application_theme` chooses the V2 stylesheet builder
  inside a `try/except` that falls back to V1 on any error.
- **Rollback:** unset the flag → V1 renders exactly as before. No code revert needed.

## 2. The golden rule — apply at the source, not after the fact

Many AI-PACS widgets re-run their own `setStyleSheet(...)` frequently (theme refresh, state
changes, per-frame toolbar updates). An "apply V2 style after creation" call gets **clobbered**
by the next re-style.

**Invariant:** every `apply_*_v2(...)` call is placed **inside the V1 source style function**,
immediately after that function's own `setStyleSheet(...)`. So when the widget re-styles, the V2
override is re-applied in the same pass. Examples:
- `_apply_qtoolbutton_style`, `_apply_tool_button_style`, `_apply_split_left_style`,
  `_apply_split_right_style`, `_apply_dropdown_button_style` (in `toolbar_manager.py`) each end
  with a gated `apply_*_v2(...)` call.
- Home: `apply_results_table_v2` lives inside `PatientTableWidget._apply_theme`, etc.

Do **not** "fix" a V2 style by calling the apply helper from some outer creation site — it will
regress under re-styling.

## 3. Where V2 is applied (as-built map)

### Home (`get_ui_variant('home') == 'v2'`)
| Element | Helper | Applied in |
|---|---|---|
| Search button | `apply_search_button_v2` | `home_ui/patient_search_widget.py` |
| "Adaptive to Screen" button (demoted to outline) | `apply_adaptive_button_v2` (`secondary_button_qss`) | `home_ui/home_panel/_hp_layout.py` |
| Results table header | `apply_table_header_v2` | `home_ui/home_panel/_hp_layout.py` |
| Patient results table (density + soft selection) | `apply_results_table_v2` | `home_ui/patient_table_widget.py::_apply_theme` |
| "Series Thumbnails" sidebar header (purple→accent) | `apply_thumbnail_header_v2` | `patient_widget_core/_pw_panels.py` |
| Right-rail "Study Information" header (filled blue → quiet flat header) | `apply_home_panel_header_v2` (`home_panel_header_qss`) | `home_ui/right_panel_widget.py` |
| Right-rail series-count chip (quiet) | `apply_home_count_chip_v2` (`home_count_chip_qss`) | `home_ui/right_panel_widget.py` |
| Sub-toolbar buttons → one flat ghost family (download=primary, delete=danger, rest neutral) | `apply_home_toolbar_buttons_v2` (`home_toolbar_button_qss`) | `home_ui/patient_table_widget.py::_apply_theme` |
| Numeric table columns (Images/Age) **center-aligned** (balanced spacing) | `_CenterNumericDelegate` (gate read once in `_setup_neon_highlight_delegate`) | `home_ui/patient_table_widget.py` |
| Modality-aware results summary ("N MRI studies, M CT studies found") | `_build_modality_count_summary` (gated in `_update_results_count`) | `home_ui/patient_table_widget.py` |
| Sub-toolbar cluster separators (view \| config \| study-actions) | `_make_v2_toolbar_separator` (gated insert in `header_layout`) | `home_ui/patient_table_widget.py` |
| Critical **Download** button widened + labelled (76→132px, " Download") | gated block in `_apply_theme` (on `apply_home_toolbar_buttons_v2` return) | `home_ui/patient_table_widget.py` |

### Viewer toolbar & menus (`get_ui_variant('viewer') == 'v2'`)
| Element | Helper | Applied in |
|---|---|---|
| Main toolbar icons (QToolButton) | `apply_qtoolbutton_v2` (`qtoolbutton_qss`) | `_apply_qtoolbutton_style` |
| QPushButton "tool" items | `apply_tool_button_v2` (`tool_button_qss`) | `_apply_tool_button_style` |
| Split-pair halves (≡ hamburger + tool) | `apply_split_inner_v2` (`split_inner_side_qss`) | `_apply_split_left_style` / `_apply_split_right_style` |
| Unified split-pair hover | `apply_split_hover_groups_v2` (event filter `_SplitGroup`) | end of `add_toolbar_actions` + `_update_toolbar_theme` |
| Count badge (red→calm blue) | `badge_qss` | `_update_badge_stylesheet` |
| Dropdown/submenu panel | `apply_dropdown_panel_v2` | each `_show_*_dropdown` |
| Dropdown/submenu header | `apply_dropdown_header_v2` | each `_show_*_dropdown` |
| Dropdown/submenu **items** (two-column icon/text) | `apply_dropdown_item_v2` (`dropdown_item_qss`) | `_apply_dropdown_button_style` (covers all `create_dropdown_tool` items) |
| Sync Options dropdown | panel + header + item; lock icon quieted amber/green→accent/muted | `_show_sync_dropdown` |
| Selected Status dropdown | panel + header + `dropdown_status_chip/row/text` + sync icon; emoji fixed-width column | `_show_status_upload_dropdown` |
| Inline voice controls (cancel/send/pause) | `apply_mic_control_v2` (`mic_control_qss`, roles danger/primary/warning) | viewer toolbar build (the `_mic_*` buttons) |
| Dropdown **attachment/positioning** (snug anchor + 4px gap + screen clamp) | `position_dropdown_v2` (pure `clamp_popup_position`) | called before every `_show_*_dropdown`'s `dropdown.show()` |

### Settings (`get_ui_variant('settings') == 'v2'`)
| Element | Helper | Applied in |
|---|---|---|
| Whole Settings tab widget (token sheet: accent tabs/focus, ghost buttons, calm GroupBox title) | `apply_settings_v2` (`settings_stylesheet_qss`) | `settings_ui/settings_ui.py::apply_dark_theme` |

The Settings sheet is a single object-scoped block (`QTabWidget#SettingsTabWidget …`), so the V2
version is a full token-based replacement applied right after the V1 sheet — mirrors every selector
1:1 so nothing goes unstyled; V1 is byte-identical unless `settings==v2`.

### Behavioural fixes shipped alongside the visual work (NOT gated — these are bug fixes)
- **Voice play/pause toggle:** `_on_mic_pause_toggle` / `_update_mic_record_ui` now flip the
  pause↔play icon + tooltip from the real `soundbox.is_paused()` state.

## 4. Design-language invariants (keep these consistent when extending)

- **Rest:** transparent / flat (no gradients, no heavy borders).
- **Hover:** `accent_soft` fill + `1px solid accent` border (the "Adaptive button" feel).
- **Active/selected:** solid `accent` fill.
- **Tokens only** — colours come from the theme dict (`accent`, `accent_soft`, `panel_bg`,
  `card_bg`, `border`, `text_secondary`, `text_muted`, `button_text`, `danger`, `success`,
  `warning`, `badge_blue`, …). Hard-coded hex only as a safe fallback default inside a builder.
- **Split pairs read as ONE box:** each half draws its own box with split geometry (left keeps
  left-rounded corners + drops its right border; right mirrors it); the `_SplitGroup` event filter
  sets `groupHover=true` on **both** halves so hovering either lights the whole pair. (We use
  per-button boxes because a container-widget background does not paint reliably in this layout.)
- **Dropdown rows = two columns:** `qproperty-iconSize: 18px 18px` (uniform icon column) +
  `text-align: left` + consistent left padding, so every icon and label lines up.
- **Status menus keep meaning, lose the loud colour:** the small status **dot** stays its status
  colour (semantic); the row chrome and text are quieted to the V2 language. Emoji glyphs are
  preserved (replacing them with line icons would change meaning — out of scope).
- **Action buttons keep affordance colour:** voice controls stay red (cancel) / green (send) /
  amber (pause), just in the flat ghost structure.

## 5. Tests

`tests/code/test_v2_style_scaffold.py` and `tests/code/test_ui_variant_scaffold.py` — pure-function
tests (no Qt) covering: gate reflects flag and never raises; each QSS builder uses accent tokens
and drops the old V1 colours; split geometry; dropdown two-column alignment; status-row/text/chip
quieting; mic-control flat/ghost + semantic role; `_hex_to_rgba`. **Run these after any v2_style edit.**

## 6. How to extend (checklist)

1. Add a pure `*_qss(theme, …)` builder to `v2_style.py` (tokens only, safe defaults, no Qt import at module top).
2. Add a gated `apply_*_v2(widget, …)` wrapper that checks `home_is_v2()` / `viewer_is_v2()` and never raises.
3. Call the wrapper **inside the widget's V1 source style function**, right after its own `setStyleSheet`.
4. Add a pure-function test to `test_v2_style_scaffold.py`.
5. Keep V1 reachable: with the flag off, the wrapper must be a no-op and the V1 look unchanged.

## 7. Rollout status (2026-05-30)

Home slices, viewer toolbar (flat/ghost + unified split hover), badge, voice toggle, all dropdown
panels/headers, dropdown item two-column alignment across all menus, the Selected Status and Sync
Options dropdowns, the inline voice controls, and the **dropdown attachment/positioning pass**
(snug anchor + 4px gap + screen clamp on all 9 toolbar dropdowns) are **done**. The **Home cluster
review** (`HOME_CLUSTER_LAYOUT_REVIEW.md`) is also done: single primary blue, quiet Study-Information
header, flat ghost sub-toolbar + cluster separators, right-aligned numeric columns, widened/labelled
Download button.

**Phase 4 (other modules) — started:** **Settings** is now V2 (token stylesheet, gated
`settings==v2`). Remaining: EchoMind, Eagle Eye, Education, Printing per the phased plan in
`CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`. Optional polish: swap status emoji glyphs for monochrome line
icons (deferred — would change semantics).
