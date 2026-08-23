# MPR geometry — what the repo already knows, read before changing anything

**2026-08-23.** Written because A1 in
`docs/reports/ENDUSER_SANAM_STABILITY_REVIEW_2026-08-23.md` recommended a change
to the oblique camera path. Before writing that change I read the existing
documentation. **The recommendation was wrong and must not be implemented.**

---

## STOP — do not implement the A1 recommendation

The stability review said:

> *"In the oblique-rotation handler, after the reslice axes are set, re-set
> `camera.SetFocalPoint(crosshair_world_centre)` and recompute `ParallelScale`
> from the new plane extent, for every non-primary view."*

**That is precisely what v1.09 did, and it was deliberately reverted by
v1.09.Fix-E.** From `_mpr_oblique.py::_set_oblique_camera` (lines 232–252):

> *"**v1.09.Fix-E — camera-stable oblique slicing:** Instead of repositioning the
> camera (which shifts the viewport centre and makes the displayed image appear
> to move), we switch the vtkImageResliceMapper from camera-driven slicing to an
> explicit vtkPlane. **The camera stays in its original orthogonal position, so
> the viewport is perfectly stable.**"*

and from `standard_mpr_viewer_original.py` (L3577):

> *"`── v1.09.Fix-E:` **always use orthogonal-style through-plane tracking for the
> camera (in BOTH orthogonal and oblique modes). This keeps the viewport centre
> stable.**"*

Implementing the recommendation would have re-introduced the image-pans-under-
your-cursor-while-rotating defect that Fix-E removed, and broken at least six
guard tests. **The paper trail for this is thin — the reversal exists only in
source comments, in no report, with no test asserting it.** That is why it was
nearly walked into.

---

## What the code actually does in oblique mode (verified in source, not inferred)

`_mpr_oblique.py::_set_oblique_camera` (L281–297):

```python
mapper.SliceFacesCameraOff()      # <- camera no longer selects the plane
mapper.SliceAtFocalPointOff()     # <- focal point no longer positions it
plane = mapper.GetSlicePlane()
plane.SetOrigin(self.current_position)   # <- THE CROSSHAIR CENTRE
plane.SetNormal(oblique_normal.tolist())
mapper.SetSlicePlane(plane)
mapper.Modified()
# Camera stays UNTOUCHED — no viewport shift.
renderer.ResetCameraClippingRange()
```

`_mpr_crosshair_state.py::_update_slice_positions` (L84–102): the camera moves
**only along the pane's through-plane axis** (`look_axis` from `_view_axes`),
carrying focal and position together so direction and distance are preserved;
then, when oblique is active, `plane.SetOrigin(self.current_position)` — **all
three components.**

**Therefore, in oblique mode the displayed slice plane passes exactly through
the crosshair centre, by construction.** `plane.origin IS current_position`. The
containment error of the *displayed* plane is identically zero.

---

## So why 1 147 `[MPR_DIAG] FAILED` lines?

**Because the validator measures the camera, and since Fix-E the camera no
longer defines the displayed plane.**

`mpr_diagnostic_validator.py::validate_after_oblique` (L661–668) builds its
snapshots from `renderer.GetActiveCamera()` and then calls:

* `check_focal_at_crosshair(snap, crosshair_center)` → `|camera.focal − crosshair|`
* `check_plane_containment(snap, crosshair_center)` → `dot(crosshair − camera.focal, camera.direction)`

Neither expression mentions `mapper.GetSlicePlane()`. The validator header says
**`Version: 2026-02-17`** — it encodes the *pre-Fix-E* design, in which the
camera was repositioned along the oblique normal, and it was never updated when
the mechanism changed.

Every failure count in the review is explained by this, and the explanations are
different for each check:

| check | n | what it actually measured | verdict |
|---|---:|---|---|
| `focal_at_crosshair` | 1 046 | in-plane distance between camera focal and crosshair | **By design.** Fix-E keeps the camera put; only the through-plane component tracks. A large in-plane value is the feature working. |
| `plane_containment` | 28 | `dot(crosshair − camera.focal, camera.direction)` | **Camera-only staleness.** For `kind='rotate'`, `_apply_interaction_update` runs `["crosshairs", "oblique"]` — it **skips `_update_slice_positions`** — so the camera focal's look-axis component can be one frame stale when the validator samples it. The *displayed* plane is still exactly on the crosshair. |
| `parallel_scale` | 101 | current vs the validator's stored baseline | **Stale baseline.** `_diag.capture_baseline()` runs only at view creation (`_mpr_views.py:376`) and after `_reset_all_to_orthogonal` (`_mpr_oblique.py:425`). A user zoom or a pane enlarge is never re-baselined, so the delta is the user's own zoom. Nothing in the oblique path writes `ParallelScale` at all. |
| passes | 0 | — | **Expected.** Violations log at WARNING always; passes log only under `ZETA_MPR_DIAG=1` (`mpr_diagnostic_validator.py` L48–54). |

