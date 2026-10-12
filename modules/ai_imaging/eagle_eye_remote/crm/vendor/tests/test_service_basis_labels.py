"""The report tools must say which revenue basis their money figures are on.

⚠️ WHY THIS FILE EXISTS. `financial-analysis` used to label its `patient_debt`
field, in Persian, inside the payload the model reads:

    «patient_debt» همان مانده‌بدهی واقعی بیماران است ... برای پرسش «بیمارها چقدر
    بدهکارند» همین عدد پاسخ است.

— the real patient balance, and the answer to that question. Both halves were
false. The reception app's summary is on the SERVICE basis throughout, and
consumables billed on the reception are in none of it. On 1405/06/02 the field
read 439,530,000 while patients actually owed 705,450,000, measured as
Σ patientTotal − Σ paidAmount over the same 220 receptions in Mongo.

Seven of seventy benchmark answers repeated the short figure, and none of them
was a reasoning failure: a field that states its own meaning is believed, and it
was stating the wrong one. Correcting the metric registry alone did not fix
them, because these tools were read directly. The label is part of the contract.
"""

from __future__ import annotations

import inspect

from reception_crm import finance, management

# The claim that was wrong, in the form it was written.
RETIRED_CLAIM = "مانده‌بدهی واقعی بیماران"


def _source(func) -> str:
    """The function's source WITHOUT its comments.

    The comments quote the retired claim verbatim, which is the point of them —
    a correction that does not say what it corrected teaches nobody. What must
    not contain the claim is the payload the model reads, so the comments are
    stripped before the check rather than the explanation being removed.
    """
    return "\n".join(
        line for line in inspect.getsource(func).splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_service_basis_debt_field_no_longer_claims_to_be_the_whole_debt():
    text = _source(management.financial_analysis)
    assert RETIRED_CLAIM not in text, (
        "financial-analysis is again telling the model that the service-basis "
        "figure is the real patient balance; it is short by the consumables"
    )


def test_the_service_basis_debt_field_names_the_metric_that_carries_the_rest():
    text = _source(management.financial_analysis)
    assert "patient_balance_total" in text
    assert '"basis": "service"' in text


def test_the_daily_summary_financial_block_declares_its_basis():
    """`daily-summary.financial.total_amount` is service value, and answers have
    called it «ارزش پذیرش‌ها». The two differ by the consumables, which is also
    why this tool and `risk-analysis` looked like they disagreed about the same
    day when they were simply on different bases."""
    text = _source(management.daily_summary)
    assert '"basis": "service"' in text
    assert "reception_total_value" in text
    assert "patient_balance_total" in text


def test_the_metric_the_labels_point_at_actually_exists():
    """A label naming a metric nobody registered would send the model to a
    refusal, which is worse than the wrong number it replaced."""
    total = finance.get("patient_balance_total")
    assert total.name == "patient_balance_total"
    assert total.components, "it has to be derivable, or the pointer is a dead end"


def test_the_two_bases_differ_by_the_consumables_in_the_worked_example():
    """The number that makes the whole correction concrete: 265,920,000 of
    705,450,000, a little under 40% of the day's outstanding balance."""
    service = finance.get("patient_balance").example_1405_06_02
    whole = finance.get("patient_balance_total").example_1405_06_02
    consumables = finance.get("consumables_value").example_1405_06_02
    discount = finance.get("discount_amount").example_1405_06_02
    assert whole - service == consumables - discount == 265_920_000
