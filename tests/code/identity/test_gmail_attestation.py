"""Unit tests for the ADR-0008 Gmail attestation identity bridge (Qt-free).

Covers:
* ``attest_gmail`` — faked OAuth flow: ID-token decode, openid+email-ONLY
  scopes + ``prompt=select_account``, account-mismatch raise, cancelled-flow
  message, and the no-personal-credential invariant (no secure_store write);
* ``link_google`` — payload shape, 201 success, clean 422 message extraction
  (admin-not-registered), missing-token + network-error paths;
* ``connect_via_google_attestation`` — Sanctum token stored exactly like
  ``connect()``; identity shape + ``extra["link"]`` snapshot for the UI.
"""

import base64
import json
import types

import pytest

from modules.Identity import secure_store
from modules.Identity.providers import aipacs_web as aw
from modules.Identity.providers.aipacs_web import (
    ATTEST_SCOPES,
    AipacsWebError,
    AipacsWebIdentityProvider,
    attest_gmail,
    link_google,
)
from modules.Identity.providers.google import oauth_flow


# ── helpers ────────────────────────────────────────────────────────────────────
def _jwt(payload: dict) -> str:
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'RS256', 'typ': 'JWT'})}.{seg(payload)}.fakesig"


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def post(self, url, json=None, timeout=None, **kw):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self._responses.pop(0) if self._responses else _FakeResp()


@pytest.fixture
def fake_oauth(monkeypatch):
    """Patch the Google client config + the OAuth flow; record flow calls and
    any secure_store writes (there must be NONE for the transient attestation)."""
    state = {"flow_calls": [], "saved": []}
    monkeypatch.setattr(
        "modules.Identity.config.load_google_client_config",
        lambda: {"installed": {"client_id": "cid", "client_secret": "sec"}},
    )
    monkeypatch.setattr(
        secure_store, "save_secret",
        lambda provider, subject, payload: state["saved"].append(
            (provider, subject, payload)) or True,
    )

    def install_flow(id_token):
        # Q0 2026-07-14: the fake must mirror the REAL signature of
        # `oauth_flow.run_installed_app_flow`, which gained `require_embedded`. The stale
        # double raised `TypeError: unexpected keyword argument` and took 8 identity tests
        # red — invisible, because the suite was already red by default.
        def _fake_flow(client_config, scopes=None, *, auth_url_kwargs=None,
                       open_url_cb=None, require_embedded=False):
            state["flow_calls"].append({
                "client_config": client_config, "scopes": scopes,
                "auth_url_kwargs": auth_url_kwargs, "open_url_cb": open_url_cb,
                "require_embedded": require_embedded,
            })
            return types.SimpleNamespace(
                id_token=id_token, token="acc", refresh_token="ref",
            )

        monkeypatch.setattr(oauth_flow, "run_installed_app_flow", _fake_flow)

    state["install_flow"] = install_flow
    return state


# ── attest_gmail ───────────────────────────────────────────────────────────────
def test_attest_gmail_success_decodes_token_and_discards_credentials(fake_oauth):
    token = _jwt({"sub": "g-sub-1", "email": "Dr.A@gmail.com", "aud": "cid"})
    fake_oauth["install_flow"](token)

    out = attest_gmail("dr.a@gmail.com")
    assert out == {"id_token": token, "subject": "g-sub-1", "email": "Dr.A@gmail.com"}

    # Transient: scopes are openid+email ONLY (never Drive) with select_account.
    call = fake_oauth["flow_calls"][0]
    assert call["scopes"] == list(ATTEST_SCOPES)
    assert all("drive" not in s for s in call["scopes"])
    assert call["auth_url_kwargs"] == {"prompt": "select_account"}
    # The no-personal-credential invariant: nothing was written to secure_store.
    assert fake_oauth["saved"] == []


def test_attest_gmail_email_mismatch_raises(fake_oauth):
    # Provided-gmail path (admin/testing): the mismatch guard stays.
    fake_oauth["install_flow"](_jwt({"sub": "s", "email": "other@gmail.com"}))
    with pytest.raises(AipacsWebError, match="signed in as other@gmail.com.*entered dr.a@gmail.com"):
        attest_gmail("dr.a@gmail.com")
    assert fake_oauth["saved"] == []


def test_attest_gmail_match_is_case_insensitive(fake_oauth):
    fake_oauth["install_flow"](_jwt({"sub": "s", "email": "DR.A@GMAIL.COM"}))
    assert attest_gmail("dr.a@gmail.com")["subject"] == "s"


def test_attest_gmail_empty_returns_signed_in_email(fake_oauth):
    """Unified one-step login: no pre-typed Gmail — whatever Google verifies
    is returned (no mismatch comparison); the server authorizes it."""
    token = _jwt({"sub": "g-sub-9", "email": "whoever@gmail.com"})
    fake_oauth["install_flow"](token)

    out = attest_gmail()  # default "" — no gmail argument at all
    assert out == {"id_token": token, "subject": "g-sub-9",
                   "email": "whoever@gmail.com"}

    # Still openid+email ONLY + select_account; still no secure_store write.
    call = fake_oauth["flow_calls"][0]
    assert call["scopes"] == list(ATTEST_SCOPES)
    assert call["auth_url_kwargs"] == {"prompt": "select_account"}
    assert fake_oauth["saved"] == []


