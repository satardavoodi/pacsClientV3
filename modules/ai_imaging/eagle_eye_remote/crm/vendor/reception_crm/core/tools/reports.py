from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from ...ino_api import InoClient
from ...jalali import jalali_to_gregorian
from ...management import (
    cashier_deleted_transactions,
    cashier_reconciliation,
    cashier_report,
    daily_summary,
    financial_analysis,
    patient_list,
    physician_performance,
    resolve_period,
    risk_analysis,
    trend_analysis,
)
from ...operations import load_operations
from ..registry import ToolRegistry
from ..types import ToolDefinition


def register_report_tools(registry: ToolRegistry) -> None:
    # The descriptions below are the tool-SELECTION prompt. They were two words
    # each ("Cashier reconciliation", "Financial review", "Period comparison"),
    # which gave the model nothing to choose on between six tools that all read
    # the same day and all sound plausible for any money question. A wrong tool
    # is not recoverable downstream: no prompt can make the right answer out of
    # the wrong source. Each one now says what it reads, what it is FOR, and --
    # where two tools are easy to confuse -- which one to prefer instead.
    registry.register(report_tool(
        "daily-summary",
        _daily_summary,
        "Headline numbers for a day: admissions, unique patients, service count, revenue, "
        "cash/card/insurance split, and a breakdown by modality and insurer. Use for "
        "'how many patients today', 'how did today go' and any single-figure question. "
        "Counts, not rows — for the actual names use patient-list.\n"
        "DATE BASIS: reception date. Every figure here describes receptions CREATED in "
        "the period, on live (non-deleted) records.\n"
        "⚠️ REVENUE BASIS: **SERVICE**. Every money figure in `financial` is summed over "
        "service lines and EXCLUDES consumables billed on the reception. That is one "
        "basis of two, and which one you are on changes the answer:\n"
        "  • `financial.total_amount` is SERVICE value — tariff x quantity. Measured "
        "1405/06/02: 6,833,900,000, against a reception total of 7,101,550,000. The "
        "267,650,000 difference is materials (`inventoryTotalAmount`). Do not call this "
        "«ارزش پذیرش‌ها» — for that, ask `finance.metric` for `reception_total_value`.\n"
        "  • `financial.patient_debt` is the SERVICE-basis balance: 439,530,000 on "
        "1405/06/02, where patients actually owed 705,450,000. **It is NOT the answer to "
        "«بیمارها چقدر بدهکارند»** — that is `finance.metric{patient_balance_total}`, "
        "which adds the consumables back. Quoting this field as the outstanding balance "
        "understated it by nearly 40% in seven benchmark answers. If you do quote it, "
        "say «مانده بدهی خدمات» and name the basis.\n"
        "  • `financial.patient_share`, `financial.paid_amount` and "
        "`financial.patient_debt` are what patients OWE, what has ARRIVED and what is "
        "LEFT — three questions, all on the service basis.\n"
        "Also do NOT answer a debt question from cashier-report: its "
        "`withdrawals.receptionDebt` is the day's receptions being debited and is about "
        "three times larger than any balance.\n"
        "⚠️ `by_modality[].uniquePatients` is NOT distinct people — it equals the "
        "reception count in every bucket. Distinct patients exist only at the top level, "
        "as `admissions.unique_patients`.",
    ))
    registry.register(report_tool(
        "patient-list",
        _patient_list,
        "The individual receptions of a day, one row per service, with patient name, time, "
        "modality and amounts. Optionally narrowed to one modality. Use when the user wants "
        "to SEE the patients rather than count them.",
        extra_properties={"modality": {"type": "string"}},
    ))
    registry.register(report_tool(
        "financial-analysis",
        _financial_analysis,
        "Revenue for a period broken down by payer: patient share, each insurer, discounts, "
        "debt, settled and unsettled counts. Use for income and insurance questions over a "
        "date range. For what the cashier actually took in, use cashier-report instead.\n"
        "DATE BASIS: reception date — this is LIABILITY, not collection.\n"
        "⚠️ REVENUE BASIS: **SERVICE**. Everything here is summed over service lines and "
        "leaves consumables out.\n"
        "**«بیمارها چقدر بدهکارند» is NOT answered from this tool.** "
        "`debt_and_discounts.patient_debt` is the SERVICE-basis balance — 439,530,000 on "
        "1405/06/02, where the real outstanding balance was 705,450,000, because the "
        "267,650,000 of consumables patients were billed for is in neither the share nor "
        "the debt. Ask `finance.metric` for `patient_balance_total`. If you quote this "
        "field anyway, call it «مانده بدهی خدمات» and say the basis — the label used to "
        "claim it was the real balance, and seven benchmark answers repeated the claim.\n"
        "Keep four different things apart, because they are four different questions:\n"
        "  • `revenue.patient_share` — what patients OWE for the SERVICES (their portion "
        "of the service bill; consumables are extra).\n"
        "  • `revenue.insurance_share` — what the INSURER owes the centre. It is a "
        "receivable, not money received, and its date is the reception's, not the "
        "insurer's payment date.\n"
        "  • `debt_and_discounts.paid_amount` — what patients have actually PAID against "
        "those receptions, on any day.\n"
        "  • `debt_and_discounts.patient_debt` — the service-basis remainder.\n"
        "The identity patient_share − paid_amount = patient_debt holds ON THE SERVICE "
        "BASIS; verified on 1405/06/02 as 5,786,640,000 − 5,347,110,000 = 439,530,000. "
        "⚠️ Checking «سهم بیمار + سهم بیمه» against «مبلغ پذیرش‌ها» must compare it to "
        "`service_value`, not `reception_total_value`: 5,786,640,000 + 1,047,270,000 = "
        "6,833,910,000 closes against the service total and is 267,650,000 short of the "
        "reception total. An answer that quotes one and names the other has made the "
        "identity look like it closed when it did not.\n"
        "Do NOT answer a debt question from cashier-report either: its "
        "`withdrawals.receptionDebt` is the day's receptions being debited and is roughly "
        "three times larger. If a question asks how much money came IN, this is the wrong "
        "tool — use cashier-report.\n"
        "⚠️ `cashier.cash` and `cashier.card` here are the same upstream figures "
        "cashier-report publishes; agreement between them corroborates nothing.",
    ))
    registry.register(report_tool(
        "cashier-report",
        _cashier_report,
        "THE CASHIER REPORT as the reception software itself produces it, for a date or "
        "date range: income by cash, card and insurance, withdrawals, net, per-cashier "
        "totals, per-bank-card totals, per-modality totals and discounts. This is the right "
        "source for «گزارش صندوق» / 'the cashier report' / 'what did the cashier take'. "
        "Works for past days as well as today. To check the till against what the day's "
        "receptions should have produced, use cashier-reconciliation instead.\n"
        "DATE BASIS: TRANSACTION date, and this is the one thing that most often goes "
        "wrong. A payment made today against a reception from last week counts HERE today "
        "and in the reception reports on last week's date. So this total is NOT the value "
        "of today's receptions and must never be compared to one as though it were.\n"
        "⚠️ THREE INSTRUMENTS, NOT TWO. «این پول از چه روش‌هایی دریافت شده؟» has three "
        "answers here and an answer that gives two is incomplete even when its arithmetic "
        "is right. Cash was 0 on 1405/06/02, so card and cash-plus-card were the SAME "
        "number that day — quoting either is correct, and stopping there left out the "
        "whole 1,036,030,000 of insurance credit.\n"
        "The figures and how they fit together, measured at the END of 1405/06/02:\n"
        "  • `payment_details.totalCardPayments` + `totalCashPayments` = money through the "
        "till (4,939,790,000 + 0, over 193 card transactions).\n"
        "  • `by_payment_method.insurance.amount` (1,036,030,000) is an insurance CREDIT "
        "posted against receptions, not cash through the drawer — but it IS money "
        "received, and it belongs in any answer about how the money arrived.\n"
        "  • `totals.income` = card + cash + insurance = 5,975,820,000.\n"
        "  • NET = cash + card − manual withdrawals = 4,939,790,000 − 5,720,000 = "
        "4,934,070,000. **Insurance is not in the net.**\n"
        "  • `withdrawals.receptionDebt` (about 7.1bn over 220 rows) is the day's "
        "receptions being debited, not money leaving the building; only "
        "`manualWithdrawal` is an actual withdrawal.\n"
        "  • `discounts` here is the CASH-DESK discount, a different field from a service "
        "or reception discount.",
    ))
    registry.register(report_tool(
        "cashier-deleted-transactions",
        _cashier_deleted_transactions,
        "Detailed, read-only audit of DELETED CASH-DESK TRANSACTIONS for a Jalali date "
        "or range. Use when the user asks who deleted a transaction, which cashier's "
        "transactions were deleted, or needs deleted-transaction amounts by person. "
        "This is not the deleted-reception list: it reads the Transaction audit endpoint. "
        "It keeps `registered_by` (who originally registered the transaction) separate "
        "from `deleted_by` (who deleted it); neither is inferred from the reception "
        "creator. Deletion alone is not proof of an error or misconduct. Patient identity "
        "is excluded by default and should be requested only when the user's task needs it.",
        extra_properties={
            "category": {"type": "string"},
            "userId": {"type": "string"},
            "maxItems": {"type": "integer", "minimum": 1, "maximum": 5000},
            "includePatientDetails": {"type": "boolean"},
        },
    ))
    registry.register(report_tool(
        "cashier-reconciliation",
        _cashier_reconciliation,
        "Checks the cashier's takings AGAINST what the day's receptions should have "
        "produced, and reports the differences and their possible causes. This is a "
        "variance check, not the cashier report — if the user simply asked for the cashier "
        "report, use cashier-report.\n"
        "⚠️ `supporting_financials.patient_debt` here is the SERVICE-basis balance, the "
        "same field `daily-summary` and `financial-analysis` publish — 439,530,000 on "
        "1405/06/02 where patients owed 705,450,000. It is carried as context for the "
        "variance, not as an answer to «چقدر بدهکارند». For that ask `finance.metric` for "
        "`patient_balance_total`; if you quote this one, say «مانده بدهی خدمات».",
    ))
    registry.register(report_tool(
        "physician-performance",
        _physician_performance,
        "Workload and revenue per reporting physician for a period, already ranked: how "
        "many patients each carried, their revenue, and their split by modality. Use for "
        "'which physician did the most', workload comparisons and per-physician activity. "
        "Counts patients ATTRIBUTED TO A PHYSICIAN, which is fewer than the day's total "
        "admissions — for those use daily-summary.",
    ))
    registry.register(report_tool(
        "risk-analysis",
        _risk_analysis,
        "Receptions flagged as financially risky for a period — heavy discounts, repeated "
        "edits, unsettled balances — grouped low/medium/high with the high-risk rows. Use "
        "for 'what should I look at', follow-up and audit questions.",
    ))
    registry.register(report_tool(
        "trend-analysis",
        _trend_analysis,
        "Compares one day against yesterday, last week or last month: admissions, services, "
        "revenue, patient share and cashier inflow, with the modality split for both "
        "periods. Use whenever the question involves 'compared to', 'more than' or a change "
        "over time.",
        extra_properties={"compare": {"type": "string", "enum": ["yesterday", "last-week", "last-month"]}},
    ))
    registry.register(reporting_tool("reporting-queue", _reporting_queue, "Read the clinical reporting worklist"))
    registry.register(reporting_tool("report-current", _report_current, "Read current report content and patient detail", required=["reception_id"]))
    registry.register(reporting_tool("report-logs", _report_logs, "Read report logs and status history"))
    registry.register(reporting_tool("report-print-preview", _report_print_preview, "Build print preview URL and read print settings"))
    registry.register(reporting_tool("report-template-list", _report_template_list, "List locally cached clinical report templates", required=["data_root"]))
    registry.register(reporting_tool("report-template-search", _report_template_search, "Search locally cached clinical report templates", required=["data_root"]))
    registry.register(reporting_tool("report-template-get", _report_template_get, "Read a locally cached clinical report template", required=["data_root", "template_id"]))
    registry.register(reporting_tool("report-template-refresh", _report_template_refresh, "Refresh read-only clinical report template/glossary cache from CRM", required=["data_root"]))
    registry.register(
        reporting_tool(
            "report-draft-plan",
            _report_draft_plan,
            "Build a dry-run clinical report write plan",
            required=["reception_id"],
            safety="clinical_write",
            permission_action="plan",
        )
    )


