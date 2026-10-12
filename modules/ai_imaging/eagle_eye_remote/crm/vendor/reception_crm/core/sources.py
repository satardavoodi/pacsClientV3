"""The source catalog — what each tool reads, and which tools can check it.

Why this exists as data rather than as prose in a prompt
--------------------------------------------------------
Tool descriptions tell the model what a tool is for. They cannot tell the
*orchestrator* anything, because they are strings written for a reader. Three
jobs need machine-readable facts about a source:

* **planning** — which sources could answer this question at all;
* **cross-checking** — which OTHER source publishes the same quantity, so a
  figure can be corroborated rather than merely stated;
* **budgeting** — what a source costs, so a plan that needs four of them can be
  judged before it runs.

Everything here was measured against the live reception system
(`scripts/_study_reports.py`), not read off the API docs. `period` in
particular: an endpoint that accepts a date range, echoes it back and ignores it
is indistinguishable from one that honours it unless you ask for two different
days and compare. One of these already fooled me once.

The measured cost matters more than it looks
---------------------------------------------
Every source here answers in 7-835 ms, and all but one in under 200 ms. A single
LLM round costs 4-18 SECONDS. So fetching four sources is roughly one
fiftieth of the price of one extra round-trip to the model.

That inverts the usual agent design. A strict one-tool-per-round ReAct loop
would spend thirty seconds deciding what a broad plan could have fetched in one.
So the planner chooses a SET of sources per round, and the loop's bound is on
rounds, not on sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..jalali import add_jalali_days, jalali_to_gregorian, normalize_jalali_date

#: Comparable meanings. Two sources publishing the same meaning can check each
#: other -- which is the entire mechanical basis of cross-checking, and the
#: reason these are named by meaning rather than by field name. The reception
#: system calls the patient count `uniquePatients`, `totalPatients`,
#: `patientCount` and `totalDebtors` in four different reports.
PATIENT_COUNT = "patient_count"
RECEPTION_COUNT = "reception_count"
SERVICE_COUNT = "service_count"
GROSS_AMOUNT = "gross_amount"
PATIENT_SHARE = "patient_share"
INSURANCE_SHARE = "insurance_share"
PAID_AMOUNT = "paid_amount"
DEBT = "debt"
DISCOUNT = "discount"
CASH = "cash"
CARD = "card"

#: What each meaning is, in the language the answer is written in. Used when an
#: answer has to explain WHY two sources disagree.
MEANING_FA: dict[str, str] = {
    PATIENT_COUNT: "تعداد بیماران (افراد متمایز)",
    RECEPTION_COUNT: "تعداد پذیرش‌ها (مراجعه‌ها)",
    SERVICE_COUNT: "تعداد خدمات",
    GROSS_AMOUNT: "مبلغ کل",
    PATIENT_SHARE: "سهم بیمار",
    INSURANCE_SHARE: "سهم بیمه",
    PAID_AMOUNT: "مبلغ پرداخت‌شده",
    DEBT: "بدهی",
    DISCOUNT: "تخفیف",
    CASH: "نقدی",
    CARD: "کارتی",
}


@dataclass(frozen=True)
class Source:
    """One tool, described for a planner rather than for a reader."""

    tool: str
    #: One line the planner sees. Deliberately about the QUESTION it answers,
    #: not about the data it returns.
    purpose_fa: str
    #: Question kinds this source is the right answer to. Matched loosely; this
    #: is planning guidance, never a routing table.
    answers: tuple[str, ...] = ()
    #: "date"   — honours a single day or a range (verified by asking twice)
    #: "none"   — reference data; a period changes nothing
    period: str = "date"
    #: Comparable meanings this source publishes at the top level.
    quantities: tuple[str, ...] = ()
    #: Measured round trip against the live system, milliseconds.
    cost_ms: int = 100
    #: Semantic traps. These are the sentences that stop a true number from
    #: answering the wrong question.
    caveats_fa: tuple[str, ...] = ()
    #: Rows this source can return in bulk, and roughly how many. A planner
    #: should know when it is about to ask for a hundred clinical records.
    row_sets: tuple[str, ...] = ()


CATALOG: tuple[Source, ...] = (
    Source(
        tool="cashier-report",
        purpose_fa="گزارش صندوق: دریافتی نقدی/کارتی/بیمه، به تفکیک صندوق‌دار، کارت‌خوان و مودالیتی",
        answers=("گزارش صندوق", "درآمد صندوق", "تفکیک روش پرداخت", "عملکرد صندوق‌داران"),
        period="date",
        quantities=(CASH, CARD, PAID_AMOUNT, DEBT, DISCOUNT, GROSS_AMOUNT, SERVICE_COUNT),
        cost_ms=600,
        caveats_fa=(
            "«تراکنش» در این گزارش یک پرداخت است، نه یک پذیرش و نه یک بیمار.",
            "تراکنش‌های حذف‌شده فقط در بخش مربوط به خود آورده می‌شوند.",
        ),
        row_sets=("by_cashier", "by_modality", "by_card", "insurance_payments"),
    ),
    Source(
        tool="cashier-deleted-transactions",
        purpose_fa=(
            "جزئیات تراکنش‌های حذف‌شدهٔ صندوق، با تفکیک ثبت‌کنندهٔ اصلی تراکنش "
            "و حذف‌کنندهٔ تراکنش"
        ),
        answers=(
            "چه کسی تراکنش حذف کرد",
            "تراکنش حذف‌شدهٔ هر فرد",
            "مبلغ حذف‌ها به تفکیک کاربر",
        ),
        period="date",
        cost_ms=250,
        caveats_fa=(
            "ثبت‌کنندهٔ پذیرش، ثبت‌کنندهٔ تراکنش و حذف‌کنندهٔ تراکنش سه نقش مستقل‌اند.",
            "حذف یک تراکنش به‌تنهایی اثبات خطا یا تخلف نیست.",
        ),
        row_sets=("transactions", "by_original_user", "by_deleted_by"),
    ),
    Source(
        tool="daily-summary",
        purpose_fa="ارقام سرجمع روز: پذیرش، بیمار متمایز، خدمت، درآمد و تفکیک مودالیتی/بیمه",
        answers=("چند بیمار", "چند پذیرش", "خلاصهٔ روز", "درآمد روز"),
        period="date",
        quantities=(PATIENT_COUNT, RECEPTION_COUNT, SERVICE_COUNT, GROSS_AMOUNT,
                    PATIENT_SHARE, INSURANCE_SHARE, PAID_AMOUNT, DEBT, DISCOUNT, CASH, CARD),
        cost_ms=120,
        caveats_fa=(
            "سه عدد متفاوت دارد: بیمار متمایز، پذیرش، خدمت. هر پاسخ باید بگوید کدام را نقل می‌کند.",
        ),
    ),
    Source(
        tool="patient-list",
        purpose_fa="سطرهای پذیرش روز با نام بیمار، ساعت، مودالیتی و مبلغ",
        answers=("لیست بیماران", "چه کسانی پذیرش شدند", "بیماران یک مودالیتی"),
        period="date",
        quantities=(SERVICE_COUNT,),
        cost_ms=120,
        caveats_fa=(
            "هر سطر یک خدمت است، نه یک پذیرش و نه یک بیمار؛ شمار سطرها با تعداد پذیرش برابر نیست.",
        ),
        row_sets=("patients",),
    ),
    Source(
        tool="financial-analysis",
        purpose_fa="درآمد بازه به تفکیک پرداخت‌کننده: سهم بیمار، هر بیمه، تخفیف، بدهی، تسویه‌شده/نشده",
        answers=("درآمد بازه", "سهم بیمه‌ها", "بدهی و تسویه"),
        period="date",
        quantities=(GROSS_AMOUNT, PATIENT_SHARE, INSURANCE_SHARE, PAID_AMOUNT, DEBT, DISCOUNT, CASH, CARD),
        cost_ms=120,
    ),
    Source(
        tool="cashier-reconciliation",
        purpose_fa="تطبیق دریافتی صندوق با آنچه پذیرش‌های همان روز باید تولید می‌کرد، و علت‌های محتمل اختلاف",
        answers=("مغایرت صندوق", "ناسازگاری مالی", "آیا صندوق می‌خواند"),
        period="date",
        quantities=(PAID_AMOUNT, DEBT, DISCOUNT),
        cost_ms=220,
        caveats_fa=(
            "این گزارشِ صندوق نیست؛ یک بررسی اختلاف است و خودش تفسیر تولید می‌کند.",
        ),
        row_sets=("high_risk_receptions", "possible_causes"),
    ),
    Source(
        tool="physician-performance",
        purpose_fa="حجم کاری و درآمد هر پزشک گزارش‌دهنده در یک بازه، مرتب‌شده",
        answers=("حجم کاری پزشکان", "کدام پزشک بیشترین", "مقایسهٔ پزشکان"),
        period="date",
        quantities=(PATIENT_COUNT, GROSS_AMOUNT, PATIENT_SHARE, INSURANCE_SHARE, PAID_AMOUNT, DISCOUNT),
        cost_ms=30,
        caveats_fa=(
            "بیمارانِ منتسب به پزشک گزارش‌دهنده را می‌شمارد، نه کل پذیرش‌های روز؛ این عدد کوچک‌تر است.",
        ),
        row_sets=("physicians",),
    ),
    Source(
        tool="risk-analysis",
        purpose_fa="پذیرش‌های پرریسک مالی بازه، گروه‌بندی‌شده و با سطرهای پرریسک",
        answers=("موارد پرریسک", "چه چیزی را بررسی کنم"),
        period="date",
        quantities=(GROSS_AMOUNT, RECEPTION_COUNT),
        cost_ms=220,
        row_sets=("high_risk_receptions",),
    ),
    Source(
        tool="trend-analysis",
        purpose_fa="مقایسهٔ یک روز با دیروز، هفتهٔ گذشته یا ماه گذشته",
        answers=("نسبت به دیروز", "روند", "بیشتر یا کمتر شده"),
        period="date",
        quantities=(RECEPTION_COUNT, SERVICE_COUNT, GROSS_AMOUNT, PATIENT_SHARE),
        # Two full daily summaries, so twice the cost of one.
        cost_ms=250,
    ),
    Source(
        tool="reporting-queue",
        purpose_fa="صف گزارش‌نویسی: مطالعاتی که منتظر گزارش یا تأیید هستند",
        answers=("صف گزارش", "چه چیزی گزارش نشده"),
        period="date",
        cost_ms=150,
        row_sets=("items",),
    ),
    Source(
        tool="report.archive-stats",
        purpose_fa="پوشش آرشیو گزارش‌ها: چند پذیرش گزارش دارد و چند مورد تأیید پزشک",
        answers=("چقدر گزارش شده", "پوشش آرشیو"),
        period="none",
        cost_ms=200,
    ),
    Source(
        tool="patients.search",
        purpose_fa="یافتن بیمار با نام یا کد ملی و بازگرداندن شناسه‌ها",
        answers=("این بیمار کیست", "پیدا کردن بیمار"),
        period="none",
        cost_ms=150,
    ),
    Source(
        tool="report.history",
        purpose_fa="همهٔ گزارش‌های یک بیمار، از جدید به قدیم، به‌صورت متن کامل",
        answers=("گزارش‌های این بیمار", "سابقهٔ بیمار", "مقایسهٔ گزارش‌ها"),
        period="none",
        cost_ms=400,
        row_sets=("reports",),
    ),
    Source(
        tool="report.search",
        purpose_fa="جست‌وجوی متن همهٔ گزارش‌ها برای یک عبارت یا یافته",
        answers=("بیماران با یافتهٔ خاص", "جست‌وجوی گزارش"),
        period="date",
        cost_ms=500,
        caveats_fa=(
            "متن گزارش‌ها لاتین است؛ عبارت فارسی باید به لاتین برگردانده شود وگرنه «۰ نتیجه» می‌دهد.",
        ),
        row_sets=("results",),
    ),
    Source(
        tool="reception.search",
        purpose_fa="شمارش پذیرش‌ها بر اساس خدمت، مودالیتی، بیمه و وضعیت گزارش",
        answers=("چند تا ماموگرافی", "چند تا ام آر آی مغز", "بیماران بیمه‌ای با سی تی"),
        period="date",
        quantities=(PATIENT_COUNT, RECEPTION_COUNT, SERVICE_COUNT),
        cost_ms=700,
        caveats_fa=(
            "مودالیتی نوع دستگاه است و خدمت نوع عمل؛ ماموگرافی و سنجش تراکم استخوان "
            "را باید با فیلتر «خدمت» شمرد، نه مودالیتی.",
            "فیلتر خدمت ایندکس ندارد، پس بازهٔ تاریخ الزامی است.",
        ),
        row_sets=("rows",),
    ),
    Source(
        tool="reception.vocabulary",
        purpose_fa="فهرست مقادیر واقعی یک فیلد — مودالیتی‌ها، خدمت‌ها، بیمه‌ها، وضعیت‌ها",
        answers=("چه مودالیتی‌هایی داریم", "چه خدمتی به این نام هست"),
        period="none",
        cost_ms=50,
        caveats_fa=(
            "پاسخ «۰ مورد» را قبل از گزارش کردن با این ابزار بررسی کنید: "
            "معمولاً یعنی مقدار فیلتر وجود ندارد، نه اینکه بیماری وجود ندارد.",
        ),
        row_sets=("values",),
    ),
)

_BY_TOOL: dict[str, Source] = {s.tool: s for s in CATALOG}


# --------------------------------------------------------------------------- #
# Comparing one source against another
# --------------------------------------------------------------------------- #
#: Where each meaning lives in OUR normalised output, per tool.
#:
#: Deliberately hand-written rather than derived from field names. An automatic
#: mapping matched `totalTransactions` in the cashier report to
#: `total_services` in the daily summary because both were "counts of things
#: that happened" -- but a transaction is a PAYMENT and a service is a
#: PROCEDURE, and asserting those should be equal would have produced a
#: confident daily inconsistency that does not exist.
#:
#: A cross-checker that compares two different meanings is worse than no
#: cross-checker: it is wrong in the direction people act on.
FIELD_PATHS: dict[str, dict[str, str]] = {
    "daily-summary": {
        PATIENT_COUNT: "admissions.unique_patients",
        RECEPTION_COUNT: "admissions.total_receptions",
        SERVICE_COUNT: "admissions.total_services",
        GROSS_AMOUNT: "financial.total_amount",
        PATIENT_SHARE: "financial.patient_share",
        INSURANCE_SHARE: "financial.insurance_share",
        PAID_AMOUNT: "financial.paid_amount",
        DEBT: "financial.patient_debt",
        DISCOUNT: "financial.cash_desk_discount",
        CASH: "financial.cash",
        CARD: "financial.card",
    },
    "financial-analysis": {
        GROSS_AMOUNT: "revenue.total_amount",
        PATIENT_SHARE: "revenue.patient_share",
        INSURANCE_SHARE: "revenue.insurance_share",
        PAID_AMOUNT: "debt_and_discounts.paid_amount",
        DEBT: "debt_and_discounts.patient_debt",
        DISCOUNT: "debt_and_discounts.cash_desk_discount",
        CASH: "cashier.cash",
        CARD: "cashier.card",
    },
    "cashier-report": {
        CASH: "payment_details.totalCashPayments",
        CARD: "payment_details.totalCardPayments",
    },
    "patient-list": {
        SERVICE_COUNT: "count",
    },
    "cashier-reconciliation": {
        DEBT: "supporting_financials.patient_debt",
        DISCOUNT: "supporting_financials.discount",
        PAID_AMOUNT: "expected_vs_actual.expected_patient_cash_card_for_report_receptions",
    },
    # Only comparable when the search was NOT narrowed — a filtered search
    # counts a subset of the day. `compare()` guards on the period; the
    # unfiltered-ness is guarded by only listing these when no filter was
    # applied, which `_period_of` cannot see, so the pairing below is
    # deliberately absent from COMPARISONS. These paths exist so the meanings
    # are addressable and publishable, not so they are cross-checked blind.
    "reception.search": {
        PATIENT_COUNT: "totals.patients",
        RECEPTION_COUNT: "totals.receptions",
        SERVICE_COUNT: "totals.serviceLines",
    },
    "physician-performance": {
        # NOT the day's patient count. Kept out of the equality comparisons and
        # used only in the `AT_MOST` relation below.
        "attributed_patients": "totals.patients",
    },
}

EQUAL = "equal"
AT_MOST = "at_most"


@dataclass(frozen=True)
class Comparison:
    """Two sources that should agree about one quantity, and how."""

    meaning: str
    left: str
    right: str
    relation: str = EQUAL
    #: The field on the RIGHT, when the two sides call it different things.
    #:
    #: An equality compares one quantity in two places, so one key serves both.
    #: A containment does not: "patients attributed to a physician" and "the
    #: day's patients" are deliberately different meanings — that is the whole
    #: point of the relation — and using one key for both silently found no
    #: field on the right and skipped the check entirely. It sat in the table
    #: looking like a comparison that passes.
    right_meaning: str = ""
    #: Why they should agree — shown when they do not, because "these two
    #: numbers differ" is only useful with "and here is why that is odd".
    because_fa: str = ""
    #: Does this compare two SEPARATE measurements, or one measurement read
    #: twice?
    #:
    #: `daily-summary` and `financial-analysis` are two views of the same
    #: upstream computation. Comparing them is worth doing — it catches a
    #: normaliser drifting — but it verifies nothing about the figure itself,
    #: and the phone rendered it with the same ✔ as a real cross-check. An
    #: owner reading four green ticks believed four independent confirmations
    #: where three were tautological by construction.
    #:
    #: A control that cannot be told apart from a stronger control is not the
    #: control people think it is.
    independent: bool = True

    @property
    def right_key(self) -> str:
        return self.right_meaning or self.meaning


#: Only pairs I am confident mean the same thing, for the same period.
COMPARISONS: tuple[Comparison, ...] = (
    # Same upstream report, read through two different tools. These must agree;
    # if they ever do not, one of our normalisers has drifted.
    Comparison(GROSS_AMOUNT, "daily-summary", "financial-analysis",
               independent=False,
               because_fa="هر دو از گزارش خدمات/بیمهٔ همان روز خوانده می‌شوند"),
    Comparison(PAID_AMOUNT, "daily-summary", "financial-analysis",
               independent=False,
               because_fa="هر دو مبلغ پرداخت‌شدهٔ همان روز هستند"),
    Comparison(DEBT, "daily-summary", "financial-analysis",
               independent=False,
               because_fa="هر دو بدهی بیمار همان روز هستند"),
    Comparison(SERVICE_COUNT, "daily-summary", "patient-list",
               because_fa="هر سطر فهرست بیماران یک خدمت است"),

    # The valuable ones: two DIFFERENT endpoints describing the same till.
    Comparison(CASH, "daily-summary", "cashier-report",
               because_fa="هر دو دریافت نقدی همان روز را گزارش می‌کنند"),
    Comparison(CARD, "daily-summary", "cashier-report",
               because_fa="هر دو دریافت کارتی همان روز را گزارش می‌کنند"),

    # A containment, not an equality: patients attributed to a reporting
    # physician are a subset of the day's patients. Asserting equality here
    # would report a mismatch every single day.
    Comparison("attributed_patients", "physician-performance", "daily-summary",
               relation=AT_MOST, right_meaning=PATIENT_COUNT,
               because_fa="بیماران منتسب به پزشک زیرمجموعهٔ بیماران روز هستند"),
)


def _dig(payload: Any, path: str) -> Any:
    node = payload
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _period_of(item: dict) -> str:
    """The window a fetched payload actually covers.

    Two sources are only comparable when they describe the same days. Reading
    it from the DATA rather than from the requested arguments, because the
    period a report returns is the one it honoured -- and at least one endpoint
    here echoes back a period it ignored.
    """
    data = item.get("data")
    period = _dig(data, "period") if isinstance(data, dict) else None
    if isinstance(period, dict):
        return f"{period.get('start_date')}..{period.get('end_date')}"
    args = item.get("arguments") or {}
    return f"args:{args.get('date')}:{args.get('days')}"


def compare(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check the figures two sources both report, arithmetically.

    Returns one entry per comparison actually possible: both sources fetched,
    both for the same period, both carrying the field. Everything else is
    silently not a finding -- an absent comparison must never be reported as a
    passed one.

    This exists because "did you notice these disagree?" is a question a model
    answers correctly most of the time, and a missed mismatch is silent: the
    answer simply does not mention it and reads as though everything agreed.
    """
    by_tool: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if item.get("ok") and isinstance(item.get("data"), dict):
            by_tool.setdefault(str(item.get("tool")), item)

    findings: list[dict[str, Any]] = []
    for check in COMPARISONS:
        left, right = by_tool.get(check.left), by_tool.get(check.right)
        if not left or not right:
            continue
        if _period_of(left) != _period_of(right):
            continue

        left_path = FIELD_PATHS.get(check.left, {}).get(check.meaning)
        right_path = FIELD_PATHS.get(check.right, {}).get(check.right_key)
        if not left_path or not right_path:
            continue

        a = _number(_dig(left["data"], left_path))
        b = _number(_dig(right["data"], right_path))
        if a is None or b is None:
            continue

        if check.relation == AT_MOST:
            agrees = a <= b
        else:
            agrees = a == b

        findings.append(
            {
                "quantity": MEANING_FA.get(check.meaning, check.meaning),
                "relation": check.relation,
                "agrees": agrees,
                # Published so the reader can tell a real corroboration from a
                # self-consistency check. Without it, three tautological ticks
                # and one genuine one looked identical on the phone.
                "independent": check.independent,
                "kind_fa": ("راستی‌آزمایی با منبع مستقل" if check.independent
                            else "بررسی سازگاری دو نمای یک منبع"),
                "left": {"tool": check.left, "value": a},
                "right": {"tool": check.right, "value": b},
                "difference": None if check.relation == AT_MOST else a - b,
                "because_fa": check.because_fa,
                "period": _period_of(left),
            }
        )
    return findings


