# MPR teardown only ran from one button

**Date:** 2026-08-19
**Trigger:** owner, after a reading session —
> "check the log for mpr 54921. And also, I MPR multiple times the different
> series; see if the cash free successfully"

**Status:** Fixed. 28 guards in `tests/code/mpr/test_mpr_lifecycle_release.py`;
12 verified to FAIL on the pre-fix codebase.

---

## 1. What the log said about 54921

CT chest, study `…1787123824391.87348`, pid 340640, 17:45–17:50. Three MPR
activations on three different series:

| # | Time | Series | Volume | Construct | Instrumented total |
|---|---|---|---|---|---|
| 1 | 17:45:21 | 202 | 512×512×165 | 1,094 ms | 2,701 ms |
| 2 | 17:49:28 | 1000201 (prior) | 512×512×60 | 896 ms | 1,981 ms |
| 3 | 17:50:14 | 1000202 (prior) | 512×512×180 | 1,155 ms | 2,430 ms |

Worst single main-thread stall **1.5 s** — against the 8.7 s freeze on 54675
two days earlier. No errors, no fallbacks, every launch `route_ready
reason=loaded_full_volume`. The `[MPR-STEP]` instrumentation added on 08-18
did its job: `3d.interactor_initialize` (403–1,185 ms) and `all.setup_ui`
(~790 ms, very stable) are the two dominant steps, and 3D varies 2.4× across
similar volumes — cold vs warm GPU, not volume size.

**The toggle-off path frees correctly.** Both closes ran the full teardown:

```
17:49:05 CLOSE → 17:49:06 cleanup() completed   (~1 s)
17:50:11 CLOSE → 17:50:11 cleanup() completed   (<1 s)
```

The third viewer was simply still open at the end of the session. That is not
a leak.

### A methodology note worth keeping

The first pass at this analysis read only `viewer_diagnostics.log*` and
reported **"0 of 3 activations freed — nothing was released."** That was
wrong and alarming. The MPR *timings* go to `viewer_diagnostics.log`, but the
close path (`toolbar_manager._restore_selected_viewer`) logs to **`app.log`**.
Any future audit of this question must read both; the analysis script now
does, and says so at the top.

## 2. The real finding

`cleanup()` is excellent — it releases GPU resources, finalizes the render
windows, drops the flipped host volume and breaks the interactor-style
reference cycles. But it was reachable from **exactly one place**: the
toolbar's MPR toggle.

