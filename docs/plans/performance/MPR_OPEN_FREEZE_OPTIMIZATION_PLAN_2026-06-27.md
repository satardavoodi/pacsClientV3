# MPR‑Open GUI Freeze — Optimization Plan (2026‑06‑27)

**Status: DESIGN DOC ONLY — no code yet.** This is the careful‑design record so the deferral can be
implemented deliberately, intra‑domain, with a clinical‑lane verify — not rushed. The MPR module is
its own VTK execution domain; this plan stays inside it.

## 1. Symptom (measured)

Opening MPR (`toggle_zeta_mpr`) freezes the GUI thread for **5–11.5 seconds** — the single worst
freeze in the app. Live `[MAIN_THREAD_STALL_TRACE]` (the main.py:1118 GUI‑thread sampler), 2026‑06‑27:

```
gap=11496ms / 8096ms / 6869ms / 4985ms  @ 17:05
  patient_toolbar/toolbar_manager.py:5398   toggle_zeta_mpr
  modules/mpr/zeta_mpr/mpr_viewer/widget.py:375   StandardMPRViewer.__init__
  modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:96   _setup_ui
  modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:642  _create_3d_view      (the 11.5s / 8s traces)
  modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:323/356  _create_axial_view (the 6.8s / 5s traces)
  .venv/.../vtkmodules/qt/QVTKRenderWindowInteractor.py:362  __init__
  modules/mpr/zeta_mpr/mpr_viewer/_mpr_layout.py:321  _update_view_highlights
```

