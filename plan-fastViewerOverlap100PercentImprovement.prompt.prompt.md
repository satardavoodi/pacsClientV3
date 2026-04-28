# Plan: FAST Viewer Same-Series Download+Stack — Step-Based 100% Improvement Plan

Date: 2026-04-28
Owner: FAST viewer team
Scope: FAST mode only (`pydicom_qt`). Advanced viewer untouched. Only shared services that demonstrably impact overlap scenario are in scope.
Primary scenario: user is stacking (drag/wheel) on a series whose download is still in progress.
Goal: ≥100% improvement (i.e., halve) on at least two of `overlap_set_slice_present_p95_ms`, `overlap_cache_hit_ratio_pct` (raise), `overlap_effective_fps` (raise) — without any image-quality regression.

---

## Global rules (apply to every phase and every step)

1. **No regression vs current status — hard rule.** Every step must improve the targeted KPI(s) AND must not degrade any other KPI, behavior, or user-visible function compared to the immediately-preceding committed baseline. "No regression" covers:
   - **Image quality**: pixel-hash match 100% on settled frames, ≥99% on surrogate frames (Phase F1 harness).
   - **Functional behavior**: every test in §"Regression test bundle" must stay green from baseline `main` through F10.
   - **Performance KPIs (non-overlap)**: `fast_drag_event_p95_ms`, `set_slice_present_p95_ms` (idle), `cache_hit_ratio_pct` (idle), `cpu_p95_pct` (idle), `process_rss_mb`, `download_throughput_mb_s`, `thumbnail_first_paint_ms`, `series_switch_ms`, `startup_ms` must each stay within ±5% of the preceding baseline.
   - **R1–R17 invariants**: no rule weakened. Step-level callouts list which R-rules are in scope.
   - **Memory & threads**: 60-min synthetic stress shows flat RSS and bounded thread count.
   - **Builds**: PyInstaller build (`build.py --clean-build`) green on PC A every phase; full builder validation at F10.3.
2. **Plugin-package mirror parity.** Any change to `modules/viewer/fast/*.py` (or other production modules with mirror copies) is mirrored in `builder/plugin package/packages/.../payload/python/...` in the same commit.
3. **Per-step gating.** Each step has a Done-When block. No step is marked complete until Done-When passes AND the no-regression bundle below passes.
4. **One step per commit.** Commits are atomic to allow rollback per step.
5. **Cross-PC validation per repo rule.** PC A implements + measures; PC B re-runs same scenario; both KPI files committed before next phase starts.
6. **Default-off for risky knobs.** Any new env var, lane, or behavior change that could surprise other code paths ships default-off and is documented in copilot-instructions.md.

### Regression test bundle (must stay green every step)

Run these as a single named bundle `pytest -m regression_overlap` (label added in F0.2):

- `tests/viewer/test_fast_viewer_pipeline.py` (61 tests — progressive display, done-guard, stale-guard, DM notify cooldown, H4 lifecycle).
- `tests/viewer/test_overlap_pixel_quality.py` (Phase F1 — image quality).
- `tests/viewer/test_b34_interaction_aware_policy.py` (R12 prefetch admission, series readiness).
- `tests/viewer/test_advanced_protected_interaction.py` (R15 unified latch — ensures FAST changes do not break Advanced).
- `tests/viewer/test_stage1_migration_validation.py` + `test_stage2_hardening_validation.py` (backend resolution, escape hatch).
- `tests/viewer/test_disk_pixel_cache.py`, `test_decode_service.py` (caches & decode service).
- `tests/viewer/test_cp1_control_plane_governance.py` (epoch-aware L3, mixed-load throttle).
- `tests/download_manager/run_dm_test.py` (S1–S27 — priority, cancel, R17/R19b/R20).
- `tests/download_manager/test_dm_stress.py` (H1–H10 — load tests).
- `tests/load/run_load_test.py` (L1–L11 — multi-patient load).
- `tests/database/run_db_test.py` (DB pool & FK indexes).
- `tests/network/test_network.py` (socket framing, retry).
- `tests/smoke/test_import_smoke.py` (26+ imports).
- `tests/connection_between_modules/` (cross-module wiring).
- `tests/performance/test_overlap_kpi_parser.py` (added F0.2).

### KPI no-regression matrix (delta tolerances)

| KPI | Tolerance vs preceding baseline | Notes |
|---|---|---|
| `fast_drag_event_p95_ms` (idle, no download) | +0% | already-shipped v2.3.6 win, must hold |
| `set_slice_present_p95_ms` (idle) | +5% | scrolling without download |
| `cache_hit_ratio_pct` (idle) | -2 pts | idle drag should not regress |
| `cpu_p95_pct` (idle) | +5% | absolute pts |
| `process_rss_mb` (60-min run) | +5% | leak guard |
| `thread_count_p95` | +1 thread per declared new lane only | F4.1 +1, F8.2 +1 |
| `startup_ms` | +3% | covers eager-init regressions |
| `series_switch_ms` (warm) | +5% | drag-drop responsiveness |
| `thumbnail_first_paint_ms` | +5% | sidebar responsiveness |
| `download_throughput_mb_s` | -3% (default config) / -10% (F9 opt-in only) | DM cooperation must not steal throughput |
| `overlap_pixel_hash_match_pct` (settled) | 100% absolute | hard gate |
| `overlap_pixel_hash_match_pct` (surrogate) | ≥99% absolute | hard gate |