def report_tool(name: str, handler, description: str, extra_properties: dict[str, Any] | None = None) -> ToolDefinition:
    properties = {
        "date": {"type": "string",
                 "description": "One Jalali day, or `today` / `yesterday`."},
        "days": {"type": "integer",
                 "description": "How many days back from `date`, inclusive."},
        # ⚠️ Declared because the model sends them: these are the names
        # `reception.search` uses, and before they were declared they were
        # accepted, ignored, and the report answered about today.
        "dateFrom": {"type": "string",
                     "description": "Start of a Jalali range. Use WITH dateTo instead of date+days."},
        "dateTo": {"type": "string", "description": "End of a Jalali range."},
        "data_root": {"type": "string"},
    }
    if extra_properties:
        properties.update(extra_properties)
    return ToolDefinition(
        name=name,
        kind="skill",
        handler=handler,
        description=description,
        safety="read",
        permission_action="read",
        input_schema={
            "type": "object",
            "required": ["data_root"],
            "properties": properties,
        },
        audit=True,
    )


def reporting_tool(
    name: str,
    handler,
    description: str,
    required: list[str] | None = None,
    safety: str = "read",
    permission_action: str = "read",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        kind="skill",
        handler=handler,
        description=description,
        safety=safety,
        permission_action=permission_action,
        input_schema={
            "type": "object",
            "required": required or [],
            "properties": {
                "reception_id": {"type": "string"},
                "workflow_id": {"type": "string"},
                "data_root": {"type": "string"},
                "template_id": {"type": "string"},
                "modality_id": {"type": "string"},
                "category": {"type": "string"},
                "priority": {"type": "string"},
                "personnel_id": {"type": "string"},
                "source": {"type": "string"},
                "query": {"type": "string"},
                "include_html": {"type": "boolean"},
                "max_content_chars": {"type": "integer"},
                "page": {"type": "integer"},
                "limit": {"type": "integer"},
                "startDate": {"type": "string"},
                "endDate": {"type": "string"},
                "search": {"type": "string"},
                "modality": {"type": "string"},
                "status": {"type": "string"},
                "radiologist": {"type": "string"},
                "hasVoiceAttachment": {"type": "string", "enum": ["yes", "no", ""]},
                "report_text": {"type": "string"},
                "report_html": {"type": "string"},
                "target_status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "awaiting_physician_approval",
                        "awaiting_approval",
                        "physician_approved",
                        "awaiting_secretary_approval",
                        "secretary_approved",
                        "completed",
                        "archived",
                    ],
                },
            },
        },
        audit=True,
    )


