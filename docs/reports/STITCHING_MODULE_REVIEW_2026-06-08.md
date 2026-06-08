# Stitching Module — Review & Safe Optimization Plan (2026-06-08)

Scope: `modules/stitching/` (landmark-based 2-D radiograph chain stitching for
long-bone / limb-length survey films). The as-found record and a phased plan.

## Implementation status (updated 2026-06-08)

**Phases 0–4 are implemented and test-verified** (26 tests green in
`tests/code/stitching/`, plugin mirror in parity; offscreen construction smoke
passes; live GUI check of the functional work passed 2026-06-08). Done:
- **Phase 0** — quarantined dead code (`canvas_builder.py`, `stitch_controller.py`
  → `_recovery/stitching_deadcode_20260608/`), dropped `StitchController` export,
  `print()` → `logging` across all 5 active files (this also fixed a real
  `UnicodeEncodeError` crash: the blend's `print("…→…")` threw on the cp1256
  Arabic console), refreshed the README.
- **Phase 1** — float32 throughout the blend + worker (was float64), eager frees,
  worker reuses already-loaded / in-memory images (fixes the uint16 round-trip on
  the next stitch stage), worker leak fixed (`finished` → `deleteLater`), export
  blank-image guard.
- **Phase 2** — the headline fix: the multiband blend now uses a **decimating**
  Burt–Adelson pyramid (each level halves), replacing the full-resolution
  difference-of-Gaussians. Output matches the prior image within 0.05% on
  mean/sum (a few seam pixels move < 0.6%); memory drops from ~`levels×N`
  full-res arrays to ~1.33× one full image.

- **Phase 3** — **Quick Preview (fast)** button: runs the worker in a new
  preview mode that caps the canvas to its longest side (`preview_max_dim`,
  default 1400 px, addressing B5) and uses the fast feather blend, skipping the
  accuracy gate, so the user can eyeball alignment in ~1 s before committing to
  the full multiband run. Plus the **"need N more pairs" hint** (U2): Compute /
  Quick Preview now explain exactly how many complete pairs each boundary still
  needs instead of staying silently disabled.

- **Phase 4** — **V2 theme reskin**: the hard-coded `_DARK_STYLE` is replaced by
  `_build_app_stylesheet(theme)` built from the V2 design tokens; every inline
  label colour now routes through tokens (`_apply_theme_styles` + a
  `_style_accuracy` helper for the info/success/danger residual states), and the
  window re-skins live on `themeChanged`. The `_MiniViewer2D` image viewport
  stays black (medical standard); only its chrome is themed. Structure/feel are
  unchanged — the window just tracks the active AI-PACS theme now.

**Still open (minor, optional):** a dedicated result view and drag-to-reposition
landmarks (ergonomic nice-to-haves, not function). Sections below are the
original review for reference.

---

---

## 1. Current architecture (as-built)

Entry point: `PacsClient/.../patient_widget_core/_pw_advanced.py:986`
→ `get_stitching_widget()` (singleton) → `launch_with_series(available_series, …)`.

| File | LOC | Role | Status |
|------|----:|------|--------|
| `stitching_widget.py` | 1563 | Main window: 2 VTK viewers, sidebar, landmark picking, drives worker | **active** |
| `stitch_worker.py` | 310 | `QThread` running the full N-series pipeline | **active** |
| `stitch_engine.py` | 208 | SimpleITK helpers: load 2-D, compute transform, resample, residuals | **active** |
| `blend_engine.py` | 330 | histogram-match + "multiband" blend (+ legacy feather/alpha) | **partly active** |
| `landmark_store.py` | 200 | pair-set landmark storage (QObject + signal) | **active** |
| `landmark_interactor_style.py` | 431 | VTK click-to-place crosshair markers | **active** |
| `stitch_controller.py` | 149 | pick-mode state machine + run_stitch | **DEAD** (not used by widget) |
| `canvas_builder.py` | 198 | union-bounds + paste helpers | **DEAD** (worker inlines this) |

Pipeline (in `StitchWorker.run`):
load N series → per-pair landmark transform → per-landmark residuals →
**pause-gate** if any residual > 4 mm → chain-compose transforms → union canvas
at finest spacing → resample each series onto canvas → histogram-match +
multiband blend → wrap as `sitk.Image` → `completed`.

The design fundamentals are sound: physical-mm coordinates throughout,
heavy work off the GUI thread, a residual-accuracy gate with a clear 3-choice
dialog, and an iterative "use result for next stitch" multi-stage flow. The
problems below are about performance, memory, dead weight, and polish — not the
core approach.

---

## 2. Bottlenecks found (performance)

### B1 — Multiband blend is the dominant cost AND the dominant memory hog (critical)
`blend_engine._build_gaussian_pyramid()` **does not decimate** — every one of the
5 pyramid levels is kept at *full canvas resolution* (it is really a stack of
difference-of-Gaussians, not a true image pyramid). For each of N images the
blend builds a 5-level Gaussian pyramid + a 5-level Laplacian pyramid, and for
each of N weight maps another 5-level Gaussian pyramid — **all full-resolution
float64**, all alive at once.