**Procedure each step:**
1. Capture pre-change run of regression bundle + KPI snapshot (`<step>_pre.json`).
2. Apply change.
3. Capture post-change run (`<step>_post.json`).
4. Diff JSONs against the matrix above. Any breach blocks the step until resolved or reverted.

---

## Phase Index

| Phase | Title | Steps | Risk | Dependencies |
|---|---|---|---|---|
| F0 | Baseline & Tooling | 4 | Low | none |
| F1 | Image-Quality Regression Harness | 3 | Low | F0 |
| F2 | Overlap KPI lane in production code | 2 | Low | F0 |
| F3 | Pre-queue cancellation guard | 3 | Low-Med | F0, F1 |
| F4 | Foreground decode lane separation | 3 | Med | F1, F3 |
| F5 | In-flight decode coalescing | 2 | Med | F1, F4 |
| F6 | Frame prefetch during protected drag | 4 | Med (highest leverage) | F1, F2, F4 |
| F7 | Adaptive surrogate radius for overlap | 2 | Low-Med | F1, F6 |
| F8 | Header pre-warm via DM completion hook | 2 | Low | F1 |
| F9 | DM disk-flush backpressure (opt-in) | 3 | Med | F1, F6 |
| F10 | Acceptance, Documentation, Release | 3 | Low | all |

---

## Phase F0 — Baseline & Tooling

**Phase goal:** Establish a reproducible overlap baseline and the parser pipeline so every later step has a numeric before/after.

### Step F0.1 — Capture canonical baseline log

**Goal:** Have one canonical `overlap_baseline_v0.json` checked in.

**Actions:**
1. With current `main` checked out clean, launch app on PC A.
2. Open a study with one large series (≥120 slices) and start its download.
3. While download is active and series is partially complete (~30–60%), perform 5 drag bursts (3 fast, 2 slow) and 2 wheel bursts on that series.
4. Stop after series completes; copy `user_data/logs/viewer_diagnostics.log` to `generated-files/benchmarks/overlap_baseline_v0/viewer_diagnostics_sess-<id>.log`.
5. Run `python tools/performance/clearcanvas_aipacs_kpi_harness.py --log <copied log> --out generated-files/benchmarks/overlap_baseline_v0.json`.

**Structures to change:** none (read-only step).

**KPIs to review (snapshot only):**
- `set_slice_present_p95_ms`, `decode_p95_ms`, `frame_render_p95_ms`, `cache_hit_ratio_pct`, `cancelled_task_ratio`, `slow_frame_count_16ms`, `cpu_p95_pct`, `effective_fps`, `prefetch_submitted`, `prefetch_completed`, `foreground_wait_p95_ms`.

**Measurement tools:**
- `clearcanvas_aipacs_kpi_harness.py` for parsing.
- Windows Task Manager / `psutil`-based one-shot probe for ground-truth CPU.

**Tests:** none.

**Documentation:**
- Append baseline JSON path and one-paragraph summary to `docs/plans/performance/FAST_VIEWER_PERFORMANCE_ENGINEERING_PLAN_2026-04-27.md` § Phase 9.
- Create `docs/performance/OVERLAP_KPI_BASELINE.md` with the JSON values inline.

**Success criteria:**
- `overlap_baseline_v0.json` exists on disk.
- All 11 listed KPIs are present and non-null.

**Done-When:** PR contains the baseline JSON, the log slice, and the doc page; reviewer confirms numbers are within ±10% of `aipacs_live_overlap_fresh.json` (sanity).

---

### Step F0.2 — Add overlap-scenario parser to KPI harness

**Goal:** Harness emits a dedicated `overlap_*` KPI block whenever the run carries the overlap tag.

**Actions:**
1. In `tools/performance/clearcanvas_aipacs_kpi_harness.py`, add CLI flag `--scenario aipacs_live_download_overlap`.
2. Add log-pattern parser for new tag `[OVERLAP_SCENARIO]` (introduced in Step F2.1).
3. Emit JSON keys `overlap_set_slice_present_p95_ms`, `overlap_decode_p95_ms`, `overlap_cache_hit_ratio_pct`, `overlap_cancelled_task_ratio`, `overlap_slow_frame_pct_16ms`, `overlap_effective_fps`, `overlap_prefetch_admitted_per_s`, `overlap_foreground_wait_p95_ms`.
4. Fall back to scenario-agnostic parsing when no tag found (back-compat).

**Structures to change:** `tools/performance/clearcanvas_aipacs_kpi_harness.py` only.

**KPIs to review:** none (this step *defines* them).

**Measurement tools:** unit test using a synthetic log fixture.

**Tests:**
- New `tests/performance/test_overlap_kpi_parser.py` — fixture log with 5 known overlap events; asserts harness emits exact expected values.

**Documentation:**
- Add "Overlap KPI block" section to `docs/performance/FAST_VIEWER_KPI_CATALOG.md`.
- Add target thresholds table:

| KPI | Baseline (F0.1) | Target | Notes |
|---|---|---|---|
| `overlap_set_slice_present_p95_ms` | ~155 | ≤77 | 50% of baseline |
| `overlap_cache_hit_ratio_pct` | ~52 | ≥85 | |
| `overlap_cancelled_task_ratio` | ~98 | ≤30 | |
| `overlap_effective_fps` | ~16 | ≥30 | |
| `overlap_pixel_hash_match_pct` | n/a | 100 | settled frames |

