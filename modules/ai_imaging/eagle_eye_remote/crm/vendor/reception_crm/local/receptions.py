"""Count and list receptions by the field the question is actually about.

The gap this fills: before it, nothing could answer *"how many brain MRI
services today"*. `report.search` searches report **text**; the summary tools
come from the vendor's HTTP API and are fixed shapes. Neither can filter on
`services[].Service`, which is where what-was-performed is recorded — so the
one question the archive answers best had no path to it.

What this returns is a **count with its definition attached**: the filters that
were applied, the services a service filter matched, and a breakdown by whatever
dimension was asked for. A bare number whose definition is invisible is a number
nobody can check, and the answer that started this work was exactly that.

Read-only, bounded, and a good neighbour on the vendor's database:
  * every query carries the server-side deadline from `local/mongo.py`;
  * a service filter has no index behind it, so a date range is REQUIRED;
  * the scan slot is taken for anything that is not index-served.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from . import datamodel as dm
from .mongo import reception_db, scan_slot

LOG = logging.getLogger("reception_crm.local.receptions")

RECEPTIONS = "receptions"

#: How many rows are RENDERED. This is a display budget, nothing more.
#:
#: It used to be 25, and the answer said so — «فهرست جزئیات به ۲۵ ردیف محدود
#: شده است» — and then refused to state a patient count, because the only
#: patient evidence in the payload was the truncated list. That is the bug: a
#: display budget was being read as a limit on what could be KNOWN.
#:
#: Counts are now computed over the whole match in `_totals`, so the row budget
#: has no bearing on any number in the answer. A caller who wants the actual
#: rows can ask for up to MAX_LIMIT of them.
DEFAULT_LIMIT = 100
MAX_LIMIT = 5000

#: A service filter reads `services[].Service`, which no index covers. Without a
#: date bound it is a collection scan of 54,000 receptions on a clinical server
#: during a working day. Refusing is friendlier than being slow: the caller
#: knows what period they meant.
UNINDEXED_NEEDS_DATES = ("service",)

#: What a row shows. Deliberately narrow — a reception document averages 28 KB
#: and the caller asked for a count, not a copy of the archive.
ROW_FIELDS = {
    "_id": 0,
    "ReceptionID": 1,
    # The patient's ObjectId, not their name: enough to tell two rows apart and
    # to see that one person had three studies, without carrying an identity.
    "patient": 1,
    "Date": 1,
    "Time": 1,
    "modality": 1,
    "insuranceType": 1,
    "services.Service": 1,
    "services.Modality": 1,
    "totalAmount": 1,
    "patientTotal": 1,
    "settled": 1,
    "imagingWorkflow.report.status": 1,
    # The discount money. Added because `discountedOnly` used to find exactly
    # the right three receptions and then report no amount at all: the answer
    # went from «۳ مورد به مبلغ ۱۳٬۵۸۰٬۰۰۰» (read off the cashier report) to
    # «۳ پذیرش دارای تخفیف بودند» once this filter existed and displaced that
    # source. A filter that is more correct about WHICH and silent about HOW
    # MUCH is a regression, however good its WHERE clause is.
    #
    # Which of the four fields carried it matters: `discountTotal` is 0 on every
    # reception measured here and `cashDeskDiscount` is not, and the vendor's own
    # report contradicts itself about this. Kept per-field, then summed.
    **{field: 1 for field in dm.DISCOUNT_FIELDS},
}

#: The discount on one reception, as a Mongo expression.
#:
#: `$ifNull` on every term on purpose: most receptions carry none of these
#: fields at all, and `$add` over a missing field yields null, not the other
#: three. One absent field would have zeroed the whole sum silently.
_DISCOUNT_SUM = {"$add": [{"$ifNull": ["$" + field, 0]} for field in dm.DISCOUNT_FIELDS]}

GROUP_BY = {
    "modality": {"$cond": [{"$eq": [{"$type": "$modality"}, "object"]},
                           "$modality._id", "$modality"]},
    "service": "$services.Service",
    # «پیک پذیرش دیروز چه ساعتی بوده؟» had no path to an answer: nothing here
    # grouped by time, so the agent reached for patient-list, found no hourly
    # aggregate, and reported that the peak hour could not be determined — on a
    # day whose peak is plainly 11:00 with 29 receptions. `Time` is "HH:MM:SS",
    # so the hour is the first two characters.
    "hour": {"$substrBytes": ["$Time", 0, 2]},
    "halfHour": {"$concat": [
        {"$substrBytes": ["$Time", 0, 2]},
        {"$cond": [{"$lt": [{"$toInt": {"$substrBytes": ["$Time", 3, 2]}}, 30]}, ":00", ":30"]},
    ]},
    "cashier": "$registeredBy",
    "insurance": "$insuranceType",
    "reportStatus": "$imagingWorkflow.report.status",
    "date": "$Date",
}


class FilterError(ValueError):
    """A filter that cannot be honoured, with the reason a person can act on."""

    code = "FILTER_NOT_POSSIBLE"


def _modality_label(code: Any) -> str:
    known = dm.modalities()
    entry = known.get(str(code))
    return entry.name if entry else str(code)


def build_filter(
    *,
    modality: Any = None,
    service: Any = None,
    insurance: Any = None,
    report_status: Any = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_deleted: bool = False,
    deleted_only: bool = False,
    discounted_only: bool = False,
    contrast_names: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Assemble the Mongo filter, and the human-readable record of what it means.

    Returns ``(query, applied)``. `applied` is published with the answer: it is
    what turns "418" into "418 receptions, matched by service name, in this
    window" — a number that can be argued with.

    Any unrecognised value raises :class:`datamodel.UnknownValue`, which carries
    the vocabulary that does exist. Nothing here ever builds a filter that
    cannot match.
    """
    conditions: list[dict[str, Any]] = []
    applied: dict[str, Any] = {}

    # «لیست بیمارانی که حذف شدن رو با کدهای پذیرششون بهم بده» could not be
    # answered: there was a way to INCLUDE deleted rows but no way to ask for
    # ONLY them, so the agent replied that no tool was available while three
    # deleted receptions sat in the data.
    #
    # A deleted RECEPTION and a deleted TRANSACTION are different records — on
    # 1405/06/01 there were 3 of the first and 7 of the second — so this filter
    # says which one it means.
    if deleted_only:
        conditions.append({"deleted": True})
        applied["deleted"] = "ONLY deleted receptions (not deleted transactions)"
    elif not include_deleted:
        conditions.append(dm.LIVE_ONLY)
        applied["deleted"] = "excluded"
    else:
        applied["deleted"] = "included"

    # Discounts live in `cashDeskDiscount`. `discountTotal` exists and is 0 on
    # every reception measured, so filtering on the obvious-looking field would
    # have returned nothing and looked like "no discounts were given".
    if discounted_only:
        conditions.append({"$or": [{f: {"$gt": 0}} for f in dm.DISCOUNT_FIELDS]})
        applied["discount"] = {"any of": list(dm.DISCOUNT_FIELDS)}

    dates = dm.date_range_filter(date_from, date_to)
    if dates:
        conditions.append(dates)
        applied["dateFrom"], applied["dateTo"] = date_from, date_to

    if service not in (None, ""):
        if not dates:
            raise FilterError(
                "a service filter needs a date range: `services.Service` has no index, "
                "and an unbounded scan of the clinical database is not a reasonable "
                "thing to run during a working day"
            )
        # Contrast is not a substring — it is a three-way classification, and
        # the negation is the discriminator. «با تزریق» matched nothing (the
        # catalogue never says «تزریق») and a naive «کنتراست» match would have
        # matched the 68 studies performed explicitly WITHOUT it.
        intent = dm.contrast_intent(service)
        if intent:
            # Classify the names that were ACTUALLY PERFORMED in the window, not
            # the catalogue's names.
            #
            # Matching performed services against catalogue strings by equality
            # under-counted: «ام آر آي مجاري صفراوي … با و بدون كنتراست» is
            # performed but is not character-identical to its catalogue entry,
            # so two receptions vanished. That is the ی/ي spelling problem one
            # layer down from where the lexicon already solves it — and it is
            # why `contrast_names` is supplied by the caller, which has the
            # collection, instead of being read from the catalogue here.
            names, resolution = dm.narrow_contrast_services(
                service, list(contrast_names or []), modality=modality,
            )
            if not names:
                raise dm.UnknownValue(
                    "service",
                    f"{service} (contrast: {intent})",
                    (
                        resolution["matchedCatalogServices"][:20]
                        or dm.services_by_contrast(intent)[:20]
                    ),
                )
            conditions.append({"services.Service": {"$in": names}})
            applied["service"] = {
                **resolution,
                "matchedCatalogServices": resolution["matchedCatalogServices"][:100],
                "interpretedAs": {
                    "contrast": intent,
                    "serviceConcept": resolution.get("canonicalConcept"),
                    "subject": resolution.get("subject"),
                },
                "matchedPerformedServices": names[:25],
                "matchedCount": len(names),
                "note_fa": (
                    "قرارداد نام‌گذاری این مرکز «با/بدون ماده حاجب» است، نه «تزریق»؛ "
                    + (
                        "«با و بدون» شامل تزریق است و در درخواست «بدون» شمرده نمی‌شود."
                        if intent == "without" else
                        "«با و بدون» فقط وقتی با معنای درخواست سازگار باشد شمرده می‌شود."
                    )
                ),
            }
        else:
            built = dm.service_filter(service)
            if built is not None:
                conditions.append(built)
            resolution = dm.service_resolution(service, modality=modality)
            matched = resolution["matchedCatalogServices"]
            applied["service"] = {
                **resolution,
                "matchedCatalogServices": matched[:100],
                "matchedCount": len(matched),
            }

    if modality not in (None, ""):
        resolved = dm.resolve_modality(modality)
        built = dm.modality_filter(modality)
        if built is not None:
            conditions.append(built)
        applied["modality"] = {"asked": modality, "code": resolved.code,
                               "name": resolved.name, "disabled": resolved.disabled}

    if insurance not in (None, ""):
        built = dm.insurance_filter(insurance)
        if built is not None:
            conditions.append(built)
        applied["insurance"] = insurance

    if report_status not in (None, ""):
        built = dm.report_status_filter(report_status)
        if built is not None:
            conditions.append(built)
        applied["reportStatus"] = report_status

    query = {"$and": conditions} if conditions else {}
    return query, applied


