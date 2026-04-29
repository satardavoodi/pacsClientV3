# Silent Main-Thread Blocker Triage — G6 (2026-04-29)

**Phase:** G6 (instrumentation only — no behavior change)
**Status:** Shipped (this commit)
**Predecessors:** G1 (paint observability) → G2 (frame prefetch P1) → G3 (Layer 2b defer) → G4 (terminal grow defer) → G5 (main-thread stack sampler)
**Successor (planned):** G7 — defer the worst-offender tag identified by the next live G6 log.

## 1. Problem statement

Post-G3 + G4 production log (2026-04-29 15:47:37–38) shows:

- F9 (`[F9] Layer 2b deferred series=201 retry=2/6 delay_ms=550`) fires correctly.
- F10 (`[F10] terminal grow deferred series=201 retry=1/6 delay_ms=1500`) fires correctly.
- A 1201 ms `[MAIN_THREAD_STALL] drag_active=True` still happens, with **558 ms of pure log silence** between the F9 retry (15:47:37.876) and the next probe tick (15:47:38.435).
- `[FAST_DRAG_KPI] event_p95_ms=843.6` confirms the user-visible freeze.
- Pipeline metrics are healthy: `handler_p95=3.3 ms`, `prefetch_per_s=0.0`, `background_decode_count=0`.

**Diagnosis:** The blocker is OUTSIDE the deferred Layer 2b / terminal grow paths. Pipeline compute and prefetch are not the bottleneck. The freeze surface is composed of one or more *other* main-thread Qt slots that fire while the user drags, and the F11 stack sampler emits 1 dump per second — not enough to attribute every individual slot.

## 2. G6 deliverables

| Item | Location | Purpose |
|---|---|---|
| Helper module | `modules/viewer/fast/slot_timing.py` | `emit_slot_timing()`, `@slot_timing` decorator, `time_slot()` context manager |
| Plugin mirror | `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/slot_timing.py` | Production-build parity (per repo rule) |
| Decorator wiring | `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` (4 methods) | Top-suspect coverage |
| Inline timing | `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py::on_series_completed` | DM → viewer fan-out lane |
| Inline timing | `modules/zeta_boost/cache_engine/_zb_lifecycle.py::notify_global_download_stop` | ZetaBoost handoff at completion |
| Inline timing | `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py::_finalize_progressive_series` | Force-run terminal work post-defer |
| KPI parser | `tools/performance/clearcanvas_aipacs_kpi_harness.py::parse_slot_timing_log_text` | Aggregates per-tag drag-active percentiles + ranked top tags |
| Tests (parser) | `tests/performance/test_slot_timing_kpi_parser.py` | 15 tests — round-trip, prefix tolerance, malformed lines, ranking |
| Tests (helper) | `tests/viewer/test_slot_timing.py` | 26 tests — decorator, contextmanager, env gates, exception safety |

All 41 new tests are green; existing 43-test overlap regression bundle stays green.

## 3. Emit format (stable contract)

```
[SLOT_TIMING] tag=<TAG> duration_ms=<F.3> drag_active=<True|False>
              threshold_ms=<F.1> series=<SN|none> extra=<k1=v1;k2=v2>
```

- Idle threshold: 30 ms (env `AIPACS_SLOT_TIMING_THRESHOLD_MS`).
- Drag threshold: 8 ms (env `AIPACS_SLOT_TIMING_DRAG_THRESHOLD_MS`).
- Master kill switch: `AIPACS_SLOT_TIMING_TRACE=0`.

The format is locked by `tests/performance/test_slot_timing_kpi_parser.py::test_emit_format_matches_production_helper` (round-trip via the real helper through the real parser).

## 4. KPI fields produced by `parse_slot_timing_log_text`

| Field | Meaning |
|---|---|
| `samples` | Total `[SLOT_TIMING]` lines parsed |
| `drag_sample_count` / `idle_sample_count` | Split by `drag_active` |
| `per_tag[tag].drag_total_ms` | Sum of durations during drag — **the budget signal** |
| `per_tag[tag].drag_p95_ms`, `drag_max_ms` | Drag-only percentiles |
| `per_tag[tag].p50_ms`, `p95_ms`, `max_ms` | All-samples percentiles |
| `top_drag_tags` | Top 5 tags ranked by `drag_total_ms` |
| `overlap_slot_timing_drag_blocked_ms_total` | Sum of all drag-active durations across tags |
| `overlap_slot_timing_worst_drag_call_ms` | Single worst drag-active call duration |
| `overlap_slot_timing_worst_drag_tag` | Tag of the single worst drag-active call |

