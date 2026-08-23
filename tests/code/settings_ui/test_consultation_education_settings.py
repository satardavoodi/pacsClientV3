"""Settings ▸ Consultation & Education — writers, routing guards, smoke.

The tab centralizes settings that were file/env-only; these tests pin:
* the three new ``save_*`` writers (merge semantics, unknown-key preservation,
  env-override reporting) — Qt-free;
* the sign-in routing rules the Identity module enforces repo-wide (modeless
  launcher, never ``exec()``, never the Drive hub connect from an identity
  button) — source-level, Qt-free;
* that the tab is actually registered in SettingsTabWidget;
* an offscreen construction smoke test (no network: refresh only reads config
  files and the local identity DB).
"""

import inspect
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def qapp_offscreen():
    """A live offscreen QApplication for the tests that build the widget."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ── cloud_consultation flag writer ────────────────────────────────────────────
def test_cloud_flag_writer_merges_and_preserves_unknown_keys(tmp_path, monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    path = tmp_path / "cloud_consultation.json"
    path.write_text(
        json.dumps({"enabled": True, "oauth_embedded": False, "junk": 1}),
        encoding="utf-8")
    monkeypatch.setattr(ff, "_flag_file_path", lambda: path)

    assert ff.save_flag_values({
        "hub_mode": True,
        "consultation_address": "doc@x.com",
        "nonsense": "must be ignored",
    })
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hub_mode"] is True
    assert data["consultation_address"] == "doc@x.com"
    assert data["enabled"] is True            # untouched keys survive
    assert data["oauth_embedded"] is False    # unknown-to-the-tab keys survive
    assert data["junk"] == 1
    assert "nonsense" not in data             # only editable keys are written


def test_cloud_flag_writer_creates_file_and_parents(tmp_path, monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    path = tmp_path / "sub" / "cloud_consultation.json"
    monkeypatch.setattr(ff, "_flag_file_path", lambda: path)
    assert ff.save_flag_values({"enabled": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"enabled": True}


def test_flag_values_returns_file_payload_without_env(tmp_path, monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    path = tmp_path / "cloud_consultation.json"
    path.write_text(json.dumps({"consultation_address": "file@x.com"}),
                    encoding="utf-8")
    monkeypatch.setattr(ff, "_flag_file_path", lambda: path)
    monkeypatch.setenv("AIPACS_CONSULTATION_ADDRESS", "env@x.com")
    # flag_values is the FILE view (what the Settings fields edit)…
    assert ff.flag_values()["consultation_address"] == "file@x.com"
    # …while the authority still resolves the env override.
    assert ff.consultation_address() == "env@x.com"


def test_env_overrides_reports_only_set_vars(monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    for var in ("AIPACS_CLOUD_CONSULTATION", "AIPACS_CONSULTATION_HUB_MODE",
                "AIPACS_CONSULTATION_ADDRESS", "AIPACS_CONSULTATION_CENTER_ID"):
        monkeypatch.delenv(var, raising=False)
    assert ff.env_overrides() == {}
    monkeypatch.setenv("AIPACS_CONSULTATION_ADDRESS", "someone@x.com")
    assert ff.env_overrides() == {
        "consultation_address": "AIPACS_CONSULTATION_ADDRESS"}


# ── aipacs_web config writer ──────────────────────────────────────────────────
def test_aipacs_web_writer_round_trip(tmp_path, monkeypatch):
    from modules.Identity.providers import aipacs_web as aw

    path = tmp_path / "aipacs_web.json"
    path.write_text(json.dumps({"base_url": "https://old", "custom": "kept"}),
                    encoding="utf-8")
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: path)
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)

    assert aw.save_aipacs_web_config("https://ai-pacs.com/consult-form/",
                                     enabled=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_url"] == "https://ai-pacs.com/consult-form"  # slash trimmed
    assert data["custom"] == "kept"
    assert aw.load_aipacs_web_config() == {
        "base_url": "https://ai-pacs.com/consult-form", "enabled": True}


def test_aipacs_web_writer_disable_round_trip(tmp_path, monkeypatch):
    from modules.Identity.providers import aipacs_web as aw

    path = tmp_path / "aipacs_web.json"
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: path)
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    assert aw.save_aipacs_web_config("https://x", enabled=False)
    assert aw.aipacs_web_configured() is False


def test_aipacs_web_env_override_detection(monkeypatch):
    from modules.Identity.providers import aipacs_web as aw

    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    assert aw.aipacs_web_env_override() == ""
    monkeypatch.setenv("AIPACS_WEB_BASE_URL", "https://env")
    assert aw.aipacs_web_env_override() == "AIPACS_WEB_BASE_URL"


# ── identity flag writer ──────────────────────────────────────────────────────
def test_identity_flag_writer_round_trip(tmp_path, monkeypatch):
    import modules.Identity.config as cfg_mod
    from modules.Identity import feature_flags as ff

    path = tmp_path / "identity.json"
    monkeypatch.setattr(cfg_mod, "identity_flag_file_path", lambda: path)
    monkeypatch.delenv("AIPACS_IDENTITY_MODULE", raising=False)
    assert ff.save_identity_enabled(True)
    assert ff.identity_module_enabled() is True
    assert ff.save_identity_enabled(False)
    assert ff.identity_module_enabled() is False


# ── aipacs_chat flag writer ───────────────────────────────────────────────────
def test_chat_flag_writer_round_trip(tmp_path, monkeypatch):
    from modules.aipacs_chat import feature_flags as ff

    path = tmp_path / "aipacs_chat.json"
    path.write_text(json.dumps({"custom": "kept"}), encoding="utf-8")
    monkeypatch.setattr(ff, "_flag_file_path", lambda: path)
    monkeypatch.delenv("AIPACS_CHAT", raising=False)

    assert ff.save_aipacs_chat_enabled(True)
    assert ff.aipacs_chat_enabled() is True
    assert json.loads(path.read_text(encoding="utf-8"))["custom"] == "kept"
    assert ff.save_aipacs_chat_enabled(False)
    assert ff.aipacs_chat_enabled() is False


def test_chat_env_override_detection(monkeypatch):
    from modules.aipacs_chat import feature_flags as ff

    monkeypatch.delenv("AIPACS_CHAT", raising=False)
    assert ff.aipacs_chat_env_override() == ""
    monkeypatch.setenv("AIPACS_CHAT", "1")
    assert ff.aipacs_chat_env_override() == "AIPACS_CHAT"


def test_chat_connection_test_is_offthread_and_readonly():
    """The probe must run on a worker (network blocks) and must use the
    read-only statuses endpoint — NEVER /chat/sync, which WRITES server state
    (clears unread, cancels the staff notification email)."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._test_chat_connection)
    assert "_start_worker" in src
    assert "statuses()" in src
    assert ".sync(" not in src


