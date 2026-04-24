# Block A / Block B / KPI / ClearCanvas Handoff

**Date:** 2026-04-20  
**Scope:** FAST mode only (`pydicom_qt`) unless explicitly stated otherwise.  
**Purpose:** Give the next agent one current, practical roadmap for the recent block-architecture work, the latest KPI interpretation, and the ClearCanvas comparison/simulation status.

---

## What this handoff covers

This document consolidates four threads that were previously spread across several files and runtime-log discussions:

1. **What was already completed** for Block A / Block B.
2. **How to optimize the blocks next** without regressing first-visible UX.
3. **What the KPI evidence currently says** about the real remaining bottleneck.
4. **What was actually done for the ClearCanvas simulation/comparison**, including what is still blocked.

If a future agent reads only one document first, it should be this one.

---

## Executive truth

The current FAST viewer path is **not decode-bound first anymore**.

The important current reality is:

- **Block A** has already been meaningfully cleaned up structurally.
- **Block B** has been hardened with several low-risk improvements that protect first-image behavior.
- **The visible drag path is already fast** in the recent runtime logs.
- **The remaining pain is mostly control-plane / background CPU pressure**, especially under overlap or cold-open conditions.
- **The ClearCanvas work so far is mostly a structured external reference + benchmark harness + AI-PACS simulation baseline**, not a completed side-by-side runtime benchmark.

So the next agent should **not** start with another raw decode optimization pass unless fresh evidence changes the story.

---

## Current block contract

### Block A — thumbnail projection first

**Goal:** make the user trust the study/series list immediately.

Block A owns:
- thumbnail widget creation,
- series identity projection,
- ready/downloading/completed state projection,
- cheap progressive sidebar visibility.

Block A must not own:
- direct DB query policy inside UI classes,
- unrelated viewer-switch behavior,
- cache/prefetch logic for the first diagnostic image.

### Block B — first image visible second

**Goal:** get the first usable image into the target viewer fast and stably.

Block B owns:
- series switch request application,
- backend binding,
- first-frame display,
- essential slider/layout stabilization,
- spinner timing for the target viewer.

Block B must not own:
- heavy warmup,
- broad follow-up UI churn,
- thumbnail-side work,
- non-essential post-switch orchestration.

### Block C — interaction and optimization third

**Goal:** improve smoothness after a stable image already exists.

Block C owns:
- scroll behavior,
- prefetch,
- surrogate/exact render policy,
- cache warm,
- progressive grow follow-up,
- post-completion optimization.

Block C must not be allowed to delay:
- first visible thumbnails,
- first image visible,
- layout stabilization after manual switch/drop.

---

## What was already completed

## 1) Block A structure cleanup already landed

The recent Block A work was real architecture cleanup, not just cosmetic renaming.

### Delivered pieces

- `PacsClient/utils/series_metadata_service.py`
  - canonical normalized series-summary source
- `PacsClient/pacs/patient_tab/utils/thumbnail_projection_service.py`
  - isolates thumbnail payload shaping
- `PacsClient/pacs/patient_tab/utils/thumbnail_metadata_service.py`
  - backward-compatible alias path
- `PacsClient/pacs/patient_tab/utils/thumbnail_image_source_service.py`
  - separates image-source resolution from panel layout logic
