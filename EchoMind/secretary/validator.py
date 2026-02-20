from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from .contracts import SecretaryActionPlan
from .errors import (
    ERR_INVALID_ACTION,
    ERR_INVALID_ENTITY,
    ERR_INVALID_TYPE,
    ERR_INVALID_VALUE,
    ERR_MISSING_FIELD,
    ERR_UNSUPPORTED_ENTITY,
)

_ALLOWED_ACTIONS = {"list_patients", "open_patient", "download_patient"}
_ALLOWED_SOURCES = {"active_tab", "local", "server"}

_ALLOWED_ENTITY_KEYS_BY_ACTION: dict[str, set[str]] = {
    "list_patients": {"source", "date", "modality"},
    "open_patient": {"source", "patient_code", "resolved_patient"},
    "download_patient": {
        "source",
        "patient_code",
        "use_context_patient",
        "resolved_patient",
    },
}

_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_COMPACT_RE = re.compile(r"^\d{8}$")
_DATE_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{8})\.\.(\d{4}-\d{2}-\d{2}|\d{8})$")


@dataclass(frozen=True)
class ValidationError:
    code: str
    field: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, str]:
        out = {
            "code": self.code,
            "field": self.field,
            "message": self.message,
        }
        if self.hint:
            out["hint"] = self.hint
        return out


def _ensure_date_like(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    if s.lower() in {"today", "yesterday"}:
        return True
    if _DATE_ISO_RE.match(s) or _DATE_COMPACT_RE.match(s):
        return True
    return bool(_DATE_RANGE_RE.match(s))


def validate_plan_shape(plan: Any) -> list[ValidationError]:
    errs: list[ValidationError] = []
    if not isinstance(plan, dict):
        return [
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="plan",
                message="Plan must be a JSON object.",
                hint="Return an object with action/entities/confidence/needs_confirmation/reason.",
            )
        ]

    for field in ("action", "entities", "confidence", "needs_confirmation", "reason"):
        if field not in plan:
            errs.append(
                ValidationError(
                    code=ERR_MISSING_FIELD,
                    field=field,
                    message=f"Missing required field '{field}'.",
                )
            )

    action = plan.get("action")
    if action is not None and not isinstance(action, str):
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="action",
                message="Field 'action' must be a string.",
            )
        )

    entities = plan.get("entities")
    if entities is not None and not isinstance(entities, dict):
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="entities",
                message="Field 'entities' must be an object.",
            )
        )

    confidence = plan.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="confidence",
                message="Field 'confidence' must be a number between 0 and 1.",
            )
        )

    needs_confirmation = plan.get("needs_confirmation")
    if needs_confirmation is not None and not isinstance(needs_confirmation, bool):
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="needs_confirmation",
                message="Field 'needs_confirmation' must be boolean.",
            )
        )

    reason = plan.get("reason")
    if reason is not None and not isinstance(reason, str):
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="reason",
                message="Field 'reason' must be a string.",
            )
        )

    return errs


def validate_plan_semantics(plan: SecretaryActionPlan) -> list[ValidationError]:
    errs: list[ValidationError] = []

    action = str(plan.get("action") or "").strip()
    if action not in _ALLOWED_ACTIONS:
        errs.append(
            ValidationError(
                code=ERR_INVALID_ACTION,
                field="action",
                message=f"Unsupported action '{action}'.",
                hint="Allowed: list_patients, open_patient, download_patient",
            )
        )
        return errs

    entities = plan.get("entities") if isinstance(plan.get("entities"), dict) else {}

    # action-specific key whitelist
    allowed_keys = _ALLOWED_ENTITY_KEYS_BY_ACTION.get(action, set())
    for k in entities.keys():
        if k not in allowed_keys:
            errs.append(
                ValidationError(
                    code=ERR_UNSUPPORTED_ENTITY,
                    field=f"entities.{k}",
                    message=f"Entity '{k}' is not supported for action '{action}'.",
                )
            )

    # confidence range
    try:
        c = float(plan.get("confidence", 0.0))
        if c < 0.0 or c > 1.0:
            errs.append(
                ValidationError(
                    code=ERR_INVALID_VALUE,
                    field="confidence",
                    message="confidence must be between 0 and 1.",
                )
            )
    except Exception:
        errs.append(
            ValidationError(
                code=ERR_INVALID_TYPE,
                field="confidence",
                message="confidence must be numeric.",
            )
        )

    # source validation
    if "source" in entities:
        src = str(entities.get("source") or "").strip().lower()
        if src not in _ALLOWED_SOURCES:
            errs.append(
                ValidationError(
                    code=ERR_INVALID_VALUE,
                    field="entities.source",
                    message=f"Invalid source '{src}'.",
                    hint="Use active_tab, local, or server.",
                )
            )

    # date validation
    if "date" in entities:
        date_v = str(entities.get("date") or "").strip()
        if not _ensure_date_like(date_v):
            errs.append(
                ValidationError(
                    code=ERR_INVALID_VALUE,
                    field="entities.date",
                    message="Invalid date format.",
                    hint="Use 'today', yyyy-mm-dd, yyyymmdd, or range with '..'.",
                )
            )

    # modality validation
    if "modality" in entities:
        mod = str(entities.get("modality") or "").strip()
        if not mod:
            errs.append(
                ValidationError(
                    code=ERR_INVALID_VALUE,
                    field="entities.modality",
                    message="modality cannot be empty.",
                )
            )

    # patient_code validation for open action
    if action == "open_patient":
        if not isinstance(entities.get("resolved_patient"), dict):
            code = str(entities.get("patient_code") or "").strip()
            if not code:
                errs.append(
                    ValidationError(
                        code=ERR_MISSING_FIELD,
                        field="entities.patient_code",
                        message="open_patient requires patient_code or resolved_patient.",
                    )
                )

    # confirmation policy
    wants_confirmation = bool(plan.get("needs_confirmation"))
    if action in {"open_patient", "download_patient"} and not wants_confirmation:
        errs.append(
            ValidationError(
                code=ERR_INVALID_VALUE,
                field="needs_confirmation",
                message=f"Action '{action}' must set needs_confirmation=true.",
            )
        )

    return errs


def validate_plan(plan: Any) -> tuple[SecretaryActionPlan | None, list[ValidationError]]:
    shape_errors = validate_plan_shape(plan)
    if shape_errors:
        return None, shape_errors

    normalized: SecretaryActionPlan = copy.deepcopy(plan)

    # normalize action/source
    normalized["action"] = str(normalized.get("action") or "").strip()  # type: ignore[typeddict-item]
    entities = normalized.get("entities") if isinstance(normalized.get("entities"), dict) else {}
    if "source" in entities:
        entities["source"] = str(entities.get("source") or "").strip().lower()
    normalized["entities"] = entities  # type: ignore[typeddict-item]

    semantic_errors = validate_plan_semantics(normalized)
    if semantic_errors:
        return None, semantic_errors

    return normalized, []