**Success criteria:** New parser test passes; harness handles legacy logs unchanged.

**Done-When:** `pytest tests/performance/ -q` green; harness output JSON contains all overlap_* keys.

---

### Step F0.3 — Cross-PC baseline parity check

**Goal:** Confirm baseline reproduces on PC B within ±20% before any change.

**Actions:**
1. Push F0.1+F0.2 branch.
2. PC B pulls, runs same scenario, copies log, runs harness.
3. Save PC B output as `generated-files/benchmarks/overlap_baseline_v0_pcb.json`.
4. Compare JSON; document any KPI that differs by >20% as a known PC-bound variable.

**Structures to change:** none.

**KPIs to review:** all overlap_* from F0.2.

**Measurement tools:** harness output diff.

**Tests:** none.

**Documentation:** append PC A vs PC B table to `docs/performance/OVERLAP_KPI_BASELINE.md`.

**Success criteria:** Both baselines committed; deltas understood and documented.

**Done-When:** doc updated; no KPI shows >50% difference (would indicate broken setup).

---

### Step F0.4 — Synthetic overlap dataset for headless runs

**Goal:** Replace ad-hoc human runs with a deterministic synthetic dataset that the harness can drive without UI.

**Actions:**
1. Generate a synthetic 60-slice 256×256 series (all SOP UIDs unique, synthetic IPP/IOP, MONOCHROME2, slope=1, intercept=-1024).
2. Add `tools/performance/synthetic_overlap_runner.py` that:
   - mocks `is_heavy_download_active = True` for a configurable duration,
   - feeds slices to `Lightweight2DPipeline` simulating mid-download arrival (drip-feed at 10 Hz),
   - drives `set_slice` calls at 30 Hz across the slice range,
   - emits the `[OVERLAP_SCENARIO]` tagged log lines.
3. Smoke-run produces `overlap_baseline_v0_synthetic.json`.

**Structures to change:**
- New file `tools/performance/synthetic_overlap_runner.py`.
- New file `tests/fixtures/synthetic_overlap_series/` with checked-in DICOM stubs (small enough to commit).

**KPIs to review:** all overlap_* — synthetic run should be within 30% of human-driven baseline (allows for jitter).

**Measurement tools:** synthetic runner itself.

**Tests:** `tests/performance/test_synthetic_overlap_runner.py` smoke test.

**Documentation:** add "Headless overlap reproducer" section to `docs/performance/FAST_VIEWER_KPI_CATALOG.md`.

**Success criteria:** Synthetic run completes <60 s and emits valid JSON.

**Done-When:** synthetic run reproduces ranking (i.e., `cancelled_task_ratio` is high, `cache_hit_ratio` is moderate) — exact numbers may differ.

---

## Phase F1 — Image-Quality Regression Harness (mandatory ship gate)

**Phase goal:** Build a deterministic pixel-hash test that catches any visual regression introduced by F3–F9 before the change ships.

### Step F1.1 — Golden hash capture utility

**Goal:** A pytest fixture that captures `sha256(qimage.bits())` per slice for the synthetic series under controlled W/L, MONOCHROME1, MONOCHROME2, filter on, filter off.

**Actions:**
1. Add `tests/viewer/test_overlap_pixel_quality.py` with 4 parametrized cases (filter×photometric).
2. Add `--capture-golden` pytest CLI flag that writes `tests/viewer/golden/overlap_pixel_<case>.json`.
3. Without flag, test asserts current hashes match golden.

**Structures to change:**
- New `tests/viewer/test_overlap_pixel_quality.py`.
- New `tests/viewer/golden/*.json` (capture-mode outputs).

**KPIs to review:** none (this is the quality gate, not a perf KPI).

**Measurement tools:** pytest, hashlib.

**Tests:** the test itself.

**Documentation:** add §"Image-quality harness" to `docs/performance/FAST_VIEWER_KPI_CATALOG.md` and a note in `.github/copilot-instructions.md` Test coverage map.

**Success criteria:** `pytest tests/viewer/test_overlap_pixel_quality.py --capture-golden` writes 4 JSON files; subsequent run without flag passes.

**Done-When:** golden files committed; CI green.

---

### Step F1.2 — Drag-mode harness variant

**Goal:** Capture both *settled* (post-drag) and *in-drag surrogate* hashes; settled must be 100% match, surrogate must be ≥99%.

**Actions:**
1. Extend the test to drive `begin_protected_drag_session` + a sequence of target slices; collect surrogate hashes during drag and final hashes after `end_protected_drag_session`.
2. Two assertion sets:
   - `settled_match_pct == 100`
   - `surrogate_match_pct >= 99`

**Structures to change:** same test file.

**KPIs to review:** none.

**Measurement tools:** pytest.

**Tests:** the test itself.

**Documentation:** none (covered by F1.1 doc).

**Success criteria:** test passes on baseline `main`.

**Done-When:** golden surrogate set captured; CI green.

---

### Step F1.3 — CI wiring

**Goal:** Pixel-hash test runs on every PR that touches `modules/viewer/fast/**`.

