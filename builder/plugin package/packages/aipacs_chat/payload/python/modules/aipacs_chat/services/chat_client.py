"""The /api/v1/chat/* client.

A THIN LAYER ON THE IDENTITY MODULE'S CLIENT, not a second one. The bearer
token, the base URL, the keychain custody, the ``Accept: application/json``
header, the off-GUI-thread guard and the Laravel error extraction all already
exist in ``modules.Identity.providers.aipacs_web``. Building a second client
here would mean a second copy of every one of them, and one copy would drift
the first time a header changed.

WHAT THIS ADDS, and only this:

  * the ``/chat/*`` paths and their payload parsing,
  * a 401 policy — discard the stored token, tell the UI to re-pair, and NEVER
    retry silently. A poller that retries a dead token just makes the same
    failure 75 times a minute,
  * proxy and timeout resolution through the module that owns them.

BLOCKING, ON PURPOSE. Every method here is a synchronous round trip and the
Identity module's thread guard raises if one is called on the GUI thread. That
is a feature: an accidental GUI-thread poll fails loudly here instead of
freezing the workstation for three to twenty seconds, which is a bug this
codebase has already paid for once.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Sequence

from .models import Filters, SyncResponse

logger = logging.getLogger(__name__)


class ChatAuthError(RuntimeError):
    """The token is no longer accepted. Re-pair; do not retry.

    Raised only for a real 401. Everything else — a refused connection, a 500,
    a timeout — is a :class:`ChatTransportError`, because the two need opposite
    responses and telling them apart from a message string is how a client ends
    up signing the operator out over a dropped packet.
    """


class ChatTransportError(RuntimeError):
    """Anything else that went wrong. Back off and try again."""

    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ChatNotConfiguredError(RuntimeError):
    """No paired AI-PACS web account, or no base URL. Nothing to talk to."""


class ChatAttachmentError(RuntimeError):
    """The selection was refused BEFORE anything was uploaded.

    Deliberately not a transport error: nothing was sent, nothing is in doubt,
    and there is nothing to back off from. The operator changes the selection
    and presses send again.
    """


class ChatForbiddenError(ChatTransportError):
    """Authenticated, and not permitted to run the console.

    Kept apart from a plain transport failure because the two send an operator
    to entirely different places: one is a network to check, the other is a
    line in the site's ``.env`` that only the owner can change.
    """


class ChatApiMissingError(ChatTransportError):
    """The server answers, is authenticated, and has no /chat routes.

    A 404 here means one specific thing: that host is running a build of the
    Laravel backend from before the chat API was added. It is NOT a network
    fault and retrying will never fix it, so it gets its own message rather
    than hiding behind "could not reach the consultation server" — which is
    what an operator would otherwise report to whoever runs the site.
    """


class ChatClient:
    """Every endpoint the manager console needs, in one object.

    Construct one per worker run rather than one per request: building it hits
    Windows Credential Manager and the identity database, which is cheap once
    and wasteful at 800 ms intervals.
    """

    def __init__(self, web_client: Any, *, aipacs_user: str = "") -> None:
        self._client = web_client
        self._aipacs_user = aipacs_user

    # ── construction ───────────────────────────────────────────────────────

    @classmethod
    def for_user(cls, aipacs_user: str, *, session: Any = None) -> "ChatClient":
        """Build from the stored AI-PACS web identity.

        Raises :class:`ChatNotConfiguredError` when there is no linked account
        or no configured base URL — which is a state to render, not an error to
        report. The console shows "sign in to AI-PACS" rather than a traceback.
        """
        try:
            from modules.Identity.providers.aipacs_web import (
                AipacsWebError,
                get_aipacs_web_client,
            )
        except Exception as exc:  # pragma: no cover - import-time only
            raise ChatNotConfiguredError(f"Identity module unavailable: {exc}") from exc

        try:
            client = get_aipacs_web_client(aipacs_user)
        except AipacsWebError as exc:
            # The identity row exists but the keychain entry is gone — the
            # operator signed out on this machine, or the credential store was
            # reset. Same remedy as never having paired.
            raise ChatNotConfiguredError(str(exc)) from exc

        if client is None:
            raise ChatNotConfiguredError(
                "This workstation is not signed in to AI-PACS Consultation."
            )

        if session is not None:
            client._session = session  # test seam; mirrors AipacsWebClient(session=…)

        return cls(client, aipacs_user=aipacs_user)

    # ── plumbing ───────────────────────────────────────────────────────────

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Sequence[tuple[str, Any]] | Mapping[str, Any] | None = None,
    ) -> Any:
        from modules.Identity.providers.aipacs_web import AipacsWebError

        try:
            return self._client.request_json(
                method, path, json_body=dict(json_body) if json_body else None, params=params
            )
        except AipacsWebError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                # The token is dead. Discard it here rather than leaving the
                # next poll to rediscover the same 401 in 800 ms — and do NOT
                # retry: re-pairing needs a human, and a silent retry loop
                # against a revoked token is indistinguishable from an attack.
                self._forget_token()
                raise ChatAuthError(str(exc)) from exc

            if status == 404:
                # Distinguish "this conversation is gone" from "this server has
                # no chat API". A route that never existed 404s just like a
                # missing case, and only the second one is worth telling the
                # operator to escalate.
                raise ChatApiMissingError(
                    "This AI-PACS server does not have the chat API yet. "
                    "The consultation backend needs the PatientChat API update "
                    "before the console can show anything.",
                    status_code=404,
                ) from exc

            raise ChatTransportError(str(exc), status_code=status) from exc

    def download_file(self, case_id: int, file_id: int) -> bytes:
        """Fetch one attachment's BYTES.

        The only call in this client that is not JSON, so it cannot go through
        ``request_json``. It still reuses the identity client's session and
        bearer token — the alternative, a second ``requests`` session here,
        would be a second copy of the auth header, the thread guard and the
        401 policy, and one of the copies would drift.

        The 401/404 mapping is duplicated deliberately and minimally: a dead
        token must discard itself here too, or an operator clicking an
        attachment after a revoke would sit on a spinner while the poll loop
        quietly signed them out.
        """
        from modules.Identity.providers.aipacs_web import API_PREFIX
        from modules.Identity.thread_guard import assert_off_gui_thread

        assert_off_gui_thread("aipacs_chat download_file")

        client = self._client
        url = f"{client.base_url}{API_PREFIX}/chat/cases/{int(case_id)}/file/{int(file_id)}"
        headers = {
            "Authorization": f"Bearer {client._token}",
            "Accept": "application/octet-stream",
        }
        try:
            session = client._ensure_session()
            resp = session.get(url, headers=headers, timeout=client._timeout)
        except Exception as exc:
            raise ChatTransportError(
                f"Could not reach the consultation server: {exc}"
            ) from exc

        status = getattr(resp, "status_code", 0)
        if status == 401:
            self._forget_token()
            raise ChatAuthError("Your AI-PACS session expired — sign in again.")
        if status == 404:
            raise ChatTransportError(
                "That attachment is no longer on the server.", status_code=404
            )
        if status != 200:
            raise ChatTransportError(
                f"The server refused the attachment ({status}).", status_code=status
            )
        content = getattr(resp, "content", b"") or b""
        if not content:
            raise ChatTransportError("The attachment came back empty.",
                                     status_code=status)
        return content

    def _forget_token(self) -> None:
        """Drop the stored secret so the UI's next attempt asks for a sign-in.

        Deletes the keychain entry only — the identity row stays, because it is
        what tells the console WHICH account to offer to sign back in as.
        """
        if not self._aipacs_user:
            return
        try:
            from modules.Identity.providers.aipacs_web import find_aipacs_web_identity
            from modules.Identity import secure_store

            identity = find_aipacs_web_identity(self._aipacs_user)
            if identity is not None:
                secure_store.delete_secret("aipacs_web", str(identity.subject_id))
        except Exception as exc:  # pragma: no cover - must never mask the 401
            logger.debug("aipacs_chat: could not discard the expired token: %s", exc)

    @staticmethod
    def _params(pairs: Iterable[tuple[str, Any]]) -> list[tuple[str, str]]:
        return [(str(k), str(v)) for k, v in pairs]

    # ── reads ──────────────────────────────────────────────────────────────

    def sync(self, params: Sequence[tuple[str, Any]]) -> SyncResponse:
        """The everything-poll.

        ``params`` comes from :meth:`SyncEngine.next_request` and is passed
        through UNCHANGED. The server reads the cursor and the filters from the
        query string only — a JSON body is silently ignored, and a client that
        sends one looks permanently cold: full state on every poll, forever.
        """
        try:
            data = self._call("GET", "/chat/sync", params=self._params(params))
        except ChatTransportError as exc:
            if getattr(exc, "status_code", None) != 403:
                raise
            # A 403 HERE means the account authenticated and is not on the
            # console-operator list — not a network fault, and not something a
            # retry fixes. Said plainly, because the generic transport message
            # sends the operator to look for a connection problem that is not
            # there. The fix is one line of the site's .env
            # (PATIENTCHAT_CONSOLE_OPERATORS), and only the owner can make it.
            raise ChatForbiddenError(
                "This AI-PACS account is signed in but is not a chat operator. "
                "Ask whoever administers ai-pacs.com to add it to the "
                "consultation console's operator list.",
                status_code=403,
            ) from exc
        return SyncResponse.parse(data)

    def case(self, case_id: int) -> dict:
        data = self._call("GET", f"/chat/cases/{int(case_id)}")
        return data.get("case", {}) if isinstance(data, Mapping) else {}

    def saved_replies(self, *, case_id: int | None = None, locale: str = "") -> list[dict]:
        params: list[tuple[str, Any]] = []
        if case_id:
            params.append(("case", int(case_id)))
        if locale:
            params.append(("locale", locale))
        data = self._call("GET", "/chat/saved-replies", params=self._params(params))
        replies = data.get("replies") if isinstance(data, Mapping) else None
        return list(replies) if isinstance(replies, list) else []

    def pricing(self) -> dict:
        data = self._call("GET", "/chat/pricing")
        return dict(data) if isinstance(data, Mapping) else {}

    def statuses(self) -> list[dict]:
        data = self._call("GET", "/chat/statuses")
        rows = data.get("statuses") if isinstance(data, Mapping) else None
        return list(rows) if isinstance(rows, list) else []

    def visitors(self, *, live_only: bool = False) -> dict:
        params = [("scope", "live")] if live_only else []
        data = self._call("GET", "/chat/visitors", params=self._params(params))
        return dict(data) if isinstance(data, Mapping) else {}

    # ── writes ─────────────────────────────────────────────────────────────

    def send(
        self,
        case_id: int,
        body: str,
        *,
        ai_action: str = "",
        attachments=(),
        is_report: bool = False,
    ) -> dict:
        """One message, with or without files.

        WITHOUT ATTACHMENTS THIS IS BYTE-IDENTICAL to what it always was — the
        multipart branch is only taken when there is something to attach, so
        the ordinary text send cannot regress behind a feature it never uses.

        THE TEXT IS THE CAPTION OF THE WHOLE SEND, not a separate message. The
        web client behaves the same way, and splitting it would give the
        patient two notifications for one action.
        """
        if not attachments:
            payload: dict[str, Any] = {"body": body}
            if ai_action:
                payload["ai_action"] = ai_action
            if is_report:
                payload["is_report"] = True
            return self._message_of(
                self._call("POST", f"/chat/cases/{int(case_id)}/send", json_body=payload)
            )
        return self._message_of(
            self._send_multipart(
                case_id, body, ai_action=ai_action,
                attachments=attachments, is_report=is_report,
            )
        )

    def _send_multipart(
        self, case_id: int, body: str, *, ai_action: str, attachments, is_report: bool,
    ) -> Any:
        """The ONE place that knows the upload's wire format.

        Multipart, not JSON: Laravel reads uploads off ``$request->file()``,
        and a base64 field inside a JSON body would be a third of a megabyte
        larger and would not reach the validator at all.

        Booleans go as ``"1"``/``"0"`` rather than Python's ``True``/``False``:
        a multipart field is a string, and Laravel's ``boolean`` rule accepts
        ``"1"`` but not ``"True"``.
        """
        from modules.Identity.providers.aipacs_web import AipacsWebError
        from modules.aipacs_chat.services.attachments import UPLOAD_TIMEOUT_SEC

        data: dict[str, str] = {"body": body or ""}
        if ai_action:
            data["ai_action"] = ai_action
        if is_report:
            data["is_report"] = "1"

        files = [
            ("files[]", (item.name, item.data, item.mime))
            for item in attachments
        ]

        try:
            return self._client.request_json(
                "POST", f"/chat/cases/{int(case_id)}/send",
                data=data, files=files, timeout=UPLOAD_TIMEOUT_SEC,
            )
        except AipacsWebError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                self._forget_token()
                raise ChatAuthError(str(exc)) from exc
            if status == 413:
                raise ChatTransportError(
                    "The server refused the upload as too large.", status_code=413
                ) from exc
            if status == 422:
                # The server's own validator, verbatim: it knows the real
                # limits, and repeating our guess at them here would be a
                # second answer for the operator to disbelieve.
                raise ChatTransportError(str(exc), status_code=422) from exc
            raise ChatTransportError(str(exc), status_code=status) from exc

    def send_price(
        self,
        case_id: int,
        *,
        currency: str,
        amount: float | None = None,
        tier: str = "",
        body: str = "",
        with_link: bool = True,
    ) -> dict:
        """A price offer.

        EITHER an amount OR a tier that has one configured — the server refuses
        a request with neither, and the amount-to-link pairing is owner-
        confirmed and lives in the server's config. Do not guess a link here.
        """
        payload: dict[str, Any] = {"currency": currency, "with_link": bool(with_link)}
        if amount is not None:
            payload["amount"] = amount
        if tier:
            payload["tier"] = tier
        if body:
            payload["body"] = body
        return self._message_of(
            self._call("POST", f"/chat/cases/{int(case_id)}/price", json_body=payload)
        )

    def set_status(self, case_id: int, status: str, *, note: str = "") -> dict:
        payload: dict[str, Any] = {"status": status}
        if note:
            payload["note"] = note
        data = self._call("POST", f"/chat/cases/{int(case_id)}/status", json_body=payload)
        return dict(data) if isinstance(data, Mapping) else {}

    def edit_message(self, case_id: int, message_id: int, body: str) -> dict:
        return self._message_of(
            self._call(
                "POST",
                f"/chat/cases/{int(case_id)}/messages/{int(message_id)}/edit",
                json_body={"body": body},
            )
        )

    def remove_message(self, case_id: int, message_id: int) -> dict:
        return self._message_of(
            self._call("POST", f"/chat/cases/{int(case_id)}/messages/{int(message_id)}/remove")
        )

    def react(self, case_id: int, message_id: int, value: int | None) -> dict:
        """1, -1, or None to clear. Anything else is normalised to a clear."""
        data = self._call(
            "POST",
            f"/chat/cases/{int(case_id)}/messages/{int(message_id)}/react",
            json_body={"value": value},
        )
        return dict(data) if isinstance(data, Mapping) else {}

    def pin_message(self, case_id: int, message_id: int) -> dict:
        """Toggle. The answer is the ONLY place the new state arrives.

        A message pin is written quietly, without touching ``updated_at``, so
        it can never appear in the sync response's ``revised`` list. Waiting
        for the poll to confirm a pin waits forever.
        """
        data = self._call(
            "POST", f"/chat/cases/{int(case_id)}/messages/{int(message_id)}/pin"
        )
        return dict(data) if isinstance(data, Mapping) else {}

    def email_message(self, case_id: int, message_id: int) -> dict:
        data = self._call(
            "POST", f"/chat/cases/{int(case_id)}/messages/{int(message_id)}/email"
        )
        return dict(data) if isinstance(data, Mapping) else {}

    def pin_case(self, case_id: int) -> bool:
        data = self._call("POST", f"/chat/cases/{int(case_id)}/pin")
        return bool(data.get("pinned")) if isinstance(data, Mapping) else False

    def rotate_link(self, case_id: int) -> str:
        """A fresh magic link for the patient. Shown once, never stored."""
        data = self._call("POST", f"/chat/cases/{int(case_id)}/rotate-link")
        return str(data.get("link", "")) if isinstance(data, Mapping) else ""

    def save_link(self, case_id: int, url: str, *, primary: bool = True,
                  message_id: int | None = None) -> dict:
        payload: dict[str, Any] = {"url": url, "primary": bool(primary)}
        if message_id:
            payload["message_id"] = int(message_id)
        data = self._call("POST", f"/chat/cases/{int(case_id)}/links", json_body=payload)
        return dict(data) if isinstance(data, Mapping) else {}

    def set_primary_link(self, case_id: int, file_id: int) -> int | None:
        data = self._call("POST", f"/chat/cases/{int(case_id)}/links/{int(file_id)}/primary")
        if not isinstance(data, Mapping):
            return None
        value = data.get("primary_study_file_id")
        return int(value) if isinstance(value, (int, float)) else None

    def forget_link(self, case_id: int, file_id: int) -> None:
        """Only a link an OPERATOR saved. The server refuses a patient's.

        A link the patient sent is evidence of what they sent and when. It can
        stop being the study; it cannot be made never to have happened.
        """
        self._call("POST", f"/chat/cases/{int(case_id)}/links/{int(file_id)}/forget")

    # ── Drive association ──────────────────────────────────────────────────
    # The server holds NO Google credential. The desktop client signs in as the
    # clinic, talks to Drive directly, and posts only the association back — a
    # 400 MB study must never pass through Laravel.

    def link_drive_folder(self, case_id: int, folder_id: str, *, name: str = "",
                          url: str = "") -> dict:
        payload: dict[str, Any] = {"folder_id": folder_id}
        if name:
            payload["name"] = name
        if url:
            payload["url"] = url
        data = self._call("POST", f"/chat/drive/case/{int(case_id)}/folder", json_body=payload)
        return dict(data) if isinstance(data, Mapping) else {}

    def unlink_drive_folder(self, case_id: int) -> None:
        self._call("POST", f"/chat/drive/case/{int(case_id)}/folder/forget")

    def attach_drive_file(self, case_id: int, drive_id: str, *, name: str = "",
                          mime: str = "", size: int | None = None, url: str = "",
                          folder_id: str = "") -> dict:
        payload: dict[str, Any] = {"drive_id": drive_id}
        for key, value in (("name", name), ("mime", mime), ("url", url), ("folder_id", folder_id)):
            if value:
                payload[key] = value
        if size is not None:
            payload["bytes"] = int(size)
        data = self._call("POST", f"/chat/drive/case/{int(case_id)}/attach", json_body=payload)
        return dict(data) if isinstance(data, Mapping) else {}

    def detach_drive_file(self, case_id: int, file_id: int) -> None:
        self._call("POST", f"/chat/drive/case/{int(case_id)}/detach/{int(file_id)}")

    # ── shaping ────────────────────────────────────────────────────────────

    @staticmethod
    def _message_of(data: Any) -> dict:
        if isinstance(data, Mapping):
            message = data.get("message")
            if isinstance(message, Mapping):
                return dict(message)
        return {}


def query_for(engine_params: Sequence[tuple[str, Any]], filters: Filters | None = None) -> list[tuple[str, str]]:
    """Engine params plus filters, as ordered pairs.

    Kept as a free function so a caller that already has both can join them
    without constructing a client. Order is preserved because the multi-value
    filter groups post repeated keys and a dict would lose all but the last.
    """
    out = [(str(k), str(v)) for k, v in engine_params]
    if filters is not None:
        out.extend(filters.as_query_pairs())
    return out
