# VTK domains: geometry and performance review

## Inbound Alignment/Stitching source audit (2026-09-17)

ELA session, read-only source/synthetic probe: `StitchingWidget._export_as_dicom`
creates OT Secondary Capture with a new study, no patient/source lineage and
hard-coded orientation. The declared explicit VR produced an implicit-VR reader
warning in a synthetic export. Alignment rejects the file by study/modality.
Requested Stitching-owner check: export identity/encoding/geometry, exact source
SOP selection, revision invalidation, and transform/calibration provenance before
quantitative handoff. Synchronous load/export slots and series-number image keys
are additional confirmed code patterns; their live impact was not measured.
See [contract and reproduction](../modules/EAGLE_EYE_ALIGNMENT_STITCHING_HANDOFF.md).
Status: review only, owner acceptance pending; no runtime or payload edits.

## Inbound normal-source log review: 2026-09-17 10:49 launch

Unify read-only window 10:49:35-11:08:09, main PID 1172172. Advanced constructors
95.360 / 107.834 ms, first renders 56.114 / 53.005 ms; no sampled MathText import
stall. Residual F11 at 10:50:36 (412.5 ms) includes preview application -> switch ->
apply_default_window_level -> _read_window_level_from_dicom_cornerstone ->
resolve_cornerstone_like_window_level_from_dicom. At 10:51:00 (404.3 ms), placeholder
construction is on the stack; at 10:51:06 (427.4 ms), constructor/Render is sampled.
Sample gaps are not exclusive timings of the last function. No Viewer fix or geometry
inference is authorized by these observations alone. Shared Local-stream PNG I/O,
six-series zero-file admission caveat and stability limits are in the
[normal-source receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-1049-normal-source-receipt-home-preparation-active).

## Inbound sampled source verification: 2026-09-17 10:03 launch

Read-only Unify review, main PID 913840, fixed window 10:03:27-10:16:39.
Four Advanced constructors: first_render_ms 40.747 / 42.059 / 49.160 / 44.269;
total_ms 98.341 / 141.129 / 83.002 / 76.219. No MathText/Matplotlib import
stall sampled, and the previous 13.785 s GUI gap is absent. Counter correction
has positive sampled live evidence, but exact overlays/zoom and full native
acceptance are not certified by these timings. No Viewer code changed here.

Residual owner evidence: 10:14:17 F11 gap sample 401.5 ms includes placeholder
construction -> resolve_gpu_boost_plan -> resolve_graphics_profile ->
detect_software_graphics_support -> find_runtime_binary ->
graphics_runtime_search_roots -> resolve/realpath. A later 10:15:56 sample
(442.5 ms) includes Advanced constructor/Render, while paired constructor
first-render timing is 49.160 ms; do not equate the full sample gap with Render.
Do not change rendering or graphics search semantics on this evidence alone.
Shared Local cold admission/cache and Home PNG I/O findings, stability limits,
and 125 focused scale/lifecycle passes are in the
[10:03 shared receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-1003-source-receipt-warm-grouped-improvement-cold-admission-remains).

## UNIFY-HANDOFF-2026-09-17-03: first Advanced Render freezes GUI

**Status: Advanced owner correction implemented and code-verified on 2026-09-17; fresh-source GUI acceptance pending. No runtime change by Unify.**
Owner correction receipt: the generated preview counter, not an identified patient
annotation, is a confirmed sufficient trigger. Installed VTK 9.6.1 selects MathText
for `1 / 104 | 8 ready` and `1 / 8 | Loading`: the pipe is column syntax.
A cold synthetic text-actor render imports Matplotlib with the original counter;
plain text without the pipe does not. This matches the live first-render import
stack, without claiming exclusive attribution of all 13.8 seconds.

Implemented files:
- `modules/viewer/advanced/slice_progress.py`: use `1 / 104 (8 ready)` and
  `1 / 8 (Loading)`, preserving count/loading semantics.
- `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/slice_progress.py`:
  official mirror sync copied only this file after dry-run showed exactly one drift.
- `tests/code/viewer/test_advanced_counter_text_backend.py`: two real VTK backend
  checks and one cold subprocess offscreen native render/import guard.
- `tests/code/viewer/test_advanced_slice_progress.py`: update expected separator
  presentation while retaining preview, stale-total, scroll and completed-bind guards.

Fail-before: all three new guards failed (exit 1), including the actual Matplotlib
import during render. After: 49 focused preview/startup/full-stack/metadata/US/MPR
admission tests passed (exit 0); builder mirror guard 1 passed; 467 mirrors match.
Matched synthetic cold-process actor-render samples (three processes each): old pipe
515.49 / 441.16 / 487.58 ms, Matplotlib imported in all; parentheses 80.67 / 64.16 /
65.87 ms, no Matplotlib imports. OS caches were not cleared; these are renderer probes,
not complete app startup benchmarks or reproduction of the full live 13.8-second stall.

Only generated count-label punctuation changes. No global backend override, patient
text escaping, dollar/backslash transformation, dependency preloading, camera/zoom
ordering, geometry, decode/filter settings or thread changes. Other domains and shared
Local inventory remain untouched. Frozen parity is source/payload verification only;
no new frozen build was run. Rollback: restore the two status-label separators and
resync their mirror. This would restore the demonstrated MathText activation.

Remaining live gate: one coordinated fresh source launch by its owner, first Advanced
preview drag/drop after login, readable total/ready/loading counter, first-render KPI
and no MathText import-related GUI gap, full-count completion, zoom stability and
literal medical overlays. No app restart or live control was performed for this fix.