**Actions:**
1. Add path-filter to existing CI config (or local `run_test.ps1`) so this test runs whenever fast-viewer paths change.
2. Add a one-line warning in `.github/copilot-instructions.md` § Critical rules: "Any change in `modules/viewer/fast/lightweight_2d_pipeline.py` requires `tests/viewer/test_overlap_pixel_quality.py` green."

**Structures to change:** CI config, copilot-instructions.md.

**KPIs to review:** none.

**Tests:** the test runs.

**Documentation:** copilot-instructions.md update.

**Success criteria:** PR with a deliberately broken filter dimension triggers test failure (red-team verification).

**Done-When:** red-team test fails; fix-it-back PR passes.

---

## Phase F2 — Overlap KPI lane in production code

**Phase goal:** Production code emits the `[OVERLAP_SCENARIO]` tagged log lines that F0.2 parses.

### Step F2.1 — Tag emission in pipeline

**Goal:** `Lightweight2DPipeline.get_rendered_frame` and `_decode_into_cache` emit one structured log line per call carrying overlap state.

**Actions:**
1. In `Lightweight2DPipeline.get_rendered_frame`, on every call when `is_heavy_download_active() and not is_viewed_series_complete(self._series_number)`, emit:
   - `logger.debug("[OVERLAP_SCENARIO] frame idx=%d cache=%s decode_ms=%.2f wl_ms=%.2f total_ms=%.2f settled=%s", ...)`.
2. Sample at 1-in-N (N=5) to bound log volume; controlled by env `AIPACS_OVERLAP_LOG_SAMPLE`.
3. Mirror to plugin-package copy.

**Structures to change:** `modules/viewer/fast/lightweight_2d_pipeline.py` + plugin mirror.

**KPIs to review:** harness output now populated for overlap_* keys.

**Measurement tools:** harness on a fresh log.

**Tests:** extend `test_overlap_kpi_parser.py` to assert the new log lines appear and parse.

**Documentation:** add §"Overlap log tag" to `docs/performance/FAST_VIEWER_KPI_CATALOG.md`.

**Success criteria:** running scenario from F0.1 again now produces non-zero overlap_* KPIs.

**Done-When:** harness JSON shows >0 overlap samples; log volume increase <5% over baseline.

---

### Step F2.2 — Re-baseline with tag in place

**Goal:** Replace `overlap_baseline_v0.json` with `overlap_baseline_v1.json` (same code, but with tag) so future deltas use a stable reference.

**Actions:** rerun F0.1 procedure on PC A and PC B; commit JSONs.

**Structures to change:** none.

**KPIs to review:** all overlap_*.

**Measurement tools:** harness.

**Tests:** none.

**Documentation:** update `OVERLAP_KPI_BASELINE.md` with v1 numbers.

**Success criteria:** v1 baseline committed for both PCs.

**Done-When:** v1 deltas vs v0 are within ±10% (no measurement bias from logging).

---

## Phase F3 — Pre-queue cancellation guard

**Phase goal:** Reduce `cancelled_task_ratio` from ~98% toward ≤30% by rejecting stale prefetch tasks before they enter the executor queue.

### Step F3.1 — Move generation/epoch checks into `_submit_prefetch`

**Goal:** Three of the four cancel gates fire BEFORE `executor.submit`.

**Actions:**
1. In `Lightweight2DPipeline._submit_prefetch(idx, generation, request_epoch)`:
   - Read current `_prefetch_generation` and `_prefetch_request_epoch` under `_prefetch_lock`.
   - If `generation != current` or (`request_epoch > 0` and `request_epoch != current_epoch` and `idx not in _active_prefetch_targets`), set `_prefetch_pending.discard(idx)`, increment `PerfMetrics.cancelled_task`, return.
2. Same for distance check: if `abs(idx - self._current_index) > self._config.prefetch_radius * 2` → reject pre-queue.
3. Keep all post-decode guards intact (covers in-flight scroll past).
4. Mirror to plugin package.

**Structures to change:** `modules/viewer/fast/lightweight_2d_pipeline.py` + mirror.

**KPIs to review (before vs after):** `overlap_cancelled_task_ratio` (target ≤50% as intermediate).

**Measurement tools:** harness; F1.x harness for correctness.

**Tests:**
- Existing `tests/viewer/test_b34_interaction_aware_policy.py` must stay green.
- New `tests/viewer/test_prefetch_pre_queue_cancel.py` — assert that submitting with a stale generation never increments executor task count.

**Documentation:** `docs/IMAGE_PIPELINE_REFERENCE.md` section "Prefetch cancellation gates" — describe new pre-queue order.

**Success criteria:** `overlap_cancelled_task_ratio` drops by ≥40% absolute on synthetic run.

**Done-When:** F1.x harness 100% pass; perf KPI achieved on synthetic + manual PC A run.

---

### Step F3.2 — Active-target set update on direction reversal

**Goal:** Direction-flip during drag promotes new targets and demotes old ones in O(1).

