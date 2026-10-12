"""An assumed day must never be an invisible one. (F7, second half.)

The benchmark measured the cost precisely. Of twenty questions, the fourteen
containing «دیروز» were answered for the right day every time; all six that
named no day fell to today. Five were scored partial — and one of them,
«آیا تناقضی توی صندوق پیدا شد؟», answered from today's figures and named no day
anywhere in the reply.

That is the case these tests exist for. Four sibling questions defaulted the
same way and DID say which day, so the behaviour was already mostly right,
which is exactly what makes the exception easy to miss.

Which day an undated question resolves to is now **decided**: the owner chose,
on 1405/06/03, to keep today and keep saying so. The alternatives — defaulting
past-tense questions to yesterday, or asking a clarification every time — were
considered and rejected; see `jalali.UNDATED_QUESTION_MEANS`.

The two halves of that decision are not separable, and most of this file is
about the second one. Defaulting to today is defensible only because the day is
always stated; a build that kept the default and lost the disclosure would have
re-created the original defect while passing for the fix.
"""

from __future__ import annotations

from reception_crm import management
from reception_crm.core import presentation
from reception_crm.jalali import (
    UNDATED_QUESTION_MEANS,
    gregorian_to_jalali,
    resolve_day,
)


# --------------------------------------------------------------------------- #
# the decision itself
# --------------------------------------------------------------------------- #
def test_an_undated_question_means_today_and_that_is_a_decision():
    """Owner's decision, 1405/06/03: keep today, and keep saying so.

    Pinned because until it was decided, "today" was not a choice anybody had
    made — it was what `normalize_jalali_date(None)` happened to return, and
    nothing would have noticed it changing.
    """
    from datetime import date

    assert UNDATED_QUESTION_MEANS == "today"
    assert resolve_day(None).day == gregorian_to_jalali(date.today())


def test_the_two_halves_of_the_decision_are_not_separable():
    """Defaulting to today is defensible only because the day is always stated.

    Keeping the first half while weakening the second turns a stated assumption
    back into a silent one, which is the defect this replaced. So the payload
    for an undated question must always carry both the day AND the fact that it
    was assumed.
    """
    payload = resolve_day(None).as_payload()

    assert payload["was_assumed"] is True
    assert payload["day"]
    assert payload["day"] in payload["meaning_fa"]
    assert payload["must_state_fa"]


# --------------------------------------------------------------------------- #
# the resolution knows whether anyone asked
# --------------------------------------------------------------------------- #
def test_a_named_day_is_not_an_assumption():
    resolution = resolve_day("1405/06/02")

    assert resolution.day == "1405/06/02"
    assert resolution.assumed is False
    assert resolution.as_payload() == {"day": "1405/06/02", "was_assumed": False}


def test_an_explicit_today_is_not_an_assumption_either():
    """The caller said today. That is a choice, not a fallback."""
    assert resolve_day("today").assumed is False
    assert resolve_day("yesterday").assumed is False


def test_saying_nothing_is_an_assumption_and_says_so_in_persian():
    resolution = resolve_day(None)

    assert resolution.assumed is True
    payload = resolution.as_payload()
    assert payload["was_assumed"] is True
    assert "تاریخی ذکر نشده" in payload["meaning_fa"]
    assert payload["day"] in payload["meaning_fa"], "the caveat must name the day"


# --------------------------------------------------------------------------- #
# it survives into the payload
# --------------------------------------------------------------------------- #
def test_every_dated_payload_carries_the_assumption():
    """Added in `_period_dict` because nine call sites would miss one."""
    assumed = management._period_dict(management.resolve_period(None))
    asked = management._period_dict(management.resolve_period("1405/06/02"))

    assert assumed["date_assumption"]["was_assumed"] is True
    assert asked["date_assumption"]["was_assumed"] is False
    assert asked["end_date"] == "1405/06/02"


# --------------------------------------------------------------------------- #
# and the answer cannot omit it
# --------------------------------------------------------------------------- #
def test_an_answer_that_never_names_a_day_gets_told_which_one():
    data = {"period": {"date_assumption": {"was_assumed": True, "day": "1405/06/03"}}}

    display, _ = presentation.build_display("در صندوق تناقضی یافت نشد.", data)

    assert "1405/06/03" in display
    assert "تاریخی ذکر نشده" in display


def test_an_answer_that_already_names_the_day_is_left_alone():
    """This is a floor under the prompt, not a second voice talking over it."""
    message = "گزارش صندوق — ۱۴۰۵/۰۶/۰۳\n\n- خالص صندوق: ۲٬۰۷۶٬۱۳۰٬۰۰۰"
    data = {"period": {"date_assumption": {"was_assumed": True, "day": "1405/06/03"}}}

    display, _ = presentation.build_display(message, data)

    assert display == message, "nothing should be appended when the day is already stated"


def test_persian_digits_count_as_naming_the_day():
    """Answers are written in Persian digits; Latin-only matching would double up."""
    message = "پذیرش‌های امروز — ۱۴۰۵/۰۶/۰۳: ۸۲ مورد"
    data = {"period": {"date_assumption": {"was_assumed": True, "day": "1405/06/03"}}}

    display, _ = presentation.build_display(message, data)

    assert display == message


def test_a_day_that_was_asked_for_adds_nothing():
    data = {"period": {"date_assumption": {"was_assumed": False, "day": "1405/06/02"}}}

    display, _ = presentation.build_display("۲۲۰ پذیرش ثبت شده است.", data)

    assert "تاریخی ذکر نشده" not in display


def test_the_assumption_is_found_wherever_the_gathering_loop_put_it():
    """A round can place several tool results side by side."""
    data = {"steps": [
        {"data": {"period": {"date_assumption": {"was_assumed": False, "day": "1405/06/02"}}}},
        {"data": {"period": {"date_assumption": {"was_assumed": True, "day": "1405/06/03"}}}},
    ]}

    display, _ = presentation.build_display("نتیجه آماده است.", data)

    assert "1405/06/03" in display
