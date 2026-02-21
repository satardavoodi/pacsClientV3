"""
execution_repair.py
-------------------
LLM-assisted repair of execution-level failures.

When the executor returns an error (not CONFIRM_REQUIRED / AMBIGUOUS),
this module sends the original user request + failed plan + error log back
to the LLM and asks for a corrected action plan (up to max_retries times).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from typing import Any

from .contracts import SecretaryActionPlan, SecretaryResult
from .parser_llm import parse_command_llm_from_prompt
from .validator import validate_plan


# Error codes that are terminal (no LLM repair makes sense for them)
_TERMINAL_CODES = {
    "NO_HOME_WIDGET",
    "UNSUPPORTED_ACTION",
    "SELECTION_REQUIRED",
}

# Error codes that mean the action is still pending user input (not failures)
_PENDING_CODES = {"CONFIRM_REQUIRED", "AMBIGUOUS"}


def build_execution_repair_prompt(
    *,
    user_text: str,
    language: str,
    failed_plan: dict[str, Any],
    error_message: str,
    error_code: str,
    attempt: int,
    max_attempts: int,
) -> str:
    from .prompt_context import build_prompt_context

    context = build_prompt_context(language=language)
    return (
        "You are a PACS AI secretary repair agent.\n"
        "A previous action plan FAILED during execution. Fix the plan so it can succeed.\n"
        "Return ONLY a corrected JSON object — no markdown, no prose.\n\n"
        f"Context:\n{context}\n\n"
        f"Original user command:\n{user_text}\n\n"
        f"Failed plan (attempt {attempt}/{max_attempts}):\n"
        f"{json.dumps(failed_plan, ensure_ascii=False, indent=2)}\n\n"
        f"Execution error code : {error_code}\n"
        f"Execution error message: {error_message}\n\n"
        "Instructions:\n"
        "- Correct the plan to avoid the same error.\n"
        "- Keep the intent faithful to the user command.\n"
        "- Return a complete JSON with: action, entities, confidence, needs_confirmation, reason.\n"
        "- Do NOT loop on the same broken plan — change at least one entity or action.\n"
    )


def repair_plan_after_execution_failure(
    *,
    user_text: str,
    language: str,
    failed_plan: dict[str, Any],
    execution_result: SecretaryResult,
    attempt: int,
    max_attempts: int,
) -> SecretaryActionPlan | None:
    """
    Ask the LLM to produce a corrected plan based on the execution error.

    Returns a validated plan dict, or None if the LLM could not produce one.
    """
    error_code = str(execution_result.get("error_code") or "UNKNOWN")
    error_message = str(execution_result.get("message") or "Unknown error")

    _ts = datetime.now().strftime("%H:%M:%S")
    sys.stderr.write(
        f"\n[EchoMind | Repair  ] {_ts} — execution repair (attempt {attempt}/{max_attempts})\n"
        f"  error_code : {error_code}\n"
        f"  error_msg  : {error_message}\n"
    )
    sys.stderr.flush()

    prompt = build_execution_repair_prompt(
        user_text=user_text,
        language=language,
        failed_plan=failed_plan,
        error_message=error_message,
        error_code=error_code,
        attempt=attempt,
        max_attempts=max_attempts,
    )

    try:
        repaired = parse_command_llm_from_prompt(prompt=prompt)
    except Exception as exc:
        sys.stderr.write(f"[EchoMind | Repair  ] LLM call failed: {exc}\n")
        sys.stderr.flush()
        return None

    if not repaired:
        return None

    normalized, errs = validate_plan(repaired)
    if errs:
        sys.stderr.write(
            f"[EchoMind | Repair  ] repaired plan still invalid: "
            f"{[str(e) for e in errs]}\n"
        )
        sys.stderr.flush()
        return None

    _ts2 = datetime.now().strftime("%H:%M:%S")
    sys.stderr.write(
        f"[EchoMind | Repair  ] {_ts2} — repaired plan OK\n"
        f"  action  : {normalized.get('action')}\n"
        f"  entities: {normalized.get('entities')}\n"
    )
    sys.stderr.flush()
    return normalized


def is_repairable(result: SecretaryResult) -> bool:
    """Return True when an execution result is worth sending to the repair LLM."""
    if result.get("ok"):
        return False
    code = result.get("error_code") or ""
    return code not in _TERMINAL_CODES and code not in _PENDING_CODES