**Actions:**
1. In `_prefetch_around()`, when the new `direction` differs from the previously stored `_last_prefetch_direction`, fully replace `_active_prefetch_targets` and bump `_prefetch_request_epoch` even if some new targets overlap with old.
2. Add unit test for direction reversal cancelling all old-direction queued tasks.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_cancelled_task_ratio`, `overlap_prefetch_admitted_per_s`.

**Tests:** new `test_direction_reversal_invalidates_targets` in same file.

**Documentation:** add R-rule note in copilot-instructions.md "Direction-flip prefetch invalidation".

**Success criteria:** test passes; F1.x harness still 100%.

**Done-When:** unit test green; manual drag with rapid up/down reversal shows no stale-frame freeze.

---

### Step F3.3 — Cross-PC verification + commit baseline v2

**Goal:** Lock in F3 gains.

**Actions:** PC A run → PC B run → both JSONs committed as `overlap_baseline_v2_*.json`.

**Structures to change:** none.

**KPIs to review:** all overlap_*.

**Tests:** all from F1, F3.

**Documentation:** update `OVERLAP_KPI_BASELINE.md` with v2 row + delta vs v1.

**Success criteria:** ≥40% reduction in `overlap_cancelled_task_ratio` confirmed on both PCs.

**Done-When:** baseline v2 committed; delta documented.

---

## Phase F4 — Foreground decode lane separation

**Phase goal:** Decouple foreground decode from prefetch backlog so worst-case `decode_p95_ms` drops.

### Step F4.1 — Introduce `_foreground_decode_executor`

**Goal:** Dedicated 1-worker `ThreadPoolExecutor` for foreground decode.

**Actions:**
1. In `Lightweight2DPipeline.__init__`, add `_foreground_decode_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fast-fg-decode")`.
2. Add `close_series` shutdown of the new executor.
3. No callers yet (lane is dormant).

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `thread_count_p95` (must increase by exactly +1).

**Tests:** existing `test_fast_viewer_pipeline.py` — assert thread count delta on construction.

**Documentation:** `docs/IMAGE_PIPELINE_REFERENCE.md` "FAST decode lanes" section — list 3 lanes (foreground, prefetch, frame-prefetch).

**Success criteria:** unit test green; baseline KPIs unchanged.

**Done-When:** F1.x harness 100%; thread count = baseline + 1.

---

### Step F4.2 — Route foreground decode misses through new lane

**Goal:** `_set_pixel(idx)` cache miss + surrogate-staleness-break decode path uses `_foreground_decode_executor`.

**Actions:**
1. Identify the synchronous call sites that currently call `_decode_slice` directly on the main thread; convert them to `_foreground_decode_executor.submit(...).result(timeout=...)`.
2. Tune timeout: 100 ms hard cap. On timeout, fall back to in-line in-process decode (current behavior).
3. Preserve existing `disk_pixel_cache.get` + `decode_service` precedence.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_decode_p95_ms`, `overlap_foreground_wait_p95_ms`, `overlap_set_slice_present_p95_ms`.

**Tests:** F1.x; new `test_foreground_decode_lane_isolation` — block prefetch executor, assert foreground decode still completes within budget.

**Documentation:** copilot-instructions.md new R-rule "Foreground decode lane is single-worker; do not share with prefetch".

**Success criteria:** `overlap_decode_p95_ms` drops by ≥30% on synthetic run.

**Done-When:** unit test green; F1.x harness 100%; KPI drop confirmed on PC A.

---

### Step F4.3 — Cross-PC verification + baseline v3

**Goal:** Lock F4 gains.

**Actions:** PC A → PC B; commit `overlap_baseline_v3_*.json`.

**Structures to change:** none.

**KPIs to review:** decode + foreground_wait.

**Tests:** all.

**Documentation:** baseline doc updated.

**Success criteria:** both PCs show ≥30% `decode_p95` reduction.

**Done-When:** baseline v3 committed.

---

## Phase F5 — In-flight decode coalescing

**Phase goal:** Eliminate redundant foreground decode when a prefetch for the same `idx` is already running.

### Step F5.1 — Coalesce wait

**Goal:** `_set_pixel(idx)` waits ≤30 ms on a pending prefetch instead of starting a duplicate decode.

**Actions:**
1. Add `_prefetch_completion: dict[int, threading.Event]` keyed by idx, populated in `_submit_prefetch` and signalled in `_decode_into_cache` finally-block.
2. In `_set_pixel(idx)` cache miss: if `idx in _prefetch_pending`, get/create the Event, wait up to 30 ms; on signal, re-check `_pixel_cache`. On timeout, proceed with foreground decode (preserve correctness).
3. Always discard Event from dict after signalling to avoid leaks.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_foreground_wait_p95_ms` (target -50% vs F4.3 baseline), `overlap_decode_p95_ms`.

**Tests:** new `test_decode_coalesce_no_duplicate_decode` — count `_decode_slice` invocations; assert exactly 1 even with simultaneous prefetch + foreground demand for same idx.

**Documentation:** `docs/IMAGE_PIPELINE_REFERENCE.md` "In-flight decode coalescing".

**Success criteria:** test passes; KPI improves; F1.x harness 100%.

**Done-When:** unit test green; KPI confirmed; no deadlock in 1-hour stress run.

---

### Step F5.2 — Stress + cross-PC

**Goal:** Confirm no deadlock or starvation under 60-min synthetic overlap stress.

**Actions:**
1. Synthetic runner extension: 60-min loop with rapid scroll bursts.
2. Watch for hung Events, leaked dict entries, RSS growth >50 MB.

**Structures to change:** `synthetic_overlap_runner.py`.

**KPIs to review:** `process_rss_mb` over time, Event count.

**Tests:** stress run script.