def _period(args: dict[str, Any]):
    """The period these tools read, from `date`+`days` OR from `dateFrom`/`dateTo`.

    ⚠️ THE RANGE FORM EXISTS BECAUSE THE OLD ONE ANSWERED ABOUT TODAY. These
    tools took `date` and `days` and nothing else. `reception.search` — the tool
    beside them — takes `dateFrom` and `dateTo`, so the model reasonably sent
    those here too, and they were dropped in silence: `date` fell back to
    "today" and the report answered about a day nobody had asked for. The
    benchmark caught it three times (M2 and G2 asked for two named days and got
    a third; S2 compared a correct reception search against a cashier report for
    the wrong day). The agent noticed and said so, which is the only reason it
    was visible at all.

    Accepting the sibling tool's own parameter names is half the fix; the other
    half is `validation.validate_input`, which now REFUSES a name neither form
    declares rather than ignoring it.
    """
    start = args.get("dateFrom")
    end = args.get("dateTo")
    if start or end:
        # One end given is a single day, not an open range: an unbounded report
        # over a clinical archive is never what was meant.
        start = start or end
        end = end or start
        span = (jalali_to_gregorian(str(end)) - jalali_to_gregorian(str(start))).days + 1
        if span < 1:
            # Reversed, so the caller's intent is clear and their order is not.
            start, end, span = end, start, -span + 2
        return resolve_period(str(end), days=span)
    # ⚠️ `args.get("date", "today")` — the literal string — is what used to be
    # passed, and it told `resolve_day` that somebody had SAID "today". Nobody
    # had. `DayResolution.assumed` exists to mark exactly that difference, and
    # substituting a default before the resolver sees it threw the distinction
    # away, so an answer about a day nobody named could not say so.
    return resolve_period(args.get("date") or "", days=int(args.get("days", 1)))


