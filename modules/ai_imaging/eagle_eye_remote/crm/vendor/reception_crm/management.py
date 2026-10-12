from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .ino_api import InoClient
from .jalali import DayResolution, add_jalali_days, jalali_to_gregorian, resolve_day
from .storage import Storage


MODALITY_ALIASES = {
    "ct": "1",
    "سی تی": "1",
    "سی تی اسکن": "1",
    "mri": "2",
    "ام آر آی": "2",
    "us": "3",
    "sono": "3",
    "سونو": "3",
    "سونوگرافی": "3",
    "xr": "4",
    "xray": "4",
    "رادیولوژی": "4",
}


@dataclass(frozen=True)
class Period:
    start_jalali: str
    end_jalali: str
    label: str
    #: True when NOBODY said which day — the caller passed nothing and the
    #: period fell back to today. Carried so the answer can say so; see
    #: `jalali.DayResolution` for why an unstated default is the dangerous one.
    assumed: bool = False

    @property
    def business_date(self) -> date:
        return jalali_to_gregorian(self.end_jalali)

    def date_assumption(self) -> dict[str, Any]:
        """The assumption block to put in a tool payload, beside the numbers."""
        return DayResolution(
            day=self.end_jalali, assumed=self.assumed, asked_for=None
        ).as_payload()


def resolve_period(value: str | None, days: int = 1) -> Period:
    resolution = resolve_day(value)
    end_jalali = resolution.day
    start_jalali = add_jalali_days(end_jalali, -(days - 1)) if days > 1 else end_jalali
    return Period(
        start_jalali=start_jalali,
        end_jalali=end_jalali,
        label=end_jalali,
        assumed=resolution.assumed,
    )


def fetch_source_bundle(period: Period, data_root: Path, include_risk: bool = True) -> dict[str, Any]:
    client = InoClient.from_env()
    storage = Storage(data_root)
    storage.ensure_layout()
    captured_at = datetime.now().astimezone()

    service_report = client.patients_by_service_insurance(period.start_jalali, period.end_jalali)
    service_snapshot = storage.store_raw(
        "patients_by_service_insurance",
        period.business_date,
        captured_at,
        service_report,
    )

    risk_report = None
    risk_snapshot = None
    if include_risk:
        risk_report = client.cashdesk_risk_analysis(period.start_jalali, period.end_jalali)
        risk_snapshot = storage.store_raw("cashdesk_risk_analysis", period.business_date, captured_at, risk_report)

    return {
        "period": period,
        "service_report": service_report,
        "risk_report": risk_report,
        "source_paths": {
            "service_report": str(service_snapshot.raw_path),
            "risk_report": str(risk_snapshot.raw_path) if risk_snapshot else None,
        },
    }


def daily_summary(period: Period, data_root: Path) -> dict[str, Any]:
    bundle = fetch_source_bundle(period, data_root, include_risk=True)
    service_data = bundle["service_report"]["data"]
    summary = service_data["summary"]
    overall = summary["overall"]
    debt = summary["debt"]
    wallet = summary["walletVsReception"]
    risk = bundle["risk_report"]["data"]["riskDistribution"] if bundle.get("risk_report") else {}

    return {
        "skill": "daily-summary",
        "period": _period_dict(period),
        "admissions": {
            "total_receptions": overall.get("totalReceptions"),
            "unique_patients": overall.get("uniquePatients"),
            "total_services": overall.get("totalServices"),
        },
        # ⚠️ EVERY FIGURE IN THIS BLOCK IS ON THE SERVICE BASIS. The reception
        # app's summary sums service lines; consumables billed on the reception
        # are in none of them. On 1405/06/02 `total_amount` was 6,833,900,000
        # against a reception value of 7,101,550,000, and `patient_debt` was
        # 439,530,000 against a real outstanding balance of 705,450,000. The
        # gap is `inventoryTotalAmount`, 267,650,000, and it is the difference
        # that made `risk-analysis` and this tool look like they disagreed
        # about the same day. They do not disagree; they are on different bases.
        "financial": {
            "basis": "service",
            "basis_note_fa": (
                "همهٔ ارقام این بخش بر «مبنای خدمات» است و ملزومات مصرفی را شامل "
                "نمی‌شود. برای مبلغ کل پذیرش‌ها و کل مانده‌بدهی، از شاخص‌های "
                "reception_total_value و patient_balance_total استفاده کن."
            ),
            "total_amount": overall.get("totalAmount"),
            "patient_share": overall.get("totalPatientShare"),
            "insurance_share": overall.get("totalOrganizationShare"),
            "paid_amount": debt.get("totalPaidAmount"),
            "patient_debt": debt.get("totalPatientDebt"),
            "cash_desk_discount": debt.get("totalCashDeskDiscount"),
            "cash": wallet.get("cashierCashAmount"),
            "card": wallet.get("cashierCardAmount"),
            "cashier_inflow": wallet.get("cashierInflowsCashCardAndInsurance"),
        },
        "by_modality": summary.get("byModality", []),
        "by_insurance": summary.get("byInsurance", []),
        "risk": {
            key: {
                "count": value.get("count"),
                "total_amount": value.get("totalAmount"),
                "percentage": value.get("percentage"),
            }
            for key, value in risk.items()
        },
        "source_paths": bundle["source_paths"],
    }