**Conclusion: A1 is a diagnostics defect, not a clinical one.** No image is
showing the wrong plane. The correct fix is to the validator.

This also retires the last piece of the earlier framing: the review already
established (by exposure counts) that A1 was not a 3.6.x regression; it is now
established that it is not a geometry defect either.

---

## The constraints any future MPR geometry change must respect

Collected from `docs/pipelines/mpr-geometry-pipeline.md` (the governing doc —
"*Read this before touching any MPR geometry, the canonicalization pre-filter,
the camera/view-up logic, or the orientation markers*"), the archived
investigations, and the 2026-08 stability reports.

### Coordinate + orientation contract

1. **Patient space is DICOM LPS.** `+X` Left, `+Y` Posterior, `+Z` Superior.
2. **Z-spacing is ALWAYS IPP-derived**, never from `SliceThickness` /
   `SpacingBetweenSlices`. Required inputs: IOP + IPP + PixelSpacing only.
3. **`ZetaAnatA` is the world→patient authority** —
   `A = [−IOP_row, −IOP_col, slice_axis_lps]`, where `slice_axis_lps` is the
   *stacking* direction, not the bare IOP normal. The field-data
   `DirectionMatrix` is **wrong on the Z axis** and must not be used for it.
4. **Cameras take only the SIGN of each axis from `A`** and stay snapped to
   volume grid axes. Reverting to exact patient axes reintroduces the oblique
   tilt. Never hardcode signs.
5. **Plane-aware routing**: `look_k = argmax_k |A[:,k] · plane_normal|`. Do not
   restore the fixed `_ANAT_AXES` table.
6. **`_view_axes(view)` is the single source of truth** for `(look, h, v)`. ALL
   crosshair geometry must route through it — `_update_slice_positions`,
   `_calculate_crosshair_endpoints`, the drag mapping, and the oblique sample
   points. Hardcoding axial-native axes once made a sagittal-native series go
   **black** on crosshair move.
7. **The volume is PHYSICALLY X-flipped** (`vtkImageFlip` axis 0) and every
   downstream consumer assumes it — mappers, cameras, crosshairs, measurements,
   the on-screen L/R. **Folding the flip into the direction matrix or camera is
   a geometry change dressed as an optimisation.** Rejected twice.
8. **Never resample in `canonicalize_volume`** — orientation only. Resampling
   re-cut oblique acquisitions onto an axial grid and distorted the native
   plane. The resample block is retained but deliberately unreachable.
9. **Do not "correct the transpose"** in `_get_camera_vectors_for_view` in
   isolation — §6 was calibrated against the current consumption.
10. **All correction sites must agree**: `_mpr_views` ×3 create,
    `_mpr_rendering._reset_rendering`, `_mpr_series._reload_with_series`,
    `_mpr_oblique`. Changing one makes reset/scroll/reload diverge from the
    initial render.

### Interaction + render path

11. **The camera selects the slice** in orthogonal mode (`SliceFacesCameraOn` +
    `SliceAtFocalPointOn`). Any stray camera write changes which slice is shown.
12. **Scroll may change only the through-plane coordinate.** `stable_scroll_camera_step`
    moves the focal by exactly `step × unit(dir)` and carries the position
    rigidly; camera direction **and distance** are invariant; 200 notches leave
    in-plane coordinates bit-identical. Pinned by tests.
13. **No `ResetCamera` on any interaction path.** Pinned in two separate files.
14. **Renders go through `_request_render`** (5 ms coalescing batch), never
    `_render_immediately`. Interaction updates are throttled at
    `AIPACS_ZETA_MPR_INTERACT_MS` (default 16 ms) with `move ⊃ scroll ⊃ rotate`
    coalescing. An extra render per mouse-move is the real performance
    regression; an extra camera *write* is cheap but semantically dangerous.
15. **Cost scales hard with slice count** — the same VTK steps measured 101 ms
    on a small MR and **1 176 ms** on a 512×512×272 CT.

### Lifecycle

16. **Render windows, GL contexts and interactors are GUI-thread-only.** Workers
    may touch the data object only.
17. **`cleanup()` sets `_mpr_closed = True` as its first statement**; every
    deferred entry point begins with `if self._mpr_is_closed(): return`. A
    Python `try/except` cannot save you — the fault is a native access
    violation.
18. **`ReleaseGraphicsResources()` before `Finalize()`; release before
    orphaning.** After `setParent(None)` the GL context is gone and VRAM cannot
    be freed.
19. **Any new timer must be stopped AND disconnected AND nulled** in cleanup.
20. **On Windows-on-ARM the safe/dangerous choice is inverted** — bundled
    software GL (Mesa llvmpipe) crashes with `0xc000001d` under Prism;
    hardware GL works. The Qt GL pre-flight probe **passed while VTK crashed
    deeper** — a probe pass is not proof.

### Kill switches governing this area

`AIPACS_MPR_LIFECYCLE_GUARD`, `AIPACS_MPR_FULL_TEARDOWN`,
`AIPACS_MPR_RELEASE_ON_DESTROY`, `AIPACS_MPR_MEM_PROBE`,
`AIPACS_MPR_OPENGL_PREFLIGHT`, `AIPACS_MPR_VRT_GPU_BUDGET`,
`AIPACS_MPR_DEFER_3D`, `AIPACS_MPR_VRT_ON_DEMAND(_SLICES)`,
`AIPACS_MPR_DEFERRED_3D_STABLE_SWAP`, `AIPACS_MPR_STABLE_VIEWPORT_SWAP`,
`AIPACS_MPR_FLIP_OFFTHREAD(_SLICES)`, `AIPACS_MPR_PREWARM`,
`AIPACS_ZETA_MPR_INTERACT_MS`, `AIPACS_ZETA_MPR_PERF(_MS)`,
`AIPACS_MPR_STEP_TRACE`, `AIPACS_ZETA_MPR_AUTOROTATE` (default **off**),
`ZETA_MPR_DIAG(_VERBOSE)`.

---

## The test landmines — read before editing any MPR source file

Several guard tests slice the source at a **fixed character count** from a
`def`. Adding lines pushes an assertion out of the window and the test fails for
a bogus reason. **This repo has been bitten by this at least four times**, once
reading as "the coronal view stopped being built". The surviving fixed windows
in MPR-adjacent tests:

| file | test | window | sliced from |
|---|---|---:|---|
| `test_mpr_defer_3d_view.py` | `test_post_passes_are_2d_only` | **600** | `_capture_baseline_camera_state` ⚠️ the oblique baseline function |
| `test_mpr_defer_3d_view.py` | `test_post_passes_are_2d_only` | 400 | `_apply_window_level` |
| `test_mpr_defer_3d_view.py` | `test_flag_default_on` | 200 | `_MPR_DEFER_3D =` |
| `test_mpr_scroll_stability.py` | `test_wheel_handlers_use_the_invariant…` | **2200** ×2 | the two wheel handlers ⚠️ holds the only `SetParallelScale`/`SetViewUp` assertions |
| `test_mpr_scroll_stability.py` | `test_no_reset_camera_in_the_scroll_path` | **2600** ×2 | same — a NEGATIVE assertion, so growth silently *weakens* it instead of failing |
| `test_mpr_crosshair_off_left_stacks.py` | `test_left_press_routes_to_stack…` | 220 | `not self._crosshair_grab_active()` |
| `test_mpr_slice_bound_annotations.py` | `test_synchronize_oblique_views_calls_refresh` | 1500 | `_synchronize_oblique_views` |
| `test_mpr_arrows_and_sync_comment.py` | arrow guard | 1200 → 200 | `on_left_button_press` |
| `test_mpr_click_activates_cell.py` | cell activation | 3000 | `eventFilter` |
| `test_mpr_arrow_preview_smooth.py` | arrow preview | 1600 | `_activate_arrow_on_view` |
| `test_mpr_annotation_persist.py` | auto-exit | 2200 | `_do_single_use_auto_exit` |

Also brittle: `test_mpr_scroll_stability.py` asserts
`src.count("stable_scroll_camera_step(") == 3` **exactly**.

**Convert the relevant window to next-`def` bounding BEFORE editing the file it
slices, not after the test goes red.**

### Tests that would have broken on the A1 recommendation

* `test_mpr_interaction_perf.py::test_scroll_kind_matches_wheel_sync_and_skips_slice_positions`
  — asserts `rec.calls == ["crosshairs", "oblique", "text"]` exactly, and its
  docstring states the current behaviour verbatim: *"kind='scroll' must … NOT
  move the slice cameras."*
* `test_mpr_interaction_perf.py::test_move_and_rotate_kinds_unchanged` — two more
  exact call lists.
* `test_mpr_scroll_stability.py` — four camera-invariant assertions.
* `test_mpr_geometry_regression.py` — requires `_view_axes`, `_anat_look_axis`,
  `_anatomical_camera` to survive **by name**, in lockstep with the release PYZ
  gate (`verify_mpr_in_pyz.py`, fails the build on `PYZ_MPR_STALE`).
* Whole-function bans on `SetFocalPoint` / `SetViewUp` / `SetParallelScale` /
  `ResetCamera` in `test_mpr_deferred_3d_layout_stability.py` and
  `test_mpr_lifecycle_guard.py`.

---

## Recommended action

**Do not change MPR geometry. Fix the validator.** Diagnostics-only, no render
path touched, no clinical risk.

1. **Make the checks mode-aware.** In `validate_after_oblique`, ask the mapper
   which mode it is in — `mapper.GetSliceFacesCamera()` / `GetSliceAtFocalPoint()`.
   When the pane is in explicit-plane mode, validate against
   `mapper.GetSlicePlane()` (`origin`, `normal`), not the camera. The meaningful
   containment check becomes `dot(crosshair − plane.origin, plane.normal)` —
   which is the number that actually says whether the displayed slice is where
   the crosshair says it is.
2. **Retire or re-scope `check_focal_at_crosshair` for oblique.** Under Fix-E
   the camera focal is *supposed* to stay put in-plane. Keep it as a
   through-plane-only check, or drop it from the oblique report.
3. **Re-baseline `parallel_scale` on user zoom**, or compare against the live
   camera rather than a creation-time snapshot. As written it reports the
   user's own zoom as a defect.
4. ~~**Record Fix-E in the documentation.**~~ **DONE 2026-08-23** — this was the
   root cause of the near-miss, so it was fixed first. What landed:

   | # | change | where |
   |---|---|---|
   | a | Fix-E recorded as a do-not-break item, with its consequences | `mpr-geometry-pipeline.md` **§10.9** |
   | b | The render/interaction throttle documented — it had **no documentation anywhere**, which is why "just add a camera update per crosshair move" had no budget to check itself against | new **§10g** |
   | c | All nine validator checks, thresholds, the violations-only logging asymmetry, and which three are stale | new **§10h** |
   | d | Status banner mapping which sections are CURRENT vs HISTORICAL — §3–§6 were retired by §10b and are still written in the present tense | doc header |
   | e | §10.6 corrected: the canonicalization flag is default **ON**, not OFF | **§10.6** |
   | f | The fixed-character-window test landmine recorded as a do-not-break item | **§10.10** |
   | g | `_set_oblique_camera()` no longer described as *"repositions the target view's camera"* | `ZETA_MPR_PIPELINE_REFERENCE.md` §3.2, §3.3 |
   | h | `_update_slice_positions` docstring rewritten to match its own body | `_mpr_crosshair_state.py` |
   | i | Oblique-MPR camera invariant | `docs/INDEX_BY_SUBSYSTEM.md` |
   | j | Catalog row for the prevented regression | `REGRESSION_CATALOG.md` |

   Verified after: `tests/code/mpr + viewer + system + architecture + fast` →
   **2 919 passed**, 4 failed (the `test_local_search_progressive` pins carried
   since 2026-08-21). Only documentation and one docstring changed.

Each of these gets a kill switch and a guard test that fails pre-fix, per repo
convention. The behavioural guard worth writing is the one nobody has: **build a
real `vtkCamera` + `vtkImageResliceMapper`, put the mapper in explicit-plane
mode, move the crosshair, and assert the displayed plane contains it.** There is
currently *no* behavioural camera test in the repo at all.

---

## Open questions

1. **Why did oblique activity jump 165×** between 3.5.9 (7 lines) and 3.6.2
   (1 152) across a near-identical number of MPR opens? Still unanswered, and it
   is now the only part of A1 that might indicate a real behaviour change.
2. **Compound oblique is documented as undefined.** With two views rotated
   simultaneously the third receives two oblique-normal updates and "last write
   wins" — the engineering journal calls the result *"undefined and may produce
   incorrect images."* Never resolved.
3. **Oblique scroll semantics** — scrolling moves along the orthogonal look
   axis, not the tilted normal, so an oblique plane scrolls diagonally. Flagged
   as a UX decision in the journal; never decided.
4. **Was the anatomical camera path ever validated together with crosshair
   rotation?** The 2026-06 live validation covered static orientation on four
   reference cases. No document records an oblique-rotation regression test
   after the anatomical-camera change.
5. ~~**Doc/code drift**~~ — **FIXED 2026-08-23**, see recommendation 4 above. All
   four drifted statements (flag default, `_set_oblique_camera`'s description,
   `_update_slice_positions`' docstring, and the unmarked historical sections)
   have been corrected at source.

   **The lesson worth keeping**, because it will recur: *a design decision that
   lives only in a source comment will be reverted.* Fix-E was correct, tested by
   the field for months, and load-bearing — and it had no report, no catalog row
   and no test, while three separate documents actively described the behaviour
   it had replaced. The documentation did not merely fail to help; it argued for
   the regression. **When a change reverses an earlier one, the earlier one's
   documentation is part of the change.**

---

## Method note

Four parallel read-only passes over 74 MPR/geometry/VTK documents and 58 test
files, then direct verification in source of every load-bearing claim before it
was accepted: `_set_oblique_camera` (L232–303), `_update_slice_positions`
(L58–104), `validate_after_oblique` (L648–700), and the `capture_baseline` call
sites. Nothing in this brief rests on a summary alone.
