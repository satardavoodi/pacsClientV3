"""
EchoMind/secretary/config.py
-----------------------------
Secretary-specific LLM and pipeline configuration.

ALL LLM-related settings for the EchoMind Secretary module live here.
Change values here to affect the whole secretary pipeline — no need to
touch router.py, agent.py, or brain/ internals.

The shared transport layer (API URL, auth key resolution, usage logging)
comes from EchoMind.llm_client and is NOT duplicated here.
"""

from __future__ import annotations

from pathlib import Path

# ── LLM model ─────────────────────────────────────────────────────────────────
# One place to change the model for every pipeline phase of the secretary.
SECRETARY_LLM_MODEL = "gpt-5.2"

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
