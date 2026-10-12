"""The agent orchestrator: the LLM proposes, the orchestrator disposes.

``handle_command()`` takes the *text* a client sent (typed or transcribed —
after transcription they are indistinguishable) and drives:

    1. tool schemas for THIS principal      (registry.list_for)
    2. LLM interpretation                   (llm.interpreter.interpret)
    3. validation of the model's decision   ← the model's output is UNTRUSTED
    4. confirmation gate for writes         (a human taps; the model cannot)
    5. idempotency                          (a retry must not double-write)
    6. sequential dispatch through core     (permissions · validation · audit)
    7. Persian summary of the result        (best-effort)
    8. one normalized envelope back

``confirm()`` is phase 2: the human approved on the phone, the plan is redeemed
once, and the same validated steps execute.

The orchestrator never delegates a check to the LLM. If the model names a tool
that is not in the registry, the call is rejected — not "helpfully" matched to
the closest name.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__, jalali
from ..llm import client as llm_client
from ..llm.interpreter import (
    AgentDecision,
    InterpretationError,
    ProposedCall,
    assess_evidence as interpret_assess,
    analyze_attachments,
    interpret,
    summarize,
)
from .confirmation import ConfirmationError, ConfirmationStore, default_store, payload_hash
from .dispatcher import dispatch
from .errors import ToolNotFoundError
from .guards import audit_dispatch
from . import gather, modes, presentation, progress
from . import scenario_router
from . import sources as source_catalog
from .idempotency import IdempotencyConflictError, IdempotencyStore
from .registry import ToolRegistry, default_registry, requires_human_approval
from .types import DispatchContext, ToolCall, ToolDefinition
from .attachments import Attachment

LOG = logging.getLogger("reception_crm.core.orchestrator")


def _narrative(existing: str, english: str) -> str:
    import os
    if os.environ.get('CRM_EAGLE_CONFIG'):
        from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
        if current_reply_language() == 'en':
            return english
    return existing


@dataclass(frozen=True)
class CommandRequest:
    text: str
    request_id: str = ""
    source: str = "unknown"
    device_id: str = ""
    client_version: str = ""
    history: list[dict[str, str]] | None = None
    idempotency_key: str | None = None
    #: What this conversation has been about, recorded by the SERVER from the
    #: arguments earlier tools were dispatched with -- never parsed out of model
    #: prose. It is what lets «این بیمار» survive past the history window.
    facts: dict[str, Any] | None = None
    #: Complete evidence from the newest successful analysis in THIS owned
    #: conversation. Server-only: the adapter loads it after authorization and
    #: it is never accepted from or returned to the phone.
    session_evidence: dict[str, Any] | None = None
    #: Which agent mode this turn is in. An unknown value falls back to the
    #: default rather than failing: a mode narrows and never widens, so the
    #: fallback cannot grant anything the caller did not already have.
    mode: str = modes.DEFAULT_MODE
    #: Where to publish "what I am doing right now", so a phone waiting 28
    #: seconds can show something truer than a spinner. Purely decorative: the
    #: answer arrives on the response to this request either way.
    conversation_id: str = ""
    #: Optional, server-owned sink for the local archive. It is never included
    #: in the mobile envelope; the HTTP adapter uses it to retain every source
    #: that informed an analysis, including corroborating sources.
    evidence_sink: list[dict[str, Any]] | None = None
    #: Server-validated originals. The HTTP adapter decodes them once; no
    #: base64 or caller-supplied path crosses into the orchestrator.
    attachments: tuple[Attachment, ...] = ()
    #: Additive hosted-only fallback; current request language takes precedence.
    language_preference: str = "en"


@dataclass(frozen=True)
class ConfirmRequest:
    plan_id: str
    request_id: str = ""
    idempotency_key: str | None = None
    source: str = "unknown"
    device_id: str = ""
    client_version: str = ""


# ---------------------------------------------------------------------------
# Phase 1 — interpret and either answer, ask, or plan
# ---------------------------------------------------------------------------


def handle_command(
    request: CommandRequest,
    context: DispatchContext,
    registry: ToolRegistry | None = None,
    chat: Any = None,
    confirmations: ConfirmationStore | None = None,
) -> dict[str, Any]:
    import os
    if os.environ.get('CRM_EAGLE_CONFIG'):
        from modules.ai_imaging.eagle_eye_remote.crm.language import run_command
        return run_command(_handle_command, request, context, registry=registry,
                           chat=chat, confirmations=confirmations)
    return _handle_command(request, context, registry=registry, chat=chat,
                           confirmations=confirmations)


def _handle_command(
    request: CommandRequest,
    context: DispatchContext,
    registry: ToolRegistry | None = None,
    chat: Any = None,
    confirmations: ConfirmationStore | None = None,
) -> dict[str, Any]:
    registry = registry or default_registry()
    confirmations = confirmations or default_store()
    request_id = request.request_id or _new_id("req")
    started = time.perf_counter()

    text = str(request.text or "").strip()
    if not text and request.attachments:
        text = "این فایل را بررسی کن و با داده‌های مرتبط نرم‌افزار پذیرش مقایسه کن."
    if not text:
        return _failure(request_id, "VALIDATION", "متن دستور خالی است.", started)

    if not llm_client.is_configured():
        return _failure(
            request_id,
            "LLM_NOT_CONFIGURED",
            "سرویس هوشمند پیکربندی نشده است.",
            started,
            detail="Set RECEPTION_LLM_API_KEY (or RECEPTION_OPENAI_API_KEY) on the Reception CRM machine.",
        )

    # Permissions first, then the mode. The registry decides what this PERSON
    # may call; the mode only removes more from that list. Doing it in the other
    # order would let a mode widen access, which is exactly what it must not do.
    tools = registry.list_for(context.principal)
    if not tools:
        return _failure(request_id, "PERMISSION_DENIED", "شما به هیچ ابزاری دسترسی ندارید.", started)

    mode = modes.get(request.mode)
    tools = modes.tools_for(mode, tools)

    # ---- scenario routing (SHADOW) -----------------------------------------
    # Classified on every question and applied to none of them. `tools` is
    # deliberately NOT narrowed here yet: the decision is published in the
    # envelope so its accuracy can be measured against real questions before it
    # is allowed to decide what the model sees.
    #
    # Switching it on is one line — `tools = scenarios.tools_for_many(...)`
    # below this comment — and it stays absent until the shadow numbers justify
    # it. `chat=None` keeps the LLM tiebreak unused, so this costs no round
    # trip; the deterministic pass is a few set lookups.
    scenario = scenario_router.classify(text, request.facts)
    LOG.info(
        "scenario %s (%.2f, %s) for a %s-mode question",
        scenario.scenario,
        scenario.confidence,
        scenario.method,
        mode.id,
    )

    # What the phone shows instead of a spinner. Analysis takes 8-28 seconds,
    # and a spinner cannot distinguish a server thinking from a server that has
    # died -- users conclude the second and tap again, starting a second answer.
    #
    # NO step total is published, and that is deliberate. It used to guess one
    # (4 for a gathering mode, 3 otherwise) so the phone could draw a bar, and
    # the guess was wrong on the very first live Analysis run: the model asked
    # for two tools in a round, corroboration fetched a third, and the phone was
    # shown «6 از 4». The number of steps is decided by the question, not by the
    # mode, so it is not knowable here -- and an honest "unknown" (0) makes the
    # phone draw an indeterminate bar with the caption, which is what the reader
    # was actually reading anyway.
    reporter = progress.Reporter(context.principal, request.conversation_id)
    reporter.step(_narrative("در حال بررسی درخواست…", "Reviewing the request..."))

    # ---- understand user-supplied real-world evidence ---------------------
    attachment_evidence: dict[str, Any] | None = None
    attachment_source: dict[str, Any] | None = None
    if request.attachments:
        reporter.step(_narrative("در حال خواندن تصویر یا PDF…", "Reading the image or PDF..."))
        try:
            extraction = analyze_attachments(request.attachments, text=text, chat=chat)
            attachment_evidence = {
                "files": [item.public_metadata() for item in request.attachments],
                "extraction": extraction,
            }
            attachment_source = {
                "tool": "user-attachment",
                "arguments": {
                    "files": [
                        {"sha256": item.sha256, "mimeType": item.mime_type}
                        for item in request.attachments
                    ]
                },
                "ok": True,
                "data": attachment_evidence,
                "error": None,
            }
        except (InterpretationError, llm_client.LLMError) as exc:
            _audit(
                request_id, request.source, request.device_id, context,
                "attachment_analysis_failed", text, error=str(exc),
            )
            return {
                **_failure(
                    request_id,
                    "ATTACHMENT_ANALYSIS_FAILED",
                    "خواندن تصویر یا PDF ممکن نشد. لطفاً کیفیت فایل را بررسی و دوباره ارسال کنید.",
                    started,
                    detail=str(exc),
                ),
                "receivedAttachments": [
                    item.public_metadata() for item in request.attachments
                ],
            }

    # ---- interpret ---------------------------------------------------------
    try:
        decision = interpret(
            text, tools, context.principal,
            history=request.history, chat=chat, mode=mode, facts=request.facts,
            session_evidence=request.session_evidence,
            attachment_evidence=attachment_evidence,
        )
    except InterpretationError as exc:
        _audit(request_id, request.source, request.device_id, context, "interpretation_failed", text, error=str(exc))
        return _failure(
            request_id,
            "INTERPRETATION_FAILED",
            "دستور شما قابل تفسیر نبود. لطفاً دوباره بگویید.",
            started,
            detail=str(exc),
        )
    except llm_client.LLMError as exc:
        _audit(request_id, request.source, request.device_id, context, "llm_error", text, error=str(exc))
        return _failure(
            request_id,
            getattr(exc, "code", "LLM_API"),
            "ارتباط با سرویس هوشمند برقرار نشد.",
            started,
            detail=str(exc),
        )

    # ---- clarification -----------------------------------------------------
    if decision.requires_clarification or not decision.tool_calls:
        _audit(request_id, request.source, request.device_id, context, "clarification", text, decision=decision)
        return {
            **_envelope(request_id, started),
            "success": False,
            "message": decision.clarification_fa or _narrative("منظور شما را متوجه نشدم. لطفاً دقیق‌تر بگویید.", "Please clarify your request."),
            "requiresUserAction": True,
            "userAction": {"type": "CLARIFICATION"},
            "mode": mode.id,
            "scenario": scenario.as_dict(),
        }

    # ---- validate the model's decision (UNTRUSTED INPUT) -------------------
    try:
        definitions = [registry.get(call.tool) for call in decision.tool_calls]
    except ToolNotFoundError as exc:
        _audit(request_id, request.source, request.device_id, context, "unknown_tool", text, decision=decision, error=str(exc))
        return _failure(request_id, "TOOL_NOT_FOUND", "این عملیات پشتیبانی نمی‌شود.", started, detail=str(exc))

    # ---- the read-only ceiling ---------------------------------------------
    # Report and Analysis must not change anything, and "must not" has to mean
    # more than the prompt asking nicely. The model never sees a write tool in
    # these modes -- `modes.tools_for` removes them -- but the model is not the
    # only way a tool name arrives here: a stale conversation, a replayed
    # request, a future caller that builds `CommandRequest` itself. This check
    # is what makes the guarantee a property of the server rather than of the
    # model's cooperation.
    #
    # Stricter than the write gate below on purpose. That one asks "does this
    # need a human tap"; this one asks "does this leave the reception system
    # exactly as it found it", which also excludes dry-run planners. A planner
    # changes nothing, but a mode defined as retrieval has no business composing
    # an action either.
    if mode.read_only:
        not_read = [d for d in definitions if not modes.is_read_only_tool(registry.describe(d))]
        if not_read:
            _audit(
                request_id, request.source, request.device_id, context,
                "mode_is_read_only", text, decision=decision,
            )
            return {
                **_failure(
                    request_id,
                    "READ_ONLY_MODE",
                    f"حالت «{mode.label_fa}» فقط اطلاعات را می‌خواند. "
                    f"برای انجام این کار حالت «{modes.EXECUTIVE.label_fa}» را انتخاب کنید.",
                    started,
                    detail=(
                        f"mode '{mode.id}' is read_only; refused "
                        f"{[d.name for d in not_read]}"
                    ),
                ),
                "mode": mode.id,
            }

    # ---- the mode's ceiling ------------------------------------------------
    # A mode that may not act does not get to *ask* to act either. Offering a
    # confirmation the mode could never redeem would put a تأیید button in front
    # of a clinician for an operation that is going to be refused anyway -- and
    # a button that sometimes does nothing teaches people to tap without reading.
    writes = [d for d in definitions if requires_human_approval(d)]
    if writes and not mode.can_act:
        _audit(
            request_id, request.source, request.device_id, context,
            "mode_forbids_write", text, decision=decision,
        )
        return {
            **_failure(
                request_id,
                "WRITE_BLOCKED",
                f"حالت «{mode.label_fa}» فقط پیشنهاد می‌دهد و چیزی ثبت نمی‌کند.",
                started,
                detail=(
                    f"mode '{mode.id}' has can_act=False; refused "
                    f"{[d.name for d in writes]}"
                ),
            ),
            "mode": mode.id,
        }

    # ---- confirmation gate -------------------------------------------------
    # If ANY step writes, the WHOLE sequence waits. No half-applied workflows.
    if writes:
        steps = [
            {"tool": call.tool, "safety": definition.safety, "arguments": dict(call.arguments)}
            for call, definition in zip(decision.tool_calls, definitions)
        ]
        plan = confirmations.create(
            principal=context.principal,
            intent=decision.intent,
            steps=steps,
            summary_fa=_summary_fa(decision.tool_calls, definitions),
            effects=[effect for d in definitions for effect in d.effects_fa],
            request_id=request_id,
            mode=mode.id,
        )
        _audit(
            request_id, request.source, request.device_id, context,
            "confirmation_required", text, decision=decision, plan_id=plan.plan_id,
        )
        return {
            **_envelope(request_id, started),
            "success": False,
            "message": "تأیید می‌کنید؟",
            "action": {"tool": decision.tool_calls[-1].tool, "parameters": dict(decision.tool_calls[-1].arguments)},
            "requiresUserAction": True,
            "userAction": plan.as_dict(),
            "error": {"code": "CONFIRMATION_REQUIRED", "message": "Human approval required."},
            "mode": mode.id,
            "scenario": scenario.as_dict(),
        }

    # ---- execute (reads) ---------------------------------------------------
    # F11: an undated follow-up inherits the day this conversation established.
    # Below the write gate on purpose — a plan a human is about to approve keeps
    # the day the model named, and the arguments they see are the ones that run.
    calls, inherited_day = inherit_conversation_day(
        text,
        decision.tool_calls,
        request.facts,
        today=jalali.normalize_jalali_date(None),
    )
    return {
        **_run(
            request_id=request_id,
            text=text,
            source=request.source,
            device_id=request.device_id,
            calls=calls,
            definitions=definitions,
            context=context,
            registry=registry,
            started=started,
            chat=chat,
            decision=decision,
            idempotency_key=request.idempotency_key,
            mode=mode.id,
            history=request.history,
            facts=request.facts,
            reporter=reporter,
            inherited_day=inherited_day,
            evidence_sink=request.evidence_sink,
            session_evidence=request.session_evidence,
            attachment_source=attachment_source,
            attachments=request.attachments,
        ),
        # Echoed so the client can show which mode produced this answer. It is
        # the RESOLVED mode, not the requested one -- an older phone asking for
        # a mode this server does not have should be able to see that.
        "mode": mode.id,
        # The routing decision, its confidence and the terms that produced it.
        # Published while the layer is in SHADOW: nothing was narrowed by it, so
        # this records what WOULD have been chosen. That is the whole point of
        # the phase — a claim that classification is accurate has to be
        # measurable against real questions before it decides anything.
        "scenario": scenario.as_dict(),
    }


# ---------------------------------------------------------------------------
# Phase 2 — the human approved; redeem the plan exactly once and execute
# ---------------------------------------------------------------------------


def confirm(
    request: ConfirmRequest,
    context: DispatchContext,
    registry: ToolRegistry | None = None,
    chat: Any = None,
    confirmations: ConfirmationStore | None = None,
) -> dict[str, Any]:
    registry = registry or default_registry()
    confirmations = confirmations or default_store()
    request_id = request.request_id or _new_id("req")
    started = time.perf_counter()

    if not request.idempotency_key:
        # A write without an idempotency key is not a write we are willing to
        # make: a timeout would leave us unable to tell a retry from a second
        # appointment (docs/security-model.md §5).
        return _failure(
            request_id, "VALIDATION", "شناسهٔ یکتای درخواست الزامی است.", started,
            detail="idempotencyKey is required for confirmed writes.",
        )

    try:
        plan = confirmations.redeem(request.plan_id, context.principal)
    except ConfirmationError as exc:
        _audit(request_id, request.source, request.device_id, context, "confirmation_rejected", "", error=str(exc))
        return _failure(request_id, "CONFIRMATION_INVALID", "این تأیید معتبر نیست یا منقضی شده است.", started, detail=str(exc))

    calls = [ProposedCall(tool=step["tool"], arguments=dict(step.get("arguments") or {})) for step in plan.steps]
    try:
        definitions = [registry.get(call.tool) for call in calls]
    except ToolNotFoundError as exc:
        return _failure(request_id, "TOOL_NOT_FOUND", "این عملیات پشتیبانی نمی‌شود.", started, detail=str(exc))

    return _run(
        request_id=request_id,
        text=plan.summary_fa,
        source=request.source,
        device_id=request.device_id,
        calls=calls,
        definitions=definitions,
        context=context,
        registry=registry,
        started=started,
        chat=chat,
        decision=None,
        idempotency_key=request.idempotency_key,
        plan_id=plan.plan_id,
        # Carried on the plan rather than taken from this request: the mode that
        # matters is the one the action was composed under, which the human saw
        # and approved — not whatever mode the client happens to be in when it
        # taps تأیید a minute later.
        mode=plan.mode,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _run(
    *,
    request_id: str,
    text: str,
    source: str,
    device_id: str,
    calls: list[ProposedCall],
    definitions: list[ToolDefinition],
    context: DispatchContext,
    registry: ToolRegistry,
    started: float,
    chat: Any,
    decision: AgentDecision | None,
    idempotency_key: str | None,
    plan_id: str | None = None,
    mode: str | None = None,
    history: list[dict[str, str]] | None = None,
    facts: dict[str, Any] | None = None,
    reporter: progress.Reporter | None = None,
    #: Set when F11 fired: the day this turn took from the conversation rather
    #: than from the person's words. Carried here so the answer can say so —
    #: an inherited day is still a day nobody said out loud this turn.
    inherited_day: str | None = None,
    evidence_sink: list[dict[str, Any]] | None = None,
    session_evidence: dict[str, Any] | None = None,
    attachment_source: dict[str, Any] | None = None,
    attachments: tuple[Attachment, ...] = (),
) -> dict[str, Any]:
    # A Reporter with no conversation is a working object that publishes
    # nothing, so `confirm()` and the tests can omit it without every call site
    # growing a None check.
    reporter = reporter or progress.Reporter()
    steps = [{"tool": c.tool, "arguments": dict(c.arguments)} for c in calls]
    digest = payload_hash(steps)
    store = IdempotencyStore(Path(context.data_root)) if context.data_root else None

    # ---- idempotency: a replay returns the ORIGINAL result -----------------
    if store and idempotency_key:
        try:
            cached = store.lookup(idempotency_key, digest)
        except IdempotencyConflictError as exc:
            return _failure(request_id, "IDEMPOTENCY_CONFLICT", "این درخواست قبلاً با اطلاعات دیگری ثبت شده است.", started, detail=str(exc))
        if cached is not None:
            return {**cached, "requestId": request_id, "replayed": True, "latencyMs": _elapsed(started)}

    results: list[dict[str, Any]] = []
    audit_ids: list[str] = []
    for call, definition in zip(calls, definitions):
        reporter.fetched(definition.name)
        reused, saved_data, snapshot_at = _session_evidence_hit(
            session_evidence,
            definition.name,
            call.arguments,
            allow=(
                not _asks_for_fresh_data(text)
                and modes.is_read_only_tool(registry.describe(definition))
                and not requires_human_approval(definition)
            ),
        )
        if reused:
            results.append(
                {
                    "tool": definition.name,
                    "ok": True,
                    "data": saved_data,
                    "error": None,
                    "cached": True,
                    "session_snapshot_at": snapshot_at,
                }
            )
            continue
        outcome = dispatch(
            ToolCall(
                definition.name,
                _with_server_arguments(definition, call.arguments, context),
                request_id=request_id,
                idempotency_key=idempotency_key,
            ),
            registry=registry,
            context=context,
        )
        if outcome.audit_id:
            audit_ids.append(outcome.audit_id)
        results.append(
            {
                "tool": definition.name,
                "ok": outcome.ok,
                "data": outcome.data,
                "error": outcome.error,
                "cached": False,
                "session_snapshot_at": None,
            }
        )
        if not outcome.ok:
            _audit(request_id, source, device_id, context, "tool_error", text, decision=decision, plan_id=plan_id, mode=mode)
            error = outcome.error or {"code": "INTERNAL", "message": "Tool call failed."}
            return {
                **_envelope(request_id, started),
                "success": False,
                "message": _persian_error(error.get("code")),
                "result": {"steps": results} if len(results) > 1 else None,
                "action": {"tool": definition.name, "parameters": dict(call.arguments)},
                "error": error,
                "auditId": outcome.audit_id,
            }

    data = results[0]["data"] if len(results) == 1 else {"steps": results}
    primary = calls[-1]

    # ---- gather more, if this mode and this question warrant it ------------
    # `results` above is the interpreter's plan. For a retrieval question that
    # is the whole job. For "آیا ناسازگاری هست؟" it is a first look, and the
    # loop below asks whether it was enough before an answer is written on it.
    #
    # `data` deliberately stays the PRIMARY payload: the phone's `result` key
    # keeps its existing shape, and corroborating sources reach the answer
    # through `evidence` and the envelope's `sources` list instead.
    gathering = _gather_more(
        text=text,
        results=results,
        calls=calls,
        registry=registry,
        context=context,
        mode=mode,
        chat=chat,
        request_id=request_id,
        started=started,
        reporter=reporter,
        session_evidence=session_evidence,
        allow_session_reuse=not _asks_for_fresh_data(text),
    )
    crm_evidence = gathering.as_evidence() if gathering else [
        {
            "tool": r["tool"], "arguments": dict(c.arguments), "ok": r["ok"],
            "data": r["data"], "error": r["error"],
            **(
                {"sessionSnapshotAt": r["session_snapshot_at"]}
                if r.get("session_snapshot_at") else {}
            ),
        }
        for r, c in zip(results, calls)
    ]
    evidence = ([attachment_source] if attachment_source else []) + crm_evidence
    snapshot_times = _evidence_snapshot_times(evidence)
    snapshot_label = _snapshot_label(snapshot_times)
    if evidence_sink is not None:
        evidence_sink.extend(evidence)

    # ---- check the figures two sources both report, arithmetically ---------
    # Not by asking the model whether it noticed. It usually does; a miss is
    # silent, and a silent miss reads as "everything agreed".
    comparisons = source_catalog.compare(evidence)

    reporter.step(_narrative("نوشتن پاسخ…", "Writing the answer..."))
    message = ""
    try:
        message = summarize(
            text, primary.tool, data,
            chat=chat, mode=modes.get(mode), history=history, facts=facts,
            evidence=evidence if len(evidence) > 1 else None,
            comparisons=comparisons,
            session_snapshot_at=snapshot_label,
            attachments=attachments,
        )
    except Exception as exc:  # noqa: BLE001 - a summary failure must not lose the data
        # Swallowing this silently meant a broken analysis step looked exactly
        # like a working one: the caller still got the data plus the static
        # Persian fallback, and nothing anywhere said the LLM call had failed.
        # Log the type and message only — never the reply, which carries PHI.
        LOG.warning(
            "analysis step failed for tool %s (%s: %s); returning data with the fallback message",
            primary.tool,
            type(exc).__name__,
            exc,
        )
        message = ""

    # ---- what the user actually reads -------------------------------------
    # `result` above is the tool's own output: machine-readable, kept for the
    # client, the audit trail and support. `display` is the same answer written
    # for a person, in the documented `agent-md/1` dialect.
    #
    # The fallback matters more than the happy path. When the summarising call
    # fails, this used to return "نتیجه آماده است." and the data -- a true
    # sentence carrying no information, with the real answer one tap away as
    # raw JSON. Now the data is RENDERED, so a failed LLM call costs the
    # phrasing of the answer and not the answer.
    display, used_fallback = presentation.build_display(
        message,
        data,
        fallback_heading=_result_heading(primary.tool),
        inherited_day=inherited_day,
        session_snapshot_at=snapshot_label,
    )
    if used_fallback:
        LOG.info(
            "rendered the result directly for tool %s (no usable prose from the model)",
            primary.tool,
        )

    _audit(request_id, source, device_id, context, "ok", text, decision=decision, plan_id=plan_id, mode=mode)
    envelope = {
        **_envelope(request_id, started),
        "success": True,
        # Every refusal already said which mode produced it; the ANSWER did
        # not. So a client could learn the mode from being turned down and not
        # from being served, and a benchmark row recording "this was Analysis"
        # was recording the request, never the reply. `None` on the confirm
        # path, which does not carry the mode the plan was made in.
        "mode": mode,
        # `message` stays plain so a phone built before the renderer keeps
        # showing prose rather than starting to show `##` and `**` at people.
        "message": presentation.as_plain_text(display) or "نتیجه آماده است.",
        "display": display,
        "displayFormat": presentation.DISPLAY_FORMAT,
        "result": data,
        "action": {"tool": primary.tool, "parameters": dict(primary.arguments)},
        "auditId": audit_ids[-1] if audit_ids else None,
        # What this turn established about the session, for the caller to store.
        # Returned rather than written here because the orchestrator has no
        # conversation and no principal-scoped store -- the adapter that owns
        # the chat does.
        "sessionFacts": session_facts(calls),
        # Provenance, not payloads. Which sources this answer actually rests
        # on, whether each came back, and whether it was served from working
        # memory -- enough for support to reproduce an answer without putting a
        # second copy of the clinical rows on the wire.
        "sources": _provenance(gathering, evidence),
        **(
            {
                "sessionSnapshot": {
                    "reused": True,
                    "capturedAt": snapshot_times[-1],
                    **({"capturedAtAll": snapshot_times} if len(snapshot_times) > 1 else {}),
                }
            }
            if snapshot_times
            else {}
        ),
        # The server's own arithmetic across sources, published so a reader can
        # see what was checked -- including the checks that PASSED. "We compared
        # these and they agree" is the half nobody reports, and its absence is
        # what makes a silent miss invisible.
        **({"crossChecks": comparisons} if comparisons else {}),
        **(
            {"receivedAttachments": [item.public_metadata() for item in attachments]}
            if attachments else {}
        ),
        # Present only when F11 fired. Published rather than kept in the log so
        # a client, a reviewer or the benchmark can see that this turn's day
        # came from the conversation and not from the person's words — the same
        # reason `date_assumption` travels in the payload rather than a footnote.
        **({"inheritedDay": inherited_day} if inherited_day else {}),
        # Present whenever the loop ran at all, including when it decided one
        # source was enough. "We checked and stopped" and "we never checked"
        # are different facts, and only one of them is Report mode.
        **(
            {"gathering": {"rounds": gathering.rounds, "stopped": gathering.stopped_because,
                           "refused": [{"tool": r.tool, "reason": r.reason} for r in gathering.refused]}}
            if gathering is not None
            else {}
        ),
    }
    if store and idempotency_key:
        store.remember(idempotency_key, digest, envelope)
    # Told it is finished, so a poll already in flight stops rather than showing
    # "نوشتن پاسخ…" until the entry expires three minutes later.
    reporter.finish()
    return envelope


_FRESH_DATA_RE = re.compile(
    r"(?:"
    r"همین\s*الان|الان|لحظه[‌ ]?ای|به[‌ ]?روز|بروزرسان|به\s*روز\s*کن|"
    r"دوباره\s+(?:بررسی|چک|بخوان|بگیر|استعلام)|"
    r"(?:سرور|دیتابیس|پایگاه\s*داده|سامانه|نرم[‌ ]?افزار\s+پذیرش)\s*(?:را|رو)?\s*(?:بررسی|چک|بگرد|جستجو|جست‌وجو)|"
    r"مجدداً?\s+(?:بررسی|چک|بخوان|بگیر|استعلام)|بررسی\s+مجدد|از\s+نو|"
    r"آپدیت|تازه(?:‌ترین)?|جدیدترین|آخرین|"
    r"\b(?:refresh|recheck|check again|fetch again|right now|latest|current)\b"
    r")",
    re.IGNORECASE,
)


def _asks_for_fresh_data(text: str) -> bool:
    """Did the person explicitly ask to bypass the conversation snapshot?"""
    return bool(_FRESH_DATA_RE.search(str(text or "")))


def _reusable_session_data(data: Any) -> bool:
    """Empty/failed evidence cannot answer a later follow-up without a new read."""
    if not isinstance(data, dict) or not data:
        return False
    if data.get("error") or data.get("available") is False or data.get("raw_success") is False:
        return False
    if "rows" in data and not data["rows"]:
        return False
    return True


def _reporting_recovery_requests(results, calls) -> list[dict[str, Any]]:
    """One bounded independent read after a missing/invalid reporting cohort."""
    for result, call in zip(results, calls):
        if call.tool != "reporting-queue":
            continue
        data = result.get("data")
        if not isinstance(data, dict) or _reusable_session_data(data):
            continue
        start, end = call.arguments.get("startDate"), call.arguments.get("endDate")
        term = call.arguments.get("modality")
        # Never widen a patient/worklist-specific question to a whole day.
        if (not start or not end or not term
                or any(call.arguments.get(k) for k in
                       ("reception_id", "search", "status", "radiologist", "hasVoiceAttachment"))):
            continue
        error = data.get("error") or {}
        field = "service" if error.get("code") == "SERVICE_FILTER_REQUIRED" else "modality"
        return [{"tool": "reception.search",
                 "arguments": {"dateFrom": start, "dateTo": end, field: term, "limit": 1},
                 "why": "Verify the cohort independently; an empty worklist does not prove no physicians."}]
    return []


def _session_evidence_hit(
    session_evidence: Any,
    tool: str,
    arguments: dict[str, Any],
    *,
    allow: bool,
) -> tuple[bool, Any, str | None]:
    """Find one exact prior read result; ambiguity always falls back to live."""
    if not allow or not isinstance(session_evidence, dict):
        return False, None, None
    sources = session_evidence.get("sources")
    if not isinstance(sources, list):
        return False, None, None
    wanted = gather.WorkingMemory.key(tool, arguments)
    matches = [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("ok")
        and _reusable_session_data(source.get("data"))
        and gather.WorkingMemory.key(
            str(source.get("tool") or ""), source.get("arguments") or {}
        ) == wanted
    ]
    if len(matches) != 1:
        return False, None, None
    snapshot_at = matches[0].get("snapshotAt") or session_evidence.get("createdAt")
    return True, matches[0].get("data"), str(snapshot_at or "") or None


def _seed_session_memory(
    memory: gather.WorkingMemory, session_evidence: Any
) -> None:
    """Make all exact sources from the same snapshot available to gather."""
    if not isinstance(session_evidence, dict):
        return
    default_snapshot_at = str(session_evidence.get("createdAt") or "") or None
    sources = session_evidence.get("sources")
    if not isinstance(sources, list):
        return
    for source in sources:
        if (not isinstance(source, dict) or not source.get("ok")
                or not _reusable_session_data(source.get("data"))):
            continue
        tool = str(source.get("tool") or "").strip()
        arguments = source.get("arguments")
        # Attachment evidence is context for the model, not a dispatchable CRM
        # query and therefore never belongs in the exact-query cache.
        if tool == "user-attachment" or not tool or not isinstance(arguments, dict):
            continue
        memory.put(
            tool, arguments, source.get("data"),
            origin="session",
            snapshot_at=str(source.get("snapshotAt") or default_snapshot_at or "") or None,
        )


def _evidence_snapshot_times(evidence: Any) -> list[str]:
    if not isinstance(evidence, list):
        return []
    values = {
        str(item.get("sessionSnapshotAt"))
        for item in evidence
        if isinstance(item, dict) and item.get("sessionSnapshotAt")
    }
    return sorted(values)


def _snapshot_label(times: list[str]) -> str | None:
    if not times:
        return None
    if len(times) == 1:
        return times[0]
    return f"{times[0]} تا {times[-1]}"


def _provenance(
    gathering: gather.Gathering | None,
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Which sources the answer rests on -- in EVERY mode, not just Analysis.

    This used to read straight off the gathering loop, so Report mode published
    an empty list: the loop does not run there. An empty `sources` does not say
    "this mode keeps no fetch log"; it says "this answer rests on nothing", and
    a live run showed exactly that next to an answer built from the cashier
    report. Same failure shape as every other one in this system -- a true
    statement answering a question nobody asked.

    When the loop ran, its record is used as-is: it measured each fetch. When it
    did not, the same list is rebuilt from the calls that were dispatched, minus
    the fields nobody measured. `ms` is ABSENT rather than zero -- a missing key
    says "not measured", and a zero would say "answered instantly".
    """
    if gathering is not None:
        return [
            {
                "tool": f.tool,
                "arguments": {k: v for k, v in f.arguments.items() if k != "data_root"},
                "ok": f.ok,
                "cached": f.cached,
                **({"sessionCached": True} if f.session_cached else {}),
                **({"snapshotAt": f.snapshot_at} if f.session_cached and f.snapshot_at else {}),
                "ms": f.ms,
            }
            for f in gathering.fetched
        ]
    return [
        {
            "tool": item.get("tool"),
            "arguments": {k: v for k, v in (item.get("arguments") or {}).items() if k != "data_root"},
            "ok": bool(item.get("ok")),
            "cached": bool(item.get("sessionSnapshotAt")),
            **({"sessionCached": True} if item.get("sessionSnapshotAt") else {}),
            **({"snapshotAt": item.get("sessionSnapshotAt")} if item.get("sessionSnapshotAt") else {}),
        }
        for item in evidence
    ]


