"""The financial lexicon: every metric pinned to a meaning, a source and a basis.

The premise: a financial answer is only as good as the question the number
answers. Every money error in this project has been a NAMING error — a plausible
field picked out of a report already in hand — never an arithmetic one. So the
lexicon is data the agent can reach at query time, and these tests hold it to
the standard that makes it worth reaching.
"""

from __future__ import annotations

import dataclasses

import pytest

from reception_crm import finance
from reception_crm.core.registry import default_registry
from reception_crm.core.tools import finance as finance_tool


def _patch_source(monkeypatch, tool_name, **changes):
    """Swap one source tool for a modified copy, for the duration of a test.

    `ToolDefinition` is a frozen dataclass — deliberately, since a tool's safety
    level is exactly the kind of thing that should not be mutable at runtime. So
    the test builds a replacement and patches the REGISTRY LOOKUP rather than
    reaching into the definition.
    """
    import dataclasses

    from reception_crm.core import registry as registry_module

    real = registry_module.default_registry()
    replacement = dataclasses.replace(real.get(tool_name), **changes)

    class _Patched:
        def get(self, name):
            return replacement if name == tool_name else real.get(name)

    monkeypatch.setattr(registry_module, "default_registry", lambda: _Patched())


# ------------------------------------------------------------ shape of the catalogue

def test_every_metric_declares_a_date_basis():
    """There is no sensible default. «صندوق دیروز» and «پذیرش دیروز» pick
    different bases from the same word 'yesterday'."""
    for metric in finance.METRICS:
        assert metric.date_basis in (finance.RECEPTION_DATE, finance.TRANSACTION_DATE)


def test_every_metric_names_a_source_field():
    """A figure whose field path is unknown cannot be checked by anyone, which
    is the condition every financial mistake here was made in."""
    for metric in finance.METRICS:
        assert metric.source_path, f"{metric.name} has no source path"


def test_every_calculated_metric_carries_its_formula():
    for metric in finance.METRICS:
        if metric.calculated:
            assert metric.formula, f"{metric.name} is calculated but states no formula"


def test_every_metric_has_a_persian_label_and_aliases():
    """Staff ask in Persian. A lexicon that only speaks the normalized name
    cannot be reached from the question."""
    for metric in finance.METRICS:
        assert metric.fa
        assert metric.aliases or metric.name


def test_confidence_is_declared_and_honest():
    """`reception_total_value` and `consumables_value` are reached through a
    proxy or not exposed at all. Marking them `high` would hide the gap that is
    the point of recording them."""
    assert finance.get("reception_total_value").confidence == "medium"
    assert finance.get("consumables_value").confidence == "medium"
    assert finance.get("net_cashier_amount").confidence == "high"


# ------------------------------------------------------------------- resolution

@pytest.mark.parametrize("asked,expected", [
    ("net_cashier_amount", "net_cashier_amount"),
    ("خالص صندوق", "net_cashier_amount"),
    # ⚠️ These two moved deliberately. Both used to land on `patient_balance`,
    # which is the reception software's own service-basis figure and leaves
    # consumables out — 439,530,000 where the real outstanding balance was
    # 705,450,000. The unqualified Persian words mean the whole debt.
    ("بدهکارند", "patient_balance_total"),
    ("مانده بیمار", "patient_balance_total"),
    ("مانده بدهی خدمات", "patient_balance"),
    ("سهم بیمار", "patient_liability"),
    ("کارتخوان", "cashier_card_amount"),
    ("دریافتی", "cashier_received_total"),
    ("تخفیف", "discount_amount"),
])
def test_persian_aliases_resolve_to_the_right_metric(asked, expected):
    assert finance.get(asked).name == expected


def test_an_unknown_metric_raises_and_never_guesses():
    """Resolving a financial metric by similarity is exactly how a plausible
    wrong number reaches someone who will act on it."""
    with pytest.raises(finance.UnknownMetric) as exc:
        finance.get("total_money_ish")
    assert "net_cashier_amount" in exc.value.as_dict()["known_metrics"]


def test_asking_for_the_wrong_date_basis_is_refused():
    """`cashier_received_total` on a reception basis is meaningless, and would
    otherwise return a confident number."""
    with pytest.raises(finance.WrongDateBasis) as exc:
        finance.check_basis("cashier_received_total", finance.RECEPTION_DATE)
    detail = exc.value.as_dict()
    assert detail["actual_basis"] == finance.TRANSACTION_DATE
    assert detail["requested_basis"] == finance.RECEPTION_DATE

    with pytest.raises(finance.WrongDateBasis):
        finance.check_basis("service_value", finance.TRANSACTION_DATE)