def plan_corroboration(
    fetched: list[str],
    *,
    available: set[str],
    arguments: dict[str, Any] | None = None,
    limit: int = 2,
) -> list[tuple[str, dict[str, Any], str]]:
    """Which one more source would let a defined comparison actually run.

    The catalog already knows that `cashier-report` and `daily-summary` both
    report the day's cash. Spending an LLM round to rediscover that is six
    seconds to learn something written down here — and worse, the model does
    not reliably pick it: told to stop reaching on retrieval questions, it
    stopped fetching the corroborating source too, and the cash/card
    cross-check that had found a 43,710,000 discrepancy silently stopped
    firing. The capability was traded away by a prompt edit and nothing said so.

    So the server plans corroboration itself. It is nearly free — a report
    answers in 7-835 ms against 4-18 s for a model round — and unlike a prompt
    it cannot change its mind.
    """
    have = set(fetched)
    if not have:
        return []

    # Carry the primary call's period, or the corroborating source answers
    # about a different day and `compare()` correctly refuses to use it.
    period_args = {k: v for k, v in (arguments or {}).items() if k in ("date", "days")}

    out: list[tuple[str, dict[str, Any], str]] = []
    seen: set[str] = set()
    for check in COMPARISONS:
        pair = (check.left, check.right)
        if not (have & set(pair)) or have.issuperset(pair):
            continue
        missing = check.right if check.left in have else check.left
        if missing in seen or missing not in available or missing in have:
            continue
        seen.add(missing)
        other = check.left if missing == check.right else check.right
        out.append((
            missing,
            dict(period_args),
            f"corroborates {MEANING_FA.get(check.meaning, check.meaning)} against {other}",
        ))
        if len(out) >= limit:
            break
    return out


