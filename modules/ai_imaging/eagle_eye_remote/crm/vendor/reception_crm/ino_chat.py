"""The patient conversation system — the CENTRAL IranNoobat backend.

The agent could not answer «سامانه گفتگو امروز مرکز را بررسی کن» at all: there
was no conversation tool among the 29, so the model quietly answered with the
reception day summary instead. A missing capability that reads as a wrong answer
is worse than a refusal.

**The conversations are not on this machine.** The reception box's Mongo has a
`chatrooms` collection, but that is the internal STAFF messenger — 89 rooms of
staff-to-staff messages, most of them from 2025. Patient conversations live on
`https://api.irannobat.ir` and are shared with the `irannobat.ir/chat` page.
Answering a patient-conversation question from local `chatrooms` would be a true
statement about the wrong store, which is the failure this module exists to stop.

Every endpoint, field name, request body and date format below was read off the
reception web app's own client (`Ino.V1/pages/chat.jsx`) and then verified
against the live API. None of it is inferred:

    POST /ChatRoom/GetData/Admin      {"User2": <centre LIC>, "MyID": <staff id>}
        -> {"ChatRooms": [...], "ChatStatus": {...}, "Patients": [...], ...}
    POST /ChatRoom/GetChatRoomData    {"id": <room id>}
        -> {"ChatRooms": {... "ChatsDate": [{"Date": "1405/06/02", "Chats": [...]}]}}

Two properties of that API shape the whole module:

* **The room list is hard-capped at 100.** `Page`, `page`, `Skip`, `skip`,
  `Limit` and `limit` were all tried and all returned the same first 100 rows.
  The cap is upstream and cannot be paged past, so it is REPORTED rather than
  hidden — a ceiling nobody can see is the same defect as the 25-row display
  budget that once made the agent say a patient count was unknowable.
* **`LastMessage.Time` is "HH:MM:SS" with no date.** The day a conversation was
  active is only knowable from the per-room detail call, whose `ChatsDate[].Date`
  is a zero-padded Jalali string. So "today" costs one detail request per room —
  mitigated by the list being ordered newest-activity-first, which lets the walk
  stop at the first room older than the window.

PHI: this module returns counts, statuses, dates, times and latencies. It never
returns message text, patient names, national codes, phone numbers or avatars,
and it never writes anything.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .jalali import normalize_jalali_date

BASE_URL = os.getenv("RECEPTION_CHAT_BASE_URL", "https://api.irannobat.ir")

#: The upstream list ceiling, established by probing every paging parameter the
#: client uses and several it does not. Not a choice of ours.
UPSTREAM_ROOM_CEILING = 100

#: How many rooms we will open in one answer.
#:
#: Set to the upstream ceiling on purpose. It was 60, and on the first live run
#: the walk hit that budget after 60 rooms without ever reaching an older
#: conversation — so rooms 61-100 might have been active today and were never
#: opened. The answer nonetheless said «آمار امروز کامل گزارش شده است», because
#: the completeness flag below was wrong too. A budget below the ceiling makes
#: silent truncation the DEFAULT case rather than the exception.
#:
#: The cost is bounded: the list is newest-activity-first, so a question about
#: today stops naturally at the first conversation older than today, and only a
#: question about an old date pays for all 100.
DEFAULT_ROOM_BUDGET = UPSTREAM_ROOM_CEILING

#: `ChatStatus` on a room is a numeric string; the API publishes the names in the
#: same response, so they are read from the payload rather than hard-coded here.
#: This is only the fallback for a room whose status is absent from that map.
UNKNOWN_STATUS_FA = "نامشخص"


class ChatUnavailable(RuntimeError):
    """The conversation backend could not be reached or answered.

    Deliberately distinct from "there were no conversations". The reception box's
    DNS has dropped intermittently, and a network failure that returns an empty
    summary would tell the owner the clinic had no patient conversations today —
    a confident, false, operationally serious zero.
    """

    code = "CHAT_UNAVAILABLE"

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "detail": self.detail,
            "message_fa": (
                "ارتباط با سامانهٔ گفتگو (سرور مرکزی ایران‌نوبت) برقرار نشد. "
                "این یعنی «نتوانستم بخوانم»، نه «گفتگویی نبوده است»."
            ),
        }


class ChatIdentityMissing(RuntimeError):
    """No centre code or no staff code — the API cannot be called without both."""

    code = "CHAT_IDENTITY_MISSING"

    def __init__(self, message: str) -> None:
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "message_fa": (
                "کد مرکز (InoCode) یا کد کاربر (InoUserCode) در تنظیمات محلی ثبت نشده "
                "است؛ بدون این دو، سامانهٔ گفتگو قابل فراخوانی نیست."
            ),
        }


@dataclass
class ChatIdentity:
    """Who we are to the central system.

    `centre` is the clinic's `InoCode` (the LIC the chat pages use) and `staff`
    is an `InoUserCode` from the local `AdminUsers` collection — that field is
    the only join between a local staff row and a central chat participant.
    """

    centre: str
    staff: str
    staff_pool: list[str] = field(default_factory=list)


def identity_from_local() -> ChatIdentity:
    """Read the centre and staff codes from the reception box's own database."""
    from .local.mongo import reception_db

    db = reception_db()
    centre = ""
    for collection in ("settings", "setting"):
        try:
            doc = db[collection].find_one({}, {"InoCode": 1})
        except Exception:  # noqa: BLE001 - a missing collection is not an error here
            doc = None
        if doc and doc.get("InoCode"):
            centre = str(doc["InoCode"])
            break

    staff_pool = [
        str(row["InoUserCode"])
        for row in db["AdminUsers"].find(
            {"InoUserCode": {"$exists": True, "$nin": ["", None]}}, {"InoUserCode": 1}
        )
        if row.get("InoUserCode")
    ]

    if not centre or not staff_pool:
        raise ChatIdentityMissing(
            "conversation identity incomplete: "
            f"InoCode={'set' if centre else 'missing'}, "
            f"AdminUsers with InoUserCode={len(staff_pool)}"
        )
    return ChatIdentity(centre=centre, staff=staff_pool[0], staff_pool=staff_pool)


