from __future__ import annotations

import copy
import time
from typing import Any

from . import audit
from .adapters.home_widget_adapter import HomeWidgetAdapter
from .confirm import is_no, is_yes, parse_selection_index
from .contracts import SecretaryActionPlan, SecretaryCommand, SecretaryResult
from .executor import SecretaryExecutor
from .parser_llm import parse_command_llm
from .parser_rules import parse_command_rule


class SecretaryOrchestrator:
    def __init__(self, home_widget=None, llm_fallback: bool = True):
        self.adapter = HomeWidgetAdapter(home_widget=home_widget)
        self.executor = SecretaryExecutor(self.adapter)
        self.llm_fallback = llm_fallback
        self._sessions: dict[str, dict[str, Any]] = {}

    def _get_state(self, sid: str) -> dict[str, Any]:
        state = self._sessions.get(sid)
        if state is None:
            state = {
                "pending": None,  # {"type":"confirm"|"choose","plan":..., "candidates":[...]}
                "last_patient": None,
                "last_list": [],
            }
            self._sessions[sid] = state
        return state

    @staticmethod
    def _ensure_source(plan: SecretaryActionPlan, cmd: SecretaryCommand) -> SecretaryActionPlan:
        out = copy.deepcopy(plan)
        source_scope = cmd.get("source_scope", "active_tab")
        if source_scope in ("local", "server"):
            out.setdefault("entities", {})
            out["entities"]["source"] = source_scope
        return out

    def _parse_plan(self, cmd: SecretaryCommand) -> SecretaryActionPlan | None:
        text = cmd.get("text") or ""
        language = cmd.get("language") or "auto"

        plan = parse_command_rule(text)
        if plan:
            return self._ensure_source(plan, cmd)

        if self.llm_fallback:
            try:
                llm_plan = parse_command_llm(text=text, language=language)
            except Exception:
                llm_plan = None
            if llm_plan:
                return self._ensure_source(llm_plan, cmd)
        return None

    @staticmethod
    def _count_result_rows(data: Any) -> int:
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            if isinstance(data.get("candidate"), dict):
                return 1
            return len(data)
        return 0

    def _result_from_pending_choice(self, state: dict[str, Any], text: str) -> SecretaryResult | None:
        pending = state.get("pending")
        if not pending or pending.get("type") != "choose":
            return None

        candidates = pending.get("candidates") or []
        idx = parse_selection_index(text, len(candidates))
        if idx is None:
            return {
                "ok": False,
                "action": str(pending.get("plan", {}).get("action") or "unknown"),
                "message": f"Please choose a number between 1 and {len(candidates)}.",
                "data": candidates,
                "error_code": "SELECTION_REQUIRED",
            }

        chosen = candidates[idx]
        plan = copy.deepcopy(pending.get("plan"))
        plan.setdefault("entities", {})
        plan["entities"]["resolved_patient"] = chosen
        state["pending"] = {"type": "confirm", "plan": plan}

        row = chosen
        action = plan.get("action")
        action_text = "open" if action == "open_patient" else "download"
        return {
            "ok": False,
            "action": str(action),
            "message": (
                f"Selected #{idx + 1}: {row.get('patient_id')} ({row.get('patient_name')}). "
                f"Reply yes to {action_text}, or no to cancel."
            ),
            "data": {"candidate": row},
            "error_code": "CONFIRM_REQUIRED",
        }

    def _run_plan(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool) -> SecretaryResult:
        result = self.executor.execute(plan, state, confirmed=confirmed)
        if result.get("ok"):
            payload = result.get("data")
            if isinstance(payload, dict):
                candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else payload
                if isinstance(candidate, dict):
                    state["last_patient"] = candidate
            elif isinstance(payload, list):
                state["last_list"] = payload
                if len(payload) == 1 and isinstance(payload[0], dict):
                    state["last_patient"] = payload[0]
            state["pending"] = None
            return result

        error_code = result.get("error_code")
        if error_code == "CONFIRM_REQUIRED":
            pending_plan = copy.deepcopy(plan)
            candidate = None
            if isinstance(result.get("data"), dict):
                candidate = result["data"].get("candidate")
            if isinstance(candidate, dict):
                pending_plan.setdefault("entities", {})
                pending_plan["entities"]["resolved_patient"] = candidate
            state["pending"] = {"type": "confirm", "plan": pending_plan}
            return result

        if error_code == "AMBIGUOUS":
            candidates = result.get("data") if isinstance(result.get("data"), list) else []
            state["pending"] = {
                "type": "choose",
                "plan": copy.deepcopy(plan),
                "candidates": candidates,
            }
            result["message"] = (
                f"{result.get('message')} Reply with a number 1..{len(candidates)} to choose a patient."
            )
            return result

        state["pending"] = None
        return result

    def handle(self, cmd: SecretaryCommand) -> SecretaryResult:
        text = (cmd.get("text") or "").strip()
        sid = cmd.get("session_id") or "secretary-default"
        state = self._get_state(sid)
        source_tab = self.adapter.get_active_source()
        stt_req = cmd.get("stt_route", "native")
        stt_used = cmd.get("stt_route_used", stt_req)
        t0 = time.perf_counter()
        action_id: int | None = None
        confirmed = False
        action_name = "unknown"
        entities: dict[str, Any] = {}
        action_blob: dict[str, Any] = {}
        confirmation_required = False

        try:
            pending = state.get("pending")
            if pending and pending.get("type") == "choose":
                action_name = str(pending.get("plan", {}).get("action") or "unknown")
                entities = dict(pending.get("plan", {}).get("entities") or {})
                action_blob = dict(pending.get("plan") or {})
                confirmation_required = True
                action_id = audit.log_start(
                    sid=sid,
                    source_tab=source_tab,
                    command_text=text,
                    stt_route_requested=stt_req,
                    stt_route_used=stt_used,
                    intent=action_name,
                    entities=entities,
                    action=action_blob,
                    confirmation_required=True,
                )
                result = self._result_from_pending_choice(state, text)
                if result is None:
                    result = {
                        "ok": False,
                        "action": action_name,
                        "message": "Pending selection could not be resolved.",
                        "data": None,
                        "error_code": "SELECTION_REQUIRED",
                    }
                audit.log_end(
                    action_id=action_id,
                    confirmed=False,
                    status="ok" if result.get("ok") else "error",
                    error_code=result.get("error_code"),
                    error_text=result.get("message"),
                    result_count=self._count_result_rows(result.get("data")),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result

            if pending and pending.get("type") == "confirm":
                plan = copy.deepcopy(pending.get("plan"))
                action_name = str(plan.get("action") or "unknown")
                entities = dict(plan.get("entities") or {})
                action_blob = dict(plan or {})
                confirmation_required = True
                action_id = audit.log_start(
                    sid=sid,
                    source_tab=source_tab,
                    command_text=text,
                    stt_route_requested=stt_req,
                    stt_route_used=stt_used,
                    intent=action_name,
                    entities=entities,
                    action=action_blob,
                    confirmation_required=True,
                )

                if is_no(text):
                    state["pending"] = None
                    result = {
                        "ok": True,
                        "action": action_name,
                        "message": "Action cancelled.",
                        "data": None,
                        "error_code": None,
                    }
                    audit.log_end(
                        action_id=action_id,
                        confirmed=False,
                        status="cancelled",
                        error_code=None,
                        error_text=None,
                        result_count=0,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                    )
                    return result

                if not is_yes(text):
                    result = {
                        "ok": False,
                        "action": action_name,
                        "message": "Please answer yes to confirm, or no to cancel.",
                        "data": pending.get("plan", {}).get("entities"),
                        "error_code": "CONFIRM_REQUIRED",
                    }
                    audit.log_end(
                        action_id=action_id,
                        confirmed=False,
                        status="error",
                        error_code=result.get("error_code"),
                        error_text=result.get("message"),
                        result_count=0,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                    )
                    return result

                confirmed = True
                result = self._run_plan(plan, state, confirmed=True)
                audit.log_end(
                    action_id=action_id,
                    confirmed=confirmed,
                    status="ok" if result.get("ok") else "error",
                    error_code=result.get("error_code"),
                    error_text=result.get("message"),
                    result_count=self._count_result_rows(result.get("data")),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result

            plan = self._parse_plan(cmd)
            if not plan:
                return {
                    "ok": False,
                    "action": "unknown",
                    "message": "I could not map this command to a Secretary action.",
                    "data": None,
                    "error_code": "UNPARSED",
                }

            action_name = str(plan.get("action") or "unknown")
            entities = dict(plan.get("entities") or {})
            action_blob = dict(plan)
            confirmation_required = bool(plan.get("needs_confirmation"))
            action_id = audit.log_start(
                sid=sid,
                source_tab=source_tab,
                command_text=text,
                stt_route_requested=stt_req,
                stt_route_used=stt_used,
                intent=action_name,
                entities=entities,
                action=action_blob,
                confirmation_required=confirmation_required,
            )

            result = self._run_plan(plan, state, confirmed=False)
            audit.log_end(
                action_id=action_id,
                confirmed=confirmed,
                status="ok" if result.get("ok") else "error",
                error_code=result.get("error_code"),
                error_text=result.get("message"),
                result_count=self._count_result_rows(result.get("data")),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            return result
        except Exception as exc:
            result = {
                "ok": False,
                "action": action_name,
                "message": f"Secretary runtime error: {exc}",
                "data": None,
                "error_code": "RUNTIME_ERROR",
            }
            audit.log_end(
                action_id=action_id,
                confirmed=confirmed,
                status="error",
                error_code=result.get("error_code"),
                error_text=result.get("message"),
                result_count=0,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            return result
