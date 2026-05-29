"""Schema-integrity guard for the KPI registry.

Catches typos and inconsistencies in tests/_kpi/schema.py before they
become silent telemetry drift.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_registry():
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tests._kpi.schema import KPI_REGISTRY, KpiSpec  # type: ignore
    return KPI_REGISTRY, KpiSpec


def test_registry_not_empty():
    reg, _ = _load_registry()
    assert len(reg) >= 25, "KPI registry should cover the 25+ workflows in the architecture doc"


def test_every_key_matches_naming_convention():
    """Keys are dot-separated lowercase identifiers: workflow.metric[.sub]."""
    reg, _ = _load_registry()
    # snake_case head; tail segments allow CamelCase (DICOM endpoint names)
    pat = re.compile(r"^[a-z][a-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
    bad = [k for k in reg if not pat.match(k)]
    assert not bad, f"keys violating naming convention: {bad}"


def test_every_key_has_workflow_unit_and_thresholds():
    reg, _ = _load_registry()
    incomplete = []
    for k, spec in reg.items():
        if not spec.workflow:
            incomplete.append(f"{k}: missing workflow")
        if not spec.unit:
            incomplete.append(f"{k}: missing unit")
        if spec.hard is None and spec.warn is None:
            incomplete.append(f"{k}: must specify hard or warn threshold")
    assert not incomplete, "; ".join(incomplete)


def test_threshold_ordering_is_sane():
    reg, _ = _load_registry()
    inverted = []
    for k, spec in reg.items():
        if spec.hard is None or spec.warn is None:
            continue
        if spec.higher_better:
            if spec.warn < spec.hard:
                inverted.append(
                    f"{k}: higher_better=True but warn({spec.warn}) < hard({spec.hard})"
                )
        else:
            if spec.warn > spec.hard:
                inverted.append(
                    f"{k}: warn({spec.warn}) > hard({spec.hard})"
                )
    assert not inverted, "; ".join(inverted)


def test_baseline_json_in_sync_with_schema():
    """baseline.json keys must match the registry exactly."""
    reg, _ = _load_registry()
    baseline_path = PROJECT_ROOT / "tests" / "_kpi" / "baseline.json"
    assert baseline_path.exists(), "tests/_kpi/baseline.json missing"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_keys = set(baseline.get("kpis", {}).keys())
    reg_keys = set(reg.keys())
    missing = reg_keys - baseline_keys
    extra = baseline_keys - reg_keys
    assert not missing, f"baseline.json missing keys: {sorted(missing)}"
    assert not extra, f"baseline.json has unknown keys: {sorted(extra)}"


def test_critical_workflows_have_at_least_one_kpi():
    """Each critical workflow listed in the architecture doc has ≥1 KPI."""
    reg, _ = _load_registry()
    by_wf = {}
    for k, spec in reg.items():
        by_wf.setdefault(spec.workflow, []).append(k)
    REQUIRED_WORKFLOWS = {
        "patient_open", "bulk_download", "viewer",
        "search", "thumbnail", "process",
        "ui", "crash", "recovery",
    }
    missing = sorted(REQUIRED_WORKFLOWS - set(by_wf.keys()))
    assert not missing, f"workflows in arch doc with no KPI: {missing}"
