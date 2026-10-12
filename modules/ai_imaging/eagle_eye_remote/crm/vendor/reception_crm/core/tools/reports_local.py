"""Clinical report tools that read the reception database on this machine.

These four exist because the vendor's HTTP API has no endpoint for them. There
is no way to ask it "which reports mention BI-RADS 3 last month", and no way to
get one patient's reports side by side. Both are one query against the local
database, where 25,375 report bodies already live.

They are ordinary registry tools: ``safety="read"``, ``permission_action="read"``,
audited, and filtered by ``roles.json`` exactly like every API-backed tool. The
only thing different about them is where the data comes from.

Every one degrades to a plain, explanatory error when the local database is not
reachable -- an agent installed somewhere other than the reception server keeps
working, it just cannot answer these.
"""

from __future__ import annotations

from typing import Any

from ...local import datamodel as dm
from ...local import reports as local_reports
from ...local.mongo import LocalMongoUnavailable, ScanBusy
from ..registry import ToolRegistry
from ..types import ToolDefinition


def register_local_report_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="report.get",
            kind="skill",
            handler=_get,
            description=(
                "Read one clinical report as plain text. Give receptionId for a specific study, "
                "or nationalCode for that patient's most recent report. Use this to summarize, "
                "explain or quote a report."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "receptionId": {"type": "integer"},
                    "nationalCode": {"type": "string"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="report.search",
            kind="skill",
            handler=_search,
            description=(
                "Search clinical REPORT TEXT for any user-named word, disease or finding, and "
                "return the matching patients/studies with evidence snippets. This is the "
                "generic cohort tool for questions such as lumbar-MRI reports with disc "
                "bulging, brain-MRI reports mentioning atrophy AND small-vessel disease, CT "
                "reports with a named finding, or mammography services with BI-RADS 3. "
                "Narrow the SAME search by Jalali date range, service (the billed procedure), "
                "modality and report status — do not fetch reception.search and try to "
                "intersect row samples yourself. A service filter requires both dateFrom "
                "and dateTo. The service argument is resolved through this centre's service "
                "lexicon (for example «کمر» also searches the centre's «لومبر/لومبار» service "
                "names), and the returned filters show the canonical concept, expanded terms "
                "and matching catalogue services. Do not substitute one literal substring. "
                "`query` names the criterion. For spelling/synonym alternatives, pass the "
                "actual report phrases in `queries` and use matchMode=`any`; use `all` only "
                "when every phrase must occur in the same report. `approvedOnly=true` limits "
                "the cohort to physician-approved reports. This is textual retrieval, not a "
                "new diagnosis: a matched snippet shows exactly why each row was included."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": local_reports.MAX_QUERY_TERMS,
                    },
                    "matchMode": {"type": "string", "enum": ["any", "all"]},
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "modality": {"type": "string"},
                    "service": {"type": "string"},
                    "status": {"type": "string"},
                    "approvedOnly": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="report.history",
            kind="skill",
            handler=_history,
            description=(
                "Every report for one patient, newest first, as full text — for comparing "
                "studies over time or tracking a finding between visits. Identify the patient "
                "by national code."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["nationalCode"],
                "properties": {
                    "nationalCode": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="report.archive-stats",
            kind="skill",
            handler=_stats,
            description=(
                "How many receptions have a report, how many are physician-approved, and the "
                "breakdown by modality. Use to answer 'how much is reported' questions and to "
                "sanity-check coverage before a search."
            ),
            safety="read",
            permission_action="read",
            input_schema={"type": "object", "required": [], "properties": {}},
        )
    )


def _guard(fn, /, **kwargs) -> dict[str, Any]:
    """Turn an unreachable local database into an answer, not a stack trace."""
    try:
        return fn(**kwargs)
    except dm.FilterValueProblem as exc:
        # A filter value this database has no such thing as. Returned as a
        # refusal that NAMES what exists, never as an empty result: the two
        # used to be indistinguishable, and that is how «۰ مورد ماموگرافی» came
        # to be reported to a clinician who had 418 of them.
        return {
            "count": None,
            "error": exc.as_dict(),
            "hint": (
                "The filter value does not exist in this database. Ask "
                "`reception.vocabulary` for what does, and consider whether the "
                "question is about a SERVICE rather than a modality."
            ),
        }
    except ScanBusy as exc:
        # Not a failure: the agent is deliberately allowed only one scan of the
        # reception database at a time, and this request waited its turn and
        # ran out of patience. Saying so plainly is better than either queueing
        # forever or pretending the archive is empty.
        return {
            "available": False,
            "busy": True,
            "reason": str(exc),
            "hint": "The agent runs one database scan at a time so the reception "
                    "software is never competing with two. Ask again in a moment.",
        }
    except LocalMongoUnavailable as exc:
        return {
            "available": False,
            "reason": str(exc),
            "hint": (
                "Report tools read the reception database directly and only work when the "
                "agent is installed on the reception server."
            ),
        }


# Handlers take exactly one argument -- see core/dispatcher.py, which calls
# `definition.handler(call.arguments)`. The dispatch context is not passed in;
# `data_root` is injected into the arguments server-side and these tools ignore
# it because the reception database is not under our data root.
def _get(args: dict[str, Any]) -> dict[str, Any]:
    if not (args.get("receptionId") or args.get("nationalCode")):
        raise ValueError("Provide receptionId or nationalCode.")
    result = _guard(
        local_reports.get_report,
        reception_id=args.get("receptionId"),
        national_code=args.get("nationalCode"),
    )
    return {"skill": "report.get", **result}


def _search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("Provide a search term.")
    result = _guard(
        local_reports.search_reports,
        query=query,
        queries=args.get("queries"),
        match_mode=args.get("matchMode", "any"),
        date_from=args.get("dateFrom"),
        date_to=args.get("dateTo"),
        modality=args.get("modality"),
        service=args.get("service"),
        status=args.get("status"),
        approved_only=bool(args.get("approvedOnly")),
        limit=args.get("limit", local_reports.DEFAULT_LIMIT),
    )
    return {"skill": "report.search", **result}


def _history(args: dict[str, Any]) -> dict[str, Any]:
    national_code = str(args.get("nationalCode") or "").strip()
    if not national_code:
        raise ValueError("Provide the patient's national code.")
    result = _guard(
        local_reports.patient_report_history,
        national_code=national_code,
        limit=args.get("limit", 10),
    )
    return {"skill": "report.history", **result}


def _stats(args: dict[str, Any]) -> dict[str, Any]:
    return {"skill": "report.archive-stats", **_guard(local_reports.archive_stats)}
