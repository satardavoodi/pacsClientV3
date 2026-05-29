# AI-PACS Testing Architecture

> The project has reached a stage where most modules exist. The next
> phase is **optimization, stability, harmony between modules, and
> reliability under different workloads** — repeatable, measurable,
> regression-proof. This document defines the testing architecture
> that gets us there.

---

## 0. Goals and non-goals

**Goals**

1. **Vertical correlation.** Every important workflow is validated from
   two perspectives: a *backend / code* test that exercises the data
   path with isolated inputs, and a *GUI* test that exercises the same
   workflow through the user-visible surface. The two emit the **same
   KPI metrics** so you can spot a backend regression that the UI
   somehow hides — or a UI regression that the backend doesn't see.

2. **Module-by-module test plan.** Each major module
   (download_manager, viewer, MPR, Eagle Eye, printing, education,
   etc.) has its own test catalog with explicit assertions, KPI
   budgets, and acceptance gates. Adding a feature without adding the
   test is a review-blocking smell.

3. **KPI extraction baked into the framework.** Tests don't just
   pass/fail; every run emits structured KPI records (download start
   latency, viewer render time, queue build time, RAM, CPU, etc.). The
   numbers are aggregated and trended so a *slow* regression — the
   kind that doesn't fail any single test but degrades the product
   week by week — surfaces in a chart.

4. **One automation layer.** GUI tests, AI-agent control of the app,
   and user voice/text commands all flow through the same
   `CommandBus` (the foundation that landed 2026-05-27). No parallel
   automation stacks. Adding a new module means writing one adapter,
   not three.

5. **Stability validation.** Multi-cycle open/close, long-running
   sessions, restart with state preserved, no zombie processes after
   shutdown, no leak under workload. The framework owns these.

6. **Regression prevention as a system.** Past bugs become permanent
   guards. "Thumbnails of patient A showing on patient B" gets a test
   that fails the moment it can happen again, in any module.

**Non-goals**

- Replacing the existing 167 unit tests. They form the foundation.
- Coverage % as a primary metric. We optimize for *KPI stability over
  time* plus *every shipped bug has a test*, not for arbitrary
  coverage percentages.
- A test framework rewrite. We build on `pytest`, `pywinauto`, and the
  CommandBus we already have.

---

## 1. Bugs the architecture must catch

The framework is designed around the recurring failure modes the user
has called out. Each one becomes a category of test that has to exist:

| Past failure mode | Test discipline |
|---|---|
| Thumbnails of patient A on patient B | Cross-patient isolation tests; UID-tagged thumbnail correctness; teardown assertions |
| Download starts very slowly | Download-start latency KPI < 400 ms; ZETA §14 guard test |
| Patients need multiple clicks before opening | Idempotency + first-click-success rate KPI; debounce guard |
| UI inconsistencies | UI snapshot tests; layout invariant assertions; widget state machine tests |
| Background process issues | Background-thread accounting; subprocess lifecycle tests |
| Crashes | `native_fault.log` diff per test; crash-on-shutdown guard |
| App doesn't close (zombie in Task Manager) | Post-close `psutil` PID check; clean-exit timing budget |
| Memory leaks | Per-cycle RSS delta budget; multi-cycle accumulation test |
| CPU spikes | Idle-CPU budget; per-operation CPU envelope |
| Delayed pipelines | End-to-end pipeline timing KPIs; per-stage timing budgets |
| Regression loops | Regression-guard catalog + named KPIs in `KPIS_BASELINE.json` |

Every category above maps to a specific test directory in §3.

---

## 2. Architecture overview — the pyramid + the matrix

### 2.1. The vertical pyramid (already in place; this section codifies it)