- `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
  - reduced mixed ownership
- `ThumbnailBatchRunner`
  - batch cadence extracted from duplicated ad hoc timer logic
- panel-side indexing improvements
  - avoids repeated duplicate scans during thumbnail insertion

### Practical meaning

Block A is now **closer to a projection pipeline**:

$$
SeriesMetadataService \rightarrow ThumbnailImageSourceService \rightarrow ThumbnailProjectionService \rightarrow ThumbnailPanel \rightarrow ThumbnailManager
$$

That is healthier than the older “thumbnail panel as UI + DB + disk + timer + payload shaper” setup.

### What is still not finished in Block A

Block A is better, but not fully pure yet.

The remaining direction is:
- continue removing direct fallback policy from `thumbnail_panel.py`,
- continue reducing sidebar-local state authority,
- keep `HomeDownloadService` as the canonical progress/terminal source.

---

## 2) Block B hardening already landed

Recent Block B work was intentionally **bounded** and aimed at first-visible-image stability.

### Already landed before the latest log pass

#### a) `_vc_switch.py` follow-up deferral

`_perform_series_switch_optimized()` now keeps these inline:
- actual viewer switch,
- spinner hide,
- Qt refit / first-visible presentation stabilization.

And defers these to the next Qt tick via `_schedule_post_switch_followups(...)`:
- corner refresh,
- reference-line recompute,
- protected-series refresh.

**Meaning:** Block B does less side work before the user sees the image.

#### b) FAST shutdown cleanup fixed

`modules/viewer/fast/lightweight_2d_pipeline.py::shutdown()` was corrected to stop the real FAST executors, and the matching builder payload copy was updated too.

**Meaning:** no stale shutdown path drift between workspace and packaged viewer runtime.

### Latest Block B fix from runtime logs (`log 79` / `log 80`)

#### c) Fresh Qt startup refit for wrong-zoom-on-last-series bug

File:
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py`

Added:
- `_queue_qt_startup_refit(self, bridge)`

Behavior:
- after fresh `_start_qt_viewer(...)`, one guarded `QTimer.singleShot(0, ...)` refit is queued,
- it only runs if the Qt bridge is still active and still the same viewer.

### Why this mattered

The immediate startup `zoom_to_fit()` could run before the final layout geometry had fully settled.
That produced the user-visible bug where **the last series dropped into the layout had the wrong zoom / under-fit presentation**.

### What the runtime evidence showed after the fix

`log 80` showed two `QT_PRESENTATION` entries:
- immediate startup fit,
- then the deferred follow-up fit.

That matched the intended repair path and explained why the last inserted series no longer depended on a later click or UI event to look correct.

---

## 3) Latest Block C / interaction-side refinement already landed

### Small-stack fast-prefetch tightening

File:
- `modules/viewer/fast/stack_cache_profile.py`

Current policy for stacks `n <= 24`:
- `fast_prefetch_radius = 4`
- idle and medium prefetch still allow aggressive/full-series warm behavior where appropriate.

### Why this was changed

In the latest runtime analysis, the visible drag path was already very fast, but small stacks could still spend unnecessary background CPU on a wider fast-interaction prefetch band immediately after cold open.

This was a **CPU trim**, not a visible rendering fix.

### Live-path verification already done

The runtime path in:
- `modules/viewer/fast/lightweight_2d_pipeline.py`

was checked and confirmed to use the updated profile in `_compute_adaptive_radius(...)` and `_prefetch_around(...)`.

### Regression coverage already exists

- `tests/viewer/test_stack_cache_profile.py`
- `tests/viewer/test_b34_interaction_aware_policy.py`

The relevant expectation now verifies the tighter radius of `4` for small fast-interaction stacks.

---

## KPI truth as of now

## 1) Headless benchmark truth (existing baseline)

The current documented benchmark truth is still the `run_001` and `run_002` AI-PACS captures.

Artifacts:
- `generated-files/benchmarks/run_001/*`
- `generated-files/benchmarks/run_002/*`

### High-level interpretation

These runs showed:
- visible frame presentation improved a lot,
- but **stale background work remained very high**,
- and **overlap CPU stayed too high**.

### Important KPI takeaway

Even when these got better:
- `set_slice_present_p95_ms`
- `decode_p95_ms`
- `frame_render_p95_ms`

these still stayed bad or suspicious under overlap:
- `stale_task_ratio ≈ 0.99`
- `cpu_p95_pct` under overlap remained too high
- `first_image_visible_ms` under overlap remained much worse than common local viewing

