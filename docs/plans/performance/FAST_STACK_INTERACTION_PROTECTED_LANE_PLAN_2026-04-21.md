# FAST Stack Interaction Protected Lane Plan

## Summary

Optimize stack drag / rapid stack review while preserving wheel scrolling as exact, one-slice-at-a-time precision browsing. Stack drag becomes a protected interaction lane where only the current target frame and a tiny directional neighborhood compete for UI, decode, cache, and future object-fetch resources.

Primary success target: stack drag remains responsive during active download/open/cache work, with lower UI backlog, fewer stale decode/render tasks, and less CPU churn.

## Key Changes

- Add FAST stack scheduling primitives:
  - `FastWorkItem(priority, generation, kind, series_uid, slice_index, direction, quality_class, deadline_ms)`.
  - Priorities: P0 current target, P1 directional neighbors, P2 settle warm, P3 noncritical UI, P4 bulk.
  - During active stack drag, admit only P0/P1. Freeze P2-P4 until settle/idle.
  - Wheel remains outside this stack scheduler.

- Refine stack drag bridge/pipeline flow:
  - Preserve `QtSliceViewer` drag input policy, bounded overflow, reversal handling, and target clamping.
  - `QtViewerBridge` starts a protected stack session on drag start, assigns a new generation to meaningful target changes, and passes stack direction into the FAST pipeline.
  - Stale generation results must not present over newer stack targets.
  - Drag stop keeps the existing 200 ms settle window, then exact/full-quality rendering and P2 warmup may resume.

- Improve cache admission:
  - Frame cache hit remains fastest path.
  - Stack drag may use existing surrogate/preview behavior during movement; wheel must not.
  - P1 prefetch is directional: max 2 ahead and 1 behind relative to drag direction.
  - Disk pixel cache writes are bounded through a single writer queue and may be deferred during protected stack drag.
  - `Lightweight2DPipeline` remains the owner of pixel/frame cache policy.

- Add object/blob cache boundary:
  - Phase 1 works with current local files/download manager.
  - Provide `has_object(series_uid, slice_index)` and `request_object(priority, series_uid, slice_index)` hooks for future slice-level retrieval.
  - Later download-manager/server work can map jump-to-target stack behavior to P0/P1 object requests.

- Reduce hot-path overhead:
  - Keep stack diagnostics summarized around drag stop/settle.
  - Avoid per-target INFO logging during active stack drag.
  - Defer thumbnails, reference-line refreshes, broad warmup, frame prefetch, and bulk cache fill while stack drag is active.

## Interfaces And Defaults

- Active stack drag:
  - P0: current target, preview quality, 16 ms deadline.
  - P1: two slices ahead and one behind in current direction, preview quality, 120 ms deadline.
  - Direction reversal: bump generation and invalidate pending opposite-direction work.

- Settle/idle:
  - Existing 200 ms settle delay remains.
  - Final settled frame is rendered exact/full quality.
  - Broader prefetch resumes only after protected drag is cleared and system admission allows it.

- Admission:
  - During stack drag: no P2+ work, no broad frame prefetch, no noncritical disk writes.
  - If UI lag or active P0 work is present, keep decode/cache-write tokens at protected minimum.
  - For incomplete series during active download, prefer cache/surrogate over synchronous exact stack decode when a usable cached neighbor exists.

## Test Plan

- Unit tests:
  - Stack drag scheduler emits P0/P1 and bumps generation on target changes/reversals.
  - Protected stack drag admits tiny directional P1 prefetch, not broad warmup.
  - Wheel still renders exact and does not use stack surrogate policy.
  - Disk cache uses a bounded single writer queue instead of one thread per put.
  - Object/blob cache boundary exists without forcing network changes.

- Integration/KPI scenarios:
  - Fast stack drag over 100+ slices with cold cache.
  - Fast stack drag while progressive download is active.
  - Rapid direction reversal every 0.5-1 s.
  - Jump-like stack movement across an incomplete series.
  - Drag stop settles to exact frame and resumes broader warmup.

## Assumptions

- Wheel scrolling is out of scope except for regression protection.
- Stack drag may show preview/surrogate during movement, but the settled image must refine to exact/full quality.
- Existing Block A/B/C ownership remains intact.
- Full slice-level object retrieval is phase 2+ because it may require download manager/API/server support.
