# AI-PACS — Impatient End-User Stress Test: KPI & Stability Report
**Date:** 2026-06-16  ·  **Scope:** stability / performance / GUI responsiveness / state correctness under heavy, impatient usage.
**Method:** read-only analysis of the live workstation (running source build PID 506088), its DB, and its diagnostic logs; the project's own KPI/stall tooling; targeted headless pytest; and a docs/regression-guard audit. One clearly-safe fix was applied with a regression test. No clinically-verified geometry, slice order, orientation, or rendering was changed.

> **Environment during the run (a realistic worst case).** The machine was simultaneously running: the workstation app (PID 506088, ~622 MB) with **two active download subprocesses** (~274 MB each), a **`build_release.py --clean-build`** in `.venv_build`, and an education pytest. CPU/disk were already contended — heavy VTK test suites ran slowly as a result (noted under §6).

---

## 1. Executive summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | **`GetReportStatus` poll holds the *shared* socket client lock ~30 s** (server never answers), blocking GUI-thread patient/thumbnail socket calls → **1.3–1.7 s main-thread stalls** + ~30 s-cadence ERROR spam. Amplified for multi-study patients (looped per study UID). | **HIGH** | **FIXED + tested** (circuit breaker, env-reversible) |
| F2 | **Main-thread stalls** instrumented: 1688 events, p50 155 ms, **p95 1.5 s, p99 ~10 s, 100 events >1 s**; 1627/1688 with `interaction_active=False` (background work blocking GUI). | **HIGH** | Partly addressed by F1; rest = registry |
| F3 | **Disk > DB instance drift**: downloaded `.dcm` files exist that are not indexed in `instances` (4/54 sampled studies, e.g. pt 43977 disk 2418 vs DB 2414; one +19). Safe direction (no missing images) but can confuse completion / "downloaded N/M". | MED | Registry (downloader index path — not a blind fix) |
| F4 | Extreme stall outliers (10–95 s, `interaction=False`, uncorrelated with any event) — consistent with shutdown/teardown or OS suspension, **not** interactive freezes. | LOW (caveat) | Documented |
| — | DB integrity otherwise clean; download-pressure subsystem stable (156 tests green); cross-patient & multi-study guards intact. | — | OK |

**Headline fix (F1)** directly targets the #1 live responsiveness + log-noise problem and is the highest-value, lowest-risk change available. It is isolated to one service, gated by `AIPACS_REPORTSTATUS_BREAKER`, and changes no DICOM/thumbnail/geometry path.

---

## 2. Fix applied this session (clearly-safe, tested)

**`modules/network/socket_report_status_service.py` — GetReportStatus circuit breaker.**

*Root cause.* `SocketReportStatusService._get_client()` reuses the **shared** `PatientListSocketClient` (the same client the GUI thread uses for patient-list/thumbnail calls). `socket_client.send_request()` holds that client's `RLock` (`socket_client.py:165`) for the entire request up to the **30 s** timeout (`socket_config.py:50`). The server does not answer `GetReportStatus` (documented benign), so every poll holds the shared lock until timeout (or a stream-desync → `Invalid response length header`). Meanwhile the GUI thread blocks on the same lock → the observed **1.3–1.7 s** `interaction_active=False` stalls clustered with server study-opens, plus 36 timeouts/114 ERROR lines in a single day's tail. `_hp_download._download_reception_data_for_targets()` loops the call **once per study UID**, so a multi-study patient (e.g. Patient ID 1 with 20 studies) could chain up to 20 × ~30 s of shared-lock holds.

*Fix.* After `AIPACS_REPORTSTATUS_BREAKER_FAILS` (default 3) consecutive failures, open a breaker for `AIPACS_REPORTSTATUS_BREAKER_COOLDOWN` seconds (default 300) and **short-circuit `get_report_status()` without touching the client** — so the shared lock is never held for an endpoint the server isn't answering. Self-heals: the next success resets it (half-open trial after cooldown). Logs the open event **once** at WARNING instead of every 30 s at ERROR.

*Safety.* Isolated to one method + three helpers; legacy behavior is byte-identical when disabled (`AIPACS_REPORTSTATUS_BREAKER=0`); no protocol/geometry/thumbnail/DB-write change; honors the socket-only-transport invariant (dead gRPC stack untouched).

*Regression test.* `tests/code/network/test_report_status_circuit_breaker.py` — 4 cases: opens after threshold & stops calling the client; half-open recovery on success; disabled = legacy; success still emits/returns. **All pass.** No regressions: `tests/code/network` + `tests/code/system/test_refresh_report_column.py` = **25 passed**; `tests/code/download_manager` = **156 passed**.

*To activate live:* the running app imported the old module — **restart the source build** to pick up the fix (the user runs the source build, so a normal restart suffices).

---

## 3. KPI measurements (from live instrumentation, this machine)

