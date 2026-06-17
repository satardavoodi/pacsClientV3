"""Unit tests for the canonical patient-study-set contract + merge authority.

Target: ``PacsClient/utils/patient_study_set.py`` (pure Python; no Qt/VTK).
Foundation (Phase 1) for the unified pipeline — see
``docs/reports/UNIFIED_PIPELINE_EVALUATION_2026-06-17.md``.

The module is loaded BY FILE PATH (importlib) so these tests stay hermetic: they
do not require PySide6 or the ``PacsClient`` package ``__init__`` import chain, and
can run anywhere (sandbox or Windows).
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _REPO_ROOT / "PacsClient" / "utils" / "patient_study_set.py"

_spec = importlib.util.spec_from_file_location(
    "aipacs_patient_study_set_under_test", _MODULE_PATH
)
pss = importlib.util.module_from_spec(_spec)
# Register under its spec name BEFORE exec_module: the module uses
# `from __future__ import annotations`, and on Python 3.11+ @dataclass resolves
# the owning module via sys.modules during class processing. Without this the
# synthetic module name is absent from sys.modules and dataclasses raises
# "AttributeError: 'NoneType' object has no attribute '__dict__'".
sys.modules[_spec.name] = pss
_spec.loader.exec_module(pss)


# ── merge_study_uids: the single "which studies?" authority ──────────────────
def test_merge_union_dedup_selected_first():
    ordered, dropped = pss.merge_study_uids([["A", "B"], ["B", "C"]], selected_study_uid="C")
    assert ordered == ["C", "A", "B"]  # selected first, then first-seen, deduped
    assert dropped == []


def test_merge_filters_empty_and_whitespace():
    ordered, dropped = pss.merge_study_uids([["A", "", "  ", None, "B"]], selected_study_uid="")
    assert ordered == ["A", "B"]
    assert dropped == []


def test_merge_no_owner_filter_when_no_callable():
    ordered, dropped = pss.merge_study_uids([["A", "B"]], selected_study_uid="A")
    assert ordered == ["A", "B"]
    assert dropped == []


def test_merge_drops_foreign_owner_keeps_unknown():
    owners = {"A": "P", "B": "OTHER", "C": None}
    ordered, dropped = pss.merge_study_uids(
        [["A", "B", "C"]], selected_study_uid="A",
        owner_of=lambda u: owners.get(u), patient_id="P")
    assert ordered == ["A", "C"]  # A(owner P) kept, B(foreign) dropped, C(unknown) kept
    assert dropped == ["B"]


def test_merge_keeps_selected_even_if_foreign():
    # The explicitly-selected study is kept (and first) even if its owner looks foreign.
    ordered, dropped = pss.merge_study_uids(
        [["S", "Y"]], selected_study_uid="S",
        owner_of=lambda u: "OTHER", patient_id="P")
    assert ordered[0] == "S"
    assert "S" not in dropped
    assert "Y" in dropped


def test_merge_owner_lookup_exception_keeps_uid():
    def _raising(_u):
        raise RuntimeError("flaky owner lookup")

    ordered, dropped = pss.merge_study_uids(
        [["A", "B"]], selected_study_uid="A", owner_of=_raising, patient_id="P")
    assert ordered == ["A", "B"]  # A selected (no lookup); B lookup raises -> kept
    assert dropped == []


def test_merge_empty_inputs():
    ordered, dropped = pss.merge_study_uids([], selected_study_uid="")
    assert ordered == []
    assert dropped == []


# ── data contract ────────────────────────────────────────────────────────────
def test_patient_study_set_props():
    ps = pss.PatientStudySet(
        patient_id="P", patient_name="N", selected_study_uid="S1",
        studies=(
            pss.StudyDescriptor(study_uid="S1", patient_id="P"),
            pss.StudyDescriptor(study_uid="S2", patient_id="P"),
        ),
    )
    assert ps.study_uids == ("S1", "S2")
    assert ps.is_multistudy is True
    assert ps.study("S2").study_uid == "S2"
    assert ps.study("NOPE") is None


def test_single_study_not_multistudy():
    ps = pss.PatientStudySet(
        patient_id="P", patient_name="N", selected_study_uid="S1",
        studies=(pss.StudyDescriptor(study_uid="S1"),),
    )
    assert ps.is_multistudy is False
    assert ps.study_uids == ("S1",)


def test_contract_is_frozen():
    req = pss.PatientStudySetRequest(patient_id="P")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.patient_id = "X"  # type: ignore[misc]

    sd = pss.SeriesDescriptor(study_uid="S1", series_uid="U1", series_number="3")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sd.series_number = "9"  # type: ignore[misc]


def test_series_descriptor_defaults():
    s = pss.SeriesDescriptor(study_uid="S1")
    assert s.series_uid == "" and s.series_number == "" and s.image_count == 0
    assert s.is_document is False


def test_intent_vocabulary_stable():
    # The intent vocabulary the unified path branches on must stay stable.
    assert pss.Intent.PREVIEW_ONLY == "preview_only"
    assert pss.Intent.OPEN_VIEWER == "open_viewer"
    assert pss.Intent.REFRESH_OPEN_VIEWER == "refresh_open_viewer"


# ── diff_study_uids: the Phase-2 study-set-growth detector core ──────────────
def test_diff_basic_growth():
    assert pss.diff_study_uids(["A"], ["A", "B"]) == ["B"]


def test_diff_no_growth_when_subset():
    assert pss.diff_study_uids(["A", "B"], ["A"]) == []
    assert pss.diff_study_uids(["A", "B"], ["B", "A"]) == []


def test_diff_dedups_and_cleans():
    assert pss.diff_study_uids(["A"], ["B", "B", "  ", None, "C", "A"]) == ["B", "C"]


def test_diff_empty_previous_is_all_new():
    assert pss.diff_study_uids([], ["A", "B"]) == ["A", "B"]


def test_late_growth_46630_scenario():
    # Open recorded only the imaging study; the reconcile discovered imaging + DOC.
    # The DOC study (separate 1.2.826 UID) must surface as the late growth.
    open_uids = ["1.3.12.090"]
    discovered = ["1.3.12.090", "1.2.826.389"]
    owners = {u: "46630" for u in discovered}
    canonical, dropped = pss.merge_study_uids(
        [discovered], "", owner_of=lambda u: owners.get(u), patient_id="46630")
    new = pss.diff_study_uids(open_uids, canonical)
    assert new == ["1.2.826.389"]
    assert dropped == []


def test_late_growth_excludes_foreign_study():
    # A foreign study leaking into the discovered set must NOT be reported as growth.
    open_uids = ["1.3.12.090"]
    discovered = ["1.3.12.090", "1.2.826.389", "9.9.FOREIGN"]
    owners = {"1.3.12.090": "46630", "1.2.826.389": "46630", "9.9.FOREIGN": "44533"}
    canonical, dropped = pss.merge_study_uids(
        [discovered], "", owner_of=lambda u: owners.get(u), patient_id="46630")
    new = pss.diff_study_uids(open_uids, canonical)
    assert new == ["1.2.826.389"]
    assert dropped == ["9.9.FOREIGN"]


# ── resolve_study_uids: conditional-fallback gather + owner-filter ────────────
def test_resolve_table_primary_ignores_fallbacks_when_multi():
    # Table already gives >1 study -> stale right-panel/cache must NOT widen it.
    ordered, dropped = pss.resolve_study_uids(
        table_uids=["A", "B"], rightpanel_uids=["STALE"], cache_uids=["X"],
        selected_study_uid="A")
    assert ordered == ["A", "B"]
    assert dropped == []


def test_resolve_consults_rightpanel_when_table_sparse():
    # Table gives 1 -> right-panel consulted; then len==2 -> cache NOT consulted.
    ordered, _ = pss.resolve_study_uids(
        table_uids=["A"], rightpanel_uids=["B"], cache_uids=["C"], selected_study_uid="A")
    assert ordered == ["A", "B"]


def test_resolve_consults_cache_when_still_sparse():
    ordered, _ = pss.resolve_study_uids(
        table_uids=["A"], rightpanel_uids=[], cache_uids=["C"], selected_study_uid="A")
    assert ordered == ["A", "C"]


def test_resolve_owner_filter_drops_foreign():
    owners = {"A": "P", "FOREIGN": "OTHER"}
    ordered, dropped = pss.resolve_study_uids(
        table_uids=["A", "FOREIGN"], selected_study_uid="A",
        owner_of=lambda u: owners.get(u), patient_id="P")
    assert ordered == ["A"]
    assert dropped == ["FOREIGN"]


def test_resolve_selected_first():
    ordered, _ = pss.resolve_study_uids(table_uids=["A", "B"], selected_study_uid="B")
    assert ordered == ["B", "A"]


# ── build_download_payload: canonical DownloadPlan dict ──────────────────────
def test_build_download_payload():
    info = {"study_date": "2026-06-17", "modality": "DOC", "study_description": "Doc",
            "count_of_series": 1,
            "series": [{"series_uid": "u", "series_number": "100000", "image_count": 3}]}
    p = pss.build_download_payload("S1", " 46630 ", "Name", info)
    assert p["study_uid"] == "S1" and p["patient_id"] == "46630"
    assert p["series_count"] == 1 and p["images_count"] == 3
    assert p["modality"] == "DOC" and p["description"] == "Doc" and p["study_date"] == "2026-06-17"
    # Both keys must carry the description (DM queue reads 'study_description').
    assert p["study_description"] == "Doc"
    assert p["series"] is info["series"]


def test_build_download_payload_defaults():
    p = pss.build_download_payload("S1", "P", "N", {})
    assert p["series"] == [] and p["images_count"] == 0 and p["series_count"] == 0


def test_service_class_api():
    assert pss.PatientStudySetService.merge_study_uids is pss.merge_study_uids
    assert pss.PatientStudySetService.resolve_study_uids is pss.resolve_study_uids
    assert pss.PatientStudySetService.build_download_payload is pss.build_download_payload
