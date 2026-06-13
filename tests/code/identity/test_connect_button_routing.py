"""Guard: the account-popup "Connect Google Account" action routes to the
IDENTITY attestation/link path (attest_gmail → link-google), NOT the Drive hub
connect (provider.connect("google")).

Background (crash-fix investigation 2026-06-12): a user signed into Gmail but
"could not connect to the identity". One hypothesised cause was the connect
button being wired to the hub Drive connect instead of the aipacs_web identity
attestation. These tests pin the correct wiring so it cannot drift:

* ``AccountPopup._sign_in_aipacs_web`` opens ``AipacsWebSignInDialog`` (the
  one-button identity dialog) — it does NOT call ``service.connect("google")``;
* ``AipacsWebSignInDialog`` runs the attestation worker, which calls
  ``IdentityService.connect_aipacs_web_via_google`` (→
  ``provider.connect_via_google_attestation``);
* ``IdentityService.connect_aipacs_web_via_google`` delegates to the
  ``aipacs_web`` provider's attestation method (the identity/link path).

Source-level assertions keep the test Qt-free (no QApplication needed).
"""

import inspect


def test_connect_button_handler_opens_identity_dialog_not_drive_connect():
    from modules.cloud_consultation.ui import account_popup

    src = inspect.getsource(account_popup.AccountPopup._sign_in_aipacs_web)
    # Routes to the identity sign-in dialog (now via the modeless launcher,
    # which opens AipacsWebSignInDialog internally — live bug 2026-06-12).
    assert "open_signin_dialog" in src
    # …and must NOT trigger the hub Drive connect ("google") from this button.
    assert 'connect("google")' not in src
    assert "_ConnectWorker" not in src


def test_signin_dialog_primary_button_runs_attestation_worker():
    from modules.Identity.ui import aipacs_web_dialog

    # The primary "Sign in with Google" handler starts the attestation worker.
    on_verify = inspect.getsource(
        aipacs_web_dialog.AipacsWebSignInDialog._on_verify_google
    )
    assert "_AttestWorker" in on_verify

    # The attestation worker calls the IDENTITY attestation route, never a
    # Drive/hub connect.
    worker_run = inspect.getsource(aipacs_web_dialog._AttestWorker.run)
    assert "connect_aipacs_web_via_google" in worker_run
    assert 'connect("google")' not in worker_run


def test_service_route_delegates_to_provider_attestation(monkeypatch):
    """``connect_aipacs_web_via_google`` must call the aipacs_web provider's
    ``connect_via_google_attestation`` (the attest→link path) and upsert the
    returned identity — not the Google Drive provider's ``connect``."""
    from modules.Identity import identity_service as svc_mod
    from modules.Identity.identity_service import IdentityService

    calls = {}

    class _FakeProvider:
        def connect_via_google_attestation(self, user, gmail, *, server_id="",
                                           center_id=""):
            calls["attestation"] = {"user": user, "gmail": gmail,
                                    "server_id": server_id}
            return "the-identity"

        def connect(self, *a, **k):  # pragma: no cover - must not be called
            calls["drive_connect"] = True
            return "WRONG"

    monkeypatch.setattr(svc_mod, "get_provider",
                        lambda pid: _FakeProvider() if pid == "aipacs_web" else None)

    import database.identity_db as idb

    upserts = []
    monkeypatch.setattr(idb, "upsert_identity", lambda ident: upserts.append(ident))

    out = IdentityService("drv").connect_aipacs_web_via_google("a@gmail.com",
                                                               server_id="srv1")

    assert out == "the-identity"
    assert calls["attestation"] == {"user": "drv", "gmail": "a@gmail.com",
                                    "server_id": "srv1"}
    assert "drive_connect" not in calls  # the hub Drive connect is NOT used
    assert upserts == ["the-identity"]


# ── modeless sign-in (live bug 2026-06-12) ────────────────────────────────────
# The Google consent page opens in the DOCKED browser (same top-level window);
# a modal exec() would grab input and block the user from clicking their Google
# account behind the dialog. These source-level guards (Qt-free) pin that the
# dialog is constructed NON-modal and that every caller routes through the
# modeless launcher instead of exec().


def test_signin_dialog_constructed_non_modal():
    from modules.Identity.ui import aipacs_web_dialog

    ctor = inspect.getsource(aipacs_web_dialog.AipacsWebSignInDialog.__init__)
    # Modeless: explicitly non-modal, never application-modal.
    assert "setModal(False)" in ctor
    assert "Qt.NonModal" in ctor
    assert "ApplicationModal" not in ctor


def test_modeless_launcher_uses_show_not_exec():
    from modules.Identity.ui import aipacs_web_dialog

    # The supported entry point exists and shows modeless (show(), not exec()).
    assert hasattr(aipacs_web_dialog, "open_signin_dialog")
    launcher = inspect.getsource(aipacs_web_dialog.open_signin_dialog)
    assert ".show()" in launcher
    assert ".exec(" not in launcher
    # It keeps a strong reference so the modeless dialog isn't GC'd.
    assert "_LIVE_SIGNIN_DIALOG_ATTR" in launcher


def test_all_signin_callers_use_modeless_launcher_not_exec():
    """Every place that opens the sign-in dialog must use the modeless launcher
    (open_signin_dialog), never a modal AipacsWebSignInDialog(...).exec()."""
    from modules.cloud_consultation.ui import account_popup, manage_account_dialog
    from modules.education.online_consultation import (
        assign_dialog,
        consultation_page,
    )

    callers = {
        "account_popup._sign_in_aipacs_web":
            account_popup.AccountPopup._sign_in_aipacs_web,
        "manage_account_dialog._connect_identity":
            manage_account_dialog.ManageAccountDialog._connect_identity,
        "consultation_page._sign_in_aipacs_web":
            consultation_page.OnlineConsultationPage._sign_in_aipacs_web,
        "assign_dialog._sign_in":
            assign_dialog.ConsultationAssignDialog._sign_in,
    }
    for name, fn in callers.items():
        src = inspect.getsource(fn)
        assert "open_signin_dialog" in src, f"{name} must use open_signin_dialog"
        assert ".exec(" not in src, f"{name} must not call a modal exec()"
