# Standard MPR is slow on high slice counts — 672-slice measurement (patient 52827)

**Date:** 2026-08-01 · **Case:** patient 52827, series 202, **512×512×672** CT chest
(scalar range −1024…19757), source `pydicom_qt` (FAST) → orthogonal Standard MPR.
**Verdict:** MPR open took **~21 s wall / 17.9 s inside `StandardMPRViewer` construction**, and
**~30 s of the main thread was blocked** (19.3 s + 10.8 s stalls). It is **not one slow step** —
it is ~8 serial GUI-thread costs that all scale with slice count. Nothing crashed; this is pure
latency. Master plan item: **OPT-48** (extends OPT-47 large-volume work).

---

## 1. Measured timeline (from `[MPR-STEP]`, `[MPR VTK LOAD]`, `[MPR-OPEN-KPI]`, F11 stall stacks)

| # | t (11:3x) | Δ | Stage | Where |
|---|---|---|---|---|
| 1 | 34:56.48 → 34:58.70 | **2.2 s** | 672-file DICOM→VTK load | `_load_vtk_paths_responsive` — **already off-thread** ✅ |
| 2 | 34:59.13 → 34:59.83 | 0.7 s | `canonicalize_volume` (geometry probe) | ok |
| 3 | 34:59.83 → **35:03.18** | **3.3 s** | **`vtkImageFlip.Update()`** — full 352 MB volume copy | `widget.py:134` **GUI THREAD** 🔴 |
| 4 | 35:03.18 | **1.5 s** | **`GetScalarRange()`** — full-volume min/max scan | `widget.py:149` **GUI THREAD** 🔴 |
| 5 | 35:03.63 → **35:08.10** | **4.5 s** | **`QVTKRenderWindowInteractor(container)` → `winId()`** (axial pane) | `_mpr_views.py:457` 🔴 |
| 6 | 35:09.22 → 35:11.63 | 2.4 s | `AddRenderer` + `vtkRenderer()` construction | `_mpr_views.py:462` |
| 7 | 35:11.63 → **35:14.28** | **2.7 s** | **`vtk_widget.Initialize()`** (first GL context + upload) | `_mpr_views.py:498` 🔴 |
| 8 | 35:15.90 → 35:17.13 | 1.2 s | crosshairs + `vtkTextActor` + pane toggle buttons | `_mpr_crosshair_render.py:173`, `_mpr_layout.py:132` |
| — | 35:17.78 | — | **`[MPR-OPEN-KPI] standard_mpr_construct_ms=17944.1`** | (deferred-3D ON) |
| 9 | 35:19.47 → 35:28.61 | **~9 s** | **deferred 3D VRT**: `vtkGPUVolumeRayCastMapper` + `SetDisableGradientOpacity` + 3 × `Render()` | after the KPI, still GUI thread 🔴 |

**Main-thread stalls this open:** `19,271 ms` (construction) + `10,812 ms` (deferred 3D) + a
2,014 ms pre-load stall = the app is unresponsive ~30 s. The `_heavy` OPT-47 path did engage
(`SetDisableGradientOpacity(1 if _heavy else 0)` is in the trace) — so the **OPT-47 crash fix is
working**, but it addresses *stability*, not *latency*.

## 2. Why it scales badly with slice count

672 slices × 512 × 512 × 2 B = **352 MB**. Steps 3, 4, 7 and 9 each touch that entire buffer on
the **GUI thread**:

- **`vtkImageFlip.Update()` (3.3 s)** — allocates a SECOND 352 MB volume and copies it just to
  mirror X. This is the single biggest *avoidable* cost: the same left-right correction can be
  expressed as a **direction-matrix / camera** operation (the geometry contract already carries
  `ZetaAnatA`), or done inside the existing off-thread loader, instead of a full memcpy.
- **`GetScalarRange()` (1.5 s)** — a full min/max scan of 352 MB. For CT it can be derived from
  the DICOM rescale/window tags, cached with the volume, or computed in the loader thread.
