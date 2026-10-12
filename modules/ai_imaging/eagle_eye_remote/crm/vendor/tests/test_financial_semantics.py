"""What each money figure MEANS, and which source and date basis it comes from.

Ground truth is the reception software's own three screens for **1405/06/02**,
cross-read against the vendor's REST endpoints and against the database. Every
number below was verified three ways before it was written down.

The failure these exist to prevent is not an arithmetic slip. It is the agent
answering «چقدر پول گرفتیم؟» with the value of the day's receptions, or calling
an insurance receivable "income" — confusing what was BILLED with what was
COLLECTED, and reception date with transaction date. A wrong source is not
recoverable downstream: no prompt turns the right answer out of the wrong number.
"""

from __future__ import annotations

import pytest

from reception_crm.core import sources


# --------------------------------------------------------------------------- #
# Measured 1405/06/02. Screenshot = API = database for every line here.
# --------------------------------------------------------------------------- #

RECEPTIONS = 219
SERVICES = 267
PATIENTS = 213

#: What the SERVICES were worth: sum of services[].PrivateTariff x Qty.
#: `/Reports/patients-by-service-insurance/summary` -> grandTotal.totalAmount
SERVICE_VALUE = 6_833_900_000

#: What the RECEPTIONS were worth: sum of receptions.totalAmount.
#: `/Reports/dashboard` -> overview.periodTotalAmount
RECEPTION_VALUE = 7_099_550_000

#: The difference between them, and it is not a defect: consumables.
INVENTORY = 265_650_000

PATIENT_SHARE = 5_794_980_000      # grandTotal.totalPatientShare
INSURANCE_SHARE = 1_038_930_000    # grandTotal.totalOrganizationShare
PAID = 3_481_960_000               # sum(receptions.paidAmount)
DEBT = 2_313_020_000               # patient share not yet paid
SETTLED, UNSETTLED = 151, 68

CARD = 4_563_530_000               # paymentDetails.totalCardPayments (185 tx)
CASH = 0
INSURANCE_CREDIT = 1_038_930_000   # by_payment_method.insurance (123 tx)
CASHIER_INCOME = 5_602_460_000     # totals.income
MANUAL_WITHDRAWAL = 5_720_000
CASHIER_NET = 4_557_810_000
RECEPTION_DEBT_POSTING = 7_099_560_000


# ------------------------------------------------- the identities that must hold

def test_reception_value_is_service_value_plus_consumables():
    """The 265,650,000 that made two of the vendor's own screens disagree.

    The Dashboard totals `receptions.totalAmount`; the Service & Insurance report
    totals `services[].PrivateTariff x Qty`. Same 219 receptions, same date
    filter, same deleted-exclusion — different FIELD. The difference is
    `inventoryTotalAmount`: materials billed on the reception that are not part
    of any service tariff.

    Neither figure is wrong. Reporting either one as "the day's revenue" without
    saying which is what makes them look like a bug.
    """
    assert SERVICE_VALUE + INVENTORY == RECEPTION_VALUE


def test_patient_share_minus_paid_is_the_outstanding_balance():
    """Three different questions, three different numbers.

    «سهم بیمار» is what patients owe. «پرداخت‌شده» is what has arrived. «بدهکاری»
    is the remainder. An answer that offers one when asked for another is wrong
    even though every figure in it is real.
    """
    assert PATIENT_SHARE - PAID == DEBT


def test_settled_and_unsettled_partition_the_receptions():
    assert SETTLED + UNSETTLED == RECEPTIONS


def test_cashier_income_includes_insurance_but_the_net_does_not():
    """The single most misread pair on the cashier screen.

    `totals.income` counts an insurance credit as income. `net` does not — it is
    money through the drawer, less what was taken out of it. Quoting income as
    "what the till took" overstates it by the entire insurance receivable.
    """
    assert CASH + CARD + INSURANCE_CREDIT == CASHIER_INCOME
    assert CASH + CARD - MANUAL_WITHDRAWAL == CASHIER_NET
    assert CASHIER_NET != CASHIER_INCOME - MANUAL_WITHDRAWAL


def test_reception_debt_posting_is_not_a_withdrawal():
    """`withdrawals.receptionDebt` is the day's receptions being debited — it
    tracks the reception value, not cash leaving the building. Only
    `manualWithdrawal` is an actual withdrawal, and it is three orders of
    magnitude smaller."""
    assert abs(RECEPTION_DEBT_POSTING - RECEPTION_VALUE) <= 10_000
    assert MANUAL_WITHDRAWAL < RECEPTION_DEBT_POSTING / 1000


def test_the_two_totals_must_never_be_compared_as_though_equal():
    """Cashier income is transaction-dated; reception value is reception-dated.
    They describe different events over different populations and there is no
    reason for them to match. The gap is not a discrepancy to report."""
    assert CASHIER_INCOME != RECEPTION_VALUE
    assert CASHIER_INCOME != SERVICE_VALUE


# ------------------------------------------------------ counting units are three

def test_patients_receptions_and_services_are_three_different_numbers():
    """213 people generated 219 visits containing 267 procedures. Every one of
    those is the right answer to a different question and the wrong answer to
    the other two."""
    assert PATIENTS < RECEPTIONS < SERVICES


# --------------------------------------------- the cross-check honesty guarantee

