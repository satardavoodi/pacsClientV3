from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def gregorian_to_jalali(g_date: date) -> str:
    gy = g_date.year - 1600
    gm = g_date.month - 1
    gd = g_date.day - 1
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for index in range(gm):
        g_day_no += g_days_in_month[index]
    if gm > 1 and ((gy + 1600) % 4 == 0 and ((gy + 1600) % 100 != 0 or (gy + 1600) % 400 == 0)):
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    while jm < 11 and j_day_no >= j_days_in_month[jm]:
        j_day_no -= j_days_in_month[jm]
        jm += 1
    jd = j_day_no + 1
    return f"{jy:04d}/{jm + 1:02d}/{jd:02d}"


def jalali_to_gregorian(value: str) -> date:
    jy, jm, jd = [int(part) for part in value.replace("-", "/").split("/")]
    jy -= 979
    jm -= 1
    jd -= 1
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4
    for index in range(jm):
        j_day_no += j_days_in_month[index]
    j_day_no += jd

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097

    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False

    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    gm = 0
    while gm < 11:
        days = g_days_in_month[gm] + (1 if gm == 1 and leap else 0)
        if g_day_no < days:
            break
        g_day_no -= days
        gm += 1
    gd = g_day_no + 1
    return date(gy, gm + 1, gd)


#: What a question with no date in it means.
#:
#: **Decided by the owner on 1405/06/03 (2026-08-25): keep today, and keep
#: saying so.** Recorded here as a named policy rather than left implicit in
#: `normalize_jalali_date(None)`, because until that decision "today" was not a
#: choice anybody had made — it was what the function happened to return, and
#: nothing in the code or the tests would have noticed it changing.
#:
#: The alternatives considered and rejected were: default past-tense questions
#: («اوضاع صندوق چه‌جوری بود؟») to yesterday, which needs the agent to judge
#: Persian tense and gets «لیست تخفیف‌ها رو بده» wrong; and asking a
#: clarification every time, which costs a round trip on the most common
#: question in the building.
#:
#: The decision has two halves and they are not separable. Defaulting to today
#: is only defensible BECAUSE the day is always stated — see
#: `DayResolution.as_payload` and `presentation.ensure_assumed_date_is_stated`.
#: Anything that keeps the first half while weakening the second turns a stated
#: assumption into a silent one, which is the defect this replaced.
UNDATED_QUESTION_MEANS = "today"


@dataclass(frozen=True)
class DayResolution:
    """Which day a request resolved to, and whether anyone actually said so.

    `normalize_jalali_date(None)` returns today, which is a reasonable default
    and was an invisible one. The benchmark measured the cost: of twenty
    questions, the fourteen that contained «دیروز» were answered for the right
    day every time, and all six that named no day fell to today. Five of those
    six were scored as partials — and one, «آیا تناقضی توی صندوق پیدا شد؟»,
    answered from today's figures while naming no day at all.

    That last one is the case that matters. A stated default can be caught by
    the reader; an unstated one cannot. So the resolution now carries whether it
    was assumed, and that travels with the payload into the answer.

    What an undated question SHOULD mean is a separate question and still the
    owner's to answer — a rule that suits «اوضاع صندوق چه‌جوری بود؟» does not
    suit «لیست تخفیف‌ها رو بده». This changes nothing about which day is chosen.
    """

    day: str
    assumed: bool
    asked_for: str | None

    def as_payload(self) -> dict:
        """The assumption, in the payload, next to the numbers it produced.

        In the payload rather than in a log or a prompt footnote, because a
        warning one scroll from the number loses to the number — a lesson this
        project has already paid for once, on patient debt.
        """
        if not self.assumed:
            return {"day": self.day, "was_assumed": False}
        return {
            "day": self.day,
            "was_assumed": True,
            "meaning_fa": (
                f"در این پرسش تاریخی ذکر نشده بود؛ پاسخ بر اساس «امروز» "
                f"({self.day}) محاسبه شده است."
            ),
            "must_state_fa": (
                "در پاسخ حتماً بنویس که این ارقام مربوط به چه روزی است و اینکه "
                "این تاریخ فرض شده، نه خواسته‌شده."
            ),
        }


def resolve_day(value: str | None) -> DayResolution:
    """Resolve a day AND report whether it was assumed rather than asked for.

    Routed through `UNDATED_QUESTION_MEANS` rather than relying on
    `normalize_jalali_date(None)`, so the default is the policy the owner chose
    and not a side effect of a falsy check. Changing the policy is then one
    edit in one place, and the tests notice.
    """
    if not value:
        return DayResolution(
            day=normalize_jalali_date(UNDATED_QUESTION_MEANS),
            assumed=True,
            asked_for=None,
        )
    return DayResolution(day=normalize_jalali_date(value), assumed=False, asked_for=value)


def normalize_jalali_date(value: str | None) -> str:
    if not value or value.lower() == "today":
        return gregorian_to_jalali(date.today())
    if value.lower() == "yesterday":
        return gregorian_to_jalali(date.today() - timedelta(days=1))
    if "/" in value:
        parts = [int(part) for part in value.split("/")]
        return f"{parts[0]:04d}/{parts[1]:02d}/{parts[2]:02d}"
    parsed = date.fromisoformat(value)
    return gregorian_to_jalali(parsed)