def test_the_right_basis_passes():
    assert finance.check_basis("net_cashier_amount", finance.TRANSACTION_DATE)
    assert finance.check_basis("patient_balance", finance.RECEPTION_DATE)
    assert finance.check_basis("patient_balance", None), "basis is optional"


# -------------------------------------------------- the confusions that actually happened

def test_patient_balance_warns_about_the_field_that_overstated_it_3x():
    metric = finance.get("patient_balance")
    assert "reception_total_value" in metric.not_to_be_confused_with
    assert "receptionDebt" in metric.notes


def test_the_two_revenue_bases_point_at_each_other():
    service = finance.get("service_value")
    reception = finance.get("reception_total_value")
    assert "reception_total_value" in service.not_to_be_confused_with
    assert "service_value" in reception.not_to_be_confused_with


def test_insurance_liability_is_distinguished_from_the_cashier_posting():
    """One is a reception-dated receivable, the other a transaction-dated posting.

    ⚠️ This test used to assert the two examples were EQUAL, and drew the lesson
    that equal numbers are the most dangerous case rather than the safest. Both
    halves of that were true of a MOMENT, not of the metrics: mid-day on
    1405/06/02 both read 1,038,930,000. By close the insurer was owed
    1,047,270,000 and 1,036,030,000 had actually been posted to the till. The
    gap is the point — it is the part the insurer has not paid yet — and an
    equality baked into a test is how a coincidence becomes a rule.
    """
    liability = finance.get("insurance_liability")
    posting = finance.get("cashier_insurance_credit")
    assert liability.date_basis == finance.RECEPTION_DATE
    assert posting.date_basis == finance.TRANSACTION_DATE
    assert liability.example_1405_06_02 != posting.example_1405_06_02
    assert liability.example_1405_06_02 > posting.example_1405_06_02
    assert "cashier_insurance_credit" in liability.not_to_be_confused_with


def test_the_insurance_share_records_that_per_service_is_unreliable():
    """`services[].org` looks like a per-line insurance share and agrees with the
    header on only 115 of 220 receptions. I nearly wrote it in as a fact."""
    assert "services[].org" in finance.get("insurance_liability").notes


def test_cash_records_that_a_missing_card_field_is_not_cash():
    assert "card" in finance.get("cashier_cash_amount").notes


# ------------------------------------------------------------------- identities

def test_the_identities_are_published_with_their_evidence():
    """Each identity says where it was verified. 'It should hold' is not
    verification; '220/220 receptions, per record' is."""
    ids = finance.identities()
    assert len(ids) >= 6
    for row in ids:
        assert row["identity"] and row["verified"] and row["fa"]
    joined = " ".join(r["identity"] for r in ids)
    assert "service_value + consumables_value = reception_total_value" in joined
    assert "patient_liability − patient_paid_amount = patient_balance" in joined
    assert "− cashier_withdrawal_amount = net_cashier_amount" in joined


def test_the_examples_satisfy_their_own_identities():
    """The catalogue's worked values must actually reconcile — a lexicon whose
    own numbers do not add up teaches the wrong thing with authority."""
    g = lambda n: finance.get(n).example_1405_06_02  # noqa: E731
    assert g("service_value") + g("consumables_value") == g("reception_total_value")
    assert g("patient_liability") - g("patient_paid_amount") == g("patient_balance")
    assert g("settled_count") + g("unsettled_count") == g("reception_count")
    assert (g("cashier_cash_amount") + g("cashier_card_amount")
            + g("cashier_insurance_credit") == g("cashier_received_total"))
    assert (g("cashier_cash_amount") + g("cashier_card_amount")
            - g("cashier_withdrawal_amount") == g("net_cashier_amount"))


def test_patients_receptions_services_stay_three_numbers():
    assert (finance.get("patient_count").example_1405_06_02
            < finance.get("reception_count").example_1405_06_02
            < finance.get("service_count").example_1405_06_02)


# ----------------------------------------------------------------------- the tools