def _gather_more(
    *,
    text: str,
    results: list[dict[str, Any]],
    calls: list[ProposedCall],
    registry: ToolRegistry,
    context: DispatchContext,
    mode: str | None,
    chat: Any,
    request_id: str,
    started: float,
    reporter: progress.Reporter | None = None,
    session_evidence: dict[str, Any] | None = None,
    allow_session_reuse: bool = False,
) -> gather.Gathering | None:
    """Ask whether the first fetch was enough, and fetch what is missing.

    Returns None when this mode gets a single round, which is Report's normal
    case: a retrieval question has one right source, and a second model round
    would cost eight seconds to confirm what is already in hand.

    Every failure path here returns what was already fetched. The data exists;
    a broken assessor must cost thoroughness and never the answer.
    """
    mode_obj = modes.get(mode)
    reporter = reporter or progress.Reporter()
    budget = gather.Budget.for_mode(mode_obj)
    recovery = _reporting_recovery_requests(results, calls)
    if budget.rounds <= 1 and not recovery:
        return None

    memory = gather.WorkingMemory()
    if allow_session_reuse:
        _seed_session_memory(memory, session_evidence)
    gathering = gather.Gathering(rounds=1)
    for result, call in zip(results, calls):
        memory.put(
            call.tool,
            call.arguments,
            result["data"],
            origin="session" if result.get("cached") else "turn",
            snapshot_at=result.get("session_snapshot_at"),
        )
        gathering.fetched.append(
            gather.Fetched(
                tool=result["tool"],
                arguments=dict(call.arguments),
                ok=result["ok"],
                data=result["data"],
                error=result["error"],
                cached=bool(result.get("cached")),
                session_cached=bool(result.get("cached")),
                snapshot_at=result.get("session_snapshot_at"),
                why="the interpreter's plan",
            )
        )

    # The menu the model may choose from is the mode's, not the registry's. A
    # tool absent here is one this principal or this mode may not call, and the
    # loop must not be a way around that.
    try:
        offered = modes.tools_for(mode_obj, registry.list_for(context.principal))
    except Exception:  # noqa: BLE001 - a broken menu must not fail a done answer
        return gathering
    allowed_names = {t.get("name", "") for t in offered if isinstance(t, dict)}
    sources = source_catalog.catalog_for(sorted(allowed_names))

    if recovery:
        # New memory deliberately bypasses yesterday's/earlier empty evidence.
        # run_round still enforces mode, permission and the shared source budget.
        fetched, refused = gather.run_round(
            gather.normalise_requests(recovery), registry=registry, context=context, mode=mode_obj,
            allowed_names=allowed_names, memory=gather.WorkingMemory(),
            request_id=request_id, with_server_arguments=_with_server_arguments,
            remaining_sources=max(0, budget.sources - len(gathering.fetched)),
        )
        gathering.fetched.extend(fetched)
        gathering.refused.extend(refused)
        for item in fetched:
            reporter.fetched(item.tool)

    # ---- guarantee coverage for explicitly compound questions -------------
    # The assessor is advisory.  When the user names concrete axes such as
    # "per person: receptions, risk and deleted transactions", the server can
    # prove which sources are required before asking a model whether the data
    # feels sufficient.  This keeps role-specific evidence from disappearing
    # between turns while still respecting the mode and permission ceilings.
    required = source_catalog.plan_required_coverage(
        text,
        [(f.tool, dict(f.arguments)) for f in gathering.fetched],
        available=allowed_names,
        argument_sets=[dict(call.arguments) for call in calls],
        limit=max(0, budget.sources - len(gathering.fetched)),
    )
    if required:
        fetched, refused = gather.run_round(
            required,
            registry=registry,
            context=context,
            mode=mode_obj,
            allowed_names=allowed_names,
            memory=memory,
            request_id=request_id,
            with_server_arguments=_with_server_arguments,
            remaining_sources=budget.sources - len(gathering.fetched),
        )
        gathering.fetched.extend(fetched)
        gathering.refused.extend(refused)
        for f in fetched:
            reporter.fetched(f.tool)
        if fetched:
            LOG.info(
                "required evidence fetched %s before sufficiency assessment",
                ", ".join(f.tool for f in fetched),
            )

    # ---- corroborate first, without asking ---------------------------------
    # The catalog already knows which source can check the one just fetched.
    # Spending a model round to rediscover that costs six seconds to learn
    # something written down -- and the model does not reliably choose it:
    # tightening the assessor so it would stop over-fetching on retrieval
    # questions also stopped it fetching corroborating sources, and the
    # cash/card cross-check that had found a 43,710,000 discrepancy quietly
    # stopped firing. Nothing said so; the runs just showed "no cross-check
    # possible" where they used to show a mismatch.
    #
    # A report costs 7-835 ms. This is the cheapest evidence in the system.
    extra = source_catalog.plan_corroboration(
        [f.tool for f in gathering.fetched],
        available=allowed_names,
        arguments=dict(calls[-1].arguments) if calls else {},
        limit=max(0, min(2, budget.sources - len(gathering.fetched))),
    )
    if extra:
        fetched, refused = gather.run_round(
            extra,
            registry=registry,
            context=context,
            mode=mode_obj,
            allowed_names=allowed_names,
            memory=memory,
            request_id=request_id,
            with_server_arguments=_with_server_arguments,
            remaining_sources=budget.sources - len(gathering.fetched),
        )
        gathering.fetched.extend(fetched)
        gathering.refused.extend(refused)
        if fetched:
            for f in fetched:
                reporter.fetched(f.tool)
            LOG.info(
                "corroboration fetched %s without a model round",
                ", ".join(f.tool for f in fetched),
            )

    while gathering.rounds < budget.rounds:
        if (time.perf_counter() - started) > budget.seconds:
            gathering.stopped_because = "time budget"
            break
        if len(gathering.fetched) >= budget.sources:
            gathering.stopped_because = "source budget"
            break

        reporter.step(_narrative("بررسی کفایت داده‌ها…", "Checking whether the evidence is sufficient..."))
        verdict = interpret_assess(
            text,
            gathering.as_evidence(),
            catalog=source_catalog.describe_for_prompt(sources),
            cross_checks=source_catalog.cross_check_map(sources),
            mode=mode_obj,
            chat=chat,
        )
        if verdict.get("sufficient"):
            gathering.stopped_because = "sufficient"
            break

        requests = gather.normalise_requests(verdict.get("fetch"))
        if not requests:
            gathering.stopped_because = "nothing further named"
            break

        fetched, refused = gather.run_round(
            requests,
            registry=registry,
            context=context,
            mode=mode_obj,
            allowed_names=allowed_names,
            memory=memory,
            request_id=request_id,
            with_server_arguments=_with_server_arguments,
            remaining_sources=budget.sources - len(gathering.fetched),
        )
        gathering.fetched.extend(fetched)
        gathering.refused.extend(refused)
        # Name them on the phone, exactly as the corroboration branch above
        # does. Without this the progress line under-reported: a live Analysis
        # run read three sources and told the reader about two, so the caption
        # was a partial account of the work presented as the whole of it —
        # which is the same defect as an empty `sources` list, one layer up.
        for f in fetched:
            reporter.fetched(f.tool)
        gathering.rounds += 1
        LOG.info(
            "gather round %d for '%s': +%d source(s), %d refused (%s)",
            gathering.rounds, mode_obj.id, len(fetched), len(refused),
            verdict.get("reasoning", ""),
        )
        if not fetched:
            gathering.stopped_because = "nothing new could be fetched"
            break
    else:
        gathering.stopped_because = "round budget"

    return gathering


