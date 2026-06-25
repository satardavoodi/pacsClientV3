# Dental Curve MPR — Improvement Plan (codebase-grounded)

**Date:** 2026-06-22
**Scope:** How to improve the Patient-Tab **Dental Curve MPR** module, mapped to *this* repo's
code, constraints, and reusable infrastructure. Every item names concrete files/functions, an
effort/risk rating, a default-on feature flag, a guard test, and what still needs live
source-build validation.
**Reads with:**
- `docs/reports/DENTAL_CURVE_MPR_CODE_REVIEW_2026-06-22.md` (the as-found audit)
- `docs/pipelines/dental-curve-mpr.md` (as-built + invariants)
- `docs/research/DENTAL_CBCT_WORKSTATION_LANDSCAPE_2026-06-22.md` (what leading dental CBCT
  workstations do — the clinical "north star")

> Working rules honored throughout: minimal safe edits, preserve clinical behavior, FAST mode
> never instantiates VTK render windows, flag-gate behavior changes default-on with a legacy
> kill switch, add a guard test, and flag anything that needs the Windows source-build lane.

---

## ⚠ ALIGNMENT UPDATE (2026-06-22) — supersedes parts of this plan

After a direct comparison with the working standard (Zeta) MPR pipeline
(`docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md`), the direction below is
revised so Dental Curve MPR **reuses the standard MPR foundation** instead of diverging:
- **Item B1 is REVISED:** do **NOT** add a QPainter/FAST display. Standard MPR is fully VTK
  (`vtkImageResliceMapper`+`vtkImageSlice`); an explicitly-activated MPR is the *sanctioned* VTK
  path. Reuse standard MPR's VTK rendering rather than build a parallel raster renderer.
- **New top-priority item A0:** adopt standard MPR's **geometry contract** (shared prepared volume
  + `vtkImageFlip` X + `DirectionMatrix`/`ZetaAnatA` LPS triad + IPP slice-sign). The dental engine
  currently ignores orientation → possible L/R mirror + oblique mis-orientation.
- **Item B3 is PROMOTED** (and re-rated lower risk): mirror standard MPR's in-place single-cell
  swap (`_mpr_grid_position` save/restore + `_zeta_mpr_widget`/`_original_widget` cross-link) to
  replace the destructive `cleanup_all_viewers()` wipe.
The verdict was **CONDITIONAL PASS** — proceed only with these revisions. Other items (A1, A5, C1,
D1–D4) remain compatible.

---

## 0. Where the module stands today

- **Three engines, two are this feature.** Generation = `modules/mpr/zeta_mpr/curved_mpr.py`
  `CurvedMPRGenerator`; display = `modules/mpr/curved_mpr/curved_mpr_panoramic_view.py`
  (`CurvedMPRPanoramicView`/`CurvedMPRViewport`); the `zeta_mpr/CurveMPR/` package is the
  *separate* "Curve MPR" button. Orchestration lives in `toolbar_manager.py`
  (`_show_curved_mpr_panel` → `_generate_curved_mpr_from_points` → `_show_curved_mpr_result`).
- **Landed 2026-06-22 (safe cleanup):** `print()`→logging shadow; flag-gated teardown
  (`AIPACS_CURVED_MPR_TEARDOWN`) fixing the leaked 100 ms timer / VTK use-after-free;
  disambiguation docstrings; guard test `tests/code/viewer/test_curved_mpr_teardown.py`.
- **Still open (this plan):** the FAST-rule violation in the display widget, the destructive
  global layout teardown, synchronous GUI-thread generation, geometry simplifications, and the
  absence of clinical niceties (slice slider, measurements, canal overlay) that the research
  shows are table-stakes for a dental CBCT workstation.

Two facts that shape everything below:
1. **Generation is headless VTK compute** (`vtkImageReslice`) — it does **not** create a render
   window, so it is FAST-legal. Only the **display** widget instantiates render windows.
2. **The module operates on the active viewport's volume only** — it never resolves studies, so
   it is *outside* the cross-patient / multi-study guards. Keep it that way (see §6).

---

## 1. Improvement backlog

Each item: **Problem** (code + research grounding) → **Change** (files/functions, reusable infra) →
**Effort** / **Risk** / **Flag** / **Test** / **Validation**.

### Theme A — Correctness & clinical-safety guardrails (do first; high value / low effort)

**A1. Never present CBCT gray values as Hounsfield Units.**
- *Problem:* Research is unambiguous — CBCT gray values are not calibrated HU (AAOMR). If the
  curved/panoramic UI shows any pixel-value/"density" readout, it must be labeled relative.
  (`docs/research/...` §2.4)