def _data_root(args: dict[str, Any]) -> Path:
    return Path(args["data_root"])


def _daily_summary(args: dict[str, Any]) -> dict[str, Any]:
    return daily_summary(_period(args), _data_root(args))


def _patient_list(args: dict[str, Any]) -> dict[str, Any]:
    return patient_list(_period(args), _data_root(args), modality=args.get("modality"))


def _financial_analysis(args: dict[str, Any]) -> dict[str, Any]:
    return financial_analysis(_period(args), _data_root(args))


def _cashier_reconciliation(args: dict[str, Any]) -> dict[str, Any]:
    return cashier_reconciliation(_period(args), _data_root(args))


def _cashier_report(args: dict[str, Any]) -> dict[str, Any]:
    return cashier_report(_period(args), _data_root(args))


def _cashier_deleted_transactions(args: dict[str, Any]) -> dict[str, Any]:
    return cashier_deleted_transactions(
        _period(args),
        _data_root(args),
        category=args.get("category"),
        user_id=args.get("userId"),
        max_items=int(args.get("maxItems", 5000)),
        include_patient_details=bool(args.get("includePatientDetails")),
    )


def _physician_performance(args: dict[str, Any]) -> dict[str, Any]:
    return physician_performance(_period(args), _data_root(args))


def _risk_analysis(args: dict[str, Any]) -> dict[str, Any]:
    return risk_analysis(_period(args), _data_root(args))


def _trend_analysis(args: dict[str, Any]) -> dict[str, Any]:
    return trend_analysis(_period(args), _data_root(args), compare=args.get("compare", "yesterday"))


def _client() -> InoClient:
    client = InoClient.from_env()
    client.login()
    return client


def _reporting_queue(args: dict[str, Any]) -> dict[str, Any]:
    from ...local import datamodel as dm
    from ...local.mongo import LocalMongoUnavailable
    from ...lexicon import center

    modality = args.get("modality")
    if modality not in (None, ""):
        try:
            concept = center.resolve_clinical_concept(str(modality))
            if concept.level in {"service", "service_group"}:
                return {
                    "available": True,
                    "error": {"code": "SERVICE_FILTER_REQUIRED",
                              "message": "This concept is a service, not one department. "
                                         "Use reception.search or report.search with service and dates.",
                              "resolution": concept.as_dict()},
                }
            resolved = dm.resolve_modality(modality)
            if resolved.disabled:
                raise dm.DisabledValue("modality", str(modality), [resolved.label])
            modality = resolved.code
        except dm.FilterValueProblem as exc:
            return {"available": True, "error": exc.as_dict()}
        except LocalMongoUnavailable:
            return {"available": False, "error": {"code": "CENTER_CATALOG_UNAVAILABLE",
                    "message": "Run bootstrap-center on this installation before filtering departments."}}
    client = _client()
    raw = client.reporting_worklist(
        reception_id=args.get("reception_id"),
        page=int(args.get("page", 1)),
        limit=int(args.get("limit", 20)),
        start_date=args.get("startDate"),
        end_date=args.get("endDate"),
        search=args.get("search"),
        modality=modality,
        status=args.get("status"),
        radiologist=args.get("radiologist"),
        has_voice_attachment=args.get("hasVoiceAttachment"),
        include_stats=True,
    )
    rows = _extract_rows(raw)
    return {
        "skill": "reporting-queue",
        "count": len(rows),
        "rows": [_normalize_reporting_row(row) for row in rows],
        "pagination": raw.get("pagination") if isinstance(raw, dict) else None,
        "statistics": raw.get("statistics") if isinstance(raw, dict) else None,
        "filters": raw.get("filters") if isinstance(raw, dict) else None,
        "raw_success": raw.get("success") if isinstance(raw, dict) else None,
    }


def _report_current(args: dict[str, Any]) -> dict[str, Any]:
    reception_id = str(args["reception_id"])
    client = _client()
    workflow = _resolve_workflow(client, reception_id, args.get("workflow_id"))
    report = client.pacs_report(reception_id)
    patient_detail = client.pacs_patient_detail(reception_id)
    report_data = _payload_data(report)
    patient_data = _payload_data(patient_detail)
    return {
        "skill": "report-current",
        "reception_id": reception_id,
        "workflow_id": workflow.get("workflow_id"),
        "worklist_row": workflow.get("row"),
        "patient": _patient_summary(patient_data),
        "services": patient_data.get("services") or [],
        "report": _report_summary(report_data.get("report") or patient_data.get("report") or {}),
        "workflow_status": patient_data.get("workflowStatus"),
        "created_at": patient_data.get("createdAt"),
        "updated_at": patient_data.get("updatedAt"),
    }