#: Heading used when the answer has to be rendered from the data. Keyed by tool
#: so the fallback still names what the reader is looking at, rather than
#: leading with a generic "نتیجه" that could be anything.
_RESULT_HEADINGS: dict[str, str] = {
    "daily-summary": "خلاصهٔ روز",
    "financial-analysis": "گزارش مالی",
    # The two are named apart on purpose. They used to share "گزارش صندوق",
    # which is the name of only one of them: a variance check headed "cashier
    # report" reads as the cashier report and is not.
    "cashier-report": "گزارش صندوق",
    "cashier-reconciliation": "تطبیق صندوق",
    "physician-performance": "حجم کاری پزشکان",
    "trend-analysis": "روند",
    "risk-analysis": "تحلیل ریسک",
    "reporting-queue": "صف گزارش‌نویسی",
    "report.search": "نتیجهٔ جست‌وجوی گزارش‌ها",
    "report.get": "گزارش بیمار",
    "report.history": "سابقهٔ گزارش‌های بیمار",
    "report.archive-stats": "آمار آرشیو گزارش‌ها",
    "patients.search": "نتیجهٔ جست‌وجوی بیماران",
    "patient-list": "فهرست بیماران",
    "appointments.list": "نوبت‌ها",
}


def _result_heading(tool: str) -> str:
    return _RESULT_HEADINGS.get(tool, "نتیجه")


