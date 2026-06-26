# S4B — VTK / Decoded-Volume Cache Architecture (design report)

**Status:** design (no code yet) · **Date:** 2026-06-26 · **Owns:** the S4 "speed win" of
`VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md` (§ S4 / S4b).
**Scope:** define the cache-layer separation, ownership/reuse/invalidation rules, and the access
patterns for the two VTK scenarios, so the build-once shared VTK volume can be wired in safely
(flag-gated, default-off, clinical-lane-validated).

This report is grounded in a four-area source inspection (file:line evidence in §2). It does **not**
change behavior; it is the blueprint S4b implements in staged, flag-gated commits.

---

## 0. The two scenarios (must both work)

- **Scenario 1 — full viewer switch to ADVANCED (VTK/SimpleITK).** The user flips the whole 2D viewer
  from FAST to Advanced; every open series reloads in the VTK backend.
- **Scenario 2 — FAST stays, a VTK module opens.** The 2D viewer remains FAST; the user opens MPR /
  Dental Curve MPR / Dental Imaging / Orthogonal MPR / a VTK-input AI tool, which needs a VTK volume.

**Non-negotiable (rule 1):** opening a VTK module must NOT convert the FAST 2D viewer to VTK. FAST
stays FAST; the VTK volume is a *separate, shared* representation built on demand.

---

## 1. Executive findings (why S4B is needed)

The disk DICOM cache is a clean single source of truth, and the **in-process consumers are mostly
correct read-only reusers** of the active viewer's volume handle — but there is **no shared decoded-
volume cache**, so every VTK consumer that needs real scalars **rebuilds the volume from disk**, and
the same series is built up to **three** times by three different builders with two different geometry
derivations. Concretely:

1. **FAST stores a scalar-less / 1-slice stub** as the series' `vtk_image_data`
   (`image_io.py:2919-2921`; the real FAST pixels live in `PyDicomLazyVolume`'s per-slice memmap,
   `pydicom_lazy_volume.py:140/306`). So a VTK consumer cannot simply reuse the stored handle.
2. **Scenario 1 (Advanced switch) re-reads every DICOM from disk** via SimpleITK
   `ImageSeriesReader.Execute()` (`image_io.py:3310`, `_execute_series_reader:150`) then
   `convert_itk2vtk()` builds a fresh VTK volume (`utils.py:173-274`). ~6-9 s per MR series.
3. **Scenario 2 (Standard/Dental MPR) double-builds**: `_resolve_mpr_volume_for_route` detects the
   scalar-less FAST handle and calls `_load_full_vtk_for_mpr` (`toolbar_manager.py:5757-5789`) — a
   **second full decode of all slices from disk** into a new VTK volume, discarding FAST's decode.
4. **Orthogonal MPR has a divergent SimpleITK builder** (`orthogonal/core/volume_loader.py:70-119`)
   with a *different* geometry derivation (native `SetDirectionMatrix`), reachable off the live button.
5. **No build is cached** across consumers or successive opens; **no pin/unpin**, **no shared
   invalidation bus**; one FAST cache (`_series_cache`) is **unbounded**; the same series can
   **decode twice** (preview→full; warmup↔interactive) with no coalescing authority.

The S4a `VolumeCache` (`PacsClient/utils/volume_cache.py`, built + tested, **unused**) — keyed by
`(study_uid, series_uid)`, with decode-coalescing + pin/unpin + one invalidation bus — is the
purpose-built fix. S4B is the architecture for wiring it in as the **one** VTK-volume builder.

---

## 2. Current-state review (answers the 10 required inspection points)

