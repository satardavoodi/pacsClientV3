from __future__ import annotations

from typing import Any, Literal, TypedDict


ActionName = Literal["list_patients", "open_patient", "download_patient"]
SourceScope = Literal["active_tab", "local", "server"]
SttRoute = Literal["native", "v2t"]


class SecretaryCommand(TypedDict):
    text: str
    language: str
    session_id: str | None
    source_scope: SourceScope
    stt_route: SttRoute
    stt_fallback: bool


class SecretaryActionPlan(TypedDict):
    action: ActionName
    entities: dict[str, Any]
    confidence: float
    needs_confirmation: bool
    reason: str


class SecretaryResult(TypedDict):
    ok: bool
    action: str
    message: str
    data: list[dict[str, Any]] | dict[str, Any] | None
    error_code: str | None

