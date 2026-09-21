# Unified Pipeline — Shared Infrastructure vs Viewer-Specific Boundary

**Status:** architecture clarification (authoritative boundary) · **Date:** 2026-06-27
**Supersedes the over-reach in** `S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md` §6 rule 1 (see §8 below).

**2026-09-16 clarification:** this document defines architectural responsibility, not
proof that every proposed service/cutover is active. Current implementation and acceptance
belong to the dated receipts in the master plan. Sections 0.1 and 7.1 govern all VTK
cache reuse: per-domain stores are the default, not one mutable cache shared by modules.

**2026-09-17 Local catalog application:** import, download, Home Local and patient
Local now converge on one immutable pixel/displayability fact contract in the existing
series index. Geometry-index trust, download lifecycle/completion and UI readiness remain
separate states. Legacy facts are verified on workers and persisted through one revision-
checked batch writer; no viewer decode/cache/render domain consumes mutable shared state.

**2026-09-20 viewport input clarification:** drag-hover timing is shared UI coordination,
not a shared render pipeline. Fast and Advanced consume one immutable dwell/tolerance
policy for traversal feedback, but keep separate drop dispatch, decode, cache, render and
lifecycle behavior. The hover timer never gates a deliberate drop and never advances the
U0-U5 ledger. See the dated OPT-60 receipt in the master plan.

## Current execution ledger - 2026-09-18

This is the only active order for shared Unify work. Historical staged plans and dated
incident sections remain evidence, but they do not authorize a parallel implementation.
Only one `U*` slice may change shared-trunk behavior at a time. The next slice starts only
after the current slice has an explicit code-gate result, source-GUI result, rollback, and
dated receipt in the master plan.

| Order | Shared-trunk slice | Current state | Exit gate before the next slice |
|---|---|---|---|
| **U0** | Accept the already-landed ordered Local catalog owner and completed-load tab handoff | Post-catalog orphan ordering, indexed-Local warm suppression, final open identity and pre-construction tab admission are code-verified; fresh rerun remains open. Import/Download already publish one revision-bound durable DB summary; the disk fact cache is accelerator-only | Previously unopened single- and multi-study Local cases, blank-primary Local promotion, warm reopen, one Server control, first card before `LOCAL_ORPHAN_RECONCILE phase=post_catalog_start`, zero Local whole-series `SERIES_FILE_WARM` reads, exact card identity/order/object/frame counts, no overlap/jump, hidden-tab completion replay, four admitted tabs plus a prompt fifth-tab rejection with no widget/pipeline construction or qasync re-entry, no GUI-thread file read, and a normal exit with session-scoped native evidence |
| **U1** | Publish one authoritative download-completion fact | Not implemented as a complete shared contract | Completion is emitted only after atomic file publication and required index/state convergence; notification, PNG presence and an inferred count are not completion; retry/resume and already-resident paths agree |
| **U2** | Make per-series state authoritative for shared decisions | Partial/additive; `SeriesStateStore` is not the sole truth and Download Manager still owns its live queue | Download events and display lifecycle feed one identity-keyed state record; the store becomes primary for shared await/grow/rebuild/settled decisions; Download Manager keeps queue ownership and viewer-private render state stays private |
| **U3** | Introduce one identity/revision invalidation bus | Target only; invalidation remains scattered | A single server-grow, series-change, re-import or published-download event invalidates every subscribed read model/cache for the canonical key without exposing one viewer's cache to another |
| **U4** | Route shared entry points through the decision chokepoint and retire parallel branches | Partial; `plan_series_display` is not yet the only acting path | Open/drop, progress, completion and disk-ready resume use the same shared plan; obsolete flags and re-key/count fallbacks are removed only after zero-divergence code and live soak evidence |
| **U5** | Installed/restart/stress closure | Open | Source and installed behavior agree; cold/warm/restart, interrupted download, repeated open/close, normal shutdown and packaged configuration/mirror gates pass |

### Stop conditions and document ownership

- A native access violation, wrong-patient/study/series identity, lost download, or
  authoritative count mismatch stops the active slice. Diagnose it in the owning existing
  record before changing another stage. Do not compensate with a second loader, downloader,
  cache, timer or fallback.
- Shutdown/native lifetime is tracked in
  [`CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md`](../../reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).
  It is a release stop condition, not proof that catalog, download or a viewer caused the
  fault. If a U0-U5 acceptance run faults on exit, pause the queue and close the lifecycle
  evidence gap first.
- The optimization master plan owns priority and status; this document owns architecture
  and order; the UI-stall and crash reports own dated evidence; the regression catalog owns
  fail-before/pass-after guards. Viewer-private findings stay in their viewer-owner report.
  Do not copy a repair plan between these documents.
