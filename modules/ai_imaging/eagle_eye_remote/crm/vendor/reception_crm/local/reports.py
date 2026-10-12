"""Reading and searching clinical reports out of the reception database.

Reports are not files. They live in ``receptions.imagingWorkflow.report`` as
HTML embedded in the reception document -- 25,375 of 53,911 receptions carry
one. That single fact removes the entire "resolve a path, open a file, parse a
document" layer this capability was assumed to need.

Two shapes in the vendor's data will silently corrupt a naive query, and both
are handled here rather than at every call site:

* ``modality`` is *usually* a code string ("3"), but several hundred documents
  embed the whole Modality object instead. ``modality_filter()`` matches both.
* ``Date`` is a Jalali **string** ("1405/05/29"), zero-padded, so lexicographic
  comparison is a valid range test -- while ``createdAt`` is a real datetime.
  Mixing them in one filter produces nonsense.
"""

from __future__ import annotations

import re
from typing import Any

from . import datamodel as dm
from .html_text import html_to_text, looks_empty
from .mongo import reception_db, scan_slot

RECEPTIONS = "receptions"

# Match the shape the caller cares about, not the shape the vendor happened to
# store. `report.content` is the report body; a report exists when it is a
# non-empty string.
HAS_REPORT: dict[str, Any] = {
    "imagingWorkflow.report.content": {"$type": "string", "$ne": ""}
}

MODALITY_NAMES = {"1": "CT", "2": "MRI", "3": "Sonography", "4": "Radiology"}

# What we read back for every report. Keeping this explicit matters: a reception
# document averages 28 KB, and pulling whole documents for a 500-row search
# would move ~14 MB to answer a question about dates.
SUMMARY_FIELDS = {
    "_id": 0,
    "ReceptionID": 1,
    "Date": 1,
    "Time": 1,
    "modality": 1,
    "nationalCode": 1,
    "patientNameSnapshot": 1,
    "patient": 1,
    "services.Service": 1,
    "imagingWorkflow.report.status": 1,
    "imagingWorkflow.report.reportDate": 1,
    "imagingWorkflow.report.approvalFlags.physicianApproved": 1,
    "imagingWorkflow.workflowStatus": 1,
}

REPORT_FIELDS = dict(SUMMARY_FIELDS)
REPORT_FIELDS["imagingWorkflow.report.content"] = 1
REPORT_FIELDS["imagingWorkflow.report.findings"] = 1

# Display budgets. Raised from 200/25 for the same reason as in receptions.py:
# a short row list was being reported to the user as a limit on the answer.
# `count` here has always been the full match, and it still is.
# Leave headroom below MAX_SCAN so the tool can still count every match when
# the requested display/export page is full.  If both ceilings were identical,
# a full page and a capped scan would be indistinguishable.
MAX_LIMIT = 2500
DEFAULT_LIMIT = 100
JALALI_DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")

# A user may describe one clinical concept with several spellings (for example
# ``disc bulge``, ``disc bulging`` and ``bulging disc``), or require several
# findings to coexist (``atrophy`` AND ``small vessel``).  The list is bounded
# because every term becomes a compiled expression and part of the Mongo
# pre-filter.  This is a search vocabulary, not a place to upload a document.
MAX_QUERY_TERMS = 12
MAX_QUERY_CHARS = 200

# Phase two of a search reads and strips every candidate, so it is bounded. At
# ~24 KB per document this is ~72 MB of reads worst case, a few seconds -- and
# a search that hits the cap says so rather than quietly under-reporting.
MAX_SCAN = 3000


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def modality_filter(modality: str | int | None) -> dict[str, Any] | None:
    """Match a modality whichever way this database happens to store it.

    Several hundred receptions embed the entire Modality document in the
    ``modality`` field instead of its code. A plain ``{"modality": "3"}`` filter
    silently misses those -- which looks like "we have fewer ultrasounds than we
    do", the worst kind of wrong answer.

    Delegates to :func:`datamodel.modality_filter`, which **refuses** a value it
    does not recognise instead of building one that cannot match. That is not a
    refinement; it is the fix for a wrong clinical answer. This used to fall
    through on an unknown name and return ``{"modality": "mammography"}`` --
    zero documents, reported to a clinician as "we have no BI-RADS 3
    mammography cases". Measured truth: 418 mammography receptions in that
    window, 15 of them with a BI-RADS 3 report, every one recorded under
    Radiology or MRI because mammography here is a SERVICE, not a modality.
    """
    return dm.modality_filter(modality)


