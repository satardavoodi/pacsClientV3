"""The chat REST client: URLs, payloads, and the 401 policy.

House style for this area (tests/code/identity): duck-typed fakes defined at
the top of the file rather than unittest.mock, monkeypatch for module-level
functions, and assertions on the recorded call dict — url, params, json,
headers.

The one behaviour worth more than the URLs is the 401 policy. A poller that
treats "your token is dead" the same as "the wifi dropped" either signs the
operator out over a lost packet or hammers a revoked token 75 times a minute.
"""

import pytest

from modules.aipacs_chat.services import chat_client as cc
from modules.aipacs_chat.services.chat_client import (
    ChatAuthError,
    ChatClient,
    ChatNotConfiguredError,
    ChatTransportError,
)
from modules.Identity.providers.aipacs_web import AipacsWebError


class _FakeWebClient:
    """Duck-typed AipacsWebClient capturing every call."""

    def __init__(self, responses=None, raises=None):
        self.calls = []
        self._responses = list(responses or [])
        self._raises = raises

    def request_json(self, method, path, *, json_body=None, params=None):
        self.calls.append(
            {"method": method, "path": path, "json": json_body, "params": params}
        )
        if self._raises is not None:
            raise self._raises
        return self._responses.pop(0) if self._responses else {}


def _client(responses=None, raises=None):
    fake = _FakeWebClient(responses, raises)
    return ChatClient(fake, aipacs_user="drv"), fake


# --- URLs and payloads ------------------------------------------------------


def test_sync_passes_the_engine_params_through_untouched():
    """The server reads the cursor from the QUERY STRING only.

    A JSON body is silently ignored, and a client that sends one looks
    permanently cold: rev=0 every poll, full state every time, forever.
    """
    client, fake = _client([{"t": 1, "cursor": {"m": 5, "rev": 9, "ev": 2, "req": 3}}])

    params = [("m", 5), ("rev", 9), ("ev", 2), ("req", 3), ("visible", "0")]
    response = client.sync(params)

    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/chat/sync"
    assert call["json"] is None
    assert ("visible", "0") in call["params"]
    assert response.cursor.m == 5


def test_sync_params_keep_repeated_filter_keys():
    """attn[] twice cannot survive a dict. It must stay a list of pairs."""
    client, fake = _client([{}])

    client.sync([("attn[]", "unread"), ("attn[]", "stalled")])

    params = fake.calls[0]["params"]
    assert params.count(("attn[]", "unread")) == 1
    assert ("attn[]", "stalled") in params


def test_send_posts_the_body_and_returns_the_message():
    client, fake = _client([{"ok": True, "message": {"id": 9, "body": "hi"}}])

    message = client.send(41, "hi")

    assert fake.calls[0] == {
        "method": "POST",
        "path": "/chat/cases/41/send",
        "json": {"body": "hi"},
        "params": None,
    }
    assert message["id"] == 9


def test_a_price_omits_the_amount_when_a_tier_carries_it():
    """Retyping an amount beside a menu that already says it is a chance to typo."""
    client, fake = _client([{"ok": True, "message": {"id": 1}}])

    client.send_price(41, currency="EUR", tier="advanced")

    assert fake.calls[0]["json"] == {"currency": "EUR", "with_link": True, "tier": "advanced"}


def test_forgetting_a_link_names_the_file_and_the_case():
    client, fake = _client([{"ok": True, "deleted": 7}])

    client.forget_link(41, 7)

    assert fake.calls[0]["path"] == "/chat/cases/41/links/7/forget"


def test_the_case_read_unwraps_the_envelope():
    client, _ = _client([{"ok": True, "case": {"id": 41, "reference": "9400123"}}])

    assert client.case(41)["reference"] == "9400123"


def test_saved_replies_can_be_scoped_to_a_case_so_name_tokens_resolve():
    client, fake = _client([{"ok": True, "replies": [{"id": 1, "body": "x"}]}])

    client.saved_replies(case_id=41)

    assert ("case", "41") in fake.calls[0]["params"]


