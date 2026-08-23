# MPR interaction stability — jitter, lag, loading, tool state

**2026-08-23.** Owner report: the MPR *geometry* is correct — zoom, normal
viewing and rotation all look right, including rotated planes. What feels
unstable is the interaction. Five items, all diagnosed to a specific mechanism
and fixed. **No geometry was touched**, per
`docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.

---

## 1. Crosshair centre jitter — the pointer really was being drawn twice

**Cause.** The hover path drove the cursor through **two different APIs on the
same frame, with contradictory values.** In the centre zone:

```python
self.parent._set_view_cursor(self.view_name, None)          # Qt, SYNCHRONOUS  → arrow
self.GetInteractor().GetRenderWindow().SetCurrentCursor(10) # VTK, DEFERRED    → crosshair
```

The VTK write does not reach the widget on the same turn —
`QVTKRenderWindowInteractor` applies it via `QTimer.singleShot(0, ShowCursor)`,
a full event-loop turn later. At the ~60 Hz hover cadence that is a 30–60 Hz
alternation between two glyphs whose hotspots differ by 8–16 px. That is the
shake.

Two aggravating factors:

* **No hysteresis, at a boundary that is geometrically guaranteed to overlap.**
  The centre disc is 20 px; the line bands are 15 px. Every point of the centre
  disc is also inside a line band (`20/√2 = 14.1 < 15`), so `centre` and
  `h_line` share a hard edge at exactly r = 20. Display coordinates are
  integers, so hand tremor is a 1 px flip across it — every frame.
* **No "only on change" guard.** The computed zone was thrown away by the
  caller, so the cursor was re-issued ~62×/s even when nothing had changed.

**Fix.** One API (Qt), one write per actual change, and a dead-band: enter the
centre at 20 px, leave at 26; enter a line at 15, leave at 19. The cached shape
is cleared on button release, because a drag can move the cursor behind the
hover path's back.

**Also fixed on the way** — a latent bug found while reading it. The three drag
branches in `on_mouse_move` tested `dragging_handle` / `dragging_line` /
`dragging_center` **without checking whether the button was down** (the stack
branch below them did). `dragging_center` lives on the *parent*, shared by all
three panes, so a single missed release — interactor style swapped mid-gesture,
a toolbar tool taking over, focus lost — would let a buttonless hover keep
re-centring the crosshair on the pointer. The crosshair would visibly chase the
mouse. All three now require the button.

Kill switch: `AIPACS_MPR_HOVER_STABLE=0`.

---

## 2. The loading indicator — there was never one dialog

The MPR button does not have *a* loading dialog. It has **four independently
created, independently thresholded, independently parented `QProgressDialog`s
plus an in-cell placeholder**:

| # | text | threshold | parent |
|---|---|---|---|
| A | "Loading MPR volume…" | ≥ 80 **files** | patient widget |
| B | "Preparing MPR views (N slices)…" | ≥ 200 **slices** | patient widget |
| C | "Preparing MPR volume…" | ≥ 200 **slices** | patient widget |
| D | "Building 3D volume rendering…" | **no threshold** | **the MPR widget** |
| E | in-cell "Rendering 3D…" / "click to render" | — | the 3D cell |

That explains all five reported symptoms without anything being wrong with the
build itself:

* **open / close** — each helper creates and `deleteLater()`s its own dialog
  before the next exists. Between A closing and B opening the code runs the
  volume resolve tail and `canonicalize_volume` with **no indicator and no event
  loop**: a visible gap where the window looks hung.
* **reappear** — D is parented to the MPR widget, not the patient widget, so the
  "same" popup returns **in a different screen position with a different title**
  ("3D View"), *after* MPR is already on screen.
* **speed change** — an indeterminate marquee needs the event loop. During C's
  nested `loop.exec()` it animates; the moment C closes, the
  `StandardMPRViewer(...)` constructor runs ~10 s with no `processEvents`, so
  B's marquee **stops dead** and then jumps when the dialog is destroyed.
* **restart** — every hand-off constructs a *new* `QProgressDialog`, whose
  marquee starts at phase 0. C is created **on top of a visible B**, so the
  popup changes text and size and restarts in place without ever going away.

**Fixed now:** C no longer exists as a separate dialog. `_prepare_mpr_flip_offthread`
accepts the caller's live dialog and reuses it (text only), so the stacked
second modal and its restarted animation are gone. When no dialog is passed —
small volume, flag off — it still creates and owns one, exactly as before.

**Deliberately not done yet, and why.** Collapsing A/B/D into one hoisted
indicator is the right end state, but D's existence and its default-ON flag are
pinned by `test_mpr_deferred_3d_layout_stability.py`
(`test_busy_dialog_has_a_default_on_kill_switch`), and B's gate, its single
`processEvents` and its close are pinned by `test_mpr_open_latency_opt48.py`.
Those are deliberate guards, not accidents; changing them is a separate,
explicit decision rather than something to slip into an interaction fix. The
remaining honest improvement is **not to show an animation that is expected to
move** — a marquee that stalls for 10 s reads as "crashed", where a static
indicator reads as "working".

---

## 3. Interaction latency, and the VRT first-rotation delay

**The first-rotation delay had a specific cause, and it was not the throttle.**
The interaction throttle is a correct leading-edge design — the first event of
an idle gesture runs immediately.

What actually happened: **`_set_active_view` was called twice per press and
twice per wheel notch** — once from the Qt event filter (which sees the event
first) and again from the interactor style's own handler. Each call restyled all
four view containers, and `QWidget.setStyleSheet` on a container re-polishes its
whole subtree — including the `QVTKRenderWindowInteractor` child, whose
`paintEvent` is a full `Render()`. On the 3D pane that is a full ray-cast,
queued *between the press and the first rotate frame*.

Fixes:

* **Re-setting the already-active view now returns immediately.** Kills the
  second sweep on every press and every notch. (`AIPACS_MPR_ACTIVE_VIEW_NOOP_GUARD=0`)
* **A genuine view change restyles only the two containers that changed**, not
  all four.
* **VRT press arms rotation before restyling.** `super().OnLeftButtonDown()` is
  what calls `StartRotate()`, which switches the window from `StillUpdateRate`
  to `DesiredUpdateRate` — so restyling first meant the queued repaint ran at
  **still quality**. Order only; no behaviour change.
* **The oblique diagnostic validator no longer runs on every frame.** It
  snapshotted all three cameras, allocated numpy arrays, ran ten checks and
  formatted a log record — synchronously, on the GUI thread, inside the
  crosshair rotation loop. One field session produced 1 152 such lines. And its
  failures are false: three of its checks measure the *camera's* plane, which
  has not selected the displayed slice since v1.09.Fix-E. Per-frame cost for a
  wrong answer. Still available: `ZETA_MPR_DIAG=1` or
  `AIPACS_MPR_OBLIQUE_VALIDATE=1`.
* **A new gesture is no longer throttled by the previous one.** The final update
  on release resets the throttle clock, so a release-then-press inside 16 ms had
  its first event deferred.

**Rejected**, because each violates a documented invariant: batching the
scrolled pane's own render (that immediacy is deliberate and would *add*
latency); any `ResetCamera` on an interaction path; changing
`stable_scroll_camera_step`; adding a step to the per-kind interaction call
lists.

---

## 4 & 5. Toolbar tools must not close MPR; MPR opens and closes from its own button

**Cause — one line.** `check_and_deactivate_tools` ended its MPR branch with an
unconditional `self.toggle_zeta_mpr()`. It fires when `tool_selected == 'mpr'`
(the state right after MPR opens) and the active widget is the MPR host — so the
**first** tool click after opening MPR tore it down.

Eight tools reached it: Text, Two-Line Angle, ROI, Circle ROI, AI Chat, Reset
All, Sync Image, Upload.

**On Arrow specifically — worth being exact.** Arrow does *not* close MPR; it has
a correct MPR branch and `activate_arrow()` is fully implemented. What it was
missing is `handle_buttons_checked()`, which Ruler and Angle both call. So the
button stayed unchecked after a successful activation, the user clicked again,
and the second click took the *deactivate* branch. From the reading desk that is
indistinguishable from "the tool broke". Fixed.

**Fixes:**

1. **The implicit close is now opt-in.** `check_and_deactivate_tools(close_mpr=…)`
   defaults to *preserve*. Tool selection changes the tool, not the viewing mode.
   (`AIPACS_MPR_PRESERVE_ON_TOOL_SELECT=0` restores the old behaviour.)
2. **The callers that genuinely need the cell still close it, explicitly** —
   Curve MPR, Dental Curve MPR and the post-series-switch reset each pass
   `close_mpr=True`. Without this, two MPR pipelines would fight over one grid
   cell: the duplicate-pipeline class the re-entrancy guard exists to prevent.
3. **Text now works inside MPR.** `activate_caption()` — a text box with a leader
   line, placed on all three 2D panes — has existed in the MPR measurement tools
   since the refactor and nothing ever called it. Wiring it turns "closes MPR"
   into a working tool.
4. **Tools with no MPR implementation say so** instead of silently doing
   nothing. This matters: preserving MPR while ROI/Circle ROI/AI Chat/Two-Line
   Angle quietly ran on the hidden 2D widget underneath would be *worse* than
   the original bug, not better. They now tell the user to close MPR first.

Everything the owner listed — Arrow, annotation, rotation, measurement, eraser,
zoom, pan — already had an MPR implementation and now keeps MPR open.

---

## Verification

`tests/code/mpr + viewer + system + architecture + fast` → **2 939 passed**, 4
failed — the same four `test_local_search_progressive` pins carried since
2026-08-21. Baseline before this work was 2 919 passed with the same four.
**Regressions: 0.**

New guards: `tests/code/mpr/test_mpr_interaction_stability.py` (20).

One existing guard was re-pinned rather than worked around:
`test_mpr_flip_offthread_opt48.py::test_toolbar_passes_preflipped_to_the_viewer`
required the literal `self._prepare_mpr_flip_offthread(vtk_image_data)` and broke
when the call gained the `existing_dlg=` argument and wrapped onto two lines.
The assertion was still true — only the spelling had moved — so it now pins the
wiring rather than one line's formatting.

## Kill switches added

| flag | default | `=0` restores |
|---|---|---|
| `AIPACS_MPR_HOVER_STABLE` | on | every-frame cursor writes, no hysteresis |
| `AIPACS_MPR_ACTIVE_VIEW_NOOP_GUARD` | on | unconditional 4-container restyle |
| `AIPACS_MPR_PRESERVE_ON_TOOL_SELECT` | on | tool selection closes MPR |
| `AIPACS_MPR_OBLIQUE_VALIDATE` | off | (set to 1) per-frame oblique validation |

## What to watch for in the next field log

* `[MPR-TEARDOWN] … close_mpr=` — should now appear only with `close_mpr=True`,
  i.e. only for Curve MPR, Dental Curve MPR or a series switch. Any other
  occurrence is a tool still closing MPR.
* `[MPR-TOOL] … has no MPR implementation` — tells us which unsupported tools
  users actually reach for inside MPR, and therefore which are worth
  implementing next.
* `[MPR_DIAG]` lines should be absent unless diagnostics are explicitly enabled.