For contrast: the FAST series **reading** path is smooth (TTFI avg 56 ms; **zero** series‑build/grow
stalls). So this is NOT the "volume build on the GUI thread" concern (task #39) — it is VTK **view**
construction.

## 2. Root cause

`StandardMPRViewer._setup_ui` builds **four VTK render windows synchronously** on the GUI thread
(`_mpr_views.py:95‑98`):

```python
self._create_axial_view(views_layout, 0, 0)
self._create_3d_view(views_layout, 0, 1)
self._create_sagittal_view(views_layout, 1, 0)
self._create_coronal_view(views_layout, 1, 1)
```

Each `_create_*_view` constructs a `QVTKRenderWindowInteractor` (creating its OpenGL context) and calls
`Initialize()` + `Start()` + a first `Render()`. The **3D (VRT) view additionally uploads the whole
volume to the GPU** (`vtkGPUVolumeRayCastMapper`) and does the first ray‑cast render
(`_create_3d_view`, `widget.Initialize()/Start()` at :634‑635) — the most expensive single step. All
four + the GPU upload + the first renders complete **before control returns to the event loop**, so the
UI is locked the entire time.

## 3. Hard constraints (must respect)

1. **VTK render windows + GL contexts MUST be created on the GUI thread.** A
   `QVTKRenderWindowInteractor` / GL context cannot be constructed on a worker thread. So — unlike the
   patient‑close `gc.collect()` freeze — this **cannot be moved off‑thread.** The only lever is *when*
   (defer/stage the work across event‑loop turns), not *where* (thread).
2. **MPR is its own VTK domain** (`docs/plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`
   §0.1 hard rule). Optimize **intra‑domain only** — never couple MPR to FAST/Advanced. The volume it
   consumes already arrives through the shared read‑only trunk (`vtk_image_data`); that is unchanged.
3. **Geometry / orientation / reslice / render correctness is clinically protected.** The deferral may
   change only the **order/timing** of view creation — never *what* is shown. No change to the camera
   baseline, native‑plane interpolation, slab projection, cross‑hair sync, or the reslice pipeline.

## 4. Proposed staged optimization (each flag‑gated, default‑off until clinical‑lane‑validated)

### L1 — Defer the 3D (VRT) view  ·  biggest single win, lowest risk
The three reslice planes (axial/sagittal/coronal) are the diagnostically primary views; the 3D VRT is
the **most expensive AND the least time‑critical**. Plan:
- Create the **three 2D views first**, add them to the layout, and let the event loop paint them — the
  user sees a working MPR with the three planes in roughly the 2D‑only time.
- **Defer `_create_3d_view`** to a `QTimer.singleShot(0, …)` (idle) callback that runs *after* the 2D
  views are shown. Reserve its grid cell with a lightweight placeholder (e.g. a "Rendering 3D…" label)
  so the layout doesn't jump when the 3D pane lands.
- The post‑creation passes that depend on **all** views must be handled correctly:
  `_apply_native_plane_interpolation` (:105), `_capture_baseline_camera_state` (:127), and
  `_apply_slab_projection` (:118) — split them so the 2D‑relevant parts run now and the 3D‑relevant part
  re‑runs inside the deferred callback (or run the whole tail in the deferred callback once the 3D
  exists, if cheap).
- **Teardown race:** if MPR is closed before the deferred 3D builds, the singleShot callback MUST bail
  before touching anything (widget‑alive guard) — reuse the existing deleted‑object / cancellation‑by‑
  handle guards (`AIPACS_SWALLOW_DELETED_OBJECT_EVENTS`, `CancellationRegistry`).
- **Expected:** 11.5 s → "2D planes shown in ~the 2D‑creation time" + "3D fills in a moment later."
  Even if 2D creation is still a couple of seconds, the user gets diagnostic content far sooner and the
  heaviest step (3D GPU upload + first ray‑cast) no longer blocks first paint.
- **Flag:** `AIPACS_MPR_DEFER_3D` (default off → byte‑identical synchronous build).

### L2 — Progressive 2D view creation  ·  only if 2D alone is still too slow
The axial trace alone showed ~5–6.8 s, so the 2D views aren't free either. If L1 leaves an
unacceptable 2D freeze:
- Create one 2D view, show it, then create the next on the next idle turn (one render window per
  event‑loop turn) — axial first, then sagittal, then coronal.
- More complex (the cross‑hair/camera sync across views must tolerate a partially‑built set) — do only
  if L1 is insufficient. **Flag:** `AIPACS_MPR_PROGRESSIVE_2D`.

### L3 — Cheaper first 3D render  ·  optional, deeper
- Coarse first 3D render (lower initial sample distance), refine at rest (`AutoAdjustSampleDistances` is
  already set; `SetDesiredUpdateRate(15)` / `SetStillUpdateRate(0.001)` at :629‑630). Or defer the GPU
  upload until the 3D pane is first made visible/interacted.

## 5. Invariants / guards
- Every stage flag‑gated **default‑off**; `=0`/off path is byte‑identical to today's synchronous build.
- Only view‑creation **order/timing** changes — geometry, orientation, reslice, slab, interpolation,
  crosshair sync, and camera baseline are unchanged and verified equal.
- The deferred callback is **teardown‑safe** (widget‑alive + handle‑cancellation guard) — closing MPR
  mid‑build must never touch a deleted VTK/Qt object.
- Stays in `modules/mpr/zeta_mpr/`; **no** FAST/Advanced coupling, no `cleanup_all_viewers()` global
  wipe.
- Per the Unified MPR/3D direction
  (`docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`), Standard (Zeta) MPR is
  the reference foundation — this deferral lands **here first**; Dental Curve / Orthogonal MPR inherit
  it when they re‑home onto the standard foundation.

## 6. Validation
- **Offscreen (agent lane):** a guard test source‑pinning the deferral wiring + the teardown‑safe
  callback (the actual VTK render needs the clinical lane, so the functional render isn't unit‑testable).
- **Clinical lane (Windows source build) — required before flipping any flag on:** open MPR on a large
  CBCT and confirm
  (a) the three reslice planes appear in ≲ a second or two,
  (b) the 3D pane fills in shortly after with the correct VRT,
  (c) geometry / orientation / crosshairs / slab are **identical** to the synchronous build,
  (d) closing MPR mid‑build does not crash (no deleted‑object RuntimeError into `main.notify`),
  (e) `[MAIN_THREAD_STALL_TRACE]` shows the MPR‑open gap dropping from ~11 s to the 2D‑only time.

## 7. Why not now
This is delicate, clinically‑visible VTK‑domain work in a module the project rules explicitly protect.
It is captured here so it can be implemented as a deliberate, flag‑gated, clinical‑lane‑validated pass —
not bundled into the FAST series‑display unification cutover (a separate domain). Implement L1 first;
measure; only then consider L2/L3.