def _report_logs(args: dict[str, Any]) -> dict[str, Any]:
    client = _client()
    workflow_id = args.get("workflow_id")
    reception_id = args.get("reception_id")
    workflow: dict[str, Any] = {}
    if not workflow_id:
        if not reception_id:
            raise ValueError("Either workflow_id or reception_id is required.")
        workflow = _resolve_workflow(client, str(reception_id), None)
        workflow_id = workflow["workflow_id"]
    logs = client.report_logs(
        workflow_id,
        page=int(args.get("page", 1)),
        limit=int(args.get("limit", 50)),
        action=args.get("action"),
        field=args.get("field"),
        start_date=args.get("startDate"),
        end_date=args.get("endDate"),
        changed_by=args.get("changedBy"),
        sort=args.get("sort", "desc"),
    )
    history = client.report_status_history(workflow_id)
    return {
        "skill": "report-logs",
        "workflow_id": workflow_id,
        "reception_id": str(reception_id or logs.get("receptionID") or ""),
        "worklist_row": workflow.get("row"),
        "logs": logs.get("data") if isinstance(logs, dict) else logs,
        "pagination": logs.get("pagination") if isinstance(logs, dict) else None,
        "statistics": logs.get("statistics") if isinstance(logs, dict) else None,
        "status_history": history,
    }


def _report_print_preview(args: dict[str, Any]) -> dict[str, Any]:
    client = _client()
    workflow_id = args.get("workflow_id")
    reception_id = args.get("reception_id")
    workflow: dict[str, Any] = {}
    if not workflow_id:
        if not reception_id:
            raise ValueError("Either workflow_id or reception_id is required.")
        workflow = _resolve_workflow(client, str(reception_id), None)
        workflow_id = workflow["workflow_id"]
    settings = client.report_settings()
    stamp_settings = client.stamp_settings()
    layout = client.print_layout()
    host = client.host.replace("http://", "").replace("https://", "").strip("/")
    preview_url = f"http://{host}/printReportCanvas?id={workflow_id}"
    return {
        "skill": "report-print-preview",
        "workflow_id": workflow_id,
        "reception_id": str(reception_id or ""),
        "preview_url": preview_url,
        "worklist_row": workflow.get("row"),
        "layout_name": (_payload_data(layout) or {}).get("templateName"),
        "paper_size": (_payload_data(layout) or {}).get("paperSize"),
        "report_settings": (_payload_data(settings) or {}).get("reportSettings"),
        "stamp_settings": _payload_data(stamp_settings),
    }


def _report_draft_plan(args: dict[str, Any]) -> dict[str, Any]:
    reception_id = str(args["reception_id"])
    target_status = args.get("target_status") or "awaiting_physician_approval"
    report_html = args.get("report_html") or build_report_html(args.get("report_text") or "")
    if not _text_from_html(report_html).strip():
        raise ValueError("report_text or report_html is required.")

    current = _report_current({"reception_id": reception_id, "workflow_id": args.get("workflow_id")})
    workflow_id = current["workflow_id"]
    flags = approval_flags_for_status(target_status)
    registry = load_operations()
    content_plan = registry.plan(
        "reports.update_content",
        {
            "ReceptionID": reception_id,
            "content": report_html,
            "findings": report_html,
            "status": target_status,
            "patient": current["patient"].get("name"),
            "service": _service_names(current.get("services") or []),
            "contentPreview": _text_from_html(report_html)[:300],
            "priorStatus": current["report"].get("status"),
            "priorVersionHash": _simple_hash(current["report"].get("html") or ""),
        },
    )
    flags_plan = registry.plan(
        "reports.approval_flags",
        {
            "workflowId": workflow_id,
            "physicianApproved": flags["physicianApproved"],
            "secretaryApproved": flags["secretaryApproved"],
            "ReceptionID": reception_id,
            "patient": current["patient"].get("name"),
            "targetStatus": target_status,
            "actor": "pending_identity_binding",
        },
    )
    return {
        "skill": "report-draft-plan",
        "dry_run_only": True,
        "execution_enabled": False,
        "message": "این فقط پیش‌نویس عملیات است؛ چیزی در CRM ثبت نشده است.",
        "reception_id": reception_id,
        "workflow_id": workflow_id,
        "target_status": target_status,
        "approval_flags": flags,
        "patient": current["patient"],
        "services": _service_names(current.get("services") or []),
        "report_html": report_html,
        "content_plan": content_plan.as_dict(),
        "approval_flags_plan": flags_plan.as_dict(),
        "required_before_execution": [
            "binding actor to a real physician/personnel identity",
            "out-of-band human confirmation",
            "before/after audit snapshot",
            "idempotency hash check",
            "read-back verification from /api/pacs/report/{ReceptionID}",
        ],
    }


def _report_template_list(args: dict[str, Any]) -> dict[str, Any]:
    templates = _filtered_templates(args)
    return {
        "skill": "report-template-list",
        "template_root": str(_template_root(args)),
        "filters": _template_filters(args),
        "count": len(templates),
        "templates": [_template_summary(data, path) for data, path in templates[: int(args.get("limit") or 500)]],
    }


def _report_template_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("search") or "").strip()
    templates = _filtered_templates(args)
    ranked = sorted(
        ((_template_score(data, query), data, path) for data, path in templates),
        key=lambda item: (-item[0], str(item[1].get("title") or "")),
    )
    ranked = [item for item in ranked if item[0] > 0 or not query]
    limit = int(args.get("limit") or 20)
    include_html = bool(args.get("include_html"))
    max_content_chars = int(args.get("max_content_chars") or 600)
    results = []
    for score, data, path in ranked[:limit]:
        summary = _template_summary(data, path)
        summary["score"] = score
        summary["plain_preview"] = _text_from_html(str(data.get("content_html") or data.get("html") or ""))[:max_content_chars]
        if include_html:
            summary["content_html"] = str(data.get("content_html") or data.get("html") or "")[:max_content_chars]
        results.append(summary)
    return {
        "skill": "report-template-search",
        "template_root": str(_template_root(args)),
        "filters": _template_filters(args),
        "query": query,
        "count": len(results),
        "results": results,
    }


