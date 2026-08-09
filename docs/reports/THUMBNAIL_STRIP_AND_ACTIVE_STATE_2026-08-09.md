# Series thumbnails: progress bar hidden + active state stuck (UX-1/2/3)

Three reported UI/UX defects on the series thumbnail cards, all fixed in
`PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` (+ one hook in
`_pw_series.py`). Visual reference: `thumb_states_2026-08-09.png`.

## UX-1 — download progress bar partially hidden behind the thumbnail

**Measured, not guessed.** Built a real card offscreen and read the stacking
order and the rendered pixels:

```
stacking order (last = topmost):  glass_overlay, dl_bar, CircularProgressborder
bar rows 204..207 painted:  #162134, #162134, #162134, #3180c9
```

Three of the bar's four rows painted the card's content background — only the
single row below the content was ever blue. Exactly the reported symptom.

**Root cause.** The strip widgets are absolutely-positioned direct children of
the card, but `main_layout.addWidget(progress_border)` runs *after* them, and
`addWidget` **re-parents** the border onto the card. A re-parent moves a widget
to the TOP of the sibling stack, so the opaque card content ended up above the
bar. The existing `_bar.raise_()` ran *before* that `addWidget`, so it was
always undone. (The later `_raise_dl_bar_above_glass` calls only run when a
download shows the glass overlay — which is why the bar looked correct in some
situations and hidden in others: "in some layouts".)

**Fix.**
* Re-raise + re-place the strip **after** the border joins the layout.
* `_CardStripKeeper` event filter re-applies geometry *and* z-order on
  Show/Resize/ChildAdded/LayoutRequest, so no later re-parent, re-polish or
  resize can bury or displace it again.
* Geometry now derives from the card's **live size** (`_card_strip_rect`)
  instead of the hard-coded `setGeometry(8, 215 - 11, 190 - 16, 4)`, which
  silently assumed a 215 px card and drifted in any other layout.
* `_raise_dl_bar_above_glass` delegates to the same helper — one code path owns
  "the strip is placed correctly and on top".

Verified after the fix: all 4 bar rows paint `#3182ce`, no sibling above it.

## UX-2 — active state stuck on green after re-dragging a viewed series

**Root cause.** `DraggableButton.mouseMoveEvent` emitted `dragStarted` only when
the button was *not already checked* — and nothing in the app ever un-checks a
card. So on **drag A → drag B → drag A**, the third drag found A still checked
from the first, skipped the signal entirely, and the manager never moved
`selected_series` back to A. A kept its green "viewed" border.

(The paint precedence was already correct — `paintEvent` ranks selected above
viewed/ready/pending. The state simply never arrived.)

**Fix.**
* `begin_drag_selection()` — extracted, always sets checked **and** emits, on
  every drag. Extracted as a method so it is testable without spinning the
  native OLE drag loop.
* New `ThumbnailManager.set_active_series()` — sets `selected_series`
  unconditionally, un-checks every other card (so the checkable state can no
  longer drift out of sync and suppress a later drag), and applies with
  `immediate=True` (a direct user action must not wait on the 150 ms coalescing
  window).
* Hooked into `_PWSeriesMixin.change_series_on_viewer` — the single entry point
  for drag-drop / click / keyboard series loads, so the active marker follows
  whatever actually lands in the viewport rather than only the drag signal.
  Gated on `flag_change_selected_widget` so internal reloads are unchanged.
* A click on the already-active card used to un-check it and fall through doing
  nothing; it now re-asserts active.

## UX-3 — red active-series line

A red line in the same bottom strip, driven only from `selected_series`, so it
can never get stuck on a card that is no longer active. Strip precedence:

| strip | meaning |
|---|---|
| blue bar filling | downloading / caching |
| red line | this series is the active one |

While a download is **still filling** (`value < maximum`) the blue bar owns the
strip — an in-flight transfer is the more urgent fact. Once complete the red
line (raised last, same geometry) takes it back. Plus the existing stronger
accent border on the active card.

Kill switch: `AIPACS_THUMB_ACTIVE_BAR=0`.

## Tests

`tests/code/ui_services/test_thumbnail_active_state_and_strip.py` — 20 new pins,
**behavioural on real Qt widgets** (offscreen): no sibling covers the bar; bar
above the border specifically; every bar row paints the chunk colour; strip
geometry follows the card size and stays inside it; the full A→B→A sequence;
`dragStarted` fires on an already-checked button; other cards un-checked;
immediate apply; red line visibility, colour, stacking and reset; strip stays
click-through.

A z-order bug is invisible to a source-string pin — which is exactly how this
survived the existing `test_thumbnail_panel_ui_fixes` file. That file's pin on
the hard-coded geometry literal was updated to pin the new invariant instead.

**Results.** 232 passed across the thumbnail/fast/viewer suites; `py_compile`
clean. Full `ui_services + fast + viewer` run: 15 failures — **14 of which
reproduce identically with these changes stashed** (verified by a baseline run:
`test_field_icon_chip` ×5, `test_local_incremental_and_import_date` ×3,
`test_report_assign_rendering`, `test_status_report_sorting`, and
`test_fast_viewer_pipeline::test_b41_*` ×4, the last being cross-file ordering
pollution — they pass in isolation). The 15th was the stale source pin above,
now fixed. **No regressions introduced.**

## Residual risk

* `change_series_on_viewer` also fires on pipeline/progressive loads into a
  non-focused viewport, so the active marker could move without a user drag.
  Gated on `flag_change_selected_widget`; worth a live look during normal
  reporting, and easy to narrow to the drop path alone if it feels wrong.
* Requires an app restart to take effect.
* The strip keeper adds one event filter per card (~16 cards typical) — it only
  acts on Show/Resize/ChildAdded and compares geometry before writing, so the
  scrolling/repaint cost is negligible, but it is new per-card machinery.