def _post(path: str, body: dict[str, Any], *, timeout: int = 30) -> Any:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("Accept", "application/json")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise ChatUnavailable(
            f"conversation backend returned HTTP {exc.code} for {path}",
            detail=str(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        # The common one here is DNS. Named explicitly because this box has lost
        # name resolution before and the symptom is indistinguishable from the
        # service being down unless the reason is carried through.
        raise ChatUnavailable(
            f"cannot reach the conversation backend at {BASE_URL}",
            detail=f"{type(exc.reason).__name__}: {exc.reason}",
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise ChatUnavailable(
            f"cannot reach the conversation backend at {BASE_URL}",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise ChatUnavailable(
            "conversation backend replied with something that is not JSON",
            detail=str(exc)[:120],
        ) from exc


def room_list(identity: ChatIdentity) -> dict[str, Any]:
    """The centre's conversations, newest activity first. Capped upstream at 100."""
    data = _post("/ChatRoom/GetData/Admin",
                 {"User2": identity.centre, "MyID": identity.staff})
    if not isinstance(data, dict) or not isinstance(data.get("ChatRooms"), list):
        raise ChatUnavailable(
            "conversation backend answered without a ChatRooms list",
            detail="keys=" + ",".join(sorted(data)[:12]) if isinstance(data, dict) else "not-an-object",
        )
    return data


def room_detail(room_id: str) -> dict[str, Any]:
    """One conversation, with its messages grouped by Jalali date."""
    data = _post("/ChatRoom/GetChatRoomData", {"id": room_id})
    if not isinstance(data, dict):
        raise ChatUnavailable("conversation detail was not an object")
    room = data.get("ChatRooms")
    return room if isinstance(room, dict) else {}


def _minutes(hhmmss: Any) -> int | None:
    """"HH:MM:SS" -> minutes since midnight. None if it is not that shape."""
    parts = str(hhmmss or "").split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def summary(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    room_budget: int = DEFAULT_ROOM_BUDGET,
) -> dict[str, Any]:
    """What happened in the patient conversations over a Jalali date range.

    Counts and timings only — never a message body, a name or a phone number.
    """
    start = normalize_jalali_date(date_from or "today")
    end = normalize_jalali_date(date_to or date_from or "today")
    if end < start:
        start, end = end, start
    budget = max(1, min(int(room_budget or DEFAULT_ROOM_BUDGET), UPSTREAM_ROOM_CEILING))

    identity = identity_from_local()
    listing = room_list(identity)
    rooms = listing.get("ChatRooms") or []
    status_names = {
        str(key): (value or {}).get("Name")
        for key, value in (listing.get("ChatStatus") or {}).items()
        if isinstance(value, dict)
    }

    active_rooms = 0
    new_rooms = 0
    messages = 0
    from_patient = 0
    from_centre = 0
    awaiting_reply = 0
    by_status: dict[str, int] = {}
    by_department: dict[str, int] = {}
    by_hour: dict[str, int] = {}
    reply_gaps: list[int] = []
    inspected = 0
    stopped_early = False
    budget_exhausted = False

    for room in rooms:
        if inspected >= budget:
            # Ran out of budget with conversations still unopened. Recorded, not
            # shrugged off: this is the difference between "no more to find" and
            # "stopped looking".
            budget_exhausted = True
            break
        room_id = room.get("_id")
        if not room_id:
            continue
        inspected += 1
        detail = room_detail(str(room_id))
        days = detail.get("ChatsDate") or []
        dated = [d for d in days if isinstance(d, dict) and d.get("Date")]
        if not dated:
            continue

        newest = max(str(d["Date"]) for d in dated)
        if newest < start:
            # The listing is ordered by last activity, so everything after this
            # room is older still. Stated as a stop REASON in the payload rather
            # than silently shortening the walk.
            stopped_early = True
            break

        in_window = [d for d in dated if start <= str(d["Date"]) <= end]
        if not in_window:
            continue

        active_rooms += 1
        oldest = min(str(d["Date"]) for d in dated)
        if oldest >= start:
            new_rooms += 1

        status = str(room.get("ChatStatus"))
        by_status[status_names.get(status) or UNKNOWN_STATUS_FA] = (
            by_status.get(status_names.get(status) or UNKNOWN_STATUS_FA, 0) + 1
        )
        department = str(room.get("DepName") or "—")
        by_department[department] = by_department.get(department, 0) + 1

        patient_side = room.get("User1")
        last_inbound_at: int | None = None
        last_was_inbound = False

        for day in sorted(in_window, key=lambda d: str(d["Date"])):
            for chat in day.get("Chats") or []:
                if not isinstance(chat, dict):
                    continue
                messages += 1
                at = _minutes(chat.get("Time"))
                if at is not None:
                    hour = "%02d" % (at // 60)
                    by_hour[hour] = by_hour.get(hour, 0) + 1
                inbound = chat.get("Sender") == patient_side
                if inbound:
                    from_patient += 1
                    last_was_inbound = True
                    if last_inbound_at is None and at is not None:
                        last_inbound_at = at
                else:
                    from_centre += 1
                    last_was_inbound = False
                    if last_inbound_at is not None and at is not None and at >= last_inbound_at:
                        reply_gaps.append(at - last_inbound_at)
                    last_inbound_at = None

        if last_was_inbound:
            awaiting_reply += 1

    reply_gaps.sort()
    median_gap = reply_gaps[len(reply_gaps) // 2] if reply_gaps else None

    return {
        "skill": "conversation.summary",
        "source": {
            "system": "IranNoobat central chat backend",
            "base_url": BASE_URL,
            "endpoints": ["/ChatRoom/GetData/Admin", "/ChatRoom/GetChatRoomData"],
            "note": (
                "Patient conversations are NOT stored on the reception server. The "
                "local `chatrooms` collection is the internal staff messenger and is "
                "not this."
            ),
        },
        "period": {"from": start, "to": end},
        "totals": {
            "conversationsActive": active_rooms,
            "conversationsStarted": new_rooms,
            "messages": messages,
            "fromPatient": from_patient,
            "fromCentre": from_centre,
            "awaitingCentreReply": awaiting_reply,
        },
        "byStatus": by_status,
        "byDepartment": by_department,
        "byHour": dict(sorted(by_hour.items())),
        "responsiveness": {
            "measuredReplies": len(reply_gaps),
            "medianMinutes": median_gap,
            "slowestMinutes": reply_gaps[-1] if reply_gaps else None,
            "note": (
                "Minutes from a patient message to the centre's next message in the "
                "same conversation, within the period. Same-day only: the message "
                "timestamps carry no date of their own."
            ),
        },
        "coverage": {
            "conversationsOnServer": len(rooms),
            "upstreamListCeiling": UPSTREAM_ROOM_CEILING,
            "ceilingReached": len(rooms) >= UPSTREAM_ROOM_CEILING,
            "conversationsInspected": inspected,
            "stoppedAtFirstOlderConversation": stopped_early,
            "budgetExhausted": budget_exhausted,
            "note": (
                "The central API returns at most 100 conversations, newest activity "
                "first, and offers no paging — Page/Skip/Limit were all tried and all "
                "return the same 100. If ceilingReached is true, conversations whose "
                "last activity is older than the 100th are invisible to this tool, so "
                "a figure for an OLD date may be incomplete."
            ),
        },
        # Complete means one of exactly two things happened: the walk reached a
        # conversation older than the window (so every later one is older still
        # and nothing in the window was missed), or it opened every conversation
        # the server offered. Running out of budget is NEITHER.
        #
        # The first version of this line was `len(rooms) < CEILING or not
        # stopped_early`, which returned True precisely when the budget ran out —
        # and the answer told the owner «آمار امروز کامل گزارش شده است» over an
        # inspection that had stopped at 60 of 100. A completeness flag that is
        # wrong in the optimistic direction is worse than having none.
        "figuresAreComplete": bool(stopped_early or inspected >= len(rooms)),
        "incompleteReason_fa": (
            None if (stopped_early or inspected >= len(rooms)) else
            "بررسی پس از {n} گفت‌وگو به سقف تعیین‌شده رسید و همهٔ گفت‌وگوهای سرور باز "
            "نشدند؛ بنابراین ممکن است گفت‌وگوهای فعال دیگری شمرده نشده باشند. "
            "این ارقام «حداقل» هستند، نه «کل».".format(n=inspected)
        ),
        "privacy": "counts, statuses and timings only; no message text, names or phone numbers",
    }