def test_both_finance_tools_are_registered_and_on_the_money_menus():
    from reception_crm.core import modes

    names = {str(t.get("name")) for t in default_registry().list()}
    assert {"finance.metric", "finance.vocabulary"} <= names
    for mode in (modes.REPORT, modes.ANALYSIS):
        assert "finance.metric" in mode.tools
        assert "finance.vocabulary" in mode.tools


def test_vocabulary_returns_the_whole_catalogue_with_identities():
    out = finance_tool._vocabulary({})
    assert len(out["metrics"]) == len(finance.METRICS)
    assert out["identities"]
    assert set(out["date_bases"]) == {finance.RECEPTION_DATE, finance.TRANSACTION_DATE}


def test_vocabulary_can_explain_one_metric_by_persian_alias():
    out = finance_tool._vocabulary({"metric": "خالص صندوق"})
    assert out["metric"]["metric"] == "net_cashier_amount"
    assert out["metric"]["formula"]


def test_metric_refuses_an_unknown_name_without_calling_a_source():
    out = finance_tool._metric({"metric": "vibes"})
    assert out["value"] is None
    assert out["error"]["code"] == "UNKNOWN_METRIC"


def test_metric_refuses_a_mismatched_basis_without_calling_a_source():
    out = finance_tool._metric({"metric": "service_value",
                                "dateBasis": finance.TRANSACTION_DATE})
    assert out["value"] is None
    assert out["error"]["code"] == "WRONG_DATE_BASIS"


def test_a_metric_with_no_tool_says_so_instead_of_returning_nothing(monkeypatch):
    """A metric nothing exposes must SAY so. Silence would read as zero.

    ⚠️ This test used to use `consumables_value` as its specimen, and that
    stopped being true when the metric gained a derivation — the assertion
    then failed for the right reason. It is kept, with a synthetic specimen,
    because not every future gap will have a derivation available and the
    refusal is the honest floor underneath the whole tool.
    """
    orphan = dataclasses.replace(finance.get("consumables_value"),
                                 name="orphan_metric", components=())
    monkeypatch.setattr(finance, "get", lambda key: orphan)
    out = finance_tool._metric({"metric": "orphan_metric"})
    assert out["value"] is None
    assert out["error"]["code"] == "NO_SOURCE_TOOL"
    assert out["metric"]["formula"]


def test_the_prompt_rendering_states_the_date_basis_rule():
    text = finance.describe_for_prompt()
    assert "transaction-dated" in text and "reception-dated" in text
    assert "net_cashier_amount" in text


def test_the_inner_dispatch_supplies_data_root(monkeypatch):
    """Every metric came back `VALIDATION: Missing required input(s): data_root`.

    The report tools require it and the HTTP adapter injects it on the way in;
    dispatching from inside a tool skips that layer. What made it dangerous is
    that the failure looked identical to the three DELIBERATE refusals beside
    it — a real break wearing the costume of a designed one. So the happy path
    gets its own test rather than being inferred from the refusals passing.
    """
    seen: dict = {}

    def fake_handler(args):
        seen["args"] = args
        return {"financial": {"patient_debt": 123}, "period": {"from": "x"}}

    _patch_source(monkeypatch, "daily-summary", handler=fake_handler)

    out = finance_tool._metric({"metric": "patient_balance", "date": "1405/06/02"})
    assert seen["args"].get("data_root"), "the inner call must carry a data_root"
    assert seen["args"].get("date") == "1405/06/02"
    assert out["value"] == 123
    assert out["traceable_to"]["path"] == "financial.patient_debt"
    assert out["traceable_to"]["date_basis"] == finance.RECEPTION_DATE


def test_a_null_value_is_labelled_as_not_reported_not_zero(monkeypatch):
    """An absent field is 'the source did not report this', which is a different
    answer from 'it was zero' and must not be rendered as one."""
    _patch_source(monkeypatch, "daily-summary", handler=lambda args: {"financial": {}})

    out = finance_tool._metric({"metric": "patient_balance", "date": "today"})
    assert out["value"] is None
    assert "not 'zero'" in out["value_is_null_means"]


def test_the_facade_can_only_ever_reach_read_tools():
    """Calling the source handler directly skips the inner permission check, so
    the escalation is closed here instead: a facade that could reach a write
    tool would be a way around the confirmation gate."""
    from reception_crm.core.registry import default_registry

    registry = default_registry()
    for metric in finance.METRICS:
        if not metric.source_tool:
            continue
        source = registry.get(metric.source_tool)
        assert source.safety == "read", f"{metric.name} points at a non-read tool"
        assert source.permission_action == "read"


