"""Cross-checks between reception records, reports and files on disk.

None of these are answerable through the vendor's HTTP API: each needs either a
join the API does not expose or a look at the filesystem. They became possible
only because the agent runs on the reception server.

Every check is bounded and reports how far it actually looked. A quality check
that silently examines the first N records and presents the result as complete
is worse than no check at all -- so `scanned` and `capped` are part of every
answer, and the tools say so in the summary.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .mongo import reception_db, scan_slot
from .reports import HAS_REPORT, MODALITY_NAMES, _modality_code

RECEPTIONS = "receptions"
REPORT_LOGS = "ReportLogs"
DOC_ATTACHMENTS = "document_attachments"
RECEPTION_ATTACHMENTS = "ReceptionAttachments"

MAX_SCAN = 4000
DEFAULT_LIMIT = 25

# Files the reception system writes. A path that is not under one of these is
# not ours to open, whatever the database says -- the database is data, and a
# path out of it is no more trustworthy than any other stored string.
#
# The list is a per-SITE fact, published by server/config.py into the
# environment, because the vendor's layout is not identical everywhere and this
# installer is meant to run on more than one reception server. The default is
# the layout Razi uses; a site with different folders sets `reception.file_roots`
# in server.json.
DEFAULT_FILE_ROOTS = (
    r"D:\api\images\ReceptionAttachments",
    r"D:\Program Files\data\captures",
    r"D:\Program Files\AI_PACS_SERVER\data\dicom_data",
)
ENV_FILE_ROOTS = "RECEPTION_FILE_ROOTS"


def file_roots() -> tuple[str, ...]:
    """The site's storage roots, resolved per call.

    Per call rather than at import: the environment is published by
    `apply_to_environment()` during service start, which happens after this
    module is imported. A module-level constant captured the value before it
    existed and every site would have silently used the default.
    """
    raw = os.getenv(ENV_FILE_ROOTS) or ""
    roots = tuple(p.strip() for p in raw.split(os.pathsep) if p.strip())
    return roots or FILE_ROOTS


# The in-process default, and the seam the tests point at a temp directory.
FILE_ROOTS = DEFAULT_FILE_ROOTS

JALALI = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def _clamp(value: Any, default: int = DEFAULT_LIMIT, ceiling: int = 200) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(ceiling, n))


def _under_known_root(path: str) -> bool:
    try:
        resolved = os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return False
    return any(resolved.startswith(os.path.normcase(os.path.abspath(r))) for r in file_roots())


# A reception document averages 28 KB. `_row` needs seven small fields out of
# it, so the projection is the difference between moving ~700 KB and ~5 KB for a
# 25-row answer -- and, more to the point, between asking mongod to hand back
# whole clinical records and asking it for the columns we display.
_ROW_FIELDS = {
    "_id": 0,
    "ReceptionID": 1,
    "Date": 1,
    "modality": 1,
    "patientNameSnapshot": 1,
    "nationalCode": 1,
    "imagingWorkflow.report.status": 1,
    "imagingWorkflow.report.approvalFlags.physicianApprovedAt": 1,
    "imagingWorkflow.workflowStatus": 1,
}


def _row(doc: dict) -> dict:
    workflow = doc.get("imagingWorkflow") or {}
    report = workflow.get("report") or {}
    code = _modality_code(doc.get("modality"))
    return {
        "receptionId": doc.get("ReceptionID"),
        "date": doc.get("Date"),
        "modality": MODALITY_NAMES.get(code or "", code),
        "patientName": doc.get("patientNameSnapshot"),
        "nationalCode": doc.get("nationalCode"),
        "reportStatus": report.get("status"),
        "workflowStatus": workflow.get("workflowStatus"),
    }


# --------------------------------------------------------------------------- #
# A reception sitting in `waiting_appointment` is a BOOKING, not a performed
# study: the patient has not attended, so there is nothing to report and its
# absence is not a backlog item. Including this state made the first run of this
# check return 26,590 "unreported studies" -- a number that looked alarming and
# meant nothing, because most of it was future appointments.
NOT_YET_PERFORMED = "waiting_appointment"


def missing_reports(
    *,
    older_than_days: Any = 7,
    date_from: str | None = None,
    date_to: str | None = None,
    modality: str | None = None,
    include_not_yet_performed: bool = False,
    limit: Any = DEFAULT_LIMIT,
) -> dict:
    """Studies that were performed long enough ago to have been reported.

    Two things make this number honest rather than merely large:

    * bookings that never became studies are excluded (see NOT_YET_PERFORMED);
    * "long enough ago" is a parameter, because the right interval is the
      centre's clinical decision and not something to hard-code.
    """
    from .reports import date_range_filter, modality_filter

    col = reception_db()[RECEPTIONS]
    limit = _clamp(limit)
    days = _clamp(older_than_days, default=7, ceiling=3650)

    conditions: list[dict[str, Any]] = [
        {"$or": [{"imagingWorkflow.report.content": {"$in": [None, ""]}},
                 {"imagingWorkflow.report.content": {"$exists": False}}]},
        # A cancelled or returned reception is not a missing report.
        {"deleted": {"$ne": True}},
        {"returned": {"$ne": True}},
    ]
    if not include_not_yet_performed:
        conditions.append({"imagingWorkflow.workflowStatus": {"$ne": NOT_YET_PERFORMED}})

    window = date_range_filter(date_from, date_to)
    if window:
        conditions.append(window)
    else:
        # No explicit window: everything older than the cut-off. createdAt is a
        # real datetime, unlike Date which is a Jalali string -- so the age test
        # uses createdAt and the display uses Date.
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conditions.append({"createdAt": {"$lt": cutoff}})

    mod = modality_filter(modality)
    if mod:
        conditions.append(mod)

    query = {"$and": conditions}
    # Measured: this examines ~20k documents to return 25, because the `$ne`
    # conditions are not index-friendly. It is bounded and it is not on the
    # interactive path, but it is real work on someone else's database, so it
    # queues behind any other scan rather than running alongside one.
    with scan_slot():
        total = col.count_documents(query)
        rows = [
            _row(doc)
            for doc in col.find(query, _ROW_FIELDS).sort([("Date", -1)]).limit(limit)
        ]
    return {
        "check": "missing-reports",
        "criteria": {
            "olderThanDays": None if window else days,
            "dateFrom": date_from,
            "dateTo": date_to,
            "modality": modality,
            "excludedNotYetPerformed": not include_not_yet_performed,
        },
        "count": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "rows": rows,
        "note": (
            "Performed studies with no report body. Cancelled and returned receptions are "
            "excluded, and so are bookings still waiting for an appointment — those are not "
            "a reporting backlog."
        ),
    }


# --------------------------------------------------------------------------- #
# A row marked `deleted` is one whose file the reception system removed on
# purpose. Its path is *supposed* to lead nowhere, so counting it as a broken
# link inverts the meaning of the check: the first live run reported 24 "broken
# links" and every one of them was deliberate cleanup. Same class of error as
# NOT_YET_PERFORMED above -- a true statement about the data that answers a
# different question from the one asked.
DELETED_SYNC_STATUS = "deleted"


def broken_file_links(
    *,
    limit: Any = DEFAULT_LIMIT,
    scan: Any = 1500,
    include_deleted: bool = False,
) -> dict:
    """Database rows whose file is no longer on disk.

    Checked in both directions is tempting, but only this direction is
    trustworthy: a file with no row may be a legitimate orphan from an import,
    whereas a row pointing at a vanished file is a defect -- unless the row was
    deliberately marked deleted, which is why those are set aside and counted
    rather than reported as damage.
    """
    db = reception_db()
    limit = _clamp(limit)
    budget = _clamp(scan, default=1500, ceiling=MAX_SCAN)

    broken: list[dict[str, Any]] = []
    broken_total = 0
    outside_roots = 0
    deleted_skipped = 0
    checked = 0

    docs = db[DOC_ATTACHMENTS]
    has_path = {"dicomFilePath": {"$type": "string", "$ne": ""}}
    if include_deleted:
        candidates = has_path
    else:
        candidates = {**has_path, "syncStatus": {"$ne": DELETED_SYNC_STATUS}}
        deleted_skipped = docs.count_documents(
            {**has_path, "syncStatus": DELETED_SYNC_STATUS}
        )

    # `document_attachments` is 3,251 rows of ~700 bytes -- 2.2 MB, measured at
    # 7 ms for a full pass. No scan slot for this one: taking a lock to protect
    # the database from a 2 MB read would only add contention.
    cursor = docs.find(
        candidates,
        {"_id": 0, "receptionID": 1, "dicomFilePath": 1, "originalFileName": 1,
         "syncStatus": 1, "syncedAt": 1, "StudyInstanceUID": 1},
    ).sort([("syncedAt", -1)])

    for doc in cursor.limit(budget):
        checked += 1
        path = doc.get("dicomFilePath") or ""
        if not _under_known_root(path):
            outside_roots += 1
            continue
        if os.path.exists(path):
            continue
        broken_total += 1
        if len(broken) < limit:
            broken.append(
                {
                    "collection": DOC_ATTACHMENTS,
                    "receptionId": doc.get("receptionID"),
                    "fileName": doc.get("originalFileName"),
                    "studyUid": doc.get("StudyInstanceUID"),
                    "syncStatus": doc.get("syncStatus"),
                    "path": path,
                }
            )

    total_rows = docs.count_documents(candidates)
    return {
        "check": "broken-file-links",
        "collection": DOC_ATTACHMENTS,
        "rowsWithPath": total_rows,
        "checked": checked,
        "capped": total_rows > checked,
        "brokenFound": broken_total,
        "returned": len(broken),
        "truncated": broken_total > len(broken),
        "pathsOutsideKnownRoots": outside_roots,
        # Named in the answer because a wrong list is otherwise invisible: at a
        # site whose images live somewhere else, every path falls outside, the
        # check examines nothing, and "0 broken links" looks like good news.
        "knownRoots": list(file_roots()),
        "deletedRowsExcluded": deleted_skipped,
        "includedDeleted": include_deleted,
        "rows": broken,
        "note": (
            "Rows whose recorded file is missing from disk. Only paths under this "
            "site's configured storage roots are opened, and rows the reception "
            "system marked deleted are excluded — their file is meant to be gone. "
            "`checked` says how many of `rowsWithPath` were actually examined; if "
            "`pathsOutsideKnownRoots` is high, `knownRoots` is probably wrong for "
            "this site."
        ),
    }


# --------------------------------------------------------------------------- #
def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def post_approval_edits(
    *,
    limit: Any = DEFAULT_LIMIT,
    scan: Any = 400,
    grace_minutes: Any = 0,
) -> dict:
    """Reports whose text was changed after a physician approved them.

    This is the check with real clinical weight: an approved report is a signed
    document, and an edit afterwards means the approved version and the current
    version are not the same text. `ReportLogs` keeps every change with a
    timestamp, so the question is answerable exactly -- it just needs a join the
    API does not offer.

    `grace_minutes` exists because "after approval" and "a change to the signed
    document" are not the same thing. A save that lands seconds after the
    approval click is part of the same act; one that lands the next morning is
    not. Every row therefore carries `minutesAfterApproval` for the first such
    edit, so the reader can see which kind they are looking at instead of being
    handed a count and asked to trust it. The default is 0 -- no grace, nothing
    hidden -- and widening it is the reader's explicit choice.
    """
    db = reception_db()
    receptions = db[RECEPTIONS]
    logs = db[REPORT_LOGS]
    limit = _clamp(limit)
    budget = _clamp(scan, default=400, ceiling=2000)
    try:
        grace = max(0, int(grace_minutes))
    except (TypeError, ValueError):
        grace = 0

    query = {
        **HAS_REPORT,
        "imagingWorkflow.report.approvalFlags.physicianApproved": True,
        "imagingWorkflow.report.approvalFlags.physicianApprovedAt": {"$type": "string"},
    }
    findings: list[dict[str, Any]] = []
    found_total = 0
    checked = 0

    # The outer query is index-served (4 ms for 300 rows, measured) and each
    # inner ReportLogs lookup uses `receptionID_1_changedAt_-1` (1 ms). What
    # makes this worth the slot is the SHAPE: one query per scanned row, so a
    # 300-row check is ~600 round trips. Serialising it keeps that burst from
    # overlapping another one.
    with scan_slot():
        approved_total = receptions.count_documents(query)
        cursor = receptions.find(query, _ROW_FIELDS).sort([("ReceptionID", -1)])

        for doc in cursor.limit(budget):
            checked += 1
            flags = ((doc.get("imagingWorkflow") or {}).get("report") or {}).get("approvalFlags") or {}
            approved_at = _parse_iso(flags.get("physicianApprovedAt"))
            if not approved_at:
                continue
            threshold = approved_at + timedelta(minutes=grace)
            log_query = {
                "receptionID": doc.get("ReceptionID"),
                "changedAt": {"$gt": threshold},
                "field": {"$in": ["content", "findings"]},
            }
            # Earliest first: its distance from the approval is what tells a
            # same-session save apart from a later revision.
            first = next(
                iter(logs.find(log_query, {"_id": 0, "changedAt": 1}).sort([("changedAt", 1)]).limit(1)),
                None,
            )
            if first is None:
                continue
            later = logs.count_documents(log_query)
            found_total += 1
            if len(findings) < limit:
                changed_at = _parse_iso(first.get("changedAt"))
                row = _row(doc)
                row["approvedAt"] = flags.get("physicianApprovedAt")
                row["editsAfterApproval"] = later
                row["firstEditAt"] = first.get("changedAt")
                row["minutesAfterApproval"] = (
                    round((changed_at - approved_at).total_seconds() / 60, 1)
                    if changed_at
                    else None
                )
                findings.append(row)

    return {
        "check": "post-approval-edits",
        "approvedReportsTotal": approved_total,
        "checked": checked,
        "capped": approved_total > checked,
        "graceMinutes": grace,
        "found": found_total,
        "returned": len(findings),
        "truncated": found_total > len(findings),
        "rows": findings,
        "note": (
            "The report text changed after a physician approved it, so the approved "
            "version and the current version differ. Counted from the edit log. "
            "`found` is out of `checked`, not out of `approvedReportsTotal`. "
            "`minutesAfterApproval` is the gap to the first such edit: a gap of "
            "seconds is usually the same editing session finishing, while hours or "
            "days is a real revision of a signed document."
        ),
    }