def date_range_filter(date_from: str | None, date_to: str | None) -> dict[str, Any] | None:
    """A Jalali string range. Zero-padded YYYY/MM/DD compares lexicographically."""
    bounds: dict[str, Any] = {}
    if date_from and JALALI_DATE.match(date_from.strip()):
        bounds["$gte"] = date_from.strip()
    if date_to and JALALI_DATE.match(date_to.strip()):
        bounds["$lte"] = date_to.strip()
    return {"Date": bounds} if bounds else None


def _tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"[0-9A-Za-z؀-ۿ]+", query or "") if t]


# Grades in this archive are written as digits AND as Roman numerals in the same
# field -- real examples include "BIRADS :3", "BIRADS:IV" and "BIRADS:II". A
# search for 3 that cannot find III is wrong in a way nobody would notice.
_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V", "6": "VI"}
_ROMAN_REVERSE = {v.lower(): k for k, v in _ROMAN.items()}

# On CLEAN text the gap between words is punctuation and spaces. Bounded so a
# phrase match cannot silently span half a paragraph.
_GAP = r"[\s\-_.:،,/\\|()\[\]]{0,8}"


# Radiology grading acronyms get hyphenated inconsistently by the people typing
# them -- this archive holds 1,591 "BIRADS" and 11 "BI-RADS", and the same will
# be true of LI-RADS, TI-RADS and PI-RADS. Allowing at most one separator
# between the letters of a long ASCII acronym makes one search find every
# spelling, without loosening the match enough to hit an unrelated word.
_INTERNAL_SEPARATOR = r"[\s\-_.]?"

# A grade must end where it ends. Without this, "V" happily matches the first
# letter of "VI" and "I" matches the first letter of "III" and "IV" -- so a
# search for BI-RADS 5 returned a report reading "BIRADS: VI", and a search for
# BI-RADS 1 would have matched grades III, IV and VI. Found on the live archive:
# reception 52047 came back as a "BI-RADS 5" match with "BIRADS: VI" in its own
# snippet. This is the dangerous direction of error -- a known malignancy
# presented as a lower grade -- and no unit test written from the schema would
# have caught it.
_GRADE_BOUNDARY = r"(?![IVXivx0-9])"


def _is_grade(token: str) -> bool:
    return token in _ROMAN or token.lower() in _ROMAN_REVERSE


def _token_alternatives(token: str) -> str:
    """One token as a regex alternation covering the forms this archive uses."""
    forms = {re.escape(token)}

    if token in _ROMAN:
        forms.add(_ROMAN[token])
    lowered = token.lower()
    if lowered in _ROMAN_REVERSE:
        forms.add(_ROMAN_REVERSE[lowered])

    if len(token) >= 4 and token.isascii() and token.isalpha():
        forms.add(_INTERNAL_SEPARATOR.join(re.escape(c) for c in token))

    alternation = "(?:%s)" % "|".join(sorted(forms, key=len, reverse=True))
    return alternation + _GRADE_BOUNDARY if _is_grade(token) else alternation


def phrase_pattern(query: str) -> str:
    """Match the query as a phrase in *stripped* report text."""
    tokens = _tokens(query)
    if not tokens:
        return re.escape((query or "").strip())
    return _GAP.join(_token_alternatives(t) for t in tokens)


def _narrow_filter(query: str) -> dict[str, Any] | None:
    """A cheap Mongo-side pre-filter, used only to shrink the candidate set.

    The precise phrase match happens in Python on stripped text, because the
    stored HTML is far too messy for one regex to be both correct and readable:
    a real report contains ``BIRADS&nbsp;&nbsp; 2 :`` and
    ``BIRADS:IV</span></span></p>``. Trying to express "BIRADS then a grade"
    across entity references and nested tags produced a pattern that matched 23
    documents out of 1,591 -- confidently, and wrongly.

    So Mongo narrows on the distinctive WORD only (fast, ~2s over the archive,
    ~1s date-narrowed), and correctness is decided after the markup is gone.
    Short and numeric tokens are useless as filters -- "3" appears in nearly
    every report -- so they are left to the second phase.

    Grades are excluded even when long enough ("III"), because a grade is
    precisely the token with two spellings: narrowing Mongo on the literal
    "III" would drop every report that wrote the same grade as "3", so
    `BIRADS III` would quietly return fewer matches than `BIRADS 3`.
    """
    words = [
        t for t in _tokens(query)
        if len(t) >= 3 and not t.isdigit() and not _is_grade(t)
    ]
    if not words:
        return None
    return {
        "$and": [
            {"imagingWorkflow.report.content": {"$regex": re.escape(w), "$options": "i"}}
            for w in words
        ]
    }


