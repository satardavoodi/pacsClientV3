from __future__ import annotations

import json
from typing import Any

from .contracts import SecretaryActionPlan
from .parser_llm import parse_command_llm_from_prompt
from .prompt_context import build_prompt_context
from .validator import ValidationError, validate_plan


def _normalize_validation_errors(
    errors: list[ValidationError] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in errors:
        if isinstance(e, ValidationError):
            out.append(e.to_dict())
        elif isinstance(e, dict):
            out.append(e)
    return out


def build_repair_prompt(
    *,
    user_text: str,
    language: str,
    invalid_plan: dict[str, Any],
    validation_errors: list[dict[str, Any]],
) -> str:
    context = build_prompt_context(language=language)
    return (
        "You are correcting an invalid PACS secretary action JSON.\n"
        "Return only corrected JSON. No markdown. No explanation.\n\n"
        f"Context:\n{context}\n\n"
        f"Original user command:\n{user_text}\n\n"
        f"Invalid plan:\n{json.dumps(invalid_plan, ensure_ascii=False)}\n\n"
        f"Validation errors:\n{json.dumps(validation_errors, ensure_ascii=False)}\n\n"
        "Task:\n"
        "- Fix all validation errors.\n"
        "- Keep intent faithful to the original user command.\n"
        "- Ensure side-effect actions have needs_confirmation=true.\n"
        "- Return a complete object with required fields.\n"
    )


def retry_plan_with_llm(
    *,
    user_text: str,
    language: str,
    invalid_plan: dict[str, Any],
    validation_errors: list[ValidationError] | list[dict[str, Any]],
    max_retries: int = 2,
) -> SecretaryActionPlan | None:
    current_plan = dict(invalid_plan)
    current_errors = _normalize_validation_errors(validation_errors)

    for _ in range(max(0, int(max_retries))):
        prompt = build_repair_prompt(
            user_text=user_text,
            language=language,
            invalid_plan=current_plan,
            validation_errors=current_errors,
        )
        repaired = parse_command_llm_from_prompt(prompt=prompt)
        if not repaired:
            continue

        normalized, errs = validate_plan(repaired)
        if not errs and normalized is not None:
            return normalized

        current_plan = dict(repaired)
        current_errors = [e.to_dict() for e in errs]

    return None
