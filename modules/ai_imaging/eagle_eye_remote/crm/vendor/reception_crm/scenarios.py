"""Scenario registry: the operational workflows of an imaging centre, modelled.

## What a scenario is, and what it is NOT

A **mode** (`core/modes.py`) says what the assistant is allowed to DO. A
**scenario** says what the question is ABOUT. They compose:

    offered tools = principal's permissions
                  ∩ mode's menu          (the capability ceiling)
                  ∩ scenario's menu      (the domain narrowing)

**Always an intersection, never a union.** A scenario can only ever remove
tools. If it could add one, a scenario id arriving from a client would be a way
to widen a read-only mode, and the read-only guarantee would stop being a
property of the server.

## What the system actually contains — measured, twice

The first version of this file was written against `reports_catalog.json` and
said "62 reports". That was the brief's framing and it was too narrow by an
order of magnitude. Reading `D:\\api` directly:

| | measured |
|---|---:|
| backend routes, all routers | **691** |
| mounted API namespaces | **39** |
| of those, `/api/Reports` | **64** (9%) |
| served UI page routes (`next start -p 80`) | **130** |
| registered agent tools | 32 |
| reachable by the agent today | **3** report routes + Mongo |

So a report is one kind of source among many, and the biggest domains are not in
the Reports router at all: `/api/Reception` (55) holds the wallet, the discounts,
the refunds and the per-reception consumables; `/api/Patient` (50) holds the
medical record; `/api/imagingWorkflow` (28) holds BOTH the appointment stage and
the whole clinical-report lifecycle; insurance is 77 routes across three
namespaces.

`api_catalog.json` ships beside `reports_catalog.json` so this is checkable
rather than remembered. `tests/test_scenarios.py` verifies every path named
below against it.

## Sources, not just reports

Each scenario names three kinds of source, because a report is not always the
best path:

* `preferred_tools`  — agent tools that exist **now** (test-checked against the
  live registry). This is what narrowing actually uses.
* `preferred_apis`   — real backend routes (test-checked against
  `api_catalog.json`). The map for what to wire next.
* `planned_tools`    — the semantic tools to build, each naming what it wraps.
  Design held as data. **Nothing reads these yet**, and they are deliberately
  NOT in `tools()`, so a planned tool can never be offered to a model as if it
  existed.

## Fallback is the whole safety argument

`GENERAL` has an empty tool set, which by the convention `modes.tools_for`
already uses means "everything the mode allows". A misclassification into
General is byte-for-byte today's behaviour. Every uncertain path leads there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FALLBACK_SCENARIO = "general"

#: Below this the deterministic classifier does not believe itself.
MIN_CONFIDENCE = 0.45


@dataclass(frozen=True)
class PlannedTool:
    """A semantic tool worth building, and the source it would wrap.

    Named as data rather than written as prose because the point of the
    exercise is that whoever builds one does not have to rediscover which of 691
    routes answers the question. `wraps` is checked against the catalogues.
    """

    name: str
    purpose_fa: str
    #: Absolute API paths or report-catalogue paths this tool would call.
    wraps: tuple[str, ...] = ()
    #: True when the tool would change something — so it can never be built as a
    #: read tool by accident.
    writes: bool = False


@dataclass(frozen=True)
class Scenario:
    """One modelled workflow. Data, not behaviour — the router reads it."""

    id: str
    name_fa: str
    description_fa: str
    intent_fa: str
    #: The owner's own example questions, verbatim. This is the test corpus.
    triggers_fa: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    modes: tuple[str, ...] = ("report", "analysis")
    #: UI modules this corresponds to, by the sidebar's own Persian labels.
    ui_modules_fa: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    preferred_reports: tuple[str, ...] = ()
    preferred_apis: tuple[str, ...] = ()
    planned_tools: tuple[PlannedTool, ...] = ()
    database_path: tuple[str, ...] = ()
    lexicon_domains: tuple[str, ...] = ()
    validation_rules: tuple[str, ...] = ()
    cross_check_rules: tuple[str, ...] = ()
    response_template: tuple[str, ...] = ()
    quick_actions_fa: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    ui: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """The client-facing shape, published by `GET /api/scenarios`.

        Omits reports, APIs, database paths and rules: those describe how the
        server works, and a phone rendering quick actions has no use for them.
        """
        return {
            "id": self.id,
            "nameFa": self.name_fa,
            "descriptionFa": self.description_fa,
            "intentFa": self.intent_fa,
            "examplesFa": list(self.triggers_fa),
            "entities": list(self.entities),
            "modes": list(self.modes),
            "uiModulesFa": list(self.ui_modules_fa),
            "quickActionsFa": list(self.quick_actions_fa),
            "responseTemplate": list(self.response_template),
            "related": list(self.related),
            "ui": dict(self.ui),
        }

    def tools(self) -> tuple[str, ...]:
        """Preferred and optional together — the menu this scenario narrows to.

        `planned_tools` is deliberately absent: a tool that does not exist must
        never reach a model as if it did.
        """
        seen: list[str] = []
        for name in self.preferred_tools + self.optional_tools:
            if name not in seen:
                seen.append(name)
        return tuple(seen)


# --------------------------------------------------------------------------- #
# A — Financial / centre operations
# --------------------------------------------------------------------------- #
# Widened by the source read. The Reports router holds the ANALYTICS; the money
# itself lives in `/api/Reception`, which is where the wallet, both discount
# kinds, the refund and the per-reception consumables actually are.
FINANCIAL = Scenario(
    id="financial",
    name_fa="مالی و عملکرد مرکز",
    description_fa="آنچه امروز در مرکز از نظر مالی و عملیاتی گذشته است",
    intent_fa=(
        "پرسنده می‌خواهد بداند مرکز امروز چه کرده است: چند پذیرش، چقدر درآمد، "
        "صندوق چه وضعی داشته، چقدر وصول شده و چقدر مانده، و آیا عددی با عدد "
        "دیگری نمی‌خواند."
    ),
    triggers_fa=(
        "امروز چند تا پذیرش داشتیم؟",
        "درآمد امروز چقدر بود؟",
        "صندوق امروز چه‌جوری بود؟",
        "آیا تناقضی در پرداخت‌ها و دریافت‌ها وجود داشت؟",
        # «آیا حذف غیرطبیعی داشتیم؟» moved to AUDIT. It was filed here only
        # because there was nowhere else to file it, and «حذف» is the reason it
        # routed here — a money word standing in for an integrity question.
        "تخفیف‌های امروز چقدر بود؟",
        "چه مقدار از بیماران وصول شده و چه مقدار مانده دارند؟",
        "مرجوعی‌های امروز چقدر بوده؟",
        "کیف پول بیمارها چقدر موجودی دارد؟",
    ),
    entities=("center", "day", "cashier", "transaction", "wallet", "refund"),
    ui_modules_fa=("صندوق", "مرجوعی پذیرش", "کیف پول", "گزارش صندوق", "آنالیز صندوق",
                   "گزارش بیماران بدهکار"),
    preferred_tools=(
        "daily-summary", "cashier-report", "cashier-reconciliation",
        "financial-analysis", "finance.metric", "finance.vocabulary",
    ),
    optional_tools=(
        "risk-analysis", "reception.search", "patient-list", "trend-analysis",
        "reception.vocabulary",
    ),
    preferred_reports=(
        "/financial", "/financial/summary", "/financial/reception-income",
        "/financial/transactions-list", "/financial/expenses",
        "/financial/expenses-list", "/financial/wallet-transactions",
        "/cashier-report", "/cashier-report/category-details",
        "/cashier-report/deleted-details", "/cashier-report/insurance-details",
        "/cashier/by-user", "/debtors", "/deleted-items", "/reception/general",
        # `/cashier/summary` is absent on purpose: the catalogue records it twice
        # and the second definition shadows the first, so it is dead code.
    ),
    preferred_apis=(
        # The wallet — ten routes, and NOT in `/api/wallet`, which has one.
        "/api/Reception/wallets",
        "/api/Reception/getWallet/:patientId",
        "/api/Reception/wallets/:walletId/transactions",
        "/api/Reception/wallet/:id/report",
        "/api/Reception/all-wallets-transactions",
        # Two distinct discount kinds, matching the two fields in the data.
        "/api/Reception/discount-summary/:id",
        # Refunds — «مرجوعی پذیرش», a two-step workflow with a completion step.
        "/api/reception-refund/",
        "/api/Reception/transactions/cancelled",
        # Petty cash: a separate float from the cashier's till.
        "/api/petty-cash-account/",
        "/api/petty-cash-account/:id/transactions",
        # Live operational, not a report.
        "/api/Reception/today-reception",
        "/api/Reception/deleted",
    ),
    planned_tools=(
        PlannedTool("get_wallet_summary", "موجودی و گردش کیف پول بیماران",
                    ("/api/Reception/wallets", "/api/Reception/all-wallets-transactions",
                     "/financial/wallet-transactions")),
        PlannedTool("get_refunds", "مرجوعی‌های پذیرش و وضعیت تکمیل آن‌ها",
                    ("/api/reception-refund/",)),
        PlannedTool("get_petty_cash", "حساب‌های تنخواه و تراکنش‌های آن‌ها",
                    ("/api/petty-cash-account/", "/api/petty-cash-account/:id/transactions")),
        PlannedTool("get_cancelled_transactions", "تراکنش‌های ابطال‌شده",
                    ("/api/Reception/transactions/cancelled",)),
        PlannedTool("get_debtors", "بیماران بدهکار و مانده هرکدام",
                    ("/debtors", "/debtors/:patientId")),
    ),
    database_path=(
        "receptions", "receptions.services[]", "patientTotal / paidAmount",
        "transactions (ReceptionID)", "wallets + wallet transactions",
        "receptionRefunds", "pettyCashTransactions",
        "cashDeskDiscount / fundDiscount",
    ),
    lexicon_domains=("insurance_type", "insurance_source", "transaction_type"),
    validation_rules=(
        "Never mix date bases in one figure: `Date` is the reception day, "
        "`date` is the transaction day. A number carrying both is meaningless.",
        "A cashier-report response is stamped with when it was GENERATED, never "
        "with the period it covers — never use that stamp as the period.",
        "`cashier-report.withdrawals.receptionDebt` is not the patient balance.",
        "⚠️ There are TWO discount kinds — `cashDeskDiscount` and "
        "`fundDiscount`, applied and removed by separate endpoints. A single "
        "'discount' total that silently merges them answers a question nobody "
        "asked.",
        "⚠️ A refund («مرجوعی») is a two-step workflow: created, then completed. "
        "An uncompleted refund is not money that has left the building.",
        "The wallet is a patient's stored credit, not centre revenue. Never add "
        "wallet balances to income.",
    ),
    cross_check_rules=(
        "reception-side paidAmount vs transaction-side credit — a difference is "
        "usually the date basis, not a loss.",
        "daily-summary revenue vs financial-analysis gross_amount.",
        "cash + card + discount should reconcile to the credit total.",
        "refunds and cancelled transactions should account for any negative gap.",
    ),
    response_template=(
        "خلاصه", "اعداد کلیدی", "وصول و مانده", "تخفیف و حذف و مرجوعی",
        "مغایرت‌ها", "جزئیات",
    ),
    quick_actions_fa=("گزارش امروز", "صندوق", "وصول", "تخفیف‌ها", "مرجوعی‌ها", "تناقض‌ها"),
    related=("staff", "marketing", "insurance", "patient"),
    ui={"icon": "payments"},
)


# --------------------------------------------------------------------------- #
# B — Staff / personnel performance
# --------------------------------------------------------------------------- #
STAFF = Scenario(
    id="staff",
    name_fa="عملکرد کارکنان",
    description_fa="کارکرد یک فرد یا یک گروه از کارکنان، نه کل مرکز",
    intent_fa=(
        "پرسنده درباره یک شخص یا یک نقش می‌پرسد — پذیرشگر، صندوق‌دار، پزشک، "
        "تکنولوژیست — و می‌خواهد کارکرد او را ببیند یا با همکارانش مقایسه کند."
    ),
    triggers_fa=(
        "کدوم کارمند امروز بیشتر کار کرده؟",
        "هر پذیرشگر چند تا بیمار پذیرش کرده؟",
        "صندوق‌دارها امروز چجوری کار کردن؟",
        "فلان کارمند از چه ساعتی شروع کرده؟",
        "چه کسی بیشترین خطا رو داشته؟",
        "پزشک‌ها امروز چند تا بیمار دیدن؟",
        "گزارش‌های فلان پزشک رو بررسی کن.",
    ),
    entities=("staff", "physician", "cashier", "receptionist"),
    ui_modules_fa=("کاربران مرکز", "سطوح دسترسی کاربران", "گزارش کارکرد پزشک"),
    # ⚠️ `staff.activity` is the answer to «از چه ساعتی شروع به کار کرده» — and
    # the reason it is here rather than absent is that declining twice was safe
    # but not helpful: first and last recorded action ARE derivable, they are
    # simply not a clock-in, and the tool carries that caveat in its payload so
    # the answer can state it instead of the model having to remember it.
    preferred_tools=(
        "physician-performance", "cashier-report", "staff.activity",
        "patient-list", "reception.search",
    ),
    optional_tools=(
        "daily-summary", "cashier-reconciliation", "risk-analysis",
        "cashier-deleted-transactions",
        "reporting-queue", "report.archive-stats",
        "integrity.post-approval-edits", "reception.vocabulary",
    ),
    preferred_reports=(
        "/personnel", "/personnel-performance/summary",
        "/personnel-performance/detailed/:personnelId",
        "/personnel-performance/comparison", "/personnel-performance/daily",
        "/physician-performance/summary", "/physician-performance/by-department",
        "/physician-performance/patients/:radiologistId",
        "/reception/by-user", "/cashier/by-user",
    ),
    preferred_apis=(
        "/api/personnel/",
        "/api/AdminUser/getCenterUsers",
        "/api/Reports/personnel-performance/comparison",
        "/api/Reports/cashier/by-user",
        # Who reported what, and who changed a report after approval.
        "/api/imagingWorkflow/:receptionId/workflow/report/logs",
        "/api/imagingWorkflow/:receptionId/workflow/report/logs/summary",
    ),
    planned_tools=(
        PlannedTool("get_staff_activity", "کارکرد پرسنل در یک بازه، قابل مقایسه",
                    ("/personnel-performance/summary", "/personnel-performance/comparison")),
        PlannedTool("get_receptionist_activity", "پذیرش‌های ثبت‌شده به تفکیک پذیرشگر",
                    ("/reception/by-user",)),
        PlannedTool("get_cashier_activity", "دریافتی و تراکنش هر صندوق‌دار",
                    ("/cashier/by-user", "/cashier-report")),
        PlannedTool("get_physician_activity", "کارکرد پزشک و حجم گزارش‌نویسی",
                    ("/physician-performance/summary", "/physician-performance/by-department")),
        PlannedTool("get_report_edit_log", "چه کسی گزارشی را پس از تأیید تغییر داده",
                    ("/api/imagingWorkflow/:receptionId/workflow/report/logs",)),
    ),
    database_path=(
        "AdminUsers / personnel", "receptions.registeredBy",
        "transactions.registeredBy", "imagingWorkflow.report logs",
        "timestamps (receptions.Time)",
    ),
    lexicon_domains=("report_status", "transaction_type"),
    validation_rules=(
        "Name the ROLE the figures are for. A receptionist's count and a "
        "radiologist's count are different things and read alike.",
        "A person with no rows is not a person who did nothing — check whether "
        "the field that names them was populated at all before saying so.",
        "Never publish a staff member's figures as an accusation; report the "
        "number and what it does and does not establish.",
    ),
    cross_check_rules=(
        "per-operator transaction totals should sum to the day's cashier total.",
        "receptions by user should sum to the day's reception count.",
    ),
    response_template=("رتبه‌بندی کارکنان", "عملکرد فردی", "ساعات کاری", "استثناها", "مقایسه"),
    quick_actions_fa=("کارمندان", "صندوق‌دارها", "پزشکان", "عملکرد امروز"),
    related=("financial", "reporting", "patient"),
    ui={"icon": "badge"},
)


# --------------------------------------------------------------------------- #
# C — Marketing / referral / service trends
# --------------------------------------------------------------------------- #
MARKETING = Scenario(
    id="marketing",
    name_fa="روند خدمات و ارجاع",
    description_fa="تغییرات حجم خدمات، مودالیتی‌ها و ارجاع پزشکان در طول زمان",
    intent_fa=(
        "پرسنده می‌خواهد بداند چه چیزی نسبت به قبل بهتر یا بدتر شده است: کدام "
        "خدمت رشد کرده، کدام افت کرده، کدام پزشک کمتر ارجاع می‌دهد. پاسخ بدون "
        "یک دورهٔ مقایسه معنا ندارد."
    ),
    triggers_fa=(
        "امروز چند تا ماموگرافی داشتیم؟",
        "ماموگرافی نسبت به ماه قبل کمتر شده؟",
        "کدوم پزشک این ماه کمتر بیمار فرستاده؟",
        "کدوم پزشک بیشتر ارجاع داده؟",
        "MRI نسبت به ماه قبل بهتر شده یا بدتر؟",
        "کدوم خدمت افت کرده؟",
        "کدوم خدمت رشد داشته؟",
        "از کدوم پزشک‌ها بیمار کمتری اومده؟",
    ),
    entities=("service", "modality", "referring_physician", "period"),
    ui_modules_fa=("گزارش پزشکان ارجاع‌دهنده", "داشبورد"),
    # ⚠️ `marketing.referrers` closes the gap this scenario's own triggers
    # advertised and could not serve: «کدوم پزشک بیشتر ارجاع داده؟» and «از کدوم
    # پزشک‌ها بیمار کمتری اومده؟» are both listed above, and until 1.29.0 there
    # was no tool that read `receptions.referrerPhysician` at all. Four benchmark
    # questions asked for a referrer ranking and four came back as clarifications.
    preferred_tools=("trend-analysis", "marketing.referrers", "reception.search",
                     "reception.vocabulary"),
    optional_tools=(
        "daily-summary", "financial-analysis", "finance.metric", "patient-list",
        "report.archive-stats",
    ),
    preferred_reports=(
        "/reception/modality-stats", "/reception/top-services",
        "/reception/daily-stats", "/reception/insurance-stats",
        "/services/general", "/services/by-group", "/services/by-modality",
        "/services/detailed-list", "/medical-services",
        "/referring-physicians/stats", "/referring-physicians/details",
        "/insurance/by-modality", "/insurance/by-type",
        "/patients/by-gender", "/patients/by-age", "/patients/by-insurance",
        "/patients-by-service-insurance/summary",
    ),
    preferred_apis=(
        "/api/ReferrerPhysician/getAll",
        "/api/Reports/referring-physicians/stats",
        "/api/Reports/reception/daily-stats",
        "/api/ServicesInfo/getByModality/:id",
        # Reception tags: how the centre segments campaigns and cohorts.
        "/api/receptions-tag/active/list",
    ),
    planned_tools=(
        PlannedTool("get_service_trends", "روند حجم خدمات بین دو دوره",
                    ("/services/by-group", "/reception/top-services")),
        PlannedTool("get_modality_trends", "روند هر مودالیتی بین دو دوره",
                    ("/reception/modality-stats", "/services/by-modality")),
        PlannedTool("get_referral_physician_trends", "روند ارجاع هر پزشک",
                    ("/referring-physicians/stats", "/referring-physicians/details")),
        PlannedTool("compare_periods", "مقایسهٔ دو بازه با همان مبنای تاریخ",
                    ("/reception/daily-stats",)),
        PlannedTool("get_cohort_by_tag", "بیماران یک برچسب/کمپین",
                    ("/api/receptions-tag/active/list", "/api/Reception/:receptionId/tags")),
    ),
    database_path=(
        "receptions", "receptions.services[]", "services[].Modality",
        "receptions.referrerPhysician", "receptions.Date", "receptionsTag",
    ),
    lexicon_domains=("modality", "service_group", "insurance_type"),
    validation_rules=(
        "A trend needs BOTH periods measured the same way. Comparing a "
        "reception-date count against a transaction-date count is not a trend.",
        "⚠️ `/patients*` routes count REGISTRATIONS (createdAt), not visits. A "
        "'patients this month' figure from there answers a different question.",
        "⚠️ **A department is not the concept.** Department structure is this "
        "centre's administrative policy and it changes; service identity is the "
        "work. Resolve every clinical term through "
        "`lexicon.center.resolve_clinical_concept()` and use the filter it "
        "builds — never a hand-written department filter. Measured here: "
        "«ماموگرافی» is **4** receptions on 1405/06/02 by service and **108** "
        "by the departments its services live in, because its own department "
        "was retired and its services scattered into Radiology and MRI.",
        "Say WHICH level answered. '4 mammography studies' and '4, found as "
        "services because the department is switched off' are the same figure "
        "with very different auditability — `center.explain()` writes the "
        "sentence.",
        "Say the base sizes, not only the percentage. '−50%' on four studies is "
        "two studies.",
        "An in-progress day compared against a finished one is not a decline.",
    ),
    cross_check_rules=(
        "period totals should reconcile with the day-by-day series behind them.",
        "a modality's service count vs its reception count — the fan-out over "
        "`services[]` makes these legitimately different, so report which.",
    ),
    response_template=(
        "روند", "درصد تغییر", "بیشترین رشد", "بیشترین افت",
        "تغییرات ارجاع", "فرصت‌های بازاریابی", "تفسیر",
    ),
    quick_actions_fa=("روند خدمات", "ارجاع پزشکان", "مقایسه ماهانه", "خدمات رو به کاهش"),
    related=("financial", "staff", "insurance"),
    ui={"icon": "trending_up"},
)


# --------------------------------------------------------------------------- #
# D — Single patient / case investigation
# --------------------------------------------------------------------------- #
# Widened most by the source read: `/api/Patient` is 50 routes of medical
# record — diseases, surgeries, family and drug history, allergies, attachments,
# notes — none of which is in any report.
PATIENT = Scenario(
    id="patient",
    name_fa="بررسی یک بیمار",
    description_fa="پیگیری پروندهٔ یک بیمار مشخص، نه آمار کل مرکز",
    intent_fa=(
        "پرسنده یک شناسه داده است — نام، کد ملی، کد پذیرش — و می‌خواهد سابقهٔ "
        "همان یک نفر را ببیند: مراجعه‌ها، گزارش‌ها، پرداخت‌ها، بدهی، کیف پول و "
        "اینکه چه کسی و چه زمانی او را پذیرش کرده است."
    ),
    triggers_fa=(
        "بیمار با کد پذیرش 12345 رو بررسی کن.",
        "این بیمار چند بار مراجعه کرده؟",
        "گزارش‌های این بیمار چی بوده؟",
        "مشکل مالی این بیمار چی بوده؟",
        "چه کسی پذیرشش کرده؟",
        "چقدر پرداخت کرده؟",
        "آیا تخفیف داشته؟",
        "چرا هنوز بدهکار مونده؟",
    ),
    entities=("patient", "reception", "study"),
    ui_modules_fa=("پرونده بیماران", "لیست پذیرش"),
    preferred_tools=(
        "patients.search", "patient-list", "report.history", "report.get",
        "reception.search",
    ),
    optional_tools=(
        "finance.metric", "report.search", "report.archive-stats",
        "appointments.list", "reception.vocabulary",
    ),
    preferred_reports=(
        "/patients/details/:patientId", "/patients/:patientId/receptions",
        "/reception/details/:receptionId", "/debtors/:patientId",
        "/service-patients", "/physician-performance/search",
        "/patients/detailed-list", "/reception-list",
    ),
    preferred_apis=(
        "/api/Patient/getOne/:id",
        "/api/Patient/search",
        "/api/Patient/getMedicalHistory/:PatientID",
        "/api/Patient/getMedicalHistoryByType/:PatientID/:Type",
        "/api/Patient/getAttachments/:PatientID",
        "/api/Reception/getOneByReceptionID/:id",
        "/api/Reception/getWallet/:patientId",
        "/api/Reception/insurance-status/:receptionId",
        "/api/Reception/inventory-consumption/:id",
        "/api/imagingWorkflow/:receptionId/workflow/status",
    ),
    planned_tools=(
        PlannedTool("find_patient", "یافتن بیمار با نام، کد ملی یا کد پذیرش",
                    ("/api/Patient/search", "/api/Patient/checkByNID")),
        PlannedTool("get_patient_medical_record", "سابقهٔ پزشکی: بیماری، جراحی، آلرژی",
                    ("/api/Patient/getMedicalHistory/:PatientID",)),
        PlannedTool("get_patient_receptions", "همهٔ پذیرش‌های یک بیمار",
                    ("/patients/:patientId/receptions",)),
        PlannedTool("get_patient_financial_history", "پرداخت، بدهی و کیف پول یک بیمار",
                    ("/debtors/:patientId", "/api/Reception/getWallet/:patientId")),
        PlannedTool("get_patient_timeline", "خط زمانی مراجعه‌ها، گزارش‌ها و پرداخت‌ها",
                    ("/patients/:patientId/receptions",
                     "/api/imagingWorkflow/:receptionId/workflow/status")),
    ),
    database_path=(
        "patients", "receptions (patient)", "receptions.services[]",
        "receptions.imagingWorkflow.report", "transactions (ReceptionID)",
        "wallets (patient)", "receptions.registeredBy",
    ),
    lexicon_domains=("report_status", "insurance_type", "modality"),
    validation_rules=(
        "⚠️ Never blend this patient's figures with centre aggregates. A total "
        "on the same screen as one person's row will be read as that person's.",
        "Resolve every identifier to ONE patient before answering. Two people "
        "can share a name; a national code is the identifier that does not.",
        "A reception code is not a patient id and not a study id — say which "
        "one was used.",
        "PHI discipline: give what was asked for. A financial question does not "
        "need the report text, and a report question does not need the balance.",
        "⚠️ Medical history (diseases, allergies, surgeries) is clinical data "
        "about a person. Retrieve it only when the question is clinical, never "
        "as background colour on a billing question.",
    ),
    cross_check_rules=(
        "the patient's paid total vs the transactions filed against their "
        "reception ids.",
        "the reception count from the patient record vs the reception search.",
    ),
    response_template=(
        "هویت بیمار", "خط زمانی", "پذیرش‌ها", "خدمات", "گزارش‌ها",
        "وضعیت مالی", "مشکل یافت‌شده",
    ),
    quick_actions_fa=("جستجوی بیمار", "پرونده", "گزارش‌ها", "مالی", "نوبت‌ها"),
    related=("financial", "reporting", "appointment"),
    ui={"icon": "person_search"},
)


# --------------------------------------------------------------------------- #
# E — Conversation system (سامانه گفتگو)
# --------------------------------------------------------------------------- #
CONVERSATION = Scenario(
    id="conversation",
    name_fa="سامانهٔ گفتگو",
    description_fa="پیام‌های بیماران، پاسخ اپراتورها و تبدیل گفتگو به پذیرش",
    intent_fa=(
        "پرسنده دربارهٔ سامانهٔ چت می‌پرسد: چند نفر پیام دادند، چقدر طول کشید "
        "تا جواب بگیرند، چند پیام بی‌پاسخ ماند، و چند گفتگو به پذیرش رسید."
    ),
    triggers_fa=(
        "امروز چند بیمار از طریق چت پیام دادن؟",
        "چند نفر از چت تبدیل به پذیرش شدن؟",
        "کدوم اپراتور بهتر جواب داده؟",
        "میانگین زمان پاسخ چقدر بوده؟",
        "چند پیام بدون پاسخ مونده؟",
        "کدوم گفتگوها منجر به پرداخت شدن؟",
        "بیمارها بیشتر چه سوالاتی پرسیدن؟",
    ),
    entities=("conversation", "operator", "message"),
    ui_modules_fa=("سامانه گفتگو",),
    preferred_tools=("conversation.summary",),
    optional_tools=("patients.search", "reception.search"),
    #: EMPTY, and now with direct evidence rather than inference. The sidebar's
    #: «سامانه گفتگو» is `/chat`, and both `pages/chat.jsx` and `chat2.jsx`
    #: talk to **https://irannobat.ir:8443** — a CENTRAL backend. None of the
    #: 691 local routes serve it.
    #:
    #: ⚠️ The local `ChatRouter` (`/rooms`, `/admin-users`, `/private-room`,
    #: `/online-users`) is a DIFFERENT system — the staff messenger — and it is
    #: not what this menu item opens. Two things are called «سامانه گفتگو» and
    #: only one of them is the patient conversation.
    preferred_reports=(),
    preferred_apis=(),
    planned_tools=(
        PlannedTool("get_conversations", "گفتگوهای یک بازه و وضعیت هرکدام",
                    ("central: irannobat.ir:8443",)),
        PlannedTool("get_operator_response_metrics", "زمان پاسخ و حجم کار هر اپراتور",
                    ("central: irannobat.ir:8443",)),
        PlannedTool("get_unanswered_conversations", "گفتگوهای بی‌پاسخ",
                    ("central: irannobat.ir:8443",)),
        PlannedTool("get_conversion_metrics", "نرخ تبدیل گفتگو به پذیرش و پرداخت",
                    ("central: irannobat.ir:8443", "/api/Reception/search")),
    ),
    database_path=(
        "central conversations (irannobat.ir:8443)", "messages",
        "operator assignment", "patient (InoUserCode bridge)",
        "reception linkage", "payment linkage",
    ),
    lexicon_domains=(),
    validation_rules=(
        "⚠️ Do NOT answer a chat question from reception reports. The patient "
        "chat is a CENTRAL system; a reception total is not a conversation "
        "total.",
        "⚠️ The local `chatrooms` collection and `/api/Chat/*` are the STAFF "
        "messenger, not the patient chat. Similar names, different systems.",
        "Conversion (chat → reception → payment) is a cross-system join. Say "
        "when it was inferred rather than recorded.",
        "Never quote a patient's message text back in an aggregate answer.",
    ),
    cross_check_rules=(
        "conversations claiming a reception should resolve to receptions that "
        "exist on that day.",
    ),
    response_template=(
        "حجم گفتگو", "عملکرد پاسخ‌گویی", "نرخ تبدیل", "موارد بی‌پاسخ", "مشکلات کیفیت",
    ),
    quick_actions_fa=("گفتگوهای امروز", "بدون پاسخ", "عملکرد اپراتورها", "نرخ تبدیل"),
    related=("patient", "marketing"),
    ui={"icon": "forum"},
)


# --------------------------------------------------------------------------- #
# F — Appointment / scheduling (نوبت‌دهی)  ·  NEW
# --------------------------------------------------------------------------- #
# Earned its place on all four tests. Different sources: the Room → Shift →
# service-group → slot model, which appears in no report. Different logic:
# capacity, not history. Different output: a queue and free slots. And it is the
# ONLY scenario with a real executive action — `appointments.schedule` exists
# and ships disabled in `operations.json`.
#
# ⚠️ The finding that shaped this: there is no standalone appointment book.
# Scheduling is a STAGE OF THE IMAGING WORKFLOW — a reception is created, may
# become «waiting appointment», and is then scheduled. Asking "book Mr X an MRI
# for Tuesday" with no reception is asking for something the data model does not
# have.
APPOINTMENT = Scenario(
    id="appointment",
    name_fa="نوبت‌دهی",
    description_fa="نوبت‌ها، ظرفیت اتاق‌ها و پذیرش‌های منتظر زمان‌بندی",
    intent_fa=(
        "پرسنده دربارهٔ زمان‌بندی می‌پرسد: چه نوبت‌هایی هست، چه کسی منتظر "
        "نوبت است، کدام اتاق در چه شیفتی ظرفیت خالی دارد."
    ),
    triggers_fa=(
        "نوبت‌های امروز چند تاست؟",
        "چند نفر منتظر نوبت هستن؟",
        "ظرفیت خالی فردا چقدره؟",
        "برای این بیمار نوبت ثبت کن.",
        "کدوم اتاق شیفت صبح خالیه؟",
    ),
    entities=("appointment", "room", "shift", "slot"),
    ui_modules_fa=("نوبت دهی", "لیست کار"),
    modes=("report", "analysis", "executive"),
    # ⚠️ Until 1.29.0 this scenario had ONE tool — `appointments.list`, the
    # WAITING QUEUE — and no way to read the diary at all. All ten Appointment
    # questions in the v3 benchmark came back as clarifications with zero tool
    # calls, including the executive write test, which could never reach its
    # confirmation gate because the turn meant to propose a slot had nothing to
    # propose from. The diary, the free slots and the booking-vs-attendance
    # cross-check are the three that were missing.
    preferred_tools=("appointments.day", "appointments.availability",
                     "appointments.vs-receptions", "appointments.list",
                     "reception.search"),
    optional_tools=("patients.search", "patient-list", "reception.vocabulary",
                    "appointments.schedule"),
    preferred_reports=("/rooms",),
    preferred_apis=(
        "/api/imagingWorkflow/workflow/appointments",
        "/api/imagingWorkflow/workflow/appointments/search",
        "/api/imagingWorkflow/workflow/waiting-appointment",
        "/api/imagingWorkflow/workflow/waiting-appointment-clean",
        "/api/rooms/",
        "/api/rooms/:id/available-slots/:serviceGroupId",
        "/api/rooms/:roomId/shifts/:shiftId/available-slots/:serviceGroupId",
        "/api/rooms/:roomId/shifts/:shiftId/service-groups",
        "/api/rooms/:roomId/shifts/:shiftId/specialists",
        "/api/rooms/modality/:modalityId",
    ),
    planned_tools=(
        PlannedTool("get_available_slots", "ظرفیت خالی یک اتاق برای یک گروه خدمتی",
                    ("/api/rooms/:id/available-slots/:serviceGroupId",
                     "/api/rooms/:roomId/shifts/:shiftId/available-slots/:serviceGroupId")),
        PlannedTool("get_waiting_for_appointment", "پذیرش‌های منتظر زمان‌بندی",
                    ("/api/imagingWorkflow/workflow/waiting-appointment",)),
        PlannedTool("get_department_schedule", "برنامهٔ اتاق‌ها و شیفت‌ها",
                    ("/api/rooms/", "/api/rooms/:roomId/shifts/:shiftId/service-groups")),
        PlannedTool("schedule_appointment", "ثبت نوبت برای یک پذیرش موجود",
                    ("/api/imagingWorkflow/:receptionId/workflow/schedule",), writes=True),
    ),
    database_path=(
        "rooms → shifts → serviceGroups / specialists",
        "receptions.imagingWorkflow (schedule stage)",
        "modality → room",
    ),
    lexicon_domains=("modality", "service_group"),
    validation_rules=(
        "⚠️ Scheduling attaches to an EXISTING reception. There is no free-"
        "standing appointment book, so 'book a slot' without a reception is a "
        "request the data model cannot honour — say so rather than inventing a "
        "booking.",
        "Free capacity is per room, per shift, per SERVICE GROUP. A single "
        "'slots free today' number hides the dimension that decides whether a "
        "given patient can be fitted in.",
        "«منتظر نوبت» is a workflow state, not a waiting list someone curates. "
        "It changes as receptions are created all day.",
        "Any booking is a WRITE: it needs Executive mode, the operation switch, "
        "and a human tap. Never describe a proposed booking as done.",
    ),
    cross_check_rules=(
        "waiting-appointment count vs receptions with no scheduled time.",
    ),
    response_template=(
        "نوبت‌های بازه", "منتظر نوبت", "ظرفیت خالی", "به تفکیک اتاق و شیفت", "اقدام پیشنهادی",
    ),
    quick_actions_fa=("نوبت‌های امروز", "جستجوی نوبت", "ظرفیت خالی", "ثبت نوبت"),
    related=("patient", "reporting"),
    ui={"icon": "event_available"},
)


# --------------------------------------------------------------------------- #
# G — Clinical reporting workflow (جواب‌دهی)  ·  NEW
# --------------------------------------------------------------------------- #
# The eleven tools that belonged to NO scenario in the first version — the
# `report-template-*` / `report-current` / `report-logs` cluster and the
# `integrity.*` checks — are this scenario. Their absence was the clearest
# signal that a scenario was missing, and the source read named it: «جواب‌دهی»
# is a first-class UI module with its own 28-route workflow API.
REPORTING = Scenario(
    id="reporting",
    name_fa="گزارش‌نویسی و جواب‌دهی",
    description_fa="چرخهٔ گزارش بالینی: نوشتن، تأیید، تحویل و تأخیرها",
    intent_fa=(
        "پرسنده دربارهٔ خودِ گزارش بالینی می‌پرسد: چه چیزی هنوز گزارش نشده، چه "
        "کسی نوشته، چقدر طول کشیده تا تأیید شود، و چه چیزی منتظر جواب‌دهی است."
    ),
    triggers_fa=(
        "چند تا مطالعه هنوز گزارش نشده؟",
        "چه گزارش‌هایی منتظر تأیید هستن؟",
        "میانگین زمان جواب‌دهی چقدره؟",
        "وضعیت جواب‌دهی امروز چطوره؟",
        # «کدوم گزارش‌ها بعد از تأیید تغییر کردن؟» moved to AUDIT. A report that
        # changed after it was approved is an integrity finding, not a queue
        # state — and it is the one this project has already been burned by.
    ),
    entities=("report", "study", "radiologist", "workflow_status"),
    ui_modules_fa=("جواب دهی", "لیست کار", "تنظیمات جوابدهی"),
    preferred_tools=(
        "reporting-queue", "report.archive-stats", "report.get", "report.history",
        "integrity.missing-reports",
    ),
    optional_tools=(
        "report.search", "integrity.post-approval-edits", "integrity.broken-files",
        "report-current", "report-logs", "report-print-preview",
        "report-template-list", "report-template-search", "report-template-get",
        "physician-performance", "patients.search",
    ),
    preferred_reports=("/imaging-workflow", "/reception/detailed-list"),
    preferred_apis=(
        "/api/imagingWorkflow/workflow/reporting",
        "/api/imagingWorkflow/workflow/reports/awaiting-approval",
        "/api/imagingWorkflow/:receptionId/workflow/status",
        "/api/imagingWorkflow/:receptionId/workflow/report/status/history",
        "/api/imagingWorkflow/:receptionId/workflow/report/logs/summary",
        # A status vocabulary the SERVER publishes. Read it rather than
        # inventing names for the states.
        "/api/imagingWorkflow/workflow/report/status-guide",
    ),
    planned_tools=(
        PlannedTool("get_reporting_queue", "مطالعات منتظر گزارش",
                    ("/api/imagingWorkflow/workflow/reporting",)),
        PlannedTool("get_awaiting_approval", "گزارش‌های نوشته‌شده و منتظر تأیید",
                    ("/api/imagingWorkflow/workflow/reports/awaiting-approval",)),
        PlannedTool("get_report_turnaround", "فاصلهٔ تصویربرداری تا تأیید گزارش",
                    ("/api/imagingWorkflow/:receptionId/workflow/report/status/history",)),
        PlannedTool("get_report_status_guide", "معنی هر وضعیت، از خود سرور",
                    ("/api/imagingWorkflow/workflow/report/status-guide",)),
    ),
    database_path=(
        "receptions.imagingWorkflow", "imagingWorkflow.report",
        "imagingWorkflow.report.statusHistory", "report logs",
        "personnel (radiologist)",
    ),
    lexicon_domains=("report_status", "modality"),
    validation_rules=(
        "⚠️ Read the status vocabulary from `/workflow/report/status-guide` "
        "rather than naming states yourself. The server publishes what each "
        "state means; a guessed name is a wrong answer that reads fluently.",
        "'Not reported' is not one thing: a future booking, an in-progress "
        "study and a genuinely overdue report all look alike in a count. The "
        "integrity check found 26,590 'unreported' studies that were future "
        "bookings — say which kind before reporting a number.",
        "Turnaround needs two timestamps that actually exist on the record. If "
        "one is missing the study is not 'instant', it is unmeasurable.",
        "Report TEXT is clinical PHI. A workflow question wants counts and "
        "timings, not the body of anyone's report.",
    ),
    cross_check_rules=(
        "queue length vs receptions of that day without an approved report.",
        "archive-stats approved counts vs the workflow's approval events.",
    ),
    response_template=(
        "وضعیت جواب‌دهی", "صف گزارش", "منتظر تأیید", "زمان جواب‌دهی", "استثناها",
    ),
    quick_actions_fa=("صف گزارش", "منتظر تأیید", "گزارش‌نشده‌ها", "زمان جواب‌دهی"),
    related=("staff", "patient", "appointment"),
    ui={"icon": "assignment_turned_in"},
)


# --------------------------------------------------------------------------- #
# H — Insurance (بیمه)  ·  NEW
# --------------------------------------------------------------------------- #
# 77 routes across three namespaces — `/api/Salamat` (35), `/api/Tamin` (20),
# `/api/supplementary-insurance` (22) — plus five report families and its own
# settings pages. Distinct sources, distinct business logic (eligibility,
# prescription, share calculation), and a vocabulary the lexicon already warns
# about: `insuranceType` means different things in two collections.
INSURANCE = Scenario(
    id="insurance",
    name_fa="بیمه",
    description_fa="سهم بیمه، نوع بیمه، استعلام و بیمهٔ تکمیلی",
    intent_fa=(
        "پرسنده دربارهٔ بیمه می‌پرسد: سهم هر بیمه‌گر چقدر بوده، چه نوع بیمه‌ای "
        "بیشتر آمده، وضعیت استعلام سلامت یا تأمین چیست، بیمهٔ تکمیلی چه سهمی "
        "داشته."
    ),
    triggers_fa=(
        "سهم بیمه امروز چقدر بود؟",
        "کدوم بیمه بیشترین سهم رو داشته؟",
        "بیمه تکمیلی چقدر پرداخت کرده؟",
        "استعلام سلامت چند تا پذیرش مونده؟",
        "توزیع بیمه‌ها به تفکیک مودالیتی چطوره؟",
    ),
    entities=("insurance", "insurer", "reception"),
    ui_modules_fa=("گزارش بیمه", "گزارش خدمت و بیمه"),
    preferred_tools=("financial-analysis", "reception.search", "finance.metric"),
    optional_tools=(
        "daily-summary", "finance.vocabulary", "reception.vocabulary",
        "patient-list", "trend-analysis",
    ),
    preferred_reports=(
        "/insurance", "/insurance/general", "/insurance/by-type",
        "/insurance/by-modality", "/reception/insurance-stats",
        "/patients-by-service-insurance", "/patients-by-service-insurance/summary",
        "/cashier-report/insurance-details", "/patients/by-insurance",
    ),
    preferred_apis=(
        "/api/Reception/pending-insurance",
        "/api/Reception/insurance-status/:receptionId",
        "/api/supplementary-insurance/list",
        "/api/supplementary-insurance/coverage/service/:id",
        "/api/Patient/getInsuranceType/:CenterID",
        "/api/Setting/Insurance/getAll",
    ),
    planned_tools=(
        PlannedTool("get_insurance_shares", "سهم هر بیمه‌گر در یک بازه",
                    ("/insurance/by-type", "/cashier-report/insurance-details")),
        PlannedTool("get_insurance_by_modality", "توزیع بیمه به تفکیک مودالیتی",
                    ("/insurance/by-modality",)),
        PlannedTool("get_pending_insurance", "پذیرش‌های منتظر استعلام یا تأیید بیمه",
                    ("/api/Reception/pending-insurance",)),
        PlannedTool("get_supplementary_insurance", "سهم و وضعیت بیمهٔ تکمیلی",
                    ("/api/supplementary-insurance/list",
                     "/api/supplementary-insurance/coverage/service/:id")),
    ),
    database_path=(
        "receptions.insuranceType / insuranceSource",
        "services[].org (needs `service.Salamat` as its guard)",
        "transactions.insuranceType", "supplementaryInsurance",
    ),
    lexicon_domains=("insurance_type", "insurance_source",
                     "transaction_insurance_type"),
    validation_rules=(
        "⚠️ `insuranceType` means DIFFERENT things on receptions and on "
        "transactions. The lexicon records the collision; resolve which "
        "collection a figure came from before comparing two of them.",
        "⚠️ `services[].org` read without its guard condition looks broken. It "
        "needs `service.Salamat`, and with it the totals reconcile 220/220.",
        "Basic and supplementary insurance are separate payers. A single "
        "'insurance share' that merges them is not a number anyone can act on.",
        "A pending enquiry is not a rejection. Report the state, not a verdict.",
    ),
    cross_check_rules=(
        "insurance share + patient share + discount should reconcile to the "
        "gross amount.",
        "`/insurance/by-type` totals vs `cashier-report/insurance-details`.",
    ),
    response_template=(
        "خلاصه بیمه", "سهم هر بیمه‌گر", "به تفکیک خدمت و مودالیتی",
        "استعلام‌های باز", "مغایرت‌ها",
    ),
    quick_actions_fa=("سهم بیمه", "بیمه تکمیلی", "استعلام‌های باز", "بیمه به تفکیک خدمت"),
    related=("financial", "marketing", "patient"),
    ui={"icon": "health_and_safety"},
)


# --------------------------------------------------------------------------- #
# I — Inventory / consumables (انبار)  ·  NEW
# --------------------------------------------------------------------------- #
# The smallest of the new scenarios and it still passes the four-part test:
# its own models (`WarehouseProduct`, `WarehouseTransaction`), its own logic
# (stock in/out and per-reception consumption), its own units (items, not
# rials) and its own output. It also closes a real loop — the per-reception
# consumables are what explained the 265,650,000 dashboard-vs-service gap.
INVENTORY = Scenario(
    id="inventory",
    name_fa="انبار و مصرفی",
    description_fa="موجودی کالا، ورود و خروج، و مصرف هر پذیرش",
    intent_fa=(
        "پرسنده دربارهٔ کالا و مصرفی می‌پرسد: چه چیزی در انبار مانده، چه چیزی "
        "مصرف شده، و مصرف یک پذیرش چه بوده."
    ),
    triggers_fa=(
        "موجودی انبار چقدره؟",
        "چه کالایی امروز مصرف شده؟",
        "کدوم قلم داره تموم میشه؟",
        "مصرفی این پذیرش چی بوده؟",
    ),
    entities=("product", "stock", "consumption"),
    ui_modules_fa=("انبار",),
    preferred_tools=("reception.search",),
    optional_tools=("patient-list", "finance.metric", "reception.vocabulary"),
    preferred_reports=("/warehouse",),
    preferred_apis=(
        "/api/Warehouse/inventory",
        "/api/Warehouse/products",
        "/api/Warehouse/transactions/report",
        "/api/Warehouse/logs",
        "/api/Reception/reception-warehouse-transactions/:receptionId",
        "/api/Reception/inventory-consumption/:id",
    ),
    planned_tools=(
        PlannedTool("get_inventory", "موجودی فعلی کالاها",
                    ("/api/Warehouse/inventory",)),
        PlannedTool("get_stock_movements", "ورود و خروج انبار در یک بازه",
                    ("/api/Warehouse/transactions/report", "/warehouse")),
        PlannedTool("get_reception_consumption", "مصرفی ثبت‌شده برای یک پذیرش",
                    ("/api/Reception/inventory-consumption/:id",)),
    ),
    database_path=(
        "warehouseProducts", "warehouseTransactions",
        "receptions → inventory consumption",
    ),
    lexicon_domains=("modality",),
    validation_rules=(
        "⚠️ The warehouse report is dated by `PersianDate` — a movement date, "
        "and the only route in the catalogue on that basis. It is not the "
        "reception day and not the transaction day.",
        "Stock is counted in ITEMS. Do not present a stock figure beside a "
        "rial figure without saying which is which.",
        "Per-reception consumption is what makes the dashboard total exceed the "
        "sum of service prices — consumables are real cost, not a discrepancy.",
    ),
    cross_check_rules=(
        "recorded consumption vs stock movements out over the same period.",
    ),
    response_template=("موجودی", "ورود و خروج", "رو به اتمام", "مصرف به تفکیک"),
    quick_actions_fa=("موجودی انبار", "مصرف امروز", "رو به اتمام"),
    related=("financial",),
    ui={"icon": "inventory_2"},
)


# --------------------------------------------------------------------------- #
# J — Audit / integrity (بازرسی)  ·  NEW, added because the benchmark asked for it
# --------------------------------------------------------------------------- #
# The scenario benchmark measured «آیا نکته‌ای بود که دیروز نگران‌کننده باشه، مثل
# حذف غیرطبیعی یا چیزی؟» routing to `financial` at 0.50 — one point over the
# fallback threshold, on the strength of a single deletion word, into a scenario
# that owns none of the tools that answer it. The three `integrity.*` tools and
# `risk-analysis` had existed for months and nothing routed to them.
#
# It passes the four-part test the other scenarios were held to: its own
# question ("did anything happen that should not have"), its own sources (the
# deleted-record trails and the edit trails), its own unit (records and events,
# not rials or receptions) and its own output shape (findings with evidence, or
# an explicit statement that a trail does not exist).
#
# ⚠️ The last of those is the point. This scenario's most likely correct answer
# is "the system does not record that" — see `validation_rules`. A scenario that
# made the model feel equipped to answer every integrity question would be worse
# than no scenario at all.
AUDIT = Scenario(
    id="audit",
    name_fa="بازرسی و یکپارچگی",
    description_fa="حذف‌ها، ویرایش‌ها و هر چیزی که باید بررسی شود",
    intent_fa=(
        "پرسنده می‌پرسد آیا اتفاق غیرعادی افتاده: حذف، ویرایش پس از تأیید، "
        "تغییر نام، یا هر نشانهٔ دیگری که نیاز به بررسی داشته باشد."
    ),
    triggers_fa=(
        "آیا نکته‌ای نگران‌کننده بود؟",
        "آیا حذف غیرطبیعی داشتیم؟",
        "آیا تغییر نامی انجام شده؟",
        "کدوم گزارش‌ها بعد از تأیید تغییر کردن؟",
    ),
    entities=("record", "event", "user"),
    ui_modules_fa=("گزارش‌ها", "صندوق", "پذیرش"),
    modes=("report", "analysis", "executive"),
    # ⚠️ `audit.name-changes` is here because this scenario shipped a rule
    # saying the trail did NOT exist. It does — 67 records, 9 of them on the
    # benchmark day — and a rule that tells the model the centre does not record
    # something it records is worse than no rule: it converts a missing tool
    # into a false claim about the clinic.
    preferred_tools=(
        "integrity.post-approval-edits", "integrity.broken-files",
        "integrity.missing-reports", "audit.name-changes",
        "risk-analysis", "reception.search", "cashier-deleted-transactions",
    ),
    optional_tools=(
        "cashier-report", "cashier-reconciliation", "daily-summary",
        "patient-list", "report.history",
    ),
    # ⚠️ Every path here was checked against `api_catalog.json` by the test that
    # guards this field, and the first draft failed it: two of the three routes
    # I reached for — a deleted-transactions endpoint and a reception log —
    # simply do not exist. The real trails are these, and they are all GET.
    preferred_apis=(
        "/api/Reports/deleted-items",
        "/api/Reports/cashier-report/deleted-details",
        "/api/Reception/deleted",
        "/api/imagingWorkflow/:receptionId/workflow/report/logs",
        "/api/imagingWorkflow/:receptionId/workflow/report/logs/summary",
        "/api/imagingWorkflow/:receptionId/workflow/report/status/history",
    ),
    planned_tools=(
        PlannedTool("get_deleted_receptions", "پذیرش‌های حذف‌شده در یک بازه",
                    ("/api/Reception/deleted", "/api/Reports/deleted-items")),
        PlannedTool("get_deleted_transactions", "تراکنش‌های حذف‌شده در یک بازه",
                    ("/api/Reports/cashier-report/deleted-details",)),
        PlannedTool("get_report_log", "لاگ و تاریخچهٔ وضعیت گزارش یک پذیرش",
                    ("/api/imagingWorkflow/:receptionId/workflow/report/logs",
                     "/api/imagingWorkflow/:receptionId/workflow/report/status/history")),
    ),
    database_path=(
        "receptions.deleted / returned / updateHistory",
        "transactions.deleted / updateHistory",
        "PatientNameChangeLogs (oldName, newName, changedBy, persianDate)",
        "ReportLogs (action, field, oldValue, newValue, changedBy, persianDate)",
        "receptions.imagingWorkflow.report (approval timestamps)",
    ),
    lexicon_domains=("modality",),
    validation_rules=(
        "⚠️ A deleted RECEPTION and a deleted TRANSACTION are different objects "
        "in different collections. Count them separately and say which is "
        "which; merging them answers neither question.",
        "⚠️ A name-change trail DOES exist: `PatientNameChangeLogs` records "
        "oldName, newName, changedBy, the Jalali date and time, the reason and "
        "the affected receptions. Read it with `audit.name-changes`. This rule "
        "has now been wrong twice in opposite directions — it first said no "
        "trail existed, then that no tool could read one — so state what the "
        "tool returns and nothing about what the centre does or does not keep. "
        "A record is not an accusation: most are spelling fixes or authorised "
        "changes, and `blocked: true` means the change did not happen.",
        "⚠️ Every integrity check this project has built reported a TRUE number "
        "that answered a different question: 26,590 'unreported' studies were "
        "future bookings, 24 'broken links' were deliberate deletes, and 93 "
        "'post-approval edits' were same-session saves. State what the figure "
        "literally counts before calling anything abnormal.",
        "A deletion is not a finding. Compare against a normal day before "
        "describing anything as unusual.",
    ),
    cross_check_rules=(
        "deleted transactions vs the day's cashier figures — a deletion that "
        "moved money should be visible in both.",
        "deleted receptions vs the reception count for the same day.",
    ),
    response_template=("خلاصه", "یافته‌ها", "شواهد", "آنچه سامانه ثبت نمی‌کند"),
    quick_actions_fa=("حذف‌های امروز", "ویرایش پس از تأیید", "موارد پرریسک"),
    related=("financial", "staff", "reporting"),
    ui={"icon": "policy"},
)


# --------------------------------------------------------------------------- #
# K — General / open investigation
# --------------------------------------------------------------------------- #
GENERAL = Scenario(
    id="general",
    name_fa="بررسی آزاد",
    description_fa="پرسش‌هایی که در هیچ‌کدام از سناریوهای بالا نمی‌گنجند",
    intent_fa=(
        "پرسش روشن به یک سناریو نمی‌خورد، یا به چند سناریو به یک اندازه "
        "می‌خورد. مدل خودش از میان همهٔ ابزارهای مجاز انتخاب می‌کند."
    ),
    modes=("report", "analysis", "executive"),
    #: EMPTY, and that is the entire fallback guarantee. `Scenario.tools()`
    #: returns nothing, the router narrows by nothing, and the model sees
    #: exactly the menu the mode gave it.
    preferred_tools=(),
    optional_tools=(),
    validation_rules=(
        "Say which source each figure came from — with no scenario, provenance "
        "is the only thing telling the reader what was actually consulted.",
    ),
    response_template=("خلاصه", "یافته‌ها", "منابع"),
    ui={"icon": "explore"},
)


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
ALL: tuple[Scenario, ...] = (
    FINANCIAL, STAFF, MARKETING, PATIENT, CONVERSATION,
    APPOINTMENT, REPORTING, INSURANCE, INVENTORY, AUDIT, GENERAL,
)

_SCENARIOS: dict[str, Scenario] = {s.id: s for s in ALL}


def all_scenarios() -> list[Scenario]:
    return list(ALL)


def get(scenario_id: Any) -> Scenario:
    """Resolve an id, falling back to General.

    Forgiving in the same way and for the same reason as `modes.get`: an
    unknown scenario from an older client is a reason to answer generally, not
    to refuse the question. General narrows nothing, so falling back here can
    never grant anything either.
    """
    return _SCENARIOS.get(str(scenario_id or "").strip().lower(), GENERAL)


def is_known(scenario_id: Any) -> bool:
    return str(scenario_id or "").strip().lower() in _SCENARIOS


def tools_for(scenario: Scenario, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Narrow an already mode-filtered tool list to this scenario.

    Order is not negotiable and mirrors `modes.tools_for`: permissions first
    (the registry), then the mode, then this. **Subtraction only.** A tool the
    mode did not offer cannot appear here, because this filters the list it is
    given and never consults the registry.
    """
    return tools_for_many([scenario.id], tools)


def tools_for_many(
    scenario_ids: list[str] | tuple[str, ...], tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Narrow to the UNION of several scenarios — the multi-scenario case.

    A union of two scenario menus is still a subset of what the mode allowed,
    so merging is exactly as safe as narrowing to one: this only ever removes.

    Narrowing to nothing returns the input unchanged. A scenario whose tools are
    all absent — a deployment without the local database, say — must degrade to
    the mode's menu, not to an assistant that can do nothing. That is the same
    failure `modes.tools_for` guards, and it is worth guarding twice: this layer
    is a routing hint, and a hint must never be able to disable the agent.

    Any General or unknown id means "do not narrow", because `GENERAL.tools()`
    is empty and an empty want-set is the do-not-narrow signal.
    """
    wanted: set[str] = set()
    for scenario_id in scenario_ids:
        names = get(scenario_id).tools()
        if not names:
            return tools
        wanted.update(names)
    if not wanted:
        return tools
    narrowed = [t for t in tools if str(t.get("name", "")) in wanted]
    return narrowed or tools
