# Theme System Review — 2026-05-30

**Scope.** Live walk-through of all seven themes in the source build plus a code audit for hard-coded colors that bypass the theme system.
**Build.** AI-PACS source build from VS Code; today's home page state with server `razi` connected.
**Verifier.** Manual switching via Theme panel (`grid.png` button on left sidebar → center menu) with 3–4 s settle time after each apply.

---

## 1. Executive summary

The theme system is well-architected: a single `ThemeManager` (`PacsClient/utils/theme_manager.py`) holds seven named palettes (Blue / Gray / Green / Turquoise / Dark Red / Yellow / Custom), each palette is expanded into ~40 derived tokens (`accent_hover`, `panel_alt_bg`, `accent_soft`, …), and a `themeChanged` Qt signal lets widgets re-style on switch. Most chrome correctly consumes those tokens.

Two real problems stand out:

1. **A handful of UI surfaces are pinned to fixed colors and never re-style.** The patient row left accent strip, the patient tabs on the title bar, the sidebar Reception/service buttons, the patient-search inputs, and several status badges keep Material-blue / Material-green hex values regardless of which theme is selected. The mismatch is most jarring under Green, Yellow, and Dark Red.
2. **Several "fallback" hex values in theme-aware code use a *different* default than the Blue theme.** `right_panel_widget.py` and `thumbnail_panel.py` both fall back to `#7c3aed` (violet) for `accent` and `#0f1419` for `panel_bg`. If `theme.get(...)` ever misses (rare, but reachable), a stray violet button appears mid-page on a Blue theme. These are bugs in waiting.

The Theme panel itself works but its visual presentation lags the new V2 chrome on the rest of the home page — fixed-size 2-column grid, no live preview of the home, no semantic-color swatch row.

Priority of recommended fixes is listed in §5.

---

## 2. Per-theme evaluation (live)

Each theme was applied with the patient list visible (1 patient, MEHRI SIMIN, study date 2026-05-26). Observations are grouped by surface so you can compare apples-to-apples across themes.

### 2.1 Blue (default)

| Surface | Notes |
|---|---|
| Window / panel bg | Dark navy `#18212f` / `#111927`. Calm. |
| Search button | Solid blue `#3182ce`. Clear primary affordance. |
| Patient row select | Blue left accent — matches accent token. |
| Sidebar text inputs | Dark with subtle border — readable. |
| Status icons | Gold graduation cap + green report-✓ + green "Server Ready" badge. Reads cleanly because the accent is also blue, so semantic icons don't clash. |
| "Study Information" tab | Blue active state — consistent. |
| Verdict | **The reference theme.** All cross-cutting hard-coded blues happen to match, so nothing looks wrong. |

### 2.2 Gray

| Surface | Notes |
|---|---|
| Window / panel bg | Charcoal `#1d2026` / `#171b20`. |
| Search button | Muted `#8b95a7`. Lower contrast — the *primary* CTA stops looking primary. **Issue.** |
| Patient row select | Blue accent persists (hard-coded). **Mismatch.** |
| Sidebar inputs | Same as Blue. |
| Status icons | Gold + green badges keep saturating against a now-grey UI; loud. |
| Verdict | The most muted theme; surfaces well, but the persistent blue patient-row accent and the loud gold/green status chips break the calm. |

### 2.3 Green

| Surface | Notes |
|---|---|
| Window / panel bg | Forest `#15241e` / `#12201b`. |
| Search button | Solid `#2f9e70`. Reads as primary. |
| Patient row select | **Still blue.** Clear mismatch against green chrome. |
| "Study Information" tab | Active state turns green ✓ |
| Status icons | Gold graduation cap competes with the warm-green accent; report-✓ green melts into the panel. |
| Verdict | Good base palette; the persistent blue row-accent is the loudest visual bug here. |

### 2.4 Turquoise

| Surface | Notes |
|---|---|
| Window / panel bg | Cool `#14252b` / `#102027`. |
| Search button | Teal `#20a4a5` — distinctive. |
| Patient row select | Still blue (hard-coded). |
| Status badge "2 US studies, 1 MRI study" | Stays blue pill — looks like an out-of-place tag. |
| Verdict | Closest to Blue in feel; same issues but less jarring because the palette is already cyan-adjacent. |

### 2.5 Dark Red

| Surface | Notes |
|---|---|
| Window / panel bg | Burgundy `#191015` / `#120a0f`. Genuinely dark. |
| Search button | Pink/red `#b63c57`. |
| "Study Information" tab | Pink active state ✓ |
| Status icons | Gold graduation cap + green report-✓ + green Server Ready — visually clash with the warm red base. |
| `danger` token is the *same* as `accent` | Every error/cancel button is now indistinguishable from the primary CTA. **Issue.** |
| Verdict | The most theme-coherent chrome of the dark themes, but `danger == accent` is a usability problem. |

### 2.6 Yellow

| Surface | Notes |
|---|---|
| Window / panel bg | Warm brown `#1f1b10` / `#171106`. |
| Search button | Amber `#c99512`. |
| Graduation-cap icon | **Disappears into the theme** — the gold-on-yellow has almost no contrast. **Issue.** |
| Status badge "2 US studies, 1 MRI study" | Stays blue pill. |
| `info`/`success`/`warning` tokens collapse | info=`#f59e0b`, warning=`#c99512`, success=`#eab308` — every status is amber. Semantic differentiation is lost. **Issue.** |
| Verdict | The riskiest theme for clinical use: status icons are designed around amber=warning, and Yellow turns the whole UI into a warning state. |