#: Tool arguments worth remembering as "what this conversation is about", mapped
#: to the label the model sees.
#:
#: An allow-list, not a filter. Copying every argument would sweep whatever a
#: future tool happens to accept into a blob that is stored AND re-sent to the
#: provider on every subsequent turn -- which is how a referent quietly becomes
#: a patient record. Adding a key here is a deliberate act.
_FACT_KEYS: dict[str, str] = {
    "nationalCode": "patient national code",
    "receptionId": "reception id",
    "patientId": "patient id",
    "dateFrom": "date range from",
    "dateTo": "date range to",
    "date": "date",
    "query": "last search phrase",
    "modality": "modality",
}


#: Argument names that carry a single day. `dateFrom`/`dateTo` are a range and
#: are only touched when they name the SAME day — a real range is a period the
#: person asked for, not a defaulted day.
_SINGLE_DAY_KEYS = ("date", "day")


def inherit_conversation_day(
    text: str,
    calls: list[ProposedCall],
    facts: dict[str, Any] | None,
    *,
    today: str,
) -> tuple[list[ProposedCall], str | None]:
    """F11: let the day this conversation established win over today.

    Returns the calls to dispatch and, when it fired, the inherited day.

    Three conditions, all of them necessary, and each one is the reason a
    simpler version of this would be wrong:

    1. **The conversation established an absolute day.** Read from the session
       facts, which the SERVER wrote from dispatched arguments — so this cannot
       be moved by a model that misremembers the conversation.
    2. **The person's own words said nothing about time.** `text_names_a_day`
       fails closed: anything time-shaped means they spoke, and a day from three
       turns ago must never be substituted over what they said.
    3. **The model actually defaulted to today.** If it chose any other day it
       had a reason this function cannot see, and overwriting that would be
       replacing one guess with another.

    Deliberately NOT applied on the write path. A write goes to a human for
    approval, and the summary that human reads is built from these arguments —
    but a silent argument change is worst exactly where the consequence is a
    record, so writes keep the day the model named and nothing is inherited.
    """
    day = jalali.conversation_day(facts)
    if not day or day == today or jalali.text_names_a_day(text):
        return calls, None

    rewritten: list[ProposedCall] = []
    fired = False
    for call in calls:
        arguments = dict(call.arguments)
        changed = False
        for key in _SINGLE_DAY_KEYS:
            if _means_today(arguments.get(key), today):
                arguments[key] = day
                changed = True
        if _means_today(arguments.get("dateFrom"), today) and _means_today(
            arguments.get("dateTo"), today
        ):
            arguments["dateFrom"] = day
            arguments["dateTo"] = day
            changed = True
        if changed:
            fired = True
            rewritten.append(ProposedCall(tool=call.tool, arguments=arguments))
        else:
            rewritten.append(call)

    if not fired:
        return calls, None
    LOG.info(
        "undated follow-up: inherited the conversation's day %s in place of today %s",
        day,
        today,
    )
    return rewritten, day


