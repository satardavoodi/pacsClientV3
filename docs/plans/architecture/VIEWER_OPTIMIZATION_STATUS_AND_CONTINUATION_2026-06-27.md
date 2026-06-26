# Viewer Optimization & Unification — Status & Continuation Guide

**Date:** 2026-06-27 · **Purpose:** one place a future developer/agent reads to continue this work —
what is done and live, what is built-but-staged, what remains, the plan, the flags, and how to test.

---

## 0. READ FIRST — the governing rules (non-negotiable)

1. **Separation HARD RULE.** Fast Viewer, Advanced Viewer, and the VTK modules (MPR / Dental Curve MPR
   / Advanced Analysis / Imaging Analysis / Orthogonal / in-process AI) are **separate execution
   domains** and must stay completely separated. Unify **only** through the read-only trunk; never
   couple two domains. **This outranks every optimization.** Authoritative:
   `CLAUDE.md` (top, "ARCHITECTURE HARD RULE") + `docs/plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`
   (§0.1 rule, §7.1 strict 5-point test for the one shared artifact = the VTK volume).
2. **Optimize top-down, not symptom-by-symptom** — advance the shared spine; retire guards rather than
   stack new ones (`docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md`).
3. **House discipline for every change:** flag-gated (`AIPACS_*`); **default-ON only for correctness
   fixes**, **default-OFF for structural/perf** until live-validated; keep a `=0` kill switch that is
   byte-identical legacy; one guard test (source-pin + functional offscreen); **clinical-lane
   (Windows source build) validation before flipping a structural flag default-on.**

---

## 1. DONE and ACTIVE by default (plain `python main.py`)

These are correctness/robustness fixes + the two monotonic-safe spine layers + the freeze fix. All
default-ON with a `=0` kill switch.

| Area | Flag (default ON) | What it does | File(s) | Guard test |
|------|-------------------|--------------|---------|------------|
| Grow starvation | `AIPACS_PROGRESSIVE_HOT_FORCE` | forces forward progress when a still-downloading series is actively scrolled (45743) | `_vc_progressive.py` | `test_progressive_hot_force_starvation.py` |
| Sibling-study live grow | `AIPACS_GROW_SIBLING_STUDY` | secondary-study series grows live (route by series_uid) | `home_download_service.py`, `_vc_progressive.py` | `test_grow_sibling_study.py` |
| Multi-study thumbnail status | `AIPACS_THUMB_SIBLING_STUDY_STATUS` | side-panel thumbnails turn ready in real time for secondary studies | `home_download_service.py` | `test_thumb_sibling_study_status.py` |
| Resume anti-livelock | `AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND` | kills the 1 Hz reload loop on complete multi-study series (47084) | `_vc_switch.py`, `_vc_progressive.py` | `test_resume_livelock_complete_series.py` |
| Reception breaker | `AIPACS_RECEPTION_BREAKER` | stops hammering a dead report endpoint, per-server (Mehr) | `modules/network/reception_api_config.py` | `test_reception_api_breaker.py` |
| **S2 state authority** | `AIPACS_VIEWER_STATE_AUTHORITY` | additional *monotonic* settled-stop signal (can only stop the resume loop earlier; never loads a wrong series) | `_vc_progressive.py`, `series_state_store.py` | `test_resume_livelock_complete_series.py` |
| **S5 unified teardown** | `AIPACS_VIEWER_UNIFIED_TEARDOWN` | cancels in-flight loads on tab/patient close so a stale apply can't touch a deleted widget | `_vc_switch.py`, `_pw_lifecycle.py`, `viewer_cancellation.py` | `test_unified_teardown_cancellation.py` |
| **Patient-open freeze fix** | `AIPACS_THUMB_BATCHED_RENDER` (+ `AIPACS_THUMB_IMMEDIATE_MAX`=16) | large right-panel thumbnail sets render incrementally instead of one synchronous GUI-thread build (was a ~23s freeze) | `right_panel_widget.py` | `test_thumb_batched_render.py` |
| Log-level fix | (no flag) | false `preview remained active` ERROR → debug | `_vc_switch.py` | — |

These were exercised in live runs and are the safe set.

---

## 2. BUILT but OFF by default (staged / opt-in — NOT running unless you set the flag)