def search(
    *,
    modality: Any = None,
    service: Any = None,
    insurance: Any = None,
    report_status: Any = None,
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
    include_deleted: bool = False,
    deleted_only: bool = False,
    discounted_only: bool = False,
) -> dict[str, Any]:
    """Count receptions matching the filters, optionally broken down."""
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    collection = reception_db()[RECEPTIONS]

    contrast_names = None
    # Bound once rather than called twice: the second call was what the checker
    # saw, and it cannot know it returns the same non-None value as the first.
    # Calling a resolver twice to ask and then to use is also how the two answers
    # drift apart the day the resolver stops being pure.
    intent = dm.contrast_intent(service) if service not in (None, "") else None
    effective_modality = modality
    if intent is not None and modality in (None, ""):
        inferred = dm.modality_in_text(service)
        effective_modality = inferred.code if inferred is not None else None
    if intent is not None:
        contrast_names = _performed_services_by_contrast(
            collection,
            intent,
            modality=effective_modality,
            date_from=date_from,
            date_to=date_to,
        )

    query, applied = build_filter(
        modality=effective_modality, service=service, insurance=insurance,
        report_status=report_status, date_from=date_from, date_to=date_to,
        include_deleted=include_deleted, deleted_only=deleted_only,
        discounted_only=discounted_only, contrast_names=contrast_names,
    )

    # An index-served filter does not need the scan slot; a service filter does.
    unindexed = service not in (None, "")
    performed_service_names: list[dict[str, Any]] = []
    with scan_slot() if unindexed else _NullSlot():
        totals = _totals(collection, query)
        rows = list(collection.find(query, ROW_FIELDS).sort([("Date", -1)]).limit(limit))
        breakdown = _breakdown(collection, query, group_by, service) if group_by else None
        if service not in (None, "") and intent is None:
            performed_service_names = _matched_performed_service_names(
                collection, query, service
            )

    if service not in (None, "") and intent is None and isinstance(applied.get("service"), dict):
        applied["service"]["matchedPerformedServices"] = performed_service_names
        applied["service"]["matchedPerformedCount"] = len(performed_service_names)

    # A service query that finds nothing must say what its WORDS find.
    #
    # «چند تا MRI شکم لگن» answered «۰ مورد». True — there is no combined
    # abdomen-pelvis service in this catalogue — but useless, and
    # indistinguishable from "no such patients". Abdomen alone and pelvis alone
    # both happened that day. Zero without the vocabulary behind it is the same
    # confident-nothing this module exists to stop.
    if totals["receptions"] == 0 and service not in (None, "") and isinstance(applied.get("service"), dict):
        applied["service"]["termBreakdown"] = _terms_that_do_match(
            collection, service, modality=modality, date_from=date_from, date_to=date_to,
        )
        applied["service"]["zero_note_fa"] = (
            "هیچ خدمتی با همهٔ این واژه‌ها با هم وجود ندارد. شمارش هر واژه به‌تنهایی "
            "در «termBreakdown» آمده است — آن‌ها را خودسرانه با هم جمع نکن."
        )

    for row in rows:
        modality_value = row.get("modality")
        code = modality_value.get("_id") if isinstance(modality_value, dict) else modality_value
        row["modalityCode"] = str(code)
        row["modality"] = _modality_label(code)
        row["services"] = [s.get("Service") for s in (row.get("services") or [])]
        if row.get("patient") is not None:
            row["patientRef"] = str(row.pop("patient"))
        # One number the reader can use, plus the field it came from — four
        # near-identical keys, three of them 0, is not a row a person can read,
        # and «کدام فیلد» is a real question here because the vendor's own
        # report disagrees with itself about which one holds the money.
        parts = {field: row.pop(field, None) or 0 for field in dm.DISCOUNT_FIELDS}
        row["discountAmount"] = sum(parts.values())
        if row["discountAmount"]:
            row["discountFields"] = {k: v for k, v in parts.items() if v}

    return {
        "skill": "reception.search",
        "filters": applied,
        "period": {"from": date_from, "to": date_to},
        # Three grains and the discount money, all computed over the FULL match.
        # Naming the grains separately is the point: «چند بیمار» and «چند پذیرش»
        # and «چند خدمت» are three different questions and the same filter
        # answers all three differently. `discountAmount` is 0 on most queries
        # and that is a fact about the matched receptions, not a missing value.
        "totals": totals,
        # Kept so older callers do not break. It is the reception count.
        "count": totals["receptions"],
        # Every figure above and in `breakdown` covers the whole match. Stated as
        # a positive at the TOP LEVEL because the previous shape did not work:
        # `rowsComplete: false` sat beside a complete breakdown and the model read
        # it as "the answer is partial", then refused to name the top MRI service
        # it had been handed. Replacing one truncation flag with three richer ones
        # made that worse, not better -- the fix is to say plainly what IS
        # complete and to bury the row bookkeeping.
        "figuresAreComplete": True,
        "breakdown": breakdown,
        "rows": rows,
        "rowsInfo": {
            "shown": len(rows),
            "note": (
                "Rows are a display sample, newest first, for showing people. They "
                "are not what any figure is computed from and never limit an answer."
            ),
        },
    }