- `VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md` is implementation history. Where it
  conflicts with this ledger or current code, this ledger and the master plan win.

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
  only under the strict test in §7.1 — a built VTK volume). Sharing a read-only *artifact* is allowed;
  sharing *implementation, lifecycle, widgets, interactors, or mutable state* is **forbidden**.

Consequences already in force: the Fast "no VTK render windows" rule; the Fast-branch freeze of
2026-06-27 is fixed **inside the Fast branch** (never by routing Fast through Advanced/VTK machinery);
module-specific outputs (panoramic, segmentation, resample) stay isolated and are never written back
into anything shared.

## 0.2 Workstream ownership and two-way handoff (user decision, 2026-09-16)

One shared coordination path feeds two intentionally distinct patient-viewer backends:
Fast and Advanced. VTK tools remain independent execution domains under section 0.1;
calling them part of the VTK representation family does not merge their ownership.

| Boundary | Workstream and owning record |
|---|---|
| Identity/SeriesRef, catalog and thumbnail mapping/presentation, source-file availability, download/state/progress coordination, cancellation tokens, common cache keys/revisions/invalidation, shared KPIs | Unify workstream: [UI-stall evidence and guarded fixes](../../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md), under OPT-58 / OPT-60 and the existing master-plan items. Reuse each existing owning service; do not create a second coordinator. |
| Advanced/VTK load/decode/filter/geometry/render/scroll, decoded-volume stores and native resource lifetime; their runtime/payload parity | Viewer workstream: [VTK-domain review](../../reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md). Unify records evidence there; it does not patch these implementations. |
| Fast-specific decode/filter/raster/render/cache-store internals | Fast execution-domain owner, not the Unify workstream and not implicitly assigned to VTK. Route an identified branch defect through its subsystem record before implementation. |
| Shared contract consumed by either viewer | Unify owns the contract; the affected viewer owner owns its adapter and branch changes. Agree on identity, source revision, cancellation and immutable payload semantics before either side changes the interface. |

Handoff procedure, in both directions:

1. Record a PHI-free finding in the **destination owner's existing document**: source
   session/time, concrete method or boundary, evidence, confirmed versus suspected cause,
   affected contract, requested owner check and current status. Keep only a backlink in
   the source report; do not maintain competing repair plans or copy sensitive logs.
2. Do not implement, hot-reload, change flags or synchronize another owner's in-progress
   mirrors merely because its code appeared in a shared log. A handoff is not acceptance
   or an instruction to close a defect without that owner's verification.
3. The destination owner records diagnosis/fix/verification there and returns a linked
   summary of any shared-contract impact. Unknown attribution stays **unclassified**;
   a loading cover, COM frame or long gap alone does not identify the responsible domain.
4. For an interface change, document the producer/consumer contract and add both-side
   guards plus affected-workflow source-GUI verification. Do not smuggle another backend's
   mutable Qt/VTK objects, worker ownership or lifecycle through the common service.

Unification removes duplicate **authority and orchestration**, not legitimate backend
representations. Cached PNGs and authoritative source files can use shared data services;
decoded raster/volume stores stay private. Shared download/file availability must not
turn one consumer's decoded/displayed outcome into another consumer's completion.
A fallback may remain only for a documented
capability/failure boundary, with one request owner, explicit handoff and stale-result
rejection. Retire obsolete routes after contract parity and code/live verification,
not merely because two call paths exist. This decision does not activate a cache,
promise a completed migration, or authorize a new raw-pixel producer.

## 1. The shared trunk — what is genuinely common (ONE implementation)

These responsibilities have **no per‑viewer difference** and must be implemented once and reused by
both viewers. Each line is the real owning code.

| Shared responsibility | Owner (code) | Notes |
|---|---|---|
| **Download management** | `modules/download_manager/` (Zeta socket `network/socket_client.py`) | One downloader; writes atomically (`*.part`→`os.replace`). Viewer‑agnostic. |
| **DICOM File Cache (source of truth)** | disk `SOURCE_PATH/<study_uid>/<series_number>/` (`data_paths.py:DICOM_IMAGES_DIR` ← `config.py:SOURCE_PATH`) | The one authoritative copy of pixels. Both viewers read from here. |
| **Identity model** | `PacsClient/utils/viewer_identity.py` (`ViewerHandle`, `SeriesRequest`) | `(patient_id, study_uid, series_uid, viewer_handle)`. The cache key + request token for BOTH viewers. |
| **Per-series state target (not fully cut over)** | `PacsClient/utils/series_state_store.py` (`SeriesStateStore`) | Target vocabulary is `Requested→Queued→Downloading→PartialOnDisk→Decoding→Displayed`, but runtime code still labels this S0/shadow and Download Manager retains its live queue authority. Do not treat the planned store as current truth until an explicitly guarded cutover. Producer-verified Local catalog facts are a separate immutable read model, not lifecycle state. |
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

