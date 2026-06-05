# AI-PACS Testing & Automation Architecture Review — 2026-06-04

**Goal:** a testing framework that pushes the software much harder than a human can — high event
rates, concurrency, repeatable stress scenarios, deterministic failure reproduction — by letting
agents invoke application functions directly instead of driving the mouse.

**Context that motivates this:** the 2026-06-04 stress test (`STRESS_TEST_REPORT_2026-06-04.md`)
was driven through computer-use mouse automation at ~1 action/2–4 s. Even at that modest rate it
exposed BUG-1 (orphaned drop-await loop), BUG-2 (`admitted_count`), and BUG-3 (swallowed clicks).
The mouse layer was the bottleneck: every additional order of magnitude of event rate is currently
unreachable, and every run costs an agent-hours-scale session that is only semi-reproducible.

---

## 1. Current GUI testing infrastructure — review

### 1.1 What exists (three driver tiers, already well-architected)

| Tier | Location | Mechanism | Drives |
|---|---|---|---|
| In-process headless | `tests/code/` (~66k lines) | direct signal `.emit()` + `QApplication.processEvents()`, offscreen QApplication; `tests/code/diagnostics/harness.py` orchestrates multi-signal scenarios + 20 failure detectors | state machines, DM, progressive pipeline, viewer logic |
| In-process live bus | `tests/gui/echomind_driven/` (9 tests) | **CommandBus** `bus.execute(CommandPlan(...))`; dual fixture: `FakeHomeAdapter` (CI-safe) / `live_bus` via `secretary_bridge.get_runtime_home_widget()` against the running app | search, patient open, bulk download, cross-patient isolation, long-session KPI |
| OS-level | `tests/gui/pywinauto/` (5 tests) | pywinauto 0.6.9 (UIA backend), attach by window title, `click_input()` / `drag_mouse_input()` (real Win32 + OLE) | open/close cycles, zombie check, **real OLE drag-drop** (`test_eagle_eye_dragdrop.py` — the only thing that exercises the 0x8001010d surface), thumbnail pixel isolation |

Support assets: `tests/_kpi/collector.py` (KPI thresholds, auto-records from CommandBus),
`tools/performance/clearcanvas_aipacs_kpi_harness.py` (~20 structured log-tag extractors:
FAST_DRAG_KPI, INTENT_PRIORITY, SLOT_TIMING, DM_REBUILD…), `tools/reliability/process_soak_sampler.py`
(RSS/threads/handles per cycle, human-driven), `tests/gui/live_walkthroughs/_verify_source_build.py`
(never-test-the-frozen-exe gate).

### 1.2 Strengths

The fake/live dual-fixture CommandBus pattern is the standout: the same test code runs CI-safe and
against the live app. Observability is strong (structured log tags + KPI collector + native_fault
baselining). The pywinauto tier is correctly reserved for what only it can do (real OLE, real
window lifecycle). Coverage breadth at the unit level is excellent (DM state machine, progressive
pipeline, MPR routing, multi-study guards).

### 1.3 Bottlenecks for high-pressure testing

1. **No external command injection.** The CommandBus is in-process only; `live_bus` works only when
   pytest runs inside the same interpreter as the app — which is not how the app is normally run.
   Agents therefore fall back to the mouse.
2. **No high-rate replay.** pywinauto walkthroughs are single-shot clicks seconds apart; nothing can
   fire dozens of actions/second, overlap actions, or run the same aggressive timeline twice.
3. **Event-level realism gap in fast tiers.** `tests/code` injects signals *below* the input layer —
   the click-debounce, drag-dwell, OLE-loop, and spinner logic (where BUG-3 and Crash A live) is
   never exercised except by slow OS-level tests.
4. **Single-instance lock** prevents parallel instances; tests serialize.
5. **Post-hoc KPI only.** Log parsing happens after the session; no live pass/fail while a scenario
   runs.
6. Not installed (would help): pytest-qt, pytest-xdist, hypothesis. Installed and sufficient:
   pywinauto, pytest, pydantic, qasync.