def _terms_that_do_match(
    collection, service: Any, *, modality: Any, date_from: str | None, date_to: str | None
) -> list[dict[str, Any]]:
    """For each WORD of a zero-result service query, what it matches on its own.

    Deliberately per-term and never summed: abdomen and pelvis are clinically
    different studies and adding them would invent a combined figure the
    catalogue does not have. The caller is told not to add them, and the numbers
    are reported separately so a person can decide.
    """
    match: dict[str, Any] = dict(dm.LIVE_ONLY)
    dates = dm.date_range_filter(date_from, date_to)
    if dates:
        match.update(dates)
    if modality not in (None, ""):
        built = dm.modality_filter(modality)
        if built is not None:
            match.update(built)

    terms = [t for t in re.split(r"[\s،,/]+", str(service)) if len(t) >= 2][:6]
    out: list[dict[str, Any]] = []
    for term in terms:
        try:
            cond = dict(match)
            built = dm.service_filter(term)
            if built is not None:
                cond.update(built)
            hits = list(collection.aggregate(
                [{"$match": cond},
                 {"$group": {"_id": None, "receptions": {"$sum": 1},
                             "patients": {"$addToSet": "$patient"}}},
                 {"$project": {"receptions": 1, "patients": {"$size": "$patients"}}}],
                maxTimeMS=15000,
            ))
            names = list(collection.aggregate(
                [{"$match": cond}, {"$unwind": "$services"},
                 {"$match": dm.service_filter(term)},
                 {"$group": {"_id": "$services.Service", "n": {"$sum": 1}}},
                 {"$sort": {"n": -1}}, {"$limit": 10}],
                maxTimeMS=15000,
            ))
            row = hits[0] if hits else {"receptions": 0, "patients": 0}
            out.append({
                "term": term,
                "receptions": row.get("receptions", 0),
                "patients": row.get("patients", 0),
                "services": [{"service": n["_id"], "lines": n["n"]} for n in names],
            })
        except dm.FilterValueProblem:
            out.append({"term": term, "receptions": 0, "patients": 0, "services": []})
    return out