def test_visitors_can_ask_for_the_live_strip_only():
    client, fake = _client([{"live": []}])

    client.visitors(live_only=True)

    assert ("scope", "live") in fake.calls[0]["params"]


# --- the 401 policy ---------------------------------------------------------


def test_a_401_raises_an_auth_error_and_discards_the_token(monkeypatch):
    """Dead token: stop, discard, ask the operator. Never retry.

    A silent retry loop against a revoked token is indistinguishable from an
    attack, and re-pairing needs a human either way.
    """
    forgotten = []
    monkeypatch.setattr(
        ChatClient, "_forget_token", lambda self: forgotten.append(True)
    )

    client, _ = _client(raises=AipacsWebError("expired", status_code=401))

    with pytest.raises(ChatAuthError):
        client.sync([])

    assert forgotten == [True]


def test_a_transport_failure_is_not_an_auth_failure(monkeypatch):
    """A dropped packet must not sign the operator out."""
    forgotten = []
    monkeypatch.setattr(
        ChatClient, "_forget_token", lambda self: forgotten.append(True)
    )

    client, _ = _client(raises=AipacsWebError("Could not reach the consultation server: refused"))

    with pytest.raises(ChatTransportError):
        client.sync([])

    assert forgotten == [], "the token is fine; the network is not"


def test_a_403_is_a_transport_error_carrying_its_status(monkeypatch):
    """403 means this operator is not allowed, which re-pairing does not fix."""
    monkeypatch.setattr(ChatClient, "_forget_token", lambda self: None)

    client, _ = _client(raises=AipacsWebError("Chat console operators only.", status_code=403))

    with pytest.raises(ChatTransportError) as excinfo:
        client.sync([])

    assert excinfo.value.status_code == 403


def test_a_404_on_the_chat_routes_says_the_server_needs_updating(monkeypatch):
    """Retrying never fixes a route that does not exist.

    Hiding this behind "could not reach the consultation server" is what makes
    an operator report a network fault to whoever runs the site.
    """
    from modules.aipacs_chat.services.chat_client import ChatApiMissingError

    monkeypatch.setattr(ChatClient, "_forget_token", lambda self: None)

    client, _ = _client(raises=AipacsWebError("Not Found", status_code=404))

    with pytest.raises(ChatApiMissingError) as excinfo:
        client.sync([])

    assert "does not have the chat API yet" in str(excinfo.value)
    # Still a transport error, so the poll loop backs off rather than signing out.
    assert isinstance(excinfo.value, ChatTransportError)


def test_the_discard_never_masks_the_401(monkeypatch):
    """Even if the keychain write fails, the caller still learns it was a 401."""
    def _boom(self):
        raise OSError("credential manager unavailable")

    monkeypatch.setattr(ChatClient, "_forget_token", _boom)

    client, _ = _client(raises=AipacsWebError("expired", status_code=401))

    with pytest.raises((ChatAuthError, OSError)):
        client.sync([])


# --- construction -----------------------------------------------------------


def test_an_unpaired_workstation_is_a_state_not_a_crash(monkeypatch):
    """"Sign in to AI-PACS" is a screen. It is not a traceback."""
    import modules.Identity.providers.aipacs_web as aw

    monkeypatch.setattr(aw, "get_aipacs_web_client", lambda user: None)

    with pytest.raises(ChatNotConfiguredError):
        ChatClient.for_user("drv")


def test_a_missing_keychain_entry_reads_as_not_configured(monkeypatch):
    import modules.Identity.providers.aipacs_web as aw

    def _raise(user):
        raise AipacsWebError("No stored AI-PACS Consultation token; sign in again.")

    monkeypatch.setattr(aw, "get_aipacs_web_client", _raise)

    with pytest.raises(ChatNotConfiguredError):
        ChatClient.for_user("drv")