| # | Question | Finding (file:line) | Verdict |
|---|----------|---------------------|---------|
| 1 | Where FAST 2D cache is created | `PyDicomLazyVolume` memmap `pydicom_lazy_volume.py:140`; FAST `_pixel_cache`/`_frame_cache` LRU `lightweight_2d_pipeline.py:646-647` (cap 192/512 `:218-237`); disk pixel cache `:52` (`decode-v4`) | OK, FAST-local |
| 2 | Where Advanced Viewer loads data | Settings → `_pw_metadata.py:101 apply_viewer_backend_config` → `_vc_backend.py:113 apply_backend_setting_to_open_viewers` → `change_series_on_viewer` → `_vc_load.py:796 load_single_series_by_number(viewer_backend=vtk_simpleitk, allow_lazy_backend=False)` → SimpleITK `Execute()` `image_io.py:3310` → `convert_itk2vtk` `utils.py:173` | **RE-READ + REBUILD** from disk; no FAST reuse |
| 3 | Where MPR builds VTK volume | Reuse handle from `lst_thumbnails_data['vtk_image_data']` via `_resolve_mpr_volume_for_route` `toolbar_manager.py:5715`; **but** scalar-less FAST handle → `_load_full_vtk_for_mpr` `:5766` full re-decode; `StandardMPRViewer(vtk_image_data=…)` `:5398` | **REUSE → conditional REBUILD** |
| 4 | Where Dental MPR builds VTK volume | Engine `zeta_mpr/curved_mpr.py:806 ResliceEngine(image_data)` consumes the passed VTK volume (reslice only); volume sourced from the same MPR route (`_launch_dental_curve_vtk_host` → `StandardMPRViewer`) | **REUSE** (inherits MPR build) |
| 5 | Where Advanced Analysis modules receive data | Dental Imaging `core/volume_binder.py:23 get_active_image_data` = active `vtk_image_data` (read-only `DentalVolume`); non-active → `from_series` `_pw_advanced.py:1224`. Advanced MPR (3D Slicer) + Stitching = **external process**, dicom_dir re-read `_pw_advanced.py:809/1002`. Eagle Eye AI = own VTK tab `ai_imaging/.../patient_widget.py:60` | **REUSE** in-proc; **SEPARATE** for external/AI |
| 6 | VTK volumes rebuilt unnecessarily? | **Yes**: (a) Advanced switch re-reads all DICOM; (b) MPR `_load_full_vtk_for_mpr` second full decode; (c) Orthogonal SimpleITK third builder; (d) Dental non-active `from_series`; (e) `canonicalize_volume` re-reads all DICOM headers per open `_mpr_canonicalize.py:215` | **REBUILD redundancy** |
| 7 | VTK modules bypass the unified pipeline? | **No** for downloads — all read disk `SOURCE_PATH/<study_uid>/<series>/` (`config.py:25`, `data_paths.py:55`), no re-download. External processes (Slicer/Stitching) re-read by design (process boundary) | Disk-unified; re-decode, not re-fetch |
| 8 | Cache invalidation safe? | **Ad-hoc, no shared bus**: `_invalidate_series_caches` `_vc_cache.py:365` must be called manually each grow tick and skips `_disk_count_cache`/`_series_number_to_index`; ZetaBoost has its own `invalidate_series` `_zb_cache.py:261` | **Fragile** (C1) |
| 9 | Partial series handled correctly? | FAST grows progressively (`pydicom_lazy_volume.grow()` `:366`); VTK builders read the *current on-disk set* and have no grow-aware invalidation — a VTK volume built mid-download is not refreshed until manually invalidated | **Gap** (see §6) |
| 10 | Memory controlled? | Bounded: `_hot_series_cache` ≤3, FAST LRUs, ZetaBoost L1 byte-budget + L2 ~20 GB. **Unbounded**: `_series_cache` `:155`, `_metadata_flat_cache`, `_series_number_to_index`. **No single owner, no pin/unpin** → displayed series can be evicted from L1 while shown, or held in 3 layers at once | **Partial / no owner** |

**Geometry contract:** FAST / Standard MPR / Dental Curve / Dental Imaging share **one** contract —
`DirectionMatrix` field-data set in `pydicom_lazy_volume.py:316-333`, read by `canonicalize_volume`
(`_mpr_canonicalize.py:266`). The Advanced 2D `convert_itk2vtk` (`utils.py:186-225`) and the
Orthogonal SimpleITK loader (`volume_loader.py:392-408`) derive geometry **differently** (ITK/native
`SetDirectionMatrix`). Converging on the one field-data contract is part of S4B's conversion layer.