def add_jalali_days(value: str, days: int) -> str:
    return gregorian_to_jalali(jalali_to_gregorian(value) + timedelta(days=days))


# ---------------------------------------------------------------------------
# F11 — what an undated question means as a FOLLOW-UP
# ---------------------------------------------------------------------------

#: What a question with no date in it means when the CONVERSATION already
#: established one.
#:
#: **Decided by the owner on 1405/06/03 (2026-08-25): the conversation's day
#: wins.** `UNDATED_QUESTION_MEANS` above answers the question asked on its own;
#: this answers the same question asked as turn two, and the two are separate
#: decisions because they were separately wrong.
#:
#: What was measured: turn 1 established 1405/06/02 and the session stored it —
#: `{"date range from": "1405/06/02", "date range to": "1405/06/02",
#: "modality": "MRI", "last tool": "reception.search"}`. Turn 2, undated, HAD
#: those facts and still dispatched `dateFrom: 1405/06/03`. So the memory
#: mechanism was never the problem; the model simply did not treat a
#: conversation-established day as binding on it.
#:
#: The disclosure half of F7 is NOT weakened by this. An inherited day is still
#: a day nobody said out loud this turn, so it is still stated — see
#: `presentation.ensure_inherited_date_is_stated`. What changes is only WHICH
#: day is inherited, never whether the reader is told.
UNDATED_FOLLOWUP_MEANS = "the day the conversation established"


#: Any Jalali or ISO date, in Latin or Persian digits.
_DATE_TOKEN = re.compile(
    r"[\d۰-۹]{4}\s*[/-]\s*[\d۰-۹]{1,2}\s*[/-]\s*[\d۰-۹]{1,2}"
)

#: Persian words that name or scope a time, written after ی/ک normalisation.
#:
#: Deliberately WIDER than "words that name a day". A period word («این هفته»,
#: «ماه گذشته», «۳ روز پیش») is not a day, but its presence means the person did
#: say something about time — and the safe reading of that is "do not silently
#: substitute a day from three turns ago". Matching too much here costs nothing:
#: the fallback is the behaviour that already shipped.
_TIME_WORDS = (
    "امروز", "دیروز", "پریروز", "فردا", "پسفردا", "امشب", "دیشب",
    "روز", "هفته", "ماه", "سال", "تاریخ", "بازه", "از تا",
)


def _normalize_persian(text: str) -> str:
    """ی/ي, ک/ك and ZWNJ folded, so one spelling matches the other.

    The same fold the lexicon applies. Without it «امروز» typed with an Arabic
    yeh does not match the Persian one, and the caller silently concludes the
    question named no day — which here would mean silently inheriting one.
    """
    return (
        str(text or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("‌", "")
    )


def text_names_a_day(text: str) -> bool:
    """Did the person's own words say anything about WHEN?

    Used to decide whether a follow-up may inherit the conversation's day. It
    answers "did they mention time at all", never "which day did they mean" —
    parsing Persian tense is exactly the judgement F7 refused to make, and this
    does not make it either.

    Fails CLOSED: anything time-shaped counts as the person having spoken, so
    the inherited day is not substituted over their words.
    """
    folded = _normalize_persian(text)
    if _DATE_TOKEN.search(folded):
        return True
    return any(word in folded for word in _TIME_WORDS)


#: Session-fact labels that carry a day, in the order they should be believed.
#: These are the labels `orchestrator._FACT_KEYS` writes, not raw argument
#: names — the facts are stored already labelled.
_DAY_FACT_LABELS = ("date range from", "date")


def conversation_day(facts: Any) -> str | None:
    """The day this conversation has been about, if it established one.

    Read from the server-written session facts — which record the arguments
    tools were ACTUALLY called with — so a model that misremembers the
    conversation cannot move the day. Returns None when the conversation has no
    day yet, or when the stored value is not a day this module can parse:
    inheriting something unparseable would be worse than not inheriting.
    """
    if not isinstance(facts, dict):
        return None

    values = [str(facts.get(label) or "").strip() for label in _DAY_FACT_LABELS]

    # A stored «today»/«yesterday» is a word, not a day, and its presence is
    # disqualifying for the WHOLE conversation rather than for its own label.
    #
    # Session facts are MERGED across turns, not ordered, so "which day is the
    # most recent" is not a question they can answer. A conversation holding
    # both `date range from: 1405/06/02` (turn 1) and `date: today` (turn 3)
    # looks identical whichever turn came last — and inheriting the absolute one
    # would silently overrule a day the person named more recently. Falling back
    # to F7's «today» is the honest failure here: it is the documented default,
    # and it is what the person last said out loud.
    if any(value.lower() in {"today", "yesterday", "tomorrow"} for value in values):
        return None

    for value in values:
        if not value:
            continue
        try:
            return normalize_jalali_date(value)
        except (ValueError, IndexError):
            continue
    return None