def _report_template_get(args: dict[str, Any]) -> dict[str, Any]:
    template_id = str(args["template_id"])
    for data, path in _local_templates(_template_root(args)):
        if str(data.get("template_id") or data.get("id") or path.stem) == template_id:
            content_html = str(data.get("content_html") or data.get("html") or "")
            return {
                "skill": "report-template-get",
                "path": str(path),
                "summary": _template_summary(data, path),
                "template": data,
                "content_html": content_html,
                "plain_text": _text_from_html(content_html),
                "ready_for_report_draft_plan": bool(content_html.strip()),
            }
    raise ValueError(f"Template not found: {template_id}")


def _report_template_refresh(args: dict[str, Any]) -> dict[str, Any]:
    template_root = _template_root(args)
    discovery_root = template_root / "crm_discovery"
    discovery_root.mkdir(parents=True, exist_ok=True)
    client = _client()
    sample_cache = _cache_sample_reports(client, template_root)
    modality_candidates = _template_modality_candidates(client, args)
    glossary_results = []
    for modality_id in modality_candidates:
        try:
            data = client.get_json(f"/api/radiology-glossary/{modality_id}")
            glossary_results.append({"modality_id": modality_id, "ok": True, "data": data})
        except Exception as exc:  # pragma: no cover - live CRM shape varies
            glossary_results.append({"modality_id": modality_id, "ok": False, "error": str(exc)})

    probe_paths = [
        "/api/report-templates",
        "/api/ReportTemplates",
        "/api/ReportTemplate",
        "/api/templates",
        "/api/Templates",
        "/api/pacs/report-templates",
        "/api/pacs/templates",
        "/api/Reports/templates",
        "/api/normal-reports",
        "/api/NormalReports",
        "/api/radiology-templates",
        "/api/RadiologyTemplates",
        "/api/reporting/templates",
        "/api/imagingWorkflow/report/templates",
    ]
    template_endpoint_results = []
    for path in probe_paths:
        try:
            data = client.get_json(path)
            template_endpoint_results.append({"path": path, "ok": True, "data": data})
        except Exception as exc:  # pragma: no cover - live CRM shape varies
            template_endpoint_results.append({"path": path, "ok": False, "error": str(exc)})

    successful_glossary = [item for item in glossary_results if item["ok"]]
    successful_templates = [item for item in template_endpoint_results if item["ok"]]
    snapshot = {
        "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "modality_candidates": modality_candidates,
        "sample_reports": sample_cache,
        "glossary_results": glossary_results,
        "template_endpoint_results": template_endpoint_results,
        "conclusion": (
            "The clinical report editor uses /api/sample-reports for the UI sample/template list. "
            "radiology-glossary is a separate editor term-completion resource."
        ),
    }
    snapshot_path = discovery_root / f"template_refresh_{snapshot['created_at'].replace(':', '')}.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "skill": "report-template-refresh",
        "snapshot_path": str(snapshot_path),
        "successful_glossary_count": len(successful_glossary),
        "successful_template_endpoint_count": len(successful_templates),
        "successful_template_paths": [item["path"] for item in successful_templates],
        "modality_candidates": modality_candidates,
        "sample_reports_count": sample_cache["count"],
        "sample_reports_index_path": sample_cache["index_path"],
        "local_template_count": _report_template_list(args)["count"],
    }


def _extract_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    return data if isinstance(data, list) else []


def _payload_data(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    return data if isinstance(data, dict) else raw


def _resolve_workflow(client: InoClient, reception_id: str, workflow_id: str | None) -> dict[str, Any]:
    if workflow_id:
        return {"workflow_id": workflow_id, "row": None}
    raw = client.reporting_worklist(reception_id=reception_id, page=1, limit=5, include_stats=False)
    for row in _extract_rows(raw):
        if str(row.get("receptionID")) == str(reception_id):
            return {"workflow_id": row.get("receptionId"), "row": _normalize_reporting_row(row)}
    raise ValueError(f"Could not resolve workflow id for reception {reception_id}.")


def _normalize_reporting_row(row: dict[str, Any]) -> dict[str, Any]:
    patient = row.get("patient") or {}
    report = row.get("report") or {}
    modality = row.get("modality") or {}
    registered_by = row.get("registeredBy") or {}
    return {
        "workflow_id": row.get("receptionId"),
        "reception_id": row.get("receptionID"),
        "date": row.get("date"),
        "time": row.get("time"),
        "patient_name": patient.get("Name") or patient.get("name"),
        "national_code": patient.get("nationalCode") or patient.get("NationalID"),
        "modality": modality.get("name") or modality.get("PerFullName") or modality.get("Modality"),
        "registered_by": registered_by.get("fullName") or registered_by.get("FullName") or registered_by.get("username"),
        "workflow_status": row.get("workflowStatus"),
        "report_status": report.get("status"),
        "report_date": report.get("reportDate"),
        "radiologist": report.get("radiologist"),
        "voice_attachments_count": row.get("voiceAttachmentsCount"),
        "services": _service_names(row.get("services") or []),
    }


def _patient_summary(data: dict[str, Any]) -> dict[str, Any]:
    patient = data.get("patient") or {}
    return {
        "id": patient.get("_id") or patient.get("id"),
        "name": patient.get("Name") or patient.get("name"),
        "national_code": patient.get("NationalID") or data.get("nationalCode"),
        "age": patient.get("Age"),
        "tel": patient.get("Tel"),
    }


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    html_body = report.get("findings") or report.get("content") or ""
    return {
        "status": report.get("status"),
        "report_date": report.get("reportDate") or report.get("date"),
        "radiologist": report.get("radiologist"),
        "typist": report.get("typist"),
        "approved_by": report.get("approvedBy"),
        "approval_flags": report.get("approvalFlags") or {},
        "has_voice": bool((report.get("pacsVoice") or {}).get("hasVoice")),
        "html": html_body,
        "plain_text": _text_from_html(html_body),
        "is_empty": not bool(_text_from_html(html_body).strip()),
    }


def _service_names(services: list[dict[str, Any]]) -> list[str]:
    names = []
    for service in services:
        if isinstance(service, dict):
            name = service.get("Service") or service.get("service")
            if name:
                names.append(str(name))
    return names


def approval_flags_for_status(status: str) -> dict[str, bool]:
    return {
        "physicianApproved": status in {"physician_approved", "awaiting_secretary_approval", "secretary_approved", "completed", "archived"},
        "secretaryApproved": status in {"secretary_approved", "completed", "archived"},
    }


def build_report_html(text: str) -> str:
    lines = [line.strip() for line in str(text).replace("\r\n", "\n").split("\n")]
    paragraphs = []
    for line in lines:
        if not line:
            paragraphs.append('<p style="text-align: right; direction: rtl;"></p>')
            continue
        paragraphs.append(
            '<p style="text-align: right; direction: rtl;">'
            '<span style="font-family: &quot;Times New Roman&quot;; font-size: 18px;">'
            f"{_wrap_ltr_segments(line)}"
            "</span></p>"
        )
    return "".join(paragraphs)


LTR_SEGMENT_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9\s:/().*+%\\-]*[A-Za-z0-9%)]|[0-9])")
TAG_RE = re.compile(r"<[^>]+>")


