# AI-PACS — Software Optimization, Stability & Reliability Master Plan

**Status:** CANONICAL — this is the single source of truth for optimization, stability, reliability,
and performance work. Every future optimization task extends this document rather than starting a new
disconnected plan.
**Created:** 2026-07-03 (consolidates ~1 month of fragmented optimization work)
**Owner discipline:** code is the source of truth for *implementation status*; docs describe *intent*;
logs/KPIs show *runtime behavior*. All three are reconciled here.

> **UPDATE 2026-07-05 — optimization release SHIPPED (deploy gate PASSED).** The #1 performance target
> — main-thread blocking *during use* — is **RESOLVED and live-verified**: during-use main-thread stalls
> went from the 725 ms baseline (48 s worst-case on the reporting PC) to **0 this release run**, and the
> disk-walk / status-refresh functions are **absent from every stall trace**. Shipped + verified:
> **OPT-01** (status disk-walk TTL cache + refresh-trim, off the GUI thread), **OPT-12** (startup
> single-instance sweep — psutil name-reuse; `:446` stall gone), **OPT-09** (download telemetry log
> hygiene), plus the **multi-study wrong-series clinical fix** (viewport study-identity gate +
> per-series `study_uid`/`series_uid` stamp + primary poison-guard; live-verified on 2 PCs, gate ran with
> 0 wrong-study stomps). **OPT-11:** 7 validated flags collapsed to unconditional (4 non-clinical + 3
> clinical wrong-series). Deploy gate PASSED with owner clinical sign-off — record
> `deploy-record-workstation-2026-07-05.md`. **Still default-OFF pending a live-validation run** (do NOT
> assume active): `AIPACS_FAST_INSTANCE_SWEEP` (safety-critical startup ppid snapshot),
> `AIPACS_STATUS_EXPENSIVE_TTL`, and `AIPACS_LOG_TELEMETRY_DOWNGRADE` effect unconfirmed. **Remaining for
> a future phase:** OPT-04 lifecycle cutover; promote the two default-off flags after validation.
> Per-fix evidence in §15; backlog states in §9.

> **UPDATE 2026-07-06 — OPT-20 "previous-exam series won't display" RESOLVED + shipped default-on; more
> items verified.** The long-running "a previous-exam X-ray/document doesn't render" bug (patients 48456,
> 45289, and the 48912/multi-study family) is **fixed and live-verified**. TRUE root cause: an
> async-apply **render-gate type mismatch** — `_apply_loaded_series_data` (`_vc_load.py`) gated the render
> on `current_idx == series_idx`, comparing a **series NUMBER** (`last_series_show`) to a **list INDEX**
> (`replace_series_data` return). Offset-key previous-exam series (e.g. `2000001`) can never match a small
> index, so the render was always skipped and `_start_qt_viewer` never ran (metadata was fine —
> `[FAST-YIELD-TRACE] will_yield=True`). Fix (`AIPACS_APPLY_RENDER_TARGET_VIEWER`, promoted **default-on**
> after 45289: `[apply-path] target_fix_render=29` renders that the buggy gate would have skipped;
> previous-exam DX/documents now display). Instrumentation kept behind `AIPACS_APPLY_TRACE` (default-off).
> **Honesty note:** this took THREE wrong root-cause calls (contention/OPT-04, then a stale-token "race" +
> a render-convergence retry, then even the right file/wrong line) before per-hop apply instrumentation
> made it undeniable — the "66 display-misses" metric was ALSO false (benign spinner clears). Contention
> (OPT-04) is NOT behind the previous-exam display bug. Also this window: **OPT-09/12/18 VERIFIED-COMPLETE**
> (live), **OPT-06** grow-lane study-scoped bind shipped (mechanism-verified-safe, default-off),
> **OPT-17** cache study-identity shipped. Remaining OPT-20 residuals (rare, P2): a lost worker→UI apply
> post, and a rare empty metadata build. Evidence in §15; backlog in §9.

