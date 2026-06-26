# Unified Pipeline — Shared Infrastructure vs Viewer-Specific Boundary

**Status:** architecture clarification (authoritative boundary) · **Date:** 2026-06-27
**Supersedes the over-reach in** `S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md` §6 rule 1 (see §8 below).

## 0. The principle (as directed)

We unify the **download / file / cache‑coordination / metadata / state / logging** infrastructure
wherever it is *genuinely common*. We do **NOT** merge the **Fast Viewer** and the **Advanced Viewer**
into one implementation. They stay two independent viewer architectures with their own decode, cache,
and render strategies. **Unified ≠ identical** — the two pipelines branch the moment their technical
requirements diverge, and they branch **cleanly and intentionally**.

```
                         SHARED INFRASTRUCTURE  (one implementation)
                                     │
                         ── BRANCH POINT: files-on-disk + identity + state + metadata ──
                                     │
                 ┌───────────────────┴────────────────────┐
                 │                                         │
          FAST VIEWER PIPELINE                      ADVANCED / VTK PIPELINE
          (lazy 2D, Qt raster)                      (full volume, VTK render)
                                                    └─ also feeds the VTK modules
                                                       (MPR, Dental, Orthogonal, AI)
```

---

## 0.1 HARD RULE — complete separation of the three execution domains (NON-NEGOTIABLE)

There are **THREE separate execution domains**, and they must remain **completely separated and never
mixed**:

1. **Fast Viewer** (2D, `pydicom_qt`).
2. **Advanced Viewer** (full VTK mode switch, `vtk_simpleitk`).
3. **VTK modules** (MPR, Dental Curve MPR, **Advanced Analysis / Imaging Analysis**, Orthogonal MPR,
   in-process VTK/AI) — each module is its own domain too.

**This rule OUTRANKS every optimization.** If a unification would blur, couple, or let one domain
interfere with another, the unification is **wrong and must not be done** — keep them separate. We
optimize toward a cleaner structure, but never at the cost of mixing the modes/modules or introducing
interference. Separation and stability win, always.

What "separated, not mixed" means concretely:

- **Separate implementations.** Each domain owns its **decode, cache store, render, lifecycle, and
  state**. No domain's internals are reachable from another — no shared mutable object, no shared
  widget, no cross-domain call into another domain's internals, no shared render/interactor state.
- **No interference.** A bug, slowdown, cache eviction, or teardown in one domain must **not** affect
  another. Any one domain failing must leave the others fully functional.
- **Unify ONLY through the trunk.** The single thing the three domains may share is the
  read-only / coordination **TRUNK** (download, disk files, identity, state-read, metadata,
  invalidation bus, KPIs — §1). Each domain **calls** the trunk; the trunk **never** exposes one
  domain to another. **Unification happens INSIDE the trunk, never across a domain boundary.**
- **Through the trunk, only IMMUTABLE, identity-keyed ARTIFACTS may be shared** (the DICOM files; and —
  only under the strict test in §6.1 — a built VTK volume). Sharing a read-only *artifact* is allowed;
  sharing *implementation, lifecycle, widgets, interactors, or mutable state* is **forbidden**.

Consequences already in force: the Fast "no VTK render windows" rule; the Fast-branch freeze of
2026-06-27 is fixed **inside the Fast branch** (never by routing Fast through Advanced/VTK machinery);
module-specific outputs (panoramic, segmentation, resample) stay isolated and are never written back
into anything shared.

## 1. The shared trunk — what is genuinely common (ONE implementation)

These responsibilities have **no per‑viewer difference** and must be implemented once and reused by
both viewers. Each line is the real owning code.