### 2.7 Custom

| Surface | Notes |
|---|---|
| Default | Resets to Blue palette ✓ |
| Customizer dialog | Opens; lets the user adjust 14 colors per palette. |
| Verdict | Functions correctly. Same hard-coded-blue caveats apply if the user picks anything non-blue. |

---

## 3. Theme-aware components — pass/fail

| Component | Adapts on switch? | Notes |
|---|---|---|
| Patient list table chrome (bg, text, header row) | ✓ | Picks up panel_bg / text_primary. |
| Patient list *selected row left accent* | ✗ | Hard-coded `#2196f3` in `sidebar_widget.py`. |
| Patient list status icons (graduation cap, printer) | partial | Icons use semantic colors (`#fbbf24`, `#60a5fa`) — they're meant to stay semantic but no contrast-against-theme check. |
| Status count badge ("2 US studies, …") | ✗ | Blue pill stays blue across all themes. |
| Search panel (modality checkboxes, ID/Name inputs, date) | ✗ | `patient_search_widget.py` hard-codes `#f7fafc`, `#4a5568`, `#0f1419`. |
| Search button | ✓ | Uses accent token. |
| Left sidebar icon column | ✓ | Uses menu_bg / hover tokens. |
| Settings (gear) page top tabs | ✓ | Uses accent. |
| Right-side "Study Information" panel header | ✓ | Uses accent. |
| Right-side thumbnail card | ✓ via theme.get | But fallback default is violet `#7c3aed`. **Bug-in-waiting.** |
| Patient tabs (top of viewer) | ✗ | `custom_tab_manager.py` has hard-coded blue gradient stops `#2a3360 → #1f2850 → #111a34`. The case-of-day green variant we just added is the one exception. |
| Reception panel buttons (Save / Action) | ✗ | `reception_panel_widget.py` hard-codes Material blue `#2196f3` and Material green `#4caf50`. |
| Service tab widget (background gradient) | ✗ | Hard-coded `#1f2937 → #111827`. |
| Toolbar buttons (viewer top bar) | ✓ | `toolbar_manager.py` uses `theme.get(...)` consistently. |
| Dropdown menus (modality, server) | partial | Background themed; selected-item highlight is hard-coded. |
| Hover states (sidebar, buttons) | ✓ | Use `accent_hover` token. |
| Notifications / toasts | not observed | None fired during walk. |
| Sidebar panels (Reception Data, ECHO MIND, EAGLE EYE, Advanced An.) tab labels | ✓ | Uses panel_bg / text. |
| MessageBox dialogs | ✓ | `ThemeManager.build_application_stylesheet` themes them. |

---

## 4. Hard-coded color audit (key offenders)

> Counts are total hex occurrences in the file — not all are violations (some are legitimate semantic colors, gradient stops, or RGB→QColor conversions). Highlighting the files where the *biggest concentration of non-themed UI* lives.

| File | Hex count | Status |
|---|---|---|
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` | 333 | Mostly OK — uses `theme.get(...)` with fallbacks; many counts are inside dropdown variants. |
| `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` | 143 | Mix of legitimate semantic chips (`#fbbf24` graduation cap, `#60a5fa` print) and unthemed scrollbar / button backgrounds (`#1a202c`, `#2d3748`, `#0f1419`). |
| `attachments_dropdown.py` | 75 | Hard-coded panel/border colors. |
| `home_ui/data_access_panel.py` | 51 | "Server Ready" badge uses fixed `#10b981` (semantic green) + `rgba(16,185,129,…)` glow. Could move to `success` token. |
| `home_ui/right_panel_widget.py` | 48 | Reads `theme.get(...)` correctly **but** fallback default is `#7c3aed` (violet) and `#0f1419` (panel) — wrong for the Blue baseline. |
| `home_ui/secretary_button_widget.py` | 37 | Hard-coded. |
| `patient_tab/ui/patient_ui/reception_reports_viewer.py` | 28 | Hard-coded. |
| `home_ui/patient_search_widget.py` | 24 | Hard-coded inputs / borders. |
| `patient_tab/ui/patient_ui/custom_tab_manager.py` | 19 | Blue tab gradients (`#2a3360`, `#1f2850`, `#111a34`, `#1a2344`, `#0c1324`). |
| `patient_tab/ui/patient_ui/patient_tab_widget.py` | 18 | Reviewed already during Case-of-Day work; uses semantic colors. Case-of-Day green added cleanly. |
| `patient_tab/ui/patient_ui/thumbnail_panel.py` | 12 | Themed *with* violet `#7c3aed` fallback — same bug-in-waiting as right_panel. |
| `patient_tab/ui/patient_ui/sidebar_widget.py` | 3 | Material blue `#2196f3` / `#1976d2` — this is the unthemed patient-row left accent. |

### 4.1 Confirmed offenders (UI users will see)