| Stage | Flag (default OFF) | State | Why held |
|-------|--------------------|-------|----------|
| S1b stable identity | `AIPACS_VIEWER_STABLE_IDENTITY` | wired, default-off | load-bearing request-currency flip; needs a live shadow pass first |
| Spine shadow | `AIPACS_VIEWER_SPINE_SHADOW` | read-only diagnostic | logs `[VIEWER-IDENTITY-SHADOW]`/`[STATE-AUTHORITY-SHADOW]`; validation runs only |
| S3b chokepoint shadow | `AIPACS_ENSURE_SERIES_DISPLAYED` | shadow wired in `_feed_state_authority` | measures whether `plan_series_display` agrees with the live path; cutover gated |
| S4b VTK volume cache | `AIPACS_VTK_VOLUME_CACHE` | per-domain cache wired into MPR route + Advanced observe | needs live validation (cross-open lifetime; cross-builder geometry) |
| S4b cache shadow | `AIPACS_VTK_VOLUME_CACHE_SHADOW` | observe-only | measures rebuilds + `[VTK-VOLUME-SHADOW] GEOMETRY DIVERGES` across MPR/Advanced |
| S4b cross-domain reuse | `AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN` | per-domain by default; this shares across VTK domains | opt-in only after the §7.1 strict test passes live |

**Pure foundation modules** (built + unit-tested, mostly unwired — only S2/S5 wiring is live):
`PacsClient/utils/viewer_identity.py` (S0 identity), `series_state_store.py` (S0/S2 state),
`series_display_state.py` + `viewer_request_pipeline.py` (S3a decision), `volume_cache.py` (S4a),
`vtk_volume_service.py` (S4b owner, **per-domain**), `viewer_cancellation.py` (S5a).

---

## 3. The architecture (where the boundary is)

```
SHARED TRUNK (one impl):  download · DICOM files (SOURCE_PATH/<study_uid>/<series>/) · identity
                          (viewer_identity) · per-series state (series_state_store) · S3 decision
                          (viewer_request_pipeline) · metadata/geometry contract · invalidation bus ·
                          KPIs/logging
        │  BRANCH POINT = files-on-disk + identity + state + metadata known
        ├── FAST VIEWER  (lazy 2D memmap + pixmap LRU + Qt raster — VTK-FREE)
        └── ADVANCED / VTK  (SimpleITK→convert_itk2vtk full volume + VTK Volume Cache + VTK render)
                 └── VTK MODULES (MPR / Dental / Orthogonal / AI) — Advanced-branch citizens; share the
                      VTK volume cache ONLY as per-§7.1 (immutable artifact), default per-domain.
```
Full detail: `UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`. Cache-layer detail + current-state file:line
map: `S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md`. End-to-end review: `VIEWER_PIPELINE_ARCHITECTURE_REVIEW_2026-06-25.md`.

---

## 4. WHAT REMAINS — the ordered plan (each flag-gated, live-validated before default-on)

**Gate discipline:** strict order — do not start S3 retirements until S1/S2 are default-ON and soaked;
do not enable cross-domain VTK reuse until the geometry shadow is clean.

1. **S1b live-validate → default-on.** Launch with `run_with_validation.cmd` (sets
   `AIPACS_VIEWER_SPINE_SHADOW=1` + `AIPACS_VIEWER_STABLE_IDENTITY=1` + S2 + S5), switch patients/
   layouts, run `check_validation.ps1`. If `[VIEWER-IDENTITY-SHADOW] grid_slot_reused` fires and
   stable-identity rejections look right, flip `AIPACS_VIEWER_STABLE_IDENTITY` default-on. (Closes A1.)
2. **S3b cutover** (`AIPACS_ENSURE_SERIES_DISPLAYED`). GATED on S1/S2 default-on + soaked **and** the
   S3 shadow showing **0 divergences** live. Then route the 4 entry points to ACT on
   `plan_series_display`, and retire `_PROGRESSIVE_UID_BIND` + the sibling re-keying patches.