```
                ┌─────────────────────────────────────┐
                │   Live walkthroughs (computer-use)  │   ad-hoc agentic, slow
                │   tests/gui/live_walkthroughs/      │
                └─────────────────────────────────────┘
                                  ▲
                ┌─────────────────────────────────────┐
                │   pywinauto end-to-end GUI smoke    │   ~5-15 critical workflows
                │   tests/gui/pywinauto/              │   external automation
                │                                     │   catches OLE/COM/paint/a11y
                └─────────────────────────────────────┘
                                  ▲
                ┌─────────────────────────────────────┐
                │   CommandBus scenario tests         │   ~30-80 scenarios
                │   tests/gui/echomind_driven/        │   in-process, fast, typed
                │                                     │   adapters register here
                └─────────────────────────────────────┘
                                  ▲
                ┌─────────────────────────────────────┐
                │   Pure code / headless-Qt unit      │   ~167+ tests
                │   tests/code/                       │   CI-safe, < 30 s each
                └─────────────────────────────────────┘
```

### 2.2. The horizontal correlation matrix (new)

For each major workflow, the SAME journey is validated from two
perspectives. Tests on each row emit the same KPI keys so a
divergence becomes a finding by itself.

| Workflow | Code test  (`tests/code/<domain>/`) | GUI test (`tests/gui/echomind_driven/`) | Pyramid-top (`tests/gui/pywinauto/`) |
|---|---|---|---|
| Patient open | `viewer/test_pipeline_a_qt_repro.py` | `test_scenario_1_patient_open.py` | `test_patient_open_smoke.py` |
| Bulk Download enqueue | `download_manager/test_dm_widget_init_contract.py` | `test_scenario_3_bulk_download.py` | — (slow E2E) |
| Eagle Eye drag-drop | `viewer/test_multi_series_drag_drop.py` | — (in-process can't hit COM bug) | `test_eagle_eye_dragdrop.py` |
| Multi-study sidebar | `viewer/test_qt_stack_drag_bridge.py` | `test_multistudy_sidebar.py` (new) | — |
| MPR build | `viewer/test_stage1_migration_validation.py` | `test_mpr_open_and_apply_preset.py` (new) | — |
| Thumbnail correctness | `download_manager/test_priority_handoff_v2.py` | `test_thumbnails_match_patient.py` (new) | `test_thumbnail_visual_diff.py` (new) |
| Search → results | `network/test_grpc_thumbnail_guard.py` | `test_secretary_list_mri_yesterday.py` (new) | — |
| Print job | `printing/test_*` | `test_print_module_open.py` (new) | — |
| AI Eagle Eye apply | `ai_imaging` headless | `test_eagle_apply_csv.py` (new) | combine w/ drag-drop test |
| Education case open | `education/*` (new) | `test_education_case_of_day.py` (new) | — |
| App restart | `runtime/test_*` | `test_restart_preserves_state.py` (new) | `test_close_no_zombie.py` (new) |
| Long session | `system/test_system_stress.py` | `test_long_session_workload.py` (new) | — |

KPI keys are shared. Example: the workflow `patient_open` emits
`patient_open.elapsed_ms` from BOTH the code-level test (measured via
direct `bus.execute(plan)`) AND the GUI test (measured via screenshot
timestamps or `right_panel_socket_done` log delta). If the code test
reports 150 ms and the GUI reports 6 s, something is being added to
the UI path that the backend can't see — that's a finding by itself.

### 2.3. One automation entry point

Every test driver enters the running app through `CommandBus` from
`modules/EchoMind/secretary/`. The bus already accepts:

- typed `CommandPlan` (tests, agent SDKs)
- raw text (chat orb, voice STT, ad-hoc CLI)
- async dispatch via qasync (Qt-thread-safe)

No test driver writes pywinauto pixel coordinates or screenshots
unless its WHOLE PURPOSE is to validate things the bus can't see
(drag-drop COM contexts, paint regressions, accessibility names,
modal-dialog handling). Those tests live in
`tests/gui/pywinauto/` and are explicitly the pyramid top — see the
pyramid in §2.1.

---

## 3. Test categories by module

This is the test plan the user asked for — every module gets its own
directory and a fixed shape: unit tests + bus-driven scenario tests +
KPI budgets + a regression-guard file.

```
tests/code/                                ← 167 existing files, CI-safe
├── architecture/        layering, signal hygiene, no-VTK-in-FAST
├── build/               PyInstaller / Nuitka manifest checks
├── builder/             plugin packaging
├── cd_burner/
├── connection_between_modules/  cross-module contracts
├── database/            SQLite isolation; pollution cleanup verification
├── diagnostics/         log emission, queue handler, KPI emission
├── download_manager/    DM internals — see "Per-module pattern" below
├── echomind/            CommandBus + envelope + registry (landed 2026-05-27)
├── education/           course / case-of-day / slide editor
├── fast/                FAST viewer non-UI bits
├── fast_viewer/         FAST viewer with offscreen Qt
├── load/                load profile probes
├── manual_archive/      legacy snapshots
├── module_system/       module registry + loader
├── network/             socket + retired gRPC stubs
├── offline_cloud_server/
├── performance/         microbench harness
├── printing/            print job builders
├── runtime/             aipacs_runtime helpers
├── smoke/               full-app start smoke
├── startup/             startup ordering, lazy-load gates
├── storage/             cleanup panel + storage policy
├── system/              cross-cutting regression guards (THIS IS THE GUARD CATALOG)
├── ui_services/         UI-thread dispatch lifecycle
├── utils/               logging lint, config helpers
├── viewer/              main viewer + VTK + drag-drop (headless)
└── web_browser/

tests/gui/echomind_driven/                ← bus-driven scenarios (in-process)
├── test_scenario_1_patient_open.py        2026-05-27 — landed
├── test_scenario_3_bulk_download.py       2026-05-27 — landed
├── test_command_bus_smoke.py              2026-05-27 — landed
├── test_multistudy_sidebar.py             planned
├── test_mpr_open_and_apply_preset.py      planned
├── test_stack_scroll_keyboard.py          planned
├── test_thumbnails_match_patient.py       planned   ← critical regression guard
├── test_education_case_of_day.py          planned
├── test_print_module_open.py              planned
├── test_eagle_apply_csv.py                planned
├── test_restart_preserves_state.py        planned
├── test_long_session_workload.py          planned   ← stability runner
└── test_idle_resource_budget.py           planned   ← CPU/RAM/no-leak guard

tests/gui/pywinauto/                      ← OS-level smoke (real Win32)
├── test_eagle_eye_dragdrop.py             2026-05-27 — landed (canonical case)
├── run_patient_open_smoke.py              2026-05-27 — landed
├── test_close_no_zombie.py                planned   ← Task-Manager zombie check
├── test_modal_dialog_handling.py          planned
├── test_drag_series_across_layouts.py     planned
└── test_thumbnail_visual_diff.py          planned   ← pixel-diff vs golden

tests/gui/live_walkthroughs/              ← agentic ad-hoc
├── _verify_source_build.py                2026-05-27 — landed (pre-flight gate)
├── extract_2026_05_27_kpis.py             2026-05-27 — landed (log parser)
└── README.md                              2026-05-27 — landed

tests/_kpi/                               ← KPI machinery (NEW, this doc)
├── __init__.py
├── schema.py             single-source KPI key registry
├── collector.py          context manager + bus hook
├── baseline.json         per-KPI thresholds + last-known-good
├── reporter.py           pretty-print + trend chart export
└── README.md
```

### 3.1. Per-module pattern (template)

Every domain dir `tests/code/<module>/` follows the same shape:

```
tests/code/<module>/
├── conftest.py                   common fixtures (mocks, fake data)
├── test_<module>_contract.py     interface contracts (signatures, types)
├── test_<module>_state_machine.py state transitions
├── test_<module>_concurrency.py  race conditions, locks, async safety
├── test_<module>_persistence.py  DB writes, file writes, recovery
├── test_<module>_kpi_budgets.py  KPI assertions (uses tests/_kpi/)
└── test_<module>_regression_*.py named regressions (one file per past bug)
```

A regression-guard test is filed under the module that owns the bug AND
indexed in `tests/code/system/` for cross-cutting bugs that touch
multiple modules.

---

## 4. KPI taxonomy

KPIs are the spine of the framework. Every test emits structured KPI
records to a single sink. The collector enforces a registered key — typos
fail loudly so the dashboard never has two metrics for the same thing.

### 4.1. KPI key registry (single source of truth)

Lives in `tests/_kpi/schema.py`. Every KPI has: key, unit, lower-is-better
bool, hard threshold (PR-blocking), warning threshold, and the workflow
that emits it.

| Workflow | KPI key | Unit | Lower better | Hard threshold | Warning | Source |
|---|---|---|---|---|---|---|
| Patient open | `patient_open.elapsed_ms` | ms | yes | 400 | 250 | code + gui |
| Patient open | `patient_open.right_panel_socket_ms` | ms | yes | 400 | 250 | log/gui |
| Bulk download | `bulk_download.queue_build_ms` | ms | yes | 3000 | 1500 | code + gui |
| Bulk download | `bulk_download.first_chunk_ms` | ms | yes | 5000 | 2500 | log |
| Thumbnail | `thumbnail.load_ms` | ms | yes | 200 | 100 | log/gui |
| Thumbnail | `thumbnail.cross_patient_leak` | count | yes | 0 | 0 | gui visual diff |
| Viewer | `viewer.first_render_ms` | ms | yes | 800 | 500 | gui/log |
| Viewer | `viewer.scroll_fps` | fps | no | 30 | 45 | gui |
| Viewer | `viewer.stack_rebuild_ms` | ms | yes | 500 | 300 | code+gui |
| MPR | `mpr.build_ms` | ms | yes | 4000 | 2000 | log |
| Search | `search.server_round_trip_ms` | ms | yes | 1500 | 800 | log |
| Search | `search.first_row_render_ms` | ms | yes | 200 | 100 | gui |
| DB | `db.query_ms.<query_name>` | ms | yes | (per query) | (per query) | log |
| Socket | `socket.send_request_ms.<endpoint>` | ms | yes | (per endpoint) | (per endpoint) | log |
| Process | `proc.idle_cpu_pct` | % | yes | 5.0 | 2.0 | system probe |
| Process | `proc.rss_mb_steady` | MB | yes | 1500 | 1000 | system probe |
| Process | `proc.rss_mb_growth_per_hour` | MB/h | yes | 50 | 20 | system probe |
| Process | `proc.zombie_after_close` | count | yes | 0 | 0 | system probe |
| GPU | `gpu.util_pct_peak` | % | no | — | — | system probe (when GPU avail) |
| UI | `ui.freeze_ms_per_session` | ms | yes | 1000 | 200 | event-loop monitor |
| Crash | `crash.native_fault_count` | count | yes | 0 | 0 | native_fault.log diff |
| Recovery | `recovery.restart_to_ready_ms` | ms | yes | 15000 | 8000 | startup probe |
| Long session | `session.no_leak_after_8h` | bool | yes | true | true | long-session runner |

### 4.2. Collection API

Tests don't manually build KPI dicts. The collector is a `pytest`
fixture and a `with` block:

```python
from tests._kpi import kpi

def test_open_patient_kpi(bus, kpi):
    with kpi.measure("patient_open"):
        result = bus.execute(CommandPlan(
            action="open_patient", entities={"patient_id": "43743"}
        ))
    assert result.ok
    kpi.record("patient_open.elapsed_ms", result.elapsed_ms)
    # the fixture auto-asserts against thresholds + writes to sink
```

CommandBus already fills `elapsed_ms` on every result — the collector
listens for `CommandResult` records on a bus signal and records them
automatically. Tests can override the auto-recorded value or add their
own.

### 4.3. KPI sink

Every test run appends JSONL records to
`user_data/test_kpis/<run_id>.jsonl`. Each record:

```json
{
  "ts": "2026-05-28T10:27:13.451Z",
  "run_id": "2026-05-28-10-25-bulk",
  "test_id": "tests/gui/echomind_driven/test_scenario_3_bulk_download.py::test_20_patients_under_3s",
  "key": "bulk_download.queue_build_ms",
  "value": 1842.0,
  "threshold_hard": 3000,
  "threshold_warning": 1500,
  "verdict": "PASS",
  "host": "alizadeh-imaging-2",
  "git_sha": "f03607d",
  "build_kind": "source"
}
```

The reporter aggregates this into:
- A per-run summary table (PASS/WARN/FAIL counts per workflow).
- A trend chart per KPI key (last 50 runs).
- A baseline updater (`tools/kpi_update_baseline.py`) that promotes
  newer-better KPI values into `tests/_kpi/baseline.json` after manual
  review — never automatically.

### 4.4. What "PASS" means

A test PASSes when:

1. Its assertions hold (the existing pytest model).
2. **Every KPI it emitted is below the hard threshold.**
3. Optional: every KPI is below the warning threshold (otherwise
   verdict is `WARN`, not `FAIL`).

Hard thresholds are PR-blocking. Warning thresholds surface in the
report but don't fail CI — they exist to catch slow drift before it
crosses into a hard fail.

---

## 5. The code ↔ GUI correlation pattern (worked example)

This is the central pattern. Take ONE workflow — patient open — and
show how both perspectives validate it with shared KPI keys.

### 5.1. Backend / code test

`tests/code/echomind/test_patient_open_workflow.py`:

```python
from modules.EchoMind.secretary import CommandBus, CommandPlan, AdapterRegistry
from tests._kpi import kpi

def test_patient_open_backend_kpi(kpi):
    # Build bus with a FAKE adapter that simulates the socket fetch.
    # The fake replays the real GetStudyInfo probe + GetStudyThumbnails
    # timing distribution captured from production logs.
    bus = build_bus_with_fake_pacs_server(probe_ms=8, thumbnails_ms=180)

    with kpi.measure("patient_open"):
        result = bus.execute(CommandPlan(
            action="open_patient",
            entities={"patient_id": "43743", "modality": "MR"}
        ))

    assert result.ok
    assert result.data["series_count"] > 0
    kpi.record("patient_open.elapsed_ms", result.elapsed_ms)
    # threshold check is automatic; this test fails if elapsed > 400 ms.
```

### 5.2. GUI / bus-driven test

`tests/gui/echomind_driven/test_scenario_1_patient_open.py` (already
landed 2026-05-27, extended to emit KPIs):

```python
def test_five_patient_opens_each_under_400ms(bus, fake_home, kpi):
    for pid in ("43649", "43698", "43676", "43586", "43743"):
        with kpi.measure("patient_open", labels={"patient_id": pid}):
            result = bus.execute(CommandPlan(
                action="open_patient", entities={"patient_id": pid}
            ))
        assert result.ok
        kpi.record("patient_open.elapsed_ms", result.elapsed_ms)
```

### 5.3. OS-level / pywinauto test

`tests/gui/pywinauto/test_patient_open_smoke.py`:

```python
def test_patient_open_wallclock_to_right_panel(kpi):
    require_source_build()                 # pre-flight
    _, window = connect_aipacs()
    rows = window.children(class_name_re=r".*PatientRow.*")[:5]
    for row in rows:
        t0 = time.monotonic()
        row.click_input()
        wait_for_widget(window, "RightPanelSeries", timeout=2.0)
        elapsed = (time.monotonic() - t0) * 1000
        kpi.record("patient_open.elapsed_ms", elapsed,
                   labels={"source": "pywinauto"})
```

### 5.4. Divergence becomes a finding

The same KPI key (`patient_open.elapsed_ms`) is reported from three
sources. The reporter cross-checks them:

| Source | Median (ms) | Verdict |
|---|---|---|
| code   | 152 | PASS |
| bus    | 187 | PASS |
| pywinauto | 6712 | **FAIL** |

A divergence like this is itself a finding — "the workflow is fast at
the bus level but slow at the OS level" points at paint / layout /
modal-dialog / OLE issues that wouldn't show up in code tests alone.
That's exactly the kind of failure mode the original
`patient-needs-multiple-clicks` and `UI-inconsistencies` bug categories
came from.

---

## 6. Automation approach

### 6.1. Bus-first

The `CommandBus` foundation that landed 2026-05-27 is the default
entry point. Every adapter we add to `AdapterRegistry` doubles as:

- The agent's tool surface (Pydantic schema → tool description).
- The chat orb's executor.
- The GUI test's `bus.execute(plan)` call site.

Adding an adapter is the way you add to ALL THREE at once.

### 6.2. pywinauto for the pyramid top

Reserved for what the bus can't see — drag-drop COM contexts, modal
dialogs, paint, accessibility names, zombie-process check after close.
Each pywinauto test must call `require_source_build()` first (the
pre-flight gate that already exists). Tests skip cleanly when the
source build isn't detected so they never fail CI.

### 6.3. computer-use MCP for one-off

Stays as the agentic ad-hoc tool — discovery, demos, new-scenario
exploration. Not part of CI.

### 6.4. Adapter coverage roadmap

The bus has one adapter today (`HomeCommandAdapter`). The roadmap:

| Phase | Adapter | Workflows it unlocks | Effort |
|---|---|---|---|
| 1 (done 2026-05-27) | `HomeCommandAdapter` | `list_patients`, `open_patient`, `download_patient` | shipped |
| 2 | `ViewerAdapter` | `scroll_series`, `stack_images`, `set_window_level`, `ruler`, `set_layout`, `toggle_sync` | medium — read MULTI_STUDY guard first |
| 3 | `DownloadAdapter` | `check_download_status`, `pause_download`, `cancel_download`, `set_priority` | low — DM is well-isolated |
| 4 | `ModuleAdapter` | `open_mpr`, `open_eagle`, `open_print`, `run_analysis`, `open_education_case` | medium — one method per module launcher |
| 5 | `SystemAdapter` | `restart_app`, `simulate_crash`, `gc_now`, `snapshot_memory` | tiny — wraps existing probes |

Each adapter ships with its own
`tests/code/echomind/test_<adapter>_unit.py` (mocked target) and one
or more `tests/gui/echomind_driven/test_<workflow>.py` scenario tests.

---

## 7. Stability testing

Three reinforcing layers.

### 7.1. Cycle tests

`tests/gui/pywinauto/test_open_close_cycles.py`:

- Launch the source build (pywinauto launches `python main.py`).
- Wait for Server Ready.
- Run a small scenario (one patient open).
- Close cleanly (Alt+F4 / window close).
- `psutil` PID check — process gone within 10 s.
- Repeat N=20 times.
- KPIs emitted: `recovery.restart_to_ready_ms` per cycle, peak RSS
  during the run, `proc.zombie_after_close` count (must be 0).

### 7.2. Long-session workload

`tests/gui/echomind_driven/test_long_session_workload.py`:

- Single launch.
- Loop for 4–8 hours: random workflow from a weighted catalog
  (`list_patients`, `open_patient`, `download_patient`, `scroll`,
  `change_layout`, `open_eagle`, `apply_preset`, `close_tab`).
- Sample RSS / CPU / open-fd count every 60 s.
- Assertions:
  - `proc.rss_mb_growth_per_hour < 20` (warning) / `< 50` (hard).
  - No `native_fault.log` entry growth.
  - `ui.freeze_ms_per_session < 1000` (sum of freezes > 200 ms).
- KPIs: same three keys, plus `session.no_leak_after_8h` boolean.

### 7.3. Resource probes

`tests/gui/echomind_driven/test_idle_resource_budget.py`:

- Launch, sit idle for 5 min.
- `proc.idle_cpu_pct < 5.0` median.
- No new log entries beyond heartbeats.
- File descriptors stable.

These three together cover everything the user listed:
multi-cycle, leak, CPU spike, zombie, delayed pipeline, long-session.

---

## 8. Regression prevention

This is the discipline that prevents bug-fix loops.

### 8.1. Every shipped bug becomes a guard test

Pattern:

1. Bug filed → root cause identified.
2. Fix prepared (the code change).
3. **In the same PR**: a regression-guard test under
   `tests/code/system/test_<YYYY-MM-DD>_<short_slug>.py`. The test
   FAILS on the pre-fix codebase, PASSES on the fixed one.
4. The regression guard is named in the commit message and indexed in
   `docs/plans/architecture/REGRESSION_CATALOG.md` (new — see §10).

The 2026-05-27 fixes already follow this:
`tests/code/system/test_2026_05_27_regression_guards.py` has 15 named
assertions, all PASS. Every future session adds rows here, never
removes them.

### 8.2. KPI baselines as long-running guards

A KPI never gets *worse* between releases. If `patient_open.elapsed_ms`
median was 180 ms last release and the current PR pushes it to 220 ms,
the PR is blocked. The baseline file `tests/_kpi/baseline.json` is the
source of truth; updates happen only via
`tools/kpi_update_baseline.py` with a human-readable changelog entry.

### 8.3. Cross-module isolation guards

Specific to the failure modes the user named:

- **Thumbnail cross-patient leak.** A guard in
  `tests/gui/echomind_driven/test_thumbnails_match_patient.py` opens
  patient A, captures the thumbnail UIDs in the right panel, opens
  patient B, then asserts NONE of patient A's thumbnail UIDs appear.
  Add a pywinauto pixel-diff variant for the worst case.

- **Multi-study sidebar drift.** A guard re-validates the multi-study
  invariants listed in CLAUDE.md (offset-keyed series, single-tab
  rendering, no flicker). Runs as both a code test
  (assertions on `lst_thumbnails_data` shape) and a GUI test
  (right-panel UID assertions).

- **Database pollution.** The cleanup test from
  `tests/code/database/test_database.py` already exists; add a
  parallel CommandBus-driven check that the DB row count after a
  bus-driven workflow returns to baseline.

### 8.4. Test-was-the-bug guard

The 2026-05-27 cleanup found that `tests/database/test_database.py`
had been silently polluting the live `dicom.db` for 43 runs because the
test's isolation was broken. The framework prevents that with a
**loud-fail invariant in `tests/code/database/conftest.py`** that
opens a connection, calls `PRAGMA database_list`, and asserts the
path is NOT `dicom.db`. Already in place; this section codifies it.

---

## 9. KPI collector — concrete implementation

(See §11 for the actual files shipped this session.)

### 9.1. Files

```
tests/_kpi/
├── __init__.py          re-exports kpi, KpiCollector, KpiVerdict
├── schema.py            registered KPI keys + thresholds
├── collector.py         KpiCollector + pytest fixture
├── baseline.json        last-known-good values per key
├── reporter.py          CLI: pretty table + trend chart
└── README.md
```

### 9.2. Sink

JSONL append to `user_data/test_kpis/<run_id>.jsonl`. `<run_id>` is
`YYYY-MM-DD-HH-MM-<slug>` (slug = the pytest collection root). The
sink is rotated by `tools/maintenance/kpi_rotate.py` (existing pattern
mirrors `tests/code/diagnostics/log_rotate`).

### 9.3. CommandBus hook

`CommandBus.execute()` already fills `elapsed_ms`. The collector
patches `CommandBus.execute` (only inside tests, via the fixture) so
every result is auto-recorded with key
`<action_name>.elapsed_ms`. Manual `kpi.record(key, value)` overrides
the auto-record for tests that compute their own KPI.

### 9.4. Reporter

```bash
python tests/_kpi/reporter.py last                    # last run table
python tests/_kpi/reporter.py trend patient_open.elapsed_ms  # ASCII chart
python tests/_kpi/reporter.py diff <run_a> <run_b>    # delta report
```

The reporter is plain stdlib — no extra deps.

---

## 10. Evolution roadmap

How this framework grows as the project does.

### 10.1. Now (this session — what landed)

- The architecture doc (this file).
- `tests/_kpi/` with the collector, schema, baseline-seed, reporter.
- `tests/code/system/test_kpi_schema.py` — a regression guard that
  every registered KPI key has a baseline entry.
- `tests/code/echomind/test_kpi_auto_record.py` — proves the bus hook
  emits records correctly.
- `docs/plans/architecture/REGRESSION_CATALOG.md` — index of every
  named regression guard (linked from CLAUDE.md).

### 10.2. Phase A (1-2 weeks)

- Adapter coverage: `ViewerAdapter`, `DownloadAdapter`,
  `ModuleAdapter`, `SystemAdapter` (see §6.4).
- New bus-driven scenario tests for each adapter: ~12 files,
  template under `tests/gui/echomind_driven/test_<workflow>.py`.
- Pywinauto suite extended to 8–10 critical workflows.

### 10.3. Phase B (1-2 months)

- Stability runner: open/close cycle test runs nightly.
- Long-session test runs weekly on a dedicated host.
- KPI trend page (`tools/kpi_html_report.py`) auto-generated from the
  JSONL sink.

### 10.4. Phase C (2-6 months)

- PydanticAI parser (Phase 2 of the Unified Command Layer plan).
- Cross-build comparison: same KPI key recorded from source build,
  frozen build, and CI offscreen build — divergence catches
  build-specific regressions.
- Visual diff (pixel-level) for the worst thumbnail-leak class of
  bugs.

### 10.5. Phase D (6+ months)

- Property-based tests on adapter contracts (`hypothesis`).
- Fuzz the CommandBus with malformed plans — should never crash,
  always return a typed error envelope.
- Multi-machine load test: spin N pywinauto agents against one
  shared PACS server; KPIs must hold.

---

## 11. What ships in this session

(See `IMPLEMENTATION_NOTES_2026-05-28.md` in this folder for the
exact files.)

- `tests/_kpi/` — collector + schema + baseline + reporter (~500 LOC).
- `tests/code/system/test_kpi_schema.py` — schema-integrity guard.
- `tests/code/echomind/test_kpi_auto_record.py` — bus-hook test.
- `docs/plans/architecture/REGRESSION_CATALOG.md` — guard index.
- Updates to `tests/README.md` and `tests/gui/README.md` referencing
  the new framework.

Each new test file follows the patterns in §3.1 and §5 of this doc.

---

## 12. Decisions in one paragraph

Vertical pyramid (code → bus → pywinauto → live walkthrough) plus a
horizontal correlation matrix that pairs code-level and GUI-level
tests for the SAME workflow with SHARED KPI keys. One automation
entry point — the CommandBus from `modules/EchoMind/secretary`. KPIs
emitted from every test into a single JSONL sink, threshold-checked
against `tests/_kpi/baseline.json`, never silently degraded. Every
shipped bug becomes a regression-guard test under
`tests/code/system/`. Stability validated via open/close cycles,
long-session runner, idle-resource probes — all expressed as
CommandBus scenarios so adding a new module adds the corresponding
stability test for free. The framework grows in phases A→D, each
adding adapters / scenarios / trend tooling without re-architecting.

---

*Author: 2026-05-28 session, builds on UNIFIED_COMMAND_LAYER_2026-05-27.md
and IMPLEMENTATION_PLAN_2026-05-27.md.*