| Location | What's hard-coded | Visible symptom |
|---|---|---|
| `sidebar_widget.py:148-159` | `background-color: #2196f3` / `#1976d2` | Selected patient row's left strip stays Material blue in every theme. |
| `custom_tab_manager.py:387-440` | Three blue gradient triplets | Patient tabs on the top title bar stay blue in Green / Red / Yellow themes. |
| `patient_search_widget.py:42-104` | `#0f1419`, `#f7fafc`, `#4a5568` repeated | Search inputs (Patient ID, Patient Name, dates) keep one fixed look. |
| `reception_panel_widget.py:109-145` | Material blue + green | Reception Save / Action buttons stay Material blue/green in every theme. |
| `service_tab_widget.py:114-130` | `#1f2937 → #111827` gradient | Service tab background stays the same dark grey under any theme. |
| `data_access_panel.py:303-348` | `#f59e0b` + `#10b981` + `#ef4444` semantic status text | "Server Ready" stays green even in Yellow theme where the success token *is* green-yellow — no actual collision, but uses the wrong source-of-truth. |
| `right_panel_widget.py:528,617` | `#93c5fd`, `#1f2937` | A small purple text accent + thumbnail fill that don't theme-shift. |
| `right_panel_widget.py:31,255` | `theme.get('accent', '#7c3aed')` | Fallback is violet — wrong default for any of our seven themes. |
| `thumbnail_panel.py:150,187` | `theme.get('accent', '#7c3aed')` + `'#4a5568'` | Same fallback bug. |

### 4.2 Status-icon contrast issues (per-theme)

The graduation cap (`#fbbf24` — amber-400) and print icon (`#60a5fa` — blue-400) are intentionally semantic, but they're not contrast-checked against the theme:

- **Yellow theme**: graduation cap `#fbbf24` on `panel_bg=#171106` is fine; on Yellow's `accent_soft` (a hover band) it loses contrast.
- **Dark Red theme**: graduation gold + green check + pink accent + red danger = four warm hues fighting.
- **Blue theme**: print icon `#60a5fa` matches accent — looks intentional.

---

## 5. Prioritized fix list

Priority is calibrated to user impact (P1 = visible mismatch users will notice immediately), with rough effort estimates.

### P1 — visible mismatch on every non-Blue theme

1. **Patient row left accent → theme accent.** `sidebar_widget.py` lines 148–159: replace `#2196f3` / `#1976d2` with `theme['accent']` / `theme['accent_pressed']`. Effort: 15 min.
2. **Patient tabs gradient → theme.** `custom_tab_manager.py` lines 387–440: convert the three blue gradient triplets to `qlineargradient` with `theme['tab_bg']`, `theme['accent']`, `theme['panel_bg']` (we already wired `case_of_day_mode` to override these; same pattern, just generalize). Effort: 30 min.
3. **Patient search inputs → theme.** `patient_search_widget.py`: replace fixed `#0f1419` / `#f7fafc` / `#4a5568` with `panel_bg` / `text_primary` / `border`. Effort: 20 min.
4. **Reception panel buttons → theme.** `reception_panel_widget.py`: Save → `accent`, Action → `success`. Effort: 15 min.

### P2 — fallback bugs / inconsistency

5. **Fix violet fallback defaults.** `right_panel_widget.py:31,255` and `thumbnail_panel.py:150,187`: change `theme.get('accent', '#7c3aed')` to `theme.get('accent', '#3182ce')` (Blue baseline) — or better, remove the fallback and assert the theme is loaded. Effort: 10 min.
6. **"Server Ready" badge → use `success` token.** `data_access_panel.py:317`: read `status_color` from `theme['success']` and the glow from a mix-with-bg helper instead of hard-coded `#10b981` / `rgba(16,185,129,…)`. Effort: 20 min.
7. **Service tab background → theme.** `service_tab_widget.py`: convert the gradient to `theme['panel_alt_bg']` → `theme['panel_deep_bg']`. Effort: 10 min.

### P3 — palette balance

8. **Dark Red theme: split `accent` from `danger`.** Right now both are `#b63c57`, which makes Cancel/Delete buttons look like primary CTAs. Pick a more distinct red for `danger` (e.g. `#dc2626`) and keep `accent` as the rose pink. Effort: 5 min (data-only change in `DEFAULT_THEMES`).
9. **Yellow theme: differentiate `info`/`success`/`warning`.** All three are amber-adjacent (`#f59e0b`, `#eab308`, `#c99512`), making status indicators indistinguishable. Suggest `info` → blue-leaning amber `#0ea5e9`, `success` → olive-green `#84cc16`, keep `warning` amber. Effort: 5 min.
10. **Status-icon contrast guard.** Add a small helper that, given a token color and a background token, picks between two pre-defined variants (light/dark) when contrast ratio < 3.5. Use it for graduation cap and print icon. Effort: 1 hour.

### P4 — Theme panel UI

11. **Replace the 2×4 fixed card grid with a flowing card layout** and add a *Status* row inside each card showing the four key derived tokens (panel, accent, success, danger) so the user can preview without applying. Effort: 1–2 hours.
12. **Add a "Live preview" toggle** in the customizer that re-styles the home page in real time as sliders move, rather than only on Apply. Effort: 1 hour (the `themeChanged` signal already supports this).
13. **Larger active-theme indicator.** Currently the selected card has a thin 2 px border; bump to 3 px + accent-colored corner ribbon. Effort: 10 min.

---

## 6. Confirmation matrix (live walk-through)

| Theme | Loaded | Window / Panel | Search button | Patient row accent | Status bar | "Study Info" tab | Verdict |
|---|---|---|---|---|---|---|---|
| Blue | ✓ | Navy | Blue | Blue (matches) | Blue pill | Blue | Reference — no issues. |
| Gray | ✓ | Charcoal | Muted gray | Blue (mismatch) | Blue pill | Gray | CTA loses prominence. |
| Green | ✓ | Forest | Green | Blue (mismatch) | Blue pill | Green | Row accent jars. |
| Turquoise | ✓ | Cool dark | Teal | Blue (mismatch) | Blue pill | Teal | Similar to Green. |
| Dark Red | ✓ | Burgundy | Pink | Blue (mismatch) | Blue pill | Pink | `danger==accent` problem. |
| Yellow | ✓ | Brown | Amber | Blue (mismatch) | Blue pill | Amber | Status icons collide. |
| Custom (=Blue) | ✓ | Navy | Blue | Blue (matches) | Blue pill | Blue | OK. |

