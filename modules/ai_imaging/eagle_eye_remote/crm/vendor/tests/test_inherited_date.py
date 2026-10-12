"""F11 — an undated FOLLOW-UP inherits the day the conversation established.

Decided by the owner on 1405/06/03, after a two-turn probe showed the failure
that the benchmark structurally could not: turn 1 established 1405/06/02 and
the session STORED it, and turn 2 — undated — had those facts and still
dispatched `dateFrom: 1405/06/03`. Session memory was never the problem; the
model simply did not treat a conversation-established day as binding.

These tests hold three things, and they are three because each could hold while
another broke:

1. the day is inherited when, and only when, all three preconditions are met;
2. the person's own words always win over the inherited day;
3. an inherited day is STATED — F7's disclosure half is not weakened by F11.
"""

from __future__ import annotations

from reception_crm import jalali
from reception_crm.core import orchestrator, presentation
from reception_crm.llm.interpreter import ProposedCall, format_session_facts

TODAY = "1405/06/03"
ESTABLISHED = "1405/06/02"

# Persian built from escapes on purpose: these strings are compared against
# model output and stored facts, and a mojibake'd literal would make every
# assertion below pass for the wrong reason.
UNDATED_FOLLOWUP = "لیست رو بهم بده"  # «لیست رو بهم بده»
NAMES_TODAY = "امروز چند تا؟"  # «امروز چند تا؟»
NAMES_YESTERDAY = "دیروز چند تا؟"  # «دیروز چند تا؟»

FACTS = {
    "date range from": ESTABLISHED,
    "date range to": ESTABLISHED,
    "modality": "MRI",
    "last tool": "reception.search",
}


def _inherit(text, calls, facts=FACTS):
    return orchestrator.inherit_conversation_day(text, calls, facts, today=TODAY)


# --------------------------------------------------------------------------- #
# reading the day out of the session facts
# --------------------------------------------------------------------------- #
def test_conversation_day_is_read_from_the_stored_facts():
    assert jalali.conversation_day(FACTS) == ESTABLISHED


def test_a_conversation_with_no_day_yields_none():
    assert jalali.conversation_day({"modality": "MRI"}) is None
    assert jalali.conversation_day(None) is None
    assert jalali.conversation_day("not a dict") is None


def test_a_relative_word_is_not_an_inheritable_day():
    """«today» stored as a word resolves against whoever reads it.

    A conversation that began before midnight would otherwise hand a later turn
    a different day than the one that established it.
    """
    assert jalali.conversation_day({"date": "today"}) is None
    assert jalali.conversation_day({"date range from": "yesterday"}) is None


def test_a_relative_word_disqualifies_the_whole_conversation():
    """Facts are MERGED, not ordered — so recency is not knowable from them.

    Observed live: after a turn that said «امروز», the probe's conversation held
    both `date range from: 1405/06/02` and `date: today`, and nothing in the
    record says which turn was last. Preferring the absolute one would silently
    overrule the day the person named most recently.
    """
    facts = {
        "date range from": ESTABLISHED,
        "date range to": ESTABLISHED,
        "date": "today",
    }
    assert jalali.conversation_day(facts) is None
    _, inherited = _inherit(UNDATED_FOLLOWUP, [ProposedCall("x", {"date": "today"})], facts)
    assert inherited is None


def test_an_unparseable_stored_day_is_not_inherited():
    assert jalali.conversation_day({"date": "sometime"}) is None


# --------------------------------------------------------------------------- #
# whether the person said anything about when
# --------------------------------------------------------------------------- #
def test_a_question_with_no_time_word_names_no_day():
    assert jalali.text_names_a_day(UNDATED_FOLLOWUP) is False


def test_time_words_and_dates_count_as_naming_a_day():
    for text in (NAMES_TODAY, NAMES_YESTERDAY, "1405/06/01", "۱۴۰۵/۰۶/۰۱"):
        assert jalali.text_names_a_day(text) is True, text


def test_arabic_yeh_still_matches():
    """«ديروز» with an Arabic yeh must not read as a question that named no day.

    Without the fold this returns False, the day is silently inherited, and the
    person's own word is overridden — the exact failure the fold exists for.
    """
    assert jalali.text_names_a_day("ديروز") is True


# --------------------------------------------------------------------------- #
# the rewrite
# --------------------------------------------------------------------------- #
def test_an_undated_followup_inherits_the_day():
    calls = [ProposedCall("reception.search", {"dateFrom": TODAY, "dateTo": TODAY})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls)
    assert inherited == ESTABLISHED
    assert rewritten[0].arguments["dateFrom"] == ESTABLISHED
    assert rewritten[0].arguments["dateTo"] == ESTABLISHED


def test_the_word_today_is_inherited_too():
    """The model sends `date: "today"` as often as it sends a literal date."""
    calls = [ProposedCall("cashier-report", {"date": "today"})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls)
    assert inherited == ESTABLISHED
    assert rewritten[0].arguments["date"] == ESTABLISHED