> **UPDATE 2026-07-07 — OPT-20 slot-3 residual ROOT-CAUSED + fixed default-on (multi-study display-miss).**
> The 49317 residual where distinct SECONDARY-study series (`3000001`/`3000002`) never displayed while
> slot-2 (`2000001`) did is now a **deterministic, static-analysis root cause** (not the token race — ruled
> out: `[APPLY-STALE-EARLY]=0` and same-UI-thread ⇒ token current at both gates). Cause:
> `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py`) had a **study-blind name+count dedup** — a series
> sharing a `series_name` **and** instance count with an already-present series hit `return False` and was
> **never appended**, even when its `series_number` was DIFFERENT. For a multi-study / previous-exam patient
> two studies routinely share a name (scout/localizer/DX/same-protocol repeat), so the distinct secondary
> series was dropped → `replace_series_data` returned **-1** → the async apply render loop was gated off
> (`series_idx < 0`, no `[APPLY-GATE]`) → the series never displayed. Fix (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`,
> **default on**; `=0` = byte-identical legacy): only skip as a TRUE duplicate when the incoming
> `series_number` is already present; a distinct, not-yet-present number is appended (same end-append the
> different-count pairing path already used — no ordering change for any working case). **Isolation
> untouched** — each series keeps its own offset number + stamped `study_uid`/`series_uid`, and the
> viewport identity gate (fail-closed on `series_uid`) still blocks any cross-exam paint. Verified against
> the REAL method (8/8 headless checks incl. `replace_series_data` now returns ≥0). Residual `1100000`
> (DICOMized document, `[APPLY-ENTER]=0`) is a distinct path = **OPT-07** document handling, not this gate.
> Evidence in §15; backlog in §9. **NEEDS live source-build verify on 49317** (drag every series of both
> studies → all display; 0 `[IDENTITY-GATE] SKIP`).

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
| **OPT-03** | Seam B: previous-exam grow keep-alive (kills "second drag needed") | D | 200 `resolved=None`; shipped 07-03 | `home_download_service.py` default-on | High reliab | Med | Low | **VERIFY FAILED 2026-07-05** (sess-11818cd24bf6): grow-lane `resolved=None` for prev-exam series 202 but seam_b nudge fired 0x — the nudge sits DOWNSTREAM of the primary-`study_uid` filter that drops SECONDARY-study progress, so it only ever covers the primary study. Series 202 crawled 40->58/256 via the disk-readiness resume fallback = "needs a 2nd nudge". PROPER FIX SHIPPED as **OPT-06** (study-scoped `(study_uid, series_number)` grow-lane fallback, `AIPACS_GROW_LANE_STUDY_NUMBER_BIND` default-OFF, 9/9 guard-test green) — OPT-03's seam becomes redundant once OPT-06 verifies. Same multi-study offset-key family as **OPT-20** (but OPT-20 is the initial `change_series` LOAD path, a different resolution — OPT-06 does not automatically close it) | **P1 (→ OPT-06)** |
| **OPT-01** | Move manifest scan / DM rebuild / GC off the GUI thread (the amplifier) | H | 10,105 stalls, max 48 s; `build_local_manifest` iterdir on GUI thread | P1.1–1.3 + status-refresh dicom-only (`AIPACS_STATUS_REFRESH_DICOM_ONLY`, live-validated) + startup theme dedup (`AIPACS_THEME_APPLY_DEDUP`: patient-search + mainwindow + control-panel `AIPacs_ui`) + license defer (`AIPACS_DEFER_LICENSE_INFO`) done; tab-construction/EchoMind init (P1.4) / DM rebuild not | Very high (fixes 20% + drag) | Med | Med | **VERIFIED-COMPLETE** (during-use; startup OPT-12) | **DONE 07-05** |
| **OPT-09** | Log hygiene: download telemetry off WARNING; 13 MB single-record cap; throttle geometry-mismatch | — | 17 k WARNING/run bury 13 real errors | Shipped default-on 07-05 (`AIPACS_LOG_TELEMETRY_DOWNGRADE`) | Med (observability) | **Low** | Low | **VERIFIED-COMPLETE 2026-07-05** (live run sess-…416036: **+753 INFO / +295 WARNING / +9 ERROR** this run — telemetry relabelled to INFO, down from ~36,663 WARNING/run; real WARNING/ERROR now grep-able) | **DONE** |
| **OPT-14** | Reconcile `CLAUDE.md` with code (retired flags, `AIPACS_DENTAL_VTK_MPR` note) | — | registry §21 divergences | Not done | Med (maintainability) | **Low** | Low | **READY-SAFE** | **P1** |
| **OPT-05** | Download subprocess spawn access violation (pickle into child) | E | `native_fault.log` `download_process_worker.py:148` | Tracked | High (session stability) | Med | Med | **REGRESSION** | **P1** |
| **OPT-13** | Live-verify cine / multi-frame decode + playback | G | implemented; no cine data exercised | default-on | Low-Med | Low | Low | **IMPL-UNVERIFIED** | **P2** |
| **OPT-08** | Resolve Dental VTK-MPR default (doc ON vs code OFF) + geometry parity | D/geom | registry 🔴 row | code default-OFF | Med (dental correctness) | **High (geometry, clinical)** | Med | **REGRESSION/DIVERGENCE** | **P2** |
| **OPT-04** | Full Stage-1 lifecycle cutover: sidebar renders from model; DM re-key by canonical identity; off-GUI convergence sweep replaces `_dl_watchdog_tick`+resume+grow | B/C/D/F | the whole §4 defect | shadow only | **Very high (determinism)** | **High** | High | **HIGH-RISK-DEFERRED** (decompose) | **P2 (staged)** |
| **OPT-06** | Multi-study grow-lane bind for a PREVIOUS-EXAM/secondary series whose offset-key stored `series_uid` is stale/degenerate — the grow lane (`_grow_lane_display_key`→`display_key_for_active_series_uid`) matched DM download events by `series_uid` ONLY, so a prev-exam series was dropped (`resolved=None`) or mis-resolved to a bare number and never grew. This is the ROOT of OPT-03's failure and the recurring "series N shows in current AND previous exam / needs a 2nd drag" report | D | sess-11818cd24bf6 2026-07-05: `resolved=None`/wrong-number for prev-exam series 202; seam_b 0× | **study-scoped `(study_uid, series_number)` fallback SHIPPED default-OFF** (`AIPACS_GROW_LANE_STUDY_NUMBER_BIND`): binds ONLY after the `series_uid` match fails AND only when BOTH the resolved study_uid AND series_number equal the DM event's OWN (never cross-study; never overrides a series_uid match; default-off byte-identical). `home_download_service.py` `_dm_event_series_number` + identity threading; `_vc_progressive.py` fallback loop + `[GROW-LANE-STUDYNUM-BIND]` success marker; widened `[GROW-LANE-TRACE]` (full uids + `ev_num`). Guard `tests/code/viewer/test_grow_lane_study_number_bind.py` 9/9 green | High reliab (kills "2nd drag" + prev-exam no-grow) | **Low** (additive; study-scoped; default-off byte-identical) | Low | **MECHANISM-VERIFIED-SAFE, target not yet reproduced** (live run sess-…416036 with flag on: `ev_num` correctly computed = 10 / 100000; **0 false binds** under a 3-study + document session; the awaited prev-exam series 3000201/3000202 had VALID stored series_uids and loaded fine — this patient never hit the stale-uid case. The 77 unmatched `[GROW-LANE-TRACE]` were the DM downloading *other* series (10, doc 100000) no viewport awaited = correctly unbound. **KEY LEARNING: `resolved=None` is NOT inherently the defect** — it is the normal signal for a background series no viewport awaits; the bug is only when the DM `series_uid` MATCHES an awaiting entry's uid yet still resolves None. Keep default-OFF until a run shows a `[GROW-LANE-TRACE]` whose DM `series_uid` equals an `awaiting` uid with `resolved=None`) | **P2 (staged; safe)** |
| **OPT-07** | Multi-study B1 Series 100000 (DICOMized document) offset-key resolution | D | STAGED in MULTISTUDY 06-30 | not started | Low-Med | Med | Med | **NOT STARTED** | **P3** |
| **OPT-12** | Startup main-thread stall — ROOT-CAUSED 07-05 to the single-instance takeover sweep (NOT EchoMind/add_AIPacs_tab as first assumed): psutil `proc.name()`/`.exe()` + `ppid_map()` rebuilds | A | STALL_TRACE `single_instance_lock.py:446`/`:387` | name-reuse + fast ppid-snapshot (`AIPACS_FAST_INSTANCE_SWEEP`) BOTH now **default-on** | Med (one-time) | Med | Med | **VERIFIED-COMPLETE 2026-07-05** (live run sess-…416036 with the flag on: `single_instance_lock.py:387` sweep stall **0 traces**, `:446` already gone, **0 crashes**, nothing wrongly closed. During-use **0 stalls / max 0 ms**) | **DONE** |
| **OPT-10** | Geometry T2/T3: persist spacing/photometric; DB metadata path (~1424 ms H1) | G/geom | GEOMETRY 06-14 | staged | Med (latency) | **High (every render)** | High | **HIGH-RISK-DEFERRED** | **P3 (golden-compare gate)** |
| **OPT-11** | Collapse verified default-on kill switches (one at a time, post-verify) | — | ~40+ flags; `CLAUDE.md` directive | 8 collapsed (07-05: license-defer, theme-dedup, status-trim, dl-cache, + 3 clinical wrong-series flags) | Med (maintainability) | Med (per-flag) | Med | **PARTIAL** (continue as items soak) | **P3 (continuous)** |
| **OPT-16** | Add CPU/GPU runtime sampling to live logs | — | KPI §4 gap | none | Low (visibility) | Low | Low | **NEEDS-INSTRUMENTATION** | **P3** |
| **OPT-15** | EchoMind prompt safety (legacy "exaggeration", correction schema, modality match, temp/max_tokens) | — | UNIFIED P4.2 | audit | Med (output quality) | Med | Med | **NOT STARTED** | **P3 (separate track)** |
| **OPT-17** | Viewer-cache STUDY-IDENTITY hardening: make study_uid an intrinsic, positively-checked property of every in-memory viewer/ZetaBoost cache entry (tiers 1-3 had NO study check; tier-4 failed open on missing study_uid) | C/D (isolation) | audit `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05` finding #1; 48952 | `_vc_backend.py` + `_vc_cache.py` default-on (`AIPACS_CACHE_STUDY_IDENTITY`); 11/11 guard-test green | High (clinical isolation) | **Low** (additive; multi-study-gated; fail-open; single-study byte-identical) | Low | **IMPL-UNVERIFIED** (shipped in the 07-05 release; live-verify in N-1) | **P1** |
| **OPT-18** | DB series-owner enforcement: default `AIPACS_DB_ENFORCE_OWNER=1` for clinical builds so a non-conformant DUPLICATE SeriesInstanceUID across studies cannot silently repoint a series' `study_fk` (blocks + metadata-only refresh; already logged as `[CrossStudyReassignment]`) | C/D (isolation) | audit `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05` finding #2 | guard EXISTS in `database/dicom_db.py` but default `"0"` = OBSERVE-ONLY (logs, does not block); enforcement path already coded behind `=1` | High (clinical isolation; cheap) | **Low** (config-default flip; enforce path exists + `test_multistudy_identity_guards`) | Low | **VERIFIED-COMPLETE 2026-07-05** (default `"1"`; live run sess-…416036: **0 CrossStudy/CrossPatient reassignment events** on a multi-study + previous-exam + document session = enforce-on causes no false blocks on conformant data) | **DONE** |
| **OPT-19** | Series-identity robustness cluster (defence-in-depth; NOT a misread hazard): (a) self-describing drag payload — carry study_uid+series_uid, not only the offset display key [#3]; (b) DM `series_uid` degrade-to-bare-number defensive guard/log [#4]; (c) study-completeness probe use the collision-safe canonical folder resolver, not the bare series_number [#5 — partly covered by `_DM_CANON_IDENTITY` default-on] | D (multi-study) | audit findings #3/#4/#5 | not started (all Low; no active leak observed) | Low-Med (robustness) | Low | Med | **NOT STARTED** | **P3** |
| **OPT-20** | Multi-study SECONDARY-study series (higher-slot offset key, e.g. `3000002` = slot 3 / series 2) **fails to resolve → load → display** when its original number collides with another study's series — a viewport display MISS (blank/stuck), NOT wrong pixels | D (multi-study) | **live sess-34560eed25d3 2026-07-05**: `change_series(3000002)` → `_load_single_series_on_demand` runs but **no `[MULTI-STUDY LOAD]` resolution, no `open_series`** → `ViewportLoadingStateCleared series=None`; sibling keys (`3000004`, `2000005`, primary `2`) `hot_hit`+render. 59 display-misses this run. Gate held (0 wrong-study skips) | **RESOLVED (metric) + NARROWED to a self-recovering edge case 2026-07-05.** Deep trace of sess-…416036: **(1) the "66 display-misses" metric was FALSE.** `ViewportLoadingStateCleared series=None` is emitted by `_hide_spinner_for_widget` logging `_awaiting_series_number`, which is **None AFTER a successful load** (awaiting reset). Every one of the 66 followed a successful `open_series` + `first_image_visible`; `ViewportLoadFailed=0`; non-None clears=0. So there were **ZERO real display failures**, and every actively-viewed series — INCLUDING previous exams (slots 2 & 3: `2000002-6`, `3000201/2`) — rendered. Verify script metric corrected to count `ViewportLoadFailed` + non-None clears (not benign `series=None`). **(2) ONE series genuinely did not render: `1000001`** (a 13.5 MB single-frame **DX**, slot-1 previous exam, study `…20260607092105.0.28`), dragged at 20:09 **DURING its own 13.5 MB download**. Study/disk/DB/metadata ALL resolved CORRECTLY (`[MULTI-STUDY LOAD] entry-authority slot=1`, `study_pk=1793`, `disk_series=1`, `[H7-P4] disk_file_count=1`, `[FAST_LOAD_BREAKDOWN] headers_only_build=4ms`) — but the render aborted AFTER header-build (never reached `_start_qt_viewer`: no `IDENTITY-GATE eval`, no `first_image_visible`). `itk_pipeline files=2` disagrees with the fresh `[H7-P4] disk_file_count=1` at the SAME retry → a **stale mid-download metadata/instance cache** (`_get_cached_metadata` / `_reconcile_db_instances_with_disk` reconcile=0 ms did not refresh) that `force_reload` + `ZetaBoost INVALIDATE` did NOT clear, so the 3 retries reused it. NOT a multi-study resolution bug (resolution correct) and NOT wrong-pixels (blank, re-openable). Fix target = FAST metadata-cache invalidation on `force_reload`. LIVE TEST: re-drop `1000001` after an app restart (clears in-mem cache) — renders ⇒ confirms stale-mid-download-cache **(3) SECOND, HIGHER-SEVERITY RESIDUAL - previous-exam INTERMITTENT render miss under contention (sess-9721c090163f, the "second patient" symptom).** Per-series tally: previous-exam offset keys render only SOMETIMES - `1000004` 1/5, `1000006` 1/3, `1000003` 4/5 - while primary series 1-6 render 1:1. Decisive compare: `1000003` (21:48:46) load completes (`load_single_series_total 155ms`) then `first_image_visible render_ms=40`; `1000004` (21:48:56) load completes IDENTICALLY (`143ms`) then NO `first_image`, immediately a `MAIN_THREAD_STALL 224ms` with `active_series_number=1000003` (viewport stayed on the PRIOR series). This run had **65 main-thread stalls, max 5.7s** (vs 0 in run 1) because the second patient has many previous-exam studies downloading at once. Under GUI-thread contention the FAST **render-apply for a rapidly-switched previous-exam series is DROPPED** (metadata load finishes, repaint never lands) with NO convergence to re-render. Amplified by `[DB_METADATA_GATE] geometry holes -> disk header path` (a still-downloading study's DB metadata is incomplete). NOT the identity gate (0 skips, never reached), NOT resolution, NOT the false metric = the OPT-04 no-convergence x OPT-01 main-thread intersection, reproduced. `verify_opt20.ps1` verdict corrected to flag intermittent offset-key renders + correlate stalls | Med-High (real intermittent previous-exam display miss) | Med (contained: FAST disk-header metadata path for DX) | High | **METRIC FIXED. (4) CORRECTED ROOT CAUSE 2026-07-06 (48456, sess pid454684, 0 stalls) — NOT contention/OPT-04 (that theory disproved: 0 main-thread stalls this run, study download COMPLETE).** The RENDER-DROP detector caught all 3 misses; ALL THREE (`1000001`, `2000001`, `2000002`) are **large single-frame DX images** (~13 MB, SOP `1.2.840.10008.5.1.4.1.1.1.1`) loaded as PREVIOUS-EXAM series. DX images have NO ImageOrientationPatient (2D projection), so their DB metadata is flagged "geometry holes" -> `[DB_METADATA_GATE] -> disk header path`. The SAME DX render fine as PRIMARY series AND via the DB-metadata path (slot-1 `1000002-5` all rendered 2/2); they fail ONLY via the FAST **disk-header** metadata path (slot-2 study `…20260615200149.0.42`): metadata builds (`[FAST_LOAD_BREAKDOWN] headers_only_build`) but the render never reaches `_start_qt_viewer` (identity-gate evals=0, no first_image) -> empty apply. So the real bug = **the FAST disk-header metadata/apply path does not render DX / no-geometry single-frame images**, while the DB-metadata path does. Deterministic (not timing/contention). Fix target = reconcile the disk-header DX metadata/apply with the working DB path (narrow, contained). Detector: `AIPACS_RENDER_DROP_DETECT` default-on. **(5) DEFINITIVE ROOT CAUSE + FIX 2026-07-06 (48456, run pid via FAST-YIELD-TRACE): NOT a metadata bug — ALL 51 `[FAST-YIELD-TRACE]` = `will_yield=True` (metadata always builds). It is a DROPPED UI APPLY.** On a rapidly re-switched LARGE single-frame previous-exam image (DX up to 13613x4424 = 60 MP, and DICOMized documents series 100000), the worker-thread load finishes (`stage-timing ~179ms`, `[MULTI-STUDY LOAD]`, `[H7-P4]` all present) and queues the UI apply FIRE-AND-FORGET (`_apply_loaded_series_data_threadsafe` -> `_queue_on_ui_thread`), but `_apply_loaded_series_data`'s stale-request guard (`_vc_load.py:1204`, `_is_request_current` False -> `[APPLY STALE]` return) DROPS the repaint, and nothing re-renders it -> `_start_qt_viewer` never runs (IDENTITY-GATE evals=0 for the miss, skips=0). Intermittent (same series renders on the switches whose apply wins the token), 0 stalls, no supersession by a new `change_series` (detector gen-confirmed). The manual re-click renders (the user's 4/7). **FIX = render-convergence:** the `[RENDER-DROP]` detector, on a confirmed drop (gen-match, not-rendered, not-awaiting), re-issues the SAME series ONCE (`change_series_on_viewer`) = the auto version of the successful re-click. Bounded 1 retry/series/episode (reset on next render) so it cannot loop; only fires when NOT superseded/awaiting. `_vc_switch.py`, flag `AIPACS_RENDER_DROP_RECONVERGE` DEFAULT OFF pending live validation (`run_dx_trace.ps1` sets it =1); marker `[RENDER-DROP-RECONVERGE]`. **(6) TRUE ROOT CAUSE + FIX 2026-07-06 (48456) — a TYPE-MISMATCH gate, deterministic (my (3) contention + (5) stale-token/reconverge theories were BOTH WRONG; the reconverge fired but the miss persisted + fails even fully-cached => not a race).** The async worker-load apply path `_apply_loaded_series_data` (`_vc_load.py:1259`) gated the render (`_perform_series_switch_optimized` -> `_start_qt_viewer`) on `current_idx == series_idx`, where `current_idx = vtk_w.last_series_show`. But `last_series_show` holds the **series NUMBER** (`_pw_viewers.py:684` sets it = `metadata['series']['series_number']`) while `series_idx` is the **list INDEX** returned by `replace_series_data` (`-> int`). For an offset-key previous-exam series (`2000001`, `1100000`, …) a series number can NEVER equal a small list index -> the gate is ALWAYS False -> the render block is skipped -> `_start_qt_viewer` never runs (IDENTITY-GATE evals=0, `[FAST-YIELD-TRACE] will_yield=True` = metadata was fine). Small primary numbers matched the index only by coincidence and/or rendered via the SYNC path, so only large/offset async loads failed. **FIX (`_vc_load.py`, flag `AIPACS_APPLY_RENDER_TARGET_VIEWER` DEFAULT OFF pending live verify): also render for the explicitly-targeted, non-stale viewer** (already past the `target_viewer_id` filter + the `_is_request_current` stale check, so THIS is the viewer that requested THIS series) regardless of the broken index compare. Additive (legacy index match preserved; no-target broadcast unchanged). Confirmation log `[APPLY-GATE] last_series_show=… series_idx=… legacy_match=… target_fix_render=…` proves both the mismatch and the fix. **LIVE-VERIFIED + PROMOTED DEFAULT-ON 2026-07-06 (45289).** With `AIPACS_APPLY_TRACE=1` the `[apply-path]` breakdown proved it: `APPLY-ENTER=34`, `APPLY-STALE-EARLY=0` (the stale-token theory is dead), `APPLY-GATE legacy_match=False=28` (the type-mismatch would have skipped 28 renders), **`target_fix_render=29`** (the fix rendered them). The `[APPLY-GATE]` lines show it exactly: `series=1000002 last_series_show=4 series_idx=5 legacy_match=False target_fix_render=True` (series NUMBER 4 vs list INDEX 5) + `first_image_visible` follows each. Previous-exam DX/document series that were 0/N now render (1000001 4/4, 1000004 3/3, …). Flag `AIPACS_APPLY_RENDER_TARGET_VIEWER` flipped default `"0"`->`"1"` (kill switch `=0`); the `[APPLY-ENTER]`/`[APPLY-GATE]` telemetry gated behind `AIPACS_APPLY_TRACE` (default OFF, no clinical-log spam). **TWO RARE RESIDUALS (small follow-ups, not the main bug):** (a) an occasional miss where `_apply_loaded_series_data` was NEVER entered (no `[APPLY-ENTER]`) = the worker->UI fire-and-forget post (`_queue_on_ui_thread`) was lost for that one switch (1000002 1-of-5, recovered on the user's next click); (b) 1 `[FAST-YIELD-TRACE] will_yield=False` = a rare metadata-build returning no instances. Both intermittent + rare. **(7) SLOT-3 RESIDUAL ROOT-CAUSED + FIXED default-on 2026-07-07 (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`).** The 49317 case where distinct secondary-study series `3000001`/`3000002` reached `[APPLY-ENTER]` but never `[APPLY-GATE]` was NOT the token gate (`[APPLY-STALE-EARLY]=0`, same UI thread) — it was `series_idx<0`: `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py`) had a **study-blind name+count dedup** that `return False`'d a distinct series sharing a `series_name`+count with an already-present series (common across a multi-study patient's studies), so it was never appended → `replace_series_data` returned -1 → render loop gated off. Fix: skip as a true duplicate ONLY when the incoming `series_number` is already present; a distinct not-present number appends. Isolation untouched (identity gate still fail-closed on `series_uid`). 8/8 headless checks vs the real method; guard `test_series_append_study_distinct.py`. NEEDS live verify on 49317 | **DONE (index-gate + slot-3 append-skip fixes shipped default-on); residuals (a) lost UI-post + (b) rare empty metadata + `1100000` document = OPT-07 = P2 follow-ups** |
| **OPT-21** | End-user PC whole-app NATIVE crash opening Standard MPR: a machine whose display driver cannot provide OpenGL 3.2 dies with an access violation inside the FIRST `QVTKRenderWindowInteractor` (`_mpr_views._create_axial_view`, between construction and `Initialize()`) — no Python traceback, every log stops mid-line. FAST 2D is VTK-free so the machine looks healthy until the MPR click (PC2 "baba", 2026-07-07 14:48, MR 144-slice; deferred-3D never reached) | MPR | PC2 logs (`app.log`/`viewer_diagnostics.log`/`zeta_mpr_canon_probe.log` all end 14:48:02.63-.64 at `create_view axial`) | **SHIPPED default-on 2026-07-07**: (1) `modules/mpr/opengl_preflight.py` — PERSISTED once-per-INSTALL check (`<config>/hardware_check.json`; user directive: never re-probe per session/click): persisted PASS = zero probing on MPR open; persisted FAIL/missing = graceful Qt probe now + persist (self-heals after a driver update); called in `toggle_zeta_mpr` BEFORE volume load/VTK construction → friendly QMessageBox + tool-state reset instead of process death (`AIPACS_MPR_OPENGL_PREFLIGHT`, `=0` legacy); (2) **Settings → Viewer Configuration → "Hardware Requirements Check"** (`settings_ui/hardware_check_panel.py`) — on-demand full check (OpenGL/GPU, CPU, RAM, disk via pure `evaluate_hardware`; only OpenGL gates MPR) with persisted display; (3) production faulthandler → `user_data/logs/native_fault.log` (`PacsClient/utils/native_fault_log.py`, wired early in `main.py`, `AIPACS_NATIVE_FAULT_LOG`, `=0` off) so any future native fault leaves all-thread Python stacks even frozen. `hardware_check.json` = machine state, never seeded | High (whole-app crash → contained failure + diagnosability) | **Low** (additive; probe cached; flag-gated; blocked path only on probe failure) | Low | **IMPL-VERIFIED offscreen** (15/15 new guard tests; viewer suite 60 fails = byte-identical to stashed baseline, 0 new). NEEDS: machine-level confirm on PC2 (Event Viewer faulting module / driver update) + live source-build sanity (MPR still opens on a good GPU) | **P1** |

