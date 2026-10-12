"""The appointment diary: what is booked, what a room can hold, what is free.

⚠️ THE BIGGEST GAP THE v3 BENCHMARK FOUND. All ten Appointment questions came
back as clarifications with **zero tool calls** — free slots, capacity
utilisation, one patient's active appointment, appointment-versus-reception
conversion, and the single executive write test, which could never reach its
confirmation gate because the turn meant to propose a slot had nothing to
propose from. Fourteen per cent of the question set, unanswerable, while the
data sat in the database the agent was already reading.

## What an appointment IS here, which is the thing that makes this tricky

It is **not a calendar entry**. There is no appointments collection. An
appointment is a sub-document ON A RECEPTION:

    receptions.imagingWorkflow.appointment = {
        persianDate, startTime, endTime, duration, timeSlot,
        room,      # ObjectId
        shift, shiftName, scheduledAt
    }

So the patient is admitted FIRST and scheduled SECOND, and «کسی نوبت داشت ولی
پذیرش نشد» is close to structurally impossible — saying so is a better answer
than a number, and `appointment_vs_reception` says it.

## The join hazard, measured

`Rooms._id` is a **string**; `appointment.room` is an **ObjectId**. Comparing
them directly matches nothing and every room reads as empty — which is
indistinguishable from a genuinely empty day, and a free-slot report that says
"all free" because its join failed is the worst possible failure mode for this
tool. Everything below compares rooms as `str(...)` on both sides.

## Capacity, and the two wrong denominators before this one

⚠️ THIS FUNCTION HAS BEEN WRONG TWICE, both times by reading a real field as
something it is not, and it is worth writing down because the second mistake was
caused by the fix for the first.

**First:** capacity was counted as the NUMBER of `timeSlots`, which reported
**198% utilisation** — 127 bookings against 64 slots. A room is never more than
full, so that was not a large number, it was a wrong one.

**Second:** a probe printed a `timeSlots` entry and I read it as a shift, so the
"fix" summed `shift.capacity` and filtered on `shift.day`. Neither field exists.
Every shift matched nothing, capacity came out as 0 for every room, and the tool
reported `utilisation: null` on a day with 127 appointments in it — a failure
that looks exactly like a room with no diary.

**What the data actually holds**, counted across all 14 rooms:

    shifts[]     name, timeSlots, specialists, serviceGroups, isActive, _id
    timeSlots[]  day, startTime, endTime, capacity, isAvailable, isOvernight, _id

So a "time slot" is not a slot at all: it is a WEEKLY WINDOW carrying its own
`day` and its own `capacity`. 64 of them across six weekday names — there is no
جمعه, because the centre is closed on Fridays.

For 1404/05/22, a چهارشنبه: 205 declared places against 127 appointments, 62%.
Two rooms are individually over their declared capacity (4 places, 18 booked),
which is a real fact about how the centre works rather than an arithmetic error —
so it is reported per room and flagged, not smoothed away.

Utilisation is booked ÷ Σ capacity of the windows that run on that weekday, and
it is reported ONLY where such windows exist. A room with none has no
denominator, and a percentage against zero is not a small number, it is a
meaningless one.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from ..jalali import jalali_to_gregorian
from . import datamodel as dm
from .mongo import reception_db, scan_slot

RECEPTIONS = "receptions"
ROOMS = "Rooms"
JALALI_DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")

APPOINTMENT = "imagingWorkflow.appointment"
MAX_SCAN = 20000


def _day(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if JALALI_DATE.match(text) else None


def _rooms() -> tuple[list[dict], dict[str, dict]]:
    """Every room, and an index by STRING id.

    ⚠️ The index is keyed by `str(_id)` for the reason in the module docstring:
    the two sides of this join do not have the same type, and a lookup that
    assumes they do returns nothing while looking like it worked.
    """
    rooms = list(reception_db()[ROOMS].find())
    return rooms, {str(room.get("_id")): room for room in rooms}


#: Persian weekday names, indexed by `date.weekday()` (Monday = 0).
#: A booking window's `day` holds one of these, so a room's diary is a WEEKLY
#: pattern and only the windows matching the asked-for day apply to it. There is
#: no جمعه anywhere in the data — the centre is closed on Fridays.
_WEEKDAYS = ("دوشنبه", "سه شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")


def weekday_of(day: str) -> str:
    """The Persian weekday name for a Jalali date."""
    return _WEEKDAYS[jalali_to_gregorian(day).weekday()]


def _windows_for(room: dict, weekday: str) -> list[dict]:
    """The room's booking WINDOWS that run on that weekday.

    A window is an entry of `shifts[].timeSlots[]`, and it carries its own `day`
    and its own `capacity` — the shift above it carries neither. Filtering by
    `day` is what makes the denominator mean anything: summing every window a
    room declares would count Tuesday's places into Saturday's utilisation, and
    the answer would be wrong in the direction that looks reassuring — plenty of
    room, on a day that is full.
    """
    out = []
    for shift in room.get("shifts") or []:
        if not isinstance(shift, dict) or shift.get("isActive") is False:
            continue
        for slot in shift.get("timeSlots") or []:
            if not isinstance(slot, dict) or slot.get("isAvailable") is False:
                continue
            if fold_spaces(str(slot.get("day") or "")) != fold_spaces(weekday):
                continue
            out.append({**slot, "shiftName": shift.get("name")})
    return out


def fold_spaces(text: str) -> str:
    """ZWNJ and spaces are interchangeable in «سه‌شنبه»; the data uses both."""
    return re.sub(r"[\s‌]+", "", text)


def _declared_capacity(windows: list[dict]) -> int:
    """Places, from the windows themselves. See the module docstring for the
    two denominators this replaced."""
    total = 0
    for window in windows:
        try:
            total += int(window.get("capacity") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _booked_on(day: str) -> list[dict]:
    """Live receptions carrying an appointment for that Jalali day."""
    query = {
        f"{APPOINTMENT}.persianDate": day,
        "deleted": {"$ne": True},
    }
    projection = {
        "_id": 0, "ReceptionID": 1, "Date": 1, "modality": 1,
        APPOINTMENT: 1,
    }
    with scan_slot():
        return list(reception_db()[RECEPTIONS].find(query, projection).limit(MAX_SCAN))


def _appointment_of(doc: dict) -> dict:
    node = (doc.get("imagingWorkflow") or {}).get("appointment")
    return node if isinstance(node, dict) else {}


# --------------------------------------------------------------------------- #
# What is booked
# --------------------------------------------------------------------------- #
def appointments_on(*, date: Any = None, room: Any = None) -> dict:
    """Every appointment on one day, by room and shift.

    A ZERO IS AN ANSWER. There were no appointments at all for the day after the
    benchmark's test day, and «۰ نوبت» stated plainly is the correct reply — not
    a refusal, and not a silence that reads as a failure.
    """
    day = _day(date)
    if not day:
        return _needs_a_day("appointments.day")

    rooms, by_id = _rooms()
    booked = _booked_on(day)
    wanted_room = str(room) if room else None

    per_room: dict[str, list[dict]] = defaultdict(list)
    per_shift: Counter = Counter()
    for doc in booked:
        appt = _appointment_of(doc)
        room_id = str(appt.get("room") or "")
        if wanted_room and room_id != wanted_room:
            continue
        per_room[room_id].append({
            "receptionId": doc.get("ReceptionID"),
            "start": appt.get("startTime"),
            "end": appt.get("endTime"),
            "duration": appt.get("duration"),
            "timeSlot": appt.get("timeSlot"),
            "shiftName": appt.get("shiftName"),
        })
        per_shift[str(appt.get("shiftName") or "?")] += 1

    rows = [
        {
            "roomId": room_id,
            "room": (by_id.get(room_id) or {}).get("persianName")
                    or (by_id.get(room_id) or {}).get("name"),
            "booked": len(items),
            "appointments": sorted(items, key=lambda a: str(a.get("start") or "")),
        }
        for room_id, items in sorted(per_room.items(), key=lambda kv: -len(kv[1]))
    ]
    total = sum(len(items) for items in per_room.values())

    return {
        "skill": "appointments.day",
        "date": day,
        "booked_total": total,
        "rooms_with_bookings": len(per_room),
        "rooms_total": len(rooms),
        "by_shift": dict(per_shift),
        "rows": rows,
        "meaning_fa": (
            "نوبت در این سامانه یک رکورد مستقل نیست؛ زیرمجموعه‌ای از «پذیرش» است "
            "(imagingWorkflow.appointment). یعنی بیمار اول پذیرش می‌شود و بعد "
            "زمان‌بندی. عدد صفر هم یک پاسخ است: یعنی برای آن روز نوبتی ثبت نشده، "
            "نه اینکه اطلاعاتی در دسترس نباشد."
        ),
    }


# --------------------------------------------------------------------------- #
# What is free
# --------------------------------------------------------------------------- #
def availability(*, date: Any = None, modality: Any = None) -> dict:
    """Declared capacity against bookings, per room, for one day.

    Utilisation is reported ONLY where the room has a shift running on that
    WEEKDAY. A room with none has no denominator, and «۰٪ پر شده» against a
    diary nobody wrote is a statement about our arithmetic, not about the clinic.

    ⚠️ The denominator is `shift.capacity`, not the number of `timeSlots`. See
    the module docstring: counting slots reported 198% and a room cannot be more
    than full.
    """
    day = _day(date)
    if not day:
        return _needs_a_day("appointments.availability")

    rooms, _ = _rooms()
    weekday = weekday_of(day)
    booked = _booked_on(day)
    booked_per_room: Counter = Counter()
    for doc in booked:
        appt = _appointment_of(doc)
        booked_per_room[str(appt.get("room") or "")] += 1

    # ⚠️ `Rooms.modalityId` is the vendor's CODE — the string '1'..'14' that keys
    # the `Modality` collection. A user asks in words: «سونوگرافی», "MRI". This
    # used to compare the word against the code, so every room was skipped and
    # the tool reported a day with no rooms, no capacity and no windows.
    #
    # That is the worst shape a wrong answer can take here, because it is not
    # recognisable as one: «فردا برای سونوگرافی چه ساعت‌های خالی داریم؟» came
    # back as «برای این روز هیچ اتاق یا ظرفیت فعالی تعریف نشده است» on a
    # چهارشنبه with 205 declared places. An unmatched filter must never be
    # readable as a shut clinic — that is the rule `datamodel` exists to keep.
    #
    # `resolve_modality` raises `UnknownValue` carrying the vocabulary that does
    # exist, and that is deliberately NOT caught here: a term this database has
    # never heard of is a different answer from a modality with no room.
    wanted = wanted_label = None
    if modality:
        resolved = dm.resolve_modality(modality)
        wanted, wanted_label = str(resolved.code), resolved.label

    rows = []
    per_modality: Counter = Counter()
    capacity_total = booked_total = 0
    for room in rooms:
        room_id = str(room.get("_id"))
        if room.get("isActive") is False:
            continue
        per_modality[str(room.get("modalityId") or "")] += 1
        if wanted and str(room.get("modalityId") or "") != wanted:
            continue
        windows = _windows_for(room, weekday)
        capacity = _declared_capacity(windows)
        taken = booked_per_room.get(room_id, 0)
        capacity_total += capacity
        booked_total += taken
        rows.append({
            "roomId": room_id,
            "room": room.get("persianName") or room.get("name"),
            "roomNumber": room.get("roomNumber"),
            "modalityId": room.get("modalityId"),
            "windows_today": [
                {
                    "shift": window.get("shiftName"),
                    "from": window.get("startTime"),
                    "to": window.get("endTime"),
                    "capacity": window.get("capacity"),
                    "overnight": bool(window.get("isOvernight")),
                }
                for window in windows
            ],
            "declared_capacity": capacity,
            "booked": taken,
            # ⚠️ None, not 0.0, when there is nothing to divide by.
            "utilisation_percent": round(taken * 100 / capacity, 1) if capacity else None,
            "places_left": max(0, capacity - taken) if capacity else None,
            "over_capacity": bool(capacity and taken > capacity),
        })

    # Three different zeros, told apart, because they call for three different
    # sentences and reporting any of them as "no capacity" is a lie:
    #
    #   * no room carries that modality      -> the centre does not do it in a
    #                                           bookable room; name what it does
    #   * rooms exist, no window that weekday-> the diary is closed that day
    #   * windows exist, nothing booked      -> the day is genuinely empty
    unmatched = bool(wanted and not rows)
    known_modalities = None
    if unmatched:
        catalogue = dm.modalities()
        known_modalities = sorted(
            (catalogue[code].label if code in catalogue else f"code {code}")
            for code in per_modality
        )

    return {
        "skill": "appointments.availability",
        "date": day,
        "weekday": weekday,
        "modality_requested": wanted_label,
        "modality_code": wanted,
        # ⚠️ Read this BEFORE the totals. True means the totals below describe an
        # empty selection, not an empty day.
        "filter_matched_no_room": unmatched,
        "modalities_with_a_room": known_modalities,
        "rooms_considered": len(rows),
        "rooms_open_today": sum(1 for r in rows if r["declared_capacity"]),
        "declared_capacity_total": capacity_total,
        "booked_total": booked_total,
        "utilisation_percent": (round(booked_total * 100 / capacity_total, 1)
                                if capacity_total else None),
        # ⚠️ Reported rather than hidden. Utilisation above 100% cannot be true —
        # a room is not more than full — so it means the declared capacity is
        # not what the clinic is actually working to that day, and an answer
        # should say that instead of quoting the percentage as a fact.
        "over_capacity": bool(capacity_total and booked_total > capacity_total),
        "rooms_over_capacity": [r["room"] for r in rows if r["over_capacity"]],
        "rows": sorted(rows, key=lambda r: -(r["places_left"] or 0)),
        "meaning_fa": (
            "«ظرفیت» جمعِ capacity بازه‌های زمانی‌ای است که برای همان روزِ هفته "
            "تعریف شده‌اند. هر بازه، خودش «روز هفته» و «ظرفیت» دارد؛ شیفت فقط نام "
            "و گروهِ آن‌هاست. اندازه‌گیری‌شده در ۱۴۰۴/۰۵/۲۲ (چهارشنبه): ۲۰۵ ظرفیت "
            "اعلام‌شده در برابر ۱۲۷ نوبت.\n"
            "اگر اتاقی برای آن روزِ هفته بازه‌ای تعریف نکرده باشد، درصد اشغال گزارش "
            "نمی‌شود — نه صفر، بلکه «نامشخص»، چون مخرجی وجود ندارد.\n"
            "⚠️ اگر filter_matched_no_room درست باشد، یعنی هیچ اتاقی با آن مودالیته "
            "ثبت نشده است؛ اعداد پایین «صفر برای آن انتخاب» است، نه «آن روز اتاق و "
            "ظرفیتی وجود ندارد». در این حالت باید گفت کدام مودالیته‌ها اتاق دارند "
            "(modalities_with_a_room) و نباید روز را تعطیل یا بی‌ظرفیت اعلام کرد.\n"
            "اگر over_capacity درست باشد، یعنی نوبت‌های ثبت‌شده از ظرفیت اعلام‌شده "
            "بیشتر است. این یک واقعیت دربارهٔ روش کار مرکز است، نه خطای محاسبه؛ اما "
            "در آن حالت نباید درصد را به‌عنوان «چقدر پر شده» گزارش کرد، بلکه باید "
            "گفت ظرفیتِ ثبت‌شده با آنچه واقعاً انجام شده هم‌خوان نیست."
        ),
    }


def _slot_label(slot: Any) -> str:
    """A slot is a string in some rooms and a {start,end} document in others."""
    if isinstance(slot, str):
        return slot.strip()
    if isinstance(slot, dict):
        start = str(slot.get("startTime") or slot.get("start") or "").strip()
        end = str(slot.get("endTime") or slot.get("end") or "").strip()
        if start and end:
            return f"{start} تا {end}"
        return start or end
    return ""


# --------------------------------------------------------------------------- #
# The cross-check the benchmark asked for
# --------------------------------------------------------------------------- #
def appointment_vs_reception(*, date: Any = None) -> dict:
    """«چند نفر نوبت داشتن ولی پذیرش نشدن؟» — and why that is the wrong shape.

    An appointment is a field ON a reception. A booking that never became a
    reception therefore has nowhere to exist, so the honest answer is not a
    count but the structure: everything with an appointment on that day IS a
    reception, and the only thing that can be missing is the visit itself, which
    shows up as a deleted or unattended reception rather than an orphan booking.
    """
    day = _day(date)
    if not day:
        return _needs_a_day("appointments.vs-receptions")

    booked = _booked_on(day)
    deleted = list(reception_db()[RECEPTIONS].find(
        {f"{APPOINTMENT}.persianDate": day, "deleted": True},
        {"_id": 0, "ReceptionID": 1},
    ).limit(MAX_SCAN))
    same_day = sum(1 for doc in booked if str(doc.get("Date") or "") == day)

    return {
        "skill": "appointments.vs-receptions",
        "date": day,
        "appointments_on_the_day": len(booked),
        "of_those_admitted_the_same_day": same_day,
        "of_those_admitted_earlier_or_later": len(booked) - same_day,
        "appointments_on_deleted_receptions": len(deleted),
        "meaning_fa": (
            "«نوبت داشت ولی پذیرش نشد» در این ساختار تقریباً ناممکن است: نوبت یک "
            "فیلد روی خود پذیرش است، پس هر نوبتی الزاماً یک پذیرش دارد. آنچه "
            "می‌تواند وجود داشته باشد، پذیرشی است که حذف شده یا بیمار مراجعه "
            "نکرده — و همان عدد در بالا آمده است. پاسخ درست به این پرسش، توضیح "
            "همین ساختار است، نه یک عدد."
        ),
    }


def _needs_a_day(skill: str) -> dict:
    return {
        "skill": skill,
        "error": {
            "code": "DATE_REQUIRED",
            "message": "a Jalali date (YYYY/MM/DD, or today/tomorrow resolved by "
                       "the caller) is required",
            "message_fa": "برای این گزارش باید تاریخ جلالی مشخص شود.",
        },
    }
