"""Counting receptions by the field the question is about.

`report.search` searches the TEXT of reports. These two search the reception
RECORD — what was performed, for whom, under which insurer, on which machine —
which is a different question and, until now, one the agent could not ask.

The tool descriptions below are the tool-SELECTION prompt: they are what the
model reads when deciding where a question goes. `reception.search` says
explicitly that mammography and bone density are services rather than
modalities, because that single confusion produced a confidently wrong clinical
answer and a description is where it is cheapest to prevent.
"""

from __future__ import annotations

from typing import Any

from ...local import datamodel as dm
from ...local import receptions as local_receptions
from ...local.mongo import LocalMongoUnavailable, ScanBusy
from ..registry import ToolRegistry
from ..types import ToolDefinition


def _fail(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, dm.FilterValueProblem):
        # The defect this whole module exists for: an unknown value used to
        # produce a filter that matched nothing, and "no such modality" read as
        # "no such patients". Now it comes back as a refusal that names what
        # DOES exist, so the answer can say so.
        return {"error": exc.as_dict(), "count": None}
    if isinstance(exc, local_receptions.FilterError):
        return {"error": {"code": exc.code, "message": str(exc)}, "count": None}
    if isinstance(exc, ScanBusy):
        return {"error": {"code": exc.code, "message": str(exc)}, "count": None}
    if isinstance(exc, LocalMongoUnavailable):
        return {"error": {"code": exc.code, "message": str(exc)}, "count": None}
    raise exc


def _search(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return local_receptions.search(
            modality=args.get("modality"),
            service=args.get("service"),
            insurance=args.get("insurance"),
            report_status=args.get("reportStatus"),
            date_from=args.get("dateFrom"),
            date_to=args.get("dateTo"),
            group_by=args.get("groupBy"),
            limit=args.get("limit", local_receptions.DEFAULT_LIMIT),
            deleted_only=bool(args.get("deletedOnly")),
            discounted_only=bool(args.get("discountedOnly")),
        )
    except Exception as exc:  # noqa: BLE001 - narrowed inside _fail
        return _fail(exc)


def _vocabulary(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return local_receptions.vocabulary(
            str(args.get("field") or "modality"),
            date_from=args.get("dateFrom"),
            date_to=args.get("dateTo"),
            contains=args.get("contains"),
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def register_reception_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="reception.search",
            kind="skill",
            handler=_search,
            description=(
                "Count and list RECEPTIONS by what was performed and for whom — service, "
                "modality, insurance, report status, Jalali date range — with an optional "
                "breakdown (groupBy: modality, service, insurance, reportStatus, date). "
                "Use this for 'how many …' questions about procedures and admissions. "
                "IMPORTANT: `modality` is the machine (CT, MRI, Sonography, Radiology, "
                "Bone Density); `service` is the procedure actually billed. Mammography and "
                "bone-density questions must use `service` — mammograms in this centre are "
                "recorded as services under Radiology and MRI, not under a mammography "
                "modality. Service terms are resolved through this centre's service lexicon: "
                "for example «کمر», «لومبر», «لومبار» and `lumbar` are one concept here. "
                "The result publishes `expandedTerms`, matched catalogue names and the exact "
                "performed service names, so use those fields to verify what was counted. "
                "Never replace that resolution with one hand-written substring. A service "
                "filter requires a date range.\n"
                "RETURNS `totals` with THREE counts plus the discount money, each "
                "computed over the whole match "
                "and none of them affected by how many rows are shown: `patients` "
                "(distinct people), `receptions` (visits), `serviceLines` (procedures), "
                "`discountAmount` (rials discounted across the matched receptions). "
                "Answer «چند بیمار» from totals.patients, «چند پذیرش» from "
                "totals.receptions, «چند خدمت» from totals.serviceLines, and «چه مبلغی "
                "تخفیف» from totals.discountAmount. `rows` is a "
                "display sample only — never count it, and never say a figure is "
                "unavailable because the row list is short. With `groupBy`, every bucket "
                "carries the same three counts. `limit` only changes how many rows are "
                "rendered; it never changes a number.\n"
                "groupBy also accepts `hour` and `halfHour` (peak-time questions — "
                "«پیک پذیرش چه ساعتی بوده») and `cashier`. "
                "`discountedOnly: true` returns only receptions carrying a discount "
                "(the discount lives in cashDeskDiscount, not discountTotal); state "
                "totals.discountAmount alongside the count — a discount answer that "
                "gives only how MANY and not how MUCH is half an answer. "
                "`deletedOnly: true` returns only DELETED receptions — note a deleted "
                "reception and a deleted cashier transaction are different records; "
                "this filter means the former. "
                "For «با تزریق» / «با کنتراست» pass it as `service`: this centre names "
                "services «با/بدون ماده حاجب» and never «تزریق», and the tool resolves "
                "the intent — do not build your own text match, because «کنتراست» also "
                "appears in every «بدون کنتراست» service."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "modality": {"type": "string"},
                    "insurance": {"type": "string"},
                    "reportStatus": {"type": "string"},
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "groupBy": {
                        "type": "string",
                        "enum": ["modality", "service", "hour", "halfHour",
                                 "cashier", "insurance", "reportStatus", "date"],
                    },
                    "limit": {"type": "integer"},
                    "deletedOnly": {"type": "boolean"},
                    "discountedOnly": {"type": "boolean"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="reception.vocabulary",
            kind="skill",
            handler=_vocabulary,
            description=(
                "What values a reception field actually contains — the modalities that "
                "exist, the services in the catalogue (optionally filtered by `contains`), "
                "and, when a date range is supplied, the exact performed service names in "
                "that period. `contains` is expanded through the centre service lexicon and "
                "the response includes the resolution provenance. Call this when a filtered "
                "count comes back 0, or before guessing at a term: a zero next to a "
                "non-zero unfiltered count usually means the filter value does not exist "
                "rather than that the patients do not."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "contains": {"type": "string"},
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                },
            },
        )
    )
