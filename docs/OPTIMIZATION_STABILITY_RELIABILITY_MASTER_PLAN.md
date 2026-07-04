# AI-PACS — Software Optimization, Stability & Reliability Master Plan

**Status:** CANONICAL — this is the single source of truth for optimization, stability, reliability,
and performance work. Every future optimization task extends this document rather than starting a new
disconnected plan.
**Created:** 2026-07-03 (consolidates ~1 month of fragmented optimization work)
**Owner discipline:** code is the source of truth for *implementation status*; docs describe *intent*;
logs/KPIs show *runtime behavior*. All three are reconciled here.

> **Reading order for a new agent:** §1 (how to use) → §4 (current architecture) → §6 (reconciliation
> matrix) → §9 (backlog) → §10 (next safe phase). Then, only if you touch a pipeline, the linked
> subsystem doc.

---

## 1. Purpose & the one non-negotiable rule

Over the last month the same three themes — **reliability, stability, performance** — were worked
repeatedly across many documents, code changes, and partially-finished implementation phases. The
knowledge fragmented. This document reconciles all of it into one backlog with one status per problem.

**The critical rule going forward:** do **not** create another independent optimization plan. When a
new optimization idea appears, first locate it in the backlog (§9). If it is already tracked, update
that item. If it is genuinely new, add a new backlog ID here. Never fork a parallel plan.

**Architecture guardrails that outrank every optimization** (from `CLAUDE.md`; unchanged, every phase):

- FAST viewer never instantiates VTK render windows.
- Never remove viewer features: overlays, metadata, measurements, sync, reference lines, sidebars,
  patient/thumbnail workflows.
- Keep the three execution domains separated: **Fast** (`pydicom_qt`), **Advanced** (`vtk_simpleitk`),
  **VTK modules** (MPR / Dental / Analysis). Unify only through the read-only trunk.
- Preserve cross-patient isolation and single-study-vs-multi-study gating.
- Never write the live `dicom.db`; atomic `.part` → `os.replace`; resume rejects partials.
- Minimal safe edits, flag-gated with a kill switch, verify-lane test + fresh-log review after each phase.

---

## 2. TL;DR — where we are on 2026-07-03

1. **The performance bottleneck was mis-identified for months and is now correctly known.** Decode and
   render are **healthy** (decode p50 ≈ 4.5 ms, TTFI p50 ≈ 19 ms). The real #1 issue is **main-thread
   blocking** on the download-status refresh + filesystem manifest scan path, which starves every
   async fetch and grow event.

