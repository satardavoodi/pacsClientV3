# MPR / VTK lifecycle review and stabilization (2026-08-01)

**Scope requested:** review the whole MPR/VTK lifecycle — initialization, threading, memory
management, shutdown — with an emphasis on high-slice-count studies, and make these two
scenarios reliably stable:

- **A.** open a large study → open MPR → close MPR → use another viewer/tool
- **B.** open MPR → close → open → close → open another patient → another reconstruction

**Method:** audit against the requested checklist, then fix only what the audit actually found.
Three real defects were found and fixed; the rest of the checklist was already satisfied and is
recorded below as *verified*, so a future reader does not re-audit it.

---

## 1. Audit result — the scorecard

### 1.1 Initialization

| Item | Finding |
|---|---|
| Thread creation and ownership | ✅ Two QThreads, both created *and joined* inside the function that made them (`_load_vtk_paths_responsive`, `_prepare_mpr_flip_offthread`). Neither is stored on `self`, so **no MPR worker can outlive the open, let alone the close.** |
| Memory allocation before/during render | ✅ Volume built off-thread; scalar range warmed off-thread (OPT-48) |
| RAM/VRAM allocated at MPR open | ⚠️ **Two full volume copies** (source + X-flipped ≈ 375 MB each at 716 slices). Known, deliberately deferred — see §4 |
| VTK volume construction | ✅ Single canonical builder `StandardMPRViewer.build_lr_flipped_volume` |
| DICOM → VTK conversion | ✅ Off the GUI thread |
| Temporary buffers / duplicate arrays | ⚠️ One avoidable duplicate remains (§4); the OPT-47 triple-copy in `convert_itk2vtk` was already reduced to one |
| Renderer / render-window init | ✅ On the GUI thread, where it must be. Guarded by the OPT-21 OpenGL pre-flight |
| Qt/VTK object ownership | ✅ Panes are children of the MPR widget; the widget is swapped into the host cell and cross-linked for restore |
| Large-volume handling | ✅ OPT-47 GPU budget (`max(512 MB, bytes × 1.6)`), gradient-opacity and MSAA relaxation; OPT-48 on-demand VRT above 200 slices |

### 1.2 Threading

| Item | Finding |
|---|---|
| Background work is controlled | ✅ Both workers run behind an application-modal `QProgressDialog` + local `QEventLoop`, then `worker.wait()` |
| VTK ops on the correct thread | ✅ The worker touches only the data object — never a render window, widget or interactor. Pinned by `test_mpr_workers_do_not_touch_qt_or_vtk_widgets` |
| Worker never touches a destroyed Qt/VTK widget | ✅ By construction (previous row) **and** by the join |
| **No simultaneous MPR init** | ❌ **DEFECT 1 — no re-entrancy guard existed.** Fixed, §2.1 |
| **Repeated clicks can't duplicate workers** | ❌ Same defect. Fixed, §2.1 |
| Worker cancellation / completion | ✅ Completion-joined. Cancellation is intentionally not offered: the load must finish to build the viewer, so the dialogs are built with `setCancelButton(None)` |
| No worker active after close | ✅ Guaranteed by the join |

### 1.3 Memory management

| Item | Finding |
|---|---|
| Duplicate arrays / deep copies | ⚠️ One (§4) |
| Large temporary NumPy/VTK buffers | ✅ Released; OPT-47 cut `convert_itk2vtk` from three copies to one |
| Volume caches | ✅ Per-domain, opt-in, flag-gated |
| Render textures | ✅ `ReleaseGraphicsResources` **before** `Finalize()` (OPT-47) — ordering re-pinned by test |
| References preventing garbage collection | ❌ **DEFECT 3 — six containers and two cross-module references were never cleared.** Fixed, §2.3 |
| Memory growth across repeated open/close | ❌ Consequence of defect 3 — this is scenario **B**. Fixed |

### 1.4 Shutdown — the requested 10-step contract

| # | Step | Before | After |
|---|---|---|---|
| 1 | Stop accepting new MPR operations | ❌ nothing | ✅ `_mpr_closed = True` as the **first** statement of `cleanup()` |
| 2 | Cancel/await background work | ✅ already joined at open time | ✅ unchanged |
| 3 | Stop timers | ⚠️ partial — `_render_timer`, `_prewarm_timer`, auto-rotation | ✅ **+ `_interaction_timer`**, all disconnected and dropped |
| 4 | Remove observers / callbacks | ✅ `RemoveAllObservers`, `Disable` | ✅ + cross-module `_viewport_activate_cb` dropped |
| 5 | Detach mapper inputs | ✅ `SetInputData(None)` | ✅ unchanged |
| 6 | Remove props from renderers | ✅ `RemoveAllViewProps` | ✅ + actor dicts cleared |
| 7 | Release GPU resources | ✅ before `Finalize()` | ✅ unchanged |
| 8 | Finalize render windows | ✅ | ✅ unchanged |
| 9 | Break reference cycles | ⚠️ `viewers` only | ✅ + 6 containers + 2 cross-module refs |
| 10 | Release the volume | ✅ `image_data = None` | ✅ unchanged |

