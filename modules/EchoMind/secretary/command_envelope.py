"""Typed command envelopes for the unified Command Layer."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

SourceScope = Literal["active_tab", "local", "server"]
SttRoute = Literal["native", "v2t"]


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    text: str = ""
    language: str = "auto"
    session_id: str | None = None
    source_scope: SourceScope = "active_tab"
    stt_route: SttRoute = "native"
    stt_fallback: bool = True
    context: dict[str, Any] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandRequest | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


class CommandPlan(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    needs_confirmation: bool = False
    reason: str = ""
    notes: str = ""
    canonical_text: str = ""

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandPlan | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool
    action: str
    message: str = ""
    # Accepts dict / list / scalar payloads (see test_dispatch_raw_payload_wrapped_as_data).
    data: Any = None
    error_code: str | None = None
    elapsed_ms: float | None = None

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandResult | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


__all__ = ["CommandRequest", "CommandPlan", "CommandResult", "SourceScope", "SttRoute"]