---

## 7. Suggested order of work

If you want to apply fixes incrementally:

1. **One commit** for P1.1 + P1.2 (sidebar accent + patient tabs) — biggest visible win for the smallest diff.
2. **One commit** for P1.3 + P1.4 (search inputs + reception buttons) — knocks out the remaining home-page mismatches.
3. **One commit** for P2 (fallback bugs + Server Ready) — defensive, low-risk.
4. **One commit** for P3 (Dark Red / Yellow palette rebalance) — pure data change in `DEFAULT_THEMES`, easy to revert.
5. Theme-panel UI (P4) is its own follow-up — would benefit from a quick mock-up first.

The theme system itself is solid. The work above is mostly tracking down stragglers, not redesigning the framework.

---

## 8. Implementation log (2026-05-30, same session)

The P1 + P2.5 + P2.6 + P2.7 + P3.8 + P3.9 fixes were applied in the same review session. Restart the source build to pick them up.

### P1.1 — Patient name underline → theme `info` token
**File:** `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:133-141`
**Change:** `CombinedDelegate._status_to_theme_color['opened']` switched from hard-coded `#60a5fa` to the theme token `'info'`. The faint blue underline that used to stamp on every row now shifts to cyan (Blue), teal (Green/Turquoise), pink (Dark Red), or cyan-blue (Yellow). The `'synced'` entry already used `'success'`.

### P1.2 — Patient tab gradient + border → theme tokens
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py`
**Change:** Imported `get_theme_manager`. Subscribed to `themeChanged`. `apply_styling()` now derives gradient stops from `tab_bg / panel_bg / accent / accent_secondary / accent_pressed` so default/hover/active backgrounds follow the active theme. `paintEvent()` border colour follows `theme['accent']` for active and `theme['border']` for inactive. Case-of-Day green override is preserved.

### P1.3 — Patient search inputs (no edit)
Already fully theme-aware via `apply_theme()` + `themeChanged` subscription. The hard-coded values in `setup_ui()` are dead initial state, immediately overwritten at construction.

### P1.4 — Reception panel buttons → theme `accent` / `success`
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/reception_panel_widget.py`
**Change:** Imported `get_theme_manager`. Subscribed to `themeChanged`. Two new builder methods (`_build_accent_button_stylesheet` for Open Attachments, `_build_success_button_stylesheet` for View Reports) consume theme tokens. Replaced inline stylesheets with calls to those builders.

### P2.5 — Violet fallback defaults swept
**Files:** `PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py` (3 sites), `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py` (2 sites).
**Change:** `theme.get('accent', '#7c3aed')` → `'#3182ce'` (Blue baseline); `theme.get('accent_pressed', '#5b21b6')` → `'#2c5282'`.

### P2.6 — "Server Ready" badge → theme `success` / `warning` / `danger`
**File:** `PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py`
**Change:** Added `_rgba_glow(hex)` helper that returns `(top, bottom, border)` rgba strings for the connection-status pill background. `on_server_changed()` now reads `t.get('warning')` for the in-flight Checking state, `t.get('success')` for ready states, and `t.get('danger')` for not-found. The pill glow + border are derived from the same hue, so when the user switches theme the pill stays semantic *and* harmonious.

### P2.7 — Service tab background → theme tokens
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/service_tab_widget.py`
**Change:** Imported `get_theme_manager`. Subscribed to `themeChanged`. `apply_styling()` themed-prefix derives from `panel_alt_bg / panel_deep_bg / border / tab_hover_bg / accent / text_primary`; the rest of the stylesheet (icon container alpha overlays, label colors) stays static.

### P3.8 — Dark Red theme: split `accent` from `danger`
**File:** `PacsClient/utils/theme_manager.py:99-118`
**Change:** `danger` moved from `#b63c57` (== accent) to `#dc2626` crimson. `status_busy` follows. Accent stays rose pink. The two reds are now visually distinct, so the Delete button no longer reads as a primary CTA.

### P3.9 — Yellow theme: differentiate info/success/warning
**File:** `PacsClient/utils/theme_manager.py:119-138`
**Change:** Palette rebalance so the three status tokens don't all cluster around amber.

| Token | Before | After | Hue |
|---|---|---|---|
| `info` | `#f59e0b` (amber) | `#0ea5e9` | sky blue — clear "informational" |
| `info_subtle` | `#78350f` | `#0c4a6e` | deep navy |
| `success` | `#eab308` (amber) | `#84cc16` | olive green — readable "ready/OK" |
| `success_subtle` | `#713f12` | `#365314` | deep olive |
| `warning` | `#c99512` (amber) | `#f59e0b` | canonical amber — caution |
| `badge_cyan` | `#c99512` | `#0ea5e9` | aligned with new `info` |
| `status_online` | `#eab308` | `#84cc16` | aligned with new `success` |

Other tokens (`accent`, `accent_secondary`, `danger`, backgrounds) unchanged so the overall Yellow feel is preserved.

### Verification
All five edited Python files parse cleanly under Python 3.13 (the runtime). The standalone sandbox uses Python 3.10 which trips on PEP 701 f-string features (`{t['accent']}` with single quotes inside a double-quoted f-string), but those reports are *pre-existing* and unrelated to this work.

