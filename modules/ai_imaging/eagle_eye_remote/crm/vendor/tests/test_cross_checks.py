"""Comparing one source against another, arithmetically.

This exists because "did you notice these two figures disagree?" is a question
a model answers correctly most of the time. A miss is silent — the answer
simply does not mention it, and reads as though everything agreed.

The dangerous failure here is the opposite one. A cross-checker that compares
two quantities which merely SOUND the same reports a confident daily
inconsistency that does not exist, and people act on it. So most of these tests
are about what is deliberately NOT compared.
"""

from __future__ import annotations

from reception_crm.core import sources


def ev(tool: str, data: dict, ok: bool = True, **arguments) -> dict:
    return {"tool": tool, "arguments": arguments, "ok": ok, "data": data, "error": None}


def period(day: str = "1405/06/01") -> dict:
    return {"start_date": day, "end_date": day, "label": day}


def summary(day="1405/06/01", **financial) -> dict:
    base = {
        "total_amount": 1000, "patient_share": 900, "insurance_share": 100,
        "paid_amount": 500, "patient_debt": 500, "cash_desk_discount": 0,
        "cash": 40, "card": 460,
    }
    base.update(financial)
    return {
        "skill": "daily-summary",
        "period": period(day),
        "admissions": {"total_receptions": 96, "unique_patients": 95, "total_services": 111},
        "financial": base,
    }


def cashier(day="1405/06/01", cash=40, card=460) -> dict:
    return {
        "skill": "cashier-report",
        "period": period(day),
        "payment_details": {"totalCashPayments": cash, "totalCardPayments": card},
        "totals": {"transactions": 108},
    }


# --------------------------------------------------------------------------- #
# what it catches
# --------------------------------------------------------------------------- #
def test_two_sources_that_agree_are_reported_as_agreeing():
    """The passing half matters. "We compared these and they agree" is what
    nobody reports, and its absence is what makes a silent miss invisible."""
    findings = sources.compare([ev("daily-summary", summary()), ev("cashier-report", cashier())])

    cash = [f for f in findings if f["quantity"] == sources.MEANING_FA[sources.CASH]]
    assert cash and cash[0]["agrees"] is True


def test_a_real_disagreement_is_caught_with_its_size():
    """The live case: the daily summary reported cash as 0 while the cashier
    report showed 43,710,000 across five transactions."""
    findings = sources.compare([
        ev("daily-summary", summary(cash=0)),
        ev("cashier-report", cashier(cash=43_710_000)),
    ])

    cash = next(f for f in findings if f["quantity"] == sources.MEANING_FA[sources.CASH])
    assert cash["agrees"] is False
    assert abs(cash["difference"]) == 43_710_000
    assert cash["left"]["tool"] == "daily-summary"
    assert cash["because_fa"]


def test_a_subset_relation_is_not_an_equality():
    """Patients attributed to a reporting physician are FEWER than the day's
    patients — 30 against 96 on a normal day. Asserting equality would report a
    mismatch every single day, and a checker that cries wolf daily is a checker
    nobody reads."""
    physicians = {"skill": "physician-performance", "period": period(), "totals": {"patients": 30}}
    findings = sources.compare([ev("physician-performance", physicians), ev("daily-summary", summary())])

    rel = next(f for f in findings if f["relation"] == sources.AT_MOST)
    assert rel["agrees"] is True, "30 attributed patients out of 95 is normal, not a mismatch"


def test_the_subset_relation_still_catches_the_impossible():
    physicians = {"skill": "physician-performance", "period": period(), "totals": {"patients": 400}}
    findings = sources.compare([ev("physician-performance", physicians), ev("daily-summary", summary())])

    rel = next(f for f in findings if f["relation"] == sources.AT_MOST)
    assert rel["agrees"] is False


# --------------------------------------------------------------------------- #
# what it refuses to compare — the more important half
# --------------------------------------------------------------------------- #
def test_payments_are_not_compared_against_procedures():
    """The cashier report's `transactions` (108) and the daily summary's
    `total_services` (111) are both "counts of things that happened today", and
    an automatic field-name mapping paired them. A transaction is a PAYMENT and
    a service is a PROCEDURE. Asserting they should be equal would invent a
    daily discrepancy of three."""
    findings = sources.compare([ev("daily-summary", summary()), ev("cashier-report", cashier())])

    quantities = {f["quantity"] for f in findings}
    assert sources.MEANING_FA[sources.SERVICE_COUNT] not in quantities


def test_two_different_days_are_never_compared():
    """Yesterday's cashier report against today's summary would disagree about
    everything, correctly, and mean nothing."""
    findings = sources.compare([
        ev("daily-summary", summary(day="1405/06/01")),
        ev("cashier-report", cashier(day="1405/05/31")),
    ])
    assert findings == []


