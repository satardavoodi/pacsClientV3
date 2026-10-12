"""Which modelled workflow is this question? Deterministically, first.

## The shape

    text → normalise → consume identifiers → consume terms, longest first
         → score → primary (+ secondary) → confidence
         → below MIN_CONFIDENCE: LLM tiebreak if one is offered, else General

The deterministic pass is the common path and costs microseconds. An LLM
tiebreak is offered, not assumed: `classify(..., chat=None)` never calls a
model, which is what lets this run in shadow mode on every live question
without adding a round trip to any of them.

## Why longest-match-and-consume rather than "does the text contain X"

«صندوق‌دارها امروز چجوری کار کردن؟» contains «صندوق». So does «صندوق امروز چه‌جوری
بود؟». A naive substring scan scores both as financial, and the first question
is about people. So a matched term's SPAN is removed from the text before
shorter terms are tried: «صندوق‌دار» (staff, specific) consumes the characters
that «صندوق» (financial, generic) would otherwise have matched. Specificity wins
because it eats first, not because of a special case.

The same mechanism handles «گزارش‌های فلان پزشک» — «پزشک» is a staff term, and
the generic «گزارش» that would drag it towards report-retrieval has already lost
its span.

## Why a wrong answer here is cheap

`scenarios.GENERAL` narrows nothing, so an unclassifiable question is answered
exactly as it was before this module existed. And `scenarios.tools_for`
subtracts only — a scenario cannot add a tool the mode withheld. The worst case
of a misclassification is a narrower menu than ideal, which the model can still
answer from or say it cannot; it is never a wrong number, and never a widened
capability.

That is the property that makes it safe to ship this classifying every live
question before it is allowed to change any of them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .. import jalali, scenarios
from ..lexicon.normalize import fold

LOG = logging.getLogger("reception_crm.core.scenario_router")

#: A secondary scenario is reported when it scores at least this fraction of the
#: primary. Multi-part questions ("which employee gave the most discount, and
#: was that abnormal?") are real, and reporting only the winner would hide half
#: of what was asked. See `docs/SCENARIO_ROUTING.md` §13.
SECONDARY_RATIO = 0.55


@dataclass(frozen=True)
class ScenarioMatch:
    """What the router decided, and on what evidence.

    `evidence` exists so a wrong routing can be diagnosed from the envelope
    without re-running anything: it names the exact terms that scored. A
    classifier whose decisions cannot be explained is one nobody will trust
    enough to switch on.
    """

    scenario: str
    confidence: float
    method: str
    secondary: str | None = None
    entities: tuple[str, ...] = ()
    identifiers: dict[str, str] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "scenario": self.scenario,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }
        if self.secondary:
            out["secondary"] = self.secondary
        if self.entities:
            out["entities"] = list(self.entities)
        if self.identifiers:
            # Keys only. A national code or a reception id is the patient, and
            # the envelope is logged — the shape of the evidence belongs here,
            # the value does not.
            out["identifierKinds"] = sorted(self.identifiers)
        if self.evidence:
            out["evidence"] = list(self.evidence)
        return out


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
# Terms are stored FOLDED (see `lexicon.normalize.fold`), so ی/ي, ک/ك, ZWNJ and
# Persian digits are already reconciled and «صندوق‌دار» and «صندوقدار» are one
# entry. Writing them folded rather than folding at match time keeps the table
# readable as the thing that is actually compared.
#
# Weights are coarse on purpose — 3 for a term that names the scenario outright,
# 2 for a strong one, 1 for a term that merely leans. Fine-grained weights would
# imply a precision this has no way to earn.
_TERMS: dict[str, tuple[tuple[str, float], ...]] = {
    "conversation": (
        ("گفتگو", 3), ("گفت و گو", 3), ("چت", 3), ("پیام", 2), ("اپراتور", 3),
        ("پاسخگویی", 2), ("پاسخ گویی", 2), ("بدون پاسخ", 2), ("بی پاسخ", 2),
        ("زمان پاسخ", 3), ("نرخ تبدیل", 3), ("مشاوره", 1),
        # «بیمارها بیشتر چه سوالاتی پرسیدن؟» has no chat word in it at all. What
        # it has is the shape of asking about questions people ASKED, which
        # nothing in the reception system records.
        #
        # ⚠️ The bare singular is worth LESS than the plural, and deliberately
        # less than the fallback threshold on its own. «یه سوال داشتم» is how a
        # person opens a conversation, not a question about the conversation
        # system, and at 2.5 it classified that opener as `conversation` with
        # 0.63 confidence. At 1.5 the opener alone falls to General, while
        # «بیمارها بیشتر چه سوالاتی پرسیدن؟» still scores 4.5 from the plural
        # and the verb together and lands at 1.0.
        ("سوالات", 2.5), ("سوال", 1.5), ("پرسیدن", 2),
        # ⚠️ «میانگین زمان اولین پاسخ به بیمارها دیروز چقدر بوده؟» scored
        # NOTHING — not a low score, zero — and fell to General with no signal
        # at all. «زمان پاسخ» is in the table and the sentence says «زمان اولین
        # پاسخ», which is not the same contiguous span, and matching is by span.
        # A term table cannot be written by listing the words a concept uses;
        # it has to hold the phrases people actually type.
        ("اولین پاسخ", 3), ("پاسخ اول", 3),
        ("زمان پاسخگویی", 3), ("زمان پاسخ گویی", 3),
        # Dissatisfaction is a conversation-channel concept here: there is no
        # complaints table, and «بیمار ناراضی» reaches the centre by message.
        # Without these «آیا دیروز بیمار ناراضی یا گفتگوی نگران‌کننده‌ای داشتیم؟»
        # tied 3-3 with `audit` on «نگران کننده» and lost the tiebreak.
        ("ناراضی", 3.5), ("نارضایتی", 3.5), ("شکایت", 3),
    ),
    "staff": (
        # Compounds appear TWICE, joined and space-separated. `fold` turns a
        # ZWNJ into a space, so «صندوق‌دار» arrives as «صندوق دار» — and a table
        # holding only the joined spelling matched none of the owner's own
        # questions, while the generic «صندوق» matched all of them. The whole
        # specificity mechanism was silently inverted by one invisible
        # character, which is a failure mode this project has paid for before.
        ("صندوق دار", 3), ("صندوقدار", 3),
        ("پذیرشگر", 3), ("پذیرش گر", 3),
        ("کارمند", 3), ("پرسنل", 3), ("کارکنان", 3),
        ("تکنولوژیست", 3), ("رادیولوژیست", 3),
        ("پزشکان", 3), ("پزشک", 3),
        ("کارکرد", 2), ("عملکرد", 2), ("بهره وری", 2),
        ("چه کسی", 2), ("کدوم کارمند", 3), ("مقایسه با همکار", 2),
        ("ساعت شروع", 2), ("بیشترین خطا", 2),
        # «شیفت» moved to `appointment`: a shift is a capacity window that
        # rooms and service groups hang off, and «کدوم اتاق شیفت صبح خالیه؟» is
        # a scheduling question, not a staffing one.
    ),
    "marketing": (
        ("روند", 3), ("نسبت به ماه", 3), ("نسبت به هفته", 3), ("ماه قبل", 3),
        ("ماه گذشته", 3), ("این ماه", 2), ("هفته قبل", 2), ("سال قبل", 2),
        ("رشد", 2), ("افت", 2), ("کاهش", 2), ("افزایش", 2), ("مقایسه", 2),
        # «ارجاع داده» before «ارجاع»: the verb phrase says a physician REFERRED,
        # which is the referral question, while the bare noun ties with «پزشک»
        # and sends «کدوم پزشک بیشتر ارجاع داده؟» to a tiebreak it does not need.
        ("ارجاع دهنده", 3.5), ("ارجاع داده", 3.5), ("ارجاع", 3),
        ("فرستاده", 2), ("بازاریابی", 3),
        ("کدوم خدمت", 3), ("کدام خدمت", 3), ("پرطرفدار", 2), ("محبوب", 1),
        # «از کدوم پزشک‌ها بیمار کمتری اومده؟» is a referral question wearing a
        # physician word. Long enough to be unambiguous, and because it eats the
        # span it also removes the «پزشک» that would otherwise call it staff.
        ("از کدوم پزشک", 3.5), ("از کدام پزشک", 3.5), ("کمتری", 1.5),
    ),
    "financial": (
        ("صندوق", 3), ("درامد", 3), ("مالی", 3), ("تخفیف", 3), ("پرداخت", 2),
        ("دریافت", 2), ("بدهی", 3), ("بدهکار", 3), ("وصول", 3), ("تراکنش", 3),
        ("مغایرت", 3), ("تناقض", 3), ("تسویه", 3), ("کارتخوان", 3),
        ("نقدی", 2), ("کارتی", 2), ("سهم بیمار", 3),
        ("حذف", 2), ("برداشت", 2), ("هزینه", 2), ("مانده", 2),
        # Refunds — «مرجوعی پذیرش» in the UI, a financial workflow with its own
        # router. Not «مرجع» (referral), which is what it looks like at a glance.
        ("مرجوعی", 3), ("عودت", 3),
        ("کیف پول", 3), ("تنخواه", 3),
        # ---- centre VOLUME and TIMING, as evidence rather than as a bonus ---
        # ⚠️ These belong HERE, not with `marketing`, and working that out is
        # what the benchmark was actually for. This scenario is «مالی و عملکرد
        # مرکز» — its own `intent_fa` says «چند پذیرش، چقدر درآمد», and
        # `daily-summary`, the tool that answers a reception count, is one of
        # its preferred tools. `marketing` is about CHANGE over time and about
        # which service, not about how many admissions there were.
        #
        # So the defect the benchmark found was never the destination. It was
        # that «مجموع پذیرش‌هامون دیروز چند تا بوده؟» arrived here at confidence
        # 0.50 on the centre-vocabulary BONUS, with no term of its own — a
        # question decided by a mechanism that had nothing to say about it, and
        # one term away from being decided differently. Naming the phrases makes
        # the same routing an argument instead of an accident.
        #
        # «چند تا MRI دیروز پذیرش شده؟» contains none of these, so the service
        # questions stay with the clinical term. «هر پذیرشگر چند تا بیمار پذیرش
        # کرده؟» contains none of them either, so staff keeps its own.
        ("مجموع پذیرش", 3.5), ("کل پذیرش", 3.5), ("تعداد پذیرش", 3.5),
        ("چند تا پذیرش", 3.5), ("چند پذیرش", 3.5),
        # ⚠️ The VALUE of the receptions, not their count. «سهم بیمار و سهم بیمه
        # ... آیا جمعشون با مبلغ پذیرش‌ها می‌خونه؟» is a reconciliation question
        # and it went to `insurance` 3.5 to 3.0, on the strength of one «بیمه».
        # The thing being reconciled is the reception total, which is this
        # scenario's own quantity — and the answer that came back compared the
        # two shares against the SERVICE total while calling it the reception
        # total, which is the failure the whole basis work is about.
        ("مبلغ پذیرش", 3), ("ارزش پذیرش", 3), ("مبلغ کل", 3),
        ("پیک پذیرش", 3.5), ("شلوغ ترین", 3), ("ساعت شلوغ", 3),
        # ⚠️ «بیمه» used to sit here at weight 1 and now belongs to `insurance`.
        # It could not have stayed in both: terms are matched longest-first and
        # the match CONSUMES the span, so at equal length whichever scenario is
        # declared first wins outright and the other entry is dead. A duplicated
        # term is not a tie — it is a silent winner and a table that lies.
    ),
    "appointment": (
        # «نوبت» is the word, and it is unambiguous in this building.
        ("نوبت دهی", 3.5), ("نوبتدهی", 3.5), ("نوبت", 3),
        ("منتظر نوبت", 3.5), ("ظرفیت", 3), ("ظرفیت خالی", 3.5),
        ("زمان بندی", 3), ("شیفت", 3), ("اتاق", 3), ("رزرو", 3),
        # «برای این بیمار نوبت ثبت کن» is a booking, and the patient referent
        # «این بیمار» scores 4. The ACTION has to outweigh the referent or a
        # booking request is answered as a case investigation.
        ("نوبت ثبت", 4.5), ("ثبت نوبت", 4.5), ("نوبت بده", 4.5),
        # ⚠️ AVAILABILITY IS THE COMMONEST APPOINTMENT QUESTION AND IT HAD NO
        # VOCABULARY. «فردا برای سونوگرافی چه ساعت‌های خالی داریم؟» scored
        # nothing for `appointment` at all and went to `marketing` on
        # «سونوگرافی», because the table held «ظرفیت خالی» and the owner says
        # «ساعت خالی». Five of the ten Appointment questions lost this way — to
        # a modality word or to a patient referent — and none of them was a
        # close call the weights got wrong; the phrase simply was not there.
        #
        # These are worth 4, above the patient referent's 4 only in combination
        # and above every clinical term on their own, because a sentence that
        # names a free slot is asking about the diary whatever else is in it.
        ("نوبت خالی", 4), ("نوبت های خالی", 4), ("اولین نوبت", 4),
        ("ساعت خالی", 4), ("ساعت های خالی", 4),
        ("زمان خالی", 4), ("وقت خالی", 4), ("وقت آزاد", 4), ("جای خالی", 3.5),
        # Having one, versus asking for one.
        ("نوبت گرفته", 4.5), ("نوبت گرفتن", 4.5), ("نوبت میگیرن", 4),
        ("نوبت فعال", 4.5), ("نوبت داره", 4), ("نوبت دارن", 4),
    ),
    "reporting": (
        # ⚠️ NOT «گزارش» on its own. «گزارش صندوق» is a financial report and
        # «گزارش‌های این بیمار» is a case investigation; a bare «گزارش» term
        # would take both. Only phrases that mean the clinical report LIFECYCLE.
        ("جواب دهی", 3.5), ("جوابدهی", 3.5),
        ("گزارش نویسی", 3.5), ("گزارش نشده", 3.5), ("بدون گزارش", 3),
        ("منتظر تایید", 3.5), ("تایید گزارش", 3.5),
        # ⚠️ «بعد از تایید» / «پس از تایید» moved to `audit`. Whether a report
        # was EDITED after it was approved is an integrity question, not a queue
        # question — and it is the one this project has already been burned by:
        # 93 "post-approval edits" turned out to be same-session saves. The
        # scenario that has to say that out loud is the one that owns the term.
        ("صف گزارش", 3.5), ("زمان جواب", 3), ("لیست کار", 3),
        # «چند تا گزارش هنوز تایید نشده؟» scored NOTHING and fell to General.
        # Falling back is safe and the answer was not wrong because of it, but a
        # scenario no plain phrasing can reach is a scenario that will never be
        # used — and this is the plainest phrasing there is for the report
        # queue. Approval belongs to the report lifecycle and to nothing else in
        # this building, so these are unambiguous without naming «گزارش» at all.
        ("تایید نشده", 3.5), ("تایید نکرده", 3.5), ("بدون تایید", 3.5),
        ("هنوز تایید", 3.5), ("تایید نهایی", 3),
        # «رادیولوژیست» stays with `staff`: asked about as a PERSON it is a
        # performance question. Listing it here too would be dead — staff is
        # declared first and consumes the span.
    ),
    "audit": (
        # «آیا نکته‌ای بود که دیروز نگران‌کننده باشه، مثل حذف غیرطبیعی یا چیزی؟»
        # used to score `financial` 2.0 on the deletion word alone and route
        # there at 0.50 — barely over the fallback threshold, on a scenario that
        # owns none of the tools that answer it. The integrity tools existed the
        # whole time; nothing routed to them.
        #
        # ⚠️ The bare «حذف» stays with `financial` and is NOT duplicated here. A
        # deletion is a money event as often as an integrity one, and a term
        # declared in two scenarios is not a tie — longest-match consumes the
        # span, so at equal length whichever is declared first wins outright and
        # the other entry is silently dead.
        #
        # The PAST PARTICIPLE is different, and it is longer, so it is consumed
        # first. «لیست بیمارانی که حذف شدن رو با کدهای پذیرششون بهم بده» is a
        # request for the deleted-records trail, and it routed to `financial` on
        # the bare verb at confidence 0.50 — the weakest evidence of any of the
        # owner's twenty questions. It is also the question this scenario's
        # first validation rule was written for: a deleted reception and a
        # deleted transaction are different objects, and saying which is which
        # is the whole answer.
        ("حذف شدن", 3.5), ("حذف شده", 3.5), ("حذف شد", 3.4),
        ("نگران کننده", 3), ("نگرانکننده", 3),
        ("غیرطبیعی", 3), ("غیر طبیعی", 3), ("غیرعادی", 3), ("غیر عادی", 3),
        ("مشکوک", 3), ("تخلف", 3.5), ("دستکاری", 3.5),
        ("سواستفاده", 3.5), ("سوءاستفاده", 3.5),
        ("حسابرسی", 3.5), ("ممیزی", 3.5),
        # Longer than `patient`'s «سابقه», so it consumes the span first: asking
        # what CHANGED is an integrity question, not a case history.
        ("سابقه تغییر", 3.5), ("تغییر نام", 3.5),
        ("بعد از تایید", 3.5), ("پس از تایید", 3.5), ("ویرایش بعد", 3.5),
        ("رد پای", 3), ("لاگ", 3),
        # ⚠️ «برای این بیمار چیزی حذف، لغو یا تغییر داده شده؟» is a change-trail
        # question and it routed to `patient` — the referent outscored the
        # subject, because the only audit-ish word in it, the bare «حذف», is
        # deliberately financial (deleted TRANSACTIONS). «لغو» and «تغییر داده»
        # are not: cancelled and altered are what an audit trail records, and
        # nothing else in this system uses them.
        ("لغو", 2.5), ("لغو شده", 3), ("لغو شدن", 3.5), ("لغو شد", 3.4),
        ("تغییر داده", 3), ("تغییر کرده", 3),
        # ⚠️ NOT FIXED, and left visible rather than tuned away: «دیروز چه
        # پذیرش‌هایی حذف یا لغو شدن و ارزش مالی اون‌ها چقدر بوده؟» still scores
        # financial 5 to audit 3.5 and routes to `financial`. It is genuinely
        # both questions — which receptions were deleted, and what they were
        # worth — and the answer it produced was correct and complete. A term
        # invented to win this one sentence would be fitting the table to the
        # test, which is how a lexicon stops describing the language.
    ),
    "insurance": (
        ("بیمه تکمیلی", 3.5), ("بیمه", 3), ("سهم بیمه", 3.5),
        ("استعلام", 3), ("سلامت", 2), ("تامین اجتماعی", 3.5),
        ("نسخه", 2), ("بیمه گر", 3),
    ),
    "inventory": (
        ("انبار", 3.5), ("موجودی", 3), ("مصرفی", 3), ("مصرف شده", 3),
        ("کالا", 3), ("تموم میشه", 2), ("رو به اتمام", 3),
    ),
    "patient": (
        # A REFERENT, not a topic. «مشکل مالی این بیمار» is a patient question
        # that happens to be about money, so the referent has to outscore the
        # topic word or the answer arrives as a centre aggregate — the exact
        # confusion `PATIENT.validation_rules` exists to prevent.
        ("این بیمار", 4), ("همین بیمار", 4), ("گزارش های این", 4),
        ("مراجعه کرده", 3), ("بار مراجعه", 3),
        ("پرونده", 2), ("سابقه", 2), ("سوابق", 2),
        # «کد پذیرش» and «کد ملی» are deliberately NOT here. Bare, they name a
        # COLUMN people want listed — «لیست بیمارانی که تخفیف گرفتن رو با کد
        # پذیرششون بهم بده» is a discount report, not a case investigation. With
        # digits after them they are identifiers, and `_IDENTIFIERS` already
        # settles that case outright.
    ),
}

#: Terms that describe a whole day at the centre. They pull towards `financial`
#: only when nothing more specific has fired — «امروز چند تا پذیرش داشتیم؟» is a
#: centre-performance question, but «امروز چند تا ماموگرافی داشتیم؟» is a service
#: question and the modality term must win. So these score LOW and are listed
#: apart, as a tiebreak rather than as evidence.
_CENTRE_TERMS: tuple[tuple[str, float], ...] = (
    ("پذیرش", 2), ("مرکز", 2), ("بیمار", 0.5), ("خدمت", 0.5), ("امروز", 0.5),
)

#: Identifier shapes. A hard identifier is the strongest signal there is: a
#: reception code or a national code means ONE person, whatever else the
#: sentence says.
_IDENTIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 10 consecutive digits, not part of a longer run — Iranian national code.
    ("national_code", re.compile(r"(?<!\d)(\d{10})(?!\d)")),
    # 24 hex characters — a Mongo ObjectId, so a patient or study id.
    ("object_id", re.compile(r"(?<![0-9a-f])([0-9a-f]{24})(?![0-9a-f])")),
    # «کد پذیرش ۱۲۳۴۵» / «پذیرش 12345» — folded, so the digits are already Latin.
    ("reception_code", re.compile(r"(?:کد\s*)?پذیرش\s*(?:شماره\s*)?(\d{3,8})(?!\d)")),
)

#: A bare number is NOT an identifier. «چند تا MRI 3 تسلا» and «۵ روز گذشته» both
#: carry digits, and reading them as a patient would route a centre question
#: into a single-case pipeline. Only the labelled and the structurally
#: unmistakable shapes above count.


def _consume(text: str, term: str) -> tuple[str, bool]:
    """Remove the first occurrence of `term`, so shorter terms cannot reuse it."""
    index = text.find(term)
    if index < 0:
        return text, False
    return text[:index] + " " + text[index + len(term):], True


# All (term, weight, scenario) triples, longest term first. Sorted once at
# import: the ordering IS the specificity rule, and recomputing it per call
# would let a caller's ordering decide the outcome.
_ORDERED: tuple[tuple[str, float, str], ...] = tuple(
    sorted(
        (
            (fold(term), weight, scenario_id)
            for scenario_id, terms in _TERMS.items()
            for term, weight in terms
        ),
        key=lambda item: -len(item[0]),
    )
)

_ORDERED_CENTRE: tuple[tuple[str, float], ...] = tuple(
    sorted(((fold(t), w) for t, w in _CENTRE_TERMS), key=lambda item: -len(item[0]))
)


def find_identifiers(text: str) -> dict[str, str]:
    """Hard identifiers in the question, by kind.

    Returned rather than logged: the caller decides what to do with a value
    that identifies a person. Nothing here prints one.
    """
    folded = fold(text)
    found: dict[str, str] = {}
    for kind, pattern in _IDENTIFIERS:
        match = pattern.search(folded)
        if match:
            found[kind] = match.group(1)
    return found


def score(text: str) -> tuple[dict[str, float], tuple[str, ...]]:
    """Weighted scenario scores and the terms that produced them."""
    remaining = fold(text)
    scores: dict[str, float] = {}
    evidence: list[str] = []

    for term, weight, scenario_id in _ORDERED:
        remaining, hit = _consume(remaining, term)
        if hit:
            scores[scenario_id] = scores.get(scenario_id, 0.0) + weight
            evidence.append(f"{scenario_id}:{term}")

    # ⚠️ Centre vocabulary is RECORDED and scores NOTHING. It used to add its
    # weight to `financial` unconditionally, and that had three consequences,
    # none of them intended by the comment on `_CENTRE_TERMS` that calls it a
    # tiebreak:
    #
    # * it CREATED a scenario out of nothing. «مجموع پذیرش‌هامون دیروز چند تا
    #   بوده؟» has no financial word in it at all, yet scored financial 2.0 and
    #   routed there at 0.50. The destination happened to be right — this
    #   scenario is «مالی و عملکرد مرکز» and owns the day tool — but it was
    #   decided by a mechanism with nothing to say about admissions, and one
    #   term away from being decided differently;
    # * on «چند تا MRI دیروز پذیرش شده؟» it manufactured a financial runner-up,
    #   dropping a clear service question from 1.0 to 0.65 and reporting a
    #   secondary scenario nobody asked about;
    # * and «چه کسی پذیرشش کرده؟», asked inside an open case, had 2 points
    #   handed to a scenario that was not the patient it was about.
    #
    # The phrases that genuinely mean "how busy was the centre" are now real
    # `financial` terms, scored and visible in the evidence. A rule nobody can
    # point at in the table is a rule nobody can argue with, and this one was
    # deciding four of the owner's twenty questions.
    #
    # The terms are still CONSUMED, so a leftover «امروز» cannot be picked up by
    # something shorter, and they are still reported so a reader can see the
    # question named the centre's own vocabulary.
    centre: list[str] = []
    for term, _weight in _ORDERED_CENTRE:
        remaining, hit = _consume(remaining, term)
        if hit:
            centre.append(term)
    if centre:
        evidence.append("centre:" + ",".join(centre) + " (recorded, not scored)")

    return scores, tuple(evidence)


def _confidence(scores: dict[str, float]) -> float:
    """How much the winner beat the field, normalised to 0..1.

    Margin-based rather than absolute: a question scoring 3 against nothing is a
    clearer signal than one scoring 9 against 8. An absolute threshold would
    have got that backwards, and the second case is exactly the multi-scenario
    question that should be going to a tiebreak.
    """
    if not scores:
        return 0.0
    ranked = sorted(scores.values(), reverse=True)
    top = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else 0.0
    if top <= 0:
        return 0.0
    margin = (top - runner_up) / top
    # A lone weak signal must not read as certainty. `strength` is how much
    # evidence there was at all, `margin` is how decisively it won, and both
    # have to be present: one 1-point term against nothing scores 0.25 and goes
    # to General, while two 3-point terms tied score 0.41 and go to the
    # tiebreak — which is exactly the multi-scenario question.
    strength = min(1.0, top / 4.0)
    return round(strength * (0.55 + 0.45 * margin), 3)


#: How much a clinical service or modality term is worth as evidence for
#: `marketing`. Above the 3-point word terms, because naming a modality is the
#: least ambiguous thing a question can do about services: «امروز چند تا
#: ماموگرافی داشتیم؟» is a service question and «امروز چند تا پذیرش داشتیم؟» is a
#: centre question, and the ONLY difference between them is that word.
_CLINICAL_WEIGHT = 3.5

#: Words to try against the lexicon, longest n-gram first. Three is enough for
#: «سنجش تراکم استخوان» and «سی تی اسکن»; beyond that the lexicon's own folding
#: is doing the work anyway.
_MAX_NGRAM = 3

#: Shortest phrase worth asking the lexicon about.
#:
#: Two, not three: «CT» is a modality people type, and a floor of three
#: classified «چند تا CT دیروز پذیرش شده؟» as a centre question while its three
#: sibling questions about MRI, radiology and sonography went to services. The
#: particles that caused the original bug are excluded by requiring an EXACT
#: resolution, which is the guard that actually addresses them — this floor only
#: keeps single letters from reaching the lexicon at all.
_MIN_CLINICAL_CHARS = 2

#: What an established patient referent is worth on a follow-up (§17). Enough to
#: beat a lone topic word, not enough to survive the person changing the subject.
_CARRIED_PATIENT_WEIGHT = 3.5


def find_clinical_terms(text: str) -> tuple[str, ...]:
    """Service / modality words in the question, per the LEXICON, not a word list.

    Resolving through `lexicon.try_resolve` rather than keeping a parallel
    Persian vocabulary here is the point: the lexicon is the grounding asset,
    and a second list beside it would drift from it silently.

    ⚠️ A **disabled** concept counts. «ماموگرافی» resolves to `DisabledValue` —
    modality 9 is `status: disabled` at this centre — and that is still
    conclusive evidence the question named a service. Whether the data can
    answer it is the tool's problem, and the lexicon already refuses loudly;
    routing must not also swallow the term, or the question would be classified
    as if the word were never said.

    ⚠️ Matching is **exact against the concepts' own surface forms**, not via
    `lexicon.resolve`. That is a deliberate difference, and it took two bugs to
    arrive at:

    * `resolve` matches loosely by design — it is answering "what did this
      person probably mean", where a near miss is a service. Here the question
      is "did they name a service at all", where a near miss is noise. Loose
      matching made «تا», «هر» and «کن» resolve to radiology service groups.
    * Requiring `Resolution.exact` fixed those and not «رو», because a loose
      match against a **disabled** concept raises `DisabledValue`, which carries
      no exactness flag at all. The guard had a hole exactly where the data was
      least used, and a clinical hit is the heaviest signal the router has — so
      one particle turned a discount question into a service question.

    Reading the surface forms directly has neither failure mode and is not a
    parallel vocabulary: it is the same lexicon rows, asked a different
    question. Disabled concepts are included on purpose — «ماموگرافی» is
    `status: disabled` here, and someone naming it has still named a service.
    """
    words = [w for w in fold(text).split() if w]
    surfaces = _clinical_surfaces()
    found: list[str] = []
    for size in range(min(_MAX_NGRAM, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            if len(phrase) < _MIN_CLINICAL_CHARS or phrase in found:
                continue
            if phrase in surfaces:
                found.append(phrase)
    return tuple(found)


@lru_cache(maxsize=1)
def _clinical_surfaces() -> frozenset[str]:
    """Every folded name a modality or service group is actually called.

    Built once from the lexicon's own concept rows — codes, vendor short names,
    preferred displays, the `acceptable` lists in both languages, and spelling
    variants. Cached because it is derived from a file that does not change at
    runtime, and because this runs on every classified question.
    """
    from .. import lexicon  # local: keeps import cost off modules that never route

    names: set[str] = set()

    def add(surface: Any) -> None:
        key = fold(surface)
        # Single characters are not names. Nothing in the catalogue is one, and
        # admitting them would put every Persian preposition in the index.
        if len(key) >= _MIN_CLINICAL_CHARS:
            names.add(key)

    # This CENTRE's own department and service-group names, first.
    #
    # ⚠️ The lexicon's `value_sets.modality` is a general vocabulary; the centre
    # configuration is what this centre actually calls things, including groups
    # the lexicon never saw. «ماموگرافی» is a service GROUP here as well as a
    # retired department, so a router reading only the value sets would depend
    # on a disabled concept to notice the word at all.
    try:
        from ..lexicon import center

        for department in center.departments():
            for surface in (department.name_fa, department.name_en, department.short):
                add(surface)
        for group in center.load_center().get("service_groups") or []:
            add(group.get("name"))
    except Exception as exc:  # noqa: BLE001 - routing must never fail a question
        LOG.warning(
            "centre configuration unavailable for clinical terms (%s: %s); "
            "falling back to the lexicon value sets alone",
            type(exc).__name__,
            exc,
        )

    value_sets = lexicon.load().get("value_sets") or {}
    for value_set in ("modality", "service_group"):
        for concept in (value_sets.get(value_set) or {}).get("concepts", []) or []:
            add(concept.get("vendor_short"))
            add(concept.get("display_fa"))
            display = concept.get("display") or {}
            acceptable = concept.get("acceptable") or {}
            for language in ("en", "fa"):
                add((display.get(language) or {}).get("preferred"))
                for surface in acceptable.get(language) or []:
                    add(surface)
            for surface in concept.get("spelling_variants") or []:
                add(surface)
            # `code` is deliberately NOT added. Modality codes are bare digits
            # ("1", "2", "9"), and a question mentioning «۲ تا» would otherwise
            # name a modality.
    return frozenset(names)


def classify(
    text: str,
    facts: dict[str, Any] | None = None,
    *,
    chat: Any = None,
) -> ScenarioMatch:
    """Decide the scenario for one question.

    `chat` is the LLM tiebreak and is **optional by design**. With `chat=None`
    this never calls a model, which is what lets the router run on every live
    question in shadow mode without adding a round trip to any of them. The
    orchestrator passes `None` until the layer is switched on.

    `facts` are the conversation's session facts. They resolve «همین بیمار» in a
    follow-up that carries no identifier of its own — the same referent
    machinery F11 uses for the day.
    """
    scores, evidence = score(text)
    identifiers = find_identifiers(text)
    clinical = find_clinical_terms(text)

    if clinical:
        scores["marketing"] = scores.get("marketing", 0.0) + _CLINICAL_WEIGHT
        evidence = evidence + tuple(f"clinical:{term}" for term in clinical)

    # A hard identifier settles it. Someone who types a reception code is asking
    # about that one case, whatever else the sentence contains — and this is the
    # one classification that must never be left to a margin, because mixing one
    # patient's row into a centre aggregate is the failure `PATIENT`'s
    # validation rules exist to prevent.
    if identifiers:
        return ScenarioMatch(
            scenario="patient",
            confidence=0.95,
            method="identifier",
            entities=("patient",),
            identifiers=identifiers,
            scores=scores,
            evidence=evidence + tuple(f"id:{kind}" for kind in sorted(identifiers)),
        )

    # §17, scenario memory. A conversation already about one patient keeps that
    # referent for a follow-up that names nobody — «چقدر پرداخت کرده؟», «آیا
    # تخفیف داشته؟», «چرا هنوز بدهکار مونده؟». Read cold, every one of those is
    # a financial question about the centre; read as turn two of a case
    # investigation, all three are about one person, and answering them as
    # centre aggregates is the specific confusion PATIENT exists to prevent.
    #
    # Scored rather than short-circuited. A carried referent is strong evidence,
    # not a lock: «صندوق امروز چه‌جوری بود؟» in the middle of a patient
    # investigation really has changed the subject, and §12 says the pipeline
    # must switch when the intent does. 3.5 beats a lone topic word and loses to
    # a scenario the person named outright.
    carried = _carried_patient(facts)
    if carried:
        # ⚠️ Naming a DAY is naming a scope, and it counts against the referent.
        #
        # The comment on `_CARRIED_PATIENT_WEIGHT` says it "beats a lone topic
        # word and loses to a scenario the person named outright". That was not
        # true: at 3.5 it also beat «صندوق» at 3, so «صندوق امروز چه‌جوری بود؟»
        # asked inside an open case was a patient question. It passed its test
        # only because the centre-vocabulary bonus happened to top financial up
        # by the «امروز» in it — an accident, and one that disappeared the
        # moment that bonus was corrected.
        #
        # Weight alone cannot separate «آیا تخفیف داشته؟» from «صندوق امروز
        # چه‌جوری بود؟»: both carry a weight-3 financial term, and the first must
        # stay with the patient while the second must not. What separates them
        # is the day. Asking about a period is asking about the centre over that
        # period; asking with no period, in an open case, is asking about the
        # person.
        #
        # Halved rather than dropped, because the two are not exclusive —
        # «دیروز چقدر پرداخت کرده؟» is still about that patient, and a referent
        # that vanished on any date word would lose it. `text_names_a_day` is
        # the lexicon's single definition of the question, deliberately wide and
        # failing closed; a second list here would drift from it.
        weight = _CARRIED_PATIENT_WEIGHT
        if jalali.text_names_a_day(text):
            weight /= 2
            evidence = evidence + ("scope:day",)
        scores["patient"] = scores.get("patient", 0.0) + weight
        evidence = evidence + ("session:" + carried,)

    if not scores:
        # No keyword matched at all. That is the deepest doubt there is, not an
        # answer — an unfamiliar phrasing is precisely the case a model handles
        # and a term table cannot, so the tiebreak gets it when one is offered.
        # An earlier version returned here outright, which meant the one input
        # the deterministic pass had NO opinion about was the one input the
        # model was never asked about.
        if chat is not None:
            decided = _ask_the_model(text, scores, chat)
            if decided is not None:
                return decided
        return ScenarioMatch(
            scenario=scenarios.FALLBACK_SCENARIO,
            confidence=0.0,
            method="no-signal",
            evidence=evidence,
        )

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    primary, top = ranked[0]
    confidence = _confidence(scores)
    secondary = None
    if len(ranked) > 1 and top > 0 and ranked[1][1] >= SECONDARY_RATIO * top:
        secondary = ranked[1][0]

    if confidence >= scenarios.MIN_CONFIDENCE:
        return ScenarioMatch(
            scenario=primary,
            confidence=confidence,
            method="lexical",
            secondary=secondary,
            entities=tuple(scenarios.get(primary).entities[:2]),
            scores=scores,
            evidence=evidence,
        )

    # §13, multi-scenario. Two STRONG contenders that neither of them wins is
    # not doubt — it is a question that genuinely spans both. «کدوم کارمند
    # بیشترین تخفیف رو داده و آیا این تخفیف‌ها غیرطبیعی بوده؟» is staff and
    # financial, and answering it from either alone answers half of it.
    #
    # Merging is as safe as falling back: the union of two scenario menus is
    # still a SUBSET of what the mode allowed, so this can no more widen a
    # capability than General can. What it risks is a menu narrower than ideal
    # when both guesses are wrong, which is the thing shadow mode is for
    # measuring before any of it is applied.
    if secondary and top >= 3:
        return ScenarioMatch(
            scenario=primary,
            confidence=confidence,
            method="multi",
            secondary=secondary,
            entities=tuple(scenarios.get(primary).entities[:2]),
            scores=scores,
            evidence=evidence,
        )

    if chat is not None:
        decided = _ask_the_model(text, scores, chat)
        if decided is not None:
            return decided

    # Unsure, and nothing to ask. General narrows nothing, so this costs the
    # benefit of routing and never the answer. `secondary` still names what the
    # keywords leaned towards, so a reviewer reading the envelope can see what
    # was nearly chosen — a fallback that records nothing teaches nothing.
    return ScenarioMatch(
        scenario=scenarios.FALLBACK_SCENARIO,
        confidence=confidence,
        method="low-confidence",
        secondary=primary,
        scores=scores,
        evidence=evidence,
    )


def _carried_patient(facts: dict[str, Any] | None) -> str | None:
    """Is this conversation already about one patient?

    Read from the labels `orchestrator._FACT_KEYS` writes, so the referent is
    the server's record of what was queried rather than the model's memory of
    it — the same rule F11 follows for the day.
    """
    if not isinstance(facts, dict):
        return None
    for label in ("patient national code", "reception id", "patient id"):
        if str(facts.get(label) or "").strip():
            return label
    return None


#: The tiebreak prompt. Small on purpose: it is asked only for the questions the
#: deterministic pass could not settle, it gets no tools and no data, and its
#: only job is to name one of six ids. A failure here falls to General, so this
#: call is never on the path to a wrong number.
_TIEBREAK_SYSTEM = (
    "You route a question at a medical imaging centre to ONE workflow.\n"
    "Reply with ONLY a JSON object: {\"scenario\": \"<id>\", \"confidence\": <0..1>}\n"
    "No prose, no markdown fences.\n\n"
    "The ids and what each is for:\n"
)


def _tiebreak_messages(text: str, scores: dict[str, float]) -> list[dict[str, str]]:
    lines = [_TIEBREAK_SYSTEM]
    for scenario in scenarios.all_scenarios():
        lines.append(f"- {scenario.id}: {scenario.intent_fa}")
    lines.append(
        "\nChoose `general` when the question fits none of the others, or fits "
        "two equally and neither leads. Choosing `general` is a valid answer "
        "and costs nothing — a wrong specific id is worse than an honest one."
    )
    hint = ", ".join(f"{k}={v:g}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1]))
    lines.append(f"\nA keyword pass scored: {hint or 'nothing'}. It was not decisive.")
    return [
        {"role": "system", "content": "\n".join(lines)},
        {"role": "user", "content": str(text)[:1000]},
    ]


def _ask_the_model(text: str, scores: dict[str, float], chat: Any) -> ScenarioMatch | None:
    """One small call, and never a reason to fail the question.

    Returns None on anything unexpected — an exception, an unparseable reply, an
    id that is not a scenario. The caller then falls to General, which is the
    behaviour this whole layer degrades to everywhere else.
    """
    import json

    try:
        reply = chat(_tiebreak_messages(text, scores), response_format_json=True)
        payload = json.loads(str((reply or {}).get("content") or ""))
    except Exception as exc:  # noqa: BLE001 - routing must never fail a question
        LOG.warning(
            "scenario tiebreak failed (%s: %s); falling back to general",
            type(exc).__name__,
            exc,
        )
        return None

    if not isinstance(payload, dict):
        return None
    chosen = str(payload.get("scenario") or "").strip().lower()
    if not scenarios.is_known(chosen):
        LOG.warning("scenario tiebreak named an unknown scenario %r; using general", chosen)
        return None

    try:
        confidence = float(payload.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6

    return ScenarioMatch(
        scenario=chosen,
        confidence=max(0.0, min(1.0, confidence)),
        method="llm-tiebreak",
        entities=tuple(scenarios.get(chosen).entities[:2]),
        scores=scores,
        evidence=("tiebreak",),
    )