So the benchmark evidence already says:

> the next wins are more about admission control, fan-out reduction, and background work discipline than about making `_decode_slice()` slightly faster.

## 2) Runtime-log truth from the latest manual investigation

### `log 80` summary

The latest runtime-log review showed a healthier visible path than the older headless overlap story suggested.

Observed signals from the recent manual log investigation:
- `FAST:first_image_visible ... total_ms ≈ 21.8`
- `[UX_VIEWER_INTERACTIVE] ... ≈ 120.9ms`
- sampled `[B3.8_SCROLL]` frames around `0.4–0.8ms`
- `decode_ms = 0.0` on those scroll samples
- CPU still spiked around `87.2%`

### Interpretation

That combination matters a lot:

- visible drag frames were already cheap,
- decode was not the limiting factor in those samples,
- but CPU still spiked.

That means the remaining cost is more likely from:
- background prefetch/warm work,
- progressive/control-plane work,
- UI-side follow-up churn,
- or some combination of those.

### Current KPI priority order

For the next agent, KPI priority should be:

1. **Protect `first_image_visible_ms`**
2. **Keep cache-hot `set_slice_present_p95_ms` low**
3. **Reduce overlap/background CPU**
4. **Reduce stale work and duplicated follow-up work**
5. **Only then consider deeper decode micro-optimizations**

---

## How to optimize the blocks next

## Block A — next safe optimization moves

1. **Keep `ThumbnailPanel` projection-only**
   - continue removing data-source and fallback policy from the widget layer
2. **Keep one canonical sidebar progress/terminal feed**
   - avoid duplicate direct consumers deciding their own completion semantics
3. **Keep UI-thread thumbnail work minimal**
   - any disk/DB fallback should stay behind service helpers
4. **Keep batch insertion deterministic**
   - preserve cheap O(1)-style duplicate checks and isolated batch cadence

### Block A anti-pattern to avoid

Do not let the sidebar become a second orchestration center.
If logic decides download/viewer lifecycle instead of just projecting it, it belongs outside Block A.

## Block B — next safe optimization moves

1. **Preserve first-frame authority** in `_vc_switch.py`
   - first frame + essential layout stabilization stay inline
2. **Continue moving non-essential work out of the switch hot path**
   - especially follow-ups that do not change the first visible image
3. **Split `_vc_switch.py` further by responsibility**
   - request validation
   - first-frame apply path
   - post-display follow-ups
4. **Preserve the fresh Qt startup refit**
   - it is now the guard against the last-series wrong-zoom regression

### Block B anti-pattern to avoid

Do not pull Block C work back into the first-image path just because it seems “cheap enough”.
That phrase has caused enough drama already.

## Block C — next safe optimization moves

1. **Use fresh runtime logs after the small-stack radius trim**
   - verify whether overlap CPU drops while hot drag remains decode-free
2. **If CPU is still high, target control-plane admissions before decode**
   - prefetch cadence
   - cache-warm entry points
   - progress fan-out
   - non-interactive follow-up churn
3. **Keep the small-stack fast radius at 4 until new evidence says otherwise**
4. **Preserve fast drag responsiveness and exact-on-settle behavior**

### Block C anti-pattern to avoid

Do not widen fast small-stack prefetch again without measured evidence.
That would be a fine way to pay more CPU for less user-visible benefit. A classic bad trade, like buying a race car to improve parking.

---

## ClearCanvas simulation / comparison status

## What was actually done

The ClearCanvas work so far included **three distinct things**:

### 1) Static architecture comparison

A local external ClearCanvas checkout was inspected as a read-only reference.