### 1.4 Coverage audit (target workflows × stress)

| Workflow | Functional coverage | Under load/race pressure |
|---|---|---|
| Search | echomind_driven + logging guard | bulk only via fakes |
| Thumbnail loading | unit + isolation guards | **no concurrent-load race tests** |
| Double-click open | source-regex guard + pywinauto smoke | **no rapid single/double interleave** (BUG-3 class untested) |
| Drag-and-drop | OLE (3 drags), in-process progressive | **no drop-before-download bursts** (BUG-1 class found only manually) |
| Download manager | 15 suites incl. preemption | good in-process; no real-network churn |
| Viewer (FAST) | 70+ modules | scroll stress yes; grow-under-budget races thin (BUG-2 escaped) |
| MPR | launch route + VTK bridge | **no open/close cycling under download** |
| Multi-patient | tab guards + `test_system_stress.py` | fakes only; no live tab churn |

---

## 2. Secretary / EchoMind infrastructure — review

### 2.1 Architecture (verified)

`modules/EchoMind/secretary/`: **CommandBus** (`command_bus.py` — `parse / execute / dispatch /
dispatch_async / actions`), Pydantic envelopes (`command_envelope.py` — `CommandPlan{action,
entities, confidence…}` → `CommandResult{ok, action, message, data, error_code, elapsed_ms}`),
**AdapterRegistry** (`registry.py` — action → adapter method, auto-normalizes results),
**bus_factory.py::build_command_bus** — instantiated in
`PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py` (~L233-247) as
`home_widget.command_bus`. Bridge: `modules/EchoMind/secretary_bridge.py::get_runtime_home_widget()`.

Registered adapters and their reach into the live app:

| Adapter | Commands | App functions called |
|---|---|---|
| HomeCommandAdapter | `list_patients`, `open_patient`, `download_patient`, `search` | `_on_patient_double_clicked(...)` (the REAL open path), `_on_download_requested(...)`, `patient_list_function_identifier` |
| ViewerCommandAdapter (read-only) | `get_active_tab`, `list_open_tabs`, `get_thumbnails_data`, `get_active_series`, `get_multistudy_info` | attribute reads on the live tab |
| DownloadCommandAdapter (lazy-wired) | `cancel/pause/resume_download`, `check_download_status`, `list_downloads`, `download_statistics` | DM widget + `state_store` |
| ModuleCommandAdapter | `open_module`, `open_mpr`, `toggle_eagle`, … | launcher callables (MPR = the real `toggle_zeta_mpr` route) |
| SystemCommandAdapter | `snapshot_resources`, `count_native_faults_since`, `probe_idle_cpu`, `count_aipacs_processes` | psutil + log probes — **built-in failure detection** |

### 2.2 Determinations

**Can EchoMind directly invoke application functions? YES — today, in-process.** `open_patient`
already calls the same `_on_patient_double_clicked` a mouse double-click reaches; `open_mpr` reaches
the real MPR launcher; downloads enqueue through the real DM API. This is exactly the substrate the
requested MCP needs.

**Can it be extended for deeper control? YES, with four specific gaps:**
1. **No external transport** — the bus is unreachable from outside the process (the single reason
   agents currently use the mouse).
2. **No Qt main-thread marshalling in the bus** — callers must already be on the GUI thread; an
   external transport must add queued dispatch or it will corrupt Qt state.
3. **Viewer write-side is deliberately absent** (multi-study guardrails): no `change_series`,
   `change_layout`, `close_tab`.
4. **Study-level granularity only** for downloads; no series-level trigger/wait.

---

## 3. Automation layers — review (the "AutoWin" question)

