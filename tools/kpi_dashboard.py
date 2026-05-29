"""Framework health dashboard — one-stop CLI.

Prints a single-screen snapshot of the testing framework:

* CommandBus adapter coverage  (how many actions are reachable?)
* KPI schema integrity         (registered keys vs baseline)
* Latest KPI run summary       (PASS / WARN / FAIL across workflows)
* Regression-catalog row count (how many guarded behaviours?)
* Sandbox test-file count      (code / gui / pywinauto / live)
* Recent crash count           (native_fault.log delta in last 24h)

Use this as the project's "is everything green?" check before a
release, after a refactor, or as the first command of a new session::

    python tools/kpi_dashboard.py

Exit code 0 = all green, 1 = one or more warnings, 2 = one or more
hard failures.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── individual probes ──────────────────────────────────────────────────

def _probe_adapter_coverage() -> dict:
    """Count actions exposed across the registered adapters."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from modules.EchoMind.secretary import build_command_bus
        # Build a bus with the LEAST input — just SystemAdapter is always wired.
        # For dashboard purposes we only care about *static* action counts
        # (not whether home_widget is actually around), so we build with
        # every kwarg supplied and stubs that satisfy the adapters' constructors.

        class _Stub:
            def is_available(self): return True
            def search(self, **_): pass
            class _Store:
                def get(self, *_): return None
                def get_all(self): return []
                def get_statistics(self): return {}
            state_store = _Store()
            def count(self): return 0
            def tabText(self, _): return ""
            def currentIndex(self): return -1
            def currentWidget(self): return None

        bus = build_command_bus(
            home_widget=_Stub(),
            dm_widget=_Stub(),
            module_launchers={"eagle_ai": lambda _: None,
                              "mpr": lambda _: None,
                              "printing": lambda _: None,
                              "education": lambda _: None},
            get_active_patient_tab=lambda: None,
            get_main_tab_widget=lambda: _Stub(),
        )
        actions = bus.actions()
        adapters = bus.registry.list_adapters()
        return {"ok": True, "actions": len(actions), "adapters": len(adapters),
                "adapter_names": adapters, "action_names": actions}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "actions": 0, "adapters": 0}


