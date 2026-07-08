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

_ALLOWED_ACTIONS = {
    "list_patients",
    "open_patient",
    "download_patient",
    "set_source_mode",
    "import_dicom",
    "select_patient",
    "change_font_size",
    "sort_patients",
    "select_and_download",
}

# ── CommandBus bridge (2026-06-06) ──────────────────────────────────────────
# Actions executed by routing the plan to the app's CommandBus (bus_factory
# adapters) instead of SecretaryExecutor's own handlers. These were previously
# rejected here with ERR_INVALID_ACTION even though the bus implements them —
# the voice assistant was hard-capped at the home-panel set. Entities for
# these actions are validated leniently (an object with string keys); every
# bus adapter performs its own typed validation and returns a recoverable
# error envelope (e.g. MODULE_NOT_REGISTERED, MISSING_MODULE).
# ``close_patient_tab`` is deliberately ABSENT (destructive; test-server only).
_BUS_ALLOWED_ACTIONS = {
    # modules
    "open_module",
    "list_modules",
    "toggle_eagle",
    "open_mpr",
    "open_printing",
    "open_education",
    # download manager
    "cancel_download",
    "pause_download",
    "resume_download",
    "check_download_status",
    "list_downloads",
    "download_statistics",
    # viewer — read-only
    "get_active_tab",
    "list_open_tabs",
    "get_thumbnails_data",
    "get_active_series",
    "get_multistudy_info",
    "get_series_info",
    # viewer — safe writes (series/tab/slice navigation; nothing destructive)
    "change_series",
    "query_viewport_state",
    "switch_tab",
    "change_layout",
    "scroll_slices",
    # EchoMind reporting workflow (phase 2)
    "start_report",
    "transcribe_voice",
    "generate_report",
    "send_report_to_pacs",
    # Web Browser module (2026-06-11) — Google search / URL / navigation
    "open_browser",
    "web_search",
    "open_url",
    "browser_back",
    "browser_forward",
    "refresh_page",
    # Web Browser structured page tools (2026-06-27) — read / inspect / interact
    "browser_navigate",
    "browser_go_back",
    "browser_go_forward",
    "browser_reload",
    "browser_get_url",
    "browser_get_title",
    "browser_get_text",
    "browser_get_html",
    "browser_dom_summary",
    "browser_dom_snapshot",
    "browser_accessibility_tree",
    "browser_find_element",
    "browser_get_buttons",
    "browser_get_inputs",
    "browser_fill_field",
    "browser_type_text",
    "browser_click",
    "browser_scroll",
    "browser_submit_form",
    "browser_selected_text",
    "browser_selected_element",
    "browser_extract_table",
    "browser_structured_data",
    "browser_get_links",
    "browser_scroll_state",
    "browser_network",
    "browser_clear_network",
    "browser_screenshot",
    # Education module deep navigation (2026-06-11)
    "open_consultation",
    "show_consultant_profiles",
    "open_courses",
    "open_case_of_day",
    "search_education",
    # Background agent workflows (2026-06-11)
    "login_website",
    "search_education_content",
    "agent_task_status",
    "cancel_agent_task",
}
_ALLOWED_SOURCES = {"active_tab", "local", "server"}

# Bus actions that must pass the Secretary confirmation turn ("yes") before
# they execute. ``send_report_to_pacs`` additionally keeps the interactive
# reception dialog inside the app — two human gates for a clinical send.
_BUS_CONFIRM_REQUIRED_ACTIONS = {
    "send_report_to_pacs",
}


def validate_steps(steps: list) -> tuple[list, list]:
    """Validate each step of a multi-step (workflow) plan (2026-06-23).

    Reuses :func:`validate_plan` per step, so steps obey the SAME allowlist,
    entity-key, source and date rules as a single plan. Side-effect steps
    (``open_patient`` / ``download_patient``) are normalized to
    ``needs_confirmation=True`` because a workflow confirms ONCE up front and
    then runs its steps. Returns ``(normalized_steps, errors)``; ``errors`` are
    the same ``ValidationError`` objects ``validate_plan`` produces (so callers
    can ``e.to_dict()`` them).
    """
    norm: list = []
    errors: list = []
    for st in (steps or []):
        st2 = dict(st) if isinstance(st, dict) else {}
        # Normalize to the full single-plan shape validate_plan expects, so a
        # terse LLM step ({"action","entities"}) still validates.
        if not st2.get("action") and st2.get("tool"):
            st2["action"] = st2["tool"]
        st2.setdefault("entities", {})
        st2.setdefault("confidence", 1.0)
        st2.setdefault("reason", "")
        if str(st2.get("action") or "") in ("open_patient", "download_patient"):
            st2["needs_confirmation"] = True  # workflow confirms once up front
        else:
            st2.setdefault("needs_confirmation", False)
        normalized, errs = validate_plan(st2)
        norm.append(normalized if normalized is not None else st2)
        if errs:
            errors.extend(errs)
    return norm, errors

_ALLOWED_ENTITY_KEYS_BY_ACTION: dict[str, set[str]] = {
    "list_patients": {"source", "date", "modality", "patient_name", "patient_code"},
    "open_patient": {"source", "patient_code", "resolved_patient"},
    "download_patient": {
        "source",
        "patient_code",
        "use_context_patient",
        "resolved_patient",
    },
    "set_source_mode": {"mode", "source"},
    "import_dicom": {"path"},
    "select_patient": {"patient_code", "limit", "row_index"},
    "change_font_size": {"direction", "delta"},
    "sort_patients": {"column", "order"},
    "select_and_download": {"sort_column", "sort_order", "column", "order", "limit"},
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

    # CommandBus-bridged actions: lenient semantics — the action name must be
    # known and entities must be an object; per-entity typing is the owning
    # adapter's job (each returns a typed, recoverable error envelope).
    if action in _BUS_ALLOWED_ACTIONS:
        for k in (plan.get("entities") or {}).keys() if isinstance(plan.get("entities"), dict) else []:
            if not isinstance(k, str):
                errs.append(
                    ValidationError(
                        code=ERR_INVALID_ENTITY,
                        field="entities",
                        message="Entity keys must be strings.",
                    )
                )
                break
        return errs

    if action not in _ALLOWED_ACTIONS:
        errs.append(
            ValidationError(
                code=ERR_INVALID_ACTION,
                field="action",
                message=f"Unsupported action '{action}'.",
                hint=(
                    "Allowed: list_patients, open_patient, download_patient, "
                    "set_source_mode, import_dicom, select_patient, "
                    "change_font_size, sort_patients, select_and_download, "
                    "plus module/viewer/download bus actions such as "
                    "open_module, toggle_eagle, open_mpr, change_series"
                ),
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