| Shared responsibility | Owner (code) | Notes |
|---|---|---|
| **Download management** | `modules/download_manager/` (Zeta socket `network/socket_client.py`) | One downloader; writes atomically (`*.part`→`os.replace`). Viewer‑agnostic. |
| **DICOM File Cache (source of truth)** | disk `SOURCE_PATH/<study_uid>/<series_number>/` (`data_paths.py:DICOM_IMAGES_DIR` ← `config.py:SOURCE_PATH`) | The one authoritative copy of pixels. Both viewers read from here. |
| **Identity model** | `PacsClient/utils/viewer_identity.py` (`ViewerHandle`, `SeriesRequest`) | `(patient_id, study_uid, series_uid, viewer_handle)`. The cache key + request token for BOTH viewers. |
| **Per‑series state authority** | `PacsClient/utils/series_state_store.py` (`SeriesStateStore`) | `Requested→Queued→Downloading→PartialOnDisk→Decoding→Displayed`. The shared "where is this series" truth. |
| **Pipeline state / orchestration** | `viewer_request_pipeline.py` (`plan_series_display` / `ensure_series_displayed` chokepoint, S3) | Decides *what a viewport must do* (await / grow / rebuild / noop) — backend‑agnostic; only the **execution** differs per viewer. |
| **Metadata + geometry contract** | series/instance metadata; the `DirectionMatrix` field‑data contract (`pydicom_lazy_volume.py::_attach_direction_field_data`, read by `_mpr_canonicalize.py` and produced compatibly by `utils.convert_itk2vtk`) | Spacing / origin / orientation / slice‑order derived **once, one way** from the headers. Both viewers honor the same patient‑coordinate contract. |
| **Cache COORDINATION** (not the stores) | the **identity keys** + the **invalidation bus** + eviction‑policy ownership | A server‑grew / series‑changed event invalidates *whatever each viewer cached* for that key. This is the coordination layer — see §7. |
| **Logging + KPIs** | `user_data/logs/*` channels, `main_thread_probe`, TTFI/TTFS/TTSSD, the diagnostic emitters | One telemetry vocabulary across both viewers. |

**Cache coordination is shared; cache *stores* are not.** The common layer owns the **keys** (the
stable `(study_uid, series_uid)`), the **state** (`SeriesStateStore`), and **one invalidation bus**.
It does **not** own a single unified cache object — each viewer keeps the cache *store* its decode
strategy needs (§4, §5), and both subscribe to the one bus.

---

## 2. The branch point — exactly where "shared" ends

The trunk ends — and the two viewer pipelines begin — at the moment a series is:

> **files on disk** (`SOURCE_PATH/<study_uid>/<series>/`) **+ identity resolved + state known +
> metadata/geometry available.**

Everything **up to and including** that point is shared. Everything **after** it — *how the bytes are
turned into something on screen* — is viewer‑specific, because that is precisely where the technical
requirements diverge:

- **decode strategy** (lazy per‑slice 2D vs. full 3D volume),
- **cache strategy** (slice‑indexed raster vs. identity‑keyed VTK volume),
- **render technology** (Qt raster vs. VTK).

The branch is a **clean handoff**: the viewer asks the shared layer "give me the disk location +
identity + metadata for this `SeriesRequest`," and then owns everything downstream.

---

## 3. FAST Viewer pipeline (branch A — lazy 2D, Qt raster)

Optimized for instant first image + fast scroll. **VTK‑free by rule.**

- **Decode:** lazy, per‑slice — `modules/viewer/fast/pydicom_lazy_volume.py` (`np.memmap`, decode
  slice‑on‑demand) + `dicom_header_scan.py`.
- **Cache (Fast‑own):** Decoded‑2D — `lightweight_2d_pipeline.py` `_pixel_cache` / `_frame_cache`
  (slice‑index + `(idx,ww,wl)` keyed LRU), the disk pixel cache (`decode-v4`), and the
  `ViewerController` per‑series metadata dicts. **Slice‑indexed, raster, no geometry volume.**
- **Render:** Qt 2D — `modules/viewer/fast/qt_viewer_bridge.py` (`_set_slice_impl`, QImage/QPainter).
- **Backend id:** `pydicom_qt` (`viewer_backend_config.py`, the DEFAULT).

The Fast viewer **never builds a VTK volume** and never depends on the VTK cache. Its only contact
with the trunk is: disk files, identity, state, metadata, KPIs.

---

## 4. ADVANCED / VTK pipeline (branch B — full volume, VTK render)

Optimized for true 3D / reformatting / measurement. Owns the VTK world.

- **Decode:** full‑volume — `image_io.py::load_single_series_by_number` (the `allow_lazy_backend=False`
  path): SimpleITK `ImageSeriesReader.Execute()` → `utils.convert_itk2vtk()` → a `vtkImageData` with
  the shared geometry contract.
- **Cache (Advanced/VTK‑own):** the **VTK Volume Cache** — `PacsClient/utils/volume_cache.py`
  (`VolumeCache`, S4a) fronted by `vtk_volume_service.py` (`VtkVolumeService`, S4b). Identity‑keyed
  `(study_uid, series_uid)`, pin/unpin, decode‑coalescing.
- **Render:** VTK — `vtkImageSlice` / `vtkGPUVolumeRayCastMapper`; backend `vtk_simpleitk`
  (`viewer_backend_config.py:BACKEND_VTK`, selected via `_vc_backend.py`).