**Documentation:** add stress run results to `OVERLAP_KPI_BASELINE.md`.

**Success criteria:** flat RSS, no hangs, KPI stable.

**Done-When:** 60-min run logged; commit `overlap_baseline_v4_*.json`.

---

## Phase F6 — Frame prefetch during protected drag (highest leverage)

**Phase goal:** Convert cache-hit drag frames from 5–10 ms (W/L+QImage on main) to ≤0.5 ms (paint only) by pre-rendering the directional next frame on a background thread.

### Step F6.1 — New `WorkClass.FRAME_PREFETCH` admission rule

**Goal:** `ui_throttle.should_admit` accepts a new work class with priority gating.

**Actions:**
1. In `modules/viewer/fast/ui_throttle.py`:
   - Add `WorkClass.FRAME_PREFETCH`.
   - During protected drag, admit only if `ctx.get("priority", 999) <= 1`. Default = deny.
   - During heavy download alone, admit unconditionally up to system load controller.
2. Mirror.

**Structures to change:** `ui_throttle.py` + mirror, `system_load_controller.py` if needed.

**KPIs to review:** none yet (caller not wired).

**Tests:** new `test_frame_prefetch_admission` — assert priority<=1 admits, others deny under protected drag.

**Documentation:** copilot-instructions.md new R-rule "FRAME_PREFETCH admission" (mirrors R12 for PREFETCH).

**Success criteria:** unit test green.

**Done-When:** test green; admission table verified.

---

### Step F6.2 — Submit P1 frame prefetch on drag target step

**Goal:** On each `begin_stack_drag_target` call during protected drag, if direction is known and `(center+sign)` exists in `_pixel_cache`, submit a frame prefetch for that slice.

**Actions:**
1. In `Lightweight2DPipeline._prefetch_around` protected-drag branch: for the first ordered target only, also call `self._submit_frame_prefetch(target_idx, priority=FastWorkPriority.P1_NEIGHBOR)` if its pixel is cached AND its frame is NOT cached.
2. Cap concurrent in-flight frame prefetches to 1 (`_frame_prefetch_inflight: int`); skip if already at cap.
3. Mirror.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_set_slice_present_p95_ms` (target ≤77 — primary KPI of plan).

**Tests:** new `test_frame_prefetch_during_drag_p1_only` — drag with cached pixels at center±1 → exactly 1 frame prefetch submitted per drag step in P1 lane.

**Documentation:** `docs/IMAGE_PIPELINE_REFERENCE.md` "Frame prefetch in protected drag" + R-rule note.

**Success criteria:** F1.x harness 100%; KPI `overlap_set_slice_present_p95_ms` drops by ≥50% vs F5.2 baseline.

**Done-When:** all green; KPI confirmed on PC A.

---

### Step F6.3 — Frame cache key audit

**Goal:** Confirm the frame cache key `(idx, ww, wc, filter_enabled)` is stable during a drag (no per-slice WL change). Detect any code path that mutates WL mid-drag.

**Actions:**
1. Audit `set_window_level` callers; assert none fire during `_protected_drag_active`.
2. If any do, add a guard that defers WL updates until drag end (rare, but defensive).
3. Add unit test `test_wl_stable_during_drag`.

**Structures to change:** possibly `qt_viewer_bridge.py`, `lightweight_2d_pipeline.py`.

**KPIs to review:** F1.x pixel hash (must remain 100%).

**Tests:** new test as above.

**Documentation:** R-rule "WL changes deferred during protected drag".

**Success criteria:** test green; F1.x 100%.

**Done-When:** audit doc + test in PR.

---

### Step F6.4 — Cross-PC + baseline v5

**Goal:** Lock F6 gains.

**Actions:** PC A → PC B; commit `overlap_baseline_v5_*.json`.

**Structures to change:** none.

**KPIs to review:** **the primary KPI** — `overlap_set_slice_present_p95_ms`.

**Tests:** full F1.x + perf.

**Documentation:** baseline doc with delta from v0.

**Success criteria:** Both PCs show `overlap_set_slice_present_p95_ms ≤ 77 ms` (≥50% drop from v0=155).

**Done-When:** PC B confirms; this is the candidate "100% improvement" milestone for the primary KPI.

---

## Phase F7 — Adaptive surrogate radius for overlap

**Phase goal:** Push `overlap_cache_hit_ratio_pct` from current ~52% to ≥85% by widening the nearest-cached-pixel surrogate window when sparse.

### Step F7.1 — Sparse-density measurement

**Goal:** Compute average gap between cached slices in the ±15 window in O(1) per drag step.

**Actions:**
1. Maintain a small sorted list `_cached_index_window` of cached idx within ±15 of `_current_index`; updated on `_put_pixel_cache` and on drag move.
2. Compute `sparse_density = mean(gaps)` lazily.
3. Mirror.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** none yet.

**Tests:** new `test_sparse_density_calc`.

**Documentation:** none yet (next step uses it).

**Success criteria:** unit test green; perf cost ≤5 µs/call.

**Done-When:** unit test green.

---

### Step F7.2 — Surrogate radius adapts during overlap

**Goal:** `_try_surrogate_frame` allows radius up to `min(25, sparse_density * 1.5)` only when `is_heavy_download_active() and not is_viewed_series_complete()`.

**Actions:**
1. In `_try_surrogate_frame`, replace fixed ±20 cap with adaptive cap.
2. Preserve `_surrogate_repeat_count` break (R1) — must NOT widen if surrogate would otherwise be stuck.
3. Mirror.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_cache_hit_ratio_pct` (target ≥85), `overlap_pixel_hash_match_pct` for surrogate frames (must stay ≥99).

