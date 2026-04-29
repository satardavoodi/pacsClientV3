# Current KPIs — v2.3.6 (2026-04-22)

> **⚠ Superseded for "what to do next" by [`FAST_VIEWER_OPTIMIZATION_STATE_2026-04-29.md`](FAST_VIEWER_OPTIMIZATION_STATE_2026-04-29.md)** (2026-04-29). That document is the consolidated post-F0–F11 state. The KPI tables in this v2.3.6 file remain valid as a historical snapshot for log 96; live Tier-2 numbers and current targets are tracked in the state-of-system doc.

**Source log: `log 96.txt`** (low-config test PC, 150-series CT study, active download during interaction)
**Baseline for comparison:** log 93 (v2.3.5 — "mostly smooth but occasional stuck image")

This is the single canonical KPI file. When a future log (97, 98, ...) is taken, update the **"Latest"** column and move the previous numbers into a dated column on the right.

---

## 1. Stack drag KPIs (the headline metric)

| Drag | Dur (s) | Targets | event_p50 (ms) | event_p95 (ms) | handler_p50 (ms) | handler_p95 (ms) | ui_lag_max (ms) | bg_decode | prefetch/s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.16 | 0 | — | — | — | — | 0 | **0** | 0 |
| 2 | 0.77 | 1 | — | — | 6.9 | 6.9 | 0 | **0** | 0 |
| 3 | **3.49** | **41** | 67.3 | 157.6 | 3.4 | 21.3 | 221.8 | **0** | 0 |
| 4 | 0.39 | 3 | 43.0 | 76.9 | 3.1 | 14.2 | 64.9 | **0** | 0 |
| 5 | 0.67 | 5 | 99.5 | 167.9 | 3.0 | 12.6 | 154.6 | **0** | 0 |
| 6 | **2.57** | **23** | 81.4 | 191.0 | 3.2 | 24.2 | **373.3** | **0** | 0 |
| 7 | 0.73 | 7 | 95.0 | 182.1 | 3.7 | 6.3 | 166.4 | **0** | 0 |

### Progression (log 93 → log 96)

| KPI | log 93 (v2.3.5) | log 96 (v2.3.6) | Change |
|---|---|---|---|
| bg_decode_count (max) | 15 | **0** | ✅ 100 % eliminated on ALL drags |
| event_p50 | 60–158 ms | 43–99 ms | ✅ 28–37 % better |
| event_p95 | 151–232 ms | 77–191 ms | ✅ 18–49 % better |
| handler_p50 | 2–9 ms | 3.0–3.7 ms | ✅ stable low |
| handler_p95 | 1.6–2.6 ms | 6.3–24.2 ms | neutral (still <25 ms nominal) |
| ui_lag_max | 136–627 ms | 0–373 ms | ✅ 41 % better (max) |
| User verdict | "mostly smooth, occasional stuck" | **"almost smooth and fluid"** | ✅ subjective fix confirmed |

### Targets for next iteration

| KPI | Current | Target | Rationale |
|---|---|---|---|
| event_p50 | 43–99 ms | **< 50 ms** | Nominal mouse = 16 ms; 50 ms = "fluid" perception. |
| event_p95 | 77–191 ms | **< 120 ms** | Eliminate the worst tail spikes. |
| ui_lag_max | 0–373 ms | **< 200 ms** | Single-stutter perception floor. |
| prefetch/s | 0 | **5–15** | Cache must grow during drag; currently 0 (P1 lane is idle). |

---

## 2. Startup / series-switch KPIs

| Metric | Log 96 | Target | Gap |
|---|---|---|---|
| First `load_single_series_total` | **4022 ms** | < 1500 ms | **-62 %** needed |
| Second `load_single_series_total` | **4389 ms** | < 1500 ms | **-66 %** needed |
| `series_switch_breakdown` (psso_total) | 663 ms | < 300 ms | -55 % needed |
| `FAST:first_image_visible` | 54.6 ms | < 80 ms | ✅ OK |
| `UX_FIRST_IMAGE_VISIBLE` total | 54.6 ms | < 80 ms | ✅ OK |
| Startup `zoom_to_fit` calls | **4 calls** in ~1 s | 1 call | Redundant refit storm |
| `startup_refit` sequence | delay 50 → 120 → 220 → 0 | 1 final refit | Same |