Upstream explanation: VTK's `DetectBackend` treats an unescaped pipe as MathText
column syntax (https://raw.githubusercontent.com/Kitware/VTK/v9.5.2/Rendering/Core/vtkTextRenderer.cxx);
installed 9.6.1 behavior is independently exercised by the guards above.

Historical diagnostic evidence follows:

Source main PID 1238252 launched 2026-09-17 09:13:10. Read-only log window
09:13:10-09:18:00, including all relevant app/viewer/download rotations. User
reported a freeze when placing the first series into the viewport. The recorded
workflow is Advanced preview application after native drop, not proof of a new
file-import failure. Keep diagnosis and implementation within Advanced ownership.

- F8 records a single 13785.1 ms GUI gap at 09:16:15.032. Repeated F11 samples
  from 09:16:01-09:16:14 are samples of that same interval, not separate freezes.
- Preview application enters `_vc_switch::_apply_preview_ui` ->
  `_vc_load::_apply_loaded_series_data` -> `_perform_series_switch_optimized` ->
  `_vw_series::switch_series` -> `modules/viewer/advanced/viewer_2d.py::__init__`.
- At 09:16:14.919, constructor timing is 13401.579 ms, including
  **first_render_ms=13209.090**, overlays 145.576 ms and geometry 10.410 ms.
- The 09:16:07.867 F11 sample explicitly pairs `viewer_2d.py:479 Render`
  (`super().Render()`) with `matplotlib/mathtext.py:22 <module>`. Surrounding
  samples include matplotlib rcsetup, transforms, backend_tools, textpath,
  backend_agg and compiled-extension imports on the GUI thread. This supports
  cold MathText dependency loading during first native render as the dominant
  sampled cause. It does not identify which actor/text selects the MathText route
  or whether disk/AV activity amplified import wall time.
- Later constructor at 09:16:24.077 is 86.059 ms, first render 48.400 ms;
  another at 09:17:41.819 is 85.801 ms / 48.637 ms. These are different series,
  not a matched benchmark or proof all cold render costs are resolved.

Requested owner check: identify the actor/text/backend activating MathText, then
evaluate a guarded plain-text rendering route where appropriate versus bounded
dependency preparation. Do not move VTK/Qt rendering to a worker, eagerly warm
the whole viewer on GUI, remove required annotation semantics or change camera
first-render/zoom ordering. Protect literal dollar/backslash text, medical overlays,
source/frozen packaging, cancellation and first-use behavior. No fix is authorized
or claimed by this diagnostic handoff itself.

The 39-card grouped sidebar was in progress during this freeze, so its 22.904 s
elapsed build time is not exclusive thumbnail work. Separate Local filesystem
admission and Home GUI image I/O are owned by Unify; see the
[shared receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-0913-source-verification-local-multistudy-and-first-render).
No patient identifiers, raw logs or images copied; no decode/filter/geometry edits.

## Inbound live KPI handoff: 22:47 source session, 2026-09-16

Read-only review by Unify; main PID 1197880, logs through 23:04:47. The previously
blocked remote study now completes 2262/2262 plus its separate 2/2 secondary task.
No Viewer implementation change was made for this review. Full evidence/remaining
shared thumbnail stalls are in the UI-stall report's 22:47 receipt.

Owner-specific residuals: F8 gaps 1713.3 ms at 23:01:09.644 and 1655.9 ms at
23:01:11.926 align with MPR opening/deferred 3D construction. F11 samples include
toggle_zeta_mpr -> canonicalize_volume -> _read_dicom_slice_axis_sign -> dcmread,
then _create_coronal_view construction, and _build_deferred_3d_view ->
_update_view_highlights. Advanced preview/switch constructor/Render is sampled
near 417/492 ms; DICOM window-level reading at 23:02:00 near 418 ms. These are
attribution samples, not exclusive per-function timings or proven regressions.
Only two scroll summary values were emitted (set_slice_max_ms 29.36 / 44.59);
insufficient for an all-scroll p95 or a matched contention acceptance claim.
Investigate within existing OPT-35/MPR ownership; no decode/render fix is requested
from the shared Unify conversation.

## UNIFY-HANDOFF-2026-09-16-02: suspended download process after Advanced interaction

**Authorized follow-up:** Unify retired only the shared download-process hard
suspend/resume hooks in current and legacy compatibility modules; callable APIs
and shutdown registration remain. No scroll/series-switch/render/decode code was
changed. [Implementation, alternatives, tests and live gate](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-opt-04-download-liveness-independent-of-viewport-settling)
are owned there. The diagnostic-only status below describes the earlier inspection.
Fresh source GUI/scroll contention acceptance is still pending.

**Separate owner test finding:** expanded code suite found
`test_vtk_widget_split.py::test_start_process_series_qt_syncs_progressive_available_count`
fails at `_vw_series.py:480` because its `_Spinner` double has no
`hide_loading_after`. Re-running with original HEAD download hooks restored in
memory in an isolated test process fails identically. The current real spinner
has this API; review/update the owner's test double without weakening the
progressive-available-count assertion. Unify has not edited that test or implementation.

**Status: diagnosed immediate blocker; exact suspension/release trigger not yet
proven. Read-only investigation, no runtime change or live recovery performed.**
This is a cross-boundary OPT-04 / OPT-35 finding. Unify owns download admission,
worker liveness and shared resource coordination; this owner owns the Advanced
scroll/series-switch adapter. Do not change decoding, geometry or filters for it.

Source launch 21:27:14 local, main PID 1215900. The user opened cached cases around
one remote case and dropped two remote series. PHI-free evidence:

- 21:31:03.462: primary remote task queued with 32 series. Thumbnail fetch finished
  in approximately 164 ms; later authoritative backfill added a second study with
  one series. These are separate metadata/thumbnail and image-download paths.
- 21:31:03.490: worker adopted prewarmed PID 1130316 (created 21:28:19), while
  PID 1220412 became the next idle spare. Two drops at 21:31:10.058 and 11.875
  produced priority intents. Therefore neither missing drag delivery nor thumbnail
  ownership takeover explains the missing download start.
- Repeated Windows process inspection during this investigation: all 23 threads
  of adopted PID 1130316 have wait reason `Suspended`; CPU remained 2.59375 seconds.
  The replacement spare has ordinary `UserRequest` waits, not suspension.
- Read-only `py-spy dump --nonblocking`, without locals: adopted child is still in
  `download_process_entry.py::_prewarmed_download_worker_main`, line 52,
  `task_queue.get() -> _recv_bytes`. Parent has a queue feeder in `_send_bytes`
  and a bridge waiting for results at `download_process_worker.py:247`.
  No `[SPAWN-TIMING]` entry into the actual download function or file-count
  completion marker appears in this session window; the adopted PID has no TCP
  connection at the sampled check. This is not a server-response timeout.
- Existing local test-control client ping/actions succeed. Read-only state:
  primary `Downloading`, 32 series, zero downloaded and zero progress;
  secondary `Pending`, one series. Process existence therefore masks lack of
  execution progress. No actual ERROR/CRITICAL severity in the initial scoped
  app/viewer/download window (21:27:14-21:36:00); silent logs do not certify health.

### Structural findings and attribution limits

`workers/prewarm.py::ensure_warm` registers an idle spare in the same PID set
used both for app-shutdown cleanup and VTK scroll suspension. `acquire` accepts
`is_alive` plus the historical ready event, queues the job and adopts it, without
a runnable/job-accepted acknowledgement. The bridge polls indefinitely while
`is_alive` remains true. The priority retry path clears when the state is already
`Downloading`; repeated drops cannot make this suspended process run.

`vtk_widget/_vw_globals.py` directly suspends/resumes every registered PID, without
per-owner leases, suspension tracking or checked native return status.
`_vw_scroll.py::wheelEvent` suspends before missing-image/one-slice early returns;
the release timer is armed later by a successful coalesced render. Separately,
`_vw_series.py::switch_series` stops that timer and clears `_gc_suppressed` while
restoring GC, without releasing the download suspension. These are demonstrable
unbalanced-release opportunities, **not proof which one occurred in this run**.
Advanced wheel events and `gc_reenable` markers are present, but the native
suspend/resume calls have no receipt; the exact missed release requires a guard
and bounded ownership instrumentation. These core suspension/prewarm/bridge files
are unchanged from HEAD; the series-switch reset block is also unchanged. Do not
attribute this failure to the latest sidebar/header patch from timing alone.

### Requested coordinated follow-up, not an implemented fix

First reproduce using synthetic idle-spare, no-render/one-slice, series-switch,
close-during-scroll and overlapping-viewer scenarios. Shared download ownership
must distinguish shutdown registration from interaction throttling and must not
consider an alive-but-suspended child a successful start. The Viewer owner must
balance acquire/release on every branch/lifetime exit through the agreed shared
contract. Prefer bounded cooperative coordination over unchecked whole-process
suspension; compare responsiveness and IPC safety before selecting the seam.
Do not force-resume the live child, broadly reset queues, duplicate downloads or
disable Viewer features as an unverified repair. Require code guards and a fresh
source cached-scroll -> remote-open -> two-series-drop -> actual file/pixel pass.

Source backlink: [Unify incident receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-2127-session-remote-download-start-blocked).

Date: 2026-09-16. Status: source/document review and isolated automated verification;
no runtime changes, feature activation, live GUI acceptance, or performance claim.
The initial review status above is historical; the implementation receipt below records
the subsequently authorized cache prerequisite fix. Other slices remain planned.
This is a follow-up to OPT-35, OPT-47, OPT-48, OPT-49 and OPT-56 in the
[master plan](../OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md), not a new optimization program.

## Scope and execution map

### Inbound handoff from Unify (2026-09-16)

The user reaffirmed separate conversation/workstream ownership. Shared coordination
and sidebar work stays in the [UI-stall owner report](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md).
Advanced/VTK implementation findings belong here, not in that workstream's fix queue.
The [two-way handoff contract](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#02-workstream-ownership-and-two-way-handoff-user-decision-2026-09-16)
defines the common-data handoff and independent Fast/Advanced/module execution domains.
This documentation update does not widen this VTK task to Fast-specific internals.

**UNIFY-HANDOFF-2026-09-16-01 — point-in-time Advanced payload drift.** During the
sidebar patch, the mirror verifier initially passed all 466 pairs. The later recheck
around 18:20 local time returned exit 1: `modules/viewer/advanced/viewer_2d.py` differed
from `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py`.
The Unify patch did not edit either file or synchronize this owner's concurrent work.
This was a packaging-parity observation, not evidence that it caused thumbnail jumping,
decode failure, a native popup or a crash.

**Follow-up at documentation handoff:** the Viewer owner's subsequent preview-count
receipt below records 467 matching pairs. A fresh read-only verifier run by Unify also
returns **467 pairs match, exit 0**. Thus the observed parity mismatch is no longer
present at this check. No competing runtime fix or mirror write was performed here;
GUI/clinical acceptance and any later edits remain subject to their own gates.

The reported transient central window is **not yet attributed**: Unify observed a
viewport loading cover after loading, but did not capture a separate transient native
window during the event. It remains in the shared UI investigation until evidence
identifies a branch loading-cover/native-lifetime defect. Do not treat this handoff as
a reproduced new VTK issue or reopen the already user-accepted cover fix without evidence.

**User scope decision, 2026-09-16:** this conversation owns VTK defects and their
direct loading/filtering, volume-cache, rendering, scroll, geometry and resource-lifetime
boundaries. It does not own general Home/startup, Fast Qt, dashboard selection, download,
or application-wide native/crash fixes. Record those findings in their owning documents
for the separate conversations already working on them; do not implement them here.
An unclassified COM exception is not a VTK defect until attribution supports that claim.
External Advanced Analysis work here is limited to its VTK/image path; generic Slicer
startup/process work stays with the existing OPT-56 owner.

Handoffs from the fresh log review: dashboard freshness and unclassified native evidence
are recorded in [the crash/KPI audit](CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md);
Home construction/theme timings in [the UI stall report](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md).
This VTK workstream's next target remains the observed Advanced constructor/first-render
stall. The measured 6.1-second gap spans several stages and must not be assigned wholesale
to one VTK call without phase timing. VTK placeholder construction is also in scope;
generic loading-overlay overhead is a separate UI boundary.

| Consumer | Actual path | Review boundary |
|---|---|---|
| Settings: Advanced Viewer | `vtk_simpleitk` -> `image_io.py` -> SimpleITK loading/filtering -> `convert_itk2vtk` -> `modules/viewer/advanced/viewer_2d.py::ImageViewer2D` | Full-volume loading, display preprocessing, reset/reuse, scrolling, overlays, cleanup. The similarly named optimized viewer file is not the active import. |
| Eagle Eye / AI Imaging | `modules/ai_imaging/ai_module_ui/overrides/patient_widget.py` selects Advanced by default; `AIVTKWidget` extends the VTK widget | Bone-age uses a Qt exception. Preserve AI box coordinate conversion, per-widget backend selection, deferred drag/drop, and independent ownership. |
| Standard / Zeta MPR | `toolbar_manager.py::toggle_zeta_mpr` -> route resolver -> optional full-volume build -> canonicalization -> X flip -> `StandardMPRViewer` | The Fast Qt caller needs a full-volume build. Another caller can already supply a volume. MPR rendering remains a separate domain. |
| Advanced Analysis / Advanced Imaging external workflow | Resident Slicer viewer and separate headless analysis roles | Readiness/prewarm and process ownership are separate from GUI DICOM import, MRML updates, and rendering. App-side VTK cache reuse does not eliminate Slicer's own import. |

Do not collapse Fast, Advanced and module execution domains to share a mutable viewer,
renderer, camera, worker lifecycle, or cache object. Shared code for policies is different
from shared mutable state. The existing Advanced-volume-to-MPR route also needs explicit
ownership checks before changing either consumer; it is not evidence that all routes
already have independent decoded buffers.

## Geometry contracts that govern optimization

The current [Advanced contract](../architecture/ADVANCED_VTK_GEOMETRY_CONTRACT.md),
[MPR constraints](../plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md),
and [domain boundary](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md)
take precedence over older proposals and historical journal entries.

1. Advanced pixels, ordered files, metadata instances, SOP mapping, and display indices
   must use the same frozen geometry contract. A metadata-only reorder is unsafe.
2. Advanced uses explicit medical affines while the rendering pipeline remains in its
   established voxel space. Activating native VTK direction mutation is a separate design
   change. Do not treat the stored field-data direction as interchangeable with it.
3. Preserve the conversion Y flip and the actual MPR X voxel flip. The proposed shortcut
   of replacing the X flip with a matrix/camera change is not an approved optimization.
4. MPR's `ZetaAnatA` columns model negative IOP row, negative IOP column, and actual stack
   direction. View routing and signs derive from this contract, not a bare slice normal.
5. Canonicalization attaches geometry without resampling. Native acquisition views keep
   their native interpolation behavior; reconstructed views keep their existing behavior.
6. Orthogonal MPR uses camera-defined planes. Oblique MPR uses explicit `vtkPlane` origin
   and normal; the camera deliberately stays stable. Reintroducing camera recentering
   can cause the previously fixed image-pan problem.
7. Scroll must preserve camera direction, distance and in-plane position. Do not add
   `ResetCamera` to interaction. Preserve physical spacing, slice correspondence,
   anatomical markers, measurements and AI-box coordinates.
8. Render windows, interactors and graphics-resource release remain on the GUI thread.
   Release resources before finalization and before the host loses its native context.

## Findings and evidence levels

### Reproduced with isolated synthetic inputs

**Cache invalidation can lose to an in-flight build.** In
`PacsClient/utils/volume_cache.py::get_or_create`, the owner publishes after its factory
returns. `invalidate`, `invalidate_study` and `invalidate_all` remove stored entries but
do not invalidate in-flight generations. A two-Event experiment paused a factory,
invalidated its key, then released it: `peek` returned the old-generation result.
This is a cache correctness prerequisite, not a reproduced clinical incident.

**The integrated volume wrapper records zero payload bytes.**
`PacsClient/utils/vtk_volume_service.py::build_or_get_volume` calls `get_or_build` without
`size`; the default is zero. An isolated process enabled the flag and supplied a synthetic
4096-byte payload: the stored entry accounted for zero bytes. The configured byte budget
cannot control these entries, although the entry-count cap still operates. A real fix must
measure retained VTK buffers, define ownership, and avoid double-counting shared storage.
The service is default-off; enabling it was confined to this short-lived probe process.

### Confirmed code behavior; user-visible impact needs measurement

**MPR still has GUI-side preparation.** In `toolbar_manager.py`, directory resolution,
file enumeration, header audits, and canonicalization occur around the responsive build
helper. `_load_vtk_paths_responsive` uses a worker for at least 80 files, but smaller
builds and its exception fallback can execute synchronously. The modal nested event loop
does not remove reentrancy. `_mpr_canonicalize.py::_read_dicom_slice_axis_sign` scans
headers and sorts by InstanceNumber; moving this work must preserve its existing result
and reconcile it with the actual loader order before changing the algorithm.

**Advanced reuse keys do not describe a source revision.**
`viewer_2d.py::reset_image_viewer` can reuse a reslice based on series identity and matching
dimensions. Preprocessing keys include identity/fallback series number, viewer height,
filter-enabled state and dimensions, but not a complete source/filter revision. Same-size
replacement data deserves a behavioral guard before optimization. This is a source-level
staleness risk; this review did not reproduce wrong displayed pixels in a live viewer.

**The preprocessing budget is not the whole retained-memory budget.** Advanced's class
cache has count/byte limits, but viewer-local references can keep outputs alive after
class-cache eviction. Eagle Eye uses the same Advanced implementation; class-level cache
keys do not establish module isolation. Account for per-consumer ownership and retained
buffers before claiming a process memory cap or changing cross-consumer reuse.

**Slicer prewarm has a narrower benefit than full warm display.** Resident runtime readiness
can remove process/module startup, while GUI import and scene construction still cost time.
Keep OPT-56 measurements separate from in-process Advanced and MPR metrics.

### Do not optimize these again without new evidence

- MPR already has render batching and interaction throttling, background large-volume
  scalar-range preparation and X flip, deferred/on-demand 3D, and teardown safeguards.
- The expensive oblique diagnostic validator is already opt-in rather than per-frame by default.
- Advanced already coalesces scroll work and throttles selected annotations/WL updates.
- Standard MPR's actual full loader calls SimpleITK through `get_itk_image`; the old claim
  that this route directly consumes a pydicom lazy volume is not the current implementation.
- `_mpr_series.py` contains a reload path that does not visibly rebuild all anatomical
  routing state. Repository search found definitions but no calls to `_create_series_scroller`.
  Treat this as a reachability question, not an established active bottleneck or a reason
  to alter geometry in the opening path.

## Documentation reconciliation

Reviewed references include the Advanced pipeline/architecture/affine/display-index docs;
MPR geometry pipeline, constraints, engineering journal, rotation status and pipeline
reference; S4B cache and domain-boundary plans; MPR latency, lifecycle, interaction and
deferred-layout reports; AI CSV conversion; and Advanced Analysis resident-runtime,
Slicer-control and offline-lumbar documents. Historical broad references were cross-checked
against the current source rather than accepted as implementation specifications.

| Historical statement | Current interpretation |
|---|---|
| One shared VTK cache/builder across all viewers | Superseded by the explicit domain-separation rule; cache service is default-off and per-domain by default. Advanced's observe call is not a cache read. |
| Canonicalization off / resamples into a canonical volume | Current active canonicalization returns without resampling; old text and unreachable code are not a proposed implementation. |
| Recenter oblique camera to fix a plane problem | Superseded by explicit-plane Fix E. |
| Remove the MPR X flip to save time | Preserve it; large-volume flip already moved off-thread in OPT-48 Phase 2. |
| Metadata always stays in DB InstanceNumber order | Historical `IMAGE_PIPELINE_REFERENCE` rule conflicts with its own later R31 addendum and the current Advanced contract. Order pixels and metadata together using the frozen contract. |
| Every geometry test is current | Five expected failures remain in display/geometry APIs. Historical identity-matrix assertions conflict with one-based display indexing, but stack-policy cases still need individual semantic review. |

Do not bulk-rewrite historical journals or apply their abandoned proposals. Future edits
should put a dated authority notice at the relevant conflicting sections and preserve history.

## Ordered implementation slices

| Order | Existing work item | Concrete scope and acceptance |
|---|---|---|
| 0 | OPT-35 / OPT-48 | Lock source revision, pixel/order/affine baselines and authoritative docs. Classify the five geometry xfails individually; do not just change expected values to make tests green. Capture current cold/warm GUI timings. |
| 1 | OPT-35 / S4B prerequisite | Add failing behavioral tests for invalidation during build, replacement generation, waiters/failure, byte accounting and domain isolation. Fix primitives before enabling any consumer. Define cancellation and avoid GUI waits. |
| 2 | OPT-48 | Move immutable MPR file/header/geometry preparation off the GUI thread with generation/close rejection. Preserve exact order, flips, pixels and interpolation. Measure small-series and fallback paths as well as large series. Keep GL creation on GUI. |
| 3 | OPT-35 / OPT-49 | Address Advanced/Eagle Eye source-revision keys and retained-memory ownership, one consumer at a time. Verify filter changes, same-size source replacement and AI-overlay alignment. No cross-domain cache activation as a shortcut. |
| 4 | OPT-48 / OPT-49 | Use measured render counts and close/reopen RSS/VRAM to select further work. Any render suppression must preserve final-frame delivery and pending-interaction flush. |
| 5 | OPT-56 | Measure Slicer readiness, transfer/import, scene creation and first visible image separately; optimize the observed stage with its process-specific lifecycle gates. |

Compound oblique behavior, camera contracts, new resampling, quality reductions and native
direction activation are separate geometry-sensitive work, not general optimization slices.
Each runtime slice needs a fails-before regression, minimal change, regression-catalog row,
applicable mirror parity, automated verification and an affected-workflow live source-GUI pass.

## Validation receipt and next measurement matrix

This expanded review ran direct pytest with `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`,
`-p no:debugging`, and `--reruns 0`: **418 passed, 6 xfailed, 6 warnings; exit 0**.
Selection: `tests/code/mpr`, the volume-cache/service tests, backend geometry boundary guards,
source/display/series-index/geometry APIs, MPR scroll/open-latency/off-thread-flip/deferred-layout
tests, and system MPR interaction tests. Five xfails are in geometry/display APIs and one is
the stale service-routing source assertion. The earlier Advanced-focused selection passed
39 tests; these are separate runs, not a claimed non-overlapping aggregate.

The two synthetic probes above used no DICOM, clinical database or GUI. Runtime code was
not modified. No FPS, latency improvement, clinical correctness, or leak-free acceptance
is established by these source/structural tests.

For each later slice, measure cold/warm first-2D and first-3D time, longest GUI block,
interaction p50/p95, render count, cache hit/build count, accounted bytes and retained RSS/VRAM.
Verify source identity/revision, ordered SOP correspondence, pixels, affines, markers and
millimeter measurements. Cover axial/sagittal/coronal/oblique and anisotropic volumes;
small and large stacks; rapid scroll/WL/resize; partial-download growth and same-count
replacement; repeated-series-number studies; mode switches; close during work; repeated
open/close; and Eagle Eye box alignment. Use the existing source-app control procedure;
record real rendered output separately from command acceptance and offscreen tests.

## Authorized follow-up: cache prerequisites implemented

The user authorized continuation after the review. This slice changes only
`PacsClient/utils/volume_cache.py` and `PacsClient/utils/vtk_volume_service.py`.
No feature flag, viewer geometry, pixel conversion, filter, or rendering path was activated
or altered. This is correctness and retention accounting, not a measured speed improvement.

- Each in-flight build now owns its event, result and error. Key/study/all invalidation
  detaches that generation and wakes its waiters with `VolumeCacheError`. Its factory may
  finish, but cannot publish or replace a newer generation. Explicit `put` also supersedes
  an older in-flight build. Return counts still count stored entries, preserving the API.
- Completed-flight delivery is independent of cache retention, so an oversized volume
  still reaches all waiting consumers without a second decode or an empty-result error.
- The integrated VTK wrapper supplies post-build sizing using `GetActualMemorySize()`
  converted from KiB to bytes. Sizing runs outside the cache lock. Existing integer-size
  callers remain supported. Duck-typed objects without VTK sizing retain the legacy zero
  fallback; real VTK buffers are covered by a synthetic `vtkImageData` behavioral test.
- This budget covers the cache's VTK dataset estimate, not process RSS, GPU allocations,
  consumer-held references or exact deduplication of aliased arrays. Pinned entries retain
  the existing exemption. Source-revision production and cancellation of the actual decode
  computation remain separate work.

**Fail-before:** four new guards failed, exit 1, on the unchanged implementation: three
invalidation scopes overwrote a fresh entry with the stale owner result, and an oversized
wrapper payload stayed cached. **After:** eight new cases pass, including multiple waiters,
new-generation completion before the old owner, failure delivery, oversized delivery,
real VTK byte budgeting, unchanged scalar values and independent module caches.

Expanded direct pytest: **398 passed, 5 xfailed, 1 xpassed, 6 warnings, exit 0**. Selection:
the three cache/service test files, backend geometry boundaries, `tests/code/mpr`, Fast
viewer pipeline adjacency, MPR open-latency and off-thread-flip guards. The quarantined
Fast source/timing cases and stale service source pin are reported, not counted as ordinary
passes. No source edits to Fast. Mirror verifier: **465 matching pairs**; neither modified
utility has a packaged mirror, so no unrelated mirror synchronization was performed.

**Live gate: BLOCKED on patch freshness.** The existing control client's ping and action
discovery succeeded. The source launch at 11:52:59 precedes this patch. No hot reload,
restart, extra instance, installed executable, patient selection or cache activation was
performed. A human fresh source launch/sign-in is needed for affected-workflow acceptance.
Default-off smoke must be distinguished from a deliberate cache-enabled validation session;
the latter requires worker-driven loading, same-series reopen, distinct domains, close/reopen
and rendered identity checks. Do not enable cross-domain sharing. The broader optimization
program and this slice's live acceptance remain open.

Rollback: revert this slice's two utility diffs and its guard as a targeted change if needed;
do not reset the dirty worktree. `AIPACS_VTK_VOLUME_CACHE` remains off by default.

## Fresh source log review, 15:01 launch

The user explicitly requested launch, then KPI/log inspection. The source instance started
at 15:01:03; the disk notice was acknowledged with OK and sign-in left to the human.
Subsequent ping and discovery of 83 live actions succeeded. This supersedes the earlier
patch-freshness blocker, but does not close cache-enabled or MPR workflow acceptance.

Bounded review on 2026-09-16 through approximately 15:06, without patient identifiers:

- No ERROR/CRITICAL records in the selected fresh app/viewer/download log window.
- 21 `MAIN_THREAD_STALL` records; maximum 6102.8 ms at 15:03:07. Associated sampler
  stacks traverse Advanced preview application, `ImageViewer2D` construction, direction
  extraction, input binding and initial Render. Samples locate work, not its exact cost.
- Startup main-window construction: 1855.0 ms. Another 2177.5 ms event-loop gap coincides
  with VTK placeholder construction/loading-overlay preparation.
- Two `UX_VIEWER_INTERACTIVE` records report 5377.8 and 154.6 ms. These are distinct
  events, not a controlled cold/warm comparison. Three first-display timing fields are
  `-1.0`, meaning unavailable, not a successful timing measurement.
- Both recorded source/display geometry bindings report valid geometry. This is contract
  telemetry, not independent visual or clinical verification.
- Viewer log has 733 WARNING-level entries, predominantly diagnostic audit tags, including
  240 geometry-field-map and 149 orientation-audit entries. Investigate logging overhead
  with measurements; do not infer 733 faults or remove geometry checks blindly.
- The new main-process native sink contains one `0x8001010d` COM exception record, zero
  Python-fatal records and zero watchdog dumps. The same process remains alive and ping
  succeeds. This is a native exception observation, not proof of terminal crash or safety.
- Framework schema has 42 keys matching its baseline. Its displayed three PASS records
  are synthetic records dated 2026-05-28 under `run_id=source-run`, not this session.
  The dashboard chooses run IDs lexically; its green latest-run summary is not current
  performance acceptance. Its 428 native records are historical inventory, not fresh crashes.
- No `MPR-OPEN-KPI` or `VTK-VOLUME-SHADOW` markers were found in this window. Fresh app
  availability is verified, but cache-enabled behavior and MPR remain unverified.

No runtime changes were made for this log-review request. Next evidence priorities are
phase timings around Advanced construction/first rendering and trustworthy session-scoped
KPI selection, while retaining geometry/camera behavior.

## Next-test preparation: Advanced constructor timing (OPT-23)

Implemented after the user requested proceeding within the VTK scope. This slice is
measurement preparation for the observed 6102.8 ms gap, not a latency fix. Generic KPI
dashboard work remains handed off. The first Render followed by `zoom_to_fit` is intentional:
VTK's first-render camera reset must run before fitting. No render was removed or reordered.

`ImageViewer2D.__init__` now records elapsed, non-overlapping phases with the small
`startup_timing.py` helper: VTK base construction, object setup, preprocessing, direction
setup, geometry preparation/binding, render-window setup, reslice, native input binding,
display setup, overlays, first render, fit/render, and finalization. Exactly one
`[ADVANCED-STARTUP-KPI] schema=1 build=<process-local counter> outcome=complete`
summary is logged per completed construction, with `total_ms` and named `*_ms` fields.
It contains no patient/series identity, file paths, dimensions, or clinical metadata.
Nothing is added to scroll callbacks; no image/widget is retained by the helper.

Limitations: the record measures elapsed phase time, not exclusive CPU time or screen
presentation latency. The display-setup phase includes existing diagnostics and mapper/
camera setup; the geometry phase includes metadata initialization and inversion handling.
An aborted constructor emits no completion; existing sampler/native logs remain necessary.
The helper neither replaces general KPI collection nor instruments reslice reuse/reset.
Absence of a constructor record during an in-place series reset is therefore expected.

Validation: the structural boundary guard failed before instrumentation (exit 1).
Four final guards cover boundary placement and first-render/fit ordering, deterministic
non-overlapping durations, single-record emission, log-sink failure isolation and absence
of false completion for unfinished construction. Expanded direct pytest: **257 passed,
6 existing xfailed, 6 warnings, exit 0**; selected Advanced interaction, scalar-input,
geometry, cache and builder-mirror guards. An AST comparison against the pre-edit tracked
viewer showed exact executable equivalence after removing only the timing import/calls.
Canonical and viewer-package copies synchronized with the official tool: **466 pairs match**.

Next source-GUI test (still pending; current process predates this instrumentation):

1. Fresh single source launch with the existing test-server flag; human sign-in, then
   ping/actions and verify source freshness. Keep cache/default geometry flags unchanged.
2. Open the same authorized Advanced workflow as the earlier stall. Observe actual pixels,
   count, markers and initial fit. Repeat the same series operation and distinguish a
   new constructor from an in-place reset; do not call distinct events a cold/warm pair.
3. Exercise actual wheel scrolling, WL and zoom; confirm first/final images and camera
   behavior. Include Eagle Eye when using its Advanced-derived viewer; keep MPR a separate lap.
4. Extract the new phase fields from the session window, correlate with stall samples,
   and choose the dominant proven stage for a separate minimal fix. Constructor completion
   and green automated tests are not GUI/performance acceptance.

Rollback is the timing import/checkpoints plus helper and its packaged copy only; no
image-processing behavior needs restoration. No new source launch was performed in this slice.

## Preview count presentation and diagnostic correction (OPT-23 / OPT-35, 2026-09-16)

User request: preserve geometry, image quality and filters; stop presenting an eight-image
preview as if the entire known 80-image series contained eight images. Implemented a
presentation-only counter: **`1 / 80 | 8 ready`**, updating with navigation, then ordinary
**`1 / 80`** after full binding. It uses the loader's existing `preview_total_instances`
from the resolved series folder, not the thumbnail badge. Unknown/invalid totals and a
preview that already reaches the reported total still say `Loading`; full payloads ignore
stale preview totals. There is no inferred server-wide total when only partial disk data
is known. The denominator is a known preview-loader count, not a promise that mixed-size
or unsupported inputs will all pass full-series validation.

Only the Advanced image counter changes; actual VTK count, slider bounds, wheel handling
and current preview position remain tied to available images. No extra header/DB/disk
read occurs during drawing. No preview admission, geometry, decode/filter quality, cache
policy or Fast rendering changes. Five counter guards failed before correction; seven
pass, including real initial text actors and refresh on scrolling/full binding.

The geometry-related correction is deliberately restricted to diagnostics. Eight tests
against the real audit reproduced false 180-degree normal mismatch on ideal camera bases
in axial/sagittal/coronal/oblique cases. Correct the expected screen normal's handedness;
do not alter render geometry. `schema=2` now states
`comparison_scope=unregistered_camera_vs_dicom`, reports `camera_iop_basis_match`, and
sets `orientation_valid=not_evaluated`. Raw camera vectors are no longer mislabeled LPS.
The legacy heuristic becomes `legacy_failure_hint`; the diagnostic report no longer calls
its table proof. A ninth guard failed on that misleading report label before correction.
Camera/image MTime, position and view-up stay identical across audit calls. Full clinical
geometry validation is explicitly still open; mixed-orientation and preview metadata
alignment remain separate concerns, not silently treated as solved by a sign correction.

Latency evidence from the inspected session: maxima across collected (not matched) loads
are about **364 ms disk read**, **172 ms series switch**, **155 ms ITK-to-VTK conversion**,
and **10.3 s filter chain**. Whole-load maximum is about **12.1 s**. These are different
samples and may include background work, not an additive timeline for one drop. This
slice claims improved progress clarity, **no speedup**. Preserve all filters and quality;
profile matched filter stages and contention before changing computation or caching.

Verification: **257 passed, 5 existing geometry xfailed, 6 dependency warnings, exit 0**
across counter/diagnostic/complete-stack/US/partial-stack/slider/geometry/MPR/architecture
and builder guards. **467 mirror pairs match**, including new `slice_progress.py`.
Existing control ping/actions succeed, but the source process started at 17:58:46 before
these changes. No hot reload or restart. Fresh live gate: drag a known complete 80-image
series; verify preview says total 80 plus ready count, scroll remains within loaded frames,
and full binding removes the loading suffix. Also verify new diagnostic fields and the
unchanged image orientation/markers with known cases. Roll back this slice's counter
import/calls/helper, audit-only changes and report-tool changes; resync the viewer payload.

## Consolidated acceptance review: 17:58:46 source session (2026-09-16)

**Human confirmation:** the user now confirms the Advanced drag/drop background flash
is fixed. Earlier US RGB appearance confirmation still stands. This accepts the reported
visual symptoms on the user's tested workflow; rapid-overlap/teardown and all separate
module workflows are not thereby certified.

Read-only review through app 18:04:03 / viewer 18:04:01 / downloader 18:01:02:

- No actual ERROR or CRITICAL severity in these three logs. Fresh source parent/child
  launched at 17:58:46. Existing control ping and action discovery succeeded.
- Four complete Advanced binds have **30, 30, 88 and 80** metadata instances, matching
  VTK Z dimensions exactly. Control readback reports the active viewport at **80 slices**,
  `preview_only=False`, `progressive_mode=False`. The other viewport has zero slices;
  it is not evidence of a partial active series.
- **Seven full hot-cache reads** have count, instance-path order hash, canonical-order
  hash and display-order hash identical to the same-series full bind. A separate main-cache
  read contains one preview metadata instance with an eight-slice preview volume before
  the full 80-image replacement. Do not count that preview as a complete-stack cache hit.
- The running process has no overrides for `AIPACS_VTK_VOLUME_CACHE`, its SHADOW flag
  or CROSS_DOMAIN flag; their source defaults remain **off**. Successful legacy viewer
  hot-cache reads do not establish acceptance of the separate shared-volume cache.
  Prior generation-invalidation/byte-accounting unit guards remain the evidence for that
  inactive service. Memory boundedness/leak freedom cannot be certified from these reads.
- Completed preview constructor times: **71.084, 80.684, 70.746 ms**; first-render phases
  **44.603, 47.676, 42.855 ms**. Do not substitute them for full-load latency.
- All eight render-geometry records say source/display valid and no collapse. Two
  `mixed_plane_or_orientation` warnings report 90-degree mixtures; neither warned Series
  UID was among the full series bound in the inspected window. They remain an admission
  follow-up for mixed/localizer data, not proof that a displayed volume was mixed.
- 287 camera-orientation audit records say false: 184 show row/column/normal mismatch
  0/180/0 degrees and 103 show 0/~95/0. Code inspection at
  `viewer_2d._emit_advanced_vtk_orientation_audit` exposes an internally inconsistent
  diagnostic: expected right=row and up=-column imply screen normal=-cross(row,column),
  but the audit compares that screen normal with +cross(row,column). A synthetic axial
  basis gives dot=-1 even at the audit's ideal right/up. Thus this boolean cannot be
  treated as clinical orientation truth. Repair the diagnostic with a fail-before
  handedness/transform-aware guard before considering any render-geometry correction.
- Viewer diagnostics contain 2708 WARNING-level entries, many routine per-scroll audit
  messages (660 hydration field checks, 611 audit-active, 287 marker and 287 display-layer
  audits). This is a logging-noise/throttling candidate, not a measured latency cause.
- 27 stall samples include growing gaps to **4843.8 ms** through thumbnail image reads /
  widget creation, and another gap rising to **10642.5 ms** with only Qt event-loop/notify
  frames. These samples are cumulative observations, not 27 independent long stalls.
  No VTK render stack supports attributing the long gap to VTK. Handoff recorded with
  the UI-stall owner. COM `0x8001010d` recurs while the source remains reachable; recorded
  with the crash owner, no terminal VTK crash claim.

No Zeta MPR, Eagle Eye or external Advanced Analysis image-path evidence appears in
this viewer session window. Their domain-specific acceptance stays open. No runtime
code or flags changed in this consolidated review. Remaining VTK work is accurate
orientation diagnostics, mixed-orientation/preview admission validation, and separate
module live passes; do not mark the whole VTK program complete.

## Advanced drag/drop loading cover and full-stack checks (OPT-23, 2026-09-16)

The user confirmed that **US displays in color correctly**. This is human visual
confirmation of RGB appearance, not confirmation of every frame or a matched timing
run. The new report is a brief background/Home-page exposure at the start of Advanced
thumbnail drag/drop; Fast already holds its own Qt loading surface correctly.

Three code-level defects were reproduced without patient data:

1. The Advanced native loading cover painted alpha 210, allowing underlying content
   through. A real Qt corner-pixel guard returned `(10, 15, 19, 210)` instead of opaque
   black. Fast uses a child overlay; its existing appearance passed the same baseline.
2. Re-showing an existing branded overlay did not synchronously repaint it. The VTK
   switch tried to repaint `viewport_spinner.spinner`, which is normally None when
   the branded `overlay` is active. That failure was silently caught.
3. Delayed hide callbacks targeted the manager directly, so completion from an earlier
   switch could dismiss a newly shown loading cover. The overlap guard reproduced
   `overlay is None` while the second operation was still loading.

Correction: viewport loading requests an opaque black backdrop only for the native
overlay branch. General overlays and the Fast child backdrop keep their defaults.
Existing overlays repaint synchronously without event-loop pumping. VTK series-switch
and reset completion timers now capture the loading generation; a newer show, hide or
cleanup invalidates old callbacks. No renderer geometry, decode, cache identity or
frame-order policy was changed. This prevents the reproduced cover failures; native
Windows drag/drop flicker acceptance still requires a live pass.

Fail-before: **4 failed, 1 passed**, exit 1 (pixel opacity, reused repaint, stale hide,
and unscoped scheduling guard). Final new coverage: 6 loading-cover cases plus 2 full
stack cases. Expanded verification: **106 passed, 15 opt-in native-GUI stress cases
skipped, 1 existing progressive-grow xfailed**, exit 0. Dependency warnings remain.
Official mirror sync/verification: **466 matching pairs**. The skips are not GUI passes.

Full-stack verification used synthetic **3- and 30-image MR series** through the actual
filesystem loader, SimpleITK and VTK. Every frame had unique scalar values; loaded
metadata order matched the corresponding pixel frames, no frame was omitted, VTK's
reported count matched the source count, and both first/last indices were reachable.
Existing partial-stack and slider-domain guards passed. The prior live log also had a
30-instance / 30-slice full binding; that alone is not proof of user wheel traversal.
The existing control-client probe was unavailable during this investigation, so live
slider state and real OLE drag/drop were not tested. No source app was relaunched.

Next fresh-source GUI lap: drag a known complete 30-image series onto an occupied
Advanced viewport; verify continuous black/loading coverage, including rapid repeated
drops and preview-to-full replacement; verify 30 images and first/last/back scrolling.
Then verify US RGB, CT/US/CT switching and an unchanged Fast loading presentation.
Rollback only this slice's loading-overlay option, spinner generation/repaint changes,
six VTK scheduling call sites and obsolete repaint removal; resync the viewer payload.

## Latest log review: 17:14:46 source session (2026-09-16)

Inspected through app 17:23:40 / viewer 17:22:57. MR preview constructor completed
at 17:22:19 in **64.791 ms**, first render **40.832 ms**. At 17:22:22 the full
series post-bind has 30 instances and VTK dimensions **384 x 240 x 30**. No new
US load occurred in this window; this does not close US acceptance. App/viewer
contain no actual ERROR/CRITICAL-level records in this inspected session.

Source/display contracts report valid and no collapse at both bindings, while
the camera-vector orientation audit reports `orientation_valid=False`. That audit
compares camera vectors to DICOM row/column/normal vectors; it is not by itself a
pixel/affine-aware proof of a wrong clinical orientation. Keep this discrepancy
open for live geometry verification; do not change the protected geometry on this
log evidence alone. Two stall samples: **428.0 ms** and **424.1 ms**.

Native COM `0x8001010d` recurs; source remains responsive and existing test-client
ping returns pong. Downloader's sole ERROR is `Download cancelled (preemption)`;
it is outside the VTK display path. No runtime changes made in this readout.

## Log review: 16:51:12 source session (2026-09-16)

The user requested another source launch and then a log review. Existing control ping
succeeded; the source child remained alive/responding at the final probe. No runtime
code changes or synthetic GUI actions were made during this review.

- At 16:52:28 the nonspatial US loader accepted **5 frames**, followed by an
  `ADVANCED_SERIES_BIND` post-bind record with the nonspatial ordering contract,
  5 metadata instances, VTK dimensions **1136 x 852 x 5**, extent Z=0..4 and current
  slice 0. This is a different frame count/dimension from the earlier 12-frame report;
  do not represent it as a matched reproduction of that original series.
- No missing-IPP/IOP exception, Advanced index-build failure or VTK scalar-input guard
  error appeared in this session window. This supports successful delivery/binding,
  not visual confirmation of RGB, scroll endpoints or clinical orientation.
- One `source_geometry_invalid` warning occurs on the preceding **single-frame preview**,
  before the full five-frame nonspatial bind. Preview admission remains a separate VTK
  follow-up; the full-load fix must not be described as covering that preview boundary.
- Two completed constructor KPIs: **105.596 ms** and **77.082 ms**, with first-render
  phases **55.041 ms** and **32.679 ms**. These are initial/preview constructions;
  they are not full-series switch timings or matched evidence of an optimization.
- 13 main-thread stall samples, maximum **1440.9 ms**. No 6.1-second sample in this
  window, but workloads are not matched, so no speedup claim.
- The two textual `CRITICAL` occurrences in viewer diagnostics are INFO-level download
  priority notifications, not CRITICAL-severity errors. Viewer records have no actual
  ERROR/CRITICAL severity in the inspected window.
- Repeated series-display-key exceptions in Home/thumbnail setup are handed to the
  UI-stall owner document. Native log contains Windows COM exception **0x8001010d**;
  the process subsequently remains alive/responding. The recorded background stack
  includes Advanced Analysis resident-service subprocess startup, but does not prove
  it caused the COM event. Handoff is in the crash-closure audit; no VTK crash claimed.

Live visual acceptance remains open, especially the original 12-frame US workflow,
preview markers, frame scrolling, CT/US/CT switching and spatial MPR regression lap.

## US correction (OPT-35): code verified, live pending

The reported US failure and two related viewport defects are now corrected in source.
This slice changes only the Advanced loading/viewing boundary and its shared MPR
admission check; unrelated dirty toolbar edits are preserved.

- `advanced_nonspatial.py` supplies a separate display plan for single-frame Ultrasound
  Image Storage with both IOP and IPP absent. Every file must have the same Study/Series
  UIDs and dimensions/components, unique SOP identity, and match supplied identity hints.
  Partial spatial headers, other modalities/classes and multiframe input are rejected.
  Frames sort by InstanceNumber then SOP identity. No patient-space affine, anatomical
  ordering, slice spacing or geometry-cache entry is fabricated. Actual PixelSpacing is
  retained when present; US-region calibration is not newly implemented by this slice.
- `image_io.py` uses that plan only after strict spatial indexing raises ValueError.
  The DB, filesystem and grouped Advanced routes use the same plan and stamp an explicit
  `spatial_geometry_available=False` capability. Fast loading and strict spatial indexing
  remain unchanged. Header reads and decode remain in existing loader execution paths.
- `viewer_2d.py` retires the previous source/display affine and registry binding before
  attempting a new bind, skips patient-geometry construction for display-only frames,
  and clears orientation markers. Raw frame scrolling remains zero-based and unreversed.
- Reused byte-RGB(A) color mappers reset to VTK's neutral 255/127.5 W/L. The synthetic
  CT-to-RGB test previously turned colored input into grayscale/saturated output and now
  preserves exact channel values. First-use mapper behavior and grayscale W/L are unchanged.
- The shared toolbar MPR route refuses explicitly nonspatial sequences with an explanatory
  message, and Advanced curved-MPR activation is blocked for them. Real MPR transforms,
  including the X flip, explicit planes and camera geometry, were not changed.

Verification: after correcting fixture syntax for the installed pydicom, the original
loader and stale-binding guards failed for the intended reasons (2 failed / 5 passed,
exit 1). The RGB guard then failed on mismatched pixel values before its correction.
Four MPR admission cases also failed before gating. Final new suite: **17 passed**.
Expanded geometry, interaction, native-input, MPR-route, architecture and builder parity
selection: **245 passed, 5 pre-existing quarantined xfailed, 6 dependency warnings,
exit 0**. Synthetic DB-metadata, grouped and filesystem routes all returned three aligned
frames. DB-facing tests patch the database path, clear connection pools and stub repository
access; no live database was used. Official mirror sync/verification: **466 matching pairs**.

Live gate: existing control-client ping and action discovery succeeded. The one source
app (venv launcher plus child, launched at 15:42:20) predates the runtime changes. It was
not restarted or hot-reloaded. At the final continuation check, no source `main.py`
process remained and the existing test-client ping could no longer connect.
**No live US rendering pass or performance improvement is
claimed.** After a fresh human source launch/sign-in, use actual UI input to open the same
authorized US series, verify all 12 frames and RGB appearance, scroll first/last/back,
switch CT/MR -> US -> CT/MR, check marker/zoom behavior and confirm MPR rejection for US.
Inspect only session-scoped load/render/native logs and startup phase KPIs. Standard/Zeta
MPR with a real spatial CT/MR volume is a separate regression lap.

Rollback: remove this slice's nonspatial helper and loader branches, viewer geometry/RGB
guards and MPR admission additions, then resync the viewer payload. Preserve earlier
startup instrumentation, cache fixes and unrelated worktree changes. No configuration,
clinical files, schemas or cache-enable flags were changed.

## US missing viewport: 15:32-15:35 session investigation

User report: ultrasound did not appear in the viewport. This is a VTK/Advanced loading
compatibility issue, distinct from the generic series-key exception handed off below.
The source process was no longer present and test-server ping failed at investigation time;
no restart, live database write, file rewrite or patient-image export was performed.

Read-only identity matching between recent log Study/Series UIDs, the local catalog and
on-disk headers identified one US series with 12 stored files. All headers matched the
selected SeriesInstanceUID. They describe single-frame RGB Ultrasound Image Storage
objects (SOP class `1.2.840.10008.5.1.4.1.1.6.1`), 1080 x 810, with JPEG Lossless SV1
encoding (`1.2.840.10008.1.2.4.70`) and no ImagePositionPatient/ImageOrientationPatient.
The files lack the Part-10 preamble; strict pydicom reading fails, but the application's
force-reading convention succeeds. This alone is not evidence of corrupted pixel data.

Boundary probes, all local with only structural aggregates emitted:

- pydicom decoded one selected sample to nonconstant uint8 RGB pixels.
- SimpleITK read all 12 files into a 1080 x 810 x 12 image with three components.
- The existing ITK-to-VTK conversion preserved three components and one scalar tuple per
  voxel. This does not verify color appearance or clinical calibration in a live viewport.
- Calling the actual `build_series_geometry_index` on those same files raised `ValueError`
  for missing IPP/IOP. `_read_minimal_header` currently permits only a special single-slice
  MG fallback; these US files are rejected before the Advanced volume can be delivered.
- Advanced DB, filesystem and grouped load paths invoke this strict contract. The controller
  treats unsuccessful loading as not-resident/download-waiting. Session logs show repeated
  `ViewportLoadWaitingForDownload`, `ViewportLoadResumedFromDisk` and
  `RemoteSeriesDownloadAttached` transitions for this US identity despite local files.

The narrow correction requires an explicitly non-spatial US display path: preserve actual
frame order, RGB, source identity and image-local calibration; do not invent patient-space
IOP/IPP or enable anatomical MPR/reference-line/sync semantics from a fabricated affine.
Keep CT/MR strict geometry and the real MPR transforms unchanged. Prove with synthetic
US fixtures through DB/filesystem/grouped routes and source-GUI rendering before acceptance.
No geometry contract or loader was changed during this diagnostic request.

Two constructor timing records in this later session completed at 100.037 and 114.525 ms
(first Render 43.873 and 74.993 ms). They are not attributable to the failed US constructor
and are not a matched before/after speed comparison. They demonstrate the new timing is
active, not that US rendering succeeded or that the earlier 6.1-second gap is fixed.

A separate `Prior series display keys must be study-local numeric handles` exception
occurred during background setup of a CT-containing study. It is recorded in the UI/identity
owner report and must not be substituted for the independently reproduced US geometry failure.


## OPT-35 preview frame metadata alignment (2026-09-16, post-20:51 session)

The latest session bound an eight-frame preview with one metadata record, then an
88-frame full volume with 88 records. Other preview/full pairs were 8/30 and 8/80.
Full binds matched VTK depth. Two main-cache/hot-cache pairs agreed on counts,
dimensions and all three order hashes. Initial render took 1677 ms versus 80/48 ms
on subsequent constructors. Preview-to-full bind intervals were approximately
4.93/1.57/6.48 seconds; these are not decode-only durations or a controlled benchmark.
The native COM finding and shared UI stalls remain with their owners in
[crash closure](CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md) and
[UI stall evidence](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md).

Three synthetic fail-before guards reproduced a one-record filesystem preview,
DB metadata order differing from decoded pixels, and publication despite missing
header metadata. `load_series_preview` now reads bounded header stubs for exactly
the selected files, in decode order. It retains actual instance numbers, SOPs,
IOP/IPP and spacing; it does not substitute the first N DB records. Missing headers,
multiframe files without per-frame mapping, or decoded-depth mismatch defer the
preview to the existing full-load path. No fabricated per-frame metadata is published.
This is file/pixel alignment, not a new geometry index or clinical orientation verdict.
Full-load ordering, transforms, filters and Fast execution remain unchanged.

Six final guards cover filesystem/DB order, missing headers, single-slice numbering,
multiframe deferral and count mismatch. Synthetic repositories are stubbed and the
DB path is isolated with pools cleared; no database file is created. Direct pytest:
280 passed / 4 existing xfailed / 1 existing quarantined xpassed in the load/preview/
Fast-adjacency/parity suite, and 129 passed / 5 existing xfailed in the additional
geometry/MPR suite (six preview cases overlap). Both exit 0; 467 mirror pairs match.
The changed PacsClient source has no payload mirror. No speed improvement is claimed.

Control client ping and list_actions succeed, but the source process predates this
patch: live acceptance is pending a fresh source session. Next gate: native drag/drop,
scroll within ready frames, compare preview SOP/IPP/pixels and count, then full-stack
first/last slices and cache reopen. Roll back only this preview metadata hunk plus
its guard; preserve preceding US and geometry-diagnostic fixes. Mixed orientation,
complete transform-aware validation and filter timing optimization remain open.


## OPT-23 native cover after page switch (2026-09-16)

User reports the now-opaque cover persists over Download Manager when switching
pages during import/loading. Reproduced with real Qt widgets: anchor Hide correctly
hid an existing top-level cover, but a later background `show_loading()` could create
or re-show it while the anchor remained hidden. The old event-only guard had already
received Hide, so it could not suppress that later show.

`AiPacsLoadingOverlay.show()` now checks scoped anchor liveness/visibility and loading
intent on every show request. Hidden anchors keep the loading intent but cannot show
the cover. Returning to the viewport restores a pending cover via the existing Show
handler; completion while hidden still clears it. Child-mode Fast overlays and native
window flags are unchanged. No geometry, decode, filters or download code changes.
Two behavioral cases failed before the fix (new/reused cover while hidden); a third
checks completion while hidden. Focused overlay, liveness, reentrancy and lifecycle
suite: 46 passed, exit 0; 467 mirror pairs match (this PacsClient file has no mirror).
Ping/list_actions work. Live acceptance remains pending a fresh source session: start
load/import, switch to Download Manager, ensure no floating black cover, return while
loading and after completion. Rollback only the `show()` override plus these guards.

The separate never-local series drop report is handed off in
[Download Pipeline](../pipelines/download-pipeline.md#2026-09-16-vtk-handoff-remote-drop-waits-without-visible-download).
Around 21:31, two accepted drops attached remote-download waiting states; intent begin
records report Downloading, but viewport wait events continued beyond 21:37. This is
not proof of bytes transferred, failure cause, or a VTK rendering defect. No download
runtime fix or queue mutation was attempted here.


## OPT-23 filter-stage measurement (2026-09-16)

The 21:30-21:46 source logs show full-load maximum 12079 ms and filter-chain maximum
11462 ms; these aggregate records cannot identify the expensive individual filter.
A synthetic 30x256x256 MR profile with two ITK threads measured 1.05/1.08 seconds in
apply_filters, spread over multiscale (0.36/0.42 s), adaptive (0.28/0.30 s), and
Laplacian (0.21/0.22 s). This is not a reproduction of the clinical 11-second workload.

`image_filters.apply_filters` now emits one PHI-free ADVANCED-FILTER-KPI record per
completed enabled run: preparation, noise, anti-alias, multiscale, Laplacian, adaptive,
final cast/clamp and separately measured yield time. Existing filter operations,
parameters, scheduling sleeps and geometry are unchanged. Skips/failures do not
emit a completion record. Two guards failed before instrumentation; four final guards
verify synthetic baseline MR/CT pixel hashes, geometry, privacy, skip and exception
semantics. Focused load/filter/parity suite: 30 passed, exit 0. Current runtime control
probe returns ConnectionError, so live acceptance is blocked pending human source
launch/sign-in; no hot reload/restart was attempted. Inspect stage records on the same
slow series before selecting an optimization. No speed improvement is claimed.

The first-render stall sampled font_manager/mathtext within VTK Render. Installed
vtkTextActor exposes no per-actor backend override; vtkTextRenderer default backend
is shared. No global backend change or GUI-thread warmup was made because other VTK
domains and markup rendering could change. Separately, existing filter exception
cleanup can bypass restoration of ITK thread defaults and Windows worker priority;
this needs its own guarded reliability slice, including concurrent-owner semantics.
Rollback only the timing checkpoints and KPI line. The source has no packaged mirror;
existing mirror parity passes. Patient content was not used in synthetic profiling.


## 2026-09-16 tab-switch preview stuck at 8/104: investigation

User screenshot shows 8 ready out of 104 after dropping a second series and rapidly
switching between the patient tab and Download Manager. No patient identifiers or
screenshot are copied into repository artifacts.

Confirmed log sequence: 23:01:59.856-23:02:00.060 binds an eight-frame preview;
23:02:00.472 records 104 aligned source-file/metadata entries; 23:02:03.416 completes
filtering with slices=104 (one requested thread); 23:02:03.445 attaches download-wait
state. At 23:02:05.457 hot_cache returns n_instances=104 with dims=(320,210,8), and
23:02:05.480 post-bind still has eight pixel slices with 104 metadata records.
Thus full filtering completed, but the resumed display used an inconsistent cached
payload. This is not explained by filter duration or the count label alone.

Source mechanisms requiring a guarded reproduction: `_vc_load` returns False after
caching an item when `_tab_active` is false; `_vc_switch` treats False as not-resident
and enters download-wait. `_vc_cache._refresh_stored_metadata_instances` can extend
non-indexed preview metadata in place and republish it with unchanged vtk_image_data;
`_sync_viewer_metadata_instances` can also extend non-indexed viewer metadata. The
hot-cache validator checks current object identity, not pixel/metadata depth. These
paths explain how an eight-slice preview can survive with a larger metadata list,
but the exact mutator call and race ordering need a synthetic reproduction before
assigning the complete root cause or changing runtime behavior.

Ownership: shared tab activation/result handoff and metadata/invalidation contract
belong to Unify; decoded VTK payload integrity belongs to Advanced. Coordinate a
single reproduction with full result arriving while hidden, activation before/after
completion, cache promotion, replacement/cancellation, and completed download without
another signal. Preserve geometry ordering and per-frame pixel/SOP alignment. This
investigation made documentation-only changes; no runtime fix or live-pass claim.

Paired owner record: [UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md).

## MPR/NPR inbound review: 23:01 open (2026-09-16)

Reviewed the inbound 22:47-source KPI handoff against app/viewer logs and current
Standard Zeta MPR code. No MPR ERROR/CRITICAL severity in the inspected 22:55-23:07
window. One open uses the existing vtk_simpleitk volume with 144 metadata instances.
The constructor KPI is 1190 ms; UI stall samples are 1713.3 ms and 1655.9 ms, not
additive exclusive construction timings. First 2D interactor initialization spans
291 ms; deferred 3D initialization spans 927 ms; reslice prewarm spans 253 ms.

The sampled GUI stack confirms toolbar canonicalize_volume reaches
_read_dicom_slice_axis_sign, which enumerates files and reads DICOM headers inline.
Deferred 3D uses a Qt callback but still constructs/render-initializes on the GUI
thread. Deferral does not make that work nonblocking. Preserve GL thread affinity;
move only independently prepared immutable data off-thread with cancellation guards.

Five GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH records explicitly mean local MPR geometry
continues without the Advanced contract adapter. Existing provenance reports
geometry_ok=True/missing=none, direction metadata is loaded and input flip is applied.
Neither message validates clinical orientation. The fixed-layout used_default_axial
classification is a policy label, not proof that sagittal/oblique inputs are wrong.
Do not remove direction transforms or X/Y flips to suppress warnings.

Additional source-review concern: _resolve_mpr_volume_for_route forces full rebuild
for Fast Qt or missing scalar data, but has no explicit preview_only/depth-consistency
gate for an existing Advanced volume. The observed MPR open is not proven partial;
the separate 8/104 incident makes a synthetic preview-to-MPR admission guard a high
priority before a correction. Full spatial volume and no fabricated geometry required.

Inbound test-double issue also remains: test_vtk_widget_split.py spinner double lacks
hide_loading_after; preserve its progressive-count assertion when updating the double.
Review priorities: partial-volume admission proof; off-thread canonical header prep;
deferred 3D timings/presentation and cancellation; known-phantom orientation validation.
Documentation-only review: no runtime change, performance improvement or new live
acceptance claim. Related tab-switch/cache corruption remains a separate coordinated
Advanced/Unify slice.


## OPT-35 / OPT-48 guarded MPR admission (2026-09-16)

The source-review concern is now reproduced and guarded. Eight synthetic cases
(orthogonal/curved/projection/dental route names, explicit preview or 8 pixels versus
104 metadata records) previously returned a launch-ready volume. A ninth failed
recovery-message test and a passing complete-volume control established the baseline.

The shared toolbar resolver now blocks reuse of an existing scalar VTK volume when
preview_only is true, depth is invalid, or metadata contains more instance records
than the pixel depth. This is a bounded in-memory gate: no new GUI-thread reads,
filtering, reconstruction or cache mutation. Explicit messages ask the user to wait
for full loading or reload inconsistent data. Complete-volume reuse, Fast Qt full
rebuild and existing nonspatial US refusal remain intact. A smaller metadata count
alone is not rejected because multi-frame data need not have one record per frame.
This is not a proof of completeness for all unknown/multiframe metadata shapes.

Verification: 9 failed / 1 passed before; 10 final new cases. Combined MPR, launch-route
and US suite: 192 passed, exit 0; 467 mirror pairs match (toolbar has no payload mirror).
No geometry, flips, camera, resampling, image quality or processing changes. Existing
unrelated toolbar/Eagle Eye changes preserved. Current source control ping/actions
succeed, but it predates this edit; fresh GUI gate remains open. On the next source
run attempt MPR during preview, then after full completion, and verify the existing
2D view survives rejection and full MPR renders. The 8/104 upstream tab/cache issue
is not fixed by this admission guard. Cold-open header/3D latency remains separate.
Rollback only the new admission and message branches plus their test file.


## OPT-35 Advanced decoded cache integrity (2026-09-17 coordinated fix)

Method ownership agreed with Unify: this slice changes only
`_vc_cache._is_full_volume_cache_candidate`, `_refresh_stored_metadata_instances`,
`_sync_viewer_metadata_instances`, and `_vc_backend._get_series_by_number_fast`.
Shared load delivery, activation and teardown remain with the Unify owner.

Five synthetic failures reproduced: both directions of metadata/depth mismatch passed
full-cache admission; preview metadata grew independently of eight decoded slices;
live Advanced metadata was extended without replacement pixels; invalid hot/main
entries were re-admitted through the index. The new pure in-memory
`advanced_payload_integrity` helper identifies explicit vtk_simpleitk or unlabelled
geometry-index-backed data and validates frame coverage. Equal record/depth counts
allow per-frame metadata; summed NumberOfFrames allows per-SOP multiframe metadata.
Fast/unknown legacy payload rules remain unchanged. No disk reads, pixel copies,
ordering/geometry changes or global cache resets are added.

Advanced stored/live metadata no longer grows through catalog refresh/sync. A complete
replacement must publish pixels plus metadata as one payload. Hot/main and index
admission reject mismatched pairs; valid previews remain readable but preview_only
still excludes them from full cache. The full-candidate method is the contract used
by Unify's same-series-visible no-op correction. This checks decoded consistency,
not server download completeness or arbitrary unknown-backend metadata correctness.

Verification: initial five failures / three passes, then eight passes; final eleven
cases add matched-preview readability/full rejection, full-cache fallback after bad
entries, and expanded multiframe acceptance. Expanded cache/Fast/partial/US/MPR/parity
suite: 391 passed / four existing xfailed / one quarantined xpassed, exit 0. The three
additional cases pass in final 11-case rerun. All 467 mirrors match; edited PacsClient
sources have no payload mirrors. No other owners' payloads synchronized.

Ping/list_actions succeed on the running pre-edit source. No restart, download retry
or hot reload performed. Live gate remains open: fresh source, real drop, rapid
patient/Download Manager switches while full loading finishes, confirm 104 pixels and
104 metadata records, correct first/last frame, cache reuse, replacement cancellation,
and Fast progressive growth. Shared-delivery fix must land with this guard for full
incident closure. Roll back only these four method hunks, helper and guard; preserve
concurrent lifecycle changes. MPR admission guard remains unchanged.

### Shared delivery return receipt (2026-09-17)

Unify's paired fix now preserves and publishes full results when a tab hides during
loading, releases owned load events, and defers only presentation until the original
token-bound request can resume. Twenty-five synthetic handoff guards pass; the
combined shared/cache/adjacent run is 214 passed / six existing quarantined xfailed,
exit 0. Cross-owner review additionally caught and guarded the old-full-same-series
replacement shortcut. No decoded-cache methods or geometry were edited by Unify.
Fresh source/native GUI remains pending; running PID 739276 predates both fixes.
See [shared evidence and remaining acceptance](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-completed-load-tab-handoff-opt-35--opt-60).

### Packaging and shared-interface follow-up (2026-09-17)

`advanced_payload_integrity.py` is an internal core PacsClient helper, not a new
installable feature/module or flag. The existing viewer catalog/component applies.
PyInstaller `builder/spec/appA_workstation.spec` collects PacsClient submodules and
its runtime filter admits this name; Nuitka `AIPacs_nuitka.spec.py` includes PacsClient.
Static controller imports make it reachable. No separate installer component, plugin
payload or config family is introduced. This verifies source packaging paths, not
a frozen release build; Unify's separate staged-config baseline failure remains open.

Current combined inactive-result handoff, cache-integrity and MPR-admission guards:
45 passed, exit 0. Hidden publication and full-candidate interfaces are compatible.
A residual same-series full-view force-reload review concern was sent to Unify:
completion's duplicate-switch predicate checks series/preview status rather than
payload version, potentially leaving an older full volume visible. This is not the
reproduced 8/104 preview incident and requires its own guarded check. No shared
handoff methods changed during this read-only interface review.

## Read-only source receipt: 2026-09-17 00:43:30-00:51:06, PID 1215216

Reviewed deduplicated app/viewer logs including rotation, scoped to the named source
PID and window. No decoding/rendering changes, restart, package sync or patient data
exports. Shared Local catalog latency and Home thumbnail stalls remain Unify-owned.

### Completeness evidence and limits

Eleven post-bind records and six cache-read records all have metadata count equal to
VTK depth. Six preview binds are 8/8; full binds are 128, 96, 224 (twice), and 27.
Full cache reads include 128/128, 224/224, 96/96 and 27/27; a main-cache 8/8 read is a
consistent preview, not proof of full completion. No recurrence of the former 104/8
pair appears in these records. A 19-slice filter completes at 00:47:01.004 and the
shared handoff logs loaded=True/active=False/stage=deferred at 00:47:01.021. There is
no activation_replay receipt or matching 19-slice full bind in the window: cancellation,
replacement or later activation must be correlated by the shared owner. Do not claim
full hidden-tab recovery or native GUI acceptance from this partial evidence.

### Advanced-owned timings

Cold constructor 549.851 ms, first render 510.580 ms; sampled stack includes initial
Matplotlib backend import. Subsequent constructor totals are about 77-91 ms and first
renders 40-49 ms. The 421.0/414.4 ms UI gaps near 00:47:14/19 sample preview apply ->
constructor -> Render; the whole gaps are not exclusive Render durations.

All seven completed filter records report one requested ITK thread. Stage sums:
128 slices 2.856 s; 19 slices 3.195 s; 96 slices 11.794 s; 224 slices 22.619 s;
27 slices 2.852 s; repeat 224 slices 22.869 s. The 224-slice passes respectively
spend 6.479/6.244 s multiscale, 5.925/5.707 s Laplacian, and 6.812/7.797 s adaptive;
yields remain milliseconds. These are elapsed stage measurements, not CPU attribution
or proof of an optimal thread budget. Next seam: matched synthetic/workload comparison
of existing thread limits and worker contention, pixel/geometry invariance, GUI scroll
latency and memory; preserve filter parameters. Do not remove sharpening to meet KPI.

MPR opens from the 224-slice input: constructor KPI 1523.7 ms; setup_ui wall span
641 ms; axial/sagittal/coronal initialize spans 81/79/74 ms; reslice prewarm 206 ms.
The 651.5 ms gap samples coronal QVTK interactor construction. Confirmed VTK GUI-path
work; no evidence justifies removing geometry transforms or moving GL construction
to a worker. Next seam: separate header preparation, per-view construction and first
render timings with cancellation-safe deferred work and visible loading state.

At 00:48:33 the placeholder path samples graphics profile detection -> runtime binary
search -> Path.resolve/realpath during a 400.8 ms UI gap. This confirms filesystem
resolution is reached on GUI; it does not prove every millisecond is path resolution.
Next seam: reuse an immutable graphics-capability snapshot prepared outside the GUI,
with an explicit invalidation rule for runtime/backend changes. Shared graphics
runtime ownership must agree before altering aipacs_runtime.py.

No actual ERROR/CRITICAL in inspected scoped app/viewer records. Warning-heavy
geometry diagnostics remain, including 1407 active-audit and 1320 hydration records;
counts alone do not prove incorrect geometry or logging-caused lag. Next measurement
can quantify repeated diagnostic cost without removing clinically useful checks.


## OPT-48 MPR deferred 3D teardown reentrancy (2026-09-17)

Status: reproduced, fixed and code-verified; fresh-source GUI acceptance pending.
A synthetic behavioral probe demonstrated that `_build_deferred_3d_view` continued
into `_create_3d_view` after the progress dialog's `QApplication.processEvents()`
dispatched teardown. Cleanup clears `_deferred_3d_pending`, but the callback already
consumed that flag before pumping events. The saved layout and finalized VTK resources
could consequently be accessed after closure. This is a proven control-flow defect,
not attribution of any particular historical native crash.

The callback now checks `_mpr_closed` after event processing, before layout access or
VTK construction. The check is inside the existing finally scope so the progress
dialog is closed/deleted on early return as well as success and build failure.
No image geometry, camera, reslice, filtering, pixel quality or worker ownership changes.

Guard: `tests/code/mpr/test_mpr_deferred_build_reentrancy.py`. Before: 2 failed / 2 passed,
exit 1 (construction incorrectly called after teardown). After: four cases pass;
combined lifecycle, interaction, geometry, canonicalization, toolbar and admission
suite: 121 passed, exit 0. The suite uses synthetic objects without patient data or DB.
Official mirror sync dry-run reports zero drift; this MPR source has no payload mirror.
Control client ping and list_actions both return ok, but the running process predates
this edit. No restart, clinical interaction or live acceptance was performed.
Fresh source gate: open MPR, request 3D, close the MPR/patient during progress presentation;
verify no late construction/native error, no retained modal, then reopen and verify all
panes, orientation and scrolling. Normal 3D success and failure cleanup are code-tested.
Rollback: revert only this callback's post-event teardown check and its enclosing guard
reorganization. Keep all unrelated worktree changes. Cold Advanced MathText render latency
and MPR geometry/header-I/O performance remain separate open investigations.


## Mixed MR spectroscopy presentation series: Advanced admission diagnosis (2026-09-17)

Status: reproduced admission failure; diagnosis only, no runtime correction or GUI acceptance.
User supplied a viewport screenshot of a spectroscopy presentation series failing in Advanced,
with Fast reported working. Patient identity and source paths remain local and are omitted here.
Read-only catalog lookup followed by exact SeriesInstanceUID equality against local headers
verified 45 files. The initial indexed existing-path subset contained 36; directory inspection
with header identity verification found all 45, so the smaller catalog subset must not be mistaken
for proof that nine frames are missing on disk.

Structural inventory: 30 MR Image Storage MONOCHROME2 frames at 124x160 with IOP/IPP;
six Secondary Capture Image Storage MONOCHROME2 frames at 512x512 without IOP/IPP;
nine Secondary Capture Image Storage RGB frames at 124x160 without IOP/IPP. This is a
heterogeneous presentation series, not one uniformly sampled scalar spatial volume.
No MR Spectroscopy Storage object was found in this inventory. Representative local pydicom
decode succeeded for each of the three groups, with shapes (124,160), (512,512), and
(124,160,3), respectively. This checks development decoding of three representatives,
not every frame, packaged codecs, or visual/clinical accuracy.

Direct invocation of build_series_geometry_index on the verified files reproduces ValueError
for missing IPP/IOP. The authoritative rejecting seam is advanced_geometry_contract.py's
missing-geometry check. image_io.py's fallback is exclusively nonspatial_us_plan; it cannot
admit MR/Secondary Capture. Even fabricating geometry would leave incompatible dimensions
and scalar/RGB component counts, so bypassing this check is not a safe repair.

Fast's qt_viewer_bridge.py already documents this heterogeneous spectroscopy case and
reapplies per-instance DICOM window/level unless the user selected a custom window. Its
per-frame display contract is materially different from Advanced's whole-series volume.
The screenshot also shows a loading label for a different series; the current evidence does
not establish the cause of that stale label, which must be traced separately through request
ownership. Do not claim a logged request correlation or downloader failure from the screenshot.

Proposed implementation boundary: Advanced-owned nonspatial heterogeneous frame display
with per-frame dimensions, scalar/RGB handling and DICOM VOI, preserving authoritative
instance identities/order. Keep this sequence out of spatial-volume cache admission and MPR;
never fabricate IOP/IPP or resample reports into a false anatomical volume. Synthetic guards
must cover mixed SC/MR, RGB preservation, per-frame VOI, rapid series switches, unavailable
frames and truthful loader cleanup before any runtime correction. Geometry contract remains
unchanged. No app restart, live DB mutation, patient fixture or clinical data export performed.


## OPT-35 mixed MR/SC presentation implementation (2026-09-17)

Status: implemented and code-verified; source live/clinical acceptance pending.
Follow-up to the preceding mixed spectroscopy-presentation diagnosis. The worker now
recognizes MR Secondary Capture sequences before DB best-group selection/size grouping.
`advanced_presentation.py` prepares native-size independent SimpleITK/VTK frames;
scalar MR invokes the existing filter entry point per frame, while already-rendered SC
reports/RGB retain their original source pixels. Per-frame VOI is prepared on the worker.
There is no synthetic spatial stack, dominant-size truncation, anatomical resampling,
new patient affine, or Fast renderer dependency. This is image presentation support,
not raw MR Spectroscopy Storage/spectral-data processing.

All 45 verified local files prepared successfully, including nine RGB frames and 45
nonempty DICOM overlay graphics layers. Graphics stay separate from source pixels;
worker-decoded RGBA overlays honor origin/clipping, transparency and existing overlay
color/enable preferences. No patient identifiers, pixels or source paths enter this receipt.
The earlier 270 ms local preparation probe preceded overlay support and is NOT the
final-path latency benchmark. Live image appearance remains unverified.

Changed runtime seams:
- `PacsClient/pacs/patient_tab/utils/advanced_presentation.py`: bounded worker preparation,
  single-study/series/SOP identity, single-frame MR/SC MONOCHROME2 or byte RGB only,
  immutable frame-reference tuples across metadata snapshots; 512 MiB conservative
  preparation estimate. Unsupported layouts/LUT transforms fail atomically.
- `image_io.py`: Advanced-only routing, no mixed-volume preview; count-only
  `[ADVANCED_PRESENTATION]` receipt. Ordinary spatial series retain the existing path.
- `modules/viewer/advanced/presentation_frames.py` and `viewer_2d.py`: native frame switching,
  per-frame/default and user scalar W/L across RGB, separate overlay prop, logical
  counter, native-plane coordinate defaults, same-shape camera preservation, and reset
  between presentation/spatial series. Disk/decode stay outside render/scroll callbacks.
- `advanced_payload_integrity.py`: validate paired independent-frame/metadata coverage.
- `_vc_cache.py`: these sequences never enter the full spatial-volume cache.
- `vtk_widget/_vw_series.py`: a replacement tuple cannot be skipped merely because its
  first frame has unchanged dimensions; in-place Z growth is refused by the viewer.

Regression: `test_advanced_presentation_sequence.py` (10 synthetic cases). Original
loader-route guard failed before implementation (empty result); the same-series tuple
refresh guard also fails against the prior predicate restored only in an isolated Python
process, without modifying worktree files. Native offscreen viewer tests switch frames,
check RGB output bytes/independent scalar W/L, retain custom scalar W/L across RGB, and
switch out of/back into the presentation route. Additional checks cover metadata deepcopy,
MPR/full-volume-cache rejection, exact order, overlay origin/alpha, identity mismatch,
worker budget and preview deferral. Test database is redirected and pools cleared;
no test database is opened. Expanded suite 153 passes, exit 0; 468 mirror pairs match.
The viewer helper was added with official sync tooling; no unrelated payloads synchronized.

Source GUI gate: documented test-control client was unavailable. No app restart/login or
GUI acceptance was performed. Human next run: source launch/login, real drag/drop of the
mixed series, scroll all 45 frames, confirm spectra/colored maps/graphics and frame VOI,
switch away/back, verify no stale spinner, then ordinary MR/US and MPR smoke. Clinical
confirmation of report graphics/color remains required. Physical spatial MPR is blocked
for the mixed sequence; no correctness claim for anatomical reconstruction from it.

Separate shared-owner handoff: `_VCProgressiveMixin._resolve_series_identity` returns the
previous rendered series label for a different requested series. `_finish_on_ui` also
maps a generic decode failure to download waiting. Reproduced with synthetic metadata;
recorded under VTK-to-Unify mixed-series loading identity in the UI-stall owner report.
Those shared coordination methods were NOT patched by this VTK implementation.
Rollback: remove the Advanced presentation routing/hooks/helper and its new cache/refresh
branches together; preserve prior US/geometry/cache fixes and resync only viewer files.


## OPT-35 large DX viewport admission diagnosis (2026-09-18)

Status: reproduced geometry-admission failure; diagnosis only, no runtime edit.
User supplied an empty Advanced viewport screenshot with large radiography thumbnails.
Read-only catalog/header inspection found eight locally indexed DX single-frame images
(Digital X-Ray Image Storage for Presentation, MONOCHROME2, 16-bit). All eight lack
ImageOrientationPatient and ImagePositionPatient. Sizes include 4300x4298, 6676x4431
and 6869x4528 rows/columns. Two further catalog series had no existing indexed paths;
that limited observation is not proof their files are absent from disk. No patient
identifiers, source paths or image content are copied here.

Largest selected frame: SimpleITK successfully reads size (4528,6869,1), one component,
unsigned 16-bit, Explicit VR Little Endian. Direct invocation of the current Advanced
_get_or_build_series_geometry_index rejects that same file with ValueError for missing
IPP/IOP. The existing nonspatial fallback admits only US; the presentation-frame route
admits MR/SC, so neither covers DX. This establishes a blocker before VTK rendering;
it does NOT certify GPU texture capability or exclude additional downstream size limits.

PixelSpacing is absent while ImagerPixelSpacing is present in the selected frame. A future
DX presentation route must distinguish detector-plane spacing from calibrated patient
measurements, preserve native resolution/windowing/polarity and truthful 2D orientation,
and prohibit invented 3D geometry/MPR. Do not merely relax the anatomical geometry contract.
DICOM DX module reference: https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.26.3.html

Logs around the observed opening window contain lifecycle/download-complete breadcrumbs;
no matched allocation/texture error or explicit geometry exception was found in the
searched app/viewer log window. The geometry result above comes from a separate local
read-only reproduction, not a claimed exception trace from that GUI attempt. The screenshot
alone does not establish whether the native drop reached rendering. No live GUI action,
restart, source/payload change or clinical DB mutation was performed.


## OPT-35 large DX presentation correction (2026-09-18)

Status: implemented and code-verified; fresh-source GUI and packaged-runtime acceptance remain open.

The earlier DX diagnosis is corrected at Advanced's worker admission boundary. Exact Digital
X-Ray Image Storage for Presentation (SOP class 1.2.840.10008.5.1.4.1.1.1.1, modality DX)
now uses independent native 2D presentation frames. Missing IPP/IOP no longer sends these
objects through CT/MR spatial-stack validation. No patient affine, anatomical orientation,
spatial MPR volume, dominant-size grouping or downsampling is fabricated. The existing
Advanced decoded-frame cache/identity contracts and preparation budget remain in force.

Changes: `PacsClient/pacs/patient_tab/utils/advanced_presentation.py` classifies and validates
DX separately from MR/SC, preserves modality, source dimensions/scalars and window settings,
and calls the existing modality filter dispatcher. PixelSpacing describes the image plane;
ImagerPixelSpacing is explicitly detector spacing, never promoted to patient PixelSpacing.
The VTK ruler (`modules/viewer/interactor_styles/ruler_interactorstyle.py`) labels detector
lengths `mm (detector)` and uncalibrated lengths `px`, scoped to presentation metadata.
The renderer consumes prepared frames without filesystem access or decode on scroll.

Scope is MONOCHROME2 with identity presentation LUT and supported linear window transform.
MONOCHROME1, nonidentity presentation LUT, VOI/modality LUT sequences and processing-only
DX SOP classes are not newly implemented by this change. Existing CT/MR/US admission stays
separate. This is not a global projection-measurement calibration redesign.

Evidence:
- Synthetic DX admission guard failed before the fix (loader returned None), then passed.
- Detector and uncalibrated ruler guards both failed before their label correction.
- A synthetic 4528 x 6869 uint16 DX goes through `load_single_series_by_number` and the real
  `ImageViewer2D`: exact source pixels retained, native mapper dimensions retained, rendered
  central gradient verified away from text/borders, no observed render-window ErrorEvent.
- Eight locally available affected DX frames prepared successfully, maximum 31,102,832
  pixels. No identifiers, source paths, image payloads or screenshots retained in this report.
- Direct focused pytest: 132 passed, exit 0; includes all 15 presentation tests plus US,
  complete-stack/cache/preview/count/timing/orientation, ruler and MPR geometry guards.
- Builder mirror freshness guard: 1 passed, exit 0. Dry-run identified only our ruler mirror;
  synchronized with the standard tool; all 468 source/payload pairs match.
- Existing test server ping and 83-action discovery succeeded. Running source predates the
  edits, so no hot reload or restart was attempted and this is NOT live GUI acceptance.

Next gate: human fresh source launch/sign-in with test control enabled; real thumbnail drop
of the affected large DX into Advanced, verify visible pixels, pan/zoom, window adjustment,
series replacement and detector ruler label. Capture session-scoped errors and identity/counts
locally. Then verify the packaged candidate independently under the normal release workflow.
No full release build, version change or deployment was performed.

Rollback: remove only this DX classification/validation/spacing extension and presentation-
scoped ruler labels, then sync that mirror. Preserve earlier MR/SC, US and all unrelated edits.


### Incoming Total Spine acceptance handoff (2026-09-19)

Owner boundary: Advanced rendering/input, not shared Unify or Total Spine geometry.
During an authorized DX test, Test Control ping and action discovery succeeded.
Native thumbnail double-click selected the coronal series but the Advanced viewport
remained empty. Native mouse drag displayed an unfinished drag preview; Escape
cancelled it. This is not proof of a decoder root cause or a completed OLE drop.
Eagle Eye then exposed only disabled generic function entries; no Total Spine dialog
could be opened. Catalog code offers Total Spine for DX/CR, while the chooser binds
to loaded viewer modality. Preserve the distinction between missing entry context
and a proven detector failure. No viewer/pipeline code, processes or mirrors were
changed by this Total Spine task. Next owner check: current-session rendered output
and selected study/modality identity at the native input boundary. Clinical source
identifiers and previews remain only in local private artifacts.


Total Spine follow-up (2026-09-19): its owner has added a direct study-bound header
button and an embedded review tab, removing that editor's dependency on Advanced
render readiness. This does not fix or certify the earlier Advanced input/render
finding. No Advanced or shared pipeline code was changed. Native acceptance of the
new editor entry awaits a human fresh source launch; source offscreen guards pass.


## OPT-35 DOC/SC document-page admission (2026-09-20)

Status: fixed and code-verified; not live-verified. This addresses Advanced's document
page admission, not the historical OPT-07 shared multi-study offset-key issue.

Evidence: bounded read-only local inventory of 30 available series-number-100000 files
identified Secondary Capture Image Storage (1.2.840.10008.5.1.4.1.1.7), modality DOC,
single-frame RGB, without IPP/IOP. The latest bounded app-log sample contained seven
series-number resolution breadcrumbs, but no matching geometry exception. The decisive
failure is the synthetic worker guard: DOC/SC bypassed the presentation classifier and
entered spatial grouping. This reproduced at both series numbers 100000 and 7; the number
itself is not the classification rule. No patient identifiers, payloads or paths are retained.

Minimal correction: `PacsClient/pacs/patient_tab/utils/advanced_presentation.py` accepts
exact SC + DOC, retains DOC metadata, allows only SC in that document sequence and uses
the existing immutable independent-frame renderer/cache contract. Documents bypass image
filters, retain native pixels/components and have no invented patient affine or MPR volume.
Absent PixelSpacing means unit pixel coordinates and the existing uncalibrated ruler label;
explicit PixelSpacing remains image-plane spacing. Encapsulated PDF is not admitted merely
because its modality says DOC. MR/SC and DX validation, memory bounds and UID consistency
remain enforced. No shared identity, thumbnail, download, hover or Fast Viewer edits.

Verification:
- Two fail-before behavioral worker cases at series numbers 100000 and 7; both pass now.
- Presentation suite: 19 passed, exit 0. Includes native DOC page scroll, RGB/window retention,
  return to spatial series, type-not-number routing and a negative encapsulated-PDF boundary.
- Thirty local DOC/SC samples now prepare with native dimensions and RGB components.
- Focused/adjacent suite plus builder parity: 137 passed, exit 0 (Advanced admission/cache,
  US/DX/MR/SC, preview/count/timing/orientation, ruler, MPR geometry and mirror freshness).
- Standard mirror dry-run: zero drift; modified worker is in PacsClient, not a plugin mirror.
- Existing test server ping and 83-action discovery succeed. No app restart or hot reload;
  real thumbnail-drop validation against the changed source remains pending.

Live gate: fresh human source launch/sign-in; drag the documented page series into Advanced,
verify all pages, color, readable text, scroll order and series replacement, with local session
logs and viewport identity/count checks. Native/offscreen success is not this acceptance gate.
Rollback only this DOC classifier/spacing branch; retain previous MR/SC/DX corrections.


## OPT-35 DOC whole-series memory admission follow-up (2026-09-20)

The user's repeat failure invalidated full-series acceptance of the prior admission slice.
Latest source logs show `Presentation sequence exceeds preparation memory limit` after
successful secondary-study resolution. The SC/DOC classifier fix was active; the remaining
blocker was the preparation estimate, not an old process or a series-number limit. Prior
local checks prepared individual pages and therefore missed this whole-series condition.

Seven byte-RGB pages at 1598 x 2200 need about 70.4 MiB of retained pixel buffers, but the
old eight-bytes-per-component estimate charged about 563.3 MiB and exceeded the unchanged
512 MiB limit. `advanced_presentation.py` now accounts for validated, unfiltered DOC RGB
as actual byte buffers plus four largest-page scratch buffers, with additional retained RGBA
and scratch allowance for overlays. Other frame types retain the previous conservative
estimate. No quality reduction, cap increase, GUI decode or shared pipeline change.

Fail-before: `test_document_budget_accounts_for_rgb_bytes_and_decode_workspace` rejects
seven synthetic pages under the old estimate. After correction it loads all seven; one byte
below the calculated budget still fails before decoding. Presentation suite now 20 cases;
focused/adjacent plus builder parity suite 138 passed, direct exit 0. Standard mirror dry-run
zero drift. Full affected local series now passes the real worker entry point (7/7), followed
by actual ImageViewer2D offscreen switching across all seven native-size pages, with no
observed render-window ErrorEvent. No clinical payload, image or identifier exported.

Status: code-verified and local whole-series/offscreen verified; NOT live GUI accepted.
Test-control ping and 83-action discovery succeed, but the running app predates this memory
correction. Fresh human source launch/sign-in and real thumbnail drop remain required.
Rollback only the DOC byte-RGB budget branch to the earlier conservative estimate.

Shared follow-up: logs subsequently label exhausted retries as LoadSucceeded with visible=0,
and classify the preparation failure as awaiting download. These are not proof of a rendered
page. Existing Unify failure-state ownership applies; no shared retry/hover logic edited here.


## Incoming Unify evidence: DOC presentation visibility telemetry (2026-09-20)

Owner boundary: Advanced render observability, not shared identity/download coordination.
A fresh source run contains two native DOC/SC drops. The seven-page case completed worker
admission, bound seven instances with the presentation order contract, and recorded real
slice changes through pages zero to four. A one-page case also completed and bound one
instance. There was no load exception, identity rejection or access violation.

Both successful binds nevertheless emitted
`load_completed_no_first_image_repaint_dropped`, while the generic switch KPI retained
`first_image_visible_ms=-1` and no first-render timestamp. Binding and scroll prove the
presentation payload is active, but logs alone cannot certify visible pixels. The likely
gap is that the generic first-image detector does not observe the Advanced independent-frame
presentation render terminal. Add a backend-owned behavioral guard and terminal marker before
changing render behavior; preserve spatial-volume, presentation-frame and shared lifecycle
separation. Unify did not patch Advanced telemetry or renderer code in this handoff.

## Eagle Eye Segment integration handoff (2026-09-20)

Investigation for a proposed local seed+ROI intensity tool found two existing
integration boundaries to review before reuse:
`modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py::toggle_tool` selects
`lst_nodes_viewer[0]` instead of the currently selected viewport;
`modules/viewer/interactor_styles/segmentation_styles/polygon_interactorstyle.py::on_contour_closed`
uses the segmentation-server request path when no local callback consumes the
contour. Reusing that path would not provide the requested local intensity preview.
The new tool should own its interaction, original-scalar snapshot and identity-bound
mask within its viewer domain, with computation off the GUI thread. No viewer,
server, download or cache behavior was changed in this investigation.
See `docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md` Segment investigation for
primary API references, synthetic feasibility evidence and proposed UX.


## OPT-35 large CT drag, preview direction and header reuse (2026-09-20)

User reported slow stack drag on a 392-frame CT, initial eight-frame direction changing
at full load, and requested opportunistic caching. Status: domain corrections code-verified;
normal-app interaction speed and preview/full handoff still require live acceptance.

Confirmed mechanisms and minimal corrections:
1. `load_series_preview` selected filesystem-order files before applying full-series geometry.
   It now obtains the same cached SeriesGeometryIndex as full loading, then uses
   `advanced_geometry_contract.preview_geometry_prefix`. The prefix retains the full anatomical
   policy/direction and rebuilds only subset hashes, paths, SOP lists and index mappings.
   No affine, sorting policy, resampling or geometry-repair heuristic was changed. Metadata
   describes only decoded preview frames. Unsupported geometry defers to the full loader.
2. `_apply_geometry_index_metadata` retains valid source-header WW/WC provenance as a small
   per-instance tuple. Advanced's header resolver returns it directly; it no longer reopens
   these DICOMs on every scroll. Unprepared/missing-window cases retain existing fallbacks.
   Filters, window values and contrast precedence are unchanged; this is metadata reuse,
   not a cross-domain decoded cache.
3. `AbstractInteractorStyle.change_quickly_slices` capped a large-stack event at six slices,
   discarded excess mouse distance, and ignored destinations beyond either endpoint. For
   Advanced (`vtk_simpleitk`) stacks over 100 frames only, the full distance-derived target
   is passed to the existing coalescing queue and clamped to the available range. A 120-pixel
   gesture on a 392-frame stack now requests 24 slices, versus six previously. This is a
   gesture-distance correction, not a fourfold rendering-FPS claim. Small stacks, other
   backends and separate module contexts keep the existing policy.

Verification:
- Three preview order/first-frame fail-before cases, one GUI-header-reopen fail-before case,
  three large-drag fail-before cases; negative other-backend drag case remains unchanged.
- Native ImageViewer2D preview-to-full guard verifies identical displayed SOP direction.
- Local read-only checks on both reported 392-frame CT stacks: eight preview SOPs match the
  full index prefix; all eight pixel planes match source pixels with their rescale and Y flip;
  eight source-window tuples present. Full geometry lookup hits the index prepared by preview.
- Cold worker previews measured 1100 and 1052 ms in that bounded local probe. Reading full
  geometry before preview has a first-load cost; do not claim faster cold preview or faster
  than Fast Viewer from these measurements. The full loader reuses the validated index.
- Broad focused/adjacent/mirror suite: 208 passed, four existing quarantined display-geometry
  xfails, exit 0. Additional native preview transition guard: one passed, exit 0. Twelve tests
  now in `test_advanced_preview_metadata.py`. The quarantined tests are not acceptance passes.
- Only our viewer_2d and abstract_interactorstyle mirrors drifted; standard sync performed;
  all 468 mirror pairs match. No shared coordinator or Fast Viewer source changes.

Cache review: adjacent lookahead already exists (two candidates), with memory/count limits;
open-tab and heavy warmup defer during interaction/interactive loading. Do not introduce a
second prefetch coordinator or increase concurrency without a measured admission/eviction
trace. Requested runtime eligibility/idle-resume check is handed to the existing Unify report;
Advanced geometry/header reuse improvements above remain within this domain.

Live gate: test-control ping unavailable during this turn; no flag was enabled and no process
restarted, respecting the normal-launch preference. Next fresh source run: verify real fast
stack drag and reversal/endpoints on a 392-frame CT, first-eight/full SOP continuity, unchanged
window/filter appearance, warm re-drop and adjacent-series idle readiness. FPS equivalence,
cache-hit rate and end-to-end latency are not yet live-verified.
Rollback only prefix-selection/stamping, prepared-header shortcut and Advanced large-drag
branch as a coherent slice; preserve prior DOC/DX/US changes and other workstream edits.


Final verification for the large-CT slice: added legacy cached-metadata WW/WC memoization
inside the viewer, so a successful fallback header resolution is reused on return to the
same frame. One additional fail-before case observed three reads instead of one. Missing
or unsuccessful resolutions are not memoized. Existing first fallback for old payloads
remains; new worker-prepared values avoid it entirely. Final suite: **210 passed, 4 existing
quarantined xfailed, exit 0**; preview/window/drag file has 13 cases. Mirror sync rechecked
only viewer_2d drift and synchronized it. This final receipt supersedes intermediate counts
above; live acceptance remains pending.


## OPT-35 single native render per spatial slice update (2026-09-20)

User reported remaining large-stack slowness after the drag/header/preview corrections.
Bounded latest viewer-log sample contained five slow-frame records: conditional median
50.4 ms total, 21.8 ms SetSlice, 0.2 ms window resolution, 0.1 ms corners, 11.8 ms final
Render. Only updates over the existing 30 ms threshold are logged: these are NOT general
frame-time percentiles or measured FPS. The sample confirms rendering dominates these
slow records; it does not attribute all stalls or background contention.

Native guard reproduced two window StartEvents per changed slice. VTK SetSlice already
updates its extent/clipping and renders; the former Python tail rendered again after
annotations/window work. Upstream implementation reference (verified against the local
native behavioral test): https://raw.githubusercontent.com/Kitware/VTK/v9.5.0/Interaction/Image/vtkImageViewer2.cxx

Correction in `modules/viewer/advanced/viewer_2d.py`: extract existing visual preparation
into `_prepare_slice_visuals`; for the Advanced vtk_simpleitk domain only, execute it once
at render-window StartEvent, after native slice/extent updates and before drawing. Remove
the observer before preparation and in finally; propagate captured preparation errors to
the existing set_slice error boundary. Same-slice refresh still prepares/renders explicitly.
Other backend/module contexts retain the previous path. DOC independent-frame rendering,
filters, resolution, geometry and interaction scheduling are unchanged. Substage timing
now places native drawing in Render instead of partly in SetSlice; compare total timings,
not old/new SetSlice numbers alone.

Verification:
- Native preview/full transition guard failed before at two renders instead of one.
- Updated guard checks one render, exact captured-pixel equality against the legacy branch,
  unchanged zoom/displayed SOP order, fast-interaction draw, and callback cleanup/recovery
  after an injected preparation failure. Two existing lightweight test doubles now bind the
  extracted preparation method; their US/order/overlay assertions are unchanged.
- Final focused and adjacent suite: 253 passed / 4 existing quarantined display-geometry
  xfailed, direct exit 0. Quarantines remain open, not counted as passes.
- Synthetic 392 x 512 x 512 int16 CT, 800 x 600 offscreen window; four alternating rounds
  of 30 updates after five warmups: legacy renders 60/round, corrected renders 30/round.
  Legacy median 15.55 / 14.02 ms; corrected 11.11 / 13.73 ms. P95 varied substantially:
  legacy 27.54 / 18.84 ms, corrected 18.83 / 53.69 ms. No tail-latency or twofold FPS claim.
  Synthetic startup emitted input-port warnings before timing (incomplete early harnesses
  also missed required display metadata); do not treat this as a clean clinical startup
  test. Completed steady-state rounds are indicative only.
- Only viewer_2d mirror drifted; standard sync and builder guard passed; 468 pairs match.
- Test bridge unavailable. No live app restart, authentication, hot reload or test flag
  change. Fresh normal source run and actual rapid large-CT drag/settle, measurements,
  annotations, zoom retention and new session timings remain the live gate.

Status: fixed/code-verified for redundant spatial renders; overall user-perceived speed is
not yet live-verified. Roll back only this single-draw branch/helper extraction together
and resync its mirror; preserve earlier stack/order/window/cache fixes.
