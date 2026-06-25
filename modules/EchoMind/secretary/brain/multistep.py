"""Multi-step Phase-2 plan handling for the brain (2026-06-23, pure).

The brain (LLM, Phase 2) may emit EITHER a single-action plan (legacy) OR a
multi-action plan ``{"goal": ..., "steps": [<single plan>, ...]}`` for a
genuinely sequential request like *"download this patient and open it"*. This
module normalizes that output and turns a multi-step plan into an executable
:class:`~modules.EchoMind.secretary.workflow.WorkflowPlan`.

Pure (stdlib + the pure ``workflow`` module). The orchestrator decides whether
to ACT on a ``__workflow__`` plan (flag-gated); this module only parses/builds.
"""
from __future__ import annotations

from typing import Any, Optional

from ..workflow import WorkflowPlan, build_plan

#: Sentinel action name the brain uses to signal "this is a multi-step plan".
#: The orchestrator detects it and runs the workflow engine; the legacy
#: single-action path never sees it.
WORKFLOW_ACTION = "__workflow__"


def extract_steps(obj: Any) -> Optional[list]:
    """Return the list of single-action step dicts if ``obj`` is a multi-step
    plan, else ``None``. Accepts ``{"steps": [...]}`` or a bare ``[...]`` array."""
    if isinstance(obj, list):
        raw = obj
    elif isinstance(obj, dict):
        raw = obj.get("steps")
        if not isinstance(raw, list):
            return None
    else:
        return None
    steps = [s for s in raw if isinstance(s, dict) and (s.get("action") or s.get("tool"))]
    return steps or None


def is_multi(obj: Any) -> bool:
    """True when ``obj`` carries two or more sequential action steps."""
    steps = extract_steps(obj)
    return bool(steps) and len(steps) >= 2


def to_brain_plan(obj: Any) -> Any:
    """Normalize an LLM Phase-2 object into a brain plan.

    ≥2 steps → a ``__workflow__`` plan carrying the steps (with an aggregate
    ``needs_confirmation`` = any step needs it, and ``confidence`` = the min step
    confidence). Otherwise the object is returned UNCHANGED (single-action legacy
    plan), so the single path is byte-identical.
    """
    steps = extract_steps(obj)
    if not steps or len(steps) < 2:
        return obj
    goal = ""
    if isinstance(obj, dict):
        goal = str(obj.get("goal") or obj.get("reason") or "").strip()
    needs = any(bool(s.get("needs_confirmation")) for s in steps)
    confs = [float(s.get("confidence", 1.0)) for s in steps]
    return {
        "action": WORKFLOW_ACTION,
        "goal": goal or "multi-step task",
        "steps": steps,
        "confidence": min(confs) if confs else 1.0,
        "needs_confirmation": needs,
        "reason": goal or "multi-step task",
    }


def to_workflow_plan(brain_plan: dict) -> WorkflowPlan:
    """Build the executable WorkflowPlan from a ``__workflow__`` brain plan,
    attaching the default verify/capture per action (see ``workflow.build_plan``)."""
    steps = brain_plan.get("steps") if isinstance(brain_plan, dict) else None
    goal = str((brain_plan or {}).get("goal") or "workflow")
    return build_plan(goal, steps or [])


__all__ = [
    "WORKFLOW_ACTION", "extract_steps", "is_multi", "to_brain_plan", "to_workflow_plan",
]
