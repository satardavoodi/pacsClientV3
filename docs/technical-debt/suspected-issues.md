# AI-PACS — Suspected Issues / Technical-Debt Registry

Machine-readable source of truth: [`suspected-issues.json`](./suspected-issues.json).
This file is the human-readable companion + the operating principle.

## Clinical-safety principle (read first)

The **final visual/clinical result currently observed by the physician is considered CORRECT**
unless there is clear evidence of a real bug. The purpose of tests and automated checks is to find
**software-engineering defects and real user-visible bugs — not to redefine clinically accepted
behavior.**

**Do NOT change without evidence:** image geometry · slice ordering · orientation / flip / rotation ·
final displayed anatomical direction · clinically validated rendering output · medically verified
viewport behavior.

**If the final medical/visual result is already correct, do not change it just because a test
suggests a different theoretical behavior.** Do not "fix" slice order / geometry / orientation /
rendering output only to satisfy a test.

## When to FIX immediately (clear software-engineering defects)

duplicate processing / repeated paths · unnecessary loops · memory/resource leaks · file locks ·
UI-thread blocking · bad async cancellation · duplicate downloads/imports · **stale viewport data** ·
**missing slices on import** · **wrong series after drag-and-drop** · **server sync not checking for
new series** · crashes/freezes · broken file-format handling · broken Education attachment loading ·
a clear double-operation that preserves the result by accident but creates risk.

## When to DEFER + document (this registry)

The code looks strange but the final clinical result is correct · changing it may alter
geometry/orientation/slice-order · the only evidence is a theoretical test mismatch · the physician
has not observed a display problem · the change could affect diagnostic safety.

For deferred items: **document the suspicion, add logs/tests to monitor, and record it here** — do not
change behavior yet.

## Issue schema

`issueId · area · file · function · observation · whyMayBeWrong · reasonForDeferral · risk ·
relatedStudy · relatedTests/logs · severity · recommendedInvestigation · status`
status ∈ { observed · deferred · confirmed · fixed · rejected }

## Current registry (2026-06-14)

| id | area | severity | status | one-line |
|----|------|----------|--------|----------|
| SUSPECT-001 | Geometry/SliceOrdering | medium | **deferred** | `apply_k_flip_for_stack_order` may double-apply the 1-based→0-based offset (`display_k_to_raw_k(1)`→-1); docstring vs tests contradict; **live CT rendered correctly** → do not touch without author intent + real-series check |
| SUSPECT-002 | Geometry/EffectiveAffine | low | deferred | 3 tests assert pre-R30 (0-based) contract; the **code is the verified R30 behavior** → test-only update, deferred (needs careful R30-derived recompute) |
| SUSPECT-003 | Rendering/BackendResolution | medium | deferred | stage1/2 expect `pydicom_qt`/`vtk_simpleitk`; code returns `pydicom_2d`/`pydicom` → confirm backend moved intentionally before touching (rendering-adjacent) |
| SUSPECT-004 | Rendering/PixelGolden | medium | deferred | `overlap_pixel_quality` golden-hash fails under offscreen ("dim/zero QImage") → **do NOT re-baseline blind**; run on real platform first |
| SUSPECT-005 | Performance/ProgressiveGrow | medium | **fixed** | VERIFIED the `max_new_entries` cap IS applied (`_max_grow`→`scan_series_header_entries`); the 2 contract tests checked an old literal → updated (test-only) |
| SUSPECT-006 | TestHarness/Behavioral | medium | deferred | ~25 viewer tests look like fake/harness drift; some may be real (dragdrop_progressive, live_sync) → verify per-cluster before editing |
| SUSPECT-007 | Performance/OpenLatency | medium | observed | server 156-slice CT cold open `first_series_visible`=77.9s (download-bound; render 23.9ms) → progressive first-series prefetch |
| SUSPECT-008 | Qt-lifetime/Stability | medium | **fixed** | `_register_buttons_with_safeguard` now filters deleted Qt widgets (shiboken6.isValid) so a dead button can't abort the batch |
| FIX-001 | UI/Theme (non-clinical) | low | **fixed** | theme re-apply deferred out of the `themeChanged` emit (main.py) |
| FIX-002 | Resource/Memory (non-clinical) | medium | **fixed** | `_vw_series.py` used `gc` un-imported → GC restore silently failed → added `import gc` |
| FIX-003 | Storage/InMemoryConsistency | medium | **fixed** | Clear Cache/Patient now clears the in-memory `ThumbnailStore` (was: deleted on disk but served stale from RAM until restart) |
| FIX-004 | Storage/UIStatusRefresh | medium | **fixed** | `storageChanged` was emitted but **unconnected** → study stayed green/downloaded after a clear; now wired to a focused `refresh_download_statuses_local_only` (recomputes status from disk, **no server call / no button animation**; falls back to `refresh_download_statuses`) |
| FIX-005 | Storage/ConsistencyValidator | medium | **fixed** | added `validate_storage_consistency` + files-safe `repair_storage_consistency` (removes stale DB studies for missing files, NULLs dangling thumbnails; never deletes files) + "Check Consistency" button |
| FIX-006 | Storage/PartialFailureWarnings | low | **fixed** | a DB-cleanup failure after files were deleted now sets `success=False` + surfaces a warning (was: silent partial success) |

## How this engagement applied the principle

- **Did NOT change** any geometry / slice-order / orientation / rendering code to satisfy a test.
- The geometry **test** updates only made tests assert the **existing verified R30 code** (round-trip
  tests compare to the captured initial matrix — a pure math invariant, no hardcoded geometry).
- `base_divisor` is **drag sensitivity** (px-per-slice during a stack drag), not anatomy — updated to
  the documented source values.
- The two **code** fixes (theme deferral, `gc` import) are **non-clinical-output** SE/resource defects.
- DisplayKPolicy (clinically sensitive) was **documented here, not changed**.