3. **S4b-2 live-validate** (MPR cache). `run_s4b_shadow.cmd` → open MPR (+ Advanced) on the same
   series → `check_s4b.ps1`. Need `[VTK-VOLUME-SHADOW]` rebuilds + **0 GEOMETRY DIVERGES**. Then
   `run_s4b_cache.cmd` → reopen MPR on a series → must build once + reopen shows the correct image
   (cross-open `vtkImageData` lifetime is the one thing the sandbox can't prove).
4. **S4b-3b** (Advanced reuse). After S4b-2 validated **and** cross-builder shadow clean: route the
   Advanced build (`image_io.py::load_single_series_by_number` DB path) through
   `get_or_build("advanced", …)`. Still **per-domain** unless `AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN`
   is explicitly opted-in per §7.1.
5. **S4b-4** (memory + retirement). Enable eviction/pin-active, retire the bare-`series_number` VTK
   caches (ZetaBoost L1 dedup → `VolumeCache`), and converge Orthogonal MPR's divergent SimpleITK
   builder onto the one conversion layer. Off-thread build lands here (also addresses task #39).
6. **Task #39** — full-series VOLUME build / `_finalize_progressive_series` off the GUI thread (the
   separate ~3-4 s stall; NOT the patient-open freeze, which is fixed). Folds into S4b-4's off-thread build.
7. **Task #52** — one-time STARTUP init stalls (app/VTK/Qt init); out of the viewer-unification scope.
8. **Freeze-fix follow-up (optional):** if 120 ms/thumbnail is too slow on huge sets, batch N-per-tick
   in `display_next_thumbnail` (right_panel_widget) — responsiveness is already fixed; this is speed.

Open task IDs in the tracker: #39, #52, #57 (S4b-3b), plus S1b/S3b/S4b-4 (to be opened when reached).

---

## 5. Validation tooling

| Script (project root) | Purpose |
|---|---|
| `run_with_validation.cmd` | launch source build with the spine flags (S1 shadow + identity + S2 + S5 + test server) for S1/S2/S3-shadow validation |
| `check_validation.ps1` | scan logs → PASS/WARN for grow-sibling, S1 identity, S2 authority, **S3 chokepoint shadow**, resume-watchdog health, TTFI, stalls, reception breaker |
| `run_s4b_shadow.cmd` / `.ps1` | S4b VTK cache **measure** mode (`AIPACS_VTK_VOLUME_CACHE_SHADOW=1`) — observe only |
| `run_s4b_cache.cmd` / `.ps1` | S4b VTK cache **act** mode (`AIPACS_VTK_VOLUME_CACHE=1`) — only after the shadow gate passes |
| `check_s4b.ps1` | S4b gate: `[VTK-VOLUME-SHADOW]` events, **GEOMETRY DIVERGES = 0** gate, both-builders-seen, rebuild count |

Log markers to grep (in `user_data/logs/viewer_diagnostics.log` + `app.log`): `[VIEWER-IDENTITY-SHADOW]`,
`[STATE-AUTHORITY-SHADOW]`, `[ENSURE-DISPLAYED-SHADOW]`, `[VTK-VOLUME-SHADOW]`,
`[PROGRESSIVE_GROW_FORCE_PROGRESS]`, `[GROW-SIBLING]`, `[MAIN_THREAD_STALL_TRACE]` (the GUI-freeze stack
sampler — grep this FIRST for any hang; it dumps the frozen stack).

---

## 6. Testing notes (important)

- **Two lanes:** (a) offscreen pytest in the Linux sandbox (`tools/dev/sandbox_setup.sh` then
  `python3 -m pytest tests/code/<x> -p no:debugging -q`) — pure + Qt-offscreen, but **no VTK and no
  real GUI**; (b) the Windows source build (clinical lane) — the only lane that proves GUI/VTK/render.
- **Sandbox FUSE caveat (observed heavily this session):** the FUSE mount intermittently serves
  **torn/stale** reads of large files, which breaks whole-file `py_compile` and can make pytest read a
  stale test or hit `INTERNALERROR`. When that happens, verify via the authoritative **Read/Grep
  tools** (they read the real Windows file) and via **direct longest-read checks**; treat a torn
  compile/pytest as an environment artifact, not a code defect. The full test suites run green on the
  Windows `.venv`.
- New guard tests this effort: `tests/code/viewer/test_progressive_hot_force_starvation.py`,
  `tests/code/viewer/test_ensure_displayed_shadow.py`, `tests/code/ui_services/test_vtk_volume_service.py`,
  `tests/code/ui_services/test_thumb_batched_render.py` (+ the existing S1/S2/S5 guards).

---

## 7. Detailed docs & memory pointers

- **Boundary + separation rule:** `docs/plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`
- **Staged spine plan (S0–S5):** `docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md`
- **VTK cache design (4 layers, file:line map):** `docs/plans/architecture/S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md`
- **Architecture review (hazards A1/C1/D1/F1):** `docs/reports/VIEWER_PIPELINE_ARCHITECTURE_REVIEW_2026-06-25.md`
- **Agent memory** (this workspace): the separation rule, S4B architecture, the patient-open freeze
  root cause, the progressive-grow/sibling fixes — see `MEMORY.md` index.

**One-line state:** the user-visible bug fixes + S2 + S5 + the patient-open freeze fix are LIVE by
default; the structural spine (S1 load-bearing, S3 cutover) and the entire S4b VTK cache are BUILT,
per-domain-isolated, and OFF behind flags awaiting the live-validation gates above. Keep Fast /
Advanced / VTK-modules separate; advance only through the trunk.
