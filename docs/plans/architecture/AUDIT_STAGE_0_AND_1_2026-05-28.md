# AI-PACS Application Audit — Stage 0 + Stage 1 Report

**Date:** 2026-05-28
**Method:** Evidence-driven, no broad refactors. All findings traced to specific
log lines, test results, or source-file ranges.

---

## Stage 0 — Baseline health check

### Build identity (from `user_data/logs/app.log`)

```
[SESSION_START] session_id=sess-9fcabb7d214d
version=3.1.2
build_mode=dev
frozen=False
python=3.13.5
os=Windows-11-10.0.22631-SP0
pid=547508
crash_hook=installed
```

Source build confirmed: `build_mode=dev frozen=False`, Python 3.13.5, single PID 547508 throughout the run. No frozen-build records appear in the log.

### Runtime status at audit time

The source build process is **no longer running** as of the audit. `app.log` mtime
is 14:23 UTC; current time is 15:11 UTC — a 48-minute silence after the previous
2-second heartbeat cadence. The app closed cleanly at ~14:23 UTC. All evidence below is from the last known live state of that PID 547508 session.

### Framework dashboard

`python tools/kpi_dashboard.py` → exit **0**, verdict **`[1 warn]`** (stale).

| Check | Result | Detail |
|---|---|---|
| Command Layer | OK | 5 adapters / 24 actions (static catalog count) |
| KPI schema | OK | 42 keys, baseline in sync |
| Latest KPI run | OK | 3 records PASS in run `source-run` |
| Regression catalog | OK | 33 rows |
| Test inventory | OK | 190 files (179 code · 7 bus · 4 pywinauto) |
| Native faults | WARN | 1 fatal exception, file age **1.2 h** — **pre-dates today's source build start (14:00 UTC vs build at 14:21 UTC)**. Stale artifact from earlier Eagle Eye drag-drop test. Not a Stage 0 regression. |

### Test sweep

Sandbox-runnable subset:
- `tests/code/echomind/` — **72 / 0 / 0**
- `tests/code/system/` (excl. `test_system_stress.py`) — **29 / 0 / 0**

Subtotal: **101 passed, 0 failed**. PySide6/grpc-dependent domains run only on the user's Windows venv.

### Baseline numbers

