# UI-4 — the stray bar at the bottom of the main page

**Date:** 2026-08-10
**Reported as:** *"Look at the screenshot on the main page; there is a bar at the lower part. Please remove it."*
**Status:** fixed, guarded, reversible
**Files touched:** `PacsClient/pacs/workstation_ui/AIPacs_ui.py` (one guarded block)
**Guard test:** `tests/code/ui_services/test_main_footer_bar_removed.py` (6 guards)
**Kill switch:** `AIPACS_MAIN_FOOTER=1` restores the old behaviour

---

## 1. What the user saw

A thin horizontal band across the bottom of the main (home) page, under the
patient list. On the screenshot it reads as either a stray separator or a
disabled horizontal scrollbar. It carries no text, no control the user can
click, and no state.

## 2. What it actually was

`AIPacs_ui.py::setupUi` builds a **footer container** and appends it to the
main vertical layout (`AIPacs_ui.py:812-843`):

```python
self.footerContainter = QWidget(self.mainBodyContainer)          # 812
  self.frame_10  -> self.label_15      = QLabel("")               # 819-823
  self.frame_14  -> self.activityLabel = QLabel("")               # 826-834
  self.sizeGrip  = QFrame(...)  20x20, objectName "sizeGrip"      # 837-841
self.verticalLayout_10.addWidget(self.footerContainter)           # 843
```

Measured on the live window at 1920x1032 by sampling the rendered pixels, the
band is made of three separate things:

| y | What draws it |
|---|---|
| 1002 | a full-width 1 px line — the `border-top` that `apply_theme()` applies to `footerContainter` (`AIPacs_ui.py:931`) |
| 1007-1008 | the borders of the two **empty** child frames, x 72-684 and x 1291-1296 |
| 1007-1008 | the 20 px `sizeGrip` square at x 1890-1909 |

So it is not one widget: it is a themed empty strip whose only visible output
is its own chrome. It also consumed roughly **30 px of vertical space** —
space that the patient list could otherwise use.

## 3. Root cause

The footer is a leftover from the Qt Designer-generated shell. Its two labels
were designed to show a status message and an activity indicator, and the
`sizeGrip` was meant to be a window resize handle. None of the three was ever
wired up:

- `label_15` and `activityLabel` are constructed with `""` at
  `AIPacs_ui.py:822` / `:829` and are **written nowhere else in the codebase**
  — verified by scanning every `.py` under `PacsClient/`, `modules/` and
  `main.py`.
- `sizeGrip` is a bare `QFrame`, **not** a `QSizeGrip`. There is no `QSizeGrip`
  anywhere in the project, and nothing references the `sizeGrip` attribute
  after it is created. It never resized anything — the frameless main window
  is resized by its own edge handler, which this change does not touch.

The band therefore has no function. It is pure residue that the theme makes
visible.

## 4. The fix

Hide the container, keep the objects alive (`AIPacs_ui.py:863-868`):

```python
try:
    if (os.getenv("AIPACS_MAIN_FOOTER", "0") or "0").strip() == "0":
        self.footerContainter.setVisible(False)
        self.footerContainter.setFixedHeight(0)
except Exception:
    pass
```

Three deliberate choices:

- **Hidden, not deleted.** `apply_theme()` still styles `footerContainter` and
  `activityLabel` (`AIPacs_ui.py:931`). Deleting the widgets would mean editing
  the theme path too — a larger change with more ways to go wrong. Hiding is
  the minimal edit and it is fully reversible.
- **`setFixedHeight(0)` as well as `setVisible(False)`.** `setVisible(False)`
  alone leaves the layout free to re-reserve the space on a later relayout;
  pinning the height to 0 makes the reclaim stick.
- **`try/except`.** Consistent with the rest of `setupUi`: a UI cosmetic must
  never be able to abort window construction.

`AIPACS_MAIN_FOOTER=1` puts the strip straight back, with no code change.

## 5. Why this is safe

| Risk | Why it does not apply |
|---|---|
| Loses a status message | Both labels are permanently `""`; nothing writes them. |
| Breaks window resizing | `sizeGrip` is a `QFrame`, never a `QSizeGrip`; nothing references it. The frameless-window resize handler is untouched. |
| Breaks theming | The widgets still exist, so `apply_theme()` keeps working unchanged. |
| Irreversible | One env var restores it. |

No clinical surface, no metadata, no overlay, no measurement, no sidebar and no
patient workflow is involved — this is chrome on the home shell only.

## 6. Guard tests

`tests/code/ui_services/test_main_footer_bar_removed.py` — 6 tests:

| Test | What it pins |
|---|---|
| `test_footer_is_suppressed_by_default` | default env hides the strip |
| `test_footer_widgets_are_not_deleted` | the widgets survive, so `apply_theme` cannot break |
| `test_footer_labels_are_never_written_anywhere` | scans the app sources — fails if anyone starts writing `label_15` / `activityLabel`, which would mean the footer has become functional and must not stay hidden |
| `test_sizegrip_is_a_plain_frame_and_unused` | `sizeGrip` stays a bare, unreferenced `QFrame` |
| `test_no_qsizegrip_anywhere_in_the_project` | fails if a real `QSizeGrip` is ever introduced |
| `test_footer_hidden_on_the_real_shell` | behavioural — builds the actual shell offscreen and asserts the strip is not visible |

The last one matters: the first five are source pins, and a source pin cannot
see a layout regression. Note also that `test_no_qsizegrip_anywhere_in_the_project`
strips comments before matching (`_strip_comments()` / `_uses_qsizegrip()`),
because the explanatory comment written for this very fix contains the string
`QSizeGrip` and would otherwise fail its own guard.

## 7. Remaining risk

Low. The one scenario worth naming: if a future feature wants a status bar on
the home page, the correct move is to build it deliberately rather than to flip
`AIPACS_MAIN_FOOTER=1` and reuse this shell — the strip's geometry and styling
were never designed for real content.