2. **The reliability failures (blank thumbnails, previous-exam won't grow, 80/20 flakiness) are ONE
   architectural defect, not three bugs:** completion is defined by *notification arrival*, not *state
   convergence*. Dropped notifications leave a study partial until a manual reopen.

3. **A canonical fix has been designed and partially shipped.** The pure lifecycle core
   (`patient_load_lifecycle.py`, 15 tests green) + shadow telemetry + **Seam A/B cutovers** shipped
   **default-on** in the 2026-07-03 build with kill switches. They are **safe-by-construction and
   unit-tested but NOT yet live-verified on the reporting workstation** — that verification is the
   explicit purpose of that build.

4. **Phase-1 main-thread fixes shipped** (async thumbnail save, chunked status refresh, chunked sidebar
   build). The *broad* off-GUI-thread move (the amplifier) and the full lifecycle cutover remain the
   two biggest open items.

**The single most valuable next action:** live-verify the shipped Seam A/B cutovers and the P1 fixes on
the reporting PC with fresh logs, *before* writing any more code. If they hold, collapse their flags and
proceed to the off-thread convergence sweep (Stage 2). See §10.

---

## 3. Historical work summary & document inventory (Deliverable 1)

Roughly 240 markdown files touch performance/stability/reliability across `docs/`. They cluster into
generations. The table lists the **canonical** documents a consolidation must build on; the many
per-fix reports are folded into the backlog (§9) and remain as historical evidence.

### 3.1 The anchor documents (read these; they supersede the rest)

| Doc | Date | Role | Status of its content |
|---|---|---|---|
| `docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md` | 07-02 | **Root-cause bible.** Proves the single "completion ≠ convergence" defect; designs the Study Load Lifecycle. | Phase-1 core built + green; Seams A/B shipped 07-03 (unverified). **Supersedes all prior thumbnail/grow patch docs as the explanation.** |
| `docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md` | 07-01 | **Phased execution plan** across stability/perf/maintainability. | Phase 0 + P1.1–P1.3 DONE; P1.4 assessed; Phases 2–4 open. |
| `docs/reports/KPI_SESSION_REVIEW_2026-07-01.md` | 07-01 | **KPI baseline + bottleneck proof** (Conference-Loop, live logs). | Read-only finding. Establishes decode/render healthy, main-thread blocking = #1. Authoritative baseline. |
| `docs/reports/deploy-record-workstation-2026-07-03.md` | 07-03 | **As-shipped record** of the lifecycle build. | Gate PASSED with informed override; live-verify pending. |
| `docs/reference/AIPACS_FLAG_REGISTRY_2026-07-01.md` | 07-01 | **Flag audit** (62 `AIPACS_*` flags; doc-vs-code divergences). | Seed for the Phase-4 central registry. |
| `docs/plans/VIEWER_GEOMETRY_HARDENING_MASTER_PLAN_2026-06-14.md` | 06-14 | Geometry correctness/latency (T1/T2/T3). | T1 shipped; T2/T3 staged (golden-compare gate). |

### 3.2 Supporting / superseded generations (historical evidence, folded into §9)

- **FAST viewer stabilization (2026-05-08 → 05-13):** `FAST_VIEWER_STABILIZATION`, `FAST_VIEWER_REGRESSION_GUARDS`, `FAST_GROW_BATCHING_HARDENING`, `FAST_RENDER_CLOCK_PRODUCTION_HARDENING`. Mostly **shipped**; their guards live in `tests/code/viewer/`.
- **Responsive-UI generation (2026-05-26):** `RESPONSIVE_UI_ROOT_CAUSE`, `_SCALING_PLAN(+REVIEW)`, `_STRUCTURAL_PATTERN`, `_TEST_CRITERIA`. Partly shipped; the main-thread findings are **superseded** by the sharper 07-01 KPI review.
- **ClearCanvas KPI benchmark set (2026-04-20 → 05):** `docs/plans/clear-canvas/*`, `docs/analysis/CLEARCANVAS_KPI_MAPPING`. Origin of the KPI catalog; **superseded** by `FAST_VIEWER_KPI_CATALOG.md` + `CURRENT_KPIS_v2.3.6.md`.
- **MPR open-freeze (2026-06-27):** `docs/plans/performance/MPR_OPEN_FREEZE_OPTIMIZATION_PLAN_2026-06-27.md`. L1 deferred-3D shipped default-on; L2 progressive-2D + off-thread volume build **staged**.
- **Zeta Download Manager review (2026-05-24):** `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN`. Most fixes shipped; residual steps test-gated.
- **Per-fix reliability reports (2026-06):** drag-drop thrash, viewport loading lifecycle, canonical-disk-complete, resume-settle, grow-displayed-to-disk, multi-study identity/grouping review. All **shipped default-on**; their behaviors are the ones the lifecycle refactor will *absorb into one authority*.
- **Standards:** `docs/performance/FAST_VIEWER_KPI_CATALOG.md`, `docs/plans/performance/CURRENT_KPIS_v2.3.6.md` — the KPI source of truth (§13).
- **Tooling:** `tools/performance/kpi_session_report.py` + `kpi_targets.py` (read-only session analyzer, Phase 0), `stall_correlation_report.py`.

---

## 4. Current architecture map (Deliverable 3)

### 4.1 Patient-load pipeline, as actually built

```
                    ┌─────────────────────────────────────────────┐
   user click ──▶   │ HOME PANEL  (_hp_search / _hp_series /       │
                    │             _hp_patient_open / _hp_modules)  │
                    │  • debounced single vs double click          │
                    │  • right-panel thumbnail fetch (asyncio)     │  ← Seam A wired here
                    │  • study-set resolution + download enqueue   │    (lifecycle shadow + cutover)
                    └───────┬─────────────────────┬────────────────┘
                            │ (Qt signals)        │ (add_downloads)
                            ▼                     ▼
        ┌───────────────────────────┐   ┌──────────────────────────────┐
        │ DOWNLOAD MANAGER (zeta)   │   │ PATIENT TAB / VIEWER          │
        │  • subprocess + sockets   │   │  • thumbnail sidebar          │
        │  • per-series progress    │   │  • progressive grow           │
        │  • writes .dcm to disk    │   │  • viewport population        │
        └───────────┬───────────────┘   └───────────────┬──────────────┘
                    │  on_series_progress/completed      │  awaiting/grow
                    └────────► home_download_service ◄────┘  ← Seam B wired here
                              (DM → widget BRIDGE, keyed to ONE study_uid)   ← Seam C tap in _vc_progressive
```

**The structural defect visible in the diagram:** the DM→viewer bridge is keyed to one primary
`study_uid`; the home-panel fetch is a cancellable fire-and-forget task; neither owns a durable "this
study reached displayed-complete" contract. Every subsystem *hopes* its signal lands. There is **no
stage that asserts the study is displayed-complete** — the pipeline runs out of events.

### 4.2 The eight stages and where each can silently stop

| # | Stage | Owner today | Completion signal | Silent-stop risk |
|---|---|---|---|---|
| 1 | Click disambiguation | `patient_table_widget`, `_hp_series` | timer fires | debounce dropped under load |
| 2 | Study-set resolution | `_hp_patient_open`, `patient_study_set` | function returns | mostly deterministic |
| 3 | Right-panel thumbnail fetch | `show_patient_studies` (`_hp_search`) | `right_panel_display_done` | **≥9 early returns; 3 silent drops** |
| 4 | Series discovery / metadata | `_get_or_fetch_series_info` | dict returned | stale-token discard |
| 5 | Download (per series) | Zeta DM subprocess | `on_series_completed` | subprocess spawn crash; response desync |
| 6 | DM→viewer progress bridge | `home_download_service` | `series_images_progress.emit` | **secondary-study key → `sn=None` → dropped** |
| 7 | Progressive grow / populate | `_vc_progressive` | `DISPLAYED_COMPLETE` (implicit) | grow event never arrives → timer backstop |
| 8 | Backstop reconcile | `_dl_watchdog_tick` (GUI-thread QTimer) | resume/grow | starved by GUI stalls; self-stops if `awaiting` cleared early |

### 4.3 The three execution domains (must stay separate)

Fast (`pydicom_qt`, 2D, no VTK render windows) · Advanced (`vtk_simpleitk`) · VTK modules (MPR, Dental
Curve MPR, Advanced Analysis, Orthogonal MPR). Each owns its own decode/cache/render/lifecycle/state.
The lifecycle controller (§5, when built) lives in the **read-only trunk** and only *calls* each
domain — it never couples them.

---

## 5. Per-pipeline current state (Deliverable 3, A–H)

### A. Application startup
**State:** the two largest one-time freezes are `add_AIPacs_tab` building the whole
`ControlPanelInterface` (AIPacs + EchoMind) synchronously (~1.4 s) plus theme `apply_modern_style`
(~2.5 s). **Assessed, not optimized** (P1.4). Lower during-use value (one-time at launch, not during
reading), higher risk (tab presence, `control_panel` deps, EchoMind init). Recommendation: defer
EchoMind CommandBus registration specifically, not the whole tab. → backlog **OPT-12**.

### B. Patient opening
**State:** works ~80% of the time; ~20% leaves a study partial until reopen — the machine-dependent
flakiness. Fully mapped in §4. The pure lifecycle model exists; Seam A (thumbnail token-stale render)
shipped default-on but unverified. The full deterministic cutover is **not** done. → **OPT-02, OPT-04**.

### C. Thumbnail pipeline
**State below the socket = reliable** (`socket_done = display_input = display_done`, 72=72=72). The loss
is entirely upstream: a fetch is cancelled (`CancelledError` bypasses `except Exception` → 29
unaccounted starts) or discarded on a stale token (18). "Only the first thumbnail" = a *partial* cache
set renders first, and the full-set fetch that would replace it is the one dropped, with **no
reconciliation back to the full set**. Canonical disk path + memory-first store are sound
(`docs/pipelines/thumbnail-pipeline.md`). → **OPT-02** (Seam A) and **OPT-04** (render-from-model).

### D. Current exam vs Previous Exam loading
**State:** they use **different event paths** — this is the core "works here / fails there." A previous
exam is a *different* `study_uid`; the DM→viewer bridge is keyed to the primary `study_uid`, so
secondary-study progress arrives with `uid != study_uid` and is dropped (`sn=None`, 200
`GROW-LANE-TRACE resolved=None`). The first image shows; the rest download to disk unseen; a **second
drag** re-registers awaiting after files are on disk and reads the complete set. Seam B (watchdog
keep-alive) shipped default-on but unverified; the real fix is re-keying the bridge by canonical
identity. → **OPT-03** (Seam B verify), **OPT-04/OPT-06** (canonical-identity DM adapter).

### E. Drag and drop
**State:** folded into the unified view-intent pipeline (first-image prime, view-intent coalescing,
complete-on-disk skip, disk-ready resume). Multiple historically-competing paths were consolidated onto
`_coalesce_dm_view_intent` + the shared authority. Remaining risk is the same secondary-study grow gap
(D) and the GUI-thread amplifier widening the drop→grow race. Drag KPIs still FAIL at the tail (§13). →
**OPT-01, OPT-04**.

### F. Cache architecture
**State:** disk is the single source of truth (canonical `SOURCE_PATH/<study_uid>/<orig_series>` +
`THUMBNAIL_PATH/<study_uid>/<series>.png`), atomic writes, resume rejects partials. The competing
*state* is not on disk but in **notifications vs memory flags** (`_thumbnail_fetch_token`,
`_awaiting_series_number`, primary-bound bridge) that can disagree with disk. The lifecycle model makes
disk authoritative for existence and reduces the in-memory gates to one identity-keyed model. Server
`expected` count (never disk-derived) stays the completeness authority. → **OPT-04**.

### G. Decode and rendering
**State: HEALTHY — do not optimize.** decode p50 ≈ 4.5 ms, TTFI p50 ≈ 19 ms, frame ≈ 16 ms, scroll fast.
Multi-frame/cine decode implemented (needs live verify, **OPT-13**). The pipeline below the socket and
the DICOM/decode/geometry layers are proven sound and must not be touched by reliability work.

### H. UI thread and responsiveness
**State: the #1 problem.** Synchronous disk I/O (manifest `Path.iterdir()` walk) + per-study DB status
checks run **on the GUI thread** during DM/patient-table refresh. 63 stalls >100 ms in 20 min (07-01
local); 10,105 stalls, max 48 s, on the reporting PC. P1.1–P1.3 removed the thumbnail-save, status-
refresh, and sidebar-build stalls; the manifest scan, DM table rebuild, GC pauses, and subprocess spawn
remain. → **OPT-01** (the amplifier).

---

## 6. Document ↔ code reconciliation matrix (Deliverable 2)

Each row is a distinct optimization/reliability concern, classified by the required states. **Code is
authoritative for status.**

| Concern | Planned in | Code reality (2026-07-03) | Class |
|---|---|---|---|
| Async thumbnail disk save off GUI thread | UNIFIED P1.1 | `AIPACS_THUMB_SAVE_ASYNC` default-on, in code, live-verified | **COMPLETED** |
| Chunked DM status refresh | UNIFIED P1.2 | `AIPACS_STATUS_REFRESH_CHUNKED` default-on, in code, offscreen-verified | **COMPLETED** |
| Chunked single-study sidebar build | UNIFIED P1.3 | `AIPACS_SIDEBAR_BUILD_CHUNKED` default-on, in code, visual-verified | **COMPLETED** |
| KPI session analyzer + flag registry | UNIFIED P0 | `tools/performance/kpi_session_report.py` + `kpi_targets.py` + registry doc exist | **COMPLETED** |
| Lifecycle pure core (identity model + reconcile) | RELIABILITY §6, §10 | `PacsClient/utils/patient_load_lifecycle.py`, 15 tests green, additive | **COMPLETED (core only)** |
| Lifecycle shadow telemetry | RELIABILITY §7.1 | `lifecycle_shadow.py`, `AIPACS_LIFECYCLE_THUMBS` default-on | **COMPLETED (telemetry)** |
| Seam A: thumbnail token-stale render from model | deploy 07-03 | `_hp_search.py`, `AIPACS_LIFECYCLE_THUMBS_ACTIVE` default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Seam B: previous-exam grow watchdog keep-alive | deploy 07-03 | `home_download_service.py`, `AIPACS_LIFECYCLE_GROW_ACTIVE` default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Retry-exhausted → FAILED terminal tap | deploy 07-03 | `series_intent_coordinator.py` (+mirror) | **IMPLEMENTED — UNVERIFIED (live)** |
| Main-thread blocking — manifest scan / DM rebuild / GC off thread | KPI review §3; RELIABILITY §7.3 | NOT started (beyond P1.1–P1.3) | **PARTIAL / NOT STARTED** |
| Full Stage-1 cutover (render-from-model; DM re-key; convergence sweep off-GUI replaces watchdog) | RELIABILITY §7.2 | Shadow only; cutover not done | **DEFERRED (staged, high-risk)** |
| Startup `add_AIPacs_tab` / EchoMind init defer | UNIFIED P1.4 | Assessed only | **DEFERRED** |
| Multi-study A2 live secondary progress bridge | MULTISTUDY 06-30 | Watchdog-grow shipped; live bridge not | **PARTIAL (subsumed by OPT-04)** |
| Multi-study B1 Series 100000 (DICOMized doc) offset-key | MULTISTUDY 06-30 | Not resolved | **NOT STARTED** |
| Dental VTK-MPR geometry parity default | UNIFIED 1b; registry | Code default **OFF**; `CLAUDE.md` says ON | **REGRESSED / DOC-DIVERGENCE** |
| Geometry hardening T1 (IPP-spacing invariant) | GEOMETRY 06-14 | Shipped + guard test | **COMPLETED** |
| Geometry T2/T3 (persist spacing/photometric; DB metadata path ~1424 ms) | GEOMETRY 06-14 | Staged; needs golden-compare | **DEFERRED (high-risk)** |
| MPR open-freeze L1 deferred-3D | MPR 06-27 | Shipped default-on | **COMPLETED** |
| MPR open-freeze L2 progressive-2D / off-thread volume | MPR 06-27 | Design-only | **DEFERRED** |
| Cine / multi-frame decode + playback | DICOM_COMPLEX 07-01 | Implemented default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Download subprocess spawn access violation | RELIABILITY §7.4 | Tracked; not fixed | **REGRESSION / NOT STARTED** |
| Log hygiene (WARNING telemetry; 13 MB record; mismatch spam) | UNIFIED P3.2; KPI §4 | Not done | **NOT STARTED (low-risk)** |
| Flag collapse (verified default-on kill switches) | UNIFIED P4.1 | `AIPACS_DISK_COUNT_CANONICAL` collapsed (template); rest pending | **PARTIAL** |
| CLAUDE.md reconciliation (retired flags) | UNIFIED P4.3 | Not done | **NOT STARTED (low-risk)** |
| CPU/GPU runtime sampling | KPI §4 | Instrumentation gap | **NEEDS INSTRUMENTATION** |
| EchoMind prompt safety | UNIFIED P4.2 | Audit, unfixed | **NOT STARTED (out of core perf scope)** |

**Duplicated concerns merged:** "previous-exam won't grow," "canonical-disk-complete," "resume-settle,"
"grow-displayed-to-disk," and "A2 live bridge" are **one problem** (secondary-study completion by
convergence). They are consolidated into **OPT-04**; the individual shipped fixes are the *interim
compensations* the lifecycle authority will absorb and let us delete.

---

## 7. Completed & verified optimizations (Deliverable 4) — do not re-touch

- **Main-thread P1.1/P1.2/P1.3** — async thumbnail save, chunked status refresh, chunked sidebar build
  (all default-on, verified). `save_thumbnail`, `refresh_download_statuses`, `build_local_manifest`,
  `_pw_thumbnails`, `_pw_panels` all absent from stall traces after the fix.
- **KPI Phase 0** — read-only session analyzer + thresholds table + flag registry.
- **Multi-study Stage A1** — canonical on-disk count for offset display keys (flag collapsed to
  unconditional) + A1 watchdog `force_reload=True`. Live-verified on patient 48695.
- **Geometry hardening T1** — IPP-spacing invariant guard.
- **DM dedup** (phantom count inflation) — user-confirmed.
- **FAST viewer stabilization + grow batching + render-clock hardening** (May) — guards in place.
- **MPR open-freeze L1** deferred-3D; **Curved/Dental MPR safety** (teardown/UAF, deleted-object swallow,
  2D-mouse, WL inherit, robust WL, panoramic quality, FAST→VTK pick, in-place result).
- **MPR annotation** slice-binding + viewport-scoped targeting + click-to-activate.
- **Single-instance takeover, attachment local-first, voice keep-on-close, import-opens-FAST,
  drag-drop view-intent coalescing / first-image prime / complete-on-disk skip** — shipped.

---

## 8. Partially completed / implemented-but-unverified (Deliverable 5)

| Item | What's done | What's missing |
|---|---|---|
| **Lifecycle refactor** | Pure core + shadow + Seam A/B cutovers + failure tap, all default-on | Live source-build verification; full cutover (render-from-model, DM re-key, off-GUI convergence sweep) |
| **Main-thread de-blocking** | P1.1–P1.3 (three stall sources removed) | Manifest scan, DM table rebuild, GC pause, subprocess spawn still on GUI thread; startup (P1.4) |
| **Multi-study secondary completion** | A1 (post-settle grow), watchdog keep-alive | Grow *during* download (live secondary bridge, A2); B1 Series-100000 doc |
| **Geometry** | T1 invariant | T2 (persist spacing/photometric), T3 (DB metadata path for ~1424 ms) — golden-compare gated |
| **Cine / multi-frame** | Decode + playback default-on | Live verify with real cine/US/XA data |
| **Flag collapse** | 1 flag collapsed (template) | ~40+ verified default-on kill switches remain |

---

## 9. Canonical optimization backlog (Deliverables 6 + 7)

One unified, risk-ranked backlog. Priority score ≈ **(Benefit × Confidence) ÷ (Risk × Complexity)**.
States: VERIFIED-COMPLETE · COMPLETE-MONITOR · PARTIAL · READY-SAFE · IMPL-UNVERIFIED · NEEDS-INSTRUMENTATION
· HIGH-RISK-DEFERRED · REGRESSION · OBSOLETE.

| ID | Problem | Pipeline | Evidence | Code status | Benefit | Risk | Cmplx | State | Priority |
|---|---|---|---|---|---|---|---|---|---|
| **OPT-02** | Seam A: verify thumbnail token-stale render-from-model (kills "only first thumbnail") | C | 18 stale + 29 unaccounted; shipped 07-03 | `_hp_search.py` default-on | High reliab | Med (default-on, unverified) | Low | **IMPL-UNVERIFIED** | **P0** |
| **OPT-03** | Seam B: verify previous-exam grow keep-alive (kills "second drag needed") | D | 200 `resolved=None`; shipped 07-03 | `home_download_service.py` default-on | High reliab | Med | Low | **IMPL-UNVERIFIED** | **P0** |
| **OPT-01** | Move manifest scan / DM rebuild / GC off the GUI thread (the amplifier) | H | 10,105 stalls, max 48 s; `build_local_manifest` iterdir on GUI thread | P1.1–1.3 + status-refresh dicom-only (`AIPACS_STATUS_REFRESH_DICOM_ONLY`, live-validated) + startup theme dedup (`AIPACS_THEME_APPLY_DEDUP`: patient-search + mainwindow + control-panel `AIPacs_ui`) + license defer (`AIPACS_DEFER_LICENSE_INFO`) done; tab-construction/EchoMind init (P1.4) / DM rebuild not | Very high (fixes 20% + drag) | Med | Med | **PARTIAL** | **P1** |
| **OPT-09** | Log hygiene: download telemetry off WARNING; 13 MB single-record cap; throttle geometry-mismatch | — | 17 k WARNING/run bury 13 real errors | Not done | Med (observability) | **Low** | Low | **READY-SAFE** | **P1** |
| **OPT-14** | Reconcile `CLAUDE.md` with code (retired flags, `AIPACS_DENTAL_VTK_MPR` note) | — | registry §21 divergences | Not done | Med (maintainability) | **Low** | Low | **READY-SAFE** | **P1** |
| **OPT-05** | Download subprocess spawn access violation (pickle into child) | E | `native_fault.log` `download_process_worker.py:148` | Tracked | High (session stability) | Med | Med | **REGRESSION** | **P1** |
| **OPT-13** | Live-verify cine / multi-frame decode + playback | G | implemented; no cine data exercised | default-on | Low-Med | Low | Low | **IMPL-UNVERIFIED** | **P2** |
| **OPT-08** | Resolve Dental VTK-MPR default (doc ON vs code OFF) + geometry parity | D/geom | registry 🔴 row | code default-OFF | Med (dental correctness) | **High (geometry, clinical)** | Med | **REGRESSION/DIVERGENCE** | **P2** |
| **OPT-04** | Full Stage-1 lifecycle cutover: sidebar renders from model; DM re-key by canonical identity; off-GUI convergence sweep replaces `_dl_watchdog_tick`+resume+grow | B/C/D/F | the whole §4 defect | shadow only | **Very high (determinism)** | **High** | High | **HIGH-RISK-DEFERRED** (decompose) | **P2 (staged)** |
| **OPT-06** | Multi-study A2 live secondary progress bridge (grow during download) | D | subsumed by OPT-04 DM re-key | staged | High | Med-High | Med | **PARTIAL** | **P2 (via OPT-04)** |
| **OPT-07** | Multi-study B1 Series 100000 (DICOMized document) offset-key resolution | D | STAGED in MULTISTUDY 06-30 | not started | Low-Med | Med | Med | **NOT STARTED** | **P3** |
| **OPT-12** | Startup: defer EchoMind CommandBus init off `add_AIPacs_tab` critical path | A | ~1.4 s tab + ~2.5 s theme at launch | assessed | Med (one-time) | Med | Med | **DEFERRED** | **P3** |
| **OPT-10** | Geometry T2/T3: persist spacing/photometric; DB metadata path (~1424 ms H1) | G/geom | GEOMETRY 06-14 | staged | Med (latency) | **High (every render)** | High | **HIGH-RISK-DEFERRED** | **P3 (golden-compare gate)** |
| **OPT-11** | Collapse verified default-on kill switches (one at a time, post-verify) | — | ~40+ flags; `CLAUDE.md` directive | 1 collapsed | Med (maintainability) | Med (per-flag) | Med | **PARTIAL** | **P3 (continuous)** |
| **OPT-16** | Add CPU/GPU runtime sampling to live logs | — | KPI §4 gap | none | Low (visibility) | Low | Low | **NEEDS-INSTRUMENTATION** | **P3** |
| **OPT-15** | EchoMind prompt safety (legacy "exaggeration", correction schema, modality match, temp/max_tokens) | — | UNIFIED P4.2 | audit | Med (output quality) | Med | Med | **NOT STARTED** | **P3 (separate track)** |

---

## 10. Next safe optimization phase (Deliverable 9)

**Principle:** do not start with the largest/most invasive item (OPT-04). Start with high-value, safe,
easily-validated work that cannot damage working systems. The next phase is **verification + low-risk
hygiene**, which also *earns the evidence* required to safely attempt OPT-04.

### Phase N (next) — three parallel, low-blast-radius workstreams

**N-1 — Live-verify what already shipped (OPT-02, OPT-03, OPT-13).** No new code.
- *Exact problem:* Seam A/B cutovers and cine are default-on but unverified on a live source build.
- *Code path:* `_hp_search.py` (Seam A), `home_download_service.py` (Seam B), the FAST cine engine.
- *Why unresolved:* shipped 07-03 as a test build; the reporting PC run is the acceptance step.
- *Method:* on the reporting workstation, with fresh logs, follow the deploy record's post-deploy plan —
  open multi-study / previous-exam patients on a poor link; confirm `[LIFECYCLE] …->thumbs_ready`,
  `[LIFECYCLE-CUTOVER] rendered token-stale ACTIVE` (rapid A→B→A), `seam_b watchdog kept alive`, rising
  `watchdog_grow`, and previous-exam series finishing **without a second drag**.
- *Must not change:* nothing — verification only.
- *Instrumentation:* the shipped `[LIFECYCLE*]` markers + the KPI analyzer.
- *Acceptance:* invariants 1–4 (§12.3) hold across ≥100 patients incl. several previous-exam cases;
  zero reopens, zero second-drags; no wrong-study display; stalls not worse than the 07-03 baseline.
- *Rollback:* `AIPACS_LIFECYCLE_THUMBS_ACTIVE=0` / `AIPACS_LIFECYCLE_GROW_ACTIVE=0` → byte-identical
  legacy; keep the prior installer available.

**N-2 — Log hygiene + doc reconciliation (OPT-09, OPT-14).** Read-only-ish, near-zero clinical risk.
- *Exact problem:* `download_diagnostics.log` is ~99% WARNING (17 k lines) burying 13 real socket
  errors; a single 13 MB log record is a main-thread write hazard; `CLAUDE.md` cites retired flags and a
  wrong `AIPACS_DENTAL_VTK_MPR` default.
- *Code path:* the log formatter / `log_stage_timing` channel; `diagnostic_logging.py`; `CLAUDE.md`.
- *Why unresolved:* never scheduled; low urgency vs reliability.
- *Proposed correction:* move download stage-timing/progress telemetry from WARNING to an INFO/diag
  channel; add a byte-length cap in the formatter (truncate + flag oversized records); throttle repeat
  `FAST_GEOMETRY_ORDER_MISMATCH` to once/series; correct the `CLAUDE.md` flag notes.
- *Why safe:* changes log routing/formatting only; preserves every useful marker (stall probe, stage
  timing, `[KPI]`, `VIEWPORT_LIFECYCLE`).
- *Must not change:* the diagnostic markers themselves, or `dicom.db`.
- *Acceptance:* no log file ≥90% WARNING; no single record > ~256 KB; the 13 real errors visible; guard
  test on a fixture log.
- *Rollback:* revert the formatter/routing change; docs are text-only.

**N-3 — Subprocess spawn hardening (OPT-05).** Contained stability fix.
- *Exact problem:* `access violation` while pickling args to spawn the download subprocess
  (`download_process_worker.py:148` → `popen_spawn_win32 → reduction.dump`).
- *Why unresolved:* intermittent; surfaced only in the 07-02 review's `native_fault.log`.
- *Proposed correction:* audit exactly what is pickled into the child; ensure only picklable, fully-
  constructed data crosses; guard the spawn against racing teardown; confirm the pre-warm note does not
  spawn during teardown.
- *Why safe:* touches only the spawn arg construction/guard, not the download protocol or disk writes.
- *Acceptance:* no `native_fault.log` access violation across a stress session of repeated
  open/download/close; download throughput unchanged.
- *Rollback:* revert the guard; behavior returns to prior spawn.

**Only after N-1 passes** do we attempt **OPT-01** (broaden off-thread work — the amplifier) and then the
decomposed **OPT-04** cutover. OPT-01 is sequenced first because §3.4/§6.7 of the reliability review make
clear that even a perfect state machine "feels broken behind a 48 s freeze" — removing the amplifier is a
prerequisite for the cutover to show its value.

### OPT-04 decomposition (when reached — never one change)

1. Thumbnail sidebar renders from the model (kills Problem #1; smallest blast radius) — shadow-agreement
   gate first, then cut over.
2. DM adapter re-keyed to canonical `(study_uid, orig_series, series_uid)` (previous-exam first-class;
   delete the `sn is None` drop + sibling lane) — this *is* OPT-06.
3. Convergence sweep on a worker replaces `_dl_watchdog_tick` + resume + grow-to-disk; delete the flag
   quartet. Each sub-step independently live-verifiable and reversible.

---

## 11. Risk classification (Deliverable 5 support)

- **LOW** (do freely, guard-tested): OPT-09 log hygiene, OPT-14 doc reconciliation, OPT-16 CPU/GPU
  sampling, most single-flag collapses (OPT-11), the N-1 verification (no code).
- **MEDIUM** (staged, kill switch, fresh-log review): OPT-01 off-thread moves (touch guarded thumbnail/
  multistudy/patient-table paths — honor canonical-path/memory-first/offset-key/gating invariants),
  OPT-05 subprocess spawn, OPT-12 startup defer, OPT-03/OPT-02 already-shipped verification.
- **HIGH** (decompose into observable, reversible sub-phases; never one change): OPT-04 lifecycle
  cutover, OPT-08 dental geometry default flip (clinical-lane golden compare), OPT-10 geometry T2/T3 (DB
  metadata feeds every render — golden-compare before any flip). High-risk items **must not** ship as a
  single large change.

---

## 12. Current bottleneck assessment (Deliverable 8)

1. **Main-thread blocking (H) is the #1 bottleneck and the amplifier of every reliability race.**
   Synchronous manifest disk-walk + per-study DB status on the GUI thread; stalls to 48 s on the loaded
   machine. Everything else (drag lag, dropped fetches, missed grows) is downstream of it. → OPT-01.
2. **Notification-not-convergence completion (B/C/D)** is the #1 *reliability* defect. → OPT-02/03/04.
3. **Not bottlenecks (leave alone):** decode, render/frame, scroll, layout-switch, memory (RSS ~930 MB
   stable). Spending effort here is wasted — the months of decode/render work targeted the wrong path.
4. **Secondary stability risks:** subprocess spawn AV (OPT-05); log bloat obscuring faults (OPT-09);
   dental geometry divergence from the default-OFF VTK-MPR flag (OPT-08).

### 12.3 Determinism invariants (the acceptance bar for reliability, not "usually works")

From the lifecycle log, any run must satisfy:
1. `count(SELECTED) == count(DISPLAYED_COMPLETE) + count(THUMBS_READY[preview]) + count(FAILED[explicit])` — no study vanishes.
2. Every `right_panel_socket_start` has a terminal (`done|error|empty`) — **zero silent drops**.
3. Every `SERIES_LOADING` reaches `FIRST_IMAGE` then `DISPLAYED_COMPLETE` — **zero permanent `awaiting`**.
4. `DISPLAYED_COMPLETE` viewport slice count == canonical on-disk count — **no partial grow**.
5. No state entered twice for one identity — no duplicate execution.

---

## 13. Permanent KPI framework & current baseline (Deliverable 10)

**Source of truth:** `docs/performance/FAST_VIEWER_KPI_CATALOG.md` + `CURRENT_KPIS_v2.3.6.md`.
**Analyzer:** `tools/performance/kpi_session_report.py` (run after every phase, from fresh logs).
Reliability KPIs rank **equal to** speed KPIs — the target is *deterministic behavior across repeated
runs*, never "usually works."

### 13.1 Performance KPIs (baseline = 2026-07-01 authoritative session)

| KPI | Marker | Baseline p50 / p95 / max | Target | Verdict |
|---|---|---|---|---|
| DICOM decode | `[KPI] decode_ms` | 4.5 / 9.4 / 12.0 ms | low | ✅ |
| Time to first image | `[KPI] TTFI total_ms` | 18.8 / 93.2 / 114.4 ms | < 80 ms | ✅ p50 |
| Render frame | `FAST_SET_SLICE_STAGE frame_ms` | 16.1 / 28.7 / 39.2 ms | ~1 frame | ✅ |
| Layout switch → 1st image | `VIEWER_SWITCH total_ms` | 18.8 / 93.2 / 114.4 ms | < 80 ms | ✅ |
| **Drag event interval** | `FAST_DRAG_KPI event_p95_ms` | 157.7 / 454.8 / 725.2 ms | **< 120 ms** | ❌ |
| **Drag UI lag** | `FAST_DRAG_KPI ui_lag_max_ms` | 216.3 / 943.2 / 1054.6 ms | **< 200 ms** | ❌ |
| **Main-thread stalls** | `MAIN_THREAD_STALL stall_duration_ms` | 175.5 / 548.5 / 1421.2 ms; 63 > 100 ms / 20 min | **0 during interaction** | ❌ |
| Process RSS | `rss_mb` | ~930 MB stable | bounded | ✅ |
| CPU / GPU | — | not sampled | — | ⛔ gap (OPT-16) |

**Reporting-PC reference (worst observed, 2026-07-02):** main-thread stalls **10,105** ≥100 ms, p99
1,243 ms, **max 48,387 ms**, 23 ≥5 s. Local control same-code: 741 stalls, max 9,684 ms. The gap between
these two on identical code *is* the 80/20.

**Current-run spot check (2026-07-03 `viewer_diagnostics.log`):** drag `event_p95` sample p50 ≈ 95 ms,
max ≈ 840 ms (n=346) — tail still elevated (OPT-01 open). `MAIN_THREAD_STALL` count 0 in the current
`app.log`/`viewer_diagnostics.log`, but the stall-trace flags (`AIPACS_MAIN_THREAD_TRACE`) are default-OFF
and the probe may not have emitted this run → **treat as "not measured," not "improved."** Re-run the
analyzer with the probe enabled to refresh this baseline (fresh-log discipline, §14).

### 13.2 Reliability KPIs (the equal-weight half)

| Reliability KPI | Marker / source | Target |
|---|---|---|
| Thumbnail completion success rate | socket_start → terminal; full-set render | **100%**, zero silent drops |
| Viewport grow-up success rate | `SERIES_LOADING → DISPLAYED_COMPLETE` | **100%** on first drag |
| Patient-open success rate | `SELECTED → DISPLAYED_COMPLETE/THUMBS_READY` | **100%**, zero manual reopen |
| Silent-drop count | 29 unaccounted (07-02) | **0** |
| Lost grow notifications | 200 `GROW-LANE-TRACE resolved=None` | **0** |
| Duplicate execution | double-spelled traces; re-entered pipeline | **0** |
| Determinism under injected stall | §12.3 invariants with vs without stalls | identical (latency may rise) |

---

## 14. Fresh-log discipline (Deliverable 9 / Phase 9)

Historical logs explain *past* failures; **current** decisions use fresh logs from the current build.
Do not let resolved problems dominate the plan. After each implementation phase:

1. Rotate/clear the relevant dev logs (`user_data/logs/`).
2. Run a defined scenario (source build; multi-study + previous-exam patients; the `aipacs-control` MCP
   harness where possible for repeatability).
3. Run `tools/performance/kpi_session_report.py` on the fresh logs.
4. Compare the KPI panel + reliability invariants to the §13 baseline.
5. Confirm no regression (viewer/geometry/isolation guard suites green).
6. **Update this document** (§9 states, §13 baseline, §15 history).

Two testing lanes (see `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`): the **verify lane**
(offscreen pytest in the sandbox — pure/Qt-offscreen, pre-merge gate) and the **clinical lane** (Windows
source build — the only lane that proves GUI/render/clinical behavior; human-assisted bootstrap default).

---

## 15. Validation & regression history (living log)

| Date | Change | KPI/reliability before | After | Regression check | Result |
|---|---|---|---|---|---|
| 2026-07-01 | KPI Phase 0 analyzer + flag registry | fragmented scratch scripts | one report generator + thresholds | guard test on fixture | ✅ read-only |
| 2026-07-01 | P1.1 async thumbnail save | `save_thumbnail` in stall traces | absent from traces (pid 193028) | offscreen + live | ✅ |
| 2026-07-01 | P1.2 chunked status refresh | `refresh_download_statuses` stalls | cooperative chunk, no threads | offscreen | ✅ |
| 2026-07-01 | P1.3 chunked sidebar build | single-study build stall | progressive build | source-build visual | ✅ |
| 2026-07-02 | Lifecycle pure core (additive) | n/a | 15 invariant tests green | offscreen | ✅ additive, no runtime change |
| 2026-07-03 | Shadow + Seam A/B cutovers + failure tap (default-on) | 80/20 flakiness | model holds parked data; seams active | 359 pass/1 skip (3 pre-existing unrelated); live sanam max stall 4.8 s | ✅ gate PASSED; **live cutover verify pending** |
| 2026-07-03 | OPT-01 status-refresh dicom-only trim (`AIPACS_STATUS_REFRESH_DICOM_ONLY`, default-on) | per-row `os.walk`(attachments)+2 DB queries on GUI thread each refresh | only `dicom` flag re-read; attachment/DB flags kept cached | py_compile OK; 13 offscreen tests green (`test_status_refresh_dicom_only` + sibling P1.2); no test pins old behavior | ✅ offscreen; **live-verify pending** (fresh probe run). Report: `docs/reports/OPT-01_STATUS_REFRESH_DICOM_ONLY_2026-07-03.md` |
| 2026-07-03 | OPT-01 **live-verified** via probe run (`AIPACS_MAIN_THREAD_TRACE=1`, session `sess-4e53e3d33995`, pid 38204) | 07-01 baseline: 63 stalls/20 min, status-refresh + `build_local_manifest` in stall stacks | run: **35 stalls, p50 200 / p95 1023 / max ~3140 ms**; status-refresh / `_compute_local_status_flags` / attachment-`os.walk` / manifest = **ABSENT from all traces** (0 lines) — `TABLE_REFRESH` correlation now coincidental (stacks prove it) | 0 errors from the changed functions; lifecycle shadow active (`grow_lane_drop`=116, `watchdog_grow`=24) | ✅ **OPT-01 status path validated.** New top freezes shifted to STARTUP: `apply_theme`/`_apply_field_styling` (~2.3 s), `add_AIPacs_tab`/`_wrap_home_tripane_in_splitter` (~1.3 s), thumbnail-widget build (~0.3 s) → OPT-12/P1.4 |
| 2026-07-03 | OPT-01 startup theme dedup (`AIPACS_THEME_APPLY_DEDUP`, default-on) | `PatientSearchWidget.apply_theme` re-styled 11 fields × ~15 `setStyleSheet` several times/launch (~2.3 s startup stall) | idempotent skip of identical-theme re-apply | py_compile OK; 20 offscreen tests green (`test_theme_apply_dedup` + OPT-01 + P1.2) | ✅ offscreen; **live-verify pending** (re-run probe → `apply_theme` should drop from startup traces). Report: `docs/reports/OPT-01_THEME_APPLY_DEDUP_2026-07-03.md` |
| 2026-07-04 | **Reliability/clinical: wrong-study load fix** (`AIPACS_PRIMARY_SERIES_POISON_GUARD`, default-on) | patient 48912: loading previous-exam 29694 series 4 then current series 4 re-displayed the PREVIOUS study's series 4 (log: `rebind_to_series=1000004`, `open_series path=<previous>/4`) | plain (<1M) key now re-resolves to its own primary `study_uid` folder when a poisoned tab path (previous-exam study) collides on the same series number | py_compile OK; 7 offscreen tests green (`test_primary_series_poison_guard`); pre-existing PySide6-missing errors in sibling tests unrelated | ✅ **LIVE-VERIFIED on 48912 (2026-07-04, user-confirmed)** — current series 4 now loads from the current study. HIGH severity (cross-study display). Kill switch RETAINED (clinical fix; collapse deferred until more clinical mileage). Deeper audit: the guard is the primary key's counterpart to the existing offset-key fallback (`_vc_load.py:476`); resolver now symmetric. Report: `docs/reports/WRONG_STUDY_PRIMARY_SERIES_AFTER_PREVIOUS_EXAM_2026-07-04.md` |
| 2026-07-04 | OPT-01 control-panel theme dedup (`AIPacs_ui.apply_theme`, shared flag `AIPACS_THEME_APPLY_DEDUP`) | `AIPacs_ui.apply_theme` ~1.4 s startup stall (3rd theme layer; restyles shell + cascades to child widgets) | idempotent skip of identical-theme re-apply (children self-dedup) | py_compile OK; 23 startup/theme/OPT-01 tests + 4 startup-subtiming tests green; `test_apply_theme_call_preserved` still passes | ✅ offscreen; **live-verify pending** (next probe run → `AIPacs_ui.apply_theme` should drop from startup traces) |
| 2026-07-04 | OPT-01 startup fixes **LIVE-VERIFIED** (fresh run `sess-71efc2d063b8`, pid 318112, 84-min session) | apply_modern_styling ~2.3 s, _update_license_info ~1.7 s, _apply_field_styling ~2.3 s, _compute_local_status_flags in startup traces | **ALL FOUR = 0 occurrences** in stall traces (gone). Render healthy: frame p50 17.9/p95 31 ms, TTFI p50 22.8 ms. **Decode cache 100% hit (5560/0).** | no regression | ✅ **startup theme + license + status-refresh fixes confirmed eliminated.** Remaining: stack-drag ui_lag p50 255/p95 849 ms (main-thread contention, not render); NEW targets: `AIPacs_ui.apply_theme` ~1.4 s (another theme layer — same dedup), a 5.9 s + 2.4 s generic `main.py:notify` stall (GC/subprocess-spawn? needs deeper trace; note a 1.4 s `linecache/tokenize` is the trace mechanism itself, not a real app stall) |
| 2026-07-03 | OPT-01 during-use **re-validated** on a later fresh run (`sess-edc3b36c2070`, pid 306988, 23:51–23:53, terminal capture) | — | only **4 main-thread stalls in ~2 min, max 355 ms, 0 ≥1 s**; series 6/16/17/18/19/20 grew 96/96 smoothly | GetReportStatus timeout (report column only, non-blocking) | ✅ during-use rock-solid. NOTE: startup-trace confirmation of increment-3 (mainwindow theme + license defer) still pending a clean-log capture — the sandbox FUSE mount served a STALE cached copy of the big log (showed 22:48 while the app ran at 23:53); use a cleared/backed-up log or read the terminal capture, not the mounted file |
| 2026-07-03 | OPT-01 startup **live-verified (increment 2)** + increment 3 shipped (probe `sess-2f9be9ca545a`, pid 315304) | patient-search `_apply_field_styling` = 2264 ms freeze | `_apply_field_styling` **ABSENT from traces** (theme dedup worked); during-use KPIs healthy (decode p50<1 ms, TTFI p50 43 ms, **drag p95 266 ms** vs 725 baseline). New top startup freezes: `apply_modern_styling` ~2.3 s, `_update_license_info` ~1.7 s, `setupUi` ~1.3 s | — | ✅ increment-2 validated; increments 3 = mainwindow theme dedup (`AIPACS_THEME_APPLY_DEDUP`) + license defer (`AIPACS_DEFER_LICENSE_INFO`), 27 offscreen tests green, **live-verify pending**. Report: `docs/reports/OPT-01_STARTUP_FREEZES_2026-07-03.md` |

**Known pre-existing (unrelated) test failures:** `test_pin_overlay`, `test_vtk_volume_service` (×3) —
confirmed pre-existing via git; not caused by this work.

---

## 16. Permanent update rule

From now on, **every optimization task updates this document** instead of creating a disconnected plan.
After each change record, in §9 and §15: what changed, why, files/modules affected, KPI before/after,
reliability result, regression result, remaining work, new priority order. Per-fix detail lives in the
linked report; the *status* lives here. Fragmented docs remain as historical evidence but this file is
the current source of truth.

---

## 17. Final decision — the safest highest-value remaining work

> **Given everything already attempted and implemented, the safest changes with the greatest
> reliability/stability/performance gain and the least regression risk are, in order:**
>
> 1. **Live-verify the already-shipped Seam A/B cutovers + cine (N-1).** Zero new code, highest
>    reliability payoff — it either confirms the "blank thumbnail / no-grow / 80-20" family is fixed
>    (then collapse the flags) or produces the fresh-log evidence to correct course. Nothing is safer
>    than verifying code that already shipped.
> 2. **Log hygiene + `CLAUDE.md` reconciliation (N-2, OPT-09/OPT-14)** and **subprocess-spawn hardening
>    (N-3, OPT-05)** — low blast radius, immediately improve fault visibility and session stability.
> 3. **Broaden the off-GUI-thread move (OPT-01)** — the manifest scan / DM rebuild / GC. This is the
>    highest-value *performance* item and the prerequisite that makes the reliability cutover meaningful;
>    it is medium-risk, well-scoped, and reuses existing worker/deferred patterns.
> 4. **Only then, the decomposed lifecycle cutover (OPT-04)** — high value, high risk, done as three
>    independently reversible sub-steps behind shadow-agreement gates.
>
> Deliberately **not** next: decode/render optimization (healthy — wasted effort), geometry T2/T3 and the
> dental VTK-MPR flip (high-risk, clinical-lane golden-compare gated), and any large single-shot rewrite.
>
> The goal is not continuous refactoring. It is measurable, monotonic progress toward a **faster, more
> deterministic, more maintainable** application — verified by fresh logs against the §13 baseline after
> every phase.

---

## 18. Linked evidence (historical documents this consolidates)

Root-cause/plan: `docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md` ·
`docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md` ·
`docs/reports/KPI_SESSION_REVIEW_2026-07-01.md` · `docs/reports/deploy-record-workstation-2026-07-03.md`.
Reference/tooling: `docs/reference/AIPACS_FLAG_REGISTRY_2026-07-01.md` ·
`docs/performance/FAST_VIEWER_KPI_CATALOG.md` · `docs/plans/performance/CURRENT_KPIS_v2.3.6.md` ·
`tools/performance/kpi_session_report.py`. Subsystem as-built: `docs/pipelines/thumbnail-pipeline.md` ·
`docs/pipelines/unified-patient-study-pipeline.md` · `docs/plans/VIEWER_GEOMETRY_HARDENING_MASTER_PLAN_2026-06-14.md`
· `docs/plans/performance/MPR_OPEN_FREEZE_OPTIMIZATION_PLAN_2026-06-27.md` ·
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`. P1 reports:
`docs/reports/P1_1..P1_4_*_2026-07-01.md`. Control/testing:
`docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`. Code authorities:
`PacsClient/utils/patient_load_lifecycle.py`, `PacsClient/utils/lifecycle_shadow.py`,
`PacsClient/utils/patient_study_set.py`, `series_display_state.decide_display_action`, `series_completeness`.
