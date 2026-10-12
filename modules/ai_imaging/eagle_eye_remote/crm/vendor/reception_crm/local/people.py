"""Referring physicians, staff activity windows, and the name-change trail.

Three questions the v3 benchmark asked twenty-one times between them and the
agent could not answer once. None of them was missing DATA — every field below
was already populated on the reception server. What was missing was a tool, and
the agent said so honestly each time, which is the right behaviour and not a
substitute for the capability.

⚠️ WHAT EACH ONE IS *NOT*, because that is where the value is:

* A referral count is receptions, not people. The same patient referred twice is
  two receptions and one patient, and both numbers are reported.
* A staff activity WINDOW is not a shift. There is no attendance table in this
  database — the `Shift` collection is empty — so the earliest recorded action
  is a LOWER BOUND on arrival and the latest is a lower bound on departure.
  Someone who arrived at 07:30 and first touched the system at 08:08 shows here
  as 08:08. Every payload carries that caveat in Persian, bound to the numbers,
  because a caveat that lives in a docstring is a caveat the model never sees.
* A name change is not necessarily an error. Nine were recorded on the benchmark
  day and seven of those are `admin_override`; one was a spelling fix and one was
  blocked. The trail exists to be read, not to accuse.

PHI: names of PATIENTS are never returned by the two aggregate functions. The
name-change trail is the exception and it is deliberate — the whole point of the
record is which name became which — so it is gated behind an explicit
`include_names` and defaults to off.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .mongo import reception_db, scan_slot
from .staff_roles import ROLE_DEFINITIONS, typist_assignments

RECEPTIONS = "receptions"
TRANSACTIONS = "transactions"
REPORT_LOGS = "ReportLogs"
REFERRERS = "ReferrerPhysician"
ADMIN_USERS = "AdminUsers"
NAME_CHANGES = "PatientNameChangeLogs"

JALALI_DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")

#: Bounded like every other local scan. A month of receptions is ~4,000 rows and
#: a year is ~50,000; the cap is what keeps an unbounded question off someone
#: else's clinical database, and `capped` in the reply is what stops a truncated
#: answer being read as a complete one.
MAX_SCAN = 20000
DEFAULT_LIMIT = 20


def _clamp(value: Any, default: int = DEFAULT_LIMIT, ceiling: int = 200) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(ceiling, n))


def _window(date_from: str | None, date_to: str | None) -> dict[str, Any]:
    """A Jalali range on `Date`. Zero-padded YYYY/MM/DD compares lexically."""
    bounds: dict[str, Any] = {}
    if date_from and JALALI_DATE.match(str(date_from).strip()):
        bounds["$gte"] = str(date_from).strip()
    if date_to and JALALI_DATE.match(str(date_to).strip()):
        bounds["$lte"] = str(date_to).strip()
    return {"Date": bounds} if bounds else {}


def _needs_a_window(date_from: str | None, date_to: str | None) -> dict | None:
    """Refuse an unbounded scan rather than performing one.

    ⚠️ Not a convenience. `receptions` has no index that makes a whole-archive
    grouping cheap, and this runs against the database a clinic is using right
    now. An unbounded question is also almost never the one being asked: «کدوم
    پزشک این ماه بیشترین بیمار رو فرستاده» has a month in it.
    """
    if _window(date_from, date_to):
        return None
    return {
        "error": {
            "code": "PERIOD_REQUIRED",
            "message": "dateFrom and/or dateTo is required; this reads the clinic's "
                       "live database and will not scan the whole archive",
            "message_fa": (
                "برای این گزارش باید بازهٔ تاریخ (dateFrom/dateTo) مشخص شود؛ "
                "بدون بازه، کل آرشیو خوانده می‌شود و این کار روی پایگاه دادهٔ "
                "در حال استفادهٔ مرکز انجام نمی‌شود."
            ),
        }
    }


# --------------------------------------------------------------------------- #
# Referring physicians
# --------------------------------------------------------------------------- #
def referring_physicians(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: Any = DEFAULT_LIMIT,
) -> dict:
    """Who sent the centre its patients in a period, ranked.

    ⚠️ `receptions.referrerPhysician` is an **ObjectId**, and the names live in
    a separate `ReferrerPhysician` collection. Reporting the ids would be
    technically true and useless — the same failure `reception.search` still has
    with staff ids — so this resolves them, and says how many it could not.
    """
    refusal = _needs_a_window(date_from, date_to)
    if refusal:
        return {"skill": "marketing.referrers", **refusal}

    limit = _clamp(limit)
    query: dict[str, Any] = {"deleted": {"$ne": True},
                             "referrerPhysician": {"$ne": None}}
    query.update(_window(date_from, date_to))

    receptions_by_ref: Counter = Counter()
    patients_by_ref: dict[Any, set] = defaultdict(set)
    scanned = 0
    with scan_slot():
        cursor = reception_db()[RECEPTIONS].find(
            query, {"_id": 0, "referrerPhysician": 1, "patient": 1}
        ).limit(MAX_SCAN + 1)
        for doc in cursor:
            scanned += 1
            if scanned > MAX_SCAN:
                break
            ref = doc.get("referrerPhysician")
            if ref is None:
                continue
            receptions_by_ref[ref] += 1
            if doc.get("patient") is not None:
                patients_by_ref[ref].add(str(doc["patient"]))

    capped = scanned > MAX_SCAN
    top = receptions_by_ref.most_common(limit)
    names = _referrer_names([ref for ref, _ in top])

    rows = [
        {
            "referrerId": str(ref),
            "name": names.get(str(ref)),
            "receptions": count,
            "patients": len(patients_by_ref.get(ref, ())),
        }
        for ref, count in top
    ]
    unnamed = sum(1 for r in rows if not r["name"])

    return {
        "skill": "marketing.referrers",
        "period": {"from": date_from, "to": date_to},
        "referrers_total": len(receptions_by_ref),
        "receptions_with_a_referrer": sum(receptions_by_ref.values()),
        "scanned": min(scanned, MAX_SCAN),
        "capped": capped,
        "rows": rows,
        "unresolved_names": unnamed,
        "meaning_fa": (
            "شمارش بر مبنای «پذیرش» است، نه «بیمار یکتا»؛ هر دو عدد آورده شده. "
            "این فهرست فقط پذیرش‌هایی را می‌شمارد که پزشک ارجاع‌دهنده روی آن‌ها "
            "ثبت شده است."
        ),
        "_caveat": (
            "TRUNCATED: only the first %d receptions of the period were counted, "
            "so the ranking is not final." % MAX_SCAN if capped else None
        ),
    }


def _referrer_names(ids: list[Any]) -> dict[str, str]:
    """Resolve referrer ObjectIds to names, in one query, never one per row."""
    if not ids:
        return {}
    docs = reception_db()[REFERRERS].find(
        {"_id": {"$in": list(ids)}}, {"_id": 1, "FullName": 1, "Expertise": 1}
    )
    out: dict[str, str] = {}
    for doc in docs:
        name = str(doc.get("FullName") or "").strip()
        expertise = str(doc.get("Expertise") or "").strip()
        if name:
            out[str(doc["_id"])] = f"{name} ({expertise})" if expertise else name
    return out


# --------------------------------------------------------------------------- #
# Staff activity windows
# --------------------------------------------------------------------------- #
#: What each collection can say about a person, and under which field. Written
#: as data because the three answers are genuinely different questions and an
#: answer that merges them without saying so is the «کدوم کارمند بیشترین حجم کار
#: رو داشته» failure: 53 receptions registered and 105 transactions processed are
#: not comparable quantities.
_ACTIVITY_SOURCES = (
    ("registrations", RECEPTIONS, "registeredBy", "Date", "Time"),
    ("transactions", TRANSACTIONS, "registeredBy", "date", "time"),
)

_REPORT_APPROVAL_ACTIONS = frozenset({"secretary_approved", "physician_approved"})
_REPORT_EDIT_ACTIONS = frozenset({"content_updated", "findings_updated"})


def _record_activity_event(
    activity: dict[str, Any], kind: str, stamp: str | None
) -> dict[str, Any]:
    """Record an event without making a missing timestamp erase the event.

    Counts and activity windows have different completeness requirements.  A
    log row with no time is still an event, but it cannot safely move the first
    or last recorded-action boundary.
    """
    entry = activity.setdefault(kind, {"count": 0, "first": None, "last": None})
    entry["count"] += 1
    if stamp:
        entry["first"] = min(entry["first"], stamp) if entry["first"] else stamp
        entry["last"] = max(entry["last"], stamp) if entry["last"] else stamp
    return entry


def _report_activity_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Turn internal report-id sets into the explicit public metric contract."""
    reports_by_action = stats["reports_by_action"]
    approval_reports = set().union(
        *(reports_by_action.get(action, set()) for action in _REPORT_APPROVAL_ACTIONS)
    )
    edited_reports = set().union(
        *(reports_by_action.get(action, set()) for action in _REPORT_EDIT_ACTIONS)
    )
    event_counts: Counter = stats["event_counts"]
    return {
        "events": sum(event_counts.values()),
        "distinct_reports": len(stats["distinct_reports"]),
        "event_counts_by_action": dict(sorted(event_counts.items())),
        "distinct_reports_by_action": {
            action: len(report_ids)
            for action, report_ids in sorted(reports_by_action.items())
        },
        "approval_reports": len(approval_reports),
        "secretary_approved_reports": len(
            reports_by_action.get("secretary_approved", set())
        ),
        "physician_approved_reports": len(
            reports_by_action.get("physician_approved", set())
        ),
        "content_edited_reports": len(edited_reports),
        "radiologist_assigned_reports": len(
            reports_by_action.get("radiologist_assigned", set())
        ),
        "status_changed_reports": len(
            reports_by_action.get("status_changed", set())
        ),
        "metric_note": (
            "events/count are ReportLogs rows, not reports. Use distinct_reports "
            "or an action-specific *_reports field when answering how many reports."
        ),
    }


