"""
brain/agent.py  —  AgentBrain: two-phase LLM action planner.
-------------------------------------------------------------
Orchestrates the full pipeline:

  Phase 1  (router.py)
    ┌─────────────────────────────────────────┐
    │  user_text + catalog.yaml (Document 1)  │  →  LLM  →  modules: [...]
    └─────────────────────────────────────────┘

  Phase 2  (this file, _phase2_plan)
    ┌──────────────────────────────────────────┐
    │  user_text + module docs (Document 2s)   │  →  LLM  →  JSON action plan
    └──────────────────────────────────────────┘

  Dispatch  (this file, _dispatch)
    JSON plan  →  validate  →  executor / adapter call

Usage
-----
    brain = AgentBrain(home_widget=widget)
    result = brain.handle(user_text="لیست بیماران امروز", language="fa")
    # result.ok, result.message, result.data
"""

from __future__ import annotations

import json
import logging
from typing import Any

from EchoMind.llm_client import gapgpt_chat, LLMError
from ..contracts import SecretaryActionPlan, SecretaryResult
from ..validator import validate_plan
from .catalog_loader import load_module_docs
from .router import RouteDecision, route_request

log = logging.getLogger(__name__)

# ── LLM connection — all calls routed through EchoMind.llm_client ─────────────
# Key is resolved automatically from EchoMind Settings (Settings → EchoMind).
_MODEL = "gpt-4.1-mini"
_TIMEOUT = 30

_SYSTEM_PHASE2 = """\
You are the Action Planner for the AIPacs DICOM workstation.
You will receive one or more MODULE DOCUMENTS that describe what actions are
available.  Your job is to read the user's request and produce ONE executable
JSON action plan that exactly follows the output contract in the module document.

STRICT RULES:
- Return a single JSON object only.  No prose, no markdown fences.
- The JSON must contain exactly these top-level keys:
    action, entities, confidence, needs_confirmation, reason
- Use the entity schema and confirmation policy from the module document.
- If the user request maps to a side-effect action, set needs_confirmation=true.
- confidence is a float 0.0–1.0.
"""

# ── Dispatcher map ────────────────────────────────────────────────────────────
# Maps action name → the name of the executor method to call.
# This is extended as new modules add their executors.
_ACTION_EXECUTOR_MAP: dict[str, str] = {
    # homepage module actions (existing executor)
    "list_patients": "_list_patients",
    "open_patient":  "_open_patient",
    "download_patient": "_download_patient",
    # mpr_zeta (future)
    "open_mpr":      "_open_mpr",
    "apply_preset":  "_apply_preset",
    "measure":       "_measure",
    # advanced_analysis (future)
    "run_analysis":  "_run_analysis",
    "export_report": "_export_report",
    # printing (future)
    "print_series":  "_print_series",
    "export_pdf":    "_export_pdf",
    # echomind (future)
    "ai_chat":           "_ai_chat",
    "generate_summary":  "_generate_summary",
    "generate_report":   "_generate_report",
    # eagle_ai (future)
    "toggle_eagle":   "_toggle_eagle",
    "show_findings":  "_show_findings",
    "explain_finding": "_explain_finding",
}

# These actions can be dispatched right now with the current executor
_IMPLEMENTED_ACTIONS = {"list_patients", "open_patient", "download_patient"}


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        return "\n".join(l for l in lines if not l.strip().startswith("```")).strip()
    return text


def _parse_action_plan(raw: str) -> SecretaryActionPlan | None:
    """Parse LLM Phase 2 response into a SecretaryActionPlan dict."""
    try:
        obj: dict[str, Any] = json.loads(_strip_fences(raw))
        return obj  # type: ignore[return-value]
    except json.JSONDecodeError:
        log.warning("Phase 2: could not parse action plan JSON: %r", raw[:300])
        return None


