"""Different clinics must never inherit RAZI's department numbers."""
import time
from types import SimpleNamespace

import pytest

from reception_crm.local import datamodel as dm
from reception_crm.local.mongo import LocalMongoUnavailable
from reception_crm.lexicon import center
from reception_crm.core.tools import reports


@pytest.fixture
def other_center(monkeypatch):
    departments = [
        dm.Modality("3", "MRI", "ام آر آی", "MR", False),
        dm.Modality("72", "Sonography", "سونوگرافی", "US", False),
        dm.Modality("44", "Radiology", "رادیولوژی", "DX", False),
    ]
    monkeypatch.setattr(dm, "_cache", dm._Cache(
        at=time.time(), modalities={m.code: m for m in departments}))
    monkeypatch.setattr(center, "load_center", lambda: {
        "center": "OTHER", "departments": [
            {"code": m.code, "name_en": m.name, "name_fa": m.name_fa,
             "short": m.short, "disabled": m.disabled} for m in departments
        ], "services": [], "service_groups": [], "service_concepts": []})
    return departments


@pytest.mark.parametrize("term", ["ultrasound", "US", "Sonography", "سونوگرافی"])
def test_alias_uses_local_identity_even_when_old_code_is_another_department(other_center, term):
    assert dm.resolve_modality(term).code == "72"
    assert dm.resolve_modality("MRI").code == "3"


def test_queue_sends_resolved_id_to_vendor_api(other_center, monkeypatch):
    calls = []
    def worklist(**kwargs):
        calls.append(kwargs)
        return {"success": True, "data": [], "pagination": {"totalItems": 0}}
    monkeypatch.setattr(reports, "_client", lambda: SimpleNamespace(reporting_worklist=worklist))
    reports._reporting_queue({"modality": "ultrasound", "startDate": "1405/07/04"})
    assert calls[0]["modality"] == "72"
    assert calls[0]["start_date"] == "1405/07/04"


def test_unknown_department_does_not_call_vendor_or_report_zero(other_center, monkeypatch):
    monkeypatch.setattr(reports, "_client", lambda: pytest.fail("invalid filter reached API"))
    result = reports._reporting_queue({"modality": "underwater scanner"})
    assert result["error"]["code"] == "UNKNOWN_FILTER_VALUE"
    assert "count" not in result


def test_duplicate_department_names_are_not_arbitrarily_selected(other_center):
    dm._cache.modalities["73"] = dm.Modality("73", "Sonography", "سونوگرافی", "US", False)
    with pytest.raises(dm.FilterValueProblem):
        dm.resolve_modality("ultrasound")
    with pytest.raises(dm.FilterValueProblem):
        dm.resolve_modality("Sonography")


def test_missing_live_catalog_uses_only_local_profile(other_center, monkeypatch):
    dm._cache.at = 0
    def unavailable():
        raise LocalMongoUnavailable("offline")
    monkeypatch.setattr(dm, "reception_db", unavailable)
    assert dm.resolve_modality("ultrasound").code == "72"


def test_missing_live_and_local_catalog_fails_closed(monkeypatch):
    monkeypatch.setattr(dm, "_cache", dm._Cache())
    def unavailable():
        raise LocalMongoUnavailable("offline")
    monkeypatch.setattr(dm, "reception_db", unavailable)
    monkeypatch.setattr(center, "load_center", lambda: {"available": False})
    with pytest.raises(LocalMongoUnavailable, match="bootstrap-center"):
        dm.resolve_modality("ultrasound")


def test_mammography_under_radiology_is_not_entire_radiology(other_center, monkeypatch):
    profile = center.load_center()
    profile["services"] = [{"id": "s1", "name": "ماموگرافی دو طرفه",
                            "department": "44", "group_name": "breast"}]
    monkeypatch.setattr(center, "load_center", lambda: profile)
    monkeypatch.setattr(reports, "_client", lambda: pytest.fail("service widened to department"))
    result = reports._reporting_queue({"modality": "ماموگرافی"})
    assert result["error"]["code"] == "SERVICE_FILTER_REQUIRED"
    assert result["error"]["resolution"]["departments"] == ["44"]


def test_dedicated_mammography_department_is_supported(other_center, monkeypatch):
    dm._cache.modalities["91"] = dm.Modality("91", "Mammography", "ماموگرافی", "MG", False)
    profile = center.load_center()
    profile["departments"].append({"code": "91", "name_en": "Mammography",
                                   "name_fa": "ماموگرافی", "short": "MG", "disabled": False})
    monkeypatch.setattr(center, "load_center", lambda: profile)
    calls = []
    def worklist(**kw):
        calls.append(kw)
        return {"success": True, "data": []}
    monkeypatch.setattr(reports, "_client", lambda: SimpleNamespace(reporting_worklist=worklist))
    reports._reporting_queue({"modality": "ماموگرافی"})
    assert calls[0]["modality"] == "91"