- **QVTK widget creation + `Initialize()` (7.2 s combined)** — first GL context, texture upload of
  a 352 MB volume. Partly inherent, but it is paid **synchronously for the axial pane before any
  pane paints**.
- **Deferred 3D VRT (~9 s)** — `AIPACS_MPR_DEFER_3D=1` correctly moved it *after* the 2D panes,
  but it still runs on the GUI thread, so the app freezes again ~2 s after the panes appear.

Sub-linear items (canonicalize, crosshairs, text actors) are noise by comparison.

## 3. Ranked fix candidates (no clinical/geometry change)

| # | Fix | Saves | Risk | Notes |
|---|---|---|---|---|
| 1 | **Eliminate `vtkImageFlip`** — fold the X-flip into the direction matrix/camera (or into the off-thread loader's array view) | **~3.3 s** + 352 MB peak RAM | Med (geometry — must golden-compare L/R on axial/sag/cor) | biggest single win; also halves peak memory, complements OPT-47 |
| 2 | **Compute `GetScalarRange()` off-thread** (in `_load_vtk_paths_responsive`, pass it in) or from DICOM tags | **~1.5 s** | Low | pure move; value identical |
| 3 | **Build the 2 remaining 2D panes lazily/deferred** like the 3D one | perceived ~2-3 s | Low-Med | axial paints first; sag/cor fill in |
| 4 | **Defer the 3D VRT until the user opens the 3D pane** (or idle-gate it, like the browser prewarm) | **~9 s** off the open path | Low | `AIPACS_MPR_DEFER_3D` already exists — extend to "on demand" |
| 5 | Progress feedback during construction (spinner + stage text) | 0 s, big UX | Low | 30 s with a frozen window reads as a hang |
| 6 | Down-sample the VRT input for >400 slices (render 3D at half Z) | ~4 s of #9 | Med (3D fidelity only, not 2D diagnostic) | 2D reslice stays full-resolution |

**Not the problem (measured, do not chase):** the DICOM decode/load (2.2 s, already off-thread and
proportionate), disk I/O, the download path, geometry canonicalization, or the OPT-47 GPU budget
(the heavy path engaged correctly and did not crash).

## 3b. PHASE 1 SHIPPED (2026-08-01, same day) — #2 + #4 + #5, all default-on

| Fix | Implementation | Flags (kill switch) |
|---|---|---|
| **#2 scalar range off the GUI thread** (−1.5 s) | The loader's existing worker thread now warms `GetScalarRange()` on the source volume (`toolbar_manager._load_vtk_paths_responsive::_VtkLoadWorker`), and `StandardMPRViewer.__init__` reads the range from the **PRE-FLIP** volume. Safe by construction: `vtkImageFlip` only PERMUTES voxels along X, so the value set — and therefore min/max — is identical. Falls back to the flipped output on any error. | `AIPACS_MPR_WARM_SCALAR_RANGE=0`, `AIPACS_MPR_SCALAR_RANGE_FROM_SOURCE=0` |
| **#4 3D VRT on demand** (−9 s off the open path) | For volumes ≥200 slices the deferred-3D placeholder becomes a **clickable "3D view (click to render)"** cell; the VRT is built the first time the user asks. Below the threshold the existing L1 auto-build is unchanged. Pure decision `should_defer_vrt_to_demand(slice_count)`; unknown/garbage slice count → legacy auto-build. Logs `[MPR-VRT-ON-DEMAND]`. | `AIPACS_MPR_VRT_ON_DEMAND=0`, `AIPACS_MPR_VRT_ON_DEMAND_SLICES=N` |
| **#5 build progress** (UX) | A modal busy dialog ("Preparing MPR views (N slices)…") is shown + painted BEFORE the blocking `StandardMPRViewer(...)` construction and closed in a `finally`. Only for volumes ≥200 slices, so small series are untouched. | `AIPACS_MPR_BUILD_PROGRESS=0`, `AIPACS_MPR_BUILD_PROGRESS_SLICES=N` |

`[MPR-OPEN-KPI]` now also reports `slices=`, `vrt_on_demand=` and `warm_scalar_range=` so the
before/after is measurable from one log line. **Geometry, slice order, orientation, the three
diagnostic 2D planes and the OPT-47 large-volume safety path are all untouched.**
Guard: `tests/code/viewer/test_mpr_open_latency_opt48.py` (11) — 45 green with the L1/OPT-47/
preflight suites. **Expected on the 672-slice case: construct ≈17.9 s → ≈16.4 s, and the ~9 s
post-open VRT freeze removed entirely (paid only if 3D is opened).** NEEDS live re-measure.

Note for future edits: the auto-build is gated with `if not self._vrt_on_demand:` rather than an
`else:` — the pre-existing L1 guard test slices that branch at the first `else:`.

## 3c. PHASE 2 SHIPPED (2026-08-01) — the X-flip moved OFF the GUI thread, geometry-identical

**The geometry-safe interpretation of fix #1 was chosen deliberately.** The report's original
option — expressing the left-right correction as a direction-matrix / camera operation — WOULD
have changed the radiological convention contract: every downstream consumer (reslice mappers,
cameras, crosshairs, measurements, and the on-screen L/R validated by the user) assumes the
volume itself is physically flipped. **That is a geometry change, not a speed-up, so it was NOT
done.** Instead the SAME `vtkImageFlip` now runs on a worker thread:

- `StandardMPRViewer.build_lr_flipped_volume(vtk_image_data)` is now **the single canonical
  implementation** of the flip (`vtkImageFlip` + `SetFilteredAxis(0)` + the field-data copy that
  carries `DirectionMatrix` / `ZetaAnatA`). A guard test asserts `widget.py` constructs
  `vtkImageFlip()` **exactly once**, so the two paths can never drift.
- `toolbar_manager._prepare_mpr_flip_offthread()` runs that same function on a `QThread` behind
  the existing modal-progress pattern (≥200 slices; smaller volumes flip in ms and are skipped),
  and passes the result as `pre_flipped_image_data=`.
- The viewer **validates** the handed-in volume (dims must equal the source — a flip cannot change
  dims) and falls back to the inline flip on ANY mismatch, failure, or when the flag is off.
- The other two `StandardMPRViewer(...)` call sites (dental host, CurveMPR) do not pass it → they
  keep the inline flip, byte-identical.

Flags: `AIPACS_MPR_FLIP_OFFTHREAD=0`, `AIPACS_MPR_FLIP_OFFTHREAD_SLICES=N`. Marker `[MPR-FLIP]`.

**Proof of no geometry regression** — `tests/code/viewer/test_mpr_flip_offthread_opt48.py` (10)
runs REAL VTK on a synthetic asymmetric volume where each voxel encodes its own (x,y,z):
1. helper output is **voxel-for-voxel identical** to the verbatim legacy inline flip (plus dims /
   spacing / origin identical);
2. the output IS the X-mirror (`out[x] == src[nx-1-x]`) and nothing else moved — the radiological
   L/R correction still happens;
3. `DirectionMatrix` and `ZetaAnatA` field arrays survive value-for-value;
4. one-flip-implementation, dims-validation/fallback and call-site pins.
`tests/code/viewer -k "mpr or orientation or geometry or canon"` = **404 passed**.

Expected saving: **~3.3 s** more off the GUI thread (total Phase 1 + 2 ≈ **−13.8 s** of blocking
time on the 672-slice case). Peak memory is unchanged (still two volumes) — reducing that means
releasing the source after the flip, which is NOT safe here because the caller may reuse the
volume (cache / other viewers); left as a separate, later item.

## 4. Suggested sequencing

**Phase 1 (safe, no geometry risk):** #2 + #4 + #5 → removes ~10.5 s from the open path and makes
the rest visible/explained. **Phase 2 (needs golden-image L/R validation):** #1 → another ~3.3 s
and a 352 MB memory saving. **Phase 3:** #3/#6 if still needed.

Instrumentation to keep: `[MPR-OPEN-KPI] standard_mpr_construct_ms` is the KPI to track
before/after; `[MPR-STEP]` gives the per-step split; F11 stall traces name any new hot spot.
