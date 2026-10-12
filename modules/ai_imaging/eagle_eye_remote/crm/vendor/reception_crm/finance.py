"""The financial lexicon: what every money number MEANS, as data not prose.

A financial answer is only as good as the question the number answers. This
module is the authority on that mapping — one normalized metric name per
business concept, each carrying its source, its exact field path, its date
basis, its formula, and the metrics it is most often confused with.

It exists because a document cannot be consulted at query time. The agent once
answered «بیمارها چقدر بدهکار موندن؟» with `withdrawals.receptionDebt` —
7,099,560,000 against a true balance of 2.3bn — while a document three files
away said in plain words that this field is not a debt. **Meaning has to be
reachable from where the decision is made.**

Every entry was verified on 1405/06/02 against three sources: the reception
software's own screens, its REST endpoints, and MongoDB — and, for the
identities, against all 220 receptions of the day individually rather than one
worked example. `confidence` records how firmly, and `NOTES` records what is
still open. Nothing here is inferred from a UI label.

The two rules everything rests on:

* **Money that has MOVED is transaction-dated; money that is OWED is
  reception-dated.** A payment today against last week's reception belongs to
  today's till and last week's receptions. The difference between those two
  totals is not a discrepancy.
* **There are two revenue bases**, and every derived patient figure inherits the
  split: the SERVICE basis (what the vendor's screens show) and the RECEPTION
  basis (which adds consumables). Neither is wrong; an answer that does not say
  which is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lexicon.normalize import squash

#: Date bases. The Query Planner must choose one deliberately; there is no
#: sensible default, because the same words pick different ones.
RECEPTION_DATE = "reception_date"
TRANSACTION_DATE = "transaction_date"

#: Aggregation levels a metric can exist at.
LEVEL_DAY = "day"
LEVEL_RECEPTION = "reception"
LEVEL_SERVICE = "service"
LEVEL_TRANSACTION = "transaction"


class UnknownMetric(ValueError):
    """The requested metric is not in the lexicon.

    Raised rather than guessed. A financial metric resolved by similarity is how
    a plausible wrong number reaches a person who will act on it.
    """

    code = "UNKNOWN_METRIC"

    def __init__(self, asked: str, known: list[str]) -> None:
        super().__init__(f"no financial metric named {asked!r}")
        self.asked = asked
        self.known = known

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "known_metrics": self.known,
            "message_fa": (
                "این شاخص مالی در واژه‌نامه تعریف نشده است. برای پاسخ مالی، شاخص باید "
                "تعریف‌شده باشد — عدد حدسی بدتر از نبودِ عدد است."
            ),
        }


class WrongDateBasis(ValueError):
    """The caller asked for a metric on a basis it does not have."""

    code = "WRONG_DATE_BASIS"

    def __init__(self, metric: str, asked: str, actual: str) -> None:
        super().__init__(
            f"{metric} is {actual}; it cannot be reported on {asked}"
        )
        self.metric, self.asked, self.actual = metric, asked, actual

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "metric": self.metric,
            "requested_basis": self.asked,
            "actual_basis": self.actual,
            "message_fa": (
                "مبنای تاریخ این شاخص با آنچه خواسته شده یکی نیست. «پولی که جابه‌جا شده» "
                "بر مبنای تاریخ تراکنش است و «پولی که بدهکار است» بر مبنای تاریخ پذیرش؛ "
                "این دو را نباید جابه‌جا گرفت."
            ),
        }


@dataclass(frozen=True)
class Metric:
    """One financial concept, pinned to one source field."""

    name: str
    fa: str
    definition_en: str
    definition_fa: str
    level: str
    date_basis: str
    source_tool: str
    #: Dotted path inside that tool's payload. The single most useful field
    #: here: it is what turns "revenue" into something checkable.
    source_path: str
    calculated: bool = False
    formula: str = ""
    #: Signed components, for a metric no single tool exposes but arithmetic over
    #: other metrics does. `(("reception_total_value", 1), ("service_value", -1))`
    #: reads as reception_total_value − service_value.
    #:
    #: ⚠️ This exists because "no tool exposes it" was being reported as "the
    #: number cannot be known", and that is a different and much weaker claim.
    #: `consumables_value` was the whole 267,650,000 difference between the two
    #: revenue bases, sitting one subtraction away from two metrics that both
    #: had sources, and the agent answered seven questions with a patient debt
    #: that omitted it. A component list is checkable in a way that asking the
    #: model to do the subtraction is not.
    components: tuple[tuple[str, int], ...] = ()
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    #: The metrics this one is most often mistaken for, and why that matters.
    not_to_be_confused_with: tuple[str, ...] = ()
    validation: str = ""
    #: high  — verified against screen, API and database, identity tested per record
    #: medium — verified against two of the three, or via a proxy field
    #: low   — meaning inferred, not yet confirmed against a second source
    confidence: str = "high"
    example_1405_06_02: int | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.name,
            "label_fa": self.fa,
            "meaning_en": self.definition_en,
            "meaning_fa": self.definition_fa,
            "level": self.level,
            "date_basis": self.date_basis,
            "source": {"tool": self.source_tool, "path": self.source_path},
            "calculated": self.calculated,
            "formula": self.formula or None,
            "components": [
                {"metric": name, "sign": sign} for name, sign in self.components
            ] or None,
            "related": list(self.related),
            "not_to_be_confused_with": list(self.not_to_be_confused_with),
            "validation": self.validation or None,
            "confidence": self.confidence,
            "example_1405_06_02": self.example_1405_06_02,
            "notes": self.notes or None,
        }


# --------------------------------------------------------------------------- #
# The catalogue.
#
# Ordered by the question a person actually asks: how many, what was billed,
# who owes what, what arrived.
# --------------------------------------------------------------------------- #

METRICS: tuple[Metric, ...] = (
    # ---------------------------------------------------------------- counting
    Metric(
        name="reception_count",
        fa="تعداد پذیرش",
        definition_en="Visits registered in the period. One patient may have several.",
        definition_fa="تعداد پذیرش‌های ثبت‌شده در بازه. یک بیمار می‌تواند چند پذیرش داشته باشد.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="admissions.total_receptions",
        aliases=("پذیرش", "تعداد پذیرش", "چند پذیرش", "receptions", "admissions"),
        related=("patient_count", "service_count"),
        not_to_be_confused_with=("patient_count", "service_count"),
        validation="219 on 1405/06/02, agreeing across dashboard, service report and DB",
        example_1405_06_02=220,
    ),
    Metric(
        name="patient_count",
        fa="تعداد بیماران",
        definition_en="Distinct people. Always ≤ reception_count.",
        definition_fa="تعداد افراد یکتا. همیشه کمتر یا مساوی تعداد پذیرش است.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="admissions.unique_patients",
        aliases=("بیمار", "تعداد بیماران", "چند بیمار", "patients", "unique patients"),
        related=("reception_count",),
        not_to_be_confused_with=("reception_count",),
        validation="213 on 1405/06/02",
        example_1405_06_02=214,
        notes=("⚠️ `uniquePatients` inside a GROUPED breakdown is not this — in "
               "by_modality and in the vendor's rawStats it equals the reception "
               "count of the bucket. Distinct people exist only at the top level."),
    ),
    Metric(
        name="service_count",
        fa="تعداد خدمات",
        definition_en="Procedure lines. One reception may carry several.",
        definition_fa="تعداد خطوط خدمت. یک پذیرش می‌تواند چند خدمت داشته باشد.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="admissions.total_services",
        aliases=("خدمت", "تعداد خدمات", "چند خدمت", "services", "procedures"),
        related=("reception_count",),
        not_to_be_confused_with=("reception_count",),
        validation="267 on 1405/06/02; 175 receptions had 1 service, 42 had 2, 3 had 3",
        example_1405_06_02=267,
    ),

    # ------------------------------------------------------------- what was billed
    Metric(
        name="service_value",
        fa="ارزش خدمات",
        definition_en=("What the SERVICES were worth: tariff x quantity, summed over "
                       "service lines. This is the figure the reception software's own "
                       "Service & Insurance report calls «جمع کل درآمد»."),
        definition_fa=("ارزش خدمات انجام‌شده: تعرفه ضربدر تعداد، جمع روی خطوط خدمت. "
                       "همان عددی که گزارش خدمت و بیمهٔ نرم‌افزار نشان می‌دهد."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.total_amount",
        calculated=True, formula="Σ services[].PrivateTariff × services[].Qty",
        aliases=("درآمد", "جمع کل درآمد", "مبلغ خدمات", "ارزش خدمات", "revenue", "service value"),
        related=("reception_total_value", "consumables_value", "patient_liability",
                 "insurance_liability"),
        not_to_be_confused_with=("reception_total_value", "cashier_received_total",
                                 "patient_paid_amount"),
        validation=("6,833,900,000 on 1405/06/02 across screen, API and DB. Billed, "
                    "not collected."),
        example_1405_06_02=6_833_900_000,
    ),
    Metric(
        name="reception_total_value",
        fa="مبلغ کل پذیرش",
        definition_en=("What the RECEPTIONS were worth: service value PLUS consumables. "
                       "This is the figure the software's home Dashboard shows."),
        definition_fa=("مبلغ کل پذیرش‌ها: ارزش خدمات به‌علاوهٔ ملزومات مصرفی. "
                       "همان عددی که داشبورد نرم‌افزار نشان می‌دهد."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="cashier-report", source_path="withdrawals.receptionDebt.amount",
        calculated=True, formula="Σ receptions.totalAmount = service_value + consumables_value",
        aliases=("مبلغ پذیرش", "مبلغ کل پذیرش", "جمع مبلغ پذیرش‌ها", "reception value"),
        related=("service_value", "consumables_value"),
        not_to_be_confused_with=("service_value", "cashier_received_total"),
        validation=("Identity `totalAmount = Σ(tariff×qty) + inventoryTotalAmount` holds "
                    "EXACTLY on 220 of 220 receptions of 1405/06/02 — tested per record, "
                    "not in aggregate."),
        confidence="medium",
        example_1405_06_02=7_101_550_000,
        notes=("Reached through a PROXY: no tool exposes it directly. "
               "`cashier-report.withdrawals.receptionDebt.amount` tracks it — the two "
               "agree to within one 10,000 rounding record, see `consumables_value` "
               "notes. A first-class field is the recommended fix.\n"
               "⚠️ The example was re-measured at the END of 1405/06/02 over all 220 "
               "live receptions. The earlier 7,099,550,000 was captured while the day "
               "was still running, and every worked example taken that morning — "
               "receptions 219, unsettled 68, patient debt 2,313,020,000 — was a "
               "half-finished day recorded as if it were a closed one."),
    ),
    Metric(
        name="consumables_value",
        fa="ملزومات مصرفی",
        definition_en=("Materials billed on the reception that are not part of any "
                       "service tariff. The whole difference between the two revenue "
                       "bases."),
        definition_fa=("ملزومات مصرفی که روی پذیرش ثبت می‌شود و جزو تعرفهٔ خدمت نیست؛ "
                       "تمام تفاوت دو مبنای درآمد از همین است."),
        level=LEVEL_RECEPTION, date_basis=RECEPTION_DATE,
        source_tool="", source_path="receptions.inventoryTotalAmount",
        calculated=True, formula="reception_total_value − service_value",
        components=(("reception_total_value", 1), ("service_value", -1)),
        aliases=("ملزومات", "مصرفی", "consumables", "inventory"),
        related=("service_value", "reception_total_value"),
        not_to_be_confused_with=("discount_amount",),
        validation=("267,650,000 on 1405/06/02, measured over all 220 live receptions "
                    "directly in Mongo — the exact gap between the Dashboard and the "
                    "Service report, and the exact gap between the two patient bases."),
        confidence="medium",
        example_1405_06_02=267_650_000,
        notes=("No tool exposes the field, so it is DERIVED from the two revenue bases, "
               "both of which have sources. Still recommended as a first-class field: a "
               "derivation costs two source calls and inherits both their date windows."),
    ),

    # --------------------------------------------------------------- who owes what
    Metric(
        name="patient_liability",
        fa="سهم بیمار",
        definition_en=("What patients OWE for the period's receptions, after insurance "
                       "and discount. A liability, not a receipt."),
        definition_fa=("سهمی از مبلغ که بر عهدهٔ بیمار است، پس از کسر بیمه و تخفیف. "
                       "این «تعهد» است، نه «وصول»."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.patient_share",
        calculated=True,
        formula=(
            "Σ receptions.patientTotal, where the reception app computes "
            "round(max(0, round(Σ(cost − insurance − supplementary − serviceDiscount)) "
            "− cashDeskDiscount)) and round(x) = floor(x/10000)*10000"
        ),
        aliases=("سهم بیمار", "سهم بیماران", "patient share", "patient liability"),
        related=("patient_paid_amount", "patient_balance", "insurance_liability"),
        not_to_be_confused_with=("patient_paid_amount", "cashier_received_total"),
        validation=("Source-derived formula reproduces the stored value on 219 of 220 "
                    "receptions. The exception (ReceptionID 55622) stores 6,000,000 "
                    "where a single-stage recomputation gives 5,990,000 — the app "
                    "floors at several stages, and one 10,000 falls out of the order."),
        example_1405_06_02=5_786_640_000,
        notes=("⚠️ SERVICE BASIS. This is the app's `overall.totalPatientShare`, summed "
               "over service lines, and it EXCLUDES consumables. The reception header "
               "carries the other one: Σ patientTotal was 6,052,560,000 on 1405/06/02 "
               "against this 5,786,640,000, the difference being consumables of "
               "267,650,000 less the 1,730,000 discount. An answer that checks «سهم "
               "بیمار + سهم بیمه» against «مبلغ پذیرش‌ها» must compare it to "
               "`service_value`, not `reception_total_value`, or say which it used — "
               "quoting one and naming the other is how the identity was once made to "
               "look like it closed when it did not.\n"
               "⚠️ COMPUTED IN THE BROWSER. `components/reception/AddedServicesSummary.jsx` "
               "does this arithmetic client-side and POSTs the result; the server stores "
               "what it is given rather than recomputing. So a stored figure is the "
               "output of one particular front-end build, and every stage floors to "
               "10,000 with `Math.floor` — never expect an exact match from a "
               "single-expression recomputation."),
    ),
    Metric(
        name="insurance_liability",
        fa="سهم سازمان/بیمه",
        definition_en=("What the INSURER owes the centre for the period's receptions. "
                       "A receivable — it is not money received, and its date is the "
                       "reception's, not the insurer's payment date."),
        definition_fa=("طلب مرکز از سازمان بیمه بابت پذیرش‌های این بازه. این «مطالبه» "
                       "است، نه پولی که بیمه پرداخت کرده باشد."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.insurance_share",
        calculated=True,
        formula="Σ (taminInsuranceTotal + salamatInsuranceTotal + armyInsuranceTotal + supplementaryInsuranceTotal)",
        aliases=("سهم بیمه", "سهم سازمان", "بیمه", "insurance share", "organization share"),
        related=("patient_liability", "cashier_insurance_credit"),
        not_to_be_confused_with=("cashier_insurance_credit",),
        validation=("1,038,930,000 on 1405/06/02 = سلامت 137,960,000 + تامین 453,950,000 "
                    "+ ارتش 447,020,000, matching the screen's three bars exactly."),
        example_1405_06_02=1_047_270_000,
        notes=(
            "PER-SERVICE insurance IS available and exact, once the flag that selects "
            "the field is known — read out of the reception app's own "
            "`AddedServicesSummary.jsx`:\n"
            "    tamin   = service.Tamin   ? service.ST            : 0\n"
            "    salamat = service.Salamat ? (service.org || SS)   : 0\n"
            "    army    = service.Army    ? service.SA            : 0\n"
            "Each reconciles to its header total on 220 of 220 receptions.\n"
            "⚠️ `services[].org` is the SALAMAT share specifically, not a generic "
            "insurance amount. Summed across ALL lines it matches the header on only "
            "115 of 220 — which is how I first recorded it as unusable. Filtered by "
            "the `Salamat` flag it is exact. A field read without its guard condition "
            "looks broken."
        ),
    ),
    Metric(
        name="patient_paid_amount",
        fa="پرداخت‌شدهٔ بیمار",
        definition_en=("What patients have actually paid against the period's receptions, "
                       "on whatever day they paid."),
        definition_fa=("مبلغی که بیماران بابت پذیرش‌های این بازه واقعاً پرداخت کرده‌اند، "
                       "در هر روزی که پرداخت شده باشد."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.paid_amount",
        calculated=True, formula="Σ receptions.paidAmount",
        aliases=("پرداخت شده", "پرداختی بیمار", "وصول از بیمار", "paid", "collected from patients"),
        related=("patient_liability", "patient_balance"),
        not_to_be_confused_with=("cashier_received_total", "net_cashier_amount"),
        validation=("3,481,960,000 on 1405/06/02. ⚠️ Payment is ALL-OR-NOTHING at "
                    "reception level: of 220 receptions, 156 paid exactly the patient "
                    "share and 64 paid nothing. Zero partial payments, zero overpayments."),
        example_1405_06_02=5_347_110_000,
    ),
    Metric(
        name="patient_balance",
        fa="مانده بدهی بیمار (مبنای خدمات)",
        definition_en=("What patients still owe ON THE SERVICE BASIS: service-level "
                       "liability minus what has been paid. Consumables are NOT in it."),
        definition_fa=("مانده‌بدهی بیماران بر «مبنای خدمات»: سهم بیمار در سطح خدمت منهای "
                       "پرداخت‌شده. ملزومات مصرفی در این رقم نیست."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.patient_debt",
        calculated=True, formula="patient_liability − patient_paid_amount",
        aliases=("بدهی خدمات", "مانده بدهی خدمات", "service-basis balance"),
        related=("patient_balance_total", "patient_liability", "patient_paid_amount",
                 "unsettled_count"),
        not_to_be_confused_with=("patient_balance_total", "reception_total_value"),
        validation=("439,530,000 on 1405/06/02, end of day: the reception app's own "
                    "`summary.debt.totalPatientDebt`, reproduced exactly in Mongo as "
                    "Σ(service-level patient share) − Σ paidAmount over the 220 live "
                    "receptions."),
        example_1405_06_02=439_530_000,
        notes=("⚠️ THIS IS NOT THE WHOLE DEBT, and the plain question «بیمارها چقدر "
               "بدهکار موندن؟» does not mean it. The reception app's summary works on "
               "the SERVICE basis throughout — totalAmount, totalPatientShare and "
               "totalPatientDebt all exclude consumables — so this figure understated "
               "the real outstanding balance by 265,920,000 of 705,450,000 on "
               "1405/06/02, a little under 40%. Use `patient_balance_total` unless the "
               "question is explicitly about service value.\n"
               "⚠️ THE THREE-TIMES TRAP still applies: "
               "`cashier-report.withdrawals.receptionDebt` is NOT a balance at all. That "
               "field is the day's receptions being debited — it tracks "
               "reception_total_value and was once answered as the patient balance, "
               "overstating it by 3x."),
    ),
    Metric(
        name="patient_balance_total",
        fa="مانده بدهی بیمار",
        definition_en=("What patients still owe IN FULL, on the reception basis: the "
                       "service-basis balance plus the consumables they were billed for, "
                       "less the cash-desk discount. This is the answer to the "
                       "unqualified question «how much are patients still owing»."),
        definition_fa=("کل مانده‌بدهی بیماران بر «مبنای پذیرش»: مانده بدهی خدمات به‌علاوهٔ "
                       "ملزومات مصرفی و منهای تخفیف صندوق. پاسخ پرسش «بیمارها چقدر "
                       "بدهکار موندن؟» همین عدد است."),
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="", source_path="receptions.patientTotal − receptions.paidAmount",
        calculated=True,
        formula="patient_balance + consumables_value − discount_amount",
        components=(("patient_balance", 1), ("consumables_value", 1),
                    ("discount_amount", -1)),
        aliases=("بدهی", "بدهکاری", "مانده بیمار", "بدهی بیمار", "بدهکارند",
                 "چقدر بدهکار", "مانده بدهی", "outstanding", "patient debt", "balance"),
        related=("patient_balance", "consumables_value", "unsettled_count"),
        not_to_be_confused_with=("patient_balance", "reception_total_value"),
        validation=("705,450,000 on 1405/06/02 = Σ patientTotal (6,052,560,000) − Σ "
                    "paidAmount (5,347,110,000) over the 220 live receptions, measured "
                    "in Mongo. The derivation reproduces it exactly: 439,530,000 + "
                    "267,650,000 − 1,730,000 = 705,450,000."),
        confidence="medium",
        example_1405_06_02=705_450_000,
        notes=("⚠️ A SECOND DEFENSIBLE FIGURE EXISTS and an answer should say which it "
               "is quoting: 713,790,000 summed over only the 20 UNSETTLED receptions. "
               "The two differ because a handful of settled receptions carry a small "
               "residue. Neither is wrong; an answer that does not name the basis is.\n"
               "Derived rather than read, because no tool exposes the reception-header "
               "figures. A first-class `patient_debt_reception_basis` field on "
               "daily-summary would make this a single read."),
    ),
    Metric(
        name="discount_amount",
        fa="تخفیف",
        definition_en="Discount granted on the period's receptions.",
        definition_fa="تخفیف داده‌شده روی پذیرش‌های این بازه.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="daily-summary", source_path="financial.cash_desk_discount",
        calculated=True, formula="Σ cashDeskDiscount (discountTotal is 0 in this database)",
        aliases=("تخفیف", "discount"),
        related=("patient_liability",),
        validation="1,730,000 on 1405/06/02, over 2 receptions (55607, 55742).",
        example_1405_06_02=1_730_000,
        notes=("The money lives in `cashDeskDiscount`. `discountTotal` exists and is 0 on "
               "every reception measured — filtering on it returns 'no discounts were "
               "given', which is false."),
    ),
    Metric(
        name="settled_count",
        fa="پذیرش تسویه‌شده",
        definition_en="Receptions whose patient share has been paid in full.",
        definition_fa="پذیرش‌هایی که سهم بیمار آن‌ها کامل پرداخت شده است.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="financial-analysis", source_path="debt_and_discounts.settled_count",
        aliases=("تسویه شده", "تسویه", "settled"),
        related=("unsettled_count", "patient_balance"),
        validation=("151 of 219 on 1405/06/02. `settled == (paidAmount >= patientTotal)` "
                    "holds on 220 of 220 receptions."),
        example_1405_06_02=200,
    ),
    Metric(
        name="unsettled_count",
        fa="پذیرش تسویه‌نشده",
        definition_en="Receptions with an outstanding patient balance.",
        definition_fa="پذیرش‌هایی که هنوز مانده‌بدهی دارند.",
        level=LEVEL_DAY, date_basis=RECEPTION_DATE,
        source_tool="financial-analysis", source_path="debt_and_discounts.unsettled_count",
        aliases=("تسویه نشده", "بدهکار", "unsettled"),
        related=("settled_count", "patient_balance"),
        validation="68 of 219 on 1405/06/02; settled + unsettled = receptions.",
        example_1405_06_02=20,
    ),

    # ------------------------------------------------------------ what arrived
    Metric(
        name="cashier_received_total",
        fa="دریافتی کل صندوق",
        definition_en=("Everything posted to the till in the period, INCLUDING insurance "
                       "credits that never passed through the drawer."),
        definition_fa=("جمع کل آنچه در این بازه به صندوق ثبت شده، شاملِ اعتبار بیمه که "
                       "اصلاً از درِ صندوق رد نشده است."),
        level=LEVEL_DAY, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="totals.income",
        calculated=True,
        formula="cashier_cash_amount + cashier_card_amount + cashier_insurance_credit",
        aliases=("دریافتی", "دریافتی کل", "صندوق چقدر گرفته", "جمع دریافتی", "receipts", "income"),
        related=("net_cashier_amount", "cashier_card_amount", "cashier_insurance_credit"),
        not_to_be_confused_with=("service_value", "reception_total_value",
                                 "net_cashier_amount", "patient_paid_amount"),
        validation="0 + 4,563,530,000 + 1,038,930,000 = 5,602,460,000 on 1405/06/02.",
        example_1405_06_02=5_975_820_000,
    ),
    Metric(
        name="cashier_card_amount",
        fa="دریافت کارتی",
        definition_en="Card payments taken in the period, across all POS terminals.",
        definition_fa="پرداخت‌های کارتی این بازه، روی همهٔ کارتخوان‌ها.",
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="payment_details.totalCardPayments",
        aliases=("کارتی", "کارتخوان", "پوز", "card", "pos"),
        related=("cashier_cash_amount", "net_cashier_amount"),
        validation=("4,939,790,000 over 193 transactions at the END of 1405/06/02, "
                    "counted directly in Mongo as the credit rows carrying a `card`. "
                    "Mid-day it read 4,563,530,000 over 185, summing exactly across the "
                    "three terminals (2,814,710,000 + 1,346,190,000 + 402,630,000)."),
        example_1405_06_02=4_939_790_000,
        notes="Per-terminal detail is in `by_card` — the basis of future POS reconciliation.",
    ),
    Metric(
        name="cashier_cash_amount",
        fa="دریافت نقدی",
        definition_en="Physical cash taken in the period.",
        definition_fa="وجه نقدِ دریافت‌شده در این بازه.",
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="payment_details.totalCashPayments",
        aliases=("نقدی", "نقد", "cash"),
        related=("cashier_card_amount", "net_cashier_amount"),
        validation="0 on 1405/06/02, and genuinely zero — confirmed against transactions.",
        example_1405_06_02=0,
        notes=("⚠️ A transaction lacking a `card` field is NOT cash — that bucket is "
               "insurance credits plus the cash-desk discount. Reading it as cash "
               "reported 1,040,660,000 of cash on a day with none."),
    ),
    Metric(
        name="cashier_insurance_credit",
        fa="پرداخت بیمه (صندوق)",
        definition_en=("Insurance credit posted against receptions during the period. "
                       "Recorded in the till, but no money moved through the drawer."),
        definition_fa=("اعتبار بیمه که در این بازه روی پذیرش‌ها ثبت شده است؛ در صندوق ثبت "
                       "می‌شود ولی پولی جابه‌جا نشده."),
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="by_payment_method.insurance.amount",
        aliases=("پرداخت بیمه", "اعتبار بیمه", "insurance payment"),
        related=("insurance_liability", "cashier_received_total"),
        not_to_be_confused_with=("insurance_liability",),
        validation=("1,038,930,000 over 123 transactions on 1405/06/02. The VALUE happens "
                    "to equal insurance_liability that day; the MEANING does not — one is "
                    "reception-dated liability, this is transaction-dated posting."),
        example_1405_06_02=1_036_030_000,
    ),
    Metric(
        name="cashier_withdrawal_amount",
        fa="برداشت دستی",
        definition_en="Money actually taken out of the till by an operator.",
        definition_fa="پولی که واقعاً توسط کاربر از صندوق برداشت شده است.",
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="withdrawals.manualWithdrawal.amount",
        aliases=("برداشت", "برداشت دستی", "withdrawal"),
        related=("net_cashier_amount",),
        validation="5,720,000 over 2 transactions on 1405/06/02.",
        example_1405_06_02=5_720_000,
        notes=("`withdrawals.total` is NOT this: it also contains `receptionDebt`, which "
               "is the day's receptions being debited and is a thousand times larger."),
    ),
    Metric(
        name="net_cashier_amount",
        fa="خالص صندوق",
        definition_en=("What the till is actually holding: cash and card taken, less what "
                       "was withdrawn. Insurance is excluded — it never entered the drawer."),
        definition_fa=("آنچه واقعاً در صندوق است: نقد و کارت دریافتی، منهای برداشت دستی. "
                       "اعتبار بیمه در این عدد نیست."),
        level=LEVEL_DAY, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="totals.net",
        calculated=True,
        formula="cashier_cash_amount + cashier_card_amount − cashier_withdrawal_amount",
        aliases=("خالص صندوق", "خالص", "net cashier", "net"),
        related=("cashier_received_total", "cashier_withdrawal_amount"),
        not_to_be_confused_with=("cashier_received_total",),
        validation=("0 + 4,563,530,000 − 5,720,000 = 4,557,810,000 on 1405/06/02. "
                    "⚠️ NOT `income − withdrawals`, which would double-count the "
                    "insurance receivable and give 5,596,740,000."),
        example_1405_06_02=4_934_070_000,
        notes="This is the figure a physical cash-and-POS count should be compared against.",
    ),
    Metric(
        name="cashier_discount_amount",
        fa="تخفیف صندوق",
        definition_en="Discount recorded as a cash-desk transaction in the period.",
        definition_fa="تخفیفی که به‌صورت تراکنش صندوق در این بازه ثبت شده است.",
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="by_payment_method.discount.amount",
        aliases=("تخفیف صندوق", "cashier discount"),
        related=("discount_amount",),
        validation="1,730,000 over 2 transactions on 1405/06/02.",
        example_1405_06_02=1_730_000,
    ),
    Metric(
        name="deleted_transaction_amount",
        fa="تراکنش‌های حذف‌شده",
        definition_en="Transactions deleted during the period.",
        definition_fa="تراکنش‌هایی که در این بازه حذف شده‌اند.",
        level=LEVEL_TRANSACTION, date_basis=TRANSACTION_DATE,
        source_tool="cashier-report", source_path="deleted_transactions.total.amount",
        aliases=("حذف شده", "تراکنش حذف شده", "deleted transactions"),
        validation="92,650,000 over 7 transactions on 1405/06/02.",
        example_1405_06_02=95_550_000,
        notes="A deleted TRANSACTION and a deleted RECEPTION are different records.",
    ),
)

_BY_NAME = {m.name: m for m in METRICS}

#: Alias -> metric name, folded so Persian spelling variants resolve. Built once.
_BY_ALIAS: dict[str, str] = {}
for _m in METRICS:
    for _a in (_m.name, _m.fa, *_m.aliases):
        _BY_ALIAS.setdefault(squash(_a), _m.name)


def names() -> list[str]:
    return [m.name for m in METRICS]


def get(metric: str) -> Metric:
    """Resolve a metric by normalized name or by an alias staff actually use."""
    key = str(metric or "").strip()
    if key in _BY_NAME:
        return _BY_NAME[key]
    resolved = _BY_ALIAS.get(squash(key))
    if resolved:
        return _BY_NAME[resolved]
    raise UnknownMetric(key, names())


def check_basis(metric: str, date_basis: str | None) -> Metric:
    """Resolve, and refuse if the caller asked for the wrong date basis.

    Refusing matters. `cashier_received_total` on a reception basis and
    `service_value` on a transaction basis are both meaningless, and both would
    otherwise return a confident number.
    """
    found = get(metric)
    if date_basis and str(date_basis) != found.date_basis:
        raise WrongDateBasis(found.name, str(date_basis), found.date_basis)
    return found


def identities() -> list[dict[str, str]]:
    """The relationships that must hold, for cross-level reconciliation."""
    return [
        {"identity": "service_value + consumables_value = reception_total_value",
         "verified": "220/220 receptions of 1405/06/02, per record",
         "fa": "ارزش خدمات + ملزومات = مبلغ کل پذیرش"},
        # ⚠️ BOTH SIDES OF THIS ONE ARE ON THE SERVICE BASIS. Written against
        # `reception_total_value` it does NOT close: 5,786,640,000 + 1,047,270,000
        # + 1,730,000 = 6,835,640,000 against a reception value of 7,101,550,000,
        # short by the consumables. The version below closes because it compares
        # like with like, and an answer that checked the parts against the
        # reception figure and reported "it reconciles" was quoting one total and
        # naming the other.
        {"identity": "patient_liability + insurance_liability + discount_amount ≈ service_value + discount_amount",
         "verified": "5,786,640,000 + 1,047,270,000 = 6,833,910,000 against a service "
                     "value of 6,833,900,000 on 1405/06/02 — one 10,000 rounding record",
         "fa": "سهم بیمار + سهم بیمه ≈ ارزش خدمات (هر دو بر مبنای خدمات)"},
        {"identity": "patient_liability + consumables_value − discount_amount = Σ receptions.patientTotal",
         "verified": "5,786,640,000 + 267,650,000 − 1,730,000 = 6,052,560,000, measured "
                     "over all 220 live receptions of 1405/06/02 in Mongo",
         "fa": "سهم بیمار (خدمات) + ملزومات − تخفیف = سهم بیمار (پذیرش)"},
        {"identity": "patient_liability − patient_paid_amount = patient_balance",
         "verified": "holds at day level and per reception, on the SERVICE basis",
         "fa": "سهم بیمار − پرداخت‌شده = مانده بدهی (مبنای خدمات)"},
        {"identity": "patient_balance + consumables_value − discount_amount = patient_balance_total",
         "verified": "439,530,000 + 267,650,000 − 1,730,000 = 705,450,000 on 1405/06/02, "
                     "matching Σ(patientTotal − paidAmount) over the 220 live receptions",
         "fa": "مانده بدهی خدمات + ملزومات − تخفیف = کل مانده بدهی بیمار"},
        {"identity": "settled_count + unsettled_count = reception_count",
         "verified": "200 + 20 = 220 at the end of 1405/06/02",
         "fa": "تسویه‌شده + تسویه‌نشده = تعداد پذیرش"},
        # ⚠️ THREE INSTRUMENTS, NOT TWO. Cash was 0 on 1405/06/02 and card was
        # 4,939,790,000, so «نقدی و کارتی» and «کارتی» were the same number that
        # day — and an answer that quoted the card figure as everything the till
        # took was short by the whole 1,036,030,000 of insurance credit while
        # looking arithmetically consistent. Insurance credit is money received.
        {"identity": "cashier_cash_amount + cashier_card_amount + cashier_insurance_credit = cashier_received_total",
         "verified": "0 + 4,939,790,000 + 1,036,030,000 = 5,975,820,000 at the end of "
                     "1405/06/02; the 193 card and 125 non-card credit transactions were "
                     "counted separately in Mongo, and every non-card row carried an "
                     "insurance source or was a discount posted as a credit",
         "fa": "نقدی + کارتی + بیمه = دریافتی کل"},
        {"identity": "cashier_cash_amount + cashier_card_amount − cashier_withdrawal_amount = net_cashier_amount",
         "verified": "0 + 4,939,790,000 − 5,720,000 = 4,934,070,000",
         "fa": "نقدی + کارتی − برداشت دستی = خالص صندوق"},
        # Per-service, from the reception app's own code. Each needs its FLAG as
        # the guard — reading the amount field without it is what made this look
        # unusable the first time.
        {"identity": "Σ services[Tamin].ST = taminInsuranceTotal",
         "verified": "220/220 receptions of 1405/06/02",
         "fa": "جمع سهم تامین خطوط = سهم تامین پذیرش"},
        {"identity": "Σ services[Salamat].(org || SS) = salamatInsuranceTotal",
         "verified": "220/220 — `org` is the SALAMAT share, not a generic one",
         "fa": "جمع سهم سلامت خطوط = سهم سلامت پذیرش"},
        {"identity": "Σ services[Army].SA = armyInsuranceTotal",
         "verified": "220/220 receptions of 1405/06/02",
         "fa": "جمع سهم ارتش خطوط = سهم ارتش پذیرش"},
    ]


#: Where the arithmetic actually happens — §4 of the audit brief.
#:
#: It is not the database and it is not the API. The reception app computes the
#: reception's money **in the browser** and POSTs the result; the server stores
#: what it is given. Two consequences that matter for any answer built on these
#: figures:
#:
#:   * a stored value is the output of one particular front-end build, so two
#:     receptions taken months apart may have been computed by different code;
#:   * `round(x) = Math.floor(x / 10000) * 10000` is applied at SEVERAL stages,
#:     not once at the end, so a single-expression recomputation will disagree
#:     with the stored figure now and then by 10,000 and be right to.
CALCULATION_SITES: dict[str, str] = {
    "reception money (totalAmount, patientTotal, insurance totals, discounts)":
        "components/reception/AddedServicesSummary.jsx — FRONTEND, posted to the API",
    "service & insurance report totals":
        "D:\\api\\routes\\ReportsRouter.js — /Reports/patients-by-service-insurance"
        " — server-side Mongo aggregation over services[]",
    "dashboard totals":
        "D:\\api\\routes\\ReportsRouter.js — /Reports/dashboard — server-side, "
        "reception header fields",
    "cashier report and net":
        "D:\\api\\routes\\ReportsRouter.js — /Reports/cashier-report — server-side, "
        "over transactions",
}


def describe_for_prompt(limit: int | None = None) -> str:
    """A compact rendering for the model: name, basis, source, and the trap."""
    lines = ["FINANCIAL METRICS — name | date basis | source.path | what it is NOT"]
    for metric in METRICS[:limit]:
        confusion = ("  ≠ " + ", ".join(metric.not_to_be_confused_with)
                     if metric.not_to_be_confused_with else "")
        lines.append(
            f"  {metric.name} | {metric.date_basis} | "
            f"{metric.source_tool or 'db'}.{metric.source_path}{confusion}"
        )
    lines.append("RULE: money that MOVED is transaction-dated; money that is OWED is "
                 "reception-dated. Never compare across the two as if equal.")
    return "\n".join(lines)


#: The vendor ALREADY has physical cash reconciliation, and the agent has no
#: tool for any of it. `components/cashDeskAnalysis/` posts a cashier's counted
#: cash and bank-slip totals to `POST /CashDeskAnalysis/reality` («ثبت واقعیت
#: صندوق»), alongside a whole analysis subsystem:
#:
#:   POST /CashDeskAnalysis/reality       the physical count, per cashier
#:   POST /CashDeskAnalysis/record        an analysis run
#:   GET  /CashDeskAnalysis/receipts | discounts | refunds | cancellations
#:   POST /CashDeskAnalysis/checklists
#:   POST /CashDeskAnalysis/ai/analyze
#:
#: So "compare the counted drawer against the system" is largely a matter of
#: READING what the reception software already records, rather than asking the
#: owner to type a number at the agent. Building a parallel reconciliation on
#: top of a system that has one would produce a second set of figures that can
#: disagree with the screen the clinic trusts.
CASHDESK_ANALYSIS_ENDPOINTS: tuple[str, ...] = (
    "POST /CashDeskAnalysis/reality",
    "POST /CashDeskAnalysis/record",
    "PUT  /CashDeskAnalysis/record/{id}",
    "GET  /CashDeskAnalysis/receipts",
    "GET  /CashDeskAnalysis/discounts",
    "GET  /CashDeskAnalysis/refunds",
    "GET  /CashDeskAnalysis/cancellations",
    "POST /CashDeskAnalysis/checklists",
    "POST /CashDeskAnalysis/ai/analyze",
)

__all__ = [
    "METRICS", "Metric", "UnknownMetric", "WrongDateBasis",
    "RECEPTION_DATE", "TRANSACTION_DATE", "CALCULATION_SITES",
    "CASHDESK_ANALYSIS_ENDPOINTS",
    "get", "check_basis", "names", "identities", "describe_for_prompt",
]