def plan_required_coverage(
    text: str,
    fetched: list[tuple[str, dict[str, Any]]],
    *,
    available: set[str],
    argument_sets: list[dict[str, Any]] | None = None,
    limit: int = 4,
) -> list[tuple[str, dict[str, Any], str]]:
    """Deterministically fetch sources explicitly required by a compound ask.

    The sufficiency model remains useful for open-ended analysis, but it is not
    an enforcement mechanism.  A live two-turn cashier question explicitly
    requested three per-person measures and the model declared four nearby
    sources sufficient while omitting the only two sources that could provide
    reception counts and deletion actors.  This guard covers only concepts the
    user names directly; it does not speculate or broaden the investigation.

    Actor roles are deliberately separate.  A grouped reception search speaks
    about the reception creator, risk rows retain that same association, and
    the deleted-transaction source separately reports transaction registrar and
    deletion actor.  Nothing here joins those roles or labels any event an
    error.
    """
    question = " ".join(str(text or "").lower().replace("\u200c", " ").split())
    if not question:
        return []

    per_person = any(
        phrase in question
        for phrase in (
            "هر فرد", "هر نفر", "هر کاربر", "هر کارمند", "هر صندوق دار",
            "جداگانه", "به تفکیک فرد", "به تفکیک کاربر", "به تفکیک صندوق دار",
        )
    )
    mentions_receptions = "پذیرش" in question
    mentions_risk = "ریسک" in question or "پرخطر" in question
    mentions_deleted_transactions = (
        any(stem in question for stem in ("حذف", "ابطال"))
        and any(stem in question for stem in ("تراکنش", "پرداخت صندوق", "سند صندوق"))
    )

    period = _coverage_period(argument_sets or [args for _, args in fetched])
    present_tools = {tool for tool, _ in fetched}
    has_cashier_reception_breakdown = any(
        tool == "reception.search" and args.get("groupBy") == "cashier"
        for tool, args in fetched
    )

    wanted: list[tuple[str, dict[str, Any], str]] = []
    if per_person and mentions_receptions and not has_cashier_reception_breakdown:
        wanted.append((
            "reception.search",
            {**period["range"], "groupBy": "cashier", "limit": 1},
            "the user explicitly requested reception counts per reception creator",
        ))
    if per_person and mentions_risk and "risk-analysis" not in present_tools:
        wanted.append((
            "risk-analysis",
            dict(period["report"]),
            "the user explicitly requested risk counts per associated reception creator",
        ))
    if mentions_deleted_transactions and "cashier-deleted-transactions" not in present_tools:
        wanted.append((
            "cashier-deleted-transactions",
            dict(period["report"]),
            "the user explicitly requested deleted-transaction actors and counts",
        ))

    return [call for call in wanted if call[0] in available][: max(0, limit)]