def _performed_services_by_contrast(
    collection, intent: str, *, modality: Any, date_from: str | None, date_to: str | None
) -> list[str]:
    """Service names ACTUALLY PERFORMED in the window that match a contrast intent.

    Classifying the catalogue and matching by equality lost receptions whose
    stored service name is a spelling variant of the catalogue entry — the same
    ی/ي divergence that splits the service groups. Reading the distinct names
    that were performed and classifying those is exact, and bounded: a day of
    MRI is ~26 names.
    """
    match: dict[str, Any] = dict(dm.LIVE_ONLY)
    dates = dm.date_range_filter(date_from, date_to)
    if dates:
        match.update(dates)
    if modality not in (None, ""):
        built = dm.modality_filter(modality)
        if built is not None:
            match.update(built)

    wanted = dm.contrast_classes_for_intent(intent)

    names = collection.aggregate(
        [{"$match": match}, {"$unwind": "$services"},
         {"$group": {"_id": "$services.Service"}}],
        maxTimeMS=20000,
    )
    return [n["_id"] for n in names
            if n["_id"] and dm.contrast_of(n["_id"]) in wanted]


def _matched_performed_service_names(
    collection, query: dict[str, Any], service: Any
) -> list[dict[str, Any]]:
    """Exact stored names that contributed to a service-concept count.

    Catalogue names alone are insufficient: this centre still performs legacy
    service names that are no longer present in ``ServicesInfo``.  Reporting
    the names from the matched reception lines makes the cohort auditable and
    is bounded by the caller's mandatory date range.
    """
    service_match = dm.service_filter(service)
    if service_match is None:
        return []
    rows = list(collection.aggregate([
        {"$match": query},
        {"$unwind": "$services"},
        {"$match": service_match},
        {"$group": {"_id": "$services.Service", "serviceLines": {"$sum": 1}}},
        {"$sort": {"serviceLines": -1, "_id": 1}},
        {"$limit": 200},
    ]))
    return [
        {"service": row.get("_id"), "serviceLines": int(row.get("serviceLines") or 0)}
        for row in rows if row.get("_id")
    ]