---

## 3. The four cache layers (the requested separation)

```
Layer 1  DICOM File Cache          (raw .dcm on disk)            — EXISTS, unchanged
Layer 2  Decoded 2D Cache          (FAST per-slice frames)       — EXISTS, FAST-only, unchanged
Layer 3  VTK Volume Cache          (shared whole-series volume)  — NEW (S4a VolumeCache, wire in S4b)
Layer 4  Module-Specific Cache     (per-tool preprocessing)      — per module, isolated, short-lived
```

### Layer 1 — DICOM File Cache (source of truth)
- **Contents:** original downloaded `Instance_*.dcm`.
- **Location / key:** `SOURCE_PATH/<study_uid>/<series_number>/` (`config.py:25` aliases
  `DICOM_IMAGES_DIR`, `data_paths.py:55`). Patient-blind, keyed by `study_uid`.
- **Owner / writer:** the Zeta download subprocess only, atomically (`*.part` → `os.replace`,
  `socket_client.py:1597-1600`). **No other layer ever writes here.**
- **Role:** the *only* source of truth. Every higher layer is derived and disposable.

### Layer 2 — Decoded 2D Cache (FAST viewer, unchanged, FAST-only)
- **Contents:** FAST viewer-ready per-slice frames for fast scroll: `PyDicomLazyVolume` memmap
  (slice-index keyed, `_load_lock`), `_pixel_cache`/`_frame_cache` LRU, disk pixel cache.
- **Owner:** `Lightweight2DPipeline` / `ViewerController` (GUI + decode workers).
- **Rule:** stays **slice-index keyed and VTK-free** — this is what keeps FAST fast (rule 1, 8). S4B
  does **not** route 2D scrolling through the VTK cache. Layer 2 *may feed* Layer 3's builder
  (reuse already-decoded slices) but is never replaced by it.

### Layer 3 — VTK Volume Cache (NEW, shared, the heart of S4B)
- **Contents:** one complete VTK volume (`vtkImageData` + its numpy/memmap backing) per series, with
  correct **spacing / origin / orientation / DirectionMatrix / slice order / patient coordinate
  system** (the one field-data contract).
- **Implementation:** `PacsClient/utils/volume_cache.py` (`VolumeCache`, S4a — built + tested).
- **Key:** the **stable identity `(study_uid, series_uid)`** (`make_key`) — multi-study number
  collisions are structurally impossible (closes the bare-`series_number` class).
- **Shared by (in-process VTK consumers):** Advanced Viewer (Scenario 1), Standard/Zeta MPR, Dental
  Curve MPR, Dental Imaging, Orthogonal MPR (once converged), in-process AI/segmentation.
- **NOT shared by (by design):** external-process tools (3D Slicer Advanced MPR, Stitching) — they
  live in another process and re-read disk; that's acceptable and out of scope.
- **Lifecycle:** built **on demand** when the first VTK consumer needs it; **built once** (decode-
  coalescing); **pinned** while displayed; **LRU/byte-evicted** when not; **invalidated** on
  server-grew / series change.

### Layer 4 — Module-Specific Cache (isolated, temporary)
- **Contents:** per-tool derived data that is NOT a faithful copy of the source volume — curved/
  panoramic reconstruction output (`curved_mpr.py` reslice outputs), resampled volumes
  (`orthogonal/.../resampler.py`), segmentation masks (`segmentation_tools.py` output), AI seg input.
- **Owner:** each module; created on demand, freed on module close.
- **Rule (7):** module caches are **outputs**; they must **never** be written back into Layer 3 or
  overwrite a shared volume. (Verified today: `DentalVolume` is read-only by contract
  `volume.py:34`; segmenters/curved-MPR emit *new* output volumes — keep it that way.)