def patient_list(period: Period, data_root: Path, modality: str | None = None) -> dict[str, Any]:
    bundle = fetch_source_bundle(period, data_root, include_risk=False)
    rows = bundle["service_report"]["data"].get("receptions", [])
    modality_code = normalize_modality(modality)
    if modality_code:
        rows = [row for row in rows if str(row.get("modality")) == modality_code]

    return {
        "skill": "patient-list",
        "period": _period_dict(period),
        "filter": {"modality": modality, "modality_code": modality_code},
        "count": len(rows),
        "patients": [normalize_reception(row) for row in rows],
        "source_paths": bundle["source_paths"],
    }


def financial_analysis(period: Period, data_root: Path) -> dict[str, Any]:
    bundle = fetch_source_bundle(period, data_root, include_risk=False)
    summary = bundle["service_report"]["data"]["summary"]
    overall = summary["overall"]
    debt = summary["debt"]
    wallet = summary["walletVsReception"]
    return {
        "skill": "financial-analysis",
        "period": _period_dict(period),
        "revenue": {
            "total_amount": overall.get("totalAmount"),
            "patient_share": overall.get("totalPatientShare"),
            "insurance_share": overall.get("totalOrganizationShare"),
            "salamat": overall.get("totalSalamatInsurance"),
            "tamin": overall.get("totalTaminInsurance"),
            "army": overall.get("totalArmyInsurance"),
            "supplementary": overall.get("totalSupplementaryInsurance"),
        },
        "cashier": {
            "cash": wallet.get("cashierCashAmount"),
            "card": wallet.get("cashierCardAmount"),
            "patient_cash_and_card": wallet.get("cashierPatientCashAndCard"),
            "insurance_credits": wallet.get("cashierInsuranceCreditsAmount"),
            "total_inflow": wallet.get("cashierInflowsCashCardAndInsurance"),
        },
        # ⚠️ THIS FIELD IS ON THE SERVICE BASIS AND IS NOT THE WHOLE DEBT.
        #
        # The label here used to read «همان مانده‌بدهی واقعی بیماران است ... برای
        # پرسش «بیمارها چقدر بدهکارند» همین عدد پاسخ است» — the real patient
        # balance, the answer to that question. It is neither. The reception
        # app's summary works on the SERVICE basis throughout: totalAmount,
        # totalPatientShare and totalPatientDebt all leave consumables out. On
        # 1405/06/02 this field read 439,530,000 while patients actually owed
        # 705,450,000 — Σ patientTotal − Σ paidAmount over the same 220
        # receptions, measured in Mongo. The label was short by 265,920,000 and
        # seven answers repeated it, because a field that states its own meaning
        # is believed.
        #
        # The label now says which basis it is on and names the metric that
        # carries the other. `finance.metric{patient_balance_total}` derives it
        # as patient_balance + consumables_value − discount_amount.
        "debt_and_discounts": {
            "paid_amount": debt.get("totalPaidAmount"),
            "patient_debt": debt.get("totalPatientDebt"),
            "cash_desk_discount": debt.get("totalCashDeskDiscount"),
            "fund_discount": debt.get("totalFundDiscount"),
            "settled_count": debt.get("settledCount"),
            "unsettled_count": debt.get("unsettledCount"),
            "meaning_fa": (
                "«patient_debt» مانده‌بدهی بیماران بر «مبنای خدمات» است: سهم بیمار در "
                "سطح خدمت منهای پرداخت‌شده. ملزومات مصرفی در این رقم نیست، بنابراین "
                "کمتر از کل بدهی است. برای پرسش «بیمارها چقدر بدهکارند» از شاخص "
                "patient_balance_total استفاده کن؛ این عدد فقط وقتی پاسخ است که "
                "پرسش صریحاً دربارهٔ ارزش خدمات باشد."
            ),
            "basis": "service",
            "identity": "patient_share - paid_amount = patient_debt (both service basis)",
            "whole_debt_metric": "patient_balance_total",
        },
        "date_basis": {
            "basis": "reception",
            "meaning_fa": (
                "ارقام این گزارش بر مبنای تاریخ پذیرش‌اند و «تعهد» را نشان می‌دهند، "
                "نه «وصول». سهم بیمه یعنی طلب مرکز از بیمه، نه پولی که بیمه پرداخت "
                "کرده است. برای پولی که واقعاً وارد صندوق شده از cashier-report "
                "استفاده کن."
            ),
        },
        "by_modality": summary.get("byModality", []),
        "by_insurance": summary.get("byInsurance", []),
        "source_paths": bundle["source_paths"],
    }