def _totals(collection, query: dict[str, Any]) -> dict[str, int]:
    """Receptions, distinct patients and service lines — over the whole match.

    One pass. Grouping by `patient` first makes the memory proportional to the
    number of distinct patients rather than to the number of matched documents,
    which keeps a year-wide question inside the aggregation memory limit.

    This exists because the answer used to be assembled from a truncated row
    list, so the model could see 25 rows, know the count was 62, and correctly
    refuse to say how many PEOPLE that was. The information was absent, not
    withheld — and absent information reads to a user like a limit.
    """
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$patient",
            "receptions": {"$sum": 1},
            "serviceLines": {"$sum": {"$size": {"$ifNull": ["$services", []]}}},
            # Summed here rather than left to the caller, because the only other
            # place the money could come from is `rows` — and rows are a display
            # sample that no figure may be computed from. Offering the amount
            # only on the rows would have invited exactly the arithmetic the
            # rest of this module exists to prevent.
            "discountAmount": {"$sum": _DISCOUNT_SUM},
        }},
        {"$group": {
            "_id": None,
            "patients": {"$sum": 1},
            "receptions": {"$sum": "$receptions"},
            "serviceLines": {"$sum": "$serviceLines"},
            "discountAmount": {"$sum": "$discountAmount"},
        }},
    ]
    rows = list(collection.aggregate(pipeline))
    if not rows:
        return {"patients": 0, "receptions": 0, "serviceLines": 0, "discountAmount": 0}
    row = rows[0]
    return {
        "patients": int(row.get("patients") or 0),
        "receptions": int(row.get("receptions") or 0),
        "serviceLines": int(row.get("serviceLines") or 0),
        "discountAmount": int(row.get("discountAmount") or 0),
    }