def _wrap_ltr_segments(text: str) -> str:
    escaped = html.escape(text, quote=False)

    def replace(match: re.Match[str]) -> str:
        value = match.group(1)
        if not re.search(r"[A-Za-z0-9]", value):
            return value
        return f'<span dir="ltr" style="direction: ltr; unicode-bidi: normal;">{value}</span>'

    return LTR_SEGMENT_RE.sub(replace, escaped)


def _text_from_html(value: str | None) -> str:
    if not value:
        return ""
    without_tags = TAG_RE.sub(" ", str(value))
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def _simple_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _template_root(args: dict[str, Any]) -> Path:
    return Path(args["data_root"]) / "data" / "templates" / "report"


def _template_summary(data: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "template_id": data.get("template_id") or data.get("id") or path.stem,
        "title": data.get("title_fa") or data.get("title") or data.get("name") or path.stem,
        "modality": data.get("modality"),
        "modality_id": data.get("modality_id"),
        "body_part": data.get("body_part"),
        "category": data.get("category"),
        "priority": data.get("priority"),
        "language": data.get("language"),
        "source": data.get("source"),
        "verified_on_reception_id": data.get("verified_on_reception_id"),
        "verified_text_saved": data.get("verified_text_saved"),
        "html_chars": len(str(data.get("content_html") or data.get("html") or "")),
        "path": str(path),
    }