def _normalise_queries(query: str, queries: Any = None) -> list[str]:
    """Return the exact clinical phrases to search, safely bounded.

    ``query`` remains the backwards-compatible single-term contract.  When
    ``queries`` is supplied it is authoritative: the human-facing criterion may
    be Persian while the actual report phrases are Latin, so automatically
    adding ``query`` would turn an ``all`` search into an impossible condition.
    """
    raw = queries if queries not in (None, []) else [query]
    if not isinstance(raw, list):
        raise ValueError("queries must be an array of clinical words or phrases")
    if not raw or len(raw) > MAX_QUERY_TERMS:
        raise ValueError(f"provide between 1 and {MAX_QUERY_TERMS} search phrases")

    terms: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise ValueError("every queries item must be a string")
        term = value.strip()
        if not term:
            raise ValueError("search phrases may not be empty")
        if len(term) > MAX_QUERY_CHARS:
            raise ValueError(
                f"each search phrase must be at most {MAX_QUERY_CHARS} characters"
            )
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _normalise_match_mode(value: Any) -> str:
    mode = str(value or "any").strip().lower()
    if mode not in {"any", "all"}:
        raise ValueError("matchMode must be 'any' or 'all'")
    return mode


def _combined_narrow_filter(terms: list[str], match_mode: str) -> dict[str, Any] | None:
    """A lossless Mongo pre-filter for several precise Python-side matches.

    In ``any`` mode, one term without a useful distinctive word means Mongo
    cannot safely narrow: excluding that branch could drop a real result.  In
    ``all`` mode every report must match every term, so the useful filters can
    still be combined and the short terms left to phase two.
    """
    narrowed = [_narrow_filter(term) for term in terms]
    if match_mode == "any" and any(item is None for item in narrowed):
        return None
    usable = [item for item in narrowed if item is not None]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    return {"$or" if match_mode == "any" else "$and": usable}


def _clamp(limit: Any, default: int = DEFAULT_LIMIT) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_LIMIT, value))


# --------------------------------------------------------------------------- #
# Shaping
# --------------------------------------------------------------------------- #
def _modality_code(raw: Any) -> str | None:
    if isinstance(raw, dict):
        return str(raw.get("_id") or "") or None
    return str(raw) if raw not in (None, "") else None


def summarize_row(doc: dict, *, text: str | None = None) -> dict:
    workflow = doc.get("imagingWorkflow") or {}
    report = workflow.get("report") or {}
    flags = report.get("approvalFlags") or {}
    code = _modality_code(doc.get("modality"))
    row = {
        "receptionId": doc.get("ReceptionID"),
        "date": doc.get("Date"),
        "time": doc.get("Time"),
        "modalityCode": code,
        "modality": MODALITY_NAMES.get(code or "", code),
        "nationalCode": doc.get("nationalCode"),
        "patientName": doc.get("patientNameSnapshot"),
        "services": [
            str(service.get("Service"))
            for service in (doc.get("services") or [])
            if isinstance(service, dict) and service.get("Service")
        ],
        "reportStatus": report.get("status"),
        "reportDate": report.get("reportDate"),
        "physicianApproved": bool(flags.get("physicianApproved")),
        "workflowStatus": workflow.get("workflowStatus"),
    }
    if text is not None:
        row["reportText"] = text
        row["reportChars"] = len(text)
    return row


