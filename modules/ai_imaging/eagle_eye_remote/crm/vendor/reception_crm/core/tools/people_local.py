"""Tools for the four capabilities the v3 benchmark found missing.

Referring physicians, staff activity windows, the name-change trail, and the
whole appointment diary. Twenty-one of seventy questions could not be answered
without them, and in every case the data was already on the reception server —
the agent said so honestly and had nowhere to go.

Reads only, like everything in ``reception_crm.local``, and each one degrades to
an explanatory payload rather than a stack trace when Mongo is unreachable: the
API-backed tools have to keep working on a machine where this one cannot.
"""

from __future__ import annotations

from typing import Any

from ...local import appointments
from ...local import datamodel as dm
from ...local import people
from ...local.mongo import LocalMongoUnavailable, ScanBusy
from ..registry import ToolRegistry
from ..types import ToolDefinition

_FALSE_WORDS = {"", "0", "false", "no", "off", "none", "null"}


def _flag(value: Any) -> bool:
    """Truthiness for a value that may have arrived from an LLM as text.

    `"false"` is a non-empty string and therefore true to Python, which would
    turn a caller's explicit *off* into *on* — and for `includeNames` that means
    returning patient names nobody asked for.
    """
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def _guard(fn, /, **kwargs) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except dm.FilterValueProblem as exc:
        # A term this database has never heard of. Refused with the vocabulary
        # that DOES exist, exactly as `reception.search` refuses one — never as
        # a filter that matches nothing, because "no such modality" and "no such
        # day" are indistinguishable once they are both zero.
        return {"available": True, "error": exc.as_dict()}
    except ScanBusy as exc:
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
            "hint": ("This reads the reception database directly and only works when "
                     "the agent is installed on the reception server."),
        }


