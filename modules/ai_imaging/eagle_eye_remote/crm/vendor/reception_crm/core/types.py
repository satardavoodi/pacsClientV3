from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolCall:
    """One call into the core.

    ``request_id`` traces client → core → CRM. ``idempotency_key`` makes a write
    replay-safe. Note what is NOT here: a username. Identity travels in the
    session, never in the call (docs/security-model.md §2).
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True)
class Principal:
    """Resolved from an authenticated session — never asserted by a caller."""

    user: str | None = None
    center: str | None = None
    roles: list[str] = field(default_factory=list)
    auth_method: str = "unknown"  # "session" | "shared_token" | "os_session"
    session_id: str = ""


@dataclass(frozen=True)
class DispatchContext:
    principal: Principal = field(default_factory=Principal)
    client: str = "unknown"
    data_root: Path | None = None
    audit: bool = True


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    kind: str
    handler: ToolHandler
    description: str = ""
    safety: str = "read"
    permission_action: str = "read"
    input_schema: dict[str, Any] = field(default_factory=dict)
    audit: bool = True
    requires_confirmation: bool = False
    requires_idempotency: bool = False
    # A short Persian sentence describing what executing this tool will do,
    # rendered on the human's confirmation screen. Formatted with the arguments.
    confirmation_summary_fa: str = ""
    effects_fa: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    name: str
    data: Any = None
    error: dict[str, Any] | None = None
    audit_id: str | None = None
    requires_confirmation: bool = False
    confirmation_request: dict[str, Any] | None = None

    def unwrap(self) -> Any:
        if not self.ok:
            message = self.error.get("message") if self.error else "Tool call failed"
            raise RuntimeError(message)
        return self.data