### 4.1 The VTK modules live on THIS branch (not a third thing)
MPR (`zeta_mpr/mpr_viewer/widget.py::StandardMPRViewer`), Dental Curve MPR
(`mpr/zeta_mpr/curved_mpr.py`), Dental Imaging (`modules/dental_imaging/`), Orthogonal MPR, and the
in‑process VTK/AI tools are **all VTK‑volume consumers**. A VTK volume is a VTK volume regardless of
which feature asked for it, so they share the **Advanced‑side** VTK Volume Cache — they do **not**
get a separate pipeline, and they have **nothing to do with the Fast cache**. (Module‑specific
*outputs* — panoramic reconstructions, segmentation masks, resampled volumes — are isolated Layer‑4
caches per module; never written back into the shared VTK volume.)

---

## 5. The boundary, drawn on the actual cache layers

```
Layer 1  DICOM File Cache        SHARED   SOURCE_PATH/<study_uid>/<series>/      (download manager)
   │
   ├── identity + state + metadata + invalidation bus + KPIs        SHARED TRUNK
   │
   ├─► Layer 2  FAST Decoded-2D     FAST-ONLY   memmap + pixmap/frame LRU        (lightweight_2d_pipeline)
   │            (slice-indexed, Qt raster — never VTK)
   │
   └─► Layer 3  VTK Volume Cache    ADVANCED+MODULES   (study_uid, series_uid)   (volume_cache / VtkVolumeService)
                │  (full volume + geometry, pin/unpin, coalescing)
                └─► Layer 4  Module-specific (panoramic / seg / resample)  per-module, isolated
```

- **Layer 1** and the **trunk** (identity/state/metadata/bus/KPIs) are the only truly shared pieces.
- **Layer 2** is Fast‑private. **Layer 3** is Advanced‑private (shared *only* among VTK consumers).
- The two viewers meet **only** at Layer 1 + the trunk — never at Layer 2/3.

---

## 6. Reconciling the S0–S5 work onto this model

| Stage | What it is | Trunk or branch? |
|---|---|---|
| S0 identity (`viewer_identity.py`) | stable keys/handles | **Trunk** (both viewers key by it) |
| S0/S2 state store (`series_state_store.py`) | per‑series state | **Trunk** |
| S3 `ensure_series_displayed` (`viewer_request_pipeline.py`) | the *decision* of what to do | **Trunk** (decision); the **execution** is per‑branch |
| S4 VolumeCache / VtkVolumeService | the VTK volume store | **Advanced/VTK branch** (NOT Fast) |
| S5 cancellation‑by‑handle | teardown safety | **Trunk** (keyed by the shared `ViewerHandle`) |

So the spine (S0/S1/S2/S3/S5) is correctly **trunk**, and S4 is correctly **branch‑B (Advanced)**.
Nothing in the spine forces Fast and Advanced through one execution path — S3 decides *what*, each
branch executes *how*.

---

## 7. Cache coordination — the shared part, made precise

The thing that is shared about caching is **coordination, not storage**:

1. **One key namespace:** `(study_uid, series_uid)` (the full DICOM UID, normalized by
   `vtk_volume_service.series_uid_from_meta`). Fast's slice caches additionally key by slice index
   *within* that series; Advanced keys the whole volume by it.
2. **One invalidation bus:** a *server‑grew* / *series‑changed* / *re‑import* event for a key must
   invalidate **both** Fast's decoded entries **and** Advanced's VTK volume for that key. Today this
   is ad‑hoc (`_vc_cache._invalidate_series_caches` + `zeta_boost.invalidate_series` +
   `VolumeCache.invalidate`); the unification target is a single `invalidate(study_uid, series_uid)`
   the download/state layer raises, that each cache store subscribes to.
3. **One state authority:** `SeriesStateStore` is the shared "is this series on disk / complete /
   displayed" — both viewers read it; neither keeps a private copy of *download/disk* truth.

What is **NOT** shared: the cache **stores** themselves (Fast's memmap+LRU vs. Advanced's VolumeCache),
the **decode** that fills them, and the **render**.

---

## 7.1 STRICT TEST — when a built VTK volume may be shared across VTK domains

The VTK volume cache is the ONLY place the design lets two domains touch the same artifact. Per the
§0.1 hard rule it is allowed **only** as a TRUNK data-service that hands out an **immutable** artifact,
and **only** if it passes ALL of:

1. **Immutable.** The cached `vtkImageData` is read-only to every consumer. No domain mutates a shared
   volume (W/L, geometry, scalars, orientation). A domain needing to modify makes its own copy.
2. **Per-consumer reference / independent lifetime.** Each consumer holds its OWN reference; the cache
   holding or evicting its reference can never pull a volume out from under a live consumer, and one
   consumer closing never frees another's volume.
3. **Independently failable.** A build failure / eviction / exception serving one domain returns that
   domain to its OWN legacy build path and CANNOT raise into, stall, or corrupt another domain.
4. **No lifecycle / widget / interactor coupling.** Sharing the volume must not share render windows,
   interactors, observers, or teardown. Closing MPR must not touch the Advanced viewer or any module.
5. **Keyed by trunk identity only** (`study_uid, series_uid`) — never by a domain-local handle/state.

If any of 1–5 cannot be guaranteed for a consumer, that consumer **does not share** — it builds and
caches its own VTK volume. **The conservative default is per-domain caches.** Cross-domain reuse of the
immutable volume is an OPT-IN optimization (flag-gated, clinical-lane-validated) that turns on only
once 1–5 are proven — it must cut rebuilds **without** creating any path by which one domain disturbs
another. (This is why S4b is staged flag-off: the reuse is exactly this opt-in, and the §0.1 rule is
its acceptance gate.)

## 8. Correction to the earlier S4B draft (important)

`S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md` §6 "reuse rule 1" proposed that the Advanced VTK build
**reuse Fast's already‑decoded `PyDicomLazyVolume` slices** to skip the re‑read. **That is withdrawn**
— it couples the two viewers' decode pipelines, which violates this boundary. Under the clean model:

- The Advanced viewer **decodes its own way from the shared disk files** (SimpleITK → VTK). It does
  **not** read Fast's 2D memmap.
- The re‑read elimination Advanced *does* get is **build‑once among VTK consumers**: once the VTK
  volume for `(study_uid, series_uid)` exists (built by the Advanced viewer **or** by an MPR/Dental
  open), the next VTK consumer reuses it — no second SimpleITK build. That is the legitimate,
  in‑branch win, and it needs no Fast coupling.
- Fast and Advanced decoding the same series independently is **accepted** as the price of clean
  independence (they are different representations for different renderers). If a future measurement
  shows that double‑decode is a real cost worth removing, the *correct* place to do it is a shared
  **raw‑pixel** producer in the trunk that both decoders consume — a deliberate trunk addition, not a
  reach across the branch.

This keeps S4b's value (no triple VTK rebuild across Advanced+MPR+Dental; off‑thread build; one
invalidation bus) while respecting viewer independence.

---

## 9. Rules / invariants (the contract going forward)

1. **Fast never becomes VTK.** No VTK volume, no VTK cache dependency in the Fast path. (The "FAST mode
   never instantiates VTK render windows" rule already encodes this.)
2. **The trunk ends at disk‑files + identity + state + metadata.** New shared work must fit *above* the
   branch (download, files, identity, state, metadata, bus, KPIs). If a change is about *decode / cache
   store / render*, it belongs in **one** branch, not the trunk.
3. **Branch only where technically justified** — a different decode, cache strategy, or render
   technology. Not "to unify for its own sake."
4. **VTK modules are Advanced‑branch citizens** — they share the VTK volume cache, never the Fast cache.
5. **Module‑specific caches are isolated outputs** — never written back into the shared VTK volume.
6. **One key + one bus + one state authority** are the shared coordination; the cache **stores** stay
   per‑branch.
7. **Cross‑branch reuse of internal representations is prohibited** unless it is refactored into an
   explicit trunk producer (§8).

---

## 10. Where this leaves the in‑flight work

- **Keep (trunk):** S0 identity, S2 state authority, S3 chokepoint, S5 cancellation, the shared
  invalidation‑bus goal, KPIs.
- **Keep (Advanced branch):** S4a `VolumeCache` + S4b `VtkVolumeService` as the **Advanced/VTK** cache,
  shared with the VTK modules — exactly where it already sits.
- **Drop:** the "Advanced reuses Fast slices" idea (§8).
- **Unchanged Fast branch:** the lazy‑2D decode + raster caches stay Fast‑private and untouched.
- The patient‑open GUI freeze observed 2026‑06‑27 is a **trunk‑adjacent** concern (the *Fast* full‑series
  finalize running on the GUI thread under a download‑completion flood) — i.e. branch‑A execution, task
  #39 — and is independent of the Advanced VTK cache.
