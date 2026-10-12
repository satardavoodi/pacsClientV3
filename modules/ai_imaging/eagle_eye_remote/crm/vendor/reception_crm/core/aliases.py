"""One concept, several spellings: rename a caller's argument onto the declared one.

⚠️ WHY THIS EXISTS, measured rather than imagined. Replaying the 194 tool calls
the v3 benchmark actually made through the validator found **thirteen that were
already silently broken** — accepted, ignored, and answered anyway:

    reporting-queue   {date}                    x3   the tool takes startDate/endDate
    reception.search  {start_date, end_date}    x2   it takes dateFrom/dateTo
    daily-summary     {start_date, end_date}    x2   answered about TODAY instead
    cashier-reconciliation {start_date, end_date} x2 same
    trend-analysis    {compare_to}              x1   it takes compare
    patients.search   {name}                    x1   it takes patientName — the
                                                     search matched nothing and
                                                     the model was not told

Every one is the same failure: the house has more than one spelling for the same
idea, and the model guessed a real one from a sibling tool. Blaming the guess
misses the point. `reception.search` says `dateFrom`, the report tools said
`date`, and `reporting-queue` says `startDate`; a menu that inconsistent will be
guessed at by anything reading it, and the guesses will be reasonable.

So there are two halves to the fix and both are needed. `validation` REFUSES an
undeclared input instead of dropping it, which turns a wrong answer into a
correctable error. This module makes the correction unnecessary where the intent
is unambiguous: rename onto whatever the tool declared, and leave everything else
to the refusal.

⚠️ WHAT THIS DELIBERATELY DOES NOT DO. It never invents a capability. If a tool
does not accept grouping, `groupBy` is still refused — «کدوم صندوق‌دار» was sent
to `cashier-report {groupBy}` and the right answer is that this tool cannot do
that, not a silent report of the ungrouped total.
"""

from __future__ import annotations

from typing import Any

from .errors import ToolValidationError

#: Spellings of the same argument. Within a class every name means one thing, so
#: renaming between them cannot change what was asked for — which is the only
#: reason a rename is safe at all.
EQUIVALENT: tuple[frozenset[str], ...] = (
    frozenset({"dateFrom", "date_from", "startDate", "start_date", "fromDate"}),
    frozenset({"dateTo", "date_to", "endDate", "end_date", "toDate"}),
    frozenset({"patientName", "patient_name", "name", "fullName"}),
    frozenset({"nationalCode", "national_code", "nationalId", "melliCode"}),
    frozenset({"receptionId", "reception_id", "receptionID"}),
    frozenset({"workflowId", "workflow_id"}),
    frozenset({"personnelId", "personnel_id"}),
    frozenset({"templateId", "template_id"}),
    frozenset({"modalityId", "modality_id"}),
    frozenset({"compare", "compare_to", "compareTo", "compareWith"}),
    frozenset({"olderThanDays", "older_than_days"}),
    frozenset({"includeNames", "include_names"}),
    frozenset({"includeDeleted", "include_deleted"}),
    frozenset({"includeNotYetPerformed", "include_not_yet_performed"}),
    frozenset({"graceMinutes", "grace_minutes"}),
    frozenset({"maxContentChars", "max_content_chars"}),
    frozenset({"includeHtml", "include_html"}),
    frozenset({"reportStatus", "report_status"}),
    frozenset({"groupBy", "group_by"}),
    frozenset({"dataRoot", "data_root"}),
)

#: The one-day shorthand. A tool that takes a RANGE and not a day still gets
#: asked «صف گزارش امروز», and expanding one day into both ends of the range is
#: exactly what the asker meant. Widened deliberately and only in this
#: direction: a range is never collapsed into a day, because that would drop
#: part of what was asked for.
DAY_KEY = "date"
RANGE_START = frozenset({"dateFrom", "startDate", "start_date", "date_from"})
RANGE_END = frozenset({"dateTo", "endDate", "end_date", "date_to"})


def normalise_arguments(schema: dict[str, Any] | None, arguments: dict[str, Any]
                        ) -> dict[str, Any]:
    """Rename the caller's spellings onto the ones this tool declares.

    Returns a NEW dict; the caller's is never mutated, because the original
    arguments are what the audit log records and what a confirmation shows a
    human. Renaming in place would make the two disagree.
    """
    declared = set((schema or {}).get("properties") or {})
    if not declared or not arguments:
        return dict(arguments)

    out = dict(arguments)
    for family in EQUIVALENT:
        target = declared & family
        if len(target) != 1:
            # Nothing declared from this family, or several — in the second case
            # the tool has chosen to distinguish them and it is not our place to
            # merge two names it treats as different.
            continue
        wanted = next(iter(target))
        sent = [k for k in list(out) if k in family and k != wanted]
        if not sent:
            continue
        if wanted in out:
            raise ToolValidationError(
                f"{wanted} was given together with {', '.join(sorted(sent))}, which "
                f"mean the same thing. Send one."
            )
        if len(sent) > 1:
            raise ToolValidationError(
                f"{', '.join(sorted(sent))} all mean {wanted}. Send one."
            )
        out[wanted] = out.pop(sent[0])

    # A single day given to a tool that only speaks in ranges.
    if DAY_KEY in out and DAY_KEY not in declared:
        start = declared & RANGE_START
        end = declared & RANGE_END
        if start and end:
            day = out.pop(DAY_KEY)
            out.setdefault(next(iter(start)), day)
            out.setdefault(next(iter(end)), day)

    return out
