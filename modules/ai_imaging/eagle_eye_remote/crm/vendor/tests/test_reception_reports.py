"""The two tools that read the reception software's OWN reports.

Both exist because of the same finding: the agent answered every management
question from two endpoints, while the reception system ships around twenty. A
question with no matching source does not fail politely — it gets answered from
whatever was nearest, in fluent Persian, with a date printed on it.

The tests here guard the two things that make these tools trustworthy: that the
cashier report never claims a period it does not have, and that "who was
busiest" is decided by a sort rather than by a model.
"""

from __future__ import annotations

import pytest

from reception_crm import management
from reception_crm.core.registry import default_registry


class FakeClient:
    """Records what was asked of the reception API, and answers with a fixture."""

    def __init__(self, cashier=None, physician=None):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._cashier = cashier or CASHIER_PAYLOAD
        self._physician = physician or PHYSICIAN_PAYLOAD

    @classmethod
    def bind(cls, monkeypatch, **kwargs):
        client = cls(**kwargs)
        monkeypatch.setattr(management, "InoClient", type("_Factory", (), {"from_env": staticmethod(lambda: client)}))
        return client

    def cashier_report(self, *a, **kw):
        self.calls.append(("cashier_report", a, kw))
        return self._cashier

    def physician_performance_summary(self, *a, **kw):
        self.calls.append(("physician_performance_summary", a, kw))
        return self._physician


CASHIER_PAYLOAD = {
    "success": True,
    "data": {
        "cashierReport": [
            {"fullName": "حمیده عباس زاده", "userName": "abaszadeh", "totalTransactions": 101,
             "totalCredit": 2_600_000_000, "totalDebt": 0, "netAmount": 2_600_000_000},
            {"fullName": "احمد احمدی", "userName": "ahmadi", "totalTransactions": 4,
             "totalCredit": 135_690_000, "totalDebt": 0, "netAmount": 135_690_000},
        ],
        "byModality": [{"modalityName": "سونوگرافی", "totalTransactions": 60}],
        "paymentsByCard": [{"cardName": "کارت‌خوان ۱", "bankName": "ملت", "totalAmount": 2_573_240_000}],
        "cashPayment": {"paymentType": "cash", "totalAmount": 43_710_000, "transactionCount": 5},
        "insurancePayments": [{"insuranceType": "تامین اجتماعی", "totalAmount": 291_320_000}],
        "discountedPatientsStats": {"totalDiscountedPatients": 3, "totalAllDiscounts": 2_050_000},
        "summary": {
            "incomes": {"cash": {"amount": 43_710_000}, "card": {"amount": 2_573_240_000}, "total": 3_027_010_000},
            "withdrawals": {"total": 2_600_860_000},
            "deleted": {"total": {"amount": 0, "count": 0}},
            "cashDeskNet": {"net": 2_735_690_000},
            "overall": {"totalCredit": 2_735_690_000, "totalDebt": 0, "netAmount": 2_735_690_000,
                        "totalTransactions": 105, "uniqueUsers": 2},
            "paymentDetails": {"totalCardPayments": 2_573_240_000, "totalCashPayments": 43_710_000},
        },
        "reportInfo": {
            "currentPersianDate": "1405/06/01",
            "reportDate": "1405/06/01 14:11:48",
            "scope": "cashier_active",
            "scopeNotes": ["تراکنش‌های حذف‌شده فقط در بخش تفکیک نمایش داده می‌شوند."],
            "filters": {},
        },
    },
}

PHYSICIAN_PAYLOAD = {
    "success": True,
    "data": [
        {"radiologistName": "دکتر الف", "personnelCode": "11", "speciality": "رادیولوژی",
         "totalPatients": 4, "totalRevenue": 90_000_000, "totalPatientShare": 80_000_000,
         "departmentSummary": [{"modalityName": "سی‌تی", "patientCount": 4, "revenue": 90_000_000}]},
        {"radiologistName": "دکتر ب", "personnelCode": "12", "speciality": "رادیولوژی",
         "totalPatients": 21, "totalRevenue": 300_000_000, "totalPatientShare": 280_000_000,
         "departmentSummary": [{"modalityName": "سونوگرافی", "patientCount": 21, "revenue": 300_000_000}]},
        {"radiologistName": "دکتر ج", "personnelCode": "13", "speciality": "رادیولوژی",
         "totalPatients": 5, "totalRevenue": 60_680_000, "totalPatientShare": 42_980_000,
         "departmentSummary": []},
    ],
    "summary": {
        "totalRadiologists": 3, "totalPatients": 30, "totalRevenue": 450_680_000,
        "totalPatientShare": 402_980_000, "totalInsuranceShare": 45_650_000,
        "totalPaidAmount": 402_980_000, "totalDiscount": 2_050_000,
        "departmentBreakdown": [{"modality": "3", "patientCount": 27}],
    },
}