def _means_today(value: Any, today: str) -> bool:
    """Does this argument name today — as a literal date or as the word?"""
    if value in (None, ""):
        return False
    text = str(value).strip()
    if text.lower() == "today":
        return True
    try:
        return jalali.normalize_jalali_date(text) == today
    except (ValueError, IndexError):
        return False


def session_facts(calls: list[ProposedCall]) -> dict[str, Any]:
    """What the tools this turn were ACTUALLY called with.

    Read from the dispatched arguments, never from the model's prose or its
    stated intent. The distinction is the whole value: the session's idea of
    "this patient" is then a record of what was really queried, and a model that
    misremembers cannot corrupt it.
    """
    facts: dict[str, Any] = {}
    for call in calls:
        for key, label in _FACT_KEYS.items():
            value = call.arguments.get(key)
            if value in (None, "", [], {}):
                continue
            text = " ".join(str(value).split())
            if text:
                facts[label] = text[:120]
    if facts:
        facts["last tool"] = calls[-1].tool
    return facts


def _with_server_arguments(
    definition: ToolDefinition, arguments: dict[str, Any], context: DispatchContext
) -> dict[str, Any]:
    """Inject the server-owned arguments the model is forbidden to send.

    ``data_root`` is a path on the CRM machine. It is stripped from the schemas
    the model sees and rejected if the model sends it — so the server puts it
    back here, right before dispatch.
    """
    merged = dict(arguments)
    properties = (definition.input_schema or {}).get("properties") or {}
    if "data_root" in properties and context.data_root is not None:
        merged["data_root"] = str(context.data_root)
    return merged