def cashier_reconciliation(period: Period, data_root: Path) -> dict[str, Any]:
    bundle = fetch_source_bundle(period, data_root, include_risk=True)
    summary = bundle["service_report"]["data"]["summary"]
    debt = summary["debt"]
    wallet = summary["walletVsReception"]
    high_risk = bundle["risk_report"]["data"]["riskDistribution"]["high"]["receptions"]

    expected_same_receptions = wallet.get("receptionPaidAmountSum") or debt.get("totalPaidAmount")
    actual_same_receptions = wallet.get("cashierPatientCashAndCardForReportReceptions")
    same_reception_difference = _num(actual_same_receptions) - _num(expected_same_receptions)
    transaction_date_difference = _num(wallet.get("cashierPatientCashAndCard")) - _num(expected_same_receptions)

    return {
        "skill": "cashier-reconciliation",
        "period": _period_dict(period),
        "expected_vs_actual": {
            "expected_patient_cash_card_for_report_receptions": expected_same_receptions,
            "actual_cash_card_for_report_receptions": actual_same_receptions,
            "same_reception_difference": same_reception_difference,
            "actual_cash_card_by_transaction_date": wallet.get("cashierPatientCashAndCard"),
            "transaction_date_difference": transaction_date_difference,
            "insurance_credits": wallet.get("cashierInsuranceCreditsAmount"),
            "total_cashier_inflow": wallet.get("cashierInflowsCashCardAndInsurance"),
        },
        # ⚠️ SERVICE BASIS, like every other surface of this field. Carried here
        # as CONTEXT for the variance, not as the outstanding balance: two
        # benchmark answers read it out of this block and reported 439,530,000
        # where patients owed 705,450,000. The relabelling in 1.28.1 reached
        # daily-summary and financial-analysis and missed this one, and the two
        # answers that still quoted it bare were exactly the two that had read
        # it here.
        "supporting_financials": {
            "basis": "service",
            "patient_debt": debt.get("totalPatientDebt"),
            "patient_debt_meaning_fa": (
                "مانده‌بدهی بیماران بر «مبنای خدمات»؛ ملزومات مصرفی در آن نیست. "
                "برای کل بدهی از شاخص patient_balance_total استفاده کن."
            ),
            "whole_debt_metric": "patient_balance_total",
            "discount": debt.get("totalCashDeskDiscount"),
            "settled_count": debt.get("settledCount"),
            "unsettled_count": debt.get("unsettledCount"),
        },
        "possible_causes": classify_reconciliation_causes(same_reception_difference, transaction_date_difference, high_risk),
        "high_risk_receptions": [normalize_risk_reception(row) for row in high_risk],
        "source_paths": bundle["source_paths"],
    }