Reference path used:
- `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

This produced architecture and KPI comparison docs already in the repo, including:
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
- related plan docs under `docs/plans/clear-canvas/`

### 2) Benchmark harness / simulation framework

A side-by-side benchmark workflow was prepared, including:
- scenario definitions,
- execution-pack generation,
- AI-PACS headless capture,
- manual ClearCanvas normalization flow.

This is the **simulation framework** for comparison.

### 3) AI-PACS-only simulated comparison baselines

Because ClearCanvas was not runnable in the current workspace environment, the practical comparison work captured **AI-PACS baseline/common/overlap runs first**.

That produced:
- `run_001`
- `run_002`

These are best understood as:
- **AI-PACS simulated/common baseline truth**, and
- **AI-PACS overlap truth**,
- ready for a future true ClearCanvas runtime side-by-side once build blockers are removed.

## What is still blocked

A real ClearCanvas runtime benchmark is still blocked by environment/setup issues already documented:
- missing .NET Framework 4.0 targeting pack,
- missing `ReferencedAssemblies` checkout,
- legacy build/runtime requirements.

So the honest status is:

> ClearCanvas comparison is **prepared and partially simulated**, but not yet fully executed as a real same-machine runnable benchmark.

## What the next agent should do with ClearCanvas

Treat the current ClearCanvas work as:
- **valid architecture guidance**,
- **valid KPI interpretation guidance**,
- **valid benchmark harness preparation**,
- but **not yet final side-by-side runtime truth**.

### Next ClearCanvas action only if environment work is allowed

1. make ClearCanvas buildable,
2. build the viewer shell,
3. run the prepared common-local benchmark flow,
4. compare real `clearcanvas_common.json` against AI-PACS common local baseline.

If environment work is *not* the priority, do not get stuck there yet; continue AI-PACS KPI improvement first.

---

## Current best explanation of the remaining bottleneck

The strongest current explanation is:

- Block A has improved structurally,
- Block B first-image behavior is substantially healthier,
- Block C visible drag path is fast when cache-hot,
- but the workstation still spends too much CPU on non-visible work around interaction.

So the likely remaining classes are:

1. **event fan-out too early / too often**
2. **background prefetch or cache-warm admitted too eagerly**
3. **control-plane work still distributed across too many owners**
4. **overlap churn causing CPU spikes even when visible decode is 0ms**

That is the current roadmap center.

---

## Recommended next run order

### 1. Re-read these in order

1. this file
2. `docs/plans/implementation/block-structure-roadmap-2026-04-19.md`
3. `docs/plans/analysis/block-priority-review-clearcanvas-2026-04-19.md`
4. `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
5. `docs/plans/plan.md` — especially current KPI/benchmark sections

### 2. First validation task

Collect a fresh runtime log for the same small-stack/drag scenario after the `fast_prefetch_radius = 4` change.

### 3. First comparison questions

From that log, answer these before changing code again:
- Did CPU peak drop vs the prior `log 80` small-stack behavior?
- Did `[B3.8_SCROLL]` remain decode-free and low-latency during drag?
- Did the last-inserted-series zoom remain correct?
- Did any new control-plane churn become more visible after the prefetch trim?

### 4. Only if CPU remains high

Then target:
- non-interactive admission tightening,
- fan-out reduction,
- post-completion/cache-warm duplication,
- or Block B/Block C boundary tightening.

Not raw decode first.

---

## Do not repeat these mistakes

1. **Do not start with another decode micro-pass** unless fresh evidence shows visible decode is again dominant.
2. **Do not remove the Qt startup refit**; it is the current fix for the last-series wrong-zoom bug.
3. **Do not widen small-stack fast prefetch again** without new measured evidence.
4. **Do not move Block C work back into the first-image path**.
5. **Do not treat the ClearCanvas comparison as fully executed runtime truth yet**; it is still partially simulated/prepared.

---

## One-line handoff summary

The current FAST path has already improved Block A structure and Block B first-image stability, the latest visible drag path is fast enough that decode is no longer the first suspect, and the next agent should continue the roadmap by measuring and reducing **background/control-plane CPU pressure** while preserving the current A → B → C priority contract.