def _snippet(text: str, match: re.Match | None, window: int = 160) -> str:
    """The matched phrase in context, so a person can see WHY a report matched."""
    if not text:
        return ""
    if not match:
        return text[:window].strip()
    start = max(0, match.start() - window // 2)
    end = min(len(text), match.end() + window // 2)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


# --------------------------------------------------------------------------- #
# The three operations
# --------------------------------------------------------------------------- #
def get_report(reception_id: Any = None, national_code: str | None = None) -> dict:
    """One report, as text. By reception id, or the latest for a patient."""
    # Build and validate the query BEFORE touching the database: a malformed
    # call should not open a connection, and should answer the same way whether
    # or not this machine has a reception database at all.
    if reception_id not in (None, ""):
        try:
            query: dict[str, Any] = {"ReceptionID": int(reception_id)}
        except (TypeError, ValueError):
            return {"found": False, "reason": "receptionId must be a number"}
    elif national_code:
        query = {"nationalCode": str(national_code).strip()}
    else:
        return {"found": False, "reason": "provide receptionId or nationalCode"}

    query.update(HAS_REPORT)
    col = reception_db()[RECEPTIONS]
    doc = col.find_one(query, REPORT_FIELDS, sort=[("ReceptionID", -1)])
    if not doc:
        return {
            "found": False,
            "reason": "no reception with a report body matched",
            "query": {"receptionId": reception_id, "nationalCode": national_code},
        }

    report = (doc.get("imagingWorkflow") or {}).get("report") or {}
    text = html_to_text(report.get("content"))
    row = summarize_row(doc, text=text)
    row["found"] = True
    row["reportEmpty"] = looks_empty(text)
    findings = html_to_text(report.get("findings"))
    if findings and findings != text:
        row["findings"] = findings
    return row


def search_reports(
    query: str,
    *,
    queries: Any = None,
    match_mode: str = "any",
    date_from: str | None = None,
    date_to: str | None = None,
    modality: str | None = None,
    service: str | None = None,
    status: str | None = None,
    approved_only: bool = False,
    limit: Any = DEFAULT_LIMIT,
) -> dict:
    """Find reports whose body matches a clinical term.

    Cost note: this is an unindexed scan of the report bodies (~2s across the
    whole archive, ~1s when date-narrowed, measured). No index is created on the
    vendor's collection -- see local/mongo.py for why.
    """
    if not (query or "").strip() and queries in (None, []):
        return {"count": 0, "rows": [], "reason": "empty search term"}

    terms = _normalise_queries(query, queries)
    match_mode = _normalise_match_mode(match_mode)
    date_filter = date_range_filter(date_from, date_to)
    if service not in (None, "") and not (
        isinstance(date_from, str)
        and isinstance(date_to, str)
        and JALALI_DATE.fullmatch(date_from.strip())
        and JALALI_DATE.fullmatch(date_to.strip())
    ):
        raise ValueError(
            "a service-filtered report search needs both dateFrom and dateTo "
            "as valid Jalali dates; services.Service is not indexed"
        )
    if (
        isinstance(date_from, str)
        and isinstance(date_to, str)
        and JALALI_DATE.fullmatch(date_from.strip())
        and JALALI_DATE.fullmatch(date_to.strip())
        and date_from.strip() > date_to.strip()
    ):
        raise ValueError("dateFrom must not be later than dateTo")

    limit = _clamp(limit)

    conditions: list[dict[str, Any]] = [dm.LIVE_ONLY, HAS_REPORT]
    narrow = _combined_narrow_filter(terms, match_mode)
    if narrow:
        conditions.append(narrow)
    for extra in (date_filter, modality_filter(modality), dm.service_filter(service)):
        if extra:
            conditions.append(extra)
    if status:
        conditions.append({"imagingWorkflow.report.status": str(status).strip()})
    if approved_only:
        conditions.append(
            {"imagingWorkflow.report.approvalFlags.physicianApproved": True}
        )

    mongo_query = {"$and": conditions}
    col = reception_db()[RECEPTIONS]

    # Phase two: decide correctness on stripped text. Every candidate is read
    # and stripped, so the scan is bounded to protect an interactive request --
    # and when the bound is hit we say so rather than under-reporting.
    #
    # Two things about this cursor were measured on the live server and are not
    # arbitrary (docs/AGENT_SAFETY_REVIEW.md):
    #
    # * **The sort is on `Date` alone.** Sorting on (Date, ReceptionID) is not
    #   served by any of the vendor's indexes, so mongod fell back to a blocking
    #   SORT -- which on a whole-archive search sorted 295 MB, exceeded its
    #   100 MB budget and **spilled to the clinical server's disk**. Sorting on
    #   `Date` alone is index-provided: no SORT stage, no spill, and the same
    #   wall time cut by roughly a third. The ReceptionID tie-break moved to
    #   Python below, where it costs nothing.
    #
    # * **There is no `count_documents` first.** There used to be, purely to
    #   decide whether the cap had been hit -- and it ran the identical filter,
    #   which meant every whole-archive search scanned the collection TWICE.
    #   Hitting the cap is knowable from the scan itself.
    patterns = [
        (term, re.compile(phrase_pattern(term), re.IGNORECASE)) for term in terms
    ]

    rows: list[dict[str, Any]] = []
    matched = scanned = 0
    capped = False

    # One scan of the reception database at a time, across the whole process.
    # A thread-per-request HTTP server will happily start three of these at
    # once; three concurrent collection scans of a 1.4 GB clinical collection is
    # not a thing to do to a shared server during a working day.
    with scan_slot():
        cursor = col.find(mongo_query, REPORT_FIELDS).sort([("Date", -1)])
        for doc in cursor.limit(MAX_SCAN):
            scanned += 1
            if scanned >= MAX_SCAN:
                capped = True
            report = (doc.get("imagingWorkflow") or {}).get("report") or {}
            text = html_to_text(report.get("content"))
            found = [(term, pattern.search(text)) for term, pattern in patterns]
            is_match = (
                any(match is not None for _, match in found)
                if match_mode == "any"
                else all(match is not None for _, match in found)
            )
            if not is_match:
                continue
            matched += 1
            if len(rows) < limit:
                # A search result carries a SNIPPET, never the whole body: 25
                # full reports would be ~19 KB of prompt to answer "which ones
                # matched".
                row = summarize_row(doc)
                matched_terms = [(term, match) for term, match in found if match is not None]
                row["matchedQueries"] = [term for term, _ in matched_terms]
                row["snippets"] = [
                    {"query": term, "text": _snippet(text, match)}
                    for term, match in matched_terms
                ]
                # Compatibility for answer prompts and older clients that know
                # only the original one-snippet shape.
                row["snippet"] = row["snippets"][0]["text"]
                row["reportChars"] = len(text)
                rows.append(row)

    # The tie-break the server no longer does. Same order as before, paid for in
    # microseconds on at most `limit` rows instead of by a 295 MB disk spill.
    rows.sort(key=lambda r: (str(r.get("date") or ""), r.get("receptionId") or 0), reverse=True)

    return {
        "query": query,
        "queries": terms,
        "matchMode": match_mode,
        "filters": {
            "dateFrom": date_from,
            "dateTo": date_to,
            "modality": modality,
            "service": (
                dm.service_resolution(service, modality=modality)
                if service not in (None, "")
                else None
            ),
            "status": status,
            "physicianApprovedOnly": bool(approved_only),
            "deleted": "excluded",
        },
        "count": matched,
        "returned": len(rows),
        "truncated": matched > len(rows),
        "candidatesScanned": scanned,
        "scanCapped": capped,
        "rows": rows,
    }


def patient_report_history(national_code: str, *, limit: Any = 10) -> dict:
    """Every report for one patient, newest first, as text.

    This is what makes "has anything changed since last year?" answerable: the
    stripped bodies are ~750 characters each, so ten of them fit in one prompt.
    """
    if not (national_code or "").strip():
        return {"count": 0, "rows": [], "reason": "nationalCode is required"}

    db = reception_db()
    col = db[RECEPTIONS]
    limit = _clamp(limit, default=10)

    query = {"nationalCode": str(national_code).strip(), **HAS_REPORT}
    total = col.count_documents(query)
    cursor = col.find(query, REPORT_FIELDS).sort([("Date", -1), ("ReceptionID", -1)]).limit(limit)

    rows = []
    for doc in cursor:
        report = (doc.get("imagingWorkflow") or {}).get("report") or {}
        text = html_to_text(report.get("content"))
        rows.append(summarize_row(doc, text=text))

    return {
        "nationalCode": national_code,
        "count": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "rows": rows,
    }


def archive_stats() -> dict:
    """How much of the archive is reportable.

    Not as cheap as it looks: `HAS_REPORT` is a `$type`/`$ne` test that no index
    serves, so each of the three questions below is a pass over 54k documents.
    They take the scan slot together rather than one at a time, so this counts
    as ONE piece of work against the reception database instead of three that
    can interleave with somebody else's search.
    """
    db = reception_db()
    col = db[RECEPTIONS]
    total = col.estimated_document_count()
    with scan_slot():
        with_report = col.count_documents(HAS_REPORT)
        approved = col.count_documents(
            {**HAS_REPORT, "imagingWorkflow.report.approvalFlags.physicianApproved": True}
        )
        modality_rows = list(
            col.aggregate(
                [{"$match": HAS_REPORT}, {"$group": {"_id": "$modality", "n": {"$sum": 1}}}]
            )
        )
    by_modality: dict[str, Any] = {}
    for row in modality_rows:
        code = _modality_code(row.get("_id"))
        label = MODALITY_NAMES.get(code or "", code or "unknown")
        by_modality[label] = by_modality.get(label, 0) + row.get("n", 0)
    return {
        "receptions": total,
        "withReport": with_report,
        "physicianApproved": approved,
        "byModality": by_modality,
    }
