from __future__ import annotations

import hashlib
import json
from typing import Any

from ..audit import PHI_KEYS, AuditLogger, new_audit_id
from ..config import DEFAULT_DATA_ROOT
from ..permissions import PermissionDecision, load_permissions
from .errors import ToolPermissionError, ToolValidationError
from .types import DispatchContext, ToolCall, ToolDefinition
from .validation import validate_input

# Identity is never an argument (docs/security-model.md §2). A caller that sends
# these keys is rejected — dropping them silently would let it believe they took
# effect.
FORBIDDEN_INPUT_KEYS = {"user", "center", "roles", "token", "password"}


def run_pre_dispatch_guards(definition: ToolDefinition, call: ToolCall, context: DispatchContext) -> PermissionDecision:
    validate_context(definition, context)
    reject_identity_inputs(call)
    validate_input(definition.input_schema, call.arguments)

    decision = load_permissions().check(
        context.principal.user,
        context.principal.center,
        definition.name,
        definition.permission_action,
        definition.safety,
    )
    if not decision.allowed:
        raise ToolPermissionError(decision.reason)
    return decision


def validate_context(definition: ToolDefinition, context: DispatchContext) -> None:
    if definition.safety != "read" and not context.principal.user:
        raise ToolValidationError("Principal is required for non-read tools")


def reject_identity_inputs(call: ToolCall) -> None:
    smuggled = FORBIDDEN_INPUT_KEYS.intersection(call.arguments)
    if smuggled:
        raise ToolValidationError(
            "identity comes from the session, not from tool inputs; "
            f"remove: {', '.join(sorted(smuggled))}"
        )


def audit_dispatch(
    event_type: str,
    definition: ToolDefinition,
    call: ToolCall,
    context: DispatchContext,
    status: str,
    permission: PermissionDecision | None = None,
    error: dict | None = None,
) -> str | None:
    """Write one audit record and return its id.

    The inputs are HASHED, not stored: the audit proves what happened without
    becoming a second PHI store (docs/security-model.md §6). Which PHI fields
    were present is recorded — the values are not.
    """
    if not context.audit or not definition.audit:
        return None

    audit_id = new_audit_id()
    data_root = context.data_root or DEFAULT_DATA_ROOT
    AuditLogger(data_root).write(
        event_type,
        {
            "request_id": call.request_id,
            "client": context.client,
            "tool": definition.name,
            "kind": definition.kind,
            "safety": definition.safety,
            "permission_action": definition.permission_action,
            "principal": {
                "user": context.principal.user,
                "center": context.principal.center,
                "roles": context.principal.roles,
            },
            "inputs_hash": inputs_hash(call.arguments),
            "phi_fields_present": phi_fields_present(call.arguments),
            "idempotency_key": call.idempotency_key,
            "status": status,
            "permission": permission.as_dict() if permission else None,
            "error": error,
        },
        audit_id=audit_id,
    )
    return audit_id


def inputs_hash(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def phi_fields_present(value: Any, found: set[str] | None = None) -> list[str]:
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in PHI_KEYS and child not in (None, "", [], {}):
                found.add(key)
            phi_fields_present(child, found)
    elif isinstance(value, list):
        for item in value:
            phi_fields_present(item, found)
    return sorted(found)
