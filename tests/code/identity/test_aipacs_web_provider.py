"""Unit tests for the AI-PACS web identity provider + API client (ADR-0006).

Qt-free; all network is faked with duck-typed sessions/responses. Covers config
resolution, pairing, token storage/removal, the JSON client methods, and error
paths (clean messages, never raw tracebacks)."""

import pytest

from modules.Identity import secure_store
from modules.Identity.models import Capability
from modules.Identity.providers import aipacs_web as aw
from modules.Identity.providers.aipacs_web import (
    AipacsWebClient,
    AipacsWebError,
    AipacsWebIdentityProvider,
    pair_workstation,
)


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    """Duck-typed requests.Session capturing every call."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _next(self):
        return self._responses.pop(0) if self._responses else _FakeResp()

    def post(self, url, json=None, timeout=None, **kw):
        self.calls.append({"method": "POST", "url": url, "json": json, "timeout": timeout})
        return self._next()

    def request(self, method, url, json=None, params=None, headers=None, timeout=None):
        self.calls.append({
            "method": method, "url": url, "json": json,
            "params": params, "headers": headers, "timeout": timeout,
        })
        return self._next()


# ── config resolution ──────────────────────────────────────────────────────────
def test_env_override_wins_and_enables(monkeypatch):
    monkeypatch.setenv("AIPACS_WEB_BASE_URL", "http://example.test/consult/")
    cfg = aw.load_aipacs_web_config()
    assert cfg == {"base_url": "http://example.test/consult", "enabled": True}
    assert aw.aipacs_web_configured() is True


def test_unconfigured_when_no_file_and_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: tmp_path / "missing.json")
    assert aw.load_aipacs_web_config()["enabled"] is False
    assert aw.aipacs_web_configured() is False


def test_config_file_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    p = tmp_path / "aipacs_web.json"
    p.write_text('{"base_url": "http://localhost:8080/consult-form/", "enabled": true}')
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: p)
    cfg = aw.load_aipacs_web_config()
    assert cfg["base_url"] == "http://localhost:8080/consult-form"
    assert cfg["enabled"] is True


def test_is_available_reports_reason_when_unconfigured(monkeypatch):
    monkeypatch.setattr(aw, "aipacs_web_configured", lambda: False)
    ok, reason = AipacsWebIdentityProvider().is_available()
    assert ok is False and reason


# ── pairing ────────────────────────────────────────────────────────────────────
def test_pair_with_email_password():
    sess = _FakeSession([_FakeResp(200, {"token": "tok1", "user": {"id": 7, "email": "a@b.c"}})])
    data = pair_workstation("http://h/consult", {"email": "a@b.c", "password": "pw"},
                            device_name="WS-1", session=sess)
    assert data["token"] == "tok1"
    call = sess.calls[0]
    assert call["url"] == "http://h/consult/api/v1/auth/workstation/pair"
    assert call["json"] == {"device_name": "WS-1", "email": "a@b.c", "password": "pw"}


def test_pair_with_pairing_code():
    sess = _FakeSession([_FakeResp(200, {"token": "tok2", "user": {"id": 1}})])
    pair_workstation("http://h", {"pairing_code": " ABC123 "}, device_name="WS", session=sess)
    assert sess.calls[0]["json"] == {"device_name": "WS", "pairing_code": "ABC123"}


def test_pair_requires_credentials():
    with pytest.raises(AipacsWebError, match="email and password"):
        pair_workstation("http://h", {}, session=_FakeSession())


def test_pair_surfaces_laravel_error_message():
    sess = _FakeSession([_FakeResp(422, {"message": "Invalid credentials.",
                                         "errors": {"email": ["The email is wrong."]}})])
    with pytest.raises(AipacsWebError, match="Invalid credentials"):
        pair_workstation("http://h", {"email": "x@y.z", "password": "no"}, session=sess)


def test_pair_rejects_missing_token():
    sess = _FakeSession([_FakeResp(200, {"user": {"id": 1}})])
    with pytest.raises(AipacsWebError, match="token"):
        pair_workstation("http://h", {"pairing_code": "c"}, session=sess)


def test_pair_network_error_is_clean():
    class _Boom:
        def post(self, *a, **k):
            raise OSError("connection refused")

    with pytest.raises(AipacsWebError, match="Could not reach"):
        pair_workstation("http://h", {"pairing_code": "c"}, session=_Boom())


# ── provider connect / disconnect ──────────────────────────────────────────────
def test_connect_builds_identity_and_stores_token(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available", lambda self: (True, "ok"))
    monkeypatch.setattr(aw, "load_aipacs_web_config",
                        lambda: {"base_url": "http://h/consult", "enabled": True})
    monkeypatch.setattr(
        aw, "pair_workstation",
        lambda base, creds, **kw: {"token": "tok", "user": {"id": 5, "email": "dr@x.com", "name": "Dr X"}},
    )
    saved = {}
    monkeypatch.setattr(
        secure_store, "save_secret",
        lambda provider, subject, payload: saved.__setitem__((provider, subject), payload) or True,
    )

    ident = prov.connect("drv", credentials={"email": "dr@x.com", "password": "pw"})
    assert ident.provider == "aipacs_web"
    assert ident.subject_id == "5"
    assert ident.handle == "dr@x.com"
    assert ident.display_name == "Dr X"
    assert ident.aipacs_user == "drv"
    assert "consultation" in ident.capabilities
    assert saved[("aipacs_web", "5")] == {"token": "tok", "base_url": "http://h/consult"}


def test_connect_requires_credentials(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available", lambda self: (True, "ok"))
    with pytest.raises(RuntimeError, match="credentials"):
        prov.connect("drv")


def test_connect_raises_when_unavailable(monkeypatch):
    prov = AipacsWebIdentityProvider()
    monkeypatch.setattr(AipacsWebIdentityProvider, "is_available", lambda self: (False, "no config"))
    with pytest.raises(RuntimeError, match="no config"):
        prov.connect("drv", credentials={"pairing_code": "c"})


def test_disconnect_deletes_secret(monkeypatch):
    from modules.Identity.models import ExternalIdentity

    deleted = []
    monkeypatch.setattr(secure_store, "delete_secret",
                        lambda provider, subject: deleted.append((provider, subject)))
    ident = ExternalIdentity(provider="aipacs_web", subject_id="5", aipacs_user="drv")
    AipacsWebIdentityProvider().disconnect(ident)
    assert deleted == [("aipacs_web", "5")]


def test_build_client_requires_stored_token(monkeypatch):
    from modules.Identity.models import ExternalIdentity

    monkeypatch.setattr(secure_store, "load_secret", lambda provider, subject: None)
    ident = ExternalIdentity(provider="aipacs_web", subject_id="5", aipacs_user="drv")
    with pytest.raises(AipacsWebError, match="sign in"):
        AipacsWebIdentityProvider().build_client(ident)


def test_capability_client_is_the_api_client(monkeypatch):
    from modules.Identity.models import ExternalIdentity

    monkeypatch.setattr(secure_store, "load_secret",
                        lambda provider, subject: {"token": "tok", "base_url": "http://h"})
    ident = ExternalIdentity(provider="aipacs_web", subject_id="5", aipacs_user="drv")
    client = AipacsWebIdentityProvider().get_capability_client(ident, Capability.CONSULTATION)
    assert isinstance(client, AipacsWebClient)
    assert client.base_url == "http://h"


def test_provider_is_registered():
    from modules.Identity import registry

    registry.reset_for_tests()
    try:
        prov = registry.get_provider("aipacs_web")
        assert prov is not None and prov.id == "aipacs_web"
    finally:
        registry.reset_for_tests()


# ── API client ─────────────────────────────────────────────────────────────────
def _client(responses):
    sess = _FakeSession(responses)
    return AipacsWebClient("http://h/consult", "tok", session=sess), sess


def test_client_sends_bearer_and_json_accept():
    client, sess = _client([_FakeResp(200, {"id": 1, "email": "a@b.c"})])
    me = client.me()
    assert me["email"] == "a@b.c"
    call = sess.calls[0]
    assert call["url"] == "http://h/consult/api/v1/me"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["headers"]["Accept"] == "application/json"


def test_client_consultants_unwraps_data_envelope():
    client, _ = _client([_FakeResp(200, {"data": [{"name": "Dr A"}, {"name": "Dr B"}]})])
    rows = client.consultants()
    assert [r["name"] for r in rows] == ["Dr A", "Dr B"]


def test_client_consultants_accepts_bare_list():
    client, _ = _client([_FakeResp(200, [{"name": "Dr A"}])])
    assert client.consultants() == [{"name": "Dr A"}]


def test_client_consultants_no_args_sends_no_params():
    client, sess = _client([_FakeResp(200, {"consultants": []})])
    client.consultants()
    assert sess.calls[0]["params"] is None  # byte-identical to pre-ADR-0007


def test_client_consultants_passes_type_and_specialty_to_server():
    client, sess = _client([_FakeResp(200, {"consultants": []})])
    client.consultants(type="Internal", specialty="Neuroradiology")
    call = sess.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/api/v1/consultants")
    assert call["params"] == {"type": "internal",
                              "specialty": "Neuroradiology"}


def test_client_consultants_search_filters_client_side():
    roster = [
        {"name": "Dr Ada", "specialty": "Neuro", "expertise": "MRI brain"},
        {"name": "Dr Bob", "specialty": "MSK",
         "consultation_interests": "knee MRI"},
        {"name": "Dr Cyn", "specialty": "Chest"},
    ]
    client, sess = _client([_FakeResp(200, {"consultants": roster})])
    rows = client.consultants(search="mri")
    assert [r["name"] for r in rows] == ["Dr Ada", "Dr Bob"]
    assert sess.calls[0]["params"] is None  # search never goes to the server


def test_client_create_consultation_payload_shape():
    client, sess = _client([_FakeResp(201, {"data": {"id": 9}})])
    row = client.create_consultation(
        type="internal", consultant_address="dr.b@x.com",
        patient_ref="44113 DOE JOHN", study_uid="1.2.3", note="opinion please",
    )
    assert row == {"id": 9}
    call = sess.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/consultations")
    assert call["json"] == {
        "type": "internal", "consultant_address": "dr.b@x.com",
        "patient_ref": "44113 DOE JOHN", "study_uid": "1.2.3", "note": "opinion please",
    }
    assert "drive_folder_id" not in call["json"]


def test_client_create_consultation_metadata_kwargs_sent_when_non_empty():
    """Workflow v2 (2026-06-12): center_id/patient_id/study_date/modality."""
    client, sess = _client([_FakeResp(201, {"data": {"id": 11}})])
    client.create_consultation(
        type="internal", consultant_address="dr.b@x.com",
        patient_ref="44113 DOE JOHN",
        center_id="C7", patient_id="44113",
        study_date="2026-06-10", modality="MRI",
    )
    body = sess.calls[0]["json"]
    assert body["center_id"] == "C7"
    assert body["patient_id"] == "44113"
    assert body["study_date"] == "2026-06-10"
    assert body["modality"] == "MRI"


def test_client_create_consultation_metadata_omitted_when_empty():
    """Empty metadata kwargs keep the pre-v2 POST body byte-identical."""
    client, sess = _client([_FakeResp(201, {"data": {"id": 12}})])
    client.create_consultation(
        type="internal", consultant_address="dr.b@x.com",
        patient_ref="44113 DOE JOHN",
        center_id="", patient_id="", study_date="", modality="",
    )
    body = sess.calls[0]["json"]
    assert body == {
        "type": "internal", "consultant_address": "dr.b@x.com",
        "patient_ref": "44113 DOE JOHN",
    }


def test_client_create_external_carries_drive_folder():
    client, sess = _client([_FakeResp(201, {"id": 10})])
    client.create_consultation(
        type="external", consultant_address="dr.b@x.com",
        patient_ref="44113 DOE", drive_folder_id="folder123",
    )
    assert sess.calls[0]["json"]["drive_folder_id"] == "folder123"


def test_client_list_consultations_box_param():
    client, sess = _client([_FakeResp(200, {"data": []})])
    client.list_consultations(box="inbox")
    assert sess.calls[0]["params"] == {"box": "inbox"}
    assert sess.calls[0]["method"] == "GET"


def test_client_update_consultation_patches_fields():
    client, sess = _client([_FakeResp(200, {"id": 4, "status": "accepted"})])
    row = client.update_consultation(4, status="accepted")
    assert row["status"] == "accepted"
    call = sess.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"].endswith("/api/v1/consultations/4")
    assert call["json"] == {"status": "accepted"}


def test_client_401_says_sign_in_again():
    client, _ = _client([_FakeResp(401, {"message": "Unauthenticated."})])
    with pytest.raises(AipacsWebError, match="sign in again"):
        client.me()


def test_client_network_error_is_clean():
    class _Boom:
        def request(self, *a, **k):
            raise OSError("refused")

    client = AipacsWebClient("http://h", "tok", session=_Boom())
    with pytest.raises(AipacsWebError, match="Could not reach"):
        client.consultants()


# ── ADR-0007 client methods (profile / storage / shared) ───────────────────────
def test_client_my_profile_envelope():
    client, sess = _client([_FakeResp(200, {"profile": {"name": "Dr A"},
                                            "configured": True})])
    prof = client.my_profile()
    assert prof["configured"] is True
    assert prof["profile"]["name"] == "Dr A"
    call = sess.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/api/v1/me/profile")


def test_client_my_profile_null_profile():
    client, _ = _client([_FakeResp(200, {"profile": None, "configured": False})])
    assert client.my_profile() == {"profile": None, "configured": False}


def test_client_my_profile_tolerates_data_wrapper():
    client, _ = _client([_FakeResp(200, {"data": {"profile": {"name": "X"},
                                                  "configured": True}})])
    assert client.my_profile()["profile"]["name"] == "X"


def test_client_update_my_profile_put_and_unwrap():
    client, sess = _client([_FakeResp(200, {"profile": {"name": "New",
                                                        "availability": "busy"}})])
    row = client.update_my_profile(name="New", availability="busy",
                                   accepts_consultations=True)
    assert row["name"] == "New"
    call = sess.calls[0]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/api/v1/me/profile")
    assert call["json"] == {"name": "New", "availability": "busy",
                            "accepts_consultations": True}


def test_client_update_my_profile_strips_server_controlled_fields():
    client, sess = _client([_FakeResp(200, {"profile": {}})])
    client.update_my_profile(name="N", address="hax@x", type="external")
    assert sess.calls[0]["json"] == {"name": "N"}


def test_client_my_storage_unwraps_storage_envelope():
    client, sess = _client([_FakeResp(200, {"storage": {"quota_bytes": 100,
                                                        "used_bytes": 40}})])
    s = client.my_storage()
    assert s["quota_bytes"] == 100 and s["used_bytes"] == 40
    assert sess.calls[0]["url"].endswith("/api/v1/me/storage")


def test_client_my_storage_accepts_bare_object():
    client, _ = _client([_FakeResp(200, {"quota_bytes": 7, "used_bytes": 3})])
    assert client.my_storage()["quota_bytes"] == 7


def test_client_storage_breakdown_keeps_marker_keys():
    payload = {"total_bytes": 90, "breakdown": {"consultations": 50, "other": 40},
               "largest_folders": [{"name": "f", "id": "1", "bytes": 50}],
               "cleanup_candidates": []}
    client, sess = _client([_FakeResp(200, dict(payload))])
    b = client.storage_breakdown()
    # The body's own "breakdown" sub-key must NOT be mistaken for an envelope.
    assert b["total_bytes"] == 90
    assert b["breakdown"]["consultations"] == 50
    assert sess.calls[0]["url"].endswith("/api/v1/me/storage/breakdown")


def test_client_storage_breakdown_tolerates_data_wrapper():
    payload = {"data": {"total_bytes": 5, "breakdown": {"other": 5}}}
    client, _ = _client([_FakeResp(200, payload)])
    assert client.storage_breakdown()["total_bytes"] == 5


def test_client_shared_content_normalizes_lists():
    client, sess = _client([_FakeResp(200, {
        "shared_by_me": [{"name": "Course A", "grants": [{"grantee_address": "x"}]}],
        "shared_with_me": [],
    })])
    shared = client.shared_content()
    assert [r["name"] for r in shared["shared_by_me"]] == ["Course A"]
    assert shared["shared_with_me"] == []
    assert sess.calls[0]["url"].endswith("/api/v1/education/shared")


def test_client_shared_content_tolerates_wrapper_and_missing_keys():
    client, _ = _client([_FakeResp(200, {"data": {"shared_with_me": [{"name": "B"}]}})])
    shared = client.shared_content()
    assert shared["shared_by_me"] == []
    assert [r["name"] for r in shared["shared_with_me"]] == ["B"]
