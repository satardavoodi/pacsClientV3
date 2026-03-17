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