Rough peak for a 3-series limb film, ~2000×8000 union canvas (16 Mpix):
- 128 MB per float64 full-canvas array.
- Simultaneous arrays ≈ N×12 (lap pyr 5 + weight pyr 5 + distance 1 + input 1)
  ≈ 36 → **~4.6 GB**, plus histogram-match copies and the still-alive `arrays`
  list. This is the **#1 cause of lag and out-of-memory crashes** on exactly the
  intended use case.

5× full-resolution `SmoothingRecursiveGaussian` per image is also the main CPU
cost; with real decimation the upper levels would be ¼, 1⁄16, … the area.

### B2 — float64 everywhere
The worker casts each resampled image `astype(np.float64)` (the resample output
is already float32 — instant 2× memory), and the whole blend runs in float64.
Radiograph intensity fits comfortably in float32. float64 doubles memory and
halves SIMD throughput for zero clinical benefit.

### B3 — Series are loaded from disk twice
The widget loads each series for display (`_loaded_images`), then the worker
calls `load_series_as_2d()` again from `series_dirs`. Double DICOM I/O on every
Compute.

### B4 — No fast/low-res preview; the only feedback is the full pipeline
"Preview Result" just displays the already-computed full-res result. To see *any*
stitched output the user must run the entire expensive blend. There is no quick
low-resolution alignment preview, so a misplaced landmark costs a full multi-GB
pipeline run to discover visually (numeric live-residuals exist, but no picture).

### B5 — Canvas always built at the finest spacing of any series
Union canvas uses `min(spacing)` across all inputs, so one finely-sampled series
inflates the whole canvas (and every B1/B2 array with it). No option to cap
canvas resolution.

### B6 — Blend runs as one un-chunked, un-cancellable call
`retouch_and_blend()` is a single call; `is_cancelled()` is only checked between
stages, and the progress bar sits frozen at one value through the longest stage.

---

## 3. Stability risks

### S1 — Worker leak across repeated stitches
`self._worker = StitchWorker(..., parent=self)` is reassigned every Compute. With
`parent=self` Qt keeps the previous worker alive (parented, never deleted) → a
QThread + its captured images leak on each run. Use `deleteLater()` on finish and
drop the parent, or reuse one worker.

### S2 — In-memory "high-fidelity" result is silently defeated for Compute
`_on_use_result_for_next_stitch()` stores the float result in `_virtual_images`
"to avoid uint16 round-trip loss," but the worker stitches from `series_path`
(the exported uint16 DICOM), not the in-memory image. The optimization helps
display only; the next stitch still eats the uint16 loss. Either feed virtual
images into the worker or drop the misleading claim.

### S3 — Cross-thread `LandmarkStore` access
The worker reads landmark lists from the worker thread while the store lives on
the GUI thread. During the residual pause-gate the GUI is live; landmark edits
aren't hard-disabled, so a determined user can mutate the store mid-run. Low
probability, but it's an unguarded data race on clinical geometry.

### S4 — Transform inversion fallback can mis-place a series
Canvas-bounds (Stage 4) inverts each pair transform; on failure it falls back to
a crude mean-translation estimate. For an affine with a near-singular matrix this
silently produces a wrong canvas placement rather than failing loudly.

### S5 — `min 4 pairs` enforced for all transform types
`_MIN_PAIRS` requires 4 even for rigid/similarity (which are solvable with 2).
Safe, but it's a hard gate that turns into a workflow tax (see U2).

### S6 — Export normalization edge case
`_export_as_dicom` rescales by global min/max; if `vmax<=vmin` (blank/constant
result) it skips scaling and casts raw floats to uint16 → garbage pixels instead
of a clean guard.

### S7 — `print()`-only diagnostics
22 `print()` calls, zero use of `logging`. None of the module's diagnostics reach
`user_data/logs/` — which is exactly why a log scan for stitching errors comes up
empty. Failures are invisible post-hoc.

### S8 — Singleton re-create abandons the old window
`get_stitching_widget()` builds a fresh widget when the old one isn't visible;
the previous instance is dropped without `deleteLater()`. `cleanup()` frees VTK,
but the Python/Qt object lingers to GC.

---

## 4. UI/UX findings

- **U1 — Off the design system.** The window uses a hard-coded `_DARK_STYLE`
  blob, not the V2 theme tokens the rest of the app now uses. Visually
  inconsistent and not theme-aware.
- **U2 — 4-landmark minimum is unexplained and rigid.** Compute stays disabled
  with no message saying *why* ("need 4 complete pairs per boundary"). The
  transform combo offers Rigid/Similarity but the UI still demands 4.
- **U3 — No visual preview before the full run.** Users fly blind on alignment
  until a multi-GB compute finishes (see B4).
- **U4 — Result replaces the "Right Image" panel.** Confusing dual-purpose pane;
  a dedicated/full-width result view would read better.
- **U5 — Frozen-looking progress** during blend (see B6).
- **U6 — Landmark repositioning is select-then-click**, not drag — workable but
  less direct than dragging the marker.