def test_web_console_link_derives_from_staff_panel_authority():
    """The chat-console button must build the staff-panel login from the
    staff-panel authority — never a stored second copy of the address."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    widget_cls = ces.ConsultationEducationSettingsWidget
    assert "_open_staff_panel" in inspect.getsource(widget_cls._open_web_chat_console)
    panel = inspect.getsource(widget_cls._open_staff_panel)
    assert "staff_panel_url" in panel
    assert "load_aipacs_web_config" in inspect.getsource(widget_cls._web_base_url)


# ── the two mounts are NOT nested (verified against the deployment) ───────────
def test_portal_url_is_a_sibling_mount_not_a_sub_path(tmp_path, monkeypatch):
    """ai-pacs.com serves the portal and the API/forms mount side by side.

    `/consult-form/ai-pacs-consultation` is 404'd by .htaccess, so the portal
    address must be built from the HOST — appending to base_url would produce a
    dead link. This is the trap this test exists to prevent.
    """
    from modules.Identity.providers import aipacs_web as aw

    path = tmp_path / "aipacs_web.json"
    path.write_text(json.dumps({"base_url": "https://ai-pacs.com/consult-form"}),
                    encoding="utf-8")
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: path)
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)

    assert aw.portal_url() == "https://ai-pacs.com/ai-pacs-consultation"
    assert "consult-form" not in aw.portal_url()
    # The staff panel DOES live under the base URL — same mount as the API.
    assert aw.staff_panel_url() == "https://ai-pacs.com/consult-form/forms-panel"


def test_portal_url_explicit_override_wins(tmp_path, monkeypatch):
    from modules.Identity.providers import aipacs_web as aw

    path = tmp_path / "aipacs_web.json"
    path.write_text(
        json.dumps({"base_url": "https://ai-pacs.com/consult-form",
                    "portal_url": "https://portal.example.test/x/"}),
        encoding="utf-8")
    monkeypatch.setattr(aw, "aipacs_web_config_path", lambda: path)
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    assert aw.portal_url() == "https://portal.example.test/x"


def test_portal_url_empty_when_unconfigured(tmp_path, monkeypatch):
    from modules.Identity.providers import aipacs_web as aw

    monkeypatch.setattr(aw, "aipacs_web_config_path",
                        lambda: tmp_path / "missing.json")
    monkeypatch.delenv("AIPACS_WEB_BASE_URL", raising=False)
    assert aw.portal_url() == ""
    assert aw.staff_panel_url() == ""


# ── roles come from the SERVER, never from a client-side guess ────────────────
def test_access_check_probes_the_server_and_invents_no_role():
    """`GET /api/v1/me` returns `roles: []` hard-coded and never serialises
    is_admin, so the tab must ASK each area and read 200 vs 403. A client-side
    role model would be a second opinion about a server-only decision."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._check_access)
    assert "_start_worker" in src            # network → off the GUI thread
    assert "statuses()" in src               # read-only chat probe, not /sync
    assert ".sync(" not in src
    # The integration contract's probe endpoints, exactly.
    assert '"/consultants"' in src
    assert '"/education/shared"' in src
    # Entitlements are asked for FIRST; a 404 falls through to probing, so the
    # same client works against today's server and the improved one.
    assert '"/me/entitlements"' in src
    assert src.index('"/me/entitlements"') < src.index('"/consultants"')