**Tests:** F1.x extended with sparse-cache scenario.

**Documentation:** R-rule "Adaptive surrogate radius".

**Success criteria:** KPI hits ≥85% on PC A synthetic.

**Done-When:** F1.x 100% settled / ≥99% surrogate; baseline v6 committed.

---

## Phase F8 — Header pre-warm via DM completion hook

**Phase goal:** Eliminate per-slice header read latency for newly-arrived slices on the actively viewed series.

### Step F8.1 — Per-instance saved hook

**Goal:** `HomeDownloadService` exposes a per-instance saved Qt signal for the actively viewed series.

**Actions:**
1. In `home_download_service.py`, add `instance_saved = Signal(int, str)` (series_number, file_path).
2. Emit from `on_series_progress` only when the new file count increased.
3. ViewerController connects the signal for its active series; disconnects on switch.

**Structures to change:** `home_download_service.py`, `_vc_progressive.py` (or appropriate VC mixin).

**KPIs to review:** none yet.

**Tests:** new `test_instance_saved_signal` — DM mock fires N progress updates; signal fires N times.

**Documentation:** `docs/architecture/home-ui-services.md` updated with new signal.

**Success criteria:** test green; no signal storm (rate-limited if needed).

**Done-When:** signal wiring committed.

---

### Step F8.2 — Header pre-warm executor in pipeline

**Goal:** Receive `instance_saved`, post a header-only `dcmread` to a 1-worker `_header_warm_executor`, update `_slices[idx]` IPP/IOP/spacing fields.

**Actions:**
1. In `Lightweight2DPipeline`, add `_header_warm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fast-hdr-warm")`.
2. New method `prewarm_header(file_path)` — submit; on completion update `_slices[idx]` fields atomically.
3. Use `_INSTANCE_TAGS` from `series_downloader.py` (already optimized in Phase 6 patch).
4. Skip if `is_protected_drag_active()` to keep drag GIL clean; queue and resume after drag.

**Structures to change:** `lightweight_2d_pipeline.py` + mirror.

**KPIs to review:** `overlap_set_slice_present_p95_ms` for first-visit slices (sub-KPI: `first_visit_set_slice_p95_ms`).

**Tests:** new `test_header_prewarm_no_main_thread_io`.

**Documentation:** R-rule "Header pre-warm queues during drag".

**Success criteria:** First-visit slice latency on actively-downloading series drops by ≥30%.

**Done-When:** test + KPI green; baseline v7.

---

## Phase F9 — DM disk-flush backpressure (opt-in)

**Phase goal:** Reduce disk I/O contention during drag without OS-priority side effects (avoid R13 priority inversion).

### Step F9.1 — Inter-batch sleep flag

**Goal:** `SeriesDownloader._download_batch` honors `AIPACS_OVERLAP_BATCH_PAUSE_MS` env var (default 0).

**Actions:**
1. After each batch write, if env var > 0 AND `{user_data}/cache/.drag_active` was modified within last 2 s AND the active study UID matches viewer's series → `time.sleep(env_value / 1000)`.
2. Default OFF.

**Structures to change:** `modules/download_manager/download/series_downloader.py` + builder mirror.

**KPIs to review:** `download_throughput_mb_s` (must regress ≤10%), `overlap_set_slice_present_p95_ms` (target additional ≥10% improvement).

**Tests:** new `test_overlap_batch_pause_when_drag_active`.

**Documentation:** `docs/pipelines/download-pipeline.md` new R-rule "Opt-in overlap batch pause".

**Success criteria:** When env var=80, throughput regression ≤10% AND overlap KPI improves; when env var=0 (default), zero behavior change.

**Done-When:** test green; PC A measurement with both flag values.

---

### Step F9.2 — Cross-PC throughput regression check

**Goal:** Confirm flag is safe to recommend.

**Actions:** PC A and PC B run both env values; commit `overlap_baseline_v8_throttled_*.json`.

**Structures to change:** none.

**KPIs to review:** `download_throughput_mb_s`, all overlap_*.

**Tests:** none additional.

**Documentation:** add measurement table to `docs/pipelines/download-pipeline.md`.

**Success criteria:** both PCs ≤10% throughput regression at env=80.

**Done-When:** both runs committed; recommendation documented.

---

### Step F9.3 — Documentation only — no default-on flip

**Goal:** Document opt-in flag; do NOT change default.

**Actions:** update copilot-instructions.md, release notes, README.

**Structures to change:** docs only.

**KPIs to review:** none.

**Tests:** none.

**Documentation:** as above.

**Success criteria:** docs reviewed.

**Done-When:** PR merged with default unchanged.

---

## Phase F10 — Acceptance, Documentation, Release

### Step F10.1 — Final acceptance benchmark

**Goal:** Produce `overlap_acceptance_final.json` (PC A + PC B) showing cumulative deltas.

**Actions:** run full overlap scenario on both PCs from current `main` after F1–F9; commit.

**Structures to change:** none.

