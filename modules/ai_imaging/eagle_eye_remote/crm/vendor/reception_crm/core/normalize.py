from __future__ import annotations

from typing import Any

from .errors import ReceptionCoreError
from .types import ToolResult


def normalize_success(name: str, data: Any, audit_id: str | None = None) -> ToolResult:
    return ToolResult(ok=True, name=name, data=data, audit_id=audit_id)


def normalize_error(name: str, exc: Exception, audit_id: str | None = None) -> ToolResult:
    code = exc.code if isinstance(exc, ReceptionCoreError) else type(exc).__name__
    return ToolResult(
        ok=False,
        name=name,
        error={"code": code, "message": str(exc)},
        audit_id=audit_id,
    )