def staff_activity(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: Any = 50,
) -> dict:
    """First and last recorded ACTION per person, per kind of activity.

    ⚠️ THIS IS NOT AN ATTENDANCE REPORT AND MUST NOT BE PRESENTED AS ONE. The
    `Shift` collection is empty; nothing in this database records when anyone
    arrived. What it records is when they first touched the system, which is a
    lower bound and can be an hour or more after they walked in. The benchmark
    asked for working hours twice and the agent declined both times — the right
    call, and the reason this function carries its caveat in the payload rather
    than leaving the model to remember it.
    """
    refusal = _needs_a_window(date_from, date_to)
    if refusal:
        return {"skill": "staff.activity", **refusal}

    limit = _clamp(limit, default=50)
    db = reception_db()
    people: dict[str, dict[str, Any]] = {}
    report_stats: dict[str, dict[str, Any]] = {}
    scanned_total = 0
    capped = False

    with scan_slot():
        for kind, collection, actor_field, date_field, time_field in _ACTIVITY_SOURCES:
            bounds = _window(date_from, date_to).get("Date")
            query: dict[str, Any] = {actor_field: {"$ne": None}}
            if bounds:
                query[date_field] = bounds
            projection = {"_id": 0, actor_field: 1, date_field: 1, time_field: 1}
            scanned = 0
            for doc in db[collection].find(query, projection).limit(MAX_SCAN + 1):
                scanned += 1
                if scanned > MAX_SCAN:
                    capped = True
                    break
                actor = str(doc.get(actor_field) or "")
                stamp = f"{doc.get(date_field) or ''} {doc.get(time_field) or ''}".strip()
                if not actor:
                    continue
                slot = people.setdefault(actor, {})
                _record_activity_event(slot, kind, stamp or None)
            scanned_total += min(scanned, MAX_SCAN)

        # ReportLogs is a different grain from the two sources above.  One
        # report can create several approval, status, and content-edit rows.
        # Scan actor-less rows too so the payload can disclose attribution
        # coverage instead of presenting the named subset as the whole staff.
        bounds = _window(date_from, date_to).get("Date")
        report_query: dict[str, Any] = {}
        if bounds:
            report_query["persianDate"] = bounds
        projection = {
            "_id": 0,
            "changedBy": 1,
            "persianDate": 1,
            "persianTime": 1,
            "receptionID": 1,
            "action": 1,
        }
        report_quality: dict[str, Any] = {
            "log_events": 0,
            "attributed_events": 0,
            "unattributed_events": 0,
            "events_missing_reception_id": 0,
            "attribution_coverage_percent": None,
            "distinct_reports_with_log_activity": 0,
            "distinct_reports_with_attributed_activity": 0,
            "distinct_reports_without_attributed_activity": 0,
            "report_attribution_coverage_percent": None,
            "capped": False,
        }
        all_report_ids: set[str] = set()
        attributed_report_ids: set[str] = set()
        edited_report_ids: set[str] = set()
        attributed_edit_ids: set[str] = set()
        unattributed_edit_ids: set[str] = set()
        edit_events: Counter[str] = Counter()
        scanned = 0
        cursor = db[REPORT_LOGS].find(report_query, projection).limit(MAX_SCAN + 1)
        for doc in cursor:
            scanned += 1
            if scanned > MAX_SCAN:
                capped = True
                report_quality["capped"] = True
                break
            report_quality["log_events"] += 1
            report_id = doc.get("receptionID")
            report_key = str(report_id) if report_id is not None else None
            if report_key is None:
                report_quality["events_missing_reception_id"] += 1
            else:
                all_report_ids.add(report_key)
            actor = str(doc.get("changedBy") or "").strip()
            action = str(doc.get("action") or "unspecified").strip() or "unspecified"
            if action in _REPORT_EDIT_ACTIONS:
                edit_events["attributed" if actor else "unattributed"] += 1
                if report_key is not None:
                    edited_report_ids.add(report_key)
                    (attributed_edit_ids if actor else unattributed_edit_ids).add(report_key)
            if not actor:
                report_quality["unattributed_events"] += 1
                continue

            report_quality["attributed_events"] += 1
            report_stamp = (
                f"{doc.get('persianDate') or ''} {doc.get('persianTime') or ''}".strip()
                or None
            )
            slot = people.setdefault(actor, {})
            _record_activity_event(slot, "report_actions", report_stamp)

            stats = report_stats.setdefault(
                actor,
                {
                    "event_counts": Counter(),
                    "distinct_reports": set(),
                    "reports_by_action": defaultdict(set),
                },
            )
            stats["event_counts"][action] += 1
            if report_key is not None:
                stats["distinct_reports"].add(report_key)
                stats["reports_by_action"][action].add(report_key)
                attributed_report_ids.add(report_key)

        scanned_total += min(scanned, MAX_SCAN)
        for actor, stats in report_stats.items():
            # Keep the old count for compatibility, but bind its true grain to
            # the same object so an answer writer cannot mistake it for reports.
            people[actor]["report_actions"].update(_report_activity_payload(stats))
        attributed = report_quality["attributed_events"]
        total_report_events = report_quality["log_events"]
        report_quality["attribution_coverage_percent"] = (
            round(attributed * 100 / total_report_events, 1)
            if total_report_events
            else None
        )
        report_quality["distinct_reports_with_attributed_activity"] = len(
            attributed_report_ids
        )
        report_quality["distinct_reports_with_log_activity"] = len(all_report_ids)
        report_quality["distinct_reports_without_attributed_activity"] = len(
            all_report_ids - attributed_report_ids
        )
        report_quality["report_attribution_coverage_percent"] = (
            round(len(attributed_report_ids) * 100 / len(all_report_ids), 1)
            if all_report_ids
            else None
        )
        assignments = typist_assignments(
            db, bounds, max_scan=MAX_SCAN, limit=limit, resolve_names=_staff_names,
        )
        scanned_total += assignments["assignment_events"]
        capped = capped or assignments["capped"]

    names = _staff_names(list(people))
    rows = sorted(
        (
            {
                "userId": actor,
                "name": names.get(actor),
                "activity": activity,
                # Compatibility alias only.  These event counts have different
                # grains and must never be presented as a workload score.
                "total_actions": sum(v["count"] for v in activity.values()),
                "total_recorded_events": sum(v["count"] for v in activity.values()),
            }
            for actor, activity in people.items()
        ),
        key=lambda row: -row["total_actions"],
    )[:limit]

    return {
        "skill": "staff.activity",
        "period": {"from": date_from, "to": date_to},
        "people": len(people),
        "scanned": scanned_total,
        "capped": capped,
        "report_activity_quality": report_quality,
        "role_definitions": dict(ROLE_DEFINITIONS),
        "typist_assignments": assignments,
        "report_content_activity": {
            "edit_events": sum(edit_events.values()),
            "attributed_edit_events": edit_events["attributed"],
            "unattributed_edit_events": edit_events["unattributed"],
            "distinct_edited_reports": len(edited_report_ids),
            "reports_with_attributed_edits": len(attributed_edit_ids),
            "reports_with_unattributed_edits": len(unattributed_edit_ids),
            "reports_with_only_unattributed_edits": len(edited_report_ids - attributed_edit_ids),
            "capped": report_quality["capped"],
            "meaning_fa": (
                "ویرایش محتوا/یافته‌ها، تایپ کامل گزارش نیست. صفر ویرایش منتسب "
                "برای یک فرد، اثبات تایپ نکردن او نیست. دو گروه ویرایش منتسب و "
                "بی‌نام ممکن است هم‌پوشانی داشته باشند؛ تعدادشان را جمع نزن."
            ),
        },
        "rows": rows,
        "⚠️_not_attendance": (
            "first/last are the earliest and latest RECORDED ACTIONS, not clock-in "
            "and clock-out. There is no attendance table in this system."
        ),
        "⚠️_do_not_sum_or_rank_mixed_activity": (
            "total_actions/total_recorded_events are compatibility event totals across "
            "different grains. Do not use them to rank workload or compare roles."
        ),
        "meaning_fa": (
            "این ارقام «اولین و آخرین فعالیت ثبت‌شده» است، نه ساعت ورود و خروج. "
            "در این سامانه جدول حضور و غیاب وجود ندارد، بنابراین اولین فعالیت "
            "حداکثر می‌تواند «حداقلِ زمان حضور» باشد و نه بیشتر. هر پاسخی که این "
            "را «ساعت کاری» بنامد، چیزی را ادعا کرده که داده پشتیبانش نیست.\n"
            "سه نوع فعالیت جداگانه شمرده شده‌اند — ثبت پذیرش، تراکنش صندوق و "
            "اقدام روی گزارش — چون با هم قابل جمع زدن نیستند. در بخش گزارش، "
            "count و events تعداد ردیف‌های لاگ‌اند، نه تعداد گزارش. برای پاسخ "
            "به «چند گزارش» باید distinct_reports یا شمارش یکتای همان اقدام مثل "
            "secretary_approved_reports و physician_approved_reports استفاده شود. "
            "ویرایش محتوا و تخصیص رادیولوژیست نیز از تأیید گزارش جدا هستند. درصد "
            "پوشش changedBy هم در سطح رویداد و هم گزارش یکتا نشان می‌دهد چه سهمی "
            "اصلاً به کاربر مشخص منتسب است؛ فهرست افراد فقط درباره همان بخش "
            "منتسب ادعا دارد."
        ),
    }


