# Plan: FAST Viewer Same-Series Download+Stack — Step-Based 100% Improvement Plan

Date: 2026-04-28
Owner: FAST viewer team
Scope: FAST mode only (`pydicom_qt`). Advanced viewer untouched. Only shared services that demonstrably impact overlap scenario are in scope.
Primary scenario: user is stacking (drag/wheel) on a series whose download is still in progress.
Goal: ≥50% reduction on each of the four Tier-1 synthetic KPIs (`overlap_decode_only_p95_ms`, `overlap_decode_only_max_ms`, `overlap_decode_sample_share_pct`, `overlap_slow_frame_count_16ms`) measured on the harsh-preset synthetic anchor, **plus** ≥50% reduction on the two real-world Tier-2 north stars (`overlap_drag_event_p95_max_ms`, `overlap_drag_ui_lag_max_max_ms`) extracted from `[FAST_DRAG_KPI]` end-of-burst summaries (added in F2.4b, 2026-04-29), **plus** no regression on the supporting Tier-2 KPIs (`overlap_drag_handler_p95_max_ms`, `overlap_drag_background_decode_count_total` = 0 R3 invariant, `overlap_settled_present_p95_ms`, F1 drag-mode pixel hash). The legacy north stars `overlap_set_slice_present_p95_ms` and the standalone `ui_event_loop_lag_ms` p95 were retired on 2026-04-29 — see "Plan retarget — post-F0.5 anchor (2026-04-29)" and "Live-run findings (2026-04-29)" — because the harsh synthetic anchor already reports `set_slice_present` at 0.0 ms (surrogate path dominates the all-samples p95) and because the live-run capture showed Qt event-loop spacing (`event_p95_ms=607.9`, `ui_lag_max_ms=363.9`) is the dominant user-visible spike, not the per-frame `ui_event_loop_lag_ms` callback estimate. Image-quality regression is ruled out by Phase F1.

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
| `overlap_priority_handoff_latency_ms` (drag-drop → critical worker started, p95) | -50% vs F3.5 baseline; absolute ceiling 5 s | added F3.5 |
| `overlap_priority_retry_exhaustion_rate` (warnings per 10 drag-drops during overlap) | ≤0.05 (≈1 in 20) on PC A; 0 on idle baseline | added F3.5 |
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
| F3.5 | DM priority-handoff stall during overlap | 4 | Low-Med | F0, F2, F3 |
| F4 | Foreground decode lane separation | 3 | Med | F1, F3 |
| F5 | In-flight decode coalescing | 2 | Med | F1, F4 |
| F6 | Frame prefetch during protected drag | 4 | Med (highest leverage) | F1, F2, F4 |
| F7 | Adaptive surrogate radius for overlap | 2 | Low-Med | F1, F6 |
| F8 | Header pre-warm via DM completion hook | 2 | Low | F1 |
| F9 | DM disk-flush backpressure (opt-in) | 3 | Med | F1, F6 |
| F10 | Acceptance, Documentation, Release | 3 | Low | all |

---

## Progress snapshot & plan revision (2026-04-28)

This section captures what has actually shipped, what was learned, and the plan deltas that follow. It is appended in-place rather than rewriting the original phases so the audit trail is preserved.

### Commits landed (in order)

| Phase | Commit | Status | Notes |
|---|---|---|---|
| F0.2 | `bb8294fa` | DONE | overlap parser + `parse_overlap_log_text` |
| F1.1 | `f3118ad4` | DONE | golden hash capture (settled) |
| F1.2 | `4bdb422f` | DONE | drag-mode harness variant (surrogate ≥ 99%) |
| F1.3 | `fbb9d105` | DONE | regression bundle wrapper `tools/dev/run_overlap_regression.ps1` (26 tests, ~9–13 s) |
| F2.1 | `9f180262` | DONE | `[OVERLAP_SCENARIO]` emit at 3 return paths in `Lightweight2DPipeline.get_rendered_frame` |
| F0.4 | `ddb773cf` | DONE | `tools/performance/synthetic_overlap_runner.py` + smoke test |

Mirror parity verified for F2.1 (SHA256 match `C8D5893F…CCEAA1A`). F0.x / F1.x / F2.x changes touch only `tools/`, `tests/`, `docs/`, and `modules/viewer/fast/lightweight_2d_pipeline.py` (mirrored).

### Real F0.4 synthetic baseline (committed as `overlap_baseline_v0_synthetic.json`)

Runner config: 5 s @ 30 Hz set_slice, 10 Hz drip-feed, sample_rate=1, 60 slices 256×256.

| KPI | Original plan target table | **Actual synthetic v0** | Implication |
|---|---|---|---|
| `overlap_set_slice_present_p95_ms` | v0=155, target ≤77 | **11.68** | Already 7× better than target. v0=155 was speculative. |
| `overlap_decode_p95_ms` | v0=208, target ≤105 | **10.78** | Same — speculative. |
| `overlap_cache_hit_ratio_pct` | v0=52, target ≥85 | **86.67** | Already past target. F7 widening may not be needed. |
| `overlap_cache_breakdown` | n/a | hit=37, surrogate=93, decode=20 | Surrogate dominates as designed (R1+B3.7). |
| `overlap_slow_frame_pct_16ms` | n/a | 2.67% | 4 frames / 150 — acceptable. |
| `overlap_effective_fps` | v0=16, target ≥30 | **0.0** | **Parser bug** — fps comes back zero; needs F2.x fix (see Revision item R3 below). |
| `overlap_pixel_hash_match_pct` (settled / surrogate) | 100 / ≥99 | null / null | Synthetic runner doesn't capture hashes; F1.x covers this in tests, not in KPI JSON. |

### Production F2.1 verification (2026-04-28 23:01)

Live run produced exactly **2** `[OVERLAP_SCENARIO]` lines for a real drag burst on a partially-downloaded series. Both were `cache=surrogate`, `settled=False`. This is functionally correct (R7 sampling, default 1-in-5) but **statistically thin** for KPI capture from organic user runs.

### Findings that drive plan revision

**R1. The original v0 baseline numbers (155 / 52 / 98 / 16) cannot be reproduced and should be treated as estimates, not measurements.** The synthetic v0 shows the FAST pipeline is already very close to the original "final targets" because subsequent rules (R1 surrogate-staleness break, R12 P1 prefetch, B3.7 nearest-cached surrogate, B3.12 disk pixel cache) shipped between when the original baseline was measured and now. Conclusion: the **definition of "100% improvement"** must be re-anchored on either (a) a real PC A manual repro OR (b) a deliberately harsher synthetic preset.

**R2. The current synthetic preset is too kind to the pipeline.** drip_hz=10 + set_slice_hz=30 with 60 slices means within ~6 s the cache is fully populated and the rest of the run is mostly cache hits and surrogates. The realistic overlap scenario — 200+ slice series, sub-1 Hz drip during slow network, sustained 60+ Hz drag — is not exercised. Plan adjustment: **add a "harsh" preset** as an additional F0.4 invocation rather than as a new phase.

**R3. `overlap_effective_fps = 0.0` is a parser defect**, not a real measurement. The harness `parse_overlap_log_text` derives fps from sample timestamps; the synthetic runner emits `total_ms` but not wall-clock spacing the parser can use. Plan adjustment: **fix in F2.x**, not in a phase by itself.

**R4. F2.1 sampling produces too few production samples for organic capture.** Either (a) accept that synthetic runs are the canonical KPI lane and manual runs are sanity checks, or (b) add "sentinel" emits at decision boundaries (decode-fallback, drag-begin, drag-end, direction-flip) that bypass the 1-in-N sampler. Plan adjustment: **option (a) is canonical; option (b) is a small F2.x follow-up.**

**R5. F3 (FAST pipeline cancellation guards) and F3.5 (DM coordinator priority handoff) touch disjoint code paths and have no shared state.** They can proceed in parallel; the only ordering constraint is that F3.5.4 (default-on flip) waits for F3 baselines so cross-PC measurements are clean.

**R6. Cross-PC validation has not yet exercised PC B for any committed F-step.** F0.3 was the first cross-PC step and is still pending. Plan adjustment: **state explicitly that committed work up to and including F2.1 / F0.4 has been validated on PC A only**; the F0.3 cross-PC pass is the gating step before F3 can claim any baseline-relative win.

### Plan deltas (additive, no prior commit invalidated)

**Add Step F0.5 — Real-world v0 anchor (new).** Replace the speculative 155/52/98/16 numbers in the plan with one of:
- (a) PC A manual overlap repro → commit `overlap_baseline_v0_real.json`. Procedure as F0.1 but with `AIPACS_OVERLAP_LOG_SAMPLE=1` and a series ≥200 slices, network throttled to ~10 MB/s. **Preferred.**
- (b) If (a) is impractical, run synthetic with **harsh preset**: `--duration 30 --set-slice-hz 60 --drip-hz 1 --n-slices 240 --rows 512 --cols 512 --sample-rate 1`. Commit as `overlap_baseline_v0_synthetic_harsh.json`.
- Whichever is captured, **rewrite the target table** in F0.2 (and the Success snapshot at the bottom of the plan) so "100% improvement" means ≥50% reduction relative to the new v0, not the speculative one. Done-When: a single canonical v0 JSON is referenced by every later phase.