def test_same_source_comparisons_are_marked_as_not_independent():
    """`daily-summary` and `financial-analysis` are two views of ONE upstream
    computation. Comparing them catches a normaliser drifting and verifies
    nothing about the figure itself — but the phone rendered those ticks
    identically to a real cross-check, so an owner reading four green ✔ saw four
    confirmations where three were tautological."""
    by_pair = {(c.left, c.right, c.meaning): c for c in sources.COMPARISONS}
    same_source = [c for c in sources.COMPARISONS
                   if {c.left, c.right} == {"daily-summary", "financial-analysis"}]
    assert same_source, "the self-comparisons should still exist — they catch drift"
    for check in same_source:
        assert check.independent is False, f"{check.meaning} is not an independent check"
    assert by_pair  # the pairs are addressable


def test_cross_source_comparisons_stay_marked_independent():
    """The cash and card checks compare two genuinely different endpoints
    describing the same till. Those are the ones worth a green tick."""
    real = [c for c in sources.COMPARISONS
            if {c.left, c.right} == {"daily-summary", "cashier-report"}]
    assert real, "the only independent money checks we have must not be dropped"
    assert all(c.independent for c in real)


def test_every_comparison_declares_its_kind():
    """A finding must carry `independent` so the reader can tell the two apart.
    A control that cannot be distinguished from a stronger control is not the
    control people think it is."""
    for check in sources.COMPARISONS:
        assert isinstance(check.independent, bool)


# ------------------------------------------------- the tool descriptions teach it

@pytest.mark.parametrize("tool,must_say", [
    ("cashier-report", ["TRANSACTION date", "Insurance is not in the net"]),
    ("financial-analysis", ["reception date", "receivable, not money received"]),
    ("daily-summary", ["reception date", "inventoryTotalAmount", "uniquePatients"]),
])
def test_the_tool_description_states_its_date_basis(tool, must_say):
    """The description is the tool-SELECTION prompt, and date basis is the thing
    that most often decides whether an answer is right. It belongs where the
    model is choosing, not in a document nobody loads at query time."""
    from reception_crm.core.registry import default_registry

    text = default_registry().get(tool).description
    for phrase in must_say:
        assert phrase in text, f"{tool} description must say {phrase!r}"


# ------------------------------------ meaning must travel WITH the value

def test_the_withdrawals_block_says_it_is_not_the_patient_balance():
    """Live failure, caught on the first routing test after this work.

    «بیمارها امروز چقدر بدهکار موندن؟» chose `cashier-report` and answered
    **7,099,560,000** — the whole day's reception value — as «بدهی باقی‌مانده
    بیماران». The true outstanding balance was 2,313,020,000. A threefold
    overstatement of a debt, read off a field that is not a debt.

    The tool description already warned about that exact field and it did not
    help: a warning one scroll away from the number loses to the number. So the
    meaning now ships inside the block, next to the figure it governs.
    """
    from reception_crm import management
    import inspect

    src = inspect.getsource(management.cashier_report)
    assert "not_the_patient_balance_fa" in src
    assert "financial-analysis" in src, "it must name where the answer actually lives"
    assert "manualWithdrawal" in src, "and which withdrawal is a real withdrawal"


def test_the_debt_block_claims_the_question_by_name():
    from reception_crm import management
    import inspect

    src = inspect.getsource(management.financial_analysis)
    assert "patient_share - paid_amount = patient_debt" in src
    assert "بدهکار" in src, "the owner's own word has to appear where the answer is"


@pytest.mark.parametrize("skill,basis", [("cashier_report", "transaction"),
                                         ("financial_analysis", "reception")])
def test_every_money_report_declares_its_date_basis_in_the_payload(skill, basis):
    """Not only in the description: the payload itself carries `date_basis`, so a
    figure can never be lifted out of it without its basis coming along."""
    from reception_crm import management
    import inspect

    src = inspect.getsource(getattr(management, skill))
    assert '"date_basis"' in src
    assert f'"{basis}"' in src


def test_patient_debt_and_reception_debt_are_far_apart():
    """The guard rail behind the confusion: these two numbers are not close, so
    a mix-up is never a rounding question. On 1405/06/02 one was 3.07x the
    other."""
    assert RECEPTION_DEBT_POSTING > DEBT * 3


def test_report_mode_can_reach_the_patient_debt_figure_without_an_analysis_tool():
    """The capability was already on the menu; nothing pointed at it.

    Report mode answered «بیمارها چقدر بدهکارند» from `cashier-report` and
    returned a figure 3x too large. My first fix was to put `financial-analysis`
    on the Report menu — and `test_modes.py` rejected it, correctly: Report
    retrieves, and a tool whose output IS interpretation makes a Report answer
    interpretive whatever the prompt says.

    The guard was right and it exposed the better fix. `daily-summary` is
    already on that menu and already returns `financial.patient_debt`. This is
    the fourth time in this project the shape has been the same: **the
    capability existed and nothing was wired to it.**
    """
    from reception_crm.core import modes
    from reception_crm.core.registry import default_registry

    assert "daily-summary" in modes.REPORT.tools
    assert "financial-analysis" not in modes.REPORT.tools, (
        "Report mode stays retrieval-only — see test_modes.py"
    )
    text = default_registry().get("daily-summary").description
    assert "financial.patient_debt" in text
    assert "بدهکارند" in text, "the owner's own word must be on the tool that answers it"