def _staff_names(ids: list[str]) -> dict[str, str]:
    """Resolve staff ObjectIds to names, in one query.

    ⚠️ `AdminUsers._id` is an ObjectId and the callers hold strings, so the
    lookup converts. A version that compared strings to ObjectIds matched
    nothing and reported every person as unnamed, which looks exactly like a
    database that does not store names.
    """
    if not ids:
        return {}
    try:
        from bson import ObjectId
    except ImportError:  # pragma: no cover - bson ships with pymongo
        return {}
    oids = []
    for value in ids:
        try:
            oids.append(ObjectId(value))
        except Exception:  # noqa: BLE001 - a non-ObjectId actor is simply unnamed
            continue
    if not oids:
        return {}
    docs = reception_db()[ADMIN_USERS].find(
        {"_id": {"$in": oids}}, {"_id": 1, "FullName": 1, "User": 1}
    )
    return {
        str(doc["_id"]): str(doc.get("FullName") or doc.get("User") or "").strip()
        for doc in docs
        if (doc.get("FullName") or doc.get("User"))
    }


# --------------------------------------------------------------------------- #
# The name-change trail
# --------------------------------------------------------------------------- #
def name_changes(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    include_names: bool = False,
    limit: Any = DEFAULT_LIMIT,
) -> dict:
    """Who changed a patient's name, when, why, and on which receptions.

    ⚠️ THE SCENARIO REGISTRY ONCE SAID THIS TRAIL DID NOT EXIST. It does — 67
    records, with the old name, the new name, who changed it, the reason, the IP
    address and the affected receptions — and a rule telling the model that the
    centre does not record something it does record is worse than no rule: it
    turns a missing tool into a false statement about the clinic.

    `include_names` is off by default. The counts, the reasons and the actors
    answer «آیا تغییری ثبت شده؟» without naming a patient; the names themselves
    are returned only when the caller asks for them.
    """
    limit = _clamp(limit)
    query: dict[str, Any] = {}
    bounds: dict[str, Any] = {}
    if date_from and JALALI_DATE.match(str(date_from).strip()):
        bounds["$gte"] = str(date_from).strip()
    if date_to and JALALI_DATE.match(str(date_to).strip()):
        bounds["$lte"] = str(date_to).strip()
    if bounds:
        query["persianDate"] = bounds

    col = reception_db()[NAME_CHANGES]
    total = col.count_documents(query)
    docs = list(col.find(query).sort("persianDate", -1).limit(limit))

    by_reason: Counter = Counter()
    blocked = 0
    rows = []
    for doc in docs:
        reason = str(doc.get("reason") or "unspecified")
        by_reason[reason] += 1
        blocked += bool(doc.get("blocked"))
        row: dict[str, Any] = {
            "date": doc.get("persianDate"),
            "time": doc.get("persianTime"),
            "changedBy": str(doc.get("changedBy") or ""),
            "changedByName": doc.get("changedByName"),
            "reason": reason,
            "reasonNote": doc.get("reasonNote") or None,
            "blocked": bool(doc.get("blocked")),
            "source": doc.get("source"),
            "affectedReceptions": [
                r.get("receptionId") or r.get("receptionNumber")
                for r in (doc.get("relatedReceptions") or [])
                if isinstance(r, dict)
            ],
        }
        if include_names:
            row["oldName"] = doc.get("oldName")
            row["newName"] = doc.get("newName")
        else:
            # Lengths, so a change is visibly a change without naming anyone.
            row["oldName"] = f"<withheld:{len(str(doc.get('oldName') or ''))}>"
            row["newName"] = f"<withheld:{len(str(doc.get('newName') or ''))}>"
        rows.append(row)

    return {
        "skill": "audit.name-changes",
        "period": {"from": date_from, "to": date_to},
        "count": total,
        "shown": len(rows),
        "blocked": blocked,
        "by_reason": dict(by_reason),
        "names_included": bool(include_names),
        "rows": rows,
        "meaning_fa": (
            "این سیاههٔ تغییر نام بیمار است: نام قبلی، نام جدید، کاربر تغییردهنده، "
            "علت، و پذیرش‌های متأثر. وجود یک رکورد به‌تنهایی «خطا» یا «تخلف» نیست — "
            "بیشتر موارد اصلاح املا یا تغییر با مجوز مدیر است. رکورد «blocked» یعنی "
            "تغییر انجام نشده است.\n"
            "نام‌ها به‌صورت پیش‌فرض بازگردانده نمی‌شوند."
        ),
    }