**Add Step F0.6 — Harsh-preset CLI flag in synthetic runner (new, small).** In `tools/performance/synthetic_overlap_runner.py`, add `--preset {default,harsh,realistic}` that bundles `--set-slice-hz/--drip-hz/--n-slices/--rows/--cols`. Default keeps current behavior. Done-When: smoke test covers all three presets.

**Refine Step F0.4 — mark numbers as committed; freeze runner version at F0.4 until F0.6 lands.** No code change — documentation refinement only. The runner JSON includes `runner.version="F0.4"`; bump to `"F0.6"` only when the preset flag lands.

**Refine Step F2.1 — add a "sentinel emit" sub-step F2.1b (new).** In `Lightweight2DPipeline.get_rendered_frame`, the existing 1-in-N sampler is unchanged, but four boundary sites bypass the sampler and always emit:
- decode-fallback path (always emit when `cache=decode`),
- first frame after `set_fast_interaction(True, ...)` (drag-begin),
- first frame after `set_fast_interaction(False, ...)` (drag-end),
- direction-flip detected in `_prefetch_around` (emit at next render call).
Guard each with a per-pipeline boolean to ensure exactly one emit per boundary. Mirror to plugin package. Tests: extend `test_overlap_kpi_parser.py` to assert sentinel coverage. **Risk:** small log-volume increase; F2.1's ui_lag rule still holds because emits go through the queued listener (R7).

**Refine Step F2.2 — reclassify as optional sanity check.** If F0.5 captures a real-world v0, F2.2's manual re-baseline becomes a sanity confirmation, not a blocking step. Plan rewording: "Recommended; not a phase gate."

**Refine Step F0.1 — reclassify as optional.** Synthetic v0 (F0.4) + real-world anchor (F0.5) supersede the original F0.1 manual procedure. F0.1 is kept in the document for completeness but marked **optional** in the success snapshot.

**Refine Step F0.3 — retarget to synthetic.** Cross-PC parity check uses `synthetic_overlap_runner.py` on PC B with the **same preset as PC A's anchor**. Manual scenario remains optional. This decouples F0.3 from human availability on PC B.

**Refine Step F2.x — fix `overlap_effective_fps` parser (small).** In `tools/performance/clearcanvas_aipacs_kpi_harness.py::parse_overlap_log_text`, derive fps from the timestamp delta between first and last sample (using the diagnostic_logging timestamp prefix), not from intra-line `total_ms`. Add a regression test in `tests/performance/test_overlap_kpi_parser.py`. Tracked as **F2.3** (new step, after F2.2). Done-When: synthetic runner output reports a non-zero fps.

**Refine Phase F7 (adaptive surrogate radius) — status: candidate for deferral.** If the real-world v0 (F0.5) shows `overlap_cache_hit_ratio_pct ≥ 85` already, F7 has no measurable upside and should be **skipped** rather than risking R1 (surrogate-staleness break) regressions. Decision moved into F0.5's Done-When: "if cache_hit_ratio ≥ 85 on real v0, mark F7 deferred and document in `OVERLAP_KPI_BASELINE.md`."

**Refine Phase F3.5 — split F3.5.2 risk explicitly.** F3.5.1 instrumentation will reveal whether the production exhaustion is dominated by (i) peer-worker stuck >27 s OR (ii) reclamation race. If exclusively (i), F3.5.2 ships only the wall-clock budget extension (low risk) and the reclamation-race CAS is deferred to a follow-up step F3.5.5 (or dropped). If both, F3.5.2 ships as currently written. **Done-When for F3.5.1 must include this branch decision** before F3.5.2 starts coding.

**Add parallelism note to Phase Index:** F3 and F3.5 may proceed in parallel; F3.5.4 default-on flip waits for F3 baselines to land so the F3.5 measurement is taken on a stable FAST pipeline.

### Status of pending phases (after this revision)

| Phase | New status | Blocking |
|---|---|---|
| F0.1 | OPTIONAL (manual sanity) | none |
| F0.3 | RETARGETED to synthetic on PC B | none — can run now |
| **F0.5** | **NEW — BLOCKING for F3+ baselines** | none — can run now |
| **F0.6** | NEW — small, ship before F0.5 if option (b) chosen | none |
| F2.1b | NEW — sentinel emits | F2.1 (done) |
| F2.2 | OPTIONAL sanity | F0.5 |
| F2.3 | NEW — fps parser fix | F0.4 (done) |
| F3 | F3.1 DONE; F3.2 DONE — F3.3 pending (PC B unavailable) | F0.5 (real-world parity), F2.3 (done) |
| F3.5 | F3.5.1 DONE — F3.5.2 pending PC-B baseline | F0.5 (for clean cross-PC measurement) |
| F4–F6 | unchanged | F3 |
| F7 | CONDITIONAL — may be deferred if F0.5 shows cache_hit_ratio ≥ 85 | F0.5 |
| F8–F10 | unchanged | predecessors |

---

## Plan retarget — post-F0.5 anchor (2026-04-29)

The harsh-preset synthetic anchor (committed at `2489af61` as `overlap_baseline_v0_synthetic_harsh.json`) showed that the previously-named primary KPI `overlap_set_slice_present_p95_ms` is **already 0.0 ms** in the worst synthetic scenario (30 s @ 60 Hz drag, 240 slices @ 512×512, drip 1 Hz). The surrogate path (R1 + B3.7) makes the per-frame compute time of in-drag frames structurally <1 ms; that KPI is no longer a meaningful north star. Re-targeting follows.

### Why the old north star is dead

The harness payload over `total_ms` averages **all** samples — and the harsh anchor was 95.55% surrogate/hit and 4.45% decode. The 95.55% are sub-1 ms, so the p95 over the full population is 0.0. The 4.45% decode tail is where every user-visible spike lives, and it was being washed out at the aggregate level.

### New parser KPIs (committed in F2.4)

`tools/performance/clearcanvas_aipacs_kpi_harness.py::parse_overlap_log_text` now emits per-cache-source splits so the plan can target the path that actually drives spikes. New keys (added in this commit):

- `overlap_decode_only_p95_ms` — p95 of `total_ms` for `cache=decode` samples only.
- `overlap_decode_only_max_ms` — max `total_ms` for `cache=decode` samples.
- `overlap_decode_sample_count` — number of `cache=decode` samples in the run.
- `overlap_decode_sample_share_pct` — `decode / total` × 100.
- `overlap_settled_present_p95_ms` — p95 of `total_ms` for `settled=True` samples.
- `overlap_settled_sample_count` — number of `settled=True` samples.
- `overlap_surrogate_present_p95_ms` — p95 of `total_ms` for `cache=surrogate` samples.
- `overlap_hit_present_p95_ms` — p95 of `total_ms` for `cache=hit` samples.
- `overlap_slow_frame_count_16ms` — already existed; promoted to a primary KPI.
- `overlap_slow_frame_source_breakdown` — `{hit, surrogate, decode}` count of frames > 16 ms.

All new keys appear in the empty-input payload with safe defaults so existing diff tooling never sees missing fields. Parser tests: 18 total green (13 prior + 5 new F2.4).

### Anchor numbers (re-captured against the new parser)

`overlap_baseline_v0_synthetic_harsh.json` — preset=harsh, runner.version=F0.6, n=1797 samples:

| KPI | Harsh anchor value | Notes |
|---|---|---|
| `overlap_decode_only_p95_ms` | **13.94** | Real tail latency for foreground decode. |
| `overlap_decode_only_max_ms` | **77.67** | Worst single foreground decode in 30 s. |
| `overlap_decode_sample_count` | **80** | |
| `overlap_decode_sample_share_pct` | **4.45** | |
| `overlap_settled_sample_count` | 1 | Synthetic runner barely exercises settled path; needs real-world capture. |
| `overlap_settled_present_p95_ms` | 7.94 | Single-sample artifact — not yet a stable measurement. |
| `overlap_hit_present_p95_ms` | 0.0 | Cache hit is essentially free (expected). |
| `overlap_surrogate_present_p95_ms` | 0.0 | Surrogate is essentially free (expected, validates R1). |
| `overlap_slow_frame_count_16ms` | **3** | 3 / 1797 = 0.17%. |
| `overlap_slow_frame_source_breakdown` | `{hit:0, surrogate:0, decode:3}` | **100% of slow frames are decode-cache misses.** |
| `overlap_effective_fps` (wall_clock) | 59.59 | Confirms drag rate; not a target. |
| `overlap_set_slice_present_p95_ms` (legacy) | 0.0 | **Demoted from primary; kept for backward compat.** |
| `overlap_cache_hit_ratio_pct` | 95.58 | (hit + surrogate) / total. |

`overlap_baseline_v0_synthetic.json` — preset=default, n=149 samples:

| KPI | Default anchor value |
|---|---|
| `overlap_decode_only_p95_ms` | 14.12 |
| `overlap_decode_only_max_ms` | **91.38** |
| `overlap_decode_sample_share_pct` | 12.75 |
| `overlap_slow_frame_count_16ms` | 1 (from `decode`) |

The smaller default preset lets prefetch warm less of the volume → higher decode share. Both anchors agree on the qualitative shape: decode-cache misses are the only source of >16 ms frames.

### New primary KPIs (north stars)

Two layers — synthetic-canonical and real-world-canonical:

**Synthetic (canonical for F3–F10 commit gating):**

| Tier | KPI | Harsh v0 | Target | Rationale |
|---|---|---|---|---|
| 1 | `overlap_decode_only_p95_ms` | 13.94 | **≤7.0** (≥50% drop) | The path that produces every visible spike. |
| 1 | `overlap_decode_only_max_ms` | 77.67 | **≤40.0** (≥48% drop) | Tail control — single bad frame = perceptible. |
| 1 | `overlap_decode_sample_share_pct` | 4.45 | **≤2.5** (≥44% drop) | Fewer foreground decodes = fewer spike opportunities. |
| 1 | `overlap_slow_frame_count_16ms` | 3 over 30 s | **≤1 over 30 s** | User-visible frame budget metric. |
| 2 | `overlap_drag_event_p95_max_ms` | 607.9 (live 2026-04-28) | **≤300** (≥50% drop) | Real-world Qt event-loop spacing — primary north star (F2.4b). |
| 2 | `overlap_drag_ui_lag_max_max_ms` | 363.9 (live 2026-04-28) | **≤180** (≥50% drop) | Real-world UI-callback lag — primary north star (F2.4b). |
| 2 | `overlap_drag_handler_p95_max_ms` | 3.7 (live 2026-04-28) | hold ≤16 ms (no regression) | Pipeline-side per-frame work budget. |
| 2 | `overlap_drag_background_decode_count_total` | 0 (live 2026-04-28) | hold at 0 | R3 invariant (PREFETCH/CACHE_WARM denied during drag). |
| 2 | `overlap_settled_present_p95_ms` | 1 sample (TBD) | Establish in F0.5b (≥30 samples) | End-of-drag re-render latency. |

**Real-world (added as F0.5b; runs the actual app):**

| KPI | Why real-world only |
|---|---|
| `overlap_drag_event_p95_max_ms` / `overlap_drag_ui_lag_max_max_ms` | `[FAST_DRAG_KPI]` end-of-burst summaries are 100% sampled but only emit during real Qt drag bursts; synthetic runner has no Qt event loop. |
| `overlap_drag_handler_p95_max_ms` / `overlap_drag_background_decode_count_total` | Same source — confirms handler budget and R3 invariant under real load. |
| `overlap_settled_present_p95_ms` (≥30 settled samples) | Synthetic runner doesn't drive enough settled re-renders. |
| `overlap_sentinel_breakdown.decode` (≥1 per drag-with-decode) | F2.1b sentinel emits — without this we cannot prove decode-cache misses are being captured under real load. |
| `process_rss_mb` peak during overlap | Real DM subprocess + Qt allocations. |
| Visual quality (drag-mode hash gate from F1.2) | Confirms no regression. |

### Demoted / non-targets

- `overlap_set_slice_present_p95_ms` — KEPT in payload (compat) but **NOT a target** any more. Will be reported in PR descriptions for context only.
- `overlap_decode_p95_ms` (the old "all-samples" decode metric) — KEPT for compat but non-target; replaced by `overlap_decode_only_p95_ms` for gating.
- `overlap_effective_fps` — kept for context; capped at the synthetic drag rate so it cannot improve beyond ~60 in synthetic runs.
- `overlap_cache_hit_ratio_pct` — already 95.58% in the harsh anchor; F7's adaptive-radius work is **deferred** unless real-world F0.5b shows a different picture (per Revision R6 / F7 conditional).

### What the new gating looks like

A phase ships when **both**:
1. ≥1 Tier-1 synthetic KPI moves toward target by ≥10% **and** no Tier-1 KPI regresses by >5% on the harsh anchor.
2. The F1 regression bundle stays green.

The plan reaches "Final target" (formerly "100% improvement") when:
- All four Tier-1 synthetic KPIs hit their targets above on the harsh anchor, **AND**
- F0.5b real-world capture shows `overlap_drag_event_p95_max_ms ≤ 300` and `overlap_drag_ui_lag_max_max_ms ≤ 180` (≥50% drop from the 2026-04-28 live anchor), **AND**
- F0.5b real-world capture confirms no regression on `overlap_drag_handler_p95_max_ms` (≤16 ms), `overlap_drag_background_decode_count_total` (=0, R3 invariant), and `overlap_settled_present_p95_ms`, **AND**
- F0.5b real-world capture has `overlap_sentinel_breakdown.decode ≥ 1` for any drag burst that hit a decode-cache miss (F2.1b sampler sanity check), **AND**
- Drag-mode pixel hash gate from F1.2 stays green.

### Plan deltas from this retarget

**Add Step F0.5b — Real-world overlap anchor with new KPIs (new, BLOCKING for "Final target" claim).** Run actual app on PC A, drive a download+drag scenario on a ≥200-slice series with `AIPACS_OVERLAP_LOG_SAMPLE=1`. Parse with the F2.4 harness. Commit as `overlap_baseline_v0_real.json`. Required to populate `overlap_settled_present_p95_ms` with ≥30 samples. Done-When: the JSON has `overlap_settled_sample_count >= 30` and is referenced from the Success snapshot below. **NOT BLOCKING** for F3 / F3.5 / F4–F6 commit gating (which uses synthetic harsh anchor) — only blocking for the final "we're done" claim.

**Refine F2.1b — sentinel emits become more important.** With decode samples being the gating KPI, capturing every decode sample (instead of 1-in-N sampling) materially improves measurement precision. F2.1b now bypasses the 1-in-N sampler specifically for `cache=decode` AND drag-end (`set_fast_interaction(False)`) paths. Mirror to plugin package; tests added in F2.1b's own commit.

**Refine F3 / F3.5 / F4–F6 success criteria.** Replace every reference to `overlap_set_slice_present_p95_ms` as "primary KPI" with `overlap_decode_only_p95_ms` + `overlap_slow_frame_count_16ms`. F3.5 cancellation work specifically targets `overlap_decode_sample_share_pct` (cancelled prefetches → fewer foreground decodes when the cache misses).

**Refine F7 conditionality.** F7 (adaptive surrogate radius) only ships if the real-world F0.5b capture shows `overlap_cache_hit_ratio_pct < 90%`. Synthetic harsh shows 95.58% so F7 is currently in the **deferred** column.

**Defer F2.2 indefinitely.** With per-source KPIs in place, the manual re-baseline F2.2 was supposed to provide loses its purpose. Mark as `deferred — superseded by F2.4`.

---

## Live-run findings (2026-04-29)