def _template_modality_candidates(client: InoClient, args: dict[str, Any]) -> list[str]:
    candidates = []
    if args.get("modality_id"):
        candidates.append(str(args["modality_id"]))
    if args.get("reception_id"):
        try:
            raw = client.reporting_worklist(reception_id=args.get("reception_id"), page=1, limit=5, include_stats=False)
            for row in _extract_rows(raw):
                modality = row.get("modality") or {}
                for key in ("id", "_id", "Modality", "modality", "code", "name"):
                    value = modality.get(key)
                    if value is not None:
                        candidates.append(str(value))
        except Exception:
            pass
    candidates.extend(["3", "US", "ultrasound"])
    deduped = []
    for value in candidates:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _cache_sample_reports(client: InoClient, template_root: Path) -> dict[str, Any]:
    from datetime import datetime

    base = template_root / "crm_sample_reports"
    raw_dir = base / "raw"
    html_dir = base / "html"
    json_dir = base / "json"
    for directory in (raw_dir, html_dir, json_dir):
        directory.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().isoformat(timespec="seconds")
    pages, items = _fetch_sample_report_pages(client, {})
    raw_path = raw_dir / f"sample_reports_all_{created_at.replace(':', '')}.json"
    raw_path.write_text(
        json.dumps(
            {"created_at": created_at, "endpoint": "/api/sample-reports", "query": {}, "pages": pages},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    seen = set()
    unique = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("_id") or item.get("id") or item.get("Name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    index = []
    for number, item in enumerate(unique, 1):
        template_id = str(item.get("_id") or item.get("id") or f"row-{number:03d}")
        title = str(item.get("Name") or item.get("title") or f"template-{number:03d}").strip()
        content_html = str(item.get("Html") or item.get("html") or item.get("content") or "")
        filename = f"{number:03d}-{_safe_filename(title)}-{_safe_filename(template_id, 'id')}"
        json_path = json_dir / f"{filename}.json"
        html_path = html_dir / f"{filename}.html"
        normalized = {
            "template_id": template_id,
            "title": title,
            "source": "crm_ui_sample_reports",
            "endpoint": "/api/sample-reports",
            "modality_id": str(item.get("Modality") or ""),
            "cached_at": created_at,
            "category": item.get("Category"),
            "priority": item.get("Priority"),
            "personnel": item.get("Personnel"),
            "user": item.get("User"),
            "disabled": item.get("Disabled"),
            "usage_count": item.get("UsageCount"),
            "last_used": item.get("LastUsed"),
            "created_at": item.get("CreatedAt"),
            "updated_at": item.get("UpdatedAt"),
            "tags": item.get("Tags") or [],
            "content_html": content_html,
            "raw": item,
        }
        json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        html_path.write_text(content_html, encoding="utf-8")
        index.append(
            {
                "template_id": template_id,
                "title": title,
                "modality_id": str(item.get("Modality") or ""),
                "category": item.get("Category"),
                "priority": item.get("Priority"),
                "personnel": item.get("Personnel"),
                "user": item.get("User"),
                "disabled": item.get("Disabled"),
                "usage_count": item.get("UsageCount"),
                "html_chars": len(content_html),
                "json_path": str(json_path),
                "html_path": str(html_path),
            }
        )

    index_path = base / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "created_at": created_at,
                "endpoint": "/api/sample-reports",
                "count": len(index),
                "raw_path": str(raw_path),
                "templates": index,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    categorized = _write_template_category_indexes(base, index)
    return {"count": len(index), "index_path": str(index_path), "raw_path": str(raw_path), "categorized": categorized}


def _fetch_sample_report_pages(client: InoClient, query: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages = []
    items = []
    page = 1
    limit = 100
    while True:
        params = {**query, "limit": limit, "page": page}
        response = client.get_json("/api/sample-reports", params)
        data = response.get("data") if isinstance(response, dict) else []
        batch = data if isinstance(data, list) else []
        pages.append({"page": page, "params": params, "response": response})
        items.extend(batch)
        pagination = response.get("pagination") if isinstance(response, dict) else {}
        total_pages = int((pagination or {}).get("pages") or page)
        if page >= total_pages or not batch:
            break
        page += 1
    return pages, items


def _safe_filename(value: Any, fallback: str = "template") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return (text or fallback)[:100]


def _local_templates(template_root: Path) -> list[tuple[dict[str, Any], Path]]:
    templates = []
    for path in sorted(template_root.rglob("*.json")):
        if any(part in path.parts for part in {"crm_discovery", "raw", "indexes"}):
            continue
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not (data.get("template_id") or data.get("id")):
            continue
        templates.append((data, path))
    return templates


def _template_filters(args: dict[str, Any]) -> dict[str, Any]:
    return {
        key: args.get(key)
        for key in ("query", "search", "modality_id", "category", "priority", "personnel_id", "source")
        if args.get(key) not in {None, ""}
    }


def _filtered_templates(args: dict[str, Any]) -> list[tuple[dict[str, Any], Path]]:
    filters = _template_filters(args)
    return [(data, path) for data, path in _local_templates(_template_root(args)) if _template_matches(data, filters)]


def _template_matches(data: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("source") and str(data.get("source") or "") != str(filters["source"]):
        return False
    if filters.get("modality_id") and str(data.get("modality_id") or data.get("modality") or "") != str(filters["modality_id"]):
        return False
    if filters.get("category") and str(data.get("category") or "") != str(filters["category"]):
        return False
    if filters.get("priority") and str(data.get("priority") or "") != str(filters["priority"]):
        return False
    if filters.get("personnel_id"):
        personnel = data.get("personnel") or {}
        personnel_id = personnel.get("_id") if isinstance(personnel, dict) else personnel
        if str(personnel_id or "") != str(filters["personnel_id"]):
            return False
    query = str(filters.get("query") or filters.get("search") or "").strip()
    if query and _normalize_search_text(query) not in _normalize_search_text(_template_search_blob(data)):
        return False
    return True


def _template_score(data: dict[str, Any], query: str) -> int:
    if not query:
        return 1
    needle = _normalize_search_text(query)
    title = _normalize_search_text(str(data.get("title") or data.get("title_fa") or ""))
    blob = _normalize_search_text(_template_search_blob(data))
    score = 0
    if needle == title:
        score += 100
    if needle in title:
        score += 50
    if needle in blob:
        score += 10
    for token in needle.split():
        if token and token in title:
            score += 5
        elif token and token in blob:
            score += 1
    return score


def _template_search_blob(data: dict[str, Any]) -> str:
    personnel = data.get("personnel") or {}
    personnel_text = ""
    if isinstance(personnel, dict):
        personnel_text = " ".join(str(personnel.get(key) or "") for key in ("FirstName", "LastName", "Speciality", "_id"))
    return " ".join(
        [
            str(data.get("title") or data.get("title_fa") or ""),
            str(data.get("category") or ""),
            str(data.get("priority") or ""),
            str(data.get("modality") or data.get("modality_id") or ""),
            personnel_text,
            _text_from_html(str(data.get("content_html") or data.get("html") or "")),
        ]
    )


def _normalize_search_text(value: str) -> str:
    return (
        str(value)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("‌", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .lower()
    )


def _write_template_category_indexes(base: Path, index: list[dict[str, Any]]) -> dict[str, str]:
    index_dir = base / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "by_modality": _group_templates(index, "modality_id"),
        "by_category": _group_templates(index, "category"),
        "by_priority": _group_templates(index, "priority"),
        "by_personnel": _group_templates(index, "personnel"),
    }
    paths = {}
    for name, payload in outputs.items():
        path = index_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        paths[name] = str(path)
    return paths


def _group_templates(index: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in index:
        value: Any
        if key == "personnel":
            raw = item.get("personnel")
            if isinstance(raw, dict):
                value = raw.get("_id") or "unassigned"
            else:
                value = raw or "unassigned"
        else:
            value = item.get(key) or "unknown"
        grouped.setdefault(str(value), []).append(item)
    return grouped
