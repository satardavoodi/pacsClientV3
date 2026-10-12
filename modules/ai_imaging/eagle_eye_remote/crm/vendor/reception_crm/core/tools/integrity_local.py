"""Data-quality checks between reception records, reports and files.

Three questions the vendor's API cannot answer, all of which became possible
only because the agent runs on the reception server:

* which studies are old enough to have been reported, and have not been;
* which attachment rows point at a file that is no longer on disk;
* which reports were edited after a physician approved them.

Reads only, like everything in ``reception_crm.local``.
"""

from __future__ import annotations

from typing import Any

from ...local import integrity
from ...local.mongo import LocalMongoUnavailable, ScanBusy
from ..registry import ToolRegistry
from ..types import ToolDefinition


def register_integrity_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="integrity.missing-reports",
            kind="skill",
            handler=_missing,
            description=(
                "Studies with no report body that are older than a given number of days — "
                "the reporting backlog. Optionally narrow by Jalali date range and modality. "
                "Use for 'what hasn't been reported yet' questions."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "olderThanDays": {"type": "integer"},
                    "dateFrom": {"type": "string"},
                    "dateTo": {"type": "string"},
                    "modality": {"type": "string"},
                    "limit": {"type": "integer"},
                    "includeNotYetPerformed": {
                        "type": "boolean",
                        "description": (
                            "Also count bookings still waiting for an appointment. Off by "
                            "default: those patients have not attended, so there is nothing "
                            "to report and they are not a backlog."
                        ),
                    },
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="integrity.broken-files",
            kind="skill",
            handler=_broken,
            description=(
                "Attachment records whose file is missing from disk — broken links between "
                "the database and stored images. Use for storage-health questions."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "limit": {"type": "integer"},
                    "scan": {"type": "integer"},
                    "includeDeleted": {
                        "type": "boolean",
                        "description": (
                            "Also include rows the reception system marked deleted. Off by "
                            "default: their file is supposed to be gone, so they are "
                            "deliberate cleanup rather than a broken link."
                        ),
                    },
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="integrity.post-approval-edits",
            kind="skill",
            handler=_edits,
            description=(
                "Reports whose text was changed after a physician approved them, so the "
                "approved version and the current version differ. Use for audit and "
                "report-governance questions."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "limit": {"type": "integer"},
                    "scan": {"type": "integer"},
                    "graceMinutes": {
                        "type": "integer",
                        "description": (
                            "Ignore edits landing within this many minutes of the approval — "
                            "those are usually the same editing session finishing rather than "
                            "a revision of a signed document. Default 0 (report everything)."
                        ),
                    },
                },
            },
        )
    )


def _guard(fn, /, **kwargs) -> dict[str, Any]:
    try:
        return fn(**kwargs)
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
            "hint": (
                "Integrity checks read the reception database and filesystem directly, and "
                "only work when the agent is installed on the reception server."
            ),
        }


_FALSE_WORDS = {"", "0", "false", "no", "off", "none", "null"}


def _flag(value: Any) -> bool:
    """Truthiness for a value that may have come through an LLM as text.

    ``"false"`` is a non-empty string and therefore true to Python, which would
    silently turn a caller's explicit *off* into *on* — for these two flags that
    means re-admitting exactly the rows the defaults exist to keep out.
    """
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def _missing(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill": "integrity.missing-reports",
        **_guard(
            integrity.missing_reports,
            older_than_days=args.get("olderThanDays", 7),
            date_from=args.get("dateFrom"),
            date_to=args.get("dateTo"),
            modality=args.get("modality"),
            include_not_yet_performed=_flag(args.get("includeNotYetPerformed")),
            limit=args.get("limit", integrity.DEFAULT_LIMIT),
        ),
    }


def _broken(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill": "integrity.broken-files",
        **_guard(
            integrity.broken_file_links,
            limit=args.get("limit", integrity.DEFAULT_LIMIT),
            scan=args.get("scan", 1500),
            include_deleted=_flag(args.get("includeDeleted")),
        ),
    }


def _edits(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill": "integrity.post-approval-edits",
        **_guard(
            integrity.post_approval_edits,
            limit=args.get("limit", integrity.DEFAULT_LIMIT),
            scan=args.get("scan", 400),
            grace_minutes=args.get("graceMinutes", 0),
        ),
    }