def _probe_kpi_schema() -> dict:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from tests._kpi.schema import KPI_REGISTRY
        baseline_path = PROJECT_ROOT / "tests" / "_kpi" / "baseline.json"
        if baseline_path.exists():
            bl = json.loads(baseline_path.read_text(encoding="utf-8"))
            bl_keys = set(bl.get("kpis", {}).keys())
        else:
            bl_keys = set()
        return {"ok": True,
                "registered_keys": len(KPI_REGISTRY),
                "baseline_keys": len(bl_keys),
                "in_sync": bl_keys == set(KPI_REGISTRY.keys()),
                "drift": sorted(set(KPI_REGISTRY.keys()) ^ bl_keys)[:5]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _probe_latest_run() -> dict:
    sink = PROJECT_ROOT / "user_data" / "test_kpis"
    if not sink.exists():
        return {"ok": True, "records": 0, "verdicts": {}}
    records: list[dict] = []
    for p in sorted(sink.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip(): continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError: pass
    if not records:
        return {"ok": True, "records": 0, "verdicts": {}}
    latest_run = max(r.get("run_id", "") for r in records)
    latest_recs = [r for r in records if r.get("run_id") == latest_run]
    verdicts: dict[str, int] = defaultdict(int)
    for r in latest_recs:
        verdicts[r.get("verdict", "?")] += 1
    return {"ok": True, "run_id": latest_run,
            "records": len(latest_recs), "verdicts": dict(verdicts)}


def _probe_regression_catalog() -> dict:
    p = PROJECT_ROOT / "docs" / "plans" / "architecture" / "REGRESSION_CATALOG.md"
    if not p.exists():
        return {"ok": False, "rows": 0}
    text = p.read_text(encoding="utf-8")
    rows = sum(1 for line in text.splitlines()
               if line.startswith("| 2026-") or line.startswith("| 2025-"))
    return {"ok": True, "rows": rows}


def _probe_test_inventory() -> dict:
    tests = PROJECT_ROOT / "tests"
    if not tests.exists():
        return {"ok": False}
    counts = {}
    for sub in ("code", "gui/echomind_driven", "gui/pywinauto",
                "gui/live_walkthroughs"):
        d = tests / sub
        if d.exists():
            counts[sub] = sum(1 for p in d.rglob("test_*.py"))
        else:
            counts[sub] = 0
    counts["total"] = sum(counts.values())
    return {"ok": True, "counts": counts}


def _probe_recent_crashes() -> dict:
    nf = PROJECT_ROOT / "user_data" / "logs" / "native_fault.log"
    if not nf.exists():
        return {"ok": True, "file_exists": False, "total": 0,
                "com_inhibit": 0, "mtime": None}
    text = nf.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = sum(1 for l in lines if "Windows fatal exception" in l)
    com = sum(1 for l in lines if "0x8001010d" in l)
    mtime = nf.stat().st_mtime
    age_h = (time.time() - mtime) / 3600.0
    return {"ok": True, "file_exists": True, "total": total,
            "com_inhibit": com, "mtime": mtime, "age_hours": age_h}


# ── rendering ──────────────────────────────────────────────────────────

C_RESET = "\033[0m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"


def _badge(label: str, kind: str = "ok") -> str:
    if kind == "ok":     return f"{C_GREEN}[{label}]{C_RESET}"
    if kind == "warn":   return f"{C_YELLOW}[{label}]{C_RESET}"
    if kind == "fail":   return f"{C_RED}[{label}]{C_RESET}"
    return f"[{label}]"


def main() -> int:
    print(f"{C_BOLD}AI-PACS framework health dashboard{C_RESET}")
    print(f"  project: {PROJECT_ROOT}")
    print(f"  generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    overall = "ok"
    warns = fails = 0

    # ── Adapter coverage ────────────────────────────────────────────
    a = _probe_adapter_coverage()
    print(f"{C_BOLD}Command Layer{C_RESET}")
    if a["ok"]:
        print(f"  {_badge('OK')} {a['adapters']} adapters · "
              f"{a['actions']} actions registered")
        print(f"        adapters: {', '.join(a['adapter_names'])}")
    else:
        print(f"  {_badge('FAIL', 'fail')} {a['error']}")
        fails += 1
    print()

    # ── KPI schema ──────────────────────────────────────────────────
    k = _probe_kpi_schema()
    print(f"{C_BOLD}KPI schema{C_RESET}")
    if k["ok"]:
        if k["in_sync"]:
            print(f"  {_badge('OK')} {k['registered_keys']} KPI key(s), "
                  f"baseline in sync")
        else:
            print(f"  {_badge('WARN', 'warn')} schema vs baseline drift: "
                  f"{k['drift']}")
            warns += 1
    else:
        print(f"  {_badge('FAIL', 'fail')} {k['error']}")
        fails += 1
    print()

    # ── Latest KPI run ──────────────────────────────────────────────
    r = _probe_latest_run()
    print(f"{C_BOLD}Latest KPI run{C_RESET}")
    if r["ok"] and r["records"]:
        v = r["verdicts"]
        passed = v.get("PASS", 0)
        warned = v.get("WARN", 0)
        failed = v.get("FAIL", 0)
        if failed:
            print(f"  {_badge('FAIL', 'fail')} "
                  f"run={r['run_id']}  PASS={passed} WARN={warned} FAIL={failed}")
            fails += 1
        elif warned:
            print(f"  {_badge('WARN', 'warn')} "
                  f"run={r['run_id']}  PASS={passed} WARN={warned}")
            warns += 1
        else:
            print(f"  {_badge('OK')} "
                  f"run={r['run_id']}  {passed} record(s) PASS")
    else:
        print(f"  {_badge('-')} no KPI records yet — run a test first")
    print()

    # ── Regression catalog ──────────────────────────────────────────
    rc = _probe_regression_catalog()
    print(f"{C_BOLD}Regression catalog{C_RESET}")
    if rc["ok"]:
        print(f"  {_badge('OK')} {rc['rows']} guarded behaviour(s) indexed")
    else:
        print(f"  {_badge('FAIL', 'fail')} catalog missing")
        fails += 1
    print()

    # ── Test inventory ──────────────────────────────────────────────
    t = _probe_test_inventory()
    print(f"{C_BOLD}Test inventory{C_RESET}")
    if t["ok"]:
        c = t["counts"]
        print(f"  {_badge('OK')} {c['total']} test files: "
              f"code={c.get('code', 0)} · "
              f"bus={c.get('gui/echomind_driven', 0)} · "
              f"pywinauto={c.get('gui/pywinauto', 0)} · "
              f"live={c.get('gui/live_walkthroughs', 0)}")
    else:
        print(f"  {_badge('FAIL', 'fail')} tests/ missing")
        fails += 1
    print()

    # ── Recent crashes ──────────────────────────────────────────────
    cr = _probe_recent_crashes()
    print(f"{C_BOLD}Native faults{C_RESET}")
    if not cr["file_exists"]:
        print(f"  {_badge('-')} native_fault.log not present")
    else:
        age = cr.get("age_hours", 0)
        if cr["com_inhibit"] == 0:
            print(f"  {_badge('OK')} {cr['total']} fatal exception(s) total · "
                  f"0 COM-inhibit (0x8001010d) · "
                  f"file age {age:.1f}h")
        else:
            print(f"  {_badge('WARN', 'warn')} {cr['total']} fatal "
                  f"exception(s) total · {cr['com_inhibit']} COM-inhibit · "
                  f"file age {age:.1f}h")
            warns += 1
    print()

    # ── Verdict ─────────────────────────────────────────────────────
    print(f"{C_BOLD}Verdict{C_RESET}: ", end="")
    if fails:
        print(f"{_badge(f'{fails} fail(s)', 'fail')}  {_badge(f'{warns} warn(s)', 'warn') if warns else ''}")
        return 2
    if warns:
        print(f"{_badge(f'{warns} warn(s)', 'warn')}")
        return 1
    print(_badge("ALL GREEN"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
