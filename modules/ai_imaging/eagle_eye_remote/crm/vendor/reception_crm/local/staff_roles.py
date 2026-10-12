"""Role-specific, read-only report evidence; assignment is not authorship."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable

ROLE_DEFINITIONS = {
    "service_performer": "انجام‌دهندهٔ خدمت، پزشک انجام‌دهنده است؛ نه تایپیست و نه کاربر ثبت‌کنندهٔ تغییر.",
    "typist": "تایپیست تعیین‌شده برای گزارش؛ انتساب، اثبات تایپ کامل متن توسط آن فرد نیست.",
    "changedBy": "حساب ثبت‌کنندهٔ رویداد تغییر یا تأیید؛ از آن نقش پزشک یا تایپیست استنتاج نکن.",
    "radiologist_assigned": "ثبت تغییر انتساب رادیولوژیست؛ ثبت‌کنندهٔ این تغییر لزوماً پزشک منتسب نیست.",
    "physician_approved": "ثبت رویداد تأیید پزشک؛ عنوان رویداد، شغل حساب ثبت‌کننده را اثبات نمی‌کند.",
}


def typist_assignments(
    db: Any,
    bounds: dict[str, Any] | None,
    *,
    max_scan: int,
    limit: int,
    resolve_names: Callable[[list[str]], dict[str, str]],
) -> dict[str, Any]:
    """Latest logged typist target per report in the requested event-date range.

    A separate filtered projection is deliberate: projecting newValue from ALL
    ReportLogs would also read patient report text. Never do that here.
    No current-report join is used: today's typist may differ from that day's.
    """
    query: dict[str, Any] = {
        "action": {"$in": ["typist_assigned", "typist_changed"]}, "field": "typist",
    }
    if bounds:
        query["persianDate"] = bounds
    projection = {
        "_id": 1, "receptionID": 1, "newValue": 1,
        "persianDate": 1, "persianTime": 1, "changedAt": 1,
    }
    latest: dict[str, tuple[tuple[str, ...], str | None]] = {}
    unordered: set[str] = set()
    scanned = missing_id = 0
    capped = False
    for doc in db["ReportLogs"].find(query, projection).limit(max_scan + 1):
        scanned += 1
        if scanned > max_scan:
            capped = True
            scanned = max_scan
            break
        if doc.get("receptionID") is None:
            missing_id += 1
            continue
        report_id = str(doc["receptionID"])
        day, time = str(doc.get("persianDate") or ""), str(doc.get("persianTime") or "")
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", day) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", time
        ):
            unordered.add(report_id)
            continue
        stamp = (day, time, str(doc.get("changedAt") or ""), str(doc.get("_id") or ""))
        raw = doc.get("newValue")
        target = str(raw).strip() if raw is not None else None
        if report_id not in latest or stamp > latest[report_id][0]:
            latest[report_id] = (stamp, target)

    counts: Counter[str] = Counter()
    missing_target = 0
    for report_id, (_, target) in latest.items():
        if report_id in unordered:
            continue
        if not target or not re.fullmatch(r"[0-9a-fA-F]{24}", target):
            missing_target += 1
        else:
            counts[target.lower()] += 1
    names = resolve_names(list(counts))
    rows: list[dict[str, Any]] = [
        {"userId": actor, "name": names.get(actor), "assigned_reports": n}
        for actor, n in counts.items()
    ]
    rows.sort(key=lambda row: (-row["assigned_reports"], row["userId"]))
    return {
        "basis": "latest_logged_typist_assignment_per_report_in_period",
        "assignment_events": scanned,
        "distinct_reports_with_assignment_events": len(set(latest) | unordered),
        "assigned_reports": sum(counts.values()),
        "reports_missing_or_invalid_target": missing_target,
        "reports_with_unorderable_events": len(unordered),
        "events_missing_reception_id": missing_id,
        "reports_with_unresolved_typist_name": sum(n for actor, n in counts.items() if not names.get(actor)),
        "people": len(rows), "rows": rows[:limit], "rows_truncated": len(rows) > limit,
        "capped": capped,
        "meaning_fa": (
            "آخرین انتساب ثبت‌شدهٔ تایپیست برای هر گزارش در بازهٔ تاریخ رویداد، "
            "نه تاریخ پذیرش و نه تعداد تایپ قطعی یا پزشک انجام‌دهندهٔ خدمت. "
            "خالی بودن changedBy به معنی خالی بودن تایپیست هدف نیست. "
            "اگر اسکن ناقص باشد آخرین انتساب فقط در بخش مشاهده‌شده معتبر است."
        ),
    }
