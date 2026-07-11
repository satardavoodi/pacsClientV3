# -*- coding: utf-8 -*-
"""Regression tests for the Admission Reports dashboard data layer.

Covers the PURE, headless-safe pieces of ``modules.data_analysis.admission_api``:
the Jalali date-range resolver, the snapshot builder (raw API JSON -> dashboard
view-model), and the client's URL/param/auth construction (with ``requests``
monkeypatched — no real network).

These do not require a display; ``admission_api`` imports ``PySide6.QtCore``
(QObject/Signal) only, which is available in the offscreen sandbox.
"""

import pytest

pytest.importorskip("PySide6.QtCore")

from modules.data_analysis import admission_api as api  # noqa: E402


# --------------------------------------------------------------------------- #
# Jalali date presets
# --------------------------------------------------------------------------- #
def test_jalali_today_format():
    today = api.jalali_today(0)
    parts = today.split("/")
    assert len(parts) == 3
    year, month, day = (int(p) for p in parts)
    assert year > 1400
    assert 1 <= month <= 12
    assert 1 <= day <= 31


def test_resolve_date_range_presets():
    s, e = api.resolve_date_range("today")
    assert s == e == api.jalali_today(0)

    s, e = api.resolve_date_range("yesterday")
    assert s == e == api.jalali_today(-1)

    s, e = api.resolve_date_range("last7")
    assert s == api.jalali_today(-6) and e == api.jalali_today(0)

    s, e = api.resolve_date_range("last30")
    assert s == api.jalali_today(-29) and e == api.jalali_today(0)

    # Unknown preset degrades safely to today.
    s, e = api.resolve_date_range("???")
    assert s == e == api.jalali_today(0)


def test_gregorian_to_jalali_known_date():
    # 2025-07-09 (Gregorian) == 1404/04/18 (Jalali).
    assert api._fmt_jalali(2025, 7, 9) == "1404/04/18"


# --------------------------------------------------------------------------- #
# Snapshot builder
# --------------------------------------------------------------------------- #
def _sample_payload():
    return {
        "success": True,
        "data": {
            "summary": {
                "overall": {
                    "uniquePatients": 1914,
                    "totalReceptions": 2061,
                    "totalServices": 2456,
                    "totalAmount": 58411970000,
                    "totalPatientShare": 50535220000,
                    "totalOrganizationShare": 7879900000,
                    "totalDiscount": 0,
                    "totalSalamatInsurance": 1030520000,
                    "totalTaminInsurance": 4519730000,
                    "totalArmyInsurance": 2329650000,
                    "totalSupplementaryInsurance": 0,
                },
                "debt": {
                    "totalPatientTotal": 50535220000,
                    "totalPaidAmount": 48289900000,
                    "totalCashDeskDiscount": 765870000,
                    "totalFundDiscount": 0,
                    "totalPatientDebt": 2245320000,
                },
                "byModality": [
                    {"modality": "2", "modalityFullName": "ام آر آی", "count": 730,
                     "uniquePatients": 564, "totalAmount": 29776700000, "percentageOfTotal": 50.98},
                    {"modality": "3", "modalityFullName": "سونوگرافی", "count": 924,
                     "uniquePatients": 767, "totalAmount": 13091480000, "percentageOfTotal": 22.41},
                    {"modality": "1", "modalityFullName": "سی تی اسکن", "count": 258,
                     "uniquePatients": 200, "totalAmount": 5000000000, "percentageOfTotal": 8.5},
                    {"modality": "4", "modalityFullName": "رادیولوژی", "count": 544,
                     "uniquePatients": 477, "totalAmount": 5571930000, "percentageOfTotal": 18.1},
                ],
                "byInsurance": [
                    {"insuranceType": "4", "insuranceTypeLabel": "آزاد", "count": 1158,
                     "percentageOfTotal": 41.78, "totalAmount": 24407200000},
                    {"insuranceType": "2", "insuranceTypeLabel": "تامین اجتماعی", "count": 1046,
                     "percentageOfTotal": 46.12, "totalAmount": 26941170000},
                ],
            },
            "receptions": [
                {"Date": "1405/04/17", "Time": "10:20", "modality": "2",
                 "insuranceTypeLabel": "آزاد", "totalAmount": 500000, "ReceptionID": 123,
                 "patientDetails": {"fullName": "علی رضایی"},
                 "modalityDetails": {"fullName": "ام آر آی"}, "service": {"name": "MRI Brain"}},
                {"Date": "1405/04/17", "Time": "11:00", "modality": "3",
                 "insuranceTypeLabel": "تامین اجتماعی", "totalAmount": 300000, "ReceptionID": 124,
                 "patientDetails": {"fullName": "مریم احمدی"}},
                {"Date": "1405/04/16", "Time": "09:00", "modality": "1",
                 "insuranceTypeLabel": "آزاد", "totalAmount": 900000, "ReceptionID": 125,
                 "patientDetails": {"fullName": "حسن کریمی"}},
            ],
            "pagination": {"totalCount": 2061},
        },
    }


