# Legacy exports (preserved verbatim — every existing caller continues to work)
from .contracts import (
    AgentRouteRequest,
    AgentRouteResponse,
    ModuleActionPlan,
    SecretaryActionPlan,
    SecretaryCommand,
    SecretaryResult,
)
from .orchestrator import SecretaryOrchestrator
from .prompt_context import build_prompt_context
from .repair_loop import build_repair_prompt, retry_plan_with_llm
from .validator import ValidationError, validate_plan

# Unified Command Layer (2026-05-27 — phase 1/3/4). See
# docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md
from .bus_factory import build_command_bus
from .command_bus import CommandBus
from .command_envelope import (
    CommandPlan,
    CommandRequest,
    CommandResult,
    SourceScope,
    SttRoute,
)
from .registry import AdapterRegistry

__all__ = [
    # ── legacy ──────────────────────────────────────────────────────
    "AgentRouteRequest",
    "AgentRouteResponse",
    "ModuleActionPlan",
    "SecretaryActionPlan",
    "SecretaryCommand",
    "SecretaryResult",
    "SecretaryOrchestrator",
    "build_prompt_context",
    "build_repair_prompt",
    "retry_plan_with_llm",
    "ValidationError",
    "validate_plan",
    # ── unified command layer ───────────────────────────────────────
    "CommandBus",
    "build_command_bus",
    "CommandPlan",
    "CommandRequest",
    "CommandResult",
    "AdapterRegistry",
    "SourceScope",
    "SttRoute",
]
