from __future__ import annotations

import logging
from typing import Any

# Dedicated logger for the CommandBus / MCP / Test-Control-Server dispatch path.
# Before the P0 safety layer (2026-06-23) this path had NO in-app audit trail —
# only the voice orchestrator logged (log_start/log_end below, DB-routed). This
# logger gives every bus dispatch a structured line in user_data/logs/.
_bus_audit_logger = logging.getLogger("aipacs.agent_control.audit")


def record_bus_action(
    *,
    action: str | None,
    side_effect: str | None = None,
    mode: str | None = None,
    status: str,
    adapter: str | None = None,
    confirmation_required: bool = False,
    elapsed_ms: float | None = None,
) -> None:
    """Best-effort, never-raising audit of a single CommandBus dispatch.

    Emits one structured log line. Persistent DB audit stays the voice path's
    job (``log_start``/``log_end``); this is the lightweight in-app trail for
    the agent-control (bus / MCP / test-server) path. ``status`` is one of
    ``ok | fail | denied | confirm_required | error``.
    """
    try:
        _bus_audit_logger.info(
            "agent_action action=%s side_effect=%s mode=%s status=%s "
            "adapter=%s confirm=%s elapsed_ms=%s",
            action, side_effect, mode, status, adapter, confirmation_required,
            (round(elapsed_ms, 1) if isinstance(elapsed_ms, (int, float)) else elapsed_ms),
        )
    except Exception:
        # Audit must never affect dispatch.
        pass


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