def test_probe_failures_are_unknown_not_denied():
    """A network blink must never disable a clinician's modules: 403 is a
    server answer, anything else is Unknown."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._check_access)
    assert 'return "denied"' in src and "403" in src
    assert 'return "unknown"' in src
    render = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._render_access)
    assert "STATE_UNKNOWN" in render and "STATE_UNAUTHORIZED" in render
    # 403 is reported as the server's answer, not as a transport failure.
    assert "denied" in render


# ── identity first: nothing is asked before we know who is asking ────────────
def test_sections_two_and_three_stay_hidden_until_signed_in(monkeypatch,
                                                            qapp_offscreen):
    """Owner directive: identity → access → settings. Current user and Access
    must not be on screen before an AI-PACS sign-in exists."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    monkeypatch.setattr(ces, "_resolve_auth_user", lambda: {"username": "tester"})
    monkeypatch.setattr(
        ces.ConsultationEducationSettingsWidget, "_aipacs_identity",
        lambda self: None)
    widget = ces.ConsultationEducationSettingsWidget()
    try:
        assert widget.box_current_user.isVisibleTo(widget) is False
        assert widget.box_access.isVisibleTo(widget) is False
        # …and the two ways in are both offered.
        assert widget.btn_signin_google.text() == "Sign in with Google"
        assert widget.btn_signin_account.text() == "Sign in with AI-PACS account"
    finally:
        widget.deleteLater()


def test_sections_appear_once_an_identity_exists(monkeypatch, qapp_offscreen):
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    class _Ident:
        provider = "aipacs_web"
        subject_id = "s1"
        handle = "doc@example.test"
        display_name = "Dr Example"
        extra = {"link": {"profile_name": "Dr Example",
                          "gmail_email": "doc@example.test"}}

    monkeypatch.setattr(ces, "_resolve_auth_user", lambda: {"username": "tester"})
    monkeypatch.setattr(
        ces.ConsultationEducationSettingsWidget, "_aipacs_identity",
        lambda self: _Ident())
    widget = ces.ConsultationEducationSettingsWidget()
    try:
        assert widget.box_current_user.isVisibleTo(widget) is True
        assert widget.box_access.isVisibleTo(widget) is True
        assert "Dr Example" in widget.lbl_signed_in_as.text()
        assert widget.lbl_user_email.text() == "doc@example.test"
        # No role invented before the server has been asked.
        assert "not read yet" in widget.lbl_user_role.text()
        # Access rows wait to be told, rather than assuming.
        assert widget.row_chat.state_label.text() == "Not reported"
    finally:
        widget.deleteLater()


