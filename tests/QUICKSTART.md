# AI-PACS testing framework — 5-minute quickstart

> If you only read one testing doc, read this one. Everything else is
> a deeper drill-down. The full architecture is in
> `docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`.

---

## The 30-second tour

```
tests/
├── code/        ← 167 headless tests (pytest, CI-safe)
├── gui/
│   ├── echomind_driven/    ← scenario tests via the CommandBus (fast, no GUI)
│   ├── pywinauto/          ← OS-level smoke (real Win32; opt-in)
│   └── live_walkthroughs/  ← agentic + log-based KPI extractor
└── _kpi/                   ← KPI schema + collector + reporter
```

Each test on the right column is paired with a code test on the left
column for the same workflow. They share KPI keys, so a divergence
between layers is itself a finding.

---

## What changed if you haven't been following along

We built a **unified Command Layer** so every "do something in the
app" path — chat orb, voice STT, AI agent, GUI tests — goes through one
typed bus call. The bus exposes ~19 actions across four adapters
(home, system, download, modules). Tests dispatch the same actions a
user would; KPIs (`elapsed_ms`, RSS, crash count, etc.) are recorded
automatically.

See `docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md`
(architecture), `IMPLEMENTATION_PLAN_2026-05-27.md` (code-level spec),
and `TESTING_ARCHITECTURE_2026-05-28.md` (testing strategy).

---

## Running tests — by category

| Command | Runtime | What it covers |
|---|---|---|
| `pytest tests/code/` | < 2 min | All 167 headless tests + the new echomind/system guards |
| `pytest tests/code/system/test_2026_05_27_regression_guards.py -v` | < 5 s | 15 regression guards for the 2026-05-27 fixes |
| `pytest tests/code/system/test_kpi_schema.py -v` | < 1 s | KPI registry integrity |
| `pytest tests/code/echomind/ -v` | < 10 s | 8 unit tests for CommandBus + adapters + factory |
| `pytest tests/gui/echomind_driven/ -v` | < 30 s | 7 bus-driven scenarios (fake adapters; runs in CI) |
| `pytest tests/gui/pywinauto/test_eagle_eye_dragdrop.py -v` | depends on app | Eagle Eye 0x8001010d drag-drop guard |
| `pytest tests/gui/pywinauto/test_close_no_zombie.py -v` | < 30 s + app | Zombie-process guard after close |
| `AIPACS_CYCLE_LAUNCH_CMD="python main.py" AIPACS_CYCLE_COUNT=3 pytest tests/gui/pywinauto/test_open_close_cycles.py -s` | ~3 × startup | N×launch+close stability runner |

All GUI tests **auto-skip** when their preconditions aren't met
(source build not running, pywinauto missing, etc.) — they never fail
CI for environmental reasons.

---

## Adding a test in 5 minutes

Pick the right slot:

### "I'm validating data-path logic" → `tests/code/<module>/`

```python
# tests/code/echomind/test_my_thing.py
from modules.EchoMind.secretary import CommandBus, CommandPlan
# ... write a plain pytest function.
```

### "I'm validating a user-facing workflow" → `tests/gui/echomind_driven/`

```python
# tests/gui/echomind_driven/test_my_workflow.py
from tests._kpi import KpiCollector

def test_open_3_patients_fast(tmp_path):
    bus = build_test_bus()                       # use the fixture if you can
    kpi = KpiCollector(sink_dir=tmp_path)
    kpi.hook_bus(bus)                            # auto-records elapsed_ms

    for pid in ("43649", "43698", "43676"):
        result = bus.execute(
            CommandPlan(action="open_patient", entities={"patient_id": pid})
        )
        assert result.ok, result.message

    assert kpi.summary()["FAIL"] == 0
```

The `kpi.hook_bus(bus)` line auto-records `<action>.elapsed_ms` for
every `bus.execute()` against the keys registered in
`tests/_kpi/schema.py`. No KPI registered for an action → silently
skipped. Want to record a custom value? `kpi.record(key, value)`.

### "I need a real Win32 paint / drag-drop / a11y check" → `tests/gui/pywinauto/`

Copy `test_eagle_eye_dragdrop.py` as a template. Two rules:

1. Call `require_source_build()` first — the test auto-skips if the
   running app isn't the source build.
2. Sample `native_fault.log` size before AND after the action;
   assert delta == 0.

---

## Adding a new KPI

1. Edit `tests/_kpi/schema.py` and add a `KpiSpec(...)` to `_SPECS`.
2. Run `python tests/_kpi/reporter.py last` — it'll regenerate the
   baseline automatically on next run.
3. The schema-integrity guard (`tests/code/system/test_kpi_schema.py`)
   confirms the new key has hard/warn thresholds and a workflow.
4. Emit it from your test: `kpi.record("my.key", 42.0)`.

---

## Reading KPIs

```bash
# Text-mode report of the most recent run
python tests/_kpi/reporter.py last

# Workflow PASS/WARN/FAIL summary
python tests/_kpi/reporter.py summary

# ASCII trend chart over the last 20 runs
python tests/_kpi/reporter.py trend patient_open.elapsed_ms

# Delta between two specific runs
python tests/_kpi/reporter.py diff 2026-05-27-...  2026-05-28-...

# Self-contained HTML report (opens offline; no JS deps)
python tools/kpi_html_report.py -o kpi_report.html
```

---

## Hard rules

1. **Every bug fix lands with a regression-guard test.** Same PR. The
   guard must FAIL on the pre-fix codebase. Then it goes into
   `docs/plans/architecture/REGRESSION_CATALOG.md`.

2. **Never wire a parallel automation stack.** If you find yourself
   reaching for pywinauto where the CommandBus could do it, add an
   adapter method instead. pywinauto is reserved for what the bus
   structurally can't see (drag-drop COM, paint, modal dialogs,
   accessibility names).

3. **GUI tests must call `require_source_build()` first** (pywinauto)
   or skip cleanly when `pydantic` isn't installed (bus-driven). They
   never fail CI for environmental reasons.

4. **A KPI never regresses silently.** If a metric crosses its hard
   threshold, the PR is blocked. Warn-threshold drifts surface in the
   reporter but don't block — they exist to catch problems before
   they bite.

5. **Adapter methods take `(plan, state)` and return `CommandResult`
   or dict or None.** No more, no less. The registry normalizes the
   return shape automatically.

---

## Where to go next

- **Design**: `docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`
- **Why we built it**: `docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md`
- **Implementation spec**: `docs/plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md`
- **Catalog of guarded bugs**: `docs/plans/architecture/REGRESSION_CATALOG.md`
- **KPI machinery**: `tests/_kpi/README.md`
- **Per-driver runbook**: `tests/gui/README.md`