def test_a_non_read_source_is_refused_at_runtime_too(monkeypatch):
    """Not only asserted over today's catalogue — refused in the code path, so a
    later change to a source tool cannot quietly open the door."""
    _patch_source(monkeypatch, "daily-summary", safety="write")
    out = finance_tool._metric({"metric": "patient_balance", "date": "today"})
    assert out["value"] is None
    assert out["error"]["code"] == "NOT_A_READ_SOURCE"


# ------------------------------------------- what the source code corrected

def test_per_service_insurance_is_recorded_as_usable_with_its_guard():
    """A correction to something I published as a finding.

    I reported `services[].org` as unusable — 115 of 220. Reading the reception
    app's own `AddedServicesSummary.jsx` showed why: `org` is the **Salamat**
    share, selected only when `service.Salamat` is set. Summed across all lines
    it is meaningless; filtered by its flag it reconciles 220 of 220, as do
    `ST` for Tamin and `SA` for Army.

    **A field read without its guard condition looks broken.** The lexicon now
    carries the guard, not the accusation.
    """
    notes = finance.get("insurance_liability").notes
    assert "service.Salamat" in notes and "service.Tamin" in notes and "service.Army" in notes
    assert "SALAMAT share specifically" in notes
    assert "220 of 220" in notes


def test_the_per_service_identities_are_published_with_their_guards():
    joined = " ".join(row["identity"] for row in finance.identities())
    assert "services[Tamin].ST" in joined
    assert "services[Salamat].(org || SS)" in joined
    assert "services[Army].SA" in joined


def test_the_lexicon_records_that_reception_money_is_computed_in_the_browser():
    """§4 of the audit brief — and it changes what a recomputation can prove.

    The arithmetic is not in the database or the API: the reception app does it
    client-side and POSTs the result. Every stage floors to 10,000, so a
    single-expression recomputation disagreeing by 10,000 is expected, not a
    defect to chase.
    """
    sites = finance.CALCULATION_SITES
    assert any("FRONTEND" in v for v in sites.values())
    assert any("AddedServicesSummary" in v for v in sites.values())
    assert "browser" in finance.get("patient_liability").notes.lower()
    assert "floor" in finance.get("patient_liability").formula.lower()


def test_the_vendors_own_cash_reconciliation_is_recorded_before_we_build_one():
    """The reception software already captures a physical cash count
    («ثبت واقعیت صندوق»). Building a parallel reconciliation on top of a system
    that has one would produce a second set of figures that can disagree with
    the screen the clinic trusts — and the clinic would be right."""
    endpoints = finance.CASHDESK_ANALYSIS_ENDPOINTS
    assert any("reality" in e for e in endpoints)
    assert any("refunds" in e for e in endpoints)
    assert len(endpoints) >= 8


# ------------------------------------------------------- the two patient bases

def test_the_unqualified_debt_question_reaches_the_reception_basis_metric():
    """«بیمارها چقدر بدهکار موندن؟» must not resolve to the service-basis figure.

    ⚠️ This is the defect the v3 challenge benchmark found, and it was invisible
    to every check that compared numbers: `patient_balance` returned
    439,530,000, which is genuinely what the reception software reports, and is
    genuinely NOT what the question asks. The software's summary works on the
    service basis throughout and leaves consumables out; the real outstanding
    balance on 1405/06/02 was 705,450,000. Seven of the seventy answers carried
    the short figure.
    """
    for word in ("بدهی", "بدهکارند", "چقدر بدهکار", "outstanding", "patient debt"):
        assert finance.get(word).name == "patient_balance_total", (
            f"{word!r} resolves to {finance.get(word).name}, which is not the "
            "complete balance"
        )


def test_the_service_basis_balance_is_still_addressable_by_name():
    """Correcting the default must not delete the other figure. The vendor's
    screens show it, and an answer comparing against those screens needs it."""
    service_basis = finance.get("patient_balance")
    assert service_basis.name == "patient_balance"
    assert service_basis.source_tool == "daily-summary"
    assert service_basis.source_path == "financial.patient_debt"


def test_both_patient_balances_warn_about_each_other():
    total = finance.get("patient_balance_total")
    service = finance.get("patient_balance")
    assert "patient_balance" in total.not_to_be_confused_with
    assert "patient_balance_total" in service.not_to_be_confused_with