def _summary_fa(calls: list[ProposedCall], definitions: list[ToolDefinition]) -> str:
    """The sentence the human reads before tapping تأیید.

    Built from the tool's own template and the *exact* arguments that will be
    sent — never from prose the model wrote, which it could use to describe one
    action while performing another.
    """
    lines = []
    for call, definition in zip(calls, definitions):
        template = definition.confirmation_summary_fa
        if template:
            arguments = call.arguments if isinstance(call.arguments, dict) else {}
            missing = [key for key in _template_keys(template) if key not in arguments]
            if missing:
                # Every template slot used to be pre-filled with an em-dash so
                # that `.format()` could not raise. It could not — and that was
                # the defect, not the protection: a call that named the wrong
                # argument rendered as «لغو پذیرش —» and a human was asked to
                # approve it. The sentence still looked like a confirmation
                # while it had stopped naming what would happen.
                #
                # An unfilled slot in a confirmation is exactly the case that
                # must not be papered over, so the plain form is used instead —
                # it shows the arguments that will actually be sent.
                LOG.warning(
                    "confirmation template for %s is missing %s; showing the "
                    "arguments plainly instead of a placeholder",
                    definition.name, missing,
                )
            else:
                try:
                    lines.append(template.format(**arguments))
                    continue
                except Exception as exc:  # noqa: BLE001 - fall back, but not to less
                    LOG.warning(
                        "confirmation template for %s could not be formatted (%s: %s); "
                        "showing the arguments plainly instead",
                        definition.name, type(exc).__name__, exc,
                    )
        lines.append(_fallback_summary_fa(definition, call))
    return "\n".join(lines)