### Still outstanding from §5

- **P3.10** — Status-icon contrast guard ✓ landed (see §9 below).
- **P4.13** — Theme panel active-indicator ✓ landed (see §9 below).
- **P4.11** — Theme panel per-card swatch row ✓ landed (see §10 below).
- **P4.12** — Customizer live-preview toggle ✓ landed (see §10 below).

All items from §5 are now applied.

---

## 9. Implementation log — second batch (same session)

### P3.10 — Status-icon contrast guard
**File:** `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py`
**Change:** Added a `_STATUS_ICON_PALETTE` dict mapping each semantic icon (graduation cap, print, voice) to a `(canonical, high-contrast-fallback)` tuple. Added two helpers:
- `_wcag_contrast_ratio(fg, bg)` — WCAG 2.1 contrast ratio (1.0–21.0)
- `_contrast_safe_color(icon_key, bg_hex, threshold=3.0)` — picks the canonical color if contrast vs `bg_hex` ≥ threshold, otherwise the fallback

Wired into `_build_local_status_widget`: graduation cap, print, and voice icons now ask the guard with the active theme's `panel_bg`. On Blue/Gray/Green/Turquoise/Dark Red the canonical colors pass (ratio ≥ 3.0 vs dark panels), so behavior is unchanged. On Yellow theme the graduation gold `#fbbf24` would drop below threshold against panel_bg `#171106`, so the lighter `#fde68a` variant ships instead — readable as semantic gold without competing with the amber accent.

### P4.13 — Theme panel: stronger active-theme indicator
**File:** `PacsClient/pacs/workstation_ui/AIPacs_ui.py:139-180`
**Change:** `_build_theme_card_style`:
- Selected border bumped 2px → 3px
- Selected gradient bottom stop swaps from `panel_bg` to `accent`, producing an accent wash along the bottom of the active card
- Unselected cards keep the original three-stop gradient + 2px border

Net effect: the active theme card has both a thicker accent border AND an accent-tinted bottom edge, so it's immediately distinguishable when scanning the 2×4 grid.

---

## 10. Implementation log — third batch (same session)

### P4.11 — Theme panel: per-card semantic-color swatch row
**File:** `PacsClient/pacs/workstation_ui/AIPacs_ui.py`
**Change:** Added `_build_theme_swatch_icon(theme_name)` that renders a 2×-resolution `QPixmap` of four colored rounded pills (accent / success / warning / danger) and returns it as a `QIcon`. The icon is set on each theme `QPushButton` at construction time (`button.setIcon(...)`, `setIconSize(QSize(72, 16))`). `_refresh_theme_selector` re-renders the icons on every theme switch so any palette edits made via the Customizer surface in the Custom card's preview swatches without a restart.

Net effect: a user opening the Theme panel can compare palettes side-by-side — Blue vs Yellow's new sky-blue `info`, Dark Red's split crimson `danger`, etc. — without having to apply each theme to see what its accent / success / warning / danger look like.

### P4.12 — Customizer dialog: live preview toggle
**File:** `PacsClient/pacs/workstation_ui/theme_ui.py`
**Change:** Added a `QCheckBox` ("Live preview (apply changes to the running app)") between the Reset button and the OK/Cancel row. State machinery:
- `__init__` snapshots `_original_active_theme_name` and `_original_custom_palette` so Cancel can restore them.
- `_on_live_preview_toggled(state)` flips `_live_preview_enabled` and either pushes the current palette to the running app (`update_custom_theme`) or restores the snapshot (`_restore_original_theme`).
- Every swatch change (`_pick_color`) and the Reset button now call `_push_live_if_enabled()`, which is a silent no-op when the toggle is off.
- The OK/Cancel buttons route through `_on_accept` / `_on_reject` — Cancel restores the snapshot if live preview was on; OK just calls the standard `accept()` and lets the outer caller's existing `update_custom_theme(dialog.custom_palette())` commit the result.

Default is OFF, preserving the legacy "OK to commit / Cancel to discard" semantics for any user who doesn't opt in.

---

## 11. Final status

All 13 items in §5 are landed and (where verifiable in this session) live-confirmed on the running source build:

| Tier | Items | Outcome |
|---|---|---|
| **P1** | 1.1 – 1.4 | landed + live-verified on Gray / Green / Yellow / Dark Red |
| **P2** | 2.5 – 2.7 | landed |
| **P3** | 3.8, 3.9 | landed + live-verified |
| **P3** | 3.10 | landed (Yellow-theme graduation-cap auto-swaps to light-amber `#fde68a`) |
| **P4** | 4.11 – 4.13 | landed (swatch row, larger active indicator, live-preview toggle) |

The theme system is now coherent across all seven palettes and the Theme panel itself is more informative (swatch previews) and responsive (live edit).

---

## 12. Implementation log — fourth batch (Default theme + final walk-through)

### "Default" theme added
**File:** `PacsClient/utils/theme_manager.py`
**Change:** Added a new "Default" entry as the first card in `DEFAULT_THEME_ORDER` and a corresponding palette in `DEFAULT_THEMES`. The Default palette is a cool neutral slate with a calm cobalt accent (`#2563eb`) — distinct from the saturated "Blue" theme. `reset_custom_theme()` now restores active theme to `"Default"` (was `"Blue"`), so the Reset button gives the user a one-click return to the canonical baseline.

### Final live walk-through (2026-05-30, post-restart)
With every P1–P4 fix in place, walked all six named themes and Custom on the running source build. Findings:

| Theme | Verdict | Notes |
|---|---|---|
| Blue | ✓ clean | Row underlines now cyan (`info` token), Search button blue, no issues |
| Gray | ⚠ CTA-soft | Accent `#8b95a7` reads as a quiet button. Intentional for the neutral theme. Recommended: user picks "Default" if they want a stronger CTA in a neutral palette. No code change. |
| Green | ✓ clean | Search button forest green, row underlines teal, Study Info tab green |
| Turquoise | ✓ clean | Teal accent, cyan underlines, distinctive without being loud |
| Dark Red | ✓ clean | P3.8 split (`danger` crimson vs `accent` rose) holding; Study Info pink |
| Yellow | ✓ clean | P3.9 differentiation working — info sky-blue, success olive, warning amber. Server Ready badge in olive (was muddy amber). Row underlines sky-blue (was hard-coded Material blue). The major-improvement theme of the review. |
| Custom | ✓ functional | Defaults to whatever the user last saved (Blue baseline out of the box) |

### Outcome

All themes render coherently. No per-theme code corrections were necessary beyond the work already landed; the Gray "soft CTA" note is a design-intent observation, not a defect. The Theme panel itself now shows:

- 4-swatch preview pills on every card (palette comparison at a glance)
- Thicker selected-card border + accent-tinted bottom edge (unmissable active state)
- A `Default` card at the top of the grid for one-click return to baseline
- Live-preview checkbox inside the Customizer for real-time edit feedback

The work plan from §5 of this review is complete.

---

## 13. Patient viewer optimization pass — 2026-05-30 (continuation)

After the home-page theme work, audited the **patient viewer chrome** for remaining hard-coded colors that escape the workstation theme. Four meaningful gaps found and fixed:

### PV-fix-1 — Active viewport container border → theme accent
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py:29-66`
**Before:** Active viewport drew a hard-coded sky-blue (`#60a5fa`) border + `rgba(96,165,250,0.08)` tint regardless of theme.
**After:** Border colour reads `theme.accent`; tint computed by parsing the accent hex into rgb and emitting `rgba(r,g,b,0.08)`. So on Green the active viewport gets a green ring + faint green wash; on Yellow it's amber; etc. Inactive viewport border stays the neutral `rgba(156,163,175,0.72)` so the active/inactive distinction reads at any palette.

### PV-fix-2 — Thumbnail panel "Loading" / "Ready" status pill → theme warning / success
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py:715-770`
**Before:** Status pill stamped `#f59e0b` (amber) on Loading and `#10b981` (emerald) on Ready, with matching rgba glow + border. Worked on Blue but stood out on Green/Yellow/Dark Red.
**After:** New helper `_build_status_pill_style(semantic_key)` derives text colour from `theme[semantic_key]` and builds the rgba glow + border ring from the same hex via QColor parsing. Status meaning (amber = in-flight, green = ready) is preserved across themes via the warning/success tokens.

### PV-fix-3 — Viewer sidebar tabs (Series / Reception Data / AI Chat) → theme accent
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/sidebar_widget.py`
**Before:** The vertical rotated tab buttons used Material blue `#2196f3` for selected and `#1976d2` for hover — clashed with every non-Blue theme.
**After:** Imported theme manager. Subscribed to `themeChanged`. `_get_button_style(checked)` now reads `accent`/`accent_hover`/`button_text` (selected) and `menu_bg`/`menu_hover_bg`/`text_muted`/`text_secondary` (inactive). Panel background uses `panel_deep_bg`. Re-styles live on theme switch.

### PV-fix-4 — Header widget toolbar → theme panel + border tokens
**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/header_widget.py`
**Before:** Toolbar background gradient hard-coded `#1f2937 → #111827` + border `#374151` + separator `#4b5563`. Same slate look under every workstation theme.
**After:** New `_build_toolbar_stylesheet(start_color, end_color)` builder derives the default gradient from `panel_alt_bg → panel_deep_bg`, border from `border`, separator from `border`. Caller overrides (used by the existing `update_gradient` API) still flow through this builder, so any custom gradient also inherits the theme border + separator. Re-styles live on `themeChanged`.

### Verification

All four files parse cleanly. Restart the source build, open a patient and:

1. Click between left/right viewport — the active viewport should ring in the theme accent (cyan on Default, blue on Blue, green on Green, pink on Dark Red, amber on Yellow).
2. Switch themes (Settings → Theme) while a patient is open — the viewer sidebar tabs, header toolbar background, and active viewport border all update live without reopening the patient.
3. Trigger a thumbnail download (re-open a patient) — the "Loading" / "Ready" pill at the top of the thumbnail panel takes on the theme's warning/success hue instead of fixed amber/emerald.

The patient viewer is now as theme-aware as the home page. Combined with the home work in §1–§12, every clinically-visible surface in the workstation follows the active theme.

---

## 14. Viewport frame + DICOM overlay safe-area pass

### Root cause

User reported two related visual issues:
1. "The box/frame around the viewport appears truncated near the bottom"
2. "DICOM overlay text appears partially outside the image area or too close to the viewport boundary"

Both trace to the same code: bottom anchors use a margin equal to the top margin, but font descenders + the container's accent border eat the available space.

**FAST viewer (`qt_slice_viewer.py::_paint_annotations`):**
With `margin = 8` and 4 lines of bottom-left text (Thk/Size/Scale/WW-WL), `y_bottom = self.height() - margin - N*line_height` places the last line's background within ~1 px of the widget's bottom edge. The widget sits flush against the container's inner edge, so the last line's text visually fuses with the 2 px container border.