There is no "AutoWin" as such; the equivalent stack is: **pywinauto 0.6.9** (only OS-level injector;
UIA backend; supports real OLE drag — keep it, it is irreplaceable for Crash-A-class regressions),
**computer-use MCP** (agent-driven screenshots+clicks — what ran the 2026-06-04 stress test; slow,
non-deterministic, but currently the only externally-reachable control), **Windows-MCP / Desktop
Commander** (shell + window management, used for launch/kill per the launch SOP), and the
**CommandBus** (the underused asset: full app-function reach, zero exposure).

**Underused capabilities ranked:** (1) CommandBus + adapters — 80 % of the requested MCP surface
already implemented, unexposed; (2) the single-instance `QLocalServer` pattern
(`PacsClient/utils/single_instance_lock.py`) — proven, crash-safe local IPC code to copy for a test
server; (3) `SystemCommandAdapter` — ready-made in-run failure detector (native-fault count,
resources) nobody calls during tests; (4) the KPI collector + log-tag extractors — could grade a
stress run automatically; (5) `dispatch_async`/qasync — an async path that external transport can
build on.

---

## 4. AI-PACS Control MCP — design proposal

### 4.1 Architecture (three layers, two new)

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent (Claude / pytest / scenario runner)                        │
│   └── aipacs-control MCP server  (NEW — stdio, thin client)      │
│        tools: OpenPatient, DragSeries, OpenMPR, Query*, Burst,   │
│               RunScenario, WaitForDownload, SnapshotHealth        │
└───────────────┬─────────────────────────────────────────────────┘
                │ JSON-lines over QLocalSocket "AIPACS_TEST_<user>"
┌───────────────▼─────────────────────────────────────────────────┐
│ In-app Test Control Server (NEW — env-gated AIPACS_TEST_SERVER=1)│
│   QLocalServer (clone of single_instance_lock pattern)           │
│   → MainThreadDispatcher (queued signal → Qt main thread)        │
│   → existing CommandBus (home_widget.command_bus)                │
│   → NEW adapters: ViewerWriteAdapter, InputInjectAdapter         │
└───────────────┬─────────────────────────────────────────────────┘
                │ direct method calls (same functions the GUI uses)
