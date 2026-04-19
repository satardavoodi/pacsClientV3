# ClearCanvas Workstation Comparison

**Date:** 2026-04-15  
**Scope:** AI-PACS FAST viewer/workstation vs local ClearCanvas source checkout  
**Reference checkout verified locally:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

---

## External reference handling

- **Reference system status:** ClearCanvas was treated strictly as an external reference system.
- **Exact path used:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`
- **Workspace-local reference folder created:** No. A separate in-workspace mirror such as `external/clearcanvas/` was **not** created because a complete local checkout already existed outside the AI-PACS workspace.
- **Analysis mode:** Static source inspection only.
- **Tooling required:** None. No additional parser, indexer, SDK, or runtime dependency was installed for this comparison.
- **Isolation rule followed:** ClearCanvas source was used for read-only architecture tracing, file/path mapping, loader/render/cache/orchestration inspection, and comparison only. It was **not** mixed into AI-PACS production code, imports, dependencies, or runtime paths.
- **Limitations encountered:** Analysis was limited to static code inspection and local source availability; no ClearCanvas build/run/debug session was performed inside the AI-PACS environment.

---

## What was actually inspected

This comparison is based on local source inspection, not a generic product summary.

### AI-PACS files reviewed

- `docs/plans/plan.md`
- `docs/performance/PERFORMANCE_STATUS.md`
- `docs/plans/performance/FAST_VIEWER_PERFORMANCE_ROADMAP.md`
- `docs/performance/CONCURRENCY_ANALYSIS_v2.3.3.md`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/pipeline/orchestrator.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_db_service.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py`
- `modules/viewer/tools/controller.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

### ClearCanvas files reviewed

- `ImageViewer/ImageViewer.sln`
- `ImageViewer/ClearCanvas.ImageViewer.csproj`
- `Desktop/Desktop.sln`
- `Desktop/ClearCanvas.Desktop.csproj`
- `ImageViewer/ImageViewerComponent.cs`
- `ImageViewer/PhysicalWorkspace.cs`
- `ImageViewer/LogicalWorkspace.cs`
- `ImageViewer/ImageBox.cs`
- `ImageViewer/DisplaySet.cs`
- `ImageViewer/PresentationImage.cs`
- `ImageViewer/StudyManagement/StudyLoader.cs`
- `ImageViewer/LocalSopLoader.cs`
- `ImageViewer/StudyManagement/Frame.cs`
- `ImageViewer/StudyManagement/StreamingSopDataSource.cs`
- `ImageViewer/StudyManagement/WeightedWindowPrefetchingStrategy.cs`
- `ImageViewer/StudyManagement/CorePrefetchingStrategy.cs`
- `ImageViewer/StudyManagement/ViewerFrameEnumerator.cs`
- `ImageViewer/StudyLoaders/Local/LocalStoreStudyLoader.cs`
- `ImageViewer/StudyLoaders/Streaming/StreamingStudyLoader.cs`
- `ImageViewer/StudyLoaders/Streaming/StreamingCorePrefetchingStrategy.cs`
- `ImageViewer/Tools/Synchronization/SynchronizationToolCoordinator.cs`
- `ImageViewer/Tools/Synchronization/StackingSynchronizationTool.cs`
- `ImageViewer/Tools/Synchronization/ReferenceLineTool.cs`
- `ImageViewer/Thumbnails/ThumbnailComponent.cs`
- `ImageViewer/Thumbnails/ThumbnailLoader.cs`
- `ImageViewer/Thumbnails/ThumbnailRepository.cs`
- `ImageViewer/Volumes/VolumeCache.cs`
- `ImageViewer/Volume/Mpr/MprViewerComponent.cs`
- `ImageViewer/Volume/Mpr/MprDisplaySet.cs`
- `ImageViewer/Volume/Mpr/VolumeSlicer.cs`
- `ImageViewer/Volume/Mpr/LaunchMprTool.cs`
- `Desktop/DesktopWindow.cs`
- `Desktop/Workspace.cs`
- `Desktop/SessionManager.cs`

---

## Executive read

The short version:

- **AI-PACS FAST is architecturally serious, not fake-fast.** The pipeline work in `Lightweight2DPipeline`, disk pixel cache, subprocess decode isolation, and download-aware throttling are all real engineering responses to a hard Python + live-download problem.
- **AI-PACS is also more control-plane-heavy than ClearCanvas.** The remaining pain is not mainly raw rendering anymore; it is orchestration, lifecycle, and mixed-load callback pressure.
- **ClearCanvas is cleaner in ownership and viewer composition.** Its shell/workspace/viewer hierarchy is crisp, and its synchronization/MPR patterns are easier to reason about.
- **ClearCanvas does not face the exact same problem class.** It lazily loads studies and prefetches around current viewing context, but it is not juggling the same progressive-download/live-growth/control-pressure problem that AI-PACS is solving.
- **Conclusion:** AI-PACS is not fundamentally on the wrong track, but it is carrying too many overlapping coordination layers around progressive display and FAST-mode auxiliary caching.

---

## ClearCanvas architecture map

### Workstation shell

The shell is clearly owned by `Desktop/`:

- `DesktopWindow.cs` owns windows, shelves, workspaces, dialogs, desktop tools, menu/toolbar model rebuilding, and global title updates.
- `Workspace.cs` owns hosted application component lifecycle, command history, close preparation, and dialog ownership.
- `SessionManager.cs` provides a formal session boundary with explicit status changes and application-marshaled notifications.

This is a notably clean split: **desktop/window/workspace ownership is not mixed into viewer internals**.

### Viewer core

The viewer core is clearly owned by `ImageViewer/`:

- `ImageViewerComponent.cs` is the root viewer application component.
- `LogicalWorkspace.cs` owns logical image content (`ImageSet` level).
- `PhysicalWorkspace.cs` owns on-screen arrangement (`ImageBox` grid/layout level).
- `ImageBox.cs` owns tiles, selection, display-set assignment, and image flow.
- `DisplaySet.cs` owns ordered `PresentationImage` collections.
- `PresentationImage.cs` owns scene graph, renderer, graphic selection/focus, and draw entry points.

This produces a very readable model:

$$
DesktopWindow \rightarrow Workspace \rightarrow ImageViewerComponent \rightarrow \{LogicalWorkspace, PhysicalWorkspace\} \rightarrow ImageBox \rightarrow DisplaySet \rightarrow PresentationImage
$$

That model is easier to reason about than AI-PACS's current FAST runtime, where authority is spread across the controller mixins, bridge, pipeline, throttle helpers, orchestrator, and optional booster/warmup paths.

---

## Side-by-side subsystem comparison

### 1) Viewer model and ownership

| Area | ClearCanvas | AI-PACS FAST | Comparison |
|---|---|---|---|
| Root viewer owner | `ImageViewerComponent` as hosted `ApplicationComponent` | `PatientWidget` + `ViewerController` + FAST bridge/pipeline | ClearCanvas is cleaner in ownership boundaries |
| Layout model | Explicit `LogicalWorkspace` vs `PhysicalWorkspace` split | Functional split exists, but FAST responsibilities are scattered across controller/bridge/pipeline | ClearCanvas is structurally simpler |
| On-screen hierarchy | `ImageBox -> Tile -> PresentationImage` | Viewer widget + bridge + Qt painter/tool overlay model | AI-PACS is leaner for FAST rendering, but less semantically crisp |
| Disposal authority | Rooted at workspace/window close; dispose cascades downward | Mostly explicit and defensive, but spread over widget/controller/service cleanup methods | AI-PACS is more defensive; ClearCanvas is more elegant |

**Judgment:** ClearCanvas wins on model clarity. AI-PACS wins on pragmatic defensive cleanup for a messier runtime environment.

### 2) Study loading, decode, and lazy access

| Area | ClearCanvas | AI-PACS FAST | Comparison |
|---|---|---|---|
| Study load abstraction | `StudyLoader` returns SOP/data sources, not eagerly decoded pixels | Local DB/download/live file system plus backend-specific loading paths | ClearCanvas is more uniform |
| Local load | `LocalStoreStudyLoader` enumerates local SOPs lazily | DB + filesystem + progressive growth during download | AI-PACS solves a harder live mutation problem |
| Streaming load | `StreamingStudyLoader` gets XML/header metadata, frame pixels later via `StreamingSopDataSource` | FAST mode loads local downloading files and can show partially available series | Different operating model |
| Pixel retrieval | `Frame.GetNormalizedPixelData()` from frame data source on demand | `_decode_slice()` with disk cache / optional decode service / in-memory cache | AI-PACS has a more aggressively optimized Python path |
| Metadata access | `Frame` caches normalized DICOM attributes lazily per frame | FAST metadata is partly DB-derived, partly header-filled, partly progressive stub-enriched | ClearCanvas metadata model is cleaner |

**ClearCanvas trick worth copying conceptually:** it very intentionally separates **study enumeration/header state** from **pixel retrieval**, while AI-PACS still has a lot of cross-talk between progressive metadata repair, live viewer state, and download lifecycle.

### 3) Prefetch and cache behavior

| Area | ClearCanvas | AI-PACS FAST | Comparison |
|---|---|---|---|
| Prefetch owner | `WeightedWindowPrefetchingStrategy` + `ViewerFrameEnumerator` | `Lightweight2DPipeline` + `ui_throttle` + `SystemLoadController` + optional booster/history | AI-PACS is more adaptive but more complex |
| Prioritization | Selected image box weight vs unselected weight | Interaction-aware radius, direction, heavy-download caps, protected UI policies | AI-PACS is more advanced |
| Retrieval/decompress split | Yes: retrieval pool and optional decompression pool | Yes in effect: decode service/background prefetch + render cache layers | Similar intent |
| Pixel cache | Implicit via frame data + prefetch + memory manager patterns | `pixel_cache`, `frame_cache`, disk pixel cache, formerly overlapping booster/Zeta paths | AI-PACS is over-layered |
| Persistent disk cache | Not evident in inspected viewer frame path; thumbnail cache is even disabled in checked tree | Explicit disk pixel cache with strong ROI for reopen speed | AI-PACS clearly better here |

**Judgment:** AI-PACS is ahead on modern cache engineering, but behind on cache simplicity. ClearCanvas shows a calmer “just enough moving parts” design.

### 4) Synchronization, linked scrolling, and reference lines

| Area | ClearCanvas | AI-PACS FAST | Comparison |
|---|---|---|---|
| Sync ownership | Dedicated synchronization tools + `SynchronizationToolCoordinator` mediator | FAST sync behavior spans bridge/controller/viewer logic with throttling and guards | ClearCanvas is cleaner |
| Redraw ordering | Explicit mediator avoids duplicate or unnecessary redraws | AI-PACS has many protections, but the ordering is more diffuse | ClearCanvas is easier to maintain |
| Reference lines | Tool computes geometric intersections only for relevant visible images and uses dirty redraw list | AI-PACS preserves geometry carefully, but progressive growth complicates metadata correctness | AI-PACS handles harder live-growth conditions |

**Important nuance:** AI-PACS’s geometry/reference-line burden is harder because newly downloaded slices appear while the viewer is already live. ClearCanvas mostly assumes a stable loaded study graph.

### 5) MPR architecture

| Area | ClearCanvas | AI-PACS FAST/overall workstation | Comparison |
|---|---|---|---|
| MPR launch | `LaunchMprTool` creates a separate MPR viewer component/workspace | AI-PACS has Advanced/MPR flows and curved-MPR UI, largely separate from FAST | Similar separation instinct |
| Volume caching | `VolumeCache` with reference counting, async load, lock/unlock, unloadability | AI-PACS has several caches, but FAST focus is 2D; MPR/Advanced responsibilities are more separated and less unified | ClearCanvas MPR cache ownership is cleaner |
| Clone avoidance | `MprViewerComponent` explicitly avoids display-set cloning for performance | AI-PACS often needs defensive duplication and live state sync | ClearCanvas has a simpler MPR lifecycle |

**Best ClearCanvas pattern here:** `Volumes/VolumeCache.cs` is a strong example of **single-authority ownership + reference-managed lifetime**. AI-PACS should keep that lesson in mind whenever a new FAST helper wants to “own” another cache.

### 6) Workstation hygiene and lifecycle

| Area | ClearCanvas | AI-PACS | Comparison |
|---|---|---|---|
| Window/workspace close | First-class shell behavior in `DesktopWindow` and `Workspace` | Recently improved via `HomeDownloadService.disconnect_widget()`, tab-close teardown, orchestrator deregistration | AI-PACS is catching up |
| Signal/tool ownership | Mostly bounded by workspace/component/tool host model | Explicit `_ConnectionRecord` and cleanup helpers needed because lifetime is more entangled | ClearCanvas is cleaner by design |
| Session boundary | Formal `SessionManager` | More application-specific login/main-window flow | ClearCanvas has better shell abstraction |

**Judgment:** ClearCanvas is better engineered at the shell boundary. AI-PACS’s recent hygiene fixes are correct and important, but they are partly compensating for earlier coupling.

### 7) Thumbnails

| Area | ClearCanvas | AI-PACS | Comparison |
|---|---|---|---|
| Thumbnail owner | Dedicated shelf `ThumbnailComponent` keyed to active viewer/workspace | Thumbnail panel mixed with patient/viewer/download behavior | ClearCanvas separation is cleaner |
| Async loading | Simple queued `ThumbnailLoader` | AI-PACS thumbnail flow is more download-aware and more complex | AI-PACS solves a harder case |
| Thumbnail caching | Surprisingly weak in inspected tree: caching repo commented out, `NullThumbnailRepository` active | AI-PACS does much more here in practice | AI-PACS is better on this specific axis |

This is a nice reminder not to mythologize the reference system: ClearCanvas is cleaner overall, but it is not automatically better everywhere.

---

## What AI-PACS gets right

### 1) FAST/Advanced separation is the correct strategic choice

Your current insistence on keeping FAST and Advanced distinct is validated. ClearCanvas also separates concerns strongly: shell vs viewer, viewer vs tools, normal viewer vs MPR workspaces. Trying to re-merge FAST with Advanced would move in the wrong direction.

### 2) The FAST data path is strong

`modules/viewer/fast/lightweight_2d_pipeline.py` is doing real work that ClearCanvas did not need to do in the same way:

- persistent disk pixel cache
- interaction-aware prefetch policy
- subprocess decode isolation
- cache-first drag behavior
- explicit mixed-load throttling

For Python/Qt, that is sound engineering.

### 3) Recent workstation hygiene work is exactly the kind of fix the architecture needed

`home_download_service.py`, `_hp_patient_open.py`, and viewer cleanup/orchestrator deregistration are moving toward the kind of bounded ownership ClearCanvas already has natively.

### 4) AI-PACS is solving a harder mixed-load problem than ClearCanvas

ClearCanvas mostly assumes a study is opened, then lazily decoded/prefetched around view context.

AI-PACS is trying to support:

- ongoing DICOM download
- progressive display growth
- thumbnails updating during download
- drag-drop/view-priority download changes
- FAST viewer interaction under all of the above

That means some extra orchestration is justified.

---

## What is over-engineered in AI-PACS

### 1) Progressive display lifecycle remains too elaborate

Even after B4 cleanup work, the FAST progressive path still has too many moving parts:

- multiple lifecycle/compatibility guards
- multi-layer completion recovery
- grow/reverify/sweep/state reconciliation
- live metadata patching for reference-line safety

Some of this is necessary because downloads mutate the visible series in real time. But the **number of authority points** is still too high compared with ClearCanvas’s calmer ownership model.

### 2) FAST-mode auxiliary caching has historically overlapped too much

The main FAST path already has enough with:

- frame cache
- pixel cache
- disk pixel cache
- decode service

Anything outside that core path must justify itself very clearly. ClearCanvas’s `VolumeCache` works because it is singular and authoritative. AI-PACS gets into trouble when helpers become quasi-caches with partial overlap.

### 3) Control policy is spread across too many layers

Current FAST policy lives across:

- `Lightweight2DPipeline`
- `QtViewerBridge`
- `ui_throttle`
- `SystemLoadController`
- `PipelineOrchestrator`
- progressive controller mixins

Each of these is individually understandable, but the total picture is harder to reason about than ClearCanvas’s more local authority model.

### 4) Sync/redraw ordering is less explicit than it should be

ClearCanvas’s `SynchronizationToolCoordinator` is a nice example of one small mediator whose job is obvious: coordinate sync tools and avoid redundant redraw. AI-PACS has equivalent behavior, but the ordering logic is more distributed.

---

## What ClearCanvas does more cleanly

### 1) Ownership boundaries

The most important ClearCanvas advantage is not “faster code”; it is **cleaner authority**:

- shell owns shell concerns
- workspace owns hosted component lifecycle
- viewer owns viewer graph
- sync tools own sync logic
- MPR owns MPR workspace/cache

AI-PACS should keep moving in that direction.

### 2) Stable viewer graph

ClearCanvas’s `ImageViewerComponent -> PhysicalWorkspace/LogicalWorkspace -> ImageBox -> DisplaySet -> PresentationImage` is a very strong conceptual model. It helps prevent lifecycle and redraw ambiguity.

### 3) Lazy metadata/pixel access with less ceremony

`StudyLoader`, `SopDataSource`, `Frame`, and prefetch strategies make it clear that pixels arrive on demand. AI-PACS does this too in practice, but with more repair logic because live download/progressive mutation keeps changing the world under the viewer.

### 4) Sync and reference-line redraw discipline

The explicit mediator pattern in `SynchronizationToolCoordinator.cs` is a subtle engineering win. It is the kind of small structure that prevents years of redraw weirdness.

### 5) MPR cache lifetime discipline

`Volumes/VolumeCache.cs` is one of the strongest files inspected. Reference-managed ownership, async load, unloadability, and a clear warning not to hold raw volume instances long-term—chef’s kiss, architecturally speaking.

---

## What explains the remaining AI-PACS lag during download + viewing

The remaining lag is best explained by **control-plane overlap**, not by the base FAST draw path.

### Evidence-backed explanation

Your current FAST path can already render cache-hot slices very quickly. The persistent spikes are more consistent with:

- progressive growth callbacks
- metadata synchronization for new instances
- thumbnail/progress UI churn
- download-state notifications
- completion/recovery safety nets
- auxiliary cache/prefetch systems competing for attention

ClearCanvas mostly avoids this class of problem because it is not trying to keep a live viewer perfectly coherent while the underlying series is still being downloaded and growing.

So the correct conclusion is:

> AI-PACS is not mainly slow because the FAST renderer is bad. It is still paying for the cost of keeping the whole workstation coherent while data, UI, and priorities are changing underneath it.

That is why the next wins are simplification and authority reduction, not heroic micro-optimization.

---

## Recommended simplification priorities

### Highest priority

1. **Finish collapsing progressive lifecycle authority**
   - One explicit state owner.
   - Fewer compatibility sets.
   - Fewer completion pathways that can re-enter each other.

2. **Keep FAST booster-style overlap retired unless it proves unique value**
   - The main FAST pipeline should remain the single authoritative 2D cache/decode path.

3. **Make redraw/sync ordering more explicit**
   - Consider a dedicated coordinator object for FAST sync/reference-line redraw ordering, inspired by ClearCanvas’s synchronization mediator.

### Medium priority

4. **Continue moving workstation lifecycle cleanup into services with bounded ownership**
   - The recent `HomeDownloadService` cleanup work is the right pattern.

5. **Reduce policy scattering**
   - Keep `SystemLoadController` as the front door for policy.
   - Avoid reintroducing new ad hoc checks in bridge/controller/progressive code.

### Lower priority

6. **Do not copy ClearCanvas thumbnail design blindly**
   - On this specific point, the inspected ClearCanvas tree is weaker than AI-PACS.

7. **Do not overlearn the “cleaner because simpler” lesson where the problem domain differs**
   - ClearCanvas’s cleaner structure is excellent, but it is not a live-progressive-download workstation in the same sense.

---

## Final judgment

### Is AI-PACS architecturally sound compared to ClearCanvas?

**Yes, with caveats.**

The FAST rendering/data path is credible and modern for a Python application. The current design is not fundamentally misguided.

### Is AI-PACS over-engineered?

**Partly yes—mostly in orchestration and progressive lifecycle, not in the core FAST pipeline.**

### What ClearCanvas validates

- strong separation of shell vs viewer
- strong separation of logical vs physical display model
- single-owner cache/lifetime patterns
- explicit sync coordination
- dedicated MPR workspace/cache ownership

### What AI-PACS should not feel bad about

- using load-aware throttling
- using disk pixel cache
- using subprocess decode isolation
- having extra download/view overlap logic

Those are appropriate responses to a harder runtime problem.

### Bottom line

If I had to summarize the architectural gap in one line:

> **AI-PACS has a solid FAST engine wrapped in too much mixed-load choreography; ClearCanvas has a calmer and cleaner workstation graph, but it is solving a less turbulent runtime problem.**

That means the best next move is **simplification around authority and lifecycle**, not a rewrite of the FAST rendering core.
