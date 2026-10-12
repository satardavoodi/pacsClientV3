"""The patient-conversation tool.

Registered because the agent had no way to answer a question about the chat and
answered a different question instead — «سامانه گفتگو امروز مرکز را بررسی کن»
came back as the reception day summary, with no hint that the conversation
system had never been consulted. A capability gap that presents as a confident
answer is the worst shape a gap can take.

The description below is the tool-SELECTION prompt. It states plainly that this
is the *patient* chat on the central server and that the local `chatrooms`
collection is a different thing, because that exact confusion produced a wrong
answer once already.
"""

from __future__ import annotations

from typing import Any

from ... import ino_chat
from ...local.mongo import LocalMongoUnavailable
from ..registry import ToolRegistry
from ..types import ToolDefinition


def _summary(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return ino_chat.summary(
            date_from=args.get("dateFrom") or args.get("date"),
            date_to=args.get("dateTo") or args.get("date"),
            room_budget=int(args.get("maxConversations") or ino_chat.DEFAULT_ROOM_BUDGET),
        )
    except (ino_chat.ChatUnavailable, ino_chat.ChatIdentityMissing) as exc:
        # Never an empty summary. "I could not read the conversation system" and
        # "the clinic had no conversations" are different answers and only one of
        # them is true here.
        return {"error": exc.as_dict(), "totals": None}
    except LocalMongoUnavailable as exc:
        return {"error": {"code": exc.code, "message": str(exc)}, "totals": None}


def register_conversation_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="conversation.summary",
            kind="skill",
            handler=_summary,
            description=(
                "The PATIENT conversation system («سامانه گفتگو» / chat) for a Jalali "
                "date or range: how many conversations were active, how many started, "
                "how many messages each way, how many are still waiting for the centre "
                "to reply, a breakdown by conversation status and department, activity "
                "by hour, and reply-time statistics.\n"
                "USE THIS for any question about گفتگو, چت, پیام, پاسخ‌گویی به بیماران, "
                "or online booking conversations. A question about the conversation "
                "system must NEVER be answered from reception or cashier data — that is "
                "a different subject, and answering it from `daily-summary` produced a "
                "confidently wrong report once already.\n"
                "IMPORTANT: these conversations live on the CENTRAL IranNoobat server, "
                "not on this machine. The reception database also has a `chatrooms` "
                "collection — that is the internal staff-to-staff messenger and is NOT "
                "the patient chat; no tool reads it, and it must not be offered as a "
                "substitute.\n"
                "RETURNS `totals` (conversationsActive, conversationsStarted, messages, "
                "fromPatient, fromCentre, awaitingCentreReply), `byStatus`, "
                "`byDepartment`, `byHour`, `responsiveness`, and `coverage`. "
                "Read `figuresAreComplete` before calling a figure a total. When it is "
                "false, `incompleteReason_fa` says why and the counts are a MINIMUM, "
                "not a total — say so in those words rather than presenting them as "
                "the day's figures. The central API returns at most 100 conversations, "
                "newest first, and cannot be paged, so `coverage.ceilingReached: true` "
                "additionally means conversations older than the 100th are invisible.\n"
                "PRIVACY: this returns counts, statuses and timings only. Message text, "
                "patient names and phone numbers are never available through it — if "
                "asked for the content of a conversation, say that the tool reports "
                "activity and not message text."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {
                    "date": {"type": "string",
                             "description": "Jalali YYYY/MM/DD, or today/yesterday."},
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "maxConversations": {
                        "type": "integer",
                        "description": (
                            "How many conversations to open, newest first "
                            f"(default {ino_chat.DEFAULT_ROOM_BUDGET}, upstream ceiling "
                            f"{ino_chat.UPSTREAM_ROOM_CEILING})."
                        ),
                    },
                },
            },
        )
    )