---

## 2. The three defects and their fixes

### 2.1 DEFECT 1 — `toggle_zeta_mpr` had no re-entrancy guard

A grep for any of `_mpr_opening | _mpr_busy | _mpr_in_progress | _zeta_mpr_building | reentr |
already_opening` in `toolbar_manager.py` returned **zero matches**.

Why it is reachable despite the modal dialogs:

- the dialogs are application-modal and block *mouse input*, but they **pump the event loop**
  (`loop.exec()`), so an already-queued activation can still be delivered;
- the open is reachable **programmatically** — the EchoMind command bus and the agent-control
  surface both call `toggle_zeta_mpr` directly, with no modal in front of them;
- the guarded window is long on exactly the studies that hurt: volume load, scalar-range warm,
  X-flip, then GUI-thread render-window creation.

A second entry would build a **second complete pipeline** — a second volume, a second worker
pair, a second set of render windows — while the first was still resident. On a 700-slice study
that is the difference between ~1.5 GB and ~3 GB, on top of a GPU budget sized for one volume.

**Fix.** A flag-gated guard (`AIPACS_MPR_LIFECYCLE_GUARD`, default on) placed **after** the
close branch and released in a `finally`:

- placed after the close branch so a stuck flag can never make MPR impossible to *close*
  (pinned by `test_reentrancy_guard_does_not_block_closing`);
- released in a `finally` so success, exception, and every early `return` inside the try all
  clear it — a stuck flag would kill the MPR button for the session, which is worse than the
  duplicate it prevents;
- the refusal logs `[MPR-LIFECYCLE] open ignored — an MPR open is already in progress`.

### 2.2 DEFECT 2 — deferred callbacks could reach VTK *during* teardown

`_request_render`, `_execute_pending_renders`, `_render_immediately` and
`_apply_interaction_update` were guarded only by `view_name in self.viewers`.

That check starts protecting only after `self.viewers.clear()` — which runs at the very **end**
of `cleanup()`. Between the first `ReleaseGraphicsResources` and that clear, a queued callback
still finds live dict entries and a render window whose graphics resources are already gone.
`_apply_interaction_update` wraps its body in `try/except`, but that catches nothing here: the
fault is **native, inside VTK**, and takes the process down with an access violation and no
Python traceback.

**Fix.** `cleanup()` sets `self._mpr_closed = True` as its first action — before any timer stop
and before any VTK call — and every deferred entry point begins with

```python
if self._mpr_is_closed():
    return
```

`_mpr_is_closed()` reads `getattr(self, "_mpr_closed", False)`, so a partially-constructed
viewer is never mistaken for a closed one; `__init__` also sets it to `False` explicitly.
`_flush_interaction_update` and `_finalize_interaction_update` are covered transitively — both
funnel into `_apply_interaction_update`.

### 2.3 DEFECT 3 — teardown released the GPU and the volume, but not the graph

OPT-47 (2026-07-29) fixed the *big* leaks. What it did not clear:

| Attribute | Assigned at | What it pins alive |
|---|---|---|
| `text_actors` | `widget.py:299` | a `vtkTextActor` per pane |
| `crosshair_actors` | `widget.py:298` | crosshair line actors per pane |
| `_view_containers` | `widget.py:323` | a `QWidget` per pane — **and a Qt widget keeps its whole parent chain alive** |
| `_vtk_widget_to_view` | `widget.py:325` | every `QVTKRenderWindowInteractor` |
| `_toolbar_styles` | `widget.py:367` | per-pane toolbar style state |
| `_render_pending` | `widget.py:362` | deferred-render bookkeeping |
| `_viewport_activate_cb` | `_mpr_layout.py:101` | a closure over the **ToolbarManager and the host cell** |
| `_diag` | `_mpr_views.py:313` | the diagnostic validator |
| `_interaction_timer` | `_mpr_orientation.py:263` | a **live QTimer** whose slot walks `self.viewers` and renders |

`self.viewers` was the only container cleared. So a "closed" MPR still held every pane widget —
and through `_viewport_activate_cb`, the patient tab's toolbar was still reachable from VTK-side
state. That is scenario **B**: repeated open → close → open grew host memory monotonically even
though each open's *volume* was correctly freed.

