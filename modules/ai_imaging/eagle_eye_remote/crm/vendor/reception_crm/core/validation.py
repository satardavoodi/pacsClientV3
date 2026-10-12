from __future__ import annotations

from typing import Any

from .errors import ToolValidationError


def validate_input(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not schema:
        return

    required = schema.get("required", [])
    missing = [field for field in required if field not in arguments or arguments[field] in (None, "")]
    if missing:
        raise ToolValidationError(f"Missing required input(s): {', '.join(missing)}")

    properties = schema.get("properties", {})

    # ⚠️ AN UNKNOWN INPUT IS REFUSED, NOT IGNORED.
    #
    # This is the same rule `guards.reject_identity_inputs` already applies to
    # `user` and `center`, for the same reason written there: dropping a key
    # silently lets the caller believe it took effect. The benchmark found what
    # that costs on a DATE. `daily-summary` and `cashier-report` took `date` and
    # `days`; the model sent `start_date`/`end_date` — the shape its sibling
    # `reception.search` uses — and those were discarded, `date` fell back to
    # "today", and the report answered confidently about a day nobody had asked
    # about. Three questions in one run, each returning real figures from the
    # wrong day.
    #
    # The message names what IS accepted, because a refusal the caller cannot
    # act on is only a slower failure.
    # A schema that declares no properties says nothing about what it accepts,
    # so there is nothing to check it against. One that declares them is a
    # contract, and a key outside it is a caller error.
    if properties:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            known = ", ".join(sorted(properties))
            raise ToolValidationError(
                f"Unknown input(s): {', '.join(unknown)}. This tool accepts: {known}"
            )

    for field, rules in properties.items():
        if field not in arguments or arguments[field] is None:
            continue
        validate_field(field, arguments[field], rules)


def validate_field(field: str, value: Any, rules: dict[str, Any]) -> None:
    expected_type = rules.get("type")
    if expected_type and not matches_type(value, expected_type):
        raise ToolValidationError(f"{field} must be {expected_type}")

    if "enum" in rules and value not in rules["enum"]:
        raise ToolValidationError(f"{field} must be one of: {', '.join(map(str, rules['enum']))}")


def matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True