- *Change:* Audit `CurvedMPRPanoramicView` / `ImageViewerWrapper.get_window_level` and any
  value readout; if present, label "gray value (relative, same machine/protocol)"; never call it
  HU. Mostly a labeling/guard change.
- *Effort:* S · *Risk:* none · *Flag:* n/a (text) · *Test:* assert no "HU" label in curved-MPR UI · *Validation:* visual.

**A2. Honor `slice_height` (stop forcing square cross-sections).**
- *Problem:* `generate_curved_mpr` collapses width/height via `slice_size = max(slice_width,
  slice_height)`, so a 150×80 request yields 150×150. Cross-section height is clinically
  meaningful (bucco-lingual extent). (review §6.8; engine `curved_mpr.py:1449`)
- *Change:* Thread `slice_height` through `ResliceEngine.reslice_along_path` /`_extract_slice`
  as a separate output extent. Keep square as the default when only one value is given.
- *Effort:* M · *Risk:* med (geometry) · *Flag:* `AIPACS_CURVED_MPR_RECT_SLICES` (off until validated) · *Test:* dimension assertions on a synthetic volume · *Validation:* **source-build, dental CBCT**.

**A3. Correct curved-stack spacing (anisotropic, not forced isotropic).**
- *Problem:* The straightened curved volume is written isotropic (`SetSpacing(s,s,s)`), so the
  along-arch spacing is mislabeled vs the true sample step — measurements on the stack can be
  off. The panoramic path already computes correct anisotropic spacing; the curved stack should
  too. (review §10; research §2.3)
- *Change:* Set the z-spacing from the actual inter-frame arc step in `_stack_slices`.
- *Effort:* M · *Risk:* med (measurement-affecting) · *Flag:* `AIPACS_CURVED_MPR_TRUE_SPACING` (off until validated) · *Test:* spacing assertion · *Validation:* **source-build; verify a known-length measurement**.

**A4. Guard the dental-axial orientation assumption.**
- *Problem:* `PlaneGenerator._initial_normal` assumes the arch lies in the axial XY plane
  (Z = superior-inferior) and forces Binormal→+Z — wrong for oblique/rotated volumes.
  (review §12)
- *Change:* Detect the dominant arch plane from the clicked points (PCA of the point cloud)
  and seed the initial frame from that, falling back to the current heuristic.
- *Effort:* M · *Risk:* med · *Flag:* `AIPACS_CURVED_MPR_AUTO_PLANE` (off until validated) · *Test:* unit test on rotated synthetic arches · *Validation:* **source-build**.

**A5. Exception-guard the generation hot path.**
- *Problem:* The engine has essentially one try/except; a degenerate frame / out-of-bounds path
  / reshape mismatch propagates into the GUI. (review §12)
- *Change:* Wrap each `vtkImageReslice.Update()` + reshape in a guarded helper that logs and
  skips the bad frame instead of raising; surface a clean "couldn't reconstruct" message.
- *Effort:* S–M · *Risk:* low · *Flag:* not needed (defensive) · *Test:* feed a degenerate path, assert no raise · *Validation:* offscreen unit + source-build.

### Theme B — Stability & architecture (resolves the review's open risks)

**A0. Adopt standard MPR's geometry contract (new top-priority item).** ⭐
- *Problem:* The dental engine reads only `GetSpacing/GetOrigin/GetDimensions` and reslices in raw
  VTK space — it **ignores** the `vtkImageFlip` X, `DirectionMatrix`/`ZetaAnatA` LPS triad, IPP
  slice-sign, and radiological correction that standard MPR applies, so it can mirror L/R and
  mis-orient oblique/non-axial volumes (geometric mismatch vs standard MPR). The curve points are
  picked on the (oriented) `ImageViewer2D` image but resliced on the unflipped raw volume.
  (alignment report §5)
- *Change:* obtain the volume the way standard MPR does (via `_resolve_mpr_volume_for_route` + the
  same flip/`DirectionMatrix` prep — extract a shared helper from `StandardMPRViewer.__init__`), and
  transform the curve control points into that same frame before reslicing. Bind the engine to the
  geometry contract (or carry the `[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH]` guard tag).
- *Effort:* L · *Risk:* high (geometry) · *Flag:* `AIPACS_CURVED_MPR_GEOMETRY_CONTRACT` (off until
  validated) · *Test:* point-frame + orientation unit tests; geometry-boundary guard · *Validation:*
  **source-build, dental CBCT + an oblique case; verify L/R matches standard MPR**.