def test_entitlements_answer_wins_over_probes(monkeypatch, qapp_offscreen):
    """`/me/entitlements` shipped 2026-08-21. When the server publishes it, the
    UI gates on `modules` — including saying Denied for a module whose read
    probe would have returned 200, because the entitlement is the real answer.
    An unknown/missing module key counts as denied."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    monkeypatch.setattr(ces, "_resolve_auth_user", lambda: {"username": "tester"})
    monkeypatch.setattr(ces, "_online_consultation_available", lambda: True)
    monkeypatch.setattr(ces, "_education_module_enabled", lambda: True)
    monkeypatch.setattr(ces, "_chat_available", lambda: True)
    widget = ces.ConsultationEducationSettingsWidget()
    try:
        widget._render_access({
            "signed_in": True,
            "account": "ok",
            "role": "panel_manager",
            "is_super_admin": False,
            "panels": {"consultation": "manage", "chat": None},
            "entitlements": {"consultation": True, "education": False,
                             "chat": False, "consultation_response": True,
                             "course_creation": False, "chat_manager": False},
            # The probes disagree on purpose: entitlements must win.
            "consultation": "allowed", "education": "allowed",
            "chat": "granted",
            "profile": {"configured": True, "name": "Dr Example",
                        "type": "internal", "accepts": True},
        })
        assert widget.row_consultation.state_label.text() == "Available"
        assert widget.row_education.state_label.text() == "Not authorized"
        assert widget.row_chat.state_label.text() == "Not authorized"
        # The grant model is surfaced for the administrator at the machine.
        assert "panel grants" in widget.lbl_access_note.text()
        assert "consultation: manage" in widget.lbl_access_note.text()
        # Sub-capabilities the server names separately are shown, not invented.
        assert "Answer consultations: yes" in widget.row_other.detail.text()
        assert "Create/publish courses: no" in widget.row_other.detail.text()
    finally:
        widget.deleteLater()


def test_account_signin_opens_the_credentials_half(monkeypatch, qapp_offscreen):
    """"Sign in with AI-PACS account" is the SAME dialog, opened on the email +
    password / pairing fields — not a second auth mechanism."""
    import modules.Identity.ui.aipacs_web_dialog as dlg_mod

    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    monkeypatch.setattr(ces, "_resolve_auth_user", lambda: {"username": "tester"})
    widget = ces.ConsultationEducationSettingsWidget()
    captured = {}

    def _fake_open(service, parent=None, *, on_success=None, on_finished=None,
                   expand_account=False):
        captured["expand_account"] = expand_account
        return None

    monkeypatch.setattr(dlg_mod, "open_signin_dialog", _fake_open)
    try:
        widget._sign_in_with_account()
        assert captured.get("expand_account") is True
        widget._sign_in_aipacs_web()
        assert captured.get("expand_account") is False
    finally:
        widget.deleteLater()


def test_signin_dialog_exposes_the_account_half():
    """The dialog must offer the credentials path publicly — Settings presents
    it as a first-class choice, not a hidden admin fallback."""
    from modules.Identity.ui import aipacs_web_dialog

    assert hasattr(aipacs_web_dialog.AipacsWebSignInDialog, "expand_account_signin")
    launcher = inspect.getsource(aipacs_web_dialog.open_signin_dialog)
    assert "expand_account" in launcher
    assert ".show()" in launcher and ".exec(" not in launcher


# ── links open INSIDE the workstation (owner directive 2026-08-20) ────────────
def test_links_open_in_internal_browser_never_system_browser():
    """Every link this tab opens must go through the workstation's embedded Web
    Browser module.

    oauth_flow.py states the repo rule outright — "never call
    webbrowser.open() directly" — and `open_verification_url` is the sanctioned
    opener (docked module tab → floating window, with the 0x8001010d
    crash-hardening a click needs). A regression here would launch Chrome/Edge
    outside the workstation, which the owner has ruled out.
    """
    from pathlib import Path

    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    module_src = Path(ces.__file__).read_text(encoding="utf-8")
    assert "webbrowser" not in module_src, (
        "the settings tab must not use the system browser")

    opener = inspect.getsource(ces.ConsultationEducationSettingsWidget._open_link)
    assert "open_verification_url" in opener

    # Every link opener routes through the one helper (the chat console goes
    # through _open_staff_panel, which is itself checked here).
    for name in ("_open_staff_panel", "_open_portal", "_open_website"):
        src = inspect.getsource(getattr(ces.ConsultationEducationSettingsWidget, name))
        assert "_open_link" in src, f"{name} must use the internal-browser helper"
    assert "_open_staff_panel" in inspect.getsource(
        ces.ConsultationEducationSettingsWidget._open_web_chat_console)


def test_open_link_reports_when_embedded_browser_unavailable(monkeypatch, qapp_offscreen):
    """When the embedded browser cannot be used, the tab must SAY so — never
    silently fall back to the operating system's browser."""
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    monkeypatch.setattr(ces, "_resolve_auth_user", lambda: {"username": "tester"})
    widget = ces.ConsultationEducationSettingsWidget()
    shown = {}

    class _FakeBox:
        # Mirror the real signature: the widget reads QMessageBox.Information
        # off the CLASS before constructing. A double missing it fails at the
        # attribute, which reads like a widget bug rather than a stale double.
        Information = object()

        def __init__(self, *a, **k):
            pass

        def setIcon(self, *a):
            pass

        def setWindowTitle(self, t):
            shown["title"] = t

        def setText(self, t):
            shown["text"] = t

        def setInformativeText(self, t):
            shown["url"] = t

        def setTextInteractionFlags(self, *a):
            pass

        def exec(self):
            shown["shown"] = True

    monkeypatch.setattr(ces, "QMessageBox", _FakeBox)
    # Simulate "embedded browser not usable" (module off / headless).
    import modules.Identity.providers.google.oauth_flow as oauth_flow

    monkeypatch.setattr(oauth_flow, "open_verification_url", lambda url: False)
    try:
        widget._open_link("https://example.test/page", what="Test link")
        assert shown.get("shown") is True
        assert shown["url"] == "https://example.test/page"
    finally:
        widget.deleteLater()


