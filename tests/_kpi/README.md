# tests/_kpi/ — KPI collection machinery

Single source of truth for every metric the test suite emits. Tests
record values; the collector checks them against the registered
thresholds; the reporter aggregates across runs.

See `docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md` for
the full design.

## Files

| File | Purpose |
|---|---|
| `schema.py` | KPI key registry — every key + thresholds in one place |
| `collector.py` | `KpiCollector` + pytest `kpi` fixture + CommandBus auto-record hook |
| `baseline.json` | Last-known-good values per key; updated only manually |
| `reporter.py` | CLI: `last` / `trend` / `diff` / `summary` |

## Usage from a test

```python
from tests._kpi import kpi  # pytest fixture

def test_open_patient(bus, kpi):
    with kpi.measure("patient_open"):
        result = bus.execute(plan)
    assert result.ok
    kpi.record("patient_open.elapsed_ms", result.elapsed_ms)
    # Threshold check is automatic — the test FAILs if value > hard
    # threshold, WARNs if value > warn threshold.
```

## Auto-record from the bus

```python
from tests._kpi import KpiCollector

collector = KpiCollector()
collector.hook_bus(bus)        # every bus.execute() emits a KPI
```

The hook records `<action>.elapsed_ms` for any action whose key is
registered. Unknown actions are silently skipped (the bus's own
UNKNOWN_ACTION envelope is enough).

## Inspecting results

```bash
python tests/_kpi/reporter.py last        # most recent run
python tests/_kpi/reporter.py summary     # workflow PASS/WARN/FAIL
python tests/_kpi/reporter.py trend patient_open.elapsed_ms -n 20
python tests/_kpi/reporter.py diff <run_a_id> <run_b_id>
```

## Adding a new KPI

1. Add a `KpiSpec(key=..., unit=..., workflow=..., hard=..., warn=...)`
   to `_SPECS` in `schema.py`.
2. Emit it from at least one test (`kpi.record(key, value)`).
3. Run the suite once and commit the updated `baseline.json` with the
   first observed value (it stays `null` until then; that's fine — the
   verdict logic uses `hard`/`warn` directly, not the baseline).

## What "FAIL" means

A KPI verdict of `FAIL` raises `KpiHardThresholdError` from
`record()` — the test fails. A `WARN` verdict is logged but not raised;
it surfaces in the reporter and gets your attention before the metric
crosses into a hard fail.

`higher_better=True` inverts the comparison (e.g. `viewer.scroll_fps`
must be at least the threshold, not at most).