def register_people_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="marketing.referrers",
            kind="skill",
            handler=_referrers,
            description=(
                "WHICH REFERRING PHYSICIANS SENT THE CENTRE ITS PATIENTS, ranked, for a "
                "Jalali date range. Returns each referrer's name, receptions and distinct "
                "patients.\n"
                "Use for «کدوم پزشک ارجاع‌دهنده بیشترین بیمار رو فرستاده», «ارجاع‌ها», "
                "«از کدوم پزشک‌ها بیمار کمتری اومده» and any referral-volume question.\n"
                "⚠️ NOT the same as physician-performance, which counts REPORTING "
                "physicians — the radiologist who read the study, not the doctor who sent "
                "the patient. Asking one when the user meant the other answers a different "
                "question with a confident number.\n"
                "⚠️ A date range is REQUIRED. This reads the clinic's live database and "
                "refuses to scan the whole archive.\n"
                "⚠️ COMPARING TWO PERIODS: normalise them first. A month that is three "
                "days old shows EVERY referrer as down; that is the calendar, not a "
                "decline. Compare like-for-like day counts or say which you did."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "dateFrom": {"type": "string", "description": "Jalali YYYY/MM/DD."},
                    "dateTo": {"type": "string", "description": "Jalali YYYY/MM/DD."},
                    "limit": {"type": "integer"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="staff.activity",
            kind="skill",
            handler=_activity,
            description=(
                "FIRST AND LAST RECORDED ACTION per member of staff over a Jalali range, "
                "split by kind of activity: receptions registered, cashier transactions, "
                "and report actions. Names are resolved from AdminUsers.\n"
                "⚠️ For report activity, `count` and `events` are ReportLogs ROWS, not "
                "reports. One report can generate several log rows. When the user asks "
                "how many reports, use `distinct_reports` or the exact action-specific "
                "field: `secretary_approved_reports`, `physician_approved_reports`, "
                "`content_edited_reports`, or `radiologist_assigned_reports`. Approval, "
                "editing, status changes, and assignment are different work and must be "
                "labelled separately. Check `report_activity_quality`: named people cover "
                "only the attributed fraction of ReportLogs.\n"
                "For who typed reports, read `typist_assignments`: the latest logged "
                "typist target per report in the period, including logs without changedBy. "
                "This is assigned typist, NOT proof of authorship. `report_content_activity` "
                "includes attributed AND unattributed edits. Never equate zero attributed "
                "edits with no typing. انجام‌دهندهٔ خدمت means the performing PHYSICIAN; "
                "it is neither typist nor changedBy. Never infer physician identity from "
                "approval actions or the account assigning a radiologist.\n"
                "⚠️ THIS IS NOT ATTENDANCE AND MUST NOT BE PRESENTED AS WORKING HOURS. "
                "There is no attendance table in this system — the Shift collection is "
                "empty. The first recorded action is a LOWER BOUND on arrival: someone who "
                "came in at 07:30 and first touched the system at 08:08 appears here as "
                "08:08. Any answer built on this must say so.\n"
                "⚠️ The three activity kinds are counted separately BECAUSE THEY ARE NOT "
                "COMPARABLE. Registering 53 receptions and processing 105 transactions are "
                "different quantities; ranking «حجم کار» across roles by adding them "
                "produces a league table of nothing. Define the measure before ranking, "
                "and say which one you used."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="audit.name-changes",
            kind="skill",
            handler=_name_changes,
            description=(
                "THE PATIENT NAME-CHANGE TRAIL: who changed a name, when, why, from what "
                "to what, whether it was blocked, and which receptions it affected.\n"
                "⚠️ This trail EXISTS. An earlier version of the audit scenario told the "
                "model the centre does not record name changes, which was false and turned "
                "a missing tool into a false statement about the clinic. There are 67 "
                "records; 9 fell on 1405/06/02 alone.\n"
                "⚠️ A record is NOT an accusation. Most are spelling corrections or "
                "authorised changes, and `blocked: true` means the change did not happen. "
                "Report the trail; do not label it misconduct.\n"
                "Patient names are WITHHELD unless `includeNames` is set — the counts, "
                "reasons and actors answer «آیا تغییری ثبت شده؟» without naming anyone."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "limit": {"type": "integer"},
                    "includeNames": {
                        "type": "boolean",
                        "description": ("Return the old and new patient names. Off by "
                                        "default; only set it when the question needs "
                                        "the names themselves."),
                    },
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="appointments.day",
            kind="skill",
            handler=_appointments,
            description=(
                "EVERY APPOINTMENT ON ONE DAY, by room and shift, with times and durations. "
                "Use for «نوبت‌های فردا», «نوبت‌های امروز به تفکیک بخش» and any question "
                "about what is scheduled.\n"
                "⚠️ NOT `appointments.list`, which is the WAITING QUEUE — patients who "
                "want an appointment and do not have one yet. This is the diary: what is "
                "actually booked, and when.\n"
                "⚠️ An appointment here is NOT a calendar entry — there is no appointments "
                "collection. It is a sub-document on a RECEPTION "
                "(imagingWorkflow.appointment), so the patient is admitted first and "
                "scheduled second.\n"
                "⚠️ A ZERO IS AN ANSWER. If nothing is booked, say «۰ نوبت» plainly. That "
                "is not a failure to find data and must not be reported as one."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["date"],
                "properties": {
                    "date": {"type": "string", "description": "Jalali YYYY/MM/DD."},
                    "room": {"type": "string", "description": "Optional room id."},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="appointments.availability",
            kind="skill",
            handler=_availability,
            description=(
                "FREE SLOTS AND CAPACITY UTILISATION per room for one day: what each room "
                "declares in its shifts, what is booked into it, what is left, and a "
                "sample of the free times.\n"
                "Use for «چه ساعت‌های خالی داریم», «اولین نوبت خالی», «چند درصد ظرفیت پر "
                "شده» and «کدوم بخش شلوغ‌تره».\n"
                "⚠️ Utilisation is reported ONLY where a room declares slots. A room with "
                "no shift times has no denominator, and the field comes back null rather "
                "than 0% — a percentage against zero is not a small number, it is a "
                "meaningless one, and «۰٪ پر شده» about a diary nobody wrote is a "
                "statement about our arithmetic rather than about the clinic.\n"
                "⚠️ `modality` is a WORD here — «سونوگرافی», «ام‌آر‌آی», \"MRI\" — and is "
                "resolved against the vendor's modality catalogue. An unknown term is "
                "REFUSED with the list that does exist; it never becomes a filter that "
                "matches nothing.\n"
                "⚠️ CHECK `filter_matched_no_room` BEFORE quoting any total. True means no "
                "room is registered for that modality, so the zeros describe an empty "
                "SELECTION, not an empty day — say which modalities do have a room "
                "(`modalities_with_a_room`) instead of reporting that the centre has no "
                "capacity that day. Reading that zero as a shut clinic is the specific "
                "wrong answer this field exists to prevent."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["date"],
                "properties": {
                    "date": {"type": "string", "description": "Jalali YYYY/MM/DD."},
                    "modality": {
                        "type": "string",
                        "description": ("Optional. The modality as a WORD — «سونوگرافی», "
                                        "«ام‌آر‌آی», \"MRI\", \"CT\" — resolved against the "
                                        "vendor's catalogue. Not a numeric room code."),
                    },
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="appointments.vs-receptions",
            kind="skill",
            handler=_vs_receptions,
            description=(
                "Appointments on a day against the receptions that carry them: how many "
                "were admitted the same day, how many earlier or later, and how many sit "
                "on a reception that was later deleted.\n"
                "⚠️ Use this to ANSWER «چند نفر نوبت داشتن ولی پذیرش نشدن؟» — and the "
                "answer is mostly structural, not numeric. An appointment is a field ON a "
                "reception, so a booking that never became a reception has nowhere to "
                "exist. Explaining that is a better answer than a count, and the payload "
                "gives you both."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["date"],
                "properties": {"date": {"type": "string"}},
            },
        )
    )


def _referrers(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(
        people.referring_physicians,
        date_from=args.get("dateFrom"),
        date_to=args.get("dateTo"),
        limit=args.get("limit", people.DEFAULT_LIMIT),
    )


def _activity(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(
        people.staff_activity,
        date_from=args.get("dateFrom"),
        date_to=args.get("dateTo"),
        limit=args.get("limit", 50),
    )


def _name_changes(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(
        people.name_changes,
        date_from=args.get("dateFrom"),
        date_to=args.get("dateTo"),
        include_names=_flag(args.get("includeNames")),
        limit=args.get("limit", people.DEFAULT_LIMIT),
    )


def _appointments(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(appointments.appointments_on,
                  date=args.get("date"), room=args.get("room"))


def _availability(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(appointments.availability,
                  date=args.get("date"), modality=args.get("modality"))


def _vs_receptions(args: dict[str, Any]) -> dict[str, Any]:
    return _guard(appointments.appointment_vs_reception, date=args.get("date"))