def test_build_snapshot_cards_and_highlights():
    snap = api.build_admission_snapshot(_sample_payload())
    cards = snap["cards"]
    assert cards["total_patients"] == 1914
    assert cards["total_receptions"] == 2061
    assert cards["total_services"] == 2456
    assert cards["total_amount"] == 58411970000

    hi = {c["code"]: c for c in snap["highlight_cards"]}
    assert hi["2"]["count"] == 730     # MRI
    assert hi["1"]["count"] == 258     # CT
    assert hi["3"]["count"] == 924     # US
    assert hi["4"]["count"] == 544     # X-ray
    assert hi["2"]["patients"] == 564


def test_build_snapshot_financial_section():
    snap = api.build_admission_snapshot(_sample_payload())
    fin = snap["financial"]
    assert fin["patient_share"] == 50535220000
    assert fin["insurance_share"] == 7879900000
    assert fin["total_discount"] == 0
    assert fin["cashier_discount"] == 765870000       # totalCashDeskDiscount
    assert fin["manual_withdrawal"] == 0              # totalFundDiscount
    # Total Revenue = Patient Share + Insurance Share − Manual Withdrawal − Cashier Discount
    expected = 50535220000 + 7879900000 - 0 - 765870000
    assert fin["total_revenue"] == expected
    # Headline revenue card reflects the business formula (not gross totalAmount).
    assert snap["cards"]["total_amount"] == expected
    assert fin["gross_amount"] == 58411970000


def test_financial_formula_with_nonzero_deductions():
    payload = {"data": {"summary": {
        "overall": {"totalPatientShare": 1000, "totalOrganizationShare": 500, "totalDiscount": 30},
        "debt": {"totalCashDeskDiscount": 40, "totalFundDiscount": 25},
    }}}
    fin = api.build_admission_snapshot(payload)["financial"]
    assert fin["total_revenue"] == 1000 + 500 - 25 - 40  # 1435


def test_build_snapshot_charts_sorted_desc():
    snap = api.build_admission_snapshot(_sample_payload())
    counts = [r["count"] for r in snap["modality_rows"]]
    assert counts == sorted(counts, reverse=True)
    assert snap["modality_rows"][0]["count"] == 924  # US is largest

    ins = [r["count"] for r in snap["insurance_rows"]]
    assert ins == sorted(ins, reverse=True)


def test_build_snapshot_daily_trend_and_table():
    snap = api.build_admission_snapshot(_sample_payload())
    daily = {r["date"]: r["count"] for r in snap["daily_rows"]}
    assert daily["1405/04/17"] == 2
    assert daily["1405/04/16"] == 1
    # Chronological order.
    assert [r["date"] for r in snap["daily_rows"]] == ["1405/04/16", "1405/04/17"]

    rows = snap["table_rows"]
    assert len(rows) == 3
    assert rows[0]["patient"] == "علی رضایی"
    assert rows[0]["modality"] == "ام آر آی"


def test_build_snapshot_tolerates_empty_and_partial():
    assert api.build_admission_snapshot({})["cards"]["total_patients"] == 0
    assert api.build_admission_snapshot({"data": {}})["modality_rows"] == []
    assert api.build_admission_snapshot({"data": {"summary": {}}})["daily_rows"] == []
    # Missing patientDetails must not crash.
    p = {"data": {"receptions": [{"Date": "1405/04/17", "modality": "2"}]}}
    snap = api.build_admission_snapshot(p)
    assert snap["table_rows"][0]["patient"] == "-"


# --------------------------------------------------------------------------- #
# Client — URL / params / auth (no real network)
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {"data": {"summary": {}, "receptions": []}}

    def json(self):
        return self._payload


def test_client_builds_request_with_bearer(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResp(200)

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(api, "get_socket_token_manager",
                        lambda: type("T", (), {"get_token": staticmethod(lambda: "JWT123")})())

    client = api.AdmissionReportsClient(base_url="http://host:8080")
    client.fetch_report("1405/04/01", "1405/04/18", limit=50, insurance_type="2")

    assert captured["url"].endswith(api.REPORT_PATH)
    assert captured["params"]["startDate"] == "1405/04/01"
    assert captured["params"]["endDate"] == "1405/04/18"
    assert captured["params"]["limit"] == 50
    assert captured["params"]["insuranceType"] == "2"
    assert captured["headers"]["Authorization"] == "Bearer JWT123"


def test_client_no_token_raises_auth(monkeypatch):
    monkeypatch.setattr(api, "get_socket_token_manager",
                        lambda: type("T", (), {"get_token": staticmethod(lambda: None)})())
    client = api.AdmissionReportsClient(base_url="http://host:8080")
    with pytest.raises(api.AdmissionAuthError):
        client.fetch_report("1405/04/01", "1405/04/18")


def test_client_401_without_reauth_raises_auth(monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _FakeResp(401))
    monkeypatch.setattr(api, "get_socket_token_manager",
                        lambda: type("T", (), {"get_token": staticmethod(lambda: "JWT")})())
    client = api.AdmissionReportsClient(base_url="http://host:8080")
    # Disable the saved-credentials re-auth path so we test the raise directly.
    monkeypatch.setattr(client, "try_reauth", lambda: False)
    with pytest.raises(api.AdmissionAuthError):
        client.fetch_report("1405/04/01", "1405/04/18")