---

## 4. Source of truth per layer

| Layer | Source of truth | Derived from | Disposable? |
|-------|-----------------|--------------|-------------|
| 1 DICOM files | **itself** (authoritative) | server download | no (clinical data) |
| 2 Decoded 2D | Layer 1 | decode of `.dcm` | yes (re-decodable) |
| 3 VTK Volume | Layer 1 (pixels) + the geometry contract | decode/convert of `.dcm`, preferably reusing Layer 2 | yes (rebuildable) |
| 4 Module cache | Layer 3 (+ module params) | reslice/resample/segment of the shared volume | yes (recomputable) |

**Invariant:** truth flows **down→up** only (disk → decoded → VTK → module). No upward write-back.
Geometry is *derived once* at Layer 3 from the DICOM headers via the single contract and never
re-derived per module.

---

## 5. Ownership rules

1. **Layer 1** is owned solely by the download manager. No viewer/module writes `.dcm`.
2. **Layer 3 (`VolumeCache`) is a process-wide singleton** owned by a new thin
   `VtkVolumeService` (the only place `get_or_create` / `pin` / `unpin` / `invalidate` are called).
   No module instantiates its own `VolumeCache`.
3. **One builder.** The `factory` passed to `get_or_create` is the **single conversion layer**
   (`build_vtk_volume(study_uid, series_uid, series_path)`); it replaces FAST-stub +
   `_load_full_vtk_for_mpr` + Advanced `convert_itk2vtk` + Orthogonal SimpleITK as the *only* way a
   shared VTK volume is built. (Orthogonal's SimpleITK loader converges onto it per the unified-MPR
   directive; external processes are exempt.)
4. **The displayed/active consumer owns a pin.** Whoever shows a volume (Advanced viewport, open MPR,
   open Dental workspace) holds a `pin`; it `unpin`s on close/switch-away. Eviction never touches a
   pinned entry.
5. **Module caches (Layer 4)** are owned and freed by the module; never shared, never written up.

---

## 6. Reuse rules

1. **Prefer Layer 2 over Layer 1.** The conversion-layer `factory` first tries to assemble the VTK
   volume from the FAST `PyDicomLazyVolume` already-decoded slices (the `materialize_lazy_volume`
   pattern, `dental_imaging/core/volume_binder.py:42`) — materializing only the not-yet-decoded
   slices from disk — instead of a blind full SimpleITK re-read. Falls back to disk decode when FAST
   has not opened the series. (This is the re-read elimination for Scenarios 1 + 2.)
2. **Build once per valid series (acceptance 4).** `get_or_create((study_uid, series_uid), factory)`
   coalesces concurrent requests — the Advanced switch + an MPR open + a dental open on the same
   series share **one** decode; everyone else waits and shares the result.
3. **Reuse across consumers.** Standard MPR, Dental Curve, Dental Imaging, Orthogonal, and the
   Advanced viewport all call the same `VtkVolumeService.get(study_uid, series_uid)` — the second and
   later consumers get the cached volume, not a rebuild.
4. **Reuse across opens.** Closing then reopening MPR on a pinned/resident series reuses the cached
   volume (no rebuild) until evicted or invalidated.
5. **External processes are exempt** — Slicer/Stitching get a `dicom_dir` and re-read; do not try to
   share an in-process VTK volume across the process boundary.

---

## 7. Invalidation rules (one bus, replaces the ad-hoc set)

1. **Single bus.** Server-grew / series-changed / W-L-geometry-affecting events call
   `VtkVolumeService.invalidate(study_uid, series_uid)` (or `invalidate_study`) — the one place that
   drops the Layer-3 entry. This replaces the scattered `_invalidate_series_caches` +
   `zeta_boost.invalidate_series` + per-cache invalidators for the VTK layer.
