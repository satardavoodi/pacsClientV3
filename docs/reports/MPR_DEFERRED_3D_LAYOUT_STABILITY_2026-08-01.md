> **FOLLOW-UP, same day — the real one was found.** After this investigation the report was
> clarified: with **two viewports** open, starting MPR made the **other** viewport expand to nearly
> the whole screen during the load. That is a *different grid* — the **patient viewport grid**, not
> the MPR's internal 2×2 — and it was a real, unambiguous bug:
> `toggle_zeta_mpr` called `selected_widget.setVisible(False)` ~150 lines (and several seconds)
> before the MPR widget was inserted, so the host cell was empty for the whole build and its lone
> visible sibling took the entire grid. **See §8.** Everything below about the MPR's own 2×2 grid
> remains correct and is why that measurement did not find this: three of its four panes stay
> present and still span both rows and columns, so emptying one changes nothing — whereas emptying
> one of *two* cells hands everything to the other.

# "The MPR layout breaks while the on-demand 3D/VRT loads" (2026-08-01)

**Report:** on a large series the 3D/VRT is not auto-built. Clicking the 3D cell makes the MPR
temporarily collapse, shift left and change its panel proportions until the 3D finishes loading,
then recover.

**Headline: the layout is not reflowing. It is a frozen window.** The 2×2 grid was measured and
does not move — the panes are repainted stale while the GUI thread is blocked for ~9 s by the VTK
build, which cannot be moved off the GUI thread. What shipped is therefore presentation work plus
an honest record of the disproved hypothesis, not a layout fix.

---

## 1. The current thresholds (as asked)

| Setting | Default | Meaning |
|---|---|---|
| `AIPACS_MPR_VRT_ON_DEMAND` | on | large volumes do not auto-build the 3D/VRT |
| `AIPACS_MPR_VRT_ON_DEMAND_SLICES` | **200** | at or above this Z-dimension, 3D is on demand |

It is **200 slices**, not 300–400, and it is a **slice count** — there is no size-in-MB threshold.
Below 200 the L1 behaviour is unchanged (auto-build on idle). Unchanged by this work.

## 2. The hypothesis — and why it is wrong

The obvious explanation, and the one I pursued first:

- `views_layout` is created with only `setContentsMargins` + `setSpacing`. A grep for
  `setRowStretch` / `setColumnStretch` across `modules/mpr/zeta_mpr/mpr_viewer/` returns
  **nothing** — the grid has no stretch factors at all.
- `_build_deferred_3d_view` **removed the placeholder first**, and `_create_3d_view` adds its
  container to the grid as its **very last statement** (line 938) — after the
  `QVTKRenderWindowInteractor` ctor, `winId()`, the GPU ray-cast mapper and
  `Initialize()`/`Start()`. So cell (0,1) really was empty for the entire multi-second build.

That is a genuine-looking mechanism, and it is measurably not the cause.

A real `QGridLayout` was driven with the MPR's structure — three `QFrame` panes plus a placeholder,
at host sizes **1400×900, 900×650, 700×500 and 520×420**, with and without the panes' 400×400
`QVTKRenderWindowInteractor` size hints. Removing the 3D widget moved the other three panes by
**exactly 0 px in all eight combinations**, and adding the real container afterwards also moved
them by 0 px.

The reason is simple in hindsight: all four panes are `Expanding`, so `QGridLayout` divides the
available space evenly regardless of which cells are occupied or what their size hints are.

**A stretch pin was written, measured to be a no-op, and removed.** The removal is documented in
`_mpr_views.py` at the point where it would go, and
`test_no_stretch_pin_was_added_and_the_reason_is_recorded` fails if one is re-added, so the same
dead end is not re-explored.

## 3. What is actually happening

`_create_3d_view` is one synchronous call on the GUI thread, measured at **~9 s** on a 672-slice CT
(OPT-48, `docs/reports/MPR_SLOW_HIGH_SLICE_COUNT_52827_2026-08-01.md`):

```
QVTKRenderWindowInteractor(container) -> winId() -> vtkGPUVolumeRayCastMapper
  -> SetInputData(full volume) -> Initialize() -> Start() -> Render()
```

VTK's GL context creation is GUI-thread-only, so none of this can be moved to a worker.

Windows substitutes a **DWM ghost window** for an application that stops pumping for roughly five
seconds. The ghost is a stale bitmap the compositor will happily stretch and offset — which is
exactly what "minimize/collapse, shift left, panel sizes change, then recover" describes, including
the fact that it fully reverts the instant the app becomes responsive again. A layout defect would
persist until something forced a relayout; this does not.

**One observation would confirm it:** during the load, does the window title bar grey out or does
Windows say *"Not Responding"*? If yes, this is settled. If the layout is genuinely distorted while
the app is still *responsive*, the hypothesis is wrong and I want to know.

## 4. What shipped

All presentation, all default-on, all with kill switches. None of it makes the build faster.