# ── sign-in routing guards (same rules test_connect_button_routing pins) ──────
def test_settings_signin_routes_through_modeless_launcher():
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._sign_in_aipacs_web)
    assert "open_signin_dialog" in src
    assert ".exec(" not in src
    # The identity button must never trigger the Drive hub connect.
    assert 'connect("google")' not in src


def test_drive_connect_runs_off_gui_thread():
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(
        ces.ConsultationEducationSettingsWidget._connect_drive)
    assert "_start_worker" in src              # OAuth blocks; never inline
    assert 'connect("google")' in src


def test_tab_registered_in_settings_shell():
    root = Path(__file__).resolve().parents[3]
    src = (root / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui"
           / "settings_ui.py").read_text(encoding="utf-8")
    assert "Consultation & Education" in src
    assert "_create_consultation_education_settings" in src


# ── offscreen construction smoke ──────────────────────────────────────────────
def test_widget_constructs_offscreen(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(ces, "_resolve_auth_user",
                        lambda: {"username": "tester", "full_name": "Dr Test",
                                 "role": "Radiologist"})
    widget = ces.ConsultationEducationSettingsWidget()
    try:
        # The workstation user (never the patient) is named, with their role.
        assert "Dr Test" in widget.lbl_workstation_user.text()
        assert "Radiologist" in widget.lbl_workstation_user.text()
        # Every section rendered something (refresh ran without raising).
        assert widget.lbl_local_user.text() != "—"
        assert widget.lbl_gate_verdict.text() != "—"
        assert widget.lbl_drive_auth.text() != "—"
        assert widget.lbl_chat_identity.text() != "—"
        # Refresh is idempotent.
        widget._refresh()
    finally:
        widget.deleteLater()