**B1 (REVISED). Reuse standard MPR's VTK rendering — do NOT add a QPainter path.** ⭐
- *Problem:* `CurvedMPRPanoramicView` uses `vtkImageViewer2` + an `ImageViewerWrapper` shim — a
  *second* VTK rendering plumbing, separate from standard MPR's `vtkImageResliceMapper`/`vtkImageSlice`
  panes. (The earlier idea of a QPainter/FAST display is **withdrawn** — it would diverge from
  standard MPR, which is the sanctioned VTK MPR path; see alignment report §3 and the verdict.)
- *Change:* build the curved/cross-section panels with the **same VTK pane construction standard MPR
  uses** (`QVTKRenderWindowInteractor` + `vtkRenderer` + reslice mapper/`vtkImageSlice` +
  `cleanup()`/`Finalize()` lifecycle), fed the curved reslice output. Retire the `ImageViewerWrapper`/
  bespoke `CurvedMPRInteractorStyle` shim in favor of the standard MPR interactor styles where they fit.
- *Effort:* L · *Risk:* med (keep the legacy `vtkImageViewer2` path as fallback) · *Flag:*
  `AIPACS_CURVED_MPR_STD_RENDER` (off until validated) · *Test:* offscreen — asserts the panes are
  built via the shared MPR pane helper · *Validation:* **source-build, FAST and V1/VTK**.
- *Note:* the FAST-rule concern that originally motivated a QPainter display is **moot** — standard
  MPR itself instantiates VTK render windows by design; an explicitly-opened MPR is exempt from the
  2D-stack-viewer rule.

**B2. Replace the 100 ms polling reference line with an event/overlay update.**
- *Problem:* The reference line syncs via a 100 ms `QTimer` poll of `GetSlice()` — wasteful and
  the source of the UAF the teardown now contains. (review §6.2)
- *Change:* If B1 lands, draw the reference line as a QPainter overlay updated on the
  slice-changed signal (no timer). If staying on VTK, drive it from a VTK slice observer instead
  of a timer. Either way the timer disappears.
- *Effort:* M · *Risk:* low–med · *Flag:* folds into `AIPACS_CURVED_MPR_QT_DISPLAY` / a
  `AIPACS_CURVED_MPR_REFLINE_SIGNAL` · *Test:* reference-line update fires without a timer ·
  *Validation:* source-build (scroll cross-section, line tracks).

**B3. Non-destructive result layout (stop wiping all viewports).**
- *Problem:* `_show_curved_mpr_result` calls `cleanup_all_viewers()` + `lst_nodes_viewer.clear()`
  and rebuilds the grid to 1×1 — destroying any open MPR and every other cell, with no restore.
  (review §0.4 / §9)
- *Change:* Open the result in a **dedicated cell or tab** (or snapshot + restore the prior
  layout on close). Must coordinate with `_pw_viewers`/the viewer controller — **do not** alter
  `cleanup_all_viewers` itself (shared); add a curved-MPR-specific placement path.
- *Effort:* L · *Risk:* **high** (touches layout/`selected_widget`/NodeViewer lifecycle) · *Flag:*
  `AIPACS_CURVED_MPR_DEDICATED_CELL` (off until validated) · *Test:* assert other NodeViewers
  survive · *Validation:* **source-build, multi-viewer + multi-study**.

**B4. Converge the duplicate `CurvedMPRGenerator` name.**
- *Problem:* Two classes share the name (zeta engine vs legacy advanced-viewer); documented but
  not renamed. (review §0.2)
