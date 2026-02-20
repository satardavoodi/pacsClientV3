"""
brain/router.py  —  Phase 1 of the two-phase LLM agent pipeline.
-----------------------------------------------------------------
Sends the user's request together with Document 1 (catalog.yaml) to the LLM
and asks it to decide which module(s) are needed to fulfil the request.

The LLM must reply with a JSON object:
    {
        "modules": ["homepage"],          // ordered list of module_ids
        "reason":  "User wants patient list"
    }

Public API
----------
    decision = route_request(user_text, language)
    # decision.modules -> ["homepage"]
    # decision.reason  -> "..."
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from EchoMind.llm_client import gapgpt_chat, LLMError
from .catalog_loader import list_available_module_ids, load_catalog_text

log = logging.getLogger(__name__)

# ── LLM connection — all calls routed through EchoMind.llm_client ─────────────
# Key is resolved automatically from EchoMind Settings (Settings → EchoMind).
_MODEL = "gpt-4.1-mini"
_TIMEOUT = 20

_SYSTEM_PROMPT = """\
You are the Module Router for the AIPacs medical imaging workstation.
Your ONLY job is to read the MODULE CATALOG and the user's request, then
decide which module document(s) should be fetched to fulfil the request.

Rules:
- Reply with JSON only; no prose, no markdown fences.
- The JSON must have exactly two fields:
    "modules": [<module_id>, ...]   // ordered list; max 3 entries
    "reason":  "<one sentence>"
- Use only module_ids that appear in the catalog.
- Order modules by execution dependency: put the provider module before the
  consumer module (e.g. "homepage" before "patient_viewer" when the user
  wants to open a patient from a list).
- If the request is completely unrecognisable, return {"modules": [], "reason": "unknown"}.
"""


@dataclass
class RouteDecision:
    """Result of Phase 1 routing."""
    modules: list[str] = field(default_factory=list)
    reason: str = ""
    raw_response: str = ""

    @property
    def is_empty(self) -> bool:
        return len(self.modules) == 0


def _build_phase1_prompt(user_text: str, language: str, catalog_text: str) -> str:
    """Assemble the user message for Phase 1."""
    available = list_available_module_ids()
    return (
        f"Language hint: {language or 'auto'}\n\n"
        f"Available module_ids: {available}\n\n"
        "=== MODULE CATALOG (Document 1) ===\n"
        f"{catalog_text}\n\n"
        "=== USER REQUEST ===\n"
        f"{user_text}\n\n"
        "Which modules are needed?  Reply with JSON only."
    )


def _parse_route_response(raw: str) -> tuple[list[str], str]:
    """
    Extract (modules, reason) from the LLM response string.
    Handles JSON possibly wrapped in triple-backtick fences.
    """
    text = raw.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()
    try:
        obj: dict[str, Any] = json.loads(text)
        modules: list[str] = obj.get("modules", [])
        reason: str = str(obj.get("reason", ""))
        # Validate that modules is a list of strings
        if not isinstance(modules, list):
            modules = []
        modules = [str(m) for m in modules if m]
        return modules, reason
    except json.JSONDecodeError:
        log.warning("Phase 1: could not parse LLM response as JSON: %r", raw[:200])
        return [], ""


def route_request(
    user_text: str,
    language: str = "auto",
    timeout: float = _TIMEOUT,
) -> RouteDecision:
    """
    Phase 1: ask the LLM which module document(s) are needed.

    Parameters
    ----------
    user_text : str
        The raw text of the user's request.
    language : str
        Language hint ("fa", "en", "auto").
    timeout : float
        HTTP request timeout in seconds.

    Returns
    -------
    RouteDecision
        .modules  — ordered list of module_ids chosen by the LLM
        .reason   — LLM's one-sentence explanation
        .raw_response — raw LLM reply (for debugging)
    """
    catalog_text = load_catalog_text()
    if not catalog_text:
        log.error("Phase 1: catalog.yaml is empty or missing; cannot route.")
        return RouteDecision(modules=[], reason="catalog unavailable")

    user_message = _build_phase1_prompt(user_text, language, catalog_text)

    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
    }

    import datetime as _dt
    print(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM REQUEST (module routing)")
    print(f"  model      : {_MODEL}")
    print(f"  user_text  : {user_text!r}")
    print(f"  prompt_len : {len(user_message)} chars")

    try:
        raw = gapgpt_chat(
            messages=payload["messages"],
            model=_MODEL,
            max_tokens=256,
            temperature=0.0,
            timeout=int(timeout),
        )
    except LLMError as exc:
        log.error("Phase 1 LLM call failed: %s", exc)
        print(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM ERROR: {exc}")
        return RouteDecision(modules=[], reason=f"llm_error: {exc}", raw_response="")

    modules, reason = _parse_route_response(raw)
    log.debug("Phase 1 route decision: modules=%s reason=%r", modules, reason)
    print(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM RESPONSE")
    print(f"  raw        : {raw[:300]}")
    print(f"  modules    : {modules}")
    print(f"  reason     : {reason}")
    return RouteDecision(modules=modules, reason=reason, raw_response=raw)
