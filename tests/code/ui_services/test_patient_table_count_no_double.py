"""Regression guard: patient-list Images/Series count must not double for
multi-study patients (POKORA-adjacent report, patient 46970 — 2026-06-17).

Root cause that this locks out: each per-study row fell back to the PATIENT-level
`count_of_instances` and the rows were SUMMED, so a 2-study patient showed
2 x the true total (46970: Images 5042 = 2 x 2521). The whole-patient aggregate
must be applied ONCE. This is unrelated to AcquisitionNumber (which was never in
any runtime path — only a manual maintenance tool).

The functional test imports `_hp_search` (PySide6 + package __init__), so it runs
on the workstation env; it self-skips where Qt is unavailable. The source-wiring
test runs anywhere and catches a stale/missing fix in the build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_HP = "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py"


def _load_helper():
    try:
        from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_search import (
            _resolve_patient_table_counts,
        )
    except Exception as exc:  # noqa: BLE001 - Qt/package not importable in this env
        pytest.skip(f"_hp_search not importable here: {exc}")
    return _resolve_patient_table_counts


# ── functional: the authoritative-count rule (run on the workstation env) ──────
def test_two_studies_do_not_double_even_if_rows_carry_patient_total():
    resolve = _load_helper()
    # Worst case: both study rows carry the whole-patient total (the legacy leak).
    rows = [{'series_count': 20, 'images_count': 2521},
            {'series_count': 20, 'images_count': 2521}]
    patient = {'count_of_series': 20, 'count_of_instances': 2521}
    total_series, total_images = resolve(rows, patient, patient_id='46970', total_studies=2)
    assert total_images == 2521          # NOT 5042
    assert total_series == 20            # NOT 40


def test_real_per_study_counts_sum_when_no_patient_total():
    resolve = _load_helper()
    # Server gave genuine per-study counts but no patient-level aggregate.
    rows = [{'series_count': 5, 'images_count': 519},
            {'series_count': 15, 'images_count': 2002}]
    patient = {}  # no count_of_instances / count_of_series
    total_series, total_images = resolve(rows, patient)
    assert total_images == 2521
    assert total_series == 20


def test_single_study_unchanged():
    resolve = _load_helper()
    rows = [{'series_count': 8, 'images_count': 800}]
    patient = {'count_of_series': 8, 'count_of_instances': 800}
    assert resolve(rows, patient) == (8, 800)


def test_number_of_instances_alias_is_honored():
    resolve = _load_helper()
    rows = [{'series_count': 0, 'images_count': 0},
            {'series_count': 0, 'images_count': 0}]
    patient = {'number_of_series': 20, 'number_of_instances': 2521}
    assert resolve(rows, patient) == (20, 2521)


def test_legacy_flag_restores_sum_first():
    resolve = _load_helper()
    rows = [{'series_count': 20, 'images_count': 2521},
            {'series_count': 20, 'images_count': 2521}]
    patient = {'count_of_series': 20, 'count_of_instances': 2521}
    # authoritative=False = legacy sum-first behaviour (proves the kill switch works)
    total_series, total_images = resolve(rows, patient, authoritative=False)
    assert total_images == 5042
    assert total_series == 40


# ── source wiring (runs anywhere) ──────────────────────────────────────────────
def test_source_wiring_present():
    src = (_REPO_ROOT / _HP).read_text(encoding="utf-8", errors="ignore")
    assert "_PATIENT_COUNT_AUTHORITATIVE" in src
    assert "AIPACS_PATIENT_COUNT_AUTHORITATIVE" in src
    assert "def _resolve_patient_table_counts" in src
    # the doubling fix must be wired into the server-row builder
    assert "_resolve_patient_table_counts(" in src
    # per-study placeholder rows must NOT carry the patient-level total any more
    assert "patient.get('count_of_instances', 0)" not in src
    assert "patient.get('count_of_series', 0)" not in src