- **U7 — Stale README.** Describes the old two-image "Load Moving Series /
  Compute Alignment / feather blend" flow; the code is N-series chain + multiband.

---

## 5. Safe optimization plan (phased, low-risk → higher-touch)

Ordering favors regression safety. Each phase is independently shippable and
test-gated. **Preserve all existing functionality**; nothing here removes a
viewer feature, the residual gate, the multi-stage flow, or export.

### Phase 0 — Zero-risk hygiene (no behavior change)
1. Delete/relocate dead code: `canvas_builder.py`, `stitch_controller.py`, and
   the legacy `feather_blend`/`alpha_blend`/`n_image_feather_blend` (quarantine,
   don't hard-delete, per repo convention). Drop `StitchController` from
   `__init__` exports.
2. Refresh `README.md` to match the as-built N-series pipeline.
3. Swap `print()` → module `logging` so diagnostics reach `user_data/logs/`.

### Phase 1 — Memory & speed, behavior-preserving (highest ROI)
4. **float32 the blend pipeline** (B2): keep resampled arrays float32; run blend
   in float32. ~2× memory cut, faster, output visually identical.
5. **Free eagerly** (B1): in `n_image_multiband_blend`, drop each image's
   Gaussian pyramid once its Laplacian is derived, and free per-image structures
   as the accumulation proceeds instead of holding all N at once.
6. **Reuse already-loaded images** (B3): pass the widget's `_loaded_images`
   (and `_virtual_images`, fixing S2) into the worker instead of re-reading disk.
7. Fix **S1** (worker `deleteLater()` + no parent) and **S6** (export guard).

### Phase 2 — Big memory win: true pyramid decimation (the real B1 fix)
8. Rewrite `_build_gaussian_pyramid` to **downsample 2× per level** (and
   `n_image_multiband_blend` to upsample on reconstruction). This is the correct
   Burt–Adelson construction: upper levels become ¼, 1⁄16 … the area, cutting
   blend memory and time by ~3–4× and removing the OOM ceiling. Higher touch →
   needs the golden-image test (T3) as a guard before/after.

### Phase 3 — Workflow / preview
9. **Fast low-res alignment preview** (B4/U3): a downsampled feather composite
   computed in well under a second so users can eyeball alignment before the full
   multiband run. Add a canvas-resolution cap option (B5).
10. Chunk/ә-progress the blend or at least show an indeterminate state (B6/U5).

### Phase 4 — Cosmetic / clarity (optional)
11. Re-skin onto V2 theme tokens (U1); add a "need N more pairs" hint (U2);
    consider a dedicated result view (U4) and drag-to-reposition (U6).

Recommended first PR: **Phase 0 + Phase 1** — large, safe wins with no algorithm
change. Phase 2 is the headline performance/stability fix but should ride behind
the golden-image regression test.

---

## 6. Tests needed (there are currently **none** — only a feature-flag check)

`tests/code/runtime/test_aipacs_runtime_modules.py` only asserts the module is
*enabled*. There is no functional coverage. Add (all headless,
`QT_QPA_PLATFORM=offscreen`, `-p no:debugging`), and run **before and after** each
phase to prove no regression:

- **T1 engine math** — `compute_transform` + `compute_residuals` on synthetic
  landmark sets with a known transform; assert residuals ≈ 0 and a known shift
  recovers. (Guards Phase 0/1.)
- **T2 blend invariants** — single image returns itself; 2-image blend on a
  synthetic overlap conserves intensity range and is finite/no-NaN; output dtype
  is float32 after Phase 1. (Guards Phase 1.)
- **T3 golden-image blend** — fixed synthetic 2–3 array case → hash/allclose the
  blended result. Capture the value on today's code, then require the decimated
  pyramid (Phase 2) to match within tolerance. **This is the gate for Phase 2.**
- **T4 memory ceiling** — drive `retouch_and_blend` on a representative large
  canvas; record peak RSS before vs after Phase 1/2 (assert it drops, and stays
  under a budget).
- **T5 worker lifecycle** — run two sequential stitches; assert no leaked
  `StitchWorker`/QThread (guards S1) and the result is reproducible.
- **T6 source/AST guards** — dead modules stay gone; blend stays float32; logging
  (not print) is used; plugin-payload mirror parity for `modules/stitching`.

Plus one **live GUI smoke** (human-assisted, per project default): open Advanced
Analysis → Stitching, load 2 series, place 4 pairs, Compute, Preview, Export —
confirm parity and watch peak memory in Task Manager before vs after.

> Note: `modules/stitching` **is plugin-mirrored**
> (`builder/plugin package/packages/stitching`). Any code change must be followed
> by `tools/dev/sync_plugin_mirrors.py` then `verify_plugin_mirrors.py`.

---

## 7. One-line summary

The stitching approach is sound, but the blend is a non-decimating full-resolution
float64 pyramid that can spike to multiple GB on real limb films (the #1 crash/lag
risk); the safe path is float32 + eager-free (Phase 1), then true pyramid
decimation behind a golden-image test (Phase 2), with dead code removed and the
first-ever functional tests added before any change.