def _coverage_period(argument_sets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Translate the period already chosen in this turn across tool schemas."""
    start: str | None = None
    end: str | None = None
    report_date: str | None = None
    days = 1

    # Prefer an explicit range because local Mongo tools require concrete
    # Jalali bounds.  The interpreter commonly emits a report-style `date` for
    # one source and dateFrom/dateTo for another in the same plan.
    for args in argument_sets:
        if args.get("dateFrom") or args.get("dateTo"):
            start = str(args.get("dateFrom") or args.get("dateTo"))
            end = str(args.get("dateTo") or args.get("dateFrom"))
            break
    for args in argument_sets:
        if args.get("date"):
            report_date = str(args["date"])
            try:
                days = max(1, int(args.get("days", 1)))
            except (TypeError, ValueError):
                days = 1
            break

    if start or end:
        start_j = normalize_jalali_date(start or end)
        end_j = normalize_jalali_date(end or start)
        return {
            "range": {"dateFrom": start_j, "dateTo": end_j},
            # Report tools use an end date plus an inclusive day count.
            "report": {
                "date": end_j,
                "days": max(1, (jalali_to_gregorian(end_j) -
                                 jalali_to_gregorian(start_j)).days + 1),
            },
        }

    end_j = normalize_jalali_date(report_date)
    start_j = add_jalali_days(end_j, -(days - 1))
    report_args: dict[str, Any] = {"date": report_date or "today"}
    if days > 1:
        report_args["days"] = days
    return {
        "range": {"dateFrom": start_j, "dateTo": end_j},
        "report": report_args,
    }


def format_comparisons(findings: list[dict[str, Any]]) -> str:
    """The server's verdicts, for the answer-writing call.

    Stated as settled facts because they are: this is arithmetic the server did
    on two payloads, not something the model should re-derive or second-guess.
    """
    if not findings:
        return ""
    lines = [
        "# راستی‌آزمایی خودکار (توسط سرور انجام شده)",
        "",
        "این مقایسه‌ها را سرور روی داده‌های واقعی انجام داده است. نتیجه قطعی است؛",
        "آن را دوباره محاسبه نکن و زیر سؤال نبر. اگر مغایرتی هست، در پاسخ بیاور.",
        "",
        # Added after the agent reported a "contradiction" between a daily
        # summary for 1405/06/02 and a search for 1405/06/01. The server's
        # comparator already refuses to compare different periods; the model
        # wrote the contradiction in prose anyway. Only the checks below are
        # contradictions.
        "⚠ فقط همین موارد مغایرت‌اند. اگر دو منبع بازهٔ زمانی متفاوتی دارند،",
        "اختلافشان مغایرت نیست — دو روزِ متفاوت‌اند. پیش از نوشتن «ناسازگاری»،",
        "بازهٔ هر منبع را با هم بسنج.",
        "",
    ]
    for f in findings:
        left, right = f["left"], f["right"]
        if f["agrees"]:
            lines.append(
                f"- ✔ {f['quantity']}: «{left['tool']}» و «{right['tool']}» می‌خوانند "
                f"({left['value']:,.0f})."
            )
        elif f["relation"] == AT_MOST:
            lines.append(
                f"- ✘ {f['quantity']}: «{left['tool']}» عدد {left['value']:,.0f} دارد که از "
                f"«{right['tool']}» ({right['value']:,.0f}) بیشتر است — {f['because_fa']}."
            )
        else:
            lines.append(
                f"- ✘ {f['quantity']}: «{left['tool']}» عدد {left['value']:,.0f} و "
                f"«{right['tool']}» عدد {right['value']:,.0f} می‌دهد؛ اختلاف "
                f"{abs(f['difference']):,.0f}. {f['because_fa']}."
            )
    return "\n".join(lines)


def get(tool: str) -> Source | None:
    return _BY_TOOL.get(tool)


def known(tool: str) -> bool:
    return tool in _BY_TOOL


def corroborators(tool: str, *, among: set[str] | None = None) -> dict[str, list[str]]:
    """Which other sources publish a quantity this one also publishes.

    The answer to "what could check this figure". Restricted to `among` when the
    caller knows which tools the current mode actually offers -- suggesting a
    corroboration the mode cannot perform would be worse than suggesting none,
    because the plan would look complete and quietly skip a step.
    """
    source = _BY_TOOL.get(tool)
    if source is None:
        return {}
    out: dict[str, list[str]] = {}
    for meaning in source.quantities:
        others = [
            s.tool
            for s in CATALOG
            if s.tool != tool and meaning in s.quantities and (among is None or s.tool in among)
        ]
        if others:
            out[meaning] = others
    return out


def catalog_for(tools: list[dict] | list[str]) -> list[Source]:
    """The catalog entries for an already permission- and mode-filtered list.

    Order follows CATALOG, not the caller's list, so the planner sees a stable
    menu -- a menu whose order changes between turns invites a different plan
    for the same question.
    """
    names = {t["name"] if isinstance(t, dict) else str(t) for t in tools}
    return [s for s in CATALOG if s.tool in names]


def describe_for_prompt(sources: list[Source]) -> str:
    """The catalog as the planner sees it.

    Compact on purpose: this block is sent on every planning call, and every
    line here competes with the conversation and the data for the same budget.
    """
    if not sources:
        return ""
    lines = ["# SOURCE CATALOG", ""]
    for s in sources:
        period = {"date": "بازهٔ تاریخی می‌گیرد", "none": "بازهٔ تاریخی ندارد"}.get(s.period, s.period)
        lines.append(f"- **{s.tool}** — {s.purpose_fa} ({period})")
        if s.answers:
            lines.append(f"  - پاسخ می‌دهد به: {'، '.join(s.answers)}")
        for caveat in s.caveats_fa:
            lines.append(f"  - ⚠ {caveat}")
    return "\n".join(lines)


def cross_check_map(sources: list[Source]) -> str:
    """Which sources can corroborate which, as a block for the planner.

    Only meanings carried by two or more of the AVAILABLE sources appear: a
    corroboration the current mode cannot perform is noise that makes a plan
    look more thorough than it can be.
    """
    by_meaning: dict[str, list[str]] = {}
    for s in sources:
        for meaning in s.quantities:
            by_meaning.setdefault(meaning, []).append(s.tool)
    pairs = {m: t for m, t in by_meaning.items() if len(t) > 1}
    if not pairs:
        return ""
    lines = [
        "# CROSS-CHECKS AVAILABLE",
        "",
        "هر سطر یک کمیت است و منابعی که آن را گزارش می‌کنند. برای راستی‌آزمایی یک رقم،",
        "می‌توان آن را از منبع دیگری در همان سطر گرفت و مقایسه کرد.",
        "",
    ]
    for meaning, tools in sorted(pairs.items()):
        lines.append(f"- {MEANING_FA.get(meaning, meaning)}: {'، '.join(tools)}")
    return "\n".join(lines)