- *Change:* Rename the legacy `curved_mpr/curved_mpr_module.py::CurvedMPRGenerator` →
  `LegacyAdvancedCurvedMPRGenerator` and update its only consumer (`viewer_2d.py`). Defer until a
  viewer_2d touch is already planned (don't perturb the advanced viewer just for this).
- *Effort:* M · *Risk:* med (advanced-viewer path) · *Flag:* n/a (rename) · *Test:* import test ·
  *Validation:* source-build advanced-viewer curved MPR.

### Theme C — Performance

**C1. Move generation off the GUI thread + real progress.** ⭐
- *Problem:* Generation (N reslices; panoramic up to ~500) runs synchronously on the GUI thread
  with only a wait cursor — the UI freezes. (review §7; research §1.1/§4)
- *Change — reuse existing patterns:* run `generate_curved_mpr` / `generate_panoramic_view` in a
  worker (mirror `modules/download_manager/ui/widget/_dm_workers.py` `WorkerPool` or
  `modules/upload_manager/worker.py`; or the home panel's `_schedule_ui_coro` fire-and-forget),
  marshal the resulting `vtkImageData` back to the GUI thread for display. Drive a progress
  bar/overlay from the engine's existing per-frame progress (reuse the viewer loading-overlay
  infra). Note `make_pixmap_from_bytes`/Qt objects stay main-thread-only.
- *Effort:* L · *Risk:* med (threading + VTK object handoff) · *Flag:*
  `AIPACS_CURVED_MPR_ASYNC_GEN` (off until validated) · *Test:* worker returns image; no GUI calls
  off-thread · *Validation:* **source-build (responsiveness on a big arch)**.

**C2. Sane cost caps + light caching.**
- *Problem:* `num_positions` auto-scales up to 500; the spline/frames recompute from scratch each
  call. (review §7/§8)
- *Change:* Cap/scale `num_positions` by FOV/path length with a quality setting; cache the
  spline+frames so re-running panoramic vs curved doesn't rebuild them.
- *Effort:* M · *Risk:* low · *Flag:* `AIPACS_CURVED_MPR_COST_CAPS` · *Test:* count reslice calls ·
  *Validation:* source-build timing.

### Theme D — Clinical feature parity (from research Part 1; sequence after B/C)

**D1. Cross-section slice navigation slider.**
- *Problem:* No slider/buttons — navigation relies on the VTK interactor or a toolbar stack tool.
  (review §4) Research shows step-through cross-sections are core.
- *Change:* Add a `QSlider` (and wheel) bound to `set_slice` (+ reference-line update). Trivial if
  B1's QPainter viewer is used (it already has slice plumbing).
- *Effort:* S–M · *Risk:* low · *Flag:* `AIPACS_CURVED_MPR_SLICE_SLIDER` · *Test:* slider→slice ·
  *Validation:* source-build.

**D2. Measurements/annotations on curved + panoramic views.** ⭐
- *Problem:* The curved MPR has **no measurement tools** (only a `widgets_by_slice={}` stub) —
  research lists linear/angular measurement as table-stakes. (review §8)
- *Change — reuse existing tooling:* wire `modules/mpr/zeta_mpr/mpr_measurement_tools.py`
  `MPRMeasurementTools` (ruler/angle/caption/arrow, slice-bound visibility) into the curved-MPR
  viewports. On the VTK path it attaches to the renderer directly; on the QPainter path (B1)
  reimplement ruler/angle as QPainter overlays (the viewer already paints annotations).
- *Effort:* M (VTK path) / L (QPainter path) · *Risk:* low–med · *Flag:*
  `AIPACS_CURVED_MPR_MEASURE` · *Test:* measurement count API · *Validation:* source-build, verify a
  known length.

**D3. Adjustable focal-trough width + cross-section thickness/spacing/interval.**
- *Problem:* `slice_size=150.0` and `num_slices` are hardcoded in
  `_generate_curved_mpr_from_points`; research shows trough width and slice interval are
  user-controlled in commercial tools. (review §3; research §1.1/§1.2)
- *Change:* Add controls in the path-builder panel (`_show_curved_mpr_panel`) feeding the existing
  `slice_width/height/num_slices` + panoramic `slice_thickness_mm`. No engine change — just expose
  params.
- *Effort:* M · *Risk:* low · *Flag:* `AIPACS_CURVED_MPR_PARAM_UI` · *Test:* params reach the engine ·
  *Validation:* source-build.

**D4. IAN / mandibular-canal overlay on panoramic + cross-sections.** ⭐ (highest clinical value)
- *Problem:* No nerve overlay — the single most valuable dental-CBCT safety feature; the
  curve-tracing UI for this *already exists* (the same point-collection the arch uses). (research
  §1.3/§4.2)
- *Change:* Let the user trace a second polyline (the canal) reusing the existing point-collection
  (`enable_curved_mpr_mode` / `_add_curved_mpr_point` on `ImageViewer2D`), then project it onto the
  panoramic (a polyline overlay) and mark its intersection on each cross-section. Pure overlay —
  no change to reconstruction. Later: AI auto-tracing (open models reach Dice ~0.95).
- *Effort:* L · *Risk:* med (new interaction) · *Flag:* `AIPACS_CURVED_MPR_CANAL_OVERLAY` · *Test:*
  overlay projects to expected pixels on a synthetic case · *Validation:* **source-build, dental
  CBCT**.

**D5. (Stretch / later) AI assists.**
- Auto-arch detection (enamel MIP → centerline) and auto-canal tracing, buildable on open
  models/datasets (DentalSegmentator/nnU-Net, ToothFairy2). Carries 510(k)/CE weight if positioned
  as diagnostic. Park behind a clearly-labeled experimental flag; out of scope for near-term.

---

## 2. Suggested sequencing

**Now (safe, high value, mostly offscreen-testable):** A1, A5, D1 — plus finish validating the
already-landed teardown on the source build.

**Next (the architectural wins; each flag-gated, needs source-build validation):**
B1 (FAST-safe QPainter display) → B2 (drop the polling timer) → C1 (async generation + progress)
→ D2 (measurements) → D3 (parameter UI).

**Later (higher risk / higher value, after the above prove out):**
B3 (non-destructive layout), A2/A3/A4 (geometry correctness — needs careful clinical validation),
D4 (canal overlay), B4 (rename), C2 (cost caps), D5 (AI).

Rationale: B1 is the keystone — it removes the FAST-rule violation *and* unlocks the cheap wins
(slider, reference-line overlay, eventually QPainter measurements) because `qt_slice_viewer`
already provides slice plumbing, overlay lines, and annotations.

---

## 3. Repo-fit & process notes

- **Flag convention:** every behavior change above gets a default-… flag. Per project style,
  *correctness/safety* fixes can ship default-on once validated; *new render/layout paths*
  (B1/B3/C1) should ship **default-off** until a source-build pass, then flip. Legacy path stays as
  the kill switch.
- **Guard tests:** extend `tests/code/viewer/test_curved_mpr_teardown.py` (or add siblings) as
  source-pin tests (no PySide6/VTK) for each flag + invariant, so they run in the offscreen lane.
- **Plugin mirroring:** the curved-MPR files are **not** plugin-mirrored; `qt_slice_viewer.py`
  (FAST viewer) **is** in the viewer plugin package — if B1 edits it, run
  `tools/dev/sync_plugin_mirrors.py` + `verify_plugin_mirrors.py`.
- **Clinical isolation (do not regress):** the module must keep operating on the **active
  viewport's volume only** and must not start resolving studies — that keeps it outside the
  cross-patient / multi-study guards (`docs/reports/CROSS_PATIENT_STUDY_MIXING_*`,
  `unified-patient-study-pipeline.md`). Any layout work (B3) must not orphan other patients' cells.
- **Testing lanes:** offscreen pytest is the pre-filter; **all VTK/render/layout items REQUIRE the
  Windows source-build clinical lane** (`docs/AIPACS_LAUNCH_CONTROL_RUNBOOK.md`). Note the FUSE
  mount served stale copies of large edited files this session — re-run the offscreen suite on a
  fresh sandbox or on Windows.

---

## 4. Invariants to protect (carry-over from the review)

- Keep the Dental import path `modules.mpr.zeta_mpr.curved_mpr` (the engine with
  `generate_panoramic_view`).
- `is_vtk_widget()` must keep accepting the curved-MPR result cell (or a QPainter equivalent) so
  toolbar tools stay enabled.
- Point picking requires the non-FAST `ImageViewer2D` (renderer + `vtkWorldPointPicker`); don't
  silently enable a broken flow on the FAST bridge — **note:** a fuller fix is to give the FAST
  path a real picking route, which D4/B1 make more attractive.
- Keep the `_add_curved_mpr_point` monkeypatch restore symmetric; keep the teardown
  (`AIPACS_CURVED_MPR_TEARDOWN`) intact.
- Don't alter reconstruction math (A2/A3/A4) without dental-CBCT validation.

---

## 5. One-paragraph recommendation

The highest-leverage next step is **B1 — render the curved/panoramic output through the existing
`qt_slice_viewer` QPainter widget instead of VTK render windows.** It resolves the only
architectural rule the module currently breaks (FAST + VTK render windows), it eliminates the
polling-timer/UAF surface (B2) rather than just containing it, and because that widget already
ships slice navigation, overlay reference lines, and annotation painting, it makes the cheap
clinical wins (D1 slider, D2 measurements) almost free. Pair it with **C1 (async generation)** so
the reconstruction stops freezing the UI, and **D4 (canal overlay)** for the biggest clinical
differentiator. Everything is flag-gated, the legacy VTK path stays as the kill switch, and each
render/layout/geometry change goes through the Windows source-build lane before its flag flips on.