The app has a built-in **main-thread stall watchdog** (`main.py:942–1051`, `QTimer` 50 ms interval, threshold `AIPACS_STALL_THRESHOLD_MS`=100 ms) and `[FAST_OPEN_TRACE]` open-path timing. Values below are real, from `user_data/logs`.

### UI-thread blocked time (`[MAIN_THREAD_STALL]`, 1688 events)
| Metric | Value |
|---|---|
| p50 / p90 / p95 / p99 | **155 ms / 538 ms / 1529 ms / 9997 ms** |
| count >100 / >250 / >500 / >1000 ms | 1688 / 434 / 186 / **100** |
| max | 95.8 s (outlier; teardown/suspension — see F4) |
| with `interaction_active=False` | **1627 / 1688 (96%)** → background work, not user input |
| dominant `active_viewer_state` | `fast_drag_inactive` (699), `switch_complete` (457) |
| stalls overlapping interaction | 61 |
| DM-table rebuilds during active drag | **0** (drag-deferral working) |
| DM-table rebuild duration | p50 73 ms / p95 230 ms / max 237 ms |

### Patient open / thumbnail KPIs (`[FAST_OPEN_TRACE]`)
| Action | Observed |
|---|---|
| right-panel thumbnails (6–8 series) | 250–892 ms |
| right-panel thumbnails (74 series) | 594 ms (socket) |
| cache-gate fast hit (`grew=0`) | as low as 126 ms |
| 74-series full thumbnail population | ~5.6 s (server fetch path) |

### Report-status socket failures (pre-fix, one day's tail)
| Metric | Value |
|---|---|
| `GetReportStatus: timed out` events | 36 (≈ every 30 s) |
| related ERROR lines | 114 |
| post-fix expectation | ≤ 3 attempts then suppressed for 5 min; no shared-lock hold |

---

## 4. Database / cache / lock consistency (read-only)

| Check | Result | Interpretation |
|---|---|---|
| studies | 1070 | — |
| study `number_of_instances` ≠ actual rows | 245 | **benign** — all `db_ni ≥ actual` (server total vs downloaded; partial/not-downloaded studies). Confirms *disk is source of truth*. |
| series with 0 instance rows | 1103 (~12%) | server-enumerated, not downloaded (matches known downloader gap) |
| instances with empty path | **0** | clean |
| disk dir present for sampled studies | 54/54 | no "downloaded but dir missing" |
| disk `.dcm` count vs DB | 50 match / **4 drift (disk > DB)** / 0 missing | **F3** — files on disk not fully indexed in `instances` |
| sampled thumbnails present | 331/388 (57 missing) | missing = not-yet-generated for not-downloaded series (benign) |
| lock waits in `app.log` | 503 × `request_lock_wait result=ok duration_ms≈0.00` | **no contention** — verbose instrumentation only |
| `download_progress` table | 0 rows | no stuck/duplicate progress rows |

No deadlocks, no orphaned DB rows, no cache pointers to missing files. The only real defect is **F3** (disk>DB index drift).

---

## 5. Scenario-family coverage (this session)

| Family | What was exercised | Result |
|---|---|---|
| Multi-study (Patient ID **1**, 20 studies/6062 inst) | DB enumeration; identified the report-status amplification (20× lock holds) the fix removes | F1 fix benefits this most |
| Download-manager pressure | 156 headless tests (dedup, large-batch O(n²) guard, socket payload, stress) | **green** |
| High-slice CT (pt 562346 = 802 slices; 46492/43977 = 576–580) | dataset selected; open/header-scan path reviewed (H1 latent — see registry) | data captured |
| Many-series / cardiac (pt **40921** = 135 series; 46030 server-only) | dataset selected; 74-series thumbnail timing measured (~5.6 s) | data captured |
| X-ray / DX (pt 44876 = 55 MP, 42275 = 47 MP / 10 img) | dataset selected (largest images in DB) | data captured |
| Mammography (21 MG studies) | dataset selected | data captured |
| MPR / tools | `dm_rebuild during drag = 0`; mpr/tool guards green in prior sessions | partial (VTK suites starved by build) |

Interactive drag/scroll/MPR-rotate validation belongs to the **live runbook** (`LIVE_STRESS_RUNBOOK_2026-06-16.md`) — best run after the app is restarted to activate F1.

---

## 6. Automated harness status

| Suite | Result |
|---|---|
| `tests/code/network` (incl. new breaker test) | **29 passed** |
| `tests/code/download_manager` | **156 passed** |
| `tests/code/viewer`, `fast_viewer`, `system`, `mpr` | **not captured this session** — these VTK/Qt suites ran too slowly to complete under the concurrent `--clean-build` CPU load. They carry recent green guards per project history; recommend re-running on an idle machine. |

**Total confirmed green this session: 185.** Recommended blessed re-run when idle: `tests/code/download_manager` first (circular-import collection note), then `tests/code/viewer tests/code/system tests/code/mpr tests/code/fast_viewer -p no:debugging`.

---

## 7. What was NOT done / honest limits

