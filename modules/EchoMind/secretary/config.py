"""
EchoMind/secretary/config.py
-----------------------------
Secretary-specific LLM and pipeline configuration.

ALL LLM-related settings for the EchoMind Secretary module live here.
Change values here to affect the whole secretary pipeline — no need to
touch router.py, agent.py, or brain/ internals.

The shared transport layer (API URL, auth key resolution, usage logging)
comes from modules.EchoMind.llm_client and is NOT duplicated here.
"""

from __future__ import annotations

from pathlib import Path

from modules.EchoMind.settings_store import get_llm_backend, get_openai_model_for_feature, get_openai_settings

# ── LLM model ─────────────────────────────────────────────────────────────────
# One place to change the model for every pipeline phase of the secretary.
SECRETARY_LLM_MODEL = "gpt-5.2"


def get_secretary_llm_model() -> str:
    if get_llm_backend() == "openai":
        return get_openai_model_for_feature("secretary", "gpt-5-mini")
    return SECRETARY_LLM_MODEL


def get_secretary_reasoning_effort() -> str | None:
    if get_llm_backend() != "openai":
        return None
    return str(get_openai_settings().get("reasoning_effort") or "").strip() or None

# ── Timeouts (seconds) per pipeline phase ─────────────────────────────────────
SECRETARY_PHASE1_TIMEOUT = 20    # Phase 1 — module routing  (brain/router.py)
SECRETARY_PHASE2_TIMEOUT = 30    # Phase 2 — action planning (brain/agent.py)
SECRETARY_REPAIR_TIMEOUT = 25    # Repair loop              (repair_loop.py)

# ── System-prompt file paths ──────────────────────────────────────────────────
# System prompts are stored as plain-text files inside secretary/prompts/ so
# they can be reviewed and tuned without touching Python source code.
# router.py and agent.py load from these paths at import time.
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

PHASE1_PROMPT_FILE = _PROMPTS_DIR / "router_phase1_prompt.txt"
PHASE2_PROMPT_FILE = _PROMPTS_DIR / "agent_phase2_prompt.txt"

# ── Command-routing v2 (web vs patient search fix, 2026-06-28) ─────────────────
# Default OFF → byte-identical legacy routing. Set AIPACS_SECRETARY_ROUTING_V2=1
# to enable VERB+OBJECT routing so an internet/web/google search goes to the
# web_browser module (web_search) instead of the patient list. The flag is read
# fresh on each call (so it can be toggled at runtime / in tests) and gates four
# layers: the Phase-1 router prompt (file swap below), the Phase-2 planner prompt
# (override prefix in brain/agent.py), the rule-parser web fast-paths
# (parser_rules.py), and the clarify-don't-guess fallback (orchestrator.py).
# Background + rules: docs/agent_control/command_routing_rules.md and
# docs/reports/SECRETARY_ECHOMIND_COMMAND_ROUTING_REVIEW_2026-06-28.md.
PHASE1_PROMPT_FILE_V2 = _PROMPTS_DIR / "router_phase1_prompt_v2.txt"


def routing_v2_enabled() -> bool:
    """True when AIPACS_SECRETARY_ROUTING_V2=1 (verb+object web/patient routing)."""
    import os
    return os.environ.get("AIPACS_SECRETARY_ROUTING_V2", "").strip() == "1"


def get_phase1_prompt_file() -> Path:
    """Phase-1 (router) system-prompt path, honoring the routing-v2 flag.

    Returns the v2 prompt only when the flag is on AND the v2 file exists, so a
    missing v2 file (or the flag off) always falls back to the legacy prompt —
    the legacy default can never break.
    """
    if routing_v2_enabled() and PHASE1_PROMPT_FILE_V2.exists():
        return PHASE1_PROMPT_FILE_V2
    return PHASE1_PROMPT_FILE