│ AI-PACS application (unchanged behaviour; guards still enforced) │
```

**Layer A — In-app Test Control Server** (`modules/EchoMind/secretary/test_server.py`):
QLocalServer accepting one JSON command per line (`{"action": "...", "entities": {...}, "id": n}`),
replying with the serialized `CommandResult`. Every command is marshalled to the Qt main thread via
a queued-connection signal (`MainThreadDispatcher(QObject)` with
`request = Signal(object)` connected `Qt.QueuedConnection`) — commands therefore interleave with
real user/event traffic exactly like posted input, never corrupt Qt state, and *naturally arrive
faster than the app can finish prior work*, which is the requested pressure model. **Hard safety
gates:** starts only when `AIPACS_TEST_SERVER=1`; refuses to start in the frozen build; logs a
banner; per-user socket name.

**Layer B — `aipacs-control` MCP server** (`tools/testing/aipacs_control_mcp/`): a small stdio MCP
(python `mcp` package) exposing the tool surface below; it owns conveniences the in-app layer
shouldn't (timeouts, polling waits, scenario files, KPI grading).

**Layer C — Scenario engine** (inside the MCP + runnable headless from pytest): YAML scenarios,
burst execution, deterministic seeds, session recording.

### 4.2 Tool surface (requested commands → implementation)

| MCP tool | Status today | Implementation |
|---|---|---|
| `OpenPatient(patient_id)` | EXISTS | `home.open_patient` → `_on_patient_double_clicked` |
| `ClosePatient(patient_id)` | NEW | ViewerWriteAdapter → main tab widget close-tab path (same handler as the tab X) |
| `LoadThumbnail(patient_id)` | PARTIAL | `home.search`+single-click reconcile path (`show_patient_studies`) wrapped as `select_patient`; read-back via `viewer.get_thumbnails_data` |
| `DragSeries(series_id, viewport_id)` | NEW | ViewerWriteAdapter.`change_series(viewport, series_number)` → `ViewerController.change_series_on_viewer(...)` — the precise function a real drop defers to (`_vw_dragdrop.dropEvent` → `QTimer.singleShot(0, _do_series_switch)`); optional `mode="drop_event"` posts a constructed `QDropEvent` (x-aipacs-series-number MIME) at the viewport so dwell/payload/spinner code runs too |
| `OpenMPR(series_id)` | EXISTS | `modules.open_mpr` (real `toggle_zeta_mpr` route) |
| `ChangeLayout(layout_id)` | NEW | ViewerWriteAdapter → toolbar layout handler |
| `TriggerDownload(series_id)` | PARTIAL→NEW | study-level exists (`home.download_patient`); series-level via the intent coordinator (`request_critical_series_download` — same path a drop triggers) |
| `WaitForDownload(series_id, timeout)` | NEW (MCP-side) | poll `download.check_download_status` / series progress until terminal or timeout |
| `QueryDownloadState(series_id)` | EXISTS | `download.list_downloads` / `check_download_status` |
| `QueryViewportState(viewport_id)` | EXISTS+extend | `viewer.get_active_tab` + per-viewport: series number, slice count/position, progressive state, `_awaiting_series_number`, spinner visible — the exact fields the BUG-1 debugging needed |
| `QueryThumbnailState(patient_id)` | EXISTS | `viewer.get_thumbnails_data` (+ per-card download counts/border state) |
| `Click/DoubleClickPatient(row)` | NEW | InputInjectAdapter: `QApplication.postEvent` of real `QMouseEvent` press/release (and dblclick) at the patient-table row — runs the genuine debounce/click-timer code (BUG-3 class) at arbitrary rates, no OS mouse |
| `Burst(commands, interval_ms, jitter, seed)` | NEW | MCP fires command list with given pacing; intervals can be 0 (back-to-back queued) |
| `RunScenario(file, seed)` | NEW | executes a YAML scenario (below) |
| `SnapshotHealth()` | EXISTS | `system.snapshot_resources` + `count_native_faults_since` + error-census — pass/fail per step |

### 4.3 Fidelity tiers — preserving realism

Direct function calls alone would *skip* the input layer where several real crashes live, so every
write tool declares its tier and scenarios mix them:

- **T1 state-level** (CommandBus functions): maximal rate (100s/s), deterministic — for race/state
  stress (BUG-1/BUG-2 class).
- **T2 widget-event-level** (InputInjectAdapter: posted `QMouseEvent`/`QDropEvent`): runs real Qt
  handlers — debounce, dwell, drop parsing, spinners — at high rates (10–50/s) with no OS cursor.
- **T3 OS/native-level** (existing pywinauto): real Win32 + OLE `DoDragDrop` — the only tier that
  exercises the Crash-A surface; used as a periodic regression lap, not for rate.

### 4.4 Determinism & reproduction

Scenario YAML (seeded): `steps: [{tool, args, at_ms | after: step_id, tier}]`; jitter drawn from
`random.Random(seed)`. The MCP records a **session JSONL** — every command, send-time, result,
`elapsed_ms`, plus periodic `SnapshotHealth` — so any failing run replays exactly
(`RunScenario(recording.jsonl)`) and bisects (binary-search the step list). Failure criteria per
run: native_fault delta = 0, ERROR census ⊆ allowlist, KPI thresholds (`tests/_kpi`), and
scenario-specific asserts (e.g. "viewport non-empty within 60 s of drop" — the BUG-1 oracle).

### 4.5 Example scenario (the requested sequence, encoded)

```yaml
name: impatient_full_loop
seed: 1337
loop: 10            # repeat whole sequence
steps:
  - {tool: Search,            args: {modality: CT, date: yesterday}}
  - {tool: ClickPatient,      args: {row: "$rand(0,8)"},          tier: T2}
  - {tool: DoubleClickPatient,args: {row: "$same"},  after_ms: 120, tier: T2}   # inside debounce window
  - {tool: DragSeries,        args: {series: 201, viewport: 0},  after_ms: 300} # before thumbnails/info load
  - {tool: DragSeries,        args: {series: 202, viewport: 1},  after_ms: 80}
  - {tool: OpenPatient,       args: {patient_id: "$next"},       after_ms: 200} # second patient mid-download
  - {tool: DragSeries,        args: {series: 201, viewport: 0},  after_ms: 150}
  - {tool: SwitchTab,         args: {index: 0},                  after_ms: 100}
  - {tool: SwitchTab,         args: {index: 1},                  after_ms: 100}
  - {tool: OpenMPR,           args: {},                          after_ms: 250}
  - {tool: ChangeLayout,      args: {layout: "2x2"},             after_ms: 200}
  - {tool: ClosePatient,      args: {index: 1},                  after_ms: 150} # close under load
  - {tool: SnapshotHealth,    assert: {native_fault_delta: 0, errors_new: 0}}
