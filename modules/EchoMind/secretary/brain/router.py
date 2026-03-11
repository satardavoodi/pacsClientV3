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

from modules.EchoMind.llm_client import gapgpt_chat, LLMError
from .catalog_loader import list_available_module_ids, load_catalog_text

log = logging.getLogger(__name__)

# ── LLM connection — all calls routed through modules.EchoMind.llm_client ─────────────
# Key is resolved automatically from modules.EchoMind Settings (Settings → EchoMind).
from ..config import SECRETARY_LLM_MODEL as _MODEL, SECRETARY_PHASE1_TIMEOUT, PHASE1_PROMPT_FILE
_TIMEOUT = SECRETARY_PHASE1_TIMEOUT

def _load_phase1_prompt() -> str:
    try:
        return PHASE1_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except Exception as exc:
        log.error("Could not load Phase 1 system prompt: %s", exc)
        return ""


_SYSTEM_PROMPT: str = _load_phase1_prompt()


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
    import sys as _sys
    def _elog(msg: str) -> None:
        try:
            _sys.stderr.write(msg + "\n")
            _sys.stderr.flush()
        except Exception:
            pass
    _elog(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM REQUEST (module routing)")
    _elog(f"  model      : {_MODEL}")
    _elog(f"  user_text  : {user_text!r}")
    _elog(f"  prompt_len : {len(user_message)} chars")

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
        _elog(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM ERROR: {exc}")
        return RouteDecision(modules=[], reason=f"llm_error: {exc}", raw_response="")

    modules, reason = _parse_route_response(raw)
    log.debug("Phase 1 route decision: modules=%s reason=%r", modules, reason)
    _elog(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — Phase 2 LLM RESPONSE")
    _elog(f"  raw        : {raw[:300]}")
    _elog(f"  modules    : {modules}")
    _elog(f"  reason     : {reason}")
    return RouteDecision(modules=modules, reason=reason, raw_response=raw)