class _NullSlot:
    def __enter__(self) -> "_NullSlot":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def _breakdown(collection, query: dict[str, Any], group_by: str,
               service: Any) -> dict[str, Any]:
    """Group the matched receptions by one dimension.

    `service` groups on an ARRAY element, so it needs an `$unwind` — and that
    changes what is being counted from receptions to service LINES. Said out
    loud in the result rather than left for the reader to infer: one reception
    with three services is one reception and three lines, and which of those a
    question wants is not obvious.
    """
    key = GROUP_BY.get(group_by)
    if key is None:
        raise FilterError(f"cannot group by {group_by!r}; known: {', '.join(sorted(GROUP_BY))}")

    pipeline: list[dict[str, Any]] = [{"$match": query}]
    counts = "receptions"
    if group_by == "service":
        pipeline.append({"$unwind": "$services"})
        counts = "serviceLines"
        # After unwinding, keep only the lines that matched the service filter —
        # otherwise a reception that had a mammogram AND an ultrasound reports
        # the ultrasound too, and the breakdown quietly stops being about the
        # thing that was asked for.
        if service not in (None, ""):
            pipeline.append({"$match": dm.service_filter(service)})
    # Group by (dimension, patient) first so each bucket can report distinct
    # PEOPLE as well as rows. Without this the breakdown answers "how many
    # receptions per modality" and the user asking «چند بیمار ام‌آر‌آی» has to
    # be told the number is not available — which is how this went wrong.
    pipeline += [
        {"$group": {
            "_id": {"k": key, "p": "$patient"},
            "n": {"$sum": 1},
            "lines": {"$sum": {"$size": {"$ifNull": ["$services", []]}}}
            if group_by != "service" else {"$sum": 1},
        }},
        {"$group": {
            "_id": "$_id.k",
            "patients": {"$sum": 1},
            "n": {"$sum": "$n"},
            "serviceLines": {"$sum": "$lines"},
        }},
        {"$sort": {"n": -1}},
        # No cap on dates or services: a year grouped by date is 365 buckets and
        # the user asked to see the year. Modalities and insurers are single
        # digits. A cap here would be another invisible truncation.
        {"$limit": 2000},
    ]

    rows = list(collection.aggregate(pipeline))
    cashier_names: dict[str, str] = {}
    if group_by == "cashier":
        # The aggregation key is AdminUsers._id.  Returning that ObjectId as a
        # label forced the language model to join it against a different tool,
        # and one missed source turned a known person into an opaque id.  Resolve
        # the identity once, here, where the relationship is deterministic.
        from .people import _staff_names

        cashier_names = _staff_names([str(row.get("_id") or "") for row in rows])
    items = []
    for row in rows:
        value = row["_id"]
        label = _modality_label(value) if group_by == "modality" else value
        if group_by == "insurance":
            label = dm.INSURANCE_CODES.get(str(value), f"کد {value}")
        if group_by == "cashier":
            value = str(value or "")
            label = cashier_names.get(value) or value or "نامشخص"
        items.append({
            "value": value,
            "label": label,
            "n": row["n"],
            "patients": row["patients"],
            "serviceLines": row["serviceLines"],
        })
    return {
        "by": group_by,
        "counts": counts,
        "nMeans": ("service lines" if group_by == "service" else "receptions"),
        "items": items,
        "complete": len(items) < 2000,
    }