```
At T1/T2 speeds this loop runs ~20× faster than the manual 2026-06-04 session and is repeatable
byte-for-byte — precisely the BUG-1/BUG-2/BUG-3 hunting ground.

---

## 5. Recommended architecture — summary of decisions

1. **Reuse, don't rebuild:** the CommandBus + adapters are the control plane; the test server and
   MCP are thin transports around them.
2. **Queued main-thread dispatch** is non-negotiable — it is both the Qt-safety mechanism and the
   pressure model (commands queue up against real event traffic).
3. **Three declared fidelity tiers** so speed never silently sacrifices realism; OLE stays on
   pywinauto.
4. **Env-gated, source-build-only** test server; clinical guards (cross-patient isolation,
   multi-study invariants) remain enforced because commands run the same app functions.
5. **Session recording + seeds** make every failure a replayable artifact, ending the
   "watch the screen and hope" era.

## 6. Priority implementation roadmap

| Phase | Scope | Effort | Unblocks |
|---|---|---|---|
| **P0** | In-app Test Control Server (QLocalServer + MainThreadDispatcher + JSON protocol) exposing the EXISTING bus actions; 20-line CLI client; smoke: OpenPatient/Query*/SnapshotHealth burst | ~1–2 days | external agents drive the app at all |
| **P1** | ViewerWriteAdapter (`change_series`, `change_layout`, `close_tab`, viewport state query) + series-level `TriggerDownload` + `WaitForDownload`; honor multi-study guards (`docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`) with guard tests | ~2–3 days | the full requested command set incl. DragSeries(T1) |
| **P2** | `aipacs-control` MCP server + Burst/RunScenario/JSONL recording + KPI/health grading; encode 5 scenarios (impatient_full_loop, drop_before_download, tab_churn_under_load, mpr_cycle, thumbnail_race) | ~2–3 days | agent-driven, repeatable high-pressure runs |
| **P3** | InputInjectAdapter (T2 posted events: clicks, dblclick, QDropEvent) + rate engine | ~2 days | debounce/dwell/spinner race coverage (BUG-3 class) |
| **P4** | pywinauto T3 lap integrated into scenarios (OLE regression for Crash A); nightly soak job (N loops, sampler attached, auto report); optional pytest-xdist for the fake-bus tier | ~2 days | continuous regression pressure |

**First proof-of-value (end of P0+P1):** encode the exact BUG-1 repro (open A → open B → 2 drops
→ wait) as a scenario and confirm it (a) passes on the fixed build, (b) fails loudly on a checkout
without the fix — the framework's first regression guard, replacing a 25-minute manual GUI session
with a ~90-second deterministic run.

---
*Sources: repo exploration 2026-06-04 (tests/, modules/EchoMind/secretary/, PacsClient/utils/,
tools/); `STRESS_TEST_REPORT_2026-06-04.md`; `CRASH_STABILITY_INVESTIGATION_2026-06-03.md`;
`UNIFIED_COMMAND_LAYER_2026-05-27.md`; command-layer memories (Phases 1/3/4 + Phase A).*