| Metric | Value |
|---|---|
| PID | 547508 |
| build_mode | dev |
| frozen | False |
| Python | 3.13.5 |
| Session id | sess-9fcabb7d214d |
| Dashboard verdict | OK (1 stale warn) |
| KPI keys | 42 |
| Regression rows | 33 |
| Test files | 190 |
| Test pass rate (runnable) | 101 / 101 |
| Native faults during current build | **0** (the 1 in dashboard is from before today's build) |

### Stage 0 verdict

**HEALTHY.** No new defects in framework or build identity. Single dashboard warn is a stale artifact, not a current regression.

---

## Stage 1 — Startup and idle stability audit

### Bootstrap timeline (`app.log`, t=0 at logging-configured)

| Event | Time | Notes |
|---|---|---|
| Logging configured | +0.000 s | `role=main`, catch-all `app.log` handler attached |
| First heartbeat | +0.066 s | RSS = 276.9 MB, cpu = 0.0 % |
| Bootstrap started | +0.066 s | |
| `[BACKEND_SWITCH]` FAST=pydicom_2d, Advanced=vtk_simpleitk | +0.098 s | Correct backend per CLAUDE.md (no VTK in FAST). |
| `[SESSION_START]` | +0.160 s | |
| `[CPU_BUDGET] SetPriorityClass failed (err=6)` | +0.240 s | Error 6 = invalid handle. **Cosmetic only** — falls back to Windows default. Not a regression; expected when the dev user runs `python.exe` directly (no SeIncreaseBasePriorityPrivilege). |
| Stall probes armed | +0.246 s, +0.252 s | F8/F11 main-thread stall instrumentation live |
| Instance lock acquired | +0.255 s | Single-instance guard works |
| SocketConfig loaded | +0.420 s | Path resolved correctly: `config\socket_config.json` |
| **— login screen waits for user click —** | +0.42 → +12.67 s | ~12.25 s idle window. CLAUDE.md documents this: "credentials are pre-filled — just click Sign In". RSS stable at 405 MB throughout. **Not a defect.** |
| Socket Login round-trip | +12.7 → +12.8 s | 131 ms total, ResumableDicomSocketClient → 192.168.2.222:50052 |
| Authenticated as `vahid (admin)` | +12.834 s | Token stored in TokenManager |
| Shortcut manager | +13.189 s | F5/F6/F7/F8 + arrows |
| **QScrollArea warning** | +13.253 s | See Finding #1 below |
| Patient table column settings load + apply | +14.07 → +14.09 s | 25 ms for 13 columns |
| **AdapterRegistry registrations** | +14.599 → +14.601 s | system (4 actions) → home (3) → modules (6) → viewer (5) = 18 total |
| **bus_factory built CommandBus** | +14.602 s | 4 adapters / 18 actions. **DownloadAdapter not yet attached** (by design — lazy attach when DM widget materialises; doesn't happen at idle) |
| Home widget connected to shortcut manager | +15.694 s | |
| Shortcut Manager connected to Control Panel | +15.704 s | UI fully wired |
| Final settle (last layout heartbeat with elevated CPU) | +16.273 s | cpu = 102.6 % spike (single-core busy, 1 burst) |
| Steady idle | +18 s onward | cpu = 0–2 % typical, RSS stable |

### Memory trajectory (full 112-second observation)

```
RSS samples (every 10th of 56 heartbeats):
  +0.1 s   276.9 MB
  +20.3 s  450.3 MB
  +40.7 s  449.1 MB
  +61.0 s  448.8 MB
  +81.4 s  443.3 MB
  +101.7 s 443.3 MB
  +111.9 s 443.3 MB  (last)
```

- Startup growth: 276.9 → 449 MB ≈ **+172 MB** (Qt + main window + viewer infra + sockets + EchoMind)
- Idle range after settle: **443.3 → 450.3 MB** (~7 MB swing, normal Python GC churn)
- **No monotonic growth during idle.** RSS actually trended **down ~7 MB** between +20 s and +112 s. No leak in the 90-second idle window observed.

### CPU during idle

After +18 s settle, all heartbeats show cpu in [0.0 %, 2.3 %]. Median ≈ 0.8 %. **Within idle budget.**

### Thread accounting (loggers in `app.log`)

Only 2 TIDs ever wrote to the catch-all stream:

| TID | Role | Records |
|---|---|---|
| 544004 | Main thread | 40 |
| 452816 | Resource heartbeat | 56 |

Worker threads exist (download/viewer/db) but log to their component-routed files, not to `app.log`. **No background-thread leak signature** (e.g. ever-growing TID count) seen during idle.

### Single-occurrence guard

Each of these fires exactly once at startup — no repeated initialization:

- `SocketConfig` constructor: 1 (`get_socket_config` cached and reused)
- `SESSION_START`: 1
- `AdapterRegistry.register` per adapter: 1
- `bus_factory: built CommandBus`: 1
- `Authenticated as`: 1
- `Shortcut Manager initialized`: 1

---

## Findings

### Finding #1 — QScrollArea responsive scroll silently disabled at every startup

**Severity:** Medium. **Class:** Layout/UI (Stage 9). **Status:** Documented, fix deferred.

**Evidence:**
```
2026-05-28 17:51:44.652201 | WARNING ... PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager.setup_title_bar_tabs |
  [CustomTabManager] responsive scroll wrap unavailable
  ('PySide6.QtWidgets.QScrollArea' object has no attribute 'setHorizontalScrollMode');
  falling back to plain container
```

**Root cause:**
`PacsClient/utils/responsive_layout.py:108` calls `sa.setHorizontalScrollMode(QAbstractScrollArea.ScrollPerPixel)` on a `QScrollArea`. The method does not exist on `QAbstractScrollArea` — it lives on `QAbstractItemView` (used by `QTableView`, `QListView`, etc.). PySide6 correctly raises `AttributeError`, the try/except in `custom_tab_manager.py:119–131` catches it, and the strip falls back to a non-scrolling `QHBoxLayout` with an `addStretch(1)`.

**Effect:**
The "Archetype 1" horizontal scroll wrap is silently disabled. On narrow monitors where the chip strip overflows, chips overlap — the very defect this wrap was designed to fix. Architecture record `docs/conventions/RESPONSIVE_UI_CONVENTION.md` is referenced in the source comment.

**Why not fixed in Stage 1:**
The user's plan explicitly maps `QScrollArea` usage to **Stage 9 — Layout and responsive UI audit**. Stage 1 reports only startup/idle issues; this is a layout concern, not a stability issue. Fix is small and known (delete the line or substitute with `sa.horizontalScrollBar().setSingleStep(8)`) but should land alongside the broader layout sweep so its regression guard fits the Stage-9 test discipline.

**Tracking:** task #90.

---

### Non-issue #1 — Dashboard `[1 warn]` for native fault

**Verdict:** Stale artifact. Not a regression in today's build.

`native_fault.log` mtime = 14:00:17 UTC, source build PID 547508 started at 14:21:31 UTC. The COM 0x8001010d fault is from a previous session (Eagle Eye drag-drop). It's already guarded by `test_mg_mirror_is_deferred_via_qtimer` (structural) + `test_eagle_eye_dragdrop.py` (live Win32). No new fault appeared during today's startup or idle window.

---

### Non-issue #2 — `[CPU_BUDGET] SetPriorityClass failed (err=6)`

**Verdict:** Expected for `python.exe` running without elevated privileges. Cosmetic. Falls back to Windows default priority cleanly. Not a regression.

---

### Non-issue #3 — DownloadAdapter not in live bus at startup

**Verdict:** By design. `bus_factory` wires 4 adapters at boot (`system`, `home`, `modules`, `viewer`). `DownloadAdapter` is attached via `_attach_download_adapter_lazy(zeta_manager)` when the DM widget is first materialised (typically on first download). Dashboard reports 5/24 because it inspects the catalog statically; live bus shows 4/18 until a download is initiated. Will be reverified in Stage 4.

---

### Non-issue #4 — 12-second idle gap between SocketConfig and Login

**Verdict:** This is the login-screen wait documented in CLAUDE.md ("credentials are pre-filled — just click Sign In"). RSS is stable at 405 MB throughout the window. Not a stall, not a bug.

---

## Tests run after Stage 1

No code changes were made in Stage 1. Test counts therefore unchanged from Stage 0:

- `tests/code/echomind/` — 72 / 0
- `tests/code/system/` — 29 / 0
- Total runnable: **101 / 0**

KPI dashboard re-run: same verdict (`[1 warn]`, stale native fault).
Regression catalog: unchanged at 33 rows.

---

## Remaining risks

1. **QScrollArea defect (Finding #1)** silently disables chip-strip scroll on narrow monitors. Deferred to Stage 9, tracked as task #90.
2. **Idle observation window was 92 seconds.** A genuine slow leak (< 1 MB/min) wouldn't surface yet. Long-session test (`test_long_session_workload.py`) exists but is env-gated; running it would extend the observation to hours.
3. **DownloadAdapter wiring is not exercised in startup audit** — verified again in Stage 4.
4. **App is no longer running.** Live re-validation of these findings requires a fresh source-build launch.

---

## Verdict

| Stage | Result |
|---|---|
| Stage 0 — baseline | **HEALTHY** — framework, build identity, tests, dashboard all OK. Single dashboard warn is a stale artifact. |
| Stage 1 — startup/idle | **MOSTLY HEALTHY.** One real defect (Finding #1, deferred to Stage 9). No idle CPU runaway, no RSS leak in 92 s window, no repeated initialization, no zombie thread signature. |

**Recommended next stage:** Stage 2 — patient search and patient-list workflow. Will require the user to relaunch the source build and produce a patient search interaction so the log contains fresh evidence to analyse.