def vocabulary(kind: str, date_from: str | None = None, date_to: str | None = None,
               contains: str | None = None, limit: int = 60) -> dict[str, Any]:
    """What values this field actually has — the answer to "0 results".

    When a filter finds nothing, the useful reply is not "0"; it is "0, and here
    is what this field does contain". This is the call that makes that possible.
    """
    collection = reception_db()[RECEPTIONS]
    if kind == "modality":
        known = dm.modalities().values()
        return {"field": "modality", "values": [
            {"code": m.code, "name": m.name, "nameFa": m.name_fa, "disabled": m.disabled}
            for m in known
        ]}

    if kind == "service":
        terms = (
            tuple(dm.fold(term) for term in dm.service_resolution(contains)["expandedTerms"])
            if contains else ()
        )
        items = [
            {"service": row.get("Service"), "modality": str(row.get("Modality") or ""),
             "modalityName": _modality_label(row.get("Modality")),
             "group": row.get("ServiceGroup")}
            for row in dm.service_catalog()
            if not terms or any(term in dm.fold(row.get("Service")) for term in terms)
        ]
        performed: list[dict[str, Any]] = []
        dates = dm.date_range_filter(date_from, date_to)
        if contains and dates:
            query = {
                "$and": [
                    dm.LIVE_ONLY,
                    dates,
                    dm.service_filter(contains),
                ]
            }
            with scan_slot():
                performed = _matched_performed_service_names(collection, query, contains)
        return {
            "field": "services.Service",
            "catalogueSize": len(dm.service_catalog()),
            "matched": len(items),
            "values": items[:limit],
            "resolution": dm.service_resolution(contains) if contains else None,
            "performedValues": performed[:limit],
            "performedValuesComplete": len(performed) <= limit,
        }

    if kind in ("insurance", "reportStatus"):
        path = dm.BY_MEANING[kind].path
        match = {**dm.LIVE_ONLY}
        dates = dm.date_range_filter(date_from, date_to)
        if dates:
            match.update(dates)
        rows = list(collection.aggregate([
            {"$match": match},
            {"$group": {"_id": f"${path}", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ]))
        return {"field": path, "values": [
            {"value": r["_id"],
             "label": dm.INSURANCE_CODES.get(str(r["_id"]), str(r["_id"])),
             "n": r["n"]}
            for r in rows
        ]}

    raise FilterError(f"no vocabulary for {kind!r}; known: modality, service, insurance, reportStatus")