def cashier_report(period: Period, data_root: Path) -> dict[str, Any]:
    """The reception system's own cashier report, passed through, not rebuilt.

    This is deliberately thin. The endpoint already computes every total the
    reception software shows its own users -- income by cash / card / insurance,
    withdrawals, net, per-cashier credit and debt, per-modality, per-bank-card.
    Recomputing any of it here would produce a second set of numbers that can
    disagree with the screen the clinic actually trusts, and the clinic would be
    right and we would be wrong.

    So the job here is naming, not arithmetic: give each block a stable key, and
    carry the report's OWN inclusion notes through so the answer can say what it
    is really about.
    """
    client = InoClient.from_env()
    storage = Storage(data_root)
    storage.ensure_layout()
    captured_at = datetime.now().astimezone()

    payload = client.cashier_report(period.start_jalali, period.end_jalali)
    data = payload.get("data") or {}
    snapshot = storage.store_raw("cashier_report", period.business_date, captured_at, payload)

    info = data.get("reportInfo") or {}
    summary = data.get("summary") or {}
    cashiers = data.get("cashierReport") or []

    return {
        "skill": "cashier-report",
        "period": _period_dict(period),
        # `scope` describes which cashier SESSIONS are included, not the time
        # window -- the window is the period above. The two were conflated once
        # already; keeping them as separate keys is what stops it recurring.
        "scope": {
            "kind": info.get("scope") or "cashier_active",
            "meaning_fa": "صندوق‌های فعال در این بازه",
            "report_date": info.get("reportDate"),
            "notes_fa": list(info.get("scopeNotes") or []),
        },
        "totals": {
            "income": (summary.get("incomes") or {}).get("total"),
            "withdrawals": (summary.get("withdrawals") or {}).get("total"),
            "net": (summary.get("cashDeskNet") or {}).get("net"),
            "transactions": (summary.get("overall") or {}).get("totalTransactions"),
            "cashiers": (summary.get("overall") or {}).get("uniqueUsers"),
        },
        # Every money block below carries what it MEANS, in Persian, beside the
        # figure. Asked «بیمارها امروز چقدر بدهکار موندن؟» the agent reached for
        # this report, read `withdrawals.receptionDebt`, and answered
        # 7,099,560,000 — the entire day's reception value — where the true
        # outstanding patient balance was 2,313,020,000. It overstated a debt
        # threefold from a field that is not a debt at all.
        #
        # The tool description already warned about exactly that field. It was
        # not enough: a warning one scroll away from the number loses to the
        # number. Meaning travels WITH the value or it does not travel.
        "by_payment_method": summary.get("incomes") or {},
        "payment_details": summary.get("paymentDetails") or {},
        "withdrawals": dict(
            summary.get("withdrawals") or {},
            meaning_fa=(
                "«receptionDebt» بدهکار شدنِ پذیرش‌های همین روز است — یعنی ارزش "
                "پذیرش‌ها، نه پولی که از صندوق خارج شده و نه مانده‌بدهی بیماران. "
                "تنها «manualWithdrawal» برداشت واقعی است."
            ),
            not_the_patient_balance_fa=(
                "برای «بیماران چقدر بدهکارند» از financial-analysis استفاده کن: "
                "سهم بیمار منهای پرداخت‌شده. این عدد آن نیست."
            ),
        ),
        "net_formula": {
            "formula": "cash + card - manualWithdrawal",
            "excludes_fa": "اعتبار بیمه در خالص صندوق نیست؛ از درِ صندوق رد نمی‌شود.",
            "income_includes_insurance": True,
        },
        "date_basis": {
            "basis": "transaction",
            "meaning_fa": (
                "همهٔ ارقام این گزارش بر مبنای تاریخ تراکنش‌اند: پرداختِ امروز بابت "
                "پذیرشِ هفتهٔ گذشته، امروز اینجا شمرده می‌شود. این جمع، ارزش "
                "پذیرش‌های امروز نیست و نباید با آن مقایسه شود."
            ),
        },
        "deleted_transactions": summary.get("deleted") or {},
        "by_cashier": [
            {
                "name": row.get("fullName"),
                "username": row.get("userName"),
                "transactions": row.get("totalTransactions"),
                "credit": row.get("totalCredit"),
                "debt": row.get("totalDebt"),
                "net": row.get("netAmount"),
            }
            for row in cashiers
        ],
        "by_modality": data.get("byModality") or [],
        "by_card": data.get("paymentsByCard") or [],
        "cash_payment": data.get("cashPayment") or {},
        "insurance_payments": data.get("insurancePayments") or [],
        "discounts": data.get("discountedPatientsStats") or {},
        "source_paths": {"cashier_report": str(snapshot.raw_path)},
    }


def cashier_deleted_transactions(
    period: Period,
    data_root: Path,
    *,
    category: str | None = None,
    user_id: str | None = None,
    max_items: int = 5000,
    include_patient_details: bool = False,
) -> dict[str, Any]:
    """Deleted transaction audit rows, with deterministic actor summaries.

    The ordinary cashier report contains only the deleted total.  This detail
    report keeps the person who registered a transaction separate from the
    person who deleted it; neither is inferred from the reception creator.
    """
    client = InoClient.from_env()
    storage = Storage(data_root)
    storage.ensure_layout()
    captured_at = datetime.now().astimezone()
    payload = client.cashier_deleted_transactions(
        period.start_jalali,
        period.end_jalali,
        category=category,
        user_id=user_id,
        max_items=max_items,
    )
    snapshot = storage.store_raw(
        "cashier_deleted_transactions", period.business_date, captured_at, payload
    )

    raw_data = payload.get("data") if isinstance(payload, dict) else None
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_rows = data.get("transactions") or []
    rows = [
        _normalize_deleted_transaction(row, include_patient_details=include_patient_details)
        for row in raw_rows
        if isinstance(row, dict)
    ]
    raw_pagination = data.get("pagination")
    pagination: dict[str, Any] = raw_pagination if isinstance(raw_pagination, dict) else {}
    complete = bool(pagination.get("collectionComplete", not pagination.get("hasNextPage")))
    raw_stats = data.get("stats")
    stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
    raw_overall = stats.get("overall")
    overall: dict[str, Any] = raw_overall if isinstance(raw_overall, dict) else {}

    return {
        "skill": "cashier-deleted-transactions",
        "period": _period_dict(period),
        "filters": {"category": category, "userId": user_id},
        "totals": {
            "amount": overall.get("totalAmount"),
            "transactions": overall.get("transactionCount"),
            "average_amount": overall.get("averageAmount"),
            "minimum_amount": overall.get("minAmount"),
            "maximum_amount": overall.get("maxAmount"),
        },
        "by_deleted_by": _aggregate_deleted_transactions(rows, "deleted_by"),
        "by_original_user": _aggregate_deleted_transactions(rows, "registered_by"),
        "by_category": stats.get("byCategory") or [],
        "transactions": rows,
        "completeness": {
            "detailsComplete": complete,
            "collected": len(rows),
            "total": pagination.get("totalCount", overall.get("transactionCount")),
            "note_fa": (
                "تجمیع‌های کاربری بر پایهٔ همهٔ جزئیات دریافت‌شده‌اند."
                if complete
                else "جزئیات به سقف ایمنی رسیده‌اند؛ تجمیع کاربری ممکن است ناقص باشد."
            ),
        },
        "meaning_fa": (
            "registered_by ثبت‌کنندهٔ تراکنش و deleted_by حذف‌کنندهٔ آن است. "
            "این دو با ثبت‌کنندهٔ پذیرش یکی فرض نشده‌اند. حذف به‌تنهایی اثبات خطا یا تخلف نیست."
        ),
        "source_paths": {"cashier_deleted_transactions": str(snapshot.raw_path)},
    }