### 4.1 VTK representation family, independent module execution

MPR (`zeta_mpr/mpr_viewer/widget.py::StandardMPRViewer`), Dental Curve MPR
(`mpr/zeta_mpr/curved_mpr.py`), Dental Imaging (`modules/dental_imaging/`), Orthogonal MPR,
and in-process VTK/AI tools consume VTK representations, not Fast raster caches. Each
retains its own execution, store and lifecycle by default. Reuse of an immutable built
volume is a separate opt-in optimization through the trunk, only after section 7.1's
five gates pass for every consumer. It is not an unconditional shared cache or pipeline.
Module outputs (panoramic reconstructions, segmentation masks, resampled volumes) remain
isolated and never mutate a shared source artifact. This clarification supersedes the
old "not a third thing" wording, which contradicted section 0.1.

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
   └─► Layer 3  VTK Volume Stores   PER-DOMAIN        (study_uid, series_uid)   (volume_cache / VtkVolumeService)
                │  (full volume + geometry, pin/unpin, coalescing)
                └─► Layer 4  Module-specific (panoramic / seg / resample)  per-module, isolated
```

- **Layer 1** and the **trunk** (identity/state/metadata/bus/KPIs) are the only truly shared pieces.
- **Layer 2** is Fast-private. **Layer 3** is VTK-domain-private; immutable reuse is gated by §7.1.
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
3. **One state-authority target:** `SeriesStateStore` is the intended shared "is this
   series on disk / complete / displayed" contract, but the current runtime cutover is
   incomplete and remains shadowed in several paths. Download Manager state stays the
   live download authority until that migration is explicitly guarded. The metadata
   index may accelerate immutable Local catalog facts; it must not claim download or
   displayed completion.

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
- A possible re-read elimination is **immutable artifact reuse among VTK consumers**, but
  only after every gate in §7.1 passes and the relevant optimization is explicitly enabled.
  A built `(study_uid, series_uid)` volume alone does not authorize reuse. This is a
  conditional benefit, not a statement that today's consumers share one cache or build.
- Fast and Advanced decoding the same series independently is **accepted** as the price of clean
  independence (they are different representations for different renderers). If a future measurement
  shows that double‑decode is a real cost worth removing, the *correct* place to do it is a shared
  **raw‑pixel** producer in the trunk that both decoders consume — a deliberate trunk addition, not a
  reach across the branch.

This preserves S4b's conditional reuse goal, off-thread build and invalidation coordination
while respecting viewer independence; current activation/acceptance requires a dated receipt.

---

## 9. Rules / invariants (the contract going forward)

1. **Fast never becomes VTK.** No VTK volume, no VTK cache dependency in the Fast path. (The "FAST mode
   never instantiates VTK render windows" rule already encodes this.)
2. **The trunk ends at disk‑files + identity + state + metadata.** New shared work must fit *above* the
   branch (download, files, identity, state, metadata, bus, KPIs). If a change is about *decode / cache
   store / render*, it belongs in **one** branch, not the trunk.
3. **Branch only where technically justified** — a different decode, cache strategy, or render
   technology. Not "to unify for its own sake."
4. **VTK modules are independent domains** — their representations are VTK, never Fast caches;
   any cross-domain immutable-volume reuse must pass §7.1, not merge stores or lifecycle.
5. **Module‑specific caches are isolated outputs** — never written back into the shared VTK volume.
6. **One key + one bus + one state authority** are the shared coordination; the cache **stores** stay
   per‑branch.
7. **Cross‑branch reuse of internal representations is prohibited** unless it is refactored into an
   explicit trunk producer (§8).

---

## 10. Where this leaves the in‑flight work

- **Keep (trunk):** S0 identity, S2 state authority, S3 chokepoint, S5 cancellation, the shared
  invalidation‑bus goal, KPIs.
- **Keep (Advanced/VTK domains):** S4a `VolumeCache` + S4b `VtkVolumeService` as domain-private
  cache infrastructure by default; cross-domain immutable reuse remains gated by §7.1.
- **Drop:** the "Advanced reuses Fast slices" idea (§8).
- **Unchanged Fast branch:** the lazy‑2D decode + raster caches stay Fast‑private and untouched.
- The patient‑open GUI freeze observed 2026‑06‑27 is a **trunk‑adjacent** concern (the *Fast* full‑series
  finalize running on the GUI thread under a download‑completion flood) — i.e. branch‑A execution, task
  #39 — and is independent of the Advanced VTK cache.
