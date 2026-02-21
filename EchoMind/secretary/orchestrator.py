from __future__ import annotations

import copy
import sys
import time
from datetime import datetime
from typing import Any

from . import audit
from .adapters.home_widget_adapter import HomeWidgetAdapter
from .confirm import is_no, is_yes, parse_selection_index
from .contracts import SecretaryActionPlan, SecretaryCommand, SecretaryResult
from .errors import ERR_PLAN_VALIDATION_FAILED, ERR_RUNTIME, ERR_UNPARSED
from .execution_repair import is_repairable, repair_plan_after_execution_failure
from .executor import SecretaryExecutor
from .parser_llm import parse_command_llm
from .parser_rules import is_chitchat, parse_command_rule
from .repair_loop import retry_plan_with_llm
from .session_log import SessionLog
from .validator import validate_plan


class SecretaryOrchestrator:
    # Maximum number of execution attempts per command (1 initial + up to 4 LLM repairs)
    _MAX_EXECUTION_RETRIES: int = 5

    def __init__(
        self,
        home_widget=None,
        llm_fallback: bool = True,
        use_brain: bool = False,
    ):
        """
        Parameters
        ----------
        home_widget :
            The HomePanel widget to bind the adapter to.
        llm_fallback : bool
            If True (default), fall back to the single-shot LLM parser
            + repair loop when the rule parser fails.
        use_brain : bool
            If True, route user requests through the two-phase AgentBrain
            pipeline (Phase 1: module routing → Phase 2: action planning)
            instead of the single-shot rule + LLM approach.
            Set to True when you want full multi-module agent behaviour.
        """
        self.adapter = HomeWidgetAdapter(home_widget=home_widget)
        self.executor = SecretaryExecutor(self.adapter)
        self.llm_fallback = llm_fallback
        self._sessions: dict[str, dict[str, Any]] = {}
        # ── EchoMind memory ───────────────────────────────────────────────────
        self._memory_store: Any = None   # lazy-loaded EchoMindMemoryStore
        self._last_modules: list[str] = []  # populated by _parse_plan (brain path)
        self._use_brain = use_brain
        self._brain = None          # lazy-loaded AgentBrain instance

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

    def _get_brain(self):
        """Lazy-load the AgentBrain (avoids circular import at module load time)."""
        if self._brain is None:
            from .brain.agent import AgentBrain
            self._brain = AgentBrain(executor=self.executor, fallback_to_secretary=True)
        return self._brain

    def _get_memory_store_safe(self):
        """Lazy-load EchoMindMemoryStore; returns None on any failure."""
        if self._memory_store is not None:
            return self._memory_store
        try:
            from .memory.memory_store import EchoMindMemoryStore
            self._memory_store = EchoMindMemoryStore()
        except Exception:
            self._memory_store = None
        return self._memory_store

    @property
    def memory_store(self):
        """Public accessor for the memory store (used by the UI button)."""
        return self._get_memory_store_safe()

    def _parse_plan(self, cmd: SecretaryCommand, memory_context: str = "") -> SecretaryActionPlan | None:
        text = cmd.get("text") or ""
        language = cmd.get("language") or "auto"
        progress_cb = cmd.get("progress_cb")  # optional callable(stage: str)

        # ── AgentBrain path (two-phase: routing + planning) ───────────────────
        if self._use_brain:
            try:
                if callable(progress_cb):
                    progress_cb("Phase 2: Module Routing")
                decision = self._get_brain()._get_route(user_text=text, language=language)
                if decision and not decision.is_empty:
                    if callable(progress_cb):
                        progress_cb(f"Phase 3: Planning ({', '.join(decision.modules)})")
                    self._last_modules = list(decision.modules)  # capture for memory
                brain_plan = self._get_brain().plan(
                    user_text=text, language=language, pre_routed=decision,
                    memory_context=memory_context,
                )
                if brain_plan:
                    return self._ensure_source(brain_plan, cmd)
            except Exception:
                pass  # fall through to legacy path on any brain failure

        # ── Legacy path: rule parser → single-shot LLM → repair loop ─────────
        plan = parse_command_rule(text)
        if plan:
            return self._ensure_source(plan, cmd)

        if self.llm_fallback:
            try:
                llm_plan = parse_command_llm(text=text, language=language)
            except Exception:
                llm_plan = None
            if llm_plan:
                normalized, errs = validate_plan(llm_plan)
                if not errs and normalized is not None:
                    return self._ensure_source(normalized, cmd)

                try:
                    repaired = retry_plan_with_llm(
                        user_text=text,
                        language=language,
                        invalid_plan=dict(llm_plan),
                        validation_errors=errs,
                        max_retries=2,
                    )
                except Exception:
                    repaired = None

                if repaired:
                    return self._ensure_source(repaired, cmd)
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
        """Public entry-point: wraps _handle_core with per-request session logging."""
        text = (cmd.get("text") or "").strip()
        _session = SessionLog(user_text=text)
        _result: SecretaryResult = {
            "ok": False,
            "action": "unknown",
            "message": "No result produced.",
            "data": None,
            "error_code": "INTERNAL",
        }
        try:
            _result = self._handle_core(cmd, _session)
        finally:
            _session.close(_result)
        return _result

    def _handle_core(self, cmd: SecretaryCommand, _session: SessionLog) -> SecretaryResult:  # noqa: C901
        """Core request handler — called by handle()."""
        text = (cmd.get("text") or "").strip()
        sid = cmd.get("session_id") or "secretary-default"
        state = self._get_state(sid)
        source_tab = self.adapter.get_active_source()
        stt_req = cmd.get("stt_route", "native")
        stt_used = cmd.get("stt_route_used", stt_req)
        language = cmd.get("language") or "auto"
        t0 = time.perf_counter()
        action_id: int | None = None
        confirmed = False
        action_name = "unknown"
        entities: dict[str, Any] = {}
        action_blob: dict[str, Any] = {}
        confirmation_required = False

        # ── Memory: start a new cycle ────────────────────────────────────────
        _mem = self._get_memory_store_safe()
        if _mem:
            try:
                _mem.start_cycle(text)
            except Exception:
                pass

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

            # ── Chitchat / greeting fast-path ─────────────────────────────
            # Check before _parse_plan so the LLM is never called for greetings.
            chat, chat_reply = is_chitchat(text)
            if chat:
                return {
                    "ok": True,
                    "action": "chitchat",
                    "message": chat_reply,
                    "data": None,
                    "error_code": None,
                }

            plan = self._parse_plan(
                cmd,
                memory_context=(_mem.get_context_for_llm() if _mem else ""),
            )
            if not plan:
                return {
                    "ok": False,
                    "action": "unknown",
                    "message": "I could not map this command to a Secretary action.",
                    "data": None,
                    "error_code": ERR_UNPARSED,
                }

            validated_plan, validation_errors = validate_plan(plan)
            if validation_errors:
                err_rows = [e.to_dict() for e in validation_errors]
                action_name = str(plan.get("action") or "unknown")
                entities = dict(plan.get("entities") or {}) if isinstance(plan, dict) else {}
                action_blob = dict(plan) if isinstance(plan, dict) else {}
                action_id = audit.log_start(
                    sid=sid,
                    source_tab=source_tab,
                    command_text=text,
                    stt_route_requested=stt_req,
                    stt_route_used=stt_used,
                    intent=action_name,
                    entities=entities,
                    action=action_blob,
                    confirmation_required=False,
                )
                result = {
                    "ok": False,
                    "action": action_name,
                    "message": "Plan validation failed.",
                    "data": {
                        "validation_errors": err_rows,
                        "received_plan": action_blob,
                    },
                    "error_code": ERR_PLAN_VALIDATION_FAILED,
                }
                audit.log_end(
                    action_id=action_id,
                    confirmed=False,
                    status="error",
                    error_code=result.get("error_code"),
                    error_text=result.get("message"),
                    result_count=self._count_result_rows(result.get("data")),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result

            plan = validated_plan

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

            _session.add_plan(dict(plan))

            # ── Memory: record modules + GPT command ─────────────────────────
            if _mem:
                try:
                    _mem.record_modules(self._last_modules)
                    _mem.record_gpt_command(dict(plan))
                except Exception:
                    pass

            # ── Execution retry loop (Task 6: LLM-feedback repair) ────────────
            # When the agent explicitly resolved the patient from memory and
            # produced needs_confirmation=False, skip the voice confirmation
            # gate entirely — no second "yes" command required.
            _auto_confirmed: bool = plan.get("needs_confirmation") is False
            if _auto_confirmed:
                confirmed = True  # propagate to audit log
            active_plan = copy.deepcopy(plan)
            result = None
            for _exec_attempt in range(1, self._MAX_EXECUTION_RETRIES + 1):
                result = self._run_plan(active_plan, state, confirmed=_auto_confirmed)

                # Success or pending user input → stop immediately
                if result.get("ok") or result.get("error_code") in (
                    "CONFIRM_REQUIRED", "AMBIGUOUS"
                ):
                    break

                # Last attempt → wrap up with terminal message
                if _exec_attempt >= self._MAX_EXECUTION_RETRIES:
                    _ts = datetime.now().strftime("%H:%M:%S")
                    sys.stderr.write(
                        f"\n[EchoMind | Retry   ] {_ts} — all {self._MAX_EXECUTION_RETRIES} "
                        f"attempts exhausted for action '{active_plan.get('action')}'\n"
                    )
                    sys.stderr.flush()
                    _session.add_error(
                        f"MAX_RETRIES_EXCEEDED after {self._MAX_EXECUTION_RETRIES} attempts"
                    )
                    result = {
                        "ok": False,
                        "action": str(active_plan.get("action") or "unknown"),
                        "message": (
                            f"EchoMind Secretary could not complete the command after "
                            f"{self._MAX_EXECUTION_RETRIES} attempts. "
                            f"Last error: {result.get('message')} "
                            "EchoMind Secretary is closing this request."
                        ),
                        "data": result.get("data"),
                        "error_code": "MAX_RETRIES_EXCEEDED",
                    }
                    state["pending"] = None
                    break

                # Non-repairable error → stop retrying
                if not is_repairable(result):
                    break

                # Ask LLM to repair the plan
                _session.add_error(
                    str(result.get("message")), attempt=_exec_attempt
                )
                repaired = repair_plan_after_execution_failure(
                    user_text=text,
                    language=language,
                    failed_plan=dict(active_plan),
                    execution_result=result,
                    attempt=_exec_attempt,
                    max_attempts=self._MAX_EXECUTION_RETRIES,
                )
                if not repaired:
                    break  # LLM could not produce a valid repair

                _session.add_repair(dict(repaired), attempt=_exec_attempt)
                active_plan = repaired

            # ── Memory: record execution result and close cycle ───────────────
            if _mem:
                try:
                    _patient_list = state.get("last_list", []) if result.get("ok") else []
                    # Also check if data is a list of patient dicts
                    if not _patient_list and isinstance(result.get("data"), list):
                        _patient_list = result["data"]
                    _mem.record_execution_result(result, _patient_list)
                    _mem.close_cycle()
                except Exception:
                    pass

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
                "error_code": ERR_RUNTIME,
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