def _normalize_deleted_transaction(
    row: dict[str, Any], *, include_patient_details: bool
) -> dict[str, Any]:
    raw_registered = row.get("userDetails")
    registered: dict[str, Any] = raw_registered if isinstance(raw_registered, dict) else {}
    raw_deleted_by = row.get("deletedByDetails")
    deleted_by: dict[str, Any] = raw_deleted_by if isinstance(raw_deleted_by, dict) else {}
    normalized = {
        "transaction_id": row.get("_id"),
        "reception_id": row.get("ReceptionID"),
        "amount": row.get("amount"),
        "type": row.get("type"),
        "category": row.get("category"),
        "payment_method": row.get("paymentMethod"),
        "date": row.get("date"),
        "time": row.get("time"),
        "deleted_at": row.get("deletedAt"),
        "registered_by": {
            "id": registered.get("id"),
            "name": registered.get("fullName") or registered.get("username"),
            "username": registered.get("username"),
        },
        "deleted_by": {
            "id": deleted_by.get("id"),
            "name": deleted_by.get("fullName") or deleted_by.get("username"),
            "username": deleted_by.get("username"),
        },
    }
    if include_patient_details:
        raw_patient = row.get("patientDetails")
        patient: dict[str, Any] = raw_patient if isinstance(raw_patient, dict) else {}
        normalized["patient"] = {
            "name": patient.get("name"),
            "national_code": patient.get("nationalCode"),
        }
    return normalized