`_interaction_timer` is the sharpest of these: it is created lazily by
`_request_interaction_update` and fires `_apply_interaction_update`, which walks `self.viewers`
and renders. Left running through a close it is a stale callback into a finalized render window
— exactly the use-after-free class this teardown exists to prevent.

**Fix.** A new step 7 in `cleanup()`, inside the existing `AIPACS_MPR_FULL_TEARDOWN` kill
switch, that clears all six containers, drops both cross-module references, and stops **+
disconnects + drops** all three timers. Stopping alone is not enough: a stopped timer can be
restarted by a later `_request_render`, so the reference is nulled as well.

---

## 3. Geometry safety

The standing constraint is *no regression in geometry or radiological canonical standards*.
This work touches **only** teardown and guard code. Two tests enforce it mechanically:

- `test_lifecycle_work_changed_no_geometry_api` — the new teardown section must not contain
  `SetSpacing`, `SetOrigin`, `SetDirectionMatrix`, `SetFilteredAxis`,
  `SetResampleToScreenPixels`, `SetParallelScale`, `SetViewUp`, `SetFocalPoint`, `SetPosition`
  or `ResetCamera`.
- `test_closed_guards_added_no_geometry_calls` — the same for every guarded entry point,
  including a `ResetCamera` pin that also protects the 2026-08-01 scroll-jitter fix.

The X-flip, the direction-matrix adjustment, slice order, spacing, origin and the camera path
are untouched. Nothing in this change runs while the viewer is open and rendering.

---

## 4. Deliberately NOT changed

**The second full volume copy.** `StandardMPRViewer` keeps the flipped volume while the caller
still holds the source, so peak memory at open is ~2× the volume. Releasing the source after the
flip is **unsafe** — the caller may legitimately reuse it (the FAST viewer's shared volume is the
same object). Folding the flip into the direction matrix instead would remove the copy, but it
**changes the radiological convention contract**: the reslice mappers, cameras, crosshairs,
measurements and the on-screen L/R markers all assume the volume is *physically* flipped. That is
a geometry change dressed as an optimization, and it is explicitly out of scope here.

**Worker cancellation.** Both dialogs pass `setCancelButton(None)` on purpose: the volume must be
loaded for the viewer to exist at all, and a half-loaded volume is not a valid MPR input. The
re-entrancy guard removes the reason a user would want to cancel (an accidental second open).

---

## 5. Flags

| Flag | Default | `=0` restores |
|---|---|---|
| `AIPACS_MPR_LIFECYCLE_GUARD` | on | no re-entrancy guard (legacy) |
| `AIPACS_MPR_FULL_TEARDOWN` | on | legacy `Finalize()`-only teardown (already existed; the new step 7 is inside it) |

The `_mpr_closed` guard is unconditional: there is no valid use for "let a queued callback render
into a finalizing window", and the flag surface is already wide.

---

## 6. Verification

- New guard suite `tests/code/viewer/test_mpr_lifecycle_guard.py` — **34 tests** covering the
  re-entrancy guard (including that it does not block closing and is released in a `finally`),
  the closed-guard on all five deferred entry points and its behaviour when executed against a
  recorder, the teardown ordering and completeness, the OPT-47 regression pins, the worker join,
  and the two geometry-safety pins.
- `tests/code/viewer` + `tests/code/system`: **2331 passed, 0 new failures.**
- Two pre-existing tests were repaired rather than weakened: `test_mpr_interaction_perf`'s stub
  recorder gained `_mpr_is_closed` (it execs the real function), and
  `test_mpr_defer_3d_view::test_cleanup_clears_pending_flag` had its 600-character source window
  widened to 3000 — its assertion is unchanged and it now *also* pins that the flag is still
  cleared before the first VTK release.
- 4 failures remain in `tests/code/system/test_local_search_progressive.py`. **Confirmed
  pre-existing** by stashing all four source edits and re-running on clean HEAD — unrelated to
  MPR.
- `verify_plugin_mirrors.py`: **420/420**. None of the four touched files is plugin-mirrored.

## 7. Live verification still required

1. **Scenario A** — open a ~700-slice study, open MPR, close it, then use another viewer/tool.
2. **Scenario B** — open/close MPR twice, then open another patient and another reconstruction.
   Watch RSS across the cycles: it should return to roughly its pre-MPR level each time, instead
   of stepping up.
3. Double-click the MPR button rapidly — the second click must log
   `[MPR-LIFECYCLE] open ignored` and **not** start a second load.
4. Close MPR *while* the volume is still loading, and close a patient tab with MPR open — neither
   may produce an `already deleted` `RuntimeError` or a `native_fault.log` access violation
   carrying VTK frames.