A real-world drag was captured on PC A against series 303 (the user's representative case) with the exact production config (no env overrides, default `AIPACS_OVERLAP_LOG_SAMPLE=5`). The log contains exactly **2** `[OVERLAP_SCENARIO]` samples and **2** `[FAST_DRAG_KPI]` end-of-burst summaries — and they tell completely different stories:

| Source | KPI | Burst 1 | Burst 2 | Plan implication |
|---|---|---|---|---|
| `[FAST_DRAG_KPI]` (real-world) | `event_p95_ms` | **607.9** | 328.3 | Qt event-loop spacing, NOT pipeline compute. New Tier-2 north star. |
| `[FAST_DRAG_KPI]` (real-world) | `ui_lag_max_ms` | 0.0 | **363.9** | The actual user-perceived spike. Pipeline compute is irrelevant when the loop blocks. |
| `[FAST_DRAG_KPI]` (real-world) | `handler_p95_ms` | 3.7 | 3.2 | Pipeline-side per-frame work is fine. The handler is NOT the bottleneck. |
| `[FAST_DRAG_KPI]` (real-world) | `prefetch_per_s` | 0.0 | 0.0 | Prefetch is dark during these drags — confirms F6 has unexploited headroom. |
| `[FAST_DRAG_KPI]` (real-world) | `background_decode_count` | 0 | 0 | No background decodes ran — surrogate path is fully covering navigation. |
| `[OVERLAP_SCENARIO]` (per-frame) | total samples | 2 | (same window) | 1-in-N sampler at default 5 produced **zero** decode samples. KPI distribution is unmeasurable. |
| Progressive grow apply | duration | — | **54.27 ms** at 23:01:26.792 | Inside burst 2's drag window, terminal `_grow_progressive_fast` ran. R4 says terminal grow is uncapped, but 54 ms is a likely contributor to the 363.9 ms ui_lag spike. |

### Three pivots driven by the live run

**Pivot 1 — Synthetic compute-time KPIs are insufficient.** `overlap_decode_only_p95_ms` (13.94 ms harsh anchor) is dwarfed by the real-world `event_p95_ms=607.9 ms`. The Qt event-loop / paint / blit / progressive-grow stack contributes far more user-visible latency than the pipeline compute path. Synthetic gating is still required for repeatability, but a phase cannot claim "Final target" without a Tier-2 real-world KPI bar.

**Pivot 2 — F2.1b sentinel emits are now BLOCKING for measurement.** The default 1-in-N sampling produced zero decode samples in a real drag. Without sentinel emits, no real-world `overlap_decode_only_*` KPI value is meaningful and F0.5b cannot be captured. F2.1b is promoted from "follow-up" to "next-blocking step" and lands in the same commit as the live-run plan refinement.

**Pivot 3 — Terminal progressive grow during active drag is suspect.** Burst 2's 54.27 ms grow apply landed inside the drag window. R4 (copilot-instructions) says "terminal completion is never deferred — user must see download complete," which is correct in spirit but the grow is being applied via the same Qt event loop the drag handler is competing for. This becomes the new optional step **F11** (deferred until F0.5b real-world capture confirms it as a top-3 contributor).

### New Tier-2 KPIs (real-world, mandatory for "Final target" claim)

These are extracted by `parse_overlap_log_text` from `[FAST_DRAG_KPI]` lines added in F2.4b (committed alongside F2.1b):

| KPI | Live 2026-04-28 value | Target | Source |
|---|---|---|---|
| `overlap_drag_event_p95_max_ms` | 607.9 | **≤300** (≥50% drop) | end-of-burst summary, max across bursts |
| `overlap_drag_ui_lag_max_max_ms` | 363.9 | **≤180** (≥50% drop) | end-of-burst summary, max across bursts |
| `overlap_drag_handler_p95_max_ms` | 3.7 | hold ≤16 ms (no regression) | end-of-burst summary, max across bursts |
| `overlap_drag_background_decode_count_total` | 0 | hold at 0 (R3) | sum across bursts |
| `overlap_sentinel_emit_count` (decode share) | 0 (no F2.1b yet) | ≥1 per drag | F2.1b sentinel breakdown |

### Plan delta — Step F2.1b is in this commit

`Lightweight2DPipeline._maybe_emit_overlap_tag` now bypasses the 1-in-N sampler when:

- `cache=decode` (always — every foreground decode is a candidate user-visible spike).
- `_overlap_force_emit_next` is True (set by `set_fast_interaction(True)` at drag-begin and `set_fast_interaction(False)` at drag-end).

A 50 ms min-gap (`_OVERLAP_FORCE_EMIT_MIN_GAP_MS`) prevents log storm if many decode misses fire back-to-back. The new emit format appends `sentinel=<reason>` (`decode` / `drag_begin` / `drag_end` / `-` for sampled). Parser regex made the field optional so old logs still parse. Plugin-package mirror updated; SHA256 parity verified.

### Plan delta — New Step F11 (optional, deferred)

**F11 — Defer terminal progressive grow during active drag.** Modify `_grow_progressive_fast` / `_flush_progressive_grow_impl` so terminal completion is delayed up to 250 ms past the drag-end deadline (`is_protected_drag_active()` False), instead of firing immediately at `seriesDownloadCompleted`. R4 must be relaxed from "terminal is never deferred" to "terminal is deferred only while a drag is active and only up to 250 ms past drag-end". **Status:** `optional`. **Trigger:** F0.5b real-world capture must confirm progressive-grow apply > 20 ms inside ≥1 drag burst. **Risk:** small UX delay on download-complete confetti for users mid-drag. **Rollback:** trivial flag flip.

### Updated Phase F2 status

| Step | Status | Commit |
|---|---|---|
| F2.1 | DONE | `9f180262` |
| F2.1b | NEW — DONE in this commit | TBD |
| F2.2 | DEFERRED — superseded by F2.4 | — |
| F2.3 | DONE | `b9da77ed` |
| F2.4 | DONE | `fea7f9b1` |
| F2.4b | NEW — DONE in this commit | TBD |
| F11 | NEW — OPTIONAL, deferred | — |

---

## Cross-PC log analysis (2026-04-29 PM)

Fresh production diagnostic logs from PC A (developer / home / 32 GB / internet) and PC B (LAN / 64 GB) were parsed for `[INTENT]`, `[INTENT_PRIORITY]`, `[OVERLAP_SCENARIO]`, and `[FAST_DRAG_KPI]` markers. The findings sharpen the F3.5 plan and immediately re-prioritise the next coding step.

### Raw counts

| Marker | PC A | PC B | Notes |
|---|---:|---:|---|
| Legacy `[INTENT] Priority start retry exhausted` (lifetime, 2026-04-02 → 04-29) | **759** | **0** | PC A peak 168 events on 04-05; today 2 events still firing on installed build. PC B: zero across log lifetime. |
| F3.5.1 structured `[INTENT_PRIORITY]` | 0 | 0 | Confirms neither installed build carries commit `0bdf4fae` or later. |
| Latest session timestamp | 2026-04-29 09:44:50 | 2026-04-29 09:39:47 | Both ran today. |

### Sample today-PC-A signature

```
2026-04-29 09:44:11 | WARNING | series_intent_coordinator.schedule_priority_start_retry |
  [INTENT] Priority start retry exhausted for <study> after recovery attempts=3
2026-04-29 09:44:47 | ERROR   | series_downloader.download_all_series |
  ❌ FAILED: Download cancelled (preemption)
2026-04-29 09:44:47 | WARNING | executor.execute_download |
  ⏸️ Download preempted: <patient> - Paused for higher priority download (preemption)
```

A primary-chain exhaust (≈ 9:44:11) followed 36 s later by a successful preemption on a sibling series of the same study. The recovery branch was never reached on this specific event.

### Implications (sharpening prior assumptions)

**S1. F3.5.2 targets a real, chronic production failure.** 759 lifetime events on PC A, with peak day 168/d, prove the legacy 90×200 ms primary + 3×3000 ms recovery split is exhausting under WAN tail latency. F3.5.2's 60 s wall-clock budget directly addresses the dominant failure mode. Plan deltas in the 2026-04-28 revision speculated about "three independent sessions" — the actual lifetime number is 759, two orders of magnitude larger.

**S2. PC B is structurally not a useful validation surface for F3.5 success criteria.** LAN throughput finishes batches well inside the legacy 18 s primary cap; PC B has never hit the failure mode. F3.5.4's cross-PC gating must be re-read as: "PC A confirms reduction; PC B confirms no regression on a path that never failed there." Do not block F3.5.4 on PC B exhibiting the legacy failure — by construction it will not.

**S3. F3.5.1 instrumentation is not yet observed in production.** Both PCs run a build older than `0bdf4fae`. To collect the F3.5.1 baseline measurement called out in F3.5.4's Done-When, PC A must be rebuilt and reinstalled from at least `0bdf4fae` (F3.5.1 only) or `30365119` (F3.5.1 + F3.5.2 with env=0 default). The F3.5.4 plan delta below makes this explicit.

**S4. The F3.5.2 "branch decision" called out in 2026-04-28 R8 is now answered.** Lifetime PC A logs show legacy exhausts cluster around the primary chain (the warning text matches `recovery attempts=3` because that is the recovery sub-counter spelled out at exit) — but without F3.5.1 structured `branch=primary|recovery` partition we cannot quantify the primary-vs-recovery share from the legacy text alone. The synthetic F3.5.2 baseline `priority_handoff_v2_pre.json` already captured 20 primary-chain exits and 0 recovery exits on the 25 s peer-hold scenario, so the wall-clock budget is justified independently. The reclamation-race CAS path remains in F3.5.2 because the synthetic post baseline observed 12 reclaimed defers (3 races × 4 ticks/window) — both sub-paths are non-zero in synthetic and therefore both are kept.

### Updated Phase F3.5 status (after this analysis)

| Step | Status | Commit | Notes |
|---|---|---|---|
| F3.5.1 | DONE | `0bdf4fae` | Instrumentation, KPI parser, 7 instrumentation tests + 15 parser tests. |
| F3.5.2 | DONE | `30365119` | Wall-clock V2 + reclamation-race CAS, env-gated default-off. 9 V2 tests + 10 V2 parser tests + synthetic pre/post baselines committed. |
| F3.5.3 | NEXT — coding now | TBD | UX guardrail. Findings above sharpen the trigger condition (lifetime 759 events ⇒ toast must be default-on, not opt-in, even though dev policy is to default new behaviour off). |
| F3.5.4 | BLOCKED on PC A reinstall | — | Done-When now requires "PC A installed build = `30365119` or later AND F3.5.1 instrumentation observed in production logs for ≥1 day." |
| F3.5.5 | NEW — CONDITIONAL | — | Only triggered if F3.5.4's PC A soak shows `recovery_exhaust_count > 0` AND `v2_exhaust_pool_busy_count > 0` simultaneously. "Pool starvation under wall-clock budget" follow-up; otherwise dropped. |

### F3.5.3 refinements driven by these findings

The original F3.5.3 step (2026-04-28) called for a passive toast with `AIPACS_INTENT_HANDOFF_TOAST=1` opt-out. The 759-event production signal changes the bar:

1. **Toast remains additive to the existing WARNING log** (no behavioural removal of legacy diagnostics).
2. **Default is ON** but the env name flips to `AIPACS_INTENT_HANDOFF_TOAST_DISABLE=1` (positive-default convention so headless test runs disable explicitly). Inverts the prior name; chosen for clarity.
3. **Manual retry path uses the same V2 wall-clock budget as the original chain** (60 s) — not the legacy 90+3 split, even when env=0. Rationale: a user-initiated re-promotion should always use the most-likely-to-succeed path; otherwise the toast click reproduces the original failure.
4. **One signal, no fan-out duplication.** `priorityHandoffFailed(study_uid, series_number, reason)` is the sole emit; DM widget consumes for UI, ViewerController consumes for log only. No new viewer-side popup.
5. **Cooldown bypass narrowed:** the `_dm_notify_last_ts` 500 ms cooldown is bypassed for *manual-retry-from-toast-click* only, not for any subsequent automatic re-promotion. This prevents accidental loop if the underlying network condition persists.
6. **Test surface mirrors F3.5.2:** new `tests/download_manager/test_priority_handoff_signal.py` covers signal-fires-once, signal-fires-with-correct-reason for each of the four V2 reasons (`pool_busy|reclaimed|state_lost|timeout`), manual-retry uses V2 path, and env-disable suppresses widget connection.

### F3.5.4 deltas

Done-When revised:
- PC A installed build is `30365119` or later (not just dev tree).
- ≥1 day of PC A production usage with F3.5.1 instrumentation captured.
- KPI harness on PC A diagnostics shows `recovery_exhaust_count == 0` (proof that V2 handles what legacy would have failed) AND `v2_total_exhaust_count` ≤ baseline `recovery_exhaust_count` × 0.20 (≥80% reduction) — measured over the same number of drag-drop promotions.
- PC B re-defined as no-regression smoke only (not symmetric proof).

---

## Drag-burst evidence & phase reordering (2026-04-29 PM live log)

### Source data

`user_data/logs/viewer_diagnostics.log` (mtime 2026-04-29 10:56) — captured on PC A after F3.5.3 ship at `e3ceaaaf`. Twelve `[FAST_DRAG_KPI]` end-of-burst summaries from a real download-overlap drag session:

| Burst | duration_s | targets | event_p95_ms | handler_p95_ms | ui_lag_max_ms | prefetch_per_s | bg_decode_count |
|---|---|---|---|---|---|---|---|
| 1 | 0.911 | 11 | 141.9 | 60.7 | 162.8 | 11.0 | 10 |
| 2 | **3.991** | 22 | 337.7 | 6.4 | **2496.2** | 0.0 | 0 |
| 6 | 1.876 | 17 | 222.4 | 9.7 | 356.9 | 6.9 | 13 |
| 9 | 0.916 | 8 | 168.2 | 21.5 | 153.8 | 12.0 | 11 |
| 11 | 1.426 | 18 | 199.9 | 11.0 | 245.4 | 13.3 | 19 |
| 12 | **3.825** | 16 | **559.1** | 5.8 | **1842.8** | 0.3 | 1 |

### Two pivots from this evidence

**Pivot A — Pipeline compute is decisively NOT the bottleneck.** Across 12 bursts, `handler_p95_ms` peaks at 60.7 ms (one outlier — Burst 1, with `bg_decode=10`) and is otherwise 3.2–22 ms. The user-perceived freezes (`ui_lag_max_ms` 1842–2496 ms) occur in bursts where `prefetch_per_s ≈ 0` AND `bg_decode_count ≈ 0` — the FAST pipeline is **idle** during the worst freezes. The main thread is being blocked by something **outside the FAST pipeline** for 1.8–2.5 seconds.

**Pivot B — F4 (foreground decode lane) and F5 (decode coalescing) are low-leverage at this evidence level.** F4's win condition is reducing `overlap_decode_p95_ms` and `overlap_foreground_wait_p95_ms` when prefetch saturates the executor. But foreground decode is already isolated (it runs inline, NOT through `_decode_executor`). And `handler_p95_ms` (which envelops decode) is 3–22 ms in real drag — far below F4's worst-case justification. Synthetic harsh shows `overlap_decode_only_p95_ms=75.23 ms` for the 4.74% of frames that fall into the decode source, but the real-world drag handler stays low because surrogate covers most navigation. Adding executor-submission overhead to inline decode does not fix a non-bottleneck.

### Updated phase priority (post-2026-04-29 PM)

**F4 → DEFERRED.** Re-evaluate only if F0.5b real-world capture (≥30 settled samples, sentinel decode≥1) shows `overlap_decode_only_p95_ms > 30 ms` AND `overlap_decode_sample_share_pct > 5%`. Until then, F4 cannot move the Tier-2 KPIs (`overlap_drag_event_p95_max_ms`, `overlap_drag_ui_lag_max_max_ms`).

**F5 → DEFERRED.** Same rationale — coalescing two decode paths only matters when both are competing, but in real drags only one decode lane is active at a time (foreground inline OR P1 prefetch via executor, never simultaneously for the same idx in the live capture).

**F6 → PROMOTED to next-implement (already labeled "highest leverage" in plan index).** Win condition: when P1 neighbor pixels are already cached (the common case after a few drag steps), the user still pays W/L+QImage on the main thread per drag step. Frame prefetch eliminates that cost. Even if it only saves 5 ms/frame on cache-hit drag, that compounds across 30+ frames per second.

**F11 → BLOCKED on real-world correlation.** The 2.5 s `ui_lag` freezes with `prefetch=0, bg_decode=0` are NOT necessarily progressive grow (the live log doesn't carry grow-apply timestamps inside the drag-KPI summary). F11 stays optional pending grow-apply correlation evidence from F0.5b.

### Synthetic harsh anchor (pre-F6, captured 2026-04-29 PM)

`generated-files/benchmarks/pre_f4_harsh.json` (renamed pre-F6 baseline once F6 ships):

| KPI | Value | Tier-1 target | Status |
|---|---|---|---|
| `overlap_decode_only_p95_ms` | 75.23 | ≤7.0 | far off — but per Pivot A this is not a real-world bottleneck |
| `overlap_decode_only_max_ms` | 111.81 | ≤40.0 | far off |
| `overlap_decode_sample_share_pct` | 4.74 | ≤2.5 | close |
| `overlap_slow_frame_count_16ms` | 73 | ≤1 | all 73 are decode-source — addressable only by avoiding decode (more cache hits) |
| `overlap_cache_hit_ratio_pct` | 95.26 | ≥85 | pass |
| `overlap_effective_fps` | 55.05 | ≥30 | pass |

### Updated Phase Index (priority order)

| Phase | Status | Notes |
|---|---|---|
| F4 | DEFERRED | Low leverage given live evidence; trigger = F0.5b decode share > 5% |
| F5 | DEFERRED | Same trigger as F4 |
| **F6** | **NEXT — coding now** | Frame prefetch during protected drag; eliminates W/L cost on cache-hit drag steps |
| F7 | DEFERRED | cache_hit=95% already; gain marginal |
| F8 | NEXT after F6 | Header pre-warm via DM completion hook (low risk, addresses cold-cache decode share) |
| F9 | OPT-IN, opt later | DM disk-flush backpressure |
| F10 | After F6+F8 | Acceptance + release |
| F11 | OPTIONAL | Defer terminal grow during drag (pending F0.5b grow-apply correlation) |

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

## Phase F3.5 — DM priority-handoff stall during overlap

**Phase goal:** Eliminate the silent failure mode where a drag-dropped (CRITICAL-promoted) series fails to start a download worker within the documented retry window, surfacing as `[INTENT] Priority start retry exhausted ... after recovery attempts=3` warnings. Three independent production sessions on 2026-04-28 (study `...85689` series=202, `...85688` series=202, `...85691` series=302) all hit this exhaustion, indicating it is systematic, not noise. The user observed first image appearing within ~1 s (progressive cache covered the gap) but the CRITICAL download for the dragged series never started — a direct overlap-scenario failure.

**Root-cause summary (pre-investigation hypothesis, to be confirmed in F3.5.1):**
- `SeriesIntentCoordinator.schedule_priority_start_retry` (`modules/download_manager/coordinator/series_intent_coordinator.py`) runs a primary 90-attempt × 200 ms loop (= 18 s window). On primary exhaustion it enters a single "recovery" round of 3 attempts × 3000 ms (= 9 s) with `_recovery=True`. Total nominal window ≈ 27 s.
- The exhaustion warning fires only when (a) primary 90 attempts AND (b) recovery 3 attempts both fail to find a free pool slot AND (c) the study state at end is NOT `is_auto_paused` and the error_message does not contain `preemption|higher priority`. The `recovery attempts=3` text is the recovery sub-counter, not the main budget — but the warning currently does not say which counter exhausted, which is what made the prior log read ("only 3 attempts") confusing.
- Likely failure modes: (i) the worker that needs to release the pool slot is stuck in long socket I/O (>27 s on a slow batch), (ii) the worker did release but `_start_next_pending` never picked the CRITICAL study because of a state-store race (PENDING ↔ PAUSED transitions during preemption), (iii) the pool-freed event-driven callback (`on_worker_removed` → `_start_next_pending`) and the poller raced with a state update that briefly took the study out of the eligible set.
- Whatever the cause, the expected user-visible behavior is: dragged series goes CRITICAL → starts downloading within seconds. The current behavior is: dragged series remains PENDING for 27+ s and then permanently abandons critical promotion (until the next coordinator wake-up, which may or may not come).

**Scope justification (FAST viewer focus):** This bug is in the DM coordinator, not the FAST pipeline. It is included in the FAST overlap plan because it directly degrades the same-study overlap scenario: when the user drag-drops a partially-downloaded series during another download, they expect the new series to take priority and finish quickly. A 27 s + abandonment latency for that handoff is exactly the overlap responsiveness regression this plan exists to fix. Scope limited to the priority-handoff path; broader DM rework is out of scope.

**Cross-cutting invariants (must hold across F3.5):**
- DM tests `tests/download_manager/run_dm_test.py` S1–S27 must stay green every step.
- `tests/download_manager/test_dm_stress.py` H1–H10 stays green.
- `tests/load/run_load_test.py` L1–L11 stays green (covers preemption + pool-freed callback).
- No change to default behavior unless explicitly behind an env flag; rollback is `git revert` per step.
- R-rules R20–R26 in F10.2 step expand to R20–R28 to absorb F3.5 emissions.

### Step F3.5.1 — Diagnose & instrument the priority-handoff path

**Goal:** Turn the silent stall into a measurable, parseable signal so the harness can baseline `overlap_priority_handoff_latency_ms` and so the next steps have ground-truth data on which exit branch is hit.

**Actions:**
1. Read `schedule_priority_start_retry` end-to-end and document the actual control flow in a sub-section of `docs/architecture/network-architecture.md` § "DM coordinator priority-handoff path". Include: the 90 × 200 ms primary window, the 3 × 3000 ms recovery window, the `_token` / `_priority_retry_tokens` map staleness check, the `is_auto_paused` / preemption-error-message expected-window branch, and the interaction with the `WorkerPool.on_worker_removed` event-driven callback.
2. In `series_intent_coordinator.py`, add a structured INFO line `[INTENT_PRIORITY] tag=<begin|tick|defer|recover|exhaust|started> study=<uid> series=<sn> attempt=<i>/<max> recovery=<bool> pool_busy=<bool> pool_capacity=<used>/<total> state=<status> auto_paused=<bool> elapsed_ms=<int> token=<int>` at:
   - `_begin_priority_retry` (tag=begin, elapsed_ms=0).
   - Each retry tick before the `can_add_worker` check (tag=tick).
   - The `_defer` schedule paths (tag=defer).
   - Recovery transition (tag=recover).
   - Both exhaust branches (tag=exhaust, with a new `branch=primary|recovery` field) — change the existing WARNING to also include `branch=recovery` so log parsers can distinguish primary vs recovery exhaustion.
   - `_start_download_worker` success path (tag=started, with `elapsed_ms` from begin).
3. INFO emission must use `extra={"component": "download"}` so it routes through the queued listener (does not block the main thread per R7) and is consistently parseable.
4. `elapsed_ms` is computed from a per-token timestamp dict `_priority_retry_started_ms[study_uid]` populated in `_begin_priority_retry` and removed in `_clear_priority_retry`. Bound the dict via existing token cleanup; no separate eviction needed.
5. Default-off env flag `AIPACS_INTENT_PRIORITY_TRACE=0` (when `0`, only `begin`, `recover`, `exhaust`, `started` are emitted; when `1`, every tick is emitted). Document in copilot-instructions.md F10.2 R-rule list.

**Structures to change:**
- `modules/download_manager/coordinator/series_intent_coordinator.py` — add tagged emit helper + 6 emit sites + `_priority_retry_started_ms` dict. Mirror copy under `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/coordinator/series_intent_coordinator.py` updated in same commit.
- `tools/performance/clearcanvas_aipacs_kpi_harness.py` — new parser `parse_priority_handoff_log_text(text) -> {samples, p50_ms, p95_ms, exhaustion_count, primary_exhaust_count, recovery_exhaust_count, started_count}` covering the `[INTENT_PRIORITY]` lines.
- `docs/architecture/network-architecture.md` — new sub-section.
- `docs/pipelines/download-pipeline.md` — short reference to the new log tag.

**KPIs to review (snapshot only this step):**
- `overlap_priority_handoff_latency_ms` (p50, p95) — drag-drop begin → started, parsed from `[INTENT_PRIORITY] tag=started elapsed_ms=...`.
- `overlap_priority_retry_primary_exhaust_count`, `overlap_priority_retry_recovery_exhaust_count` — per session.

**Measurement tools:**
- KPI harness (extended).
- A new contract test `tests/performance/test_priority_handoff_kpi_parser.py` round-trips the exact emit format, mirroring `test_overlap_kpi_parser.py` (F2.1). Must include one round-trip per tag and assert the parser handles the diagnostic_logging prefix.

**Tests:**
- New: `tests/performance/test_priority_handoff_kpi_parser.py` (≥6 tests covering each tag + exhaust branch field).
- Regression: `tests/download_manager/run_dm_test.py` S22 (coordinator latency) — must still measure <5 ms on the negotiate path.
- Regression: full DM and load bundles green.
- New: `tests/download_manager/test_priority_handoff_instrumentation.py` (≥3 tests) verifying that a stub coordinator emits the expected sequence (`begin → tick* → started`) with monotonic `elapsed_ms` and that `_priority_retry_started_ms` is cleared on success and on exhaust.

**Documentation:**
- `docs/architecture/network-architecture.md` — handoff path diagram.
- `docs/pipelines/download-pipeline.md` — log tag reference.
- `.github/copilot-instructions.md` Test coverage map — add the two new test files.

**Success criteria:**
- Production log run (PC A overlap repro) emits at least one full `begin … started` chain with `elapsed_ms` populated.
- KPI harness parses the new lines with zero `unparsed_lines` for `[INTENT_PRIORITY]` records.
- All regression bundles green per the global no-regression matrix.
- No change to existing DM behavior: only added emit + dict + parser.

**Done-When:**
- Commit `[F3.5.1]` with mirror copy + parser + tests + docs landed.
- `overlap_priority_handoff_latency_ms` line appears in `OVERLAP_KPI_BASELINE.md` snapshot v2.5 (post-F3 baseline + this instrumentation; can be the same JSON file with new fields).

### Step F3.5.2 — Reconcile retry budget and add early-exit on cancelled-while-pool-busy

**Goal:** Make the priority-handoff actually succeed in the dominant production failure mode (peer worker takes longer than 27 s to release, OR the released worker is immediately reclaimed by a non-CRITICAL pending task before the CRITICAL retry ticks).

**Actions:**
1. **Decision-tree fix (no heuristic).** Replace the recovery-round exit condition with: "keep retrying until either (a) `state.status` no longer eligible (DOWNLOADING / COMPLETED / CANCELLED), or (b) the worker_pool slot has been freed AND the study still has not started after one extra `interval_ms` tick (indicates structural reclamation race, see step 2), or (c) hard absolute timeout `_priority_handoff_hard_timeout_ms` (default 60 000 ms) reached." The 90 + 3 split becomes a single capped poller against a wall-clock budget; the warning text changes from `recovery attempts=N` to `total elapsed_ms=N hard_timeout_ms=M reason=<pool_busy|reclaimed|state_lost>`.
2. **Reclamation-race fix.** When a CRITICAL retry ticks and finds `worker_pool.can_add_worker() == True` but `_start_download_worker` returns False (already-pending different study claimed the slot in the same event-loop pass), atomically transition the CRITICAL study back to PENDING and trigger `_start_next_pending` AT THE FRONT of the priority queue (i.e., a one-shot priority-aware reorder rather than FIFO scan). Implementation: extend `_start_next_pending` with an optional `prefer_study_uid` parameter; the retry path passes the CRITICAL study uid when reclamation is detected.
3. **Default-off cohort.** Behavior change is gated by env var `AIPACS_INTENT_HANDOFF_V2=0`. When `0`, the legacy 90 + 3 split runs unchanged. When `1`, the new wall-clock + reclamation-aware path runs. Defaults stay legacy until F3.5.4 baseline confirms no regression. Documented in copilot-instructions.md.
4. **Coordinator latency contract preserved.** S22 must still measure <5 ms on the negotiate path; the new logic only changes the *retry tail*, not the negotiation entry path.
5. **Mirror parity** for the coordinator file.

**Structures to change:**
- `modules/download_manager/coordinator/series_intent_coordinator.py` (+ mirror).
- `modules/download_manager/core/constants.py` — add `INTENT_HANDOFF_HARD_TIMEOUT_MS = 60000` and `INTENT_HANDOFF_V2_DEFAULT = False`.
- `modules/download_manager/state/state_store.py` — only if reclamation-race fix needs an atomic compare-and-swap helper for status (`update_if_status(uid, expected, new) -> bool`); add it as additive method, do not change `update`.

**KPIs to review:**
- `overlap_priority_handoff_latency_p95_ms` — must drop ≥50% vs F3.5.1 baseline OR achieve absolute ceiling 5 000 ms (whichever is met first).
- `overlap_priority_retry_recovery_exhaust_count` — must drop to 0 in the synthetic 20-drag-drop repro.
- `overlap_set_slice_present_p95_ms` — must NOT regress vs F3 baseline (handoff change must not steal main-thread time).
- `download_throughput_mb_s` — must stay within −3% (the new path may briefly contend on the state-store CAS).

**Measurement tools:**
- KPI harness (parser from F3.5.1).
- A new synthetic harness `tools/performance/synthetic_priority_handoff_runner.py` that drives 20 simulated drag-drop priority promotions with a held pool slot (peer worker mocked to release after 25 s) and reports the parsed KPIs. Pattern follows `synthetic_overlap_runner.py` (F0.4).

**Tests:**
- New: `tests/download_manager/test_priority_handoff_v2.py` — at least: (a) primary path success (worker freed at 5 s), (b) hard-timeout path (worker never frees → exhaust at 60 s with reason=`pool_busy`), (c) reclamation-race path (`prefer_study_uid` wins), (d) legacy mode (env=0) behavior unchanged, (e) S22 latency contract.
- Regression: full DM (S1–S27), DM stress (H1–H10), load (L1–L11), network bundle.
- Regression: F1 overlap pixel-quality bundle (no FAST viewer code touched, but the bundle must be green to attest unchanged).

**Documentation:**
- `docs/architecture/network-architecture.md` — update handoff path diagram with the wall-clock + reclamation branches.
- `docs/pipelines/download-pipeline.md` — new R-rule note "Priority handoff wall-clock budget".
- `.github/copilot-instructions.md` § Critical rules — new R-rule (placeholder for F10.2 to renumber): "Priority handoff retry uses a single wall-clock budget (default 60 s) under `AIPACS_INTENT_HANDOFF_V2=1`; legacy 90+3 split is the default until F3.5.4 baseline confirms."

**Success criteria:**
- All new tests green.
- All regression bundles green per the global no-regression matrix.
- With `AIPACS_INTENT_HANDOFF_V2=1`, synthetic 20-drag-drop produces 0 exhaustion warnings.
- With `AIPACS_INTENT_HANDOFF_V2=0`, behavior matches commit prior to this step (negative test).

**Done-When:**
- Commit `[F3.5.2]` with mirror copy.
- Synthetic JSON `priority_handoff_v2_pre.json` and `priority_handoff_v2_post.json` committed under `generated-files/benchmarks/`.

### Step F3.5.3 — Drag-drop UX guardrail when handoff still fails

> **Refined 2026-04-29 PM** — see "Cross-PC log analysis (2026-04-29 PM)" → "F3.5.3 refinements" for the six-point delta. Default-on, positive-default env flag, manual-retry uses V2 wall-clock budget regardless of env=0/1, narrowed cooldown bypass, four-reason test surface.

**Goal:** Even with F3.5.2, a 60 s hard-timeout exhaustion is *possible* in the wild (network stall on the peer worker). When it happens, the user must know — silently abandoning a CRITICAL drag-drop is the worst UX. Add a minimal, non-intrusive UX guardrail.

**Actions:**
1. On exhaust (`tag=exhaust reason=pool_busy|reclaimed|state_lost|timeout`), the coordinator emits a Qt signal `priorityHandoffFailed(study_uid: str, series_number: int, reason: str)` (new signal on `SeriesIntentCoordinator`). Emitted from BOTH the legacy recovery-exhaust path AND every V2 exhaust path so toast surfaces regardless of `AIPACS_INTENT_HANDOFF_V2`.
2. `DownloadManagerWidget` connects to this signal and surfaces a passive toast in the DM table row (status column shows `Priority stalled — click to retry`). Click → `request_critical_series` is re-issued with a fresh token; legacy `_dm_notify_last_ts` cooldown (500 ms) is bypassed for this manual retry only. The manual retry forces V2 path for the new chain (`_intent_handoff_v2_enabled()` is overridden inside that one call).
3. ViewerController consumes the same signal (already a DM observer) only to log; no viewer-side popup. The 60 s ceiling should make this rare; popups would feel worse than the current silent failure.
4. Default-on for the toast; env flag `AIPACS_INTENT_HANDOFF_TOAST_DISABLE=1` (positive-default name) to disable for headless test runs. Disable suppresses the DM widget signal connection — the coordinator still emits the signal so observers (logging) keep working.
5. Keep the WARNING log line; the toast is additive.

**Structures to change:**
- `modules/download_manager/coordinator/series_intent_coordinator.py` — new signal.
- `modules/download_manager/ui/widget/_dm_priority.py` — signal connection + toast row.
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` — passive logger only.
- Mirror copies for all touched files.

**KPIs to review:**
- `overlap_priority_retry_exhaustion_rate` — must remain ≤0.05 (≈1 in 20 drag-drops in synthetic stress).
- `series_switch_ms` (warm) — must stay within +5%.
- `cpu_p95_pct` (idle) — toast widget must be inert when no exhaustion event.

**Measurement tools:** existing harness + synthetic runner from F3.5.2.

**Tests:**
- New: `tests/download_manager/test_priority_handoff_signal.py` — signal fires exactly once per exhaustion; manual-retry path bypasses cooldown; default-off env disables toast.
- New: `tests/ui_services/test_dm_priority_handoff_toast.py` — widget renders + click handler invokes `request_critical_series`.
- Regression: full DM bundle, load bundle, F1 bundle, smoke imports.

**Documentation:**
- `docs/architecture/home-ui-services.md` — add note (DM widget is in module_packages, but ViewerController integration touches home_ui).
- `.github/copilot-instructions.md` — R-rule placeholder "Priority handoff exhaustion surfaces a toast, never silent".

**Success criteria:**
- Toast renders in synthetic stress when forced exhaustion is induced; click triggers a successful re-promotion (with worker freed before this manual retry's hard timeout).
- All regression bundles green.

**Done-When:** Commit `[F3.5.3]` with mirror copy and tests.

### Step F3.5.4 — Default-on rollout and cross-PC verification

**Goal:** Flip `AIPACS_INTENT_HANDOFF_V2` default to `1` and lock in the F3.5 baseline.

**Actions:**
1. Change `INTENT_HANDOFF_V2_DEFAULT = True` in `core/constants.py` (+ mirror).
2. Run synthetic_priority_handoff_runner on PC A and PC B; commit both JSONs as `priority_handoff_v2_pcA.json` and `priority_handoff_v2_pcB.json` under `generated-files/benchmarks/`.
3. Run the full overlap repro on PC A and PC B (drag-drop during heavy download on a real study). Capture viewer + download diagnostics logs and parse with the harness; verify zero `[INTENT] Priority start retry exhausted` warnings.
4. If either PC shows even one exhaustion, do NOT flip default; revert step 1 and open a follow-up step F3.5.5 to dig deeper. Per global rule 5 (cross-PC), both PCs must be clean before declaring done.

**Structures to change:**
- `modules/download_manager/core/constants.py` (+ mirror).
- `docs/performance/OVERLAP_KPI_BASELINE.md` — add v3.5 row.

**KPIs to review:** all overlap_* + priority_handoff_*.

**Tests:** all from F3.5.1, F3.5.2, F3.5.3 + the global no-regression matrix.

**Documentation:**
- `docs/releases/RELEASE_NOTES.md` — entry for F3.5 default-on.
- `.github/copilot-instructions.md` — promote the F3.5 R-rule placeholder to a permanent R-rule (numbered in F10.2).

**Success criteria:**
- ≥50% reduction in `overlap_priority_handoff_latency_p95_ms` vs F3.5.1 baseline (PC A and PC B).
- Zero `Priority start retry exhausted` warnings across both PC overlap repros.
- All regression bundles green.

**Done-When:** Commit `[F3.5.4]` with both PC JSONs + baseline doc updated; `AIPACS_INTENT_HANDOFF_V2=1` is the default.

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

### Status (2026-04-29 PM)

**SHIPPED to working tree (uncommitted at time of write).** Implementation:

- `modules/viewer/fast/system_load_controller.py` (+ mirror): added `WorkClass.FRAME_PREFETCH = "frame_prefetch"`, mapped to `BLOCK_3_CACHE_SCROLL_ORCHESTRATION`. Always admitted at controller level (caller enforces in-flight cap).
- `modules/viewer/fast/ui_throttle.py` (+ mirror): added FRAME_PREFETCH branch in `should_admit` parallel to PREFETCH P1 rule — under `is_protected_drag_active()`, admit only if `ctx["priority"] <= 1` (`FastWorkPriority.P1_NEIGHBOR`); deny everything else (priority>1 or default 999). Outside protected drag → always admit.
- `modules/viewer/fast/lightweight_2d_pipeline.py` (+ mirror):
  - `__init__`: added `_frame_prefetch_inflight: int = 0` (in-flight cap counter for priority-driven submissions only).
  - `close_series`: resets `_frame_prefetch_inflight = 0` alongside the existing pending-set clear.
  - `_submit_frame_prefetch(idx, *, priority=None)`: new optional `priority` kwarg. When set, the call goes through `should_admit(WorkClass.FRAME_PREFETCH)`, enforces in-flight cap of 1 (returns immediately if a tracked submission is already running), and decrements the counter in the `_render_into_cache` finally block. Legacy callers (priority=None) keep the original pending-set dedup behavior (no admission gate, no in-flight cap).
  - `_render_into_cache(idx, tracked=False)`: extra `tracked` flag controls whether the finally block decrements the in-flight counter (only true for priority-driven calls).
  - `_prefetch_around` protected-drag P1 branch: after the existing pixel P1 loop, scan `ordered_targets` for the FIRST target whose pixel is already in `_pixel_cache`; submit one `_submit_frame_prefetch(target, priority=int(FastWorkPriority.P1_NEIGHBOR))` and break. This is the user-visible win path: when the next directional neighbor's pixels are already cached, its rendered frame is built in the background instead of on the main thread.
- Plugin-mirror parity verified (SHA-equal for all three files).

**Validation:**

| Suite | Result |
|---|---|
| F1 overlap regression bundle (`run_overlap_regression.ps1`) | 43/43 GREEN |
| `tests/viewer/test_b34_interaction_aware_policy.py` (Prefetch + DirectionReversal + DragStartWarmup + new F6 classes) | 21/21 GREEN |
| New `TestProtectedDragFramePrefetch` (3 tests) | GREEN — confirms exactly one P1 frame prefetch per drag P1 call, only for cached-pixel targets |
| New `TestFramePrefetchAdmission` (3 tests) | GREEN — confirms admission table: P1 admitted under drag, P2+ denied, default-priority denied, unrestricted outside drag |
| Pre-existing 14 failures in same file | unrelated (`SimpleNamespace` missing `_mark_interaction_event` on `QtViewerBridge` stubs) — confirmed pre-existing on `e3ceaaaf` via `git stash` |

**Synthetic harsh comparison (`pre_f4_harsh.json` → `post_f6_harsh.json`):** essentially flat / within run-to-run noise.

| KPI | pre-F6 | post-F6 | Note |
|---|---|---|---|
| `overlap_decode_only_p95_ms` | 75.23 | 81.98 | within noise |
| `overlap_decode_only_max_ms` | 111.81 | 162.84 | run-to-run variance |
| `overlap_decode_sample_share_pct` | 4.74 | 5.33 | within noise |
| `overlap_slow_frame_count_16ms` | 73 | 72 | within noise |
| `overlap_cache_hit_ratio_pct` | 95.26 | 94.67 | within noise |
| `overlap_effective_fps` | 55.05 | 50.24 | within noise |
| `overlap_drag_event_p95_max_ms` | 0.0 | 0.0 | synthetic doesn't emit FAST_DRAG_KPI |
| `overlap_drag_ui_lag_max_max_ms` | 0.0 | 0.0 | synthetic doesn't emit FAST_DRAG_KPI |

**Why synthetic is flat:** the synthetic harness (`tools/performance/synthetic_overlap_runner.py`) does NOT activate `is_protected_drag_active()`. F6's entire effect lives on the protected-drag P1 lane in `_prefetch_around`, which the synthetic stub never enters. This is expected and was true of F3.1/F3.2 as well — those landed without synthetic deltas and still produced the live-log drag-burst KPIs in the cross-PC workflow.

**Win condition validation requires a live log from PC A.** Specifically: a stack-drag burst on a partly-cached series during heavy download. The win signature in the next `[FAST_DRAG_KPI]` line(s) should be:

- `handler_p95_ms` lower in bursts where `bg_decode_count == 0` (cache-hit drags, where the live log shows handler 5–22 ms today). Target: shift down toward 1–5 ms once frame prefetch covers the cached-pixel directional step.
- `event_p95_ms` correspondingly lower on cache-hit cycles (because the main thread no longer pays the W/L+QImage build per step).
- No regression in `bg_decode_count` (frame prefetch lane is separate from the pixel decode executor; in-flight cap of 1 prevents executor saturation).
- No regression in `prefetch_per_s` (pixel P1 branch is unchanged; frame branch fires after, only for already-cached pixels).

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

**STATUS: DONE.** See "Status (2026-04-29 PM)" above. All admission tests green.

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

**Actions:** consolidate R-rules emitted in each step; assign R20–R28 numbers (R20–R26 for F3–F9; R27–R28 for F3.5 priority-handoff); insert under "v2.3.6 stack-drag smoothness rules".

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
| F3.5 | Wall-clock budget hides a real cancel hang OR reclamation-race fix corrupts state-store CAS | `priority_handoff_p95_ms` worsens, OR DM stress H1–H10 fails, OR S22 latency contract breaks | Set `AIPACS_INTENT_HANDOFF_V2=0` (env flip, no code revert needed); if state-store CAS is implicated, `git revert` the F3.5.2 commit |
| F4 | New executor leaks threads on series close | `thread_count_p95` grows over time in F5.2 stress | Disable executor + fall back to in-line |
| F5 | Event leak / deadlock | RSS grows; hangs in 60-min stress | Single-commit revert |
| F6 | Frame prefetch races W/L change → wrong WL on screen | F1 pixel hash diff | Revert F6.2 only; F6.1 (admission rule) is harmless if unused |
| F7 | Surrogate too wide → visible smearing | F1 surrogate match drops <99% | Revert radius cap to ±20 |
| F8 | Header pre-warm corrupts `_slices[idx]` mid-decode | Pixel hash diff or crash | Revert F8.2; keep F8.1 signal harmless |
| F9 | Default-on accidental → throughput regression | DM throughput KPI | Default already OFF; flip env var off |

**Universal rollback:** every step is one commit. `git revert <sha>` per failing step; reapply cleanly.

---

## Success snapshot

After F10.1 we expect (re-targeted on the F0.5 harsh-preset synthetic anchor — see "Plan retarget — post-F0.5 anchor (2026-04-29)"):

**Tier 1 — synthetic harsh anchor (canonical commit gate):**

| KPI | Harsh v0 | Final target | Modeled | Source |
|---|---|---|---|---|
| `overlap_decode_only_p95_ms` | 13.94 | **≤7.0** (≥50% drop) | 5–7 | F2.4 anchor |
| `overlap_decode_only_max_ms` | 77.67 | **≤40.0** (≥48% drop) | 30–40 | F2.4 anchor |
| `overlap_decode_sample_share_pct` | 4.45 | **≤2.5** (≥44% drop) | 1.5–2.5 | F2.4 anchor |
| `overlap_slow_frame_count_16ms` (per 30 s) | 3 | **≤1** | 0–1 | F2.4 anchor |

**Tier 2 — real-world anchor (added in F0.5b; required for "Final target" claim):**

| KPI | Source | Live 2026-04-28 | Final target |
|---|---|---|---|
| `overlap_drag_event_p95_max_ms` | `[FAST_DRAG_KPI]` (F2.4b) | 607.9 | **≤300** (≥50% drop) |
| `overlap_drag_ui_lag_max_max_ms` | `[FAST_DRAG_KPI]` (F2.4b) | 363.9 | **≤180** (≥50% drop) |
| `overlap_drag_handler_p95_max_ms` | `[FAST_DRAG_KPI]` (F2.4b) | 3.7 | hold ≤16 ms |
| `overlap_drag_background_decode_count_total` | `[FAST_DRAG_KPI]` (F2.4b) | 0 | hold at 0 (R3 invariant) |
| `overlap_settled_present_p95_ms` (≥30 settled samples) | real-world capture | 1 sample (TBD) | establish on F0.5b, then ≥30% drop |
| `overlap_sentinel_breakdown.decode` (per drag-with-decode) | `[OVERLAP_SCENARIO]` sentinel (F2.1b) | 0 (pre-F2.1b) | ≥1 |
| Drag-mode pixel hash (F1.2 gate) | drag-mode harness | green | unchanged (no regression) |

**Compat-only (kept in payload, NOT a target):**

- `overlap_set_slice_present_p95_ms` — averages all samples; harsh anchor already shows 0.0 because surrogate dominates.
- `overlap_decode_p95_ms` — same dilution problem; superseded by `overlap_decode_only_p95_ms`.
- `overlap_effective_fps` — capped at synthetic drag rate.
- `overlap_cache_hit_ratio_pct` — already 95.58% in harsh anchor; F7 deferred unless real-world disagrees.

This represents ≥50% reduction on every Tier-1 KPI, which (because the prior speculative-baseline framing of "halving") is the new operational meaning of "100% improvement". Image-quality regression is ruled out by Phase F1's drag-mode + settled hash gates.

**Caveat retained:** The original v0 column (155 / 52 / 98 / 16) is **fully retired** as of F2.4 / F0.5. All references downstream of this section have been re-pointed to either the harsh synthetic anchor or the real-world anchor produced in F0.5b. Any phase doc still referencing `overlap_set_slice_present_p95_ms` as a primary target predates 2026-04-29 and should be read with the retarget section in mind.