Ledger across every logged process (MPR "init started" vs "cleanup()
completed"):

| pid | opened | freed |
|---|---|---|
| 239928 | 4 | 2 |
| 340640 | 4 | 2 |
| 292260 | 2 | 1 |
| 42008 | 2 | 1 |
| 243232 | 1 | 0 |
| 335360 | 1 | 0 |
| **total** | **14** | **6** |

And the smoking gun, all inside pid 340640:

```
12:57:02  MPR opened   (never toggled off)
15:35:03  close_patient
17:45:19  toggle scan → active_mpr_widget: None   ← the widget is gone
          …no cleanup() logged anywhere in between
```

That activation's flipped host volume, four render windows and GPU texture
were orphaned, not released. The process was sitting at **1,931 MB RSS** when
measured.

### Why a `closeEvent` alone would NOT have fixed it

The obvious fix — hook `cleanup()` to `closeEvent` — does not work, and it is
worth writing down why. **Qt does not call `closeEvent` when a parent is
destroyed, nor when a widget is merely re-parented away.** All three leaking
paths are exactly those cases:

| path | how the widget died | `closeEvent`? |
|---|---|---|
| toolbar toggle OFF | explicit, via `_restore_selected_viewer` | n/a — already correct |
| patient tab closed | `_pw_lifecycle` cleans the HOST and nulls `node.vtk_widget` | no |
| layout / viewport change | `delete_widgets_in_layout` → `setParent(None)` | no |
| app exit | parent chain torn down | no |

So the fix has two halves, and the second is the load-bearing one.

## 3. What changed

### 3.1 New `_mpr_lifecycle.py` — one shared helper

`release_mpr_children(widget, reason)` finds any MPR viewer reachable from a
host widget and runs its teardown. Duck-typed on the teardown contract
(`cleanup` + `_mpr_closed`) rather than on the class, so it is importable from
`PacsClient.pacs.patient_tab.utils` with no import cycle, and a future MPR
flavour is picked up for free. It never raises — it runs on close paths where
an exception would strand the caller mid-teardown — and it skips
already-closed viewers so the log's release count stays honest.

Deliberately not a `findChildren` sweep: the hosts always publish the viewer
under one of four known attribute names, and walking every descendant of an
arbitrary widget during a layout teardown would be slower and happy to pick up
look-alikes.

### 3.2 The owners release BEFORE they orphan

* `utils.delete_widgets_in_layout` / `delete_layout` — release, then
  `setParent(None)`.
* `_pw_lifecycle` patient-close node loop — release the MPR child, then tear
  down the host.

**Order is the whole point.** Once the widget is orphaned the GL context is
gone and `ReleaseGraphicsResources()` cannot free the VRAM any more. Two
guards assert the ordering, not just the presence of the call.

### 3.3 `closeEvent` on `_MprLayoutMixin`

Covers the explicit-close case. `cleanup()` is idempotent, so a close after a
toolbar toggle is a cheap no-op rather than a double teardown.

### 3.4 The 3D mapper stopped pinning the previous volume

`_reload_with_series` (in-MPR series switch) rebound the axial/sagittal/coronal
mappers but never re-pointed the 3D `vtkGPUVolumeRayCastMapper`. Every in-MPR
switch therefore pinned one full host volume (~30–95 MB for the series seen
here) plus its GPU texture for as long as the viewer stayed open.

It was also a **reading hazard, not only a memory one**: the 3D pane kept
rendering the *old* series next to three panes showing the new one.

### 3.5 Memory is now in the log

`[MPR-MEM]` at open (`_setup_ui`), at both ends of `cleanup()`, and around
each `release_mpr_children` call, with a `freed_mb` delta. Answering "did the
cache free?" this time took a four-log reconstruction; next time it is one
grep. Deliberately unthrottled, unlike `_emit_viewer_resource_probe` — an MPR
open/close happens a handful of times per session, and throttling is exactly
what would ruin the before/after pair.

Kill switches: `AIPACS_MPR_RELEASE_ON_DESTROY=0`, `AIPACS_MPR_MEM_PROBE=0`.

## 4. A test that cried wolf for the third time

`test_mpr_defer_3d_view.py::test_cleanup_clears_pending_flag` failed on the
first regression run. Its assertion was still perfectly true — it bounds its
search window at a **fixed character count** from `def cleanup(`, and the new
memory probe pushed `_full_teardown` past 3,000 characters, so
`body.index(...)` raised `ValueError`.

That window had already been widened 600 → 3,000 on 2026-08-01 for the same
reason, and I re-bounded a *sibling* test in this same file at the next `def`
on 2026-08-18 for the same reason. It is now bounded at the next `def` too.
The assertion is untouched.

I also moved the memory probe to sit *after* the two stop-accepting flags in
`cleanup()` — those are safety-critical and must be the first thing that
happens; diagnostics must never be able to delay them.

## 5. Deliberately NOT changed

* **`cleanup()` itself** — it was already right. This is entirely about
  *reaching* it.
* **No `gc.collect()`.** The interactor-style ↔ viewer reference cycle
  survives `cleanup()` (`crosshair_styles` still holds every style), so the
  Python objects wait for a generational collection. This codebase
  deliberately avoids stop-the-world collections on the GUI thread; the large
  buffers (volume, VRAM) are released explicitly regardless, which is what
  actually matters. Noted in §7.
* **App exit** — not wired. The process is about to die and the driver
  reclaims VRAM; adding a shutdown hook is scope the evidence does not
  justify.
* **`modules/mpr/orthogonal/`** — has its own `cleanup()`/`closeEvent()` but
  is dead code (its only entry point, `_show_orthogonal_mpr_viewer`, has zero
  callers). Left alone.

## 6. Verification

```
tests/code/mpr/test_mpr_lifecycle_release.py         28 passed
tests/code/mpr + viewer + ui_services              3091 passed, 54 xfailed
```

The 2 failures in that run — `test_login_carries_the_user_identity_ids` and
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute` — are
pre-existing and unrelated: both are source-string pins on the login/JWT path
and the patient-list status renderer, neither of which this work touches.
Confirmed by running them in isolation.

**Pre-fix proof** — `tools/analysis/oneoff/verify_mpr_lifecycle_guard_fails_prefix.py`
reconstructs HEAD with `git show` (the working tree is never touched — it
carries unrelated in-flight EchoMind work) and confirms **12 guards fail
pre-fix**: the helper module absent, no `closeEvent`, no memory probe in
`cleanup()` or `_setup_ui`, neither owner releasing, and `_reload_with_series`
never mentioning the 3D view.

The load-bearing guards:

* `test_layout_teardown_releases_before_orphaning` and
  `test_patient_close_releases_the_mpr_child` — these pin the two paths that
  actually leaked, **including the ordering**. If someone "simplifies" the fix
  down to just the `closeEvent`, the closeEvent tests stay green and these
  two catch it.
* `test_series_switch_actually_repoints_the_3d_mapper` — behavioural, on real
  VTK objects, asserting the mapper's input dimensions actually changed.
* `test_an_already_closed_viewer_is_not_torn_down_twice` and
  `test_a_deleted_cpp_object_never_raises` — teardown races are normal here.

## 7. Open / worth knowing

* **The reference cycle is still there.** `cleanup()` clears `viewers` but
  `self.crosshair_styles` still holds every interactor style, and each style
  holds `self.parent = mpr_viewer`. The Python wrapper objects therefore wait
  for a generational GC. The volume and VRAM are freed explicitly, so this is
  a small, bounded cost — but clearing `crosshair_styles` in `cleanup()` would
  close it properly and is a one-line follow-up.
* **`measurement_tools`, `segmentation_results`, `preset_manager` and
  `curved_mpr_generator` are never cleared** by `cleanup()`.
  `segmentation_results` holds full-volume masks, so it is the one worth
  looking at next.
* **The `[MPR-MEM]` deltas will be noisy.** RSS is process-wide and the
  allocator does not necessarily return freed pages to the OS immediately; a
  small or even negative `freed_mb` on one close does not by itself mean the
  teardown failed. Read the trend across several open/close cycles, not one.
* **This has not been observed live yet.** The app must be restarted to pick
  the change up; the next session's log will carry `[MPR-MEM]` lines that
  either confirm the release or give the first real numbers to argue with.
