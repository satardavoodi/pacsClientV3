from __future__ import annotations

from dataclasses import replace

from .aliases import normalise_arguments
from .guards import audit_dispatch, run_pre_dispatch_guards
from .normalize import normalize_error, normalize_success
from .registry import ToolRegistry, default_registry
from .types import DispatchContext, ToolCall, ToolResult


def dispatch(
    call: ToolCall,
    registry: ToolRegistry | None = None,
    context: DispatchContext | None = None,
) -> ToolResult:
    """The one entrypoint. Every client, every tool, every time.

    Order is not negotiable: registry → validation + identity + permissions →
    execute → normalize → audit. Audit is not skippable by any code path; if the
    audit write fails, the call fails.
    """
    registry = registry or default_registry()
    context = context or DispatchContext()
    try:
        definition = registry.get(call.name)
        # ⚠️ BEFORE the guards, because validation is one of them and it now
        # REFUSES an undeclared input rather than dropping it. A caller that
        # wrote `start_date` where this tool says `dateFrom` meant the same
        # thing, and should get its answer rather than an error it has to be
        # told how to fix. Everything the alias table does not recognise still
        # reaches the refusal.
        call = replace(call, arguments=normalise_arguments(
            definition.input_schema, call.arguments))
        permission = run_pre_dispatch_guards(definition, call, context)
        data = definition.handler(call.arguments)
        audit_id = audit_dispatch("tool_call", definition, call, context, "ok", permission=permission)
        return normalize_success(call.name, data, audit_id=audit_id)
    except Exception as exc:
        audit_id = None
        try:
            definition = registry.get(call.name)
            error_result = normalize_error(call.name, exc)
            audit_id = audit_dispatch(
                "tool_call", definition, call, context, "error", error=error_result.error
            )
        except Exception:
            pass
        return normalize_error(call.name, exc, audit_id=audit_id)