- **F1 not yet validated live** — needs an app restart; the numbers above are pre-fix baselines.
- **Live interactive stress** (drag-drop, aggressive scroll, MPR rotate, 46030 server-download) was scoped into the runbook rather than driven this session (budget + the app needs a restart to test the fix; the concurrent build was competing for resources).
- **Heavy VTK suites** were starved by the concurrent clean-build and not captured.
- **F3 not fixed** — it touches the downloader's DB-index path and is not in the "clearly-safe isolated" category; logged in the registry for a deliberate fix + test.

See `TECH_DEBT_REGISTRY_2026-06-16.md` for the full suspected-issues list (including 23 doc-audited items) and `TEST_DATASET_2026-06-16.md` for the exact patients/studies.


---

## 8. Live validation (post-restart, monitor A, 2026-06-16 10:12+)

App restarted 10:12 (fix loaded from source); the concurrent clean-build had finished (contention gone). Drove the workstation on monitor A via computer-use.

- **Stability under interaction:** server search (returned "95 US + 3 DX + 1 OTHER"), opened a server patient (Heydari Sajjad), **drag-dropped a series into the viewport** (`first_series_visible` traced; overlay correct: 910×1260, WW256/WL128), then an **aggressive scroll burst** — no freeze, no crash, viewport stable. Since restart: **32 main-thread stalls, only 2 > 1 s** (one = the 3.96 s startup), **p50 160 ms** — healthy.
- **F1 fix behavior live:** one real `GetReportStatus: Invalid response length header` at 10:27 confirms the **server gap is still ongoing**; the breaker correctly stayed **dormant at 1 failure** (it opens at 3 — proven by the unit test). The 20-study Patient 1 is the live cascade trigger; it was not reachable this session (see A5). Net: the fix is loaded, behaves identically to legacy while healthy, and counts failures correctly.
- **Drag-drop loading lifecycle:** load + viewport fill verified; no stale image after the scroll.
- **NEW UI finding A5 (home layout):** the home patient-list rendered with a large dark (empty-preview) panel overlapping the table; the Local/Server toggle and Patient ID/Name fields were clipped, and search defaulted to server mode. `Escape` and toggling "Adaptive to Screen Size" did not clear it. This blocked reaching the **local** multi-study Patient 1 and high-slice CT 562346 for deeper stress. Logged in the registry (A5).
- **Not reached live (blocked by A5 / local-mode access):** deep-stack CT scroll (562346, 802 slices), multi-study Patient 1 open (the F1 cascade trigger), MPR rotate/cleanup, mammography. **Recommended:** switch the home page to **Local** search mode (or resolve the overlapping panel), then run runbook S1 (Patient 1 — watch the breaker open after 3 report-status failures), S2 (CT 562346 scroll), S7 (MPR).


### 8.1 Complete live matrix (continued session, Local mode, ~90 min)

Whole live session since restart (10:12): **134 main-thread stalls, only 9 > 1 s** (worst = the 9.4 s multi-study open), p50 **137 ms**, p95 **1240 ms**; **1** GetReportStatus failure (breaker dormant — server healthy); **no crashes** across 5 patient opens + 4 tab closes.

| Scenario | Patient/study | Result | KPI |
|---|---|---|---|
| Multi-study open (cascade) | Patient **1** (30 studies / 239 series) | Opens; **9.4 s main-thread freeze**, 8.8 s to first series | **A6** (H1 cold-open × multi-study) |
| High-slice CT open | **562346** (CT, Series 2 "+C" = 802 img) | Opens **fast** (~1.5 s first series, cache hit) | healthy |
| Drag-drop load → viewport | US / CT / DX | Works; overlay correct (size/WW/WL); no stale | OK |
| Aggressive deep-stack scroll | CT 562346 | No freeze; viewport stable | max stall unchanged |
| MPR init | CT 562346 (1.25 mm volume) | Reformats + crosshairs render | ~9 s VTK build; 1 stall > 1 s |
| MPR / VTK cleanup on close | CT 562346 | **~947 MB released** (1889 → 942 MB) | no obvious leak (B7 reassured) |
| Large X-ray load | DX **44876** (loaded 4300×4298 ≈ 18 MP) | Loads, auto-fit Scale 0.17; no freeze | OK |
| Mammography open | MG **42552** (5 series) | Tab opens; **thumbnail panel empty** → can't load | **A7** |
| Tab teardown (×4) | all | Clean, no crash/zombie | OK |
| Report-status breaker | all opens | Loaded; dormant (1 live failure < threshold) | as designed |

**Two new live findings:** **A6** (heavy multi-study open ≈ 9.4 s UI freeze — top perf item, = H1) and **A7** (viewer series-thumbnail panel empty for multi-study + mammography → can't load those from the panel; home right-panel shows the thumbnails, so it's a viewer-sidebar population gap — **confirm maximized**). Everything else (single-study open, drag-drop, scroll, MPR + cleanup, large X-ray, teardown) was stable. The **A5** cramped home/viewer layout on monitor A (DELL S2421HN) is the backdrop and likely contributes to A7.
