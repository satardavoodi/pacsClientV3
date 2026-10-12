from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import AuditLogger
from .config import DEFAULT_DATA_ROOT
from .operations import OperationRegistry, load_operations
from .permissions import PermissionPolicy, load_permissions


CONFIRM_PREFIX = "EXECUTE"


def execute_operation(
    operation_name: str,
    inputs: dict[str, Any],
    user: str | None,
    center: str | None,
    confirmation: str | None,
    execute: bool = False,
    registry: OperationRegistry | None = None,
    permissions: PermissionPolicy | None = None,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> dict[str, Any]:
    registry = registry or load_operations()
    permissions = permissions or load_permissions()
    audit = AuditLogger(data_root)
    plan = registry.plan(operation_name, inputs)
    permission = permissions.check(user, center, operation_name, "execute", plan.safety)
    expected_confirmation = f"{CONFIRM_PREFIX} {operation_name}"

    checks = {
        # This adapter accepts identity and confirmation as ordinary caller
        # strings, so it cannot establish either fact. The authenticated core
        # confirmation flow supersedes it and is the only write-capable path.
        "legacy_execution_path_active": False,
        "operation_enabled": plan.enabled,
        "no_missing_inputs": not plan.missing_required_inputs,
        "permission_allowed": permission.allowed,
        "confirmation_matches": confirmation == expected_confirmation,
        "global_write_enabled": os.getenv("RECEPTION_ENABLE_WRITES") == "true",
        "destructive_allowed": plan.safety != "destructive" or os.getenv("RECEPTION_ALLOW_DESTRUCTIVE") == "true",
        "execute_requested": execute,
    }
    allowed = all(checks.values())
    response: dict[str, Any] = {
        "operation": operation_name,
        "user": user,
        "center": center,
        "status": "executed" if allowed else "blocked",
        "checks": checks,
        "permission": permission.as_dict(),
        "expected_confirmation": expected_confirmation,
        "plan": plan.as_dict(),
    }

    response["message"] = (
        "Legacy execution is retired and cannot write to CRM. Use the authenticated "
        "core plan-and-confirm flow; this record is dry-run/audit only."
    )

    audit_path = audit.write("write_execution_attempt", response)
    response["audit_path"] = str(audit_path)
    return response


def api_path_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.path:
        raise ValueError(f"Cannot derive API path from URL: {url}")
    return parsed.path