def test_a_failed_source_is_not_compared():
    findings = sources.compare([
        ev("daily-summary", summary()),
        ev("cashier-report", cashier(), ok=False),
    ])
    assert all(f["left"]["tool"] != "cashier-report" and f["right"]["tool"] != "cashier-report"
               for f in findings)


def test_a_missing_field_is_not_a_finding():
    """An absent comparison must never be reported as a passed one — that is
    the same defect as an empty "no problems" heading."""
    findings = sources.compare([
        ev("daily-summary", {"skill": "daily-summary", "period": period(), "financial": {}}),
        ev("cashier-report", cashier()),
    ])
    assert findings == []


def test_one_source_alone_produces_nothing():
    assert sources.compare([ev("daily-summary", summary())]) == []


def test_malformed_evidence_does_not_raise():
    for bad in ([], [{"tool": "daily-summary"}], [{"tool": "x", "ok": True, "data": "not a dict"}]):
        assert sources.compare(bad) == []


# --------------------------------------------------------------------------- #
# how it reaches the model
# --------------------------------------------------------------------------- #
def test_the_verdicts_are_stated_as_settled():
    """Handed to the model as results, not as evidence to re-weigh. A model
    given two payloads and a conclusion tends to recompute the conclusion, and
    occasionally disagrees with itself in the same answer."""
    findings = sources.compare([
        ev("daily-summary", summary(cash=0)),
        ev("cashier-report", cashier(cash=43_710_000)),
    ])
    block = sources.format_comparisons(findings)

    assert "سرور" in block
    assert "43,710,000" in block
    assert "✘" in block


def test_agreement_is_rendered_too():
    findings = sources.compare([ev("daily-summary", summary()), ev("cashier-report", cashier())])
    block = sources.format_comparisons(findings)
    assert "✔" in block


def test_nothing_to_compare_produces_no_block():
    """An empty heading reads as "we checked and found nothing"."""
    assert sources.format_comparisons([]) == ""


# --------------------------------------------------------------------------- #
# the catalog itself
# --------------------------------------------------------------------------- #
def test_the_server_plans_its_own_corroboration():
    """The catalog knows `cashier-report` and `daily-summary` both report the
    day's cash. Discovering that costs an LLM round; reading it costs nothing."""
    plan = sources.plan_corroboration(
        ["cashier-report"],
        available={"cashier-report", "daily-summary", "patient-list"},
        arguments={"date": "today", "data_root": "D:/x"},
    )
    tools = [t for t, _, _ in plan]
    assert "daily-summary" in tools


def test_corroboration_carries_the_period_and_nothing_else():
    """A corroborating source fetched for a different day is refused by
    `compare()` — correctly, and silently, which would look like a check that
    simply had nothing to say."""
    plan = sources.plan_corroboration(
        ["cashier-report"],
        available={"cashier-report", "daily-summary"},
        arguments={"date": "yesterday", "days": 1, "data_root": "D:/x", "modality": "CT"},
    )
    _, args, why = plan[0]
    assert args == {"date": "yesterday", "days": 1}
    assert "data_root" not in args
    assert why


def test_nothing_is_planned_when_the_pair_is_already_complete():
    plan = sources.plan_corroboration(
        ["cashier-report", "daily-summary"],
        available={"cashier-report", "daily-summary"},
    )
    assert [t for t, _, _ in plan if t in ("cashier-report", "daily-summary")] == []


def test_corroboration_never_names_a_tool_this_mode_cannot_call():
    """Planning a fetch the mode would refuse produces a plan that looks
    thorough and quietly does less."""
    plan = sources.plan_corroboration(
        ["cashier-report"],
        available={"cashier-report"},
    )
    assert plan == []


def test_corroboration_is_bounded():
    plan = sources.plan_corroboration(
        ["daily-summary"],
        available={"daily-summary", "cashier-report", "financial-analysis", "patient-list",
                   "physician-performance"},
        limit=1,
    )
    assert len(plan) == 1


def test_no_corroboration_without_something_to_corroborate():
    assert sources.plan_corroboration([], available={"daily-summary"}) == []


def test_every_comparison_names_tools_the_catalog_knows():
    for check in sources.COMPARISONS:
        assert sources.known(check.left), f"{check.left} is not in the catalog"
        assert sources.known(check.right), f"{check.right} is not in the catalog"


def test_every_comparison_has_a_field_path_on_both_sides():
    """A comparison whose field path is missing never fires, and would sit in
    the table looking like a check that passes."""
    for check in sources.COMPARISONS:
        assert sources.FIELD_PATHS.get(check.left, {}).get(check.meaning), \
            f"{check.left} has no path for {check.meaning}"
        assert sources.FIELD_PATHS.get(check.right, {}).get(check.right_key), \
            f"{check.right} has no path for {check.right_key}"


def test_every_comparison_explains_why_the_two_should_agree():
    """"These two numbers differ" is only useful with "and here is why that is
    odd"."""
    for check in sources.COMPARISONS:
        assert check.because_fa, f"{check.meaning} between {check.left}/{check.right} has no reason"