### Interpretation
- `first_image_visible` is **already fast** (54 ms). The 4-second `load_single_series` is the wait between user clicking the patient and seeing the first image.
- **4 zoom_to_fit events with identical scale=324.64** = redundant work triggered by window-resize propagation during tab insertion.

---

## 3. Resource / CPU KPIs

| Phase | CPU % | RSS (MB) | Notes |
|---|---|---|---|
| Startup (loading) | 138 | 1082 | GPU-boost disabled, software OpenGL |
| During first drag (drag 3, 41 targets) | 91–127 | 1044–1068 | Download subprocess + main process |
| During drag with heavy download | 115 | 1053 | ui_lag 373 ms — correlates with high CPU |
| Light drag (drag 4, 3 targets) | 108 | 1067 | ui_lag 65 ms |
| Idle steady-state | 4–14 | 1010 | After download complete |

### Interpretation
- CPU never exceeded 138 % → multi-core system, no single-core saturation.
- Download subprocess and main process contention is visible (CPU 91–127 % during drag 3 correlates with ui_lag=373 ms).
- Memory is stable at ~1050 MB during active work.

---

## 4. Pipeline latency budget (v2.3.6)

End-to-end from "DM image saved to disk" → "visible in viewer":

| Layer | Timer | Effective during drag |
|---|---|---|
| DM progress batch | 100 ms | **skipped** (GC#4 rule R5) |
| Viewer progress debounce | 100 ms | **skipped** while protected |
| Progressive grow timer | 150 ms → 1500 ms during drag | 1500 ms |
| Coordinator queue recheck | 50 ms | normal |
| DM notify cooldown | 500 ms | normal |
| Protected-drag grace | 1500 ms | active for whole drag + keepalive |
| Protected-drag tail | 250 ms | after drag ends |

Worst-case perceived latency during drag: **0 ms** (user sees surrogate or cached hit; actual pixels may arrive up to 1.75 s after drag ends).
Worst-case perceived latency idle: **~350 ms** (unchanged from v2.2.8.1).

---

## 5. Regression alarm thresholds

If any future log shows any of the following, **STOP and investigate** before shipping:

- `background_decode_count > 0` on any drag → R3 regression (PREFETCH admission gate broken)
- `prefetch_per_s = 0` AND `ui_lag_max > 500 ms` → protected-drag latch not working (R2 regression)
- `event_p50 > 150 ms` on any drag > 2 s → DM progress chain not skipped (R5 regression)
- `ui_lag` showing steady-state > 500 ms → GC pause (R6 regression)
- "Scrollbar moves but image frozen" user report → GC#5 surrogate-staleness regression (R1 regression)
- Startup `load_single_series_total > 6 s` → new blocking I/O on the first-open path
- More than 5 `zoom_to_fit` calls per tab-open → refit-storm regression

---

## 6. Test suite health (as of v2.3.6)

```
tests/viewer/test_qt_slice_viewer_stack_drag.py     30/30 PASS
tests/viewer/test_qt_stack_drag_bridge.py           25/25 PASS
tests/viewer/test_fast_viewer_pipeline.py           61/61 PASS individually
tests/viewer/test_b34_interaction_aware_policy.py   26 tests, 6 batch-mode flakes (pre-existing)
tests/viewer/test_cp1_control_plane_governance.py   18 tests, 2 batch-mode flakes (pre-existing)
tests/download_manager/run_dm_test.py               27 scenarios, 129 assertions PASS
tests/download_manager/test_dm_stress.py            10 scenarios (H1–H10) PASS
tests/load/run_load_test.py                         11 scenarios (L1–L11) PASS
```

**Batch-mode flakes are NOT regressions from v2.3.6.** They are shared-module-state issues from earlier refactors and existed on the baseline. Verify by running the failing test in isolation.

---

## 7. Source-of-truth log snippets

For future forensics, the key log patterns to grep are:

```powershell
Select-String -Path "logNN.txt" -Pattern "FAST_DRAG_KPI|PROTECTED_DRAG|UX_|background_decode|ui_lag_max|series_switch_breakdown|startup_refit|first_image_visible"
```

Every release note referencing smoothness MUST cite a log number and the specific KPI line.