def _aggregate_deleted_transactions(
    rows: list[dict[str, Any]], actor_key: str
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_actor = row.get(actor_key)
        actor: dict[str, Any] = raw_actor if isinstance(raw_actor, dict) else {}
        actor_id = str(actor.get("id") or "")
        name = str(actor.get("name") or "نامشخص").strip() or "نامشخص"
        key = actor_id or name
        item = grouped.setdefault(
            key,
            {"user_id": actor_id or None, "name": name, "count": 0, "amount": 0.0},
        )
        item["count"] += 1
        item["amount"] += float(row.get("amount") or 0)
    return sorted(grouped.values(), key=lambda item: (-item["count"], item["name"]))


def physician_performance(period: Period, data_root: Path) -> dict[str, Any]:
    """Per-radiologist workload for a period, ordered by how much they carried.

    Ordering happens HERE rather than in the model. "Which physician did the
    most" is a sort, not a judgement, and a sort done in Python is right every
    time -- whereas a model asked to rank twelve rows of Persian names and
    nine-digit rials will occasionally put the second one first, and the answer
    will read exactly as confidently either way.
    """
    client = InoClient.from_env()
    storage = Storage(data_root)
    storage.ensure_layout()
    captured_at = datetime.now().astimezone()

    payload = client.physician_performance_summary(period.start_jalali, period.end_jalali)
    snapshot = storage.store_raw("physician_performance", period.business_date, captured_at, payload)

    rows = payload.get("data") or []
    summary = payload.get("summary") or {}

    physicians = sorted(
        (
            {
                "name": row.get("radiologistName"),
                "personnel_code": row.get("personnelCode"),
                "speciality": row.get("speciality"),
                "patients": _num(row.get("totalPatients")),
                "revenue": _num(row.get("totalRevenue")),
                "patient_share": _num(row.get("totalPatientShare")),
                "insurance_share": _num(row.get("totalInsuranceShare")),
                "paid_amount": _num(row.get("totalPaidAmount")),
                "discount": _num(row.get("totalDiscount")),
                "by_modality": [
                    {
                        "modality": d.get("modalityName") or d.get("modality"),
                        "patients": _num(d.get("patientCount")),
                        "revenue": _num(d.get("revenue") or d.get("totalAmount")),
                    }
                    for d in (row.get("departmentSummary") or row.get("departments") or [])
                ],
            }
            for row in rows
            if isinstance(row, dict)
        ),
        key=lambda p: (p["patients"], p["revenue"]),
        reverse=True,
    )
    for rank, entry in enumerate(physicians, start=1):
        entry["rank"] = rank

    return {
        "skill": "physician-performance",
        "period": _period_dict(period),
        # Said explicitly because it is the number people misread: this counts
        # patients ATTRIBUTED TO A RADIOLOGIST, not the day's admissions.
        "counts_what_fa": "بیمارانی که به پزشک گزارش‌دهنده نسبت داده شده‌اند — نه کل پذیرش‌های روز",
        "totals": {
            "physicians": summary.get("totalRadiologists"),
            "patients": summary.get("totalPatients"),
            "revenue": summary.get("totalRevenue"),
            "patient_share": summary.get("totalPatientShare"),
            "insurance_share": summary.get("totalInsuranceShare"),
            "paid_amount": summary.get("totalPaidAmount"),
            "discount": summary.get("totalDiscount"),
        },
        "busiest": physicians[0]["name"] if physicians else None,
        "physicians": physicians,
        "by_department": summary.get("departmentBreakdown") or [],
        "source_paths": {"physician_performance": str(snapshot.raw_path)},
    }


def risk_analysis(period: Period, data_root: Path) -> dict[str, Any]:
    bundle = fetch_source_bundle(period, data_root, include_risk=True)
    data = bundle["risk_report"]["data"]
    distribution = data["riskDistribution"]
    return {
        "skill": "risk-analysis",
        "period": _period_dict(period),
        "total_receptions": data.get("totalReceptions"),
        "total_amount": data.get("totalAmount"),
        "distribution": {
            key: {
                "count": value.get("count"),
                "total_amount": value.get("totalAmount"),
                "percentage": value.get("percentage"),
            }
            for key, value in distribution.items()
        },
        "high_risk_receptions": [normalize_risk_reception(row) for row in distribution["high"].get("receptions", [])],
        "source_paths": bundle["source_paths"],
    }


def trend_analysis(period: Period, data_root: Path, compare: str = "yesterday") -> dict[str, Any]:
    base = daily_summary(period, data_root)
    if compare == "last-week":
        comparison_period = Period(add_jalali_days(period.end_jalali, -7), add_jalali_days(period.end_jalali, -7), "last-week")
    elif compare == "last-month":
        comparison_period = Period(add_jalali_days(period.end_jalali, -30), add_jalali_days(period.end_jalali, -30), "last-month")
    else:
        comparison_period = Period(add_jalali_days(period.end_jalali, -1), add_jalali_days(period.end_jalali, -1), "yesterday")
    comparison = daily_summary(comparison_period, data_root)

    return {
        "skill": "trend-analysis",
        "period": _period_dict(period),
        "comparison_period": _period_dict(comparison_period),
        "metrics": {
            "total_receptions": _compare(
                base["admissions"]["total_receptions"], comparison["admissions"]["total_receptions"]
            ),
            "total_services": _compare(base["admissions"]["total_services"], comparison["admissions"]["total_services"]),
            "total_amount": _compare(base["financial"]["total_amount"], comparison["financial"]["total_amount"]),
            "patient_share": _compare(base["financial"]["patient_share"], comparison["financial"]["patient_share"]),
            "cashier_inflow": _compare(base["financial"]["cashier_inflow"], comparison["financial"]["cashier_inflow"]),
        },
        "current_by_modality": base["by_modality"],
        "comparison_by_modality": comparison["by_modality"],
        "source_paths": {
            "current": base["source_paths"],
            "comparison": comparison["source_paths"],
        },
    }


def render_persian_report(result: dict[str, Any]) -> str:
    skill = result["skill"]
    if skill == "daily-summary":
        return _render_daily_summary(result)
    if skill == "patient-list":
        return _render_patient_list(result)
    if skill == "financial-analysis":
        return _render_financial(result)
    if skill == "cashier-reconciliation":
        return _render_reconciliation(result)
    if skill == "risk-analysis":
        return _render_risk(result)
    if skill == "trend-analysis":
        return _render_trend(result)
    return json_like(result)


def normalize_modality(value: str | None) -> str | None:
    if not value:
        return None
    return MODALITY_ALIASES.get(value.strip().lower(), value)


def normalize_reception(row: dict[str, Any]) -> dict[str, Any]:
    patient = row.get("patientDetails") or {}
    modality = row.get("modalityDetails") or {}
    return {
        "reception_id": row.get("ReceptionID"),
        "date": row.get("Date"),
        "time": row.get("Time"),
        "patient_name": patient.get("name"),
        "national_code": patient.get("nationalCode"),
        "modality_code": row.get("modality"),
        "modality_name": modality.get("name") or modality.get("fullName"),
        "insurance_type": row.get("insuranceType"),
        "insurance_label": row.get("insuranceTypeLabel"),
        "total_amount": row.get("totalAmount"),
        "patient_share": row.get("patientShare"),
        "insurance_share": row.get("organizationShare"),
        "paid_amount": row.get("paidAmount"),
        "discount": row.get("discountTotal") or row.get("cashDeskDiscount"),
        "settled": row.get("settled"),
    }


def normalize_risk_reception(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "reception_id": row.get("receptionId"),
        "patient_name": row.get("patientName"),
        "total_amount": row.get("totalAmount"),
        "patient_share": row.get("patientTotal"),
        "insurance_type": row.get("insuranceType"),
        "services_count": row.get("servicesCount"),
        "discount_amount": row.get("discountAmount"),
        "update_history_count": row.get("updateHistoryCount"),
        "settled": row.get("settled"),
        "date": row.get("date"),
        "time": row.get("time"),
        "cashier": str(row.get("cashier") or "").strip(),
        "risk_factors": row.get("riskFactors") or [],
    }


def classify_reconciliation_causes(
    same_reception_difference: int,
    transaction_date_difference: int,
    high_risk: list[dict[str, Any]],
) -> list[str]:
    causes = []
    if same_reception_difference == 0:
        causes.append("برای همان پذیرش‌های گزارش، پرداخت ثبت‌شده با تراکنش‌های متناظر هم‌خوان است.")
    else:
        causes.append("بین paidAmount پذیرش‌ها و تراکنش‌های همان پذیرش‌ها مغایرت وجود دارد.")
    if transaction_date_difference:
        causes.append("اختلاف بر اساس تاریخ تراکنش دیده می‌شود؛ احتمال پرداخت مربوط به پذیرش‌های روزهای دیگر مطرح است.")
    if any(not row.get("settled") for row in high_risk):
        causes.append("چند مورد پرریسک تسویه‌نشده وجود دارد و باید دستی بررسی شود.")
    if any((row.get("discountAmount") or 0) > 0 for row in high_risk):
        causes.append("حداقل یک مورد پرریسک دارای تخفیف است.")
    if any((row.get("updateHistoryCount") or 0) >= 5 for row in high_risk):
        causes.append("ویرایش مکرر در موارد پرریسک مشاهده شده است.")
    return causes


def _period_dict(period: Period) -> dict[str, Any]:
    """The window a payload covers — including whether anyone chose it.

    Every dated tool payload goes through here, which is why the assumption is
    added here rather than at nine call sites: a fact that has to be remembered
    at each site is a fact that will be missing from one of them.

    `date_assumption.was_assumed` is true only when the caller named no day at
    all and the period fell back to today. The block carries its own Persian
    text, so the model sees the caveat inline with the numbers rather than in a
    prompt paragraph it may not connect to them.
    """
    return {
        "start_date": period.start_jalali,
        "end_date": period.end_jalali,
        "label": period.label,
        "date_assumption": period.date_assumption(),
    }


def _num(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        normalized = value.translate(translation).strip()
        normalized = normalized.replace(",", "").replace("٬", "").replace(" ", "")
        if not normalized:
            return 0
        return int(float(normalized))
    return int(value or 0)


def _compare(current: Any, previous: Any) -> dict[str, Any]:
    current_num = _num(current)
    previous_num = _num(previous)
    delta = current_num - previous_num
    pct = None if previous_num == 0 else round((delta / previous_num) * 100, 2)
    return {"current": current_num, "previous": previous_num, "delta": delta, "delta_percent": pct}


def fmt(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return str(value)


def json_like(result: dict[str, Any]) -> str:
    import json

    return json.dumps(result, ensure_ascii=False, indent=2)


def _render_daily_summary(result: dict[str, Any]) -> str:
    admissions = result["admissions"]
    financial = result["financial"]
    lines = [
        f"گزارش روز {result['period']['end_date']}",
        f"- کل پذیرش‌ها: {fmt(admissions['total_receptions'])}",
        f"- بیماران یکتا: {fmt(admissions['unique_patients'])}",
        f"- تعداد خدمات: {fmt(admissions['total_services'])}",
        f"- جمع کل خدمات: {fmt(financial['total_amount'])} ریال",
        f"- سهم بیمار: {fmt(financial['patient_share'])} ریال",
        f"- سهم بیمه/سازمان: {fmt(financial['insurance_share'])} ریال",
        f"- پرداخت ثبت‌شده: {fmt(financial['paid_amount'])} ریال",
        f"- کارتخوان: {fmt(financial['card'])} ریال",
        f"- نقدی: {fmt(financial['cash'])} ریال",
        f"- مانده بدهی بیمار: {fmt(financial['patient_debt'])} ریال",
        "",
        "بخش‌ها:",
    ]
    for row in result["by_modality"]:
        lines.append(f"- {row.get('modalityFullName')}: {fmt(row.get('count'))} خدمت، {fmt(row.get('totalAmount'))} ریال")
    return "\n".join(lines)


def _render_patient_list(result: dict[str, Any]) -> str:
    lines = [f"لیست پذیرش‌ها - {result['period']['end_date']}", f"تعداد: {fmt(result['count'])}", ""]
    for row in result["patients"][:50]:
        lines.append(
            f"- {row.get('reception_id')} | {row.get('patient_name')} | {row.get('modality_name') or row.get('modality_code')} | "
            f"{fmt(row.get('total_amount'))} ریال | تسویه: {'بله' if row.get('settled') else 'خیر'}"
        )
    if result["count"] > 50:
        lines.append(f"- {result['count'] - 50} مورد دیگر در خروجی JSON موجود است.")
    return "\n".join(lines)


def _render_financial(result: dict[str, Any]) -> str:
    revenue = result["revenue"]
    cashier = result["cashier"]
    debt = result["debt_and_discounts"]
    return "\n".join(
        [
            f"تحلیل مالی - {result['period']['end_date']}",
            f"- درآمد کل: {fmt(revenue['total_amount'])} ریال",
            f"- سهم بیمار: {fmt(revenue['patient_share'])} ریال",
            f"- سهم بیمه/سازمان: {fmt(revenue['insurance_share'])} ریال",
            f"- کارتخوان: {fmt(cashier['card'])} ریال",
            f"- نقدی: {fmt(cashier['cash'])} ریال",
            f"- ورودی صندوق + بیمه: {fmt(cashier['total_inflow'])} ریال",
            f"- بدهی بیمار: {fmt(debt['patient_debt'])} ریال",
            f"- تخفیف صندوق: {fmt(debt['cash_desk_discount'])} ریال",
            f"- تسویه‌شده / تسویه‌نشده: {fmt(debt['settled_count'])} / {fmt(debt['unsettled_count'])}",
        ]
    )


def _render_reconciliation(result: dict[str, Any]) -> str:
    evs = result["expected_vs_actual"]
    lines = [
        f"تطبیق صندوق - {result['period']['end_date']}",
        f"- مبلغ مورد انتظار برای پذیرش‌های گزارش: {fmt(evs['expected_patient_cash_card_for_report_receptions'])} ریال",
        f"- تراکنش متناظر همان پذیرش‌ها: {fmt(evs['actual_cash_card_for_report_receptions'])} ریال",
        f"- مغایرت قطعی همان پذیرش‌ها: {fmt(evs['same_reception_difference'])} ریال",
        f"- کارت/نقد بر اساس تاریخ تراکنش: {fmt(evs['actual_cash_card_by_transaction_date'])} ریال",
        f"- اختلاف بر اساس تاریخ تراکنش: {fmt(evs['transaction_date_difference'])} ریال",
        "",
        "علت‌های احتمالی:",
    ]
    lines.extend(f"- {cause}" for cause in result["possible_causes"])
    lines.append("")
    lines.append("موارد پرریسک برای بررسی دستی:")
    for row in result["high_risk_receptions"][:10]:
        lines.append(
            f"- پذیرش {row['reception_id']}: {fmt(row['total_amount'])} ریال، "
            f"ویرایش‌ها {fmt(row['update_history_count'])}، عوامل: {', '.join(row['risk_factors'])}"
        )
    return "\n".join(lines)


def _render_risk(result: dict[str, Any]) -> str:
    lines = [
        f"آنالیز ریسک - {result['period']['end_date']}",
        f"- کل پذیرش‌ها: {fmt(result['total_receptions'])}",
        f"- مبلغ کل: {fmt(result['total_amount'])} ریال",
    ]
    labels = {"low": "کم‌ریسک", "medium": "ریسک متوسط", "high": "پرریسک"}
    for key, label in labels.items():
        row = result["distribution"][key]
        lines.append(f"- {label}: {fmt(row['count'])} پذیرش، {fmt(row['total_amount'])} ریال، {row['percentage']}٪")
    lines.append("")
    lines.append("پرریسک‌ها:")
    for row in result["high_risk_receptions"]:
        lines.append(
            f"- پذیرش {row['reception_id']}: {fmt(row['total_amount'])} ریال، "
            f"ویرایش {fmt(row['update_history_count'])}، تسویه: {'بله' if row['settled'] else 'خیر'}، "
            f"عوامل: {', '.join(row['risk_factors'])}"
        )
    return "\n".join(lines)


def _render_trend(result: dict[str, Any]) -> str:
    lines = [f"تحلیل روند - {result['period']['end_date']} نسبت به {result['comparison_period']['end_date']}"]
    labels = {
        "total_receptions": "پذیرش",
        "total_services": "خدمات",
        "total_amount": "درآمد کل",
        "patient_share": "سهم بیمار",
        "cashier_inflow": "ورودی صندوق",
    }
    for key, label in labels.items():
        row = result["metrics"][key]
        pct = "" if row["delta_percent"] is None else f" ({row['delta_percent']}٪)"
        lines.append(f"- {label}: {fmt(row['current'])} در برابر {fmt(row['previous'])}، تغییر {fmt(row['delta'])}{pct}")
    return "\n".join(lines)
