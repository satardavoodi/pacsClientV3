# Theming dialogs & popups — OS light/dark-mode immunity (2026-07-24)

## The recurring problem

Custom popups, dialogs, and text boxes were changing appearance with the Windows
(or app) light/dark mode — text became unreadable (dark-on-dark, white-on-white).
Each instance was fixed individually (latest: the Eagle Eye 3D Cursor windows).

## Root cause

`main.py` applied a global **stylesheet** (`app.setStyleSheet(...)`) but:

- it kept the **native Windows style**, whose default palette **follows the OS
  light/dark theme**, and
- it set **no fixed `QPalette`**, and
- the global QSS only targets the **built-in** dialog classes
  (`QMessageBox`, `QInputDialog`, `QFileDialog`, `QColorDialog`, `QFontDialog`,
  `QProgressDialog`, `QToolTip`) — there is **no** broad `QDialog`/`QWidget`/
  `QLabel` rule.

So a **custom** `QDialog`/`QWidget` that does not set its own complete stylesheet
falls back to the **QApplication palette**, which tracked the OS theme → broke in
light/dark mode. The 3D Cursor dialog is the textbook case: it sets light-on-dark
**label colours** but **no background**, so on a light OS palette its text vanished.

## The centralised fix (done)

At the app level, `main.py::_apply_application_theme` now calls
`PacsClient.utils.theme_manager.apply_global_app_theme(app, theme)` **before** the
global stylesheet. That function:

1. installs the **Fusion** style — a Qt-drawn style whose colours come from the
   palette, so it does **not** follow the OS light/dark theme; and
2. sets a **fixed dark `QPalette`** built from the active theme
   (`build_application_palette(theme)`), so any widget without explicit
   stylesheet colours falls back to the app's intended dark colours.

The global QSS is applied **on top** and overrides both the style and the palette
for every widget it targets — so already-styled widgets are unchanged and only the
previously-broken, un-styled widgets change (OS-coloured → correctly dark). It is
re-applied on every theme change. Kill switch: `AIPACS_FORCE_APP_THEME=0`.

**Result:** new custom dialogs/popups are dark-and-readable by default — no
per-widget fix needed.

## What still needs care (the residual cases + the consistent method)

The centralised palette fixes any popup that **doesn't fight it**. A widget can
still look wrong only if it **hard-codes a conflicting colour**. The rules:

1. **Never hard-code a light background** (`background:#fff`, `background:#f0f0f0`,
   or a white QSS) on a dialog/container. That defeats the palette. If you need a
   panel colour, use a theme token.
2. **Prefer theme tokens over literals.** Get colours from
   `get_theme_manager().current_theme()` — e.g. `t['panel_bg']`, `t['text_primary']`,
   `t['accent']`, `t['border']` — the same tokens the app stylesheet uses. A dialog
   styled from tokens tracks the app theme automatically.
3. **If you set text colours, do NOT rely on the OS background.** Setting only a
   text colour (as the 3D Cursor dialog did) is fine now because the background is
   the app's dark palette — but only because the fix exists. Don't set a light text
   colour and assume a light background.
4. **A widget built in an unusual context** (a different top-level, an embedded
   native child) can be force-corrected with
   `theme_manager.apply_dialog_theme(widget)` — it re-asserts the app's dark
   palette on that subtree. This does **not** override a hard-coded stylesheet
   (see rule 1).

## Quick checklist for a new dialog

- [ ] Do not set a hard-coded light `background`.
- [ ] If styling, pull colours from `get_theme_manager().current_theme()` tokens.
- [ ] Test it once with Windows in **light** mode — text must stay readable.
- [ ] Only if it looks wrong in an odd embedding: call `apply_dialog_theme(self)`.

Guard: `tests/code/system/test_app_theme_enforcement.py`. Master plan: OPT-44.