| **OPT-22** | STARTUP freeze: in-app web-browser Chromium prewarm constructs `QWebEngineView` on the GUI thread → up to **21 s** main-thread stall (`interaction_active=False`, t_since_start ~39 s) while the user is on the main page / patient list | Startup | 07-07 sess-d2bd9ea75f3f: `[MAIN_THREAD_STALL] stall_duration_ms=21054.2` ends exactly at `web_browser.prewarm._construct_warm_view` "Chromium engine warmed" (14:57:54.67 vs 54.74). Also 20074/8546/7357 ms startup stalls | **PRE-EXISTING** (prewarm module + call site landed v3.3.9 2026-06-27; NOT changed v3.4.6; NOT unified-pipeline). Marker-gated (only warms if browser used before) + kill switch `AIPACS_BROWSER_PREWARM=0` already exists. QWebEngineView is GUI-thread-only (can't off-thread) → fix = defer-to-idle / open-on-intent, not off-threading | High (multi-s startup freeze) | Low (opt only; kill switch exists) | Low | **FIXED default-on 2026-07-08** (`AIPACS_BROWSER_PREWARM_IDLE_ONLY`): the GUI-thread warm now waits for a genuine idle gap (no discrete input for `idle_ms`, default 5 s) after a longer initial delay (default 20 s), rechecking on a poll timer, and SKIPS the warm entirely if the user stays busy past a cap (default 10 min) — so the 21 s block lands only when the user isn't interacting, or not at all. Marker-gate + `AIPACS_BROWSER_PREWARM=0` preserved; `IDLE_ONLY=0` = byte-identical legacy fixed-delay. `modules/web_browser/prewarm.py`. Guard `tests/code/system/test_browser_prewarm_idle_gate.py` (+ algorithm validated standalone; py_compile blocked in-sandbox by the FUSE mount-staleness on that one file — Read-tool confirms the file is complete/well-formed). NEEDS live verify. Report `docs/reports/REGRESSION_REVIEW_STARTUP_AND_ECHOMIND_FREEZE_2026-07-08.md` | **DONE (needs live verify)** |
| **OPT-23** | Secretary EchoMind viewport import FREEZE: dispatch runs **inline on the UI thread** (`QTimer.singleShot(0)`→`bus.execute`→`change_series_on_viewer`); Advanced/VTK switch builds `ImageViewer2D()`+`Render()` sync (~2.4 s); AI-seg `on_contour_closed`→`requests.post` sync network on UI thread (→6.5 s) | D / EchoMind | 07-07 stall stacks: `_perform_series_switch_optimized→switch_series→ImageViewer2D.__init__→Render()` (2439 ms); `on_contour_closed→download_file→requests.post→socket.recv_into` (411→6498 ms) | **UNDERLYING PRE-EXISTING** (sync `change_series_on_viewer` = 06-06 bridge; Advanced VTK render older); **v3.4.6 "EchoMind unified MCP" (`aipacs_control_mcp/server.py`) is the NEW TRIGGER** that first drives it programmatically. Bus BUILD is cheap (registration only) — not the freeze | High (import freeze) | Med-low (parity with proven drop path) | Med | **FIXED default-on 2026-07-08** (`AIPACS_ECHOMIND_DEFER_SWITCH`): `viewer_write_adapter.change_series` now defers the `method_change_series_on_viewer(...)` call to `QTimer.singleShot(0, ...)` — matching the REAL drop handler (`_vw_dragdrop.dropEvent → singleShot(0, _do_series_switch)`, which the file's own fidelity note already claimed). The loading spinner (shown above the call) now PAINTS before the switch and the command-bus/IPC drain returns immediately, so the import shows "loading" instead of a dead freeze. `=0` = legacy inline. Guard `tests/code/echomind/test_echomind_defer_switch.py` (3 green in-sandbox vs the REAL adapter: defers-by-default / inline-when-off / spinner-first). **STILL PENDING (follow-ups, in the report):** the Advanced/VTK `ImageViewer2D`+`Render()` is GUI-thread-inherent (spinner only); the AI-seg `on_contour_closed→requests.post` sync network POST should move off-thread. `viewer_write_adapter.py`. Report as above | **DONE (import; VTK-render + AI-seg upload = follow-ups)** |

**Audit reconciliation — `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05.md` (7 findings mapped, no separate plan):**
- **#1** (bare-number viewer caches) → **RESOLVED** = **OPT-17** (`AIPACS_CACHE_STUDY_IDENTITY`, shipped 07-05). Live-verify in **N-1**.
- **#2** (duplicate SeriesInstanceUID repoints study_fk) → **OPEN, highest value** = **OPT-18**. Cheap config-default flip; do in **N-2** (low-risk hygiene/config), guard-tested, per-flag.
- **#3/#4/#5** (drag payload, DM bare-number degrade, completeness-probe resolver) → **OPEN, Low** = **OPT-19**, **P3** robustness; fold each into the file it lives in when that area is next touched (drop path / DM adapter / view-intent). #5 is partly done (`_DM_CANON_IDENTITY`).
- **#6** (reception `study_uid` ≠ on-disk StudyInstanceUID, case 48101) → **Info, already instrumented** (`[PREV-EXAM-UID]`); worst case = previous exam *fails to render*, never wrong images. Track under **OPT-07** (previous-exam / DICOMized-document identity), not a new item.
- **#7** (identity gate + poison guard NEEDS-LIVE-VERIFY) → **largely DISCHARGED 2026-07-05**: both live-ran green in the pre-publish gate (gate 26+ evals / 0 wrong-study stomps; poison-guard tests green; app clean) and their flags were retired to unconditional. Any *formal multi-scenario* pass folds into **N-1**.

**Net:** one new **P1** action (**OPT-18**, a config default), one **P3** robustness cluster (**OPT-19**); everything else is resolved or verification debt folded into N-1. No new plan — all seven findings live inside this backlog + the existing N-1/N-2 staging.

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

**N-2 — Low-risk config + hygiene + doc reconciliation (OPT-18, OPT-14; OPT-09 shipped 07-05).** Near-zero clinical risk.
- **OPT-18 (audit #2) — DB owner enforcement (highest-value remaining):** flip `AIPACS_DB_ENFORCE_OWNER`
  default `"0"`→`"1"` for clinical builds in `database/dicom_db.py` so a duplicate SeriesInstanceUID across
  studies is BLOCKED (metadata-only refresh) instead of silently repointing `study_fk`. The enforce path
  + `[CrossStudyReassignment]` logging already exist; this is a one-line default change. *Method:* flip the
  default, run `tests/code/download_manager/test_multistudy_identity_guards.py`, then a live pass watching
  for `[CrossStudyReassignment]` (should be rare/absent on conformant data). *Rollback:*
  `AIPACS_DB_ENFORCE_OWNER=0` restores observe-only. Do this FIRST in N-2 (cheap, isolation-critical).
- *Exact problem (OPT-09, now shipped):* `download_diagnostics.log` is ~99% WARNING (17 k lines) burying 13 real socket
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
| 2026-07-04 | **Reliability/clinical: viewport study-identity gate** (`AIPACS_VIEWPORT_STUDY_IDENTITY_GATE` + `AIPACS_STAMP_SERIES_STUDY_UID`, default-on) | 48912/48952: requesting a CURRENT series rendered the same-numbered PREVIOUS exam (`change_series(4)` → `first_image_visible 1000004`); the previous series is stored in the DB under the CURRENT study_uid so study signals falsely matched | each viewport is stamped with its intended series identity (`_vc_switch`); the FAST render choke point `qt_fast_container._start_qt_viewer` skips a render whose **series_uid** (DB-corruption-proof) ≠ the intended one; metadata now also carries server-canonical study_uid/series_uid | 3 files AST-OK; 13 offscreen tests green (`test_viewport_study_identity_gate`) | ✅ **LIVE-VERIFIED on a 2nd PC (2026-07-04, user-confirmed)** — all series show and switch without the previous-exam stomp. Deeper: DB has previous-exam rows under the wrong study_uid = separate data-integrity cleanup (deferred). Report: `docs/reports/MULTISTUDY_CURRENT_SERIES_DISPLAY_MISS_48952_2026-07-04.md` |
| 2026-07-04 | OPT-01 **`_is_study_downloaded` TTL cache + scandir** (`AIPACS_STUDY_DL_CHECK_CACHE`, TTL `AIPACS_STUDY_DL_CHECK_TTL_MS`=1500, default-on) | the manifest disk-walk amplifier (§5.H): `_is_study_downloaded` ran 1+N `iterdir()` per study per row on EVERY DM-progress status refresh → re-walked every study's folder many ×/s on the GUI thread (48 s stalls on reporting PC) | short-TTL cache collapses the repeated walks; invalidated the moment a study's status changes (`update_study_download_status`→`_invalidate_study_downloaded_cache`) so completion still flips promptly; check itself is a single `os.scandir` early-exit pass (behavior preserved) | full-file AST-OK; 12 offscreen tests green (`test_study_downloaded_cache`: TTL collapse, expiry re-walk, invalidation flip, kill-switch, + real-tree scandir semantics) | ✅ offscreen; **live-verify pending** (probe run on the reporting PC → status-refresh disk-walk stalls should drop). §5.H manifest-scan amplifier addressed |
| 2026-07-04 | OPT-01 **status expensive-flag TTL reuse** (`AIPACS_STATUS_EXPENSIVE_TTL`, TTL `_S`=30, **default OFF/opt-in**) | `_compute_local_status_flags` re-runs the attachment `os.walk` + case-of-day + printed DB queries per row whenever the 5 s `_local_status_cache` TTL expires on a status-widget rebuild | between the 5 s short TTL and a 30 s expensive TTL, refresh ONLY the cheap (now-cached) dicom flag and REUSE the expensive attachment/DB flags; those change only via viewer actions that return through a cache-clearing refresh | edit region verified well-formed (Read tool); **offscreen tests + full-file AST could NOT run** — sandbox FUSE mount served STALE/truncated copies this session (source capped at 301829 B / line 6429; test file showed pre-edit 12 tests) | ⏸️ **DEFAULT-OFF pending validation** — chosen because the freshness change (5 s→30 s for docs/voice/ai/case/printed chips during continuous list viewing) is unverified in-sandbox. Flip `=1` after confirming chips still update promptly on the viewer→list transition. Mechanism shipped; guard tests written (`test_study_downloaded_cache` expensive-TTL mirror). |
| 2026-07-04 | **OPT-01 LIVE-VERIFIED (during-use)** on fresh user run (23:46, sessions incl. `sess-9f940906f3a6`) | 07-01/reporting-PC amplifier: status-refresh disk-walk in stall stacks, 48 s max stall | **during-use max stall ≈247 ms (32 total, none >250 ms)**; `_is_study_downloaded`/`_compute_local_status_flags`/`iterdir` **absent from every stall trace**; decode 7.9 ms, TTFI 30.4 ms healthy. Remaining large stalls are ALL **startup** (t_since_start 2–13 s, interaction_active=False) | 0 regressions | ✅ **disk-walk amplifier resolved.** Next perf frontier = startup init (OPT-12/P1.4) + the generic `main.py:notify` multi-second startup stalls |
| 2026-07-04 | **OPT-09 log hygiene: download telemetry off WARNING** (`AIPACS_LOG_TELEMETRY_DOWNGRADE`, default-on) | download_diagnostics.log 2026-07-04: **36,663 WARNING vs 294 ERROR** — telemetry (`[BATCH_TRACE]`/`download-summary`/`series-summary`/`stage-timing`/`[NET_TIMING]`/`[KPI] TTFC`/`[SERIES_COMPLETE]`) emitted at WARNING to pass the download component threshold, burying real errors 125:1 | `TelemetryLevelDowngradeFilter` on the download handler AFTER the threshold gate relabels known-telemetry WARNING records → INFO (telemetry still captured; handler is DEBUG); genuine WARNING/ERROR untouched → `grep WARNING/ERROR` now surfaces only real problems | module imports clean; **7 offscreen tests green** (`test_telemetry_level_downgrade`: each telemetry prefix downgraded, real WARNING/ERROR untouched, kill-switch, mid-message non-match, source-pin filter ordering) | ✅ offscreen; contained to `diagnostic_logging.py` (no socket_client touch). **live-verify pending** (next run → download_diagnostics WARNING count should collapse to real warnings only). No 13 MB single-record hazard this run (longest line 3 KB) |
| 2026-07-05 | **OPT-12 startup: single-instance sweep cheap-name reuse** | STALL_TRACE (07-04) proved the startup freezes are NOT UI construction but `main.py:1189 try_acquire → _force_close_other_instances`: psutil `me.parents()` (277 ms sample) + `proc.name()`→`.exe()`/OpenProcess in the kill loop (**1320 ms sample** on a half-dead orphan) — the latter called ONLY to build a log-description string | store the cheap Toolhelp `(proc, name)` with each candidate; the kill loop reuses `cand_name` for the description instead of re-deriving via the slow `proc.name()`/`.exe()` path. Protect-set + kill/terminate logic byte-identical (dict still keyed by pid; `proc.ppid() in candidates` intact) | AST-OK; 4 offscreen source-pin tests green (`test_instance_sweep_cheap_name`); takeover behaviour still covered by `test_single_instance_takeover` | ✅ offscreen; **live-verify pending** (STALL_TRACE at `single_instance_lock.py:446` should vanish). **DEFERRED (medium-risk, next):** replace the repeated Windows `ppid_map()` rebuilds in `me.parents()`/`me.children(recursive=True)`/`proc.ppid()` with ONE ppid snapshot — touches the safety-critical protected-set (mis-computation could kill the launching terminal), so it needs a flag + live Windows validation, not a blind sandbox edit |
| 2026-07-05 | **OPT-12 LIVE-VERIFIED** (fresh trace run `sess-3d375cab2ef4`, 00:18) | `single_instance_lock.py:446` name()→exe() stall (1320 ms) | **`:446` GONE from all traces** (0 occurrences); remaining single-instance frames = `:387` (`me.parents()`) + `:449` (kill loop). During-use **max stall 173 ms (2 total)**, decode 7.1 ms, TTFI 36.8 ms — best yet. **No crash** (0 AV/faulthandler; OPT-05 did not reproduce) | 0 regressions | ✅ name-reuse confirmed. Remaining ~2.3 s **startup** stall (one-time, interaction_active=False) is the psutil `ppid_map()` rebuild in `me.parents()`/kill-loop → the deferred ppid-snapshot (safety-critical, flag-gated + Windows-validated). OPT-09 telemetry not exercised (no downloads this run) |
| 2026-07-05 | **OPT-12 fast instance sweep — ppid snapshot** (`AIPACS_FAST_INSTANCE_SWEEP`, **default OFF pending Windows validation**) | the residual ~2.3 s startup stall: `me.parents()` + `me.children(recursive=True)` + per-candidate `proc.ppid()` each rebuild the whole Windows parent map | the Toolhelp `PROCESSENTRY32W` already carries `th32ParentProcessID`, so ONE snapshot now yields (pid, name, ppid); pure `_protected_pids_from_snapshot(pid2ppid, self_pid)` computes self+ancestors+descendants via dict walks; the kill-loop top-level check reads the snapshot ppid. Legacy psutil path byte-identical when the flag is off; snapshot can only ever OVER-protect (skip a kill), never mis-protect a real target | AST/edit verified via Read tool; **pure protected-set logic exhaustively unit-tested** (ancestors, descendants, siblings excluded, cycle + ppid-0 guards, deep trees) — 8 tests green (`test_fast_instance_sweep`) | ⏸️ **DEFAULT-OFF, ship-ready.** SAFETY-CRITICAL (protected set = "never kill our own launcher/tree"), so it needs a live Windows run with `AIPACS_FAST_INSTANCE_SWEEP=1`: confirm startup `:387`/`:449` stall drops AND nothing unexpected closes (VS Code/terminal). Then flip default. Kill switch = unset/`0` |
| 2026-07-05 | **OPT-11 flag collapse — 4 validated NON-clinical flags retired** (promoted to unconditional default) | live-verified optimizations still carrying a kill switch; user directive to close out small validated items (keep clinical kill switches) | retired `AIPACS_DEFER_LICENSE_INFO` (app_handler), `AIPACS_THEME_APPLY_DEDUP` (mainwindow_ui + AIPacs_ui + patient_search_widget), `AIPACS_STATUS_REFRESH_DICOM_ONLY` + `AIPACS_STUDY_DL_CHECK_CACHE` (patient_table_widget) → defer/dedup/trim/cache now unconditional; legacy branches deleted; `AIPACS_STUDY_DL_CHECK_TTL_MS` kept as a numeric tunable | 4 guard tests updated (flag-retired pins + kill-switch mirror tests removed); the 4 smaller source files AST-OK in sandbox; patient_table_widget verified via file tool (sandbox mount truncates it) | ✅ code complete; **CLINICAL kill switches deliberately RETAINED** (identity gate / poison-guard / study_uid stamp — recent, safety-sensitive). **Verify via VS Code pytest** (sandbox mount corrupting reads this session). Default-off flags (`AIPACS_FAST_INSTANCE_SWEEP`, `AIPACS_STATUS_EXPENSIVE_TTL`) + OPT-09 telemetry still await their live validation run before promotion |

| 2026-07-05 | **OPT-17 Reliability/clinical: viewer-cache STUDY-IDENTITY hardening** (`AIPACS_CACHE_STUDY_IDENTITY`, default-on) | audit finding #1: in-memory viewer caches keyed by BARE series_number — tiers 1-3 of `_get_series_by_number_fast` (`_hot_series_cache`/`_series_cache`/`_series_number_to_index`) validated ONLY series_number + object identity (NO study check); tier-4 `_cache_entry_study_matches` failed OPEN on a cached entry lacking `study_uid`. Isolation depended on the offset-key scheme + stable slots, not on the key itself | study identity made an INTRINSIC, positively-checked property of every entry: (1) `_full_cache_put` STAMPS the entry's own `study_uid` at write time (gap-fill only, via `_resolve_canonical_series_identity`) so the read guard can never fail-open on our entries; (2) `_entry_is_valid` (tiers 1-3) REJECTS a cached tuple whose stored `study_uid` ≠ the study the display key resolves to → miss → clean reload; (3) tier-4 fail-open branch now logged. Multi-study-gated + positive-mismatch-only ⇒ single-study byte-identical; the viewport `series_uid` identity-gate remains the final backstop. **Deliberately did NOT reformat the ZetaBoost store key** — the warmup callback `_zeta_boost_load_series` hard-requires a digit key (`isdigit()`/`int(sn)`), so a composite key would silently break warmup; that full store re-key stays a larger staged item needing warmup-callback rework + live validation | edits verified via Read tool + isolated-block AST-OK; **11/11 offscreen guard tests green** (`test_cache_study_identity`: truth-table single-study byte-identical / multi-study reject-on-positive-mismatch / fail-open-on-unknown / stamp gap-fill + 5 source-pins). Full-file AST via sandbox blocked by the known FUSE tail-truncation (verified the real files terminate cleanly via Read) | ⏳ offscreen-verified; **NEEDS-LIVE-VERIFY** on the source build (multi-study + previous-exam tab: every current & previous series shows/switches correctly; watch for `[CACHE-STUDY-IDENTITY] tier reject` — a reject should be followed by a correct reload, never a blank/stuck viewport). Files: `_vc_backend.py`, `_vc_cache.py` (neither plugin-mirrored). Report: `docs/reports/CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05.md` §5 |

| 2026-07-05 | **OPT-06 Reliability/clinical: study-scoped grow-lane fallback bind** (`AIPACS_GROW_LANE_STUDY_NUMBER_BIND`, **default OFF pending live verify**) | OPT-03 verify FAILED (sess-11818cd24bf6): the download→viewer grow lane (`_grow_lane_display_key`→`display_key_for_active_series_uid`) re-keys a DM event to the awaiting viewport by matching the DM event's globally-unique `series_uid` against the `series_uid` stored in this patient's `_server_series_info[offset_key]`. For a PREVIOUS-EXAM/secondary series whose offset-key entry carries a stale/degenerate `series_uid`, that match failed → `resolved=None` (10×) or mis-resolved to a wrong bare number (201/9001) → the awaiting prev-exam series (202) never grew; it only crawled up via the disk-readiness resume fallback (`GROW-DISPLAYED 40→58/256`). Seam B (OPT-03) fired 0× because most drops were mis-resolved (non-None), not None. This is the root of the recurring "series N shows in current AND previous exam / needs a 2nd drag" report | when the `series_uid` match finds nothing, bind by the CANONICAL `(study_uid, series_number)` instead: `home_download_service._dm_event_series_number` reads the DM event's authoritative number from ITS OWN study's DM task `series_list` (independent of the stale uid→number map) and threads `(event_study_uid=uid, event_series_number)` into `display_key_for_active_series_uid`, which matches an awaiting/progressive key ONLY when BOTH its resolved study_uid AND series_number equal the event's own. STRICTLY study-scoped (never number-only) so it can never cross-study collide; never overrides a `series_uid` match; default-off = byte-identical legacy. `[GROW-LANE-STUDYNUM-BIND]` success marker + widened `[GROW-LANE-TRACE]` (full uids + `ev_num`) for the verify | both edited blocks AST-OK as isolated snippets + **9/9 offscreen guard tests green** (`test_grow_lane_study_number_bind`: legacy-miss-on-stale-uid, fallback-binds-prev-exam, never-cross-study, number-mismatch-no-bind, series_uid-precedence, no-kwargs-byte-identical + 3 source-pins). Full-file AST blocked by the known FUSE tail-truncation (both files verified to terminate cleanly via Read) | ⏳ offscreen-verified; **DEFAULT-OFF, NEEDS-LIVE-VERIFY** on the source build (48912 / a prev-exam patient) with `AIPACS_GROW_LANE_STUDY_NUMBER_BIND=1`: the previous-exam series should grow on the FIRST drag; watch for `[GROW-LANE-STUDYNUM-BIND] bound display_key=…` and a drop in `[GROW-LANE-TRACE]` unmatched lines → then flip default-on and OPT-03's seam becomes redundant. OPT-20 (initial `change_series` LOAD miss) is a DIFFERENT resolution path — not closed by this. Files: `home_download_service.py`, `_vc_progressive.py` (neither plugin-mirrored) |

| 2026-07-05 | **VERIFY RUN sess-…416036 — closes OPT-09/12/18; OPT-06 mechanism-safe; OPT-20 narrowed** (verify_release.ps1, all validation flags on) | pre-run: OPT-09/12/18 shipped-unconfirmed; OPT-06 impl-unverified; OPT-20 open | **0 crashes; during-use 0 stalls / max 0 ms; TTFI 27.8 ms.** OPT-18 = **0** owner-reassignments (enforce-on, no false blocks). OPT-12 = `single_instance_lock.py:387` **0** stall traces (fast-sweep default-on), nothing wrongly closed. OPT-09 = **+753 INFO / +295 WARNING / +9 ERROR** (telemetry relabelled INFO, was ~36,663 WARNING). OPT-06 = `ev_num` computed (10/100000), **0 false binds** under a 3-study+document session (target stale-uid case not hit — prev-exam 3000201/3000202 had valid uids + loaded fine). OPT-20 = the 66 `series=None` misses are a DOCUMENT/secondary-capture study (`…045`, series 10 + doc 100000, empty series_uid), NOT the prev-exam path (which worked) | 0 regressions; identity-gate 24 evals / **0** wrong-study skips | ✅ **OPT-09, OPT-12, OPT-18 → VERIFIED-COMPLETE.** OPT-06 → mechanism-verified-safe, kept default-OFF (needs a real stale-uid repro; learned `resolved=None` is normal for background series). OPT-20 → narrowed to a document/secondary-capture study (overlaps OPT-07) = the next P1. OPT-02 (Seam A) not exercised (no rapid A→B→A); OPT-01 expensive-TTL still default-off pending a chip-freshness visual confirm |

| 2026-07-06 | **OPT-20 Reliability/clinical: async-apply render-gate type-mismatch — previous-exam DX/document "won't display" FIXED + PROMOTED DEFAULT-ON** (`AIPACS_APPLY_RENDER_TARGET_VIEWER`, default `"0"`→`"1"`) | patients 48456/45289: large single-frame previous-exam series (DX X-rays up to 60 MP, DICOMized documents) intermittently/never rendered. Ruled out (in order, all WRONG first): contention/OPT-04 (0 stalls), a stale-token race + render-convergence retry (reconverge fired but miss persisted; fails even fully-cached ⇒ deterministic), and the disk-header metadata path (renders primary DX fine). `[FAST-YIELD-TRACE] will_yield=True` proved metadata always builds — the drop is in the APPLY/RENDER half | `_apply_loaded_series_data` (`_vc_load.py:1259`) gated the render (`_perform_series_switch_optimized`→`_start_qt_viewer`) on `current_idx == series_idx`, but `current_idx = last_series_show` is the **series NUMBER** (`_pw_viewers.py:684`) while `series_idx` is the **list INDEX** (`replace_series_data -> int`). Offset-key series (e.g. `2000001`) never equal a small index ⇒ render ALWAYS skipped. Fix: also render for the explicitly-targeted, non-stale viewer (already past the `target_viewer_id` filter + `_is_request_current`), regardless of the broken index compare; additive, legacy match preserved | **LIVE-VERIFIED 45289** via the per-hop apply instrumentation (`AIPACS_APPLY_TRACE`): `[apply-path] APPLY-ENTER=34 APPLY-STALE-EARLY=0 APPLY-GATE(legacy_match=False)=28 target_fix_render=29`; `[APPLY-GATE] series=1000002 last_series_show=4 series_idx=5 legacy_match=False target_fix_render=True` + `first_image_visible` after each; previous-exam series now render (1000001 4/4, 1000004 3/3, …). AST-verified through the edit region (full-file blocked past the edits by the FUSE truncation cap) | ✅ **DONE — shipped default-on**, kill switch `AIPACS_APPLY_RENDER_TARGET_VIEWER=0`; telemetry `[APPLY-ENTER]`/`[APPLY-GATE]`/`[FAST-YIELD-TRACE]`/`[RENDER-DROP]` all behind flags default-off (no clinical-log spam). **Two rare P2 residuals** (each 1× this run, recover on re-click): (a) apply NEVER entered (no `[APPLY-ENTER]`) = worker→UI fire-and-forget post lost (`_queue_on_ui_thread`); (b) 1 `will_yield=False` = rare empty metadata build. The earlier `[RENDER-DROP-RECONVERGE]` retry stays as a default-off safety net. Locator: `tools/dev/run_dx_trace.ps1`. Files: `_vc_load.py` (not plugin-mirrored) |

| 2026-07-07 | **CLOSE-OUT RUN 49317** (`verify_all_opts.ps1`, all validation flags on) — closes 4 OPTs, refines OPT-20 residuals | pre-run: OPT-09/12/17/18 shipped; OPT-20 main fix shipped; residuals uncharacterized | **0 crashes; during-use 0 stalls / max 0 ms; ViewportLoadFailed=0; cleared-while-awaiting=0.** OPT-20 `[APPLY-GATE] target_fix_render=31` (fix carrying most previous-exam renders). OPT-17 = 48 gate evals / **0** skips. OPT-18 = **0** reassignments. OPT-12 = **0** `:387` stalls. OPT-09 = +1135 INFO (telemetry at INFO). **3 offset-key series still never rendered — now characterized:** `1100000` = a DICOMized DOCUMENT (series 100000, `APPLY-ENTER=0`, apply never ran) = OPT-07 document handling, not the display-gate bug; `3000001`/`3000002` = slot-3 DX (`APPLY-ENTER=4/2` but `APPLY-GATE=0`) = the apply enters then bails BEFORE the render loop (series_idx<0 OR the per-viewer stale check at `_vc_load.py:1276`, coincident with a mid-load 401 credential refresh). Residuals: 5 empty-metadata builds, 9 render-drops | 0 regressions | ✅ **CLOSE: guard-tests, safety, OPT-09, OPT-12, OPT-17, OPT-18, OPT-20 MAIN fix** (index-gate type-mismatch, default-on, target_fix_render=31). **HOLD: OPT-06** (not exercised — no stale-uid grow this run — keep default-off); **OPT-01** expensive-TTL (0 stalls, needs chip-freshness visual confirm to flip); **OPT-20 residuals (P2)** = `[APPLY-LOOP]` + `[APPLY-STALE-VIEWER]` diagnostics added (`AIPACS_APPLY_TRACE`) to pin the slot-3 per-viewer-stale vs series_idx<0 sub-case next run; `1100000` document = OPT-07 |

| 2026-07-07 | **OPT-21 Stability: MPR OpenGL pre-flight + production faulthandler** (`AIPACS_MPR_OPENGL_PREFLIGHT` + `AIPACS_NATIVE_FAULT_LOG`, both default-on) | end-user PC2: Standard MPR killed the whole frozen app with a NATIVE crash creating the FIRST VTK OpenGL render window (`_create_axial_view`; all logs stop 14:48:02.63-.64, no traceback — production build had NO faulthandler, so zero trace) | `toggle_zeta_mpr` now probes OpenGL once per session via plain Qt (graceful failure) BEFORE any volume load / VTK window; on failure shows an "update your GPU driver" dialog + resets tool state and returns — the 2D viewer keeps working. `main.py` enables faulthandler → `user_data/logs/native_fault.log` (all threads, session markers, handle kept alive, never breaks startup) | py_compile OK (toolbar_manager, main, both new modules); **15/15 new guard tests green** (`tests/code/viewer/test_mpr_opengl_preflight.py` 11 + `tests/code/system/test_native_faulthandler.py` 4) on the real venv; full `tests/code/viewer` run vs stashed baseline: **60 failed / identical set both runs, 0 new failures** (pre-existing local-env failures; `test_b43_progressive_lifecycle_state` collection error also pre-existing, verified via stash). New viewer tests +11 = 1819 passed vs 1808 baseline | ✅ shipped default-on with kill switches. NEXT: (a) PC2 machine confirm — Event Viewer faulting module + GPU driver update (the actual cure); (b) live source-build sanity on a good GPU (MPR opens unchanged; probe logs `[MPR OPENGL_PREFLIGHT] ok=True`); (c) staged follow-up — reuse the same probe for the other VTK hosts (Advanced viewer, dental VTK-MPR, curved-MPR picking host). Files: `modules/mpr/opengl_preflight.py` (new), `PacsClient/utils/native_fault_log.py` (new), `toolbar_manager.py`, `main.py` (none plugin-mirrored) |

| 2026-07-07 | **ARM64 STRATEGY PIVOT: emulation-first WoA SKU SHIPPED** (user decision — x64-under-emulation is the supported ARM64 path for now; native ARM64 = later phase) | ARM64 machines could only install the classic x64 package silently (no ARM64-aware install, no emulation profile, no WoA diagnostics) | **"AIPacs (ARM64 emulated)" SKU**: `AIPacs_Setup_woa.iss` (ARM64-hosts-ONLY installer of the SAME x64 stage; informative first page; stamps `install_package=x64_on_arm64` into installation_profile.json; same AppId = clean upgrade of a prior x64 install; plain-x64 machines can't install it) + `build_release.py --with-woa-installer` (compiled from the normal x64 pipeline, best-effort, primary artifact never at risk) + classic x64 installer's ARM64 warning now points at the WoA package + `InstallPackageKind` stamped for all three SKUs (x64 / x64_on_arm64 / arm64). **WoA runtime profile** `PacsClient/utils/woa_profile.py` wired in main.py after `[RUNTIME_ARCH]`: on emulated hosts logs `[WOA-PROFILE]` (arch, package kind, VTK/MPR=emulated-x64-via-OpenGLOn12, tuned vars) and applies user-overridable env defaults (`AIPACS_BROWSER_PREWARM=0` — Chromium prewarm is a heavy JIT cost under emulation); pure `decide_woa_tuning`; kill switch `AIPACS_WOA_PROFILE=0`; native machines byte-identical no-op. **Diagnostics completed**: `[MPR-OPEN-KPI] standard_mpr_construct_ms` (toolbar_manager) + `[MPR-GL-CAPS] emulated=/host=` fields | guard tests `test_arm64_packaging.py` **19 green** (incl. WoA iss pins) + NEW `tests/code/system/test_woa_profile.py` **8 green**; parity gate green after `sync_plugin_mirrors.py` (drift = the OPT-22/23 files `prewarm.py`/`viewer_write_adapter.py`, which ARE plugin-mirrored — their "not mirrored" notes were WRONG, corrected in CLAUDE.md + memory) | ✅ x64 machines byte-identical. NEXT: compile all three .iss variants on the next release build (ISCC syntax check); ship the WoA SKU to PC2 + run plan §6 validation (startup, patient/viewport loading, MPR via emulation, `[MPR-OPEN-KPI]`/`[WOA-PROFILE]`/`[MPR-GL-CAPS]` captured) after the pack/driver fix; publish per-arch URLs via `location_by_arch`. Native ARM64 (lite build + VTK wheel) deferred until the emulation path is stable |

| 2026-07-07 | **ARM64 platform foundation SHIPPED (x64-side half of `docs/plans/architecture/ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md` §7)** | no ARM64 packaging path existed; the x64 installer silently installs on WoA via `x64compatible` (how PC2 got the emulated build) | `requirements-arm64.txt` (PySide6>=6.11.1, grpcio dropped, vtk/SimpleITK excluded pending Phase-2/3 source wheels, `#OPTIONAL` best-effort section) + `tools/build/setup_arm64_env.ps1`; `build_release.py --arch {x64,arm64}` (default x64 byte-identical: names, script, behavior; arm64 = cross-build guard + `AIPacs_Setup_arm64.iss` + " arm64"-suffixed artifacts); post-stage **binary PE-architecture scan** (`release_gate.check_stage_binary_architecture`, enforced arm64 / warn-only x64, `AIPACS_ENFORCE_ARCH_SCAN=1`); Inno single-source arch conditionals + x64-on-ARM InitializeSetup warning (SuppressibleMsgBox); `aipacs_runtime`: `resolve_source_location` per-arch update URLs (`location_by_arch`, host-arch keyed, legacy passthrough) + `build_profile()`/`vtk_features_available()` arm64-lite foundation | **13/13 new guard tests** (`test_arm64_packaging.py`) + builder/runtime/module_system parity suites **76 green** (1 pre-existing plugin-mirror drift — user's uncommitted `polygon_interactorstyle.py` et al — fixed via the documented `sync_plugin_mirrors.py`, 411 pairs match) | ✅ x64 pipeline byte-identical (arch suffix "" default). NEXT: ISCC-compile both .iss variants on the next release build; procure the ARM64 builder → Phase 1 arm64-lite build + live validation checklist (plan §6); Phase 2 VTK win_arm64 source wheel |

| 2026-07-07 | **OPT-21 iteration 3 — PC2 is Windows-on-ARM (Snapdragon X Elite): "weak GPU" hypothesis WITHDRAWN; WoA instrumentation shipped** | PC2 identified as ASUS Vivobook S, Snapdragon X Elite, Adreno X1-85 (driver 31.0.137.0), Windows 11 ARM64. GLview proves OpenGL 3.0–4.5 render tests PASS at high FPS on `D3D12 (Adreno X1-85)` / GL 4.6 Mesa — capability is NOT missing. Our x64 frozen build runs under Prism emulation; OpenGL is served by the Microsoft compatibility pack (Mesa GLon12 / `OpenGLOn12.dll`). STRONG external corroboration for the crash class: microsoft/OpenCLOn12#68 (systematic `0xc0000005` in OpenGLOn12.dll on ARM64 incl. Snapdragon X Elite, kills Blender/Godot at GL init/extension discovery; downgrade to pack v1.2403.9.0 fixes Blender), godot#106853, Blender#142859 (Adreno driver). Slow startup = Prism JIT translation (CPU pinned ~100% through the 9.1 s UI-construction window) + known startup stages | SHIPPED default-on: `[RUNTIME_ARCH]` banner + emulation detection (`PacsClient/utils/runtime_arch_log.py` via IsWow64Process2, wired in `main.py`); `[MPR-STEP]` native-call bisector bracketing QVTK ctor→Initialize→Start + `[MPR-GL-CAPS]` VTK ReportCapabilities log (`_mpr_views.py`, `AIPACS_MPR_STEP_TRACE`); "Process architecture" row in the Settings hardware check (`evaluate_hardware` arch item — WARNS on emulation); read-only PC2 evidence collector `tools/diagnostics/collect_pc_crash_evidence.ps1` (Event-Viewer faulting module, WER, D3DMappingLayers version, GPU driver, exe PE arch, `-EnableDumps`) | py_compile OK; **34/34 guard tests green** (preflight 20 + faulthandler 4 + runtime-arch 4 + defer-3d 6) | ⏳ **Next distinguishing steps (in order): (1)** run the collector on PC2 → faulting module (predicts OpenGLOn12.dll); **(2)** compatibility-pack version swap (newest, else known-good v1.2403.9.0) → retry MPR; **(3)** Adreno driver update; **(4)** next build's `[MPR-STEP]`/`[MPR-GL-CAPS]`/native_fault.log land. Full report: `docs/reports/WOA_ARM64_MPR_CRASH_INVESTIGATION_2026-07-07.md`. NOTE: the Qt pre-flight may PASS on this machine while VTK still crashes (GLon12 dies at extension discovery/texture ops, not context creation) — the probe guards the missing-GL class, the step trace + dump pin this one. Long-term mitigation ladder (only after evidence): pack pin on WoA → optional software-GL for MPR → native ARM64 build |

| 2026-07-07 | **OPT-21 iteration 2 — once-per-INSTALL persistence + Settings "Hardware Requirements Check"** (user directive: don't check OpenGL every time; put the test in Settings → Viewer Configuration) | iteration 1 probed once per SESSION on the first MPR click | probe result now PERSISTS to `<config>/hardware_check.json`: persisted PASS = ZERO probing on MPR open (healthy machine probes exactly once ever); persisted FAIL/missing = graceful re-probe + persist (self-heals after a driver update). New `HardwareCheckPanelWidget` (`settings_ui/hardware_check_panel.py`) in `viewerconfigsetting.py`'s right column: persisted result display (OpenGL/GPU, CPU, RAM, free disk — pure `evaluate_hardware`, ok/warning/fail; only OpenGL gates MPR) + "Run Hardware Check" button (`run_hardware_check(persist=True)`, also refreshes the MPR gate). Blocked-MPR dialog now points at the Settings check | py_compile OK (4 files); **22/22 guard tests green** (persistence semantics pinned: persisted-PASS-zero-probe, fail-reprobe-self-heal, run-persists-refreshes-gate, settings wiring) + settings-related suite 15 passed; offscreen import of `viewerconfigsetting`+panel OK | ✅ shipped default-on. `hardware_check.json` is machine-generated state — NEVER seed it as a config template. NEEDS live sanity: open Settings → Viewer Configuration (panel renders; Run updates statuses), MPR unchanged on a good GPU |

| 2026-07-07 | **OPT-20 slot-3 residual: multi-study display-miss — study-blind append dedup FIXED default-on** (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`, default-on) | 49317: distinct SECONDARY-study series `3000001`/`3000002` never displayed while primary/slot-2 did (`[APPLY-ENTER]` present, `refresh=True`, but `[APPLY-GATE]` ABSENT ⇒ render loop gated off by `series_idx<0`). Ruled OUT the token race by static analysis: `[APPLY-STALE-EARLY]=0` + both token gates run on the SAME UI thread with no yield ⇒ token current at 1290 too; and the offset-key stamping aligns (`series_key==str(series_number)==metadata series_number`) ⇒ NOT a key mismatch | ROOT (deterministic): `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py:203-211`) had a **study-blind** dedup — a series sharing a `series_name` AND instance count with an already-present series hit `return False` and was NEVER appended, even with a DIFFERENT `series_number`. Multi-study/previous-exam patients routinely share a name across studies (scout/localizer/DX/repeat) → the distinct secondary series was dropped → `replace_series_data` returned **-1** → `series_idx<0` gated off the render loop → never displayed. Fix: only skip as a TRUE duplicate when the incoming `series_number` is already present; a distinct, not-yet-present number falls through to the existing end-append (no ordering change for any working case). Isolation untouched (own offset number + stamped `study_uid`/`series_uid`; identity gate still fail-closed on `series_uid`) | **8/8 headless checks vs the REAL method** (distinct same-name+count appends; `replace_series_data` returns ≥0 not -1; 3 studies same-name all present; true-duplicate still deduped; diff-count pairing unchanged; flag-off legacy drop + `replace`→-1). `import os` added to `_pw_metadata.py`; py_compile OK. Guard test `tests/code/viewer/test_series_append_study_distinct.py` | ⏳ offscreen-verified; **NEEDS-LIVE-VERIFY on 49317** (drag every series of BOTH studies → all display; `[SERIES-APPEND-DISTINCT] append distinct series=3000001…` in app.log; 0 `[IDENTITY-GATE] SKIP`; slot-3 now reaches `[APPLY-GATE]`+`first_image_visible`). Then collapse the flag. `1100000` document (`[APPLY-ENTER]=0`) remains OPT-07. File `_pw_metadata.py` (not plugin-mirrored) |

| 2026-07-08 | **OPT-22 startup freeze FIX: idle-gate the web-browser Chromium prewarm** (`AIPACS_BROWSER_PREWARM_IDLE_ONLY`, default-on) | 07-07 v3.4.6: `web_browser.prewarm._construct_warm_view` constructed `QWebEngineView` on the GUI thread ~4 s after home load → **21 s** `interaction_active=False` startup stall (ends exactly at "Chromium engine warmed") | `QWebEngineView` is GUI-thread-only (can't off-thread), so the fix is TIMING: warm only after a genuine idle gap (no click/key/wheel for `idle_ms`, default 5 s) past a longer initial delay (default 20 s), poll-recheck, and SKIP the warm if the user stays busy past `max_wait_ms` (default 10 min). Minimal app event filter (discrete events only, removed after warm/skip). Marker-gate + `AIPACS_BROWSER_PREWARM=0` preserved; `IDLE_ONLY=0` = byte-identical legacy | idle/poll/skip decision + both flag defaults validated standalone; EchoMind sibling test green; **py_compile of `prewarm.py` blocked in-sandbox by the FUSE mount caching the old file size (6306 B) — Read-tool confirms the real 314-line file is complete + well-formed**; guard `test_browser_prewarm_idle_gate.py` (host lane) | ⏳ **shipped default-on; NEEDS live verify** (probe on, browser marker armed → no `_construct_warm_view` stall in the first ~60 s; browser still opens; `AIPACS_BROWSER_PREWARM=0` clean). Report `docs/reports/REGRESSION_REVIEW_STARTUP_AND_ECHOMIND_FREEZE_2026-07-08.md` |
| 2026-07-08 | **OPT-23 EchoMind import freeze FIX: defer change_series switch to singleShot(0)** (`AIPACS_ECHOMIND_DEFER_SWITCH`, default-on) | 07-07 v3.4.6: EchoMind dispatch inline on UI thread → `change_series_on_viewer` synchronous; spinner shown but never painted (same event-loop turn); Advanced/VTK `ImageViewer2D`+`Render()` ~2.4 s | `viewer_write_adapter.change_series` now schedules `method_change_series_on_viewer(...)` via `QTimer.singleShot(0, ...)` — matching the real drop (`_vw_dragdrop.dropEvent`), so the spinner paints first and the command-bus/IPC drain returns immediately; the switch itself is unchanged (async for cache-miss). Result semantics unchanged ("async load dispatched") | **3/3 guard tests green in-sandbox vs the REAL adapter** (`test_echomind_defer_switch`: defers-by-default, inline-when-`=0`, spinner-first); `viewer_write_adapter.py` py_compile OK | ⏳ **shipped default-on; NEEDS live verify** (EchoMind `drag_series` → spinner shows, no dead freeze). Follow-ups (report): Advanced/VTK render is GUI-thread-inherent (spinner only); AI-seg `on_contour_closed→requests.post` sync network POST → move off-thread |

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
