# AI-PACS — Unified Stabilization & Optimization Plan (2026-07-01)

**Purpose:** one correction plan for stability, reliability, performance, and maintainability —
so the *same function behaves the same way in every layout and module*. Synthesized from the two
live-log reviews (`KPI_SESSION_REVIEW_2026-07-01.md` + the fresh-run delta 14:09–14:18), the recent
plans/reports under `docs/`, the actual code, `CLAUDE.md` as-built history, and a full `AIPACS_*`
flag inventory.

**Status:** PLAN ONLY — nothing implemented. Each item lands later via `aipacs-root-cause-fix`
(minimal edit → retest once → report) with the `aipacs-regression-guard` check.

---

## 0. Method & evidence base

- Live logs: two fresh runs on 2026-07-01 (13:31–13:51 warm; 14:09–14:18 cold startup+load). Both
  cleared/relaunched; second confirmed 100% fresh (0 pre-boundary lines).
- Standards: `docs/performance/FAST_VIEWER_KPI_CATALOG.md`, `CURRENT_KPIS_v2.3.6.md`.
- Flag inventory: 62 distinct `AIPACS_*` env flags found (12 default-OFF, 50 default-ON) — plus the
  many default-ON kill switches recorded only in `CLAUDE.md`. The true flag surface is larger; there
  is **no central registry**, which is itself a maintainability risk.
- Guardrail (unchanged, every phase): FAST viewer never instantiates VTK render windows; never remove
  metadata/overlays/measurements/sync/reference-lines/sidebars/patient-workflows; keep cross-patient
  isolation + multi-study vs single-study gating; never write the live `dicom.db`; keep Fast/Advanced/VTK
  domains separated.

---

## 1. Current-state comparison (reports & plans vs. actual code/docs)

### 1a. Already fixed and verified (do not re-touch)
- **Multi-study Stage A1** — canonical on-disk count for offset display keys (flag *collapsed* to
  unconditional) + A1 watchdog `force_reload=True`. **Live-verified on patient 48695** (prev-exam
  series grew 50→144 / 20→135; primary 302 29→147; clean KPIs, no cross-patient leak).
- **Geometry hardening T1** — IPP-spacing invariant guard shipped.
- **DM dedup** (46271/423988 phantom inflation) — user-confirmed.
- **Curved/Dental MPR safety** — teardown/UAF guard, deleted-object event swallow, 2D-mouse, WL
  inherit, robust WL, panoramic sharpen/quality, FAST→VTK pick routing, in-place result (all
  flag-gated default-on).
- **MPR annotation** — slice-binding by creation coordinate + viewport-scoped targeting (48272);
  MPR-click-to-activate for the standard 4-panel `toggle_zeta_mpr`.
- **EchoMind popup theme/contrast**, single-instance takeover, attachment local-first, voice
  keep-on-close, import-opens-FAST — all shipped.

### 1b. Documented ≠ implemented (inconsistencies to reconcile)
- **🔴 `AIPACS_DENTAL_VTK_MPR` default mismatch.** `CLAUDE.md` states *default-ON (supersedes the numpy
  orientation as the default)*; **code reads default-OFF** (`modules/dental_imaging/workspace.py:104`,
  docstring: "kept behind the flag for troubleshooting"). Net effect: Dental Imaging ships the
  **numpy-orientation path that CLAUDE.md itself says "didn't reliably match standard MPR"** — a
  reliability gap and a doc-vs-code divergence. Decide the intended default and align both.
- **Flag drift.** Several flags recorded in `CLAUDE.md` were later *retired/reversed* in code (e.g.
  `AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR`, `MPR_ANNOTATION_PERSIST`), but the as-built text still
  references them. Doc and code must be reconciled.
