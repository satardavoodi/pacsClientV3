"""Mobile HTTP adapter.

An adapter does exactly three things (docs/client-adapters.md §1):
  1. authenticate the caller  → Principal
  2. translate transport      → build the request, call the core
  3. relay a human confirmation back to the core

It contains no CRM knowledge, no tool list, no permission rule, and no idea what
``appointments.schedule`` means. If that stops being true, the change is wrong.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from http import HTTPStatus
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..agent_router import route_command
from ..build_provenance import build_info
from .. import scenarios
from .. import snapshots as snapshot_store
from ..core import conversations as convo
from ..core import identity
from ..core import modes
from ..core import progress
from ..core.attachments import Attachment, AttachmentError, decode_attachments
from ..core.dispatcher import dispatch
from ..core.orchestrator import CommandRequest, ConfirmRequest, confirm, handle_command
from ..core.registry import default_registry
from ..core.types import DispatchContext, Principal, ToolCall
from ..llm import client as llm_client
from .. import politeness
from ..runtime import data_root
from ..settings import resolve_center

# NOTE: resolved per-request via ``data_root()`` rather than captured at import
# time from ``__file__``. Under PyInstaller ``__file__`` points into the
# temporary extraction directory, so the previous module-level PROJECT_ROOT
# made a packaged server write clinical data to a folder Windows deletes on
# exit. See ``reception_crm/runtime.py``.

# Identity is never an argument (docs/security-model.md §2).
IDENTITY_KEYS = {"user", "center", "roles", "userId", "principal"}
LOG = logging.getLogger(__name__)


#: Snapshot accounting is cached: `/api/health` is polled, and walking a
#: growing tree of thousands of files on every poll would make the health check
#: itself the disk load it is reporting on.
_FOOTPRINT_TTL_SECONDS = 300.0
_footprint_cache: dict[str, Any] = {}

# 16 MiB of decoded attachments expands by roughly one third in base64. Leave
# room for the JSON envelope while refusing the allocation before reading it.
MAX_JSON_BODY_BYTES = 24 * 1024 * 1024


def snapshot_footprint() -> dict[str, Any]:
    """How much of the clinical disk our raw snapshots occupy.

    Every management tool writes the payload it received to
    ``<data_root>/data/raw`` so an answer can be reproduced against exactly what
    the agent saw. Nothing prunes them, and the gathering loop multiplied the
    write rate: one question can now fetch up to eight sources.

    They are not deleted here. A snapshot is the ONLY record of what a moving
    system looked like at the moment an answer was given -- re-fetching gives
    different numbers -- so it is audit evidence, and audit evidence is not
    something a health check should quietly bin. Reported instead, so the
    growth is visible before it is a problem.
    """
    now = time.time()
    cached = _footprint_cache.get("value")
    if cached and (now - _footprint_cache.get("at", 0)) < _FOOTPRINT_TTL_SECONDS:
        return cached

    root = Path(data_root()) / "data" / "raw"
    out: dict[str, Any] = {"root": str(root)}
    try:
        # Counted by `snapshots.footprint` so compacted files are included.
        # Counting only `*.json` would have shown the tree shrinking to nothing
        # as compaction ran, which is the opposite of what is happening to it.
        out.update(snapshot_store.footprint(root))
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"

    _footprint_cache["value"] = out
    _footprint_cache["at"] = now
    return out


def center_catalog_status() -> dict[str, Any]:
    """Small, PHI-free readiness view of the installation-owned service map."""
    from ..lexicon import center as center_lexicon

    config = center_lexicon.load_center()
    if config.get("available") is False:
        return {"available": False, "reason": config.get("reason")}
    counts_raw = config.get("counts")
    counts: dict[str, Any] = counts_raw if isinstance(counts_raw, dict) else {}
    return {
        "available": True,
        "center": config.get("center"),
        "generated_at": config.get("generated_at"),
        "services": counts.get("services", len(config.get("services") or [])),
        "service_concepts": len(config.get("service_concepts") or []),
    }


class BadRequest(ValueError):
    """A request that could not be parsed at all.

    Raised by `read_json` and answered as 400 by `do_POST`. It exists so that
    "we could not read what you sent" is a REPLY rather than a dropped socket:
    an exception escaping a handler thread produces no response and no log
    line, which reads from outside exactly like a crashed server.
    """


class HttpApiHandler(BaseHTTPRequestHandler):
    server_version = "ReceptionHttpApi/0.2"

    # ---- GET ---------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.respond_json(
                {
                    "status": "ok",
                    "service": "reception-http-api",
                    # Which build is actually answering. Without this the only
                    # evidence of what is deployed is the name of the installer
                    # someone copied over, which is not evidence about the
                    # process that is running.
                    "version": __version__,
                    # Which interpreter produced this build and what it had
                    # available. A release once changed size by 5.8 MB with no
                    # code change because the build was handed a virtualenv
                    # missing `cryptography`; nothing on the running server
                    # could have been asked about it.
                    "build": build_info(),
                    "tool_count": len(default_registry().tools),
                    "llm_configured": llm_client.is_configured(),
                    "center_catalog": center_catalog_status(),
                    "writes_enabled": os.getenv("RECEPTION_ENABLE_WRITES") == "true",
                    "agent_endpoint": "/api/agent/command",
                    # What this agent is costing the machine it borrows. Both
                    # numbers exist because neither is self-limiting: the API
                    # gate bounds how much of the reception system we occupy at
                    # once, and the snapshot tree grows every time a tool runs
                    # and is pruned by nothing.
                    "reception_api": politeness.reception_gate.status(),
                    "snapshots": snapshot_footprint(),
                    "bind_note": "Use 127.0.0.1 for local development; use TLS before LAN/mobile production.",
                }
            )
            return

        if parsed.path == "/api/agent/progress":
            # What the agent is doing right now, for a phone that is waiting on
            # an answer. Decoration: the result arrives on the POST either way,
            # so an empty reply here means "nothing to show", never an error.
            principal = self.authenticate()
            if principal is None:
                return
            conversation_id = parse_qs(parsed.query).get("conversationId", [""])[0]
            step = progress.board.read(principal, conversation_id)
            self.respond_json({"ok": True, "progress": step})
            return

        if parsed.path == "/api/modes":
            # Deliberately UNauthenticated and deliberately server-owned: the
            # mobile app renders whatever list it gets, so adding a mode to the
            # registry gives every phone the new mode without a new APK. Nothing
            # here is per-user or sensitive — it is the menu, not the data.
            self.respond_json(
                {
                    "modes": [m.as_dict() for m in modes.all_modes()],
                    "default": modes.DEFAULT_MODE,
                }
            )
            return

        if parsed.path == "/api/scenarios":
            # Same contract and the same reasoning as `/api/modes`: the phone
            # renders the quick actions the server publishes, so a new scenario
            # — or a reworded quick action — reaches every phone without a new
            # APK. `Scenario.as_dict` omits the server-side fields (reports,
            # database paths, validation rules), so this is the menu, not the
            # architecture.
            #
            # `applied` says whether routing currently decides anything. While
            # it is false the layer is in shadow: the server classifies and
            # reports, and a client that dimmed its UI on the strength of a
            # scenario would be dimming it on a decision nothing acted on.
            self.respond_json(
                {
                    "scenarios": [s.as_dict() for s in scenarios.all_scenarios()],
                    "fallback": scenarios.FALLBACK_SCENARIO,
                    "applied": False,
                }
            )
            return

        if parsed.path == "/api/tools":
            principal = self.authenticate()
            if principal is None:
                return
            # Filtered by principal: a role should not even see what it may not call.
            self.respond_json(
                {"tools": default_registry().list_for(principal), "principal": principal_dict(principal)}
            )
            return

        self.respond_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    # ---- POST --------------------------------------------------------------

    def do_POST(self) -> None:
        """Route, and turn an unparseable request into a 400 rather than silence.

        Without this, a body that is not valid UTF-8 or not valid JSON raised
        inside the handler thread: `BaseHTTPRequestHandler` writes no response,
        `log_message` is a no-op, and the caller sees the socket close. From the
        outside that is indistinguishable from the server having crashed -- and
        it sent a real debugging session looking through a service log that had
        nothing wrong in it. A request we cannot parse is a client error, and it
        should say so.
        """
        try:
            self.route_post()
        except BadRequest as exc:
            self.respond_json(
                {"success": False, "error": {"code": "VALIDATION", "message": str(exc)}},
                HTTPStatus.BAD_REQUEST,
            )

    def route_post(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/session":
            self.handle_session()
            return
        if parsed.path == "/api/session/logout":
            self.handle_logout()
            return
        if parsed.path == "/api/agent/command":
            self.handle_agent_command()
            return
        if parsed.path == "/api/confirm":
            self.handle_confirm()
            return
        if parsed.path == "/api/dispatch":
            self.handle_dispatch()
            return
        # Conversations are action-endpoints rather than REST paths for the same
        # reason log_message() is a no-op: an id belongs in a body, not in a URL
        # that proxies and access logs will happily record.
        if parsed.path.startswith("/api/conversations/"):
            self.handle_conversations(parsed.path.rsplit("/", 1)[-1])
            return

        if parsed.path == "/api/command":
            principal = self.authenticate()
            if principal is None:
                return
            payload = self.read_json()
            result = route_command(
                text=str(payload.get("text") or ""),
                user=principal.user,
                center=principal.center,
                inputs=payload.get("inputs") or {},
            )
            result["adapter_warning"] = (
                "DEPRECATED: keyword routing, executes nothing. "
                "Use POST /api/agent/command (LLM + orchestrator) instead."
            )
            self.respond_json(result)
            return

        self.respond_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    # ---- handlers ----------------------------------------------------------

    def handle_session(self) -> None:
        """Username + password → a per-user session token.

        The CRM proves the identity; config/roles.json grants the authority. The
        password is used once and never stored, logged, or audited.
        """
        payload = self.read_json()
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")

        if not username or not password:
            # Legacy path: the shared gateway token. Kept only so the current
            # Android build keeps working while it migrates to real sessions.
            principal = self.legacy_principal()
            if principal is None:
                self.respond_json(
                    {"ok": False, "error": {"code": "VALIDATION", "message": "username and password are required"}},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self.respond_json({"ok": True, "principal": principal_dict(principal), "legacy": True})
            return

        # The center belongs to THIS DEPLOYMENT, not to the caller. One gateway
        # serves one center, named by RECEPTION_CENTER / RECEPTION_HTTP_API_CENTER
        # (or server.json), and a client already chooses its center by choosing
        # which gateway URL to talk to -- so the field is redundant on the wire.
        #
        # It was worse than redundant: identity.login() passed it straight into
        # roles_for(), so the value a phone sent decided WHICH roles.json row was
        # consulted. That is the same class of defect as the identity smuggling
        # this adapter refuses two functions up. It also broke real logins -- the
        # Android client sends ServerProfile.id, an internal profile key the user
        # cannot edit ("CENTER" on a fresh install), so a correctly configured
        # user was rejected with "no role ... for center CENTER".
        #
        # Any client-supplied center is therefore ignored, not trusted and not
        # rejected: rejecting would break installed builds over a field that
        # carries no authority anyway.
        try:
            session = identity.login(
                username=username,
                password=password,
                center=resolve_center(),
                device_id=str(payload.get("deviceId") or ""),
            )
        except identity.AuthError as exc:
            self.respond_json(
                {"ok": False, "error": {"code": "UNAUTHORIZED", "message": str(exc)}},
                HTTPStatus.UNAUTHORIZED,
            )
            return

        self.respond_json(
            {
                "ok": True,
                "accessToken": session.token,
                "expiresAt": session.expires_at,
                "sessionId": session.session_id,
                "principal": principal_dict(session.principal),
            }
        )

    def handle_logout(self) -> None:
        token = bearer_token(self.headers.get("Authorization")) or str(self.read_json().get("accessToken") or "")
        identity.revoke(token)
        self.respond_json({"ok": True})

    def handle_agent_command(self) -> None:
        """The mobile entry point: text in (typed or transcribed), result out."""
        principal = self.authenticate()
        if principal is None:
            return
        payload = self.read_json()
        if not self.reject_identity_keys(payload):
            return

        text = str(payload.get("text") or "")
        preference = payload.get('language_preference', 'en')
        if preference not in ('fa', 'en'):
            raise BadRequest('language_preference must be fa or en.')
        try:
            attachments = decode_attachments(payload.get("attachments"))
        except AttachmentError as exc:
            raise BadRequest(str(exc)) from None
        conversation_id = str(payload.get("conversationId") or "")
        store = convo.default_store(data_root()) if conversation_id else None

        # With a conversation, the SERVER supplies the history. A phone may hold
        # a stale or edited mirror, and history is what the model reasons over —
        # letting the client write it would let a client rewrite the past.
        history = payload.get("history") if isinstance(payload.get("history"), list) else None
        facts: dict[str, Any] | None = None
        session_evidence: dict[str, Any] | None = None
        # Canonicalised here, once, so a phone still saying "order" is compared
        # against, persisted as, and answered in "executive" -- rather than the
        # comparison below finding a difference on every single turn and
        # rewriting the row each time with a value the store then renames back.
        mode = modes.canonical(payload.get("mode") or "")
        if store is not None:
            try:
                conversation = store.get(principal, conversation_id)
                history = store.history_for_llm(principal, conversation_id)
                # What earlier turns established. Read BEFORE this turn runs, so
                # the referent the model resolves is the one that was already
                # true and not one this turn is in the middle of changing.
                facts = store.facts_for_llm(principal, conversation_id)
                # Complete results stay local to the clinic.  The model gets a
                # small inventory for tool selection, while the orchestrator
                # may reuse the exact owned snapshot for a read-only follow-up.
                # A broken artifact is not a broken conversation: the store
                # fails soft and this turn simply reads fresh CRM data.
                session_evidence = store.latest_evidence_for_llm(
                    principal, conversation_id
                )
                # The conversation carries the mode. A request may override it —
                # that is the user tapping the selector — and the override is
                # PERSISTED, so reopening the chat later resumes in the mode it
                # was actually being used in rather than the one it was born in.
                if mode and modes.is_known(mode) and mode != conversation["mode"]:
                    store.set_mode(principal, conversation_id, mode)
                elif not mode:
                    mode = conversation["mode"]
                stored_text = text.strip() or "بررسی فایل پیوست"
                if attachments:
                    names = "، ".join(item.display_name for item in attachments)
                    stored_text = f"{stored_text}\n[پیوست: {names}]"
                store.append_turn(principal, conversation_id, role="user", text=stored_text)
            except convo.ConversationNotFound as exc:
                self.respond_json(
                    {"success": False, "error": {"code": exc.code, "message": str(exc)}},
                    HTTPStatus.NOT_FOUND,
                )
                return

        analysis_evidence: list[dict[str, Any]] = []
        result = handle_command(
            CommandRequest(
                text=text,
                language_preference=preference,
                request_id=str(payload.get("requestId") or ""),
                source=str(payload.get("source") or "unknown"),
                device_id=str(payload.get("deviceId") or ""),
                client_version=str(payload.get("clientVersion") or ""),
                history=history,
                facts=facts,
                session_evidence=session_evidence,
                idempotency_key=payload.get("idempotencyKey"),
                mode=mode or modes.DEFAULT_MODE,
                conversation_id=conversation_id,
                evidence_sink=analysis_evidence if store is not None else None,
                attachments=attachments,
            ),
            context=self.context_for(principal),
        )

        # Server-internal, and removed before the envelope goes anywhere: what
        # this turn established about the session. The phone already has the
        # answer it was shown; a key carrying patient identifiers alongside it
        # would be a second copy on the wire that nothing on the phone reads.
        # Popped unconditionally so a conversation-less request cannot leak it.
        session_facts = result.pop("sessionFacts", None)

        if store is not None:
            result["conversationId"] = conversation_id
            self.remember_session_facts(store, principal, conversation_id, session_facts)
            assistant_turn = self.record_agent_turn(
                store, principal, conversation_id, result
            )
            if assistant_turn is not None:
                analysis = HttpApiHandler.record_agent_analysis(
                    store,
                    principal,
                    conversation_id,
                    assistant_turn["id"],
                    result,
                    analysis_evidence,
                    attachments,
                )
                if analysis is not None:
                    result["analysis"] = analysis

        # Always HTTP 200: the envelope carries the outcome. A clarification or a
        # confirmation is not a transport failure.
        self.respond_json(result)

    @staticmethod
    def remember_session_facts(
        store: convo.ConversationStore,
        principal: Principal,
        conversation_id: str,
        facts: Any,
    ) -> None:
        """File what this turn was actually about, for the turns that follow.

        This is what lets the next message say "his report" or "the same day"
        and be resolved against what was really queried, rather than against
        whatever the model happens to still have in view.

        Best-effort, for the same reason as ``record_agent_turn``: the answer is
        already computed and correct. Failing to file a referent costs the NEXT
        turn some context; it is not a reason to fail this one.
        """
        if not isinstance(facts, dict) or not facts:
            return
        try:
            store.remember_facts(principal, conversation_id, facts)
        except convo.ConversationError:
            pass

    @staticmethod
    def record_agent_turn(
        store: convo.ConversationStore,
        principal: Principal,
        conversation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist the narrow assistant turn; large data is attached separately."""
        action = result.get("action") or {}
        try:
            return store.append_turn(
                principal,
                conversation_id,
                role="assistant",
                text=str(result.get("message") or ""),
                tool=action.get("tool"),
                arguments=action.get("parameters"),
                result_ids=_result_ids(result.get("result")),
                result_count=_result_count(result.get("result")),
                request_id=str(result.get("requestId") or ""),
                audit_id=result.get("auditId"),
            )
        except convo.ConversationError:
            # The answer is already computed and correct. Failing to file it is
            # a history gap, not a reason to withhold the result from the user.
            return None

    @staticmethod
    def record_agent_analysis(
        store: convo.ConversationStore,
        principal: Principal,
        conversation_id: str,
        turn_id: str,
        result: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> dict[str, Any] | None:
        """Best-effort durable copy of the exact response and useful tables."""
        try:
            return store.record_analysis(
                principal,
                conversation_id,
                turn_id,
                dict(result),
                evidence=evidence,
                attachments=attachments,
            )
        except Exception as exc:  # noqa: BLE001 - response must still reach caller
            # Do not log identifiers, paths or payloads; only the failure class.
            LOG.warning("Could not persist agent analysis: %s", type(exc).__name__)
            return None

    # ---- conversations -----------------------------------------------------

    CONVERSATION_ACTIONS = {"create", "list", "get", "sync", "update", "delete"}

    def handle_conversations(self, action: str) -> None:
        """The chat list the phone mirrors. Every call is scoped to the session.

        The principal is never taken from the body — the store keys on it, so a
        body-supplied user would be a way to read another clinician's chats.
        """
        principal = self.authenticate()
        if principal is None:
            return
        if action not in self.CONVERSATION_ACTIONS:
            self.respond_json(
                {"ok": False, "error": {"code": "NOT_FOUND", "message": f"unknown action: {action}"}},
                HTTPStatus.NOT_FOUND,
            )
            return

        payload = self.read_json()
        if not self.reject_identity_keys(payload):
            return

        store = convo.default_store(data_root())
        conversation_id = str(payload.get("conversationId") or "")
        try:
            body = self.run_conversation_action(store, principal, action, conversation_id, payload)
        except convo.ConversationNotFound as exc:
            self.respond_json(
                {"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                HTTPStatus.NOT_FOUND,
            )
            return
        except convo.ConversationError as exc:
            self.respond_json(
                {"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                HTTPStatus.BAD_REQUEST,
            )
            return
        self.respond_json({"ok": True, **body})

    def run_conversation_action(
        self,
        store: convo.ConversationStore,
        principal: Principal,
        action: str,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "create":
            return {
                "conversation": store.create(
                    principal,
                    title=str(payload.get("title") or ""),
                    mode=payload.get("mode") or convo.DEFAULT_MODE,
                )
            }

        if action == "list":
            return {
                "conversations": store.list(
                    principal,
                    include_archived=bool(payload.get("includeArchived")),
                    limit=payload.get("limit") or convo.DEFAULT_PAGE,
                )
            }

        if action == "sync":
            return store.changed_since(
                principal,
                payload.get("sinceRevision") or 0,
                limit=payload.get("limit") or convo.MAX_PAGE,
            )

        if action == "get":
            return {
                "conversation": store.get(principal, conversation_id),
                "turns": store.turns(
                    principal,
                    conversation_id,
                    after_seq=payload.get("afterSeq") or 0,
                    limit=payload.get("limit") or convo.DEFAULT_PAGE,
                ),
                "analyses": store.analyses(
                    principal,
                    conversation_id,
                    limit=payload.get("limit") or convo.MAX_PAGE,
                ),
            }

        if action == "delete":
            return {"conversation": store.delete(principal, conversation_id)}

        # update: exactly one field per call, so a rename can never also archive.
        if "title" in payload:
            return {"conversation": store.rename(principal, conversation_id, payload["title"])}
        if "mode" in payload:
            return {"conversation": store.set_mode(principal, conversation_id, payload["mode"])}
        if "archived" in payload:
            action_fn = store.archive if payload["archived"] else store.unarchive
            return {"conversation": action_fn(principal, conversation_id)}
        raise convo.ConversationError("update needs one of: title, mode, archived")

    def handle_confirm(self) -> None:
        """Phase 2: the human tapped تأیید on their phone."""
        principal = self.authenticate()
        if principal is None:
            return
        payload = self.read_json()
        if not self.reject_identity_keys(payload):
            return

        plan_id = str(payload.get("planId") or "")
        if not plan_id:
            self.respond_json(
                {"success": False, "error": {"code": "VALIDATION", "message": "planId is required"}},
                HTTPStatus.BAD_REQUEST,
            )
            return

        result = confirm(
            ConfirmRequest(
                plan_id=plan_id,
                request_id=str(payload.get("requestId") or ""),
                idempotency_key=payload.get("idempotencyKey"),
                source=str(payload.get("source") or "unknown"),
                device_id=str(payload.get("deviceId") or ""),
                client_version=str(payload.get("clientVersion") or ""),
            ),
            context=self.context_for(principal),
        )
        self.respond_json(result)

    def handle_dispatch(self) -> None:
        """Explicit {tool, arguments} — deterministic shortcuts and tests.

        Same core, same permissions, same audit; it just skips the brain.
        """
        principal = self.authenticate()
        if principal is None:
            return
        payload = self.read_json()
        tool_name = str(payload.get("tool") or payload.get("name") or "")
        arguments = payload.get("arguments") or payload.get("inputs") or {}
        if not tool_name:
            self.respond_json(
                {"ok": False, "error": {"code": "VALIDATION", "message": "tool is required"}},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if not isinstance(arguments, dict):
            self.respond_json(
                {"ok": False, "error": {"code": "VALIDATION", "message": "arguments must be an object"}},
                HTTPStatus.BAD_REQUEST,
            )
            return

        result = dispatch(
            ToolCall(
                tool_name,
                with_default_data_root(arguments, tool_name),
                request_id=str(payload.get("requestId") or ""),
                idempotency_key=payload.get("idempotencyKey"),
            ),
            context=self.context_for(principal),
        )
        self.respond_json(
            {
                "ok": result.ok,
                "tool": result.name,
                "data": result.data,
                "error": result.error,
                "auditId": result.audit_id,
                "principal": principal_dict(principal),
            },
            HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST,
        )

    # ---- identity ----------------------------------------------------------

    def authenticate(self) -> Principal | None:
        """Bearer → Principal. A session token first; the shared token as legacy."""
        supplied = bearer_token(self.headers.get("Authorization"))
        if not supplied:
            self.unauthorized("A session token is required. POST /api/session first.")
            return None

        try:
            return identity.resolve(supplied)
        except identity.SessionExpiredError as exc:
            self.respond_json(
                {"success": False, "error": {"code": "AUTH_EXPIRED", "message": str(exc)}},
                HTTPStatus.UNAUTHORIZED,
            )
            return None
        except identity.AuthError:
            pass  # not a session token — try the legacy shared token below

        principal = self.legacy_principal(supplied)
        if principal is None:
            self.unauthorized("Invalid session token.")
            return None
        return principal

    def legacy_principal(self, supplied: str | None = None) -> Principal | None:
        """The old shared-token identity: ONE principal for every caller.

        This is not real authentication — it cannot tell two users apart, so the
        audit log cannot either. It exists only to keep the current Android build
        working during the migration, and it is capped at `agent_readonly`.
        Delete it once the app ships per-user login.
        """
        configured = os.environ.get("RECEPTION_HTTP_API_TOKEN", "")
        supplied = supplied if supplied is not None else bearer_token(self.headers.get("Authorization"))
        local_dev = self.client_address[0] in {"127.0.0.1", "::1"} and not configured

        if configured:
            if not supplied or not secrets.compare_digest(supplied, configured):
                return None
        elif not local_dev:
            return None

        return Principal(
            user=os.environ.get("RECEPTION_HTTP_API_USER", "local_cli"),
            center=resolve_center(),
            roles=os.environ.get("RECEPTION_HTTP_API_ROLES", "agent_readonly").split(","),
            auth_method="shared_token",
        )

    def context_for(self, principal: Principal) -> DispatchContext:
        return DispatchContext(principal=principal, client="http_api", data_root=data_root())

    def reject_identity_keys(self, payload: dict[str, Any]) -> bool:
        smuggled = IDENTITY_KEYS.intersection(payload)
        if not smuggled:
            return True
        self.respond_json(
            {
                "requestId": str(payload.get("requestId") or ""),
                "success": False,
                "error": {
                    "code": "VALIDATION",
                    "message": f"identity comes from the session, not the body: {sorted(smuggled)}",
                },
            },
            HTTPStatus.BAD_REQUEST,
        )
        return False

    def unauthorized(self, message: str) -> None:
        self.respond_json(
            {"success": False, "error": {"code": "UNAUTHORIZED", "message": message}},
            HTTPStatus.UNAUTHORIZED,
        )

    # ---- transport ---------------------------------------------------------

    def read_json(self) -> dict[str, Any]:
        """Parse the body, or raise `BadRequest` — never return a plausible {}.

        Every failure here is raised rather than swallowed: a garbled body that
        came back as an empty dict would run the endpoint anyway, on arguments
        the caller never sent, and answer as though it had been asked something.

        The messages describe the SHAPE of the problem and never quote the body,
        which can carry a national code.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise BadRequest("Content-Length is not a number.") from None
        if length > MAX_JSON_BODY_BYTES:
            raise BadRequest("Request body exceeds the 24 MB limit.")
        length = max(0, length)
        try:
            raw_bytes = self.rfile.read(length)
            if len(raw_bytes) != length:
                raise BadRequest("Request body ended before Content-Length bytes were received.")
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise BadRequest("Body is not valid UTF-8. Send JSON encoded as UTF-8.") from None
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # `exc.msg` is the parser's own description ("Expecting value") and
            # carries no content from the body.
            raise BadRequest(f"Body is not valid JSON: {exc.msg}.") from None
        if not isinstance(data, dict):
            raise BadRequest("JSON body must be an object.")
        return data

    def respond_json(self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(body, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return  # never log request lines: a URL can carry a national code


def with_default_data_root(arguments: dict[str, Any], tool: str = "") -> dict[str, Any]:
    """Inject the server-owned snapshot root — but only where the tool wants it.

    ⚠️ This used to inject unconditionally, which was harmless while validation
    ignored inputs it did not recognise. It stopped being harmless the moment
    validation started REFUSING them: every tool that reads the local database
    rather than the vendor's API — six of them — began returning
    `Unknown input(s): data_root` through this endpoint, an error caused
    entirely by the server talking to itself.

    `orchestrator._with_server_arguments` has always been conditional; this is
    the same rule, in the second place that needed it.
    """
    if "data_root" in arguments:
        return arguments
    if tool:
        try:
            schema = default_registry().get(tool).input_schema or {}
        except Exception:  # noqa: BLE001 - an unknown tool fails later, with a better message
            return dict(arguments)
        if "data_root" not in (schema.get("properties") or {}):
            return dict(arguments)
    return {**arguments, "data_root": str(data_root())}


ID_KEYS = ("receptionId", "ReceptionID", "receptionID", "id", "_id")
ROW_KEYS = ("rows", "reports", "results", "items", "matches", "steps")


def _result_ids(result: Any) -> list[Any] | None:
    """The identifiers in a tool result, and nothing else.

    Saved history keeps ids and the query, never the records — the decision was
    "IDs + the query, not the people". This walks only one level into the known
    row containers rather than searching the whole payload, because a recursive
    scrape would eventually pick up a value that happens to be called `id` and
    isn't one.
    """
    if not isinstance(result, dict):
        return None
    for key in ROW_KEYS:
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        ids = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for id_key in ID_KEYS:
                if row.get(id_key) not in (None, ""):
                    ids.append(row[id_key])
                    break
        if ids:
            return ids
    return None


def _result_count(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    for key in ("count", "total", "found", "brokenFound", "matches"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    for key in ROW_KEYS:
        if isinstance(result.get(key), list):
            return len(result[key])
    return None


def bearer_token(header: str | None) -> str:
    if not header:
        return ""
    prefix = "Bearer "
    return header[len(prefix) :].strip() if header.startswith(prefix) else ""


def principal_dict(principal: Principal) -> dict[str, Any]:
    return {
        "user": principal.user,
        "center": principal.center,
        "roles": principal.roles,
        "authMethod": principal.auth_method,
    }


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_http_api_server(
    host: str = "127.0.0.1",
    port: int = 8770,
    *,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
) -> ThreadingHTTPServer:
    """Build the HTTP server without starting it.

    Split out from ``run_http_api`` so the Windows service can hold the server
    object and call ``shutdown()`` on a stop request. ``serve_forever()`` blocks
    and cannot be interrupted from a service control handler otherwise.

    TLS is optional and off by default. It is wired here so that enabling it
    later is a config change rather than a code change.
    """
    # Do not expose the port unless the operator has deliberately configured a
    # credential. Either mechanism qualifies:
    #
    #   RECEPTION_SESSION_SECRET  per-user sessions (preferred; auditable)
    #   RECEPTION_HTTP_API_TOKEN  legacy shared token (one principal for all)
    #
    # This guard predates the session system and used to demand the shared
    # token specifically, which blocked the very migration the docs call for
    # ("delete it once the app ships per-user login"). Request-time enforcement
    # in authenticate() is unchanged: without a valid token a non-local caller
    # still gets 401.
    if host not in LOCAL_HOSTS and not (
        os.environ.get("RECEPTION_SESSION_SECRET") or os.environ.get("RECEPTION_HTTP_API_TOKEN")
    ):
        raise RuntimeError(
            f"Refusing to bind to {host} with no credential configured. "
            "Set RECEPTION_SESSION_SECRET (preferred) or RECEPTION_HTTP_API_TOKEN."
        )

    server = ThreadingHTTPServer((host, port), HttpApiHandler)
    # Without this a service restart hits TIME_WAIT and fails to rebind.
    server.daemon_threads = True

    if tls_certfile:
        import ssl

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=tls_certfile, keyfile=tls_keyfile or tls_certfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)

    return server


def run_http_api(host: str = "127.0.0.1", port: int = 8770) -> None:
    if not os.environ.get("RECEPTION_SESSION_SECRET"):
        print("WARNING: RECEPTION_SESSION_SECRET is not set — sessions will not survive a restart.")
    server = create_http_api_server(host, port)
    print(f"Reception CRM HTTP API adapter running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
