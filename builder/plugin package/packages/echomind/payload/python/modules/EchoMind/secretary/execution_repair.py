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
    "EXECUTION_IN_PROGRESS", "POLICY_UNAVAILABLE", "PERMISSION_DENIED",
    "INVALID_LIST_CONTEXT", "SEARCH_FAILED",
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
    runtime_capabilities: dict | None = None,
) -> SecretaryActionPlan | None:
    """
    Ask the LLM to produce a corrected plan based on the execution error.

    Returns a validated plan dict, or None if the LLM could not produce one.
    """
    error_code = str(execution_result.get("error_code") or "UNKNOWN")
    error_message = str(execution_result.get("message") or "Unknown error")

    from . import remote_planner
    if remote_planner.uses_server():
        try:
            fields = {'runtime_capabilities':runtime_capabilities} if runtime_capabilities is not None else {}
            return remote_planner.request('repair', user_text, language=language, invalid_plan=failed_plan,
                execution_error={'code':error_code,'message':error_message},
                attempt=attempt, max_attempts=max_attempts, **fields)['plan']
        except remote_planner.RemotePlanningError:
            return None
    own_prompt = remote_planner.personal_prompt('secretary_action')

    _ts = datetime.now().strftime("%H:%M:%S")
    sys.stderr.write(
        f"\n[EchoMind | Repair  ] {_ts} — execution repair (attempt {attempt}/{max_attempts})\n"
        f"  error_code : {error_code}\n"
        f"  error_chars: {len(error_message)}\n"
    )
    sys.stderr.flush()

    prompt = json.dumps({'text':user_text,'language':language,
        'invalid_plan':failed_plan,'execution_error':{'code':error_code,'message':error_message},
        'attempt':attempt,'max_attempts':max_attempts}, ensure_ascii=False)

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
    )
    sys.stderr.flush()
    return normalized


def is_repairable(result: SecretaryResult) -> bool:
    """Return True when an execution result is worth sending to the repair LLM."""
    if result.get("ok"):
        return False
    code = result.get("error_code") or ""
    return code not in _TERMINAL_CODES and code not in _PENDING_CODES
