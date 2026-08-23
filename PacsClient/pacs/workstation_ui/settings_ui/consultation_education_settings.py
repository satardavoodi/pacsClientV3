"""Settings ▸ Consultation & Education — identity first, then what it unlocks.

THE SHAPE, AND WHY (owner directive 2026-08-21). Identify the person → sign in
to AI-PACS → read back what that account may do → only then offer settings.
The first version of this tab did the opposite: it opened on a wall of
configuration fields (server address, routing address, centre id, hub mode,
module flags) that mean nothing until you know who is signed in. Now:

    1 · Identity          Sign in with Google, or with an AI-PACS account.
    2 · Current user      Name, email, AI-PACS account, role, login status.
    3 · Access            Consultation / Education / Chat / other services,
                          each with the state the SERVER reports.
    Configuration         Everything else, collapsed, opened when needed.

Sections 2 and 3 stay closed until sign-in succeeds, so the page never asks a
question before it has established who is answering.

ROLES ARE READ, NEVER INVENTED. ai-pacs.com does not publish roles to API
clients — ``GET /api/v1/me`` returns ``roles: []`` as a literal, ``is_admin`` is
never serialised, and there is no capability endpoint. So section 3 ASKS: one
call per area, and 200 vs 403 IS the answer. A client-side permission model
would be a second opinion about a decision only the server makes, which is the
failure this whole module is built to avoid. Where the server says nothing, the
UI says "not reported" rather than guessing.

WHO THIS IS ABOUT. The workstation user is always internal staff — an
administrator, a consulting physician, another authorised member of the centre.
Patients never sign in here; they write from the website and arrive over the
API.

Everything else this tab touches goes through the ONE authority that already
owns it: sign-in via ``open_signin_dialog`` (modeless, never ``exec()``), Drive
via ``IdentityService.connect("google")`` on a worker, flags via the ``save_*``
writers beside their readers, links via the internal Web Browser module. Env
vars still win at read time; a field whose value is being overridden says so
instead of silently ignoring the edit.

This module imports no Identity/consultation code at import time — every probe
is a small guarded helper, so the file is safe to import in builds that omit
those modules (sections then render as "not available in this build").
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

DEFAULT_WEBSITE_URL = "https://ai-pacs.com"

_WARN_STYLE = "color: #f59e0b; font-size: 13px;"
_MUTED_STYLE = "color: #9ca3af; font-size: 13px;"
_SUBTITLE_STYLE = "font-weight: 700; font-size: 15px; color: #e5e7eb;"
_TITLE_STYLE = "font-weight: 800; font-size: 17px; color: #f3f4f6;"

# Access states, in the owner's vocabulary. The colour carries the same meaning
# as the word — never the colour alone.
STATE_AVAILABLE = ("Available", "#34d399")
STATE_ENABLED = ("Enabled", "#34d399")
STATE_RESTRICTED = ("Restricted", "#f59e0b")
STATE_UNAUTHORIZED = ("Not authorized", "#f87171")
STATE_OFF = ("Off on this workstation", "#9ca3af")
STATE_UNKNOWN = ("Not reported", "#9ca3af")


# ── guarded probes (import-cheap; patchable in tests) ─────────────────────────
def _identity_enabled() -> bool:
    try:
        from modules.Identity.feature_flags import identity_module_enabled

        return identity_module_enabled()
    except Exception:
        return False


def _cloud_enabled() -> bool:
    try:
        from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

        return cloud_consultation_enabled()
    except Exception:
        return False


def _consultation_registry_enabled() -> bool:
    try:
        from aipacs_runtime import is_module_enabled

        return bool(is_module_enabled("consultation"))
    except Exception:
        return False


def _online_consultation_available() -> bool:
    try:
        from modules.education.online_consultation import online_consultation_available

        return online_consultation_available()
    except Exception:
        return False


def _chat_available() -> bool:
    try:
        from modules.aipacs_chat.feature_flags import aipacs_chat_available

        return aipacs_chat_available()
    except Exception:
        return False


def _education_module_enabled() -> bool:
    try:
        from aipacs_runtime import is_module_enabled

        return bool(is_module_enabled("education"))
    except Exception:
        return True  # fails open, like the other registry lookups


def _resolve_auth_user():
    """The host login dict, via the ONE shared resolver.

    This page and the chat console MUST agree about who is signed in: the
    AI-PACS identity is filed per workstation user, so two different answers
    here mean two different accounts, and a console that says "not signed in"
    while this page says "signed in" (live bug 2026-08-22). Delegating keeps
    them identical by construction.
    """
    try:
        from modules.Identity.ui.host_user import resolve_host_auth_user

        return resolve_host_auth_user()
    except Exception:
        return None


def _aipacs_user() -> str:
    try:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(_resolve_auth_user())
    except Exception:
        return "local"


# ── off-GUI-thread call infrastructure (echomind_settings idiom) ──────────────
# A QThread must outlive Python's reference to it and must never be destroyed
# while running; parking workers here does both without giving them a parent
# that could delete them mid-flight.
_LIVE_WORKERS: list = []


def _release_worker(worker) -> None:
    try:
        _LIVE_WORKERS.remove(worker)
    except ValueError:
        pass
    try:
        worker.deleteLater()
    except Exception:
        pass


class _CallWorker(QThread):
    """Runs one blocking call off the GUI thread (OAuth flows block until
    consent completes; access probes are network round-trips).

    ``finishedWith`` carries ``(ok, payload)`` — payload is the result or the
    raised exception; the GUI slot renders it, so no Qt call ever happens on
    this thread.
    """

    finishedWith = Signal(bool, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):  # pragma: no cover - exercised live, guarded structurally
        try:
            self.finishedWith.emit(True, self._fn())
        except Exception as exc:  # noqa: BLE001 - reported, never raised out
            self.finishedWith.emit(False, exc)


def _start_worker(fn, on_finished) -> None:
    worker = _CallWorker(fn)
    worker.finishedWith.connect(on_finished)
    worker.finished.connect(lambda w=worker: _release_worker(w))
    _LIVE_WORKERS.append(worker)
    worker.start()


# ── small UI helpers ──────────────────────────────────────────────────────────
def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_TITLE_STYLE)
    return label


def _subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_SUBTITLE_STYLE)
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_MUTED_STYLE)
    return label


def _warn_label() -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setStyleSheet(_WARN_STYLE)
    label.setVisible(False)
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


class _AccessRow(QWidget):
    """One service in section 3: name, state, and what the state means.

    The state word is the owner's vocabulary (Available / Enabled / Restricted
    / Not authorized / Not reported); colour repeats it, never replaces it, so
    the row still reads correctly in monochrome or to a colour-blind operator.
    """

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet(_SUBTITLE_STYLE)
        self.state_label = QLabel("")
        self.state_label.setStyleSheet(_MUTED_STYLE)
        head.addWidget(self.name_label)
        head.addStretch(1)
        head.addWidget(self.state_label)
        lay.addLayout(head)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(_MUTED_STYLE)
        lay.addWidget(self.detail)

    def set_state(self, state: tuple, detail: str = "") -> None:
        word, colour = state
        self.state_label.setText(word)
        self.state_label.setStyleSheet(
            f"color: {colour}; font-size: 13px; font-weight: 700;")
        self.detail.setText(detail)


class ConsultationEducationSettingsWidget(QWidget):
    """The Settings ▸ Consultation & Education tab (see module docstring)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ident = None       # cached aipacs_web ExternalIdentity (or None)
        self._access = None      # last probe result (dict) or None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(16)

        self._build_identity(lay)
        self._build_current_user(lay)
        self._build_access(lay)
        self._build_configuration(lay)
        lay.addStretch(1)

        scroll.setWidget(body)
        self._refresh()

    # ── 1 · Identity ──────────────────────────────────────────────────────────
    def _build_identity(self, parent_layout):
        box = QGroupBox("1 · Identity")
        lay = QVBoxLayout(box)
        lay.setSpacing(10)

        self.lbl_identity_intro = QLabel("")
        self.lbl_identity_intro.setWordWrap(True)
        lay.addWidget(self.lbl_identity_intro)

        # Two doors into the SAME account and the same endpoints — Google
        # attestation, or the email/password the user already has. Offering
        # them side by side is the point: neither is a fallback.
        self.btn_signin_google = QPushButton("Sign in with Google")
        self.btn_signin_google.setMinimumHeight(40)
        self.btn_signin_google.clicked.connect(self._sign_in_aipacs_web)
        self.btn_signin_account = QPushButton("Sign in with AI-PACS account")
        self.btn_signin_account.setMinimumHeight(40)
        self.btn_signin_account.clicked.connect(self._sign_in_with_account)
        row = QHBoxLayout()
        row.addWidget(self.btn_signin_google)
        row.addWidget(self.btn_signin_account)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_identity_hint = _note(
            "Google signs you in without a password — AI-PACS checks the "
            "verified address against your consultant profile. Use the "
            "AI-PACS account option if you sign in to the website with an "
            "email and password, or were given a pairing code.")
        lay.addWidget(self.lbl_identity_hint)

        self.btn_signout = QPushButton("Sign out of AI-PACS")
        self.btn_signout.clicked.connect(self._disconnect_aipacs)
        row = QHBoxLayout()
        row.addWidget(self.btn_signout)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_identity_server = _note("")
        lay.addWidget(self.lbl_identity_server)

        parent_layout.addWidget(box)

    # ── 2 · Current user ──────────────────────────────────────────────────────
    def _build_current_user(self, parent_layout):
        self.box_current_user = QGroupBox("2 · Current user")
        lay = QVBoxLayout(self.box_current_user)
        lay.setSpacing(10)

        self.lbl_signed_in_as = QLabel("—")
        self.lbl_signed_in_as.setStyleSheet(_TITLE_STYLE)
        lay.addWidget(self.lbl_signed_in_as)

        form = QFormLayout()
        self.lbl_user_name = QLabel("—")
        self.lbl_user_email = QLabel("—")
        self.lbl_user_account = QLabel("—")
        self.lbl_user_role = QLabel("—")
        self.lbl_user_status = QLabel("—")
        for label in (self.lbl_user_name, self.lbl_user_email,
                      self.lbl_user_account, self.lbl_user_role,
                      self.lbl_user_status):
            label.setWordWrap(True)
        form.addRow("Name:", self.lbl_user_name)
        form.addRow("Email:", self.lbl_user_email)
        form.addRow("AI-PACS account:", self.lbl_user_account)
        form.addRow("Role:", self.lbl_user_role)
        form.addRow("Login status:", self.lbl_user_status)
        lay.addLayout(form)

        lay.addWidget(_divider())

        # The workstation user is a different fact from the AI-PACS account,
        # and both matter: the AI-PACS identity is stored PER workstation user,
        # so signing a different person in here changes whose consultations and
        # chats this workstation acts on.
        lay.addWidget(_subtitle("Workstation user"))
        self.lbl_workstation_user = QLabel("—")
        self.lbl_workstation_user.setWordWrap(True)
        lay.addWidget(self.lbl_workstation_user)

        parent_layout.addWidget(self.box_current_user)

    # ── 3 · Access & permissions ──────────────────────────────────────────────
    def _build_access(self, parent_layout):
        self.box_access = QGroupBox("3 · Access & permissions")
        lay = QVBoxLayout(self.box_access)
        lay.setSpacing(8)

        lay.addWidget(_note(
            "What this AI-PACS account may do. AI-PACS does not publish a "
            "role to connected workstations, so nothing here is guessed — "
            "each area is asked directly and its own answer is shown."))

        self.row_consultation = _AccessRow("Consultation")
        self.row_education = _AccessRow("Education")
        self.row_chat = _AccessRow("AI-PACS Chat")
        self.row_other = _AccessRow("Other AI-PACS services")
        for row in (self.row_consultation, self.row_education,
                    self.row_chat, self.row_other):
            lay.addWidget(row)

        self.btn_check_access = QPushButton("Check access")
        self.btn_check_access.clicked.connect(self._check_access)
        row = QHBoxLayout()
        row.addWidget(self.btn_check_access)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_access_note = _note("")
        lay.addWidget(self.lbl_access_note)

        parent_layout.addWidget(self.box_access)

    # ── Configuration (collapsed) ─────────────────────────────────────────────
    def _build_configuration(self, parent_layout):
        """Everything that is a setting rather than an identity.

        A checkable QGroupBox that starts CLOSED: these fields are needed
        occasionally and are meaningless before sign-in, which is exactly the
        clutter the owner asked to get out of the way.
        """
        box = QGroupBox("Configuration")
        box.setCheckable(True)
        box.setChecked(False)
        outer = QVBoxLayout(box)
        content = QWidget()
        content.setVisible(False)
        box.toggled.connect(content.setVisible)
        outer.addWidget(content)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)

        # — server + portal —
        lay.addWidget(_subtitle("AI-PACS server"))
        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("https://ai-pacs.com/consult-form")
        self.chk_web_enabled = QCheckBox("Enable the AI-PACS website connection")
        form = QFormLayout()
        form.addRow("Server address:", self.edit_base_url)
        lay.addLayout(form)
        lay.addWidget(self.chk_web_enabled)
        self.lbl_web_env = _warn_label()
        lay.addWidget(self.lbl_web_env)
        self.btn_save_web = QPushButton("Save server settings")
        self.btn_save_web.clicked.connect(self._save_web_config)
        row = QHBoxLayout()
        row.addWidget(self.btn_save_web)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_portal_url = _note("")
        lay.addWidget(self.lbl_portal_url)
        self.btn_open_portal = QPushButton("Portal…")
        self.btn_open_portal.clicked.connect(lambda: self._open_portal(""))
        self.btn_open_library = QPushButton("Education library…")
        self.btn_open_library.clicked.connect(lambda: self._open_portal("/library"))
        self.btn_open_profile = QPushButton("My consultant profile…")
        self.btn_open_profile.clicked.connect(lambda: self._open_portal("/profile"))
        self.btn_open_website = QPushButton("AI-PACS website…")
        self.btn_open_website.clicked.connect(self._open_website)
        row = QHBoxLayout()
        for button in (self.btn_open_portal, self.btn_open_library,
                       self.btn_open_profile, self.btn_open_website):
            row.addWidget(button)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_divider())

        # — this workstation's place in the centre —
        lay.addWidget(_subtitle("This workstation"))
        self.lbl_local_user = QLabel("—")
        self.edit_consult_addr = QLineEdit()
        self.edit_consult_addr.setPlaceholderText(
            "physician@center.com — routing address for this workstation")
        self.edit_center_id = QLineEdit()
        self.edit_center_id.setPlaceholderText(
            "optional imaging-center id reported on new consultations")
        self.chk_hub_mode = QCheckBox(
            "Hub mode — consultations share one hub Google Drive account")
        form = QFormLayout()
        form.addRow("Workstation login:", self.lbl_local_user)
        form.addRow("Consultation address:", self.edit_consult_addr)
        form.addRow("Center ID:", self.edit_center_id)
        lay.addLayout(form)
        lay.addWidget(self.chk_hub_mode)
        self.lbl_physician_identity = _note("")
        lay.addWidget(self.lbl_physician_identity)
        self.lbl_center_env = _warn_label()
        lay.addWidget(self.lbl_center_env)
        self.btn_save_center = QPushButton("Save workstation settings")
        self.btn_save_center.clicked.connect(self._save_center_identity)
        row = QHBoxLayout()
        row.addWidget(self.btn_save_center)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_divider())

        # — modules on/off —
        lay.addWidget(_subtitle("Modules on this workstation"))
        self.chk_identity_enabled = QCheckBox(
            "Identity (external accounts and sign-in)")
        self.chk_cloud_enabled = QCheckBox("Cloud consultation")
        self.chk_chat_enabled = QCheckBox("AiPacs Chat console")
        for widget in (self.chk_identity_enabled, self.chk_cloud_enabled,
                       self.chk_chat_enabled):
            lay.addWidget(widget)
        self.lbl_gate_env = _warn_label()
        lay.addWidget(self.lbl_gate_env)
        self.lbl_chat_env = _warn_label()
        lay.addWidget(self.lbl_chat_env)
        self.lbl_gate_verdict = _note("")
        lay.addWidget(self.lbl_gate_verdict)
        self.lbl_chat_identity = _note("")
        lay.addWidget(self.lbl_chat_identity)
        lay.addWidget(_note(
            "Some changes take effect after restarting the workstation."))
        self.btn_save_gates = QPushButton("Save module settings")
        self.btn_save_gates.clicked.connect(self._save_gate_flags)
        self.btn_chat_test = QPushButton("Test chat connection")
        self.btn_chat_test.clicked.connect(self._test_chat_connection)
        row = QHBoxLayout()
        row.addWidget(self.btn_save_gates)
        row.addWidget(self.btn_chat_test)
        row.addStretch(1)
        lay.addLayout(row)
        self.lbl_chat_test = _note("")
        lay.addWidget(self.lbl_chat_test)

        lay.addWidget(_divider())

        # — staff panel in the browser —
        lay.addWidget(_subtitle("Staff panel (opens in the AI-PACS browser)"))
        lay.addWidget(_note(
            "The same pages on the website, for when a manager wants them "
            "beside the workstation console. All of them need a staff "
            "account; anyone else is refused by the server."))
        self.btn_open_web_console = QPushButton("Chat console…")
        self.btn_open_web_console.clicked.connect(self._open_web_chat_console)
        self.btn_open_visitors = QPushButton("Live visitors…")
        self.btn_open_visitors.clicked.connect(
            lambda: self._open_staff_panel("/visitors", "Live visitors"))
        self.btn_open_drive_panel = QPushButton("Drive filing…")
        self.btn_open_drive_panel.clicked.connect(
            lambda: self._open_staff_panel("/drive", "Drive filing"))
        self.btn_open_greetings = QPushButton("Greeting rules…")
        self.btn_open_greetings.clicked.connect(
            lambda: self._open_staff_panel("/greetings", "Greeting rules"))
        row = QHBoxLayout()
        for button in (self.btn_open_web_console, self.btn_open_visitors,
                       self.btn_open_drive_panel, self.btn_open_greetings):
            row.addWidget(button)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_divider())

        # — Google Drive —
        lay.addWidget(_subtitle("Google Drive"))
        self.lbl_drive_account = QLabel("—")
        self.lbl_drive_account.setWordWrap(True)
        lay.addWidget(self.lbl_drive_account)
        self.btn_drive_connect = QPushButton("Connect Google Drive…")
        self.btn_drive_connect.clicked.connect(self._connect_drive)
        self.btn_drive_disconnect = QPushButton("Disconnect Drive")
        self.btn_drive_disconnect.clicked.connect(self._disconnect_drive)
        row = QHBoxLayout()
        row.addWidget(self.btn_drive_connect)
        row.addWidget(self.btn_drive_disconnect)
        row.addStretch(1)
        lay.addLayout(row)
        self.lbl_drive_auth = QLabel("—")
        self.lbl_drive_auth.setWordWrap(True)
        self.lbl_drive_auth.setStyleSheet(_MUTED_STYLE)
        lay.addWidget(self.lbl_drive_auth)
        self.lbl_drive_access = QLabel("—")
        self.lbl_drive_access.setWordWrap(True)
        self.lbl_drive_access.setStyleSheet(_MUTED_STYLE)
        lay.addWidget(self.lbl_drive_access)

        parent_layout.addWidget(box)

    # ── refresh (cheap: config files + local identity DB; NO network) ─────────
    def _refresh(self):
        self._ident = self._aipacs_identity()
        self._refresh_identity()
        self._refresh_current_user()
        self._refresh_access()
        self._refresh_configuration()

    def _aipacs_identity(self):
        try:
            from modules.Identity.providers.aipacs_web import find_aipacs_web_identity

            return find_aipacs_web_identity(_aipacs_user())
        except Exception:
            return None

    def _google_identity(self):
        try:
            from modules.Identity.identity_service import IdentityService

            for ident in IdentityService(_aipacs_user()).list_identities():
                if ident.provider == "google":
                    return ident
        except Exception:
            pass
        return None

    def _link(self) -> dict:
        ident = self._ident
        return ((ident.extra or {}).get("link") or {}) if ident is not None else {}

    def _refresh_identity(self):
        signed_in = self._ident is not None
        base = self._web_base_url()
        if signed_in:
            self.lbl_identity_intro.setText(
                "You are signed in to AI-PACS. Sign in again only to switch "
                "to a different account.")
            self.btn_signin_google.setText("Switch Google account")
            self.btn_signin_account.setText("Switch AI-PACS account")
        else:
            self.lbl_identity_intro.setText(
                "Sign in to AI-PACS to use Consultation, Education and Chat "
                "on ai-pacs.com. Choose the way you normally sign in to the "
                "website — both lead to the same account.")
            self.btn_signin_google.setText("Sign in with Google")
            self.btn_signin_account.setText("Sign in with AI-PACS account")
        self.btn_signout.setVisible(signed_in)
        self.lbl_identity_hint.setVisible(not signed_in)
        self.lbl_identity_server.setText(
            f"Server: {base or 'not configured — set it under Configuration'}")
        for button in (self.btn_signin_google, self.btn_signin_account):
            button.setEnabled(bool(base))

    def _refresh_current_user(self):
        signed_in = self._ident is not None
        self.box_current_user.setVisible(signed_in)

        auth = _resolve_auth_user() or {}
        login = str(auth.get("username") or auth.get("full_name") or "local")
        local_name = str(auth.get("full_name") or auth.get("username") or "—")
        # `role` is the label the PACS login supplies. The workstation has no
        # permission model of its own — it gates nothing on this value — so it
        # is shown as identification, not as authority.
        local_role = str(auth.get("role") or "").strip()
        self.lbl_workstation_user.setText(
            f"{local_name}   ·   sign-in: {login}"
            + (f"   ·   {local_role}" if local_role else "")
            + "\nThe AI-PACS account above is remembered for this workstation "
            "user, so signing a different person in to the workstation "
            "switches which AI-PACS account it acts as. Patients never sign "
            "in here.")
        self.lbl_local_user.setText(f"{login}  (identity link key: {_aipacs_user()})")

        if not signed_in:
            self.lbl_signed_in_as.setText("Not signed in")
            for label in (self.lbl_user_name, self.lbl_user_email,
                          self.lbl_user_account, self.lbl_user_role):
                label.setText("—")
            self.lbl_user_status.setText("Signed out")
            return

        ident = self._ident
        link = self._link()
        name = str(link.get("profile_name") or ident.display_name
                   or ident.handle or "—")
        email = str(link.get("gmail_email") or ident.handle or "—")
        self.lbl_signed_in_as.setText(f"Signed in as {name}")
        self.lbl_user_name.setText(name)
        self.lbl_user_email.setText(email)
        self.lbl_user_account.setText(
            f"{ident.handle or '—'}   ·   {self._web_base_url() or '—'}")
        # Role: only what the server actually said. It publishes none today,
        # so this reads honestly rather than inventing "Physician".
        access = self._access if isinstance(self._access, dict) else {}
        profile = access.get("profile") if isinstance(access, dict) else None
        # AI-PACS publishes the role on /me and /me/entitlements. SHOW it —
        # and never gate on it. `role: null` is normal and not a fault; what
        # the account may do is the `modules` answer in section 3.
        role = str(access.get("role") or "").strip()
        role_bits: list[str] = []
        if role:
            role_bits.append(role.replace("_", " "))
        if access.get("is_super_admin"):
            role_bits.append("super admin")
        if isinstance(profile, dict) and profile.get("configured"):
            role_bits.extend(str(b) for b in (profile.get("type"),
                                              profile.get("availability")) if b)
        if role_bits:
            self.lbl_user_role.setText(" · ".join(role_bits))
        elif access:
            self.lbl_user_role.setText(
                "no role set on AI-PACS — common, and not a fault. What this "
                "account may do is shown under Access below.")
        else:
            self.lbl_user_role.setText(
                "not read yet — press Check access below")
        # Account status. "Not signed in" and "token rejected" need different
        # buttons and different words: one has never signed in, the other had
        # their access changed by an administrator (tokens do not expire, so a
        # 401 is almost always a revoke or a re-pair, not a timeout).
        device = str(access.get("device_name") or "")
        if not device:
            try:
                from modules.Identity.providers.aipacs_web import default_device_name

                device = default_device_name()
            except Exception:
                device = ""
        seen = str(access.get("last_seen_at") or "")
        if access.get("account") == "expired":
            self.lbl_user_status.setText(
                "Signed in on this workstation, but AI-PACS rejected the "
                "session — your access was changed. Sign in again.")
        else:
            parts = ["Signed in ✓"]
            if device:
                parts.append(f"this workstation: {device}")
            if seen:
                parts.append(f"last seen by AI-PACS: {seen}")
            self.lbl_user_status.setText("   ·   ".join(parts))

    def _refresh_access(self):
        signed_in = self._ident is not None
        self.box_access.setVisible(signed_in)
        if not signed_in:
            return
        if self._access is None:
            for row, name in ((self.row_consultation, "Consultation"),
                              (self.row_education, "Education"),
                              (self.row_chat, "AI-PACS Chat"),
                              (self.row_other, "Other AI-PACS services")):
                row.set_state(STATE_UNKNOWN, "Press Check access to ask AI-PACS.")
            self.lbl_access_note.setText("")
            return
        self._render_access(self._access)

    def _render_access(self, data: dict) -> None:
        """Turn one probe result into the four service rows.

        Every line here is either something the server said or something this
        workstation knows about itself (a module switch). Nothing is inferred
        from a role, because there is no role to infer from.
        """
        profile = data.get("profile")
        has_profile = isinstance(profile, dict) and profile.get("configured")
        accepts = profile.get("accepts") if isinstance(profile, dict) else None
        ent = data.get("entitlements") if isinstance(data, dict) else None

        def server_says(module: str, probe_key: str) -> str:
            """The server's answer for one module.

            Entitlements win when the server publishes them; an UNKNOWN module
            key there counts as denied, per the contract. Otherwise the probe's
            status code is the answer.
            """
            if isinstance(ent, dict):
                return "allowed" if bool(ent.get(module)) else "denied"
            return str(data.get(probe_key) or "unknown")

        # — Consultation —
        consult_answer = server_says("consultation", "consultation")
        if not _online_consultation_available():
            self.row_consultation.set_state(
                STATE_OFF,
                "The consultation module is not enabled on this workstation "
                "(see Configuration).")
        elif consult_answer == "denied":
            self.row_consultation.set_state(
                STATE_UNAUTHORIZED,
                "AI-PACS does not include Consultation for this account. Ask "
                "your AI-PACS administrator.")
        elif consult_answer == "unknown":
            self.row_consultation.set_state(
                STATE_UNKNOWN,
                "Could not reach AI-PACS — showing your last known access.")
        elif has_profile:
            bits = ["Provide consultations to colleagues",
                    "Respond to consultations sent to you"]
            if accepts is False:
                self.row_consultation.set_state(
                    STATE_RESTRICTED,
                    "Your consultant profile is set to NOT accept "
                    "consultations, so colleagues cannot send you new ones. "
                    "An AI-PACS administrator changes that.")
            else:
                addr = data.get("routing_address") or "—"
                self.row_consultation.set_state(
                    STATE_AVAILABLE,
                    " · ".join(bits) + f"\nRequests reach you at: {addr}")
        else:
            self.row_consultation.set_state(
                STATE_UNAUTHORIZED,
                "No consultant profile on AI-PACS. Until an administrator "
                "creates one for your address, consultations cannot be routed "
                "to you.")

        # — Education —
        account_ok = data.get("account") == "ok"
        edu_answer = server_says("education", "education")
        if not _education_module_enabled():
            self.row_education.set_state(
                STATE_OFF, "The education module is not enabled on this "
                           "workstation.")
        elif edu_answer == "allowed":
            self.row_education.set_state(
                STATE_AVAILABLE,
                "View shared courses and teaching material · Share your own "
                "cases (each item's own owner rule still applies)\nBuilding "
                "courses happens on this workstation and needs no permission; "
                "publishing to AI-PACS has no endpoint yet.")
        elif edu_answer == "denied":
            self.row_education.set_state(
                STATE_UNAUTHORIZED,
                "AI-PACS does not include Education for this account. Your "
                "local course library still works.")
        else:
            self.row_education.set_state(
                STATE_UNKNOWN,
                "Could not reach AI-PACS — showing your last known access. "
                "Your local course library still works.")

        # — Chat —
        # Entitlements answer this directly when the server publishes them;
        # otherwise the /chat probe is itself a real answer, because that
        # route really is gated (EnsureChatOperator).
        chat = data.get("chat")
        if isinstance(ent, dict):
            chat = "granted" if bool(ent.get("chat")) else "denied"
        if not _chat_available():
            self.row_chat.set_state(
                STATE_OFF,
                "The chat console is not enabled on this workstation (see "
                "Configuration).")
        elif chat == "granted":
            self.row_chat.set_state(
                STATE_AVAILABLE,
                "Open the console · Answer patients · Send prices and status "
                "changes\nAI-PACS admits this account as staff. Manager and "
                "administrator powers on the website itself are not reported "
                "to workstations.")
        elif chat == "denied":
            self.row_chat.set_state(
                STATE_UNAUTHORIZED,
                "AI-PACS refused this account for the patient inbox. It "
                "admits administrators and the accounts on its console-"
                "operator list — ask an AI-PACS administrator to add you.")
        elif chat == "auth":
            self.row_chat.set_state(
                STATE_RESTRICTED, "The session expired — sign in again.")
        elif chat == "not_configured":
            self.row_chat.set_state(
                STATE_OFF, "Not configured on this workstation.")
        else:
            self.row_chat.set_state(
                STATE_UNKNOWN, f"Could not tell ({chat}).")

        # — Other services —
        drive = "connected" if self._google_identity() is not None else "not connected"
        extras = [f"Google Drive storage for consultations: {drive}"]
        if isinstance(ent, dict):
            # Sub-capabilities the server names separately. Rendered here
            # rather than as their own rows because each one belongs to a
            # parent module: answering a consultation is Consultation,
            # managing chat is Chat.
            def word(key: str) -> str:
                return "yes" if bool(ent.get(key)) else "no"

            extras.append(
                f"Answer consultations: {word('consultation_response')}   ·   "
                f"Create/publish courses: {word('course_creation')}   ·   "
                f"Chat management: {word('chat_manager')}")
        self.row_other.set_state(
            STATE_AVAILABLE if account_ok else STATE_UNKNOWN,
            "\n".join(extras))

        # The grant model, for the administrator standing at the machine. It
        # says what AI-PACS INTENDS; `modules` says what works today, and the
        # two can differ while the API is looser than the website.
        panels = data.get("panels")
        source = ("AI-PACS answered directly (entitlements)"
                  if isinstance(ent, dict) else
                  "asked each area (this server has no entitlements endpoint)")
        note = ("Checked just now — " + source + ". Access is decided by "
                "AI-PACS for this account; changing it means changing the "
                "account's permissions on the website, not a setting here.")
        if isinstance(panels, dict) and panels:
            granted = ", ".join(
                f"{name}: {level or 'none'}" for name, level in sorted(panels.items()))
            note += f"\nAI-PACS panel grants — {granted}"
        self.lbl_access_note.setText(note)

    def _refresh_configuration(self):
        # server + portal
        try:
            from modules.Identity.providers.aipacs_web import (
                aipacs_web_env_override,
                load_aipacs_web_config,
                portal_url,
            )

            cfg = load_aipacs_web_config()
            self.edit_base_url.setText(cfg.get("base_url") or "")
            self.chk_web_enabled.setChecked(bool(cfg.get("enabled")))
            env = aipacs_web_env_override()
            if env:
                self.lbl_web_env.setText(
                    f"Environment override active: {env} — the fields above "
                    "are ignored until it is unset.")
                self.lbl_web_env.setVisible(True)
                self.edit_base_url.setEnabled(False)
                self.chk_web_enabled.setEnabled(False)
            else:
                self.lbl_web_env.setVisible(False)
                self.edit_base_url.setEnabled(True)
                self.chk_web_enabled.setEnabled(True)
            portal = portal_url()
        except Exception:
            for widget in (self.edit_base_url, self.chk_web_enabled,
                           self.btn_save_web):
                widget.setEnabled(False)
            self.lbl_web_env.setText(
                "The Identity module is not available in this build.")
            self.lbl_web_env.setVisible(True)
            portal = ""
        self.lbl_portal_url.setText(
            "Consultation & Education portal: "
            f"{portal or 'not configured'} — a separate address from the "
            "server above, where the library and your profile live.")
        for button in (self.btn_open_portal, self.btn_open_library,
                       self.btn_open_profile):
            button.setEnabled(bool(portal))

        self._refresh_center_settings()
        self._refresh_module_flags()
        self._refresh_drive()

    def _refresh_center_settings(self):
        try:
            from modules.cloud_consultation import feature_flags as ccf

            values = ccf.flag_values()
            self.edit_consult_addr.setText(str(values.get("consultation_address") or ""))
            self.edit_center_id.setText(str(values.get("center_id") or ""))
            self.chk_hub_mode.setChecked(bool(values.get("hub_mode")))
            overrides = ccf.env_overrides()
            env_names = [env for key, env in overrides.items()
                         if key in ("hub_mode", "consultation_address", "center_id")]
            if env_names:
                self.lbl_center_env.setText(
                    "Environment override active: " + ", ".join(env_names)
                    + " — the matching field(s) above are ignored until it is "
                      "unset.")
                self.lbl_center_env.setVisible(True)
            else:
                self.lbl_center_env.setVisible(False)
            user = _aipacs_user()
            effective = ccf.consultation_address(aipacs_user=user)
            if "consultation_address" in overrides:
                source = "environment variable"
            elif str(values.get("consultation_address") or "").strip():
                source = "the field above"
            elif ccf.linked_consultation_address(user):
                source = "the signed-in AI-PACS account"
            else:
                source = "not set"
            self.lbl_physician_identity.setText(
                f"Consultations reach this physician at: {effective or '—'}  "
                f"(from {source})")
        except Exception:
            for widget in (self.edit_consult_addr, self.edit_center_id,
                           self.chk_hub_mode, self.btn_save_center):
                widget.setEnabled(False)
            self.lbl_center_env.setText(
                "The cloud consultation module is not available in this build.")
            self.lbl_center_env.setVisible(True)

    def _refresh_module_flags(self):
        identity_on = _identity_enabled()
        cloud_on = _cloud_enabled()
        registry_on = _consultation_registry_enabled()
        self.chk_identity_enabled.setChecked(identity_on)
        self.chk_cloud_enabled.setChecked(cloud_on)

        env_bits = []
        try:
            from modules.Identity.feature_flags import identity_env_override

            if identity_env_override():
                env_bits.append(identity_env_override())
        except Exception:
            pass
        try:
            from modules.cloud_consultation.feature_flags import env_overrides

            if "enabled" in env_overrides():
                env_bits.append(env_overrides()["enabled"])
        except Exception:
            pass
        if env_bits:
            self.lbl_gate_env.setText(
                "Environment override active: " + ", ".join(env_bits)
                + " — the matching box(es) above are ignored until it is unset.")
            self.lbl_gate_env.setVisible(True)
        else:
            self.lbl_gate_env.setVisible(False)

        def mark(flag: bool) -> str:
            return "✓" if flag else "✗"

        registry_note = "" if registry_on else " (not installed/enabled)"
        verdict = "AVAILABLE ✓" if _online_consultation_available() else "unavailable"
        self.lbl_gate_verdict.setText(
            f"Identity {mark(identity_on)}   ·   Cloud consultation "
            f"{mark(cloud_on)}   ·   Consultation module "
            f"{mark(registry_on)}{registry_note}   →   Online consultation: "
            f"{verdict}")

        # chat flag
        try:
            from modules.aipacs_chat.feature_flags import (
                aipacs_chat_available,
                aipacs_chat_enabled,
                aipacs_chat_env_override,
                backend_configured,
            )
        except Exception:
            self.chk_chat_enabled.setEnabled(False)
            self.btn_chat_test.setEnabled(False)
            self.lbl_chat_identity.setText(
                "The AiPacs Chat module is not available in this build.")
            self.lbl_chat_env.setVisible(False)
            return
        self.chk_chat_enabled.setChecked(aipacs_chat_enabled())
        env = aipacs_chat_env_override()
        if env:
            self.lbl_chat_env.setText(
                f"Environment override active: {env} — the chat box above is "
                "ignored until it is unset.")
            self.lbl_chat_env.setVisible(True)
        else:
            self.lbl_chat_env.setVisible(False)
        server_ok = backend_configured()
        signed_in = self._ident is not None
        chat_verdict = ("console AVAILABLE ✓" if aipacs_chat_available()
                        else "console unavailable")
        self.lbl_chat_identity.setText(
            f"Chat: server {mark(server_ok)}   ·   signed in {mark(signed_in)}"
            f"   ·   identity {mark(_identity_enabled())}   ·   enabled "
            f"{mark(aipacs_chat_enabled())}   →   {chat_verdict}")
        self.btn_chat_test.setEnabled(server_ok and signed_in)

    def _refresh_drive(self):
        google_ident = self._google_identity()
        if google_ident is not None:
            self.lbl_drive_account.setText(
                f"Connected — {google_ident.handle}\n"
                "This account stores consultation studies and shared files.")
            self.btn_drive_connect.setText("Reconnect Google Drive…")
            self.btn_drive_disconnect.setEnabled(True)
        else:
            self.lbl_drive_account.setText(
                "Not connected. Hub storage is usually configured by AI-PACS "
                "during installation/activation.")
            self.btn_drive_connect.setText("Connect Google Drive…")
            self.btn_drive_disconnect.setEnabled(False)

        client_ok = False
        try:
            from modules.Identity.config import google_client_configured

            client_ok = google_client_configured()
        except Exception:
            pass
        client_line = ("OAuth client: configured ✓" if client_ok else
                       "OAuth client: missing — config/identity/google_oauth.json")
        self.lbl_drive_auth.setText(
            f"{client_line}\n"
            "Requested permissions: profile, email, drive.file — the "
            "workstation can only see files it created itself, never the "
            "whole Drive.")
        token_line = ("Token: stored securely in Windows Credential Manager"
                      if google_ident is not None else "Token: none stored")
        self.lbl_drive_access.setText(
            "AI-PACS Drive folder: “AI-PACS Consultations” (created on first "
            f"use)\n{token_line}\n"
            "Studies upload directly from this workstation to Google Drive — "
            "they never pass through the AI-PACS server.")

    # ── actions: sign in / out ────────────────────────────────────────────────
    def _sign_in_aipacs_web(self, expand_account: bool = False):
        """Open the ONE modeless sign-in dialog — never a modal, never the
        Drive hub connect (pinned by tests/code/identity/
        test_connect_button_routing.py)."""
        try:
            from modules.Identity.identity_service import IdentityService
            from modules.Identity.ui.aipacs_web_dialog import open_signin_dialog
        except Exception:
            QMessageBox.warning(
                self, "AI-PACS",
                "The Identity module is not available in this build.")
            return
        service = IdentityService(_aipacs_user())
        open_signin_dialog(service, parent=self, on_success=self._after_signin,
                           expand_account=bool(expand_account))

    def _sign_in_with_account(self):
        """Same dialog, opened on the email + password / pairing-code half."""
        self._sign_in_aipacs_web(expand_account=True)

    def _after_signin(self, _identity):
        self._access = None  # the new account's access is not yet known
        self._refresh()
        # Let the title-bar account pill / badge pick up the new identity too.
        try:
            from modules.cloud_consultation.ui.account_hook import (
                refresh_account_area_after_connect,
            )

            refresh_account_area_after_connect(_resolve_auth_user())
        except Exception:
            logger.debug("account area refresh unavailable", exc_info=True)
        # Knowing WHO is signed in is only half the answer the page owes the
        # user; go and get the other half without making them ask.
        self._check_access()

    def _disconnect_aipacs(self):
        ident = self._ident
        if ident is None:
            return
        answer = QMessageBox.question(
            self, "Sign out of AI-PACS",
            f"Sign out of the AI-PACS account for {ident.handle}?\n\n"
            "Consultation, chat and shared education features will require "
            "signing in again.")
        if answer != QMessageBox.Yes:
            return
        try:
            from modules.Identity.identity_service import IdentityService

            IdentityService(_aipacs_user()).disconnect("aipacs_web", ident.subject_id)
        except Exception as exc:
            QMessageBox.warning(self, "Sign out", f"Could not sign out:\n{exc}")
        self._access = None
        self._refresh()

    # ── actions: access check ─────────────────────────────────────────────────
    def _check_access(self):
        """Ask AI-PACS what this account may actually do — never guess it.

        WHY A PROBE AND NOT A ROLE FIELD. The server does not publish roles to
        API clients: ``GET /api/v1/me`` returns ``roles: []`` as a literal, and
        ``is_admin`` is never serialised. The chat API has no capability
        endpoint either. So the only honest way for a workstation to report
        access is to call one endpoint per area and read the answer — 200 means
        admitted, 403 means the server refused this account for that area.
        """
        if self._ident is None:
            return
        user = _aipacs_user()

        def _do():
            from modules.aipacs_chat.services.chat_client import (
                ChatAuthError,
                ChatClient,
                ChatNotConfiguredError,
                ChatTransportError,
            )
            from modules.Identity.providers.aipacs_web import (
                AipacsWebError,
                get_aipacs_web_client,
            )

            result: dict = {}
            client = get_aipacs_web_client(user)
            if client is None:
                return {"signed_in": False}
            result["signed_in"] = True

            # /me is both the identity read and the heartbeat: calling it
            # touches `last_seen_at`, which is how an administrator sees that
            # this workstation is alive. 401 here means the token is gone.
            try:
                me = client.request_json("GET", "/me") or {}
                result["account"] = "ok"
                pairing = me.get("pairing") or {}
                result["device_name"] = pairing.get("device_name") or ""
                result["last_seen_at"] = pairing.get("last_seen_at") or ""
                me_user = me.get("user") or {}
                result["role"] = str(me_user.get("role") or "")
                result["is_super_admin"] = bool(me_user.get("is_super_admin"))
            except AipacsWebError as exc:
                code = getattr(exc, "status_code", None)
                result["account"] = "expired" if code == 401 else f"error:{code}"

            # The entitlements endpoint is the answer this probing exists to
            # replace. Ask for it FIRST and use it when present; a 404 means
            # this server has not grown it yet, which is the normal case today
            # and must fall through to the probes rather than fail.
            try:
                ent = client.request_json("GET", "/me/entitlements") or {}
                modules = ent.get("modules")
                if isinstance(modules, dict):
                    result["entitlements"] = modules
                    ent_user = ent.get("user") or {}
                    if ent_user.get("role"):
                        result["role"] = str(ent_user["role"])
                    if "is_super_admin" in ent_user:
                        result["is_super_admin"] = bool(ent_user["is_super_admin"])
                    panels = ent.get("panels")
                    if isinstance(panels, dict):
                        result["panels"] = panels
            except AipacsWebError:
                pass  # 404 (older server) or anything else → probe instead

            # Module probes, exactly as the integration contract specifies.
            # 200 = allowed, 403 = denied, 401 = dead token, anything else =
            # UNKNOWN, which must never be rendered as a denial.
            def _probe(path: str) -> str:
                try:
                    client.request_json("GET", path)
                    return "allowed"
                except AipacsWebError as exc:
                    code = getattr(exc, "status_code", None)
                    if code == 403:
                        return "denied"
                    if code == 401:
                        return "expired"
                    return "unknown"

            result["consultation"] = _probe("/consultants")
            result["education"] = _probe("/education/shared")
            try:
                data = client.request_json("GET", "/me/profile")
                profile = (data or {}).get("profile") or {}
                result["profile"] = {
                    "configured": bool((data or {}).get("configured")),
                    "name": profile.get("name") or "",
                    "type": profile.get("type") or "",
                    "availability": profile.get("availability") or "",
                    "accepts": profile.get("accepts_consultations"),
                }
            except AipacsWebError:
                result["profile"] = None
            # Chat console: staff only. 403 here is the answer, not a failure.
            try:
                ChatClient.for_user(user).statuses()
                result["chat"] = "granted"
            except ChatNotConfiguredError:
                result["chat"] = "not_configured"
            except ChatAuthError:
                result["chat"] = "auth"
            except ChatTransportError as exc:
                code = getattr(exc, "status_code", None)
                result["chat"] = "denied" if code == 403 else f"error:{code}"
            try:
                from modules.cloud_consultation import feature_flags as ccf

                result["routing_address"] = ccf.consultation_address(aipacs_user=user)
            except Exception:
                result["routing_address"] = ""
            return result

        self.btn_check_access.setEnabled(False)
        self.lbl_access_note.setText("Asking AI-PACS…")
        _start_worker(_do, self._on_access_checked)

    def _on_access_checked(self, ok, payload):
        self.btn_check_access.setEnabled(True)
        if not ok:
            self.lbl_access_note.setText(f"Could not check access:\n{payload}")
            return
        data = payload if isinstance(payload, dict) else {}
        if not data.get("signed_in"):
            self._access = None
            self.lbl_access_note.setText(
                "Not signed in to AI-PACS — sign in above, then check again.")
            return
        self._access = data
        self._render_access(data)
        # The role line in section 2 comes from the same answer.
        self._refresh_current_user()

    # ── actions: hub Google Drive ─────────────────────────────────────────────
    def _connect_drive(self):
        """Hub Drive storage connect — full Drive OAuth via the google
        provider, off the GUI thread (the flow blocks until consent
        completes)."""
        try:
            from modules.Identity.identity_service import IdentityService
        except Exception:
            QMessageBox.warning(
                self, "Google Drive",
                "The Identity module is not available in this build.")
            return
        service = IdentityService(_aipacs_user())
        self.btn_drive_connect.setEnabled(False)
        self.btn_drive_connect.setText("Waiting for Google consent…")
        _start_worker(lambda: service.connect("google"), self._on_drive_connect_done)

    def _on_drive_connect_done(self, ok, payload):
        self.btn_drive_connect.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "Google Drive",
                                f"Drive connection failed:\n{payload}")
        self._refresh()

    def _disconnect_drive(self):
        ident = self._google_identity()
        if ident is None:
            return
        answer = QMessageBox.question(
            self, "Disconnect Google Drive",
            f"Disconnect the Google Drive account {ident.handle}?\n\n"
            "Consultations using hub storage will stop syncing on this "
            "workstation until it is reconnected.")
        if answer != QMessageBox.Yes:
            return
        subject_id = ident.subject_id
        user = _aipacs_user()

        def _do():
            from modules.Identity.identity_service import IdentityService

            IdentityService(user).disconnect("google", subject_id)

        self.btn_drive_disconnect.setEnabled(False)
        _start_worker(_do, self._on_drive_disconnect_done)

    def _on_drive_disconnect_done(self, ok, payload):
        if not ok:
            QMessageBox.warning(self, "Google Drive",
                                f"Disconnect failed:\n{payload}")
        self._refresh()

    # ── actions: chat connection test ─────────────────────────────────────────
    def _test_chat_connection(self):
        """Probe the chat API on ai-pacs.com — READ-ONLY and off-thread.

        Uses ``ChatClient.statuses()`` (a plain GET) and deliberately NOT
        ``/chat/sync``: the sync endpoint WRITES server state (clears unread,
        cancels the staff notification email), so it must never double as a
        connectivity probe.
        """
        user = _aipacs_user()

        def _do():
            from modules.aipacs_chat.services.chat_client import ChatClient

            return ChatClient.for_user(user).statuses()

        self.btn_chat_test.setEnabled(False)
        self.lbl_chat_test.setText("Testing connection…")
        _start_worker(_do, self._on_chat_test_done)

    def _on_chat_test_done(self, ok, payload):
        self.btn_chat_test.setEnabled(True)
        if ok:
            count = len(payload) if isinstance(payload, list) else 0
            self.lbl_chat_test.setText(
                f"Connected ✓ — the chat API answered ({count} case statuses).")
            return
        text = f"Test failed:\n{payload}"
        try:
            from modules.aipacs_chat.services.chat_client import (
                ChatApiMissingError,
                ChatAuthError,
                ChatNotConfiguredError,
            )

            if isinstance(payload, ChatNotConfiguredError):
                text = "Not configured — sign in to AI-PACS, then test again."
            elif isinstance(payload, ChatAuthError):
                text = ("The session has expired — sign in to AI-PACS again, "
                        "then test again.")
            elif isinstance(payload, ChatApiMissingError):
                text = str(payload)
            else:
                text = f"Could not reach the server:\n{payload}"
        except Exception:
            pass
        self.lbl_chat_test.setText(text)

    # ── actions: config writers ───────────────────────────────────────────────
    def _save_center_identity(self):
        try:
            from modules.cloud_consultation.feature_flags import save_flag_values
        except Exception:
            QMessageBox.warning(self, "Settings",
                                "The cloud consultation module is not available.")
            return
        ok = save_flag_values({
            "consultation_address": self.edit_consult_addr.text().strip().lower(),
            "center_id": self.edit_center_id.text().strip(),
            "hub_mode": self.chk_hub_mode.isChecked(),
        })
        self._saved_feedback(ok)
        self._refresh()

    def _save_web_config(self):
        try:
            from modules.Identity.providers.aipacs_web import save_aipacs_web_config
        except Exception:
            QMessageBox.warning(self, "Settings",
                                "The Identity module is not available.")
            return
        ok = save_aipacs_web_config(self.edit_base_url.text(),
                                    self.chk_web_enabled.isChecked())
        self._saved_feedback(ok)
        self._refresh()

    def _save_gate_flags(self):
        ok = True
        try:
            from modules.Identity.feature_flags import save_identity_enabled

            ok = save_identity_enabled(self.chk_identity_enabled.isChecked()) and ok
        except Exception:
            ok = False
        try:
            from modules.cloud_consultation.feature_flags import save_flag_values

            ok = save_flag_values({"enabled": self.chk_cloud_enabled.isChecked()}) and ok
        except Exception:
            ok = False
        try:
            from modules.aipacs_chat.feature_flags import save_aipacs_chat_enabled

            ok = save_aipacs_chat_enabled(self.chk_chat_enabled.isChecked()) and ok
        except Exception:
            ok = False
        self._saved_feedback(ok)
        self._refresh()

    def _saved_feedback(self, ok: bool):
        if not ok:
            QMessageBox.warning(
                self, "Settings",
                "The settings file could not be written — check folder "
                "permissions.")

    # ── opening links ─────────────────────────────────────────────────────────
    def _open_link(self, url: str, *, what: str) -> None:
        """Open ``url`` in the WORKSTATION's internal Web Browser module.

        Owner directive: links open inside the workstation, never in the
        operating system's browser. ``open_verification_url`` is the repo's ONE
        sanctioned opener (see the surface-policy comment in
        ``modules/Identity/providers/google/oauth_flow.py``, which forbids
        launching the system browser directly) — it routes to the docked
        web_browser module tab, falls back to a floating WebBrowserWidget
        window, and carries the 0x8001010d crash-hardening (queued open +
        clean-turn navigate) that a button click needs, because a click IS an
        input-synchronous dispatch.

        It returns False when the embedded browser cannot be used at all
        (module not installed/enabled, or headless). In that case we tell the
        operator and show the address rather than quietly launching Chrome
        against the directive.
        """
        opened = False
        try:
            from modules.Identity.providers.google.oauth_flow import (
                open_verification_url,
            )

            opened = bool(open_verification_url(url))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("internal browser open failed: %s", exc)
        if opened:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(what)
        box.setText(
            "The workstation's Web Browser module is not available, so this "
            "page cannot be opened inside AI-PACS.\n\nAddress:")
        box.setInformativeText(url)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()

    def _web_base_url(self) -> str:
        """The configured AI-PACS server address (the ONE authority), or ""."""
        try:
            from modules.Identity.providers.aipacs_web import load_aipacs_web_config

            return (load_aipacs_web_config().get("base_url") or "").strip()
        except Exception:
            return ""

    def _open_portal(self, path: str) -> None:
        """Open a page of the AI-PACS Consultation portal.

        The portal is a DIFFERENT mount from the API base URL — appending to
        base_url produces a 404 by web-server rule — so the address comes from
        :func:`portal_url`, the one authority for it.
        """
        try:
            from modules.Identity.providers.aipacs_web import portal_url

            base = portal_url()
        except Exception:
            base = ""
        if not base:
            QMessageBox.information(
                self, "AI-PACS portal",
                "The AI-PACS server address is not configured yet, so the "
                "portal address cannot be worked out. Set the server address "
                "under Configuration first.")
            return
        self._open_link(f"{base}{path}", what="AI-PACS portal")

    def _open_staff_panel(self, path: str, what: str) -> None:
        """Open a page of the staff (forms + chat) panel. Staff accounts only —
        the server answers 403 to everyone else."""
        try:
            from modules.Identity.providers.aipacs_web import staff_panel_url

            base = staff_panel_url()
        except Exception:
            base = ""
        base = base or f"{DEFAULT_WEBSITE_URL}/consult-form/forms-panel"
        self._open_link(f"{base}{path}", what=what)

    def _open_web_chat_console(self):
        """Open the staff WEB chat console (browser session login).

        ``{base_url}/forms-panel/login`` — owner-confirmed 2026-08-20. This is
        the browser counterpart of the workstation console; the workstation
        itself never uses this page (it authenticates via ``/api/v1`` with the
        Sanctum token from the AI-PACS sign-in).
        """
        self._open_staff_panel("/login", "AiPacs Chat web console")

    def _open_website(self):
        self._open_link(self._web_base_url() or DEFAULT_WEBSITE_URL,
                        what="AI-PACS website")
