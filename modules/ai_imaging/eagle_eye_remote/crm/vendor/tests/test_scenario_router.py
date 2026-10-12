"""Classification, and the two bugs that made it worth testing this closely.

The corpus is the owner's own words — the scenario trigger examples and the
twenty benchmark questions. Paraphrasing either would be marking my own
homework, so both are used verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm import scenarios
from reception_crm.core import scenario_router as router

IN_CASE = {"patient national code": "<withheld>"}


# --------------------------------------------------------------------------- #
# the owner's own examples
# --------------------------------------------------------------------------- #
def _triggers():
    for scenario in scenarios.all_scenarios():
        for trigger in scenario.triggers_fa:
            yield scenario.id, trigger


@pytest.mark.parametrize("expected,question", list(_triggers()))
def test_the_owners_examples_route_where_he_filed_them(expected, question):
    """Every example in the spec, classified as the section it is listed under.

    The PATIENT examples are given context, because the spec introduces them as
    turn two of an open case — «چقدر پرداخت کرده؟» asked cold really is a
    question about the centre's takings.
    """
    facts = IN_CASE if expected == "patient" else None
    match = router.classify(question, facts)
    assert match.scenario == expected, (
        f"{question!r} → {match.scenario} (evidence: {list(match.evidence)})"
    )


def test_every_benchmark_question_classifies_without_error():
    """Coverage, not correctness: these have no scenario label to be right about.

    What is asserted is that nothing raises and nothing lands outside the
    registry — a router that throws on a real question would fail the question,
    and this one runs on every one of them.
    """
    spec = json.loads(
        (Path(__file__).resolve().parents[1] / "benchmark" / "persian_v1.json")
        .read_text(encoding="utf-8")
    )
    questions = spec["questions"] if isinstance(spec, dict) and "questions" in spec else spec
    for question in questions:
        text = question.get("question") or question.get("prompt") or question.get("text")
        match = router.classify(text)
        assert scenarios.is_known(match.scenario)
        assert 0.0 <= match.confidence <= 1.0


# --------------------------------------------------------------------------- #
# the two bugs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("particle", ["رو", "تا", "هر", "کن", "با", "که"])
def test_persian_particles_are_not_clinical_terms(particle):
    """Both bugs, as one assertion, in the place they actually bit.

    The lexicon matches LOOSELY by design — it is answering "what did they
    probably mean". Asked "did they name a service at all", loose matching made
    «تا», «هر» and «کن» into radiology service groups, and «رو» into a disabled
    modality that slipped past the exactness check because `DisabledValue`
    carries no exactness flag.

    A clinical hit is the heaviest signal the router has, so each of these
    turned unrelated questions into service questions: «گزارش صندوق دیروز رو
    بده» was classified as marketing.
    """
    assert router.find_clinical_terms(f"گزارش صندوق دیروز {particle} بده") == ()


@pytest.mark.parametrize("term", ["MRI", "CT", "سونوگرافی", "رادیولوژی", "ماموگرافی"])
def test_real_modality_names_are_found(term):
    assert router.find_clinical_terms(f"چند تا {term} داشتیم؟")


def test_a_disabled_modality_still_counts_as_naming_a_service():
    """«ماموگرافی» is `status: disabled` at this centre — and still a service.

    Whether the data can answer it is the tool's problem, and the lexicon
    already refuses loudly. Swallowing the term in the router would classify
    the question as if the word had never been said.
    """
    assert "ماموگرافی" in " ".join(router.find_clinical_terms("امروز چند تا ماموگرافی داشتیم؟"))


def test_no_term_belongs_to_two_scenarios():
    """A duplicated term is a silent winner, not a tie.

    Terms are matched longest-first and the match CONSUMES the span, so at equal
    length whichever scenario is declared first takes the word outright and the
    other entry never fires. «بیمه» sat in `financial` at weight 1 and in
    `insurance` at weight 3, and financial won every time purely by declaration
    order — a table that reads as a considered weighting and is not one.
    """
    owners: dict[str, list[str]] = {}
    for scenario_id, terms in router._TERMS.items():
        for term, _weight in terms:
            owners.setdefault(term, []).append(scenario_id)
    duplicated = {t: s for t, s in owners.items() if len(s) > 1}
    assert not duplicated, f"terms claimed by more than one scenario: {duplicated}"


@pytest.mark.parametrize(
    "question,expected",
    [
        ("نوبت‌های امروز چند تاست؟", "appointment"),
        ("ظرفیت خالی فردا چقدره؟", "appointment"),
        ("چند تا مطالعه هنوز گزارش نشده؟", "reporting"),
        ("وضعیت جواب‌دهی امروز چطوره؟", "reporting"),
        ("سهم بیمه امروز چقدر بود؟", "insurance"),
        ("بیمه تکمیلی چقدر پرداخت کرده؟", "insurance"),
        ("موجودی انبار چقدره؟", "inventory"),
        ("چه کالایی امروز مصرف شده؟", "inventory"),
        ("مرجوعی‌های امروز چقدر بوده؟", "financial"),
        ("کیف پول بیمارها چقدر موجودی دارد؟", "financial"),
    ],
)
def test_the_new_domains_route(question, expected):
    match = router.classify(question)
    assert match.scenario == expected, (
        f"{question!r} → {match.scenario} (evidence: {list(match.evidence)})"
    )


def test_a_bare_report_word_does_not_mean_the_reporting_scenario():
    """«گزارش» alone is the most overloaded word in this system.

    «گزارش صندوق» is financial, «گزارش‌های این بیمار» is a case investigation,
    and only the report LIFECYCLE phrases belong to `reporting`. A bare «گزارش»
    term would have taken all three.
    """
    assert router.classify("گزارش صندوق دیروز رو بده.").scenario == "financial"
    assert router.classify("گزارش‌های این بیمار چی بوده؟").scenario == "patient"


def test_a_bare_number_is_not_an_identifier():
    """«چند تا MRI 3 تسلا» and «۵ روز گذشته» carry digits and name nobody.

    Reading either as a patient would route a centre question into a
    single-case pipeline, which is the one misrouting that can put one person's
    row where a total belongs.
    """
    assert router.find_identifiers("چند تا MRI 3 تسلا داشتیم؟") == {}
    assert router.find_identifiers("۵ روز گذشته چند پذیرش داشتیم؟") == {}


# --------------------------------------------------------------------------- #
# identifiers, referents, switching
# --------------------------------------------------------------------------- #
def test_a_reception_code_settles_it_outright():
    match = router.classify("بیمار با کد پذیرش 12345 رو بررسی کن.")
    assert match.scenario == "patient"
    assert match.method == "identifier"
    assert match.confidence >= 0.9


def test_a_national_code_is_recognised():
    assert "national_code" in router.find_identifiers("کد ملی 0012345678 رو نگاه کن")


def test_the_identifier_value_is_never_published():
    """The envelope is logged. The SHAPE of the evidence belongs there; the
    value identifies a person and does not."""
    match = router.classify("کد ملی 0012345678 رو نگاه کن")
    published = json.dumps(match.as_dict(), ensure_ascii=False)
    assert "0012345678" not in published
    assert match.as_dict()["identifierKinds"] == ["national_code"]


def test_a_bare_column_request_is_not_a_case_investigation():
    """«لیست بیمارانی که تخفیف گرفتن رو با کد پذیرششون بهم بده» wants a COLUMN.

    «کد پذیرش» with no digits after it names a field people want listed, not a
    case to open — which is why it is an identifier pattern and not a keyword.
    """
    match = router.classify("لیست بیمارانی که تخفیف گرفتن رو با کد پذیرششون بهم بده.")
    assert match.scenario == "financial"


def test_an_open_case_carries_to_an_undated_follow_up():
    """§17. «چقدر پرداخت کرده؟» in an open case is about that person."""
    assert router.classify("چقدر پرداخت کرده؟", IN_CASE).scenario == "patient"
    assert router.classify("چقدر پرداخت کرده؟").scenario != "patient"


def test_an_open_case_does_not_lock_the_conversation():
    """§12. Changing the subject has to change the pipeline.

    A carried referent is evidence, not a lock — otherwise one patient lookup
    would answer every later question as if it were about that patient.
    """
    assert router.classify("صندوق امروز چه‌جوری بود؟", IN_CASE).scenario == "financial"
    assert router.classify("کدوم خدمت رشد داشته؟", IN_CASE).scenario == "marketing"


def test_a_specific_compound_beats_the_generic_word_inside_it():
    """«صندوق‌دار» is staff; «صندوق» is money; the first contains the second.

    Specificity wins by consuming the span, not by a special case — and the
    ZWNJ in «صندوق‌دار» folds to a space, which is why both spellings are in the
    table. With only the joined spelling, every one of the owner's cashier-staff
    questions scored as financial.
    """
    assert router.classify("صندوق‌دارها امروز چجوری کار کردن؟").scenario == "staff"
    assert router.classify("صندوق امروز چه‌جوری بود؟").scenario == "financial"


# --------------------------------------------------------------------------- #
# multi-scenario and the fallback
# --------------------------------------------------------------------------- #
def test_a_two_part_question_reports_both_halves():
    """The property is that BOTH halves are named, not which two they are.

    ⚠️ The pair changed when `audit` was added, and the change is the point.
    «کدوم کارمند بیشترین تخفیف رو داده و آیا این تخفیف‌ها غیرطبیعی بوده؟» asks
    who did it and whether it was abnormal. Before, the second half had nowhere
    to go and landed on `financial` — the scenario that owns the discount, which
    is the OBJECT of the question rather than the question. Now «غیرطبیعی» has a
    scenario of its own, and the two halves are the person and the integrity
    concern. `financial` is still scored and still visible in the evidence; it
    is simply no longer standing in for something it was never about.
    """
    match = router.classify(
        "کدوم کارمند بیشترین تخفیف رو داده و آیا این تخفیف‌ها غیرطبیعی بوده؟"
    )
    assert {match.scenario, match.secondary} == {"staff", "audit"}
    assert "financial" in match.scores, "the discount half must still be scored"


def test_an_unrecognisable_question_falls_to_general():
    match = router.classify("سلام حالت چطوره؟")
    assert match.scenario == scenarios.FALLBACK_SCENARIO


def test_empty_text_does_not_raise():
    assert router.classify("").scenario == scenarios.FALLBACK_SCENARIO


@pytest.mark.parametrize(
    "question",
    ["سلام حالت چطوره؟", "یک چیز کاملاً نامفهوم", "اوضاع صندوق دیروز چه‌جوری بود؟"],
)
def test_no_model_is_reachable_without_a_chat(question):
    """Shadow mode's cost guarantee.

    The router runs on every live question. If it could reach a model on its
    own it would add a round trip to all of them, and the orchestrator passes
    `chat=None` precisely so it cannot. Asserted on the METHOD rather than by
    watching for a call, so it holds for every path through `classify`
    including ones added later.
    """
    assert router.classify(question, chat=None).method != "llm-tiebreak"


def test_a_question_with_no_signal_at_all_reaches_the_tiebreak():
    """The deepest doubt there is, and it used to be the one case never asked.

    An early return on "no keyword matched" meant the input the deterministic
    pass had NO opinion about was the input the model was never consulted on —
    exactly backwards for a policy of "deterministic first, model on doubt".
    """
    calls: list[int] = []

    def chat(_messages, **_kwargs):
        calls.append(1)
        return {"content": json.dumps({"scenario": "financial", "confidence": 0.8})}

    match = router.classify("یک چیز کاملاً نامفهوم", chat=chat)
    assert calls, "an unclear question should reach the tiebreak when one is offered"
    assert match.scenario == "financial"
    assert match.method == "llm-tiebreak"


def test_a_confident_question_does_not_spend_a_call():
    """The other half of the cost argument: the common path stays free."""
    calls: list[int] = []

    def chat(_messages, **_kwargs):  # pragma: no cover - must not run
        calls.append(1)
        return {"content": "{}"}

    assert router.classify("صندوق امروز چه‌جوری بود؟", chat=chat).method == "lexical"
    assert not calls


def test_a_broken_tiebreak_falls_back_rather_than_failing():
    """Routing must never be able to fail a question."""

    def chat(_messages, **_kwargs):
        raise RuntimeError("provider down")

    match = router.classify("یک چیز کاملاً نامفهوم", chat=chat)
    assert match.scenario == scenarios.FALLBACK_SCENARIO


def test_a_tiebreak_naming_an_unknown_scenario_is_ignored():
    def chat(_messages, **_kwargs):
        return {"content": json.dumps({"scenario": "wizardry", "confidence": 0.99})}

    assert router.classify("یک چیز کاملاً نامفهوم", chat=chat).scenario == "general"