class AgentBrain:
    """
    Two-phase LLM agent brain for the AIPacs workstation.

    Parameters
    ----------
    executor : SecretaryExecutor | None
        If provided, the brain will dispatch validated plans to it directly.
        Pass None to run in dry-run (plan-only) mode.
    fallback_to_secretary : bool
        If Phase 1 returns no modules, fall back to the legacy
        rule-based + repair_loop pipeline in the existing orchestrator.
    """

    def __init__(self, executor=None, fallback_to_secretary: bool = True):
        self._executor = executor
        self._fallback = fallback_to_secretary

    # ── Public API ────────────────────────────────────────────────────────────

    def _get_route(self, user_text: str, language: str = "auto") -> RouteDecision:
        """Phase 1 only — returns the routing decision without planning."""
        return route_request(user_text=user_text, language=language)

    def plan(
        self,
        user_text: str,
        language: str = "auto",
        pre_routed: "RouteDecision | None" = None,
    ) -> SecretaryActionPlan | None:
        """
        Run Phase 1 (routing) + Phase 2 (planning) and return a validated plan.
        Does NOT execute; call ``dispatch`` to execute.

        Parameters
        ----------
        pre_routed :
            If a RouteDecision was already obtained (e.g. by the orchestrator
            for progress reporting), pass it here to skip the Phase 1 LLM call.
        Returns None if no plan could be produced.
        """
        import datetime as _dt
        # ── Phase 1: route ────────────────────────────────────────────────────
        if pre_routed is not None:
            decision: RouteDecision = pre_routed
            print(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — routing decision (pre-computed): {decision.modules}")
        else:
            decision = route_request(user_text=user_text, language=language)
        log.info("[Phase1] modules=%s  reason=%r", decision.modules, decision.reason)

        if decision.is_empty:
            log.warning("Phase 1 returned no modules; cannot plan.")
            print(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — ERROR: no modules selected, cannot proceed to Phase 3")
            return None

        # ── Phase 3: plan ────────────────────────────────────────────────────
        print(f"[EchoMind | Phase 3] {_dt.datetime.now():%H:%M:%S} — sending module docs + user text to GPT for action planning")
        print(f"  modules    : {decision.modules}")
        module_docs = load_module_docs(decision.modules)
        print(f"  docs_len   : {len(module_docs)} chars")
        plan = self._phase2_plan(
            user_text=user_text,
            language=language,
            module_docs=module_docs,
        )
        if plan is None:
            log.warning("Phase 2 returned no plan.")
            print(f"[EchoMind | Phase 3] {_dt.datetime.now():%H:%M:%S} — ERROR: LLM returned no action plan")
            return None

        # ── Validate ─────────────────────────────────────────────────────────
        normalized, errors = validate_plan(plan)
        if errors:
            log.warning("Phase 2 plan has validation errors: %s", errors)
            # Attempt one repair using the existing repair_loop
            try:
                from ..repair_loop import retry_plan_with_llm
                repaired = retry_plan_with_llm(
                    user_text=user_text,
                    language=language,
                    invalid_plan=dict(plan),
                    validation_errors=errors,
                    max_retries=1,
                )
                if repaired:
                    return repaired
            except Exception as exc:
                log.error("Repair loop failed: %s", exc)
            return None

        return normalized

    def handle(
        self,
        user_text: str,
        language: str = "auto",
        session_id: str | None = None,
    ) -> SecretaryResult:
        """
        Full pipeline: Phase 1 → Phase 2 → validate → dispatch.
        Returns a SecretaryResult.
        """
        plan = self.plan(user_text=user_text, language=language)
        if plan is None:
            return SecretaryResult(
                ok=False,
                action="unknown",
                message="I could not understand the request.",
                data=None,
                error_code="ERR_NO_PLAN",
            )
        return self.dispatch(plan, session_id=session_id)

    def dispatch(
        self,
        plan: SecretaryActionPlan,
        session_id: str | None = None,
    ) -> SecretaryResult:
        """
        Execute a validated plan.  If the executor is not set, or the action
        is not yet implemented, returns a descriptive dry-run result.
        """
        action = plan.get("action", "")

        if action not in _ACTION_EXECUTOR_MAP:
            return SecretaryResult(
                ok=False,
                action=action,
                message=f"Action '{action}' is not registered in the dispatcher.",
                data=None,
                error_code="ERR_UNKNOWN_ACTION",
            )

        if action not in _IMPLEMENTED_ACTIONS:
            return SecretaryResult(
                ok=True,
                action=action,
                message=(
                    f"Plan for '{action}' produced successfully. "
                    "Executor for this module is not yet wired — plan returned for inspection."
                ),
                data={"plan": dict(plan)},
                error_code=None,
            )

        if self._executor is None:
            return SecretaryResult(
                ok=True,
                action=action,
                message="[dry-run] No executor attached. Plan produced.",
                data={"plan": dict(plan)},
                error_code=None,
            )

        # Delegate to the existing SecretaryExecutor
        # Executor methods expect (plan, state) and side-effect methods also
        # need confirmed=True (confirmation is handled by the orchestrator before
        # dispatch is called from the brain).
        _CONFIRMED_ACTIONS = {"open_patient", "download_patient"}
        _empty_state: dict = {"pending": None, "last_patient": None, "last_list": []}
        try:
            method_name = _ACTION_EXECUTOR_MAP[action]
            method = getattr(self._executor, method_name, None)
            if method is None:
                return SecretaryResult(
                    ok=False,
                    action=action,
                    message=f"Executor has no method '{method_name}'.",
                    data=None,
                    error_code="ERR_EXECUTOR_MISSING",
                )
            if action in _CONFIRMED_ACTIONS:
                return method(plan, _empty_state, confirmed=True)
            return method(plan, _empty_state)
        except Exception as exc:
            log.exception("Dispatch error for action=%r: %s", action, exc)
            return SecretaryResult(
                ok=False,
                action=action,
                message=f"Runtime error: {exc}",
                data=None,
                error_code="ERR_RUNTIME",
            )

    # ── Private ───────────────────────────────────────────────────────────────

    def _phase2_plan(
        self,
        user_text: str,
        language: str,
        module_docs: str,
        timeout: float = _TIMEOUT,
    ) -> SecretaryActionPlan | None:
        """Call the LLM with the module document(s) to produce an action plan."""
        user_message = (
            f"Language hint: {language or 'auto'}\n\n"
            "=== MODULE DOCUMENTS (Document 2) ===\n"
            f"{module_docs}\n\n"
            "=== USER REQUEST ===\n"
            f"{user_text}\n\n"
            "Produce an executable JSON action plan following the output contract above."
        )
        payload = {
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PHASE2},
                {"role": "user",   "content": user_message},
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        import datetime as _dt
        print(f"[EchoMind | Phase 3] {_dt.datetime.now():%H:%M:%S} — Phase 3 LLM REQUEST (action planning)")
        print(f"  model      : {_MODEL}")
        print(f"  user_text  : {user_text!r}")
        print(f"  docs_len   : {len(module_docs)} chars")
        try:
            raw = gapgpt_chat(
                messages=payload["messages"],
                model=_MODEL,
                max_tokens=512,
                temperature=0.0,
                timeout=int(timeout),
            )
            log.debug("Phase 2 raw response: %r", raw[:400])
            print(f"[EchoMind | Phase 3] {_dt.datetime.now():%H:%M:%S} — Phase 3 LLM RESPONSE")
            print(f"  raw        : {raw[:500]}")
            parsed = _parse_action_plan(raw)
            if parsed:
                print(f"  action     : {parsed.get('action')}")
                print(f"  entities   : {parsed.get('entities')}")
                print(f"  confidence : {parsed.get('confidence')}")
            else:
                print(f"  [Phase 3] WARNING: could not parse JSON from response")
            return parsed
        except LLMError as exc:
            log.error("Phase 2 LLM call failed: %s", exc)
            print(f"[EchoMind | Phase 3] {_dt.datetime.now():%H:%M:%S} — Phase 3 LLM ERROR: {exc}")
            return None