**KPIs to review:** all overlap_*; primary acceptance:
- `overlap_set_slice_present_p95_ms` ≤ 50% of v0.
- AND ≥1 of `overlap_cache_hit_ratio_pct` (≥85), `overlap_effective_fps` (≥30) hit target.
- `overlap_pixel_hash_match_pct == 100` (settled), ≥99 (surrogate).

**Measurement tools:** harness, F1 test.

**Tests:** all suites green.

**Documentation:** acceptance report `docs/releases/VERSION_<next>_RELEASE.md` with full KPI table v0→final.

**Success criteria:** acceptance criteria met on both PCs.

**Done-When:** report committed; sign-off.

---

### Step F10.2 — Update copilot-instructions.md

**Goal:** Add all new R-rules generated in F3–F9 to the canonical rule list.

**Actions:** consolidate R-rules emitted in each step; assign R20–R26 numbers; insert under "v2.3.6 stack-drag smoothness rules".

**Structures to change:** `.github/copilot-instructions.md`.

**KPIs to review:** none.

**Tests:** none.

**Documentation:** the file itself.

**Success criteria:** new R-rules present, numbered, cross-referenced.

**Done-When:** PR merged.

---

### Step F10.3 — Release notes + version bump

**Goal:** Tag a new patch version; release notes describe overlap improvements.

**Actions:**
1. Bump `pyproject.toml` version.
2. Add `docs/releases/VERSION_<next>_RELEASE.md` with KPI table, changed files, R-rule additions, rollback notes per phase.
3. Run PyInstaller + Nuitka builds; smoke-test installer.

**Structures to change:** `pyproject.toml`, release notes.

**KPIs to review:** all.

**Tests:** smoke test of built installer per repo build rules.

**Documentation:** release notes.

**Success criteria:** version tagged; installer runs clean on PC B.

**Done-When:** release artifact published.

---

## Per-step no-regression checklist (applied to every step F0.x–F10.x)

Each step inherits this checklist on top of its own Done-When block:

- [ ] **Image quality**: `tests/viewer/test_overlap_pixel_quality.py` green (settled=100%, surrogate≥99%).
- [ ] **Regression bundle**: `pytest -m regression_overlap` green (full list above).
- [ ] **KPI matrix**: `<step>_post.json` vs `<step>_pre.json` within tolerances; any breach blocks merge.
- [ ] **R-rule audit**: rules touched by the step are explicitly listed in the commit message; reviewer confirms wording in `.github/copilot-instructions.md` is consistent or updated in the same PR.
- [ ] **Mirror parity**: `git diff` confirms every `modules/viewer/fast/*.py` change has a mirror in `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/*.py`.
- [ ] **Build smoke**: `python build.py --clean-build` (PyInstaller) succeeds; resulting exe launches the login window on PC A (manual smoke).
- [ ] **Default-off check**: any new env var defaults to a value that produces zero behavior change.
- [ ] **Cross-PC**: scenario rerun on PC B before phase boundary; deltas committed.

## Rollback policy

Every step is one commit. If any checklist item fails after merge, the step's commit is reverted via `git revert <sha>` before the next step is started. No squashing across phase boundaries until the phase's acceptance is recorded in `OVERLAP_KPI_BASELINE.md`.

---

## Risk register and rollback strategy

| Phase | Worst-case failure | Detection | Rollback |
|---|---|---|---|
| F3 | Stale gen check causes legitimate prefetch to be rejected | `overlap_prefetch_admitted_per_s` drops to 0 | Revert single commit |
| F4 | New executor leaks threads on series close | `thread_count_p95` grows over time in F5.2 stress | Disable executor + fall back to in-line |
| F5 | Event leak / deadlock | RSS grows; hangs in 60-min stress | Single-commit revert |
| F6 | Frame prefetch races W/L change → wrong WL on screen | F1 pixel hash diff | Revert F6.2 only; F6.1 (admission rule) is harmless if unused |
| F7 | Surrogate too wide → visible smearing | F1 surrogate match drops <99% | Revert radius cap to ±20 |
| F8 | Header pre-warm corrupts `_slices[idx]` mid-decode | Pixel hash diff or crash | Revert F8.2; keep F8.1 signal harmless |
| F9 | Default-on accidental → throughput regression | DM throughput KPI | Default already OFF; flip env var off |

**Universal rollback:** every step is one commit. `git revert <sha>` per failing step; reapply cleanly.

---

## Success snapshot

After F10.1 we expect (approximate, from PC A synthetic + manual):

| KPI | v0 baseline | Final target | Expected (modeled) |
|---|---|---|---|
| `overlap_set_slice_present_p95_ms` | 155 | ≤77 | ~50–60 |
| `overlap_decode_p95_ms` | 208 | ≤105 | ~70–90 |
| `overlap_cache_hit_ratio_pct` | 52 | ≥85 | ~85–90 |
| `overlap_cancelled_task_ratio` | 98 | ≤30 | ~25–35 |
| `overlap_effective_fps` | 16 | ≥30 | ~30–40 |
| `overlap_pixel_hash_match_pct` (settled) | n/a | 100 | 100 |
| `overlap_pixel_hash_match_pct` (surrogate) | n/a | ≥99 | ≥99 |

This represents ≥100% improvement (i.e., halving) on the primary KPI and the secondary cache/fps KPIs, with image-quality regression ruled out by Phase F1.
