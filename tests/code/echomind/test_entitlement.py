"""Guard: Turbo inherits its licence from the AI-PACS authorisation (2026-08-09).

OWNER DECISION. Turbo used to be a subfunction of the AI-PACS backend, so one company
key covered both. Turbo now holds its own hardcoded GapGPT configuration and connects
directly. Technical separation must not become LICENSING separation:

    valid AI-PACS authorisation -> backend enabled  AND Turbo enabled
    no valid authorisation      -> backend disabled AND Turbo disabled

The user's own OpenAI key stays outside this: EchoMind being installed is the only
requirement, because it spends the user's quota rather than the company's.

WHAT THE AUDIT FOUND. An install with nothing entered, and an install with junk in
settings, were already denied everywhere — the premise that Turbo was wide open was
not true through those routes. Two things were real:

  * THE TEST ACCOUNT. `validate_key(<TEST key>)` returned ok=True/code=TEST and the
    company key then resolved — full backend and Turbo. That key is a literal string
    in the shipped binary and `validate_key` is a purely local lookup, so `strings`
    on the exe was enough to licence yourself.
  * `is_active_backend_configured()` measured "is a string stored", so it said True
    for unvalidated junk and False for a key validated in memory but not yet saved.

And structurally the decision lived in four places with four shapes. Eleven call sites
reach a company function through `_ai_module(backend).<fn>()`; the next one added would
have had to remember to re-implement the check. Hence one authority.
"""

import importlib
import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import api_manager as am                          # noqa: E402
from modules.EchoMind import entitlement as ent                         # noqa: E402
from modules.EchoMind import llm_client                                 # noqa: E402
from modules.EchoMind import settings_store                             # noqa: E402
from modules.EchoMind.api_manager import (  # noqa: E402
    APIKeyManager,
    CenterRecord,
    Manage,
)
from modules.EchoMind.credential_envelope import seal_provider_key  # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


_REAL_ACCESS_CODE = "unit-real-center-access"
_TEST_ACCESS_CODE = "unit-development-center-access"


def _record(code: str, access_code: str) -> CenterRecord:
    return CenterRecord(
        center_code=code,
        center_display=f"{code} Center",
        credentials=(seal_provider_key(access_code, f"provider-token-{code}", code),),
    )


_TEST_CENTERS = [
    _record("UNIT", _REAL_ACCESS_CODE),
    _record("TEST", _TEST_ACCESS_CODE),
]


def _test_key():
    return _TEST_ACCESS_CODE


def _real_key():
    return _REAL_ACCESS_CODE


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """The manager is a process-wide singleton and the registry is module state.
    Both are restored, or these tests would licence (or de-licence) the rest of the
    suite depending on ordering."""
    mgr = APIKeyManager.instance()
    saved = (
        mgr._current_api_key,
        mgr._current_center_code,
        mgr._current_provider_key,
        mgr._is_validated,
    )
    saved_maps = (am._CENTERS_BY_CODE, am._KEY_TO_CENTER_CODE)
    monkeypatch.setattr(am, "CENTERS", list(_TEST_CENTERS))
    am._CENTERS_BY_CODE, am._KEY_TO_CENTER_CODE = am._build_registry_maps(am.CENTERS)
    stored = {"v": ""}
    monkeypatch.setattr(settings_store, "get_echomind_api_key", lambda: stored["v"])
    monkeypatch.setattr(llm_client, "get_echomind_api_key", lambda: stored["v"])
    mgr.reset()
    try:
        yield stored
    finally:
        am._CENTERS_BY_CODE, am._KEY_TO_CENTER_CODE = saved_maps
        (
            mgr._current_api_key,
            mgr._current_center_code,
            mgr._current_provider_key,
            mgr._is_validated,
        ) = saved


# ── the target access model, end to end ──────────────────────────────────────

def test_no_key_at_all_is_not_entitled(_isolate):
    assert ent.company_entitled() is False


def test_junk_in_settings_is_not_entitled(_isolate):
    """It was never validated. Storing a string is not a licence."""
    _isolate["v"] = "whatever-the-user-typed"
    assert ent.company_entitled() is False


def test_a_real_key_is_entitled(_isolate):
    _isolate["v"] = _real_key()
    assert ent.company_entitled() is True


def test_entitlement_self_heals_from_storage(_isolate):
    """A licensed user who has not opened Settings this session must not be locked
    out — the same self-heal `_resolve_company_backend` always had."""
    _isolate["v"] = _real_key()
    assert APIKeyManager.instance().is_validated() is False
    assert ent.company_entitled() is True
    assert APIKeyManager.instance().is_validated() is True


# ── the TEST account is not a licence ────────────────────────────────────────

def test_the_test_centre_is_absent_from_a_shipped_registry(_isolate):
    assert am.test_center_enabled() is False
    assert "TEST" not in am._CENTERS_BY_CODE


def test_the_test_key_no_longer_validates(_isolate):
    k = _test_key()
    if not k:
        pytest.skip("no TEST centre defined")
    ok, code, _err = APIKeyManager.instance().validate_key(k)
    assert ok is False and code is None


def test_the_test_key_grants_no_entitlement(_isolate):
    k = _test_key()
    if not k:
        pytest.skip("no TEST centre defined")
    _isolate["v"] = k
    assert ent.company_entitled() is False