def test_the_persons_own_day_always_wins():
    for text in (NAMES_TODAY, NAMES_YESTERDAY):
        calls = [ProposedCall("cashier-report", {"date": "today"})]
        rewritten, inherited = _inherit(text, calls)
        assert inherited is None
        assert rewritten[0].arguments["date"] == "today"


def test_a_day_the_model_chose_for_itself_is_left_alone():
    """Only a default to TODAY is replaced.

    Any other day means the model had a reason this function cannot see, and
    overwriting it would be swapping one guess for another.
    """
    calls = [ProposedCall("cashier-report", {"date": "1405/05/28"})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls)
    assert inherited is None
    assert rewritten[0].arguments["date"] == "1405/05/28"


def test_a_real_range_is_not_collapsed_into_one_day():
    calls = [ProposedCall("reception.search", {"dateFrom": "1405/06/01", "dateTo": TODAY})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls)
    assert inherited is None
    assert rewritten[0].arguments == {"dateFrom": "1405/06/01", "dateTo": TODAY}


def test_a_first_turn_inherits_nothing():
    calls = [ProposedCall("cashier-report", {"date": "today"})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls, facts=None)
    assert inherited is None
    assert rewritten[0].arguments["date"] == "today"


def test_a_conversation_already_on_today_changes_nothing():
    calls = [ProposedCall("cashier-report", {"date": "today"})]
    _, inherited = _inherit(UNDATED_FOLLOWUP, calls, facts={"date range from": TODAY})
    assert inherited is None


def test_a_call_with_no_date_argument_is_untouched():
    calls = [ProposedCall("patients.search", {"query": "x"})]
    rewritten, inherited = _inherit(UNDATED_FOLLOWUP, calls)
    assert inherited is None
    assert rewritten[0].arguments == {"query": "x"}


# --------------------------------------------------------------------------- #
# the disclosure — F7's half, unweakened
# --------------------------------------------------------------------------- #
def test_an_inherited_day_that_is_not_stated_gets_stated():
    display, _ = presentation.build_display(
        "تعداد: ۹۹", {}, inherited_day=ESTABLISHED
    )
    assert ESTABLISHED in display.translate(presentation._PERSIAN_DIGITS)


def test_an_answer_naming_a_DIFFERENT_day_is_still_corrected():
    """The F7 floor asks "did it name a date". That is not enough here.

    The model may write prose around today while the server dispatched the
    inherited day, so the test has to be "did it name THIS day".
    """
    display, _ = presentation.build_display(
        f"در {TODAY} ۹۹", {}, inherited_day=ESTABLISHED
    )
    assert ESTABLISHED in display.translate(presentation._PERSIAN_DIGITS)


def test_an_answer_that_already_names_the_inherited_day_gets_no_note():
    body = f"در {ESTABLISHED} ۹۹"
    display, _ = presentation.build_display(body, {}, inherited_day=ESTABLISHED)
    assert display == body


def test_persian_digits_count_as_naming_the_day():
    body = "در ۱۴۰۵/۰۶/۰۲"
    display, _ = presentation.build_display(body, {}, inherited_day=ESTABLISHED)
    assert display == body


def test_the_two_disclosures_never_both_fire():
    """An inherited day and an assumed day are mutually exclusive.

    If the turn inherited a day, nothing defaulted to today — so appending both
    notes would put two contradictory sentences under one set of figures.
    """
    data = {"date_assumption": {"day": TODAY, "was_assumed": True}}
    display, _ = presentation.build_display("x", data, inherited_day=ESTABLISHED)
    assert display.count(">") == 1
    assert TODAY not in display.translate(presentation._PERSIAN_DIGITS)


def test_without_an_inherited_day_the_f7_floor_still_works():
    data = {"date_assumption": {"day": TODAY, "was_assumed": True}}
    display, _ = presentation.build_display("x", data)
    assert TODAY in display


# --------------------------------------------------------------------------- #
# the prompt layer
# --------------------------------------------------------------------------- #
def test_the_rule_reaches_the_model_when_the_conversation_has_a_day():
    block = format_session_facts(FACTS)
    assert ESTABLISHED in block
    assert "follow-up" in block.lower()


def test_the_rule_is_absent_when_the_conversation_has_no_day():
    block = format_session_facts({"modality": "MRI"})
    assert block
    assert "follow-up" not in block.lower()


def test_the_prompt_rule_and_the_rewrite_agree_on_when_they_apply():
    """The paragraph must appear exactly when the floor would also fire.

    A rule the model is told to follow in cases the server does not cover is a
    rule whose halves can disagree, and that disagreement would only ever be
    visible in production.
    """
    disqualified = {"date range from": ESTABLISHED, "date": "today"}
    assert "follow-up" not in format_session_facts(disqualified).lower()
    _, inherited = _inherit(
        UNDATED_FOLLOWUP, [ProposedCall("x", {"date": "today"})], disqualified
    )
    assert inherited is None


def test_the_policy_is_named_rather_than_implicit():
    assert jalali.UNDATED_FOLLOWUP_MEANS == "the day the conversation established"
    assert jalali.UNDATED_QUESTION_MEANS == "today"