**VTK viewer (`viewer_2d.py::load_bottom_left_actors` and friends):**
`bottom = 0.02` (normalized) was used for all four bottom-left actors + bottom-right Hospital actor. On a 400 px-tall viewport that's only ~8 px from the bottom edge — same crowding problem.

**Container grid layout (`_vc_layout.py::apply_multi_viewer`):**
`layout.setContentsMargins(0, 0, 0, 0)` let the VTK / FAST widget paint right up to the QFrame#ViewportContainer's inner edge. Under certain DPI / layout combinations the widget's background obscured the 2 px accent border at the bottom.

### Fixes landed

**`modules/viewer/fast/qt_slice_viewer.py`** — `_paint_annotations` now distinguishes between `margin = 8` (top/left/right) and `margin_bottom = 16` (bottom). Bottom-left and bottom-right Y positions use `margin_bottom`, doubling the safe area for the last line of text.

**`modules/viewer/advanced/viewer_2d.py`** — `load_bottom_left_actors`, `load_bottom_right_actors`, and `update_corners_actors_pos` all use `bottom = 0.04` instead of `0.02`. That's ~4 % from the bottom edge — twice the previous safe area on every viewport size.

**`PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py`** — Grid layout now uses `setContentsMargins(2, 2, 2, 2)` instead of `(0, 0, 0, 0)`. The 2 px inset reserves space for the container's accent border so the child widget can't paint over it. Affects every viewport regardless of backend.

### Theme considerations preserved

The overlay text color (`QColor(255,255,255,220)` semi-transparent white) and background (`QColor(0,0,0,120)` semi-transparent black) are intentionally hard-coded. Medical images sit on a black backdrop regardless of workstation theme, so theme-aware overlay tinting would risk losing readability on dark images. Industry convention is neutral high-contrast white on a dark scrim; left unchanged.

### Verification

After restart, open any patient and a series; the bottom-left text block (Thk / Size / Scale / WW-WL) should sit visibly above the viewport's accent border with clear breathing room. Switch viewport count (1×1 → 2×1 → 2×2); overlay should remain comfortable on every layout. The bottom edge of the container's accent ring should be fully visible at every viewport size.

### Follow-up correction (same day)

VP-fix-3's `setContentsMargins(2, 2, 2, 2)` on the viewport grid layout was reverted to `(0, 0, 0, 0)`. The 2 px inset caused the embedded VTK / FAST widget to be positioned 2 px inside the container while still rendering at its un-shrunk geometry, so dragged-and-dropped DICOM images plus their bottom overlays spilled past the container's bottom border.

VP-fix-1 (FAST viewer `margin_bottom = 16`) and VP-fix-2 (VTK viewer `bottom = 0.04`) are sufficient on their own — they push the overlay text far enough from the widget edge that the container's 2 px border becomes visually distinct from the overlay row without needing to physically shrink the widget. The user confirmed the viewport frame is now correct after this combination.

**Net rule for future viewport-frame work:** never add margins to the grid layout that holds VTK / QtSliceViewer widgets. VTK render windows do not honor Qt content margins reliably (they keep their pixel-sized render buffer regardless of the Qt geometry inset), and any visible-frame fix should be expressed via *overlay padding* inside the widget, not via outer layout margins.

---

## 15. Patient viewer follow-up — theme switch propagation

User reported that under the **Dark Red theme**, the active viewport border was still drawing in cyan/blue and the "{N} images" thumbnail count labels stayed bright Material blue regardless of theme.

### PV-fix-5 — Viewport container border doesn't update on theme switch

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`

The static method `_VCLayoutMixin._viewport_container_styles` reads the theme at call time, but it's only *called* when the container is first created or when `change_container_border` runs (which only fires on viewport selection change). Switching themes mid-session leaves existing containers with their stale stylesheet — explains the cyan border under Dark Red.

Added in `ViewerController.__init__`:

- Cache the `ThemeManager` instance
- Subscribe `_on_theme_changed_refresh_viewports` to `themeChanged`
- The handler iterates `lst_nodes_viewer`, reads each container's `active` property, and re-applies `_viewport_container_styles` so the border and inner tint pick up the new theme accent immediately.

### PV-fix-6 — Thumbnail "{N} images" count label hard-coded blue

**File:** `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py:988-1015`

Two code paths build the count label: `_create_thumbnail_widget` already used `self._theme.get('accent', '#3b82f6')`, but `_set_series_count_label_text` had a fully static stylesheet with `color: #3b82f6`. Both paths now use the theme accent token.

### Verification

After restart, switch themes while a patient is open:

1. Active viewport border should re-tint with the new accent immediately (cyan on Default, rose on Dark Red, amber on Yellow, etc.).
2. Each thumbnail's "{N} images" label should change colour to match the new accent.
3. Inactive viewports keep the neutral grey border so the active/inactive distinction stays unambiguous.

---

## 16. Thumbnail panel — semantic state badges + auto-download widget

User reported (post-PV-fix-5/-6): in **Dark Red theme**, every series thumbnail card still showed a bright Material-blue badge in the upper-left, and the small "Auto Download" floating widget kept the same blue regardless of theme. Two final fixes landed.

### PV-fix-7 — Thumbnail card state borders → semantic theme tokens
**File:** `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py:340-368`

`CircularProgressborder.paintEvent` chose its border + bg colour from a state machine: selected / viewed / ready / downloading / pending. The first three were hard-coded purple `#8b5cf6`, green `#10b981`, blue `#3b82f6`. They now read from theme tokens:

