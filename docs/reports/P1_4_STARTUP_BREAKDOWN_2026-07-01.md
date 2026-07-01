# P1.4 startup freeze — finer breakdown + finding (2026-07-01)

Measurement step of P1.4 (chosen over a blind deferral). Added telemetry-only sub-stage markers to
`ControlPanelWindow.setupUi` (`setupUi_pre_home`, `setupUi_post_home`, `setupUi_apply_theme`) and
relaunched. Guard: `tests/code/system/test_startup_stage_subtiming.py` (4 green).

## Measured breakdown (pid 190784)

| stage | ms |
|---|---|
| db_init_migrate | 2 |
| setup_ui | 52 |
| `setupUi_pre_home` (left menu + hidden center/theme menu) | 139 |
| **`home_widget` (patient panel — essential visible UI)** | **1253** |
| settings_widget | 25 |
| `setupUi_post_home` (data page, nav wiring) | **6** |
| **`setupUi_apply_theme` (in-setupUi theme apply)** | **847** |
| add_AIPacs_tab (total) | 2452 |
| apply_theme (separate, in MainWindow) | 183 |
| **MainWindowWidget_total** | **~2.7–3.7 s** |

The previously-unattributed ~1334 ms of `add_AIPacs_tab` is now explained: **847 ms is theme
application inside `setupUi`**, `139 ms` is the pre-home menu build, and the post-home build is
negligible (6 ms).

## Finding

Two big startup costs, only one of which is safely actionable:

1. **`home_widget` = 1253 ms** — building the patient list/search panel. This is the **first screen
   shown**, essential, and not safely deferrable.
2. **Theme application ≈ 1030 ms total** — `setupUi_apply_theme` (847 ms) + the separate MainWindow
   `apply_theme` (183 ms). `ControlPanelWindow.apply_theme` (AIPacs_ui.py:873) does dozens of
   individual `setStyleSheet` calls and **cascades** into `home_widget.apply_theme` and
   `host_window.apply_theme` (= `MainWindowWidget.apply_theme`). The MainWindow then calls
   `apply_theme` **again** at `mainwindow_ui.py:161` — the same tree is themed at least twice.

There is a plausible **redundancy** (the setupUi cascade already themes the host window before the
MainWindow's own `apply_theme` runs), and each `setStyleSheet` forces a Qt style re-polish, so the
847 ms is likely inflated by repeated re-polishing.

## Recommendation — do NOT change this blind

`apply_theme` is a **startup-critical, visual, fragile path**. The code itself records a prior bug:
an `AttributeError` in `apply_theme` *"aborted `_open_main_window` — app hung at login"* (AIPacs_ui.py
~:934). A theme dedup/optimization:
- is **visual** — cannot be verified from logs, only by eye;
- has a **complex cascade** (ControlPanelWindow → home_widget + host_window → MainWindow), so proving
  redundancy is non-trivial;
- risks **hanging the app at login** if it goes wrong;
- buys a **one-time** launch saving, not during-reading responsiveness.

Given the during-use wins are already delivered and verified, this is **lower value / higher risk**.

### If pursued later (careful, dedicated pass)
1. Read `ControlPanelWindow.apply_theme` (AIPacs_ui.py:873) + `MainWindowWidget.apply_theme`
   (mainwindow_ui.py:1029) + their cascades fully; confirm which widgets each covers.
2. Hypothesis to test: the MainWindow `apply_theme` at `mainwindow_ui.py:161` is redundant with the
   cascade already run during `setupUi` — skip it behind a flag (default-off) and **visually verify**
   the whole window is still themed at login (single + multi-monitor, all themes).
3. Separately, reduce re-polishing: batch the per-widget `setStyleSheet` where possible, or apply the
   theme once after the tree is built rather than mid-construction.
4. Flag-gated default-off, guard test, and a **login/visual** verify on the source build before any
   default flip.

## Status

Measurement instrumentation shipped + guard-tested (telemetry-only, zero risk). The actual startup
optimization is **deferred** as a careful, dedicated, visually-verified effort — not a blind cut.