def _fallback_summary_fa(definition: ToolDefinition, call: ProposedCall) -> str:
    """What to show when the tool has no confirmation template, or it failed.

    The description alone names the KIND of action; a human approving a write
    needs the subject of it too. Arguments are rendered as `key: value` pairs
    in the order the model sent them, with no interpretation — this runs on the
    path where interpretation has already gone wrong once.
    """
    head = definition.description or definition.name
    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    if not arguments:
        return head
    detail = "، ".join(f"{key}: {value}" for key, value in arguments.items())
    return f"{head} ({detail})"


def _template_keys(template: str) -> list[str]:
    import string

    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


_PERSIAN_ERRORS = {
    "PERMISSION_DENIED": "شما اجازهٔ این عملیات را ندارید.",
    "VALIDATION": "اطلاعات دستور کامل یا معتبر نیست.",
    "TOOL_NOT_FOUND": "این عملیات پشتیبانی نمی‌شود.",
    "CONFIRMATION_REQUIRED": "این عملیات نیاز به تأیید دارد.",
    "WRITE_BLOCKED": "ثبت تغییرات از موبایل هنوز فعال نشده است.",
    "AUTH_EXPIRED": "نشست شما منقضی شده است. دوباره وارد شوید.",
}


def _persian_error(code: Any) -> str:
    return _PERSIAN_ERRORS.get(str(code), "اجرای دستور با خطا مواجه شد.")