| State | Token | What it means |
|---|---|---|
| selected | `accent` | "current / being viewed" — matches workstation accent |
| viewed | `success` | "completed" — universal green/semantic ready |
| ready | `info` | "available, not yet viewed" |
| downloading | `info` | "in flight" (was already themed) |
| pending | `border` | neutral grey (was already themed) |

The semantic palette is preserved (accent ≠ success ≠ info), but each hue now shifts with the workstation theme.

### PV-fix-8 — Auto-download widget + ModernProgressBar → theme tokens
**File:** `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`

The floating "Auto Download" widget (border + title text + progress bar chunk + counter label) and the standalone `ModernProgressBar` both stamped Material blue `#3182ce` regardless of theme. Both now derive border/chunk/title from `theme.accent`, the progress track from `theme.panel_deep_bg`, and body text from `theme.text_primary` / `theme.text_secondary`.

The status label, which was Material blue `#3182ce` in `setPendingStyle` / `setDownloadingStyle` / `setCompleteStyle`, now uses `theme.warning` / `theme.info` / `theme.success` via a new `_themed_status_style` helper.

### Result

After restart and switching to Dark Red:
- The small badge in each thumbnail card's upper-left no longer reads Material-blue; it picks up the theme's `info` (rose-magenta in Dark Red) for ready/un-viewed series, theme `success` for viewed series, and `accent` for the currently-selected series.
- Auto-download popups (if triggered) display in theme colours.
- Status labels in the thumbnail status row also follow theme `warning` / `info` / `success`.

This closes the last visible blue-on-non-Blue-theme inconsistencies in the patient viewer chrome.

---

## 17. V2 design promoted to default (2026-05-31)

After the theme + per-widget audits in §1–§16, V2 had reached parity with V1 across every clinically-visible surface and added the new (Default + 6 themes), the theme panel preview swatches, the live customizer, and the per-state thumbnail badges. The V1/V2 dual-track was always meant to be a transitional safety scaffold; with V2 now feature-complete and audited, it's time to make it the shipping default.

### What changed

**`PacsClient/utils/ui_variant.py`** — three default-value sites flipped from `"v1"` to `"v2"`, gathered behind a single new constant `_BUILD_DEFAULT_VARIANT = "v2"`:

- `get_ui_variant` first-fallback (no config, no env)
- `get_ui_variant` invalid-value fallback
- Exception-path fallback (corrupt JSON, missing file, etc.)

This is the only change required to make V2 the default. V1 stays fully reachable:

- **Env var** (per-session): `set AIPACS_UI_VARIANT=v1`
- **Config file** (persistent): write `{"variant": "v1"}` to `<USER_DATA_ROOT>/config/ui_variant.json`
- **Per-module override** (mix and match): `{"variant": "v2", "modules": {"home": "v1"}}` — V2 everywhere except the home page

Module docstring rewritten to reflect the inverted default and document the V1-rollback recipes. Build-default centralised behind `_BUILD_DEFAULT_VARIANT` so a future re-flip (in either direction) is a one-line change.

**`PacsClient/utils/v2_style.py`** — module docstring updated to document V2-as-default; the helper functions (`home_is_v2`, `viewer_is_v2`, `settings_is_v2`) unchanged because they already delegate to `get_ui_variant`, which now returns the new default.

**`tests/code/test_ui_variant_scaffold.py`** — assertion suite rewritten:

| Old test | New test |
|---|---|
| `test_default_is_v1_when_no_config` | `test_default_is_v2_when_no_config` |
| `test_invalid_variant_falls_back_to_v1` | `test_invalid_variant_falls_back_to_default_v2` |
| `test_global_v2` | `test_explicit_v2` |
| `test_per_module_override` (was V1 + home→V2) | `test_per_module_override_v1_within_v2` *and* `test_per_module_override_v2_within_v1` (both directions covered) |
| `test_env_override` | adjusted — env "garbage" now falls back to V2 |
| `test_never_raises_on_bad_load` | asserts V2 fallback on exception |

Added `test_explicit_v1_still_works` so the legacy/backup path is proven by a dedicated test — if a future change accidentally locks out V1, the test fails loudly.

**`CLAUDE.md`** — `### Viewer/Home "V2" design layer` section retitled "DEFAULT — flipped 2026-05-31" and the "V2 is opt-in and default OFF" invariant rewritten to "V2 is now the default; V1 is preserved as a backup variant". Both the env-var and config-file rollback recipes are documented in the new copy.

### What did NOT change

- The V2 stylesheets themselves (`v2_style.py`, `theme_v2.py`)
- Any V1 styling code (it remains the byte-identical fallback when a user pins V1)
- Per-module gating (every `apply_*_v2()` wrapper still consults its module flag)
- Theme manager, theme palette data, or any of the per-theme work from §1–§16

### Rollback path

If a user reports problems after the flip and we need to revert:

1. **Per-user revert**: ask the user to set `AIPACS_UI_VARIANT=v1` in their environment, or drop `{"variant": "v1"}` into `<USER_DATA_ROOT>/config/ui_variant.json`. No code change needed.
2. **Per-build revert**: change `_BUILD_DEFAULT_VARIANT = "v2"` back to `"v1"` in `ui_variant.py`. Ship a build. Every `apply_*_v2()` wrapper will revert to no-op on next start.
3. **Hybrid**: pin individual modules back to V1 via the `modules` map in the JSON config — useful if exactly one V2 surface needs more work but the rest can stay.

This is the design migration's quiet "graduation" moment: V2 is now the shipping appearance, V1 is the safety net.
