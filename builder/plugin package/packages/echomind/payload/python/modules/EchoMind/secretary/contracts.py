from __future__ import annotations

from typing import Any, Literal, TypedDict


# ── Legacy action names (secretary executor) ──────────────────────────────────
ActionName = Literal["list_patients", "open_patient", "download_patient"]

# ── Extended action names (agent brain — all modules) ─────────────────────────
BrainActionName = Literal[
    # homepage
    "list_patients",
    # patient_viewer
    "open_patient",
    # download
    "download_patient",
    "check_download_status",
    # mpr_zeta
    "open_mpr",
    "apply_preset",
    "measure",
    # advanced_analysis
    "run_analysis",
    "export_report",
    # printing
    "print_series",
    "export_pdf",
    # echomind
    "ai_chat",
    "generate_summary",
    "generate_report",
    # eagle_ai
    "toggle_eagle",
    "show_findings",
    "explain_finding",
]

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


# ── Agent brain contracts ─────────────────────────────────────────────────────

class AgentRouteRequest(TypedDict):
    """Input for Phase 1 (router): what the orchestrator sends to the LLM."""
    user_text: str
    language: str
    catalog_text: str             # Document 1 contents


class AgentRouteResponse(TypedDict):
    """Output of Phase 1 (router): which module docs to fetch next."""
    modules: list[str]            # ordered list of module_ids
    reason: str                   # LLM's one-sentence explanation


class ModuleActionPlan(TypedDict):
    """
    Output of Phase 2 (agent).  Superset of SecretaryActionPlan that allows
    any BrainActionName (not just the three legacy actions).
    """
    action: str                   # BrainActionName value
    entities: dict[str, Any]
    confidence: float
    needs_confirmation: bool
    reason: str
    # Optional: which module produced this plan (added by AgentBrain)
    source_module: str | None