def _envelope(request_id: str, started: float) -> dict[str, Any]:
    return {
        "requestId": request_id,
        # Which build produced this answer. On the base envelope, so it is on
        # every response including refusals, and never on some paths only.
        #
        # Without it an answer is not attributable: the benchmark records score
        # "server 1.16.4" because that was the name of the installer someone
        # copied over, not because anything in the reply said so. A defect
        # closed against a build and a score earned by a build both need the
        # build to have identified itself.
        "serverVersion": __version__,
        "success": False,
        "message": "",
        "result": None,
        "action": None,
        "requiresUserAction": False,
        "userAction": None,
        "error": None,
        "auditId": None,
        "latencyMs": _elapsed(started),
    }


def _failure(request_id: str, code: str, message: str, started: float, detail: str | None = None) -> dict[str, Any]:
    return {
        **_envelope(request_id, started),
        "success": False,
        "message": message,
        "error": {"code": code, "message": detail or message},
    }


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _audit(
    request_id: str,
    source: str,
    device_id: str,
    context: DispatchContext,
    status: str,
    text: str,
    decision: AgentDecision | None = None,
    error: str | None = None,
    plan_id: str | None = None,
    mode: str | None = None,
) -> None:
    """Audit the command turn itself (each tool call is audited separately).

    PHI: a Persian command can contain a patient name or a national code, so the
    text is HASHED, never stored (docs/security-model.md §6).
    """
    definition = ToolDefinition(
        name="agent.command",
        kind="agent",
        handler=lambda _args: None,
        description="Natural-language agent command",
        safety="read",
        permission_action="read",
    )
    call = ToolCall(
        "agent.command",
        {
            "source": source,
            "device_id": device_id,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text_chars": len(text),
            "intent": decision.intent if decision else None,
            "tools": [c.tool for c in decision.tool_calls] if decision else [],
            "confidence": decision.confidence if decision else None,
            "llm_usage": decision.usage if decision else None,
            "plan_id": plan_id,
            "mode": mode,
            "error": error,
        },
        request_id=request_id,
    )
    try:
        audit_dispatch("agent_command", definition, call, context, status)
    except Exception:  # noqa: BLE001 - audit must not crash the request path
        pass