2. **Server-grew (partial → fuller).** When the DM reports the series grew (the existing
   `right_panel_cache_gate` / disk-count grew signal), invalidate the VTK entry so the next consumer
   rebuilds from the larger set. A **pinned, currently-displayed** volume is invalidated **lazily**:
   mark stale, rebuild on next idle/await, never yank pixels out from under a live render (see §9
   lifetime). This closes the partial-series gap (review point 9).
3. **Series identity change** (re-import, cross-patient correction) → `invalidate` that key.
4. **Module caches** subscribe to the same bus: when Layer 3 for a series is invalidated, dependent
   Layer-4 entries (that series' curved/resampled/seg data) are dropped too.
5. **Safety:** invalidation only *drops the cache reference*; the actual memory frees when the last
   VTK consumer releases it (unpin + GC of the `vtk_image_data` backing) — never an eager unmap of a
   buffer a live `vtkImageData` still points at.

---

## 8. VTK module access pattern (Scenario 2 — FAST stays fast)

```
FAST 2D viewer running (Layer 2 active)
   │  user opens MPR / Dental MPR / Dental Imaging / Orthogonal / AI-VTK
   ▼
module asks  VtkVolumeService.get_or_build(study_uid, series_uid, series_path, pin=True)
   │
   ├─ cache HIT  → return shared vtkImageData (REUSE)               ← built-once, instant
   └─ cache MISS → factory runs OFF-THREAD:
            prefer FAST PyDicomLazyVolume slices → materialize gaps → assemble VTK volume
            (fallback: decode from SOURCE_PATH)  → set the ONE geometry contract
        → store + pin → return
   ▼
module renders from the shared volume; emits its own Layer-4 outputs (isolated)
on module close → VtkVolumeService.unpin(study_uid, series_uid)
```

- The FAST viewer is **untouched** — it keeps scrolling on Layer 2; the module gets Layer 3. Rule 1
  satisfied.
- Standard MPR / Dental Curve / Dental Imaging already *want* a passed-in `vtkImageData`; S4b changes
  only **where that volume comes from** (the service, not `_load_full_vtk_for_mpr`).
- Module-specific reconstruction (panoramic, resample, seg) stays in Layer 4, keyed by
  `(study_uid, series_uid, module, params)` — isolated (rule 7).

## 8b. Advanced Mode access pattern (Scenario 1 — full switch)

```
user switches whole viewer FAST → ADVANCED (apply_backend_setting_to_open_viewers)
   ▼
for each open series:  change_series_on_viewer(... backend=vtk_simpleitk ...)
   ▼
Advanced load asks  VtkVolumeService.get_or_build(study_uid, series_uid, series_path, pin=True)
   │  (SAME service + SAME factory as Scenario 2 — no separate Advanced builder)
   ▼
bind the shared vtkImageData into the Advanced VTK viewport (convert layer only if a
   different representation is genuinely required — controlled, not a blind re-read)
   ▼
switch back to FAST → unpin; FAST resumes on Layer 2 (still resident, instant)
```

- Advanced mode stops being a **private** SimpleITK re-read; it becomes the **first pin** on the
  shared Layer-3 volume. If FAST already opened the series, the Advanced switch reuses those pixels
  (no full disk re-read) — the headline Scenario-1 win.
- Still through the unified disk path; still no re-download (rule 2, 3).

---

## 9. Memory limit strategy (bounded — acceptance 7)

- **Layer 3 is the one bounded VTK budget.** `VolumeCache(max_entries=N, max_bytes=B)`:
  - `max_bytes` is the real control (VTK volumes are large: a 300-slice CT ≈ 180 MB). Recommend a
    config-driven budget (default ~1.5-2 GB, env `AIPACS_VTK_VOLUME_CACHE_MB`), tuned to the
    workstation. `max_entries` as a secondary guard (e.g., 6-8).
  - **Pin the active**: the displayed Advanced volume + every open module's series are pinned, so
    they are *never* evicted mid-view (closes the "evicted while displayed → re-decode" hazard).
  - **LRU-evict the unpinned** down to budget; eviction drops the cache's strong ref → memory frees
    when the last `vtkImageData` referencing the backing is gone.
- **Single owner.** `VtkVolumeService` is the one eviction authority (replaces the never-built
  `MemoryCacheManager`); no more "held in three layers at once".
- **Layer 2 stays separately bounded** (FAST LRUs already capped); **Layer 4** is small and freed on
  module close. **Fix the unbounded Layer-2 dicts** (`_series_cache` etc.) as a follow-up — out of
  S4b's critical path but tracked.
- **Triple-residency removed:** for a VTK consumer, the volume lives once in Layer 3 (pinned), not
  re-copied per module.

## 9b. Background build strategy (the B1 stall fix)

- **`factory` runs on a worker QThread**, never the GUI thread. `get_or_create` already runs the
  factory outside the cache lock; S4b wraps the *call* in the existing async-load worker
  (`_schedule_async_load_and_switch`) so the heavy decode/convert is off-GUI.
- Only the **cheap VTK hand-off** returns to the GUI thread: `SetScalars` + first `Render`. That is
  what removes the ~2.8-4.4 s `_finalize_progressive_series` freeze (B1, task #39).
- **Coalescing** means a burst (Advanced switch of N viewports, or rapid MPR opens) triggers at most
  one decode per series; the rest await the shared result.
- **Cancellation:** the build worker is registered with the S5 `CancellationRegistry` (by
  `ViewerHandle`), so a tab close / superseding switch cancels an in-flight build before it touches a
  dead widget (reuses the just-shipped S5b path).

---

## 10. The conversion layer + geometry contract (acceptance 6)

One function — `build_vtk_volume(study_uid, series_uid, series_path)` — is the **controlled
conversion layer** the user asked for. It MUST, every time:

1. Resolve the canonical ordered slice list from `SOURCE_PATH/<study_uid>/<series_number>/` (the
   multi-study entry authority `resolve_entry_study_location`), preferring already-decoded FAST
   slices.
2. Build `vtkImageData` with the **single geometry contract** used by FAST/Zeta-MPR:
   `SetSpacing`/`SetOrigin` from `ImagePositionPatient`, the `DirectionMatrix` field-data from
   `ImageOrientationPatient` (`_attach_direction_field_data`, `pydicom_lazy_volume.py:1112`), correct
   **slice order / IPP sign** (`ZetaAnatA`), patient coordinate system preserved.
3. Pin the numpy/memmap backing into the volume (`_numpy_backing_store`) so VTK's zero-copy scalars
   never dangle.
4. Be the place where the **Orthogonal SimpleITK derivation converges** onto the field-data contract
   (no second geometry convention).

This guarantees acceptance 6 (geometry correct + identical across Advanced, MPR, Dental, Orthogonal)
because geometry is derived **once, one way**.

---

## 11. The lifetime hazard (must be designed for, not bolted on)

VTK scalars point **zero-copy** into a numpy `np.memmap` backed by a temp file
(`pydicom_lazy_volume.py:140`, `numpy_to_vtk(..., deep=False)` `:330/468`). The buffer must outlive
every `vtkImageData` that references it — the code already keeps `_numpy_backing_store`,
`_old_volumes_keepalive` (`:482`), and defers mmap unmap to GC (`close()` `:546-604`); dental pins
`_lazy_owner` (`_pw_advanced.py:1244`).

**Design consequence for the cache:**
- The cache entry holds the **strong ref** that keeps the backing alive; **pin = "a live VTK consumer
  references this"**.
- Eviction/invalidation only **drops the cache's ref**; the memory frees when the consumer's
  `vtkImageData` is also released. **Never** unmap on invalidate.
- A pinned (displayed) volume is invalidated **lazily** (mark stale → rebuild on next await), never
  yanked mid-render. This is the use-after-free guard and the reason S4b is staged last.

---

## 12. Staged rollout (flag-gated, discipline per the plan)

Per `VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md` §4, land S4b in **read-only-safe slices**, each
default-OFF with a kill switch and a guard test, validated on the Windows source build before flip:

- **S4b-1 — `VtkVolumeService` + SHADOW.** ✅ **LANDED 2026-06-26.**
  `PacsClient/utils/vtk_volume_service.py` (pure stdlib + threading, no VTK/Qt at import): the
  process-wide owner over the S4a `VolumeCache` — `get_or_build`/`pin`/`unpin`/`invalidate`
  (delegating to the coalescing cache, the wiring surface for S4b-2/3) + a `vtk_geometry_signature`
  pure helper + the `observe_vtk_build(...)` shadow that records each legacy VTK build under
  `(study_uid, series_uid)` and reports a **would-be-avoided rebuild** or a **geometry divergence**.
  Flag `AIPACS_VTK_VOLUME_CACHE` (default-OFF → helper no-ops, no cache allocated, byte-identical).
  First shadow wire: `toolbar_manager.py::_resolve_mpr_volume_for_route` logs `[VTK-VOLUME-SHADOW]`
  when the MPR `_load_full_vtk_for_mpr` rebuild fires (the headline double-build). Guard
  `tests/code/ui_services/test_vtk_volume_service.py` (15 green headless). No consumer reads a cached
  volume yet.
- **S4b-2 — route Scenario 2 MPR/Dental opens through the service.** ✅ **CODE LANDED 2026-06-26
  (default-off; NEEDS live validation before flip).** `toolbar_manager.py::_resolve_mpr_volume_for_route`
  now routes the full-volume build through `build_or_get_mpr_volume(study_uid, series_uid, builder)`
  (`vtk_volume_service.py`): with `AIPACS_VTK_VOLUME_CACHE` on it builds **once per
  `(study_uid, series_uid)`** (decode-coalesced) and **reuses** across MPR/Dental opens (the
  `_load_full_vtk_for_mpr` double-build removed); with `AIPACS_VTK_VOLUME_CACHE_SHADOW` on it measures
  without caching; **both off → calls `_load_full_vtk_for_mpr` directly (byte-identical)**. `series_uid`
  is the globally-unique DICOM SeriesInstanceUID (`thumb_series_meta['series_uid']`), so the key is
  correct even with an empty study_uid. **pin deferred to S4b-4** — the volume's lifetime stays
  governed by the CALLER's own reference exactly as today (the cache holds an additional ref; a
  consumer keeping its volume is unaffected by eviction), so there is no eviction-of-live hazard in
  this cut. A failed build returns `None` (never cached) and a defensive `try/except` falls back to the
  direct builder so the cache can never block MPR. Guard `tests/code/ui_services/test_vtk_volume_service.py`
  (15 tests; the 14 functional incl. build-once-reuse / shadow / None-not-cached / passthrough run
  green headless). **Live validation needed:** Standard MPR + Dental Curve + Dental Imaging on FAST,
  multi-study, slow-link; with `AIPACS_VTK_VOLUME_CACHE_SHADOW=1` confirm `[VTK-VOLUME-SHADOW]` shows
  the rebuilds + **zero geometry divergence**, THEN with `AIPACS_VTK_VOLUME_CACHE=1` confirm the volume
  is reused (one build) and the **reopen does not show a stale/dead volume** (the cross-open
  `vtkImageData` lifetime — the one thing the sandbox cannot prove).
- **S4b-3a — Advanced build OBSERVE + cross-builder identity.** ✅ **CODE LANDED 2026-06-26
  (default-off; measurement only).** Cross-builder risk: the Advanced builder (`convert_itk2vtk`)
  derives geometry differently from MPR's, and the two sites key the UID under DIFFERENT metadata
  names (`image_io` `series_instance_uid` vs toolbar `series_uid`, some truncated for logging). So
  before any Advanced↔MPR sharing: (1) NEW pure identity helpers in `vtk_volume_service.py` —
  `normalize_series_uid` (rejects <16-char truncations → "" = safe no-key) / `series_uid_from_meta` /
  `study_uid_from_meta` — so BOTH sites resolve the SAME full SeriesInstanceUID (the MPR wire now uses
  them too); (2) `image_io.py::load_single_series_by_number` (DB path) calls `observe_vtk_build(...,
  source="advanced_itk2vtk")`. With `AIPACS_VTK_VOLUME_CACHE_SHADOW=1` the shadow now sees BOTH
  `mpr_full_rebuild` and `advanced_itk2vtk` builds of the same series and logs `[VTK-VOLUME-SHADOW]
  GEOMETRY DIVERGES` if they disagree. Observe-only + default-off + try/except → byte-identical
  Advanced loads. Guard: identity-helper + cross-builder-key tests (authoritative; 14 functional
  green headless; FUSE blocks the source-pins in sandbox).
- **S4b-3b — actually route the Advanced build through `get_or_build`** (reuse the cached volume +
  FAST slices to kill the SimpleITK re-read) stays GATED on: S4b-2 live-validated AND the S4b-3a
  shadow showing **zero geometry divergence** on a live FAST↔Advanced↔FAST round-trip +
  **close-during-build** (S5 cancellation).
- **S4b-4 — enable eviction + the invalidation bus**, retire the bare-`series_number` VTK caches
  (ZetaBoost L1 dedup → `VolumeCache`) and converge Orthogonal's SimpleITK builder. This is the
  memory + retirement step — do it last, after the pin discipline has soaked.

Kill switch `=0` at any step restores the legacy builder byte-for-byte. Each step has a guard test
(source-pin + offscreen functional) and must clear `run_with_validation.cmd` + `check_validation.ps1`
+ a Mehr slow-link multi-study pass before flipping default-on.

---

## 13. Acceptance criteria → how the design meets each

| # | Acceptance criterion | How S4B satisfies it |
|---|----------------------|----------------------|
| 1 | FAST viewer stays fast, not VTK-dependent | Layer 2 unchanged + VTK-free; VTK volume is a separate on-demand Layer 3 (rule 1). FAST never routed through VTK. |
| 2 | Advanced reuses downloaded/cached series safely | Scenario-1 path becomes a `get_or_build` + pin on the shared volume, reusing FAST slices; unified disk, no re-download (§8b). |
| 3 | MPR/Advanced-Analysis get a VTK volume without duplicating downloads | All in-proc consumers call `VtkVolumeService.get`; external processes re-read by design only (§6.5). No re-download anywhere. |
| 4 | VTK cache built once per valid series | `get_or_create` decode-coalescing + cross-consumer/cross-open reuse (§6.2-6.4). |
| 5 | Module-specific caches isolated | Layer 4 outputs only, never written up; bus-invalidated with their parent (§3 L4, §7.4). |
| 6 | DICOM geometry correct | One conversion layer, one field-data `DirectionMatrix` contract, Orthogonal converges (§10). |
| 7 | Memory bounded | One `max_bytes`-budgeted `VolumeCache` owner + pin-active/LRU-evict; triple-residency removed (§9). |
| 8 | Invalidation clear and safe | One bus (`VtkVolumeService.invalidate`), lazy for pinned/displayed, drop-ref-not-unmap (§7, §11). |

---

## 14. Out of scope / follow-ups
- Fixing the **unbounded Layer-2 dicts** (`_series_cache` etc.) and the **lock-free C1** writes is a
  parallel cleanup (the architecture review's S1/S2 identity + state work), not S4b's critical path.
- **External-process** consumers (3D Slicer Advanced MPR, Stitching) keep re-reading disk by design.
- **Startup stalls** (B2, task #52) are unrelated to this cache.

**One-line essence:** make **one** `(study_uid, series_uid)`-keyed VTK volume, **built once, off-
thread, reusing FAST's decode**, **pinned while shown**, **shared** by Advanced + every in-process VTK
module, with **one geometry contract** and **one invalidation bus** — and never let the FAST 2D viewer
depend on it.