# --------------------------------------------------------------------------- #
# the cashier report
# --------------------------------------------------------------------------- #
def test_the_cashier_report_is_asked_for_the_period_it_was_given(monkeypatch, tmp_path):
    """It honours `startDate`/`endDate` — 108 transactions today against 191
    yesterday.

    This test replaces one asserting the opposite. The endpoint ignores
    `startTime`/`endTime`, which I had read out of the minified UI bundle and
    probed with; every call including "yesterday" therefore returned today, and
    I concluded the report had no period at all. Three of the four probes were
    the same call. When testing whether a parameter is honoured, the control has
    to be a different VALUE of that parameter — a different parameter NAME makes
    "ignored" and "misspelled" produce identical evidence.
    """
    client = FakeClient.bind(monkeypatch, cashier=CASHIER_PAYLOAD)
    management.cashier_report(management.resolve_period("1405/05/31"), tmp_path)

    (name, args, kwargs), = client.calls
    assert name == "cashier_report"
    assert (args[:2] or (kwargs.get("start_date"), kwargs.get("end_date"))) == ("1405/05/31", "1405/05/31")


def test_the_cashier_report_publishes_its_period_and_its_inclusion_scope_apart(monkeypatch, tmp_path):
    """`reportInfo.scope` says which cashier SESSIONS are counted; the period
    says which days. Conflating them is what produced the wrong conclusion the
    first time, so they are separate keys."""
    FakeClient.bind(monkeypatch)
    out = management.cashier_report(management.resolve_period("1405/06/01"), tmp_path)

    assert out["period"]["start_date"] == "1405/06/01"
    assert out["scope"]["kind"] == "cashier_active"
    assert out["scope"]["notes_fa"], "the report's own inclusion notes were dropped"


def test_the_cashier_totals_are_the_reception_softwares_own(monkeypatch, tmp_path):
    """Passed through, not recomputed. A second arithmetic of our own could
    disagree with the screen the clinic trusts, and the clinic would be right."""
    FakeClient.bind(monkeypatch)
    out = management.cashier_report(management.resolve_period("1405/06/01"), tmp_path)

    assert out["totals"] == {
        "income": 3_027_010_000,
        "withdrawals": 2_600_860_000,
        "net": 2_735_690_000,
        "transactions": 105,
        "cashiers": 2,
    }
    assert [c["name"] for c in out["by_cashier"]] == ["حمیده عباس زاده", "احمد احمدی"]
    assert out["by_cashier"][0]["transactions"] == 101


def test_the_cashier_report_survives_an_empty_till(monkeypatch, tmp_path):
    """Before the first transaction of the day every block is missing. An
    answer of zeroes is right; a KeyError at 07:00 is not."""
    FakeClient.bind(monkeypatch, cashier={"success": True, "data": {}})
    out = management.cashier_report(management.resolve_period("1405/06/01"), tmp_path)

    assert out["by_cashier"] == []
    assert out["totals"]["income"] is None
    assert out["scope"]["kind"] == "cashier_active"


# --------------------------------------------------------------------------- #
# physician workload
# --------------------------------------------------------------------------- #
def test_physicians_are_ranked_by_python_not_by_the_model(monkeypatch, tmp_path):
    """"Who did the most" is a sort. A model asked to order Persian names
    against nine-digit rials will occasionally swap two of them, and the wrong
    order reads exactly as confidently as the right one."""
    FakeClient.bind(monkeypatch)
    out = management.physician_performance(management.resolve_period("1405/06/01"), tmp_path)

    assert [p["name"] for p in out["physicians"]] == ["دکتر ب", "دکتر ج", "دکتر الف"]
    assert [p["rank"] for p in out["physicians"]] == [1, 2, 3]
    assert out["busiest"] == "دکتر ب"


def test_a_tie_on_patients_is_broken_by_revenue(monkeypatch, tmp_path):
    payload = {
        "success": True,
        "data": [
            {"radiologistName": "کم‌درآمد", "totalPatients": 7, "totalRevenue": 10},
            {"radiologistName": "پردرآمد", "totalPatients": 7, "totalRevenue": 20},
        ],
        "summary": {},
    }
    FakeClient.bind(monkeypatch, physician=payload)
    out = management.physician_performance(management.resolve_period("1405/06/01"), tmp_path)
    assert [p["name"] for p in out["physicians"]] == ["پردرآمد", "کم‌درآمد"]