## 5. Suspect ranking (pre-G6 hypothesis)

| Rank | Tag | Why suspected | Confirmation needed |
|---|---|---|---|
| HIGH | `thumbnail.complete_series_download` | No drag gate; multiple widget mutations; 2 logger.info; final `apply_border_states_new`; runs once per completed series during overlap | Wait for live `[SLOT_TIMING]` log |
| HIGH | `thumbnail.start_series_download` | No drag gate; `setUpdatesEnabled(False/True)` block; multiple widget mutations; raise_/update | Same |
| MEDIUM | `home_download.on_series_completed` | Inner closure with multiple sub-emits; some `series_downloaded` connections may be `Qt.AutoConnection` (synchronous) | Same |
| MEDIUM | `progressive.finalize_terminal` (force=1) | After defer cap, force-runs `_refresh_and_sync_metadata` + `_invalidate_series_caches` + `_update_thumbnail_count` + `exit_progressive_mode` per viewer | Same |
| MEDIUM | `zetaboost.notify_global_download_stop` | Class-level lock + counter mutation, no-op when count > 0 | Same |
| LOWER | `thumbnail.update_series_progress`, `thumbnail.apply_border_states_new` | Already coalesced/throttled; included for completeness | Same |

## 6. Live-log triage protocol (G7 trigger)

1. Reproduce a "frozen image but scrollbar moves" / `[FAST_DRAG_KPI] event_p95 > 500 ms` scenario.
2. Collect `user_data\logs\viewer_diagnostics.log`.
3. Run:
   ```pwsh
   .venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py parse-slot-timing-log --log user_data\logs\viewer_diagnostics.log
   ```
   (CLI hook to be added in G6.1 if not already present; in the meantime, Python:)
   ```python
   from tools.performance.clearcanvas_aipacs_kpi_harness import parse_slot_timing_log_text
   import json, pathlib
   text = pathlib.Path(r"user_data\logs\viewer_diagnostics.log").read_text(encoding="utf-8", errors="ignore")
   print(json.dumps(parse_slot_timing_log_text(text), indent=2))
   ```
4. Inspect `top_drag_tags[0]`. The tag with the largest `drag_total_ms` AND a `drag_max_ms ≥ 200 ms` is the **G7 target**.
5. G7 implementation pattern (mirror G3/G4):
   - Bounded-retry defer using `_FAST_PROGRESSIVE_*_DEFER_BASE_MS` / `_STEP_MS` / `_MAX_RETRIES` constants.
   - Force-run after max retries (never starve the action).
   - Log line `[Gx] <tag> deferred ... (FAST drag active; avoids ~Nms+ main-thread freeze)` matching the F9/F10 style.
   - Plugin mirror parity.
   - One new test in `tests/viewer/test_<tag_area>_drag_defer.py` confirming defer-then-force semantics.

## 7. Acceptance criteria for G6 (this commit)

- [x] `slot_timing.py` exists in `modules/viewer/fast/` and plugin mirror.
- [x] At least 6 callsites instrumented (4 thumbnail methods + on_series_completed + finalize + ZetaBoost notify).
- [x] KPI parser added.
- [x] 41/41 new tests green.
- [x] 43/43 overlap regression bundle green (R-rule preservation).
- [x] No behavior change visible on existing real-world FAST_DRAG_KPI.

## 8. What G6 does NOT do

- Does NOT defer or skip any work (observation only).
- Does NOT change cadence, throttle, or timer constants.
- Does NOT add new env defaults that could affect performance.
- Does NOT touch F4/F5/F7 (deferred per consolidation doc).
- Does NOT touch F3.5.4 default-on flip (still BLOCKED on installed-build refresh + soak).

## 9. Next live-log request

Per the user's standing rule ("only stop and ask when you specifically need a live log to evaluate the result of the changes"), G6 has now produced a deterministic measurement surface. The next live log will:

- Confirm `[SLOT_TIMING]` lines appear with `drag_active=True`.
- Reveal the tag(s) responsible for the 558 ms silence + 1201 ms drag-active stall.
- Unambiguously direct G7 to a specific defer target (or, if no observed tag accounts for the silence, escalate to broader instrumentation in G6.1: GC events, decode_service IPC, paint events, signal fan-out from `series_downloaded`).

## 10. Cross-references

- `docs/plans/performance/FAST_VIEWER_OPTIMIZATION_STATE_2026-04-29.md` — phase ledger.
- `docs/plans/performance/CURRENT_KPIS_v2.3.6.md` — KPI list (extend with G6 fields after first live log).
- `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md` — strategic plan.
- Critical rules R1–R20 — preservation contract for any G7+ defer.