def test_the_dev_flag_restores_it_for_local_testing(_isolate, monkeypatch):
    k = _test_key()
    if not k:
        pytest.skip("no TEST centre defined")
    monkeypatch.setenv("AIPACS_ALLOW_TEST_CENTER", "1")
    am._CENTERS_BY_CODE, am._KEY_TO_CENTER_CODE = am._build_registry_maps(am.CENTERS)
    assert am.test_center_enabled() is True
    assert "TEST" in am._CENTERS_BY_CODE
    ok, code, _e = APIKeyManager.instance().validate_key(k)
    assert ok is True and code == "TEST"


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_the_dev_flag_is_off_for_every_falsey_spelling(_isolate, monkeypatch, value):
    monkeypatch.setenv("AIPACS_ALLOW_TEST_CENTER", value)
    assert am.test_center_enabled() is False


def test_the_real_centres_are_untouched(_isolate):
    """Excluding TEST must not cost a paying centre its licence."""
    codes = set(am._CENTERS_BY_CODE)
    expected = {c.center_code.upper() for c in am.CENTERS if c.center_code != "TEST"}
    assert codes == expected
    assert codes == {"UNIT"}


# ── the chokepoint protects all eleven call sites ────────────────────────────

def test_the_company_key_cannot_be_resolved_without_entitlement(_isolate):
    """Every `_ai_module(backend).<fn>()` funnels through get_center_and_gapgpt_key.
    That is what makes a per-call-site guard unnecessary."""
    Manage.instance()._detected = None
    with pytest.raises(Exception):
        Manage.instance().get_center_and_gapgpt_key()


def test_the_company_key_resolves_once_entitled(_isolate):
    _isolate["v"] = _real_key()
    assert ent.company_entitled() is True
    Manage.instance()._detected = None
    center, key = Manage.instance().get_center_and_gapgpt_key()
    assert center and key


# ── the UI cannot offer what the licence does not cover ──────────────────────

def test_configured_is_false_for_unvalidated_junk(_isolate, monkeypatch):
    monkeypatch.setattr(llm_client, "_active_backend", lambda: "company")
    _isolate["v"] = "junk"
    assert llm_client.is_active_backend_configured() is False


def test_configured_is_true_for_a_licensed_install(_isolate, monkeypatch):
    monkeypatch.setattr(llm_client, "_active_backend", lambda: "company")
    _isolate["v"] = _real_key()
    assert llm_client.is_active_backend_configured() is True


# ── the OpenAI exception ─────────────────────────────────────────────────────

def test_openai_works_with_no_company_authorisation(_isolate, monkeypatch):
    """EchoMind installed + the user's own key is the whole requirement."""
    monkeypatch.setattr(llm_client, "_active_backend", lambda: "openai")
    monkeypatch.setattr(llm_client, "get_openai_settings",
                        lambda: {"api_key": "sk-the-users-own-key"})
    assert ent.company_entitled() is False
    assert llm_client.is_active_backend_configured() is True


def test_openai_with_no_key_is_not_configured(_isolate, monkeypatch):
    monkeypatch.setattr(llm_client, "_active_backend", lambda: "openai")
    monkeypatch.setattr(llm_client, "get_openai_settings", lambda: {"api_key": ""})
    assert llm_client.is_active_backend_configured() is False


def test_the_openai_branch_never_consults_the_company_licence():
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "llm_client.py"),
                  encoding="utf-8-sig").read()
    a = src.index("def is_active_backend_configured")
    body = src[a:src.index("\ndef ", a + 10)]
    oai = body[body.index('if backend == "openai":'):body.index("from modules.EchoMind.entitlement")]
    assert "company_entitled" not in oai
    assert "get_echomind_api_key" not in oai


# ── Turbo: hardcoded credentials are plumbing, not permission ────────────────

def _turbo_fn():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("    def _on_hq_all_modality_clicked(self):")
    return s[a:s.index("\n    def ", a + 50)]


def test_turbo_asks_the_authority():
    assert "company_entitled()" in _turbo_fn()


def test_turbo_checks_entitlement_before_it_reads_any_key():
    """The order is the point: no credential — hardcoded, stored or otherwise — may be
    consulted as a substitute for the licence."""
    fn = _turbo_fn()
    assert fn.index("company_entitled()") < fn.index("center_key")


def test_turbo_does_not_reimplement_the_check():
    """It used to inline validate_key(stored). Two copies of an entitlement rule is
    how one of them drifts."""
    fn = _turbo_fn()
    assert "manager.validate_key(" not in fn


def test_turbo_is_still_pinned_to_the_company_backend():
    assert "backend = TURBO_BACKEND" in _turbo_fn()


def test_send_and_turbo_share_the_one_authority():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("def _resolve_active_ai_identity")
    assert "company_entitled()" in s[a:s.index("\ndef ", a + 10)]


# ── fail closed ──────────────────────────────────────────────────────────────

def test_a_broken_check_denies_rather_than_allows(_isolate, monkeypatch):
    """A wrong False costs a licensed user one re-entry. A wrong True costs company
    API budget to an unlicensed install."""
    import modules.EchoMind.api_manager as broken

    def boom():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(settings_store, "get_echomind_api_key", boom)
    assert ent.company_entitled() is False


def test_the_denial_message_is_one_string():
    assert ent.ENTITLEMENT_DENIED
    src = io.open(_PAGES, encoding="utf-8-sig").read()
    assert "ENTITLEMENT_DENIED" in src
    assert src.count("Turbo requires an authorized company key") == 0, \
        "the old bespoke Turbo message survived; the UI can drift again"


def test_require_raises_when_unentitled(_isolate):
    with pytest.raises(ent.EntitlementError):
        ent.require_company_entitlement("Turbo")


def test_entitled_center_code_is_empty_when_unentitled(_isolate):
    assert ent.entitled_center_code() == ""
