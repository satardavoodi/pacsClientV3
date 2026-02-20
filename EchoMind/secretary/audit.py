from __future__ import annotations

from typing import Any


def log_start(
    *,
    sid: str | None,
    source_tab: str,
    command_text: str,
    stt_route_requested: str,
    stt_route_used: str,
    intent: str,
    entities: dict[str, Any],
    action: dict[str, Any],
    confirmation_required: bool,
) -> int | None:
    try:
        from PacsClient.utils.database import ai_log_secretary_action_start
    except Exception:
        return None
    try:
        return ai_log_secretary_action_start(
            sid=sid,
            source_tab=source_tab,
            command_text=command_text,
            stt_route_requested=stt_route_requested,
            stt_route_used=stt_route_used,
            intent=intent,
            entities_json=entities,
            action_json=action,
            confirmation_required=confirmation_required,
        )
    except Exception:
        return None


def log_end(
    *,
    action_id: int | None,
    confirmed: bool,
    status: str,
    error_code: str | None,
    error_text: str | None,
    result_count: int,
    latency_ms: int,
) -> None:
    if action_id is None:
        return
    try:
        from PacsClient.utils.database import ai_log_secretary_action_end
    except Exception:
        return
    try:
        ai_log_secretary_action_end(
            action_id=action_id,
            confirmed=confirmed,
            status=status,
            error_code=error_code,
            error_text=error_text,
            result_count=result_count,
            latency_ms=latency_ms,
        )
    except Exception:
        return