def test_attest_gmail_whitespace_is_treated_as_empty(fake_oauth):
    fake_oauth["install_flow"](_jwt({"sub": "s", "email": "any@gmail.com"}))
    assert attest_gmail("   ")["email"] == "any@gmail.com"


def test_attest_gmail_rejects_a_non_email_when_provided(fake_oauth):
    with pytest.raises(AipacsWebError, match="Enter the Gmail"):
        attest_gmail("not-an-email")
    assert fake_oauth["flow_calls"] == []  # never opens a browser


def test_attest_gmail_missing_id_token_raises(fake_oauth):
    fake_oauth["install_flow"](None)
    with pytest.raises(AipacsWebError, match="did not return an ID token"):
        attest_gmail("dr.a@gmail.com")


def test_attest_gmail_unreadable_token_raises(fake_oauth):
    fake_oauth["install_flow"]("garbage-not-a-jwt")
    with pytest.raises(AipacsWebError, match="unreadable ID token"):
        attest_gmail("dr.a@gmail.com")


def test_attest_gmail_cancelled_flow_is_clean(fake_oauth, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("user closed the browser")

    monkeypatch.setattr(oauth_flow, "run_installed_app_flow", _boom)
    with pytest.raises(AipacsWebError, match="cancelled or did not complete"):
        attest_gmail("dr.a@gmail.com")


def test_attest_gmail_requires_google_client_config(monkeypatch):
    monkeypatch.setattr(
        "modules.Identity.config.load_google_client_config", lambda: None
    )
    with pytest.raises(AipacsWebError, match="OAuth client not configured"):
        attest_gmail("dr.a@gmail.com")


# ── link_google ────────────────────────────────────────────────────────────────
def test_link_google_success_payload_and_url():
    sess = _FakeSession([_FakeResp(201, {
        "token": "sanctum-1",
        "user": {"id": 12, "name": "Dr Linked", "email": "linked.doctor@gmail.com"},
        "link": {"gmail_email": "linked.doctor@gmail.com", "status": "active"},
    })])
    data = link_google(
        "http://h/consult/", gmail="linked.doctor@gmail.com", id_token="idtok",
        workstation_user_id="drv", device_name="WS-1", session=sess,
    )
    assert data["token"] == "sanctum-1"
    call = sess.calls[0]
    assert call["url"] == "http://h/consult/api/v1/auth/workstation/link-google"
    assert call["json"] == {
        "gmail": "linked.doctor@gmail.com", "id_token": "idtok",
        "workstation_user_id": "drv", "device_name": "WS-1",
    }


def test_link_google_includes_optional_ids_when_given():
    sess = _FakeSession([_FakeResp(201, {"token": "t"})])
    link_google("http://h", gmail="a@g.com", id_token="i",
                workstation_user_id="drv", server_id="srv9", center_id="c3",
                device_name="WS", session=sess)
    body = sess.calls[0]["json"]
    assert body["server_id"] == "srv9" and body["center_id"] == "c3"


def test_link_google_422_not_registered_message():
    # The server's owner-directive 422 wording must surface verbatim.
    sess = _FakeSession([_FakeResp(422, {
        "message": "The given data was invalid.",
        "errors": {"gmail": [
            "Your email is not registered for the Consultation module. "
            "Please contact AI-PACS.com to activate/register your "
            "Consultation access."]},
    })])
    with pytest.raises(AipacsWebError,
                       match="not registered for the Consultation module"):
        link_google("http://h", gmail="x@g.com", id_token="i",
                    workstation_user_id="drv", session=sess)


def test_link_google_422_id_token_failure_message():
    sess = _FakeSession([_FakeResp(422, {
        "errors": {"id_token": ["The Google ID token could not be verified."]},
    })])
    with pytest.raises(AipacsWebError, match="could not be verified"):
        link_google("http://h", gmail="x@g.com", id_token="bad",
                    workstation_user_id="drv", session=sess)


def test_link_google_rejects_missing_token():
    sess = _FakeSession([_FakeResp(201, {"user": {"id": 1}})])
    with pytest.raises(AipacsWebError, match="access token"):
        link_google("http://h", gmail="x@g.com", id_token="i",
                    workstation_user_id="drv", session=sess)


def test_link_google_network_error_is_clean():
    class _Boom:
        def post(self, *a, **k):
            raise OSError("connection refused")

    with pytest.raises(AipacsWebError, match="Could not reach"):
        link_google("http://h", gmail="x@g.com", id_token="i",
                    workstation_user_id="drv", session=_Boom())


# ── provider: connect_via_google_attestation ──────────────────────────────────
def test_connect_via_attestation_stores_token_and_link(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available",
                        lambda self: (True, "ok"))
    monkeypatch.setattr(aw, "load_aipacs_web_config",
                        lambda: {"base_url": "http://h/consult", "enabled": True})
    attest_calls = []
    monkeypatch.setattr(
        aw, "attest_gmail",
        lambda gmail, **kw: attest_calls.append(gmail) or {
            "id_token": "idtok", "subject": "g-sub",
            "email": "linked.doctor@gmail.com",
        },
    )
    link_calls = []
    monkeypatch.setattr(
        aw, "link_google",
        lambda base, **kw: link_calls.append((base, kw)) or {
            "token": "sanctum-9",
            "user": {"id": 12, "name": "Dr Linked",
                     "email": "linked.doctor@gmail.com"},
            "link": {"gmail_email": "linked.doctor@gmail.com",
                     "workstation_user_id": "drv", "status": "active",
                     "consultation_profile_id": 3},
            "profile": {"name": "Dr. Linked Doctor"},
        },
    )
    saved = {}
    monkeypatch.setattr(
        secure_store, "save_secret",
        lambda provider, subject, payload: saved.__setitem__(
            (provider, subject), payload) or True,
    )

    ident = prov.connect_via_google_attestation(
        "drv", "linked.doctor@gmail.com", server_id="srv1")

    assert attest_calls == ["linked.doctor@gmail.com"]
    base, kw = link_calls[0]
    assert base == "http://h/consult"
    assert kw["workstation_user_id"] == "drv"
    assert kw["id_token"] == "idtok" and kw["server_id"] == "srv1"

    # Identity shape — exactly the connect() contract + the link snapshot.
    assert ident.provider == "aipacs_web"
    assert ident.subject_id == "12"
    assert ident.handle == "linked.doctor@gmail.com"
    assert ident.aipacs_user == "drv"
    assert "consultation" in ident.capabilities
    assert ident.extra["base_url"] == "http://h/consult"
    assert ident.extra["link"]["gmail_email"] == "linked.doctor@gmail.com"
    assert ident.extra["link"]["profile_name"] == "Dr. Linked Doctor"
    assert ident.extra["link"]["status"] == "active"

    # Sanctum token stored EXACTLY like connect(); never a "google" secret.
    assert saved == {("aipacs_web", "12"): {"token": "sanctum-9",
                                            "base_url": "http://h/consult"}}


def test_connect_via_attestation_links_attested_email_when_gmail_empty(monkeypatch):
    """Unified one-step login: empty gmail → the link is made with whatever
    email Google attested (the server authorizes it)."""
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available",
                        lambda self: (True, "ok"))
    monkeypatch.setattr(aw, "load_aipacs_web_config",
                        lambda: {"base_url": "http://h/consult", "enabled": True})
    attest_calls = []
    monkeypatch.setattr(
        aw, "attest_gmail",
        lambda gmail="", **kw: attest_calls.append(gmail) or {
            "id_token": "idtok", "subject": "g-sub",
            "email": "verified.by.google@gmail.com",
        },
    )
    link_calls = []
    monkeypatch.setattr(
        aw, "link_google",
        lambda base, **kw: link_calls.append((base, kw)) or {
            "token": "sanctum-e",
            "user": {"id": 44, "name": "Dr Verified",
                     "email": "verified.by.google@gmail.com"},
            "link": {"gmail_email": "verified.by.google@gmail.com",
                     "status": "active"},
        },
    )
    monkeypatch.setattr(secure_store, "save_secret", lambda *a, **k: True)

    ident = prov.connect_via_google_attestation("drv")  # no gmail at all

    assert attest_calls == [""]
    _base, kw = link_calls[0]
    # The link payload carries the GOOGLE-VERIFIED email, not user input.
    assert kw["gmail"] == "verified.by.google@gmail.com"
    assert ident.handle == "verified.by.google@gmail.com"
    assert ident.extra["link"]["gmail_email"] == "verified.by.google@gmail.com"


def test_connect_via_attestation_raises_when_unavailable(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available",
                        lambda self: (False, "no config"))
    with pytest.raises(RuntimeError, match="no config"):
        prov.connect_via_google_attestation("drv", "a@gmail.com")


def test_connect_via_attestation_propagates_server_422(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available",
                        lambda self: (True, "ok"))
    monkeypatch.setattr(aw, "load_aipacs_web_config",
                        lambda: {"base_url": "http://h", "enabled": True})
    monkeypatch.setattr(aw, "attest_gmail", lambda gmail, **kw: {
        "id_token": "i", "subject": "s", "email": gmail})

    def _422(base, **kw):
        raise AipacsWebError(
            "Your email is not registered for the Consultation module. "
            "Please contact AI-PACS.com to activate/register your "
            "Consultation access.")

    monkeypatch.setattr(aw, "link_google", _422)
    with pytest.raises(AipacsWebError,
                       match="not registered for the Consultation module"):
        prov.connect_via_google_attestation("drv", "x@gmail.com")