def test_the_worked_example_reproduces_the_measured_balance():
    """439,530,000 + 267,650,000 − 1,730,000 = 705,450,000, all four measured
    independently in Mongo over the 220 live receptions of 1405/06/02."""
    parts = {name: finance.get(name).example_1405_06_02
             for name, _ in finance.get("patient_balance_total").components}
    signs = dict(finance.get("patient_balance_total").components)
    assert sum(signs[name] * value for name, value in parts.items()) == \
        finance.get("patient_balance_total").example_1405_06_02


def test_consumables_are_the_whole_gap_between_the_two_bases():
    assert (finance.get("service_value").example_1405_06_02
            + finance.get("consumables_value").example_1405_06_02
            == 7_101_550_000)


# --------------------------------------------------------- derived metrics work

def test_a_component_metric_declares_components_that_all_exist():
    for metric in finance.METRICS:
        for name, sign in metric.components:
            assert sign in (1, -1), f"{metric.name} gives {name} a sign of {sign}"
            assert finance.get(name), f"{metric.name} names an unknown component {name}"


def test_a_derived_metric_sums_its_components_with_their_signs(monkeypatch):
    """The derivation is arithmetic over other metrics, not a second source."""
    calls: list[str] = []

    def fake(args, _depth=0):
        calls.append(args["metric"])
        canned = {
            "patient_balance": 439_530_000,
            "consumables_value": 267_650_000,
            "discount_amount": 1_730_000,
        }
        return {"skill": "finance.metric", "value": canned[args["metric"]],
                "traceable_to": {"tool": "stub"}}

    spec = finance.get("patient_balance_total")
    monkeypatch.setattr(finance_tool, "_metric", fake)
    result = finance_tool._derive(spec, {"date": "1405/06/02"}, 0)

    assert result["value"] == 705_450_000
    assert calls == ["patient_balance", "consumables_value", "discount_amount"]
    assert [p["sign"] for p in result["derived_from"]] == [1, 1, -1]


def test_a_derivation_refuses_rather_than_returning_a_partial_sum(monkeypatch):
    """⚠️ The single most important behaviour here. A derived figure missing one
    component is short by exactly that component and looks complete — which is
    the failure `patient_balance_total` exists to correct, reproduced one level
    up. It must return no number at all."""
    def fake(args, _depth=0):
        if args["metric"] == "consumables_value":
            return {"skill": "finance.metric", "value": None,
                    "error": {"code": "SOURCE_FAILED", "message": "boom"}}
        return {"skill": "finance.metric", "value": 439_530_000}

    monkeypatch.setattr(finance_tool, "_metric", fake)
    result = finance_tool._derive(finance.get("patient_balance_total"),
                                  {"date": "1405/06/02"}, 0)
    assert result["value"] is None
    assert result["error"]["code"] == "COMPONENT_UNAVAILABLE"
    assert "consumables_value" in result["error"]["message"]


def test_a_derivation_stops_before_the_stack_does(monkeypatch):
    """A future component cycle must refuse, not crash. To the caller a crash
    and a refusal look the same; only one of them says why."""
    result = finance_tool._derive(finance.get("patient_balance_total"),
                                  {"date": "1405/06/02"},
                                  finance_tool._MAX_DERIVATION_DEPTH)
    assert result["value"] is None
    assert result["error"]["code"] == "DERIVATION_TOO_DEEP"


def test_a_derivation_passes_the_caller_period_to_every_component(monkeypatch):
    """Two components resolved over different date windows would produce a
    figure belonging to no day at all."""
    seen: list[dict] = []

    def fake(args, _depth=0):
        seen.append(dict(args))
        return {"skill": "finance.metric", "value": 1}

    monkeypatch.setattr(finance_tool, "_metric", fake)
    finance_tool._derive(finance.get("patient_balance_total"),
                         {"date": "1405/06/02", "data_root": "/tmp/x"}, 0)
    assert all(a["date"] == "1405/06/02" for a in seen)
    assert all(a["data_root"] == "/tmp/x" for a in seen)


def test_the_reception_basis_identity_is_recorded():
    """An identity nobody can look up is a fact that lives only in a commit
    message."""
    text = " ".join(i["identity"] for i in finance.identities())
    assert "patient_balance_total" in text
    assert "consumables_value" in text