def test_the_workload_tool_says_what_it_is_counting(monkeypatch, tmp_path):
    """30 patients here against 96 admissions the same day. Both are true; a
    reader who thinks this is the day's total will conclude the clinic lost
    two thirds of its patients."""
    FakeClient.bind(monkeypatch)
    out = management.physician_performance(management.resolve_period("1405/06/01"), tmp_path)

    assert out["totals"]["patients"] == 30
    assert "کل پذیرش‌های روز" in out["counts_what_fa"]


def test_the_workload_tool_is_asked_for_the_period_it_was_given(monkeypatch, tmp_path):
    """This endpoint IS date-scoped — verified by getting different answers for
    two different days — so the period must actually be sent."""
    client = FakeClient.bind(monkeypatch)
    management.physician_performance(management.resolve_period("1405/05/31"), tmp_path)

    name, args, _ = client.calls[0]
    assert name == "physician_performance_summary"
    assert args[:2] == ("1405/05/31", "1405/05/31")


def test_no_physicians_is_an_empty_answer_not_a_crash(monkeypatch, tmp_path):
    FakeClient.bind(monkeypatch, physician={"success": True, "data": [], "summary": {}})
    out = management.physician_performance(management.resolve_period("1405/06/01"), tmp_path)
    assert out["physicians"] == []
    assert out["busiest"] is None


# --------------------------------------------------------------------------- #
# the descriptions are the tool-selection prompt
# --------------------------------------------------------------------------- #
MANAGEMENT_TOOLS = [
    "daily-summary", "patient-list", "financial-analysis", "cashier-report",
    "cashier-deleted-transactions", "cashier-reconciliation", "physician-performance",
    "risk-analysis", "trend-analysis",
]


@pytest.mark.parametrize("name", MANAGEMENT_TOOLS)
def test_a_management_tool_describes_itself_well_enough_to_be_chosen(name):
    """These were two words each — "Financial review", "Period comparison" —
    for six tools that all read the same day and all sound plausible for any
    money question. The description IS the tool-selection prompt, and a wrong
    tool cannot be recovered from further down the pipeline."""
    description = default_registry().tools[name].description
    assert len(description) > 80, f"{name} gives the model almost nothing to choose on"
    assert "Use" in description or "use" in description, f"{name} never says what it is FOR"


def test_the_two_cashier_tools_point_at_each_other():
    """They are the pair most likely to be confused, so each says when the
    other is the right one."""
    tools = default_registry().tools
    assert "cashier-reconciliation" in tools["cashier-report"].description
    assert "cashier-report" in tools["cashier-reconciliation"].description


def test_deleted_transactions_keep_registration_and_deletion_actors_separate(
    monkeypatch, tmp_path
):
    class DeletedClient:
        def cashier_deleted_transactions(self, *args, **kwargs):
            return {
                "success": True,
                "data": {
                    "transactions": [
                        {
                            "_id": "tx1",
                            "ReceptionID": 123,
                            "amount": 70,
                            "date": "1405/06/11",
                            "userDetails": {"id": "u1", "fullName": "ثبت‌کننده"},
                            "deletedByDetails": {"id": "u2", "fullName": "حذف‌کننده"},
                            "patientDetails": {"name": "نباید منتشر شود", "nationalCode": "1"},
                        },
                        {
                            "_id": "tx2",
                            "ReceptionID": 124,
                            "amount": 30,
                            "date": "1405/06/11",
                            "userDetails": {"id": "u1", "fullName": "ثبت‌کننده"},
                            "deletedByDetails": {"id": "u2", "fullName": "حذف‌کننده"},
                            "patientDetails": {"name": "نباید منتشر شود", "nationalCode": "2"},
                        },
                    ],
                    "stats": {
                        "overall": {"totalAmount": 100, "transactionCount": 2},
                        "byCategory": [],
                    },
                    "pagination": {
                        "totalCount": 2,
                        "collectionComplete": True,
                    },
                },
            }

    monkeypatch.setattr(
        management,
        "InoClient",
        type("_Factory", (), {"from_env": staticmethod(DeletedClient)}),
    )
    out = management.cashier_deleted_transactions(
        management.resolve_period("1405/06/11"), tmp_path
    )

    assert out["totals"]["transactions"] == 2
    assert out["by_original_user"] == [
        {"user_id": "u1", "name": "ثبت‌کننده", "count": 2, "amount": 100.0}
    ]
    assert out["by_deleted_by"] == [
        {"user_id": "u2", "name": "حذف‌کننده", "count": 2, "amount": 100.0}
    ]
    assert "patient" not in out["transactions"][0]
    assert out["completeness"]["detailsComplete"] is True