- **Kill-switch accumulation.** Many behavior fixes shipped flag-gated default-on as *temporary* safety
  nets. Per the standing directive ("route decisions through the one authority; collapse verified
  flags"), most should now be collapsed — they are a standing source of "works here / not there"
  divergence when a flag path and its legacy branch drift.

### 1c. Still-open / staged (the real backlog)
| Item | Source | Status |
|---|---|---|
| **Main-thread blocking** (patient-open/thumbnail/DM-refresh/manifest on GUI thread) | KPI reviews | **open — #1 stability issue** |
| Multi-study **A2** live secondary-study progress bridge (grow *during* download, not only after settle) | MULTISTUDY_…_2026-06-30 | STAGED |
| Multi-study **B1** Series 100000 (DICOMized document) offset-key mis-resolution | same | STAGED |
| Cine/multi-frame decode + playback | DICOM_COMPLEX_…_2026-07-01 | implemented, **needs live verify** |
| Dental Curve MPR suite A0/B1/B3/C1/D2/D4 | DENTAL_CURVE_MPR_…_2026-06-22 | STAGED (default-off = dead for users) |
| Geometry hardening **T2/T3** (persist spacing/photometric to DB; DB metadata path, ~1424 ms H1 latency) | VIEWER_GEOMETRY_…_2026-06-14 | STAGED |
| EchoMind prompt safety (legacy "extreme exaggeration"; correction schema; modality match; temp/max_tokens) | ECHOMIND_PROMPT_…_2026-06-29 | audit, unfixed |

### 1d. "Works in one place, fails in another" (the core complaint)
- **Secondary/previous-exam series grow:** correct *after settle* (A1) but not *during download* (A2 gap)
  — grows in the primary study, lags in a secondary study.
- **Dental geometry:** standard MPR correct; dental workspace runs the numpy path (VTK-parity flag off)
  → L/R / A-P / S-I can diverge from standard MPR.
- **Annotation activation:** viewport-scoped + click-to-activate works in the standard 4-panel MPR;
  **not wired for the curve/dental VTK hosts** → annotating the MPR works in one layout, not another.
- **Thumbnail real-time status:** historically bridged for the primary study only; sibling-study status
  needed a separate fix (46630/47084) — same feature, two code paths.

### 1e. Log noise / instability sources
- `download_diagnostics.log` is **~99% WARNING** (telemetry `log_stage_timing`/progress emitted on the
  WARNING channel) — 17 k lines/run bury the real faults (13 socket errors/run:
  `get_report_status`/`send_request`).
- **One 13–15 MB single log record per run** (a large payload dumped to one line on `role=main`) — a
  main-thread write hazard and a log-bloat/parse hazard.
- `[FAST_GEOMETRY_ORDER_MISMATCH]` re-logged ~16×/series (safeguard working, but noisy).
- Curved-MPR engine uses `print()` (shadow-routed) rather than the logger.

### 1f. Cross-impact risk (changes that could break working parts)
- Off-thread moves (P1) touch **guarded** thumbnail-pipeline, multistudy render, patient-table → must
  honor canonical-path / memory-first / offset-key / single-vs-multi gating invariants.
- Geometry T2/T3 (DB metadata) touches the FAST pixel pipeline → **golden-compare required** before any
  flip; affects every series' render.
- Flag collapse touches every call site of a flag → do **one flag at a time, after live-verify**.
- Dental VTK-MPR default flip changes dental geometry for all users → source-build parity check first.

---

## 2. Correction criteria (acceptance — consistency is the theme)

Global rule: **a function must behave identically across every layout, study slot, and module.** Each
fix defines its own acceptance, but all share: (a) single-study path byte-identical when not applicable;
(b) cross-patient isolation preserved; (c) verify-lane test green; (d) fresh-log KPI review after the phase.

- **Main-thread stalls:** during patient-open + drag + switch, **no `MAIN_THREAD_STALL` > 500 ms**, p95
  < 200 ms, `table_refresh`-correlated stalls → ~0; decode/TTFI unchanged (p50 ≈ 5 / 19 ms).
- **Secondary-series grow:** a dragged previous-exam/secondary series reaches full on-disk count
  **during** download, with the *same* progressive behavior as a primary series.
- **Dental geometry:** dental workspace L/R/A-P/S-I and slice order **match standard MPR** for the same
  volume (side-by-side).
- **Annotation:** the active/clicked viewport is always the annotation target — in every host (standard
  MPR, curve, dental) and every layout.
- **EchoMind:** report output keys present only when dictated; no legacy "exaggeration" instruction;
  modality routing matches all expected modality strings; deterministic temp/max_tokens.
- **Logs:** no file that is ≥90% WARNING; no single record > ~256 KB; real warnings/errors visible; the
  useful diagnostic markers (stall probe, stage timing, KPI, VIEWPORT_LIFECYCLE) preserved.

---

## 3. Correction methods (safe, reuse existing architecture — no duplicate/temporary logic)

- **Off-thread work (P1):** reuse the existing worker/deferred patterns (`_dm_details.py` visibility-
  deferral, repaint-suppressed rebuild, `_schedule_ui_coro`). Move the *disk scan / thumbnail encode /
  status compute* to a worker or a cached snapshot; keep the UI update on the main thread as a cheap
  O(1) apply. **Do not** add a parallel refresh path — extend the existing one.
- **Decision unification (the anti-"works-here-fails-there" method):** route every "is series complete /
  should download / should grow / should skip" question through the **one authority**
  (`series_display_state.decide_display_action` / `series_completeness` predicates /
  `patient_study_set`), never a fresh bespoke `disk >= expected` compare. The 48272 complete-on-disk
  guard is the template (bespoke check → routed through `SeriesCompletenessSnapshot`).
- **Secondary-study bridge (A2):** extend the existing `HomeDownloadService` progress bridge to re-key
  by globally-unique `series_uid` (the proven `AIPACS_PROGRESSIVE_UID_BIND` mechanism), not add a second
  bridge.
- **Dental geometry:** don't write new geometry — reuse the standard (Zeta) MPR geometry contract per
  the Unified MPR directive; resolve the VTK-MPR default via source-build parity.
- **Flag collapse:** for each verified default-on flag, delete the env read + legacy branch + re-pin the
  guard test (the `AIPACS_DISK_COUNT_CANONICAL` collapse is the template). One flag per change.
- **Logging:** reclassify telemetry to an INFO/diagnostic channel (keep stage-timing, KPI, stall probe);
  add a size cap in the log formatter; throttle repeat geometry-mismatch to once per series.

---

## 4. Phased implementation (critical stability first)

### Phase 0 — Baseline & guardrails (no behavior change)
1. Productionize the read-only **KPI session analyzer** (`tools/performance/kpi_session_report.py`, from
   the KPI review plan) so every phase can be measured from fresh logs.
2. Build a **central flag registry** (audit doc + one module) enumerating all `AIPACS_*` flags, defaults,
   and purpose; reconcile against `CLAUDE.md`. Resolve the `AIPACS_DENTAL_VTK_MPR` doc/code mismatch here.
3. Freeze the current fresh-log KPI numbers as the regression yardstick.

### Phase 1 — Critical stability: main-thread blocking (the #1 issue)
- **P1.1** `save_thumbnail` / `save_thumbnail_with_bytes` off the GUI thread (most contained; highest
  value). Flag-gated default-on; kill switch = legacy inline save.
- **P1.2** DM status refresh (`refresh_download_statuses`/`_check_study_download_status`) +
  `build_local_manifest` (`modules/storage/sync_manifest.py`) off the GUI thread / cached snapshot.
- **P1.3** `_render_multistudy_grouped[_slot]` — deferred, repaint-suppressed rebuild.
- **P1.4** Startup `add_AIPacs_tab` (2.4 s, includes EchoMind registry init) — lazy/defer the EchoMind
  CommandBus registration off the critical path (measure before optimizing).
- **Acceptance:** §2 main-thread targets; decode/TTFI unchanged. Review fresh logs.

### Phase 2 — Geometry / layout / annotation consistency
- **P2.1** Resolve Dental VTK-MPR default + source-build geometry parity (dental = standard MPR).
- **P2.2** Multi-study **A2** live secondary-study progress bridge (grow during download).
- **P2.3** Multi-study **B1** Series 100000 document offset-key resolution.
- **P2.4** Annotation activation for curve/dental VTK hosts (same behavior as standard MPR).
- **P2.5** Throttle `FAST_GEOMETRY_ORDER_MISMATCH` logging (keep the safeguard).
- **Acceptance:** §2 grow/dental/annotation criteria; same series loads identically across layouts/studies.

### Phase 3 — Performance & log control
- **P3.1** Per-phase fresh-log KPI review via the Phase-0 analyzer.
- **P3.2** Log hygiene: move download telemetry off WARNING; cap single-record size (13 MB fix);
  throttle repeat markers; reduce the 17 k-WARNING volume so real faults surface.
- **P3.3** Triage the recurring download socket errors (`get_report_status`/`send_request`).
- **P3.4** Geometry hardening **T2 → T3** (persist spacing/photometric; DB metadata path for the
  ~1424 ms H1 header latency) — **only after golden-compare** passes.
- **P3.5** Cine/multi-frame **live source-build verification** with real cine/US/XA data.
- **Acceptance:** no ≥90%-WARNING log, no MB-scale records; H1 latency ↓; KPIs unchanged/better.

### Phase 4 — Consolidation, flag collapse & documentation
- **P4.1** Collapse verified default-on kill switches one-by-one (route decisions through the one
  authority; delete legacy branches after live-verify).
- **P4.2** EchoMind prompt fixes (remove legacy "extreme exaggeration"; conditional `correction()` keys;
  broaden modality match; add temperature/max_tokens).
- **P4.3** Reconcile `CLAUDE.md` with actual code (flag defaults, retired flags).
- **P4.4** Publish the final flag registry + structure doc.
- **Acceptance:** fewer flags, one decision authority, doc == code, all guard suites green.

---

## 5. Regression prevention (tests per area)

Reuse the existing verify-lane suites and extend, never fork:
- **Geometry:** IPP-spacing invariant + MPR geometry tests → **extend for dental↔standard parity**.
- **Layout:** `tests/code/viewer/test_viewer_split_architecture.py` → add a layout-switch KPI guard.
- **Annotation:** slice-binding + viewport-scope + click-activate tests → **extend to curve/dental hosts**.
- **EchoMind:** add prompt schema/format/modality tests (currently none).
- **DICOM loading:** multi-frame, canonical-disk-complete, per-series-study-pk tests (exist) → add the
  A2/B1 cases.
- **Performance KPIs:** `kpi_session_report` guard test + thresholds table; run the analyzer after each
  phase (verify lane offscreen: `python -m pytest tests/code/... -p no:debugging -q`; clinical lane:
  controlled same-patient before/after re-measure of `MAIN_THREAD_STALL` count/max + `table_refresh`
  correlation).

---

## 6. Performance & log control (ongoing)

- **Reduce:** download telemetry off the WARNING channel; single-record size cap; throttle repeat
  geometry-mismatch; aggregate the download progress spam.
- **Keep:** main-thread stall probe + traces, `stage-timing`, `[KPI]`/`[UX_*]`/`FAST_*`,
  `VIEWPORT_LIFECYCLE`, per-series completeness — these are the diagnostics that made this review possible.
- **Cadence:** after every phase, capture a fresh run and re-review with the analyzer; confirm patient
  open, drag-drop, decode, render, scroll, and **Dental Imaging** stay fast and stable (Dental was NOT
  exercised in either logged run — it must be driven in the next capture to be validated).

---

## Priority summary

1. **Phase 1 main-thread blocking** — the measured, repeatable regression (stalls to 6.5 s; `table_refresh`
   34/87). Biggest stability win, most contained.
2. **Phase 2 dental geometry default + secondary-series grow (A2) + annotation host parity** — the core
   "works here / fails there" set.
3. **Phase 3 log control + geometry T2/T3 + cine live-verify** — perf and noise.
4. **Phase 4 flag collapse + EchoMind prompts + doc reconciliation** — maintainability, fewer divergent paths.

## Progress log (2026-07-01)

- **Phase 0 — DONE.** KPI analyzer (`tools/performance/kpi_session_report.py`) + `kpi_targets.py` +
  guard test + flag registry (`docs/reference/AIPACS_FLAG_REGISTRY_2026-07-01.md`). Read-only.
- **P1.1 — DONE + live-verified.** Thumbnail disk write off the GUI thread
  (`AIPACS_THUMB_SAVE_ASYNC`, default-on). `save_thumbnail` gone from stall traces on pid 193028.
  Report: `docs/reports/P1_1_THUMBNAIL_ASYNC_SAVE_2026-07-01.md`.
- **P1.2 — DONE + offscreen-verified.** Cooperative chunking of `refresh_download_statuses`
  (`AIPACS_STATUS_REFRESH_CHUNKED`, default-on; no threads). Report:
  `docs/reports/P1_2_STATUS_REFRESH_CHUNKED_2026-07-01.md`.
- **P1.3 — DONE + visual-verified, default-on.** Progressive/chunked single-study thumbnail-sidebar
  build (`AIPACS_SIDEBAR_BUILD_CHUNKED`, flipped default-on after source-build visual check;
  multi-study path untouched). Report: `docs/reports/P1_3_SIDEBAR_BUILD_CHUNKED_2026-07-01.md`.
  NOTE: P1.3 was **evidence-re-targeted** from the plan's original `_render_multistudy_grouped`
  wording to the single-study `_render_thumbnails_from_files` path — that is what the live stall
  traces showed.

**Latest run (pid 62868):** zero errors/tracebacks from the three changes; `save_thumbnail`,
`refresh_download_statuses`, `build_local_manifest`, `_pw_thumbnails`, `_pw_panels` all absent from
the stall traces. The remaining large freeze (max ~2.9 s) is **startup** (P1.4).

- **P1.4 — assessed, NOT yet implemented.** The two biggest freezes now are one-time startup:
  `add_AIPacs_tab` builds the whole `ControlPanelInterface` (AIPacs + EchoMind) synchronously
  (~1.4 s), plus theme `apply_modern_style` (~2.5 s). Deferring core tab construction is riskier than
  P1.1-P1.3 (tab presence, `control_panel` dependencies, EchoMind init) and is **one-time at launch,
  not during clinical reading** — so lower during-use value. Recommend a separate, carefully-scoped
  pass (defer EchoMind init specifically, not the whole tab), or deprioritize vs. Phase 2.

Next candidates: consolidate (fold CLAUDE.md as-built notes; collapse the now-verified P1.x flags per
the flag-collapse policy), or move to Phase 2 (dental geometry flag reconciliation, multi-study A2/B1).
