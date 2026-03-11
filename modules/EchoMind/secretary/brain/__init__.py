"""
EchoMind Secretary  —  brain/

The brain package implements the two-phase LLM agent pipeline:

  Phase 1  (router.py)
    Input:   user_text + catalog.yaml (Document 1)
    LLM job: decide which module_ids are needed and in what order
    Output:  RouteDecision(modules=[...])

  Phase 2  (agent.py)
    Input:   user_text + concatenated per-module docs (Document 2s)
    LLM job: produce an executable JSON action plan
    Output:  ModuleActionPlan (validated TypedDict)

Public API
----------
  from .brain import AgentBrain, RouteDecision, ModuleActionPlan
"""

from .agent import AgentBrain
from .router import RouteDecision

__all__ = ["AgentBrain", "RouteDecision"]