| Change | Why |
|---|---|
| **Build first, swap after** (`_build_deferred_3d_view`) | The placeholder now holds cell (0,1) for the whole build, so the 3D viewport shows its own "Rendering 3D…" state instead of going black and empty. The swap is repaint-suppressed and the layout is `activate()`d while painting is off — the project's proven bracket; `updateGeometry()` alone only *posts* a layout request, so a repaint can land before the layout runs. |
| **Defer the build off the click handler** | It used to call the multi-second builder inline from `mousePressEvent`, so the "Rendering 3D…" label could not paint and the user's only feedback was a frozen window. Now `QTimer.singleShot(0, …)`. |
| **Refuse a second click while building** | A second activation during the freeze would start a duplicate 3D pipeline. |
| **Modal busy dialog painted before the freeze** | Gives the wait an explicit owner instead of a ghosted workstation, and absorbs stray clicks. Same treatment — and the same limitation — as the MPR open itself (OPT-48 #5). `setCancelButton(None)`: the VTK build cannot be interrupted. |

Flags: `AIPACS_MPR_DEFERRED_3D_STABLE_SWAP`, `AIPACS_MPR_DEFERRED_3D_PROGRESS` (both default on).

**One robustness bug was introduced and caught by the existing tests:** resolving the host widget
and suppressing repaints initially sat inside the outer `try`, so a failure there skipped
`_create_3d_view` entirely — presentation code preventing the actual build. It now has its own
guard.

## 5. Geometry safety

Unchanged, and enforced mechanically: `test_layout_stability_work_touched_no_geometry_api` forbids
`SetSpacing`, `SetOrigin`, `SetDirectionMatrix`, `SetFilteredAxis`, `SetResampleToScreenPixels`,
`SetParallelScale`, `SetViewUp`, `SetFocalPoint` and `ResetCamera` in every function this work
touched. Widget rectangles are not image geometry.

## 6. If the freeze itself must go

Not done here, because each option has a real cost and none is a pure win:

1. **Fewer initial renders.** `_create_3d_view` renders three times during setup. Cutting to one
   would save a meaningful share of the 9 s — but needs checking that the VRT still shows correctly
   on first paint.
2. **Coarser first render.** Raise the initial sample distance and refine after the pane is up.
   Changes what the user first sees; a quality decision, not an engineering one.
3. **Down-sample the VRT input above ~400 slices.** 3D only — the 2D reslice panes stay full
   resolution. This is the single biggest lever and is already listed as OPT-48 #6.

## 7. Verification

- New `tests/code/viewer/test_mpr_deferred_3d_layout_stability.py` (**23**), including the
  parametrised disproof, the build-then-swap ordering, a pin that `_create_3d_view` still adds its
  container last (the premise of that ordering), the repaint bracket, the `finally` guarantees, and
  the click-handler behaviour.
- `tests/code/viewer` + `tests/code/system` = **2459 passed**; the 4 remaining
  `test_local_search_progressive` failures were confirmed pre-existing earlier today.
- Two existing tests updated rather than weakened: `test_placeholder_is_clickable_when_on_demand`
  now expects the deferred dispatch (invariant unchanged, mechanism moved), and
  `test_deferred_callback_is_teardown_safe`'s fixed 1600-character source window was replaced with
  a window bounded at the next `def` — a positional slice silently rots as a function grows.

---

## 8. THE ACTUAL BUG — the patient viewport grid (found on re-report)

The clarified symptom was decisive: *with two viewports, the **non-MPR** one briefly takes over
almost the whole screen.* That is the **patient viewport grid**, and the defect is plain:

```python
selected_widget.setVisible(False)        # toolbar_manager.py ~5514   <-- cell emptied HERE
    ... resolve series, load the volume, off-thread X-flip,
        StandardMPRViewer(...)   =   SECONDS on a large study ...
parent_layout.addWidget(zeta_widget, row, col, rowSpan, colSpan)   # ~150 lines later
```

A `QGridLayout` gives a hidden widget **zero space** (nothing here calls
`setRetainSizeWhenHidden`). With two viewports, hiding one leaves its sibling as the only visible
item in the grid — and a lone visible widget takes the entire area. It reverts the instant the MPR
widget lands, exactly as reported.

**Why the earlier measurement missed it:** it tested the MPR's *internal* 2×2, where three panes
remain and still span both rows and both columns, so removing one changes nothing. Both
measurements are correct — they are different layouts, with different numbers of siblings.

**The fix — the same shape at all three sites** (`toggle_zeta_mpr`,
`_launch_dental_curve_vtk_host`, `toggle_new_curve_mpr`, all of which construct a
`StandardMPRViewer` between the hide and the insert):

1. the host stays **visible and occupied** for the whole build — it keeps showing its current image,
   so no sibling can gain space;
2. hide + insert happen in **one repaint-suppressed step**, with `parent_layout.activate()` called
   while painting is still off (`updateGeometry()` only *posts* a layout request, so the re-enabled
   repaint can beat the layout — the sidebar lesson);
3. re-enable in a `finally`, so a failed build can never leave the workstation unpainted.

One shared kill switch: `AIPACS_MPR_STABLE_VIEWPORT_SWAP=0` restores the legacy early hide.

**Guard:** `tests/code/viewer/test_mpr_viewport_swap_stability.py` (22). Its first test *reproduces
the bug* on a real two-cell grid — hiding one cell grows the sibling past 1.8× — and the second
pins the fix's guarantee: while the host stays visible the layout is bit-identical. It deliberately
does **not** assert the pixel-exact outcome of the final swap; a synthetic stand-in models the real
widget's parenting and show semantics badly enough that such an assertion would be misleading
rather than protective, and the swap is a single repaint-suppressed pass so nothing transient is
painted.

`tests/code/viewer` + `tests/code/system` = **2481 passed**, only the 4 known pre-existing
`test_local_search_progressive` failures. The 6 `test_field_icon_chip` /
`test_status_report_sorting` failures seen in a combined run were confirmed pre-existing by
stashing both source files and re-running on clean HEAD.
